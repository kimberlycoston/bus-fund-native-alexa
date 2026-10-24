// Minimal Streamlit component protocol (no build step) + a serialized request/response
// bridge to the Python backend. Requests travel as the component value; Python answers
// through the `responses` argument on the next render.

const listeners = [];
let lastArgs = null;
const pending = new Map();
let chain = Promise.resolve();

function post(type, extra = {}) {
  window.parent.postMessage({ isStreamlitMessage: true, type, ...extra }, '*');
}

window.addEventListener('message', (ev) => {
  const d = ev.data;
  if (!d || d.type !== 'streamlit:render') return;
  lastArgs = d.args || {};
  if (d.theme && d.theme.base) { document.body.classList.toggle('dark', d.theme.base === 'dark'); document.body.classList.toggle('light', d.theme.base !== 'dark'); }
  for (const r of lastArgs.responses || []) {
    const p = pending.get(r.id);
    if (p) { pending.delete(r.id); clearTimeout(p.timer); p.resolve(r); }
  }
  for (const fn of listeners) fn(lastArgs);
});

export const Streamlit = {
  ready() { post('streamlit:componentReady', { apiVersion: 1 }); },
  setFrameHeight(h) { post('streamlit:setFrameHeight', { height: h }); },
  onRender(fn) { listeners.push(fn); if (lastArgs) fn(lastArgs); },
  get args() { return lastArgs; },
};

function uid() {
  try { return crypto.randomUUID(); } catch { return 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2); }
}

/** Ask the Python backend something; resolves with its response dict. Serialized so
 *  two requests never overwrite each other's component value. */
export function backendRequest(type, payload = {}, timeoutMs = 20000) {
  const run = () => new Promise((resolve, reject) => {
    const id = uid();
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Backend did not answer "${type}" in time`)); }, timeoutMs);
    pending.set(id, { resolve, timer });
    post('streamlit:setComponentValue', { value: { id, type, ...payload, ts: Date.now() }, dataType: 'json' });
  });
  const p = chain.then(run, run);
  chain = p.catch(() => {});
  return p;
}
