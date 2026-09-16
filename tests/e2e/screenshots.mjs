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
// the Прогрес tab on a seeded week of practice, so the README shows what progress looks like rather than describing it
{
  const {page: p} = await open(b, {width: 1440, height: 980});
  await p.evaluate(async w => { const L = window.Luma, T = L.test, H = T.history, S = window.LUMA_SONG, win = eval(w);
    const midiF = m => 440 * Math.pow(2, (m - 69) / 12);
    const day = n => { const d = new Date(); d.setDate(d.getDate() - n); d.setHours(19, 0, 0, 0); return d.toISOString(); };
    const whole = Math.ceil(H.totals().song * .97), phr = S.phrases.slice(0, 6), seeds = [];
    // a real week: a handful of passes each evening, so the day streak has something to count
    for (let i = 0; i < 8; i++) for (let k = 0; k < 6; k++) seeds.push({match: 5400 + i * 460 + k * 55, target: whole,
      startedAt: new Date(Date.parse(day(7 - i)) + k * 6e5).toISOString(),
      phrases: phr.map((q, j) => ({id: q.id, target: 260, hit: Math.min(260, 108 + j * 19 + i * 8 + k), median: 44 - j * 3}))});
    await H.seedMany(seeds);
    const pts = []; for (let t = 0; t < win.b - win.a + 3; t += .02) { const ref = L.targetAt(win.a + t);
      pts.push({t, f: ref ? midiF(ref.m + Math.sin(t * 2.1) * .5) : null, confidence: .95, db: -20}); }
    T.injectTake({a: win.a, b: win.b + 3, points: pts});
    await new Promise(r => setTimeout(r, 700)); T.seek(win.a + 2.4); T.draw();
    document.getElementById('tabProgress').click(); document.getElementById('toast').classList.remove('show'); }, window_());
  // the panel scrolls in the app; for the picture let it stand at its full height so the whole tab is one image
  await p.evaluate(() => { document.getElementById('takesPanel').style.maxHeight = 'none'; });
  await p.waitForTimeout(500); await p.locator('#takesPanel').screenshot({path: `${out}/trainer-progress.png`}); await p.close();
}
try { const s = await b.newPage({viewport: {width: 1000, height: 640}}); await s.goto(process.env.LUMA_STUDIO || 'http://127.0.0.1:8792/', {timeout: 3000}); await s.waitForTimeout(700); await s.screenshot({path: `${out}/studio.png`}); await s.close(); console.log('studio screenshot ok'); }
catch (e) { console.log('studio not running, skipped'); }
await b.close(); console.log('screenshots in', out);
