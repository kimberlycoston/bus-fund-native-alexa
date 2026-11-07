"""Lisans Portal page: the hospital-facing web app (prototype).

Clinicians sign in, watch band conversations live as bilingual transcripts,
search past conversations, mark exchanges verified or flagged, manage band
assignments, and export a Section 1557 language-access log. Everything reads
from `native.portal_store`, which the band page writes to in real time.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import streamlit as st

from . import portal_store as store
from .languages import supported_names

LOGO = Path(__file__).resolve().parent.parent / "native_component" / "frontend" / "assets" / "native-lisans-logo.png"
SESSION_TIMEOUT_SEC = 20 * 60

CSS = """
<style>
.lp-eyebrow{font-size:11px;font-weight:700;letter-spacing:2px;color:#718276;text-transform:uppercase}
.lp-title{font-size:30px;font-weight:700;letter-spacing:-.8px;margin:2px 0 0;color:#202d2a}
.lp-sub{color:#6d7e75;font-size:14px;margin-bottom:6px}
.lp-banner{background:#fff6e5;border:1px solid #f0d9a8;color:#6b5320;border-radius:8px;padding:8px 12px;font-size:13px;margin:6px 0 14px}
.lp-orig{font-size:15px;color:#202d2a}
.lp-tr{font-size:15px;color:#284e40;font-weight:600}
.lp-meta{font-size:11px;color:#8a9782;letter-spacing:.5px}
.lp-flag{font-size:12px;color:#9d483c;background:#fff2ee;border-radius:6px;padding:2px 8px;display:inline-block;margin-top:4px}
.lp-ok{font-size:12px;color:#2f6b3f;background:#eaf5ec;border-radius:6px;padding:2px 8px;display:inline-block;margin-top:4px}
.lp-live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#3d9b50;margin-right:6px;box-shadow:0 0 6px #3d9b50}
</style>
"""


# ───────────────────────── helpers ─────────────────────────
def _ago(ts: float | None) -> str:
    if not ts:
        return "—"
    s = int(time.time() - ts)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    return time.strftime("%b %d, %H:%M", time.localtime(ts))


def _when(ts: float | None) -> str:
    return time.strftime("%b %d, %H:%M:%S", time.localtime(ts)) if ts else "—"


def _user() -> dict | None:
    u = st.session_state.get("portal_user")
    if u and time.time() - st.session_state.get("portal_seen", 0) > SESSION_TIMEOUT_SEC:
        store.audit(u["username"], "session_timeout")
        st.session_state.pop("portal_user", None)
        st.session_state["portal_notice"] = "You were signed out after 20 minutes of inactivity."
        return None
    if u:
        st.session_state["portal_seen"] = time.time()
    return u


def _unit_scope(user: dict) -> str | None:
    """Nurses see their own unit; Language Services and admins see the whole hospital."""
    return user["unit"] if user["role"] == "nurse" else None


def _conv_label(c: dict) -> str:
    who = c.get("name") or "Unassigned band"
    where = f"{c.get('unit') or ''} · Room {c['room']}" if c.get("room") else (c.get("unit") or "")
    sample = " · sample" if c.get("sample") else ""
    return f"{who} — {c.get('language_1')} ↔ {c.get('language_2')} · {c.get('band_id') or 'no band'} · {where}{sample}"


def _audit_view_once(user: dict, conversation_id: str) -> None:
    seen = st.session_state.setdefault("portal_viewed", set())
    if conversation_id not in seen:
        seen.add(conversation_id)
        store.audit(user["username"], "view_transcript", conversation_id)


def _transcript(user: dict, conversation_id: str, key_prefix: str) -> None:
    """Bilingual transcript with per-exchange review controls."""
    _audit_view_once(user, conversation_id)
    rows = store.exchanges(conversation_id)
    if not rows:
        st.info("No exchanges yet. They appear here as soon as the band interprets the first sentence.")
        return
    for e in rows:
        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 5, 2])
            with c1:
                st.markdown('<div class="lp-meta">ORIGINAL SPEECH</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="lp-orig">{_esc(e["source_text"]) if e["source_text"] else "<i>Not captured</i>"}</div>',
                            unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div class="lp-meta">INTERPRETATION · {_esc(e["language_1"])} ↔ {_esc(e["language_2"])}</div>',
                            unsafe_allow_html=True)
                st.markdown(f'<div class="lp-tr">{_esc(e["translation"])}</div>', unsafe_allow_html=True)
            with c3:
                st.markdown(f'<div class="lp-meta">{_when(e["ts"])}</div>', unsafe_allow_html=True)
                status = e["review_status"]
                if status == "verified":
                    st.markdown(f'<span class="lp-ok">Verified · {_esc(e["reviewed_by"] or "")}</span>', unsafe_allow_html=True)
                elif status == "flagged":
                    st.markdown(f'<span class="lp-flag">Flagged · {_esc(e["reviewed_by"] or "")}</span>', unsafe_allow_html=True)
                elif e["auto_flag"]:
                    st.markdown(f'<span class="lp-flag">Needs review: {_esc(e["auto_flag"])}</span>', unsafe_allow_html=True)
                b1, b2 = st.columns(2)
                if b1.button("Verify", key=f"{key_prefix}v{e['exchange_id']}", disabled=status == "verified",
                             use_container_width=True):
                    store.set_review(e["exchange_id"], "verified", user["username"]); st.rerun()
                if b2.button("Flag", key=f"{key_prefix}f{e['exchange_id']}", disabled=status == "flagged",
                             use_container_width=True):
                    store.set_review(e["exchange_id"], "flagged", user["username"]); st.rerun()


def _esc(s) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ───────────────────────── login ─────────────────────────
def _login() -> None:
    left, mid, right = st.columns([1, 1.3, 1])
    with mid:
        if LOGO.exists():
            st.image(str(LOGO), width=64)
        st.markdown('<div class="lp-eyebrow">Native Lisans</div><div class="lp-title">Lisans Portal</div>'
                    f'<div class="lp-sub">{store.HOSPITAL_NAME} · Language access, live</div>', unsafe_allow_html=True)
        if st.session_state.get("portal_notice"):
            st.info(st.session_state.pop("portal_notice"))
        with st.form("portal_login"):
            username = st.text_input("Hospital username", placeholder="taylor.rn")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            user = store.authenticate(username, password)
            if user:
                st.session_state["portal_user"] = user
                st.session_state["portal_seen"] = time.time()
                st.rerun()
            st.error("That username and password don’t match.")
        st.button("Sign in with hospital SSO", disabled=True, use_container_width=True,
                  help="Planned: hospital single sign-on, and opening the Portal from inside Epic (SMART on FHIR).")
        with st.expander("Demo accounts (prototype only)"):
            st.markdown(f"Password for every demo account: `{store.DEMO_PASSWORD}`")
            st.table([{"Username": u, "Name": n, "Role": store.ROLES[r], "Unit": unit or "All units"}
                      for u, n, r, unit in store.DEMO_USERS])
        st.caption("Prototype with fictional patients. Do not enter real patient information.")


# ───────────────────────── tabs ─────────────────────────
def _live_tab(user: dict) -> None:
    st.caption("Conversations from bands in use right now. Refreshes every 2 seconds. "
               "Open the Lisans Band page in another tab, press the band and speak; each sentence appears here.")

    @st.fragment(run_every=2)
    def panel():
        live = store.live_conversations(_unit_scope(user))
        if not live:
            st.info("No band is in a live conversation right now.")
            return
        ids = [c["conversation_id"] for c in live]
        sel = st.session_state.get("portal_live_sel")
        if sel not in ids:
            sel = ids[0]
        cols = st.columns(min(3, len(live)))
        for i, c in enumerate(live[:6]):
            with cols[i % len(cols)]:
                with st.container(border=True):
                    st.markdown(f'<span class="lp-live"></span><b>{_esc(c.get("name") or "Unassigned band")}</b>',
                                unsafe_allow_html=True)
                    st.caption(f"{c.get('unit') or '—'} · Room {c.get('room') or '—'} · {c.get('band_id') or '—'}\n\n"
                               f"{c['language_1']} ↔ {c['language_2']} · {c['n_exchanges']} exchanges · "
                               f"last {_ago(c['last_activity'])}")
                    if st.button("Open transcript", key=f"live_{c['conversation_id']}", use_container_width=True,
                                 type="primary" if c["conversation_id"] == sel else "secondary"):
                        st.session_state["portal_live_sel"] = c["conversation_id"]
                        sel = c["conversation_id"]
        st.markdown("##### Live transcript")
        st.caption(_conv_label(next(c for c in live if c["conversation_id"] == sel)))
        _transcript(user, sel, "live")

    panel()


def _history_tab(user: dict) -> None:
    scope = _unit_scope(user)
    f1, f2, f3, f4 = st.columns([3, 2, 2, 2])
    search = f1.text_input("Search patient, band or words spoken", key="hist_search")
    language = f2.selectbox("Language", ["All"] + [l for l in supported_names() if l != "English"], key="hist_lang")
    period = f3.selectbox("Period", ["Last 7 days", "Last 30 days", "All time"], key="hist_period")
    unit = scope or f4.selectbox("Unit", ["All units"] + store.UNITS, key="hist_unit")
    if scope:
        f4.text_input("Unit", value=scope, disabled=True, key="hist_unit_locked")
    o1, o2 = st.columns(2)
    flagged = o1.toggle("Only conversations that need review", key="hist_flagged")
    sample = o2.toggle("Include sample data", value=True, key="hist_sample")
    since = {"Last 7 days": time.time() - 7 * 86400, "Last 30 days": time.time() - 30 * 86400}.get(period)
    convs = store.conversations(unit=None if unit == "All units" else unit,
                                language=None if language == "All" else language, search=search,
                                flagged_only=flagged, since=since, include_sample=sample)
    if not convs:
        st.info("No conversations match.")
        return
    st.dataframe(
        [{"Started": _when(c["started_at"]), "Patient": c.get("name") or "Unassigned band", "Unit": c.get("unit"),
          "Room": c.get("room"), "Band": c.get("band_id"), "Languages": f"{c['language_1']} ↔ {c['language_2']}",
          "Exchanges": c["n_exchanges"], "Needs review": c["n_flags"], "Sample": bool(c["sample"])} for c in convs],
        hide_index=True, use_container_width=True)
    labels = {c["conversation_id"]: f"{_when(c['started_at'])} · {_conv_label(c)}" for c in convs}
    cid = st.selectbox("Open a conversation", list(labels), format_func=labels.get, key="hist_open")
    if cid:
        st.download_button("Export this transcript (CSV)", store.transcript_csv(cid), file_name=f"transcript_{cid}.csv",
                           mime="text/csv", on_click=store.audit, args=(user["username"], "export_transcript", cid))
        _transcript(user, cid, "hist")


def _patients_tab(user: dict) -> None:
    scope = _unit_scope(user)
    pts = store.patients(scope)
    st.dataframe([{"Patient": p["name"], "ID": p["patient_id"], "Preferred language": p["language"],
                   "Unit": p["unit"], "Room": p["room"], "Band": p["band_id"] or "—"} for p in pts],
                 hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1, st.form("assign_band"):
        st.markdown("**Assign a band**")
        bands = store.bands()
        band_id = st.selectbox("Band", [b["band_id"] for b in bands],
                               format_func=lambda b: next((f"{x['band_id']} · {x['name'] or 'available'}"
                                                           for x in bands if x["band_id"] == b), b))
        opts = {"": "— Return band to dock (unassign) —"} | {p["patient_id"]: f"{p['name']} · {p['unit']} · Room {p['room']}"
                                                            for p in pts}
        pid = st.selectbox("Patient", list(opts), format_func=opts.get)
        if st.form_submit_button("Save assignment", type="primary"):
            store.assign_band(band_id, pid or None, user["username"])
            st.success(f"{band_id} {'assigned to ' + opts[pid] if pid else 'returned to the dock'}.")
            st.rerun()
    with c2, st.form("admit_patient", clear_on_submit=True):
        st.markdown("**Register a fictional patient**")
        name = st.text_input("Name (fictional)")
        language = st.selectbox("Preferred language", [l for l in supported_names() if l != "English"])
        unit = st.selectbox("Unit", [scope] if scope else store.UNITS)
        room = st.text_input("Room")
        if st.form_submit_button("Register"):
            try:
                pid = store.admit_patient(name, language, unit, room, user["username"])
                st.success(f"Registered {name} ({pid}). Assign a band to start.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def _compliance_tab(user: dict) -> None:
    scope = _unit_scope(user)
    c1, c2 = st.columns([2, 2])
    period = c1.selectbox("Period", ["Last 7 days", "Last 30 days", "All time"], key="rep_period")
    sample = c2.toggle("Include sample data", value=True, key="rep_sample")
    since = {"Last 7 days": time.time() - 7 * 86400, "Last 30 days": time.time() - 30 * 86400}.get(period)
    rep = store.report(scope, since, sample)
    t = rep["totals"]
    m = st.columns(5)
    m[0].metric("Interpreted exchanges", t["exchanges"])
    m[1].metric("Conversations", t["conversations"])
    m[2].metric("Patients served", t["patients"])
    m[3].metric("Verified by staff", t["verified"])
    m[4].metric("Need review", t["flagged"])
    if not t["exchanges"]:
        st.info("No interpreted exchanges in this period.")
        return
    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Exchanges by patient language**")
        st.bar_chart(pd.DataFrame(rep["by_language"]).set_index("language"), horizontal=True, color="#284e40")
    with g2:
        st.markdown("**Exchanges per day**")
        st.bar_chart(pd.DataFrame(rep["by_day"]).set_index("day"), color="#2f7d75")
    st.markdown("**By unit**")
    st.dataframe([{"Unit": r["unit"], "Exchanges": r["exchanges"], "Patients": r["patients"]} for r in rep["by_unit"]],
                 hide_index=True, use_container_width=True)
    can_export = user["role"] in ("language_services", "admin")
    st.download_button("Export Section 1557 language-access log (CSV)", store.compliance_csv(scope, since, sample),
                       file_name="lisans_language_access_log.csv", mime="text/csv", disabled=not can_export,
                       on_click=store.audit, args=(user["username"], "export_compliance_log", period),
                       help=None if can_export else "Language Services and admins can export the log.")
    st.caption("The log lists each interpreted exchange (time, patient ID, unit, band, languages, review status) "
               "without transcript text. “Needs review” uses simple checks such as missing original speech or a "
               "large length mismatch; it is not a model confidence score.")


def _audit_tab(user: dict) -> None:
    st.caption("Every sign-in, transcript view, review and export is recorded.")
    st.dataframe([{"When": _when(r["ts"]), "User": r["username"], "Action": r["action"], "Detail": r["detail"]}
                  for r in store.audit_log()], hide_index=True, use_container_width=True)
    if user["role"] == "admin":
        with st.expander("Reset demo data"):
            st.write("Deletes all conversations, assignments and audit entries, then restores the sample hospital.")
            if st.button("Reset demo data", type="primary"):
                store.reset_demo()
                st.session_state.pop("portal_user", None)
                st.rerun()


# ───────────────────────── page ─────────────────────────
def render() -> None:
    store.init()
    st.markdown(CSS, unsafe_allow_html=True)
    user = _user()
    if not user:
        _login()
        return
    h1, h2 = st.columns([4, 1.4])
    with h1:
        st.markdown(f'<div class="lp-eyebrow">Lisans Portal · {store.HOSPITAL_NAME}</div>'
                    f'<div class="lp-title">Every conversation, verified</div>', unsafe_allow_html=True)
    with h2:
        st.markdown(f"**{user['display_name']}**  \n{store.ROLES[user['role']]}"
                    f"{' · ' + user['unit'] if user['unit'] else ' · All units'}")
        if st.button("Sign out", use_container_width=True):
            store.audit(user["username"], "logout")
            for k in ("portal_user", "portal_viewed", "portal_live_sel"):
                st.session_state.pop(k, None)
            st.rerun()
    st.markdown('<div class="lp-banner">Prototype with fictional patients and demo accounts. Do not enter real '
                'patient information. Production design: HIPAA-compliant cloud under a BAA, encryption in transit and '
                'at rest, hospital single sign-on, and launch from inside Epic.</div>', unsafe_allow_html=True)
    names = ["Live", "Transcripts", "Patients & bands", "Compliance"]
    if user["role"] in ("language_services", "admin"):
        names.append("Audit log")
    tabs = st.tabs(names)
    with tabs[0]:
        _live_tab(user)
    with tabs[1]:
        _history_tab(user)
    with tabs[2]:
        _patients_tab(user)
    with tabs[3]:
        _compliance_tab(user)
    if len(tabs) > 4:
        with tabs[4]:
            _audit_tab(user)
