// «Заняття» and album covers in Studio: the lessons one after another in a session frame, each sung pass ending at the
// last note with a result card (today against the median, a chart per day), a 3-2-1 into the next step that starts
// singing by itself, «Повторити», skip and close during the countdown, the browser refusing sound, songs one after
// another in picker order, lives mode, the activity log, 390 px and desktop layouts, reduced motion, and a cover
// extracted from a fixture original next to a song without one. docs/design/SESSION_FLOW_RESULTS.md
import {execFileSync} from 'node:child_process';
import {copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, unlinkSync, utimesSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {launch, assert} from './lib.mjs';

const studio = process.env.LUMA_STUDIO_URL || 'http://127.0.0.1:8793/';
const library = process.env.LUMA_TEST_LIBRARY;
const py = process.env.LUMA_PY || '.venv/bin/python';
if (!library) { console.error('FAIL session: LUMA_TEST_LIBRARY is not set (tests/e2e/run.sh exports it)'); process.exit(1); }

// ── fixtures: two song trainers (copies of the demo), one with an original carrying a letterboxed PNG and a square JPEG
const demo = 'examples/demo/Luma_Demo.html', pkg = `${library}/Cover_Fixture`;
const added = [`${library}/Luma_Cover_Fixture.html`, `${library}/Luma_No_Cover.html`];
if (!existsSync(`${library}/Luma_Lesson_1_Novachok.html`)) execFileSync(py, ['lessons/build_lessons.py', '--songs', library], {maxBuffer: 64 << 20});
const defs = JSON.parse(execFileSync(py, ['lessons/build_lessons.py', '--definitions'], {encoding: 'utf8', maxBuffer: 64 << 20}));
const lessonFiles = defs.lessons.map(l => l.file);
added.forEach((f, k) => { copyFileSync(demo, f); const t = Date.now() / 1000 - 60 * k; utimesSync(f, t, t); });   // distinct mtimes: a stable picker order
mkdirSync(pkg, {recursive: true});
const ff = (...a) => execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...a]);
ff('-f', 'lavfi', '-i', 'color=red:s=64x36', '-frames:v', '1', `${pkg}/wide.png`);
ff('-f', 'lavfi', '-i', 'color=blue:s=48x48', '-frames:v', '1', `${pkg}/square.jpg`);
ff('-f', 'lavfi', '-i', 'sine=d=1', '-i', `${pkg}/wide.png`, '-i', `${pkg}/square.jpg`, '-map', '0', '-map', '1', '-map', '2', '-c:a', 'aac', '-c:v:0', 'png', '-c:v:1', 'mjpeg', '-disposition:v', 'attached_pic', `${pkg}/original.m4a`);
unlinkSync(`${pkg}/wide.png`); unlinkSync(`${pkg}/square.jpg`);
const backfill = execFileSync(py, ['studio/covers.py', '--songs', library], {encoding: 'utf8'}).trim();
assert(/extracted 1/.test(backfill) && !/Cover_Fixture/.test(backfill), 'covers.py extracts the fixture cover and prints counts only: ' + backfill);
// A silent fake microphone: the voice in these tests is pushed in by hand, and Chrome's beep must not sing along.
const tmp = mkdtempSync(join(tmpdir(), 'luma-session-')), silence = join(tmp, 'silence.wav');
{ const rate = 48000, n = rate * 60, wav = Buffer.alloc(44 + n * 2);
  wav.write('RIFF', 0); wav.writeUInt32LE(36 + n * 2, 4); wav.write('WAVE', 8); wav.write('fmt ', 12); wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(n * 2, 40); writeFileSync(silence, wav); }
const cleanup = () => { for (const f of added) rmSync(f, {force: true}); rmSync(pkg, {recursive: true, force: true}); rmSync(tmp, {recursive: true, force: true}); };
const media = ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--use-file-for-fake-audio-capture=' + silence];

// Every luma:* message the Studio page receives, recorded by an init script: nothing here is evaluated in the page, so
// it grants no user activation. The console line lets the real-policy check read them without page.evaluate either.
const collector = () => { if (window !== window.top) return; window.__luma = [];
  addEventListener('message', e => { const d = e.data; if (!d || typeof d !== 'object' || !String(d.type).startsWith('luma:')) return;
    const m = {type: d.type, file: d.file, ok: d.ok, reason: d.reason, result: d.result, at: performance.now()}; window.__luma.push(m); console.log('luma-msg ' + JSON.stringify({type: d.type, file: d.file, ok: d.ok, reason: d.reason}));
    setTimeout(() => { m.card = !!document.querySelector('#session .rcard'); }, 50); }); };
async function openStudio(browser, viewport) {
  const page = await browser.newPage({viewport}), logs = [];
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) logs.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', e => logs.push('PAGEERROR ' + e.message));
  await page.addInitScript(collector); await page.goto(studio); return {page, logs};
}
// The last finish, once the collector has looked for the card 50 ms after it.
const lastFinish = async page => { await page.waitForFunction(() => 'card' in (window.__luma.filter(m => m.type === 'luma:finished').at(-1) || {}), null, {timeout: 3000}); return (await msgs(page, 'luma:finished')).at(-1); };
const msgs = (page, type) => page.evaluate(type => window.__luma.filter(m => m.type === type), type);
const waitMsg = (page, type, n, ms = 15000) => page.waitForFunction(([type, n]) => window.__luma.filter(m => m.type === type).length > n, [type, n], {timeout: ms});
const frameOf = async page => (await page.$('#session iframe.sframe.shown'))?.contentFrame();
const frameSrc = page => page.evaluate(() => { const f = document.querySelector('#session iframe.sframe'); return f ? new URL(f.src).pathname : null; });
const dots = page => page.evaluate(() => [...document.querySelectorAll('#sessionDots .dot')].map(d => d.className.replace('dot', '').trim() || '-'));
const cardNext = page => page.evaluate(() => document.querySelector('#session .sintro .card')?.dataset.next ?? null);
const waitCard = (page, next, ms = 10000) => page.waitForFunction(next => document.querySelector('#session .sintro:not(.over) .card')?.dataset.next === next, next, {timeout: ms});
const waitSinging = (page, file, ms = 15000) => page.waitForFunction(file => { const f = document.querySelector('#session iframe.sframe.shown'); return f && f.src.endsWith('/song/' + file) && f.contentWindow.Luma?.diagnostics().mode === 'singing'; }, file, {timeout: ms});
const shot = async (page, step, w) => { await page.waitForTimeout(400); await page.screenshot({path: `tests/e2e/shot_session_${step}_${w}.png`}); };   // after the card's rise
const fits = page => page.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth);
// Stop whatever the trainer is doing, then sing a window at the exact target pitches through the driven clock. from/to
// are song seconds, or 'end' for the trainer's singEnd; off: cents off the target for every frame.
const sing = (frame, from, to, off = 0) => frame.evaluate(async ([from, to, off]) => {
  const L = window.Luma, T = L.test, d = () => L.diagnostics();
  if (d().mode !== 'idle' || d().busy) document.getElementById('stopBtn').click();
  for (let i = 0; i < 100 && (d().mode !== 'idle' || d().busy || d().pending); i++) await new Promise(r => setTimeout(r, 50));
  const end = L.song().singEnd, a = from === 'end' ? end : from, b = to === 'end' ? end : to;
  T.closeTrace(); T.seek(a); const st = T.fakeSing({a, b}); if (!st) return {error: 'busy', d: d()};
  for (let t = 0; t <= b - a + 1e-9; t += .02) { const ref = L.targetAt(a + t); T.livePush(ref ? {t: st.when + t, f: 440 * 2 ** ((ref.m + off / 100 - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: st.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0}); }
  T.fakeTick(st.when + (b - a)); return {...T.fakeFinish(), a, b, end};
}, [from, to, off]);
// What a result card shows, and whether it fits: card inside the viewport, no sideways scroll, buttons tall enough and
// unclipped, chart type no smaller than 11 px.
const card = page => page.evaluate(() => {
  const c = document.querySelector('#session .sintro:not(.over) .card'); if (!c) return null;
  const q = s => c.querySelector(s), r = c.getBoundingClientRect(), H = innerHeight, W = innerWidth;
  const buttons = [...c.querySelectorAll('button')].filter(b => b.offsetParent).map(b => { const x = b.getBoundingClientRect(); return {id: b.id, text: b.textContent, h: x.height, inside: x.top >= 0 && x.bottom <= H && x.left >= 0 && x.right <= W, cls: b.className}; });
  return {next: c.dataset.next, eyebrow: q('.eyebrow')?.textContent, head: q('.rhead')?.textContent || null, line: q('.rline')?.textContent || null,
    cells: Object.fromEntries([...c.querySelectorAll('.rnum')].map(n => [n.dataset.cell, n.querySelector('b').textContent])),
    columns: [...c.querySelectorAll('.rchart svg path')].map(p => ({today: p.dataset.today === '1', title: p.querySelector('title')?.textContent})),
    chartFont: Math.min(99, ...[...c.querySelectorAll('.rchart svg text')].map(t => parseFloat(getComputedStyle(t).fontSize))),
    caption: q('.rchart .cap')?.textContent || null, ring: q('.ring b')?.textContent || null, nextTitle: q('.nwhat strong')?.textContent || null,
    bottom: r.bottom, fits: r.bottom <= H + .5 && document.documentElement.scrollWidth === document.documentElement.clientWidth, buttons,
    focus: document.activeElement?.id || document.activeElement?.textContent};
});
const layoutOk = c => c && c.fits && c.buttons.length && c.buttons.every(b => b.h >= 36 && b.inside) && (c.chartFont >= 11);
const layoutText = c => JSON.stringify(c && {bottom: Math.round(c.bottom), fits: c.fits, chartFont: c.chartFont, buttons: c.buttons.map(b => [b.id, Math.round(b.h), b.inside])});

const browser = await launch([...media, '--autoplay-policy=no-user-gesture-required']);
const sessions = [];
try {
  for (const [width, height] of [[390, 844], [1440, 900]]) {
    const {page, logs} = await openStudio(browser, {width, height});
    await page.waitForSelector('#lib .song .cover');
    await page.waitForFunction(() => !document.getElementById('sessionEntry').hidden);
    sessions.push(await page.evaluate(() => window.LumaActivity.session));

    // ── 1 · library covers ────────────────────────────────────────────────────────────────────────────────────
    const cards = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#lib .song')].map(c => {
      const img = c.querySelector('.cover img');
      return [c.querySelector('details .meta').textContent.split(' · ').pop(), {src: img ? img.getAttribute('src') : null, ph: c.querySelector('.cover').classList.contains('ph'), letter: c.querySelector('.cover b')?.textContent || null}];
    })));
    await page.waitForFunction(() => [...document.querySelectorAll('#lib .cover img')].every(i => i.complete));
    const natural = await page.evaluate(() => document.querySelector('#lib .cover img')?.naturalWidth || 0);
    const fx = cards['Luma_Cover_Fixture.html'], none = cards['Luma_No_Cover.html'];
    assert(fx && /^\/cover\/Luma_Cover_Fixture\.html\?v=\d+$/.test(fx.src) && natural === 48, `${width}: the fixture card shows its extracted cover ` + JSON.stringify({fx, natural}));
    assert(none && none.ph && !none.src && none.letter, `${width}: a song without a picture gets the generated placeholder ` + JSON.stringify(none));
    assert(!lessonFiles.some(f => f in cards), `${width}: lessons are not library tiles`);
    assert(await fits(page), `${width}: the library fits without horizontal scrolling`);
    const cols = await page.evaluate(() => getComputedStyle(document.getElementById('lib')).gridTemplateColumns.split(' ').length);
    assert(cols === (width < 560 ? 2 : 4), `${width}: ${cols} columns of tiles`);
    await shot(page, 'library', width);

    // ── 2 · the entry sits in the first screen ───────────────────────────────────────────────────────────────
    const entry = await page.locator('#sessionStart').boundingBox();
    assert(entry && entry.y + entry.height <= height && entry.height >= 44, `${width}: «Почати заняття» is in the first viewport ` + JSON.stringify(entry));
    assert((await page.locator('#sessionPath').textContent()).includes('Пісня'), `${width}: the entry shows the path to a song`);

    // ── 3 · start → the card for lesson 1: no result yet, a 3-2-1 into it ───────────────────────────────────────
    await page.locator('#sessionStart').click(); await waitCard(page, 'lesson:1');
    assert(await page.locator('#session').isVisible(), `${width}: the session overlay opens`);
    assert(JSON.stringify(await dots(page)) === JSON.stringify(['current', '-', '-', '-']), `${width}: four dots, the first current ` + JSON.stringify(await dots(page)));
    let c = await card(page);
    assert(c.eyebrow === 'Урок 1 з 3' && (await page.locator('#session .sintro .title').textContent()) === defs.lessons[0].title && !c.head && c.ring === '3', `${width}: card 1 names lesson 1, has no result and counts from 3 ` + JSON.stringify({eyebrow: c.eyebrow, ring: c.ring}));
    assert(c.focus === 'resultNow' && c.buttons[0].text === 'Почати урок', `${width}: focus lands on «Почати урок»`);
    assert(layoutOk(c), `${width}: card 1 fits ` + layoutText(c));
    await shot(page, 'intro1', width);

    // ── 4 · «Почати урок» → lesson 1 in the frame, singing by itself ─────────────────────────────────────────────
    let auto = (await msgs(page, 'luma:autostart')).length;
    await page.locator('#resultNow').click(); await waitSinging(page, lessonFiles[0]);
    await waitMsg(page, 'luma:autostart', auto);
    let a = (await msgs(page, 'luma:autostart')).at(-1);
    assert(a.ok === true && a.file === lessonFiles[0] && (await frameSrc(page)) === '/song/' + lessonFiles[0], `${width}: lesson 1 opens and starts singing with no click ` + JSON.stringify(a));
    await shot(page, 'lesson1', width);

    // ── 5 · passes that stop short of the last note do not finish the lesson ─────────────────────────────────
    let frame = await frameOf(page);
    const end = await frame.evaluate(() => ({d: window.Luma.song().duration, e: window.Luma.song().singEnd}));
    const short = await sing(frame, end.d - 10, end.d - 5);
    const short2 = await sing(frame, end.e - 6, end.e - 1);
    await page.waitForTimeout(1500);
    assert(short.id && short2.id && (await frameSrc(page)) === '/song/' + lessonFiles[0] && !(await page.$('#session .sintro')) && !(await msgs(page, 'luma:finished')).length,
      `${width}: stopping at d − 5 s or 1 s before the last note does not count as finishing the lesson`);

    // ── 6 · a spoofed finish from Studio itself is ignored ────────────────────────────────────────────────────
    await page.evaluate(file => window.postMessage({type: 'luma:finished', file, match: 99}, location.origin), lessonFiles[0]);
    await page.waitForTimeout(600);
    assert(!(await page.$('#session .sintro')), `${width}: a message that does not come from the lesson frame is ignored`);

    // ── 7 · the whole lesson to the last note → result without history ───────────────────────────────────────
    const whole = await sing(frame, 0, 'end');
    await waitCard(page, 'lesson:2');
    const fin = await lastFinish(page);
    c = await card(page);
    assert(whole.b === end.e && fin.result && fin.result.full && fin.result.prev === 0 && fin.result.score === whole.pct, `${width}: singing to singEnd finishes the lesson, saved and scored as a full pass ` + JSON.stringify(fin.result));
    assert(c.eyebrow === 'Урок 1 з 3 · Новачок · пройдено' && c.head === 'Перший прохід!' && /Історії ще немає/.test(c.line), `${width}: first attempt: «Перший прохід!» and no history yet ` + JSON.stringify({eyebrow: c.eyebrow, head: c.head, line: c.line}));
    assert(c.cells.score === whole.pct + ' %' && !('median' in c.cells) && !('delta' in c.cells), `${width}: a score cell and no median or delta ` + JSON.stringify(c.cells));
    assert(c.columns.length === 1 && c.columns[0].today && /з’являться/.test(c.caption), `${width}: a chart with one column, today ` + JSON.stringify({columns: c.columns, caption: c.caption}));
    assert(c.focus === 'resultNow' && c.nextTitle === defs.lessons[1].title, `${width}: «Почати зараз» has the focus and «Далі» names lesson 2`);
    assert(JSON.stringify(await dots(page)) === JSON.stringify(['done', 'current', '-', '-']), `${width}: dot 1 done, dot 2 current ` + JSON.stringify(await dots(page)));
    assert(layoutOk(c), `${width}: the result card fits ` + layoutText(c));
    assert(fin.card, `${width}: the card is there at once after the finish`);
    await shot(page, 'result_first', width);

    // ── 8 · «Повторити урок 1»: the same lesson, singing again ─────────────────────────────────────────────────
    auto = (await msgs(page, 'luma:autostart')).length;
    await page.locator('#resultRepeat').click(); await waitSinging(page, lessonFiles[0], 6000);
    await waitMsg(page, 'luma:autostart', auto);
    assert((await msgs(page, 'luma:autostart')).at(-1).ok && (await dots(page))[0] === 'current', `${width}: «Повторити урок 1» reopens lesson 1 and it sings within 6 s`);

    // ── 9 · result with history: three earlier days plus the first pass; the median is theirs ──────────────────
    frame = await frameOf(page);
    const seeded = [60, 70, 90];
    await frame.evaluate(async vals => {
      const T = window.Luma.test, tot = T.history.totals().song, day = k => new Date(Date.now() - k * 86400e3).toISOString();
      await T.history.seedMany(vals.map((m, k) => ({match: m * 100, target: tot, songTarget: tot, startedAt: day(vals.length - k)})));
    }, seeded);
    const again = await sing(frame, 0, 'end');
    await waitCard(page, 'lesson:2');
    const all = [...seeded, whole.pct].sort((x, y) => x - y), median = Math.round((all[1] + all[2]) / 2), d = again.pct - median;
    c = await card(page);
    assert(c.cells.median === median + ' %' && c.cells.delta === (d > 0 ? '+' + d : d < 0 ? '−' + -d : '0'), `${width}: the median is the true median of the earlier full passes (${median} %), delta ${d} ` + JSON.stringify(c.cells));
    assert(c.head === (d >= 2 ? 'Чудово!' : d <= -2 ? 'Готово' : 'Готово!'), `${width}: the headline follows the delta: ${c.head}`);
    assert(c.columns.length === 4 && c.columns.at(-1).today && c.columns.slice(0, 3).every(x => !x.today), `${width}: four columns, the last one today ` + JSON.stringify(c.columns));
    assert(/^Збіг повних проходів по днях · (Легко|Звично|Точно) · Ноти · 1×$/.test(c.caption), `${width}: the caption names the ruler: ${c.caption}`);
    assert(layoutOk(c), `${width}: the card with history fits ` + layoutText(c));
    await shot(page, 'result_history', width);

    // ── 10 · skip during the countdown, then × during the next one ───────────────────────────────────────────
    await page.locator('#sessionSkip').click(); await waitCard(page, 'lesson:3');
    c = await card(page);
    assert(!c.head && JSON.stringify(await dots(page)) === JSON.stringify(['done', 'skipped', 'current', '-']), `${width}: «Пропустити урок» on the result marks lesson 2 skipped and shows lesson 3 without a result ` + JSON.stringify(await dots(page)));
    auto = (await msgs(page, 'luma:autostart')).length;
    await page.locator('#sessionClose').click(); await page.waitForFunction(() => document.getElementById('session').hidden);
    await page.waitForTimeout(4000);
    assert(!(await page.$('#session iframe')) && (await msgs(page, 'luma:autostart')).length === auto, `${width}: × during the countdown leaves: no frame and no auto-start afterwards`);
    assert(await page.evaluate(() => document.activeElement.id === 'sessionStart' && !document.body.classList.contains('locked')), `${width}: × returns focus to «Почати заняття»`);

    // ── 11 · the countdown runs out: 3, 2, 1, and lesson 1 opens and sings by itself ───────────────────────────
    await page.locator('#sessionStart').click(); await waitCard(page, 'lesson:1');
    const ring = [await page.locator('#session .ring b').textContent()]; const r0 = Date.now();
    await page.waitForTimeout(1100 - (Date.now() - r0)); ring.push(await page.locator('#session .ring b').textContent());
    await page.waitForTimeout(2100 - (Date.now() - r0)); ring.push(await page.locator('#session .ring b').textContent());
    auto = (await msgs(page, 'luma:autostart')).length;
    await waitSinging(page, lessonFiles[0], 6000); await waitMsg(page, 'luma:autostart', auto);
    assert(JSON.stringify(ring) === '["3","2","1"]' && Date.now() - r0 <= 6000, `${width}: the ring counts 3, 2, 1 and the lesson sings ${Date.now() - r0} ms after the card ` + JSON.stringify(ring));

    // ── 12 · the browser refuses sound: a visible start button over the trainer, and a real click starts it ─────
    await page.locator('#sessionSkip').click(); await waitCard(page, 'lesson:2');
    await page.waitForFunction(() => document.querySelector('#session iframe.sframe')?.contentWindow?.Luma);
    await page.evaluate(() => { document.querySelector('#session iframe.sframe').contentWindow.Luma.test.autostartBlock = 'audio'; });
    auto = (await msgs(page, 'luma:autostart')).length;
    await page.locator('#resultNow').click(); await waitMsg(page, 'luma:autostart', auto);
    await page.waitForSelector('#autostartBtn');
    const fb = await page.evaluate(() => { const b = document.getElementById('autostartBtn').getBoundingClientRect(); return {h: b.height, inside: b.top >= 0 && b.bottom <= innerHeight && b.left >= 0 && b.right <= innerWidth, title: document.querySelector('#autostartCard .title').textContent, text: document.querySelector('#autostartCard .goal').textContent}; });
    assert(fb.h >= 44 && fb.inside && fb.title === 'Урок 2 готовий' && /Браузер не дав/.test(fb.text), `${width}: refused sound shows «Почати співати» inside the viewport ` + JSON.stringify(fb));
    assert(await fits(page), `${width}: the start button card fits`);
    await shot(page, 'result_fallback', width);
    auto = (await msgs(page, 'luma:autostart')).length;
    await page.locator('#autostartBtn').click(); await waitMsg(page, 'luma:autostart', auto); await waitSinging(page, lessonFiles[1], 6000);
    assert((await msgs(page, 'luma:autostart')).at(-1).ok && !(await page.$('#autostartCard')), `${width}: a real click on it starts singing and the card goes`);

    // ── 13 · the last lesson finished → the result leads to the picker ─────────────────────────────────────────
    await page.locator('#sessionSkip').click(); await waitCard(page, 'lesson:3');
    await page.locator('#resultNow').click(); await waitSinging(page, lessonFiles[2]);
    await sing(await frameOf(page), 0, 'end'); await waitCard(page, 'picker');
    c = await card(page);
    assert(c.buttons[0].id === 'resultNow' && c.buttons[0].text === 'До пісень' && c.nextTitle === 'Вибір пісні' && c.head === 'Перший прохід!', `${width}: after lesson 3 the card leads to the song picker ` + JSON.stringify(c.buttons.map(b => b.text)));
    assert(JSON.stringify(await dots(page)) === JSON.stringify(['skipped', 'skipped', 'done', 'current']) && await page.locator('#sessionSkip').isHidden(), `${width}: the bar stands on the song dot ` + JSON.stringify(await dots(page)));
    assert(layoutOk(c), `${width}: the last-lesson card fits ` + layoutText(c));
    await shot(page, 'result_lastlesson', width);
    await page.waitForSelector('#session .spicker', {timeout: 6000});
    const picker = await page.evaluate(() => ({summary: [...document.querySelectorAll('#session .summary .chip')].map(c => c.textContent),
      cards: [...document.querySelectorAll('#session .spicker .song')].length, frame: !!document.querySelector('#session iframe'), skip: document.getElementById('sessionSkip').hidden,
      order: S.songs.map(s => s.name)}));
    assert(/пропущено/.test(picker.summary[0]) && /пропущено/.test(picker.summary[1]) && /✓ \d+ %/.test(picker.summary[2]), `${width}: the picker sums up the run ` + JSON.stringify(picker.summary));
    assert(picker.cards === 2 && JSON.stringify(picker.order) === JSON.stringify(['Luma_Cover_Fixture.html', 'Luma_No_Cover.html']) && !picker.frame && picker.skip, `${width}: the picker lists the two songs in library order, no frame ` + JSON.stringify(picker.order));
    assert(await fits(page), `${width}: the picker fits`);
    await shot(page, 'picker', width);

    // ── 14 · songs: the picker's «Співати» sings at once; the result counts into the next song ───────────────────
    auto = (await msgs(page, 'luma:autostart')).length;
    await page.locator('#session .spicker .song button.primary').first().click(); await waitSinging(page, picker.order[0]);
    await waitMsg(page, 'luma:autostart', auto);
    assert((await msgs(page, 'luma:autostart')).at(-1).ok && (await page.locator('#sessionSkip').textContent()) === 'До пісень', `${width}: a song picked in the list starts singing; the bar offers «До пісень»`);
    await shot(page, 'song', width);
    await sing(await frameOf(page), 0, 'end'); await waitCard(page, 'song');
    c = await card(page);
    assert(c.eyebrow === 'Пісня · «Demo» · завершено' && c.head === 'Перший прохід!' && c.ring === '3' && c.buttons.map(b => b.id).join() === 'resultNow,resultRepeat,resultSongs', `${width}: the song result counts into the next song, with «Повторити» and «До пісень» ` + JSON.stringify(c.buttons.map(b => b.id)));
    assert(layoutOk(c), `${width}: the song card fits ` + layoutText(c));
    await shot(page, 'result_song', width);
    auto = (await msgs(page, 'luma:autostart')).length;
    await waitSinging(page, picker.order[1], 7000); await waitMsg(page, 'luma:autostart', auto);
    assert((await frameSrc(page)) === '/song/' + picker.order[1], `${width}: after 3 s the next song in picker order is in the frame and singing`);
    await sing(await frameOf(page), 0, 'end'); await waitCard(page, 'none');
    c = await card(page);
    assert(!c.ring && c.buttons[0].id === 'resultSongs' && /primary/.test(c.buttons[0].cls) && !c.buttons.some(b => b.id === 'resultNow'), `${width}: the last song: no countdown, «До пісень» is the primary ` + JSON.stringify(c.buttons));
    assert(layoutOk(c), `${width}: the last-song card fits ` + layoutText(c));
    await shot(page, 'result_lastsong', width);
    await page.waitForTimeout(3500);
    assert((await cardNext(page)) === 'none' && !(await page.$('#session iframe')), `${width}: nothing starts by itself after the last song`);
    await page.locator('#resultSongs').click(); await page.waitForSelector('#session .spicker');
    assert(!(await page.$('#session iframe')), `${width}: «До пісень» returns to the picker`);

    // ── 15 · lives mode: a rewind is no finish ─────────────────────────────────────────────────────────────────
    if (width > 1000) {
      await page.evaluate(() => { const k = 'luma.trainer.settings', v = JSON.parse(localStorage.getItem(k) || '{}'); v.lives = true; v.livesCount = 3; localStorage.setItem(k, JSON.stringify(v)); });
      const finished = (await msgs(page, 'luma:finished')).length;
      await page.locator('#session .spicker .song button.primary').first().click(); await waitSinging(page, picker.order[0]);
      frame = await frameOf(page);
      await frame.evaluate(() => { const T = window.Luma.test; window.__voice = setInterval(() => { const s = T.state(); if (s.mode !== 'singing') return; const ref = window.Luma.targetAt(s.time);
        T.livePush(ref ? {t: T.ctxTime(), f: 440 * 2 ** ((ref.m + 1.5 - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: T.ctxTime(), f: null, confidence: 0, db: -70, rms: 0, peak: 0}); }, 20); });
      await frame.waitForFunction(() => window.Luma.test.state().lives.last, null, {timeout: 20000});
      await page.waitForTimeout(1500);
      assert(!(await page.$('#session .sintro')) && (await msgs(page, 'luma:finished')).length === finished && (await frameSrc(page)) === '/song/' + picker.order[0], `${width}: losing the last life rewinds inside the trainer and shows no result card`);
      await frame.evaluate(() => { clearInterval(window.__voice); document.getElementById('stopBtn').click(); });
      await page.evaluate(() => { const k = 'luma.trainer.settings', v = JSON.parse(localStorage.getItem(k) || '{}'); v.lives = false; localStorage.setItem(k, JSON.stringify(v)); });
      await page.locator('#sessionSkip').click(); await page.waitForSelector('#session .spicker');
    }

    // ── 16 · leaving: Back ─────────────────────────────────────────────────────────────────────────────────────
    await page.goBack(); await page.waitForFunction(() => document.getElementById('session').hidden);
    assert(page.url() === studio, `${width}: Back closes the session and stays on Studio (${page.url()})`);

    // ── 17 · reduced motion: no animation, the card at once, and the countdown still takes 3 s ─────────────────
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.locator('#sessionStart').click(); await waitCard(page, 'lesson:1');
    assert((await page.evaluate(() => getComputedStyle(document.querySelector('#session .sintro .card')).animationName)) === 'none', `${width}: reduced motion: the card does not animate`);
    const t1 = Date.now(); await page.locator('#sessionSkip').click(); await waitCard(page, 'lesson:2');
    assert(Date.now() - t1 <= 300, `${width}: reduced motion: the next card is there at once (${Date.now() - t1} ms)`);
    const t2 = Date.now(); await waitSinging(page, lessonFiles[1], 8000);
    const took = Date.now() - t2;
    await sing(await frameOf(page), 0, 'end'); await waitCard(page, 'lesson:3');
    const f2 = await lastFinish(page);
    assert(took >= 2800 && f2.card, `${width}: reduced motion: the countdown still takes 3 s (${took} ms to singing) and the result card is there within 50 ms of the finish`);
    await page.locator('#sessionClose').click(); await page.waitForFunction(() => document.getElementById('session').hidden);
    await page.emulateMedia({reducedMotion: 'no-preference'});

    // ── 18 · clean console in Studio and in every frame it opened (Playwright reports frame messages on the page) ─
    await page.evaluate(() => window.LumaActivity.flush());
    assert(logs.length === 0, `${width}: console clean ` + JSON.stringify(logs.slice(0, 5)));
    await page.close();
  }

  // ── 19 · activity: the session's result, next and auto-start events reach the log ─────────────────────────────
  const folder = join(library, 'logs', 'activity');
  let events = [];
  for (let i = 0; i < 30; i++) {
    events = existsSync(folder) ? readdirSync(folder).filter(f => f.endsWith('.jsonl')).flatMap(f => readFileSync(join(folder, f), 'utf8').trim().split('\n').filter(Boolean).map(l => JSON.parse(l))).filter(e => sessions.includes(e.session)) : [];
    if (['session_result', 'session_next', 'session_autostart'].every(t => events.some(e => e.type === t))) break;
    await new Promise(r => setTimeout(r, 200));
  }
  const res = events.find(e => e.type === 'session_result' && e.data.kind === 'lesson' && e.data.prev > 0), nx = events.filter(e => e.type === 'session_next').map(e => e.data.how), au = events.find(e => e.type === 'session_autostart' && e.data.ok);
  assert(res && res.page === 'studio' && typeof res.data.median === 'number' && typeof res.data.delta === 'number' && res.data.next === lessonFiles[1], 'the activity log has session_result with score, median, delta and the next step ' + JSON.stringify(res?.data));
  assert(['countdown', 'now', 'repeat', 'skip', 'songs', 'picker'].every(h => nx.includes(h)), 'session_next records every way on ' + JSON.stringify([...new Set(nx)]));
  assert(au && typeof au.data.ms === 'number' && events.some(e => e.type === 'session_autostart' && !e.data.ok && e.data.reason === 'audio'), 'session_autostart records the answer, the refusal and the time ' + JSON.stringify(au?.data));
  assert(events.some(e => e.type === 'click' && e.data.id === 'autostartBtn') && events.some(e => e.type === 'click' && e.data.id === 'resultRepeat'), 'clicks on the new buttons are logged by id');
} finally {
  await browser.close();
}

// ── 20 · the real autoplay policy: one real click on «Почати заняття», then no input at all ─────────────────────────
// No autoplay flag. Nothing is evaluated in the page (Playwright marks page.evaluate as a user gesture); the answer comes
// from the collector's console line. The countdown opens lesson 1 three seconds after the click, in a frame that did not
// exist when it happened.
try {
  const strict = await launch(media), {page, logs} = await openStudio(strict, {width: 1440, height: 900});
  const lines = []; page.on('console', m => { if (m.text().startsWith('luma-msg ')) lines.push(JSON.parse(m.text().slice(9))); });
  await page.locator('#sessionStart:visible').click();
  const deadline = Date.now() + 15000; while (Date.now() < deadline && !lines.some(l => l.type === 'luma:autostart')) await page.waitForTimeout(200);
  const ans = lines.find(l => l.type === 'luma:autostart');
  assert(ans && ans.ok === true && ans.file === lessonFiles[0], 'real policy: after one click on «Почати заняття» the lesson the countdown opens starts by itself ' + JSON.stringify(ans));
  assert(!logs.length, 'real policy: console clean ' + JSON.stringify(logs.slice(0, 3)));
  await strict.close();
} finally {
  cleanup();
}
