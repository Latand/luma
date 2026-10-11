// «Розрахувати затримку» (docs/design/LATENCY_AUTOCAL.md §7): the microphone offset estimated from stored attempts.
// The fixture is the demo melody repeated seven times (≈ 4 minutes), served by the test Studio; a second one, the demo
// repeated four times, is another song whose melody only Studio's /targets can supply. Attempts are seeded straight into
// the history with a synthetic voice that sings the contour on time and reaches the microphone `lag` ms later, so the
// right setting is `lag` whatever the setting the attempt was recorded with.
import {existsSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {launch, open, assert} from './lib.mjs';

const studio = process.env.LUMA_STUDIO_URL || 'http://127.0.0.1:8793/';
const library = process.env.LUMA_TEST_LIBRARY;
if (!library) { console.error('FAIL latency: LUMA_TEST_LIBRARY is not set (tests/e2e/run.sh exports it)'); process.exit(1); }

// ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────────────────────
const demo = readFileSync('examples/demo/Luma_Demo.html', 'utf8'), A = 'window.LUMA_SONG=', B = ';window.LUMA_ASSETS=';
const head = demo.indexOf(A) + A.length, tail = demo.indexOf(B, head), base = JSON.parse(demo.slice(head, tail));
function repeated(times, hash) {
  const D = base.duration, f = {...base, id: hash + '-map', sourceId: hash, title: 'Fixture', duration: +(D * times).toFixed(2), notes: [], points: [], lyrics: [], phrases: []};
  for (let k = 0; k < times; k++) { const o = k * D;
    for (const n of base.notes) f.notes.push({...n, id: n.id + k * 1000, a: +(n.a + o).toFixed(3), b: +(n.b + o).toFixed(3)});
    for (const p of base.points) f.points.push([+(p[0] + o).toFixed(2), p[1], p[2], p[3]]);
    for (const l of base.lyrics) f.lyrics.push({...l, a: l.a + o, b: l.b + o, words: l.words.map(w => ({...w, a: w.a + o, b: w.b + o}))});
    for (const p of base.phrases) f.phrases.push({...p, id: p.id + k * 10, a: p.a + o, b: p.b + o, label: 'Фрагмент ' + String(p.id + k * 10).padStart(2, '0')});
  }
  return f;
}
// A third copy keeps words on its first three repeats only: the four after them are wordless, drawn dimmed and never
// scored (docs/design/WORDLESS_TARGETS.md), so they must not vote on the offset either.
const files = {main: 'Luma_Latency_Fixture.html', other: 'Luma_Latency_Other.html', wordless: 'Luma_Latency_Wordless.html'};
const songs = {main: repeated(7, 'latency-fixture'), other: repeated(4, 'latency-other'), wordless: repeated(7, 'latency-wordless')};
const WORDED = 3 * base.duration; songs.wordless.lyrics = songs.wordless.lyrics.filter(l => l.b < WORDED);
for (const k of ['main', 'other', 'wordless']) writeFileSync(join(library, files[k]), demo.slice(0, head) + JSON.stringify(songs[k]).replace(/</g, '\\u003c') + demo.slice(tail));
const mainUrl = studio + 'song/' + files.main, otherUrl = studio + 'song/' + files.other, wordlessUrl = studio + 'song/' + files.wordless;
const cleanup = () => { for (const f of Object.values(files)) rmSync(join(library, f), {force: true}); };

const browser = await launch();
const phone = {width: 390, height: 844}, desk = {width: 1440, height: 900};
const HOUR = 3600e3, t0 = Date.now() - 400 * HOUR;
let clock = 0;   // every seeded attempt is an hour newer than the one before
const takes = (n, trace, extra = {}) => Array.from({length: n}, () => { clock++; return {startedAt: new Date(t0 + clock * HOUR).toISOString(), trace: {...trace, seed: clock}, ...extra}; });
const seed = (p, list) => p.evaluate(list => window.Luma.test.history.seedMany(list), list);
const state = p => p.evaluate(() => window.Luma.test.history.latency());
async function fresh(target = mainUrl, viewport = desk) {
  const r = await open(browser, viewport, target);
  await r.page.waitForFunction(() => window.Luma?.test?.history && window.LumaLatency);
  return r;
}
// The button is pressed with the mouse, as the singer would; the result is read once the status region shows it.
async function calc(p) {
  if (!await p.evaluate(() => document.getElementById('settingsDialog').open)) await p.click('#settingsBtn');
  await p.click('#latencyCalc');
  await p.waitForFunction(() => !document.getElementById('latencyResult').hidden, null, {timeout: 20000});
  return {...await state(p), text: await p.textContent('#latencyResult'), apply: await p.evaluate(() => { const b = document.getElementById('latencyApply'); return b.hidden ? null : b.textContent; })};
}
const near = (v, want, tol) => Number.isFinite(v) && Math.abs(v - want) <= tol;
const round5 = v => Math.round(v / 5) * 5;   // the field's step: what the result names and Apply sets

try {
  // 1. Recovery: 15 attempts at 0 ms whose voice arrives 60 ms late suggest 60; Apply sets the field and survives a reload.
  let recovered;
  { const {page, logs} = await fresh();
    await seed(page, takes(15, {lag: 60}, {latency: 0}));
    const r = await calc(page); recovered = r.result.latency;
    assert(r.result.ok && near(r.result.latency, 60, 10), `recovery: 60 ms late at 0 ms suggests 60 ± 10 (got ${r.result.latency?.toFixed(1)})`);
    assert(r.result.n === 15 && near(r.result.ci90[0], 60, 15) && near(r.result.ci90[1], 60, 15), `recovery: 15 usable, interval ${r.result.ci90?.map(Math.round)}`);
    const v = round5(r.result.latency);
    assert(r.text.startsWith(`Голос приходить на ${v} мс пізніше за мелодію. Пропоную зсув ${v} мс (зараз 0 мс), точність ±`), 'recovery: the result line says late, the value and the current setting: ' + r.text);
    assert(/15 останніх спроб, \d+(–\d+)? \S+/.test(r.text) && !r.text.includes('лише ця пісня'), 'recovery: the window and its dates, from all songs');
    assert(r.apply === `Застосувати ${v} мс`, 'recovery: Apply names the value');
    await page.click('#latencyApply');
    assert(await page.inputValue('#latency') === String(v) && (await state(page)).prefs === v, 'recovery: Apply sets the field and prefs.latency');
    assert((await page.textContent('#latencyMain')).trim() === `Зсув ${v} мс збережено.` && await page.isHidden('#latencyApply'), 'recovery: the result says it is saved and Apply is gone');
    await page.reload(); await page.waitForTimeout(600);
    assert(await page.evaluate(() => JSON.parse(localStorage.getItem('luma.trainer.settings')).latency) === v && await page.inputValue('#latency') === String(v), 'recovery: the applied value survives a reload');
    const again = await calc(page);
    assert(again.text.startsWith('Зсув уже правильний (±') && again.apply === null, 'recovery: once applied, the setting is already right and there is nothing to apply: ' + again.text);
    assert(logs.length === 0, 'recovery: clean console ' + logs.join(' | '));
    await page.context().close(); }

  // 2. Pooling across settings: 8 at 0 ms (60 late) and 8 at 150 ms (90 early) are the same 60 ms round trip.
  { const {page} = await fresh();
    await seed(page, [...takes(8, {lag: 60}, {latency: 0}), ...takes(8, {lag: 60}, {latency: 150})]);
    const r = await calc(page);
    assert(r.result.ok && r.result.n === 16 && near(r.result.latency, 60, 10), `pooling: implied = latency + d/speed puts both groups at 60 (got ${r.result.latency?.toFixed(1)})`);
    await page.context().close(); }

  // 3. Speed: at 0.8× a 60 ms round trip is 48 ms of song time; the suggestion is still 60.
  { const {page} = await fresh();
    await seed(page, takes(12, {lag: 60}, {latency: 0, speed: .8}));
    const r = await calc(page);
    assert(r.result.ok && r.result.n === 12 && near(r.result.latency, 60, 10), `speed: 12 attempts at 0.8× suggest 60 (got ${r.result.latency?.toFixed(1)})`);
    await page.context().close(); }

  // 4. Robustness: random pitch and silence add nothing; attempts sung an octave down still count.
  { const {page} = await fresh();
    await seed(page, [...takes(15, {lag: 60}, {latency: 0}), ...takes(10, {kind: 'random'}), ...takes(5, {kind: 'silence'}), ...takes(5, {lag: 60, octave: -12}, {latency: 0})]);
    const r = await calc(page);
    assert(r.result.ok && near(r.result.latency, recovered, 5), `robustness: noise leaves the suggestion within 5 ms (${r.result.latency?.toFixed(1)} vs ${recovered?.toFixed(1)})`);
    assert(r.result.n === 20, `robustness: the 5 octave-down attempts are usable and the 15 noisy ones are not (usable ${r.result.n})`);
    await page.context().close(); }

  // 5. Late phrase starts: on time inside phrases, 200 ms late at every onset. The offset stays, the line names the starts.
  { const {page} = await fresh();
    await seed(page, takes(15, {lag: 60, late: 200}, {latency: 0}));
    const r = await calc(page);
    assert(r.result.ok && near(r.result.latency, 60, 10), `onsets: late starts do not pull the offset (got ${r.result.latency?.toFixed(1)})`);
    assert(near(r.result.onsetLag, 200, 40), `onsets: the phrase-start lateness is measured (~${Math.round(r.result.onsetLag)} ms)`);
    assert(/на початку фраз ти вступаєш ще на ~(1[89]0|2[0-2]0) мс пізніше — зсув цього не виправить/.test(r.text), 'onsets: the result line says so: ' + r.text);
    await page.context().close(); }

  // 6. Too few: 5 usable attempts, plus 3 recorded against another map that must not count.
  { const {page} = await fresh(mainUrl, phone);
    await seed(page, [...takes(5, {lag: 60}, {latency: 0}), ...takes(3, {lag: 60}, {latency: 0, mapVersion: 'old-map:0000000000000000'})]);
    const r = await calc(page);
    assert(!r.result.ok && r.result.n === 5, `too few: 5 usable, the old-map attempts are skipped (usable ${r.result.n})`);
    assert(r.text.includes('Поки замало даних: 5 придатних спроб з 12 потрібних.') && r.apply === null, 'too few: the state says how many and offers nothing to apply: ' + r.text);
    await page.screenshot({path: 'tests/e2e/shot_latency_few_390.png'});
    await page.context().close(); }

  // Other songs' attempts come with their melody from Studio's /targets, this browser's note edits applied.
  { const {page} = await fresh(otherUrl);
    await seed(page, takes(8, {lag: 60}, {latency: 0}));
    await page.goto(mainUrl); await page.waitForFunction(() => window.Luma?.test?.history);
    await seed(page, takes(6, {lag: 60}, {latency: 0}));
    const r = await calc(page);
    assert(r.result.ok && r.result.n === 14 && near(r.result.latency, 60, 10), `other songs: 8 attempts of another song count through /targets (usable ${r.result.n})`);
    // every note of the other song excluded in this browser: its attempts no longer have a melody to match
    await page.evaluate(notes => localStorage.setItem('luma.target.latency-other-map', JSON.stringify({notes, verified: []})), songs.other.notes.map(n => ({...n, ignored: true})));
    const edited = await calc(page);
    assert(!edited.result.ok && edited.result.n === 6, `other songs: a note edit kept in this browser applies to that song too (usable ${edited.result.n})`);
    await page.context().close(); }

  // Wordless target: attempts that sing only the wordless repeats have nothing scored to match, on this page and through
  // /targets alike; the same attempts on the worded copy are usable, so the check can fail.
  { const {page} = await fresh(wordlessUrl);
    const tail = {a: WORDED + .5, latency: 0};
    await seed(page, takes(13, {lag: 60}, tail));
    let r = await calc(page);
    assert(!r.result.ok && r.result.n === 0, `wordless: attempts over wordless notes only are not usable on their own page (usable ${r.result.n})`);
    await page.goto(mainUrl); await page.waitForFunction(() => window.Luma?.test?.history);
    r = await calc(page);
    assert(!r.result.ok && r.result.n === 0, `wordless: nor through /targets from another song (usable ${r.result.n})`);
    await seed(page, takes(13, {lag: 60}, tail));
    r = await calc(page);
    assert(r.result.ok && r.result.n === 13 && near(r.result.latency, 60, 10), `wordless: the same stretch with words is usable (usable ${r.result.n})`);
    await page.context().close(); }

  // 7. Performance: 200 attempts of about 4 minutes; the newest-first scan stops after 30 usable ones. The time is taken in
  // page script from the click to the shown result and read from the console.
  { const {page} = await fresh();
    await page.addInitScript(() => { addEventListener('click', e => { if (e.target.id !== 'latencyCalc') return; const t = performance.now(), box = document.getElementById('latencyResult');
      const mo = new MutationObserver(() => { if (!box.hidden) { mo.disconnect(); console.log('latency-ms ' + Math.round(performance.now() - t)); } }); mo.observe(box, {attributes: true}); }, true); });
    await page.reload(); await page.waitForFunction(() => window.Luma?.test?.history);
    for (let i = 0; i < 4; i++) await seed(page, takes(50, {lag: 60}, {latency: 0}));
    const timed = new Promise(ok => page.on('console', m => { if (m.text().startsWith('latency-ms ')) ok(+m.text().slice(11)); }));
    const r = await calc(page), ms = await timed;
    assert(r.result.ok && r.result.n === 30 && near(r.result.latency, 60, 10), `performance: 30 newest usable of 200 (usable ${r.result.n})`);
    assert(ms < 1500, `performance: 200 seeded 4-minute attempts, result shown in ${ms} ms (< 1500)`);
    await page.context().close(); }

  // 8. The hint: after a saved attempt, at most once a day, only when the setting is clearly wrong.
  const inject = p => p.evaluate(() => { const H = window.Luma.test.history, d = window.Luma.song().duration; return window.Luma.test.injectTake({a: 0, b: d, points: H.synthPoints({lag: 60}, 0, d)}); });
  { const {page, logs} = await fresh();
    await seed(page, takes(15, {lag: 60}, {latency: 0}));
    await inject(page);
    await page.waitForSelector('#latencyHint:not([hidden])', {timeout: 15000});
    const text = await page.textContent('#latencyHintText');
    assert(/^Схоже, зсув мікрофона замалий: голос у слідах на ~(55|60|65|70) мс пізніше за мелодію\.$/.test(text), 'hint: shown after a saved attempt when 60 ms is missing: ' + text);
    assert((await state(page)).check !== null, 'hint: the daily check is marked');
    await page.screenshot({path: 'tests/e2e/shot_latency_hint_1440.png'});
    await page.setViewportSize(phone); await page.waitForTimeout(300);
    const hb = await page.evaluate(() => { const b = document.getElementById('latencyHint'), r = b.getBoundingClientRect(); return {right: r.right, w: innerWidth, sw: document.documentElement.scrollWidth, buttons: [...b.querySelectorAll('button')].map(x => { const q = x.getBoundingClientRect(); return {h: q.height, r: q.right}; })}; });
    assert(hb.right <= hb.w + .5 && hb.sw <= hb.w && hb.buttons.every(b => b.h >= 44 && b.r <= hb.w), 'hint: fits 390 px with buttons ≥ 44 px ' + JSON.stringify(hb));
    await page.screenshot({path: 'tests/e2e/shot_latency_hint_390.png'});
    await page.setViewportSize(desk);
    // never during singing or its count-in
    await page.evaluate(() => window.Luma.test.fakeSing({a: 0, b: 20}));
    assert(await page.isHidden('#latencyHint'), 'hint: hidden while singing');
    await page.evaluate(() => window.Luma.test.fakeTick(5)); await page.evaluate(() => window.Luma.test.fakeFinish());
    await page.waitForSelector('#latencyHint:not([hidden])', {timeout: 3000});
    assert(true, 'hint: back once singing stops');
    await page.click('#latencyHintLater');
    assert(await page.isHidden('#latencyHint'), 'hint: «Не зараз» hides it');
    await inject(page); await page.waitForTimeout(2500);
    assert(await page.isHidden('#latencyHint'), 'hint: not again the same day after another attempt');
    assert(logs.length === 0, 'hint: clean console ' + logs.join(' | '));
    await page.context().close(); }
  // «Перевірити» lands on the whole result with its Apply button in sight, at every width.
  for (const vp of [phone, {width: 1000, height: 700}, desk]) { const {page} = await fresh(mainUrl, vp), w = vp.width;
    await seed(page, takes(15, {lag: 60}, {latency: 0}));
    await inject(page); await page.waitForSelector('#latencyHint:not([hidden])', {timeout: 15000});
    await page.click('#latencyHintCheck');
    assert(await page.evaluate(() => document.getElementById('settingsDialog').open) && await page.isVisible('#latencyResult') && await page.isHidden('#latencyHint'), `«Перевірити» opens the settings on the result (${w})`);
    const v = round5((await state(page)).result.latency);
    assert(near(v, 60, 10) && (await page.textContent('#latencyResult')).includes(`Пропоную зсув ${v} мс`) && await page.textContent('#latencyApply') === `Застосувати ${v} мс`, `«Перевірити»: the result offers ${v} ms (${w})`);
    const seen = await page.evaluate(() => { const d = document.getElementById('settingsDialog').getBoundingClientRect(), r = q => document.getElementById(q).getBoundingClientRect(), inside = b => b.top >= d.top - .5 && b.bottom <= d.bottom + .5 && b.left >= d.left - .5 && b.right <= d.right + .5;
      return {apply: inside(r('latencyApply')), result: inside(r('latencyResult'))}; });
    assert(seen.apply && seen.result, `«Перевірити»: the result and «Застосувати ${v} мс» lie inside the dialog's visible area at ${w} px ` + JSON.stringify(seen));
    await page.screenshot({path: `tests/e2e/shot_latency_hintcheck_${w}.png`});
    await page.context().close(); }
  { const {page} = await fresh();
    await seed(page, takes(15, {lag: 15}, {latency: 0}));
    await inject(page); await page.waitForFunction(() => window.Luma.test.history.latency().check !== null, null, {timeout: 15000}); await page.waitForTimeout(300);
    assert(await page.isHidden('#latencyHint'), 'hint: absent when the setting is within 30 ms');
    await page.context().close(); }
  { const {page} = await fresh();   // not enough attempts at the current setting: 15 recorded at 150 ms, the setting is 0
    await seed(page, takes(15, {lag: 60}, {latency: 150}));
    await inject(page); await page.waitForFunction(() => window.Luma.test.history.latency().check !== null, null, {timeout: 15000}); await page.waitForTimeout(300);
    assert(await page.isHidden('#latencyHint'), 'hint: absent when fewer than 8 usable attempts were recorded at the current setting');
    await page.context().close(); }
  { const {page} = await open(browser, desk, studio);   // inside a «Заняття» frame
    await page.evaluate(src => new Promise(ok => { const f = document.createElement('iframe'); f.id = 'lesson'; f.style.cssText = 'width:900px;height:700px'; f.onload = ok; f.src = src; document.body.append(f); }), '/song/' + files.main);
    const frame = page.frames().find(f => f.url().endsWith(files.main));
    await frame.waitForFunction(() => window.Luma?.test?.history);
    await seed(frame, takes(15, {lag: 60}, {latency: 0}));
    await inject(frame); await page.waitForTimeout(3000);
    assert(await frame.isHidden('#latencyHint') && (await state(frame)).check === null, 'hint: never inside a «Заняття» frame, and no check runs there');
    await page.context().close(); }

  // 9. Layout of the result at 390 × 844 and 1440 × 900: no horizontal overflow, nothing clipped, buttons ≥ 44 px on a phone.
  for (const [vp, tag] of [[phone, '390'], [desk, '1440']]) {
    const {page} = await fresh(mainUrl, vp);
    await seed(page, takes(15, {lag: 60}, {latency: 0}));
    await page.evaluate(() => { const i = document.getElementById('latency'); i.value = '120'; i.dispatchEvent(new Event('change')); });
    await calc(page);
    await page.evaluate(() => document.getElementById('latencyApply').scrollIntoView({block: 'center'}));
    const m = await page.evaluate(() => { const d = document.getElementById('settingsDialog'), dr = d.getBoundingClientRect(), box = d.querySelector('.latency-calc');
      const els = [...box.querySelectorAll('p,small,button')].filter(e => !e.hidden).map(e => { const r = e.getBoundingClientRect(); return {id: e.id || e.tagName, l: r.left, r: r.right, h: r.height, sw: e.scrollWidth, cw: e.clientWidth}; });
      return {dl: dr.left, dr: dr.right, over: d.scrollWidth - d.clientWidth, page: document.documentElement.scrollWidth - innerWidth, els}; });
    assert(m.over <= 0 && m.page <= 0, `layout ${tag}: no horizontal overflow (dialog ${m.over}, page ${m.page})`);
    assert(m.els.every(e => e.l >= m.dl - .5 && e.r <= m.dr + .5 && e.sw <= e.cw + 1), `layout ${tag}: every line and button inside the dialog, none clipped`);
    if (tag === '390') assert(m.els.filter(e => e.id.startsWith('latency') && e.id !== 'latencyMain' && e.id !== 'latencyMeta').every(e => e.h >= 44), 'layout 390: Apply and Calculate are ≥ 44 px ' + JSON.stringify(m.els.map(e => [e.id, Math.round(e.h)])));
    const v = round5((await state(page)).result.latency);
    assert((await page.textContent('#latencyMain')).startsWith(`Голос приходить на ${120 - v} мс раніше за мелодію. Пропоную зсув ${v} мс (зараз 120 мс)`), `layout ${tag}: at 120 ms the voice is said to arrive early`);
    await page.screenshot({path: `tests/e2e/shot_latency_settings_${tag}.png`});
    await page.context().close();
  }

  // 11. file://: no history and no Studio: the attempts in this tab, this song only, and the result says so.
  { const {page, logs} = await fresh('file://' + resolve(library, files.main));
    for (let i = 0; i < 12; i++) await page.evaluate(() => { const H = window.Luma.test.history, d = window.Luma.song().duration; window.Luma.test.injectTake({a: 0, b: d, points: H.synthPoints({lag: 60, seed: Math.random() * 1e6 | 0}, 0, d)}); });
    const r = await calc(page);
    assert(r.result.ok && r.result.only && near(r.result.latency, 60, 10), `file://: 12 attempts in the tab suggest 60 (got ${r.result.latency?.toFixed(1)})`);
    assert(r.text.includes('лише ця пісня'), 'file://: the result says only this song counted: ' + r.text);
    assert(logs.length === 0, 'file://: clean console ' + logs.join(' | '));
    await page.context().close(); }
} finally {
  await browser.close(); cleanup();
}
