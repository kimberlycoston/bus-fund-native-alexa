import time

import pytest

from native import config, portal_store as store
from native.backend import handle_request
from native.realtime import session_config


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PORTAL_DB_PATH", tmp_path / "portal.db")
    store.init()


def test_seed_users_patients_bands_and_sample_history():
    assert {p["patient_id"] for p in store.patients()} >= {"DEMO-1001", "DEMO-1002"}
    assert store.band("LB-0014")["name"] == "Minh Tran"
    rep = store.report()
    assert rep["totals"]["exchanges"] > 0 and rep["totals"]["conversations"] == 5
    assert store.report(include_sample=False)["totals"]["exchanges"] == 0


def test_login_success_failure_and_audit():
    assert store.authenticate("taylor.rn", "wrong") is None
    u = store.authenticate("Taylor.RN ", store.DEMO_PASSWORD)
    assert u["role"] == "nurse" and u["unit"] == "Cardiac Step-Down 4B"
    actions = [a["action"] for a in store.audit_log()]
    assert "login" in actions and "login_failed" in actions


def test_band_traffic_through_backend_shows_live_and_bilingual():
    cid = "conv_test_123456"
    r = handle_request({"id": "1", "type": "portal_session", "event": "start", "conversation_id": cid,
                        "band_id": "LB-0014", "patient_id": "DEMO-1001",
                        "language_1": "English", "language_2": "Vietnamese"}, None)
    assert r["ok"]
    r = handle_request({"id": "2", "type": "log_exchange", "conversation_id": cid, "band_id": "LB-0014",
                        "patient_id": "DEMO-1001", "source_text": "Tôi bị tức ngực.",
                        "translation": "My chest feels tight.", "language_1": "English",
                        "language_2": "Vietnamese"}, None)
    assert r["ok"] and r["exchange_id"]
    live = store.live_conversations()
    assert live[0]["conversation_id"] == cid and live[0]["name"] == "Minh Tran" and live[0]["n_exchanges"] == 1
    ex = store.exchanges(cid)[0]
    assert ex["source_text"] == "Tôi bị tức ngực." and ex["auto_flag"] is None
    # nurse on another unit does not see it
    assert store.live_conversations("Medical ICU") == []
    handle_request({"id": "3", "type": "portal_session", "event": "end", "conversation_id": cid}, None)
    assert store.live_conversations() == []
    assert store.conversations(search="chest")[0]["conversation_id"] == cid


def test_bad_input_is_rejected_and_flags_apply():
    assert not handle_request({"id": "x", "type": "log_exchange", "conversation_id": "bad id!",
                               "translation": "hi"}, None)["ok"]
    assert not handle_request({"id": "y", "type": "log_exchange", "conversation_id": "conv_ok_1234",
                               "translation": ""}, None)["ok"]
    assert store.auto_flag(None, "Hello") == "Original speech not captured"
    assert store.auto_flag("Hello there my friend, how are you today?", "Hi") .startswith("Length mismatch")
    assert store.auto_flag("我需要去洗手间。", "I need to use the bathroom.") is None
    xid = store.log_exchange("conv_ok_1234", None, None, None, "Hello", "English", "Spanish")
    store.set_review(xid, "verified", "taylor.rn")
    assert store.exchanges("conv_ok_1234")[0]["review_status"] == "verified"


def test_assign_band_moves_patient_and_csv_has_no_transcript_text():
    store.assign_band("LB-0063", "DEMO-1001", "taylor.rn")
    assert store.band("LB-0063")["patient_id"] == "DEMO-1001"
    assert store.band("LB-0014")["patient_id"] is None  # one band per patient
    csv_text = store.compliance_csv()
    assert "My chest feels tight" not in csv_text and "DEMO-1001" in csv_text


def test_session_config_transcription_toggle(monkeypatch):
    on = session_config("gpt-realtime", "English", "Spanish")
    assert on["audio"]["input"]["transcription"]["model"] == config.INPUT_TRANSCRIPTION_MODEL
    off = session_config("gpt-realtime", "English", "Spanish", transcription=False)
    assert "transcription" not in off["audio"]["input"]


def test_mint_retries_without_transcription(monkeypatch):
    import native.realtime as rt
    monkeypatch.setattr(rt, "model_available", lambda key, m: None)
    calls = []

    def fake_post(url, key, body, timeout=15.0):
        calls.append(body["session"]["audio"]["input"].get("transcription"))
        if body["session"]["audio"]["input"].get("transcription"):
            return 400, {"error": {"message": "Unknown parameter: 'session.audio.input.transcription'."}}
        return 200, {"value": "ek_ok"}
    monkeypatch.setattr(rt, "_post_json", fake_post)
    res = rt.mint_client_secret("sk-test-12345678", "English", "Spanish")
    assert res.ok and res.token == "ek_ok" and calls[0] and calls[1] is None
