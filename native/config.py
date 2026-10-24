"""Central configuration for Native (spec v2.0 §2 defaults).

Every timing/threshold the spec calls "configurable in code" lives here.
Environment variables override the file paths and model list so the same
code runs on a laptop or a hosted demo without edits.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Input files (spec §13a/b) ────────────────────────────────────────────────
WAKEWORD_MODEL_PATH = Path(os.getenv("NATIVE_WAKEWORD_MODEL", ROOT / "models" / "hey_native.onnx"))
START_CUE_PATH = Path(os.getenv("NATIVE_START_CUE", ROOT / "assets" / "start_record.m4a"))
STOP_CUE_PATH = Path(os.getenv("NATIVE_STOP_CUE", ROOT / "assets" / "stop_record.m4a"))
# Optional distinct session-shutdown cue (FR-06). Never reuse stop_record for this.
SHUTDOWN_CUE_PATH = Path(os.getenv("NATIVE_SHUTDOWN_CUE", ROOT / "assets" / "session_shutdown.m4a"))

# Small local preference store (FR-08).
PREFS_PATH = Path(os.getenv("NATIVE_PREFS_PATH", ROOT / "data" / "native_prefs.json"))

# ── Languages ────────────────────────────────────────────────────────────────
DEFAULT_LANGUAGE_PAIR = ("English", "Spanish")  # first-use default only, not a limit
COMMAND_INTERFACE_LANGUAGE = "English"

# ── Turn-taking and timers (seconds) ─────────────────────────────────────────
UTTERANCE_SILENCE_SEC = 1.0         # FR-05 utterance boundary after genuine speech
INACTIVITY_TIMEOUT_SEC = 120.0      # FR-06 conversational inactivity → STANDBY
COMMAND_REPLY_TIMEOUT_SEC = 30.0    # FR-06 language-selection reply timeout
COMMAND_SILENCE_SEC = 1.5           # end of a command spoken after "Hey Native" in an active session
LANGUAGE_REPLY_SILENCE_SEC = 2.0    # end of the spoken language-pair answer
PAUSED_WAKE_TIMEOUT_SEC = 8.0       # "Hey Native" [chime] ... how long to wait for the command
CONTINUATION_WINDOW_SEC = 0.6       # after wake: speech within this window = continuous command
POST_WAKE_PREROLL_SEC = 0.25        # rolling-buffer audio kept from just before wake detection
MIN_SPEECH_SEC = 0.35               # less voiced audio than this is treated as noise, not a turn
MAX_UTTERANCE_SEC = 60.0            # safety cap on one turn
PLAYBACK_TAIL_GUARD_SEC = 0.35      # mic stays gated this long after Native stops making sound

# ── Detection thresholds ─────────────────────────────────────────────────────
WAKE_THRESHOLD = 0.5                # openWakeWord score; raise if false activations, lower if missed
WAKE_COOLDOWN_SEC = 2.0             # debounce: one phrase → one activation
WAKE_CONSECUTIVE_FRAMES = 1         # frames (80 ms each) above threshold required to fire
VAD_THRESHOLD = 0.5                 # Silero VAD speech probability
VAD_START_FRAMES = 2                # consecutive 32 ms speech frames needed to open a turn

TRIM_CUE_SILENCE = True             # trim leading/trailing silence from the supplied cue files

# ── OpenAI Realtime ──────────────────────────────────────────────────────────
# Tried in order; the first one this API key can actually use wins (checked via
# GET /v1/models/<id>, and skipped automatically if the Realtime socket rejects it).
REALTIME_MODELS = [m.strip() for m in os.getenv(
    "NATIVE_REALTIME_MODELS", "gpt-realtime-2,gpt-realtime").split(",") if m.strip()]
REALTIME_VOICE = os.getenv("NATIVE_REALTIME_VOICE", "marin")
OPENAI_API_BASE = os.getenv("NATIVE_OPENAI_API_BASE", "https://api.openai.com/v1")
REALTIME_WS_URL = os.getenv("NATIVE_REALTIME_WS_URL", "wss://api.openai.com/v1/realtime")
CLIENT_SECRET_TTL_SEC = 600         # ephemeral token lifetime; only used to open the socket

# Developer-only meter showing wake score and VAD probability (off for demos).
SHOW_DEBUG_METERS = os.getenv("NATIVE_DEBUG", "0") == "1"
