// Browser port of the openWakeWord streaming pipeline (openwakeword/utils.py AudioFeatures
// + model.py predict). 16 kHz int16-scaled audio → melspectrogram.onnx (x/10+2)
// → embedding_model.onnx over 76-frame windows every 8 frames → wake classifier on
// the last 16 embeddings. Runs entirely in the browser: standby audio never leaves it.

const FRAME = 1280;          // 80 ms @ 16 kHz, openWakeWord's step
const MEL_CONTEXT = 160 * 3; // extra samples openWakeWord prepends for each melspec call
const MEL_WINDOW = 76;
const N_EMB = 16;

export class WakeWordEngine {
  static async create(ort, { melUrl, embUrl, wakeUrl }) {
    const opts = { executionProviders: ['wasm'], graphOptimizationLevel: 'all' };
    const [mel, emb, wake] = await Promise.all([
      ort.InferenceSession.create(melUrl, opts),
      ort.InferenceSession.create(embUrl, opts),
      ort.InferenceSession.create(wakeUrl, opts),
    ]);
    const eng = new WakeWordEngine(ort, mel, emb, wake);
    const dims = wake.inputNames.length === 1 ? null : 'bad';
    if (dims) throw new Error('Wake-word model must have exactly one input');
    await eng.reset();
    return eng;
  }

  constructor(ort, mel, emb, wake) {
    this.ort = ort; this.mel = mel; this.emb = emb; this.wake = wake;
    this.melIn = mel.inputNames[0]; this.embIn = emb.inputNames[0]; this.wakeIn = wake.inputNames[0];
  }

  async _melspec(samples /* Float32Array, int16-scaled */) {
    const out = await this.mel.run({ [this.melIn]: new this.ort.Tensor('float32', samples, [1, samples.length]) });
    const t = out[this.mel.outputNames[0]];
    const d = t.data; const nFrames = d.length / 32; const frames = [];
    for (let i = 0; i < nFrames; i++) {
      const f = new Float32Array(32);
      for (let j = 0; j < 32; j++) f[j] = d[i * 32 + j] / 10 + 2;
      frames.push(f);
    }
    return frames;
  }

  async _embed(melFrames /* 76 × Float32Array(32) */) {
    const buf = new Float32Array(MEL_WINDOW * 32);
    for (let i = 0; i < MEL_WINDOW; i++) buf.set(melFrames[i], i * 32);
    const out = await this.emb.run({ [this.embIn]: new this.ort.Tensor('float32', buf, [1, MEL_WINDOW, 32, 1]) });
    return Float32Array.from(out[this.emb.outputNames[0]].data);
  }

  /** Reset all streaming state (as at model start). */
  async reset() {
    this.raw = new Float32Array(FRAME + MEL_CONTEXT); // rolling raw window, zero-filled
    this.pending = [];                                 // samples not yet consumed (< FRAME)
    this.pendingLen = 0;
    this.melBuf = Array.from({ length: MEL_WINDOW }, () => new Float32Array(32).fill(1));
    if (!this._zeroEmb) {
      const zeros = new Float32Array(MEL_CONTEXT + 160 * MEL_WINDOW); // → exactly 76 mel frames
      this._zeroEmb = await this._embed(await this._melspec(zeros));
    }
    this.embBuf = Array.from({ length: N_EMB }, () => this._zeroEmb);
    this.nPredictions = 0;
    this.lastScore = 0;
  }

  /**
   * Feed audio (Float32Array in [-1, 1] at 16 kHz, any length). Returns an array of
   * scores, one per completed 80 ms frame (usually 0 or 1 entries).
   */
  async process(chunk) {
    this.pending.push(chunk); this.pendingLen += chunk.length;
    const scores = [];
    while (this.pendingLen >= FRAME) {
      const frame = this._take(FRAME);
      scores.push(await this._processFrame(frame));
    }
    return scores;
  }

  _take(n) {
    const out = new Float32Array(n); let o = 0;
    while (o < n) {
      const head = this.pending[0]; const need = n - o;
      if (head.length <= need) { out.set(head, o); o += head.length; this.pending.shift(); }
      else { out.set(head.subarray(0, need), o); this.pending[0] = head.subarray(need); o += need; }
    }
    this.pendingLen -= n;
    return out;
  }

  async _processFrame(frame) {
    // int16 scaling exactly as openWakeWord expects (it feeds int16 values as float32)
    const r = this.raw; r.copyWithin(0, FRAME);
    for (let i = 0; i < FRAME; i++) {
      r[MEL_CONTEXT + i] = Math.max(-32768, Math.min(32767, Math.trunc(frame[i] * 32768)));
    }
    const mel = await this._melspec(r.slice());
    for (const f of mel) this.melBuf.push(f);
    if (this.melBuf.length > MEL_WINDOW) this.melBuf.splice(0, this.melBuf.length - MEL_WINDOW);
    this.embBuf.push(await this._embed(this.melBuf));
    if (this.embBuf.length > N_EMB) this.embBuf.shift();

    const feat = new Float32Array(N_EMB * 96);
    for (let i = 0; i < N_EMB; i++) feat.set(this.embBuf[i], i * 96);
    const out = await this.wake.run({ [this.wakeIn]: new this.ort.Tensor('float32', feat, [1, N_EMB, 96]) });
    let score = out[this.wake.outputNames[0]].data[0];
    // openWakeWord zeroes the first 5 predictions while its buffers fill
    if (this.nPredictions++ < 5) score = 0;
    this.lastScore = score;
    return score;
  }
}
