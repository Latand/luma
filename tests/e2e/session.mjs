// «Заняття» and album covers in Studio: the lessons one after another in a session frame, finish and skip, the song
// picker, leaving, reduced motion, and a cover extracted from a fixture original next to a song without one.
import {execFileSync} from 'node:child_process';
import {copyFileSync, existsSync, mkdirSync, rmSync, unlinkSync} from 'node:fs';
import {launch, open, assert} from './lib.mjs';

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
for (const f of added) copyFileSync(demo, f);
mkdirSync(pkg, {recursive: true});
const ff = (...a) => execFileSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...a]);
ff('-f', 'lavfi', '-i', 'color=red:s=64x36', '-frames:v', '1', `${pkg}/wide.png`);
ff('-f', 'lavfi', '-i', 'color=blue:s=48x48', '-frames:v', '1', `${pkg}/square.jpg`);
ff('-f', 'lavfi', '-i', 'sine=d=1', '-i', `${pkg}/wide.png`, '-i', `${pkg}/square.jpg`, '-map', '0', '-map', '1', '-map', '2', '-c:a', 'aac', '-c:v:0', 'png', '-c:v:1', 'mjpeg', '-disposition:v', 'attached_pic', `${pkg}/original.m4a`);
unlinkSync(`${pkg}/wide.png`); unlinkSync(`${pkg}/square.jpg`);
const backfill = execFileSync(py, ['studio/covers.py', '--songs', library], {encoding: 'utf8'}).trim();
assert(/extracted 1/.test(backfill) && !/Cover_Fixture/.test(backfill), 'covers.py extracts the fixture cover and prints counts only: ' + backfill);
const cleanup = () => { for (const f of added) rmSync(f, {force: true}); rmSync(pkg, {recursive: true, force: true}); };

const browser = await launch(['--autoplay-policy=no-user-gesture-required']);
const frameOf = async page => (await page.$('#session iframe.sframe.shown'))?.contentFrame();
const frameSrc = page => page.evaluate(() => { const f = document.querySelector('#session iframe.sframe'); return f ? new URL(f.src).pathname : null; });
const dots = page => page.evaluate(() => [...document.querySelectorAll('#sessionDots .dot')].map(d => d.className.replace('dot', '').trim() || '-'));
const waitIntro = (page, n) => page.waitForFunction(n => document.querySelector('#session .sintro .eyebrow')?.textContent.startsWith('Урок ' + n + ' '), n, {timeout: 10000});
const waitLesson = (page, file) => page.waitForFunction(file => { const f = document.querySelector('#session iframe.sframe.shown'); return f && f.src.endsWith('/song/' + file) && f.contentWindow.Luma; }, file, {timeout: 15000});
const shot = (page, step, w) => page.screenshot({path: `tests/e2e/shot_session_${step}_${w}.png`});
const fits = page => page.evaluate(() => document.documentElement.scrollWidth === document.documentElement.clientWidth);
// Sing from the last phrase to the end at the exact target pitches (the lesson's end is reached), or a window that stops
// short of the end.
const sing = (frame, toEnd) => frame.evaluate(toEnd => {
  const T = window.Luma.test, d = window.Luma.song().duration, last = window.LUMA_SONG.phrases.at(-1).a;
  const a = toEnd ? Math.round(last / .02) * .02 : d - 10, b = toEnd ? d : d - 5;
  T.closeTrace(); T.seek(a); const started = T.fakeSing({a, b}); if (!started) return {error: 'busy'};
  for (let t = 0; t <= b - a + 1e-9; t += .02) { const ref = window.Luma.targetAt(a + t); T.livePush(ref ? {t: started.when + t, f: 440 * Math.pow(2, (ref.m - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: started.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0}); }
  T.fakeTick(started.when + (b - a)); return T.fakeFinish();
}, toEnd);

try {
  for (const [width, height] of [[390, 844], [1440, 900]]) {
    const {page, logs} = await open(browser, {width, height}, studio);
    await page.waitForSelector('#lib .song .cover');
    await page.waitForFunction(() => !document.getElementById('sessionEntry').hidden);

    // ── 1 · library covers ────────────────────────────────────────────────────────────────────────────────────
    const cards = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#lib .song')].map(c => {
      const img = c.querySelector('.cover img');
      return [c.querySelector('details .meta').textContent.split(' · ').pop(), {src: img ? img.getAttribute('src') : null, natural: img ? img.naturalWidth : 0, ph: c.querySelector('.cover').classList.contains('ph'), letter: c.querySelector('.cover b')?.textContent || null}];
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

    // ── 3 · start → intro 1 ───────────────────────────────────────────────────────────────────────────────────
    await page.locator('#sessionStart').click(); await waitIntro(page, 1);
    assert(await page.locator('#session').isVisible(), `${width}: the session overlay opens`);
    assert(JSON.stringify(await dots(page)) === JSON.stringify(['current', '-', '-', '-']), `${width}: four dots, the first current ` + JSON.stringify(await dots(page)));
    assert((await page.locator('#session .sintro .title').textContent()) === defs.lessons[0].title, `${width}: intro 1 names lesson 1 from the catalogue`);
    assert(await page.evaluate(() => document.activeElement.textContent === 'Почати урок'), `${width}: focus lands on «Почати урок»`);
    assert(await fits(page), `${width}: the intro fits`);
    await shot(page, 'intro1', width);

    // ── 4 · «Почати урок» → lesson 1 in the frame ────────────────────────────────────────────────────────────
    await page.locator('#session .sintro .primary').click(); await waitLesson(page, lessonFiles[0]);
    assert((await frameSrc(page)) === '/song/' + lessonFiles[0], `${width}: the frame holds lesson 1`);
    await page.waitForTimeout(400);
    await shot(page, 'lesson1', width);

    // ── 5 · an attempt that stops short of the end does not finish the lesson ─────────────────────────────────
    let frame = await frameOf(page);
    const short = await sing(frame, false);
    await page.waitForTimeout(2000);
    assert(short && short.id && (await frameSrc(page)) === '/song/' + lessonFiles[0] && !(await page.$('#session .sintro')), `${width}: a part of the lesson does not count as finishing it`);

    // ── 6 · singing to the end finishes it → intro 2 with the result ─────────────────────────────────────────
    const whole = await sing(frame, true);
    await waitIntro(page, 2);
    const result = await page.locator('#session .sintro .result').textContent();
    assert(result.includes('Урок 1 пройдено') && /\d+ %/.test(result), `${width}: intro 2 reports lesson 1 (${result}; trainer said ${whole.pct} %)`);
    assert((await dots(page))[0] === 'done' && (await dots(page))[1] === 'current', `${width}: dot 1 done, dot 2 current ` + JSON.stringify(await dots(page)));
    assert(await page.locator('#session .sintro .secondary', {hasText: 'Ще раз'}).isVisible(), `${width}: «Ще раз» offers lesson 1 again`);
    await shot(page, 'intro2', width);

    // ── 6b · «Ще раз» then «Пропустити урок» keeps lesson 1 finished ───────────────────────────────────────────
    await page.locator('#session .sintro .secondary', {hasText: 'Ще раз'}).click(); await waitLesson(page, lessonFiles[0]);
    assert((await dots(page))[0] === 'current', `${width}: «Ще раз» reopens lesson 1 ` + JSON.stringify(await dots(page)));
    await page.locator('#sessionSkip').click(); await waitIntro(page, 2);
    const kept = await page.locator('#session .sintro .result').textContent();
    assert((await dots(page))[0] === 'done' && kept === result, `${width}: skipping the repeat keeps lesson 1 done (${kept}) ` + JSON.stringify(await dots(page)));
    assert((await page.locator('#sessionLive').textContent()).startsWith('Повтор уроку 1 пропущено'), `${width}: the live region does not call lesson 1 skipped`);

    // ── 7 · a message that does not come from the lesson frame is ignored ───────────────────────────────────
    await page.evaluate(file => window.postMessage({type: 'luma:finished', file, match: 99}, location.origin), lessonFiles[1]);

    // ── 8 · the intro opens lesson 2 by itself ──────────────────────────────────────────────────────────────
    const t0 = Date.now(); await waitLesson(page, lessonFiles[1]);
    assert(Date.now() - t0 <= 7000, `${width}: lesson 2 opens by itself after the countdown (${Date.now() - t0} ms)`);
    assert((await dots(page))[1] === 'current', `${width}: the spoofed message did not advance the session`);
    await page.evaluate(file => window.postMessage({type: 'luma:finished', file, match: 99}, location.origin), lessonFiles[1]);
    await page.waitForTimeout(1500);
    assert((await frameSrc(page)) === '/song/' + lessonFiles[1] && !(await page.$('#session .sintro')), `${width}: a message from Studio itself does not finish lesson 2`);

    // ── 9 · skip lesson 2, open lesson 3, skip it → the picker ───────────────────────────────────────────────
    await page.locator('#sessionSkip').click(); await waitIntro(page, 3);
    assert(JSON.stringify(await dots(page)) === JSON.stringify(['done', 'skipped', 'current', '-']), `${width}: dot 2 is skipped ` + JSON.stringify(await dots(page)));
    await page.locator('#session .sintro .primary').click(); await waitLesson(page, lessonFiles[2]);
    await page.locator('#sessionSkip').click();
    await page.waitForSelector('#session .spicker');
    const picker = await page.evaluate(() => ({summary: [...document.querySelectorAll('#session .summary .chip')].map(c => c.textContent),
      cards: [...document.querySelectorAll('#session .spicker .song')].map(c => c.querySelector('.title').textContent),
      cover: document.querySelector('#session .spicker .cover img')?.getAttribute('src') || null, frame: !!document.querySelector('#session iframe'),
      skip: document.getElementById('sessionSkip').hidden}));
    assert(picker.summary.length === 3 && /✓ \d+ %/.test(picker.summary[0]) && /пропущено/.test(picker.summary[1]) && /пропущено/.test(picker.summary[2]), `${width}: the picker sums up the run ` + JSON.stringify(picker.summary));
    assert(picker.cards.length === 2 && !picker.cards.some(t => defs.lessons.some(l => l.title === t)), `${width}: the picker lists songs only ` + JSON.stringify(picker.cards));
    assert(/^\/cover\/Luma_Cover_Fixture\.html\?v=/.test(picker.cover || ''), `${width}: the picker shows the cover`);
    assert(!picker.frame && picker.skip && JSON.stringify(await dots(page)) === JSON.stringify(['done', 'skipped', 'skipped', 'current']), `${width}: no frame and no skip button on the picker; the last dot is current`);
    assert(await fits(page), `${width}: the picker fits`);
    await page.waitForTimeout(400);
    await shot(page, 'picker', width);

    // ── 10 · a song from the picker opens in the frame; «До пісень» comes back ──────────────────────────────
    const fixtureCard = page.locator('#session .spicker .song', {has: page.locator('img[src^="/cover/Luma_Cover_Fixture.html"]')});
    await fixtureCard.locator('button.primary').click(); await waitLesson(page, 'Luma_Cover_Fixture.html');
    assert((await page.locator('#sessionSkip').textContent()) === 'До пісень', `${width}: the bar offers «До пісень» while a song is open`);
    await shot(page, 'song', width);
    await page.locator('#sessionSkip').click(); await page.waitForSelector('#session .spicker');
    assert(!(await page.$('#session iframe')), `${width}: «До пісень» closes the song and returns to the picker`);

    // ── 11 · leaving: × and the browser's Back button ──────────────────────────────────────────────────────
    await page.locator('#sessionClose').click();
    await page.waitForFunction(() => document.getElementById('session').hidden);
    assert(await page.evaluate(() => document.activeElement.id === 'sessionStart' && !document.body.classList.contains('locked')), `${width}: × closes the session and returns focus to «Почати заняття»`);
    await page.locator('#sessionStart').click(); await waitIntro(page, 1);
    await page.goBack(); await page.waitForFunction(() => document.getElementById('session').hidden);
    assert(page.url() === studio, `${width}: Back closes the session and stays on Studio (${page.url()})`);

    // ── 12 · reduced motion: no animation, the next card at once ─────────────────────────────────────────────
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.locator('#sessionStart').click(); await waitIntro(page, 1);
    assert((await page.evaluate(() => getComputedStyle(document.querySelector('#session .sintro .card')).animationName)) === 'none', `${width}: reduced motion: the intro card does not animate`);
    const t1 = Date.now(); await page.locator('#sessionSkip').click(); await waitIntro(page, 2);
    assert(Date.now() - t1 <= 300, `${width}: reduced motion: the next card is there at once (${Date.now() - t1} ms)`);
    await page.locator('#sessionClose').click(); await page.waitForFunction(() => document.getElementById('session').hidden);
    await page.emulateMedia({reducedMotion: 'no-preference'});

    // ── 13 · clean console in Studio and in every frame it opened (Playwright reports frame messages on the page) ───────────────────────────────────────────
    assert(logs.length === 0, `${width}: console clean ` + JSON.stringify(logs.slice(0, 5)));
    await page.close();
  }
} finally {
  await browser.close();
  cleanup();
}
