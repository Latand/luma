// Built-in lessons: generated into a fresh library, listed in Studio under «Уроки», exact targets, and a guide voice
// that really sings them. Expected notes are recomputed here from lessons/definitions.py, not read back from the
// generator, so a change in either side has to be deliberate.
import {execFileSync} from 'node:child_process';
import {readFileSync, renameSync, writeFileSync} from 'node:fs';
import {launch, open, assert} from './lib.mjs';

const studio = process.env.LUMA_STUDIO_URL || 'http://127.0.0.1:8793/';
const library = process.env.LUMA_TEST_LIBRARY;
const py = process.env.LUMA_PY || '.venv/bin/python';
if (!library) { console.error('FAIL lessons: LUMA_TEST_LIBRARY is not set (tests/e2e/run.sh exports it)'); process.exit(1); }

const TAG = '<script type="application/json" id="luma-lessons">';
const run = args => execFileSync(py, ['lessons/build_lessons.py', ...args], {encoding: 'utf8', maxBuffer: 64 << 20});
const defs = JSON.parse(run(['--definitions']));
console.log(run(['--songs', library]).trim());

// The same timeline the generator builds, derived independently from the definitions.
function planned(lesson, timing) {
  const beat = 60 / lesson.bpm, notes = []; let t = timing.leadSilence;
  for (const section of lesson.sections) {
    t += section.lead * beat;
    for (const key of section.keys) {
      for (const semi of section.pattern.semitones) {
        const d = section.pattern.beats * beat;
        notes.push({a: t, b: t + d - Math.min(timing.gapMax, timing.gapRatio * d), m: lesson.root + key + semi, w: section.pattern.syllable});
        t += d;
      }
      t += section.pattern.rest * beat;
    }
  }
  return {notes, duration: t + timing.tail, keys: lesson.sections.reduce((n, s) => n + s.keys.length, 0)};
}

// YIN-style difference function on the decoded guide, so the measured pitch never comes from the map we are checking.
const YIN = `(x, from, win) => {
  const TAU = 400, n = win - TAU, d = new Float64Array(TAU); let mean = 0;
  for (let i = 0; i < win; i++) mean += x[from + i]; mean /= win;
  for (let tau = 0; tau < TAU; tau++) { let sum = 0; for (let i = 0; i < n; i++) { const v = (x[from + i] - mean) - (x[from + i + tau] - mean); sum += v * v; } d[tau] = sum; }
  const dn = new Float64Array(TAU).fill(1); let run = 0;
  for (let tau = 1; tau < TAU; tau++) { run += d[tau]; dn[tau] = d[tau] * tau / Math.max(run, 1e-12); }
  let tau = 0;
  for (let i = 2; i < TAU - 1; i++) if (dn[i] < .15 && dn[i] <= dn[i - 1] && dn[i] <= dn[i + 1]) { tau = i; break; }
  if (!tau) { let best = 1e18; for (let i = 2; i < TAU - 1; i++) if (dn[i] < best) { best = dn[i]; tau = i; } }
  const a = dn[tau - 1], b = dn[tau], c = dn[tau + 1], denom = a - 2 * b + c;
  return 22050 / (tau + (denom ? (a - c) / (2 * denom) : 0));
}`;

const browser = await launch(['--autoplay-policy=no-user-gesture-required']);

// ── Studio lists the lessons in a «Уроки» section above the library ────────────────────────────────────────────────
{
  const {page, logs} = await open(browser, {width: 1440, height: 900}, studio);
  await page.waitForSelector('#lessonsSection .lesson');
  const shown = await page.evaluate(() => [...document.querySelectorAll('#lessons .lesson')].map(card => ({
    title: card.querySelector('.title').textContent, level: card.querySelector('.chip span').textContent,
    goal: card.querySelector('.goal').textContent, description: card.querySelector('p').textContent,
    meta: card.querySelector('.meta').textContent, href: card.querySelector('a.primary').getAttribute('href'),
    action: card.querySelector('a.primary').textContent})));
  const order = defs.lessons.map(l => l.title);
  assert(shown.length === defs.lessons.length, `Studio shows every lesson (${shown.length} of ${defs.lessons.length})`);
  assert(JSON.stringify(shown.map(s => s.title)) === JSON.stringify(order), 'lessons are ordered beginner → expert ' + JSON.stringify(shown.map(s => s.title)));
  assert(JSON.stringify(shown.map(s => s.level)) === JSON.stringify(['Легко', 'Звично', 'Точно']), 'each lesson carries its suggested level');
  for (const [i, card] of shown.entries()) {
    const lesson = defs.lessons[i];
    assert(card.goal === lesson.summary && card.description === lesson.description, `${lesson.id}: the Ukrainian description comes from the definitions`);
    assert(/октав/i.test(card.description), `${lesson.id}: the description points at the vocal octave setting`);
    assert(card.href === '/song/' + lesson.file && /Відкрити/.test(card.action), `${lesson.id}: the card opens the trainer`);
    assert(/\d+ BPM/.test(card.meta) && /\d+ нот/.test(card.meta), `${lesson.id}: tempo and size are on the card (${card.meta})`);
  }
  const lib = await page.locator('#lib').textContent();
  assert(/Тут поки немає/.test(lib), 'a fresh library still reads as empty: lessons are not songs you added');
  assert(await page.evaluate(() => document.querySelector('#lessonsSection').compareDocumentPosition(document.querySelector('#lib')) & Node.DOCUMENT_POSITION_FOLLOWING) > 0, '«Уроки» sits above the library');
  // A lesson added while Studio is open reaches «Уроки» on a later poll: open the page with the third one hidden from
  // both the library and the catalogue, then put it back the way a rebuild would.
  const catalogue = library + '/lessons.index.html', whole = readFileSync(catalogue, 'utf8');
  const third = library + '/' + defs.lessons[2].file, parked = third + '.parked';
  const head = whole.indexOf(TAG) + TAG.length, tail = whole.indexOf('</script>', head);
  const known = JSON.parse(whole.slice(head, tail));
  const cards = n => page.waitForFunction(want => document.querySelectorAll('#lessons .lesson').length === want, n);
  renameSync(third, parked);
  writeFileSync(catalogue, whole.slice(0, head) + JSON.stringify({...known, lessons: known.lessons.slice(0, 2)}) + whole.slice(tail));
  await page.reload(); await page.waitForSelector('#lessonsSection .lesson'); await cards(2);
  writeFileSync(catalogue, whole); renameSync(parked, third);
  await page.evaluate(() => refresh()); await cards(3);
  assert(true, 'a lesson that appears while Studio is open joins «Уроки» without a reload');
  await page.setViewportSize({width: 390, height: 844}); await page.waitForTimeout(150);
  assert(await page.evaluate(() => document.documentElement.scrollWidth === innerWidth), 'the lessons section fits 390 px');
  if (process.env.LUMA_SHOT) await page.screenshot({path: process.env.LUMA_SHOT, fullPage: true});
  assert(logs.length === 0, 'Studio console clean ' + JSON.stringify(logs));
  await page.close();
}

// ── Each trainer: the map is exactly the planned melody, it scores strictly, and the guide sings it ────────────────
for (const lesson of defs.lessons) {
  const want = planned(lesson, defs.timing);
  const {page, logs} = await open(browser, {width: 1440, height: 900}, studio + 'song/' + lesson.file);
  await page.waitForFunction(() => window.Luma && window.Luma.test);
  const map = await page.evaluate(() => {
    const s = window.LUMA_SONG;
    return {duration: s.duration, status: s.status, title: s.title, artist: s.artist, hop: s.hop, phrases: s.phrases.length, lesson: s.lesson,
      notes: s.notes.map(n => ({a: n.a, b: n.b, m: n.m, ok: n.ok, q: n.q, ignored: n.ignored})),
      draftPoints: s.points.filter(p => p[1] !== null && !p[3]).length, voiced: s.points.filter(p => p[1] !== null).length,
      words: s.lyrics.flatMap(l => l.words).map(w => w.w), lyricLines: s.lyrics.length,
      coverage: s.metrics.comparablePercentOfTrack};
  });
  const worst = map.notes.reduce((acc, n, i) => Math.max(acc, Math.abs(n.a - want.notes[i].a), Math.abs(n.b - want.notes[i].b)), 0);
  assert(map.notes.length === want.notes.length, `${lesson.id}: ${map.notes.length} notes, as planned`);
  assert(map.notes.every((n, i) => n.m === want.notes[i].m), `${lesson.id}: every target note is the planned pitch`);
  assert(worst < .002, `${lesson.id}: every note starts and ends where the pattern puts it (worst ${worst.toFixed(4)} s)`);
  assert(Math.abs(map.duration - want.duration) < .002 && map.duration > 120 && map.duration < 240, `${lesson.id}: lasts ${map.duration.toFixed(1)} s, between two and four minutes`);
  assert(map.notes.every(n => n.ok === true && n.ignored === false && n.q >= .9), `${lesson.id}: nothing is a draft — every note is exact and confident`);
  assert(map.draftPoints === 0 && map.status !== 'unverified_draft', `${lesson.id}: the contour is exact too (status "${map.status}")`);
  assert(map.title === lesson.title && map.artist === lesson.artist, `${lesson.id}: title and artist reach the trainer`);
  // The trainer does not apply this yet (docs/LESSONS.md, "Known gaps"); the map has to carry it for the follow-up.
  assert(map.lesson && map.lesson.id === lesson.id && map.lesson.level === lesson.level && map.lesson.bpm === lesson.bpm, `${lesson.id}: the map carries the suggested level «${lesson.level}»`);
  assert(map.words.length === want.notes.length && map.words.every((w, i) => w === want.notes[i].w), `${lesson.id}: one syllable per note in the lyric lane`);
  assert(map.phrases === want.keys && map.lyricLines === want.keys, `${lesson.id}: one practice fragment and one lyric line per repetition (${want.keys})`);

  // Sing it: exact pitches through the live path score high, a semitone off scores near zero.
  const level = {'Легко': 'easy', 'Звично': 'normal', 'Точно': 'strict'}[lesson.level];
  const windows = await page.evaluate(() => {
    const ph = window.LUMA_SONG.phrases, pick = [ph[1], ph[ph.length - 2]];
    return pick.map(p => ({a: Math.round(p.a / .02) * .02, b: Math.round(p.b / .02) * .02, label: p.label}));
  });
  for (const win of windows) {
    const sung = await page.evaluate(async ({win, level, cents}) => {
      const T = window.Luma.test; T.setLevel(level); T.closeTrace(); T.seek(win.a);
      const started = T.fakeSing({a: win.a, b: win.b});
      if (!started) return {error: 'busy'};
      for (let t = 0; t <= win.b - win.a + 1e-9; t += .02) {
        const ref = window.Luma.targetAt(win.a + t), when = started.when + t;
        T.livePush(ref ? {t: when, f: 440 * Math.pow(2, (ref.m + cents / 100 - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3}
                       : {t: when, f: null, confidence: 0, db: -60, rms: 0, peak: 0});
      }
      T.fakeTick(started.when + (win.b - win.a));
      const done = T.fakeFinish(); const state = T.state();
      return {pct: done.pct, frames: state.trace.frames, matchText: state.matchText};
    }, {win, level, cents: 0});
    const off = await page.evaluate(async ({win, level, cents}) => {
      const T = window.Luma.test; T.closeTrace(); T.seek(win.a);
      const started = T.fakeSing({a: win.a, b: win.b});
      if (!started) return {error: 'busy'};
      for (let t = 0; t <= win.b - win.a + 1e-9; t += .02) {
        const ref = window.Luma.targetAt(win.a + t), when = started.when + t;
        if (ref) T.livePush({t: when, f: 440 * Math.pow(2, (ref.m + cents / 100 - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3});
      }
      T.fakeTick(started.when + (win.b - win.a));
      return T.fakeFinish();
    }, {win, level, cents: 100});
    assert(sung.pct >= 95, `${lesson.id} · ${win.label}: singing the exact pitches on «${lesson.level}» scores ${sung.pct} %`);
    assert(off.pct <= 5, `${lesson.id} · ${win.label}: a semitone off scores ${off.pct} %`);
  }

  // The guide voice in the file: measured pitch against the target it is supposed to sing.
  const guide = await page.evaluate(async ({yinSrc}) => {
    const yin = eval(yinSrc), raw = atob(window.LUMA_ASSETS['1'].foreground), bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    const SR = 22050, audio = await new OfflineAudioContext(1, 1, SR).decodeAudioData(bytes.buffer), x = audio.getChannelData(0);
    const notes = window.LUMA_SONG.notes;
    let onset = 0; while (onset < x.length && Math.abs(x[onset]) < .02) onset++;
    const shift = onset / SR - notes[0].a;                       // whatever delay the MP3 decoder adds, measured, not assumed
    let worstCents = 0, worstNote = null, measured = 0, silent = 0;
    for (const n of notes) {
      const length = n.b - n.a, win = Math.max(700, Math.min(1024, Math.floor(length * SR * .8)));
      const from = Math.round(((n.a + n.b) / 2 + shift) * SR - win / 2);
      if (from < 0 || from + win > x.length) continue;
      let peak = 0; for (let i = from; i < from + win; i++) peak = Math.max(peak, Math.abs(x[i]));
      if (peak < .01) { silent++; continue; }
      const cents = 1200 * Math.log2(yin(x, from, win) / (440 * Math.pow(2, (n.m - 69) / 12)));
      measured++; if (Math.abs(cents) > Math.abs(worstCents)) { worstCents = cents; worstNote = n.id; }
    }
    return {shift, measured, silent, total: notes.length, worstCents: +worstCents.toFixed(2), worstNote, seconds: x.length / SR};
  }, {yinSrc: YIN});
  assert(Math.abs(guide.shift) < .06, `${lesson.id}: the guide starts with the first note (decoder shift ${(guide.shift * 1000).toFixed(0)} ms)`);
  assert(guide.silent === 0 && guide.measured === guide.total, `${lesson.id}: the guide sings every one of ${guide.total} notes (${guide.silent} silent)`);
  assert(Math.abs(guide.worstCents) <= 10, `${lesson.id}: the guide is within ${Math.abs(guide.worstCents).toFixed(1)} ¢ of the target everywhere (worst note ${guide.worstNote})`);
  assert(Math.abs(guide.seconds - map.duration) < .1, `${lesson.id}: the audio is as long as the map says (${guide.seconds.toFixed(2)} s)`);
  assert(logs.length === 0, `${lesson.id}: console clean ` + JSON.stringify(logs));
  await page.close();
}
await browser.close();
