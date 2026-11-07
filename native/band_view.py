"""Lisans Band page: the clickable band, now synced to the Lisans Portal.

Each interpreted sentence (original speech + interpretation) is saved to the
Portal store against the band's current patient, so the Portal page shows it live.
"""
from __future__ import annotations

import os

import streamlit as st

from . import config, portal_store as store
from .backend import handle_request
from .languages import supported_names
from .realtime import COMMAND_TOOLS, LANGUAGE_SELECTION_TOOLS, INSTRUCTIONS_TEMPLATE, MODE_ADDENDA
from .runtime_files import prepare_runtime_files
from native_component import native_voice

@st.cache_resource
def _runtime():
    return prepare_runtime_files()


def _api_key() -> str | None:
    try:
        key = st.secrets.get("OPENAI_API_KEY")  # type: ignore[union-attr]
    except Exception:  # no secrets.toml
        key = None
    return key or os.getenv("OPENAI_API_KEY")



def _band_picker() -> dict:
    """Which band this browser is, and who wears it. Assignment is managed in the Portal."""
    store.init()
    bands = store.bands()
    ids = [b["band_id"] for b in bands]
    c1, c2, c3 = st.columns([1.2, 3, 2])
    band_id = c1.selectbox("This band", ids, index=0, key="band_id",
                           help="The band this screen represents. Assign it to a patient in the Lisans Portal.")
    b = store.band(band_id) or {}
    if b.get("patient_id"):
        label = f"{b['name']} · {b['unit']} · Room {b['room']}"
        c2.markdown(f"**Worn by:** {label}  \nPreferred language: **{b['language']}**")
    else:
        label = None
        c2.markdown("**Not assigned to a patient.** Conversations still save to the Portal as *Unassigned band*.")
    c3.caption("To watch the transcript live, open **Lisans Portal** from the top menu in a second browser tab.")
    return {"band_id": band_id, "patient_id": b.get("patient_id"), "patient_label": label,
            "patient_language": b.get("language")}


def render() -> None:
    portal_link = _band_picker()
    runtime = _runtime()
    api_key = _api_key()


    ss = st.session_state
    ss.setdefault("responses", [])
    ss.setdefault("processed", set())

    component_config = {
        "activation_mode": "button",
        "has_api_key": bool(api_key),
        "wake_model_ok": runtime.wake_model_ok,
        "wake_model_error": runtime.wake_model_error,
        "cues": runtime.cues,
        "default_pair": list(config.DEFAULT_LANGUAGE_PAIR),
        "command_language": config.COMMAND_INTERFACE_LANGUAGE,
        "supported_languages": supported_names(),
        "instructions_template": INSTRUCTIONS_TEMPLATE,
        "mode_addenda": MODE_ADDENDA,
        "command_tools": COMMAND_TOOLS,
        "language_tools": LANGUAGE_SELECTION_TOOLS,
        "realtime_ws_url": config.REALTIME_WS_URL,
        "timing": {
            "utterance_silence": config.UTTERANCE_SILENCE_SEC,
            "inactivity_timeout": config.INACTIVITY_TIMEOUT_SEC,
            "command_reply_timeout": config.COMMAND_REPLY_TIMEOUT_SEC,
            "command_silence": config.COMMAND_SILENCE_SEC,
            "language_reply_silence": config.LANGUAGE_REPLY_SILENCE_SEC,
            "paused_wake_timeout": config.PAUSED_WAKE_TIMEOUT_SEC,
            "continuation_window": config.CONTINUATION_WINDOW_SEC,
            "post_wake_preroll": config.POST_WAKE_PREROLL_SEC,
            "min_speech": config.MIN_SPEECH_SEC,
            "max_utterance": config.MAX_UTTERANCE_SEC,
            "tail_guard": config.PLAYBACK_TAIL_GUARD_SEC,
            "wake_cooldown": config.WAKE_COOLDOWN_SEC,
        },
        "thresholds": {
            "wake": config.WAKE_THRESHOLD,
            "wake_frames": config.WAKE_CONSECUTIVE_FRAMES,
            "vad": config.VAD_THRESHOLD,
            "vad_start_frames": config.VAD_START_FRAMES,
        },
        "trim_cue_silence": config.TRIM_CUE_SILENCE,
        "debug": config.SHOW_DEBUG_METERS,
        "portal": portal_link,
    }

    event = native_voice(config=component_config, responses=ss.responses, key="native")

    # Browser → backend requests (hello / token / set_languages). Each is handled
    # exactly once, answered through the component's `responses` argument.
    if isinstance(event, dict) and event.get("id") and event["id"] not in ss.processed:
        ss.processed.add(event["id"])
        ss.responses = (ss.responses + [handle_request(event, api_key)])[-8:]
        st.rerun()
