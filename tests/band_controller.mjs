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

// Every band utterance is classified before translation. Language replies bypass classification.
const routing=new NativeController({...cfg,timing:{min_speech:.1}},ui);
routing.ring={read:()=>new Float32Array(16000)};
let route;
routing._postWake=(_,origin)=>route=origin;
routing._translateTurn=()=>route='translation';
routing._languageReply=()=>route='languages';
routing.seg={speech:16000,start:0,end:16000,lastSpeech:16000,purpose:'utterance'};
routing._finalize();assert.equal(route,'button');
routing.seg={speech:16000,start:0,end:16000,lastSpeech:16000,purpose:'langsel'};
routing._finalize();assert.equal(route,'languages');

for(const intent of ['choose_languages','repeat_last_translation','not_a_command']) {
 const c=new NativeController(cfg,ui);let outcome,uploads=0;
 const rt={clearConversation(){},sendUtterance:async()=>{uploads++;return 'input1';},respond:async()=>({calls:[{name:intent}]})};
 c._ensureSession=async()=>rt;
 c._startLanguageSelection=async()=>outcome='choose';
 c._repeatLastTranslation=async()=>outcome='repeat';
 c._interpretCommitted=async()=>outcome='translate';
 c.player={playCue(){}};
 await c._postWake(new Float32Array(16000),'button');
 assert.equal(outcome,{choose_languages:'choose',repeat_last_translation:'repeat',not_a_command:'translate'}[intent]);
 assert.equal(uploads,1,'ordinary speech reuses original audio rather than recording it again');
}
assert.match(routing._instructions('COMMAND'),/No wake phrase is required/);
console.log('PASS: choose/repeat route to commands; ordinary speech translates; language replies bypass commands');
