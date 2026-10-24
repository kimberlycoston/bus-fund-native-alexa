// Silero VAD (v4 ONNX, as bundled with openWakeWord) at 16 kHz, 512-sample frames.
// Falls back to an adaptive energy detector if the model cannot be loaded.

export class SileroVAD {
  static async create(ort, url) {
    const s = await ort.InferenceSession.create(url, { executionProviders: ['wasm'] });
    return new SileroVAD(ort, s);
  }
  constructor(ort, session) {
    this.ort = ort; this.s = session; this.kind = 'silero';
    this.sr = new ort.Tensor('int64', BigInt64Array.from([16000n]), []);
    this.reset();
  }
  reset() {
    this.h = new this.ort.Tensor('float32', new Float32Array(128), [2, 1, 64]);
    this.c = new this.ort.Tensor('float32', new Float32Array(128), [2, 1, 64]);
  }
  /** frame: Float32Array(512) in [-1, 1]. Returns speech probability. */
  async process(frame) {
    const out = await this.s.run({
      input: new this.ort.Tensor('float32', frame, [1, frame.length]), sr: this.sr, h: this.h, c: this.c,
    });
    this.h = out.hn; this.c = out.cn;
    return out.output.data[0];
  }
}

export class EnergyVAD {
  constructor() { this.kind = 'energy'; this.reset(); }
  reset() { this.noise = 0.003; }
  async process(frame) {
    let e = 0; for (let i = 0; i < frame.length; i++) e += frame[i] * frame[i];
    const rms = Math.sqrt(e / frame.length);
    // slow-tracking noise floor; speech ≈ 4× above floor and above an absolute minimum
    this.noise = rms < this.noise ? 0.9 * this.noise + 0.1 * rms : 0.999 * this.noise + 0.001 * rms;
    const ratio = rms / Math.max(this.noise, 1e-4);
    return rms > 0.01 && ratio > 4 ? Math.min(1, ratio / 8) : 0;
  }
}
