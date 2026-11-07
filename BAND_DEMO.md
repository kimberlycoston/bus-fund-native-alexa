# Lisans Band + Lisans Portal live prototype

`band_app.py` now has two pages (top menu):

- **Lisans Band**: the clickable wearable. Each interpreted sentence is saved to the Portal with what was actually said (original speech) and the interpretation, against the band's current patient.
- **Lisans Portal**: the hospital web app. Staff sign in, watch live bilingual transcripts, search past conversations, mark exchanges verified or flagged, assign bands to patients, and export a Section 1557 language-access log.


Run alongside the original ambient prototype. This entry point uses the same server-side ephemeral-token flow, browser audio capture, local speech segmentation, streamed Realtime interpretation, echo gating, and exact-audio replay. It requires no wake-word model.

## Launch

```bash
python -m pip install -r requirements.txt
python -m streamlit run band_app.py
```

For Streamlit Community Cloud, set the entry point to `band_app.py` on branch `prototype/lisans-band`.

Put your API key in Streamlit's app secrets (or your local `.streamlit/secrets.toml`):

```toml
OPENAI_API_KEY = "your-key-here"
```

Never commit a key. The normal key stays on the Python server; the browser receives a short-lived session credential.

## Present the Portal

1. Open the app in two browser tabs (or two windows side by side).
2. Tab 1, **Lisans Portal**: sign in as `language.services` (all units) or `taylor.rn` (Cardiac Step-Down 4B only). Every demo account uses the password `lisans-demo`.
3. Tab 2, **Lisans Band**: band **LB-0014** is worn by Minh Tran (fictional, Vietnamese, Room 14). Click **Use patient’s language (Vietnamese)**, then press the band and speak.
4. In tab 1, the **Live** tab shows the conversation within about 2 seconds: original speech on the left, interpretation on the right. Click **Verify** or **Flag** on any line.
5. **Transcripts** searches every conversation (try “chest”) and exports one as CSV. **Compliance** shows exchanges by language, unit and day and exports the 1557 log (Language Services/admin only). **Audit log** lists every sign-in, view, review and export.
6. **Patients & bands** assigns a band to a different patient or registers a new fictional patient.

The Portal starts with clearly labelled sample history (a “Sample” column and an *Include sample data* toggle). The admin account (`portal.admin`) can reset the demo data from the Audit log tab.

## Present the band

1. Open in Chrome or Edge over HTTPS or localhost. Turn up speaker volume.
2. Select staff and patient languages, then **Set languages**. Settings persist for this browser device.
3. The prototype opens with language controls and the live transcript visible.
4. Click the large button on the band and allow microphone access. Wait for Listening and the chime.
5. Speak a sentence in either selected language, pause, and listen to the spoken translation. Wait for the next chime before replying.
6. Click **Replay last translation** to replay the exact last audio.
7. Press the band again to stop. Inactivity after two minutes and connection errors also stop the live session.

The conversation panel shows the translated output from the model, with the original speech underneath when available. It is held in page memory until cleared or reloaded. No canned exchanges or simulation mode are included. The dropdowns can be changed while stopped. During an active session, say “choose languages,” wait for the spoken prompt, then name two languages (for example, “English and Vietnamese”). Native validates and saves the pair, confirms it aloud, and resumes interpretation. The same browser device remembers the pair after stopping, restarting, or reloading. Say “repeat please” to replay the last translation. Ambiguous replies prompt clarification, and cancellation or timeout preserves the old pair.

## Prototype boundaries

This is a clickable software representation of a wearable using the computer's microphone and speakers. It does not pair with physical hardware or implement EHR integration or hospital connectivity. The Portal is a prototype: demo logins (not hospital single sign-on), fictional patients, and a SQLite file on the demo server (`data/lisans_portal.db`, not committed). On Streamlit Community Cloud that file resets when the app restarts. It is not a HIPAA-compliant system and must never hold real patient information.

**Original speech** comes from OpenAI input transcription (`NATIVE_INPUT_TRANSCRIPTION_MODEL`, default `gpt-4o-mini-transcribe`; set it to an empty string to turn it off). If OpenAI rejects that setting, the session is created again without it, so interpretation keeps working and the Portal shows “Not captured.” **Needs review** is a simple heuristic (original speech missing, or a large length mismatch), not a model confidence score.

Production design (not built): HIPAA-compliant cloud under a business associate agreement, encryption in transit and at rest, hospital single sign-on with role-based access, and opening the Portal from inside Epic via SMART on FHIR. Use fictional conversations for the presentation. This prototype is not validated for patient care.

## Checks

```bash
python -m pytest tests -q          # includes tests/test_portal.py (store, login, sync, flags, CSV, transcription fallback)
node tests/band_controller.mjs
```

A real API key and microphone are needed to verify live translation end to end.
