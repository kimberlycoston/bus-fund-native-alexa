// Verifies the browser wake-word pipeline (js/wakeword.js) against the reference Python
// openWakeWord implementation. Usage:
//   node tools/wakeword_parity.mjs <ort-web dist dir> <frontend dir> <wake.onnx> <in.wav>...
// Prints per-file max score and per-frame scores as JSON for comparison.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const [ortDir, feDir, wakePath, ...wavs] = process.argv.slice(2);
const require = createRequire(import.meta.url);
const ort = require(path.join(ortDir, 'ort.node.min.js'));
ort.env.wasm.numThreads = 1;
const { WakeWordEngine } = await import(path.join(feDir, 'js', 'wakeword.js'));
const { SileroVAD } = await import(path.join(feDir, 'js', 'vad.js'));

const buf = p => { const b = fs.readFileSync(p); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };
function readWav16(p) {
  const b = fs.readFileSync(p); let off = 12, data = null;
  while (off < b.length) {
    const id = b.toString('ascii', off, off + 4), size = b.readUInt32LE(off + 4);
    if (id === 'data') { data = b.subarray(off + 8, off + 8 + size); break; }
    off += 8 + size;
  }
  const n = data.length / 2, f = new Float32Array(n);
  for (let i = 0; i < n; i++) f[i] = data.readInt16LE(i * 2) / 32768;
  return f;
}

const eng = await WakeWordEngine.create(ort, {
  melUrl: buf(path.join(feDir, 'vendor', 'melspectrogram.onnx')),
  embUrl: buf(path.join(feDir, 'vendor', 'embedding_model.onnx')),
  wakeUrl: buf(wakePath),
});
const vad = await SileroVAD.create(ort, buf(path.join(feDir, 'vendor', 'silero_vad.onnx')));
const result = {};
for (const w of wavs) {
  await eng.reset(); vad.reset();
  const x = readWav16(w); const scores = []; let vmax = 0;
  for (let i = 0; i + 512 <= x.length; i += 512) {
    const c = x.subarray(i, i + 512);
    vmax = Math.max(vmax, await vad.process(c));
    scores.push(...await eng.process(c));
  }
  result[path.basename(w)] = { max: Math.max(...scores), scores, vadMax: vmax };
}
console.log(JSON.stringify(result));
