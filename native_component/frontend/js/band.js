import { NativeController, S } from './controller.js';
import { Streamlit } from './streamlit.js';
export function mountBand(cfg) {
  document.querySelector('link[data-band]')?.remove();
  const css=document.createElement('link'); css.rel='stylesheet';css.href='band.css';css.dataset.band='';document.head.append(css);
  document.body.className='band-app';
  document.body.innerHTML=`<main class="band-shell">
    <header class="brand"><a href="#" aria-label="Native Lisans home"><img class="brand-logo" src="assets/native-lisans-logo.png" alt=""> native <b>lisans</b></a><span class="prototype">LIVE PROTOTYPE</span><button id="present">Presentation view</button></header>
    <section class="intro"><div class="eyebrow">THE LISANS BAND</div><h1>A voice that stays with you.</h1><p>One press. A conversation in your language.</p></section>
    <div class="workspace"><section class="product" aria-label="Interactive Lisans band">
      <div class="device-stage" id="stage" data-state="OFF"><div class="halo"></div><div class="strap"><i></i><i></i><i></i><i></i></div><div class="pod"><div class="pod-top"><span>NATIVE</span><span class="led"></span></div><button id="band-button" aria-label="Start interpretation" aria-pressed="false"><span class="button-glyph">↔</span></button><div class="speaker">···············</div><div class="pod-label">LISANS</div></div></div>
      <div class="device-copy"><div class="state-label" id="status" role="status" aria-live="polite">Ready when you are</div><p id="hint">Press the band to start interpreting.</p><div class="wave" aria-hidden="true">${'<i></i>'.repeat(19)}</div></div>

    </section>
    <aside class="conversation"><div class="session-heading"><div><div class="eyebrow">CONVERSATION</div><h2>Understanding starts here.</h2></div><span class="live-dot" id="connection">Offline</span></div>
      <div class="assignment"><label>Staff language<select id="staff"></select></label><span>↔</span><label>Patient language<select id="patient"></select></label><button id="apply">Set languages</button></div>
      <div id="error" role="alert"></div><div class="transcript" id="transcript" aria-live="polite"><div class="empty" id="empty"><span>“</span><h3>Every word matters.</h3><p>Your live translations will appear here.<br>Either person can speak in their selected language.</p></div></div>
      <div class="session-actions"><button id="repeat" disabled>↻ Replay last translation</button><button id="clear">Clear transcript</button></div>
      <div class="session-footer"><span id="turns">0 exchanges</span><span id="elapsed">00:00</span></div>
    </aside></div><footer class="footnote"></footer>
  </main>`;
  const $=id=>document.getElementById(id); let ctl, count=0, started=0, lastState=S.OFF;
  const ui={
    setStatus(state,text){lastState=state;$('stage').dataset.state=state;const on=state!==S.OFF;$('band-button').setAttribute('aria-pressed',String(on));$('band-button').setAttribute('aria-label',on?'Stop interpretation':'Start interpretation');$('status').textContent=({OFF:'Ready when you are',ACTIVATING:'Connecting…',LISTENING:'Listening to you',TRANSLATING:'Finding the words…',SPEAKING:'Speaking your language',REPLAYING:'Playing it again'})[state]||text;$('hint').textContent=on?'Speak naturally. Press the band again to end.':'Press the band to start interpreting.';$('mic').textContent=on?'Microphone active':'Microphone off';$('staff').disabled=on;$('patient').disabled=on;$('apply').disabled=on;$('repeat').disabled=!on||!ctl?.lastTranslation||ctl?.busy;document.querySelector('.wave').classList.toggle('active',on);if(on&&!started)started=Date.now();if(!on)started=0;resize();},
    setPair(pair){$('staff').value=pair[0];$('patient').value=pair[1];},
    setCloud(state){$('connection').textContent=({off:'Offline',connecting:'Connecting',connected:'Connected',sending:'Sending audio',receiving:'Receiving translation'})[state]||state;$('connection').dataset.on=state!=='off';},
    prompt(text){if(text)$('hint').textContent=text;}, error(text){$('error').textContent=text||'';resize();},clearError(){$('error').textContent='';},meter(){},
    translation(text,pair){$('empty')?.remove();const article=document.createElement('article');const meta=document.createElement('div');meta.className='translation-meta';meta.textContent=`TRANSLATION · ${pair.join(' ↔ ')} · ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;const p=document.createElement('p');p.textContent=text;article.append(meta,p);$('transcript').append(article);article.scrollIntoView({block:'nearest',behavior:'smooth'});count++;$('turns').textContent=`${count} exchange${count===1?'':'s'}`;resize();}
  };
  for(const id of ['staff','patient'])for(const lang of cfg.supported_languages){const o=document.createElement('option');o.value=o.textContent=lang;$(id).append(o);}
  ctl=new NativeController(cfg,ui);window.__native=ctl;ui.setPair(ctl.pair);ctl.hello();
  $('band-button').onclick=()=>{if(ctl.state===S.OFF){if(!cfg.has_api_key){ui.error('Add OPENAI_API_KEY to Streamlit secrets or your environment, then restart.');return;}ctl.activate();}else ctl.deactivate();};
  $('apply').onclick=async()=>{ $('apply').disabled=true;const r=await ctl._setLanguages($('staff').value,$('patient').value);if(!r.ok)ui.error(r.message);else{ui.clearError();$('hint').textContent=`Ready for ${ctl.pair.join(' ↔ ')}.`;}$('apply').disabled=false;};
  $('repeat').onclick=()=>{if(ctl.state===S.LISTENING&&!ctl.busy)ctl._run(()=>ctl._repeatLastTranslation());};
  $('clear').onclick=()=>{$('transcript').replaceChildren();count=0;$('turns').textContent='0 exchanges';};
  $('present').onclick=()=>{document.body.classList.toggle('presenting');$('present').textContent=document.body.classList.contains('presenting')?'Exit presentation':'Presentation view';resize();};
  setInterval(()=>{const s=started?Math.floor((Date.now()-started)/1000):0;$('elapsed').textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;$('repeat').disabled=lastState!==S.LISTENING||ctl.busy||!ctl.lastTranslation;},500);
  window.addEventListener('pagehide',()=>ctl.deactivate());
  function resize(){Streamlit.setFrameHeight(Math.ceil(document.documentElement.scrollHeight)+4);}
  new ResizeObserver(resize).observe(document.body);resize();
}
