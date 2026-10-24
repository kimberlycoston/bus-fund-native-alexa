"""Device-associated language-pair persistence (FR-08, AT-10, AT-12).

Pairs are stored in a small JSON file keyed by a random device id the browser
keeps in its own localStorage. On a laptop-hosted demo that means "this
browser on this laptop". On a shared remote host, each visitor's browser gets
its own entry; clearing site data creates a fresh id (and the default pair).
Writes are atomic (temp file + os.replace) so a crash never corrupts the store
or half-saves a pair.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from . import config
from .languages import normalize_language

_LOCK = threading.Lock()
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _safe_id(device_id: str | None) -> str:
    return device_id if device_id and _ID_RE.match(device_id) else "default"


def _read(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def load_pair(device_id: str | None, path: Path | None = None) -> tuple[tuple[str, str], bool]:
    """Return ((language_1, language_2), was_saved)."""
    path = path or config.PREFS_PATH
    with _LOCK:
        entry = _read(path).get(_safe_id(device_id))
    if isinstance(entry, dict):
        a, b = normalize_language(entry.get("language_1", "")), normalize_language(entry.get("language_2", ""))
        if a.canonical and b.canonical and a.canonical != b.canonical:
            return (a.canonical, b.canonical), True
    return tuple(config.DEFAULT_LANGUAGE_PAIR), False  # type: ignore[return-value]


def save_pair(device_id: str | None, language_1: str, language_2: str, path: Path | None = None) -> None:
    """Atomically persist an already-validated pair."""
    path = path or config.PREFS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        data = _read(path)
        data[_safe_id(device_id)] = {"language_1": language_1, "language_2": language_2}
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".prefs-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
