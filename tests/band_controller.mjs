// Run: node tests/band_controller.mjs
import assert from 'node:assert/strict';
globalThis.location={href:'http://localhost/'};
globalThis.window={addEventListener(){},ort:{env:{wasm:{}}}};
globalThis.localStorage={getItem(){return 'band_test_device';}};
const { NativeController, S } = await import('../native_component/frontend/js/controller.js');
const ui={error(){},setStatus(){},setCloud(){}};
const cfg={activation_mode:'button',default_pair:['English','Vietnamese'],timing:{},thresholds:{}};
const ctl=new NativeController(cfg,ui);
await ctl.preload();
assert.deepEqual(await ctl.wake.process(new Float32Array(512)),[]);
let stopped=0;ctl.deactivate=()=>stopped++;
ctl._goStandby();assert.equal(stopped,1,'idle button mode must stop microphone');
const error=console.error;console.error=()=>{};
ctl._recover(new Error('network failed'));console.error=error;
assert.equal(stopped,2,'failed live session must stop microphone');
assert.equal(ctl._canStartSegment(),false);
ctl.state=S.LISTENING;assert.equal(ctl._canStartSegment(),true);
console.log('PASS: no wake dependency; idle/error shut down; listening accepts speech');
