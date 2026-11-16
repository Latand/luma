// Screenshots of the real trainer, one per time window, for the before/after contact sheets.
//
//   node shoot_trainer.mjs <trainer-url> <out-dir> [--step 11] [--from 0] [--to <duration>] [--width 1700] [--height 820] [--head] [--notes] [--profile-root directory]
//
// The trainer shows 12 s of the roll at widths >= 1100 px with the playhead 34 % from the left, so a window that
// starts at `a` is shot with the playhead at a + 4.08 s. Each shot is the #chart canvas alone; meta.json keeps the
// plot's left/right edge in canvas pixels, so another tool can lay a spectrogram over the same time axis.
// Nothing reaches the operator's activity log: the logger's own off switch is set before the page's scripts run and
// POST /activity is aborted on the network as well. The profile is a fresh directory in a short temporary path.
import {chromium} from 'playwright';
import {mkdtempSync, mkdirSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const args = process.argv.slice(2); const url = args[0], out = args[1];
const opt = (name, dflt) => { const i = args.indexOf('--' + name); return i >= 0 ? Number(args[i + 1]) : dflt; };
if (args.includes('--help')) { console.log('usage: shoot_trainer.mjs <trainer-url> <out-dir> [--profile-root directory]'); process.exit(0); }
if (!url || !out) { console.error('usage: shoot_trainer.mjs <trainer-url> <out-dir> [--step 11] [--from 0] [--to s]'); process.exit(2); }
const step = opt('step', 11), width = opt('width', 1700), height = opt('height', 820);
const target = new URL(url);
if (!['http:', 'https:'].includes(target.protocol) ||
    !['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname) ||
    !target.pathname.startsWith('/qa/')) throw Error('use an isolated local static server under /qa/');
const rootIndex = args.indexOf('--profile-root');
const profileRoot = rootIndex >= 0 ? args[rootIndex + 1] : tmpdir();
if (!profileRoot || Buffer.byteLength(join(profileRoot, 'sq-XXXXXX')) > 80)
  throw Error('provide a short private scratch directory with --profile-root');
if (!(step > 0) || !(width > 0) || !(height > 0)) throw Error('positive step and viewport required');
mkdirSync(out, {recursive: true});
const profile = mkdtempSync(join(profileRoot, 'sq-'));
let blocked = 0;
const ctx = await chromium.launchPersistentContext(profile, {headless: true, viewport: {width, height}, deviceScaleFactor: 1, args: ['--no-sandbox', '--disable-gpu']});
try {
  await ctx.addInitScript(() => { try { localStorage.setItem('luma.activity', 'off'); } catch (_) {} });
  await ctx.route('**/*', r => { if (!['GET', 'HEAD'].includes(r.request().method())) { blocked++; return r.abort(); } return r.continue(); });
  const page = ctx.pages()[0] || await ctx.newPage(); const logs = [];
  page.on('pageerror', e => logs.push('PAGEERROR ' + e.message));
  await page.goto(url, {waitUntil: 'load', timeout: 120000});
  await page.waitForFunction(() => window.Luma && window.Luma.test && window.LUMA_SONG, null, {timeout: 120000});
  await page.waitForTimeout(800);
  const info = await page.evaluate(() => { const S = window.LUMA_SONG; return {title: S.title, artist: S.artist, id: S.id, duration: S.duration, notes: S.notes.length, lines: S.lyrics.length, words: S.lyrics.reduce((n, l) => n + l.words.length, 0)}; });
  const from = opt('from', 0), to = opt('to', info.duration); const shots = [];
  // the «Голова» panel takes a third of the roll's width; it is switched off (in this throwaway profile only) unless
  // --head is given, so the 12 s window gets the whole width. The toast is hidden for the same reason.
  await page.addStyleTag({content: '#toast{display:none!important}'});
  if (!args.includes('--head')) await page.evaluate(() => { const b = document.getElementById('tractBtn'); if (b && b.getAttribute('aria-pressed') === 'true') b.click(); });
  // The operator sings from the contour view, so that is the view shot unless --notes is given.
  const wantView = args.includes('--notes') ? 'notes' : 'contour';
  await page.evaluate(v => { const b = document.querySelector('[data-view="' + v + '"]'); if (b) b.click(); }, wantView);
  await page.waitForTimeout(300);
  for (let k = 0, a = from; a < to; k++, a += step) {
    const t = Math.min(info.duration, a + 12 * .34);
    const m = await page.evaluate(t => { const T = window.Luma.test; T.seek(t); T.draw(); const v = T.viewWindow(t), b = T.plot(), c = document.getElementById('chart'), r = c.getBoundingClientRect();
      return {view: v, plot: b, canvas: {w: c.width, h: c.height, cssW: r.width, cssH: r.height}, dpr: T.dpr(), time: window.Luma.diagnostics().time}; }, t);
    await page.waitForTimeout(120);
    await page.evaluate(() => window.Luma.test.draw());
    const name = `w${String(k).padStart(2, '0')}_${a.toFixed(0).padStart(3, '0')}.png`;
    await page.locator('#chart').screenshot({path: join(out, name)});
    shots.push({k, a: m.view.a, b: m.view.b, playhead: t, file: name, plot: m.plot, canvas: m.canvas, dpr: m.dpr});
  }
  writeFileSync(join(out, 'meta.json'), JSON.stringify({url, view: wantView, shotAt: new Date().toISOString(), viewport: {width, height}, step, song: info, activityPostsBlocked: blocked, pageErrors: logs, shots}, null, 1));
  console.log(`${shots.length} windows -> ${out}; song ${JSON.stringify(info)}; POST /activity blocked: ${blocked}; page errors: ${logs.length}`);
} finally { await ctx.close(); rmSync(profile, {recursive: true, force: true}); }
