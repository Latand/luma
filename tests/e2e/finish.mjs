// Early finish: a sung pass over the whole song stops half a second after the last note or lyric line, is saved and
// scored as before, and the next «Співати» starts from the top. Listening and an explicit fragment still run to the end
// of the audio. Real transport with Chrome's fake microphone, on the demo and on lesson 1 served by the test Studio.
// docs/design/SESSION_FLOW_RESULTS.md
import {execFileSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import {launch, open, url, assert} from './lib.mjs';

const studio = process.env.LUMA_STUDIO_URL || 'http://127.0.0.1:8793/';
const library = process.env.LUMA_TEST_LIBRARY;
const py = process.env.LUMA_PY || '.venv/bin/python';
if (!library) { console.error('FAIL finish: LUMA_TEST_LIBRARY is not set (tests/e2e/run.sh exports it)'); process.exit(1); }
if (!existsSync(`${library}/Luma_Lesson_1_Novachok.html`)) execFileSync(py, ['lessons/build_lessons.py', '--songs', library], {maxBuffer: 64 << 20});

const browser = await launch(['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required']);
const COUNT_IN = 2.1;
const until = async (page, fn, arg, ms) => page.waitForFunction(fn, arg, {timeout: ms, polling: 50});

try {
  for (const [name, target, expected] of [['demo', url, 29.96], ['lesson 1', studio + 'song/Luma_Lesson_1_Novachok.html', null]]) {
    const {page, logs} = await open(browser, {width: 1280, height: 800}, target);
    await page.waitForFunction(() => window.Luma?.test.history.available() !== undefined);

    // ── 1 · where a sung pass ends ─────────────────────────────────────────────────────────────────────────────
    const song = await page.evaluate(() => {
      const S = window.LUMA_SONG, last = Math.max(...S.notes.filter(n => !n.ignored).map(n => n.b), ...(S.lyrics || []).map(l => l.b));
      return {...window.Luma.song(), want: Math.min(S.duration, last + .5)};
    });
    assert(Math.abs(song.singEnd - song.want) < 1e-6 && (expected === null || Math.abs(song.singEnd - expected) < .005),
      `${name}: singEnd is the last note or lyric + 0.5 s (${song.singEnd.toFixed(3)} of ${song.duration.toFixed(2)} s)`);
    assert(song.duration - song.singEnd > 2, `${name}: the old planned end left a ${(song.duration - song.singEnd + .5).toFixed(2)} s tail after the last note`);

    // ── 2 · a real sung pass from 3 s before the end stops at singEnd, saved and stored once ─────────────────────
    await page.waitForFunction(() => window.Luma.test.history.runs !== undefined);
    const before = await page.evaluate(() => ({takes: window.Luma.diagnostics().takeCount, runs: window.Luma.test.history.runs().length}));
    await page.evaluate(t => window.Luma.test.seek(t), song.singEnd - 3);
    const t0 = Date.now();
    await page.locator('#singBtn').click();
    await until(page, () => window.Luma.diagnostics().mode === 'singing', null, 8000);
    await until(page, () => window.Luma.diagnostics().mode === 'idle' && !window.Luma.diagnostics().pending, null, 15000);
    const took = (Date.now() - t0) / 1000;
    assert(took <= COUNT_IN + 3 + .8, `${name}: the pass ends ${took.toFixed(2)} s after «Співати» (count-in ${COUNT_IN} s + 3 s to singEnd; the old end was ${(COUNT_IN + 3 + song.duration - song.singEnd).toFixed(1)} s)`);
    await until(page, n => window.Luma.test.history.runs().length > n, before.runs, 5000).catch(() => {});
    const after = await page.evaluate(() => ({d: window.Luma.diagnostics(), runs: window.Luma.test.history.runs(), takes: window.Luma.test.takes()}));
    const take = after.d.takes[0];
    assert(after.d.takeCount === before.takes + 1 && Math.abs(take.endSong - song.singEnd) < .05, `${name}: one new take, ending at ${take.endSong.toFixed(3)} (singEnd ${song.singEnd.toFixed(3)})`);
    const run = after.runs.find(r => r.id === after.takes[0].runId);
    assert(after.runs.length === before.runs + 1 && run && Math.abs(run.b - song.singEnd) < .05, `${name}: one new run in the history, b ${run?.b}`);

    // ── 3 · the next «Співати» starts from the top ────────────────────────────────────────────────────────────
    await page.locator('#singBtn').click();
    await until(page, () => window.Luma.diagnostics().mode === 'singing', null, 8000);
    const restart = await page.evaluate(() => window.Luma.diagnostics().time);
    assert(restart < 1, `${name}: a second «Співати» after a finished pass starts at ${restart.toFixed(2)} s`);
    await page.locator('#stopBtn').click();
    await until(page, () => window.Luma.diagnostics().mode === 'idle' && !window.Luma.diagnostics().pending, null, 5000);

    // ── 5 · listening still plays to the end of the audio ─────────────────────────────────────────────────────
    await page.evaluate(t => window.Luma.test.seek(t), song.duration - 1.5);
    await page.locator('#listenBtn').click();
    await until(page, () => window.Luma.diagnostics().mode === 'listen', null, 5000);
    await until(page, () => window.Luma.diagnostics().mode === 'idle', null, 6000);
    const heard = await page.evaluate(() => window.Luma.test.state().pos);
    assert(Math.abs(heard - song.duration) < .1, `${name}: listening runs to the end of the audio (${heard.toFixed(2)} of ${song.duration.toFixed(2)})`);

    if (name === 'demo') {
      // ── 5b · an explicit fragment that ends at the end of the audio is sung to its own end ───────────────────
      await page.evaluate(([a, b]) => window.Luma.test.setRange(a, b), [song.singEnd - 1, song.duration]);
      await page.evaluate(t => window.Luma.test.seek(t), song.singEnd - 1);
      await page.locator('#singBtn').click();
      await until(page, () => window.Luma.diagnostics().mode === 'singing', null, 8000);
      await until(page, () => window.Luma.diagnostics().mode === 'idle' && !window.Luma.diagnostics().pending, null, 15000);
      const frag = await page.evaluate(() => window.Luma.diagnostics().takes[0]);
      assert(Math.abs(frag.endSong - song.duration) < .05, `${name}: a fragment to the end of the audio still ends there (${frag.endSong.toFixed(2)})`);
      await page.evaluate(() => window.Luma.test.clearRange());

      // ── 4 · the score is the same whether the pass stops at singEnd or at the end of the audio ──────────────
      const scored = await page.evaluate(async () => {
        const L = window.Luma, T = L.test, d = L.song().duration, end = L.song().singEnd, out = [];
        for (const b of [end, d]) {
          T.closeTrace(); T.seek(0); const st = T.fakeSing({a: 0, b}); if (!st) return {error: 'busy'};
          for (let t = 0; t <= b + 1e-9; t += .02) { const ref = L.targetAt(t); T.livePush(ref ? {t: st.when + t, f: 440 * 2 ** ((ref.m - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: st.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0}); }
          T.fakeTick(st.when + b); const f = T.fakeFinish(), runId = T.takes().find(x => x.id === f.id).runId;
          for (let i = 0; i < 50 && !T.history.runs().some(r => r.id === runId); i++) await new Promise(r => setTimeout(r, 100));
          const run = T.history.runs().find(r => r.id === runId); out.push({b, pct: f.pct, target: run?.target, hit: run?.hit});
        }
        return out;
      });
      assert(scored.length === 2 && scored[0].pct === scored[1].pct && scored[0].target === scored[1].target && scored[0].hit === scored[1].hit && scored[0].target > 0,
        `${name}: stopping at singEnd scores exactly like running to the end ` + JSON.stringify(scored));
    }
    assert(logs.length === 0, `${name}: console clean ` + JSON.stringify(logs.slice(0, 5)));
    await page.close();
  }
} finally {
  await browser.close();
}
