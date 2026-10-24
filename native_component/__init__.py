"""Streamlit custom component wrapper for the Native browser audio engine.

The frontend is plain HTML/JS (no build step). It implements the Streamlit
component postMessage protocol directly, so `declare_component(path=...)`
serves it as-is and the iframe persists across reruns.
"""
from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_FRONTEND = Path(__file__).parent / "frontend"
_component = components.declare_component("native_voice", path=str(_FRONTEND))


def native_voice(config: dict, responses: list, key: str = "native"):
    """Render the Native UI. Returns the latest request event from the browser
    (a dict with `id` and `type`) or None."""
    return _component(config=config, responses=responses, key=key, default=None)
