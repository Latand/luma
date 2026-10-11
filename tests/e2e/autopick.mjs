// «Обери за мене» in Studio: difficulty from /status, the tile in the song picker and the button on the home card, the
// first pick from a fresh state, a step up at the usual score, a step down after a pass that did not start at 0, no
// countdown when nobody sang, a repeat that never moves the step, random picks without repeats, the history read
// without creating the base, one step below last time at a new start, leaving, 390 px and desktop layouts, the
// activity events and the real autoplay policy after one click. docs/design/AUTOPICK.md
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, utimesSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {launch, assert} from './lib.mjs';

const studio = process.env.LUMA_STUDIO_URL || 'http://127.0.0.1:8793/';
const library = process.env.LUMA_TEST_LIBRARY;
const py = process.env.LUMA_PY || '.venv/bin/python';
if (!library) { console.error('FAIL autopick: LUMA_TEST_LIBRARY is not set (tests/e2e/run.sh exports it)'); process.exit(1); }
if (!existsSync(`${library}/Luma_Lesson_1_Novachok.html`)) execFileSync(py, ['lessons/build_lessons.py', '--songs', library], {maxBuffer: 64 << 20});

// ── fixtures: seven copies of the demo whose melody is spread and transposed so that D differs, and one cut short ───
// [spread around the mean pitch, transpose] → D (studio/difficulty.py). Seven songs make steps of 2, 2, 2 and 1.
const SHAPES = [[1, 0, 4], [1.5, 0, 13], [2, 0, 18], [1, 3, 20], [1.5, 3, 25], [2, 3, 31], [2.5, 0, 44]];
const demo = readFileSync('examples/demo/Luma_Demo.html', 'utf8'), A = 'window.LUMA_SONG=', B = ';window.LUMA_ASSETS=';
const head = demo.indexOf(A) + A.length, tail = demo.indexOf(B, head), base = JSON.parse(demo.slice(head, tail));
const mean = base.notes.reduce((a, n) => a + n.m, 0) / base.notes.length;
const fx = SHAPES.map(([spread, shift, D], k) => ({k: k + 1, D, file: `Luma_Autopick_${k + 1}.html`, title: `Підбір ${k + 1}`, hash: createHash('sha256').update('autopick-fixture-' + (k + 1)).digest('hex'), spread, shift}));
const cut = {file: 'Luma_Autopick_Cut.html', hash: createHash('sha256').update('autopick-fixture-cut').digest('hex')};
const now = Date.now() / 1000;
for (const f of [...fx, {...cut, title: 'Підбір обрізаний', spread: 1, shift: 0, k: 9}]) {
  const song = {...base, title: f.title, id: 'autopick-' + f.hash.slice(0, 12), sourceId: f.hash,
    notes: base.notes.map(n => { const m = +(mean + (n.m - mean) * f.spread + f.shift).toFixed(2); return {...n, m, n: Math.round(m)}; })};
  let html = demo.slice(0, head) + JSON.stringify(song).replace(/</g, '\\u003c') + demo.slice(tail);
  if (f.file === cut.file) html = html.slice(0, head + 2000);   // LUMA_SONG cut in the middle: no difficulty
  writeFileSync(join(library, f.file), html); utimesSync(join(library, f.file), now - 60 * f.k, now - 60 * f.k);   // picker order 1…7, the cut one last
}
const byHash = Object.fromEntries(fx.map(f => [f.hash, f]));
const cleanup = () => { for (const f of [...fx, cut]) rmSync(join(library, f.file), {force: true}); rmSync(tmp, {recursive: true, force: true}); };
// A silent fake microphone: the voice in these tests is pushed in by hand.
const tmp = mkdtempSync(join(tmpdir(), 'luma-autopick-')), silence = join(tmp, 'silence.wav');
{ const rate = 48000, n = rate * 60, wav = Buffer.alloc(44 + n * 2);
  wav.write('RIFF', 0); wav.writeUInt32LE(36 + n * 2, 4); wav.write('WAVE', 8); wav.write('fmt ', 12); wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(n * 2, 40); writeFileSync(silence, wav); }
const media = ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--use-file-for-fake-audio-capture=' + silence];

// Init script for the Studio page only: every luma:* message it receives, and Math.random fed from window.__rand while
// that holds numbers (no product hook: the page's own Math.random is replaced before its script runs).
const init = () => { if (window !== window.top) return; window.__luma = [];
  addEventListener('message', e => { const d = e.data; if (!d || typeof d !== 'object' || !String(d.type).startsWith('luma:')) return;
    window.__luma.push({type: d.type, file: d.file, ok: d.ok, reason: d.reason}); console.log('luma-msg ' + JSON.stringify({type: d.type, file: d.file, ok: d.ok, reason: d.reason})); });
  const real = Math.random; Math.random = () => { const q = window.__rand; return Array.isArray(q) && q.length ? q.shift() : real(); }; };
async function openStudio(browser, viewport) {
  const page = await browser.newPage({viewport}), logs = [];   // a new context each time: empty storage and history
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) logs.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', e => logs.push('PAGEERROR ' + e.message));
  await page.addInitScript(init); await page.goto(studio); return {page, logs};
}
const msgs = (page, type) => page.evaluate(type => window.__luma.filter(m => m.type === type), type);
const waitMsg = (page, type, n, ms = 15000) => page.waitForFunction(([type, n]) => window.__luma.filter(m => m.type === type).length > n, [type, n], {timeout: ms});
const frameOf = async page => (await page.$('#session iframe.sframe.shown'))?.contentFrame();
const waitSinging = (page, file, ms = 15000) => page.waitForFunction(file => { const f = document.querySelector('#session iframe.sframe.shown'); return f && f.src.endsWith('/song/' + file) && f.contentWindow.Luma?.diagnostics().mode === 'singing'; }, file, {timeout: ms});
const singingFile = page => page.evaluate(() => { const f = document.querySelector('#session iframe.sframe.shown'); return f ? decodeURIComponent(new URL(f.src).pathname.split('/').pop()) : null; });
const waitWhy = (page, why, ms = 10000) => page.waitForFunction(why => document.querySelector('#session .sintro:not(.out):not(.over) .card .why')?.dataset.why === why, why, {timeout: ms});
const stored = page => page.evaluate(() => JSON.parse(localStorage.getItem('luma.autopick') || 'null'));
const shot = async (page, step, w) => { await page.waitForTimeout(400); await page.screenshot({path: `tests/e2e/shot_autopick_${step}_${w}.png`}); };
const fits = page => page.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth);
// Stop whatever the trainer is doing, then sing a window through the driven clock: at the target pitch, or silence.
const sing = (frame, from, to, voice = true) => frame.evaluate(async ([from, to, voice]) => {
  const L = window.Luma, T = L.test, d = () => L.diagnostics();
  if (d().mode !== 'idle' || d().busy) document.getElementById('stopBtn').click();
  for (let i = 0; i < 100 && (d().mode !== 'idle' || d().busy || d().pending); i++) await new Promise(r => setTimeout(r, 50));
  const end = L.song().singEnd, a = from === 'end' ? end : from, b = to === 'end' ? end : to;
  T.closeTrace(); T.seek(a); const st = T.fakeSing({a, b}); if (!st) return {error: 'busy', d: d()};
  for (let t = 0; t <= b - a + 1e-9; t += .02) { const ref = voice && L.targetAt(a + t); T.livePush(ref ? {t: st.when + t, f: 440 * 2 ** ((ref.m - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: st.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0}); }
  T.fakeTick(st.when + (b - a)); return {...T.fakeFinish(), a, b, end};
}, [from, to, voice]);
// The visible card: «Далі», the reason line, and whether everything fits: inside the viewport, buttons ≥ 36 px, text ≥ 11 px.
const card = page => page.evaluate(() => {
  const c = document.querySelector('#session .sintro:not(.out):not(.over) .card'); if (!c) return null;
  const why = c.querySelector('.why'), W = innerWidth, H = innerHeight, r = c.getBoundingClientRect();
  const buttons = [...c.querySelectorAll('button')].filter(b => b.offsetParent).map(b => { const x = b.getBoundingClientRect(); return {id: b.id, text: b.textContent, h: x.height, inside: x.top >= 0 && x.bottom <= H && x.left >= 0 && x.right <= W}; });
  const texts = [...c.querySelectorAll('*')].filter(n => n.childNodes.length && [...n.childNodes].some(t => t.nodeType === 3 && t.textContent.trim()) && n.offsetParent);
  return {eyebrow: c.querySelector('.eyebrow')?.textContent, next: c.querySelector('.nwhat strong')?.textContent || null, ring: c.querySelector('.ring b')?.textContent || null,
    auto: c.querySelector('.nrow .auto')?.textContent || null, why: why?.dataset.why || null, chip: why?.querySelector('.chip')?.textContent || null, reason: why?.lastChild.textContent || null,
    meter: why ? [...why.querySelectorAll('.meter i')].map(i => i.className === 'on' ? 1 : 0).join('') : null,
    whyInside: !why || (why.getBoundingClientRect().right <= W && why.getBoundingClientRect().left >= 0), minFont: Math.min(99, ...texts.map(n => parseFloat(getComputedStyle(n).fontSize))),
    bottom: r.bottom, fits: r.bottom <= H + .5 && document.documentElement.scrollWidth === document.documentElement.clientWidth, buttons};
});
const layoutOk = c => c && c.fits && c.whyInside && c.minFont >= 11 && c.buttons.length && c.buttons.every(b => b.h >= 36 && b.inside);
const layoutText = c => JSON.stringify(c && {bottom: Math.round(c.bottom), fits: c.fits, whyInside: c.whyInside, minFont: c.minFont, buttons: c.buttons.map(b => [b.id, Math.round(b.h), b.inside])});
// The tile (or the home card): its text, its button and whether it fits.
const entry = (page, sel, button) => page.evaluate(([sel, button]) => {
  const box = document.querySelector(sel), b = document.getElementById(button); if (!box || !b) return null; const x = b.getBoundingClientRect(), W = innerWidth;
  const texts = [...box.querySelectorAll('*')].filter(n => [...n.childNodes].some(t => t.nodeType === 3 && t.textContent.trim()) && n.offsetParent);
  return {steps: [...box.querySelectorAll('.steps > span:not(.meter), .steps > small')].map(n => n.textContent), meter: [...box.querySelectorAll('.meter i')].map(i => i.className === 'on' ? 1 : 0).join(''),
    button: b.textContent, disabled: b.disabled, h: x.height, inside: x.left >= 0 && x.right <= W && x.top >= 0, minFont: Math.min(99, ...texts.map(n => parseFloat(getComputedStyle(n).fontSize))),
    right: box.getBoundingClientRect().right <= W, fits: document.documentElement.scrollWidth === document.documentElement.clientWidth};
}, [sel, button]);
const toPicker = async page => {   // «Почати заняття», then skip the three lessons
  await page.locator('#sessionStart').click();
  for (let i = 0; i < 3; i++) { await page.waitForSelector('#session .sintro .card'); await page.locator('#sessionSkip').click(); }
  await page.waitForSelector('#session .spicker #autopickStart:not(:disabled)');
};

const browser = await launch([...media, '--autoplay-policy=no-user-gesture-required']);
const sessions = [];
try {
  for (const [width, height] of [[390, 844], [1440, 900]]) {
    const {page, logs} = await openStudio(browser, {width, height});
    await page.waitForFunction(() => !document.getElementById('sessionEntry').hidden);
    sessions.push(await page.evaluate(() => window.LumaActivity.session));

    // ── 1 · /status: a song hash and D for every fixture, null for the cut one ───────────────────────────────────
    const t0 = Date.now(); await page.waitForFunction(() => autoSongs().length === 7, null, {timeout: 20000});
    const listed = await page.evaluate(() => Object.fromEntries(librarySongs.filter(s => /^Luma_Autopick_/.test(s.name)).map(s => [s.name, [s.songHash, s.difficulty]])));
    assert(fx.every(f => listed[f.file]?.[0] === f.hash && listed[f.file][1] === f.D) && JSON.stringify(listed[cut.file]) === '[null,null]',
      `${width}: /status lists songHash and D for every fixture (${Date.now() - t0} ms), null for the cut trainer ` + JSON.stringify(listed));

    // ── 2 · history safety: reading the history in a fresh profile creates no base ───────────────────────────────
    const read = await page.evaluate(async () => ({runs: (await readRuns()).length, bases: (await indexedDB.databases()).map(d => d.name)}));
    assert(read.runs === 0 && !read.bases.includes('luma'), `${width}: reading the history of a fresh profile returns nothing and creates no luma base ` + JSON.stringify(read));

    // ── 3 · the home card: «Одразу пісні: обери за мене» with the step it will start at ─────────────────────────────
    let e = await entry(page, '#sessionEntry', 'autopickHome');
    assert(e && e.steps.join('|') === 'Обери за мене: ступінь 1 з 4|без розспівки' && e.meter === '1000' && !e.disabled && e.h >= 36 && e.inside && e.right && e.fits && e.minFont >= 11,
      `${width}: the home card offers the autopick at step 1 and fits ` + JSON.stringify(e));
    const start = await page.locator('#sessionStart').boundingBox();
    assert(start && start.y + start.height <= height, `${width}: «Почати заняття» stays in the first viewport ` + JSON.stringify(start));
    await shot(page, 'home', width);

    // ── 4 · the picker tile, fresh state ───────────────────────────────────────────────────────────────────────────
    await toPicker(page);
    e = await entry(page, '#session .autotile', 'autopickStart');
    const heads = await page.evaluate(() => [...document.querySelectorAll('#session .spicker h2')].map(h => h.firstChild.textContent));
    assert(e && e.steps.join('|') === 'Почнемо зі ступеня 1 з 4' && e.button === 'Обери за мене' && JSON.stringify(heads) === '["Пісня","Або обери сам"]',
      `${width}: the tile starts at step 1 with no "last time" line; the grid is headed «Або обери сам» ` + JSON.stringify({e, heads}));
    assert(e.h >= 36 && e.inside && e.right && e.fits && e.minFont >= 11 && await fits(page), `${width}: the tile fits ` + JSON.stringify(e));
    await shot(page, 'picker', width);

    // ── 5 · «Обери за мене» opens the easiest song (random fixed at 0) and it sings by itself ────────────────────────
    let auto = (await msgs(page, 'luma:autostart')).length;
    await page.evaluate(() => { window.__rand = [0]; });
    await page.locator('#autopickStart').click(); await waitSinging(page, fx[0].file); await waitMsg(page, 'luma:autostart', auto);
    let st = await stored(page);
    assert((await msgs(page, 'luma:autostart')).at(-1).ok && st.v === 1 && st.step === 1 && st.recent[0] === fx[0].hash,
      `${width}: the first pick is a step-1 song, it sings at once, and luma.autopick remembers it ` + JSON.stringify(st));

    // ── 6 · up: three earlier attempts at 40 % (the usual), then a pass above it ──────────────────────────────────
    let frame = await frameOf(page);
    await frame.evaluate(async () => { const T = window.Luma.test, tot = T.history.totals().song, day = k => new Date(Date.now() - k * 86400e3).toISOString();
      await T.history.seedMany([3, 2, 1].map(k => ({match: 4000, target: tot, songTarget: tot, startedAt: day(k)}))); });
    let fin = (await msgs(page, 'luma:finished')).length;
    await sing(frame, 0, 'end'); await waitMsg(page, 'luma:finished', fin); await waitWhy(page, 'up');
    let c = await card(page); st = await stored(page);
    assert(byHash[st.recent[0]]?.k === 3 || byHash[st.recent[0]]?.k === 4, `${width}: after a pass above the usual the next pick is a step-2 song ` + JSON.stringify(st));
    assert(st.step === 2 && c.chip === '↑ складніша' && c.next === byHash[st.recent[0]].title && c.meter === '1100' && /^ступінь 2 з 4 · 100 % ≥ твоїх звичних 40 %$/.test(c.reason),
      `${width}: «Далі» names it, ↑ складніша, step 2, and the reason against the usual 40 % ` + JSON.stringify(c));
    assert(/ · завершено · обрано за тебе$/.test(c.eyebrow) && c.ring === '3' && c.buttons.map(b => b.id).join() === 'resultNow,resultRepeat,resultSongs', `${width}: the card says it was picked for you and counts down ` + JSON.stringify(c));
    assert(layoutOk(c), `${width}: the card with the reason line fits ` + layoutText(c));
    const runs = await page.evaluate(async () => (await readRuns()).length);
    assert(runs >= 4, `${width}: the trainer opened after the read still created the history and wrote its run (${runs} runs)`);
    await shot(page, 'result_up', width);

    // ── 7 · the countdown opens the picked song and it sings ───────────────────────────────────────────────────────
    const second = byHash[st.recent[0]];
    auto = (await msgs(page, 'luma:autostart')).length;
    await waitSinging(page, second.file, 8000); await waitMsg(page, 'luma:autostart', auto);
    assert((await msgs(page, 'luma:autostart')).at(-1).ok, `${width}: after 3 s the picked song is singing`);

    // ── 8 · down: a pass that did not start at 0 (what a lives rewind leaves) steps down ──────────────────────────────
    frame = await frameOf(page); fin = (await msgs(page, 'luma:finished')).length;
    await sing(frame, 5, 'end'); await waitMsg(page, 'luma:finished', fin); await waitWhy(page, 'lives');
    c = await card(page); st = await stored(page);
    const third = byHash[st.recent[0]];
    assert(st.step === 1 && c.chip === '↓ легша' && c.meter === '1000' && c.reason === 'ступінь 1 з 4 · спроба з перемотуванням життів' && third.k === 2,
      `${width}: a pass from 0:05 steps down to 1 and picks the step-1 song not sung lately ` + JSON.stringify({c, st}));
    assert(layoutOk(c), `${width}: the step-down card fits ` + layoutText(c));
    await shot(page, 'result_lives', width);

    // ── 9 · silent: nobody sang → the pick, no ring, nothing starts ────────────────────────────────────────────────
    await page.locator('#resultNow').click(); await waitSinging(page, third.file);
    frame = await frameOf(page); fin = (await msgs(page, 'luma:finished')).length;
    await sing(frame, 0, 'end', false); await waitMsg(page, 'luma:finished', fin); await waitWhy(page, 'silent');
    auto = (await msgs(page, 'luma:autostart')).length;
    c = await card(page); st = await stored(page);
    assert(!c.ring && c.buttons[0].id === 'resultNow' && c.buttons[0].text === 'Почати' && c.chip === '= той самий ступінь' && c.auto === 'Далі · без відліку' && c.reason === 'ступінь 1 з 4 · голосу майже не було'
      && st.step === 1 && byHash[st.recent[0]].k === 1,
      `${width}: a silent pass keeps step 1, names the pick with «Почати» and no ring ` + JSON.stringify({c, st}));
    await page.waitForTimeout(4000);
    assert((await msgs(page, 'luma:autostart')).length === auto && !(await page.$('#session iframe.sframe.shown')) && (await card(page))?.why === 'silent', `${width}: 4 s later nothing has started`);
    assert(layoutOk(c), `${width}: the silent card fits ` + layoutText(c));

    // ── 10 · a repeat after silence counts; a second repeat never moves the step ─────────────────────────────────────
    await page.locator('#resultRepeat').click(); await waitSinging(page, third.file, 8000);
    fin = (await msgs(page, 'luma:finished')).length;
    await sing(await frameOf(page), 0, 'end'); await waitMsg(page, 'luma:finished', fin); await waitWhy(page, 'up');
    st = await stored(page); const named = (await card(page)).next;
    assert(st.step === 2, `${width}: singing it after the silent pass climbs to step 2 ` + JSON.stringify(st));
    await page.locator('#resultRepeat').click(); await waitSinging(page, third.file, 8000);
    fin = (await msgs(page, 'luma:finished')).length;
    await sing(await frameOf(page), 0, 'end'); await waitMsg(page, 'luma:finished', fin); await waitWhy(page, 'repeat');
    c = await card(page); const st2 = await stored(page);
    assert(st2.step === 2 && JSON.stringify(st2.recent) === JSON.stringify(st.recent) && c.next === named && c.chip === '= той самий ступінь' && c.reason === 'ступінь 2 з 4 · повтор не змінює ступінь' && c.ring === '3',
      `${width}: «Повторити» and a good result leave the step and the pick where the first result put them ` + JSON.stringify({c, st2}));
    await shot(page, 'result_repeat', width);

    // ── 11 · «До пісень» ends the autopick: the next song follows the picker again ────────────────────────────────────
    await page.locator('#resultSongs').click(); await page.waitForSelector('#session .spicker');
    assert(!(await page.evaluate(() => S.auto)), `${width}: «До пісень» shows the picker and turns the autopick off`);
    const order = await page.evaluate(() => S.songs.map(s => s.name));
    await page.locator('#session .spicker .song button.primary').first().click(); await waitSinging(page, order[0]);
    fin = (await msgs(page, 'luma:finished')).length;
    await sing(await frameOf(page), 0, 'end'); await waitMsg(page, 'luma:finished', fin);
    await page.waitForFunction(() => document.querySelector('#session .sintro:not(.out) .card')?.dataset.next === 'song');
    c = await card(page);
    assert(c.next === 'Підбір 2' && !c.why && !/обрано за тебе/.test(c.eyebrow) && order[1] === fx[1].file, `${width}: a song from the list counts into the next one in picker order, with no autopick line ` + JSON.stringify(c));
    await page.locator('#sessionClose').click(); await page.waitForFunction(() => document.getElementById('session').hidden);

    // ── 12 · a new start: one step below last time ────────────────────────────────────────────────────────────────
    await page.evaluate(() => { const v = JSON.parse(localStorage.getItem('luma.autopick')); v.step = 3; localStorage.setItem('luma.autopick', JSON.stringify(v)); syncAutopick(); });
    e = await entry(page, '#sessionEntry', 'autopickHome');
    assert(e.steps.join('|') === 'Обери за мене: ступінь 2 з 4|без розспівки' && e.meter === '1100', `${width}: the home card says step 2 after a stored step 3 ` + JSON.stringify(e.steps));
    await toPicker(page);
    e = await entry(page, '#session .autotile', 'autopickStart');
    assert(e.steps.join(' · ') === 'Почнемо зі ступеня 2 з 4 · минулого разу — ступінь 3' && e.meter === '1100' && e.right && e.fits, `${width}: the tile says «Почнемо зі ступеня 2 з 4 · минулого разу — ступінь 3» ` + JSON.stringify(e));
    await shot(page, 'picker_again', width);
    await page.locator('#sessionClose').click(); await page.waitForFunction(() => document.getElementById('session').hidden);

    // ── 13 · the home button: straight into a picked song, no lessons ──────────────────────────────────────────────
    auto = (await msgs(page, 'luma:autostart')).length;
    await page.locator('#autopickHome').click(); await page.waitForFunction(() => document.querySelector('#session iframe.sframe.shown')?.contentWindow?.Luma?.diagnostics().mode === 'singing', null, {timeout: 15000});
    await waitMsg(page, 'luma:autostart', auto);
    // By now the history holds this run's passes, so D′ has moved songs between steps: step 2 is read from the page's ladder.
    const picked = byHash[(await stored(page)).recent[0]], bar = await page.evaluate(async () => { const songs = autoSongs(), lad = ladder(songs, autoHistory(await readRuns(), songs));
      return {dots: document.querySelectorAll('#sessionDots .dot').length, skip: document.getElementById('sessionSkip').textContent, auto: S.auto, step2: lad.list.filter(x => x.step === 2).map(x => x.s.songHash)}; });
    assert(picked && bar.step2.includes(picked.hash) && (await singingFile(page)) === picked.file && (await stored(page)).step === 2 && bar.dots === 1 && bar.skip === 'До пісень' && bar.auto,
      `${width}: «Одразу пісні» opens a step-2 song and it sings, with one dot and «До пісень» ` + JSON.stringify({picked: picked?.k, step2: bar.step2.map(h => byHash[h]?.k), dots: bar.dots, skip: bar.skip}));
    await shot(page, 'home_song', width);
    await page.locator('#sessionClose').click(); await page.waitForFunction(() => document.getElementById('session').hidden);

    // ── 14 · random within a step, no repeats while unpicked songs remain ─────────────────────────────────────────
    const rnd = await page.evaluate(() => {
      const songs = Array.from({length: 24}, (_, k) => ({name: 'x' + k, songHash: String(k).padStart(2, '0'), difficulty: k}));
      const lad = ladder(songs, {baseline: 50, pooled: new Map()}), seq = [.9, .1, .5, .7, .3, .2, .6];
      window.__rand = seq.slice(); let recent = []; const picks = [];
      for (let i = 0; i < 7; i++) { const {x} = pickIn(lad, 2, recent, picks.at(-1) || null); picks.push(x.s.songHash); recent = remember(recent, x.s.songHash, songs.length); }
      window.__rand = [0]; const a = pickIn(lad, 2, [], null).x.s.songHash; window.__rand = [.99]; const b = pickIn(lad, 2, [], null).x.s.songHash;
      // D′ = D + 0.5 × clamp(usual − pooled, ±20): 20 under the usual counts 10 harder, 40 under still 10, 10 over 5 easier
      const own = ladder([{songHash: 'p', difficulty: 40}, {songHash: 'q', difficulty: 40}, {songHash: 'r', difficulty: 40}, {songHash: 's', difficulty: 40}], {baseline: 50, pooled: new Map([['p', 30], ['q', 10], ['r', 60]])});
      return {steps: lad.list.map(x => x.step).join(''), picks, a, b, own: Object.fromEntries(own.list.map(x => [x.s.songHash, x.Dp]))};
    });
    assert(rnd.steps === '111111222222333333444444' && new Set(rnd.picks.slice(0, 6)).size === 6 && rnd.picks.slice(0, 6).every(h => +h >= 6 && +h < 12) && rnd.picks[6] === rnd.picks[0] && rnd.a !== rnd.b && JSON.stringify(rnd.own) === '{"r":35,"s":40,"p":50,"q":50}',
      `${width}: six picks in a step of six never repeat, the seventh is the one picked longest ago, and another random sequence starts elsewhere; D′ follows the personal weight ` + JSON.stringify(rnd));

    // ── 15 · clean console in Studio and in every frame it opened ─────────────────────────────────────────────────
    await page.evaluate(() => window.LumaActivity.flush());
    assert(logs.length === 0, `${width}: console clean ` + JSON.stringify(logs.slice(0, 5)));
    await page.close();
  }

  // ── 16 · activity: the autopick events, with D, D′, the usual score and the score ───────────────────────────────
  const folder = join(library, 'logs', 'activity');
  let events = [];
  for (let i = 0; i < 30; i++) {
    events = existsSync(folder) ? readdirSync(folder).filter(f => f.endsWith('.jsonl')).flatMap(f => readFileSync(join(folder, f), 'utf8').trim().split('\n').filter(Boolean).map(l => JSON.parse(l))).filter(e => sessions.includes(e.session)) : [];
    if (['start', 'up', 'lives', 'silent'].every(w => events.some(e => e.type === 'autopick' && e.data.why === w))) break;
    await new Promise(r => setTimeout(r, 200));
  }
  const ap = events.filter(e => e.type === 'autopick').map(e => e.data), up = ap.find(d => d.why === 'up');
  assert(['start', 'up', 'lives', 'silent'].every(w => ap.some(d => d.why === w)) && ap.filter(d => d.why === 'start').every(d => d.score === null),
    'the activity log has autopick events start, up, lives and silent ' + JSON.stringify(ap.map(d => d.why)));
  assert(up && up.from === 1 && up.to === 2 && byHash[up.songHash] && Number.isInteger(up.D) && typeof up.Dp === 'number' && up.baseline === 40 && up.score === 100 && up.pool >= 1,
    'an autopick event carries the steps, the song, D, D′, the usual score, the score and the pool ' + JSON.stringify(up));
  assert(events.some(e => e.type === 'click' && e.data.id === 'autopickStart') && events.some(e => e.type === 'click' && e.data.id === 'autopickHome'), 'clicks on the tile and the home button are logged by id');
} finally {
  await browser.close();
}

// ── 17 · the real autoplay policy: one real click on «Одразу пісні», then no input at all ─────────────────────────────
// The history is read between the click and the frame; the song must still start by itself.
try {
  const strict = await launch(media), {page, logs} = await openStudio(strict, {width: 1440, height: 900});
  const lines = []; page.on('console', m => { if (m.text().startsWith('luma-msg ')) lines.push(JSON.parse(m.text().slice(9))); });
  await page.locator('#autopickHome:not(:disabled)').click({timeout: 20000});
  const deadline = Date.now() + 15000; while (Date.now() < deadline && !lines.some(l => l.type === 'luma:autostart')) await page.waitForTimeout(200);
  const ans = lines.find(l => l.type === 'luma:autostart');
  assert(ans && ans.ok === true && fx.slice(0, 2).some(f => f.file === ans.file), 'real policy: after one click on «Одразу пісні» the picked step-1 song starts by itself ' + JSON.stringify(ans));
  assert(!logs.length, 'real policy: console clean ' + JSON.stringify(logs.slice(0, 3)));
  await strict.close();
} finally {
  cleanup();
}
