// Lives mode (docs/SCORING.md, «Режим життів»): a synthetic voice through the live scoring path. Part one drives the
// singing clock by hand (fakeSing / fakeTick) to pin the rules; part two sings through the real transport with a silent
// fake microphone and an off-pitch voice pushed in, until the last life goes and the song rewinds by itself.
import {mkdtempSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {launch, open, assert} from './lib.mjs';

// Sing a window through the live path. voice(t) → cents off the target at song time t, or null for silence; frames
// with no target get silence. Ticks every 0.1 s, as the frame loop would.
const sing = (page, {a, b, level = 'normal', voice}) => page.evaluate(({a, b, level, voice}) => {
  const T = window.Luma.test, fn = eval(voice);
  T.setLevel(level); T.closeTrace(); T.seek(a);
  const started = T.fakeSing({a, b}); if (!started) return {error: 'busy'};
  const seen = [];
  for (let t = 0; t <= b - a + 1e-9; t += .02) {
    const songT = a + t, ref = window.Luma.targetAt(songT), cents = ref ? fn(songT, ref) : null;
    T.livePush(cents === null ? {t: started.when + t, f: null, confidence: 0, db: -60, rms: 0, peak: 0}
      : {t: started.when + t, f: 440 * Math.pow(2, (ref.m + cents / 100 - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3});
    if (Math.round(t * 50) % 5 === 0) { T.fakeTick(started.when + t); const l = T.state().lives; if (l.left !== null && l.left !== (seen.at(-1)?.left ?? l.total)) seen.push({t: +songT.toFixed(2), left: l.left}); }
  }
  T.fakeTick(started.when + (b - a) + .3);
  const lives = T.state().lives, done = T.fakeFinish();
  return {lives, losses: seen, pct: done && done.pct};
}, {a, b, level, voice});

const setLives = (page, on, size) => page.evaluate(({on, size}) => {
  const c = document.getElementById('livesMode'); c.checked = on; c.dispatchEvent(new Event('change'));
  if (size) { const n = document.getElementById('livesCount'); n.value = String(size); n.dispatchEvent(new Event('change')); }
}, {on, size});

const b = await launch();
const {page: p, logs} = await open(b);
const song = await p.evaluate(() => ({duration: window.LUMA_SONG.duration, phrases: window.LUMA_SONG.phrases.map(x => ({a: x.a, b: x.b})),
  notes: window.LUMA_SONG.notes.map(n => ({a: n.a, b: n.b}))}));
const lastNote = song.notes.at(-1).b;

// ── off by default, and off means nothing changes ─────────────────────────────────────────────────────────────────
let st = await p.evaluate(() => window.Luma.test.state().lives);
assert(!st.on && !st.shown && !(await p.locator('#livesMode').isChecked()), 'lives mode is off by default and shows nothing ' + JSON.stringify(st));
const plain = await sing(p, {a: 1.5, b: 14, voice: '()=>150'});
assert(plain.lives.total === null && !plain.lives.shown && plain.lives.retry === null, 'with the mode off a wrong passage costs nothing and rewinds nothing ' + JSON.stringify(plain.lives));

await setLives(p, true);
st = await p.evaluate(() => window.Luma.test.state().lives);
assert(st.on && st.shown && st.hearts === 10 && st.lost === 0, 'turned on: ten hearts in the corner of the stage ' + JSON.stringify(st));
const saved = await p.evaluate(() => JSON.parse(localStorage.getItem('luma.trainer.settings')));
assert(saved.lives === true && saved.livesCount === 10, 'the switch is kept with the other settings');

// ── a single short miss inside a good passage costs no life ───────────────────────────────────────────────────────
// 1.2 s a semitone and a half off in the middle of the first phrase, everything else in tune
const short = await sing(p, {a: 1.5, b: 9.6, voice: '(t)=>t>=4.2&&t<5.4?150:0'});
assert(short.lives.left === 10 && short.losses.length === 0, 'one short miss costs no life ' + JSON.stringify(short));
// a whole note sung silent is a short miss too
const gapNote = song.notes.find(n => n.b - n.a > 1);
const hole = await sing(p, {a: 1.5, b: 9.6, voice: `(t)=>t>=${gapNote.a}&&t<${gapNote.b}?null:0`});
assert(hole.lives.left === 10, 'one note left silent costs no life ' + JSON.stringify(hole.lives));
// silence where nothing is drawn never costs a life, however long
const tail = await sing(p, {a: lastNote + .05, b: song.duration - .05, voice: '()=>null'});
assert(tail.lives.left === 10, 'four seconds of silence with no target cost nothing ' + JSON.stringify(tail.lives));

// ── a decent singer on «легко» keeps every life; a clearly wrong passage loses them, at most one per cooldown ────────
// late entries (0.15 s silent at each note), ±45 ¢ of drift and a wobble, over the whole song
const decent = await p.evaluate(() => {
  const ns = window.LUMA_SONG.notes; return `(t)=>{const ns=${JSON.stringify(ns.map(n => [n.a, n.b]))};const n=ns.find(n=>t>=n[0]&&t<n[1]);if(n&&t<n[0]+.15)return null;return 45*Math.sin(t*1.7)+12*Math.sin(t*31);}`;
});
const easy = await sing(p, {a: 0, b: song.duration - .05, level: 'easy', voice: decent});
assert(easy.lives.left === 10 && easy.pct >= 70, 'a decent singer on «легко» loses no life over the whole song ' + JSON.stringify({left: easy.lives.left, pct: easy.pct}));
const off = await sing(p, {a: 1.5, b: 16.5, level: 'easy', voice: '()=>200'});
const gaps = off.losses.slice(1).map((x, i) => +(x.t - off.losses[i].t).toFixed(2));
assert(off.losses.length >= 3 && off.lives.left === 10 - off.losses.length, 'a passage two semitones off loses lives on «легко» ' + JSON.stringify(off.losses));
assert(off.losses[0].t >= 2.02 + 1.5 && gaps.every(g => g >= 2.5 - .05), 'not before 1.5 s of missed notes, then at most one life per 2.5 s ' + JSON.stringify({first: off.losses[0], gaps}));
const ui = await p.evaluate(() => window.Luma.test.state().lives);
assert(ui.hearts === 10 && ui.lost === off.losses.length, 'the corner shows the broken hearts of that attempt ' + JSON.stringify(ui));

// ── phone and desktop: the hearts fit in the head and cover nothing ──────────────────────────────────────────────
for (const vp of [{width: 390, height: 844}, {width: 1440, height: 900}]) {
  await p.setViewportSize(vp); await p.waitForTimeout(250);
  const box = await p.evaluate(() => {
    const r = e => { const q = document.getElementById(e).getBoundingClientRect(); return {l: q.left, r: q.right, t: q.top, b: q.bottom}; };
    const plot = window.Luma.test.plot(), stage = r('chartWrap');
    return {lives: r('lives'), stage, plotTop: stage.t + plot.top, pct: r('matchPct'), vw: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth};
  });
  assert(box.lives.r <= box.vw && box.lives.l >= 0 && !box.overflow && box.lives.b <= box.plotTop + 1 && box.lives.t >= box.stage.t,
    `at ${vp.width}px the hearts sit inside the stage head, above the piano roll ` + JSON.stringify(box));
  if (process.env.LUMA_SHOT) await p.screenshot({path: process.env.LUMA_SHOT.replace(/\.png$/, `_${vp.width}.png`)});
}
assert(logs.length === 0, 'console clean (driven clock) ' + JSON.stringify(logs));
await b.close();

// ── the last life: the song rewinds, the attempt is saved, a new one starts with full lives after the count-in ──────
const dir = mkdtempSync(join(tmpdir(), 'luma-lives-'));
const silence = join(dir, 'silence.wav'), rate = 48000, n = rate * 60, wav = Buffer.alloc(44 + n * 2);
wav.write('RIFF', 0); wav.writeUInt32LE(36 + n * 2, 4); wav.write('WAVE', 8); wav.write('fmt ', 12); wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(n * 2, 40);
writeFileSync(silence, wav);
const b2 = await launch(['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required', '--use-file-for-fake-audio-capture=' + silence]);
const {page: q, logs: qlogs} = await open(b2, {width: 390, height: 844});
await setLives(q, true, 3);
// the voice: a semitone and a half above every target, pushed in step with the audio clock
await q.evaluate(() => { const T = window.Luma.test; T.clearRange(); T.seek(0); window.__off = 1.5;
  window.__voice = setInterval(() => { const s = T.state(); if (s.mode !== 'singing') return; const ref = window.Luma.targetAt(s.time);
    T.livePush(ref ? {t: T.ctxTime(), f: 440 * Math.pow(2, (ref.m + window.__off - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: T.ctxTime(), f: null, confidence: 0, db: -70, rms: 0, peak: 0}); }, 20);
  document.getElementById('singBtn').click(); });
await q.waitForFunction(() => window.Luma.test.state().lives.lost >= 1, null, {timeout: 15000});
const mid = await q.evaluate(() => window.Luma.test.state().lives);
assert(mid.left === 2 && mid.lost === 1 && mid.retry === null, 'singing off pitch takes a life, and the song plays on ' + JSON.stringify(mid));
await q.waitForFunction(() => window.Luma.test.state().lives.last, null, {timeout: 15000});
await q.waitForFunction(() => { const s = window.Luma.test.state(); return s.mode === 'singing' && s.lives.countdown && s.lives.notice; }, null, {timeout: 8000});
const re = await q.evaluate(() => { const T = window.Luma.test, s = T.state(); return {lives: s.lives, time: s.time, takes: T.takes(), shot: null}; });
await q.evaluate(() => { window.__off = 0; });// the fragment again, in tune this time
if (process.env.LUMA_SHOT) { await q.waitForTimeout(600); await q.screenshot({path: process.env.LUMA_SHOT.replace(/\.png$/, '_rewind_390.png')}); }
const at = re.lives.last.at, expect = (() => { let to = null; for (const ph of song.phrases) if (ph.a <= at - 3 && (to === null || ph.a > to)) to = ph.a; return to === null || at - to > 20 ? Math.max(0, at - 9) : to; })();
assert(Math.abs(re.lives.last.to - expect) < 1e-6 && re.lives.last.to < at - 3, 'the rewind goes back to the start of the phrase sung wrong ' + JSON.stringify({at, to: re.lives.last.to, expect}));
assert(Math.abs(re.time - re.lives.last.to) < .05, 'the new attempt starts from the rewind point ' + JSON.stringify({time: re.time, to: re.lives.last.to}));
const fmt = t => String(Math.floor(t / 60)).padStart(2, '0') + ':' + String(Math.floor(t % 60)).padStart(2, '0');
assert(re.lives.notice === 'Ще раз з ' + fmt(re.lives.last.to) && re.lives.countdown, 'the count-in says where it starts again: ' + re.lives.notice);
assert(re.lives.left === 3 && re.lives.lost === 0 && re.lives.refill && !re.lives.out, 'the lives are full again, with the refill animation ' + JSON.stringify(re.lives));
assert(re.takes.length === 1 && re.takes[0].a === 0 && Math.abs(re.takes[0].endSong - at) < .6, 'the interrupted attempt is finished and kept, ending where the last life went ' + JSON.stringify(re.takes));
await q.waitForFunction(to => window.Luma.test.state().time > to + 1.5, re.lives.last.to, {timeout: 8000});
const tuned = await q.evaluate(() => window.Luma.test.state().lives);
assert(tuned.left === 3 && tuned.notice === null, 'sung in tune, the new attempt keeps its lives and the notice is gone ' + JSON.stringify(tuned));
await q.evaluate(() => clearInterval(window.__voice));
await q.locator('#stopBtn').click();
await q.waitForFunction(() => { const s = window.Luma.test.state(); return s.mode === 'idle' && window.Luma.test.takes().length === 2; }, null, {timeout: 6000});
await q.waitForTimeout(500);
const after = await q.evaluate(() => ({takes: window.Luma.test.takes(), runs: window.Luma.test.history.runs().map(r => ({id: r.id, a: r.a, b: r.b, target: r.target}))}));
assert(after.takes[0].a === re.lives.last.to && after.runs.length === 2 && after.takes.every(t => after.runs.some(r => r.id === t.runId) && !t.historyError),
  'the re-sung fragment is an attempt of its own, and both are in the history ' + JSON.stringify(after));
const err = await q.evaluate(() => document.getElementById('errorBanner').hidden);
assert(err && qlogs.length === 0, 'no error and a clean console through the rewind ' + JSON.stringify(qlogs));
await b2.close();
rmSync(dir, {recursive: true, force: true});
