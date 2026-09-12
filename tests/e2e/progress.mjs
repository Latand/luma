// The Прогрес tab: the trend follows the ruler, the weak-phrase map moves the loop and frames it, the record shadow
// appears only where a record exists, and the day streak counts days, not open tabs. Lessons show exercises, not keys.
import {execFileSync} from 'node:child_process';
import {launch, open, window_, assert} from './lib.mjs';
const py = process.env.LUMA_PY || '.venv/bin/python';
const studio = process.env.LUMA_STUDIO_URL || 'http://127.0.0.1:8793/';
const library = process.env.LUMA_TEST_LIBRARY;
const b = await launch();
const {page: p, logs} = await open(b);
const win = await p.evaluate(w => eval(w), window_());
const hist = fn => p.evaluate(`(async () => { const H = window.Luma.test.history; return (${fn}); })()`);
const phr = await p.evaluate(() => (window.LUMA_SONG.phrases || []).map(x => ({id: x.id, a: x.a, b: x.b, label: x.label})));
assert(phr.length >= 3, 'the demo has phrases for the weak-phrase map');

// ── 1 · the trend holds exactly the attempts measured with the ruler on screen ──────────────────────────────────
const day = (n, h = 12) => { const d = new Date(); d.setDate(d.getDate() - n); d.setHours(h, 0, 0, 0); return d.toISOString(); };
const totals = await hist('H.totals()');
const whole = Math.ceil(totals.song * .97);   // a full pass: at least 95 % of the song's frames with a target
await hist(`H.seedMany([
  {match: 6000, target: ${whole}, level: 'normal', startedAt: ${JSON.stringify(day(2))}},
  {match: 7000, target: ${whole}, level: 'normal', startedAt: ${JSON.stringify(day(1))}},
  {match: 8000, target: ${whole}, level: 'normal', startedAt: ${JSON.stringify(day(0))}},
  {match: 9500, target: ${whole}, level: 'strict', startedAt: ${JSON.stringify(day(0, 13))}}
])`);
await p.evaluate(() => document.getElementById('tabProgress').click());
await p.waitForTimeout(200);
const pcts = () => hist('H.trend().map(v => Math.round(v / 100))');
let trend = await pcts();
assert(JSON.stringify(trend) === JSON.stringify([60, 70, 80]), 'the trend shows the attempts of the level on screen ' + JSON.stringify(trend));
await p.locator('[data-level="strict"]').click(); await p.waitForTimeout(200);
trend = await pcts();
assert(JSON.stringify(trend) === JSON.stringify([95]), 'switching the level switches the trend with it ' + JSON.stringify(trend));
const shown = await p.evaluate(() => ({numbers: [...document.querySelectorAll('#progressPanel .prog-num b')].map(e => e.textContent),
  ruler: document.querySelector('#progressPanel .prog-ruler').textContent,
  trendLabel: document.querySelector('#progressPanel .prog-trend').getAttribute('aria-label')}));
assert(shown.numbers.length === 4 && shown.numbers[0] === '95%' && shown.numbers[1] === '95%' && /точно/.test(shown.ruler),
  'the record and the ruler caption follow the level ' + JSON.stringify(shown));
assert(/Збіг останніх 1 спроб/.test(shown.trendLabel), 'the trend canvas reads its values out for a screen reader: ' + shown.trendLabel);
await p.locator('[data-level="normal"]').click(); await p.waitForTimeout(200);

// ── 2 · the weak-phrase map: worst first, unsung last, and a click frames the phrase before it plays ───────────
await hist(`H.seedMany([{match: 8000, target: ${whole}, phrases: [
  {id: ${phr[0].id}, target: 300, hit: 120, median: 60},
  {id: ${phr[1].id}, target: 300, hit: 285, median: 8}]}])`);
await p.waitForTimeout(200);
const weak = await hist('H.weak()');
assert(weak[0].id === phr[0].id && weak[0].best === 40 && weak[1].id === phr[1].id && weak[1].best === 95,
  'the weakest phrase is first, ranked by its personal best ' + JSON.stringify(weak.slice(0, 3)));
assert(weak.slice(2).every(w => w.best === null), 'phrases nobody has sung yet stand at the bottom');
const rowText = await p.evaluate(() => [...document.querySelectorAll('#progressPanel .prog-bar')].slice(0, 3).map(e => e.textContent));
assert(rowText[0].includes('40%') && rowText.at(-1).includes('не співано'), 'every bar carries its number, not only its colour ' + JSON.stringify(rowText));
// the bar draws the personal best and the notch the last attempt, and the title says which is which
await hist(`H.seedMany([{match: 4000, target: ${whole}, phrases: [{id: ${phr[1].id}, target: 300, hit: 90, median: 70}]}])`);
await p.waitForTimeout(250);
const moved = await p.evaluate(label => {
  const row = [...document.querySelectorAll('#progressPanel .prog-bar')].find(e => e.title.startsWith(label + ' '));
  const mark = row.querySelector('.mark');
  return {title: row.title, num: row.querySelector('.num').textContent, fill: row.querySelector('.fill').style.width,
    mark: mark && mark.style.left, markTitle: mark && mark.title};
}, phr[1].label);
assert(moved.num === '95%' && moved.fill === '95%', 'a worse recent attempt does not lower the bar of a phrase you have already nailed ' + JSON.stringify(moved));
assert(moved.mark === '30%' && /Остання спроба 30%/.test(moved.markTitle), 'the notch marks the last counted attempt ' + JSON.stringify(moved));
assert(/найкраще 95%/.test(moved.title) && /остання спроба 30%/.test(moved.title), 'the row title names both numbers: ' + moved.title);
// count every animation frame while the click lands: no note may be drawn outside the vertical range
const watch = async act => {
  await p.evaluate(() => { const w = window.__watch = {bad: 0, frames: 0};
    const step = () => { const st = window.Luma.test.state(), v = window.Luma.test.viewWindow(st.time); w.frames++;
      const oct = Number(document.getElementById('octave').value) || 0;
      if (window.LUMA_SONG.notes.some(n => !n.ignored && n.b >= v.a && n.a <= v.b && (n.m + oct < st.rangeLo || n.m + oct > st.rangeHi))) w.bad++;
      w.raf = requestAnimationFrame(step); }; w.raf = requestAnimationFrame(step); });
  await act(); await p.waitForTimeout(900);
  return p.evaluate(() => { const w = window.__watch; cancelAnimationFrame(w.raf); return {bad: w.bad, frames: w.frames}; });
};
await p.evaluate(() => { const T = window.Luma.test; T.closeTrace(); T.clearRange(); T.seek(0); });
const framed = await watch(() => p.evaluate(() => document.querySelectorAll('#progressPanel .prog-bar')[0].click()));
const after = await p.evaluate(() => window.Luma.test.state());
assert(Math.abs(after.range.a - phr[0].a) < .01 && Math.abs(after.range.b - phr[0].b) < .01, 'clicking a weak phrase sets the A–B loop on it ' + JSON.stringify(after.range));
assert(framed.bad === 0 && framed.frames > 10, 'the phrase is framed before it is played ' + JSON.stringify(framed));

// ── 3 · the record shadow: only where a record exists, and gone with the switch ────────────────────────────────
await p.evaluate(() => { const T = window.Luma.test; T.closeTrace(); T.clearRange(); });
await p.waitForTimeout(150);
assert((await hist('H.shadow()')) === null, 'no shadow while no stored attempt covers what is framed');
const dur = await p.evaluate(() => window.LUMA_SONG.duration);
const SING = `async ({a, b, off}) => { const L = window.Luma, T = L.test, midiF = m => 440 * Math.pow(2, (m - 69) / 12), pts = [];
  for (let t = 0; t < b - a; t += .02) { const ref = L.targetAt(a + t); pts.push({t, f: ref ? midiF(ref.m + off) : null, confidence: .95, db: -20}); }
  T.closeTrace(); const r = T.injectTake({a, b, points: pts}); await new Promise(r => setTimeout(r, 300)); T.closeTrace(); return r; }`;
await p.evaluate(`(${SING})({a: 0, b: ${dur}, off: 0})`);
await p.waitForTimeout(400);
const shadow = await hist('H.shadow()');
assert(shadow && shadow.points > 100, 'a stored attempt becomes the shadow of the personal best ' + JSON.stringify(shadow));
await p.locator('#shadowBtn').click(); await p.waitForTimeout(200);
assert((await hist('H.shadow()')) === null && (await p.locator('#shadowBtn').getAttribute('aria-pressed')) === 'false', 'the switch turns the shadow off');
await p.locator('#shadowBtn').click(); await p.waitForTimeout(300);
assert((await hist('H.shadow()')) !== null, 'the switch turns it back on');
// The octave is out of the comparison key, so a record sung an octave away has to follow the target, not stay behind.
// Measured as light added inside the plot rectangle with the switch on against the same frame with it off.
const plotLight = () => p.evaluate(() => {
  const T = window.Luma.test, pl = T.plot(), chart = document.getElementById('chart'), DPR = T.dpr();
  T.draw();
  const copy = document.createElement('canvas'); copy.width = chart.width; copy.height = chart.height;
  const g = copy.getContext('2d', {willReadFrequently: true}); g.drawImage(chart, 0, 0);
  const d = g.getImageData(Math.round(pl.left * DPR), Math.round(pl.top * DPR),
    Math.max(1, Math.round((pl.right - pl.left) * DPR)), Math.max(1, Math.round((pl.bottom - pl.top) * DPR))).data;
  let sum = 0; for (let i = 0; i < d.length; i += 4) sum += d[i] + d[i + 1] + d[i + 2];
  return sum;
});
const shadowInk = async () => {
  await p.waitForFunction(() => window.Luma.test.history.shadow() !== null, null, {timeout: 5000});
  const on = await plotLight();
  await p.locator('#shadowBtn').click(); await p.waitForTimeout(200);
  const off = await plotLight();
  await p.locator('#shadowBtn').click();
  await p.waitForFunction(() => window.Luma.test.history.shadow() !== null, null, {timeout: 5000});
  return on - off;
};
const straight = await shadowInk();
assert(straight > 0, 'the shadow puts ink on the plot at the octave it was sung in (' + straight + ')');
for (const oct of [-12, 12]) {
  await p.evaluate(o => { const sel = document.getElementById('octave'); sel.value = String(o); sel.dispatchEvent(new Event('change')); }, oct);
  await p.waitForTimeout(400);
  const shifted = await shadowInk();
  assert(shifted > 0, 'the shadow follows the vocal octave to ' + oct + ' instead of falling off the plot (' + shifted + ')');
}
await p.evaluate(() => { const sel = document.getElementById('octave'); sel.value = '0'; sel.dispatchEvent(new Event('change')); });
await p.waitForTimeout(300);

// ── 4 · days, not open tabs: the streak needs two minutes under a target, and the day ends at 04:00 ────────────
await p.evaluate(() => window.Luma.test.history.clearSong());
const atHour = (back, h) => { const d = new Date(); d.setDate(d.getDate() - back); d.setHours(h, 30, 0, 0); return d.toISOString(); };
await hist(`H.seedMany([
  {match: 8000, target: 6200, songTarget: 6400, startedAt: ${JSON.stringify(atHour(1, 20))}},
  {match: 8000, target: 6200, songTarget: 6400, startedAt: ${JSON.stringify(atHour(0, 2))}}
])`);
const days = await hist('H.runs().map(r => r.localDay)');
assert(days[0] === days[1], 'singing at 02:30 counts towards the evening that just passed ' + JSON.stringify(days));
assert((await hist('H.streak()')) === 1, 'two sessions on the same local day are one day of the streak');
await hist(`H.seedMany([{match: 8000, target: 6200, songTarget: 6400, startedAt: ${JSON.stringify(atHour(2, 19))}}, {match: 8000, target: 400, startedAt: ${JSON.stringify(atHour(3, 19))}}])`);
assert((await hist('H.streak()')) === 2, 'a day with under two minutes under a target does not extend the streak');

// ── 5 · a lesson shows exercises with one lamp per level, not nine keys ────────────────────────────────────────
if (library) {
  execFileSync(py, ['lessons/build_lessons.py', '--songs', library], {encoding: 'utf8', maxBuffer: 64 << 20});
  const {page: lp, logs: llogs} = await open(b, {width: 1440, height: 900}, studio + 'song/Luma_Lesson_1_Novachok.html');
  await lp.waitForFunction(() => window.Luma && window.Luma.test.history.runs);
  const ex = await lp.evaluate(() => window.Luma.test.history.exercises());
  const names = await lp.evaluate(() => [...new Set(window.LUMA_SONG.phrases.map(x => x.exercise))]);
  assert(names.length === 2 && ex.length === names.length && ex.every(r => names.includes(r.ex)),
    'the lesson groups its keys into exercises ' + JSON.stringify({names, rows: ex.map(r => r.ex)}));
  assert(ex.every(r => r.lamps.length === 3 && r.lamps.every(l => l.best === null)), 'every level lamp starts dark');
  const ids = await lp.evaluate(() => window.LUMA_SONG.phrases.filter(x => x.exercise === window.LUMA_SONG.phrases[0].exercise).map(x => x.id));
  await lp.evaluate(list => window.Luma.test.history.seedMany([{match: 9000, target: 900, level: 'easy',
    phrases: list.map(id => ({id, target: 400, hit: 360, median: 10}))}]), ids);
  await lp.evaluate(() => document.getElementById('tabProgress').click());
  await lp.waitForTimeout(250);
  const lit = await lp.evaluate(() => window.Luma.test.history.exercises()[0].lamps.map(l => l.best));
  assert(lit[0] === 90 && lit[1] === null && lit[2] === null, 'a pass on Легко lights only the Легко lamp ' + JSON.stringify(lit));
  const lamps = await lp.evaluate(() => [...document.querySelectorAll('#progressPanel .lamp')].slice(0, 3).map(e => ({text: e.textContent, on: e.classList.contains('on')})));
  assert(lamps[0].on && lamps[0].text.includes('90%') && !lamps[1].on, 'the lamp reads its number as well as its colour ' + JSON.stringify(lamps));
  assert(llogs.length === 0, 'lesson console clean ' + JSON.stringify(llogs));
  await lp.screenshot({path: 'tests/e2e/shot_progress_lesson.png'});
  await lp.close();
} else console.log('ok   lesson progress skipped: LUMA_TEST_LIBRARY is not set');

// ── 6 · the narrow layout: nothing cut off, every control named, every pair of colours readable ───────────────
for (const [width, height] of [[1440, 900], [390, 844]]) {
  await p.setViewportSize({width, height}); await p.waitForTimeout(250);
  const fit = await p.evaluate(() => ({page: document.documentElement.scrollWidth, view: innerWidth,
    cut: [...document.querySelectorAll('#progressPanel *')].filter(e => !e.hidden && e.offsetParent !== null && e.scrollWidth - e.clientWidth > 1).map(e => (e.className || e.tagName) + ' +' + (e.scrollWidth - e.clientWidth))}));
  assert(fit.page === fit.view, 'the progress tab fits ' + width + ' px');
  assert(fit.cut.length === 0, 'nothing in the progress tab is clipped at ' + width + ' px ' + JSON.stringify(fit.cut));
  const names = await p.evaluate(() => [...document.querySelectorAll('#progressPanel button, #progressPanel canvas')]
    .filter(e => e.offsetParent !== null)
    .filter(e => !(e.getAttribute('aria-label') || e.title || e.textContent.trim()).length).length);
  assert(names === 0, 'every control in the progress tab has an accessible name at ' + width + ' px');
  const contrast = await p.evaluate(() => {
    const lin = v => { v /= 255; return v <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
    const L = ([r, g, b]) => .2126 * lin(r) + .7152 * lin(g) + .0722 * lin(b);
    const rgb = s => (s.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const alpha = s => { const m = s.match(/[\d.]+/g); return m && m.length > 3 ? Number(m[3]) : 1; };
    const bg = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (alpha(c) > .9) return rgb(c); } return [11, 14, 21]; };
    const out = [];
    for (const el of document.querySelectorAll('#progressPanel *')) {
      if (el.offsetParent === null) continue;
      const text = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent.trim()).join(' ');
      if (!text) continue;
      const st = getComputedStyle(el), fore = rgb(st.color), back = bg(el);
      const ratio = (Math.max(L(fore), L(back)) + .05) / (Math.min(L(fore), L(back)) + .05);
      if (ratio < 4.5) out.push({text: text.slice(0, 28), ratio: +ratio.toFixed(2), color: st.color});
    }
    return out;
  });
  assert(contrast.length === 0, 'every line of the progress tab clears 4.5:1 at ' + width + ' px ' + JSON.stringify(contrast));
  await p.screenshot({path: 'tests/e2e/shot_progress_' + width + '.png'});
}
assert(logs.length === 0, 'console clean ' + JSON.stringify(logs));
await p.screenshot({path: process.env.LUMA_SHOT || 'shot_progress.png'});
await b.close();
