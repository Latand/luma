'use strict';
// Microphone offset from recorded attempts (docs/design/LATENCY_AUTOCAL.md §3). Pure functions, no DOM and no storage:
// the trainer (app/app.js) reads the history and the targets and hands them over.
//
// Stored traces are post-correction: capture opens `latency` ms after the music, so a take recorded with setting L whose
// voice lands d ms of song time late implies the setting L + d / speed. Every take is matched against the melody at
// offsets −300…+700 ms on a 10 ms grid; only phrase interiors vote, so a late start of a phrase cannot pull the constant.
(() => {
const CAL = {
  conf: 204, gate: -48, noPitch: -32768,          // the trainer's own voiced-frame rule: YIN ≥ .8, level ≥ gate
  dMin: -300, dMax: 700, step: 10,                // residual offset grid, ms of song time (positive = voice arrives late)
  kernel: 100,                                    // cents: per-pair credit max(0, 1-(e/kernel)^2), octave folded
  onsetGap: .25, onsetSkip: .30,                  // target phrase onset: voiced after ≥ .25 s of no target; skip its first .30 s
  block: 15,                                      // jackknife block, s of song time
  minSec: 6, minBlocks: 3, minContrast: .12, maxSe: 60,   // a take counts only past all four; inside them it is weighted
  seFloor: 15, recent: 30, minTakes: 12,          // weight 1/(se² + floor²); newest `recent` usable takes; fewer than minTakes → no suggestion
};
const fold = c => { c %= 1200; if (c > 600) c -= 1200; else if (c < -600) c += 1200; return c; };

// The melody the voice is matched against: `cents` is the contour on a `hop` grid (noPitch where there is none or it is
// not confident), `notes` remove ignored notes and carry manual shifts, `spans` (when given) are the only scored times.
function prepareTarget({hop, cents, notes, spans = null}) {
  const n = cents.length, tm = new Float32Array(n).fill(NaN), interior = new Uint8Array(n), onsets = [];
  const ns = [...notes].sort((x, y) => x.a - y.a); let k = 0, sp = 0;
  for (let i = 0; i < n; i++) {
    const t = i * hop, c = cents[i];
    while (k < ns.length && ns[k].b <= t) k++;
    const note = ns[k] && ns[k].a <= t && t < ns[k].b ? ns[k] : null;
    if (note?.ignored || c === CAL.noPitch) continue;
    if (spans) { while (sp < spans.length && spans[sp][1] < t) sp++; if (!(sp < spans.length && spans[sp][0] <= t)) continue; }
    tm[i] = c / 100 + (note?.manual ? note.m - (note.originalM ?? note.m) : 0);
  }
  let last = -1e9, runStart = -1e9;
  for (let i = 0; i < n; i++) {
    if (Number.isNaN(tm[i])) continue;
    const t = i * hop;
    if (t - last > CAL.onsetGap) { runStart = t; onsets.push(t); }
    last = t; interior[i] = t - runStart >= CAL.onsetSkip ? 1 : 0;
  }
  const G = .01, n10 = Math.max(0, Math.floor((n - 1) * hop / G)), tm10 = new Float32Array(n10), in10 = new Uint8Array(n10), T0 = {hop, tm};
  for (let j = 0; j < n10; j++) { tm10[j] = tgt(T0, j * G); in10[j] = interior[Math.round(j * G / hop)]; }
  return {hop, tm, interior, onsets, tm10, in10};
}
function tgt(T, x) {             // linear between two finite neighbours a semitone apart, else nearest
  const f = x / T.hop, i = Math.floor(f); if (i < 0 || i + 1 >= T.tm.length) return NaN;
  const a = T.tm[i], b = T.tm[i + 1], r = f - i;
  if (a === a && b === b && Math.abs(a - b) < 1) return a + (b - a) * r;
  return r < .5 ? a : b;
}
function sungFrames(run, trace) {
  const t = [], m = [];
  for (const sg of trace.segments) for (let i = 0; i < sg.cents.length; i++) {
    const c = sg.cents[i]; if (c === CAL.noPitch || sg.conf[i] < CAL.conf || sg.db[i] < CAL.gate) continue;
    t.push(run.a + (sg.t0 + i * trace.hop) * run.speed); m.push(c / 100);
  }
  return {t: Float64Array.from(t), m: Float32Array.from(m), hop: trace.hop * run.speed};
}
function estimateTake(run, trace, T) {
  const S = sungFrames(run, trace), N = S.t.length, nd = Math.round((CAL.dMax - CAL.dMin) / CAL.step) + 1;
  if (N < 50) return {ok: false, why: 'few voiced frames', startedAt: run.startedAt, latency: run.latency || 0};
  // a constant pitch bias (a semitone flat, a fifth down) would blur the match: remove the circular mode at d=0
  const hist = new Float64Array(120);
  for (let j = 0; j < N; j++) { const y = tgt(T, S.t[j]); if (y === y) hist[Math.floor((fold((S.m[j] - y) * 100) + 600) / 10) % 120]++; }
  let bias = 0, bw = -1; for (let b = 0; b < 120; b++) { let w = 0; for (let q = -5; q <= 5; q++) w += hist[(b + q + 120) % 120]; if (w > bw) { bw = w; bias = b * 10 - 595; } }
  const t0 = S.t[0], nb = Math.max(1, Math.ceil((S.t[N - 1] - t0 + 1e-9) / CAL.block));
  const acc = new Float64Array(nb * nd), k2 = CAL.kernel * CAL.kernel, q0 = CAL.dMin / 10, L = T.tm10.length;
  for (let j = 0; j < N; j++) {   // offsets are whole 10 ms steps: each one is an index shift on the 10 ms target
    const blk = Math.min(nb - 1, Math.floor((S.t[j] - t0) / CAL.block)) * nd, base = Math.round(S.t[j] * 100) - q0, mj = S.m[j] * 100 - bias;
    for (let q = 0; q < nd; q++) {
      const k = base - q; if (k < 0 || k >= L || !T.in10[k]) continue; const y = T.tm10[k]; if (y !== y) continue;
      let e = mj - y * 100; e -= 1200 * Math.round(e / 1200); const w = 1 - e * e / k2; if (w > 0) acc[blk + q] += w;
    }
  }
  const tot = new Float64Array(nd); for (let b = 0; b < nb; b++) for (let q = 0; q < nd; q++) tot[q] += acc[b * nd + q];
  const peak = arr => { let q = 0; for (let i = 1; i < arr.length; i++) if (arr[i] > arr[q]) q = i;
    let d = CAL.dMin + q * CAL.step; if (q > 0 && q < arr.length - 1) { const a = arr[q - 1], b = arr[q], c = arr[q + 1], den = a - 2 * b + c; if (den < 0) d += CAL.step * .5 * (a - c) / den; }
    return {q, d}; };
  const p = peak(tot), med = Float64Array.from(tot).sort()[nd >> 1], top = tot[p.q];
  const contrast = top > 0 ? (top - med) / top : 0, matchedSec = top * S.hop;
  const bests = []; for (let b = 0; b < nb; b++) { const row = acc.subarray(b * nd, b * nd + nd); let s = 0; for (const v of row) s = Math.max(s, v);
    if (s * S.hop >= 1.5) bests.push(peak(row).d); }
  bests.sort((a, b) => a - b);
  const bmed = bests.length ? bests[bests.length >> 1] : NaN, mad = bests.length ? bests.map(v => Math.abs(v - bmed)).sort((a, b) => a - b)[bests.length >> 1] : NaN;
  const se = bests.length >= 2 ? 1.4826 * mad / Math.sqrt(bests.length) + CAL.step / 2 : Infinity, edge = p.q === 0 || p.q === nd - 1;
  const onsetLags = [];   // phrase starts: voice onset relative to the target onset, constant removed
  for (const on of T.onsets) {
    if (on < S.t[0] - .2 || on > S.t[N - 1]) continue;
    let lo = 0, hi = N; const from = on + p.d / 1000 - .25; while (lo < hi) { const mid = (lo + hi) >> 1; if (S.t[mid] < from) lo = mid + 1; else hi = mid; }
    for (let j = lo; j < N && S.t[j] <= on + p.d / 1000 + .8; j++) {
      const quietBefore = j === 0 || S.t[j] - S.t[j - 1] >= .15, run4 = j + 3 < N && S.t[j + 3] - S.t[j] <= 4 * S.hop + .01;
      if (quietBefore && run4) { onsetLags.push((S.t[j] - on) * 1000 - p.d); break; }
    }
  }
  onsetLags.sort((a, b) => a - b);
  const ok = !edge && matchedSec >= CAL.minSec && bests.length >= CAL.minBlocks && contrast >= CAL.minContrast && se <= CAL.maxSe;
  return {ok, residual: p.d, se, contrast, matchedSec, blocks: bests.length, bias, startedAt: run.startedAt, latency: run.latency || 0,
    implied: (run.latency || 0) + p.d / run.speed, onsetLag: onsetLags.length ? onsetLags[onsetLags.length >> 1] : null, onsets: onsetLags.length};
}
const median = a => { const s = [...a].sort((x, y) => x - y), n = s.length; return n ? (n % 2 ? s[n >> 1] : (s[n / 2 - 1] + s[n / 2]) / 2) : NaN; };
const wmedian = (xs, ws) => { const o = xs.map((x, i) => [x, ws[i]]).sort((a, b) => a[0] - b[0]), h = o.reduce((s, p) => s + p[1], 0) / 2; let c = 0; for (const [x, w] of o) { c += w; if (c >= h) return x; } return NaN; };
// The bootstrap draws from a fixed seed, so the same takes always give the same interval.
function seeded(seed = 1) { return () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function aggregate(takes, rng = seeded()) {
  const good = takes.filter(t => t.ok).sort((a, b) => (a.startedAt < b.startedAt ? -1 : 1)).slice(-CAL.recent);
  if (good.length < CAL.minTakes) return {ok: false, n: good.length};
  const m0 = median(good.map(t => t.implied)), madn = 1.4826 * median(good.map(t => Math.abs(t.implied - m0)));
  const kept = good.filter(t => Math.abs(t.implied - m0) <= Math.max(3 * madn, 60)), W = kept.map(t => 1 / (t.se * t.se + CAL.seFloor * CAL.seFloor));
  const est = wmedian(kept.map(t => t.implied), W), boots = [];
  for (let b = 0; b < 500; b++) { const xs = [], ws = []; for (let i = 0; i < kept.length; i++) { const j = Math.floor(rng() * kept.length); xs.push(kept[j].implied); ws.push(W[j]); } boots.push(wmedian(xs, ws)); }
  boots.sort((a, b) => a - b);
  const on = kept.filter(t => t.onsetLag !== null && t.onsets >= 3).map(t => t.onsetLag);
  return {ok: true, n: good.length, kept: kept.length, latency: est, ci90: [boots[25], boots[474]], madn,
    onsetLag: on.length ? median(on) : null, from: good[0].startedAt, to: good[good.length - 1].startedAt, settings: good.map(t => t.latency)};
}
window.LumaLatency = {CAL, prepareTarget, estimateTake, aggregate};
})();
