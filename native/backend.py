"""Backend handlers for requests coming from the browser component (spec §9).

Each request is a dict {id, type, ...}. Each handler returns a response dict
that echoes the id; the browser waits for that explicit confirmation before
acting (e.g. it never announces a language change until `set_languages` here
has validated and persisted it).
"""
from __future__ import annotations

from . import config, prefs
from .languages import validate_pair
from .realtime import mint_client_secret


def handle_request(req: dict, api_key: str | None) -> dict:
    rid, kind = str(req.get("id", "")), req.get("type")
    device = req.get("device_id")
    if kind == "hello":
        (l1, l2), saved = prefs.load_pair(device)
        return {"id": rid, "type": kind, "ok": True, "language_1": l1, "language_2": l2, "saved": saved,
                "has_api_key": bool(api_key)}
    if kind == "token":
        (l1, l2), _ = prefs.load_pair(device)
        skip = [str(m) for m in (req.get("skip_models") or [])][:10]
        res = mint_client_secret(api_key, l1, l2, skip)
        out = {"id": rid, "type": kind, "ok": res.ok, "language_1": l1, "language_2": l2}
        if res.ok:
            out.update(token=res.token, model=res.model, expires_at=res.expires_at)
        else:
            out.update(error=res.error, error_kind=res.error_kind)
        return out
    if kind == "set_languages":
        result = validate_pair(str(req.get("language_1", "")), str(req.get("language_2", "")))
        if not result.ok:  # AT-12: never overwrite the saved pair on failure
            (l1, l2), _ = prefs.load_pair(device)
            return {"id": rid, "type": kind, "ok": False, "message": result.message, "reason": result.reason,
                    "language_1": l1, "language_2": l2}
        try:
            prefs.save_pair(device, result.language_1, result.language_2)
        except OSError as e:
            (l1, l2), _ = prefs.load_pair(device)
            return {"id": rid, "type": kind, "ok": False, "reason": "storage",
                    "message": "Sorry, I couldn't save that language choice.", "detail": str(e),
                    "language_1": l1, "language_2": l2}
        return {"id": rid, "type": kind, "ok": True, "language_1": result.language_1,
                "language_2": result.language_2, "message": result.message}
    return {"id": rid, "type": kind, "ok": False, "error": f"Unknown request type: {kind!r}"}


def default_pair() -> tuple[str, str]:
    return tuple(config.DEFAULT_LANGUAGE_PAIR)  # type: ignore[return-value]
