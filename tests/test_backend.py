import json

import pytest

from native import config, prefs
from native.backend import handle_request
from native.languages import normalize_language, validate_pair
from native.realtime import build_instructions, mint_client_secret
from native.runtime_files import check_wakeword_model


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import native.realtime as rt
    rt._MODEL_CACHE.clear()
    monkeypatch.setattr(rt, "model_available", lambda key, m: None)


@pytest.fixture(autouse=True)
def tmp_prefs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PREFS_PATH", tmp_path / "prefs.json")
    return tmp_path / "prefs.json"


DEV = "device_abc12345"


def test_aliases_and_ambiguity():
    assert normalize_language("Mandarin").canonical == "Mandarin Chinese"
    assert normalize_language("  español. ").canonical == "Spanish"
    assert normalize_language("the French language").canonical == "French"
    assert normalize_language("Chinese").ambiguous
    assert normalize_language("Klingon").canonical is None


@pytest.mark.parametrize("a,b,reason", [
    ("Spanish", "", "missing"), ("Spanish", "spanish", "duplicate"),
    ("English", "Klingon", "unsupported"), ("Spanish", "Chinese", "ambiguous")])
def test_invalid_pairs(a, b, reason):
    r = validate_pair(a, b)
    assert not r.ok and r.reason == reason and r.message


def test_first_use_default_pair():  # AT-07
    r = handle_request({"id": "1", "type": "hello", "device_id": DEV}, "sk-x")
    assert (r["language_1"], r["language_2"]) == ("English", "Spanish") and r["saved"] is False


def test_set_languages_persists_non_english_pair(tmp_prefs):  # AT-09, AT-10
    r = handle_request({"id": "2", "type": "set_languages", "device_id": DEV,
                        "language_1": "Spanish", "language_2": "Mandarin"}, None)
    assert r["ok"] and (r["language_1"], r["language_2"]) == ("Spanish", "Mandarin Chinese")
    assert json.loads(tmp_prefs.read_text())[DEV] == {"language_1": "Spanish", "language_2": "Mandarin Chinese"}
    # "restart": a fresh load reads the saved pair
    assert prefs.load_pair(DEV) == (("Spanish", "Mandarin Chinese"), True)


def test_failed_selection_keeps_saved_pair():  # AT-12
    handle_request({"id": "3", "type": "set_languages", "device_id": DEV, "language_1": "English",
                    "language_2": "French"}, None)
    for bad in [("French", "French"), ("English", "Klingon"), ("Chinese", "English"), ("", "German")]:
        r = handle_request({"id": "x", "type": "set_languages", "device_id": DEV,
                            "language_1": bad[0], "language_2": bad[1]}, None)
        assert not r["ok"]
        assert (r["language_1"], r["language_2"]) == ("English", "French")
    assert prefs.load_pair(DEV)[0] == ("English", "French")


def test_pairs_are_per_device():
    handle_request({"id": "4", "type": "set_languages", "device_id": DEV, "language_1": "Arabic",
                    "language_2": "French"}, None)
    assert prefs.load_pair("another_device_99")[0] == ("English", "Spanish")


def test_corrupt_prefs_file_falls_back(tmp_prefs):
    tmp_prefs.write_text("{not json")
    assert prefs.load_pair(DEV) == (("English", "Spanish"), False)


def test_token_without_key_is_safe_error():  # AT-24
    r = handle_request({"id": "5", "type": "token", "device_id": DEV}, None)
    assert not r["ok"] and r["error_kind"] == "no_key" and "token" not in r


def test_instructions_substitution():
    s = build_instructions("Spanish", "Mandarin Chinese", "LANGUAGE_SELECTION")
    assert "CURRENT INTERPRETATION LANGUAGES: Spanish and Mandarin Chinese." in s
    assert "CURRENT APPLICATION MODE: LANGUAGE_SELECTION." in s
    assert "{" not in s and "sk-" not in s


def test_mint_falls_through_models(monkeypatch):
    calls = []

    def fake_post(url, key, body, timeout=15.0):
        calls.append(body["session"]["model"])
        if len(calls) == 1:
            return 400, {"error": {"message": "Invalid model gpt-x"}}
        return 200, {"value": "ek_123", "expires_at": 99}

    monkeypatch.setattr("native.realtime._post_json", fake_post)
    monkeypatch.setattr(config, "REALTIME_MODELS", ["gpt-x", "gpt-y"])
    r = mint_client_secret("sk-test", "English", "Spanish")
    assert r.ok and r.model == "gpt-y" and r.token == "ek_123" and calls == ["gpt-x", "gpt-y"]


def test_mint_bad_key(monkeypatch):
    monkeypatch.setattr("native.realtime._post_json", lambda *a, **k: (401, {"error": {"message": "bad"}}))
    r = mint_client_secret("sk-bad", "English", "Spanish")
    assert not r.ok and r.error_kind == "auth"


def test_supplied_wake_model_is_compatible():
    assert check_wakeword_model(config.WAKEWORD_MODEL_PATH) == ""


def test_incompatible_wake_model(tmp_path):
    bad = tmp_path / "x.tflite"
    bad.write_bytes(b"0")
    assert "ONNX" in check_wakeword_model(bad)


def test_mint_skips_unavailable_and_rejected_models(monkeypatch):
    import native.realtime as rt
    rt._MODEL_CACHE.clear()
    monkeypatch.setattr(config, "REALTIME_MODELS", ["m-new", "m-mid", "m-old"])
    monkeypatch.setattr(rt, "model_available", lambda key, m: False if m == "m-new" else None)
    monkeypatch.setattr(rt, "_post_json", lambda url, key, body, timeout=15.0: (200, {"value": "ek_" + body["session"]["model"]}))
    r = mint_client_secret("sk-test-1234", "English", "Spanish")
    assert r.ok and r.model == "m-mid"
    # browser reported the socket rejected m-mid → next mint skips it
    r = mint_client_secret("sk-test-1234", "English", "Spanish", skip_models=["m-mid"])
    assert r.ok and r.model == "m-old"


def test_mint_reports_when_no_model_usable(monkeypatch):
    import native.realtime as rt
    rt._MODEL_CACHE.clear()
    monkeypatch.setattr(config, "REALTIME_MODELS", ["a", "b"])
    monkeypatch.setattr(rt, "model_available", lambda key, m: False)
    r = mint_client_secret("sk-x", "English", "Spanish")
    assert not r.ok and r.error_kind == "model" and "NATIVE_REALTIME_MODELS" in r.error
