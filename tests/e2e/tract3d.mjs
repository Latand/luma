// «Голова» (app/tract3d.js; docs/design/VOCAL_TRACT_3D.md §9.1, slice 1): the head cut along its midline beside the
// roll, which shows how to sing what is due now. Fixtures are the built-in lesson 1 (built here into an empty library),
// the synthetic demo and a made-up word put into a copy of the demo's package; nothing else.
//   1  the column beside the roll at 1440 px (the roll's right edge and every word left of it; the chosen head marked as
//      the roll's chosen view), at 900 px with the whole head; the overlay on the sung part at 390 px (no word on it, the
//      playhead and the next 2 s of notes clear of it, the body's tag in its corner, a ✕ when enlarged; before a choice
//      the two buttons and the prompt each whole)
//   2  «Чоловік» / «Жінка» survive a reload; the body's scale; the two heads' outlines differ
//   3  lesson 1 on «ма»: after the rest the /m/ long enough to be seen (nasal air, lips closed, soft palate lowered), the
//      vowel on the note, then the held /a/ (voiced)
//   4  demo «ta»: the closure (no air in front of the face), then voiced after the release; inside a phrase the onset
//      keeps its short length
//   5  a word missing from LUMA_PHONES: approx, and «приблизно» and every sound of it whole on screen at three widths
//   6  the demo from file://: listening moves the head; no network request
//   7  --rebuild keeps the song's data line byte for byte and writes LUMA_PHONES; a changed word changes the table
//   8  the frame budget (§6) at 390 and 1440 px under 1× and 4× CPU throttle
//   9  «Голова» off: the roll's plot is today's
//  10  no WebGL2: the 2D cut face, no console error
//  11  in VR and in a hidden tab the head draws no frames
//  12  reduced motion: two frames 200 ms apart show the same particles
// Every page must keep a clean console; SwiftShader's own notes on reading a canvas back are the driver's, not the page's.
import {execFileSync} from 'node:child_process';
import {cpSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {launch, assert, url} from './lib.mjs';

const py = process.env.LUMA_PY || '.venv/bin/python';
const scratch = mkdtempSync(join(tmpdir(), 'luma-tract-'));
const demoPkg = resolve('examples/demo/Demo'), demoHtml = resolve('examples/demo/Luma_Demo.html');
if (!existsSync(demoHtml)) { console.error('FAIL tract3d: build the demo first (tests/e2e/run.sh does)'); process.exit(1); }
const fileUrl = p => 'file://' + p;
const quiet = m => /GL Driver Message/.test(m);
const allLogs = [];

const browser = await launch(['--autoplay-policy=no-user-gesture-required']);
async function page(target, {viewport = {width: 1440, height: 900}, dpr = 2, settings = null, init = null, reduced = false, b = browser} = {}) {
  const ctx = await b.newContext({viewport, deviceScaleFactor: dpr, reducedMotion: reduced ? 'reduce' : 'no-preference'});
  if (settings) await ctx.addInitScript(s => { if (!sessionStorage.getItem('seeded')) { localStorage.setItem('luma.trainer.settings', JSON.stringify(s)); sessionStorage.setItem('seeded', '1'); } }, settings);
  if (init) await ctx.addInitScript(init);
  const p = await ctx.newPage(), logs = [];
  p.on('console', m => { if (['error', 'warning'].includes(m.type()) && !quiet(m.text())) logs.push(m.type() + ': ' + m.text()); });
  p.on('pageerror', e => logs.push('PAGEERROR ' + e.message));
  await p.goto(target); await p.waitForFunction(() => window.Luma && window.LumaTract);
  return {p, ctx, logs};
}
const seeded = body => ({tract: true, tractBody: body, audioNotice: true, viewDefault: 3, view: 'notes'});
// the head is built in idle time after the first paint: wait for its first frame
const ready = p => p.waitForFunction(() => { const s = window.Luma.test.tract(); return s.renderer && s.frames > 0; }, null, {timeout: 20000});
const frames = (p, n = 2) => p.evaluate(n => new Promise(r => { const step = k => k ? requestAnimationFrame(() => step(k - 1)) : r(); step(n); }), n);
async function at(p, t) { await p.evaluate(t => window.Luma.test.seek(t), t); await frames(p, 3); return p.evaluate(() => window.Luma.test.tract()); }
async function done(o, name) { assert(!o.logs.length, name + ': clean console ' + JSON.stringify(o.logs)); allLogs.push(...o.logs); await o.ctx.close(); }
const overlap = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

// ── fixtures: lesson 1, and the demo with a made-up word ─────────────────────────────────────────────────────────────
const library = join(scratch, 'lessons');
execFileSync(py, ['lessons/build_lessons.py', '--songs', library, '--quiet'], {encoding: 'utf8', maxBuffer: 64 << 20});
const lesson1 = join(library, 'Luma_Lesson_1_Novachok.html');
const MADE_UP = 'zorvik';
const odd = join(scratch, 'Odd');
cpSync(demoPkg, odd, {recursive: true});
{ const t = JSON.parse(readFileSync(join(odd, 'target.json'), 'utf8')); t.lyrics[0].words[1].w = MADE_UP; writeFileSync(join(odd, 'target.json'), JSON.stringify(t)); }
const oddHtml = join(scratch, 'Luma_Odd.html');
execFileSync(py, ['studio/build_html.py', odd, '-o', oddHtml], {encoding: 'utf8'});

// ── 7 · the build writes the sounds of the words beside the song's data, and a rebuild keeps the data ────────────────
{
  const SONG = '<script>window.LUMA_SONG=', END = '};</script>', PH = '<script>window.LUMA_PHONES=';
  const lines = html => { const a = html.indexOf(SONG), e = html.indexOf(END, html.indexOf(';window.LUMA_ASSETS=', a)) + END.length, p = html.indexOf(PH), q = html.indexOf('</script>', p) + 9; return {data: html.slice(a, e), phones: html.slice(p, q), after: html.slice(e, e + 1 + PH.length), table: JSON.parse(html.slice(p + PH.length, html.indexOf(';</script>', p)))}; };
  const copy = join(scratch, 'Luma_Rebuilt.html'); cpSync(oddHtml, copy);
  const before = lines(readFileSync(copy, 'utf8'));
  writeFileSync(copy, readFileSync(copy, 'utf8').replace(before.phones, '<script>window.LUMA_PHONES={"v":1,"words":{}};</script>'));
  execFileSync(py, ['studio/build_html.py', '--rebuild', copy], {encoding: 'utf8'});
  const after = lines(readFileSync(copy, 'utf8'));
  assert(after.data === before.data, '--rebuild keeps the song data line byte for byte (' + before.data.length + ' characters)');
  assert(after.after === '\n' + PH && after.phones === before.phones && after.table.words.la === 'l ɑ' && after.table.v === 1,
    '--rebuild writes LUMA_PHONES on the line after the data, from the song: ' + JSON.stringify(Object.entries(after.table.words).slice(0, 4)));
  assert(!(MADE_UP in after.table.words) && Object.keys(after.table.words).length >= 15, 'a word neither the dictionary nor the rules read is left out of the table');
  const pkg2 = join(scratch, 'Changed'); cpSync(odd, pkg2, {recursive: true});
  { const t = JSON.parse(readFileSync(join(pkg2, 'target.json'), 'utf8')); t.lyrics[0].words[1].w = 'time'; writeFileSync(join(pkg2, 'target.json'), JSON.stringify(t)); }
  const out2 = join(scratch, 'Luma_Changed.html'); execFileSync(py, ['studio/build_html.py', pkg2, '-o', out2], {encoding: 'utf8'});
  const changed = lines(readFileSync(out2, 'utf8'));
  assert(changed.table.words.time === 't a+ɪ m' && !(MADE_UP in changed.table.words), 'a changed word in target.json changes the table at the next build: time → ' + changed.table.words.time);
}

// ── 1 · where the panel stands: a column at 1440 px, an overlay on the sung part at 390 px ───────────────────────────
{
  const o = await page(url, {settings: null});
  const s = await o.p.evaluate(() => window.Luma.test.tract());
  const pick = await o.p.isVisible('#tractPick'), pressed = await o.p.$$eval('[data-body]', bs => bs.map(b => b.getAttribute('aria-pressed')));
  assert(!s.hidden && s.mode === 'column' && s.box.x1 - s.box.x0 >= 300 && s.box.x1 - s.box.x0 <= 420 && pick && pressed.join() === 'false,false' && s.body === null,
    '1440 px, a fresh profile: the panel stands as a column by default and asks «Чоловік · Жінка» before it draws a head ' + JSON.stringify({mode: s.mode, box: s.box, body: s.body}));
  await o.p.click('#tractFemale'); await ready(o.p);
  const t = await o.p.evaluate(() => window.LUMA_SONG.lyrics[1].words[2].a + .05);
  // the chosen head is marked as the roll's own segmented control marks «Контур» or «Ноти»: the same ground and ink
  const marks = await o.p.evaluate(() => { const cs = el => { const c = getComputedStyle(el); return c.backgroundColor + ' ' + c.color; };
    return {chosen: cs(document.getElementById('tractFemale')), other: cs(document.getElementById('tractMale')), view: cs(document.querySelector('[data-view].active'))}; });
  assert(marks.chosen === marks.view && marks.other !== marks.chosen, '1440 px: «Жінка», pressed, is marked as the roll\'s chosen view is ' + JSON.stringify(marks));
  const st = await at(o.p, t), plot = await o.p.evaluate(() => window.Luma.test.plot()), words = await o.p.evaluate(() => window.Luma.test.wordBoxes());
  assert(plot.right < st.box.x0, `1440 px: the roll's right edge (${plot.right.toFixed(1)}) stands left of the panel (${st.box.x0.toFixed(1)})`);
  assert(words.length >= 5 && words.every(w => w.x1 <= st.box.x0), `1440 px: none of the ${words.length} drawn words reaches the panel`);
  await done(o, '1440 px layout');

  // between the two: at 900 px the narrower column shows the whole head (a crop there cut the skull, the hair and the nose)
  const n = await page(url, {viewport: {width: 900, height: 1000}, settings: seeded('male')}); await ready(n.p);
  const sn = await at(n.p, t), pn = await n.p.evaluate(() => window.Luma.test.plot()), wn = await n.p.evaluate(() => window.Luma.test.wordBoxes());
  assert(sn.mode === 'column' && !sn.crop && sn.box.x1 - sn.box.x0 >= 240 && sn.box.x1 - sn.box.x0 <= 300 && pn.right < sn.box.x0 && wn.every(w => w.x1 <= sn.box.x0),
    '900 px: a column of 240–300 px with the whole head, right of the roll and of every word ' + JSON.stringify({w: sn.box.x1 - sn.box.x0, crop: sn.crop, right: pn.right}));
  await done(n, '900 px layout');

  const m = await page(url, {viewport: {width: 390, height: 844}, dpr: 3, settings: seeded('male')}); await ready(m.p);
  // a moment when the low «do» is on the sung part of the roll, where the overlay stands
  const t2 = await m.p.evaluate(() => { const w = window.LUMA_SONG.lyrics.flatMap(l => l.words).find(w => w.w === 'do'); return w.b + 1.2; });
  const s2 = await at(m.p, t2);
  const r = await m.p.evaluate(t => { const T = window.Luma.test, b = T.plot(), v = T.viewWindow(t), x = a => b.left + (a - v.a) / v.span * (b.right - b.left);
    const on = T.wordBoxes(); document.getElementById('tractBtn').click(); const off = T.wordBoxes(); document.getElementById('tractBtn').click();
    const notes = window.LUMA_SONG.notes.filter(n => n.b > t && n.a < t + 2).map(n => ({x0: Math.max(x(n.a), x(t)), x1: x(n.b)}));
    return {on, off, now: x(t), notes, plot: b}; }, t2);
  const ov = s2.overlay;
  assert(s2.mode === 'overlay' && ov && ov.y1 <= r.plot.bottom && Math.abs((ov.y1 - ov.y0) - .4 * (r.plot.bottom - r.plot.top)) < 2 && ov.x0 >= r.plot.left,
    '390 px: the head is an overlay 40 % of the plot high at the bottom of the roll ' + JSON.stringify({ov, plot: r.plot}));
  assert(r.off.some(w => overlap(w, ov)), '390 px: without the head a word would stand where the overlay is (' + r.off.filter(w => overlap(w, ov)).map(w => w.w).join(', ') + ')');
  assert(r.on.length === r.off.length && !r.on.some(w => overlap(w, ov)), '390 px: with the head every word climbs clear of it: ' + JSON.stringify(r.on.filter(w => overlap(w, ov))));
  assert(ov.x1 < r.now && r.notes.length > 0 && r.notes.every(n => n.x0 >= ov.x1), `390 px: the playhead (${r.now.toFixed(1)}) and the next 2 s of notes (${r.notes.length}) stay clear of the overlay (right edge ${ov.x1.toFixed(1)})`);
  // the body's tag stands in the picture's bottom right corner, in front of the neck, off the nose and the soft palate
  const tag = await m.p.evaluate(() => { const r = e => { const b = document.getElementById(e).getBoundingClientRect(); return {x0: b.left, y0: b.top, x1: b.right, y1: b.bottom}; }; return {tag: r('tractTag'), view: r('tractView'), text: document.getElementById('tractTag').textContent}; });
  assert(s2.crop && tag.text === 'Чоловік' && tag.tag.x1 <= tag.view.x1 && tag.tag.y1 <= tag.view.y1 && tag.view.x1 - tag.tag.x1 < 8 && tag.view.y1 - tag.tag.y1 < 8,
    '390 px: the overlay shows the crop, and «Чоловік» stands in its bottom right corner ' + JSON.stringify(tag));
  // enlarged by a tap while idle, the head covers the roll; its header holds a ✕ of a full tap's size that returns it
  await m.p.click('#tractView'); await m.p.waitForFunction(() => window.Luma.test.tract().big);
  const big = await m.p.evaluate(() => { const b = document.getElementById('tractClose'), r = b.getBoundingClientRect(); return {hidden: b.hidden, w: r.width, h: r.height, x0: r.left, x1: r.right, y0: r.top, label: b.getAttribute('aria-label'), vw: innerWidth}; });
  assert(!big.hidden && big.w >= 40 && big.h >= 40 && big.x0 >= 0 && big.x1 <= big.vw && big.y0 >= 0 && big.label, '390 px, enlarged: a ✕ in the header, ' + big.w + '×' + big.h + ' px, inside the screen');
  await m.p.click('#tractClose');
  const back = await m.p.evaluate(() => ({t: window.Luma.test.tract(), close: document.getElementById('tractClose').hidden}));
  assert(!back.t.big && back.t.overlay && back.close, '390 px: the ✕ returns the head to the small overlay and hides itself');
  await done(m, '390 px layout');

  // a phone before a head is chosen: the two buttons and the prompt, each whole, none over another
  const u = await page(url, {viewport: {width: 390, height: 844}, dpr: 3, settings: {audioNotice: true}});
  await frames(u.p, 3);
  const ask = await u.p.evaluate(() => { const box = e => { const b = e.getBoundingClientRect(); return {x0: b.left, y0: b.top, x1: b.right, y1: b.bottom}; };
    const p = document.getElementById('tractPick'), rg = document.createRange(); rg.selectNodeContents(p);
    const text = [...rg.getClientRects()].filter(r => r.width > 0).map(r => ({x0: r.left, y0: r.top, x1: r.right, y1: r.bottom}));
    return {mode: window.Luma.test.tract().mode, panel: box(document.getElementById('tract')), male: box(document.getElementById('tractMale')), female: box(document.getElementById('tractFemale')), text, words: p.innerText.trim()}; });
  const inside = (a, b) => a.x0 >= b.x0 - .5 && a.x1 <= b.x1 + .5 && a.y0 >= b.y0 - .5 && a.y1 <= b.y1 + .5;
  assert(ask.mode === 'overlay' && ask.words === 'Обери голову' && ask.text.length > 0 && ask.text.every(r => inside(r, ask.panel) && !overlap(r, ask.male) && !overlap(r, ask.female)) && inside(ask.male, ask.panel) && inside(ask.female, ask.panel) && !overlap(ask.male, ask.female) && ask.male.y1 - ask.male.y0 >= 40,
    '390 px, nothing chosen: «Чоловік», «Жінка» and «Обери голову» each whole in the overlay, none over another ' + JSON.stringify(ask));
  await done(u, '390 px before a choice');
}

// ── 2 · the body: chosen, kept across a reload, sized and shaped as Chimera's ────────────────────────────────────────
{
  const o = await page(url, {settings: {audioNotice: true}});
  await o.p.click('#tractMale'); await ready(o.p);
  const male = await o.p.evaluate(() => window.Luma.test.tract());
  await o.p.click('#tractFemale'); await o.p.waitForFunction(() => window.Luma.test.tract().body === 'female', null, {timeout: 20000});
  await o.p.reload(); await o.p.waitForFunction(() => window.Luma && window.LumaTract); await ready(o.p);
  const female = await o.p.evaluate(() => window.Luma.test.tract()), pressed = await o.p.$$eval('[data-body]', bs => bs.map(b => b.dataset.body + ':' + b.getAttribute('aria-pressed')));
  assert(female.body === 'female' && female.pref_body === 'female' && pressed.join() === 'male:false,female:true', '«Жінка» survives a reload ' + pressed.join());
  assert(male.scale === 1 && female.scale === .9, `the bodies' scales are Chimera's: ${male.scale} and ${female.scale}`);
  const d = ['x0', 'x1', 'y0', 'y1'].map(k => Math.abs(male.outline[k] - female.outline[k] / .9));
  assert(Math.max(...d) > .3, 'the two heads differ in shape as well as size (bounds, female scaled back: ' + d.map(v => v.toFixed(2)).join(' ') + ' cm)');
  await done(o, 'body choice');
}

// ── 3 · lesson 1 on «ма», 4 · the demo's «ta», 5 · a made-up word ───────────────────────────────────────────────────
{
  const o = await page(fileUrl(lesson1), {settings: seeded('male')}); await ready(o.p);
  const tl = await o.p.evaluate(() => { const T = window.Luma.test.tractTimeline(); return T.segs.slice(0, 6); });
  const m = tl.find(g => g.sym === 'm'), a = tl.find(g => g.sym === 'a' && g.a >= m.b - 1e-6);
  const note = await o.p.evaluate(t => window.LUMA_SONG.notes.find(n => n.a <= t + 1e-6 && n.b > t), a.a);
  // after the rest the /m/ takes its closure up early enough to be seen while the song plays; the vowel stays on the note
  assert(m.b - m.a >= .15 && Math.abs(m.b - a.a) < 1e-6 && note && Math.abs(a.a - note.a) < 1e-6,
    `lesson 1, «ма»: after the rest the /m/ lasts ${(1000 * (m.b - m.a)).toFixed(0)} ms (≥ 150), and the /a/ starts on the note (${a.a.toFixed(3)} s, the note at ${note?.a.toFixed(3)} s)`);
  const sm = await at(o.p, m.a + .04), sm2 = await at(o.p, m.b - .006), sa = await at(o.p, (a.a + a.b) / 2);
  assert([sm, sm2].every(q => q.phoneme === 'm' && q.air === 'nasal' && q.lips === 'closed' && q.velum === 'lowered' && q.word === 'ма'),
    'lesson 1, «ма», on the /m/ (its start and its end): ' + JSON.stringify([sm, sm2].map(q => ({phoneme: q.phoneme, air: q.air, lips: q.lips, velum: q.velum, word: q.word}))));
  assert(sa.phoneme === 'a' && sa.air === 'voiced' && sa.lips === 'open' && sa.velum === 'raised' && !sa.approx && sa.sound === '«ма»\nm [a]',
    'lesson 1, «ма», the held /a/: ' + JSON.stringify({phoneme: sa.phoneme, air: sa.air, lips: sa.lips, velum: sa.velum, sound: sa.sound}));
  await done(o, 'lesson 1');

  const d = await page(url, {settings: seeded('female')}); await ready(d.p);
  const segs = await d.p.evaluate(() => { const T = window.Luma.test.tractTimeline(), i = T.segs.findIndex(g => g.sym === 't' && T.words[g.word]?.w === 'ta'); return T.segs.slice(i - 1, i + 2); });
  const sc = await at(d.p, (segs[1].a + segs[1].b) / 2 + .01), sr = await at(d.p, segs[2].a + .08);
  assert(segs[1].sym === 't' && sc.phoneme === 't' && sc.air === 'closed' && sr.phoneme === 'ɑ' && sr.air === 'voiced',
    'demo «ta»: the closure reads closed, then voiced after the release ' + JSON.stringify([sc.phoneme + ':' + sc.air, sr.phoneme + ':' + sr.air]));
  // inside a phrase (no rest before it) the onset keeps Chimera's short length
  assert(segs[0].kind === 'vowel' && Math.abs(segs[0].b - segs[1].a) < 1e-6 && segs[1].b - segs[1].a < .1,
    `demo «ta», straight after «li»: the /t/ keeps its ${(1000 * (segs[1].b - segs[1].a)).toFixed(0)} ms`);
  // no air in front of the face while the tongue's tip holds the closure; after the release it leaves the mouth
  const front = sc.outline.x1, past = q => q.streaks.filter(([x]) => x > front).length;
  assert(sc.streaks.length > 0 && past(sc) === 0 && sr.streaks.length > 0 && past(sr) > 0,
    `demo «ta»: at the closure none of ${sc.streaks.length} streaks of air stands in front of the face (x > ${front} cm); after the release ${past(sr)} of ${sr.streaks.length} do`);
  await done(d, 'demo ta');

  // «приблизно» and every sound of the word measured by their own text ranges: wholly inside the caption's box (not cut by an
  // ellipsis, a clamped line or the box's edge) and inside the panel, at 1440 px, in the narrower column at 900 px and in
  // the phone's overlay
  for (const [width, height, dpr] of [[1440, 900, 2], [900, 1000, 2], [390, 844, 3]]) {
    const x = await page(fileUrl(oddHtml), {viewport: {width, height}, dpr, settings: seeded('female')}); await ready(x.p);
    const w = await x.p.evaluate(w => { const s = window.LUMA_SONG.lyrics[0].words[1]; return {a: s.a, b: s.b, inTable: w in (window.LUMA_PHONES.words || {})}; }, MADE_UP);
    const sx = await at(x.p, (w.a + w.b) / 2);
    const vis = await x.p.evaluate(() => { const e = document.getElementById('tractSound'), q = document.getElementById('tract').getBoundingClientRect(), box = e.getBoundingClientRect(), node = e.firstChild, text = node ? node.textContent : '';
      const i = text.indexOf('приблизно'); if (i < 0) return {text, found: false};
      const rects = (a, b) => { const r = document.createRange(); r.setStart(node, a); r.setEnd(node, b); return [...r.getClientRects()].filter(t => t.width > 0); };
      // a clipped part of an element that clips its overflow lies outside its padding box
      const inBox = t => t.left >= box.left - .5 && t.right <= box.right + .5 && t.top >= box.top - .5 && t.bottom <= box.bottom + .5;
      const inPanel = t => t.left >= q.left && t.right <= q.right && t.top >= q.top && t.bottom <= q.bottom;
      const word = rects(i, i + 9), all = rects(0, text.length);
      return {text, found: true, wordWhole: word.length > 0 && word.every(inBox) && word.every(inPanel), allWhole: all.every(inBox) && all.every(inPanel), lines: new Set(all.map(t => Math.round(t.top))).size,
        overflow: e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1, w: +word.reduce((s, t) => s + t.width, 0).toFixed(1)}; });
    assert(!w.inTable && sx.word === MADE_UP && sx.approx === true && vis.found && vis.wordWhole && vis.w > 20,
      `${width} px: the made-up word «${MADE_UP}» is not in LUMA_PHONES, reads approx, and «приблизно» stands whole in the panel: ` + JSON.stringify(vis));
    assert(/z ɔ ɹ · v i k$/.test(vis.text.replace(/[[\]]/g, '')) && /\[/.test(vis.text) && vis.allWhole && !vis.overflow,
      `${width} px: every sound of «${MADE_UP}» shows, nothing cut (${vis.lines} lines): ` + JSON.stringify(vis.text));
    await done(x, width + ' px made-up word');
  }
}

// ── 6 · the demo opened from file://: listening moves the head, nothing goes to the network ─────────────────────────
{
  const o = await page(fileUrl(demoHtml), {settings: seeded('male')}); await ready(o.p);
  const net = []; o.p.on('request', r => { if (!/^(file|data|blob):/.test(r.url())) net.push(r.url()); });
  await o.p.click('#listenBtn');
  // from the first sung word on, for 2.5 s of the song: the sounds the head shows on its own frames, and how far it moved
  const seen = await o.p.evaluate(async () => { const T = window.Luma.test, out = new Set(); let t0 = null, last = null, moves = 0, frames0 = 0;
    const start = window.LUMA_SONG.lyrics[0].words[0].a;
    while (true) { await new Promise(r => requestAnimationFrame(r)); const st = T.state(), s = T.tract(); if (st.mode !== 'listen') continue;
      if (t0 === null) { if (st.time < start) continue; t0 = st.time; frames0 = s.frames; }
      if (s.phoneme) out.add(s.phoneme); if (last && (s.phoneme !== last.phoneme || s.mix !== last.mix)) moves++; last = s;
      if (st.time - t0 > 2.5 || performance.now() > 60000) return {phonemes: [...out], moves, mode: st.mode, frames: s.frames - frames0, song: +(st.time - t0).toFixed(2)}; } });
  await o.p.click('#stopBtn');
  assert(seen.mode === 'listen' && seen.phonemes.length >= 3 && seen.moves >= 5 && seen.frames > 20, 'file://, «Слухати»: the head moves with the target ' + JSON.stringify(seen));
  assert(net.length === 0, 'file://: no network request ' + JSON.stringify(net));
  await done(o, 'file:// listening');
}

// ── 8 · the frame budget (§6) ────────────────────────────────────────────────────────────────────────────────────────
// 480 frames of one sung pass at 60 Hz after a lead-in of 32, the panel on and off in alternating blocks of 32 (the first frame after a
// switch left out), so drift in the machine hits both. The roll's draw() with the panel on against off; the head's own
// work in the frames it draws.
// A browser without a graphics processor (this suite's) gets the flat cut face; the 3D head, forced onto that renderer,
// is timed for its own work too (its roll budget is a graphics processor's matter, measured outside the suite).
async function budget(width, height, rate, o, cdp) {
  await cdp.send('Emulation.setCPUThrottlingRate', {rate});
  const r = await o.p.evaluate(async () => { const L = window.Luma, T = L.test, a = 2, res = {off: [], on: [], head: []}, slow = [], drawnAt = []; let skipped = 0;
    // the head alone through the same 8 s first, not timed (no take is stored): the sounds' skins posed once, the
    // shaders compiled, the first paintings done
    for (let k = 0; k < 480; k += 2) { T.tractFrame(a + k / 60, true); await new Promise(r => setTimeout(r)); }
    await new Promise(r => setTimeout(r, 300));
    T.fakeSing({a, b: a + 30}); let shown = true, first = false;
    // the first 32 frames of the pass are a lead-in, timed for neither side: singing mode starting up is in them
    for (let k = 0; k < 512; k++) { const tt = k / 60, lead = k < 32, want = lead || (k >> 5) % 2 === 1;
      if (want !== shown) { document.getElementById('tractBtn').click(); shown = want; first = true; }
      const c0 = performance.now(); const t = T.fakeTick(tt), c1 = performance.now();
      const h = shown ? T.tractFrame(t, true) : null; if (h && h.drew) drawnAt.push(performance.now());
      if (!first && !lead) { (shown ? res.on : res.off).push(c1 - c0); if (c1 - c0 > 3) slow.push((shown ? '+' : '-') + k + ':' + (c1 - c0).toFixed(1)); if (h && h.drew) res.head.push(h.ms); else if (h) skipped++; }
      first = false; await new Promise(r => setTimeout(r)); }
    T.fakeFinish(); T.closeTrace(); if (!shown) document.getElementById('tractBtn').click();
    const q = (a, f) => { const z = [...a].sort((x, y) => x - y); return +z[Math.min(z.length - 1, Math.floor(f * z.length))].toFixed(2); };
    const s = T.tract(); let gap = Infinity; for (let i = 1; i < drawnAt.length; i++) gap = Math.min(gap, drawnAt[i] - drawnAt[i - 1]);
    return {minGap: +gap.toFixed(1), offMed: q(res.off, .5), offP95: q(res.off, .95), onMed: q(res.on, .5), onP95: q(res.on, .95), headMed: q(res.head, .5), headP95: q(res.head, .95), headMax: q(res.head, 1), drawn: res.head.length, skipped, hz: s.hz, renderer: s.renderer, software: s.software, painted: s.painted, worker: s.worker, slow: slow.slice(0, 24).join(' ')}; });
  console.log('perf', JSON.stringify({width, rate, ...r}));
  return r;
}
for (const [width, height] of [[1440, 900], [390, 844]]) {
  const o = await page(url, {viewport: {width, height}, dpr: 2, settings: seeded('female')}); await ready(o.p);
  const cdp = await o.ctx.newCDPSession(o.p);
  for (const rate of [1, 4]) {
    const r = await budget(width, height, rate, o, cdp);
    assert(r.drawn > 100 && (r.software ? r.renderer === '2d' : r.renderer === 'webgl2'), `${width} px, ${rate}× CPU: the head drew ${r.drawn} frames, ${r.renderer === '2d' ? 'flat: this browser renders WebGL without a graphics processor' : 'on WebGL2'}`);
    assert(r.onP95 <= Math.max(r.offP95 * 1.25, r.offP95 + 1.5), `${width} px, ${rate}× CPU: the roll's slow frames stay within budget with the panel (p95 ${r.offP95} → ${r.onP95} ms)`);
    assert(r.onMed <= r.offMed + 1, `${width} px, ${rate}× CPU: the roll's typical frame costs at most 1 ms more with the panel (median ${r.offMed} → ${r.onMed} ms)`);
    if (width === 1440 && rate === 1) assert(r.headMed <= 2 && r.headP95 <= 4, `1440 px, 1× CPU: the head's own work, median ${r.headMed} ms ≤ 2, p95 ${r.headP95} ms ≤ 4`);
    if (width === 390 && rate === 4) assert(r.headP95 <= 8 || r.hz === 30, `390 px, 4× CPU: the head's own work, p95 ${r.headP95} ms ≤ 8, or it steps down to 30 Hz (${r.hz} Hz)`);
  }
  await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1});
  await done(o, width + ' px budget');
}
// the 3D head forced onto this browser's renderer: it draws the half-head (pixels on its canvas), at most 30 times a
// second there, and its own work stays in budget
for (const [width, height, rate] of [[1440, 900, 1], [390, 844, 4]]) {
  const o = await page(url, {viewport: {width, height}, dpr: 2, settings: seeded('male'), init: () => { window.__lumaTractGL = 'force'; }}); await ready(o.p);
  const t = await o.p.evaluate(() => window.LUMA_SONG.lyrics[0].words[2].a + .1); await at(o.p, t);
  await o.p.waitForFunction(() => window.Luma.test.tract().painted > 0, null, {timeout: 20000}); await frames(o.p, 3);
  const box = await o.p.evaluate(() => { const r = document.getElementById('tractView').getBoundingClientRect(); return {x: r.left, y: r.top, width: r.width, height: r.height}; });
  const png = await o.p.screenshot({clip: box});
  const ink = await o.p.evaluate(async b64 => { const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode(); const c = new OffscreenCanvas(img.width, img.height), g = c.getContext('2d'); g.drawImage(img, 0, 0); const d = g.getImageData(0, 0, img.width, img.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] - d[i + 2] > 40) n++; return {n, of: d.length / 4}; }, png.toString('base64'));
  const cdp = await o.ctx.newCDPSession(o.p);
  const r = await budget(width, height, rate, o, cdp);
  await cdp.send('Emulation.setCPUThrottlingRate', {rate: 1});
  assert(r.renderer === 'webgl2' && r.software && r.hz === 30 && r.minGap >= 1000 / 30 - 4.5 && ink.n > ink.of * .08,
    `${width} px, the 3D head forced onto a renderer without a graphics processor: drawn on WebGL2 (${ink.n} of ${ink.of} pixels warm), at most 30 a second (closest frames ${r.minGap} ms apart)`);
  if (rate === 1) assert(r.headMed <= 2 && r.headP95 <= 4, `${width} px, ${rate}× CPU, the 3D head: its own work, median ${r.headMed} ms ≤ 2, p95 ${r.headP95} ms ≤ 4`);
  else assert(r.headP95 <= 8, `${width} px, ${rate}× CPU, the 3D head: its own work, p95 ${r.headP95} ms ≤ 8`);
  await done(o, width + ' px 3D head');
}

// ── 9 · «Голова» off: the roll is today's ─────────────────────────────────────────────────────────────────────────────
for (const [width, height] of [[1440, 900], [390, 844]]) {
  const o = await page(url, {viewport: {width, height}, settings: {...seeded('male'), tract: false}});
  await frames(o.p, 3);
  const r = await o.p.evaluate(() => { const T = window.Luma.test, c = document.getElementById('chart'); return {plot: T.plot(), W: c.getBoundingClientRect().width, hidden: document.getElementById('tract').hidden, pressed: document.getElementById('tractBtn').getAttribute('aria-pressed'), tract: T.tract()}; });
  const left = width < 720 ? 42 : 56;
  assert(r.hidden && r.pressed === 'false' && r.plot.right === r.W - 16 && r.plot.left === left && r.tract.frames === 0 && r.tract.renderer === null,
    `${width} px, «Голова» off: no panel, and the roll's plot is today's (left ${r.plot.left}, right ${r.plot.right} = width ${r.W} − 16), no head drawn`);
  await o.p.click('#tractBtn'); await ready(o.p);
  const on = await o.p.evaluate(() => ({plot: window.Luma.test.plot(), t: window.Luma.test.tract()}));
  assert(on.t.pref === true && !on.t.hidden && (width < 720 ? on.plot.right === r.plot.right : on.plot.right < r.plot.right) && on.plot.top === r.plot.top && on.plot.bottom === r.plot.bottom,
    `${width} px: «Голова» on again brings the panel back (${on.t.mode}); the roll keeps its height`);
  await done(o, width + ' px head off');
}

// ── 10 · without WebGL2 the cut face is drawn in 2D ──────────────────────────────────────────────────────────────────
{
  const o = await page(url, {settings: seeded('female'), init: () => { const g = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (kind, opt) { return kind === 'webgl2' ? null : g.call(this, kind, opt); }; }});
  await ready(o.p);
  const t = await o.p.evaluate(() => window.LUMA_SONG.lyrics[0].words[2].a + .1); await at(o.p, t);
  await o.p.waitForFunction(() => window.Luma.test.tract().painted > 0, null, {timeout: 20000}); await frames(o.p, 3);
  const r = await o.p.evaluate(() => { const c = document.querySelector('#tract canvas.tract-2d'), gl = document.querySelector('#tract canvas.tract-gl'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let ink = 0; for (let i = 3; i < d.length; i += 16) if (d[i] > 200) ink++; return {renderer: window.Luma.test.tract().renderer, ink, shown: !c.hidden && c.getBoundingClientRect().width > 0, glHidden: gl.hidden}; });
  assert(r.renderer === '2d' && r.shown && r.glHidden && r.ink > 2000, 'WebGL2 refused: the 2D cut face shows instead ' + JSON.stringify(r));
  await done(o, 'no WebGL2');
}

// ── 11 · a hidden tab and a VR session draw no head ──────────────────────────────────────────────────────────────────
{
  const o = await page(url, {settings: seeded('male')}); await ready(o.p);
  await o.p.click('#listenBtn'); await o.p.waitForTimeout(400);
  const f0 = await o.p.evaluate(() => window.Luma.test.tract().frames);
  await o.p.evaluate(() => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'}); document.dispatchEvent(new Event('visibilitychange')); });
  const f1 = await o.p.evaluate(() => window.Luma.test.tract().frames); await o.p.waitForTimeout(600);
  const f2 = await o.p.evaluate(() => ({frames: window.Luma.test.tract().frames, mode: window.Luma.test.state().mode}));
  assert(f1 > f0 - 1 && f2.frames === f1 && f2.mode === 'idle', `a hidden tab: the head drew no frame in 600 ms (${f1} → ${f2.frames}), listening stopped`);
  await o.ctx.close();

  const iwerPath = process.env.LUMA_IWER || (() => { try { return createRequire(import.meta.url).resolve('iwer/build/iwer.min.js'); } catch { return ''; } })();
  const vb = await launch(['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--enable-unsafe-swiftshader', '--use-angle=swiftshader']);
  const setup = `${readFileSync(iwerPath, 'utf8')}\n;(() => { const d = new IWER.XRDevice(IWER.metaQuest3, {stereoEnabled: false}); d.installRuntime({forceInstall: true}); d.primaryInputMode = 'controller'; d.position.set(0, 1.6, 0); window.__iwer = d; })();`;
  const v = await page(url, {viewport: {width: 1280, height: 800}, settings: seeded('male'), init: setup, b: vb});
  await v.ctx.grantPermissions(['microphone'], {origin: new URL(url).origin});
  await ready(v.p);
  await v.p.click('#xrBtn');
  await v.p.waitForFunction(() => window.__lumaXr && window.__lumaXr.frames > 10, null, {timeout: 20000}).catch(() => {});
  const entered = await v.p.evaluate(() => ({xrFrames: window.__lumaXr?.frames || 0, frames: window.Luma.test.tract().frames}));
  // listening in the headset: the chart draws on every headset frame, the head on none
  await v.p.evaluate(() => document.getElementById('listenBtn').click());
  await v.p.waitForFunction(n => window.__lumaXr && window.__lumaXr.frames > n + 40, entered.xrFrames, {timeout: 20000}).catch(() => {});
  const inVr = await v.p.evaluate(() => ({xr: !!window.__lumaXr && document.body.classList.contains('in-xr'), xrFrames: window.__lumaXr?.frames || 0, mode: window.Luma.test.state().mode, t: window.Luma.test.tract()}));
  assert(inVr.xr && inVr.xrFrames > entered.xrFrames + 40 && inVr.t.frames === entered.frames && inVr.t.hidden && !inVr.t.shown,
    `in VR the panel hides and the head draws no frame over ${inVr.xrFrames - entered.xrFrames} of the headset's frames while ${inVr.mode} (${entered.frames} → ${inVr.t.frames})`);
  await done(v, 'VR'); await vb.close();
}

// ── 12 · reduced motion: the air stands still ────────────────────────────────────────────────────────────────────────
{
  const o = await page(url, {settings: seeded('female'), reduced: true}); await ready(o.p);
  const r = await o.p.evaluate(async () => { const T = window.Luma.test, a = 2;
    T.fakeSing({a, b: a + 10}); let t = T.fakeTick(1.0); T.tractFrame(t, true); const p0 = T.tract().particles;
    await new Promise(r => setTimeout(r, 200)); t = T.fakeTick(1.2); T.tractFrame(t, true); const p1 = T.tract().particles;
    T.fakeFinish(); T.closeTrace();
    return {same: p0.length > 0 && p0.join() === p1.join(), n: p0.length, air: T.tract().air}; });
  assert(r.same, 'reduced motion: two frames 200 ms apart show the same ' + r.n + ' particles');
  const moving = await page(url, {settings: seeded('female')}); await ready(moving.p);
  const m = await moving.p.evaluate(async () => { const T = window.Luma.test, a = 2; T.fakeSing({a, b: a + 10}); let t = T.fakeTick(1.0); T.tractFrame(t, true); t = T.fakeTick(1.02); T.tractFrame(t, true); const p0 = T.tract().particles; await new Promise(r => setTimeout(r, 200)); t = T.fakeTick(1.2); T.tractFrame(t, true); const p1 = T.tract().particles; T.fakeFinish(); return p0.join() !== p1.join(); });
  assert(m, 'without reduced motion the same two frames move the air');
  await done(o, 'reduced motion'); await done(moving, 'motion');
}

if (process.env.LUMA_SHOT) { const o = await page(url, {settings: seeded('male')}); await ready(o.p); await at(o.p, 10.74); await o.p.screenshot({path: process.env.LUMA_SHOT}); await o.ctx.close(); }
await browser.close();
rmSync(scratch, {recursive: true, force: true});
