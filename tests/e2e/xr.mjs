// VR in the headset without a headset: the trainer in headless Chromium with Meta's WebXR emulator (IWER, the
// `iwer` dev dependency) installed before the page loads, as a Quest 3. It enters VR by the header's button, finds
// the panel 1.5 m in front of the eyes with the chart drawn at its size, presses «Слухати» and «Вокал» with a
// controller's trigger and «Сюди» with a pinch of a tracked hand, seeks on the progress bar, and leaves by «Вийти»:
// the page's chart gets its own size back. Before that a refused session leaves the page out of VR with a toast that is
// true to the microphone, and a hidden session (the headset taken off) stops listening and singing. Every wait is on
// the state it waits for, counted in the headset's frames. Screenshots of the panel go to LUMA_SHOT (with _listen /
// _hand suffixes).
import {readFileSync, existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {launch, open, assert, url} from './lib.mjs';

const iwerPath = process.env.LUMA_IWER || (() => { try { return createRequire(import.meta.url).resolve('iwer/build/iwer.min.js'); } catch { return ''; } })();
if (!iwerPath || !existsSync(iwerPath)) { console.error('FAIL iwer is not installed (bun install)'); process.exit(1); }
const setup = `${readFileSync(iwerPath, 'utf8')}
;(() => {
  const d = new IWER.XRDevice(IWER.metaQuest3, {stereoEnabled: false});
  d.installRuntime({forceInstall: true});
  d.primaryInputMode = 'controller';
  d.position.set(0, 1.6, 0);
  window.__iwer = d;
})();`;

const browser = await launch(['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--enable-unsafe-swiftshader', '--use-angle=swiftshader']);
const context = await browser.newContext({viewport: {width: 1280, height: 800}});
await context.grantPermissions(['microphone'], {origin: new URL(url).origin});
await context.addInitScript(setup);
const page = await context.newPage(); const logs = [];
// SwiftShader's own performance notes (a screenshot reads the canvas back) are the emulator's, not the page's
page.on('console', m => { if (['error', 'warning'].includes(m.type()) && !/GL Driver Message/.test(m.text())) logs.push(m.type() + ': ' + m.text()); });
page.on('pageerror', e => logs.push('PAGEERROR ' + e.message));
await page.goto(url); await page.waitForFunction(() => window.Luma && window.LumaXR);
const shot = suffix => process.env.LUMA_SHOT ? page.screenshot({path: process.env.LUMA_SHOT.replace(/\.png$/, suffix + '.png')}) : null;
const pageChart = await page.evaluate(() => ({w: document.getElementById('chart').width, h: document.getElementById('chart').height}));

await page.waitForSelector('#xrBtn:not([hidden])', {timeout: 5000}).catch(() => {});
assert(await page.isVisible('#xrBtn'), 'the header shows «VR» where immersive-ar is supported');

// A refused session (the click's activation lapsed while the microphone was asked, or any other refusal): the page
// stays out of VR and its toast says only what is true of the microphone. The browser's answers are stubbed per case.
const refuse = mic => page.evaluate(async mic => {
  const P = navigator.permissions, M = navigator.mediaDevices, X = navigator.xr;
  const keep = {query: P.query, gum: M.getUserMedia, request: X.requestSession}; let asked = 0;
  P.query = async () => ({state: mic === 'allowed' ? 'granted' : 'prompt'});
  M.getUserMedia = async () => { asked++; if (mic === 'denied') throw new DOMException('denied', 'NotAllowedError'); return new MediaStream(); };
  X.requestSession = async () => { throw new DOMException('activation lapsed', 'SecurityError'); };
  const toast = document.getElementById('toast'); toast.textContent = '';
  try {
    document.getElementById('xrBtn').click();
    const t0 = performance.now(); while (!toast.textContent.includes('VR') && performance.now() - t0 < 5000) await new Promise(r => setTimeout(r, 20));
    return {toast: toast.textContent, asked, inXr: document.body.classList.contains('in-xr'), run: !!window.__lumaXr};
  } finally { P.query = keep.query; M.getUserMedia = keep.gum; X.requestSession = keep.request; }
}, mic);
for (const [mic, say] of [['denied', 'Без мікрофона в шоломі можна тільки слухати. Натисни «VR» ще раз, щоб увійти.'],
  ['asked', 'Мікрофон дозволено. Натисни «VR» ще раз, щоб увійти.'], ['allowed', 'VR не відкрився. Натисни «VR» ще раз, щоб увійти.']]) {
  const r = await refuse(mic);
  assert(!r.inXr && !r.run && r.toast === say && r.asked === (mic === 'allowed' ? 0 : 1),
    'a refused session with the microphone ' + mic + ' stays out of VR and says so: ' + JSON.stringify(r));
}

// A session that opens but cannot be drawn in (a shader that fails to compile): it ends again, the page stays out of
// VR and says why, and the press leaves no rejected promise behind.
await page.evaluate(() => {
  const G = WebGL2RenderingContext.prototype, X = navigator.xr;
  window.__keep = {param: G.getShaderParameter, log: G.getShaderInfoLog, request: X.requestSession};
  G.getShaderParameter = function (s, p) { return p === this.COMPILE_STATUS ? false : window.__keep.param.call(this, s, p); };
  G.getShaderInfoLog = () => 'stub: the shader failed';
  window.__broken = {opened: false, ended: false};
  X.requestSession = async (...a) => { const s = await window.__keep.request.apply(X, a); window.__broken.opened = true; s.addEventListener('end', () => { window.__broken.ended = true; }); return s; };
  document.getElementById('toast').textContent = '';
});
await page.click('#xrBtn');
await page.waitForFunction(() => window.__broken.ended && document.getElementById('toast').textContent.includes('VR'), null, {timeout: 5000}).catch(() => {});
const broken = await page.evaluate(() => {
  const G = WebGL2RenderingContext.prototype, k = window.__keep;
  G.getShaderParameter = k.param; G.getShaderInfoLog = k.log; navigator.xr.requestSession = k.request;
  return {...window.__broken, inXr: document.body.classList.contains('in-xr'), run: !!window.__lumaXr, toast: document.getElementById('toast').textContent};
});
assert(broken.opened && broken.ended && !broken.inXr && !broken.run && broken.toast.startsWith('VR не запустився') && !logs.length,
  'a session the panel cannot be drawn in ends again, out of VR, with a toast that says so: ' + JSON.stringify({...broken, logs}));

await page.click('#xrBtn');
await page.waitForFunction(() => window.__lumaXr && window.__lumaXr.frames > 10, null, {timeout: 15000}).catch(() => {});
const entered = await page.evaluate(() => {
  const x = window.__lumaXr; if (!x) return null;
  const c = document.getElementById('chart'), head = window.__iwer.position;
  return {frames: x.frames, centre: x.panel.c, head: [head.x, head.y, head.z], chart: [c.width, c.height], inXr: document.body.classList.contains('in-xr')};
});
assert(entered && entered.inXr, 'the session starts and the page marks itself in VR');
assert(entered && Math.abs(Math.hypot(entered.centre[0] - entered.head[0], entered.centre[2] - entered.head[2]) - 1.5) < .01 && entered.centre[1] < entered.head[1], 'the panel stands 1.5 m in front of the eyes, a little below them');
const L = await page.evaluate(() => window.LumaXR.layout);
assert(entered && entered.chart[0] === Math.round(L.CHART.w * 1.6) && entered.chart[1] === Math.round(L.CHART.h * 1.6), 'the chart is drawn at its place on the panel: ' + (entered && entered.chart.join('×')));
await shot('');

// Points the right controller (or hand) from beside the head at a spot of the panel, in page pixels.
const point = (u, v, kind = 'controllers') => page.evaluate(({u, v, kind}) => {
  const x = window.__lumaXr, L = window.LumaXR.layout, M = 1.5 / L.UW, {c, cs, sn} = x.panel;
  const lx = (u - L.UW / 2) * M, ly = (L.UH / 2 - v) * M, target = [c[0] + cs * lx, c[1] + ly, c[2] - sn * lx];
  const dev = window.__iwer[kind].right, from = [dev.position.x, dev.position.y, dev.position.z];
  const d = target.map((t, i) => t - from[i]), len = Math.hypot(...d), b = d.map(v => v / len);
  // the rotation that takes −z to b
  const a = [0, 0, -1], w = 1 + (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]), q = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0], w];
  const n = Math.hypot(...q); dev.quaternion.set(q[0] / n, q[1] / n, q[2] / n, q[3] / n);
}, {u, v, kind});
const centre = id => { const b = L.BUTTONS.find(b => b.id === id); return [b.x + b.w / 2, b.y + b.h / 2]; };
const hovered = () => page.evaluate(() => [...window.__lumaXr.hovered]);
// n more of the headset's frames: the session's input and the page's state are read once per frame (an ended session
// draws none: «Вийти» ends it on the press)
const frames = async (n = 3) => {
  const f0 = await page.evaluate(() => window.__lumaXr.frames);
  await page.waitForFunction(f => window.__lumaXr.frames >= f || !document.body.classList.contains('in-xr'), f0 + n, {timeout: 15000}).catch(() => { throw new Error('the headset stopped drawing frames: ' + logs.join(' | ')); });
};
// a press takes what the ray pointed at LOOK_BACK (90 ms) before it, so the ray rests on its target that long first
const rests = on => page.waitForFunction(on => [...window.__lumaXr.sources.values()].some(st => {
  const h = st.history, at = e => on === 'bar' ? e.target?.bar !== undefined : e.target?.button?.id === on, last = h.at(-1);
  return last && at(last) && h.some(e => e.t <= last.t - 120 && at(e));
}), on, {timeout: 5000}).catch(() => {});
const aim = async (id, kind) => { await point(...centre(id), kind); await rests(id); };
const trigger = async () => {
  await page.evaluate(() => window.__iwer.controllers.right.updateButtonValue('trigger', 1)); await frames(2);
  await page.evaluate(() => window.__iwer.controllers.right.updateButtonValue('trigger', 0)); await frames(2);
};
const mode = () => page.evaluate(() => window.Luma.diagnostics().mode);
const waitMode = m => page.waitForFunction(m => window.Luma.diagnostics().mode === m, m, {timeout: 8000}).catch(() => {});

await page.evaluate(() => window.__iwer.controllers.right.position.set(.2, 1.35, -.2));
await aim('listen');
assert((await hovered()).includes('listen'), 'the controller\'s ray lights «Слухати»');
await trigger();
await waitMode('listen');
assert(await mode() === 'listen', 'the trigger on «Слухати» plays the song');
await page.waitForFunction(() => window.Luma.diagnostics().time > .3, null, {timeout: 8000}).catch(() => {});
const playing = await page.evaluate(() => window.Luma.diagnostics().time);
assert(playing > 0.3, 'the song plays on in VR (the headset\'s frames drive the page): ' + playing.toFixed(2) + ' s');
await shot('_listen');

const vocal = () => page.evaluate(() => document.getElementById('vocalBtn').getAttribute('aria-pressed'));
const before = await vocal();
await aim('vocal'); await trigger();
await page.waitForFunction(b => document.getElementById('vocalBtn').getAttribute('aria-pressed') !== b, before, {timeout: 5000}).catch(() => {});
assert(await vocal() !== before, 'the trigger on «Вокал» switches the original vocal, through the page\'s own button');

const [bx, by] = [L.BAR.x + L.BAR.w * .5, L.BAR.y + L.BAR.h / 2];
await point(bx, by); await rests('bar'); await trigger();
await page.waitForFunction(() => Math.abs(window.Luma.diagnostics().time / window.LUMA_SONG.duration - .5) < .08, null, {timeout: 5000}).catch(() => {});
const half = await page.evaluate(() => { const d = window.Luma.diagnostics(); return d.time / window.LUMA_SONG.duration; });
assert(Math.abs(half - .5) < .08, 'a press on the progress bar seeks there: ' + half.toFixed(2) + ' of the song');

await aim('listen'); await trigger();
await waitMode('idle');
assert(await mode() === 'idle', 'the trigger on «Пауза» stops it');

// The session goes hidden (the headset taken off, the Quest menu opened): what plays or records stops, and the
// toast says why. The window's own visibility is ignored in VR, so this hook is the only thing that stops it.
const hide = async () => {
  await page.evaluate(() => { document.getElementById('toast').textContent = ''; window.__iwer.updateVisibilityState('hidden'); });
  await waitMode('idle');
  const r = await page.evaluate(() => ({mode: window.Luma.diagnostics().mode, toast: document.getElementById('toast').textContent, inXr: document.body.classList.contains('in-xr')}));
  await page.evaluate(() => window.__iwer.updateVisibilityState('visible'));
  await page.waitForFunction(() => window.__lumaXr.session.visibilityState === 'visible', null, {timeout: 5000}).catch(() => {}); await frames();
  return r;
};
for (const [id, playing] of [['listen', 'listen'], ['sing', 'singing']]) {
  await aim(id); await trigger(); await waitMode(playing);
  const was = await mode(), r = await hide();
  assert(was === playing && r.mode === 'idle' && r.inXr && r.toast === 'Шолом знято або відкрите меню: відтворення зупинено.',
    'a hidden session stops ' + playing + ' and stays in VR: ' + JSON.stringify({was, ...r}));
  await page.waitForFunction(() => !window.Luma.diagnostics().pending, null, {timeout: 8000}).catch(() => {});
}

// a tracked hand: its ray and a pinch read from the joints; «Сюди» puts the panel in front of where the head now looks
await page.evaluate(() => { window.__iwer.primaryInputMode = 'hand'; });
await page.waitForFunction(() => [...window.__lumaXr.session.inputSources].some(s => s.hand), null, {timeout: 5000}).catch(() => {});
await page.evaluate(() => window.__iwer.hands.right.position.set(.2, 1.35, -.25));
await aim('here', 'hands');
const handHover = await hovered();
assert(handHover.includes('here'), 'the hand\'s ray lights «Сюди»: ' + handHover.join(','));
const turn = Math.PI / 6;
await page.evaluate(t => window.__iwer.quaternion.set(0, Math.sin(t / 2), 0, Math.cos(t / 2)), turn);
await page.evaluate(() => window.__iwer.hands.right.updatePinchValue(1)); await frames();
await page.evaluate(() => window.__iwer.hands.right.updatePinchValue(0)); await frames();
const moved = await page.evaluate(() => window.__lumaXr.panel.c);
const expect = [-Math.sin(turn) * 1.5, -Math.cos(turn) * 1.5];
assert(Math.hypot(moved[0] - expect[0], moved[2] - expect[1]) < .05, 'a pinch on «Сюди» brings the panel in front of the turned head');
await shot('_hand');

await page.evaluate(() => { window.__iwer.quaternion.set(0, 0, 0, 1); window.__iwer.primaryInputMode = 'controller'; });
await page.waitForFunction(() => [...window.__lumaXr.session.inputSources].some(s => s.gamepad), null, {timeout: 5000}).catch(() => {});
await page.evaluate(() => { window.__lumaXr.placeWanted = true; window.__iwer.controllers.right.position.set(.2, 1.35, -.2); });
await page.waitForFunction(() => !window.__lumaXr.placeWanted, null, {timeout: 5000}).catch(() => {});
await aim('exit'); await trigger();
await page.waitForFunction(() => !document.body.classList.contains('in-xr'), null, {timeout: 5000}).catch(() => {});
const after = await page.evaluate(() => ({inXr: document.body.classList.contains('in-xr'), w: document.getElementById('chart').width, h: document.getElementById('chart').height}));
assert(!after.inXr && after.w === pageChart.w && after.h === pageChart.h, '«Вийти» ends the session and the page\'s chart gets its size back: ' + after.w + '×' + after.h);
assert(logs.length === 0, 'clean console' + (logs.length ? ': ' + logs.join(' | ') : ''));
await browser.close();
