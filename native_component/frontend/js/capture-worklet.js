// AudioWorklet: mono mic capture, anti-aliased decimation to 16 kHz, 512-sample chunks.
// Works at any device rate (44.1k, 48k, …) so we never depend on the browser's
// support for non-native AudioContext sample rates.
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0; this.acc = 0; this.cnt = 0;
    this.out = new Float32Array(512); this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i]; this.cnt++; this.pos += 1;
      if (this.pos >= this.ratio) {           // box-filter average over each output period
        this.pos -= this.ratio;
        this.out[this.n++] = this.acc / this.cnt;
        this.acc = 0; this.cnt = 0;
        if (this.n === 512) { this.port.postMessage(this.out, [this.out.buffer]); this.out = new Float32Array(512); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor('native-capture', CaptureProcessor);
