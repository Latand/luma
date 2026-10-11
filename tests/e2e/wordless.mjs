// Wordless target (docs/design/WORDLESS_TARGETS.md §4.7): in a song with words, note chains that come nowhere near a
// lyric line are drawn dimmed and never scored. The fixture is the demo package with three changes: (a) three short
// notes an octave above the melody in a 6 s gap with no lyric line, (b) a 3 s wordless chain at the melody's pitch after
// the last line, (c) a line whose first word was dropped, so its first note starts 0.8 s before the first word. A second
// build of the same notes with no lyrics shows the rule off.
import {execFileSync} from 'node:child_process';
import {copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {launch, open, assert, url} from './lib.mjs';

const py = process.env.LUMA_PY || '.venv/bin/python';
const studio = process.env.LUMA_STUDIO_URL || 'http://127.0.0.1:8793/';
const library = process.env.LUMA_TEST_LIBRARY;
const base = url.slice(0, url.lastIndexOf('/') + 1);

// ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────────────────────
const demo = JSON.parse(readFileSync('examples/demo/Demo/target.json', 'utf8'));
const A = [[15.00, 15.12, 83], [16.00, 16.14, 81], [17.00, 17.36, 84]];   // (a) bleed: 0.12 / 0.14 / 0.36 s, 12 semitones up
const B = [[30.40, 31.40, 72], [31.45, 32.40, 71], [32.45, 33.40, 69]];   // (b) a 3 s wordless chain at the melody's pitch
const C = {a: 19.34, word: 20.14, b: 20.09};                                  // (c) first note 0.8 s before the first word
const GAP = [13.26, 18.22];                                                  // the third line and its notes go
function fixture(lyrics) {
  const f = structuredClone(demo); f.id = f.sourceId = 'wordless-fixture'; f.title = 'Wordless fixture';
  f.notes = f.notes.filter(n => n.a < GAP[0] || n.a > GAP[1]);
  const first = f.notes.find(n => Math.abs(n.a - 19.52) < .01); first.a = C.a;
  let id = 100;
  for (const [a, b, m] of A) f.notes.push({id: id++, a, b, m, n: m, q: .5, ok: false, ignored: false});
  for (const [a, b, m] of B) f.notes.push({id: id++, a, b, m, n: m, q: .95, ok: true, ignored: false});
  f.notes.sort((x, y) => x.a - y.a);
  const at = t => f.notes.find(n => t >= n.a - 1e-6 && t < n.b - 1e-6);
  f.points = f.points.map(p => { const n = at(p[0]); return n ? [p[0], n.m, n.ok ? .95 : .5, n.ok ? 1 : 0] : [p[0], null, 0, 0]; });
  f.lyrics = lyrics ? demo.lyrics.filter(l => l.a < GAP[0] || l.a > GAP[1]).map(l => { if (Math.abs(l.a - 19.52) > .01) return l; const words = l.words.slice(1); return {...l, a: words[0].a, words}; }) : [];
  f.phrases = [...demo.phrases, {id: 5, a: 30.0, b: 33.5, label: 'Фрагмент 05', verified: false}];
  return f;
}
const tmp = mkdtempSync(join(tmpdir(), 'luma-wordless-')), built = [];
for (const [name, lyrics] of [['Wordless_Fixture', true], ['Wordless_NoLyrics', false]]) {
  const pkg = join(tmp, name); mkdirSync(pkg);
  for (const f of ['backing.mp3', 'backing_80.mp3', 'foreground.mp3', 'foreground_80.mp3']) copyFileSync('examples/demo/Demo/' + f, join(pkg, f));
  writeFileSync(join(pkg, 'target.json'), JSON.stringify(fixture(lyrics)));
  const out = `examples/demo/Luma_${name}.html`; execFileSync(py, ['studio/build_html.py', pkg, '-o', out]); built.push(out);
}
const withWords = base + 'Luma_Wordless_Fixture.html', noWords = base + 'Luma_Wordless_NoLyrics.html';
const inside = (t, spans) => spans.some(([a, b]) => t >= a - 1e-6 && t <= b + 1e-6);
const framesOf = spans => { const out = []; for (const [a, b] of spans) for (let t = Math.ceil(a / .02) * .02; t < b - .005; t += .02) out.push(+t.toFixed(2)); return out; };
const inA = framesOf(A), inB = framesOf(B), inC = framesOf([[C.a, C.b]]);
const idsA = [100, 101, 102], idsB = [103, 104, 105];

// The trainer's map hash before the rule, computed here: what every lesson and every song without words must keep.
const oldVersion = () => { const h = text => { let a = 0x811c9dc5, b = 0x1b873593; for (let i = 0; i < text.length; i++) { const c = text.charCodeAt(i); a = Math.imul(a ^ c, 16777619) >>> 0; b = Math.imul(b ^ (c + i), 2246822519) >>> 0; } return (a >>> 0).toString(16).padStart(8, '0') + (b >>> 0).toString(16).padStart(8, '0'); };
  const s = window.LUMA_SONG; return s.id + ':' + h(JSON.stringify(s.notes.map(n => [n.id, Math.round(n.a * 1000), Math.round(n.b * 1000), Math.round(n.m * 100), n.ignored ? 1 : 0]))); };
const setView = (p, v) => p.evaluate(v => { document.querySelector(`[data-view="${v}"]`).click(); }, v);
const targets = (p, ts) => p.evaluate(ts => ts.map(t => !!window.Luma.targetAt(t)), ts);
// A voice that sings every scored frame at its exact pitch and is silent everywhere else.
const take = (p, a, b) => p.evaluate(([a, b]) => { const L = window.Luma, T = L.test, points = [];
  for (let t = 0; t <= b - a + 1e-9; t += .01) { const ref = L.targetAt(a + t); points.push(ref ? {t, f: 440 * 2 ** ((ref.m - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t, f: null, confidence: 0, db: -60, rms: 0, peak: 0}); }
  const r = T.injectTake({a, b, points}); return {...r, score: T.score(points.map(q => ({...q, songT: a + q.t, m: q.f ? 69 + 12 * Math.log2(q.f / 440) : null})), {...T.levelOpt(), a, octave: 0, view: document.querySelector('[data-view].active').dataset.view})}; }, [a, b]);
const setLives = (p, on) => p.evaluate(on => { const c = document.getElementById('livesMode'); c.checked = on; c.dispatchEvent(new Event('change')); }, on);
// lives.mjs's driven clock: voice on every frame the page scores (or would score, with `all`), silence elsewhere
const singLives = (p, a, b, voiceOn) => p.evaluate(([a, b, voiceOn]) => { const L = window.Luma, T = L.test; T.closeTrace(); T.seek(a);
  const st = T.fakeSing({a, b}); let lost = 0;
  for (let t = 0; t <= b - a + 1e-9; t += .02) { const songT = a + t, ref = L.targetAt(songT), on = ref && eval(voiceOn)(songT);
    T.livePush(on ? {t: st.when + t, f: 440 * 2 ** ((ref.m - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: st.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0});
    if (Math.round(t * 50) % 5 === 0) T.fakeTick(st.when + t); }
  T.fakeTick(st.when + (b - a) + .3); const l = T.state().lives; lost = l.total - l.left; T.fakeFinish(); return {lost, out: l.out}; }, [a, b, voiceOn]);

const browser = await launch(), logs = [];
try {
  // ── 1 · what counts: (a) and (b) never, (c) everywhere, in both views ───────────────────────────────────────────────
  const {page: p, logs: l1} = await open(browser, {width: 1440, height: 900}, withWords); logs.push(l1);
  const w = await p.evaluate(() => { const w = window.Luma.test.wordless(); return {on: w.on, spans: w.spans, last: w.last}; });
  assert(w.on && inA.every(t => !inside(t, w.spans)) && inB.every(t => !inside(t, w.spans)) && inC.every(t => inside(t, w.spans)),
    'the rule is on and the scored spans leave out (a) and (b) and hold all of (c) ' + JSON.stringify(w.spans));
  const score = {};
  for (const view of ['notes', 'contour']) {
    await setView(p, view);
    const ta = await targets(p, inA), tb = await targets(p, inB), tc = await targets(p, inC);
    const raw = await p.evaluate(ts => ts.map(t => !!window.Luma.test.wordless().raw(t)), [...inA, ...inB]);
    assert(ta.every(x => !x) && tb.every(x => !x), `${view}: no target on any frame of (a) or (b)`);
    assert(raw.every(Boolean), `${view}: (a) and (b) are still there to draw`);
    assert(tc.every(Boolean), `${view}: every frame of (c), up to 0.8 s before its first word, is a target`);
    // ── 2 · a voice on every scored frame scores 100 %, and the wordless notes get no ✓/× ─────────────────────────────
    const t = await take(p, 0, 33.4);
    score[view] = t.score.target;
    const marked = new Set(t.score.notes.map(([id]) => id));
    assert(t.pct === 100 && t.score.pct === 100, `${view}: silence on (a) and (b) and every scored frame hit gives 100 % (${t.pct})`);
    assert([...idsA, ...idsB].every(id => !marked.has(id)), `${view}: no wordless note collects a frame, so none can get a ✓ or ×`);
    for (const [label, at, ids, span] of [['(a)', 16.0, idsA, [A[0][0], A[2][1]]], ['(b)', 31.9, idsB, [B[0][0], B[2][1]]]]) {
      await p.evaluate(at => { window.Luma.test.seek(at); }, at);
      const boxes = await p.evaluate(() => window.Luma.test.noteBoxes());
      const dim = boxes.filter(b => b.kind === 'wordless');
      if (view === 'notes') {
        const mine = boxes.filter(b => ids.includes(b.id));
        assert(mine.length === ids.length && mine.every(b => b.kind === 'wordless' && b.alpha < .5), `notes: ${label} is drawn dimmed, with no ✓ or × ` + JSON.stringify(mine.map(b => [b.id, b.kind, b.alpha])));
      } else assert(dim.length > 0 && dim.every(b => b.alpha < .5) && dim.some(b => b.a <= span[0] + .03 && b.b >= span[0]) && dim.every(b => b.a >= span[0] - .03 || b.b <= span[1] + .03),
        `contour: ${label} is drawn dimmed ` + JSON.stringify(dim.map(b => [b.a, b.b, b.alpha])));
    }
    await p.evaluate(() => window.Luma.test.closeTrace());
  }
  // ── 4 · the readout names the reason ────────────────────────────────────────────────────────────────────────────────
  await setView(p, 'notes');
  const readout = await p.evaluate(() => { const T = window.Luma.test; T.seek(31.5); T.draw(); const a = T.state().deviation; T.seek(9.9); T.draw(); return [a, T.state().deviation]; });
  assert(readout[0] === 'Без слів — не рахується', 'the readout over (b) says «Без слів — не рахується»: ' + readout[0]);
  assert(readout[1] === 'Тут ціль не визначена', 'a gap with nothing drawn keeps «Тут ціль не визначена»: ' + readout[1]);
  // LUMA_SHOT_WORDLESS=1: the playhead inside (a) and inside (b), both views, desktop and 390 px
  if (process.env.LUMA_SHOT_WORDLESS) {
    for (const [vw, vh] of [[1440, 900], [390, 844]]) {
      await p.setViewportSize({width: vw, height: vh}); await p.waitForTimeout(250);
      for (const view of ['notes', 'contour']) for (const [tag, at] of [['a', 17.15], ['b', 31.2]]) {
        await setView(p, view); await p.evaluate(at => { const T = window.Luma.test; T.closeTrace(); T.seek(at); T.draw(); }, at); await p.waitForTimeout(150);
        await p.screenshot({path: `tests/e2e/shot_wordless_${view}_${tag}_${vw}.png`}); }
    }
    await p.setViewportSize({width: 1440, height: 900}); await setView(p, 'notes');
  }
  // ── 9 · a pass ends at the last scored note + 0.5 s, not after the wordless tail ────────────────────────────────────
  const end = await p.evaluate(() => window.Luma.song().singEnd);
  assert(Math.abs(end - (w.last + .5)) < 1e-6 && Math.abs(end - 29.96) < .01, 'singEnd is the last scored note + 0.5 s, before the wordless tail: ' + end);
  // ── 8 · the weak-phrase map calls the phrase over (b) «без слів», outside the unsung count ──────────────────────────
  await p.evaluate(() => document.getElementById('tabProgress').click()); await p.waitForTimeout(250);
  const map = await p.evaluate(() => { const c = document.querySelector('#progressPanel .prog-col[data-phrase="5"]'), sum = [...document.querySelectorAll('#progressPanel .prog-note')].find(e => e.textContent.startsWith('Зараховано'));
    return {title: c?.title, cls: c?.querySelector('.col').className, sum: sum?.textContent, legend: document.querySelector('#progressPanel .prog-legend')?.textContent, others: [...document.querySelectorAll('#progressPanel .prog-col')].filter(e => e.dataset.phrase !== '5').map(e => e.querySelector('.col').className)}; });
  assert(/без слів — не рахується/.test(map.title) && /wordless/.test(map.cls), 'phrase 5 over (b) reads «без слів» on the weak-phrase map: ' + map.title);
  assert(map.others.every(c => !/wordless/.test(c)), 'phrases with words are not marked wordless');
  const [, counted, all, unsung] = (/Зараховано (\d+) з (\d+) · без зарахованої спроби: (\d+)/.exec(map.sum) || []).map(Number), short = +(/закоротких для рекорду: (\d+)/.exec(map.sum) || [0, 0])[1];
  assert(/· без слів: 1/.test(map.sum) && counted + unsung + short + 1 === all && /без слів — не рахується/.test(map.legend), 'the summary counts it apart from unsung phrases: ' + map.sum);
  // the column and its key read apart from «не співано» without a hover: a bare rule in place of the dashed box, the dash dimmed
  const look = await p.evaluate(() => { const st = e => e && getComputedStyle(e), q = s => document.querySelector('#progressPanel ' + s);
    const col = st(q('.prog-col[data-phrase="5"] .col')), v = st(q('.prog-col[data-phrase="5"] .v')), key = st(q('.prog-legend i.wordless')), none = st(q('.prog-legend i.none'));
    return {col: [col.borderTopStyle, col.backgroundImage.startsWith('linear-gradient'), +col.opacity], v: +v.opacity, key: [key.borderTopStyle, key.backgroundImage.startsWith('linear-gradient'), +key.opacity], none: none.borderTopStyle}; });
  assert(look.col[0] === 'none' && look.col[1] && look.col[2] === 1 && look.v < 1 && look.key[0] === 'none' && look.key[1] && look.key[2] === 1 && look.none === 'dashed',
    'a wordless column and its legend key are a full-strength rule with a dimmed dash, unlike the dashed «не співано» box: ' + JSON.stringify(look));
  // ── 3 · lives: a voice on the words keeps every life across (b) ─────────────────────────────────────────────────────
  await p.evaluate(() => document.getElementById('tabTakes')?.click());
  await setLives(p, true);
  const kept = await singLives(p, 24.0, 33.4, '() => true');
  assert(kept.lost === 0, 'lives mode: silence over the 3 s wordless chain costs no life (' + kept.lost + ' lost)');
  const v1 = await p.evaluate(() => window.Luma.test.history.mapVersion());
  assert(!l1.length, 'console clean on the fixture ' + JSON.stringify(l1));
  await p.close();

  // ── 6 · the same notes with no lyrics score (a) and (b) as before; lives notice (b) there ───────────────────────────
  const {page: q, logs: l2} = await open(browser, {width: 1440, height: 900}, noWords); logs.push(l2);
  const off = await q.evaluate(() => window.Luma.test.wordless().on);
  assert(off === false, 'with no lyrics the rule is off');
  for (const view of ['notes', 'contour']) {
    await setView(q, view);
    const ta = await targets(q, inA), tb = await targets(q, inB);
    assert(ta.every(Boolean) && tb.every(Boolean), `${view}: with no lyrics every frame of (a) and (b) is a target`);
    const t = await q.evaluate(() => { const L = window.Luma, T = L.test, pts = []; for (let t = 0; t <= 33.4 + 1e-9; t += .01) pts.push({t, songT: t, f: null, m: null, confidence: 0}); return T.score(pts, {...T.levelOpt(), a: 0, octave: 0, view: document.querySelector('[data-view].active').dataset.view}).target; });
    const extra = view === 'notes' ? inA.length + inB.length : null;
    assert(t > score[view] && (extra === null || Math.abs(t - score[view] - extra) <= 4), `${view}: (a) and (b) add their frames back to the denominator (${score[view]} → ${t})`);
  }
  await setView(q, 'notes');
  const v2 = await q.evaluate(() => window.Luma.test.history.mapVersion()), v2old = await q.evaluate(oldVersion);
  assert(v1 !== v2, 'the fixture with words has a different mapVersion from the same notes with the rule off');
  assert(v2 === v2old, 'with the rule off the mapVersion is the hash it always was');
  await setLives(q, true);
  const lost = await singLives(q, 24.0, 33.4, '(t) => t < 30.0');
  assert(lost.lost >= 1, 'with the rule off, the same silence over (b) costs a life (' + lost.lost + '): the lives check can fail');
  const end2 = await q.evaluate(() => window.Luma.song().singEnd);
  assert(Math.abs(end2 - 33.5) < .01, 'with the rule off the pass still runs to the last note: ' + end2);
  assert(!l2.length, 'console clean on the no-lyrics build ' + JSON.stringify(l2));
  await q.close();

  // ── 5 · the demo has words, so its ruler changes too ────────────────────────────────────────────────────────────────
  const {page: d, logs: l3} = await open(browser, {width: 1440, height: 900}, url); logs.push(l3);
  const dv = await d.evaluate(() => [window.Luma.test.history.mapVersion(), window.Luma.test.wordless().on]), dold = await d.evaluate(oldVersion);
  assert(dv[1] && dv[0] !== dold, 'the demo has lyrics: the rule is on and its mapVersion changed once');
  assert(!l3.length, 'console clean on the demo ' + JSON.stringify(l3));
  await d.close();

  // ── 7 · lessons: rule off, mapVersion unchanged ─────────────────────────────────────────────────────────────────────
  if (library) {
    if (!existsSync(`${library}/Luma_Lesson_1_Novachok.html`)) execFileSync(py, ['lessons/build_lessons.py', '--songs', library], {maxBuffer: 64 << 20});
    const defs = JSON.parse(execFileSync(py, ['lessons/build_lessons.py', '--definitions'], {encoding: 'utf8', maxBuffer: 64 << 20}));
    for (const lesson of defs.lessons) {
      const {page: lp, logs: l4} = await open(browser, {width: 1440, height: 900}, studio + 'song/' + lesson.file); logs.push(l4);
      const r = await lp.evaluate(() => [window.Luma.test.history.mapVersion(), window.Luma.test.wordless().on]), old = await lp.evaluate(oldVersion);
      assert(r[1] === false && r[0] === old, `${lesson.id}: the rule is off and the mapVersion is unchanged`);
      assert(!l4.length, `${lesson.id}: console clean ` + JSON.stringify(l4));
      await lp.close();
    }
  } else console.log('ok   lesson mapVersion check skipped: LUMA_TEST_LIBRARY is not set');
} catch (e) { console.error('FAIL', e); process.exitCode = 1; }
finally { await browser.close(); for (const f of built) rmSync(f, {force: true}); rmSync(tmp, {recursive: true, force: true}); }
