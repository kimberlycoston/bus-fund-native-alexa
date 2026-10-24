"""OpenAI Realtime session setup: instructions (spec §8), tools (§9) and
ephemeral client-secret minting.

The long-lived OPENAI_API_KEY never leaves this module. The browser receives
only a short-lived client secret (`ek_...`) that can open one Realtime socket.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import config

# Spec §8, verbatim, with placeholders the controller fills in.
INSTRUCTIONS_TEMPLATE = """You are Native, a hands-free, bidirectional multilingual spoken interpreter.

CURRENT INTERPRETATION LANGUAGES: {language_1} and {language_2}.
COMMAND-INTERFACE LANGUAGE: {command_language}.
CURRENT APPLICATION MODE: {mode}.

English and Spanish may be the initial defaults, but are not the only supported languages. Neither selected language needs to be English.

IN INTERPRETATION MODE:
- For each completed human utterance, identify which of the TWO currently selected languages was spoken and translate faithfully into the OTHER selected language.
- Speak only the translation. Never answer the speaker's questions, provide medical advice, invent details, summarize, or add commentary.
- Preserve numbers, dosages, negation, names, medical terminology, questions, and uncertainty.
- Do not assume that a clinician or patient always speaks a particular language.
- If speech is unclear or cannot reliably be assigned to one of the two languages, request clarification rather than guessing.
- Do not translate your own synthesized audio, chimes, or command prompts.
- Ordinary phrases such as "choose languages" or "repeat please" are translation content unless the controller has explicitly entered COMMAND mode after detecting "Hey Native."

IN COMMAND MODE (only after the controller confirms wake-word detection):
- Support exactly two actionable intents: "choose languages" and "repeat please", including unambiguous variants.
- For "choose languages", enter LANGUAGE_SELECTION mode and ask in {command_language}: "Which two languages would you like me to translate?"
- For "repeat please", call repeat_last_translation. Do not regenerate or paraphrase the previous translation. If the application reports no history, say "There's nothing to repeat yet."
- For unknown commands, briefly say you can choose languages or repeat the last translation; do not execute other actions.
- Do not claim an action succeeded before the application reports success.

IN LANGUAGE_SELECTION MODE:
- Treat the next human reply as language names, not conversation to translate; do not require another wake phrase.
- Identify exactly two distinct languages. Ask a targeted clarification if a language is missing or ambiguous.
- Call set_languages(language_1, language_2). Only after confirmed success, say in {command_language}: "Okay, I'll translate between [language 1] and [language 2]."
- If the application rejects the pair, explain briefly, preserve the previous pair, and request a corrected selection.
- Resume INTERPRETATION mode when the controller signals completion.

The application controller—not these instructions—handles wake-word detection, rolling audio buffering, command routing, chimes, turn detection, session state, microphone gating, persistent preferences, replay caching, and timeouts."""

# Per-response controller signals appended to the template for each mode.
MODE_ADDENDA = {
    "INTERPRETATION": (
        "CONTROLLER SIGNAL: The latest user audio item is ONE completed utterance. Respond with audio that is "
        "only the faithful translation of that utterance into the other selected language, in a natural, "
        "neutral interpreter voice. If the utterance starts with the device wake phrase \"Hey Native\", do not "
        "translate those two words. If it is in neither selected language, or is unclear, briefly ask the "
        "speaker (in the language they appear to use, otherwise in both selected languages) to repeat."
    ),
    "COMMAND": (
        "CONTROLLER SIGNAL: The controller detected the wake phrase \"Hey Native\". Classify the latest user "
        "audio item. It may begin with leftover sound from the wake phrase; ignore that. Call exactly one "
        "function: choose_languages (e.g. \"choose languages\", \"change languages\", \"pick languages\"), "
        "repeat_last_translation (e.g. \"repeat please\", \"say that again\", \"repeat\"), or not_a_command "
        "(anything else: ordinary conversation, other requests, unclear audio or silence). Do not speak."
    ),
    "LANGUAGE_SELECTION": (
        "CONTROLLER SIGNAL: The latest user audio item answers the question \"Which two languages would you "
        "like me to translate?\". Call exactly one function. Use set_languages with the two languages' common "
        "English names exactly as the user meant them (e.g. \"Mandarin\" → \"Mandarin Chinese\"; keep a bare "
        "\"Chinese\" as \"Chinese\"). Use ask_clarification with one short {command_language} question if a "
        "language is missing or unclear. Use cancel_language_selection if the user wants to cancel or keep "
        "the current languages. Do not speak."
    ),
}


def build_instructions(language_1: str, language_2: str, mode: str = "INTERPRETATION",
                       command_language: str | None = None) -> str:
    cl = command_language or config.COMMAND_INTERFACE_LANGUAGE
    base = INSTRUCTIONS_TEMPLATE.format(language_1=language_1, language_2=language_2,
                                        command_language=cl, mode=mode)
    addendum = MODE_ADDENDA.get(mode, "").replace("{command_language}", cl)
    return f"{base}\n\n{addendum}" if addendum else base


def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or [],
                           "additionalProperties": False}}


COMMAND_TOOLS = [
    _fn("choose_languages", "The user asked to choose / change the two interpretation languages."),
    _fn("repeat_last_translation", "The user asked Native to repeat the most recent translation."),
    _fn("not_a_command", "The audio is not one of the two supported commands."),
]

LANGUAGE_SELECTION_TOOLS = [
    _fn("set_languages", "Set the two interpretation languages.",
        {"language_1": {"type": "string", "description": "First language, English name"},
         "language_2": {"type": "string", "description": "Second language, English name"}},
        ["language_1", "language_2"]),
    _fn("ask_clarification", "Ask one short clarifying question about the languages.",
        {"question": {"type": "string"}}, ["question"]),
    _fn("cancel_language_selection", "The user wants to cancel and keep the current languages."),
]


@dataclass
class MintResult:
    ok: bool
    token: str = ""
    model: str = ""
    expires_at: int = 0
    error: str = ""
    error_kind: str = ""  # no_key | auth | network | model | api


def _post_json(url: str, api_key: str, body: dict, timeout: float = 15.0) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        return e.code, payload


def session_config(model: str, language_1: str, language_2: str) -> dict:
    return {
        "type": "realtime",
        "model": model,
        "instructions": build_instructions(language_1, language_2, "INTERPRETATION"),
        "output_modalities": ["audio"],
        "audio": {
            "input": {"format": {"type": "audio/pcm", "rate": 24000}, "turn_detection": None},
            "output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": config.REALTIME_VOICE},
        },
    }


_MODEL_CACHE: dict[tuple[str, str], bool] = {}


def model_available(api_key: str, model: str) -> bool | None:
    """GET /models/{model}: True if this account can use it, False if OpenAI says
    it doesn't exist / isn't available, None if we couldn't tell (try it anyway)."""
    key = (api_key[-8:], model)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    req = urllib.request.Request(f"{config.OPENAI_API_BASE.rstrip('/')}/models/{model}",
                                 headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            ok = r.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            ok = False
        else:
            return None
    except Exception:
        return None
    _MODEL_CACHE[key] = ok
    return ok


def mark_model_unavailable(api_key: str, model: str) -> None:
    """Remember a model the Realtime socket rejected (e.g. model_not_found)."""
    if api_key:
        _MODEL_CACHE[(api_key[-8:], model)] = False


def mint_client_secret(api_key: str | None, language_1: str, language_2: str,
                       skip_models: list[str] | None = None) -> MintResult:
    """Create a short-lived Realtime client secret using the first REALTIME_MODELS
    entry this account can actually use."""
    if not api_key:
        return MintResult(False, error="No OpenAI API key is configured on the server. Add OPENAI_API_KEY to "
                                       ".streamlit/secrets.toml or the environment.", error_kind="no_key")
    for m in skip_models or []:
        mark_model_unavailable(api_key, m)
    url = f"{config.OPENAI_API_BASE.rstrip('/')}/realtime/client_secrets"
    tried: list[str] = []
    last_err = ""
    for model in config.REALTIME_MODELS:
        if _MODEL_CACHE.get((api_key[-8:], model)) is False or model_available(api_key, model) is False:
            tried.append(model)
            continue
        body = {"expires_after": {"anchor": "created_at", "seconds": config.CLIENT_SECRET_TTL_SEC},
                "session": session_config(model, language_1, language_2)}
        try:
            status, payload = _post_json(url, api_key, body)
        except Exception as e:  # DNS, TLS, timeout …
            return MintResult(False, error=f"Could not reach OpenAI ({type(e).__name__}). Check the network.",
                              error_kind="network")
        if status == 200 and payload.get("value"):
            return MintResult(True, token=payload["value"], model=model,
                              expires_at=int(payload.get("expires_at") or 0))
        msg = (payload.get("error") or {}).get("message", "") if isinstance(payload, dict) else ""
        if status == 401:
            return MintResult(False, error="OpenAI rejected the API key (401). Check OPENAI_API_KEY.",
                              error_kind="auth")
        last_err = f"OpenAI error {status} for model {model}: {msg or 'no details'}"
        if status in (400, 403, 404) and "model" in msg.lower():
            mark_model_unavailable(api_key, model)
            tried.append(model)
            continue  # try the next model in the list
        return MintResult(False, error=last_err, error_kind="api")
    return MintResult(False, error=(
        f"None of the configured Realtime models are available to this OpenAI account "
        f"(tried {', '.join(tried) or 'none'}). Set NATIVE_REALTIME_MODELS to a model your account can use. "
        f"{last_err}").strip(), error_kind="model")
