// Pure scoring engine + trace persistence + lyrics, on any trainer (default: the synthetic demo).
import {launch, open, window_, assert} from './lib.mjs';
const b = await launch(); const {page: p, logs} = await open(b);
const r = await p.evaluate((winSrc) => {
  const L = window.Luma, T = L.test, win = eval(winSrc), out = {win};
  const meta = {a: win.a, b: win.b, speed: 1, octave: 0, view: 'notes', tolerance: 35, slack: .05, ratio: .5, octaveFree: false, level: 'custom'};
  const midiF = m => 440 * Math.pow(2, (m - 69) / 12);
  const mk = (f, t) => ({t, songT: win.a + t, f, confidence: .95, m: f ? 69 + 12 * Math.log2(f / 440) : null, db: -20});
  const correct = []; for (let t = 0; t < win.b - win.a; t += .02) { const ref = L.targetAt(win.a + t); correct.push(mk(ref ? midiF(ref.m) : null, t)); }
  const shift = (pts, semis) => pts.map(q => ({...q, f: q.f ? q.f * 2 ** (semis / 12) : null, m: q.m !== null ? q.m + semis : null}));
  const pick = s => ({target: s.target, hit: s.hit, sung: s.sung, pct: s.pct});
  out.correct = pick(T.score(correct, meta, win.b)); out.wrong = pick(T.score(shift(correct, 3), meta, win.b));
  out.uncertain = pick(T.score(correct.map(q => ({...q, confidence: .5})), meta, win.b)); out.silence = pick(T.score(correct.map(q => ({...q, f: null, m: null})), meta, win.b));
  out.notarget = pick(T.score(correct.map(q => ({...q, songT: q.t})), {...meta, a: 0, b: 1}, 1));
  const partial = T.score(correct, meta, win.a + 1), full = T.score(correct, meta, win.b);
  out.frames = {partial: partial.frames.length, full: full.frames.length, expected: Math.floor((win.b - win.a) / .02) + 1};
  const half = correct.map((q, i) => i < correct.length / 2 ? q : shift([q], 3)[0]); out.half = pick(T.score(half, meta, win.b));
  const inj = T.injectTake({a: win.a, b: win.b, tolerance: 35, points: half.map(q => ({t: q.t, f: q.f, confidence: q.confidence, db: -20, rms: .1, peak: .3}))}); out.inject = inj;
  T.draw(); out.afterInject = {trace: T.state().trace?.id, matchText: T.state().matchText, reviewHidden: T.state().reviewHidden};
  T.seek(win.a + 1.6); T.draw(); out.afterSeek = {pos: T.state().pos, trace: !!T.state().trace, deviation: T.state().deviation};
  T.jumpMiss(1); out.afterJump = {pos: T.state().pos, missCount: T.state().missCount};
  T.closeTrace(); T.draw(); out.afterClose = {trace: T.state().trace, matchText: T.state().matchText}; T.selectTake(inj.id); T.draw(); out.afterReselect = {trace: T.state().trace?.id};
  const ly = window.LUMA_SONG.lyrics; if (ly.length) { T.closeTrace(); T.seek(ly[0].words[0].a + .05); T.draw(); out.lyric = T.state().lyric.trim(); }
  return out;
}, window_());
assert(r.correct.pct === 100, 'correct pitch scores 100 %');
assert(r.wrong.pct === 0 && r.wrong.sung === r.wrong.target, 'wrong pitch scores 0 % with every frame sung');
assert(r.uncertain.pct === 0 && r.uncertain.sung === 0, 'low-confidence pitch counts as silence');
assert(r.silence.pct === 0, 'silence under a target is a miss');
assert(r.notarget.pct === null && r.notarget.target === 0, 'no target → excluded, no NaN');
assert(r.frames.full === r.frames.expected && r.frames.partial < r.frames.full, 'one frame per grid step, no double counting');
assert(r.half.pct > 40 && r.half.pct < 60, `half right ≈ 50 % (got ${r.half.pct})`);
assert(r.afterInject.trace === r.inject.id && !r.afterInject.reviewHidden, 'attempt trace shown after recording');
assert(r.afterSeek.trace && r.afterSeek.pos > r.win.a, 'trace survives seeking');
assert(/промах/.test(r.afterJump.missCount), 'miss navigation reports a miss');
assert(r.afterClose.trace === null && r.afterClose.matchText === '—', 'closing the trace clears the readout');
assert(r.afterReselect.trace === r.inject.id, 'attempt can be re-selected');
if (r.lyric !== undefined) assert(r.lyric.length > 0, 'current lyric line rendered: ' + r.lyric);
assert(logs.length === 0, 'console clean ' + JSON.stringify(logs));
await p.screenshot({path: process.env.LUMA_SHOT || 'shot_scoring.png'}); await b.close();
