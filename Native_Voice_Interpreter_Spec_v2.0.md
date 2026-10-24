# Native — Wake-Word-Activated Multilingual Voice Interpreter

**Technical Product Specification | Version 2.0 | Streamlit browser prototype**

**Status:** Consolidated implementation specification. This document replaces Versions 1.3 and 1.4 and earlier superseded requirements.

## 1. Product overview

Native is a laptop-first, hands-free, bidirectional **multilingual** spoken interpretation prototype for a simulated bedside conversation. **English ↔ Spanish is the initial default only**, not a language restriction. Users may select any two distinct languages supported and validated by the configured interpretation service, including pairs that do not involve English.

The user opens a Streamlit webpage and clicks **Activate Native** once. Native then listens for the custom wake phrase **“Hey Native”** without sending standby audio to OpenAI. On activation, Native plays `start_record.m4a` and begins a continuous spoken interpretation session. Each completed utterance is translated into the *other currently selected language* and spoken aloud. The user does not need to repeat the wake phrase between ordinary conversational turns.

Two commands are supported during an active session: **“Hey Native, choose languages”** and **“Hey Native, repeat please.”** The wake phrase is required for command recognition, not for ordinary translation. Users may say the wake phrase and command together, or say “Hey Native,” wait for a ready cue, and then say the command.

**Prototype boundary:** Native is not a certified medical interpreter or approved for unsupervised clinical use. Use fictional/synthetic conversations only.

## 2. Authoritative defaults and requirements

| Item | Default / requirement |
|---|---|
| Application | Streamlit single-page browser UI with a custom low-latency browser-audio component |
| Primary UI | One toggle button: **Activate Native** / **Deactivate Native**; status and selected language pair displayed |
| Wake phrase | “Hey Native” using the user's supplied compatible openWakeWord model |
| Initial language pair | **English ↔ Spanish (defaults only)** |
| Language selection | Voice-only: “Hey Native, choose languages,” followed by two spoken language names |
| Repeat | “Hey Native, repeat please” replays the most recent completed translation |
| Commands | Exactly two command intents: choose languages, repeat please |
| Utterance boundary | **3.0 seconds** of silence after actual speech; configurable in code |
| Conversational inactivity | **120 seconds**; configurable in code; separate from utterance boundary |
| End-of-utterance cue | `assets/stop_record.m4a` |
| Ready-to-speak cue | `assets/start_record.m4a` |
| Language persistence | Device/browser-session-associated saved pair, persistent across app restarts |
| Command-interface language | English initially; independent of the selected interpretation pair |
| Standby cloud audio | None |
| Transcript / audio persistence | Off by default |
| Hardware target | Laptop browser first; future device adaptation is out of scope |

## 3. Primary user experience

1. User opens the Streamlit webpage and clicks **Activate Native**. The browser requests microphone permission and unlocks audio playback.
2. Native displays **Standby — Say “Hey Native.”** Only wake-word detection operates; no standby audio is sent to OpenAI.
3. User says **“Hey Native.”** The detector recognizes the phrase; Native transitions to ACTIVATING, plays `start_record.m4a` when ready, and enters LISTENING.
4. The first speaker talks in either selected language. After **3 seconds** of silence following genuine speech, Native plays `stop_record.m4a`, translates the utterance into the other selected language, and speaks the translation.
5. When playback ends, Native plays `start_record.m4a` to indicate that the next speaker may talk. It continues across turns without requiring the wake phrase.
6. If the user says **“Hey Native, choose languages”**, Native enters command mode and asks, **“Which two languages would you like me to translate?”** The user answers, for example, **“Spanish and Mandarin Chinese.”** Native validates, saves, confirms, and immediately uses that pair.
7. If the user says **“Hey Native, repeat please”**, Native replays the cached audio of the latest completed translation in its original output language, without retranslating.
8. After **120 seconds** of genuine conversational inactivity, Native closes cloud interpretation streaming and returns to STANDBY, retaining the saved language pair and local wake-word detection.
9. The user may click **Deactivate Native** at any time. This immediately stops browser microphone capture, wake-word detection, and the active cloud session.

### 3.1 Wake phrase and command in the same utterance

Both of the following **must** work:

- **Continuous:** “Hey Native, choose languages.”
- **Paused:** “Hey Native.” *[ready chime]* “Choose languages.”

Likewise for “repeat please.”

**Critical audio requirement:** Maintain a short rolling audio buffer and preserve the post-wake-word speech. A command spoken immediately after “Hey Native” must not be lost while Native changes state, establishes a session, or plays the chime. The controller must isolate the command portion, not translate the full wake-word utterance as ordinary speech. Do not play a long cue that masks the remainder of a continuous command; buffer or defer processing as needed. Test both rapid and paused phrasing. The implementation must not assume the user pauses after the wake phrase.

## 4. States and transitions

| State | Behavior | Key transitions |
|---|---|---|
| OFF | No microphone capture, wake-word detection, or cloud session | Activate Native → STANDBY |
| STANDBY | Browser microphone on for wake-word detection; no audio to OpenAI | “Hey Native” → ACTIVATING; Deactivate → OFF |
| ACTIVATING | Preserve buffered post-wake speech, initialize session, play ready cue without contaminating input | Ordinary speech → LISTENING; recognized command → COMMAND; failure → ERROR |
| LISTENING | Capture human speech, run VAD; wake-word detection also active for commands | Completed utterance → TRANSLATING; “Hey Native” → COMMAND; inactivity → STANDBY |
| TRANSLATING | Process captured utterance and prepare output; no idle timeout during processing | Output ready → SPEAKING; failure → ERROR |
| SPEAKING | Play translated speech, protect microphone against feedback; then ready cue | Playback complete → LISTENING |
| COMMAND | Recognize only the two allowed commands after a valid wake phrase | Choose languages → LANGUAGE_SELECTION; repeat → REPLAYING; unknown → brief help → LISTENING |
| LANGUAGE_SELECTION | Ask for and capture two language names without another wake phrase; suspend ordinary translation | Valid selection → save/confirm → LISTENING; invalid → clarify; cancel/timeout → LISTENING |
| REPLAYING | Play cached latest translation without changing its language or content | Playback complete → LISTENING |
| ERROR | Display recoverable error and stop falsely indicating active interpretation | Recover → STANDBY or LISTENING; Deactivate → OFF |

**Status display:** Show Off, Standby, Activating, Listening, Translating, Speaking, Choosing languages, Replaying, or Error as appropriate. Always visibly distinguish browser microphone capture from active cloud transmission.

## 5. Functional requirements

### FR-01 — Wake-word detection and command routing

- Load the user's purchased/trained **“Hey Native”** openWakeWord model from a configurable file path. Check model/runtime compatibility, file format (often `.onnx`), sample rate, and inference dependencies; do not assume any third-party export works unchanged.
- Detect the wake phrase during STANDBY **and during active interpretation** (with echo protection).
- Apply sensitivity tuning, debouncing, and cooldown so a single wake phrase does not trigger twice.
- Keep a short rolling audio buffer and preserve the audio after the detected wake phrase. A continuous utterance such as “Hey Native, repeat please” must work without a pause.
- Following wake detection in an active session, route the post-wake speech to **COMMAND** handling rather than translation.
- The two actionable intents are **choose languages** and **repeat please**, including clear natural variants *only after* a valid wake phrase. Unsupported commands receive a short explanation, not execution.
- “Choose languages” or “repeat please” spoken **without** the wake phrase during normal interpretation is ordinary content to translate, not a command.
- In STANDBY, a bare “Hey Native” starts ordinary interpretation. If it is immediately followed by a recognized command, execute the command instead.
- Do not let Native's own synthesized audio or cues trigger the wake detector.

### FR-02 — Dynamic multilingual interpretation

- The first-use pair is **English ↔ Spanish**. This is a **default preference**, never a hard-coded language limitation.
- Allow **any two distinct supported and validated languages**. Neither needs to be English. Examples: English ↔ French; Spanish ↔ Mandarin Chinese; Arabic ↔ French, subject to service support and validation.
- Detect which of the **two selected languages** the human speaker uses on every completed conversational turn and translate into the other selected language.
- Do not assume a fixed speaker role or direction; clinician and patient may speak either selected language.
- No extra wake word or button is needed between ordinary turns.
- Preserve meaning, negation, uncertainty, names, numbers, medication doses, clinical terms, and questions. Do not answer questions, offer advice, embellish, summarize, or act as a conversational assistant.
- If audio is unclear, incomplete, or language identity uncertain, request repetition/clarification rather than fabricate content.
- If speech is in neither selected language, do not silently translate using an unrelated pair. Request clarification.
- No requirement to use English as an intermediary in the **user-facing** workflow; any internal processing route must preserve fidelity and be evaluated for the selected pair.
- A requested language pair must be rejected with an explanation if unsupported or unvalidated, preserving the previous pair.

### FR-03 — Voice language selection

1. User says **“Hey Native, choose languages.”**
2. Native asks, in the configured **command-interface language** (English initially): **“Which two languages would you like me to translate?”**
3. Native captures the user's immediate reply **without another wake phrase**, e.g. “Spanish and Mandarin Chinese.”
4. Parse two language names and normalize recognized aliases where unambiguous (e.g. “Mandarin” → Mandarin Chinese).
5. Validate that the languages are distinct and that both are supported for spoken input and spoken output in the intended pair.
6. On success, call `set_languages(language_1, language_2)` and wait for explicit application confirmation.
7. Persist the new pair, update the active session instructions and UI, then say: **“Okay, I'll translate between [language 1] and [language 2].”**
8. Return automatically to LISTENING. No save command, extra wake phrase, or manual restart is required.
9. If one language is missing, ambiguous, unsupported, or duplicated, ask a targeted clarifying question. **Never overwrite the previous saved pair on failure.**

The **command-interface language** is independent of the interpretation pair, initially English. Do not automatically switch it when the interpretation pair changes. The initial prototype need not support changing the command-interface language by voice.

### FR-04 — Repeat last translation

- User says **“Hey Native, repeat please”** (continuous or paused after the wake phrase).
- Call `repeat_last_translation`, which replays **the most recent completed translated audio**, using cached audio rather than generating a paraphrase.
- Do not cache chimes, command prompts, confirmation speech, or errors as the last translation.
- If no completed translation exists, say **“There's nothing to repeat yet.”**
- Resume interpretation after replay.
- Clear the cached translation on a successful language-pair change, on return to STANDBY, or on full deactivation, preventing stale output from another session.

### FR-05 — End-of-speech and turn-taking cues

- Use VAD and a **3.0-second default silence period after genuine human speech** to determine utterance completion.
- Three seconds is an **utterance boundary**, not the 120-second inactivity timeout.
- Do not submit silence or background noise as a turn.
- Show **User speaking** while speech is detected.
- On a completed ordinary speech turn, play `assets/stop_record.m4a` **once**, then translate and speak the output.
- After translated audio playback ends, play `assets/start_record.m4a` **once** to signal readiness for the next person.
- Play `start_record.m4a` on initial wake-word activation when ready. Do not interpret either cue as a command or user utterance.
- During a command interaction, prioritize clear prompts and safe turn capture; do not let ordinary translation cues interrupt or obscure command speech.
- If the Realtime API's built-in turn detection cannot reliably implement this threshold, use application-managed VAD/turn segmentation or document and test the closest supported implementation.

### FR-06 — Inactivity and command timeouts

- Return to STANDBY after **120 seconds** of genuine conversational inactivity, configurable in code.
- Measure inactivity from the most recent meaningful human conversational activity; do not count Native's synthesized output as human activity.
- Never time out while processing a translation or playing translation audio.
- Suspend the normal interpretation inactivity timer while LANGUAGE_SELECTION is awaiting an answer. Use a separate configurable **30-second command-reply timeout**; on expiration, cancel the pending selection, preserve the saved pair, and return to LISTENING.
- On normal inactivity timeout, stop cloud streaming, optionally play a distinct **session shutdown** cue if supplied, and return to local wake-word standby. **Do not use `stop_record.m4a` as a session shutdown cue**; it is the end-of-utterance cue.
- Deactivate Native always overrides these timers and stops capture immediately.

### FR-07 — Echo protection, playback and interruption

- For the first prototype, gate or suppress microphone interpretation input during Native's spoken translations and chimes so Native does not translate itself.
- Preserve command speech following a wake phrase even if the activation cue would otherwise overlap; buffer it or defer cue playback.
- Prefer headset testing initially; design toward speaker/microphone operation.
- Acoustic echo cancellation and interruption-friendly full-duplex behavior are future improvements, not guaranteed in v2.0.
- Avoid overlapping translation output, command prompts, and chimes.

### FR-08 — Persistence, privacy and error handling

- Store the selected language pair in a small local preference store (e.g. JSON), associated with the prototype device/session as appropriate; document how this behaves on shared or remotely hosted installations.
- On first use without a saved pair, use English ↔ Spanish. On later launches, load the saved pair.
- Do not store microphone recordings or transcripts by default. Cache only the most recent completed translated audio **in memory** for repeat functionality.
- Keep the OpenAI API key on the backend in environment variables or Streamlit secrets, never in frontend JavaScript, downloadable files, or prompt text.
- Clearly indicate microphone permission, active browser capture, and when audio is transmitted to OpenAI.
- Handle microphone denial, model loading failure, network loss, unsupported language pair, invalid credentials, and audio playback failure with recoverable visible errors and safe state transitions.

## 6. Minimal Streamlit interface

- **OFF:** prominent **Activate Native** button.
- **Activated:** replace it with **Deactivate Native**, which immediately stops browser microphone tracks, local/backend detection, and the cloud session.
- Display the current status and selected language pair in small, accessible text.
- No transcript panel, language selection buttons, settings form, or additional visible controls are required in the initial UI.
- Language changes happen by voice; configuration defaults may be edited in code.
- Browser microphone access requires user permission and generally HTTPS or localhost.
- The single click must also enable audio playback as required by browser autoplay restrictions.

## 7. Browser and backend architecture

**Important:** A remotely hosted Streamlit Python process cannot capture a visitor's laptop microphone using Python `sounddevice` or `pyaudio`; those libraries access the **server's** microphone.

Implement a **custom Streamlit component** with JavaScript microphone capture (`getUserMedia`, Web Audio API / AudioWorklet, or WebRTC) and a low-latency continuous transport (WebRTC or WebSocket). Do not use Streamlit rerun loops or `st.audio_input` uploads for real-time streaming.

**Wake-word inference options:**
1. **Browser-side:** if the purchased openWakeWord model can run compatibly in the browser, process standby audio there.
2. **Python backend-side:** stream audio frames securely to the Python backend for openWakeWord inference. This is acceptable for a local laptop-hosted classroom demo, but **do not call it browser/device-local** when the backend is remote. Clearly disclose that standby audio travels to the server. In either case, **never send standby audio to OpenAI**.

**Logical components:**
- Browser audio capture and playback
- Local/browser or backend wake-word engine
- Rolling audio buffer, VAD and state machine
- Command router and application functions
- OpenAI Realtime API session for speech interpretation
- Device preference storage and one-translation audio cache
- Minimal Streamlit status/button interface

**Audio flow:**

`Browser microphone → wake-word detector → wake detected → buffered command/ordinary speech routing → VAD → OpenAI Realtime API → translated audio → browser speaker → next turn`

The application controller—not the language-model prompt—owns wake-word detection, mode transitions, buffering, chimes, timers, audio routing, persistence, and replay.

Confirm current Realtime API model availability, supported languages, tool-calling behavior, audio formats, pricing, and turn-detection controls against current documentation during implementation. Do not assume every language pair performs equally well; validate intended pairs.

## 8. Copy-ready OpenAI Realtime session instructions

Supply the following in the Realtime session **instructions** field, **not** in the API key. Substitute the saved language names and the command-interface language at session creation or update. The controller must explicitly signal INTERPRETATION vs COMMAND vs LANGUAGE_SELECTION mode and execute application tools.

```text
You are Native, a hands-free, bidirectional multilingual spoken interpreter.

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

The application controller—not these instructions—handles wake-word detection, rolling audio buffering, command routing, chimes, turn detection, session state, microphone gating, persistent preferences, replay caching, and timeouts.
```

## 9. Application functions and controller contract

| Function | Inputs | Required behavior |
|---|---|---|
| `set_languages` | `language_1`, `language_2` | Normalize/validate two distinct supported languages and pair capabilities; atomically persist; update session instructions and UI; return explicit success/failure |
| `repeat_last_translation` | None | Replay exact cached audio of the latest completed translation; return no-history if unavailable; do not overwrite cache with command output |
| `enter_command_mode` | Wake-detection event and buffered post-wake audio | Route the remainder of the wake utterance to command recognition; do not send it as ordinary translation |
| `finish_or_cancel_command` | Result/timeout | Restore LISTENING safely; preserve saved languages on cancellation |
| `deactivate_native` | UI action | Immediately stop browser microphone tracks, wake detection, cloud session and audio playback |

Implement actual callable application functions/tools and inspect their return values. A prompt alone cannot guarantee persistence, exact replay, wake-word routing, or UI state.

## 10. Acceptance tests

### Startup, wake word and audio
- **AT-01:** Activate Native requests the visitor's browser microphone, then enters STANDBY without sending standby audio to OpenAI.
- **AT-02:** “Hey Native” triggers one activation and the supplied `start_record.m4a` when ready.
- **AT-03:** Ordinary speech without the wake phrase cannot initiate cloud streaming from STANDBY.
- **AT-04:** An actual speech turn followed by **3 seconds** of silence plays `stop_record.m4a` once, produces the translation, then plays `start_record.m4a` once.
- **AT-05:** Neither cues nor Native's own translated speech cause a feedback loop or wake-word activation.
- **AT-06:** A **120-second** inactivity timeout returns to STANDBY; a 3-second utterance pause does not.

### Multilingual interpretation
- **AT-07:** First use defaults to English ↔ Spanish and translates in both directions.
- **AT-08:** “Hey Native, choose languages” → “English and French” changes the pair without a button or restart.
- **AT-09:** “Hey Native, choose languages” → “Spanish and Mandarin Chinese” works in both directions **if the service supports and the implementation validates that pair**; neither language is English.
- **AT-10:** The saved pair persists across app restarts; the app does not silently revert to English ↔ Spanish.
- **AT-11:** The system detects direction turn by turn without assuming clinician/patient language roles.
- **AT-12:** An invalid, duplicate, ambiguous or unsupported pair does not overwrite the saved pair.
- **AT-13:** Five alternating turns work without additional wake phrases or button presses.

### Voice commands and buffering
- **AT-14:** **Continuous:** “Hey Native, choose languages” is recognized even when spoken without a pause; no post-wake command audio is lost.
- **AT-15:** **Paused:** “Hey Native” → chime → “Choose languages” performs the same action.
- **AT-16:** Both continuous and paused “Hey Native, repeat please” variants replay the exact most recent translation.
- **AT-17:** “Choose languages” or “repeat please” **without** the wake phrase during interpretation is translated, not executed.
- **AT-18:** Language selection accepts the next reply without a wake phrase, asks for clarification when needed, and does not trigger ordinary translation.
- **AT-19:** Repeat with no translation history gives the no-history message.
- **AT-20:** A language change or session ending clears the repeat cache.
- **AT-21:** A 30-second unanswered language-selection prompt cancels the pending command without changing saved languages.

### Browser, safety and failures
- **AT-22:** Deactivate Native immediately releases browser microphone tracks and closes the active API session.
- **AT-23:** On remote hosting, microphone audio comes from the browser visitor, not the Python server's microphone.
- **AT-24:** Permission denial, invalid API key, model incompatibility, network failure and unsupported language selection yield clear, safe errors.
- **AT-25:** Synthetic phrases with numbers, allergies, negation, pain severity, medication doses and accents are evaluated for fidelity by qualified bilingual reviewers.
- **AT-26:** No real patient data is recorded or persisted by default.

## 11. Non-goals and safety boundaries

- Not a certified medical interpreter or replacement for institution-approved clinical interpretation services.
- Do not use real patient information or recordings during classroom tests.
- Do not claim HIPAA compliance or clinical deployment readiness without security review, vendor agreements, retention analysis, access controls, and clinical validation.
- Full-duplex barge-in, multilingual voice control beyond the two defined commands, speaker identification, patient profiles, and physical-device integration are future work.
- No promise that every conceivable language or language pair is supported: expose only combinations validated with the chosen speech service.

## 12. Implementation milestones

1. **Browser audio + wake word:** One-click Streamlit activation, microphone permission, model loading, standby inference, rolling buffer, ready cue, and full deactivation.
2. **Two-way interpretation:** Realtime API, 3-second VAD, accurate spoken translations, turn cues, and echo gating.
3. **Dynamic language selection:** Continuous/paused wake-plus-command recognition, language prompts, validation, persistent settings, and session updates.
4. **Repeat and session lifecycle:** Exact cached-audio replay, 120-second inactivity timeout, command timeout, and safe state transitions.
5. **Validation:** Multi-language-pair tests, accent/clinical fidelity checks, latency, ambient-noise false positives, browser/remote hosting tests, and error handling.

## 13. Inputs and open implementation decisions

**Required before coding:** (a) the trained “Hey Native” model and actual export format; (b) `start_record.m4a` and `stop_record.m4a`; (c) target OS/browser and hosting model; (d) input/output devices; (e) securely configured OpenAI API key.

**To verify during implementation:** Realtime API's current supported speech languages, practical quality of requested pairs, audio formats, tool invocation capabilities, wake-model browser compatibility, and browser microphone/audio-playback constraints.

**Defaults chosen for this consolidated specification:** 3-second utterance silence, 120-second inactivity timeout, 30-second language-selection reply timeout, English command-interface language, and clearing replay history at language changes or session end. These may be tuned after prototype testing.
