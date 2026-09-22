// Real audio path with Chrome's fake microphone: listen, loop region, live seek, an attempt with the recording switch
// off, then the same with it on — record, punch-in, review, undo, vocal toggle.
// Needs the trainer served over http (file:// blocks the AudioWorklet module).
import {launch, open, window_, assert} from './lib.mjs';
const b = await launch(['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required']);
const {page: p, logs} = await open(b, {width: 1280, height: 800});
const win = await p.evaluate(w => eval(w), window_());
const st = () => p.evaluate(() => { const t = window.Luma.test, s = t.state(), d = window.Luma.diagnostics(); return {mode: s.mode, time: +s.time.toFixed(2), range: s.range, loop: s.loop, tl: s.transportLoop, takes: t.takes(), punch: t.punchTarget(), trace: s.trace, label: document.getElementById('singLabel').textContent, gains: t.gains(), err: document.getElementById('errorBanner').hidden ? null : document.getElementById('errorText').textContent}; });
const setAudio = on => p.evaluate(v => { const c = document.getElementById('recordAudio'); c.checked = v; c.dispatchEvent(new Event('change')); }, on);
const cardButtons = () => p.evaluate(() => [...document.querySelectorAll('#takesList .take-actions button')].map(e => e.textContent));
// listen with a loop region → the clock wraps
await p.evaluate(w => { window.Luma.test.setRange(w.a, w.a + 2); document.getElementById('loopBtn').click(); window.Luma.test.seek(w.a); document.getElementById('listenBtn').click(); }, win);
const times = []; for (let i = 0; i < 8; i++) { await p.waitForTimeout(600); times.push((await st()).time); }
const s1 = await st(); assert(s1.mode === 'listen' && s1.tl && times.some((t, i) => i && t < times[i - 1]), 'loop region wraps seamlessly ' + JSON.stringify(times));
await p.evaluate(w => window.Luma.test.applySeek(w.b + 5), win); await p.waitForTimeout(900); const s2 = await st(); assert(s2.mode === 'listen' && s2.time > win.b + 4, 'live seek while listening');
await p.keyboard.press('KeyV'); await p.waitForTimeout(300); const s3 = await st(); assert(s3.gains.fore === 0 && !s3.gains.vocal, 'vocal stem muted (мінус)');
await p.keyboard.press('KeyV'); await p.waitForTimeout(600); const s4 = await st(); assert(s4.gains.fore > 0.3, 'vocal stem back');
await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(300);

// ── the default: sing with the recording switch off ─────────────────────────────────────────────────────────────
assert(await p.locator('#recordAudio').isChecked() === false, 'recording the voice into a WAV is off by default');
await p.evaluate(w => { window.Luma.test.clearRange(); window.Luma.test.seek(w.a); document.getElementById('singBtn').click(); }, win);
await p.waitForTimeout(2100 + 3000); await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(1200);
const q1 = await st(); const quiet = q1.takes[0];
assert(q1.takes.length === 1 && quiet.bytes === 0 && !quiet.hasAudio && quiet.points > 20 && quiet.duration > 2 && !q1.err,
  'an attempt without audio keeps its trace and its duration ' + JSON.stringify(quiet));
assert(quiet.pct !== null && q1.trace && q1.trace.id === quiet.id && q1.trace.frames > 0,
  'it is scored and stays on screen after the run ' + JSON.stringify({pct: quiet.pct, trace: q1.trace && q1.trace.frames}));
const noWav = await cardButtons();
assert(!noWav.includes('WAV') && noWav.includes('CSV') && noWav.includes('JSON'), 'the card offers CSV and JSON, and no WAV ' + JSON.stringify(noWav));
// ▶ on it plays the backing in sync with the trace
await p.evaluate(() => document.querySelector('#takesList .play').click()); await p.waitForTimeout(1200);
const q2 = await st(); assert(q2.mode === 'review' && q2.time > win.a && !q2.err, 'review plays the backing under a voiceless attempt ' + JSON.stringify({mode: q2.mode, time: q2.time, err: q2.err}));
await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(300);
await p.evaluate(w => window.Luma.test.seek(w.a + 1.2), win); await p.waitForTimeout(120);
const q3 = await st(); assert(q3.punch === quiet.id && /Перезаписати/.test(q3.label), 'punch-in is offered inside a voiceless attempt');
// the same attempt no longer accepts a punch once the recording switch changes
await setAudio(true); await p.waitForTimeout(150);
const q4 = await st(); assert(q4.punch === null && q4.label === 'Співати', 'switching the audio mode turns a punch-in into a new attempt ' + JSON.stringify(q4.label));
// re-record it with the switch off, to prove the points are spliced without a WAV
await setAudio(false); await p.waitForTimeout(120);
await p.evaluate(() => document.getElementById('singBtn').click()); await p.waitForTimeout(2100 + 2500);
await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(1200);
const q5 = await st(); const merged = q5.takes.find(t => t.id === quiet.id);
assert(q5.takes.length === 1 && merged.punches === 1 && merged.bytes === 0 && merged.duration > quiet.duration && merged.points > quiet.points,
  'a voiceless attempt is re-recorded from the playhead, points and all ' + JSON.stringify(merged));
await p.locator('#undoPunchBtn').click(); await p.waitForTimeout(200);
const q6 = (await st()).takes[0];
assert(q6.punches === 0 && q6.duration === quiet.duration, 'undo restores the previous version of a voiceless attempt');

// ── with the switch on, the whole audio path is back ────────────────────────────────────────────────────────────
await setAudio(true);
await p.evaluate(w => { window.Luma.test.closeTrace(); window.Luma.test.seek(w.a); document.getElementById('singBtn').click(); }, win);
await p.waitForTimeout(2100 + 3000); await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(1200);
const t1 = await st(); const loud = t1.takes[0];
assert(t1.takes.length === 2 && loud.hasAudio && loud.bytes > 44 && loud.duration > 2 && !t1.err, 'microphone take recorded with audio ' + JSON.stringify(loud));
assert((await cardButtons()).includes('WAV'), 'the card of an attempt with audio offers its WAV');
const quietClose = await p.evaluate(() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e);
  const card = document.querySelector('#takesList .take');
  return {blocked: e.defaultPrevented, hint: document.getElementById('takesHint').textContent, title: card.querySelector('.take-title').textContent, folded: card.querySelector('.take-files').hidden}; });
assert(!quietClose.blocked && !/[Зз]береж/.test(quietClose.hint + quietClose.title) && quietClose.folded,
  'a WAV nobody downloaded neither holds the tab open nor asks for a save, and its file waits behind ↓ ' + JSON.stringify(quietClose));
await p.evaluate(w => window.Luma.test.seek(w.a + 1.2), win); await p.waitForTimeout(100);
const t2 = await st(); assert(t2.punch === loud.id && /Перезаписати/.test(t2.label), 'punch-in offered inside the take');
await p.evaluate(() => document.getElementById('singBtn').click()); await p.waitForTimeout(2100 + 2500); await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(1200);
const t3 = await st(); const punched = t3.takes.find(t => t.id === loud.id);
assert(t3.takes.length === 2 && punched.punches === 1 && punched.duration > loud.duration && punched.bytes > loud.bytes, 'same take re-recorded from the playhead ' + JSON.stringify(punched));
// review playback moves the clock in sync
await p.evaluate(() => document.querySelector('#takesList .play').click()); await p.waitForTimeout(1200); const r1 = await st(); assert(r1.mode === 'review' && r1.time > win.a, 'review playback runs ' + JSON.stringify({mode: r1.mode, time: r1.time, err: r1.err}));
await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(300);
await p.locator('#undoPunchBtn').click();
const undone = (await st()).takes.find(t => t.id === loud.id);
assert(undone.punches === 0 && undone.duration === loud.duration, 'undo restores the original recording and metadata');
await p.locator('#newTakeBtn').click(); await p.waitForTimeout(2100 + 1000); await p.locator('#stopBtn').click(); await p.waitForTimeout(600);
const fresh = await st();
assert(fresh.takes.length === 3 && fresh.takes.some(t => t.id === loud.id && t.duration === loud.duration), 'new take preserves the existing attempt');
// every attempt of this session is in the history, with and without audio
const runs = await p.evaluate(() => window.Luma.test.history.runs().map(r => ({id: r.id, hasAudio: r.hasAudio, target: r.target})));
assert(runs.length === fresh.takes.length && runs.some(r => r.hasAudio) && runs.some(r => !r.hasAudio),
  'both kinds of attempt are in the local history ' + JSON.stringify(runs.map(r => r.hasAudio)));
assert(logs.length === 0, 'console clean ' + JSON.stringify(logs));
await p.screenshot({path: process.env.LUMA_SHOT || 'shot_audio.png'}); await b.close();
