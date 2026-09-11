// Real audio path with Chrome's fake microphone: listen, loop region, live seek, record, punch-in, review, vocal toggle.
// Needs the trainer served over http (file:// blocks the AudioWorklet module).
import {launch, open, window_, assert} from './lib.mjs';
const b = await launch(['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required']);
const {page: p, logs} = await open(b, {width: 1280, height: 800});
const win = await p.evaluate(w => eval(w), window_());
const st = () => p.evaluate(() => { const t = window.Luma.test, s = t.state(), d = window.Luma.diagnostics(); return {mode: s.mode, time: +s.time.toFixed(2), range: s.range, loop: s.loop, tl: s.transportLoop, takes: t.takes(), punch: t.punchTarget(), label: document.getElementById('singLabel').textContent, gains: t.gains(), err: document.getElementById('errorBanner').hidden ? null : document.getElementById('errorText').textContent}; });
// listen with a loop region → the clock wraps
await p.evaluate(w => { window.Luma.test.setRange(w.a, w.a + 2); document.getElementById('loopBtn').click(); window.Luma.test.seek(w.a); document.getElementById('listenBtn').click(); }, win);
const times = []; for (let i = 0; i < 8; i++) { await p.waitForTimeout(600); times.push((await st()).time); }
const s1 = await st(); assert(s1.mode === 'listen' && s1.tl && times.some((t, i) => i && t < times[i - 1]), 'loop region wraps seamlessly ' + JSON.stringify(times));
await p.evaluate(w => window.Luma.test.applySeek(w.b + 5), win); await p.waitForTimeout(900); const s2 = await st(); assert(s2.mode === 'listen' && s2.time > win.b + 4, 'live seek while listening');
await p.keyboard.press('KeyV'); await p.waitForTimeout(300); const s3 = await st(); assert(s3.gains.fore === 0 && !s3.gains.vocal, 'vocal stem muted (мінус)');
await p.keyboard.press('KeyV'); await p.waitForTimeout(600); const s4 = await st(); assert(s4.gains.fore > 0.3, 'vocal stem back');
await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(300);
// record a take, stop, punch in from inside it
await p.evaluate(w => { window.Luma.test.clearRange(); window.Luma.test.seek(w.a); document.getElementById('singBtn').click(); }, win);
await p.waitForTimeout(2100 + 3000); await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(1200);
const t1 = await st(); assert(t1.takes.length === 1 && t1.takes[0].duration > 2 && !t1.err, 'microphone take recorded ' + JSON.stringify(t1.takes[0]));
await p.evaluate(w => window.Luma.test.seek(w.a + 1.2), win); await p.waitForTimeout(100); const t2 = await st(); assert(t2.punch === t1.takes[0].id && /Перезаписати/.test(t2.label), 'punch-in offered inside the take');
await p.evaluate(() => document.getElementById('singBtn').click()); await p.waitForTimeout(2100 + 2500); await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(1200);
const t3 = await st(); assert(t3.takes.length === 1 && t3.takes[0].punches === 1 && t3.takes[0].duration > t1.takes[0].duration, 'same take re-recorded from the playhead ' + JSON.stringify(t3.takes[0]));
// review playback moves the clock in sync
await p.evaluate(() => document.querySelector('#takesList .play').click()); await p.waitForTimeout(1200); const r1 = await st(); assert(r1.mode === 'review' && r1.time > win.a, 'review playback runs ' + JSON.stringify({mode: r1.mode, time: r1.time, err: r1.err}));
await p.evaluate(() => document.getElementById('stopBtn').click()); await p.waitForTimeout(300);
await p.locator('#undoPunchBtn').click();
const undone = await st(); assert(undone.takes.length === 1 && undone.takes[0].punches === 0 && undone.takes[0].duration === t1.takes[0].duration, 'undo restores the original recording and metadata');
await p.locator('#newTakeBtn').click();await p.waitForTimeout(2100 + 1000);await p.locator('#stopBtn').click();await p.waitForTimeout(500);
const fresh = await st();assert(fresh.takes.length === 2 && fresh.takes.some(t => t.id === t1.takes[0].id && t.duration === t1.takes[0].duration), 'new take preserves the existing attempt');
assert(logs.length === 0, 'console clean ' + JSON.stringify(logs));
await p.screenshot({path: process.env.LUMA_SHOT || 'shot_audio.png'}); await b.close();
