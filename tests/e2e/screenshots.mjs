// README screenshots from the synthetic demo: desktop trainer with an attempt, narrow layout, Studio page (if running).
import {launch, open, window_} from './lib.mjs';
const b = await launch(); const out = process.env.LUMA_SHOT_DIR || 'docs/screenshots';
async function trainer(viewport, file) {
  const {page: p} = await open(b, viewport);
  await p.evaluate(w => { const L = window.Luma, T = L.test, win = eval(w); const midiF = m => 440 * Math.pow(2, (m - 69) / 12); const pts = [];
    for (let t = 0; t < win.b - win.a + 3; t += .02) { const ref = L.targetAt(win.a + t); const wobble = Math.sin(t * 2.1) * 1.2 + (t > 2.2 && t < 3.4 ? 3 : 0); pts.push({t, f: ref ? midiF(ref.m + wobble * (t > 1.4 ? 1 : .15)) : null, confidence: .95, db: -20, rms: .1, peak: .3}); }
    T.injectTake({a: win.a, b: win.b + 3, points: pts}); T.seek(win.a + 2.4); T.draw(); }, window_());
  await p.waitForTimeout(200); await p.screenshot({path: `${out}/${file}`}); await p.close();
}
await trainer({width: 1440, height: 900}, 'trainer-desktop.png'); await trainer({width: 390, height: 844}, 'trainer-narrow.png');
try { const s = await b.newPage({viewport: {width: 1000, height: 640}}); await s.goto(process.env.LUMA_STUDIO || 'http://127.0.0.1:8792/', {timeout: 3000}); await s.waitForTimeout(700); await s.screenshot({path: `${out}/studio.png`}); await s.close(); console.log('studio screenshot ok'); }
catch (e) { console.log('studio not running, skipped'); }
await b.close(); console.log('screenshots in', out);
