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
// ── 1 · two attempts survive a reload with the same ids, and come back into the list with their lines ────────────
const first = await sing({a: win.a, b: win.b});
const second = await sing({a: win.a, b: win.b, off: 3});
const before = await hist('H.runs().map(r => r.id)');
assert(before.length === 2 && before.includes(first.runId) && before.includes(second.runId), 'both attempts are in the history ' + JSON.stringify(before));
await p.reload(); await p.waitForFunction(() => window.Luma && window.Luma.test.history.runs);
await p.waitForFunction(() => window.Luma.test.history.runs().length === 2, null, {timeout: 5000});
const after = await hist('H.runs()');
assert(after.length === 2 && after.every(r => before.includes(r.id)), 'a reloaded page finds the same attempts ' + JSON.stringify(after.map(r => r.id)));
assert(after.every(r => !r.hasAudio), 'attempts without audio are kept as traces and scores, not as WAV');
await p.waitForFunction(() => window.Luma.test.takes().length === 2, null, {timeout: 5000});
const shown = await p.evaluate(() => window.Luma.test.takes());
assert(shown.every(t => t.restored && !t.hasAudio && t.points > 20) && JSON.stringify(shown.map(t => t.runId)) === JSON.stringify([second.runId, first.runId])
  && shown.find(t => t.runId === first.runId).pct === first.pct && shown.find(t => t.runId === second.runId).pct === second.pct,
  'the reopened tab lists both lines again, newest first, with the score they were sung with ' + JSON.stringify(shown.map(t => [t.runId === first.runId ? 'first' : 'second', t.pct, t.points])));
assert(!/[Зз]береж/.test(await p.locator('#takesHint').textContent()), 'nothing on the list asks for a save');

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

// ── 6 · a re-scored attempt exports the ruler it now carries, not the one it was saved with ────────────────────
{
  const before = await p.evaluate(() => { const t = window.Luma.test, id = t.takes()[0].id;
    t.selectTake(id); return {id, pct: t.takes()[0].pct, json: t.history.takeJSON(id).runs[0]}; });
  await p.evaluate(() => { const sel = document.getElementById('octave'); sel.value = '12'; sel.dispatchEvent(new Event('change')); });
  await p.waitForTimeout(200);
  const after = await p.evaluate(id => ({pct: window.Luma.test.takes().find(t => t.id === id).pct,
    json: window.Luma.test.history.takeJSON(id).runs[0]}), before.id);
  assert(before.json.octave === 0 && after.json.octave === 12, 'the exported attempt carries the octave it is now scored with');
  assert(after.json.match === after.pct * 100 && after.pct !== before.pct,
    'the exported numbers follow the re-scored attempt ' + JSON.stringify({card: after.pct, file: after.json.match, was: before.pct}));
  assert(after.json.hit <= after.json.target, 'a re-scored export never claims more hits than it has target frames');
  await p.evaluate(() => { const sel = document.getElementById('octave'); sel.value = '0'; sel.dispatchEvent(new Event('change')); });
  await p.waitForTimeout(200);
  const back = await p.evaluate(id => window.Luma.test.history.takeJSON(id).runs[0], before.id);
  assert(back.match === before.json.match && back.octave === 0, 'putting the octave back restores the original numbers');
}

// ── 7 · export, clear, import, and importing the same file twice ────────────────────────────────────────────────
const payload = await p.evaluate(() => window.Luma.test.history.exportPayload(false).then(d => JSON.stringify(d)));
const parsed = JSON.parse(payload);
assert(parsed.schema === 'luma.history.v1' && parsed.runs.length === (await hist('H.runs().length')) && parsed.traces.length > 0,
  'export carries the runs and their traces ' + JSON.stringify({runs: parsed.runs.length, traces: parsed.traces.length}));
const captionsBefore = await p.evaluate(() => [...document.querySelectorAll('#takesList .rec-delta')].map(e => e.textContent));
assert(captionsBefore.length > 0, 'attempt cards carry a record caption to begin with ' + JSON.stringify(captionsBefore));
const cleared = await p.evaluate(() => window.Luma.test.history.clearSong());
assert(cleared === parsed.runs.length && (await hist('H.runs().length')) === 0, 'clearing the song empties its history');
const captionsAfter = await p.evaluate(() => [...document.querySelectorAll('#takesList .rec-delta')].map(e => e.textContent));
assert(captionsAfter.length === 0, 'clearing the history takes the record captions off the cards too ' + JSON.stringify(captionsAfter));
const back = await p.evaluate(d => window.Luma.test.history.importPayload(JSON.parse(d)), payload);
assert(back.imported === parsed.runs.length && (await hist('H.runs().length')) === parsed.runs.length, 'import restores every attempt ' + JSON.stringify(back));
const captionsBack = await p.evaluate(() => [...document.querySelectorAll('#takesList .rec-delta')].map(e => e.textContent));
assert(captionsBack.length === captionsBefore.length, 'an import puts the captions back, recounted against what it brought ' + JSON.stringify(captionsBack));
const twice = await p.evaluate(d => window.Luma.test.history.importPayload(JSON.parse(d)), payload);
assert(twice.imported === 0 && twice.skipped === parsed.runs.length, 'importing the same file again changes nothing ' + JSON.stringify(twice));
const restored = await hist('H.rescore(H.runs().find(r => r.hasTrace).id)');
assert(restored && restored.target === restored.stored.target && restored.hit === restored.stored.hit, 'an imported trace still rebuilds its own numbers');
const bad = await p.evaluate(() => window.Luma.test.history.importPayload({schema: 'nope'}).then(() => 'accepted', e => e.message));
assert(/luma.history.v1/.test(bad), 'a foreign file is refused whole with a readable message: ' + bad);
// every refusal speaks the language of the interface, whatever broke
const broken = await p.evaluate(d => {
  const cases = {};
  const one = (name, mutate) => { const copy = JSON.parse(d); mutate(copy);
    return window.Luma.test.history.importPayload(copy).then(() => (cases[name] = 'accepted'), e => (cases[name] = e.message)); };
  return Promise.all([
    // a fresh id, so the trace is really decoded instead of skipped as an attempt we already have
    one('base64', c => { c.runs[0].id = 'imported-broken-1'; c.traces[0].runId = 'imported-broken-1'; c.traces[0].segments[0].cents = '!!!not base64!!!'; }),
    one('songs', c => { delete c.songs[0].songHash; }),
    one('phrases', c => { c.runs[0].phraseIds = ['x']; c.runs[0].phraseStats = [1, 2, 3, 4]; }),
  ]).then(() => cases);
}, payload);
for (const [name, message] of Object.entries(broken))
  assert(/[\u0400-\u04FF]/.test(message) && !/Failed to execute|not correctly encoded/.test(message),
    'a broken file refuses in Ukrainian (' + name + '): ' + message);
assert((await hist('H.runs().length')) === parsed.runs.length, 'a refused file changes nothing in the store');
// one later attempt from a file: the song's first date stays, the last one moves, and the same file again is a no-op
const songRow = () => p.evaluate(() => window.Luma.test.history.exportPayload(false).then(d => JSON.stringify(d.songs[0])));
const rowBefore = JSON.parse(await songRow());
const stamp = new Date(Date.parse(rowBefore.lastRunAt) + 60e3).toISOString();
const single = {...parsed, songs: [{...parsed.songs[0], firstRunAt: stamp, lastRunAt: stamp, runCount: 1}],
  runs: [{...parsed.runs[0], id: 'imported-later-1', startedAt: stamp, endedAt: stamp, hasTrace: false}], traces: []};
await p.evaluate(d => window.Luma.test.history.importPayload(d), single);
const rowAfter = JSON.parse(await songRow());
assert(rowAfter.firstRunAt === rowBefore.firstRunAt && rowAfter.lastRunAt === stamp && rowAfter.runCount === rowBefore.runCount + 1,
  'importing a later attempt keeps the song’s first date and moves only the last one ' + JSON.stringify({
    before: [rowBefore.firstRunAt, rowBefore.lastRunAt, rowBefore.runCount], after: [rowAfter.firstRunAt, rowAfter.lastRunAt, rowAfter.runCount]}));
const rowText = await songRow();
await p.evaluate(d => window.Luma.test.history.importPayload(d), single);
assert(await songRow() === rowText, 'importing that file again leaves the song row as it was, byte for byte');

// ── 8 · four hundred attempts and the song's history still opens fast ──────────────────────────────────────────
await hist(`H.seedMany(Array.from({length: 400}, (_, i) => ({match: 5000 + i * 10, target: 900, startedAt: new Date(Date.now() - i * 36e5).toISOString()})))`);
const ms = await hist('H.reloadMs()');
assert((await hist('H.runs().length')) >= 400 && ms < 50, 'the history of one song opens in ' + ms + ' ms with 400+ attempts');

// ── 10 · a full store never loses the attempt from the tab, and never lets it go quietly ────────────────────────
await p.evaluate(() => {
  const put = IDBObjectStore.prototype.put;
  window.__restorePut = () => { IDBObjectStore.prototype.put = put; };
  IDBObjectStore.prototype.put = function () { throw new DOMException('quota', 'QuotaExceededError'); };
});
const kept = await sing({a: win.a, b: win.b});
const state = await p.evaluate(() => ({takes: window.Luma.test.takes(), note: window.Luma.test.history.note()}));
assert(state.takes.some(t => t.runId === kept.runId && t.historyError) && /переповнен/i.test(state.note),
  'a quota error keeps the attempt on screen and says so: ' + JSON.stringify(state.note));
const unloadWarns = () => p.evaluate(() => { const e = new Event('beforeunload', {cancelable: true}); window.dispatchEvent(e); return e.defaultPrevented; });
assert(await unloadWarns(), 'closing the tab warns while an attempt is missing from the history');
let asked = '';
p.once('dialog', d => { asked = d.message(); d.dismiss(); });
await p.locator('#takesList .take-actions button[aria-label$="в історії її немає"]').first().click();
assert(/немає в історії/.test(asked) && await p.evaluate(id => window.Luma.test.takes().some(t => t.id === id), kept.id),
  '× on such an attempt asks first, and a «no» keeps it: ' + asked);
// every attempt the store refused has to stay, so a tab full of them is the one case where «Співати» still refuses
// (the stored attempts the reopened tab brought back may leave, the refused ones may not)
const crowd = await p.evaluate(async a => { const T = window.Luma.test, stored = T.takes().filter(t => !t.historyError).length;
  while (T.takes().length < 21 + stored) T.injectTake({a, b: a + .8, points: []});
  await new Promise(r => setTimeout(r, 400));
  return {takes: T.takes().length, refused: T.takes().filter(t => t.historyError).length}; }, win.a);
await p.evaluate(() => { const T = window.Luma.test; T.closeTrace(); T.clearRange(); T.seek(0); });
await p.locator('#singBtn').click();
await p.waitForFunction(() => !document.getElementById('errorBanner').hidden, null, {timeout: 5000});
const refusal = await p.evaluate(() => ({text: document.getElementById('errorText').textContent, takes: window.Luma.test.takes().length}));
assert(/Ліміт слідів/.test(refusal.text) && !/не втратить|[Зз]береж/.test(refusal.text) && refusal.takes === crowd.takes,
  'with only refused attempts to drop, the trace limit refuses, promises nothing about the history and asks for no save: ' + refusal.text);
await p.evaluate(() => { window.__restorePut(); document.getElementById('dismissError').click(); });
// once the store has room again (here: the song cleared), the refused attempts are written by themselves
await p.evaluate(() => window.Luma.test.history.clearSong());
await p.waitForFunction(() => window.Luma.test.takes().every(t => !t.historyError), null, {timeout: 5000});
const written = await hist('H.runs().length');
assert(written === crowd.refused && !(await unloadWarns()), 'after the clear the refused attempts are in the history and closing the tab is quiet again ' + JSON.stringify({written, crowd}));

// ── 11 · importing another song starts its history clean and leaves the previous song's traces alone ──────────
const oldHash = await hist('H.songHash()');
const beforeSwap = await p.evaluate(() => window.Luma.test.history.exportPayload(true).then(d => ({
  traces: d.traces.map(t => t.runId), runs: d.runs.length, songs: d.songs.map(s => s.songHash)})));
await p.evaluate(() => {
  // a package for the same audio under a new identity: enough to move songHash() the way «Інша пісня» does
  const s = window.LUMA_SONG;
  const song = {...structuredClone(s), id: 'aaaaaaaaaaaaaaaaaaaa', sourceId: 'SWAPPED-SONG-SOURCE-ID'};
  const pack = {schema: 'luma.pack.v1', song, assets: window.LUMA_ASSETS};
  window.__pack = JSON.stringify(pack);
});
const packText = await p.evaluate(() => window.__pack);
await p.setInputFiles('#importFile', {name: 'other.luma.json', mimeType: 'application/json', buffer: Buffer.from(packText)});
await p.waitForFunction(() => window.Luma.test.history.songHash() === 'SWAPPED-SONG-SOURCE-ID', null, {timeout: 8000});
await p.waitForFunction(() => window.Luma.test.history.runs().length === 0, null, {timeout: 8000});
assert(await hist('H.songHash()') !== oldHash, 'the imported song brings its own key');
assert((await hist('H.runs().length')) === 0, 'a song with no attempts yet opens on an empty history, not the previous song’s');
const fresh = await sing({a: win.a, b: win.b});
const afterSwap = await p.evaluate(() => window.Luma.test.history.exportPayload(true).then(d => ({
  row: d.songs.find(s => s.songHash === 'SWAPPED-SONG-SOURCE-ID'),
  traces: d.traces.map(t => t.runId), runs: d.runs.length})));
assert(afterSwap.row && afterSwap.row.runCount === 1, 'the new song’s row counts its own attempts ' + JSON.stringify(afterSwap.row && {runCount: afterSwap.row.runCount, firstRunAt: afterSwap.row.firstRunAt}));
assert(afterSwap.row.firstRunAt === afterSwap.row.lastRunAt, 'and dates them by its own first and last attempt');
assert(afterSwap.row.maps.length === 1, 'and lists only the map version it was sung against ' + JSON.stringify(afterSwap.row.maps.map(m => m.mapVersion)));
const lost = beforeSwap.traces.filter(id => !afterSwap.traces.includes(id));
assert(lost.length === 0, 'singing in the new song evicts no trace from the previous one ' + JSON.stringify(lost));
assert(afterSwap.runs === beforeSwap.runs + 1, 'and adds exactly one attempt to the store');
assert(logs.length === 0, 'console clean ' + JSON.stringify(logs));
await p.screenshot({path: process.env.LUMA_SHOT || 'shot_history.png'});
await b.close();
