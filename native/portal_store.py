"""Lisans Portal data store (prototype).

A small SQLite database that stands in for the hospital-facing platform: demo
users, fictional patients, band assignments, interpreted conversations, review
status and an access audit log. Every band exchange the Streamlit band page
receives is written here, and the Portal page reads it back live.

Prototype only: data is fictional, the file lives on the demo server
(`data/lisans_portal.db`, git-ignored), and nothing here is a production
HIPAA control. The production design is described in README / BAND_DEMO.md.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import config

HOSPITAL_NAME = "Demo Medical Center"
UNITS = ["Cardiac Step-Down 4B", "Emergency Department", "Medical ICU"]
ROLES = {
    "nurse": "Bedside nurse",
    "language_services": "Language Services",
    "admin": "Portal administrator",
}
MAX_TEXT = 4000
_LOCK = threading.Lock()
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")

# Demo accounts. Passwords are hashed at seed time; they are shown on the login
# screen because this is a classroom prototype, not a real hospital system.
DEMO_PASSWORD = "lisans-demo"
DEMO_USERS = [
    ("taylor.rn", "Taylor Reyes, RN", "nurse", "Cardiac Step-Down 4B"),
    ("jordan.rn", "Jordan Patel, RN", "nurse", "Emergency Department"),
    ("language.services", "Morgan Lee", "language_services", None),
    ("portal.admin", "Avery Brooks", "admin", None),
]

# Fictional patients. Mr. Tran is the patient from the pitch story.
DEMO_PATIENTS = [
    ("DEMO-1001", "Minh Tran", "Vietnamese", "Cardiac Step-Down 4B", "14"),
    ("DEMO-1002", "Rosa Delgado", "Spanish", "Cardiac Step-Down 4B", "9"),
    ("DEMO-1003", "Wei Zhang", "Mandarin Chinese", "Emergency Department", "ED-6"),
    ("DEMO-1004", "Amal Haddad", "Arabic", "Medical ICU", "3"),
    ("DEMO-1005", "Ligaya Santos", "Tagalog", "Emergency Department", "ED-11"),
]
DEMO_BANDS = ["LB-0014", "LB-0021", "LB-0032", "LB-0047", "LB-0058", "LB-0063"]

# Clearly-labelled sample history so the Portal is not empty before the first live
# demo. (source text, interpretation, staff language, patient language)
_SAMPLE = {
    "DEMO-1001": [
        ("Tôi bị tức ngực.", "My chest feels tight.", "English", "Vietnamese"),
        ("Can you show me where it feels tight?", "Ông có thể chỉ cho tôi chỗ nào bị tức không?", "English", "Vietnamese"),
        ("Tôi muốn uống nước.", "I would like some water.", "English", "Vietnamese"),
        ("Please hold your breath.", "Xin ông nín thở.", "English", "Vietnamese"),
    ],
    "DEMO-1002": [
        ("Are you having any pain right now?", "¿Tiene algún dolor en este momento?", "English", "Spanish"),
        ("Me duele un poco la cabeza.", "My head hurts a little.", "English", "Spanish"),
        ("I'm going to check your blood pressure.", "Voy a tomarle la presión arterial.", "English", "Spanish"),
    ],
    "DEMO-1003": [
        ("我需要去洗手间。", "I need to use the bathroom.", "English", "Mandarin Chinese"),
        ("I will help you walk there.", "我会扶您走过去。", "English", "Mandarin Chinese"),
    ],
    "DEMO-1004": [
        ("أحتاج إلى دواء للألم.", "I need pain medicine.", "English", "Arabic"),
        ("Your nurse will bring it in a few minutes.", "ستحضره ممرضتك خلال بضع دقائق.", "English", "Arabic"),
    ],
    "DEMO-1005": [
        ("Nahihilo po ako.", "I feel dizzy.", "English", "Tagalog"),
    ],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL, unit TEXT,
  salt TEXT NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS patients (
  patient_id TEXT PRIMARY KEY, name TEXT NOT NULL, language TEXT NOT NULL, unit TEXT NOT NULL,
  room TEXT NOT NULL, admitted_at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS bands (
  band_id TEXT PRIMARY KEY, patient_id TEXT, assigned_at REAL, assigned_by TEXT);
CREATE TABLE IF NOT EXISTS conversations (
  conversation_id TEXT PRIMARY KEY, band_id TEXT, patient_id TEXT, language_1 TEXT, language_2 TEXT,
  started_at REAL NOT NULL, ended_at REAL, last_activity REAL NOT NULL, sample INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS exchanges (
  exchange_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, band_id TEXT, patient_id TEXT,
  ts REAL NOT NULL, source_text TEXT, translation TEXT NOT NULL, language_1 TEXT, language_2 TEXT,
  auto_flag TEXT, review_status TEXT NOT NULL DEFAULT 'unreviewed', reviewed_by TEXT, reviewed_at REAL,
  sample INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit (
  ts REAL NOT NULL, username TEXT, action TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_ex_conv ON exchanges(conversation_id, ts);
CREATE INDEX IF NOT EXISTS ix_ex_ts ON exchanges(ts);
"""


# ───────────────────────── connection ─────────────────────────
def _path() -> Path:
    return Path(config.PORTAL_DB_PATH)


@contextmanager
def _db():
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        con = sqlite3.connect(p, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def init(seed: bool = True) -> None:
    """Create tables and, on an empty database, seed the demo hospital."""
    with _db() as con:
        con.executescript(SCHEMA)
        empty = con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    if seed and empty:
        _seed()


def _seed() -> None:
    now = time.time()
    with _db() as con:
        for username, name, role, unit in DEMO_USERS:
            salt = os.urandom(16).hex()
            con.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?,?)",
                        (username, name, role, unit, salt, _hash(DEMO_PASSWORD, salt)))
        for i, (pid, name, lang, unit, room) in enumerate(DEMO_PATIENTS):
            con.execute("INSERT OR REPLACE INTO patients VALUES (?,?,?,?,?,?,1)",
                        (pid, name, lang, unit, room, now - (i + 1) * 86400))
        for i, band in enumerate(DEMO_BANDS):
            pid = DEMO_PATIENTS[i][0] if i < len(DEMO_PATIENTS) else None
            con.execute("INSERT OR REPLACE INTO bands VALUES (?,?,?,?)",
                        (band, pid, now - (i + 1) * 86400 if pid else None, "portal.admin" if pid else None))
        # sample history spread over the past few days
        for i, (pid, *_rest) in enumerate(DEMO_PATIENTS):
            band = DEMO_BANDS[i]
            lines = _SAMPLE.get(pid, [])
            start = now - (i % 4 + 1) * 86400 + 3600 * (i + 2)
            cid = f"sample-{pid.lower()}"
            l1, l2 = (lines[0][2], lines[0][3]) if lines else ("English", "Spanish")
            con.execute("INSERT OR REPLACE INTO conversations VALUES (?,?,?,?,?,?,?,?,1)",
                        (cid, band, pid, l1, l2, start, start + 60 * len(lines) + 30, start + 60 * len(lines)))
            for j, (src, tr, a, b) in enumerate(lines):
                con.execute(
                    "INSERT OR REPLACE INTO exchanges (exchange_id, conversation_id, band_id, patient_id, ts,"
                    " source_text, translation, language_1, language_2, auto_flag, review_status, sample)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
                    (f"{cid}-{j}", cid, band, pid, start + 60 * j, src, tr, a, b, auto_flag(src, tr),
                     "verified" if j == 0 and i % 2 == 0 else "unreviewed"))


def reset_demo() -> None:
    """Delete everything and re-seed (Portal admin button)."""
    p = _path()
    with _LOCK:
        if p.exists():
            p.unlink()
    init(seed=True)


# ───────────────────────── auth + audit ─────────────────────────
def authenticate(username: str, password: str) -> dict | None:
    with _db() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", ((username or "").strip().lower(),)).fetchone()
    if not row or not hmac.compare_digest(row["pw_hash"], _hash(password or "", row["salt"])):
        audit(username or "?", "login_failed")
        return None
    user = {k: row[k] for k in ("username", "display_name", "role", "unit")}
    audit(user["username"], "login")
    return user


def audit(username: str, action: str, detail: str = "") -> None:
    with _db() as con:
        con.execute("INSERT INTO audit VALUES (?,?,?,?)", (time.time(), username, action, detail[:300]))


def audit_log(limit: int = 200) -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ───────────────────────── patients + bands ─────────────────────────
def patients(unit: str | None = None, active_only: bool = True) -> list[dict]:
    q = ("SELECT p.*, b.band_id FROM patients p LEFT JOIN bands b ON b.patient_id = p.patient_id"
         " WHERE (? IS NULL OR p.unit = ?)" + (" AND p.active = 1" if active_only else "") + " ORDER BY p.unit, p.room")
    with _db() as con:
        return [dict(r) for r in con.execute(q, (unit, unit)).fetchall()]


def bands() -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT b.*, p.name, p.language, p.unit, p.room FROM bands b"
                           " LEFT JOIN patients p ON p.patient_id = b.patient_id ORDER BY b.band_id").fetchall()
    return [dict(r) for r in rows]


def band(band_id: str) -> dict | None:
    with _db() as con:
        r = con.execute("SELECT b.*, p.name, p.language, p.unit, p.room FROM bands b"
                        " LEFT JOIN patients p ON p.patient_id = b.patient_id WHERE b.band_id=?", (band_id,)).fetchone()
    return dict(r) if r else None


def admit_patient(name: str, language: str, unit: str, room: str, by: str) -> str:
    name, room = (name or "").strip()[:80], (room or "").strip()[:20]
    if not name or not room or unit not in UNITS:
        raise ValueError("Name, unit and room are required.")
    pid = f"DEMO-{int(time.time()) % 100000:05d}"
    with _db() as con:
        con.execute("INSERT INTO patients VALUES (?,?,?,?,?,?,1)", (pid, name, language, unit, room, time.time()))
    audit(by, "admit_patient", f"{pid} {unit} {room}")
    return pid


def assign_band(band_id: str, patient_id: str | None, by: str) -> None:
    with _db() as con:
        if patient_id:  # a patient wears one band at a time
            con.execute("UPDATE bands SET patient_id=NULL, assigned_at=NULL, assigned_by=NULL WHERE patient_id=?",
                        (patient_id,))
        con.execute("UPDATE bands SET patient_id=?, assigned_at=?, assigned_by=? WHERE band_id=?",
                    (patient_id, time.time() if patient_id else None, by if patient_id else None, band_id))
    audit(by, "assign_band" if patient_id else "unassign_band", f"{band_id} → {patient_id or '—'}")


# ───────────────────────── band traffic (called by the band page) ─────────────────────────
def _clean_id(v) -> str | None:
    v = str(v or "")
    return v if _ID_RE.match(v) else None


def auto_flag(source: str | None, translation: str | None) -> str | None:
    """Heuristic review flag (a stand-in for model confidence, which the API does not expose)."""
    t = (translation or "").strip()
    if not t or t == "Audio translation":
        return "No interpretation text captured"
    if not (source or "").strip():
        return "Original speech not captured"
    # Character counts are not comparable for Chinese/Japanese/Korean scripts, so skip the length check there.
    if _CJK.search(t) or _CJK.search(source):
        return None
    ratio = len(t) / max(1, len(source.strip()))
    if ratio < 0.35 or ratio > 3.0:
        return "Length mismatch between original and interpretation"
    return None


def session_event(event: str, conversation_id, band_id, patient_id, language_1: str, language_2: str) -> bool:
    cid = _clean_id(conversation_id)
    if not cid:
        return False
    now = time.time()
    with _db() as con:
        if event == "start":
            con.execute("INSERT OR IGNORE INTO conversations (conversation_id, band_id, patient_id, language_1,"
                        " language_2, started_at, last_activity) VALUES (?,?,?,?,?,?,?)",
                        (cid, str(band_id or "")[:20] or None, _clean_id(patient_id), str(language_1)[:40],
                         str(language_2)[:40], now, now))
        elif event == "end":
            con.execute("UPDATE conversations SET ended_at=? WHERE conversation_id=? AND ended_at IS NULL", (now, cid))
        else:
            return False
    return True


def log_exchange(conversation_id, band_id, patient_id, source_text, translation, language_1, language_2) -> str | None:
    cid = _clean_id(conversation_id)
    translation = str(translation or "").strip()[:MAX_TEXT]
    if not cid or not translation:
        return None
    source_text = (str(source_text).strip()[:MAX_TEXT] or None) if source_text else None
    band_id, patient_id = (str(band_id or "")[:20] or None), _clean_id(patient_id)
    now, xid = time.time(), uuid.uuid4().hex
    with _db() as con:
        con.execute("INSERT OR IGNORE INTO conversations (conversation_id, band_id, patient_id, language_1,"
                    " language_2, started_at, last_activity) VALUES (?,?,?,?,?,?,?)",
                    (cid, band_id, patient_id, str(language_1)[:40], str(language_2)[:40], now, now))
        con.execute("UPDATE conversations SET last_activity=?, ended_at=NULL WHERE conversation_id=?", (now, cid))
        con.execute("INSERT INTO exchanges (exchange_id, conversation_id, band_id, patient_id, ts, source_text,"
                    " translation, language_1, language_2, auto_flag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (xid, cid, band_id, patient_id, now, source_text, translation, str(language_1)[:40],
                     str(language_2)[:40], auto_flag(source_text, translation)))
    return xid


# ───────────────────────── reads for the Portal ─────────────────────────
_CONV_SELECT = """
SELECT c.*, p.name, p.unit, p.room, p.language AS patient_language,
  (SELECT COUNT(*) FROM exchanges e WHERE e.conversation_id = c.conversation_id) AS n_exchanges,
  (SELECT COUNT(*) FROM exchanges e WHERE e.conversation_id = c.conversation_id
     AND (e.review_status = 'flagged' OR (e.auto_flag IS NOT NULL AND e.review_status = 'unreviewed'))) AS n_flags
FROM conversations c LEFT JOIN patients p ON p.patient_id = c.patient_id
"""


def live_conversations(unit: str | None = None) -> list[dict]:
    cutoff = time.time() - config.PORTAL_LIVE_WINDOW_SEC
    with _db() as con:
        rows = con.execute(_CONV_SELECT + " WHERE c.ended_at IS NULL AND c.last_activity >= ?"
                           " AND (? IS NULL OR p.unit = ?) ORDER BY c.last_activity DESC", (cutoff, unit, unit)).fetchall()
    return [dict(r) for r in rows]


def conversations(unit: str | None = None, language: str | None = None, search: str = "",
                  flagged_only: bool = False, since: float | None = None, include_sample: bool = True,
                  limit: int = 200) -> list[dict]:
    where, args = ["1=1"], []
    if unit:
        where.append("p.unit = ?"); args.append(unit)
    if language:
        where.append("(c.language_1 = ? OR c.language_2 = ?)"); args += [language, language]
    if since:
        where.append("c.started_at >= ?"); args.append(since)
    if not include_sample:
        where.append("c.sample = 0")
    if search.strip():
        where.append("(p.name LIKE ? OR c.band_id LIKE ? OR EXISTS (SELECT 1 FROM exchanges e WHERE"
                     " e.conversation_id = c.conversation_id AND (e.translation LIKE ? OR e.source_text LIKE ?)))")
        s = f"%{search.strip()}%"; args += [s, s, s, s]
    q = _CONV_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY c.last_activity DESC LIMIT ?"
    with _db() as con:
        rows = [dict(r) for r in con.execute(q, args + [limit]).fetchall()]
    return [r for r in rows if r["n_flags"]] if flagged_only else rows


def conversation(conversation_id: str) -> dict | None:
    with _db() as con:
        r = con.execute(_CONV_SELECT + " WHERE c.conversation_id = ?", (conversation_id,)).fetchone()
    return dict(r) if r else None


def exchanges(conversation_id: str) -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM exchanges WHERE conversation_id=? ORDER BY ts", (conversation_id,)).fetchall()
    return [dict(r) for r in rows]


def set_review(exchange_id: str, status: str, by: str) -> None:
    if status not in ("verified", "flagged", "unreviewed"):
        raise ValueError(status)
    with _db() as con:
        con.execute("UPDATE exchanges SET review_status=?, reviewed_by=?, reviewed_at=? WHERE exchange_id=?",
                    (status, by, time.time(), exchange_id))
    audit(by, f"review_{status}", exchange_id)


def report(unit: str | None = None, since: float | None = None, include_sample: bool = True) -> dict:
    where, args = ["1=1"], []
    if unit:
        where.append("p.unit = ?"); args.append(unit)
    if since:
        where.append("e.ts >= ?"); args.append(since)
    if not include_sample:
        where.append("e.sample = 0")
    base = (" FROM exchanges e LEFT JOIN patients p ON p.patient_id = e.patient_id WHERE " + " AND ".join(where))
    with _db() as con:
        tot = dict(con.execute(
            "SELECT COUNT(*) AS exchanges, COUNT(DISTINCT e.conversation_id) AS conversations,"
            " COUNT(DISTINCT e.patient_id) AS patients,"
            " SUM(e.review_status = 'verified') AS verified,"
            " SUM(e.review_status = 'flagged' OR (e.auto_flag IS NOT NULL AND e.review_status = 'unreviewed')) AS flagged"
            + base, args).fetchone())
        by_lang = [dict(r) for r in con.execute(
            "SELECT CASE WHEN e.language_1 = 'English' THEN e.language_2 ELSE e.language_1 END AS language,"
            " COUNT(*) AS exchanges" + base + " GROUP BY language ORDER BY exchanges DESC", args).fetchall()]
        by_unit = [dict(r) for r in con.execute(
            "SELECT COALESCE(p.unit, 'Unassigned band') AS unit, COUNT(*) AS exchanges,"
            " COUNT(DISTINCT e.patient_id) AS patients" + base + " GROUP BY unit ORDER BY exchanges DESC", args).fetchall()]
        by_day = [dict(r) for r in con.execute(
            "SELECT date(e.ts, 'unixepoch', 'localtime') AS day, COUNT(*) AS exchanges" + base
            + " GROUP BY day ORDER BY day", args).fetchall()]
    tot = {k: int(v or 0) for k, v in tot.items()}
    return {"totals": tot, "by_language": by_lang, "by_unit": by_unit, "by_day": by_day}


def compliance_csv(unit: str | None = None, since: float | None = None, include_sample: bool = True) -> str:
    """Section 1557 language-access log: one row per interpreted exchange (no transcript text)."""
    where, args = ["1=1"], []
    if unit:
        where.append("p.unit = ?"); args.append(unit)
    if since:
        where.append("e.ts >= ?"); args.append(since)
    if not include_sample:
        where.append("e.sample = 0")
    q = ("SELECT datetime(e.ts, 'unixepoch', 'localtime') AS timestamp, e.patient_id, p.unit, p.room, e.band_id,"
         " e.language_1, e.language_2, e.review_status, COALESCE(e.auto_flag, '') AS auto_flag, e.sample"
         " FROM exchanges e LEFT JOIN patients p ON p.patient_id = e.patient_id WHERE " + " AND ".join(where)
         + " ORDER BY e.ts")
    with _db() as con:
        rows = con.execute(q, args).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp", "patient_id", "unit", "room", "band_id", "language_1", "language_2",
                "review_status", "auto_flag", "sample_data"])
    for r in rows:
        w.writerow(list(r))
    return buf.getvalue()


def transcript_csv(conversation_id: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp", "original_speech", "interpretation", "languages", "review_status", "auto_flag"])
    for e in exchanges(conversation_id):
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["ts"])), e["source_text"] or "",
                    e["translation"], f"{e['language_1']} ↔ {e['language_2']}", e["review_status"], e["auto_flag"] or ""])
    return buf.getvalue()
