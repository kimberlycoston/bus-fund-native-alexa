// OpenAI Realtime API over WebSocket, authenticated with a short-lived client secret
// minted by the Python backend (the real API key never reaches the browser).
// Turn detection is disabled: the application owns segmentation and sends one
// completed utterance at a time, then asks for one response in an explicit mode.

function b64FromInt16(int16) {
  const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
function int16FromB64(b64) {
  const s = atob(b64); const bytes = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) bytes[i] = s.charCodeAt(i);
  return new Int16Array(bytes.buffer, 0, bytes.length >> 1);
}

/** 16 kHz float → 24 kHz int16 (linear interpolation). */
export function to24kPCM(f16) {
  const outLen = Math.floor(f16.length * 1.5); const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const x = i / 1.5, i0 = Math.floor(x), i1 = Math.min(i0 + 1, f16.length - 1), t = x - i0;
    const v = f16[i0] * (1 - t) + f16[i1] * t;
    out[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
  }
  return out;
}

export class RealtimeClient {
  constructor({ url, model, token, onClose, onTraffic }) {
    this.url = url; this.model = model; this.token = token;
    this.onClose = onClose || (() => {}); this.onTraffic = onTraffic || (() => {});
    this.ws = null; this.waiters = new Set(); this.items = new Set(); this.seq = 0; this.closedByUs = false;
  }

  connect(timeoutMs = 10000) {
    return new Promise((resolve, reject) => {
      const u = `${this.url}?model=${encodeURIComponent(this.model)}`;
      let settled = false;
      try {
        this.ws = new WebSocket(u, ['realtime', 'openai-insecure-api-key.' + this.token]);
      } catch (e) { reject(e); return; }
      const t = setTimeout(() => { if (!settled) { settled = true; try { this.ws.close(); } catch {} reject(new Error('Timed out connecting to OpenAI')); } }, timeoutMs);
      this.ws.onmessage = (m) => this._onMessage(m);
      this.ws.onerror = () => { if (!settled) { settled = true; clearTimeout(t); reject(new Error('Could not connect to OpenAI Realtime')); } };
      this.ws.onclose = (ev) => {
        const err = new Error(`OpenAI session closed${ev.reason ? ': ' + ev.reason : ''}`);
        for (const w of this.waiters) w.reject(err);
        this.waiters.clear();
        if (!settled) { settled = true; clearTimeout(t); reject(err); }
        if (!this.closedByUs) this.onClose(ev);
      };
      // resolve on session.created so we know auth succeeded
      this.waitFor(ev => ev.type === 'session.created', timeoutMs).then(() => {
        if (!settled) { settled = true; clearTimeout(t); resolve(); }
      }, () => {});
    });
  }

  get open() { return this.ws && this.ws.readyState === WebSocket.OPEN; }

  send(ev) {
    if (!this.open) throw new Error('OpenAI session is not connected');
    ev.event_id = ev.event_id || `evt_${Date.now().toString(36)}_${this.seq++}`;
    this.ws.send(JSON.stringify(ev));
    return ev.event_id;
  }

  _onMessage(m) {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    if (ev.type === 'conversation.item.added' || ev.type === 'conversation.item.created' || ev.type === 'conversation.item.done') {
      if (ev.item && ev.item.id) this.items.add(ev.item.id);
    }
    if (ev.type === 'error') {
      const eid = ev.error && ev.error.event_id;
      if (eid && eid.startsWith('del_')) return;            // deleting an already-gone item: harmless
      if (ev.error && /not\s*found/i.test(ev.error.message || '') && ev.error.code === 'item_not_found') return;
    }
    for (const w of [...this.waiters]) {
      if (ev.type === 'error' && w.failOnError) { this.waiters.delete(w); w.reject(new Error((ev.error && ev.error.message) || 'OpenAI error')); continue; }
      if (w.match(ev)) { this.waiters.delete(w); w.resolve(ev); }
    }
    if (this._onEvent) this._onEvent(ev);
  }

  waitFor(match, timeoutMs = 30000, failOnError = true) {
    return new Promise((resolve, reject) => {
      const w = { match, failOnError, resolve: (e) => { clearTimeout(w.t); resolve(e); }, reject: (e) => { clearTimeout(w.t); reject(e); } };
      w.t = setTimeout(() => { this.waiters.delete(w); reject(new Error('OpenAI did not respond in time')); }, timeoutMs);
      this.waiters.add(w);
    });
  }

  updateSession(session) { this.send({ type: 'session.update', session: { type: 'realtime', ...session } }); }

  /** Upload one completed utterance (16 kHz float). Resolves with the new item id. */
  async sendUtterance(f16) {
    const pcm = to24kPCM(f16);
    this.onTraffic('sending');
    try {
      this.send({ type: 'input_audio_buffer.clear' });
      const step = 24000; // 1 s of audio per append event
      for (let i = 0; i < pcm.length; i += step) {
        this.send({ type: 'input_audio_buffer.append', audio: b64FromInt16(pcm.subarray(i, i + step)) });
      }
      const committed = this.waitFor(e => e.type === 'input_audio_buffer.committed', 15000);
      this.send({ type: 'input_audio_buffer.commit' });
      const ev = await committed;
      if (ev.item_id) this.items.add(ev.item_id);
      return ev.item_id;
    } finally { this.onTraffic('idle'); }
  }

  /**
   * Request one response. onAudio(int16) receives streamed audio.
   * Resolves { response, audio: Int16Array[], transcript, calls: [{name, args}] }.
   */
  async respond(responseParams, { onAudio, timeoutMs = 45000 } = {}) {
    const audio = []; let transcript = '';
    const onEvt = (ev) => {
      if (ev.type === 'response.output_audio.delta' || ev.type === 'response.audio.delta') {
        const pcm = int16FromB64(ev.delta); audio.push(pcm); this.onTraffic('receiving');
        if (onAudio) onAudio(pcm);
      } else if (ev.type === 'response.output_audio_transcript.delta' || ev.type === 'response.audio_transcript.delta') {
        transcript += ev.delta || '';
      }
    };
    this._onEvent = onEvt;
    try {
      const done = this.waitFor(e => e.type === 'response.done', timeoutMs);
      this.send({ type: 'response.create', response: responseParams });
      const ev = await done;
      const resp = ev.response || {};
      const calls = [];
      for (const it of resp.output || []) {
        if (it.id) this.items.add(it.id);
        if (it.type === 'function_call') {
          let args = {}; try { args = JSON.parse(it.arguments || '{}'); } catch {}
          calls.push({ name: it.name, args, call_id: it.call_id });
        }
      }
      if (resp.status && resp.status !== 'completed') {
        const why = (resp.status_details && (resp.status_details.error?.message || resp.status_details.reason)) || resp.status;
        if (resp.status === 'failed') throw new Error(`OpenAI response failed: ${why}`);
      }
      return { response: resp, audio, transcript, calls };
    } finally { this._onEvent = null; this.onTraffic('idle'); }
  }

  /** Forget everything from the last turn so each utterance is interpreted on its own. */
  clearConversation(keep = []) {
    if (!this.open) return;
    for (const id of [...this.items]) {
      if (keep.includes(id)) continue;
      try { this.send({ type: 'conversation.item.delete', item_id: id, event_id: `del_${id}_${this.seq++}` }); } catch {}
      this.items.delete(id);
    }
  }

  close() {
    this.closedByUs = true;
    for (const w of this.waiters) w.reject(new Error('Session closed'));
    this.waiters.clear();
    try { this.ws && this.ws.close(1000, 'client closing'); } catch {}
  }
}
