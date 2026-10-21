// VR in the headset without a headset: the trainer in headless Chromium with Meta's WebXR emulator (IWER, the
// `iwer` dev dependency) installed before the page loads, as a Quest 3. It enters VR by the header's button, finds
// the panel 1.5 m in front of the eyes with the chart drawn at its size, presses «Слухати» and «Вокал» with a
// controller's trigger and «Сюди» with a pinch of a tracked hand, seeks on the progress bar, and leaves by «Вийти»:
// the page's chart gets its own size back. Screenshots of the panel go to LUMA_SHOT (with _listen / _hand suffixes).
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
await page.goto(url); await page.waitForTimeout(600);
const shot = suffix => process.env.LUMA_SHOT ? page.screenshot({path: process.env.LUMA_SHOT.replace(/\.png$/, suffix + '.png')}) : null;
const pageChart = await page.evaluate(() => ({w: document.getElementById('chart').width, h: document.getElementById('chart').height}));

await page.waitForSelector('#xrBtn:not([hidden])', {timeout: 5000}).catch(() => {});
assert(await page.isVisible('#xrBtn'), 'the header shows «VR» where immersive-ar is supported');
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
const trigger = async () => {
  await page.evaluate(() => window.__iwer.controllers.right.updateButtonValue('trigger', 1)); await page.waitForTimeout(200);
  await page.evaluate(() => window.__iwer.controllers.right.updateButtonValue('trigger', 0)); await page.waitForTimeout(200);
};
const mode = () => page.evaluate(() => window.Luma.diagnostics().mode);

await page.evaluate(() => window.__iwer.controllers.right.position.set(.2, 1.35, -.2));
await point(...centre('listen')); await page.waitForTimeout(300);
assert((await hovered()).includes('listen'), 'the controller\'s ray lights «Слухати»');
await trigger();
await page.waitForFunction(() => window.Luma.diagnostics().mode === 'listen', null, {timeout: 8000}).catch(() => {});
assert(await mode() === 'listen', 'the trigger on «Слухати» plays the song');
await page.waitForTimeout(800);
const playing = await page.evaluate(() => window.Luma.diagnostics().time);
assert(playing > 0.3, 'the song plays on in VR (the headset\'s frames drive the page): ' + playing.toFixed(2) + ' s');
await shot('_listen');

const vocal = () => page.evaluate(() => document.getElementById('vocalBtn').getAttribute('aria-pressed'));
const before = await vocal();
await point(...centre('vocal')); await page.waitForTimeout(300); await trigger();
assert(await vocal() !== before, 'the trigger on «Вокал» switches the original vocal, through the page\'s own button');

const [bx, by] = [L.BAR.x + L.BAR.w * .5, L.BAR.y + L.BAR.h / 2];
await point(bx, by); await page.waitForTimeout(300); await trigger(); await page.waitForTimeout(300);
const half = await page.evaluate(() => { const d = window.Luma.diagnostics(); return d.time / window.LUMA_SONG.duration; });
assert(Math.abs(half - .5) < .08, 'a press on the progress bar seeks there: ' + half.toFixed(2) + ' of the song');

await point(...centre('listen')); await page.waitForTimeout(300); await trigger();
await page.waitForFunction(() => window.Luma.diagnostics().mode === 'idle', null, {timeout: 5000}).catch(() => {});
assert(await mode() === 'idle', 'the trigger on «Пауза» stops it');

// a tracked hand: its ray and a pinch read from the joints; «Сюди» puts the panel in front of where the head now looks
await page.evaluate(() => { window.__iwer.primaryInputMode = 'hand'; });
await page.waitForTimeout(500);
await page.evaluate(() => window.__iwer.hands.right.position.set(.2, 1.35, -.25));
await point(...centre('here'), 'hands'); await page.waitForTimeout(300);
const handHover = await hovered();
assert(handHover.includes('here'), 'the hand\'s ray lights «Сюди»: ' + handHover.join(','));
const turn = Math.PI / 6;
await page.evaluate(t => window.__iwer.quaternion.set(0, Math.sin(t / 2), 0, Math.cos(t / 2)), turn);
await page.evaluate(() => window.__iwer.hands.right.updatePinchValue(1)); await page.waitForTimeout(300);
await page.evaluate(() => window.__iwer.hands.right.updatePinchValue(0)); await page.waitForTimeout(300);
const moved = await page.evaluate(() => window.__lumaXr.panel.c);
const expect = [-Math.sin(turn) * 1.5, -Math.cos(turn) * 1.5];
assert(Math.hypot(moved[0] - expect[0], moved[2] - expect[1]) < .05, 'a pinch on «Сюди» brings the panel in front of the turned head');
await shot('_hand');

await page.evaluate(() => { window.__iwer.quaternion.set(0, 0, 0, 1); window.__iwer.primaryInputMode = 'controller'; });
await page.waitForTimeout(500);
await page.evaluate(() => { window.__lumaXr.placeWanted = true; window.__iwer.controllers.right.position.set(.2, 1.35, -.2); });
await page.waitForTimeout(200);
await point(...centre('exit')); await page.waitForTimeout(300); await trigger();
await page.waitForFunction(() => !document.body.classList.contains('in-xr'), null, {timeout: 5000}).catch(() => {});
const after = await page.evaluate(() => ({inXr: document.body.classList.contains('in-xr'), w: document.getElementById('chart').width, h: document.getElementById('chart').height}));
assert(!after.inXr && after.w === pageChart.w && after.h === pageChart.h, '«Вийти» ends the session and the page\'s chart gets its size back: ' + after.w + '×' + after.h);
assert(logs.length === 0, 'clean console' + (logs.length ? ': ' + logs.join(' | ') : ''));
await browser.close();
