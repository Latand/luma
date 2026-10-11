// Activity log: a trainer served by Studio writes clicks, state switches and attempt summaries to the library's
// logs/activity/<day>.jsonl; the Studio switch turns it off for every page; a trainer on another server stays silent.
import {readdirSync, readFileSync, existsSync} from 'node:fs';
import {join} from 'node:path';
import {launch, open, window_, assert} from './lib.mjs';
const studio = process.env.LUMA_STUDIO_URL || 'http://127.0.0.1:8793/', library = process.env.LUMA_TEST_LIBRARY;
if (!library) { console.error('FAIL LUMA_TEST_LIBRARY is not set: run through tests/e2e/run.sh'); process.exit(1); }
const folder = join(library, 'logs', 'activity');
const events = () => existsSync(folder) ? readdirSync(folder).filter(f => f.endsWith('.jsonl')).flatMap(f => readFileSync(join(folder, f), 'utf8').trim().split('\n').filter(Boolean).map(l => JSON.parse(l))) : [];
async function until(pred, ms = 5000) { const t0 = Date.now(); while (Date.now() - t0 < ms) { const hit = events().filter(pred); if (hit.length) return hit; await new Promise(r => setTimeout(r, 100)); } return []; }

const b = await launch(), profile = await b.newContext({viewport: {width: 1440, height: 900}});   // one profile, tabs share localStorage
async function tab(target) { const page = await profile.newPage(), logs = []; page.on('console', m => { if (['error', 'warning'].includes(m.type())) logs.push(m.type() + ': ' + m.text()); }); page.on('pageerror', e => logs.push('PAGEERROR ' + e.message)); await page.goto(target); await page.waitForTimeout(600); return {page, logs}; }
// Studio: the settings line says the log is on, and the page itself logs.
const {page: st, logs: stLogs} = await tab(studio);
assert(await st.locator('#activityLine').isVisible() && await st.locator('#activityToggle').isChecked(), 'Studio shows that activity is logged, switched on by default');
assert((await st.locator('#activityLine').textContent()).includes('songs/logs/activity'), 'the line says where the log goes');

// A trainer served by Studio: a click becomes an event with a stable control id, the page's slug and a session id.
const {page: tr, logs: trLogs} = await tab(studio + 'demo');
assert(await tr.evaluate(() => window.LumaActivity.enabled()), 'a trainer served by Studio logs');
const session = await tr.evaluate(() => window.LumaActivity.session);
await tr.locator('#lyricsBtn').click();
await tr.evaluate(() => window.LumaActivity.flush());
const clicks = await until(e => e.session === session && e.type === 'click' && e.data.id === 'lyricsBtn');
assert(clicks.length === 1, 'a trainer click is written to the activity log');
const c = clicks[0] || {data: {}};
assert(c.page === 'demo' && /^\d{4}-\d\d-\d\dT/.test(c.ts) && c.data.label && !('x' in c.data), 'the event carries page, ISO time and a label, never coordinates');
const mine = () => events().filter(e => e.session === session);
assert(mine().some(e => e.type === 'page_open' && e.data.kind === 'trainer' && e.data.songHash), 'opening a trainer is logged with its song key');
assert(mine().some(e => e.type === 'state' && e.data.lyrics === false), 'the lyrics switch shows up as a state change');

// A finished attempt logs the history's own summary.
const run = await tr.evaluate((winSrc) => {
  const L = window.Luma, T = L.test, win = eval(winSrc), pts = [];
  for (let t = 0; t < win.b - win.a; t += .02) { const ref = L.targetAt(win.a + t); pts.push({t, f: ref ? 440 * 2 ** ((ref.m - 69) / 12) : null, confidence: .95, db: -20, rms: .1, peak: .3}); }
  const r = T.injectTake({a: win.a, b: win.b, points: pts}); window.LumaActivity.flush(); return r;
}, window_());
const attempts = await until(e => e.session === session && e.type === 'attempt');
const a = (attempts[0] || {data: {}}).data;
assert(a.runId === run.runId && Math.round(a.match) === run.pct, 'the attempt event carries the same match as the trainer (' + a.match + ' vs ' + run.pct + ')');
assert(a.targetSec > 0 && a.hitSec > 0 && a.level && a.view && a.speed === 1 && Array.isArray(a.phrases), 'the attempt event has seconds, settings and per-phrase results');
await tr.goto('about:blank');
assert((await until(e => e.session === session && e.type === 'page_close')).length === 1, 'closing the trainer is logged with the time spent');

// Off in Studio means off in every trainer of this Studio.
await st.locator('#activityToggle').uncheck();
assert((await st.locator('#activityLine').textContent()).includes('вимкнено'), 'the line says the log is off');
const {page: tr2} = await tab(studio + 'demo');
const s2 = await tr2.evaluate(() => window.LumaActivity.session);
await tr2.locator('#lyricsBtn').click(); await tr2.evaluate(() => window.LumaActivity.flush()); await tr2.waitForTimeout(500);
assert(!events().some(e => e.session === s2), 'with the switch off a trainer writes nothing');
await st.locator('#activityToggle').check();
await tr2.close();

// A trainer from another server (here: the plain demo server) never posts.
const {page: other, logs: otherLogs} = await open(b);
let posted = 0; other.on('request', r => { if (r.url().includes('/activity')) posted++; });
await other.locator('#lyricsBtn').click(); await other.evaluate(() => window.LumaActivity.flush());
assert(!(await other.evaluate(() => window.LumaActivity.available)) && posted === 0, 'outside Studio the logger stays silent');
const errs = [...stLogs, ...trLogs, ...otherLogs].filter(l => !l.includes('favicon'));
assert(!errs.length, 'no console errors: ' + errs.join(' | '));
await b.close();
