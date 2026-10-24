import { Streamlit } from './streamlit.js';
import { NativeController, S } from './controller.js';

const $ = (id) => document.getElementById(id);
const btn = $('toggle');

const ui = {
  setStatus(state, text, mic) {
    $('status').textContent = text;
    $('room').dataset.state = state;
    const on = state !== S.OFF;
    btn.textContent = on ? 'Stop Demo' : 'Start Demo';
    btn.classList.toggle('on', on);
    btn.setAttribute('aria-pressed', String(on));
    const micDot = $('micDot');
    micDot.className = 'dot' + (mic === 'off' ? '' : mic === 'standby' ? ' on' : ' on pulse');
    $('micText').textContent = mic === 'off' ? 'Microphone off'
      : mic === 'standby' ? 'Microphone on · wake-word only, audio stays in this browser'
      : 'Microphone on · completed utterances are sent to OpenAI';
    if (state === S.OFF || state === S.STANDBY) ui.prompt('');
    resize();
  },
  setPair([a, b]) {
    $('pair').innerHTML = '';
    $('pair').append('Languages: ', Object.assign(document.createElement('b'), { textContent: a }), ' ↔ ',
      Object.assign(document.createElement('b'), { textContent: b }));
  },
  setCloud(status, model) {
    const dot = $('cloudDot'), t = $('cloudText');
    const map = {
      off: ['dot', 'OpenAI: not connected'],
      connecting: ['dot warn pulse', 'OpenAI: connecting…'],
      connected: ['dot on', `OpenAI: connected${model ? ' (' + model + ')' : ''} · idle`],
      sending: ['dot warn pulse', 'OpenAI: sending utterance audio'],
      receiving: ['dot on pulse', 'OpenAI: receiving translation'],
    };
    const [cls, text] = map[status] || map.off;
    dot.className = cls; t.textContent = text;
  },
  prompt(text) { $('prompt').textContent = text ? `Native: “${text}”` : ''; resize(); },
  error(msg) { $('err').textContent = msg || ''; resize(); },
  clearError() { $('err').textContent = ''; resize(); },
  meter(vad, wake) {
    $('vadBar').style.width = `${Math.round(vad * 100)}%`;
    if (wake !== null) $('wakeBar').style.width = `${Math.round(Math.min(1, wake) * 100)}%`;
  },
};

let lastH = 0;
function resize() {
  const h = Math.ceil(document.documentElement.scrollHeight) + 2;
  if (h !== lastH) { lastH = h; Streamlit.setFrameHeight(h); }
}
new ResizeObserver(resize).observe(document.body);

let ctl = null;
Streamlit.onRender((args) => {
  if (!ctl && args && args.config) {
    ctl = new NativeController(args.config, ui);
    window.__native = ctl;   // handy for debugging in DevTools
    ui.setPair(ctl.pair);
    if (args.config.debug) $('meter').style.display = 'block';
    ctl.preload().catch((e) => ui.error(e.message));
    ctl.hello();
  }
  resize();
});

btn.addEventListener('click', () => {
  if (!ctl) return;
  if (ctl.state === S.OFF) ctl.activate();      // same click unlocks audio playback
  else ctl.deactivate();
});

Streamlit.ready();
resize();
