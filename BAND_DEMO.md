# Lisans Band live prototype

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

## Present

1. Open in Chrome or Edge over HTTPS or localhost. Turn up speaker volume.
2. Select staff and patient languages, then **Set languages**. Settings persist for this browser device.
3. Choose **Presentation view** to hide setup controls.
4. Click the large button on the band and allow microphone access. Wait for Listening and the chime.
5. Speak a sentence in either selected language, pause, and listen to the spoken translation. Wait for the next chime before replying.
6. Click **Replay last translation** to replay the exact last audio.
7. Press the band again to stop. Inactivity after two minutes and connection errors also stop the live session.

The conversation panel shows actual translated output from the model, not original-source transcription. It is held in page memory until cleared or reloaded. No canned exchanges or simulation mode are included. Language changes require ending the current session.

## Prototype boundaries

This is a clickable software representation of a wearable using the computer's microphone and speakers. It does not pair with physical hardware or implement EHR integration, hospital connectivity, patient registration, or human-interpreter routing. The design does not claim those features are connected. Use fictional conversations for the presentation. This prototype is not validated for patient care.

## Checks

```bash
python -m pytest tests -q
node tests/band_controller.mjs
```

A real API key and microphone are needed to verify live translation end to end.
