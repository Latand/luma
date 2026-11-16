// Scream stretches (docs/TARGET_MAP_SCHEMA.md «unpitched»): a span of kind "scream" is drawn as a band with the word «скрим»
// and holds no target; a span of kind "noise" draws nothing; neither is scored, costs a life or counts as silence. The
// fixture is the demo package with a scream over 13.86–16.37 s (three notes) and a noise over 21.37–21.99 s (one note);
// both edges stand in the gaps between the demo's notes:
//   S  the list, the notes and contour points inside the spans removed: the shape the tools write
//   X  the list over the demo's unchanged notes: the trainer must still show and score no target there
//   N  no list, the same notes removed: «the same take without it»
//   E  an empty list on the demo, against the demo itself: nothing changes
// LUMA_SHOT_SCREAM=<dir> also saves screenshots of the band in both views at 1440×900 and 390×844: idle, while a take is
// sung through it, and in the review of that take.
import {execFileSync} from 'node:child_process';
import {copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {launch, open, assert, url} from './lib.mjs';

const py = process.env.LUMA_PY || '.venv/bin/python';
const base = url.slice(0, url.lastIndexOf('/') + 1);
const demo = JSON.parse(readFileSync('examples/demo/Demo/target.json', 'utf8'));
const SCREAM = [13.86, 16.37], NOISE = [21.37, 21.99], MID = 15.1;
const LIST = [{a: SCREAM[0], b: SCREAM[1], kind: 'scream'}, {a: NOISE[0], b: NOISE[1], kind: 'noise'}];
const inside = (t, [a, b]) => t >= a && t < b;
const inAny = t => inside(t, SCREAM) || inside(t, NOISE);

function fixture(name, {list, strip}) {
  const f = structuredClone(demo); f.id = f.sourceId = 'scream-' + name; f.title = 'Scream ' + name;
  if (strip) {
    f.notes = f.notes.filter(n => !inAny((n.a + n.b) / 2));
    f.points = f.points.map(p => inAny(p[0]) ? [p[0], null, 0, 0] : p);
  }
  if (list) f.unpitched = list;
  return f;
}
const tmp = mkdtempSync(join(tmpdir(), 'luma-scream-')), built = [];
const kinds = {S: {list: LIST, strip: true}, X: {list: LIST, strip: false}, N: {list: null, strip: true}, E: {list: [], strip: false}};
for (const [name, opts] of Object.entries(kinds)) {
  const pkg = join(tmp, 'Scream_' + name); mkdirSync(pkg);
  for (const f of ['backing.mp3', 'backing_80.mp3', 'foreground.mp3', 'foreground_80.mp3']) copyFileSync('examples/demo/Demo/' + f, join(pkg, f));
  writeFileSync(join(pkg, 'target.json'), JSON.stringify(fixture(name, opts)));
  const out = `examples/demo/Luma_Scream_${name}.html`; execFileSync(py, ['studio/build_html.py', pkg, '-o', out]); built.push(out);
}
const page = name => base + `Luma_Scream_${name}.html`;

// One voice for every page: the demo's melody on its own notes, a hard confident 700 Hz wherever the spans are (or silence).
const demoNotes = demo.notes.filter(n => !inAny((n.a + n.b) / 2));
const pointsFor = (a, b, silentInSpan = false) => { const out = [];
  for (let t = 0; t <= b - a + 1e-9; t += .01) { const s = a + t, n = demoNotes.find(n => s >= n.a && s < n.b);
    out.push(inAny(s) ? (silentInSpan ? {t, f: null, confidence: 0, db: -60} : {t, f: 700, confidence: .95, db: -10}) : n ? {t, f: 440 * 2 ** ((n.m - 69) / 12), confidence: .95, db: -20} : {t, f: null, confidence: 0, db: -60}); }
  return out; };
const setView = (p, v) => p.evaluate(v => { document.querySelector(`[data-view="${v}"]`).click(); }, v);
const score = (p, points, a) => p.evaluate(([points, a]) => { const T = window.Luma.test; const r = T.score(points.map(q => ({...q, songT: a + q.t, m: q.f ? 69 + 12 * Math.log2(q.f / 440) : null})), {...T.levelOpt(), a, octave: 0, view: document.querySelector('[data-view].active').dataset.view});
  let h = 0; for (const f of r.frames) h = (Math.imul(h, 31) + f) | 0; return {target: r.target, hit: r.hit, sung: r.sung, pct: r.pct, frames: r.frames.length, hash: h}; }, [points, a]);
const seek = (p, t) => p.evaluate(t => { const T = window.Luma.test; T.closeTrace(); T.seek(t); T.draw(); }, t);
const boxes = p => p.evaluate(() => window.Luma.test.noteBoxes());
// the canvas read back in CSS pixels: [x, y, w, h] → a flat RGBA array (the page's own pixels, at its device scale)
const pixels = (p, [x, y, w, h]) => p.evaluate(([x, y, w, h]) => { const c = document.getElementById('chart'), d = window.Luma.test.dpr(); return Array.from(c.getContext('2d').getImageData(Math.round(x * d), Math.round(y * d), Math.round(w * d), Math.round(h * d)).data); }, [x, y, w, h]);
const canvasHash = p => p.evaluate(() => { const c = document.getElementById('chart'), im = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let h = 2166136261; for (let i = 0; i < im.length; i++) h = Math.imul(h ^ im[i], 16777619) >>> 0; return h; });
const chartSize = p => p.evaluate(() => { const c = document.getElementById('chart'); return [c.width / window.Luma.test.dpr(), c.height / window.Luma.test.dpr()]; });
const swing = row => { const lum = []; for (let i = 0; i < row.length; i += 4) lum.push(row[i] + row[i + 1] + row[i + 2]); return Math.max(...lum) - Math.min(...lum); };
// pixels that differ between two pages' canvases, split by whether they fall inside a box
async function diff(p, q, box) {
  const [w, h] = await chartSize(p), a = await pixels(p, [0, 0, w, h]), b = await pixels(q, [0, 0, w, h]), d = await p.evaluate(() => window.Luma.test.dpr());
  const out = {inside: 0, outside: 0, out: null};
  for (let i = 0; i < a.length; i += 4) if (a[i] !== b[i] || a[i + 1] !== b[i + 1] || a[i + 2] !== b[i + 2]) {
    const px = (i / 4) % Math.round(w * d) / d, py = Math.floor(i / 4 / Math.round(w * d)) / d;
    if (px >= box.x - 2 && px <= box.x + box.w + 2 && py >= box.y - 2 && py <= box.y + box.h + 2) out.inside++; else { out.outside++; out.out ??= [px, py]; } }
  return out;
}
// the page's sung voice from `from` to `to`, on a clock the test drives; the take stays open, so a later call carries on
const sing = (p, a, b, from, to, silent = false) => p.evaluate(([a, b, from, to, silent, SCREAM, NOISE]) => { const L = window.Luma, T = L.test;
  if (from === a) { T.closeTrace(); T.seek(a); window.__sing = T.fakeSing({a, b}); if (!window.__sing) return null; }
  const st = window.__sing;
  for (let t = from - a; t <= to - a + 1e-9; t += .02) { const songT = a + t, ref = L.targetAt(songT), inSpan = (songT >= SCREAM[0] && songT < SCREAM[1]) || (songT >= NOISE[0] && songT < NOISE[1]);
    T.livePush(inSpan ? (silent ? {t: st.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0} : {t: st.when + t, f: 700 + 90 * Math.sin(t * 25), confidence: .95, db: -8, rms: .3, peak: .6}) : ref ? {t: st.when + t, f: 440 * 2 ** ((ref.m - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: st.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0});
    if (Math.round(t * 50) % 5 === 0) T.fakeTick(st.when + t); }
  T.fakeTick(st.when + (to - a)); const s = T.state().liveScore; return s ? {target: s.target, hit: s.hit, sung: s.sung} : null; }, [a, b, from, to, silent, SCREAM, NOISE]);
const finishSing = p => p.evaluate(() => { const T = window.Luma.test, r = T.fakeFinish(); if (r) T.selectTake(r.id); return r; });

const browser = await launch(), logs = [];
const quiet = l => l.filter(m => !/willReadFrequently/.test(m));
try {
  const shotDir = process.env.LUMA_SHOT_SCREAM; if (shotDir) mkdirSync(shotDir, {recursive: true});
  const pages = {};
  for (const [k, u] of [['S', page('S')], ['N', page('N')], ['X', page('X')]]) { const {page: p, logs: l} = await open(browser, {width: 1440, height: 900}, u); pages[k] = p; logs.push(l); }
  const {S, N, X} = pages;

  // ── 1 · no target in a span, on any frame, in either view and in raw drawing; none elsewhere is lost ─────────────────
  for (const [tag, p] of [['S', S], ['X', X]]) for (const view of ['notes', 'contour']) {
    await setView(p, view);
    const r = await p.evaluate(([spans]) => { const L = window.Luma, bad = []; let kept = 0; for (let t = 0; t < L.song().duration; t += .02) { const inSpan = spans.some(([a, b]) => t >= a && t < b), eff = !!L.targetAt(t), raw = !!L.test.wordless().raw(t);
      if (inSpan && (eff || raw)) bad.push(+t.toFixed(2)); if (!inSpan && eff) kept++; } return {bad: bad.length, first: bad[0], kept}; }, [[SCREAM, NOISE]]);
    assert(r.bad === 0 && r.kept > 600, `${tag} ${view}: no target, raw or scored, on any 20 ms frame of either span (${r.bad} found${r.bad ? ' from ' + r.first : ''}); ${r.kept} frames elsewhere keep one`);
  }
  assert(await X.evaluate(([a, b]) => window.LUMA_SONG.notes.every(n => { const m = (n.a + n.b) / 2; return !(m >= a[0] && m < a[1]) && !(m >= b[0] && m < b[1]); }), [SCREAM, NOISE]), 'X: the notes the list covers are dropped when the song opens');

  // ── 2 · the band and its word are drawn for the scream only, in both views ───────────────────────────────────────────
  for (const [tag, p] of [['S', S], ['X', X]]) for (const view of ['notes', 'contour']) {
    await setView(p, view); await seek(p, MID);
    const all = await boxes(p), bs = all.filter(b => b.kind === 'scream');
    assert(bs.length === 1 && bs[0].label === 'скрим' && Math.abs(bs[0].a - SCREAM[0]) < 1e-6 && Math.abs(bs[0].b - SCREAM[1]) < 1e-6, `${tag} ${view}: one band over the scream, labelled «скрим» ` + JSON.stringify(bs.map(b => [b.a, b.b, b.label])));
    const hit = all.filter(b => b.kind !== 'scream' && b.id !== undefined && b.x < bs[0].x + bs[0].w - 1 && b.x + b.w > bs[0].x + 1);
    assert(hit.length === 0, `${tag} ${view}: no note is drawn inside the band ` + JSON.stringify(hit.map(b => [b.id, b.kind])));
    await seek(p, 21.7);
    assert((await boxes(p)).every(b => b.kind !== 'scream'), `${tag} ${view}: the noise span draws no band`);
  }
  await setView(N, 'notes'); await seek(N, MID);
  assert((await boxes(N)).every(b => b.kind !== 'scream'), 'no band without the list');

  // ── 3 · the band is on the canvas: only its pixels differ from the same moment without the list ───────────────────────
  for (const view of ['notes', 'contour']) {
    await setView(S, view); await setView(N, view); await seek(S, MID); await seek(N, MID);
    const band = (await boxes(S)).find(b => b.kind === 'scream'), pl = await S.evaluate(() => window.Luma.test.plot()), d = await diff(S, N, band);
    assert(d.inside > 800 && d.outside === 0, `${view}: the band is painted (${d.inside} px differ inside it) and nothing else on the canvas differs (${d.outside} elsewhere${d.out ? ' e.g. at ' + d.out : ''})`);
    assert(band.y >= pl.top && band.y + band.h <= pl.bottom, `${view}: the band stands inside the plot (${band.y.toFixed(0)}–${(band.y + band.h).toFixed(0)} of ${pl.top.toFixed(0)}–${pl.bottom.toFixed(0)})`);
    const sw = swing(await pixels(S, [band.x + 4, band.y + 3, Math.min(band.w - 8, 60), 1]));
    assert(sw >= 30, `${view}: the band carries vertical strokes: a row across it swings ${sw}`);
  }

  // ── 4 · the pitch scale does not react: a fixed height whatever the scale does, the scale as without the list ─────────
  await setView(S, 'notes'); await setView(N, 'notes'); await setView(X, 'notes');
  const heights = [];
  for (const t of [14.5, 15.1, 16.0]) { await seek(S, t); heights.push((await boxes(S)).find(b => b.kind === 'scream').y); }
  assert(heights.every(h => h === heights[0]), 'the band keeps one height while the roll moves ' + JSON.stringify(heights));
  for (const t of [3, 9, 15.3, 19, 26]) { await seek(S, t); await seek(N, t); await seek(X, t);
    const [a, b, c] = await Promise.all([S, N, X].map(p => p.evaluate(() => window.Luma.test.scale())));
    assert(a.goalLo === b.goalLo && a.goalHi === b.goalHi && a.goalLo === c.goalLo && a.goalHi === c.goalHi, `the pitch scale at ${t} s is the one without the list (${a.goalLo.toFixed(2)}–${a.goalHi.toFixed(2)})`); }

  // ── 5 · scoring over the span equals the same take without it ───────────────────────────────────────────────────────
  const {page: D, logs: lD} = await open(browser, {width: 1440, height: 900}, url); logs.push(lD);
  for (const view of ['notes', 'contour']) {
    for (const p of [S, N, X, D]) await setView(p, view);
    const pts = pointsFor(0, 33.4), r = {};
    for (const [k, p] of [['S', S], ['N', N], ['X', X], ['D', D]]) r[k] = await score(p, pts, 0);
    assert(JSON.stringify(r.S) === JSON.stringify(r.N) && JSON.stringify(r.X) === JSON.stringify(r.N), `${view}: a voice on every note and a scream through the spans scores as without a target there ` + JSON.stringify(r));
    assert(r.D.target > r.S.target && r.D.pct !== r.S.pct, `${view}: the unchanged demo, with notes under the scream, scores differently (${r.D.target} frames, ${r.D.pct} %): the comparison can fail`);
    const sil = pointsFor(0, 33.4, true), q = {};
    for (const [k, p] of [['S', S], ['N', N], ['X', X]]) q[k] = await score(p, sil, 0);
    assert(JSON.stringify(q.S) === JSON.stringify(q.N) && JSON.stringify(q.X) === JSON.stringify(q.N) && q.S.pct >= 99, `${view}: silence in the spans is not a miss ` + JSON.stringify(q));
    const dq = await score(D, sil, 0); assert(dq.pct < q.S.pct, `${view}: the same silence over the demo's notes is a miss (${dq.pct} against ${q.S.pct} %)`);
  }
  // per-phrase results and the history record, through a stored attempt
  const histRun = async (p, pts) => { await p.evaluate(pts => { const T = window.Luma.test; T.closeTrace(); T.injectTake({a: 0, b: 33.4, points: pts}); }, pts); await p.waitForTimeout(400);
    return p.evaluate(() => { const r = window.Luma.test.history.runs().at(-1); return {match: r.match, target: r.target, hit: r.hit, sung: r.sung, phrases: r.phrases.map(c => [c.id, c.target, c.hit, c.match])}; }); };
  const hp = pointsFor(0, 33.4), hS = await histRun(S, hp), hN = await histRun(N, hp), hX = await histRun(X, hp), hD = await histRun(D, hp);
  assert(hS.target > 0 && JSON.stringify(hS) === JSON.stringify(hN) && JSON.stringify(hX) === JSON.stringify(hN), 'the history record and its per-phrase results equal those of the same take without the spans ' + JSON.stringify(hS));
  assert(JSON.stringify(hD) !== JSON.stringify(hN), 'the demo with notes under the scream records another result: the comparison can fail ' + JSON.stringify(hD.phrases));
  // lives: silence over the scream costs nothing; over the demo's notes it does
  const lives = (p, a, b) => p.evaluate(([a, b, SCREAM]) => { const c = document.getElementById('livesMode'); c.checked = true; c.dispatchEvent(new Event('change'));
    const L = window.Luma, T = L.test; T.closeTrace(); T.seek(a); const st = T.fakeSing({a, b});
    for (let t = 0; t <= b - a + 1e-9; t += .02) { const songT = a + t, ref = L.targetAt(songT), on = ref && !(songT >= SCREAM[0] && songT < SCREAM[1]);
      T.livePush(on ? {t: st.when + t, f: 440 * 2 ** ((ref.m - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: st.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0});
      if (Math.round(t * 50) % 5 === 0) T.fakeTick(st.when + t); }
    T.fakeTick(st.when + (b - a) + .3); const l = T.state().lives; const lost = l.total - l.left; T.fakeFinish(); return lost; }, [a, b, SCREAM]);
  const lostS = await lives(S, 11, 19), lostN = await lives(N, 11, 19), lostX = await lives(X, 11, 19), lostD = await lives(D, 11, 19);
  assert(lostS === 0 && lostN === 0 && lostX === 0, `lives mode: silence over the scream costs no life (${lostS} lost; ${lostX} with notes under it; ${lostN} without the list)`);
  assert(lostD >= 1, `lives mode: the same silence over the demo's notes costs a life (${lostD}): the check can fail`);
  // a take that sang through the scream: the live score has the same frames as without the spans
  const liveS = await sing(S, 12.5, 19, 12.5, 19), liveN = await sing(N, 12.5, 19, 12.5, 19);
  if (liveS) await finishSing(S); if (liveN) await finishSing(N);
  assert(liveS && liveN && JSON.stringify(liveS) === JSON.stringify(liveN) && liveS.target > 0, 'a take sung through the scream counts the frames it counts without the spans ' + JSON.stringify([liveS, liveN]));
  const mS = await S.evaluate(() => window.Luma.test.history.mapVersion()), mN = await N.evaluate(() => window.Luma.test.history.mapVersion());
  assert(mS !== mN, 'the spans are part of the ruler, so scores with and without them are never compared');

  // ── 6 · the singer's line is still drawn over the span, in live and in review ─────────────────────────────────────────
  {
    await setView(S, 'notes'); const id = await S.evaluate(() => window.Luma.test.takes().at(-1).id);
    await S.evaluate(id => { const T = window.Luma.test; T.closeTrace(); T.seek(15.1); T.draw(); }, id);
    const band = (await boxes(S)).find(b => b.kind === 'scream'), before = await pixels(S, [band.x, 150, band.w, 450]);
    await S.evaluate(id => { const T = window.Luma.test; T.selectTake(id); T.seek(15.1); T.draw(); }, id);
    const after = await pixels(S, [band.x, 150, band.w, 450]); let n = 0; for (let i = 0; i < after.length; i += 4) if (after[i] !== before[i] || after[i + 1] !== before[i + 1]) n++;
    assert(n > 300, `in review the singer's line is drawn across the span (${n} px of it)`);
    await S.evaluate(() => window.Luma.test.closeTrace());
  }

  // ── 7 · a song with no list, or an empty list, is the song as it was: fresh pages, so no take adds dust to one ───────
  {
    const {page: D2, logs: l1} = await open(browser, {width: 1440, height: 900}, url), {page: E, logs: l2} = await open(browser, {width: 1440, height: 900}, page('E')); logs.push(l1, l2);
    const same = [];
    for (const view of ['notes', 'contour']) for (const t of [3, 9.3, 15.3, 22, 28]) { await setView(D2, view); await setView(E, view); await seek(D2, t); await seek(E, t); same.push(await canvasHash(D2) === await canvasHash(E)); }
    assert(same.every(Boolean), 'an empty list draws the canvas pixel for pixel as the demo with no list: both views, five moments');
    assert(await D2.evaluate(() => document.getElementById('legendScream').hidden) && await E.evaluate(() => document.getElementById('legendScream').hidden), 'no scream in the legend of a song without spans');
    await D2.close(); await E.close();
  }
  assert(!(await S.evaluate(() => document.getElementById('legendScream').hidden)) && (await S.evaluate(() => document.getElementById('legendScream').textContent.trim())) === 'скрим', 'the legend names the band, «скрим», when the song has one');
  assert(/«скрим»[^.]*крик без висоти/.test(await S.evaluate(() => document.body.textContent)), 'the help explains the band in Ukrainian');

  // ── 8 · phone width ─────────────────────────────────────────────────────────────────────────────────────────────────
  await S.setViewportSize({width: 390, height: 844}); await S.waitForTimeout(300);
  for (const view of ['notes', 'contour']) {
    await setView(S, view); await seek(S, MID);
    const all = await boxes(S), bs = all.filter(b => b.kind === 'scream'), pl = await S.evaluate(() => window.Luma.test.plot());
    assert(bs.length === 1 && bs[0].label === 'скрим', `390 px ${view}: the band and its word are drawn`);
    const b = bs[0], v0 = Math.max(b.x, pl.left), v1 = Math.min(b.x + b.w, pl.right);
    assert(b.tx >= v0 - 1 && b.tx + b.tw <= v1 + 1, `390 px ${view}: the word stands inside the band and the plot (${b.tx.toFixed(0)}–${(b.tx + b.tw).toFixed(0)} of ${v0.toFixed(0)}–${v1.toFixed(0)})`);
    assert(b.y >= pl.top && b.y + b.h <= pl.bottom, `390 px ${view}: the band stands inside the plot`);
    assert(all.filter(q => q.kind !== 'scream' && q.id !== undefined && q.x < b.x + b.w - 1 && q.x + q.w > b.x + 1).length === 0, `390 px ${view}: no note is drawn inside the band`);
    assert(swing(await pixels(S, [Math.max(b.x, pl.left) + 3, b.y + 3, 30, 1])) >= 30, `390 px ${view}: the strokes show`);
    const w = await S.evaluate(() => [document.documentElement.scrollWidth, innerWidth]); assert(w[0] === w[1], `390 px ${view}: the page is as wide as the viewport (${w})`);
    // the band walks in at the right edge and out at the left: its word is whole inside the plot at every step, or absent
    const seen = []; let bad = 0;
    for (let t = 6; t <= 26; t += .25) { await seek(S, t); for (const q of (await boxes(S)).filter(q => q.kind === 'scream')) { seen.push(t); if (q.tx < pl.left || q.tx + q.tw > pl.right) bad++; } }
    assert(seen.length > 20 && bad === 0, `390 px ${view}: the word stays inside the plot while the band scrolls past it (${seen.length} frames, ${bad} cut)`);
  }
  await S.setViewportSize({width: 1440, height: 900}); await S.waitForTimeout(300);

  // ── 9 · screenshots: idle, sung through, in review; both views at 1440×900 and 390×844 ───────────────────────────────
  if (shotDir) for (const [vw, vh] of [[1440, 900], [390, 844]]) for (const view of ['notes', 'contour']) {
    const {page: P, logs: l} = await open(browser, {width: vw, height: vh}, page('S')); logs.push(l);   // a fresh page: no dust of earlier takes
    await setView(P, view); await seek(P, MID); await P.waitForTimeout(150); await P.screenshot({path: join(shotDir, `idle_${view}_${vw}.png`)});
    const live = await sing(P, 12.5, 19, 12.5, MID); await P.waitForTimeout(150); await P.screenshot({path: join(shotDir, `sung_${view}_${vw}.png`)});
    await sing(P, 12.5, 19, MID, 19);   // the rest of the pass, then the review of that take at the same moment
    await finishSing(P); await P.evaluate(() => { const T = window.Luma.test; T.seek(15.1); T.draw(); }); await P.waitForTimeout(150); await P.screenshot({path: join(shotDir, `review_${view}_${vw}.png`)});
    assert(live && live.target > 0, `${vw} px ${view}: a take was sung through the band for the screenshots`);
    await P.close();
  }
  assert(logs.every(l => quiet(l).length === 0), 'console clean ' + JSON.stringify(logs.map(quiet)));
} catch (e) { console.error('FAIL', e); process.exitCode = 1; }
finally { await browser.close(); for (const f of built) rmSync(f, {force: true}); rmSync(tmp, {recursive: true, force: true}); }
