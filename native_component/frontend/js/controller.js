// Native application controller (spec §4 state machine, §9 contract).
// Owns: wake-word routing, rolling buffer, VAD turn segmentation, cues, timers,
// mic gating, Realtime session lifecycle, repeat cache. The model only interprets.

import { WakeWordEngine } from './wakeword.js';
import { SileroVAD, EnergyVAD } from './vad.js';
import { Player } from './player.js';
import { RealtimeClient } from './realtime.js';
import { backendRequest } from './streamlit.js';

export const S = Object.freeze({
  OFF: 'OFF', STANDBY: 'STANDBY', ACTIVATING: 'ACTIVATING', LISTENING: 'LISTENING', TRANSLATING: 'TRANSLATING',
  SPEAKING: 'SPEAKING', COMMAND: 'COMMAND', LANGUAGE_SELECTION: 'LANGUAGE_SELECTION', REPLAYING: 'REPLAYING', ERROR: 'ERROR',
});

const SR = 16000;
const CHUNK = 512;

class Ring {
  constructor(seconds) { this.cap = Math.ceil(seconds * SR); this.buf = new Float32Array(this.cap); this.total = 0; }
  write(c) { for (let i = 0; i < c.length; i++) this.buf[(this.total + i) % this.cap] = c[i]; this.total += c.length; }
  read(from, to) {
    from = Math.max(0, Math.floor(from), this.total - this.cap); to = Math.min(Math.floor(to), this.total);
    const n = Math.max(0, to - from), out = new Float32Array(n);
    for (let i = 0; i < n; i++) out[i] = this.buf[(from + i) % this.cap];
    return out;
  }
}

class NativeError extends Error { constructor(msg, kind = 'error', fatal = false) { super(msg); this.kind = kind; this.fatal = fatal; } }

function concatInt16(parts) {
  const n = parts.reduce((a, p) => a + p.length, 0), out = new Int16Array(n); let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

function deviceId() {
  const k = 'native_device_id';
  try {
    let id = localStorage.getItem(k);
    if (!id) { id = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/[^A-Za-z0-9_-]/g, ''); localStorage.setItem(k, id); }
    return id;
  } catch { return 'default'; }
}

export class NativeController {
  constructor(cfg, ui) {
    this.cfg = cfg; this.ui = ui;
    this.T = cfg.timing; this.TH = cfg.thresholds;
    this.state = S.OFF; this.pair = [...cfg.default_pair];
    this.deviceId = deviceId();
    this.gen = 0; this.busy = false; this.queue = []; this.processing = false;
    this.seg = null; this.pendingWake = null; this.lastWakeAt = -1e9; this.lastHuman = performance.now();
    this.lastTranslation = null; this.rt = null; this.rtConnecting = null; this.gateUntil = 0;
    this.vadRun = 0; this.wakeRun = 0; this.zeros = new Float32Array(CHUNK);
  }

  // ───────────────────────── setup ─────────────────────────
  preload() {
    if (this.modelsReady) return this.modelsReady;
    this.modelsReady = (async () => {
      if (!this.cfg.wake_model_ok) throw new NativeError(`Wake-word model problem: ${this.cfg.wake_model_error || 'not available'}`, 'model', true);
      const ort = window.ort;
      if (!ort) throw new NativeError('ONNX Runtime failed to load in the browser.', 'model', true);
      ort.env.wasm.wasmPaths = new URL('vendor/', location.href).href;
      ort.env.wasm.numThreads = 1;
      try {
        this.wake = await WakeWordEngine.create(ort, { melUrl: 'vendor/melspectrogram.onnx', embUrl: 'vendor/embedding_model.onnx', wakeUrl: 'runtime/wakeword.onnx' });
      } catch (e) {
        throw new NativeError(`The "Hey Native" model could not run in this browser: ${e.message || e}`, 'model', true);
      }
      try { this.vad = await SileroVAD.create(ort, 'vendor/silero_vad.onnx'); }
      catch (e) { console.warn('Silero VAD unavailable, using energy VAD', e); this.vad = new EnergyVAD(); }
    })();
    this.modelsReady.catch(() => {});
    return this.modelsReady;
  }

  async hello() {
    try {
      const r = await backendRequest('hello', { device_id: this.deviceId });
      if (r.ok) { this.pair = [r.language_1, r.language_2]; this.ui.setPair(this.pair); }
      this.hasApiKey = r.has_api_key;
    } catch (e) { console.warn(e); }
  }

  // ───────────────────────── activation ─────────────────────────
  /** Must be called synchronously from the Activate click (unlocks audio output). */
  async activate() {
    if (this.state !== S.OFF) return;
    const gen = ++this.gen;
    this.ui.clearError();
    this.player = new Player();
    this.player.onActivity = (playing) => { if (!playing) this.gateUntil = performance.now() + this.T.tail_guard * 1000; };
    this.player.unlock().catch(() => {});
    try { window.speechSynthesis && window.speechSynthesis.getVoices(); } catch {}
    this._setState(S.ACTIVATING, 'Starting…');
    try {
      await this.preload();
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
        throw new NativeError('Microphone access needs a secure page (HTTPS or localhost).', 'mic', true);
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      } catch (e) {
        const msg = e && e.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow microphone access for this page, then click Activate Native again.'
          : e && e.name === 'NotFoundError' ? 'No microphone was found.' : `Could not open the microphone: ${e.message || e}`;
        throw new NativeError(msg, 'mic', true);
      }
      if (gen !== this.gen) { this._stopMic(); return; }
      const AC = window.AudioContext || window.webkitAudioContext;
      this.inCtx = new AC();
      await this.inCtx.audioWorklet.addModule('js/capture-worklet.js');
      const src = this.inCtx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.inCtx, 'native-capture');
      const mute = this.inCtx.createGain(); mute.gain.value = 0;
      src.connect(this.node); this.node.connect(mute); mute.connect(this.inCtx.destination);
      this.node.port.onmessage = (e) => this._onChunk(e.data);
      await this.inCtx.resume();
      const cues = this.cfg.cues || {};
      // A cue that can't be decoded must not block interpretation: fall back to a built-in chime.
      const cueProblems = [];
      await Promise.all(Object.entries(cues).map(([k, url]) => this.player.loadCue(k, url, this.cfg.trim_cue_silence)
        .catch(e => {
          console.warn(`cue ${k} failed`, e);
          if (k === 'shutdown') return;
          this.player.synthCue(k);
          cueProblems.push(`${k} cue: ${e.message}`);
        })));
      for (const k of ['start', 'stop']) if (!this.player.cues[k]) this.player.synthCue(k);
      if (cueProblems.length) this.ui.error(`Using a built-in chime because ${cueProblems.join('; ')}.`);
      await this.wake.reset(); this.vad.reset();
      this.ring = new Ring(this.T.max_utterance + 10);
      this.queue = []; this.seg = null; this.pendingWake = null; this.lastTranslation = null;
      if (gen !== this.gen) return;
      this.tick = setInterval(() => this._tick(), 250);
      this._setState(S.STANDBY);
    } catch (e) {
      if (gen !== this.gen) return;
      this._teardown();
      this._setState(S.OFF);
      this.ui.error(e.message || String(e));
    }
  }

  /** deactivate_native (§9): stop mic tracks, wake detection, cloud session, playback — now. */
  deactivate() {
    this.gen++;
    this._teardown();
    this._setState(S.OFF);
  }

  _stopMic() { try { this.stream && this.stream.getTracks().forEach(t => t.stop()); } catch {} this.stream = null; }

  _teardown() {
    clearInterval(this.tick); this.tick = null;
    this._stopMic();
    try { this.node && (this.node.port.onmessage = null); } catch {}
    try { this.inCtx && this.inCtx.close(); } catch {}
    this.inCtx = null; this.node = null;
    this._closeSession();
    if (this.player) { this.player.close(); this.player = null; }
    this.queue = []; this.seg = null; this.pendingWake = null; this.busy = false;
    this.lastTranslation = null;              // FR-04: clear on deactivation
  }

  _closeSession() {
    if (this.rt) { this.rt.close(); this.rt = null; }
    this.ui.setCloud('off');
  }

  // ───────────────────────── audio frames ─────────────────────────
  _gated() {
    return this.busy || (this.player && this.player.busy) || performance.now() < this.gateUntil;
  }

  _onChunk(chunk) {
    if (this.state === S.OFF || !this.ring) return;
    const idx = this.ring.total;
    this.ring.write(chunk);
    this.queue.push({ chunk, idx, gated: this._gated() });
    if (!this.processing) this._drain();
  }

  async _drain() {
    this.processing = true; const gen = this.gen;
    while (this.queue.length && gen === this.gen) {
      const it = this.queue.shift();
      try { await this._processChunk(it); } catch (e) { console.error('frame error', e); }
    }
    this.processing = false;
  }

  async _processChunk({ chunk, idx, gated }) {
    if (gated) {
      // Echo protection: Native's own audio never reaches VAD or the wake detector.
      await this.wake.process(this.zeros);
      if (!this._wasGated) { this.vad.reset(); this._wasGated = true; }
      this.vadRun = 0; this.wakeRun = 0;
      return;
    }
    this._wasGated = false;
    const prob = await this.vad.process(chunk);
    const scores = await this.wake.process(chunk);
    this._onFrame(chunk, idx, prob, scores);
  }

  _onFrame(chunk, idx, prob, scores) {
    const now = performance.now(), end = idx + chunk.length;
    const speech = prob >= this.TH.vad;
    this.vadRun = speech ? this.vadRun + 1 : 0;
    if (this.cfg.debug) this.ui.meter(prob, scores.length ? Math.max(...scores) : null);

    // 1 ─ wake phrase (STANDBY, and LISTENING for commands)
    for (const s of scores) {
      this.wakeRun = s >= this.TH.wake ? this.wakeRun + 1 : 0;
      if (this.wakeRun >= this.TH.wake_frames && now - this.lastWakeAt > this.T.wake_cooldown * 1000 && this._wakeAllowed()) {
        this._onWake(end); return;
      }
    }
    if (this.state === S.STANDBY) return;   // nothing else happens in standby; no cloud audio

    // 2 ─ an open segment (utterance / post-wake / language reply)
    const seg = this.seg;
    if (seg) {
      seg.end = end;
      if (speech) {
        seg.lastSpeech = end; this.lastHuman = now;
        if (!seg.deciding || end - seg.wakeIdx > 0.15 * SR) seg.speech += chunk.length;
        if (!seg.speaking) { seg.speaking = true; this._refreshStatus(); }
      }
      if (seg.deciding) {
        if ((end - seg.wakeIdx) / SR >= this.T.continuation_window) {
          seg.deciding = false;
          if (seg.speech >= 0.15 * SR) seg.hasSpeech = true;      // "Hey Native, choose languages" (continuous)
          else this._pausedWake(seg.origin);                        // "Hey Native." [chime] …
        }
        return;
      }
      const silence = (end - seg.lastSpeech) / SR;
      if ((seg.hasSpeech && silence >= seg.silenceSec) || (end - seg.start) / SR >= this.T.max_utterance) this._finalize();
      return;
    }

    // 3 ─ start a new segment on genuine speech
    if (this._canStartSegment() && this.vadRun >= this.TH.vad_start_frames) {
      let purpose = 'utterance', origin = null, silenceSec = this.T.utterance_silence;
      if (this.state === S.LANGUAGE_SELECTION) { purpose = 'langsel'; silenceSec = this.T.language_reply_silence; }
      else if (this.pendingWake) {
        purpose = 'postwake'; origin = this.pendingWake.origin;
        silenceSec = origin === 'active' ? this.T.command_silence : this.T.utterance_silence;
        this.pendingWake = null;
      }
      const startIdx = end - this.vadRun * CHUNK - Math.round(0.3 * SR);   // keep word onsets
      this.seg = { purpose, origin, start: startIdx, end, lastSpeech: end, speech: this.vadRun * CHUNK, hasSpeech: true, silenceSec, speaking: true };
      this.lastHuman = now;
      this._refreshStatus();
    }
  }

  _wakeAllowed() {
    if (this.busy) return false;
    if (this.state === S.STANDBY) return true;
    return this.state === S.LISTENING && !this.pendingWake && (!this.seg || this.seg.purpose === 'utterance');
  }

  _canStartSegment() {
    if (this.busy) return false;
    if (this.state === S.LISTENING || this.state === S.LANGUAGE_SELECTION) return true;
    return this.state === S.COMMAND && !!this.pendingWake;   // paused command after the ready chime
  }

  // enter_command_mode (§9): route what follows the wake phrase, never translate it blindly
  _onWake(wakeIdx) {
    this.lastWakeAt = performance.now(); this.wakeRun = 0; this.lastHuman = performance.now();
    this.ui.clearError();
    const origin = this.state === S.STANDBY ? 'standby' : 'active';
    // any utterance in progress contained the wake phrase itself → discard it
    this.seg = {
      purpose: 'postwake', origin, deciding: true, wakeIdx,
      start: wakeIdx - Math.round(this.T.post_wake_preroll * SR), end: wakeIdx, lastSpeech: wakeIdx, speech: 0,
      hasSpeech: false, silenceSec: origin === 'active' ? this.T.command_silence : this.T.utterance_silence,
    };
    this.pendingWake = null;
    if (origin === 'standby') {
      this.lastTranslation = null;
      this._setState(S.ACTIVATING);
      const gen = this.gen;
      this._ensureSession().catch(e => { if (gen === this.gen) this._recover(e); });
    } else {
      this._setState(S.COMMAND, 'Command — “choose languages” or “repeat please”');
    }
  }

  _pausedWake(origin) {
    this.seg = null;
    this.pendingWake = { origin, until: performance.now() + this.T.paused_wake_timeout * 1000 };
    if (origin === 'standby') this._setState(S.LISTENING);
    else this._setState(S.COMMAND, 'Command — “choose languages” or “repeat please”');
    this.player.playCue('start');    // ready-to-speak cue (mic gated while it plays)
  }

  _finalize() {
    const seg = this.seg; this.seg = null;
    if (seg.speech < this.T.min_speech * SR) { this._refreshStatus(); return; }   // noise, not a turn
    const audio = this.ring.read(seg.start, Math.min(seg.end, seg.lastSpeech + Math.round(0.3 * SR)));
    if (seg.purpose === 'langsel') this._languageReply(audio);
    else if (seg.purpose === 'postwake') this._postWake(audio, seg.origin);
    else this._translateTurn(audio);
  }

  // ───────────────────────── timers ─────────────────────────
  _tick() {
    if (this.state === S.OFF || this.state === S.ERROR) return;
    const now = performance.now();
    if (this.pendingWake && !this.seg && !this.busy && now > this.pendingWake.until) {
      this.pendingWake = null;
      if (this.state === S.COMMAND) this._setState(S.LISTENING); else this._refreshStatus();
    }
    if (this.state === S.LANGUAGE_SELECTION && !this.busy && !this.seg && !this.player.busy && now > this.langDeadline) {
      this._cancelLanguageSelection(true);   // FR-06 30 s command-reply timeout
      return;
    }
    if (this.state === S.LISTENING && !this.busy && !this.seg && !this.pendingWake && !this.player.busy &&
        now - this.lastHuman > this.T.inactivity_timeout * 1000) {
      this._goStandby();
    }
  }

  _goStandby() {
    this._closeSession();
    this.lastTranslation = null;       // FR-04: clear on return to standby
    this.seg = null; this.pendingWake = null;
    if (this.player && this.player.cues.shutdown) this.player.playCue('shutdown');
    this._setState(S.STANDBY);
  }

  _backToListening() {
    this.pendingWake = null; this.seg = null; this.lastHuman = performance.now();
    this._setState(S.LISTENING);
  }

  // ───────────────────────── cloud session ─────────────────────────
  _instructions(mode) {
    const [l1, l2] = this.pair, cl = this.cfg.command_language;
    const fill = (s) => s.replaceAll('{language_1}', l1).replaceAll('{language_2}', l2).replaceAll('{command_language}', cl).replaceAll('{mode}', mode);
    return fill(this.cfg.instructions_template) + '\n\n' + fill(this.cfg.mode_addenda[mode] || '');
  }

  _ensureSession() {
    if (this.rt && this.rt.open) return Promise.resolve(this.rt);
    if (this.rtConnecting) return this.rtConnecting;
    const gen = this.gen;
    this.rtConnecting = (async () => {
      this.ui.setCloud('connecting');
      const skip = [];   // models the Realtime socket rejected; the backend picks the next one
      for (let attempt = 0; attempt < 4; attempt++) {
        let r;
        try { r = await backendRequest('token', { device_id: this.deviceId, skip_models: skip }); }
        catch (e) { throw new NativeError('The app server did not respond. Is Streamlit still running?', 'network'); }
        if (!r.ok) throw new NativeError(r.error || 'Could not start the OpenAI session.', r.error_kind || 'api');
        if (gen !== this.gen) throw new NativeError('cancelled', 'cancelled');
        this.pair = [r.language_1, r.language_2]; this.ui.setPair(this.pair);
        const rt = new RealtimeClient({
          url: this.cfg.realtime_ws_url, model: r.model, token: r.token,
          onTraffic: (t) => { if (this.rt === rt) this.ui.setCloud(t === 'idle' ? 'connected' : t, r.model); },
          onClose: () => { if (this.rt === rt) { this.rt = null; this.ui.setCloud('off'); } },
        });
        try { await rt.connect(); }
        catch (e) {
          const msg = String(e.message || e);
          if (/model_not_found|model.{0,40}(not found|does not exist|not available|access)/i.test(msg)) {
            console.warn(`Realtime model ${r.model} unavailable, trying the next one`, msg);
            skip.push(r.model);
            continue;
          }
          if (/invalid_api_key|unauthorized|401/i.test(msg))
            throw new NativeError('OpenAI rejected the session credentials. Check OPENAI_API_KEY.', 'auth');
          throw new NativeError(`${msg}. Check the network connection.`, 'network');
        }
        if (gen !== this.gen) { rt.close(); throw new NativeError('cancelled', 'cancelled'); }
        this.rt = rt; this.ui.setCloud('connected', r.model);
        return rt;
      }
      throw new NativeError(`OpenAI could not find a Realtime model this account can use (tried ${skip.join(', ')}).`, 'model');
    })();
    this.rtConnecting.finally(() => { this.rtConnecting = null; }).catch(() => {});
    return this.rtConnecting;
  }

  _recover(err) {
    if (err && err.kind === 'cancelled') return;
    console.error(err);
    const gen = this.gen;
    this.busy = false; this.seg = null; this.pendingWake = null;
    this._closeSession();
    if (this.player) this.player.stopAll();
    this.ui.error(err.message || String(err));
    this._setState(S.ERROR, err.message || String(err));
    // recover to wake-word standby (mic stays on, cloud closed) after the message is visible
    setTimeout(() => { if (gen === this.gen && this.state === S.ERROR) { this.lastTranslation = null; this._setState(S.STANDBY); } }, 4000);
  }

  async _run(fn) {
    const gen = this.gen; this.busy = true;
    try { await fn(gen); }
    catch (e) { if (gen === this.gen) this._recover(e); }
    finally { if (gen === this.gen) this.busy = false; }
  }

  // ───────────────────────── interpretation ─────────────────────────
  _translateTurn(audio) {
    return this._run(async (gen) => {
      this._setState(S.TRANSLATING);
      this.player.playCue('stop');                 // end-of-utterance cue, once
      const rt = await this._ensureSession();
      if (gen !== this.gen) return;
      rt.clearConversation();
      await rt.sendUtterance(audio);
      await this._interpretCommitted(rt, gen);
    });
  }

  async _interpretCommitted(rt, gen) {
    const stream = this.player.startStream();
    let speaking = false;
    const res = await rt.respond(
      { output_modalities: ['audio'], instructions: this._instructions('INTERPRETATION') },
      { onAudio: (pcm) => { if (gen !== this.gen) return; if (!speaking) { speaking = true; this._setState(S.SPEAKING); } stream.push(pcm); } });
    if (gen !== this.gen) return;
    await stream.finish();
    rt.clearConversation();
    if (res.audio.length) this.lastTranslation = concatInt16(res.audio);   // exact audio for "repeat please"
    if (gen !== this.gen) return;
    await this.player.playCue('start');            // next speaker may talk
    this._backToListening();
  }

  // ───────────────────────── commands ─────────────────────────
  _postWake(audio, origin) {
    // From STANDBY a long post-wake utterance is ordinary speech: translate it directly.
    if (origin === 'standby' && audio.length / SR > 6) return this._translateTurn(audio);
    return this._run(async (gen) => {
      this._setState(S.COMMAND, 'Command…');
      const rt = await this._ensureSession();
      if (gen !== this.gen) return;
      rt.clearConversation();
      const itemId = await rt.sendUtterance(audio);
      const res = await rt.respond({
        output_modalities: ['text'], instructions: this._instructions('COMMAND'),
        tools: this.cfg.command_tools, tool_choice: 'required',
      });
      if (gen !== this.gen) return;
      const intent = (res.calls[0] && res.calls[0].name) || 'not_a_command';
      if (intent === 'choose_languages') { rt.clearConversation(); await this._startLanguageSelection(); }
      else if (intent === 'repeat_last_translation') { rt.clearConversation(); await this._repeatLastTranslation(); }
      else if (origin === 'standby') {
        // "Hey Native, <ordinary speech>" from standby → start interpreting with it
        rt.clearConversation([itemId]);
        this._setState(S.TRANSLATING);
        this.player.playCue('stop');
        await this._interpretCommitted(rt, gen);
      } else {
        rt.clearConversation();
        await this._say('Sorry, I can only choose languages or repeat the last translation.');
        this._backToListening();
      }
    });
  }

  // repeat_last_translation (§9)
  async _repeatLastTranslation() {
    if (!this.lastTranslation) {
      await this._say("There's nothing to repeat yet.");
      this._backToListening(); return;
    }
    this._setState(S.REPLAYING);
    await this.player.playPCM(this.lastTranslation, 24000);
    await this.player.playCue('start');
    this._backToListening();
  }

  async _startLanguageSelection() {
    this.langDeadline = Infinity;
    this._setState(S.LANGUAGE_SELECTION);
    await this._say('Which two languages would you like me to translate?');
    this.langDeadline = performance.now() + this.T.command_reply_timeout * 1000;
  }

  _languageReply(audio) {
    return this._run(async (gen) => {
      this._setState(S.LANGUAGE_SELECTION, 'Choosing languages…');
      const rt = await this._ensureSession();
      if (gen !== this.gen) return;
      rt.clearConversation();
      await rt.sendUtterance(audio);
      const res = await rt.respond({
        output_modalities: ['text'], instructions: this._instructions('LANGUAGE_SELECTION'),
        tools: this.cfg.language_tools, tool_choice: 'required',
      });
      rt.clearConversation();
      if (gen !== this.gen) return;
      const call = res.calls[0];
      const again = async (text) => {
        await this._say(text);
        this._setState(S.LANGUAGE_SELECTION);
        this.langDeadline = performance.now() + this.T.command_reply_timeout * 1000;
      };
      if (!call) return again('Sorry, which two languages would you like me to translate?');
      if (call.name === 'cancel_language_selection') return this._cancelLanguageSelection(false);
      if (call.name === 'ask_clarification') return again(call.args.question || 'Which two languages would you like me to translate?');
      if (call.name === 'set_languages') {
        const r = await this._setLanguages(call.args.language_1, call.args.language_2);
        if (gen !== this.gen) return;
        if (!r.ok) {
          const ask = r.reason === 'ambiguous' ? r.message : `${r.message} Which two languages would you like me to translate?`;
          return again(ask);
        }
        await this._say(`Okay, I'll translate between ${this.pair[0]} and ${this.pair[1]}.`);
        await this.player.playCue('start');
        this._backToListening();
      }
    });
  }

  // set_languages (§9): backend validates + atomically persists; only then do we switch.
  async _setLanguages(l1, l2) {
    let r;
    try { r = await backendRequest('set_languages', { device_id: this.deviceId, language_1: l1 || '', language_2: l2 || '' }); }
    catch (e) { return { ok: false, message: "Sorry, I couldn't save that right now." }; }
    if (r.ok) {
      this.pair = [r.language_1, r.language_2];
      this.ui.setPair(this.pair);
      this.lastTranslation = null;    // FR-04: clear repeat cache on a language change
      try { this.rt && this.rt.open && this.rt.updateSession({ instructions: this._instructions('INTERPRETATION') }); } catch {}
    }
    return r;
  }

  async _cancelLanguageSelection(timedOut) {
    await this._run(async () => {
      await this._say(timedOut
        ? `Language selection cancelled. Still translating between ${this.pair[0]} and ${this.pair[1]}.`
        : `Okay, I'll keep translating between ${this.pair[0]} and ${this.pair[1]}.`);
      this._backToListening();
    });
  }

  async _say(text) {
    this.ui.prompt(text);
    await this.player.say(text, 'en-US');
  }

  // ───────────────────────── status ─────────────────────────
  _setState(s, detail) {
    this.state = s; this.detail = detail || '';
    (this.history = this.history || []).push([Math.round(performance.now()), s]);
    if (this.history.length > 200) this.history.shift();
    this._refreshStatus();
  }

  _refreshStatus() {
    const s = this.state;
    let text = {
      OFF: 'Off', STANDBY: 'Standby — Say “Hey Native.”', ACTIVATING: 'Activating…', LISTENING: 'Listening',
      TRANSLATING: 'Translating…', SPEAKING: 'Speaking', COMMAND: 'Command', LANGUAGE_SELECTION: 'Choosing languages',
      REPLAYING: 'Replaying', ERROR: 'Error',
    }[s];
    if (this.detail) text = s === S.ERROR ? `Error — ${this.detail}` : this.detail;
    if (s === S.LISTENING) {
      if (this.seg && this.seg.speaking) text = 'User speaking';
      else if (this.pendingWake) text = 'Listening — say a command or start speaking';
    }
    if (s === S.LANGUAGE_SELECTION && this.seg && this.seg.speaking && !this.busy) text = 'Choosing languages — listening…';
    const mic = s === S.OFF ? 'off' : s === S.STANDBY ? 'standby' : (s === S.ERROR ? 'standby' : 'active');
    this.ui.setStatus(s, text, mic);
  }
}
