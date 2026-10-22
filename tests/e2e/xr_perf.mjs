// The headset's frame loop on Meta's WebXR emulator (IWER, Quest 3 profile, SwiftShader GL): frames per second, the
// time of one Run.frame (the trainer's tick, the chart drawn, the page read, the textures uploaded, the GL calls) and
// the texture uploads, idle, listening and singing, at 1× and 4× CPU throttle, with the chart's texture uploaded with
// mipmaps and without them (app/xr.js uploads it without). A measurement, not a gate: not part of run.sh.
// SwiftShader runs GL on the CPU, so its numbers say how the variants compare, not what a Quest's GPU does.
//   LUMA_XR_PERF_SECONDS=4   window per measurement
//   LUMA_XR_PERF_REPS=2      repetitions, the variants interleaved within each
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {launch, url} from './lib.mjs';

const seconds = Number(process.env.LUMA_XR_PERF_SECONDS || 4), reps = Number(process.env.LUMA_XR_PERF_REPS || 2);
const iwer = readFileSync(createRequire(import.meta.url).resolve('iwer/build/iwer.min.js'), 'utf8');
const setup = `${iwer}
;(() => { const d = new IWER.XRDevice(IWER.metaQuest3, {stereoEnabled: false}); d.installRuntime({forceInstall: true});
  d.primaryInputMode = 'controller'; d.position.set(0, 1.6, 0); window.__iwer = d; })();`;
const browser = await launch(['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--enable-unsafe-swiftshader', '--use-angle=swiftshader']);
const context = await browser.newContext({viewport: {width: 1280, height: 800}});
await context.grantPermissions(['microphone'], {origin: new URL(url).origin});
await context.addInitScript(setup);
const page = await context.newPage();
await page.goto(url); await page.waitForFunction(() => window.Luma && window.LumaXR);
await page.waitForSelector('#xrBtn:not([hidden])');
await page.click('#xrBtn');
await page.waitForFunction(() => window.__lumaXr && window.__lumaXr.frames > 10, null, {timeout: 20000});
const cdp = await context.newCDPSession(page);

// Wrap the running session's frame and upload; `variant` picks how the chart's texture is uploaded.
await page.evaluate(() => {
  const run = window.__lumaXr, r = run.r, gl = r.gl, frame = run.frame.bind(run);
  const P = window.__perf = {frames: [], uploads: [], variant: 'mip'};
  const name = t => t === run.chartTex ? 'chart' : t === run.baseTex ? 'base' : t === run.overTex ? 'over' : 'other';
  run.frame = (t, f) => { const t0 = performance.now(); frame(t, f); P.frames.push([t0, performance.now() - t0]); };
  r.upload = (t, canvas) => {
    const t0 = performance.now(), mip = P.variant === 'mip' || t !== run.chartTex;
    gl.bindTexture(gl.TEXTURE_2D, t); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    if (mip) { gl.generateMipmap(gl.TEXTURE_2D); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR); }
    else gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    if (r.aniso) gl.texParameterf(gl.TEXTURE_2D, r.aniso.TEXTURE_MAX_ANISOTROPY_EXT, 4);
    P.uploads.push([t0, name(t), performance.now() - t0, canvas.width * canvas.height]);
  };
});
const mode = () => page.evaluate(() => window.Luma.diagnostics().mode);
const stateTo = async want => {
  if (await mode() !== 'idle') { await page.evaluate(() => document.getElementById('stopBtn').click()); await page.waitForFunction(() => window.Luma.diagnostics().mode === 'idle' && !window.Luma.diagnostics().pending, null, {timeout: 10000}); }
  if (want === 'idle') return;
  await page.evaluate(() => window.Luma.test.seek(0));
  await page.evaluate(id => document.getElementById(id).click(), want === 'listen' ? 'listenBtn' : 'singBtn');
  await page.waitForFunction(m => window.Luma.diagnostics().mode === m, want === 'listen' ? 'listen' : 'singing', {timeout: 10000});
  await page.waitForFunction(() => window.Luma.diagnostics().time > .3, null, {timeout: 10000});
};
const q = (a, p) => a.length ? a[Math.min(a.length - 1, Math.floor(p * a.length))] : 0;
const rows = [];
for (const rate of [1, 4]) {
  await cdp.send('Emulation.setCPUThrottlingRate', {rate});
  for (const state of ['idle', 'listen', 'sing']) for (let rep = 0; rep < reps; rep++) for (const variant of rep % 2 ? ['flat', 'mip'] : ['mip', 'flat']) {
    await stateTo(state);
    await page.evaluate(v => { window.__perf.variant = v; }, variant);
    await page.waitForTimeout(500);   // a window of wall time is what is measured; this settles the switch
    const t0 = await page.evaluate(() => performance.now());
    await page.waitForTimeout(seconds * 1000);
    const m = await page.evaluate(t0 => {
      const P = window.__perf, t1 = performance.now(), fr = P.frames.filter(f => f[0] >= t0 && f[0] < t1).map(f => f[1]).sort((a, b) => a - b);
      const up = P.uploads.filter(u => u[0] >= t0 && u[0] < t1), by = {};
      for (const [, n, ms] of up) { const b = by[n] ||= {n: 0, ms: 0, max: 0}; b.n++; b.ms += ms; b.max = Math.max(b.max, ms); }
      for (const b of Object.values(by)) { b.ms = +b.ms.toFixed(1); b.max = +b.max.toFixed(1); }
      P.frames.length = 0; P.uploads.length = 0;
      return {fps: +(fr.length / ((t1 - t0) / 1000)).toFixed(1), frameMed: +fr[Math.floor(fr.length / 2)]?.toFixed(2), frameP95: +(fr.length ? fr[Math.min(fr.length - 1, Math.floor(.95 * fr.length))] : 0).toFixed(2), uploads: by};
    }, t0);
    if (state !== 'idle' && await mode() === 'idle') m.note = 'ended inside the window';
    const row = {rate, state, variant, rep, ...m}; rows.push(row); console.log(JSON.stringify(row));
  }
}
await stateTo('idle');
await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1});
await browser.close();
