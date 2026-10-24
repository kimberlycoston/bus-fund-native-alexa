"""Native — wake-word-activated multilingual voice interpreter (Streamlit prototype, spec v2.0).

Run:  streamlit run app.py
"""
from __future__ import annotations

import os

import streamlit as st

from native import config
from native.backend import handle_request
from native.languages import supported_names
from native.realtime import COMMAND_TOOLS, LANGUAGE_SELECTION_TOOLS, INSTRUCTIONS_TEMPLATE, MODE_ADDENDA
from native.runtime_files import prepare_runtime_files
from native_component import native_voice

st.set_page_config(page_title="Native", page_icon=None, layout="centered")


@st.cache_resource
def _runtime():
    return prepare_runtime_files()


def _api_key() -> str | None:
    try:
        key = st.secrets.get("OPENAI_API_KEY")  # type: ignore[union-attr]
    except Exception:  # no secrets.toml
        key = None
    return key or os.getenv("OPENAI_API_KEY")


runtime = _runtime()
api_key = _api_key()

st.markdown("<h2 style='margin-bottom:0'>Native Lisans</h2>", unsafe_allow_html=True)
st.caption("Hands-free, ambient multilingual interpreter for patient rooms")

for p in runtime.problems:
    st.error(p)
if not api_key:
    st.warning("No OpenAI API key found. Wake-word standby works, but translation needs OPENAI_API_KEY in "
               ".streamlit/secrets.toml or the environment.")

ss = st.session_state
ss.setdefault("responses", [])
ss.setdefault("processed", set())

component_config = {
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
}

event = native_voice(config=component_config, responses=ss.responses, key="native")

# Browser → backend requests (hello / token / set_languages). Each is handled
# exactly once, answered through the component's `responses` argument.
if isinstance(event, dict) and event.get("id") and event["id"] not in ss.processed:
    ss.processed.add(event["id"])
    ss.responses = (ss.responses + [handle_request(event, api_key)])[-8:]
    st.rerun()

with st.expander("How Native handles audio"):
    st.markdown(
        "- **Standby:** your browser listens for “Hey Native” on this device. No standby audio leaves the browser.\n"
        "- **Active:** each completed utterance is sent to OpenAI for interpretation; the translation is "
        "spoken back. Nothing is recorded or saved; only the latest translation is held in memory for "
        "“repeat please”.\n"
        "- **Commands:** “Hey Native, choose languages” · “Hey Native, repeat please”.\n"
        "- The chosen language pair is remembered for this browser.\n"
        "- **Deactivate Native** stops the microphone and closes the OpenAI session immediately."
    )
