import { NativeController, S } from './controller.js';
import { Streamlit, backendRequest } from './streamlit.js';
export function mountBand(cfg) {
  document.querySelector('link[data-band]')?.remove();
  const css=document.createElement('link'); css.rel='stylesheet';css.href='band.css';css.dataset.band='';document.head.append(css);
  document.body.className='band-app';
  document.body.innerHTML=`<main class="band-shell">
    <header class="brand"><a href="#" aria-label="Native Lisans home"><img class="brand-logo" src="assets/native-lisans-logo.png" alt=""> native <b>lisans</b></a></header>
    <section class="intro"><div class="eyebrow">INTERPRETATION</div><h1>Lisans Band</h1><p>Two-way interpretation for bedside conversations.</p></section>
    <div class="workspace"><section class="product" aria-label="Interactive Lisans band">
      <div class="device-stage" id="stage" data-state="OFF"><div class="halo"></div><div class="strap"><i></i><i></i><i></i><i></i></div><div class="pod"><div class="pod-top"><span>NATIVE</span><span class="led"></span></div><button id="band-button" aria-label="Start interpretation" aria-pressed="false"><span class="button-glyph">↔</span></button><div class="speaker">···············</div><div class="pod-label">LISANS</div></div></div>
      <div class="device-copy"><div class="state-label" id="status" role="status" aria-live="polite">Ready when you are</div><p id="hint">Press the band to start interpreting.</p><div class="wave" aria-hidden="true">${'<i></i>'.repeat(19)}</div></div>

    </section>
    <aside class="conversation"><div class="session-heading"><div><div class="eyebrow">CONVERSATION</div><h2>Conversation transcript</h2><div class="assigned" id="assigned"></div></div><span class="live-dot" id="connection">Offline</span></div>
      <div class="assignment"><label>Staff language<select id="staff"></select></label><span>↔</span><label>Patient language<select id="patient"></select></label><button id="apply">Set languages</button></div><button id="use-patient-lang" class="use-lang" hidden></button>
      <div id="error" role="alert"></div><div class="transcript" id="transcript" aria-live="polite"><div class="empty" id="empty"><span>“</span><h3>No exchanges yet</h3><p>Original speech and interpretation appear here as you speak.</p></div></div>
      <div class="session-actions"><button id="repeat" disabled>↻ Replay last translation</button><button id="clear">Clear display</button></div>
      <div class="session-footer"><span id="turns">0 exchanges</span><span id="elapsed">00:00</span></div>
    </aside></div><footer class="footnote"></footer>
  </main>`;
  const $=id=>document.getElementById(id); let ctl, count=0, started=0, lastState=S.OFF, convId=null, convPortal=null;
  // Lisans Portal link: which band this is and which patient wears it (set on the Streamlit page; latest render wins).
  const portal=()=>(Streamlit.args&&Streamlit.args.config&&Streamlit.args.config.portal)||{};
  const uid=()=>{try{return crypto.randomUUID().replace(/-/g,'');}catch{return 'c'+Date.now().toString(36)+Math.random().toString(36).slice(2,10);}};
  const showAssigned=()=>{const p=portal();$('assigned').textContent=p.band_id?`Band ${p.band_id} · ${p.patient_label||'Not assigned to a patient'}`:'';
    // Offer the patient's preferred language from the Portal (only while stopped, only if it differs).
    const lang=p.patient_language, use=$('use-patient-lang');
    const show=!!(lang&&ctl&&ctl.state===S.OFF&&ctl.pair[1]!==lang&&cfg.supported_languages.includes(lang));
    use.hidden=!show; if(show)use.textContent=`Use patient’s language (${lang})`;};
  Streamlit.onRender(showAssigned);
  const portalSend=(type,payload)=>backendRequest(type,payload).catch(e=>console.warn('Lisans Portal sync failed',e));
  function conversationChange(on){
    if(on&&!convId){convId=uid();convPortal={...portal()};portalSend('portal_session',{event:'start',conversation_id:convId,band_id:convPortal.band_id,patient_id:convPortal.patient_id,language_1:ctl?.pair[0],language_2:ctl?.pair[1]});}
    else if(!on&&convId){portalSend('portal_session',{event:'end',conversation_id:convId});convId=null;convPortal=null;}
  }
  const ui={
    setStatus(state,text){lastState=state;$('stage').dataset.state=state;const on=state!==S.OFF;$('band-button').setAttribute('aria-pressed',String(on));$('band-button').setAttribute('aria-label',on?'Stop interpretation':'Start interpretation');$('status').textContent=({OFF:'Ready when you are',ACTIVATING:'Connecting…',LISTENING:'Listening to you',TRANSLATING:'Finding the words…',SPEAKING:'Speaking your language',REPLAYING:'Playing it again',COMMAND:'Checking voice command…',LANGUAGE_SELECTION:'Choosing languages'})[state]||text;$('hint').textContent=on?'Speak naturally, or say “choose languages.” Press again to end.':'Press the band to start interpreting.';if($('mic')) $('mic').textContent=on?'Microphone active':'Microphone off';$('staff').disabled=on;$('patient').disabled=on;$('apply').disabled=on;$('repeat').disabled=!on||!ctl?.lastTranslation||ctl?.busy;document.querySelector('.wave').classList.toggle('active',on);if(on&&!started)started=Date.now();if(!on)started=0;conversationChange(on);showAssigned();resize();},
    setPair(pair){$('staff').value=pair[0];$('patient').value=pair[1];setTimeout(showAssigned,0);},
    setCloud(state){$('connection').textContent=({off:'Offline',connecting:'Connecting',connected:'Connected',sending:'Sending audio',receiving:'Receiving translation'})[state]||state;$('connection').dataset.on=state!=='off';},
    prompt(text){if(text)$('hint').textContent=text;}, error(text){$('error').textContent=text||'';resize();},clearError(){$('error').textContent='';},meter(){},
    translation(text,pair,source){$('empty')?.remove();const article=document.createElement('article');const meta=document.createElement('div');meta.className='translation-meta';const stamp=`TRANSLATION · ${pair.join(' ↔ ')} · ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;meta.textContent=stamp;const p=document.createElement('p');p.textContent=text;const orig=document.createElement('div');orig.className='original';article.append(meta,p,orig);$('transcript').append(article);article.scrollIntoView({block:'nearest',behavior:'smooth'});count++;$('turns').textContent=`${count} exchange${count===1?'':'s'}`;resize();
      // Show what was actually said, then save the bilingual exchange to the Lisans Portal.
      const cid=convId||uid(), link={...(convPortal||portal())}, langs=[...pair];
      Promise.resolve(source).catch(()=>null).then(src=>{
        if(src){orig.textContent=`Original: ${src}`;resize();}
        return backendRequest('log_exchange',{conversation_id:cid,band_id:link.band_id,patient_id:link.patient_id,source_text:src||null,translation:text,language_1:langs[0],language_2:langs[1]});
      }).then(r=>{if(r&&r.ok)meta.textContent=`${stamp} · SAVED TO LISANS PORTAL`;}).catch(e=>console.warn('Lisans Portal sync failed',e));}
  };
  for(const id of ['staff','patient'])for(const lang of cfg.supported_languages){const o=document.createElement('option');o.value=o.textContent=lang;$(id).append(o);}
  ctl=new NativeController(cfg,ui);window.__native=ctl;ui.setPair(ctl.pair);ctl.hello();
  $('band-button').onclick=()=>{if(ctl.state===S.OFF){if(!cfg.has_api_key){ui.error('Interpretation is unavailable. Contact your workspace administrator.');return;}ctl.activate();}else ctl.deactivate();};
  $('apply').onclick=async()=>{ $('apply').disabled=true;const r=await ctl._setLanguages($('staff').value,$('patient').value);if(!r.ok)ui.error(r.message);else{ui.clearError();$('hint').textContent=`Ready for ${ctl.pair.join(' ↔ ')}.`;}$('apply').disabled=false;};
  $('use-patient-lang').onclick=async()=>{const lang=portal().patient_language;if(!lang)return;const r=await ctl._setLanguages(ctl.pair[0]===lang?'English':ctl.pair[0],lang);if(!r.ok)ui.error(r.message);else{ui.clearError();$('hint').textContent=`Ready for ${ctl.pair.join(' ↔ ')}.`;}showAssigned();};
  $('repeat').onclick=()=>{if(ctl.state===S.LISTENING&&!ctl.busy)ctl._run(()=>ctl._repeatLastTranslation());};
  $('clear').onclick=()=>{$('transcript').replaceChildren();count=0;$('turns').textContent='0 exchanges';};
  setInterval(()=>{const s=started?Math.floor((Date.now()-started)/1000):0;$('elapsed').textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;$('repeat').disabled=lastState!==S.LISTENING||ctl.busy||!ctl.lastTranslation;},500);
  window.addEventListener('pagehide',()=>ctl.deactivate());
  function resize(){Streamlit.setFrameHeight(Math.ceil(document.documentElement.scrollHeight)+4);}
  new ResizeObserver(resize).observe(document.body);resize();
}
