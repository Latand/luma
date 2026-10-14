// Past takes as dust behind the target (docs/design/TAKE_CLOUD.md): the takes in the tab feed the cloud through a worker,
// the take on screen and a take being re-recorded stay out of it, the specks sit under the target and the live line and
// stay faint, the record line and its switch are gone with their saved pref, wordless notes keep their look, and a frame
// with the cloud stays within budget at 390 px and on desktop, at 1× and 4× CPU throttle.
import {launch, open, assert, url} from './lib.mjs';
const b = await launch(['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']);
const {page: p, logs} = await open(b);
const cloud = () => p.evaluate(() => window.Luma.test.cloud());
const settle = page => page.waitForFunction(() => window.Luma.test.cloud().ready, null, {timeout: 8000});
// The worker paints the layer for the scale on screen; a frame drawn before it arrives shows the previous one stretched.
const fitted = page => page.waitForFunction(() => { window.Luma.test.draw(); return window.Luma.test.cloud().fit; }, null, {timeout: 8000, polling: 30});
// Synthetic takes over the whole song: the target moved by `off` semitones, a slow wobble and a little noise.
const SEED = `(n, off, seed) => { const L = window.Luma, T = L.test, dur = window.LUMA_SONG.duration, midiF = m => 440 * 2 ** ((m - 69) / 12);
  let s = seed; const rnd = () => (s = s * 16807 % 2147483647) / 2147483647; const ids = [];
  for (let k = 0; k < n; k++) { const pts = [];
    for (let t = 0; t < dur; t += .021333) { const ref = L.targetAt(t); pts.push({t, f: ref ? midiF(ref.m + off + Math.sin(t * 9 + k) * .2 + (rnd() - .5) * .3) : null, confidence: .9, db: -20}); }
    T.closeTrace(); ids.push(T.injectTake({a: 0, b: dur, points: pts, startedAt: new Date(Date.now() - (n - k) * 6e4).toISOString()}).id); }
  T.closeTrace(); return ids; }`;
// The plot rectangle as device pixels, read off a copy of the stage after one drawn frame.
const PIXELS = `() => { const T = window.Luma.test, pl = T.plot(), chart = document.getElementById('chart'), DPR = T.dpr(); T.draw();
  const c = document.createElement('canvas'); c.width = chart.width; c.height = chart.height; const g = c.getContext('2d', {willReadFrequently: true}); g.drawImage(chart, 0, 0);
  const x = Math.round(pl.left * DPR), y = Math.round(pl.top * DPR), w = Math.round((pl.right - pl.left) * DPR), h = Math.round((pl.bottom - pl.top) * DPR);
  return {w, h, d: Array.from(g.getImageData(x, y, w, h).data)}; }`;
const frame = async shown => { await p.evaluate(v => window.Luma.test.cloudShown(v), shown); if (shown) await fitted(p);
  const px = await p.evaluate(`(${PIXELS})()`); await p.evaluate(() => window.Luma.test.cloudShown(true)); return px; };

// ── 1 · the record line is gone: no button, no legend entry, no saved pref, no `shadow` in the activity state ─────────
await p.evaluate(() => { const k = 'luma.trainer.settings', o = JSON.parse(localStorage.getItem(k) || '{}'); o.shadow = false; localStorage.setItem(k, JSON.stringify(o)); });
await p.reload(); await p.waitForTimeout(600);
const chrome = await p.evaluate(() => ({btn: !!document.getElementById('shadowBtn'), legend: document.querySelector('.legend').textContent,
  saved: JSON.parse(localStorage.getItem('luma.trainer.settings') || '{}')}));
assert(!chrome.btn, 'the «Рекорд» switch is gone from the stage');
assert(!/твій рекорд/.test(chrome.legend) && /твої спроби/.test(chrome.legend), 'the legend names the dust, not the record line: ' + chrome.legend);
assert(!('shadow' in chrome.saved), 'a saved `shadow` pref is dropped at load, never read as «cloud off» ' + JSON.stringify(chrome.saved));
const stateKeys = await p.evaluate(() => { const A = window.LumaActivity, seen = []; const orig = A.state; A.state = cur => { seen.push(...Object.keys(cur)); return orig(cur); };
  document.getElementById('lyricsBtn').click(); document.getElementById('lyricsBtn').click(); A.state = orig; return seen; });
assert(stateKeys.length && !stateKeys.includes('shadow'), 'the activity state carries no `shadow` key ' + JSON.stringify([...new Set(stateKeys)]));
let c = await cloud();
assert(c.ready && c.specks === 0 && c.ids.length === 0, 'no takes, no dust ' + JSON.stringify(c));
assert(!(await p.evaluate(() => window.Luma.test.noteBoxes())).some(e => e.kind === 'cloud'), 'an empty cloud draws nothing');

// ── 2 · seeded takes become dust, built in the worker ─────────────────────────────────────────────────────────────────
const ids = await p.evaluate(`(${SEED})(6, 2, 11)`);
await settle(p); c = await cloud();
assert(c.worker && !c.failed && c.workMs > 0 && c.takes === 6 && c.ids.length === 6, 'six takes in the tab feed the cloud from the worker ' + JSON.stringify({...c, layer: undefined}));
assert(c.specks > 6 * 400, 'every confident frame is a speck (' + c.specks + ')');
const tAt = await p.evaluate(() => { const n = window.LUMA_SONG.notes.find(n => n.ok && n.b - n.a > .5 && n.a > 4); return (n.a + n.b) / 2; });
await p.evaluate(t => { window.Luma.test.seek(t); }, tAt); await fitted(p);
const boxes = await p.evaluate(() => window.Luma.test.noteBoxes());
const cloudAt = boxes.findIndex(e => e.kind === 'cloud'), firstNote = boxes.findIndex(e => e.kind !== 'cloud');
assert(cloudAt === 0 && firstNote > 0, 'the dust is drawn before the first target bar, so every bar paints over it ' + JSON.stringify(boxes.slice(0, 2).map(e => e.kind)));
c = await cloud();
assert(c.layer && c.layer.w > 0 && c.layer.h > 0 && c.builds >= 1, 'the worker paints the specks into a layer the stage only blits ' + JSON.stringify({layer: c.layer, ms: c.layerMs}));

// faint: added light everywhere, never more than the two speck tiers together can add over the stage
const diff = (on, off) => { let ink = 0, max = 0; for (let i = 0; i < on.d.length; i += 4) { const d = Math.max(on.d[i] - off.d[i], on.d[i + 1] - off.d[i + 1], on.d[i + 2] - off.d[i + 2]); if (d > 8) ink++; if (d > max) max = d; } return {ink, max}; };
let on = await frame(true), off = await frame(false), dd = diff(on, off);
assert(dd.ink > 200, 'the dust puts light on the plot (' + dd.ink + ' pixels)');
assert(dd.max <= 110, 'no speck is brighter than the two faint tiers together (max +' + dd.max + ' of 255)');

// ── 3 · the take on screen and a take being re-recorded stay out ─────────────────────────────────────────────────────
await p.evaluate(id => window.Luma.test.selectTake(id), ids[2]); await settle(p); c = await cloud();
assert(!c.ids.includes(ids[2]) && c.takes === 5, 'the take under review is not part of its own cloud ' + JSON.stringify(c.ids));
await p.evaluate(() => window.Luma.test.closeTrace()); await settle(p); c = await cloud();
assert(c.ids.includes(ids[2]) && c.takes === 6, 'closing the review puts it back ' + JSON.stringify(c.ids));
const punch = await p.evaluate(async id => { const T = window.Luma.test; T.selectTake(id); const t = T.takes().find(x => x.id === id); T.seek(t.a + 4); await new Promise(r => setTimeout(r, 100)); return T.punchTarget(); }, ids[3]);
assert(punch === ids[3], 'a seek inside the take on screen arms a punch-in (' + punch + ')');
await p.locator('#singBtn').click();
await p.waitForFunction(() => window.Luma.test.state().mode === 'singing', null, {timeout: 9000});
await settle(p); c = await cloud();
assert(!c.ids.includes(ids[3]) && c.ids.length === 5, 'the take being re-recorded stays out while it is sung over ' + JSON.stringify(c.ids));
await p.waitForTimeout(700); await p.locator('#stopBtn').click();
await p.waitForFunction(() => window.Luma.test.state().mode === 'idle' && !document.getElementById('singBtn').disabled, null, {timeout: 9000});
await p.evaluate(() => window.Luma.test.closeTrace()); await settle(p); c = await cloud();
assert(c.ids.includes(ids[3]), 'the re-recorded take is back in the cloud once the punch is over ' + JSON.stringify(c.ids));

// the live line keeps every one of its core pixels with the dust under it (after the punch-in: a fake sing sets the real
// audio context aside)
await p.evaluate(t => { const L = window.Luma, T = L.test, a = t - 1.5, midiF = m => 440 * 2 ** ((m - 69) / 12); T.fakeSing({a, b: a + 6});
  for (let k = 0; k <= 75; k++) { const tt = k * .02, ref = L.targetAt(a + tt); T.livePush({t: tt, f: ref ? midiF(ref.m + 2) : null, confidence: .95, db: -18, rms: .1, peak: .2}); }
  T.fakeTick(1.52); }, tAt);
// the core of the voice line: mint inside the corridor, rose outside it (this voice is 2 semitones off, so mostly rose)
const near = (px, i, c) => Math.abs(px[i] - (c >> 16)) < 6 && Math.abs(px[i + 1] - (c >> 8 & 255)) < 6 && Math.abs(px[i + 2] - (c & 255)) < 6;
const core = (px, i) => near(px, i, 0xd9fdf4) || near(px, i, 0xdd8f97);
on = await frame(true); off = await frame(false);
let coreN = 0, coreMoved = 0; for (let i = 0; i < off.d.length; i += 4) if (core(off.d, i)) { coreN++; if (Math.abs(on.d[i] - off.d[i]) + Math.abs(on.d[i + 1] - off.d[i + 1]) + Math.abs(on.d[i + 2] - off.d[i + 2]) > 3) coreMoved++; }
dd = diff(on, off);
assert(coreN > 40 && coreMoved === 0, 'the live line paints over the dust: ' + coreMoved + ' of ' + coreN + ' core pixels changed');
assert(dd.ink > 200, 'while singing the dust is still there behind the live line (' + dd.ink + ' pixels)');
await p.evaluate(() => { window.Luma.test.fakeFinish(); window.Luma.test.closeTrace(); });
await settle(p); c = await cloud();
assert(c.ids.length === 7 && c.takes === 7, 'the take just sung joins the cloud once it is over ' + JSON.stringify(c.ids));

// ── 4 · wordless notes (WORDLESS_TARGETS.md) look and score the same with the dust behind them ─────────────────────────
// The demo without its last two lyric lines: the notes under them become one wordless chain.
const wp = await b.newPage({viewport: {width: 1440, height: 900}});
await wp.addInitScript(() => { let v; Object.defineProperty(window, 'LUMA_SONG', {configurable: true, get: () => v, set: x => { if (x && Array.isArray(x.lyrics)) x.lyrics = x.lyrics.slice(0, -2); v = x; }}); });
await wp.goto(url); await wp.waitForTimeout(600);
await wp.evaluate(`(${SEED})(5, 0, 5)`); await settle(wp);
const words = await wp.evaluate(async () => { const T = window.Luma.test, last = window.LUMA_SONG.notes.filter(n => !n.ignored).at(-1);
  T.seek(last.a - 1.5); for (let i = 0; i < 100 && (T.draw(), !T.cloud().fit); i++) await new Promise(r => setTimeout(r, 30));
  const strip = list => JSON.stringify(list.filter(e => e.kind !== 'cloud'));
  const out = {};
  for (const view of ['notes', 'contour']) { document.querySelector('[data-view="' + view + '"]').click(); await new Promise(r => setTimeout(r, 80));
    T.cloudShown(false); const off = T.noteBoxes(); T.cloudShown(true); const on = T.noteBoxes();
    out[view] = {same: strip(on) === strip(off), wordless: off.filter(e => e.kind === 'wordless').length, alpha: [...new Set(on.filter(e => e.kind === 'wordless').map(e => e.alpha))], cloud: on.some(e => e.kind === 'cloud')}; }
  const a = last.a - 1, sung = T.score(Array.from({length: 150}, (_, i) => ({songT: a + i * .02, m: T.wordless().raw(a + i * .02)?.m ?? null, confidence: .95, db: -18})), {tolerance: 50, octave: 0, view: 'notes', a}, a + 3);
  return {...out, scored: sung.target}; });
assert(words.notes.wordless > 0 && words.notes.same && words.notes.cloud, 'notes view: wordless bars are drawn exactly as without the dust ' + JSON.stringify(words.notes));
assert(words.notes.alpha.length === 1 && words.notes.alpha[0] < .6, 'wordless bars keep their one low alpha ' + JSON.stringify(words.notes.alpha));
assert(words.contour.wordless > 0 && words.contour.same, 'contour view: the wordless stretch is the same with the dust ' + JSON.stringify(words.contour));
assert(words.scored === 0, 'singing over the wordless chain still scores no frame (' + words.scored + ')');
await wp.close();

// ── 5 · frame time with 20 takes during singing, 390 px and desktop, 1× and 4× CPU throttle ──────────────────────────
// 480 frames of one sung pass, the dust hidden and shown in alternating blocks of 32, so drift in the machine hits both.
const perf = [];
for (const [width, height] of [[1440, 900], [390, 844]]) {
  const fp = await b.newPage({viewport: {width, height}, deviceScaleFactor: 2});
  await fp.goto(url); await fp.waitForTimeout(600);
  await fp.evaluate(`(${SEED})(20, 1, 7)`); await settle(fp);
  const cdp = await fp.context().newCDPSession(fp);
  for (const rate of [1, 4]) {
    await cdp.send('Emulation.setCPUThrottlingRate', {rate});
    const r = await fp.evaluate(async () => { const L = window.Luma, T = L.test, a = 2, midiF = m => 440 * 2 ** ((m - 69) / 12), res = {off: [], on: []};
      T.fakeSing({a, b: a + 30}); let pushed = 0;
      for (let k = 0; k < 480; k++) { const tt = k / 60, shown = (k >> 5) % 2 === 1; T.cloudShown(shown);
        for (; pushed * .021333 <= tt; pushed++) { const ref = L.targetAt(a + pushed * .021333); T.livePush({t: pushed * .021333, f: ref ? midiF(ref.m + .3) : null, confidence: .95, db: -18, rms: .1, peak: .2}); }
        const c0 = performance.now(); T.fakeTick(tt); (shown ? res.on : res.off).push(performance.now() - c0);
        await new Promise(r => setTimeout(r)); }
      T.fakeFinish(); T.closeTrace();
      const q = (a, f) => { const z = [...a].sort((x, y) => x - y); return +z[Math.min(z.length - 1, Math.floor(f * z.length))].toFixed(2); };
      return {offMed: q(res.off, .5), offP95: q(res.off, .95), onMed: q(res.on, .5), onP95: q(res.on, .95), specks: T.cloud().specks, builds: T.cloud().builds, misses: T.cloud().misses, layerMs: T.cloud().layerMs, layer: T.cloud().layer, dpr: T.dpr()}; });
    perf.push({width, rate, ...r});
    console.log('perf', JSON.stringify({width, rate, ...r}));
    // budget: a 60 Hz frame is 16.7 ms; the dust may add at most a quarter to the slow tail, or 1.5 ms when the tail is short
    assert(r.onP95 <= Math.max(r.offP95 * 1.25, r.offP95 + 1.5), `${width} px, ${rate}× CPU: the dust keeps the slow frames within budget (p95 ${r.offP95} → ${r.onP95} ms)`);
    assert(r.onMed <= r.offMed + 1, `${width} px, ${rate}× CPU: the typical frame costs at most 1 ms more (median ${r.offMed} → ${r.onMed} ms)`);
  }
  await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1});
  await fp.close();
}
// The build itself on a 4:30 song with 20 full takes (the history's whole window): off the main thread, and the main
// thread only packs each take once.
{
  const lp = await b.newPage({viewport: {width: 1440, height: 900}});
  await lp.goto(url); await lp.waitForTimeout(600);
  const r = await lp.evaluate(async () => { const T = window.Luma.test, S = window.LUMA_SONG; S.duration = 270;
    const pts = []; for (let t = 0; t < 270; t += .021333) pts.push({t, f: 220 * 2 ** (Math.sin(t) / 6), confidence: .9, db: -20});
    for (let k = 0; k < 20; k++) { T.closeTrace(); T.injectTake({a: 0, b: 270, points: pts, startedAt: new Date(Date.now() - k * 6e4).toISOString()}); }
    T.closeTrace(); const t0 = performance.now(); while (!T.cloud().ready) await new Promise(r => setTimeout(r, 20));
    return {wait: +(performance.now() - t0).toFixed(0), ...T.cloud(), layer: undefined, ids: undefined}; });
  console.log('build', JSON.stringify(r));
  assert(r.takes === 20 && r.specks > 20 * 12000, 'twenty 4:30 takes become ' + r.specks + ' specks in the worker (' + r.workMs + ' ms there)');
  await lp.close();
}
assert(!logs.some(l => /PAGEERROR|error:/.test(l)), 'no page errors ' + JSON.stringify(logs));
if (process.env.LUMA_SHOT) await p.screenshot({path: process.env.LUMA_SHOT});
await b.close();
