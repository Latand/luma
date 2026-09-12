// Local practice history: every attempt lands in IndexedDB by itself, survives a reload and a rebuilt trainer, keeps
// records inside one ruler, and round-trips through export and import. No microphone: attempts are injected.
import {execFileSync} from 'node:child_process';
import {launch, open, window_, assert, url} from './lib.mjs';
const py = process.env.LUMA_PY || '.venv/bin/python';
const b = await launch();
const {page: p, logs} = await open(b);
const win = await p.evaluate(w => eval(w), window_());

// One attempt per call, sung dead on the melody over [a, b].
const SING = `async ({a, b, off = 0, level, tolerance}) => {
  const L = window.Luma, T = L.test;
  if (level) T.setLevel(level);
  const midiF = m => 440 * Math.pow(2, (m - 69) / 12), pts = [];
  for (let t = 0; t < b - a; t += .02) { const ref = L.targetAt(a + t); pts.push({t, f: ref ? midiF(ref.m + off) : null, confidence: .95, db: -20}); }
  T.closeTrace(); const r = T.injectTake({a, b, points: pts, tolerance});
  await new Promise(r => setTimeout(r, 260));
  return r;
}`;
const sing = arg => p.evaluate(`(${SING})(${JSON.stringify(arg)})`);
const hist = fn => p.evaluate(`(async () => { const H = window.Luma.test.history; return (${fn}); })()`);

assert(await hist('H.available()'), 'the trainer page has a history store');
// ── 1 · two attempts survive a reload with the same ids ──────────────────────────────────────────────────────────
const first = await sing({a: win.a, b: win.b});
const second = await sing({a: win.a, b: win.b, off: 3});
const before = await hist('H.runs().map(r => r.id)');
assert(before.length === 2 && before.includes(first.runId) && before.includes(second.runId), 'both attempts are in the history ' + JSON.stringify(before));
await p.reload(); await p.waitForFunction(() => window.Luma && window.Luma.test.history.runs);
await p.waitForFunction(() => window.Luma.test.history.runs().length === 2, null, {timeout: 5000});
const after = await hist('H.runs()');
assert(after.length === 2 && after.every(r => before.includes(r.id)), 'a reloaded page finds the same attempts ' + JSON.stringify(after.map(r => r.id)));
assert(after.every(r => !r.hasAudio) && (await p.evaluate(() => window.Luma.test.takes().length)) === 0,
  'attempts without audio are kept as traces and scores, not as WAV');

// ── 2 · the stored trace rebuilds the stored numbers, frame for frame ────────────────────────────────────────────
const best = await hist('H.runs().slice().sort((x, y) => y.match - x.match)[0]');
const again = await hist(`H.rescore(${JSON.stringify(best.id)})`);
assert(again && again.hit > 0 && again.target === again.stored.target && again.hit === again.stored.hit,
  'rescoring the packed trace reproduces hit and target ' + JSON.stringify(again));

// ── 3 · rebuilding the trainer with the current app keeps the very same history ─────────────────────────────────
execFileSync(py, ['studio/build_html.py', '--rebuild', 'examples/demo/Luma_Demo.html'], {encoding: 'utf8'});
await p.goto(url); await p.waitForFunction(() => window.Luma && window.Luma.test.history.runs);
await p.waitForFunction(() => window.Luma.test.history.runs().length === 2, null, {timeout: 5000});
assert((await hist('H.runs().map(r => r.id)')).every(id => before.includes(id)), 'a rebuilt trainer opens on the same history');

// ── 4 · the ruler: a note edit opens a new map version, confirming a fragment by ear does not ───────────────────
const keyBefore = await hist('H.key()');
await p.evaluate(a => { const T = window.Luma.test; T.closeTrace(); T.setRange(a, a + 3); }, win.a);
await p.locator('#qualityBtn').click();
await p.evaluate(() => { document.getElementById('confirmTarget').checked = true; });
await p.locator('#saveVerify').click(); await p.waitForTimeout(120);
assert(await hist('H.key()') === keyBefore, 'confirming a fragment by ear keeps the comparison key');
await p.locator('#editBtn').click(); await p.waitForTimeout(120);
await p.locator('[data-delta="1"]').click(); await p.locator('#applyEdit').click(); await p.waitForTimeout(150);
const keyAfter = await hist('H.key()');
assert(keyAfter !== keyBefore && keyAfter.split('|')[0] === keyBefore.split('|')[0],
  'editing a note opens a new map version under the same song ' + JSON.stringify({keyBefore, keyAfter}));
await p.evaluate(() => { document.getElementById('resetEdits').onclick = null; });
await p.goto(url); await p.waitForFunction(() => window.Luma && window.Luma.test.history.runs);
await p.evaluate(() => localStorage.removeItem('luma.target.' + window.LUMA_SONG.id));
await p.goto(url); await p.waitForFunction(() => window.Luma && window.Luma.test.history.runs);
await p.waitForFunction(() => window.Luma.test.history.runs().length === 2, null, {timeout: 5000});
assert(await hist('H.key()') === keyBefore, 'dropping the edits restores the original ruler');

// ── 5 · records: coverage floors, tie-breaks, and one record per ruler ──────────────────────────────────────────
const phr = await p.evaluate(() => (window.LUMA_SONG.phrases || []).map(x => ({id: x.id, a: x.a, b: x.b})));
assert(phr.length > 0, 'the demo has practice phrases to keep records for');
const day = n => new Date(Date.now() - n * 864e5).toISOString();
await hist(`H.seedMany([
  {match: 9000, target: 900, startedAt: ${JSON.stringify(day(3))}, phrases: [{id: ${phr[0].id}, target: 40, hit: 40, median: 5}]},
  {match: 7000, target: 900, startedAt: ${JSON.stringify(day(2))}, phrases: [{id: ${phr[0].id}, target: 300, hit: 210, median: 40}]},
  {match: 7000, target: 900, startedAt: ${JSON.stringify(day(1))}, phrases: [{id: ${phr[0].id}, target: 300, hit: 210, median: 12}]}
])`);
const rec = await hist('H.records()');
const short = rec.phrases.find(x => x.id === phr[0].id);
assert(short && short.match === 7000, 'a fragment under 1.5 s of target gets no record ' + JSON.stringify(rec.phrases));
const tie = await hist(`H.runs().filter(r => r.phrases.some(x => x.id === ${phr[0].id} && x.target === 300))`);
const sharp = tie.find(r => r.phrases.some(x => x.id === phr[0].id && x.median === 12));
assert(tie.length === 2 && sharp && short.run === sharp.id, 'a tie goes to the smaller median |Δ| ' + JSON.stringify(tie.map(r => r.phrases)));
const other = await hist("H.recordsFor('strict')");
assert(other.song === null && other.phrases.length === 0, 'a different level keeps its own, still empty, records');
const songRec = await hist('H.records().song');
assert(songRec === null, 'no full pass yet, so the song record stays empty');
// a full pass of the whole song does earn one
const dur = await p.evaluate(() => window.LUMA_SONG.duration);
await sing({a: 0, b: dur});
const full = await hist('H.records().song');
assert(full && full.match > 9000, 'a pass over the whole song earns the song record ' + JSON.stringify(full));

// ── 6 · export, clear, import, and importing the same file twice ────────────────────────────────────────────────
const payload = await p.evaluate(() => window.Luma.test.history.exportPayload(false).then(d => JSON.stringify(d)));
const parsed = JSON.parse(payload);
assert(parsed.schema === 'luma.history.v1' && parsed.runs.length === (await hist('H.runs().length')) && parsed.traces.length > 0,
  'export carries the runs and their traces ' + JSON.stringify({runs: parsed.runs.length, traces: parsed.traces.length}));
const cleared = await p.evaluate(() => window.Luma.test.history.clearSong());
assert(cleared === parsed.runs.length && (await hist('H.runs().length')) === 0, 'clearing the song empties its history');
const back = await p.evaluate(d => window.Luma.test.history.importPayload(JSON.parse(d)), payload);
assert(back.imported === parsed.runs.length && (await hist('H.runs().length')) === parsed.runs.length, 'import restores every attempt ' + JSON.stringify(back));
const twice = await p.evaluate(d => window.Luma.test.history.importPayload(JSON.parse(d)), payload);
assert(twice.imported === 0 && twice.skipped === parsed.runs.length, 'importing the same file again changes nothing ' + JSON.stringify(twice));
const restored = await hist('H.rescore(H.runs().find(r => r.hasTrace).id)');
assert(restored && restored.target === restored.stored.target && restored.hit === restored.stored.hit, 'an imported trace still rebuilds its own numbers');
const bad = await p.evaluate(() => window.Luma.test.history.importPayload({schema: 'nope'}).then(() => 'accepted', e => e.message));
assert(/luma.history.v1/.test(bad), 'a foreign file is refused whole with a readable message: ' + bad);

// ── 7 · four hundred attempts and the song's history still opens fast ──────────────────────────────────────────
await hist(`H.seedMany(Array.from({length: 400}, (_, i) => ({match: 5000 + i * 10, target: 900, startedAt: new Date(Date.now() - i * 36e5).toISOString()})))`);
const ms = await hist('H.reloadMs()');
assert((await hist('H.runs().length')) >= 400 && ms < 50, 'the history of one song opens in ' + ms + ' ms with 400+ attempts');

// ── 8 · the storage ceiling drops traces that hold no record, and never a score ────────────────────────────────
const beforeCap = await hist('({traces: H.runs().filter(r => r.hasTrace).length, runs: H.runs().length})');
assert(beforeCap.traces > 1, 'there are traces to thin out ' + JSON.stringify(beforeCap));
await p.evaluate(() => window.Luma.test.history.enforceCeiling());
const afterCap = await hist('({traces: H.runs().filter(r => r.hasTrace).length, runs: H.runs().length, note: H.note()})');
const held = await hist('H.records()');
assert(afterCap.runs === beforeCap.runs && afterCap.traces < beforeCap.traces, 'the ceiling drops traces and keeps every score ' + JSON.stringify(afterCap));
const recordKeptItsTrace = held.song && await hist(`H.runs().find(r => r.id === ${JSON.stringify(held.song.id)}).hasTrace`);
assert(recordKeptItsTrace, 'the trace of the standing record survives the ceiling');
assert(/250 МБ/.test(afterCap.note) && /експорт/.test(afterCap.note), 'the footer says what happened and what to do: ' + afterCap.note);

// ── 9 · a full store never loses the attempt from the tab ──────────────────────────────────────────────────────
await p.evaluate(() => {
  const put = IDBObjectStore.prototype.put;
  window.__restorePut = () => { IDBObjectStore.prototype.put = put; };
  IDBObjectStore.prototype.put = function () { throw new DOMException('quota', 'QuotaExceededError'); };
});
const kept = await sing({a: win.a, b: win.b});
const state = await p.evaluate(() => ({takes: window.Luma.test.takes(), note: window.Luma.test.history.note()}));
await p.evaluate(() => window.__restorePut());
assert(state.takes.some(t => t.runId === kept.runId) && /переповнен/i.test(state.note),
  'a quota error keeps the attempt on screen and says so: ' + JSON.stringify(state.note));

assert(logs.length === 0, 'console clean ' + JSON.stringify(logs));
await p.screenshot({path: process.env.LUMA_SHOT || 'shot_history.png'});
await b.close();
