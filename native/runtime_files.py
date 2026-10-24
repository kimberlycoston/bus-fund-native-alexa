"""Checks the configured wake-word model and copies it plus the cue sounds into
the component's static folder so the browser can load them (FR-01, FR-08).
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import config

FRONTEND_DIR = config.ROOT / "native_component" / "frontend"
RUNTIME_DIR = FRONTEND_DIR / "runtime"


@dataclass
class RuntimeStatus:
    wake_model_ok: bool = False
    wake_model_error: str = ""
    cues: dict = field(default_factory=dict)  # name → served relative URL
    problems: list = field(default_factory=list)


def check_wakeword_model(path: Path) -> str:
    """Return "" if `path` looks like an openWakeWord classifier usable by the
    browser pipeline (input [1, 16, 96] float32 embeddings → scalar score)."""
    if not path.exists():
        return f"Wake-word model not found at {path}."
    if path.suffix.lower() != ".onnx":
        return f"Wake-word model must be an ONNX export (.onnx); got {path.suffix or 'no extension'}."
    try:
        import onnxruntime as ort
    except ImportError:
        return ""  # can't verify server-side; the browser will report a load failure
    try:
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception as e:
        return f"Wake-word model could not be loaded by ONNX Runtime: {e}"
    ins, outs = sess.get_inputs(), sess.get_outputs()
    if len(ins) != 1:
        return f"Wake-word model has {len(ins)} inputs; expected 1 (openWakeWord classifier)."
    shape = [d if isinstance(d, int) else -1 for d in ins[0].shape]
    if len(shape) != 3 or shape[1:] != [16, 96] or "float" not in ins[0].type:
        return (f"Wake-word model input is {ins[0].shape} {ins[0].type}; expected [1, 16, 96] float — "
                "i.e. an openWakeWord model trained on 16 kHz speech embeddings.")
    if not outs:
        return "Wake-word model has no outputs."
    return ""


def browser_safe_cue(path: Path, name: str) -> Path:
    """Return a WAV version of a cue sound when one is available.

    Not every browser can decode AAC/.m4a (e.g. Firefox and Chromium builds
    without proprietary codecs), but every browser decodes PCM WAV. Preference:
    the file itself if already WAV → a same-named .wav next to it → a WAV made
    with ffmpeg (if installed) → the original file as a last resort.
    """
    if path.suffix.lower() == ".wav":
        return path
    sibling = path.with_suffix(".wav")
    if sibling.exists():
        return sibling
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        out = RUNTIME_DIR / f"{name}_converted.wav"
        if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
            out.parent.mkdir(parents=True, exist_ok=True)
            res = subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-i", str(path), "-ac", "1",
                                  "-c:a", "pcm_s16le", str(out)], capture_output=True)
            if res.returncode != 0:
                return path
        return out
    return path


def _sync(src: Path, dst: Path) -> None:
    if src == dst:
        return
    if not dst.exists() or dst.stat().st_size != src.stat().st_size or dst.stat().st_mtime < src.stat().st_mtime:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def prepare_runtime_files() -> RuntimeStatus:
    st = RuntimeStatus()
    err = check_wakeword_model(config.WAKEWORD_MODEL_PATH)
    if err:
        st.wake_model_error = err
        st.problems.append(err)
    else:
        _sync(config.WAKEWORD_MODEL_PATH, RUNTIME_DIR / "wakeword.onnx")
        st.wake_model_ok = True
    for name, path, required in (("start", config.START_CUE_PATH, True),
                                 ("stop", config.STOP_CUE_PATH, True),
                                 ("shutdown", config.SHUTDOWN_CUE_PATH, False)):
        if path.exists():
            src = browser_safe_cue(path, name)
            _sync(src, RUNTIME_DIR / f"{name}{src.suffix.lower()}")
            st.cues[name] = f"runtime/{name}{src.suffix.lower()}"
        elif required:
            st.problems.append(f"Cue sound missing: {path}")
    return st
