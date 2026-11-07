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

// Band prompts stream through the existing Realtime session rather than browser TTS.
const voiced=new NativeController(cfg,{...ui,prompt(){}});
let request,finished=false;const chunks=[];const cached=new Int16Array([123]);voiced.lastTranslation=cached;
voiced.player={say(){assert.fail('band prompts must not use browser speech synthesis');},startStream(){return {push:pcm=>chunks.push(pcm),finish:async()=>{finished=true;}};}};
voiced._ensureSession=async()=>({respond:async(params,{onAudio})=>{request=params;onAudio(new Int16Array([1,2]));}});
await voiced._say('Which two languages would you like me to translate?');
assert.equal(request.conversation,'none');
assert.deepEqual(request.output_modalities,['audio']);
assert.match(request.instructions,/Which two languages/);
assert.equal(chunks.length,1);assert.equal(finished,true);
assert.equal(voiced.lastTranslation,cached,'spoken prompts must not replace translation replay');
console.log('PASS: prompts use interpretation session audio, finish playback, and preserve replay');

// Lisans Portal: each interpreted turn hands the UI the translation plus the source-language transcript.
const synced=new NativeController(cfg,{...ui,translation(text,pair,source){synced.__seen={text,pair,source};}});
let cleared=0;
const srt={respond:async(_p,{onAudio})=>{onAudio(new Int16Array([5]));return {audio:[new Int16Array([5])],transcript:'My chest feels tight.'};},
  inputTranscript:async(id)=>id==='item_u1'?'Tôi bị tức ngực.':null,clearConversation(){cleared++;}};
synced.player={startStream(){return {push(){},finish:async()=>{}};},playCue:async()=>{}};
synced._backToListening=()=>{};synced._instructions=()=>'INTERPRETATION';
await synced._interpretCommitted(srt,synced.gen,'item_u1');
assert.equal(synced.__seen.text,'My chest feels tight.');
assert.equal(await synced.__seen.source,'Tôi bị tức ngực.');
assert.equal(cleared,1,'input item is cleared only after its transcript resolved');
console.log('PASS: interpretation passes original speech + translation to the UI for the Lisans Portal');
