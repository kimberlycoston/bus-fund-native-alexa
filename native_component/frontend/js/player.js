// Output audio: cue sounds, streamed 24 kHz PCM translations, exact replay, and
// spoken command prompts. Everything is scheduled on one timeline so cues, prompts
// and translations never overlap (FR-07).

export function trimSilence(ctx, buf, thresh = 0.01, padSec = 0.03) {
  const n = buf.length, chs = buf.numberOfChannels;
  let start = n, end = 0;
  for (let c = 0; c < chs; c++) {
    const d = buf.getChannelData(c);
    for (let i = 0; i < n; i++) if (Math.abs(d[i]) > thresh) { start = Math.min(start, i); break; }
    for (let i = n - 1; i >= 0; i--) if (Math.abs(d[i]) > thresh) { end = Math.max(end, i); break; }
  }
  if (start >= end) return buf;
  const pad = Math.floor(padSec * buf.sampleRate);
  start = Math.max(0, start - pad); end = Math.min(n, end + pad);
  const out = ctx.createBuffer(chs, end - start, buf.sampleRate);
  for (let c = 0; c < chs; c++) out.copyToChannel(buf.getChannelData(c).slice(start, end), c);
  return out;
}

export class Player {
  constructor() {
    const AC = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AC();            // created inside the Activate click → autoplay unlocked
    this.cues = {};
    this.sources = new Set();
    this.nextTime = 0;
    this.onActivity = () => {};     // called with true/false when Native starts/stops making sound
    this._speaking = false;
  }
  async unlock() { if (this.ctx.state !== 'running') await this.ctx.resume(); }

  async loadCue(name, url, trim) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error(`the file ${url} could not be fetched (HTTP ${r.status})`);
    const type = r.headers.get('content-type') || '';
    if (/text\/html/i.test(type)) throw new Error(`the server returned a web page instead of ${url}`);
    const data = await r.arrayBuffer();
    let buf;
    try {
      // Safari still prefers the callback form of decodeAudioData
      buf = await new Promise((res, rej) => {
        const p = this.ctx.decodeAudioData(data, res, rej);
        if (p && p.then) p.then(res, rej);
      });
    } catch (e) {
      throw new Error(`this browser could not decode ${url} (${data.byteLength} bytes, ${type || 'unknown type'})`);
    }
    if (trim) buf = trimSilence(this.ctx, buf);
    this.cues[name] = buf;
  }

  /** Short two-note chime used only if a supplied cue file can't be decoded. */
  synthCue(name) {
    const sr = this.ctx.sampleRate, dur = 0.32, n = Math.floor(sr * dur);
    const b = this.ctx.createBuffer(1, n, sr), d = b.getChannelData(0);
    const [f1, f2] = name === 'stop' ? [880, 587] : [587, 880];   // start rises, stop falls
    for (let i = 0; i < n; i++) {
      const t = i / sr, f = t < dur / 2 ? f1 : f2;
      const env = Math.min(1, t / 0.01) * Math.min(1, (dur - t) / 0.06);
      d[i] = 0.25 * env * Math.sin(2 * Math.PI * f * t);
    }
    this.cues[name] = b;
  }

  get busy() { return this.sources.size > 0 || this._speaking; }

  _notify() { this.onActivity(this.busy); }

  /** Schedule a buffer on the shared timeline; resolves when it finishes. */
  _schedule(buffer) {
    const src = this.ctx.createBufferSource();
    src.buffer = buffer; src.connect(this.ctx.destination);
    const t = Math.max(this.ctx.currentTime + 0.02, this.nextTime);
    this.nextTime = t + buffer.duration;
    this.sources.add(src); this._notify();
    return new Promise((resolve) => {
      src.onended = () => { this.sources.delete(src); this._notify(); resolve(); };
      src.start(t);
    });
  }

  playCue(name) {
    const b = this.cues[name];
    return b ? this._schedule(b) : Promise.resolve();
  }

  pcmToBuffer(int16, rate = 24000) {
    const b = this.ctx.createBuffer(1, Math.max(1, int16.length), rate);
    const d = b.getChannelData(0);
    for (let i = 0; i < int16.length; i++) d[i] = int16[i] / 32768;
    return b;
  }

  playPCM(int16, rate = 24000) { return this._schedule(this.pcmToBuffer(int16, rate)); }

  /** Streamed translation: push chunks as they arrive; `finish()` resolves after the last plays. */
  startStream(rate = 24000, prebufferSec = 0.25) {
    const self = this; let queued = []; let queuedLen = 0; let started = false; const tails = [];
    const flush = () => {
      if (!queuedLen) return;
      const all = new Int16Array(queuedLen); let o = 0;
      for (const q of queued) { all.set(q, o); o += q.length; }
      queued = []; queuedLen = 0;
      tails.push(self.playPCM(all, rate));
    };
    return {
      push(int16) {
        queued.push(int16); queuedLen += int16.length;
        if (started || queuedLen >= prebufferSec * rate) { started = true; flush(); }
      },
      async finish() { flush(); await Promise.all(tails); },
    };
  }

  /** Spoken command prompt in the command-interface language (browser TTS). */
  say(text, lang = 'en-US') {
    const synth = window.speechSynthesis;
    if (!synth || !text) return Promise.resolve();
    // wait for anything already scheduled so prompts never overlap cues/translations
    const waitMs = Math.max(0, (this.nextTime - this.ctx.currentTime) * 1000);
    return new Promise((resolve) => {
      setTimeout(() => {
        const u = new SpeechSynthesisUtterance(text);
        u.lang = lang; u.rate = 1.0;
        const v = synth.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()) && /natural|google|samantha|aria|jenny/i.test(v.name))
          || synth.getVoices().find(v => v.lang && v.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()));
        if (v) u.voice = v;
        let done = false;
        const end = () => { if (done) return; done = true; this._speaking = false; this._notify(); resolve(); };
        u.onend = end; u.onerror = end;
        setTimeout(end, 2500 + text.length * 90);   // Chrome sometimes never fires onend
        this._speaking = true; this._notify();
        synth.cancel(); synth.speak(u);
      }, waitMs);
    });
  }

  stopAll() {
    for (const s of this.sources) { try { s.onended = null; s.stop(); } catch {} }
    this.sources.clear(); this.nextTime = 0;
    try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch {}
    this._speaking = false; this._notify();
  }

  async close() { this.stopAll(); try { await this.ctx.close(); } catch {} }
}
