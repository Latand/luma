// Vertical-scale behaviour on real playback: how often the visible pitch range changes, how abruptly, and whether every
// target note in the window (plus look-ahead) stays inside it. Plays each trainer with real audio for a fixed time.
//   LUMA_SCALE_URLS=url1,url2  trainers to measure (default: LUMA_URL / the demo)
//   LUMA_SCALE_SECONDS=45      listening time per trainer (default: 45, capped by the song length)
//   LUMA_SCALE_GATE=1          fail on jumps or visible-window violations (default when only the demo is measured)
import {launch, assert, url} from './lib.mjs';
const urls = (process.env.LUMA_SCALE_URLS || url).split(',').map(s => s.trim()).filter(Boolean);
const seconds = Number(process.env.LUMA_SCALE_SECONDS || 45), gate = process.env.LUMA_SCALE_GATE ? process.env.LUMA_SCALE_GATE === '1' : !process.env.LUMA_SCALE_URLS;
const LOOKAHEAD = 4, STILL = .25;
const b = await launch(['--autoplay-policy=no-user-gesture-required']);
for (const target of urls) {
  const p = await b.newPage({viewport: {width: 1440, height: 900}}); const logs = [];
  page: { p.on('pageerror', e => logs.push(e.message)); }
  await p.goto(target, {timeout: 120000}); await p.waitForFunction(() => window.Luma && window.Luma.test); await p.waitForTimeout(400);
  const song = await p.evaluate(() => window.Luma.song());
  const dur = Math.min(seconds, song.duration - (await p.evaluate(() => window.Luma.test.state().pos)) - .5);
  // Record the displayed range every animation frame, from the page itself, so the sampling never lags the renderer.
  await p.evaluate(() => { const S = window.__scale = {rows: []}; const step = () => { const st = window.Luma.test.state(); S.rows.push([performance.now() / 1000, st.time, st.rangeLo, st.rangeHi]); S.raf = requestAnimationFrame(step); }; S.raf = requestAnimationFrame(step); });
  await p.click('#listenBtn'); await p.waitForFunction(() => window.Luma.test.state().mode === 'listen'); await p.waitForTimeout(dur * 1000);
  await p.evaluate(() => cancelAnimationFrame(window.__scale.raf)); await p.click('#stopBtn'); await p.waitForTimeout(200);
  const m = await p.evaluate(({LOOKAHEAD, STILL}) => {
    const rows = window.__scale.rows, W = document.getElementById('chart').clientWidth, span = W < 550 ? 7 : W < 1100 ? 10 : 12, behind = span * .34;
    const notes = window.LUMA_SONG.notes.filter(n => !n.ignored), octave = window.Luma.test.levelOpt ? 0 : 0;
    let events = 0, still = 0, lastMove = -1e9, maxStep = 0, moving = 0, visViol = 0, planViol = 0, maxOver = 0; const eventTimes = [];
    for (let i = 1; i < rows.length; i++) { const [wall, t, lo, hi] = rows[i], [w0, , lo0, hi0] = rows[i - 1]; const d = Math.max(Math.abs(lo - lo0), Math.abs(hi - hi0));
      if (d > 1e-3) { moving++; if (wall - lastMove > STILL) { events++; eventTimes.push(+t.toFixed(1)); } lastMove = wall; maxStep = Math.max(maxStep, d); }
      const va = t - behind, vb = t + span - behind; let vis = false, plan = false;
      for (const n of notes) { if (n.b < va) continue; if (n.a > vb + LOOKAHEAD) break; const out = n.m + octave < lo || n.m + octave > hi; if (!out) continue; const over = Math.max(lo - (n.m + octave), n.m + octave - hi); if (n.a <= vb) { vis = true; maxOver = Math.max(maxOver, over); } else plan = true; }
      if (vis) visViol++; if (plan) planViol++; }
    const minutes = (rows[rows.length - 1][0] - rows[0][0]) / 60; const spans = rows.map(r => r[3] - r[2]).sort((a, b) => a - b);
    return {frames: rows.length, minutes: +minutes.toFixed(2), eventsPerMin: +(events / minutes).toFixed(1), events, eventTimes: eventTimes.slice(0, 40), maxStepSemitones: +maxStep.toFixed(3), movingShare: +(moving / rows.length).toFixed(2), visibleViolationFrames: visViol, lookaheadViolationFrames: planViol, maxOvershootSemitones: +maxOver.toFixed(2), spanMedian: +spans[spans.length >> 1].toFixed(1), spanMin: +spans[0].toFixed(1), spanMax: +spans[spans.length - 1].toFixed(1)}; }, {LOOKAHEAD, STILL});
  console.log(JSON.stringify({song: song.title, seconds: +dur.toFixed(1), ...m}));
  if (gate) { assert(m.visibleViolationFrames === 0, 'every target note in the visible window stays inside the range'); assert(m.maxStepSemitones <= .6, 'no per-frame jump above 0.6 semitones (got ' + m.maxStepSemitones + ')'); assert(m.eventsPerMin <= 12, 'range changes stay rare (' + m.eventsPerMin + '/min)'); assert(logs.length === 0, 'no page errors ' + JSON.stringify(logs)); }
  await p.close();
}
await b.close();
