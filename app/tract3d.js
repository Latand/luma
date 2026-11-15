// The «Голова» panel: a head cut along its midline that shows how to sing what is due now (docs/design/VOCAL_TRACT_3D.md).
//
// Ported from the Chimera vocal synth (src/ui/render/head/: asset.ts, rig.ts, section.ts, scene.ts; and the airflow
// speed of src/ui/render/anatomy3d.ts), from TypeScript on three.js to plain JavaScript on WebGL2, under its licence:
//
// MIT License
//
// Copyright (c) 2026 Jameson Hodge
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
//
// What runs here: nothing of Chimera's engine. Every posture was baked by tools/gen_tract3d.ts into app/tract3d.data.js
// (window.LUMA_TRACT3D); a frame blends two of them. The lyric's words become sounds from window.LUMA_PHONES (written at
// build time by studio/phonemes.py) or, for a word missing there, from letter rules here, marked «приблизно». The sounds
// are laid on the target's notes and words, so the head shows the target only, never the microphone.
//
// LumaTract.attach(host) → panel. host: {el, song(), noteEligible(note), octave(), reduced(), dpr(), idle(), body()}.
//   panel.layout(box)      {mode: 'column' | 'overlay', w, h, crop}: the panel's size in CSS pixels
//   panel.frame(t)         draw the head for song time t (the trainer's tick calls it while the panel shows)
//   panel.song()           the song's words or notes changed
//   panel.show(on)         the panel shows or hides; hidden, it draws nothing
//   panel.state()          what the head shows now, for tests
'use strict';
(() => {
const D = window.LUMA_TRACT3D;
if (!D) return;
const SYM = new Map(D.symbols.map((s, i) => [s, i]));
const KIND = new Map(D.symbols.map((s, i) => [s, D.kinds[i]]));
const NS = D.scalars.length, NP = D.layout.reduce((s, l) => s + l[1], 0), NC = D.centreline;
const SC = Object.fromEntries(D.scalars.map((k, i) => [k, i]));
const SEG = {};
{ let o = 0; for (const [key, n] of D.layout) { SEG[key] = [o, n]; o += n; } }
const VOWELS = new Set(D.symbols.filter((s, i) => D.kinds[i] === 'vowel'));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = t => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);
function dec(b64, T) { const s = atob(b64), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return new T(u.buffer); }
function polysOf(packed, count) { const out = []; for (let i = 0; out.length < count;) { const k = packed[i++]; out.push(Array.from(packed.subarray(i, i + k))); i += k; } return out; }
// a deterministic generator (the head looks the same on every run and in every test)
function rng(seed) { let x = seed >>> 0 || 1; return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; }; }

// ── words → sounds ───────────────────────────────────────────────────────────────────────────────────────────────────
// The key a word is looked up by; studio/phonemes.py key() normalises the same way.
function key(w) { return String(w).normalize('NFC').replace(/[̀-ͯ]/g, '').replace(/[’ʼ`´]/g, "'").toLowerCase().replace(/^(?:[^\p{L}'])+|(?:[^\p{L}'])+$/gu, ''); }
const UK_VOWEL = {'а': 'a', 'е': 'ɛ', 'и': 'ɪ', 'і': 'i', 'о': 'ɔ', 'у': 'u'}, UK_IOT = {'я': 'a', 'ю': 'u', 'є': 'ɛ', 'ї': 'i'};
const UK_CONS = {'б': 'b', 'в': 'ʋ', 'г': 'ɦ', 'ґ': 'g', 'д': 'd', 'ж': 'ʒ', 'з': 'z', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'tʃ', 'ш': 'ʃ', 'щ': 'ʃ tʃ'};
const LA_DI = {sh: 'ʃ', ch: 'tʃ', th: 'θ', ng: 'ŋ', ph: 'f', ck: 'k', qu: 'k w', ee: 'i', oo: 'u'};
const LA = {a: 'a', e: 'ɛ', i: 'i', o: 'ɔ', u: 'u', y: 'ɪ', b: 'b', c: 'k', d: 'd', f: 'f', g: 'g', h: 'h', j: 'dʒ', k: 'k', l: 'l', m: 'm', n: 'n', p: 'p', q: 'k', r: 'ɹ', s: 's', t: 't', v: 'v', w: 'w', x: 'k s', z: 'z'};
// Letter rules for a word the build did not read: Cyrillic through the Ukrainian table, Latin letters to the nearest
// vowel posture and their plain consonant. Letters neither table knows are skipped.
function letterRules(w) {
  const out = [], cyr = /[Ѐ-ӿ]/.test(w);
  if (cyr) {
    let prev = '';
    for (let i = 0; i < w.length; i++) {
      const c = w[i], nx = w[i + 1] || '';
      if (c === "'") { prev = "'"; continue; }
      if (c === 'ь') { if (prev === 'c' && out.length && !out.at(-1).endsWith('ʲ')) out[out.length - 1] += 'ʲ'; continue; }
      if (UK_VOWEL[c]) { out.push(UK_VOWEL[c]); prev = 'v'; continue; }
      if (UK_IOT[c]) { if (c !== 'ї' && prev === 'c' && out.length && !out.at(-1).endsWith('ʲ')) { out[out.length - 1] += 'ʲ'; out.push(UK_IOT[c]); } else out.push('j', UK_IOT[c]); prev = 'v'; continue; }
      if (c === 'д' && nx === 'ж') { out.push('dʒ'); prev = 'c'; i++; continue; }
      if (UK_CONS[c]) { let s = UK_CONS[c]; if (c === 'в' && prev === 'v' && (!nx || UK_CONS[nx] || nx === 'ь')) s = 'w'; out.push(...s.split(' ')); prev = 'c'; }
    }
  } else {
    for (let i = 0; i < w.length; i++) {
      const di = LA_DI[w.slice(i, i + 2)];
      if (di) { out.push(...di.split(' ')); i++; continue; }
      const s = LA[w[i]];
      if (s) out.push(...s.split(' '));
    }
  }
  return out.join(' ');
}
// Legal onsets beyond one consonant (the longest wins): a stop or fricative before a liquid or a glide, s before a
// voiceless stop, a nasal or l, and s, a voiceless stop and a liquid or a glide.
const LIQ = new Set(['l', 'ɹ', 'r', 'w', 'j', 'ʋ']), OBS = new Set(['p', 'b', 't', 'd', 'k', 'g', 'f', 'v', 'θ', 'ʃ', 's', 'z', 'x', 'ɦ']);
const plain = s => s.replace('ʲ', '');
function legalOnset(cs) {
  if (cs.length <= 1) return true;
  const c = cs.map(plain);
  if (c.length === 2) return (OBS.has(c[0]) && LIQ.has(c[1])) || (c[0] === 's' && ['p', 't', 'k', 'm', 'n', 'l', 'w'].includes(c[1]));
  if (c.length === 3) return c[0] === 's' && ['p', 't', 'k'].includes(c[1]) && LIQ.has(c[2]);
  return false;
}
// "m a+ɪ" → syllables [{onset: ['m'], nucleus: ['a', 'ɪ'], coda: []}]; unknown symbols dropped (and reported)
function syllables(str) {
  const toks = String(str || '').split(/\s+/).filter(Boolean);
  let unknown = false;
  const items = [];
  for (const t of toks) {
    const parts = t.split('+'), ok = parts.every(p => SYM.has(plain(p)) && p !== 'rest');
    if (!ok) { unknown = true; continue; }
    items.push(parts.length > 1 || VOWELS.has(parts[0]) ? {v: parts.filter(p => VOWELS.has(p))} : {c: parts[0]});
  }
  const syl = [];
  let pending = [];
  for (const it of items) {
    if (it.c) { pending.push(it.c); continue; }
    if (!it.v.length) continue;
    if (!syl.length) syl.push({onset: pending, nucleus: it.v, coda: []});
    else {
      let on = 0; for (let n = pending.length; n >= 0; n--) if (legalOnset(pending.slice(pending.length - n))) { on = n; break; }
      const split = pending.length - on;
      syl.at(-1).coda.push(...pending.slice(0, split));
      syl.push({onset: pending.slice(split), nucleus: it.v, coda: []});
    }
    pending = [];
  }
  if (syl.length) syl.at(-1).coda.push(...pending);
  return {syl, unknown};
}

// ── the timeline: which sound is due at each moment of the song ─────────────────────────────────────────────────────
// docs/design/VOCAL_TRACT_3D.md §4.5 «Timing», after Chimera's sung rules (crates/chimera/src/phonetics/sing.rs): the
// vowel lands on the note, onset consonants end at its start, codas end at the next onset (or with the note before a
// rest); a word with fewer notes than syllables splits its span evenly; a diphthong holds its first vowel 80 % of the time.
// Words follow target notes beyond short recognition marks. With fewer notes than syllables, divide that
// held span. After a rest (or at the start), an onset shorter than HOLD takes its closure up earlier, out of the silence before the
// note, so it lasts long enough to be seen while the song plays: at Chimera's 55 ms an /m/ is three frames. The vowel
// still lands on the note.
const RAMP = {vowel: .15, cons: .025, rest: .3}, REST_GAP = .25, MIN_VOWEL = .4, HOLD = .18;
function timeline(song, phones, dur, eligible = () => true) {
  const notes = (song.notes || []).filter(n => !n.ignored && eligible(n)).slice().sort((a, b) => a.a - b.a);
  const words = [];
  for (const line of song.lyrics || []) for (const w of line.words || []) if (Number.isFinite(w.a) && Number.isFinite(w.b) && w.b > w.a) words.push(w);
  words.sort((a, b) => a.a - b.a);
  const segs = [], info = [];
  let reach = -Infinity;   // where the sounds laid so far end
  const durOf = s => Math.max(.07, dur(plain(s)));
  words.forEach((w, wi) => {
    const k = key(w.w);
    let str = phones && Object.prototype.hasOwnProperty.call(phones, k) ? phones[k] : null, approx = !str || (w.c ?? 1) < .5, silent = false;
    if (!str) str = letterRules(k);
    let {syl, unknown} = syllables(str);
    if (unknown) approx = true;
    if (!syl.length) { syl = [{onset: [], nucleus: ['ə'], coda: []}]; approx = true; silent = true; }
    info.push({w: w.w, key: k, approx, silent, phones: syl.map(s => [...s.onset, s.nucleus.join('+'), ...s.coda].join(' ')).join(' · ')});
    const next = words[wi + 1];
    // Recognition marks locate a word's start. Own the following target notes until the next word.
    const limit = next ? next.a : Infinity;
    const own = [];
    let end = w.a;
    for (const n of notes) {
      if (n.b <= w.a) continue;
      if (n.a >= limit) break;
      own.push(n); end = Math.min(n.b, limit);
    }
    if (!own.length) return; // target silence, including ignored notes and excluded wordless chains
    const heldStart = Math.max(w.a, own[0].a), heldEnd = end;
    let spans;
    if (own.length >= syl.length) {
      spans = syl.map((_, i) => [Math.max(own[i].a, w.a), i === syl.length - 1 ? own.at(-1).b : own[i].b]);
    } else {
      const L = (heldEnd - heldStart) / syl.length; spans = syl.map((_, i) => [heldStart + i * L, heldStart + (i + 1) * L]);
    }
    if (next) for (const sp of spans) sp[1] = Math.min(sp[1], next.a);
    syl.forEach((s, si) => {
      const [sa, sb] = spans[si]; if (sb <= sa) return;
      const base = {word: wi, approx};
      // onset: backwards from the note's start, never into the previous vowel's first 40 %
      const prevV = segs.findLast(g => g.kind === 'vowel');
      const floor = prevV ? prevV.a + MIN_VOWEL * Math.max(.05, Math.min(sa, prevV.b) - prevV.a) : -Infinity;
      let total = s.onset.reduce((q, c) => q + durOf(c), 0), scale = 1;
      if (sa - total < floor && total > 0) scale = Math.max(.25, (sa - floor) / total);
      let t = sa - total * scale;
      const free = t - (segs.length ? reach : -Infinity);
      if (total > 0 && scale === 1 && total < HOLD && free >= REST_GAP) { const add = Math.max(0, Math.min(HOLD - total, t)); scale = (total + add) / total; t -= add; }
      // a coda left on the previous syllable shares the time before this onset: it ends where the onset starts
      const lastCoda = segs.length && segs.at(-1).coda ? segs.at(-1) : null;
      if (lastCoda && lastCoda.b > t) {
        const codas = []; for (let j = segs.length - 1; j >= 0 && segs[j].coda && segs[j].syl === lastCoda.syl; j--) codas.unshift(segs[j]);
        const span = codas.reduce((q, g) => q + (g.b - g.a), 0), vow = segs.findLast(g => g.kind === 'vowel');
        let end = t, start = Math.max(end - span, vow ? vow.a + MIN_VOWEL * (vow.b - vow.a) : end - span);
        const f = (end - start) / Math.max(1e-6, span);
        for (const g of codas) { const d = (g.b - g.a) * f; g.a = start; g.b = start + d; start = g.b; }
        if (vow && codas.length) vow.b = Math.min(vow.b, codas[0].a);
      }
      // Trim before splitting on target silences: otherwise a sliver of the previous vowel can reappear inside
      // this onset after a gap, shortening the consonant and briefly restoring the old word's caption.
      if (prevV && prevV.b > t) prevV.b = Math.max(prevV.a, t);
      for (const c of s.onset) { const d = durOf(c) * scale; segs.push({sym: c, a: t, b: t + d, kind: KIND.get(plain(c)), ...base}); t += d; }
      // the nucleus to the end of the syllable, its coda at the end of the note
      const coda = s.coda.reduce((q, c) => q + durOf(c), 0), vEnd = Math.max(sa + MIN_VOWEL * (sb - sa), sb - coda);
      if (s.nucleus.length > 1) {
        const m = sa + .8 * (vEnd - sa);
        segs.push({sym: s.nucleus[0], a: sa, b: m, kind: 'vowel', ...base}, {sym: s.nucleus[1], a: m, b: vEnd, kind: 'vowel', ...base});
      } else segs.push({sym: s.nucleus[0], a: sa, b: vEnd, kind: 'vowel', ...base, silent});
      let ct = vEnd; const cf = coda > 0 ? Math.min(1, (sb - vEnd) / coda) || 1 : 1;
      for (const c of s.coda) { const d = durOf(c) * cf; segs.push({sym: c, a: ct, b: ct + d, kind: KIND.get(plain(c)), coda: true, syl: wi * 100 + si, ...base}); ct += d; }
      reach = Math.max(reach, ct, vEnd);
    });
  });
  // Keep real silences inside a melisma. Anticipated consonants keep their lead-in before a note.
  const gaps = notes.slice(1).flatMap((n, i) => n.a - notes[i].b > .04 ? [{a: notes[i].b, b: n.a}] : []);
  const voiced = segs.flatMap(g => {
    if (g.kind !== 'vowel') return [g];
    let pieces = [g];
    for (const gap of gaps) if (gap.a < g.b && gap.b > g.a) pieces = pieces.flatMap(p =>
      gap.a >= p.b || gap.b <= p.a ? [p] : [
        ...(gap.a > p.a ? [{...p, b: gap.a}] : []), ...(gap.b < p.b ? [{...p, a: gap.b}] : [])]);
    return pieces;
  });
  // Silence relaxes to rest; the final sound gets the same release as an interior gap.
  voiced.sort((p, q) => p.a - q.a);
  const out = [];
  for (const g of voiced) {
    if (g.b <= g.a) continue;
    const prev = out.at(-1);
    if (prev) {
      if (g.a < prev.b) { prev.b = Math.max(prev.a + .01, g.a); }
      else if (g.a - prev.b >= REST_GAP) out.push({sym: 'rest', a: prev.b, b: g.a, kind: 'rest', word: -1});
      else prev.b = g.a;
    }
    out.push(g);
  }
  const last = out.at(-1);
  if (last) out.push({sym: 'rest', a: last.b, b: last.b + RAMP.rest, kind: 'rest', word: -1});
  return {segs: out, words: info, notes};
}
function segAt(segs, t) { let lo = 0, hi = segs.length; while (lo < hi) { const m = (lo + hi) >> 1; if (segs[m].a <= t) lo = m + 1; else hi = m; } return lo - 1; }

// ── bodies ─────────────────────────────────────────────────────────────────────────────────────────────────────────
// Catmull–Clark, one step, as weights over the old vertices (Chimera asset.ts).
function subdivide(polys, n) {
  const keyE = (a, b) => (a < b ? a * n + b : b * n + a);
  const edges = new Map(), vertFaces = Array.from({length: n}, () => []), vertEdges = Array.from({length: n}, () => []);
  polys.forEach((p, f) => { for (let i = 0; i < p.length; i++) { const a = p[i], b = p[(i + 1) % p.length]; vertFaces[a].push(f); const k = keyE(a, b); let e = edges.get(k); if (!e) { e = {id: edges.size, a, b, faces: []}; edges.set(k, e); vertEdges[a].push(k); vertEdges[b].push(k); } e.faces.push(f); } });
  const nf = polys.length, total = n + nf + edges.size;
  const rows = Array.from({length: total}, () => new Map());
  const add = (row, i, w) => row.set(i, (row.get(i) || 0) + w), addRow = (row, from, w) => { for (const [i, x] of from) add(row, i, x * w); };
  polys.forEach((p, f) => { for (const i of p) add(rows[n + f], i, 1 / p.length); });
  for (const e of edges.values()) { const row = rows[n + nf + e.id]; if (e.faces.length === 2) { add(row, e.a, .25); add(row, e.b, .25); addRow(row, rows[n + e.faces[0]], .25); addRow(row, rows[n + e.faces[1]], .25); } else { add(row, e.a, .5); add(row, e.b, .5); } }
  for (let v = 0; v < n; v++) {
    const row = rows[v], es = vertEdges[v].map(k => edges.get(k)), border = es.filter(e => e.faces.length === 1);
    if (border.length >= 2) { add(row, v, .75); for (const e of border.slice(0, 2)) add(row, e.a === v ? e.b : e.a, .125); }
    else if (!es.length) add(row, v, 1);
    else { const m = es.length; add(row, v, (m - 3) / m); for (const f of vertFaces[v]) addRow(row, rows[n + f], 1 / (m * vertFaces[v].length)); for (const e of es) { add(row, v, 1 / (m * m)); add(row, e.a === v ? e.b : e.a, 1 / (m * m)); } }
  }
  let count = 0; for (const r of rows) count += r.size;
  const start = new Int32Array(total + 1), index = new Int32Array(count), weight = new Float32Array(count);
  let o = 0; rows.forEach((r, i) => { start[i] = o; for (const [j, w] of r) { index[o] = j; weight[o++] = w; } }); start[total] = o;
  const edge = (a, b) => n + nf + edges.get(keyE(a, b)).id;
  const quads = []; polys.forEach((p, f) => { for (let i = 0; i < p.length; i++) { const prev = p[(i + p.length - 1) % p.length], cur = p[i], next = p[(i + 1) % p.length]; quads.push([cur, edge(cur, next), n + f, edge(prev, cur)]); } });
  return {n: total, start, index, weight, quads, edge};
}
function applySub(s, src, width) { const out = new Float32Array(s.n * width); for (let i = 0; i < s.n; i++) for (let k = s.start[i]; k < s.start[i + 1]; k++) { const j = s.index[k], w = s.weight[k]; for (let c = 0; c < width; c++) out[i * width + c] += w * src[j * width + c]; } return out; }
const openLoop = (s, l) => l.flatMap((a, i) => (i + 1 < l.length ? [a, s.edge(a, l[i + 1])] : [a]));
const closedLoop = (s, l) => l.flatMap((a, i) => [a, s.edge(a, l[(i + 1) % l.length])]);
function vertexNormals(pos, idx, n) {
  const out = new Float32Array(3 * n);
  for (let t = 0; t < idx.length; t += 3) {
    const a = idx[t], b = idx[t + 1], c = idx[t + 2];
    const ux = pos[3 * b] - pos[3 * a], uy = pos[3 * b + 1] - pos[3 * a + 1], uz = pos[3 * b + 2] - pos[3 * a + 2];
    const vx = pos[3 * c] - pos[3 * a], vy = pos[3 * c + 1] - pos[3 * a + 1], vz = pos[3 * c + 2] - pos[3 * a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const i of [a, b, c]) { out[3 * i] += nx; out[3 * i + 1] += ny; out[3 * i + 2] += nz; }
  }
  for (let i = 0; i < n; i++) { const l = Math.hypot(out[3 * i], out[3 * i + 1], out[3 * i + 2]) || 1; out[3 * i] /= l; out[3 * i + 1] /= l; out[3 * i + 2] /= l; }
  return out;
}
const lin = hex => { const v = parseInt(hex.slice(1), 16); return [(v >> 16) & 255, (v >> 8) & 255, v & 255].map(c => { c /= 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; }); };
// Chimera scene.ts: the skin's colours, the lips' vermilion, warmth over cheeks, nose, ears and chin, shade in creases
const SKIN = lin('#dab09b'), LIPC = lin('#b9625f'), BLUSH = lin('#cf8674'), SHADE = lin('#9c6a5c'), MUCOSA = lin('#b4555c'), FLUSH = [1.04, .87, .84];
// a mid brown: a dark one (#3a2a21) measured 1.47:1 against the panel, and the short male hair read as a bald head
const HAIR = lin('#8a6a52');
function mottle(x, y, z) {
  const hash = (i, j, k) => { const h = Math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453; return h - Math.floor(h); };
  const ix = Math.floor(x), iy = Math.floor(y), iz = Math.floor(z), e = t => t * t * (3 - 2 * t), fx = e(x - ix), fy = e(y - iy), fz = e(z - iz);
  let v = 0; for (let c = 0; c < 8; c++) { const dx = c & 1, dy = (c >> 1) & 1, dz = c >> 2; v += hash(ix + dx, iy + dy, iz + dz) * (dx ? fx : 1 - fx) * (dy ? fy : 1 - fy) * (dz ? fz : 1 - fz); }
  return v;
}
function hollows(rest, idx, n, k) {
  const sum = new Float32Array(3 * n), count = new Uint16Array(n), normal = new Float32Array(3 * n), edge2 = new Float32Array(n);
  for (let t = 0; t < idx.length; t += 3) {
    const a = idx[t], b = idx[t + 1], c = idx[t + 2];
    const ux = rest[3 * b] - rest[3 * a], uy = rest[3 * b + 1] - rest[3 * a + 1], uz = rest[3 * b + 2] - rest[3 * a + 2], vx = rest[3 * c] - rest[3 * a], vy = rest[3 * c + 1] - rest[3 * a + 1], vz = rest[3 * c + 2] - rest[3 * a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const [i, j] of [[a, b], [b, c], [c, a]]) { normal[3 * i] += nx; normal[3 * i + 1] += ny; normal[3 * i + 2] += nz; let l2 = 0; for (let q = 0; q < 3; q++) { sum[3 * i + q] += rest[3 * j + q]; sum[3 * j + q] += rest[3 * i + q]; l2 += (rest[3 * j + q] - rest[3 * i + q]) ** 2; } edge2[i] += l2; edge2[j] += l2; count[i]++; count[j]++; }
  }
  let h = new Float32Array(n);
  for (let i = 0; i < n; i++) { if (!count[i]) continue; const nl = Math.hypot(normal[3 * i], normal[3 * i + 1], normal[3 * i + 2]) || 1; let d = 0; for (let q = 0; q < 3; q++) d += (sum[3 * i + q] / count[i] - rest[3 * i + q]) * (normal[3 * i + q] / nl); const curve = (4 * d * k) / Math.max(1e-6, edge2[i] / count[i]); h[i] = clamp((curve - .35) / 1.4, 0, 1); }
  for (let pass = 0; pass < 2; pass++) { const acc = new Float32Array(n); for (let t = 0; t < idx.length; t += 3) { const a = idx[t], b = idx[t + 1], c = idx[t + 2]; acc[a] += h[b] + h[c]; acc[b] += h[c] + h[a]; acc[c] += h[a] + h[b]; } const next = new Float32Array(n); for (let i = 0; i < n; i++) next[i] = count[i] ? .5 * h[i] + .5 * (acc[i] / count[i]) : 0; h = next; }
  for (let i = 0; i < n; i++) h[i] = .6 * Math.min(1, h[i]);
  return h;
}
let SHARED = null;   // the skin's topology, subdivided once for both bodies
function shared() {
  if (SHARED) return SHARED;
  const S = D.skin, polys = polysOf(dec(S.polys, Uint16Array), S.np), n = S.n;
  const sub = subdivide(polys, n);
  const attr = name => applySub(sub, Float32Array.from(dec(S[name], Uint8Array), v => v / 255), 1);
  const idx = new Uint32Array(sub.quads.length * 6); sub.quads.forEach((q, i) => idx.set([q[0], q[1], q[2], q[0], q[2], q[3]], i * 6));
  const line = closedLoop(sub, S.loops.lipLine), upper = attr('upper'), lower = attr('lower');
  SHARED = {sub, n: sub.n, idx, jaw: attr('jaw'), upper, lower, tint: attr('tint'), inside: attr('inside'),
    lipUpper: Int32Array.from(line.filter(i => upper[i] >= lower[i])), lipLower: Int32Array.from(line.filter(i => upper[i] < lower[i])),
    midFront: Int32Array.from(openLoop(sub, S.loops.midFront)), midBack: Int32Array.from(openLoop(sub, S.loops.midBack))};
  return SHARED;
}
const BINS = 24;
function spread(w, idx, passes) {
  const n = w.length, count = new Uint16Array(n); let cur = w;
  for (const i of idx) count[i] += 2;
  for (let p = 0; p < passes; p++) { const acc = new Float32Array(n); for (let t = 0; t < idx.length; t += 3) { const a = idx[t], b = idx[t + 1], c = idx[t + 2]; acc[a] += cur[b] + cur[c]; acc[b] += cur[c] + cur[a]; acc[c] += cur[a] + cur[b]; } const next = new Float32Array(n); for (let i = 0; i < n; i++) next[i] = count[i] ? .4 * cur[i] + .6 * (acc[i] / count[i]) : cur[i]; cur = next; }
  return cur;
}
function lipEdge(zmax, pts, az) { const n = pts.length; if (az >= zmax) return pts[n - 1]; const step = zmax / (n - 1), i = Math.min(n - 2, Math.floor(az / step)), t = az / step - i; return {x: pts[i].x + (pts[i + 1].x - pts[i].x) * t, y: pts[i].y + (pts[i + 1].y - pts[i].y) * t}; }

function makeBody(tag) {
  const B = D[tag], k = B.scale, P = D.symbols.length, sh = shared(), n = sh.n;
  const pts = dec(B.pts, Int16Array), sc = dec(B.sc, Float32Array), cl = dec(B.cl, Int16Array), ar = dec(B.ar, Uint16Array);
  const base = new Map();
  const raw = i => ({pts: Float32Array.from(pts.subarray(i * 2 * NP, (i + 1) * 2 * NP), v => v / 100), sc: Float32Array.from(sc.subarray(i * NS, (i + 1) * NS)),
    cl: Float32Array.from(cl.subarray(i * 2 * NC, (i + 1) * 2 * NC), v => v / 100), ar: Float32Array.from(ar.subarray(i * NC, (i + 1) * NC), v => v / 100)});
  // a soft consonant: the plain one with its tongue a third of the way to /j/'s (§4.5)
  const posture = id => {
    let p = base.get(id); if (p) return p;
    if (id.endsWith('ʲ')) {
      const a = posture(plain(id)), j = posture('j'); p = {pts: a.pts.slice(), sc: a.sc.slice(), cl: a.cl.slice(), ar: a.ar.slice()};
      for (const s of ['tissue:tongue', 'outline:tongue']) { const [o, m] = SEG[s]; for (let q = 2 * o; q < 2 * (o + m); q++) p.pts[q] += (j.pts[q] - p.pts[q]) / 3; }
      for (const s of ['tbX', 'tbY', 'ttX', 'ttY']) p.sc[SC[s]] += (j.sc[SC[s]] - p.sc[SC[s]]) / 3;
      for (let q = 0; q < p.cl.length; q++) p.cl[q] += (j.cl[q] - p.cl[q]) / 3;
      for (let q = 0; q < p.ar.length; q++) p.ar[q] += (j.ar[q] - p.ar[q]) / 3;
    } else p = raw(SYM.has(id) ? SYM.get(id) : SYM.get('ə'));
    p.id = id; base.set(id, p); return p;
  };
  // the skin at rest (CC0 MakeHuman base mesh at this body's size), subdivided
  const rest = applySub(sh.sub, Float32Array.from(dec(B.skin, Int16Array), v => v / 100), 3);
  // only the far half is drawn: the near half is cut away (z > 0 faces the viewer)
  const far = []; for (let t = 0; t < sh.idx.length; t += 6) { const q = sh.idx.subarray(t, t + 6); if (Math.min(rest[3 * q[0] + 2], rest[3 * q[1] + 2], rest[3 * q[2] + 2], rest[3 * q[5] + 2]) <= .05) far.push(...q); }
  const restN = vertexNormals(rest, sh.idx, n);
  // the rig's weights (Chimera rig.ts HeadRig)
  let jaw = new Float32Array(n); const lip = new Float32Array(n), movers = [];
  for (let i = 0; i < n; i++) { const yt = rest[3 * i + 1] / k, th = clamp((yt - 2.2) / 1.8, 0, 1); jaw[i] = Math.sin((Math.PI / 2) * Math.min(1, sh.jaw[i] / .84)) * th * th * (3 - 2 * th); lip[i] = Math.min(1, sh.upper[i] + sh.lower[i]); }
  jaw = spread(jaw, sh.idx, 10);
  for (let i = 0; i < n; i++) if (jaw[i] > 1e-4 || lip[i] > 0) movers.push(i);
  let corner = 0, meet = 0; for (const i of sh.lipUpper) { corner = Math.max(corner, Math.abs(rest[3 * i + 2])); meet += rest[3 * i + 1] / sh.lipUpper.length; }
  const inner = [], share = new Float32Array(n);
  for (let i = 0; i < n; i++) { if (sh.inside[i] <= 0) continue; inner.push(i); const u = sh.upper[i], l = sh.lower[i]; share[i] = u + l > .05 ? u / (u + l) : rest[3 * i + 1] >= meet ? 1 : 0; }
  // colours (Chimera scene.ts buildRig)
  const colors = new Float32Array(3 * n), hollow = hollows(rest, sh.idx, n, k), g = (a, b, c = 0) => Math.exp(-(a * a + b * b + c * c));
  for (let i = 0; i < n; i++) {
    const x = rest[3 * i] / k, y = rest[3 * i + 1] / k, z = Math.abs(rest[3 * i + 2]) / k, zs = rest[3 * i + 2] / k;
    const tt = clamp((sh.tint[i] - .3) / .5, 0, 1), lp = tt * tt * (3 - 2 * tt), inn = Math.min(1, sh.inside[i] / .4);
    const blush = Math.min(1, .62 * g((y - 11.6) / 1.7, (z - 4.3) / 1.5, (x - 4.5) / 2.6) + .5 * g((y - 11.2) / 1, z / 1, (x - 7.6) / 1.2) + .5 * g((y - 13.2) / 2.4, (z - 7.4) / .9, (x + 2.2) / 2) + .28 * g((y - 4.9) / 1, z / 1.4, (x - 7) / 1.2) + .22 * g((y - 15.3) / .8, (z - 3.1) / 1.4, (x - 6.4) / 1.5));
    const shade = Math.min(.85, .3 * g((y - 15.4) / .9, (z - 3.1) / 1.3, (x - 6.2) / 1.6) + hollow[i]);
    const flush = .65 * mottle(x / 2.3, y / 2.3, zs / 2.3) + .35 * mottle(x / .7 + 11, y / .7, zs / .7), tone = .96 + .07 * mottle(x / 4.1 + 5, y / 4.1, zs / 4.1);
    for (let c = 0; c < 3; c++) { let v = SKIN[c] * tone * (1 + (FLUSH[c] - 1) * flush * 1.3); v = v * (1 - blush) + BLUSH[c] * blush; v = v * (1 - lp) + LIPC[c] * (.92 + .16 * flush) * lp; v = v * (1 - inn) + MUCOSA[c] * inn; v = v * (1 - shade) + SHADE[c] * v * 1.6 * shade; colors[3 * i + c] = v; }
  }
  // the hair: its shell subdivided like the skin, and its midline for the band on the cut
  const H = B.hair, hsub = subdivide(polysOf(dec(H.polys, Uint16Array), H.np), H.n);
  const hidx = new Uint32Array(hsub.quads.length * 6); hsub.quads.forEach((q, i) => hidx.set([q[0], q[1], q[2], q[0], q[2], q[3]], i * 6));
  const hpos = applySub(hsub, Float32Array.from(dec(H.pos, Int16Array), v => v / 100), 3), hn = hsub.n;
  const hfar = []; for (let t = 0; t < hidx.length; t += 6) { const q = hidx.subarray(t, t + 6); if (Math.min(hpos[3 * q[0] + 2], hpos[3 * q[1] + 2], hpos[3 * q[2] + 2], hpos[3 * q[5] + 2]) <= .05) hfar.push(...q); }
  const hnrm = vertexNormals(hpos, hidx, hn), htan = new Float32Array(3 * hn);
  let crown = 0; for (let i = 1; i < hn; i++) if (hpos[3 * i + 1] > hpos[3 * crown + 1]) crown = i;
  for (let i = 0; i < hn; i++) { const d = [hpos[3 * i] - hpos[3 * crown] - .3 * k, hpos[3 * i + 1] - hpos[3 * crown + 1], hpos[3 * i + 2] - hpos[3 * crown + 2]], nn = [hnrm[3 * i], hnrm[3 * i + 1], hnrm[3 * i + 2]], dn = d[0] * nn[0] + d[1] * nn[1] + d[2] * nn[2]; const t = d.map((v, c) => v - dn * nn[c]), l = Math.hypot(...t) || 1; for (let c = 0; c < 3; c++) htan[3 * i + c] = t[c] / l; }
  // the hair's band on the cut: between the scalp (the skin's midline, which never moves there) and the hair's midline
  const hm = openLoop(hsub, H.mid), sm = openLoop(sh.sub, H.skinMid);
  const band = {outer: hm.map(i => ({x: hpos[3 * i], y: hpos[3 * i + 1]})), inner: sm.map(i => ({x: rest[3 * i], y: rest[3 * i + 1]}))};
  // the parts that keep their shape behind the cut, each vertex with its share of the jaw's turn
  const St = B.still, spos = Float32Array.from(dec(St.pos, Int16Array), v => v / 100), sidx = dec(St.idx, Uint16Array);
  const scol = new Float32Array(3 * St.n), mat = dec(St.mat, Uint8Array), mats = D.materials.map(lin);
  for (let i = 0; i < St.n; i++) scol.set(mats[mat[i]], 3 * i);
  const still = {pos: spos, nrm: vertexNormals(spos, sidx, St.n), col: scol, jaw: Float32Array.from(dec(St.jaw, Uint8Array), v => v / 255), idx: sidx};
  const nose = []; for (let i = 0; i < B.nose.length; i += 2) nose.push({x: B.nose[i], y: B.nose[i + 1]});
  const scale = id => posture(id).sc[SC.dur];
  // the skin for a posture (Chimera rig.ts pose and bared), with the jaw-turned normals of the vertices that move
  const binsU = new Float64Array(3 * (BINS + 1)), binsL = new Float64Array(3 * (BINS + 1));
  // positions and normals at rest, interleaved as the vertex buffer takes them; a pose writes over a copy of it in a buffer
  // kept for the purpose, so posing a sound allocates nothing large
  const restBuf = new Float32Array(6 * n);
  for (let i = 0; i < n; i++) { restBuf[6 * i] = rest[3 * i]; restBuf[6 * i + 1] = rest[3 * i + 1]; restBuf[6 * i + 2] = rest[3 * i + 2]; restBuf[6 * i + 3] = restN[3 * i]; restBuf[6 * i + 4] = restN[3 * i + 1]; restBuf[6 * i + 5] = restN[3 * i + 2]; }
  const poseBuf = new Float32Array(6 * n);
  function pose(p) {
    const out = poseBuf, s = p.sc, lp = lipsOf(p), zmax = s[SC.lipZ];
    out.set(restBuf);
    const wide = Math.max(s[SC.lipHalf] + .3 * k, (1.4 + 1.1 * clamp(s[SC.lipWidth], 0, 1)) * k), narrow = Math.min(1.04, wide / corner);
    const ang = s[SC.jawAngle], px = B.pivot[0], py = B.pivot[1];
    for (const i of movers) {
      let x = rest[3 * i], y = rest[3 * i + 1]; const z = rest[3 * i + 2] * (1 - lip[i] * (1 - narrow)), w = jaw[i];
      if (w > 0) { const c = Math.cos(w * ang), sn = Math.sin(w * ang), dx = x - px, dy = y - py; x = px + dx * c - dy * sn; y = py + dx * sn + dy * c; const nx = restN[3 * i], ny = restN[3 * i + 1]; out[6 * i + 3] = nx * c - ny * sn; out[6 * i + 4] = nx * sn + ny * c; }
      out[6 * i] = x; out[6 * i + 1] = y; out[6 * i + 2] = z;
    }
    const reach = corner * 1.05;
    const table = (line, weight, target, bins) => {
      bins.fill(0);
      for (const i of line) { const az = Math.abs(out[6 * i + 2]), t = lipEdge(zmax, target, az), w = Math.max(.5, weight[i]), b = Math.min(BINS, Math.round((az / reach) * BINS)); bins[3 * b] += (t.x - out[6 * i]) / w; bins[3 * b + 1] += (t.y - out[6 * i + 1]) / w; bins[3 * b + 2] += 1; }
      let last = -1;
      for (let b = 0; b <= BINS; b++) { if (!bins[3 * b + 2]) continue; bins[3 * b] /= bins[3 * b + 2]; bins[3 * b + 1] /= bins[3 * b + 2]; if (last < 0) for (let q = 0; q < b; q++) { bins[3 * q] = bins[3 * b]; bins[3 * q + 1] = bins[3 * b + 1]; } else for (let q = last + 1; q < b; q++) { const f = (q - last) / (b - last); bins[3 * q] = bins[3 * last] + (bins[3 * b] - bins[3 * last]) * f; bins[3 * q + 1] = bins[3 * last + 1] + (bins[3 * b + 1] - bins[3 * last + 1]) * f; } last = b; }
      for (let q = last + 1; q <= BINS; q++) { bins[3 * q] = bins[3 * last]; bins[3 * q + 1] = bins[3 * last + 1]; }
    };
    const bared = baredLips(lp, s, k);
    table(sh.lipUpper, sh.upper, bared.upper, binsU); table(sh.lipLower, sh.lower, bared.lower, binsL);
    for (const i of movers) {
      const u = sh.upper[i], l = sh.lower[i]; if (u === 0 && l === 0) continue;
      const f = Math.min(BINS, (Math.abs(out[6 * i + 2]) / reach) * BINS), b = Math.min(BINS - 1, Math.floor(f)), t = f - b;
      out[6 * i] += u * (binsU[3 * b] * (1 - t) + binsU[3 * b + 3] * t) + l * (binsL[3 * b] * (1 - t) + binsL[3 * b + 3] * t);
      out[6 * i + 1] += u * (binsU[3 * b + 1] * (1 - t) + binsU[3 * b + 4] * t) + l * (binsL[3 * b + 1] * (1 - t) + binsL[3 * b + 4] * t);
    }
    for (const i of inner) {
      const az = Math.abs(out[6 * i + 2]), depth = sh.inside[i], sr = share[i], eu = lipEdge(zmax, bared.upper, az), el = lipEdge(zmax, bared.lower, az), back = .85 * k * depth, away = .4 * k * depth;
      out[6 * i] = (el.x - back) * (1 - sr) + (eu.x - back) * sr; out[6 * i + 1] = (el.y - away) * (1 - sr) + (eu.y + away) * sr;
    }
    return out;
  }
  // the skin's midline for the cut (front: neck → chin → lower lip; back: upper lip → crown → neck), from a posed buffer
  const outline = buf => { const flat = ids => { const o = new Float32Array(2 * ids.length); ids.forEach((i, j) => { o[2 * j] = buf[6 * i]; o[2 * j + 1] = buf[6 * i + 1]; }); return o; }; return {front: flat(sh.midFront), back: flat(sh.midBack)}; };
  let bottom = Infinity; for (let i = 1; i < rest.length; i += 3) bottom = Math.min(bottom, rest[i]);
  return {tag, k, ph: B.pharynx, pivot: {x: B.pivot[0], y: B.pivot[1]}, jawRest: B.jawRest, jawWeights: jaw, outlineWeights: {front: Float32Array.from(sh.midFront, i => jaw[i]), back: Float32Array.from(sh.midBack, i => jaw[i])}, n, rest, bottom, far: Uint32Array.from(far), colors, posture, pose, outline, dur: scale,
    hair: {pos: hpos, nrm: hnrm, tan: htan, far: Uint32Array.from(hfar), n: hn, band}, still, nose,
    // the air comes up from the trachea where the neck is cut
    neck: Math.max(rest[3 * sh.midFront[0] + 1], rest[3 * sh.midBack[sh.midBack.length - 1] + 1]) + .2 * k};
}
function lipsOf(p) {
  const pick = s => { const [o, m] = SEG[s], out = []; for (let i = 0; i < m; i++) out.push({x: p.pts[2 * (o + i)], y: p.pts[2 * (o + i) + 1]}); return out; };
  return {upper: pick('lips:upper'), lower: pick('lips:lower')};
}
// Chimera rig.ts bared(): opened wide, the lips draw off the teeth
function baredLips(lp, s, k) {
  const {upper, lower} = lp, open = upper[0].y - lower[0].y, t = clamp((open / k - 1.1) / 1.3, 0, 1), wide = t * t * (3 - 2 * t);
  if (wide <= 0 || open <= 0) return lp;
  const lift = Math.max(0, s[SC.upTeethY] + 1.15 * k * wide - upper[0].y), drop = Math.max(0, lower[0].y - (s[SC.lowTeethY] - .45 * k * wide));
  const share = upper.map((u, i) => Math.pow(Math.max(0, (u.y - lower[i].y) / open), .6));
  return {upper: upper.map((u, i) => ({x: u.x, y: u.y + lift * share[i]})), lower: lower.map((l, i) => ({x: l.x, y: l.y - drop * share[i]}))};
}

// ── the cut face ─────────────────────────────────────────────────────────────────────────────────────────────────────
// Chimera section.ts: the midsagittal section, painted on a canvas the scene maps onto the plane of the cut. Its source
// is shared with a worker (painterSource.toString()), so the painting runs off the trainer's main thread where it can.
function painterSource() {
  // cm above the glottis (body scale): from LUMEN down the air on the cut face is painted dark, fading in over FADE, not
  // cut out (a hard edge there drew a square box over the folds)
  const LUMEN = 1.6, FADE = 1.1;
  const smooth = t => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);   // (this source runs in a worker too: nothing from outside it)
  const CUT = {skin: '#e3b59c', fat: '#efd17c', muscle: '#a04442', deep: '#8c3d3c', bone: '#efe6d2', marrow: '#e2d2b4', cartilage: '#c4dcd6', brain: '#dcbcb6', brainFold: '#b98d8a', white: '#efe3d8', cord: '#ecdcae', tongue: '#b5484e', fibre: '#c8656b', mucosa: '#d4868a', enamel: '#f6f2e8', dentine: '#e8dcc0', hollow: '#3b1517', hair: '#80604a', strand: '#a8876b'};
  function offsetIn(pts, d) { const out = []; for (let i = 0; i < pts.length; i++) { const a = pts[Math.max(0, i - 2)], b = pts[Math.min(pts.length - 1, i + 2)], tx = b.x - a.x, ty = b.y - a.y, l = Math.hypot(tx, ty) || 1; out.push({x: pts[i].x - (ty / l) * d, y: pts[i].y + (tx / l) * d}); } return out; }
  function smoothOpen(pts, per = 8) { const n = pts.length, out = []; if (n < 3) return pts; for (let i = 0; i + 1 < n; i++) { const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(n - 1, i + 2)]; for (let s = 0; s < per; s++) { const t = s / per, t2 = t * t, t3 = t2 * t; out.push({x: .5 * (2 * p1.x + (p2.x - p0.x) * t + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 + (3 * p1.x - p0.x - 3 * p2.x + p3.x) * t3), y: .5 * (2 * p1.y + (p2.y - p0.y) * t + (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 + (3 * p1.y - p0.y - 3 * p2.y + p3.y) * t3)}); } } out.push(pts[n - 1]); return out; }
  function smoothClosed(pts, per = 6) { const n = pts.length, out = []; for (let i = 0; i < n; i++) { const p0 = pts[(i + n - 1) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n]; for (let s = 0; s < per; s++) { const t = s / per, t2 = t * t, t3 = t2 * t; out.push({x: .5 * (2 * p1.x + (p2.x - p0.x) * t + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 + (3 * p1.x - p0.x - 3 * p2.x + p3.x) * t3), y: .5 * (2 * p1.y + (p2.y - p0.y) * t + (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 + (3 * p1.y - p0.y - 3 * p2.y + p3.y) * t3)}); } } return out; }
  // in: {k, ph, bounds, scale, front, back, band, air: [envelope, tube, vallecula], tissue: [...], outline: {name: pts}, glottis, pivot, angle, larynx}
  // cache: {make(w, h) → a canvas}, where the parts that never move (the brain and the skull, the spine, the nasal cavity,
  // the hard palate) are painted once per body and size and kept
  function paint(ctx0, mctx, W, H, inp, cache) {
    let ctx = ctx0;
    const {k, ph, bounds} = inp, S = inp.scale, d = inp;
    const X = x => (x - bounds.x0) * S, Y = y => (bounds.y1 - y) * S;
    const path = (c, pts, close = true) => { c.beginPath(); pts.forEach((p, i) => (i ? c.lineTo(X(p.x), Y(p.y)) : c.moveTo(X(p.x), Y(p.y)))); if (close) c.closePath(); };
    const fill = (pts, color) => { if (pts.length < 3) return; path(ctx, pts); ctx.fillStyle = color; ctx.fill('evenodd'); };
    const stroke = (pts, color, cm, close = false) => { path(ctx, pts, close); ctx.strokeStyle = color; ctx.lineWidth = cm * S; ctx.stroke(); };
    const T = (x, y) => { const xx = x > .5 ? .5 + (x - .5) * .86 : x, yy = y < 7 ? 7 - (7 - y) * ph : y; return {x: xx * k, y: yy * k}; };
    const B = (x, y) => ({x: x * k, y: (y < 7 ? 7 - (7 - y) * ph : y) * k});
    const jc = Math.cos(d.angle), js = Math.sin(d.angle);
    const J = (x, y) => { const p = T(x, y), dx = p.x - d.pivot.x, dy = p.y - d.pivot.y; return {x: d.pivot.x + dx * jc - dy * js, y: d.pivot.y + dx * js + dy * jc}; };
    const outline = name => d.outline[name] || [];
    const g = d.glottis;
    // The epiglottis comes as a straight bar of eight points: drawn and cut out of the air as a leaf, rounded at its free
    // end and bent a little back over the entrance of the larynx, so the airway beside it has no square notch.
    const epi = d.tissue.epiglottis;
    if (epi && epi.length === 8) {
      const mid = (a, b) => ({x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}), base = mid(epi[0], epi[7]), tip = mid(epi[3], epi[4]);
      const L = Math.hypot(tip.x - base.x, tip.y - base.y) || 1, t = {x: (tip.x - base.x) / L, y: (tip.y - base.y) / L};
      let n = {x: -t.y, y: t.x}; if ((epi[0].x - base.x) * n.x + (epi[0].y - base.y) * n.y < 0) n = {x: -n.x, y: -n.y};   // n: toward the back
      const half = Math.hypot(epi[0].x - epi[7].x, epi[0].y - epi[7].y) / 2, steps = [0, .14, .3, .46, .62, .78, .9, 1];
      const at = (s, side) => { const h = half * (.8 + .45 * Math.sin(Math.PI * Math.min(1, s * 1.15))) * (s > .9 ? 1 - (s - .9) * 4 : 1), b = .16 * k * s * s;
        return {x: base.x + t.x * L * s + n.x * (b + side * h), y: base.y + t.y * L * s + n.y * (b + side * h)}; };
      d.tissue.epiglottis = smoothClosed([...steps.map(s => at(s, 1)), {x: base.x + t.x * (L + .05 * k) + n.x * .16 * k, y: base.y + t.y * (L + .05 * k) + n.y * .16 * k}, ...steps.slice().reverse().map(s => at(s, -1))], 4);
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H); ctx.lineJoin = ctx.lineCap = 'round';
    const front = d.front, back = d.back, head = [...front, ...back];
    ctx.save(); path(ctx, head); ctx.clip();
    ctx.fillStyle = CUT.deep; ctx.fillRect(0, 0, W, H);
    stroke(front, CUT.muscle, 2 * 1.3 * k); stroke(back, CUT.muscle, 2 * 1.6 * k);
    if (!cache.layer || cache.key !== inp.staticKey) {
      if (!cache.layer || cache.layer.width !== W || cache.layer.height !== H) cache.layer = cache.make(W, H);
      const keep = ctx; ctx = cache.layer.getContext('2d'); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H); ctx.lineJoin = ctx.lineCap = 'round';
    const baseT = [[6.6, 15.6], [5.0, 14.6], [3.4, 14.0], [0.8, 13.4], [-2.2, 12.5], [-4.4, 11.2], [-6.4, 11.0], [-9.2, 11.6], [-12.4, 13.4]];
    const base = baseT.map(([x, y]) => B(x, y));
    const baseAt = x => { if (x >= base[0].x) return base[0].y; for (let i = 1; i < base.length; i++) if (x >= base[i].x) return base[i].y + ((base[i - 1].y - base[i].y) * (x - base[i].x)) / (base[i - 1].x - base[i].x); return base[base.length - 1].y; };
    const vault = offsetIn(back, 1.25 * k).filter(p => p.y > baseAt(p.x) + .2 * k);
    if (vault.length > 4) {
      const brain = [...vault, ...base.slice().reverse().filter(p => p.x > vault[vault.length - 1].x && p.x < vault[0].x)];
      stroke(brain, CUT.bone, 2 * .75 * k, true); fill(brain, CUT.brain);
      ctx.save(); path(ctx, brain); ctx.clip();
      let bx0 = Infinity, bx1 = -Infinity, by0 = Infinity, by1 = -Infinity;
      for (const p of brain) { bx0 = Math.min(bx0, p.x); bx1 = Math.max(bx1, p.x); by0 = Math.min(by0, p.y); by1 = Math.max(by1, p.y); }
      const Wb = bx1 - bx0, Hb = by1 - by0, Q = (u, v) => ({x: bx0 + u * Wb, y: by0 + v * Hb});
      const line = (pts, color, cm) => stroke(smoothOpen(pts.map(([u, v]) => Q(u, v))), color, cm);
      const blob = (pts, color) => fill(smoothClosed(pts.map(([u, v]) => Q(u, v))), color);
      const rim = offsetIn(vault, .12 * k); let run = 0;
      for (let q = 3; q + 3 < rim.length; q++) {
        run += Math.hypot(rim[q].x - rim[q - 1].x, rim[q].y - rim[q - 1].y); if (run < 1.15 * k) continue; run = 0;
        const a = rim[q - 2], b = rim[q + 2], tx = b.x - a.x, ty = b.y - a.y, l = Math.hypot(tx, ty) || 1, h = Math.abs(Math.sin(q * 12.9898) * 43758.5453) % 1;
        const depth = (.55 + .75 * h) * k, lean = (h - .5) * .9 * k, p0 = rim[q], p2 = {x: p0.x - (ty / l) * depth + (tx / l) * lean, y: p0.y + (tx / l) * depth + (ty / l) * lean};
        stroke(smoothOpen([p0, {x: (p0.x + p2.x) / 2 + (tx / l) * .3 * lean, y: (p0.y + p2.y) / 2 + (ty / l) * .3 * lean}, p2]), CUT.brainFold, .07 * k);
      }
      line([[.3, .5], [.33, .6], [.45, .66], [.58, .64], [.66, .55], [.64, .47]], CUT.white, .5 * k);
      line([[.34, .5], [.42, .55], [.52, .52], [.56, .44]], CUT.white, .16 * k);
      line([[.22, .52], [.28, .69], [.45, .78], [.62, .75], [.74, .6], [.73, .44]], CUT.brainFold, .07 * k);
      line([[.2, .8], [.25, .66], [.27, .54]], CUT.brainFold, .07 * k);
      line([[.06, .52], [.16, .5], [.27, .54]], CUT.brainFold, .07 * k);
      blob([[.44, .5], [.51, .52], [.55, .47], [.51, .41], [.44, .42]], CUT.white);
      stroke(smoothOpen([B(-3.3, 15.2), B(-3.5, 14.3), B(-3.2, 13.5), B(-3.6, 12.6), B(-4.2, 11.9), B(-4.6, 11.2)]), CUT.cord, 1.25 * k);
      fill(smoothClosed([B(-3.3, 14.1), B(-2.4, 13.7), B(-2.3, 12.9), B(-3.1, 12.5), B(-3.7, 13.1)]), CUT.cord);
      const cbx = B(-8.3, 0).x, cb = {x: cbx, y: baseAt(cbx) + 1.95 * k};
      const leaf = (a, r) => ({x: cb.x + Math.cos(a) * r * 2.6 * k, y: cb.y + Math.sin(a) * r * 1.75 * k});
      fill(smoothClosed([0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(q => leaf((q / 10) * 2 * Math.PI, 1))), '#d3b0ab');
      const root = leaf(.15, .82);
      for (let q = 0; q < 9; q++) { const a = .75 + (q / 8) * 4.2; stroke(smoothOpen([root, leaf(a - .25, .42), leaf(a, .9)]), CUT.white, (.2 - .008 * q) * k); for (const side of [-1, 1]) stroke([leaf(a + side * .09, .66), leaf(a + side * .2, .86)], CUT.white, .08 * k); }
      for (let q = 0; q < 16; q++) { const a = .55 + (q / 15) * 4.6; stroke([leaf(a, 1), leaf(a + .03, .8)], CUT.brainFold, .06 * k); }
      ctx.restore();
    }
    const wallX = y => -1.2 - .025 * y, lordosis = y => .35 * Math.sin(((y + 6) / 17) * Math.PI), bodyX = y => wallX(y) - 2.2 + lordosis(y);
    stroke(smoothOpen([T(bodyX(-7.5) - .75, -7.5), T(bodyX(0) - .75, 0), T(bodyX(6) - .75, 6), T(bodyX(10.4) - .7, 10.4), B(-4.6, 11.3)]), CUT.cord, .85 * k);
    for (let i = 0; i < 9; i++) {
      const y0 = -6.15 + i * 1.75, top = i === 8, x0 = bodyX(y0 + .7), h = top ? 1.55 : 1.38;
      const bodyPts = [[.04, 0], [.8, -.04], [1.56, .02], [1.5, .5 * h], [1.6, h], [.8, h + .05], [.02, h - .02], [.12, .5 * h]];
      fill(smoothClosed(bodyPts.map(([dx, dy]) => T(x0 + dx, y0 + dy))), CUT.bone);
      fill(smoothClosed(bodyPts.map(([dx, dy]) => T(x0 + .8 + (dx - .8) * .78, y0 + h / 2 + (dy - h / 2) * .76))), CUT.marrow);
      if (!top) fill(smoothClosed([[.06, h + .06], [.8, h + .12], [1.56, h + .08], [1.58, h + .32], [.8, h + .3], [.04, h + .34]].map(([dx, dy]) => T(x0 + dx, y0 + dy))), CUT.cartilage);
      const long = i <= 2 ? 1.25 : i === 7 ? 1.15 : .9;
      fill(smoothClosed([[-1.5, 1.05], [-1.9, 1.12], [-2.2 - long, .5], [-2.3 - long, .18], [-1.95, .42], [-1.55, .5]].map(([dx, dy]) => T(x0 + dx, y0 + dy))), CUT.bone);
      if (top) {
        fill(smoothClosed([[.5, h - .1], [.42, h + .75], [.72, h + 1.35], [1.06, h + .8], [1.02, h - .1]].map(([dx, dy]) => T(x0 + dx, y0 + dy))), CUT.bone);
        fill(smoothClosed([[1.3, h + .55], [1.25, h + 1.0], [1.55, h + 1.12], [1.72, h + .78], [1.58, h + .5]].map(([dx, dy]) => T(x0 + dx, y0 + dy))), CUT.bone);
        fill(smoothClosed([[-1.6, h + .9], [-2.3, h + 1.0], [-2.75, h + .75], [-2.3, h + .55], [-1.65, h + .6]].map(([dx, dy]) => T(x0 + dx, y0 + dy))), CUT.bone);
      }
    }
    const nasal = outline('nasalCavity');
    fill(smoothClosed([B(.3, 11.2), B(1.1, 10.25), B(2.7, 10.75), B(4.6, 10.85), B(6.4, 10.65), B(7.6, 10.85), B(8.3, 11.3), B(7.9, 12.3), B(6.7, 13.4), B(4.4, 13.9), B(1.8, 13.6), B(.2, 12.6)]), CUT.hollow);
    fill(smoothClosed([B(-.3, 13.3), B(.9, 13.9), B(2.0, 13.6), B(1.9, 12.7), B(.6, 12.4), B(-.3, 12.7)]), CUT.hollow);
    fill(smoothClosed([B(5.9, 15.4), B(6.5, 16.3), B(6.2, 17.2), B(5.6, 16.6), B(5.5, 15.7)]), CUT.hollow);
    fill(smoothClosed([T(-1.32, 9.0), T(-1.4, 11.3), B(.4, 12.4), B(1.5, 10.6), T(.9, 9.5), T(-.4, 9.0)]), CUT.hollow);
    for (const [cx, cy, rx, ry] of [[3.0, 11.5, 2.0, .3], [3.5, 12.45, 1.8, .28], [4.0, 13.25, 1.35, .2]]) { const c = B(cx, cy); ctx.beginPath(); ctx.ellipse(X(c.x), Y(c.y), rx * k * S, ry * k * S, .04, 0, Math.PI * 2); ctx.fillStyle = CUT.mucosa; ctx.fill(); }
    if (nasal.length > 2) stroke(nasal, CUT.mucosa, .12 * k);
    const palOral = [[1.0, 9.6], [1.8, 9.92], [2.7, 10.18], [3.6, 10.3], [4.4, 10.25], [5.1, 10.05], [5.7, 9.72], [6.15, 9.36], [6.55, 9.15], [7.0, 9.6]].map(([x, y]) => T(x, y));
    fill([...palOral, ...palOral.slice().reverse().map(p => ({x: p.x, y: p.y + .6 * k}))], CUT.bone);
    fill([T(6.55, 9.15), T(7.0, 9.6), T(7.5, 9.5), T(7.55, 8.7), T(7.2, 8.45), T(6.9, 8.6)], CUT.bone);
      ctx = keep; cache.key = inp.staticKey;
    }
    ctx.drawImage(cache.layer, 0, 0);
    fill(smoothClosed([J(6.5, 6.5), J(7.15, 6.7), J(7.5, 6.0), J(7.55, 5.2), J(7.2, 4.7), J(6.5, 4.6), J(6.15, 5.2), J(6.2, 6.0)]), CUT.bone);
    fill(smoothClosed([J(6.6, 6.1), J(7.1, 6.2), J(7.25, 5.4), J(7.0, 4.95), J(6.55, 4.95), J(6.45, 5.5)]), CUT.marrow);
    const lar = .6 * d.larynx * k, hy = {x: T(1.7, 0).x, y: T(0, 3.1).y + lar}, G = (dx, dy) => ({x: g.x + dx * k, y: g.y + dy * k});
    fill(smoothClosed([{x: hy.x - .4 * k, y: hy.y - .5 * k}, G(1.25, 1.95), G(.75, 2.0), G(.5, 2.5), {x: hy.x - .75 * k, y: hy.y + .1 * k}]), CUT.fat);
    fill(smoothClosed([{x: hy.x - .3 * k, y: hy.y + .3 * k}, {x: hy.x + .25 * k, y: hy.y + .2 * k}, {x: hy.x + .4 * k, y: hy.y - .15 * k}, {x: hy.x, y: hy.y - .32 * k}, {x: hy.x - .4 * k, y: hy.y - .1 * k}]), CUT.bone);
    // The larynx's way down: the vestibule's walls where they reach the glottis (the tube's first and last points) run on
    // without a step into the windpipe, which widens below the folds. The cartilages stand outside those walls: the
    // cricoid's plate and the arytenoid behind, the thyroid and the cricoid's arch in front, the windpipe's rings.
    const lean = dy => .045 * dy, depth = bounds.y0 / k - g.y / k, tube = d.air[1];
    const B0 = tube.length > 1 ? (tube[0].x - g.x) / k : -.74, F0 = tube.length > 1 ? (tube[tube.length - 1].x - g.x) / k : .49;
    const wall = (dy, side) => { if (dy >= 0) return side < 0 ? B0 - .03 * dy : F0 - .06 * dy; const f = smooth(Math.min(1, -dy / 1.4)); return (side < 0 ? B0 : F0) + ((.12 + side * .78 + lean(dy)) - (side < 0 ? B0 : F0)) * f; };
    const ahead = [], behind = [];
    // (from just above the glottis, inside the vestibule's dark, so the two meet without a seam)
    for (const dy of [.45, .3, .15, 0, ...Array.from({length: 14}, (_, q) => (depth * (q + 1)) / 14)]) { ahead.push(G(wall(dy, 1), dy)); behind.push(G(wall(dy, -1), dy)); }
    fill([...smoothOpen(ahead.slice().reverse(), 4), ...smoothOpen(behind, 4)], CUT.hollow);
    stroke(smoothOpen(behind.map(p => ({x: p.x - .62 * k, y: p.y})).slice(3)), CUT.hollow, .09 * k);
    // Keep this section visible over the skin's thick cut edge and the airway mask below.
    const larynxSection = () => {
      fill(smoothClosed([G(F0 + .55, 1.75), G(F0 + .95, 1.5), G(F0 + 1.22, .6), G(F0 + 1.14, -.35), G(F0 + .82, -.55), G(F0 + .84, .3), G(F0 + .72, 1.1)]), CUT.cartilage);
      fill(smoothClosed([G(wall(-.75, 1) + .2, -.7), G(wall(-.85, 1) + .62, -.85), G(wall(-1.3, 1) + .6, -1.3), G(wall(-1.4, 1) + .24, -1.42), G(wall(-1.1, 1) + .1, -1.1)]), CUT.cartilage);
      const rear = (dy, dx) => G(wall(dy, -1) + dx, dy);
      fill(smoothClosed([rear(.5, -.1), rear(.05, -.06), rear(-.6, -.06), rear(-1.25, -.08), rear(-1.55, -.3), rear(-1.45, -.62), rear(-.6, -.58), rear(.15, -.48)]), CUT.cartilage);
      fill(smoothClosed([rear(.48, -.12), rear(.85, -.08), rear(1.2, -.2), rear(.9, -.4), rear(.5, -.42)]), CUT.cartilage);
    };
    for (let q = 0; q < 6; q++) { const dy = -1.95 - q * .95; if (g.y + (dy - .6) * k < bounds.y0) break; const c = G(wall(dy - .25, 1) + .26, dy - .25); ctx.beginPath(); ctx.ellipse(X(c.x), Y(c.y), .19 * k * S, .3 * k * S, 0, 0, Math.PI * 2); ctx.fillStyle = CUT.cartilage; ctx.fill(); }
    const tongue = outline('tongue');
    if (tongue.length > 2) {
      fill(smoothClosed([J(6.0, 5.2), J(4.6, 5.0), {x: hy.x + .3 * k, y: hy.y + .25 * k}, {x: hy.x + .35 * k, y: hy.y - .3 * k}, J(4.4, 4.45), J(6.1, 4.75)]), CUT.muscle);
      fill(tongue, CUT.tongue);
      const origin = J(6.0, 5.5);
      ctx.save(); path(ctx, tongue); ctx.clip(); ctx.globalAlpha = .34;
      const dorsal = tongue.slice(2, tongue.length - 8);
      for (let i = 1; i < dorsal.length; i += 2) { const end = dorsal[i], mx = (origin.x + end.x) / 2, my = (origin.y + end.y) / 2, dx = end.x - origin.x, dy = end.y - origin.y, l = Math.hypot(dx, dy) || 1, bow = .12 * l; stroke(smoothOpen([origin, {x: mx - (dy / l) * bow, y: my + (dx / l) * bow}, {x: end.x - (dx / l) * .45 * k, y: end.y - (dy / l) * .45 * k}]), CUT.fibre, .045 * k); }
      ctx.globalAlpha = .5; stroke(offsetIn(dorsal, -.28 * k), CUT.fibre, .2 * k); ctx.globalAlpha = 1; ctx.restore();
    }
    fill(outline('velum'), CUT.mucosa);
    if (d.tissue.epiglottis) fill(d.tissue.epiglottis, CUT.cartilage);
    for (const name of ['upperTeeth', 'lowerTeeth']) { const t = outline(name); fill(t, CUT.enamel); if (t.length > 2) stroke(t, CUT.dentine, .06 * k, true); }
    stroke(front, CUT.fat, 2 * .55 * k); stroke(back, CUT.fat, 2 * .55 * k); stroke(front, CUT.skin, 2 * .2 * k); stroke(back, CUT.skin, 2 * .2 * k);
    ctx.restore();
    // the skin's edge half a millimetre past the midline: turned, the face's edge and the skin's own cut edge left cracks a
    // texel wide, through which the inside of the far half showed as dark specks
    stroke(front, CUT.skin, .1 * k); stroke(back, CUT.skin, .1 * k);
    // the hair's band on the scalp (and, long, behind the neck): its colour, with strands along it
    if (d.band && d.band.outer.length > 2) {
      const o = d.band.outer, inn = d.band.inner, poly = [...o, ...inn.slice().reverse()];
      fill(poly, CUT.hair);
      ctx.save(); path(ctx, poly); ctx.clip(); ctx.globalAlpha = .55;
      for (let q = 1; q < 6; q++) { const f = q / 6, mix = o.map((p, i) => { const r = inn[Math.round((i * (inn.length - 1)) / Math.max(1, o.length - 1))]; return {x: r.x + (p.x - r.x) * f, y: r.y + (p.y - r.y) * f}; }); stroke(smoothOpen(mix, 3), CUT.strand, .035 * k); }
      ctx.globalAlpha = 1; ctx.restore();
    }
    // the air, by the lamina's rule (the envelope, less the tissue, plus the pockets), taken out of the painting
    mctx.setTransform(1, 0, 0, 1, 0, 0); mctx.globalCompositeOperation = 'source-over'; mctx.clearRect(0, 0, W, H); mctx.fillStyle = '#fff';
    const poly = pts => { path(mctx, pts); mctx.fill('evenodd'); };
    if (d.air[0]) poly(d.air[0]);
    mctx.globalCompositeOperation = 'destination-out'; for (const t of Object.values(d.tissue)) poly(t);
    mctx.globalCompositeOperation = 'source-over'; for (const a of d.air.slice(1)) poly(a);
    // Below the entrance of the larynx nothing lies behind the cut: turned, the view through the air went out of the head
    // and showed the page. There the air stays painted, a dark lumen like the windpipe's under it.
    // It fades in over FADE from LUMEN down, so the cut-away air and the dark lumen meet without an edge.
    const low = Math.max(0, Math.min(H, Y(g.y + LUMEN * k))), full = Math.max(low, Math.min(H, Y(g.y + (LUMEN - FADE) * k)));
    mctx.globalCompositeOperation = 'source-atop'; mctx.fillStyle = CUT.hollow; mctx.fillRect(0, low, W, H - low);
    ctx.save(); path(ctx, head); ctx.clip(); ctx.shadowColor = CUT.mucosa; ctx.shadowBlur = .12 * k * S; ctx.globalCompositeOperation = 'source-atop'; ctx.drawImage(mctx.canvas, 0, 0); ctx.restore();
    const fade = mctx.createLinearGradient(0, low, 0, full + 1e-3); fade.addColorStop(0, 'rgba(0,0,0,0)'); fade.addColorStop(1, '#000');
    mctx.globalCompositeOperation = 'destination-out'; mctx.fillStyle = fade; mctx.fillRect(0, low, W, H - low); mctx.globalCompositeOperation = 'source-over';
    ctx.globalCompositeOperation = 'destination-out'; ctx.drawImage(mctx.canvas, 0, 0); ctx.globalCompositeOperation = 'source-over';
    ctx.save(); path(ctx, head); ctx.clip(); larynxSection(); ctx.restore();
    // The folds, seen on the far wall of the cut larynx: a pale band across the airway at the glottis between the thyroid
    // in front and the arytenoid behind, and the ventricular fold above it, the ventricle a dark slit between them.
    const band = (dy, top, bottom, inset) => { const up = [], down = [];
      for (let q = 0; q <= 8; q++) { const u = q / 8, mid = (B0 + F0) / 2, x = mid + ((B0 + inset) + (F0 - inset - (B0 + inset)) * u - mid) * (d.foldLength || 1), bulge = Math.sin(Math.PI * u) ** .6; up.push(G(x, dy + top * (.6 + .4 * bulge))); down.push(G(x, dy - bottom * (.6 + .4 * bulge))); }
      return smoothClosed([...up, ...down.reverse()], 3); };
    fill(band(.6, .08, .07, .02), CUT.mucosa);
    fill(band(.04, .15 * (d.foldThickness || 1), .12 * (d.foldThickness || 1), -.01), CUT.white);
  }
  return {paint, CUT};
}
const PAINTER = painterSource();
// The section's extent (body cm): the neck's cut to the crown, the nape (and the hair) to the nose
const sectionBounds = k => ({x0: -15 * k, x1: 10.5 * k, y0: -5.4 * k, y1: 25.6 * k});
// The phone's small overlay shows the mouth to the larynx (body cm, [x0, x1, y0, y1]): from the spine to past the
// nostril, from the neck's cut (or 2 cm under the glottis, where the neck runs on) to above the nasal cavity, so the
// nose's way and the soft palate stay inside and the space in front of the neck holds the body's tag (drawn in, the
// enlarge mark). A short column (tight) takes it closer, with no margin: the front of the spine to the breath in front of
// the lips, the windpipe under the folds to the nasal cavity's roof, so the mouth stands larger beside the column's words.
const cropBox = (b, tight) => tight ? [-2.1 * b.k, 9.6 * b.k, Math.max(b.bottom, -1.3 * b.k), 14.1 * b.k] : [-2.8 * b.k, 10.8 * b.k, Math.max(b.bottom, -2 * b.k), 14.4 * b.k];
// The phone's small overlay, drawn in, puts its enlarge mark in front of the neck, its top on the level under the lowest the
// lips and the breath in front of them reach in any sound (body cm × k: the male's lower lip 4.3, the female's breath 4.0;
// tests/e2e/tract3d.mjs holds the mark off them at every size), and lower where the picture leaves room under the chin.
const UNDER_LIPS = 3.4;
// The whole head's frame (the male's, for both bodies; body cm) and how many CSS pixels a centimetre of the cut takes in a
// view of w × h at the resting turn (15°): the camera below fits the frame's height, or its width turned with the head's
// depth (8 cm for the whole head, 3 for a crop), with 5 % to spare.
const WHOLE = [-13.4, 9.4, -4.6, 24.6];
function frameFit(box, depth, yawDeg = 15) { const yaw = yawDeg * Math.PI / 180; return {hh: (box[3] - box[2]) / 2, across: (box[1] - box[0]) / 2 * Math.abs(Math.cos(yaw)) + depth * Math.abs(Math.sin(yaw))}; }
const scaleIn = (f, w, h) => Math.min(h / (2 * f.hh * 1.05), w / (2 * f.across * 1.05));
const wholeScale = (w, h) => scaleIn(frameFit(WHOLE, 8), w, h);
// The input of one painting, flat (it crosses to the worker as a few typed arrays): the blended posture's points, the
// posed skin's midline, the hair's band; unpack() turns it into the polygons the painter draws.
function paintInput(body, p, front, back, scale) {
  const s = p.sc;
  for (const [points, weights] of [[front, body.outlineWeights.front], [back, body.outlineWeights.back]]) {
    for (let i = 0; i < weights.length; i++) {
      const angle = p.jawPitch * weights[i], c = Math.cos(angle), sn = Math.sin(angle), x = points[2 * i] - body.pivot.x, y = points[2 * i + 1] - body.pivot.y;
      points[2 * i] = body.pivot.x + x * c - y * sn; points[2 * i + 1] = body.pivot.y + x * sn + y * c;
    }
  }
  return {k: body.k, ph: body.ph, bounds: sectionBounds(body.k), scale, staticKey: body.tag + '|' + scale.toFixed(4), seg: SEG, pts: p.pts.slice(), front, back, band: body.hair.band,
    glottis: {x: s[SC.glottisX], y: s[SC.glottisY]}, pivot: body.pivot, angle: s[SC.jawAngle], larynx: s[SC.larynx], foldLength: p.foldLength, foldThickness: p.foldThickness};
}
function unpack(inp) {
  const pick = key => { const [o, m] = inp.seg[key], out = new Array(m); for (let i = 0; i < m; i++) out[i] = {x: inp.pts[2 * (o + i)], y: inp.pts[2 * (o + i) + 1]}; return out; };
  const pts = a => { const out = new Array(a.length / 2); for (let i = 0; i < out.length; i++) out[i] = {x: a[2 * i], y: a[2 * i + 1]}; return out; };
  return {...inp, front: pts(inp.front), back: pts(inp.back),
    air: [pick('air:envelope'), pick('air:tube'), pick('air:vallecula')],
    tissue: {tongue: pick('tissue:tongue'), epiglottis: pick('tissue:epiglottis'), upperLip: pick('tissue:upperLip'), lowerLip: pick('tissue:lowerLip'), pharynxWall: pick('tissue:pharynxWall'), uvula: pick('tissue:uvula')},
    outline: {tongue: pick('outline:tongue'), velum: pick('outline:velum'), upperTeeth: pick('outline:upperTeeth'), lowerTeeth: pick('outline:lowerTeeth'), jawBone: pick('outline:jawBone'), nasalCavity: pick('outline:nasalCavity')}};
}
// Paints in a worker when the browser lets a worker paint (OffscreenCanvas), else on the main thread.
function makePainter(onDone) {
  let worker = null, busy = false, next = null, W = 0, H = 0, seq = 0, sync = null;
  const syncCache = {make: (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }};
  try {
    if (typeof OffscreenCanvas === 'function' && typeof Worker === 'function' && new OffscreenCanvas(1, 1).getContext('2d')) {
      const src = 'const P=(' + painterSource.toString() + ')();const unpack=' + unpack.toString() + ';let c=null,m=null;const cache={make:(w,h)=>new OffscreenCanvas(w,h)};onmessage=e=>{const d=e.data;if(!c||c.width!==d.w||c.height!==d.h){c=new OffscreenCanvas(d.w,d.h);m=new OffscreenCanvas(d.w,d.h);}const t0=performance.now();P.paint(c.getContext("2d"),m.getContext("2d"),d.w,d.h,unpack(d.inp),cache);const ms=performance.now()-t0;const b=c.transferToImageBitmap();postMessage({seq:d.seq,bitmap:b,ms},[b]);};';
      const url = URL.createObjectURL(new Blob([src], {type: 'text/javascript'}));
      worker = new Worker(url); URL.revokeObjectURL(url);
      worker.onmessage = e => { busy = false; onDone(e.data.bitmap, e.data.ms, e.data.seq); if (next) { const n = next; next = null; send(n); } };
      worker.onerror = e => { e.preventDefault?.(); worker = null; busy = false; if (next) { const n = next; next = null; send(n); } };
    }
  } catch (_) { worker = null; }
  function send(job) {
    if (worker) { busy = true; worker.postMessage(job); return; }
    if (!sync || sync.c.width !== job.w || sync.c.height !== job.h) { const c = document.createElement('canvas'), m = document.createElement('canvas'); c.width = m.width = job.w; c.height = m.height = job.h; sync = {c, m, ctx: c.getContext('2d'), mctx: m.getContext('2d')}; }
    const t0 = performance.now(); PAINTER.paint(sync.ctx, sync.mctx, job.w, job.h, unpack(job.inp), syncCache); onDone(sync.c, performance.now() - t0, job.seq);
  }
  return {
    size(w, h) { W = w; H = h; },
    // one painting at a time: while one is under way the caller keeps its posture and asks again when it ends
    get busy() { return busy; },
    request(inp) { const job = {seq: ++seq, w: W, h: H, inp}; if (busy) next = job; else send(job); return seq; },
    get worker() { return !!worker; },
    close() { worker?.terminate(); worker = null; },
  };
}

// ── WebGL2 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
const VS = `#version 300 es
layout(location=0) in vec3 aPosA; layout(location=1) in vec3 aNrmA; layout(location=2) in vec3 aPosB; layout(location=3) in vec3 aNrmB;
layout(location=4) in vec3 aCol; layout(location=5) in float aJaw;
uniform mat4 uMVP; uniform float uMix; uniform vec3 uJaw;
out vec3 vN; out vec3 vT; out vec3 vCol; out vec3 vW;
void main() {
  vec3 p = mix(aPosA, aPosB, uMix), n = mix(aNrmA, aNrmB, uMix);
  float a = uJaw.z * aJaw;
  if (a != 0.0) { vec2 d = p.xy - uJaw.xy; float c = cos(a), s = sin(a); p.xy = uJaw.xy + vec2(d.x * c - d.y * s, d.x * s + d.y * c); n.xy = vec2(n.x * c - n.y * s, n.x * s + n.y * c); }
  vW = p; vN = n; vT = aNrmB; vCol = aCol; gl_Position = uMVP * vec4(p, 1.0);
}`;
const FS = `#version 300 es
precision highp float;
in vec3 vN; in vec3 vT; in vec3 vCol; in vec3 vW;
uniform vec3 uEye; uniform vec3 uKey; uniform vec3 uFill; uniform int uKind;
out vec4 o;
void main() {
  if (vW.z > 0.0) discard;
  vec3 n = normalize(vN), v = normalize(uEye - vW);
  bool inside = !gl_FrontFacing; if (inside) n = -n;
  float hemi = 0.5 + 0.5 * n.y;
  vec3 amb = mix(vec3(0.16, 0.13, 0.13), vec3(0.34, 0.34, 0.38), hemi);
  float nl = dot(n, uKey), d = max(nl, 0.0), wrap = clamp((nl + 0.32) / 1.32, 0.0, 1.0);
  vec3 diffuse = mix(wrap * vec3(0.95, 0.42, 0.32) * 0.5, vec3(d), smoothstep(0.0, 0.5, nl));
  vec3 col = vCol * (amb + diffuse * vec3(1.0, 0.95, 0.9) * 0.95 + max(dot(n, uFill), 0.0) * vec3(0.18, 0.2, 0.24));
  vec3 h = normalize(uKey + v);
  if (uKind == 1) {
    // hair: a highlight stretched along the strands (Kajiya–Kay)
    // and a light rim where the shell turns away, so its outline holds against the dark panel
    vec3 t = normalize(vT - n * dot(vT, n)); float th = dot(t, h), band = pow(sqrt(max(0.0, 1.0 - th * th)), 60.0);
    float rim = pow(1.0 - max(dot(n, v), 0.0), 2.0);
    col = vCol * (amb * 1.2 + d * 0.9 + rim * 0.45) + band * vec3(0.22, 0.18, 0.15) * d;
  } else col += pow(max(dot(n, h), 0.0), 36.0) * 0.07 * d;
  // the skin's inner side reads as the head's inside; the parts behind the cut (teeth, gums, palate, cheeks) are seen
  // from the mouth, often from behind their outer faces, and are lit on both sides
  if (inside && uKind == 0) col = vCol * vec3(0.55, 0.32, 0.32) * (0.35 + 0.4 * hemi);
  o = vec4(pow(clamp(col, 0.0, 1.0), vec3(1.0 / 2.2)), 1.0);
}`;
const QVS = `#version 300 es
layout(location=0) in vec2 aXY; uniform mat4 uMVP; uniform vec4 uBox; out vec2 vUV;
void main() { vec2 p = mix(uBox.xy, uBox.zw, aXY); vUV = vec2(aXY.x, 1.0 - aXY.y); gl_Position = uMVP * vec4(p, 0.004, 1.0); }`;
const QFS = `#version 300 es
precision mediump float; in vec2 vUV; uniform sampler2D uTex; out vec4 o;
void main() { vec4 c = texture(uTex, vUV); if (c.a < 0.02) discard; o = vec4(c.rgb * 0.97, c.a); }`;   // premultiplied, blended over the far half
const PVS = `#version 300 es
layout(location=0) in vec3 aP; uniform mat4 uMVP; out float vA;
void main() { vA = aP.z; gl_Position = uMVP * vec4(aP.xy, 0.03, 1.0); gl_PointSize = 3.0; }`;
const PFS = `#version 300 es
precision mediump float; in float vA; uniform vec3 uColor; out vec4 o;
void main() { o = vec4(uColor * vA, vA); }`;

function mat4() { return new Float32Array(16); }
function perspective(fovy, aspect, near, far) { const f = 1 / Math.tan(fovy / 2), m = mat4(); m[0] = f / aspect; m[5] = f; m[10] = (far + near) / (near - far); m[11] = -1; m[14] = (2 * far * near) / (near - far); return m; }
function lookAt(e, c, up) {
  let zx = e[0] - c[0], zy = e[1] - c[1], zz = e[2] - c[2]; let l = Math.hypot(zx, zy, zz); zx /= l; zy /= l; zz /= l;
  let xx = up[1] * zz - up[2] * zy, xy = up[2] * zx - up[0] * zz, xz = up[0] * zy - up[1] * zx; l = Math.hypot(xx, xy, xz); xx /= l; xy /= l; xz /= l;
  const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx, m = mat4();
  m[0] = xx; m[1] = yx; m[2] = zx; m[4] = xy; m[5] = yy; m[6] = zy; m[8] = xz; m[9] = yz; m[10] = zz;
  m[12] = -(xx * e[0] + xy * e[1] + xz * e[2]); m[13] = -(yx * e[0] + yy * e[1] + yz * e[2]); m[14] = -(zx * e[0] + zy * e[1] + zz * e[2]); m[15] = 1;
  return m;
}
function mul(a, b) { const o = mat4(); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]; o[i * 4 + j] = s; } return o; }

// A renderer without a GPU (SwiftShader, llvmpipe) rasterises and composites the canvas on the processor: the panel then
// draws the cut face flat; forced onto such a renderer, the head is drawn at one pixel per CSS pixel, without
// multisampling and at most 30 times a second.
function softwareGL() {
  try { const gl = document.createElement('canvas').getContext('webgl2', {antialias: false}); if (!gl) return false; const d = gl.getExtension('WEBGL_debug_renderer_info'); return /swiftshader|llvmpipe|software|softpipe/i.test(d ? gl.getParameter(d.UNMASKED_RENDERER_WEBGL) : ''); } catch (_) { return false; }
}
// The head is drawn into a multisampled framebuffer of its own and copied onto the canvas at the frame's end. Drawn into
// the canvas's own multisampled buffer (antialias: true), a desktop graphics driver (ANGLE over OpenGL ES) at times left
// out whole draws of a frame (the far half's teeth, the skin, the air's lines), and a paused head kept that frame.
function makeGL(canvas) {
  const software = softwareGL();
  const gl = canvas.getContext('webgl2', {alpha: true, antialias: false, premultipliedAlpha: true, preserveDrawingBuffer: false, powerPreference: 'low-power'});
  if (!gl) return null;
  const samples = software && window.__lumaTractGL !== 'force-ms' ? 0 : Math.min(4, gl.getParameter(gl.MAX_SAMPLES) || 0);
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS) && !gl.isContextLost()) throw Error(gl.getShaderInfoLog(s)); return s; };
  const prog = (v, f) => { const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, v)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, f)); gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS) && !gl.isContextLost()) throw Error(gl.getProgramInfoLog(p)); const u = {}; for (let i = 0, n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i < n; i++) { const a = gl.getActiveUniform(p, i); u[a.name] = gl.getUniformLocation(p, a.name); } return {p, u}; };
  const mesh = prog(VS, FS), quad = prog(QVS, QFS), pts = prog(PVS, PFS);
  const buf = (data, target = gl.ARRAY_BUFFER, usage = gl.STATIC_DRAW) => { const b = gl.createBuffer(); gl.bindBuffer(target, b); gl.bufferData(target, data, usage); return b; };
  const quadBuf = buf(new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]));
  const partBuf = buf(new Float32Array(6 * 240), gl.ARRAY_BUFFER, gl.DYNAMIC_DRAW);
  const tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
  for (const [p, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, p, v);
  return {gl, mesh, quad, pts, buf, quadBuf, partBuf, tex, texReady: false, body: null, software, samples, ms: null};
}
// the multisampled colour and depth the head is drawn into, at the canvas's size (none without multisampling, where it
// is drawn straight onto the canvas)
function target(G, w, h) {
  const {gl} = G;
  if (!G.samples) return null;
  if (G.ms && G.ms.w === w && G.ms.h === h) return G.ms;
  if (G.ms) { gl.deleteFramebuffer(G.ms.fb); gl.deleteRenderbuffer(G.ms.color); gl.deleteRenderbuffer(G.ms.depth); G.ms = null; }
  const fb = gl.createFramebuffer(), color = gl.createRenderbuffer(), depth = gl.createRenderbuffer();
  gl.bindRenderbuffer(gl.RENDERBUFFER, color); gl.renderbufferStorageMultisample(gl.RENDERBUFFER, G.samples, gl.RGBA8, w, h);
  gl.bindRenderbuffer(gl.RENDERBUFFER, depth); gl.renderbufferStorageMultisample(gl.RENDERBUFFER, G.samples, gl.DEPTH_COMPONENT24, w, h);
  gl.bindFramebuffer(gl.FRAMEBUFFER, fb); gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.RENDERBUFFER, color); gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, depth);
  const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  if (!ok) { gl.deleteFramebuffer(fb); gl.deleteRenderbuffer(color); gl.deleteRenderbuffer(depth); G.samples = 0; return null; }
  return (G.ms = {fb, color, depth, w, h});
}
// what one body needs on the GPU: the skin's colours and far-half triangles, the hair, the parts behind the cut
function uploadBody(G, body) {
  const {gl, buf} = G;
  if (G.body) gl.deleteBuffer(G.body.skinJaw);
  const interleave = (pos, nrm, n) => { const b = new Float32Array(6 * n); for (let i = 0; i < n; i++) { b.set(pos.subarray(3 * i, 3 * i + 3), 6 * i); b.set(nrm.subarray(3 * i, 3 * i + 3), 6 * i + 3); } return b; };
  const h = body.hair, hc = new Float32Array(3 * h.n); for (let i = 0; i < h.n; i++) hc.set(HAIR, 3 * i);
  G.body = {tag: body.tag, skinCol: buf(body.colors), skinJaw: buf(body.jawWeights), skinIdx: buf(body.far, gl.ELEMENT_ARRAY_BUFFER), skinCount: body.far.length,
    hair: buf(interleave(h.pos, h.nrm, h.n)), hairTan: buf(h.tan), hairCol: buf(hc), hairIdx: buf(h.far, gl.ELEMENT_ARRAY_BUFFER), hairCount: h.far.length,
    still: buf(interleave(body.still.pos, body.still.nrm, body.still.pos.length / 3)), stillCol: buf(body.still.col), stillJaw: buf(body.still.jaw), stillIdx: buf(body.still.idx, gl.ELEMENT_ARRAY_BUFFER), stillCount: body.still.idx.length,
    keys: new Map()};
}
// a posed skin on the GPU: at most eight, the oldest out
// (an evicted keyframe's buffer is written over in place for the next one)
function skinKey(G, body, id, make) {
  const keys = G.body.keys; let e = keys.get(id);
  if (e) { keys.delete(id); keys.set(id, e); return e; }
  const {gl} = G, data = make();
  if (keys.size >= 8) { const [old, v] = keys.entries().next().value; keys.delete(old); gl.bindBuffer(gl.ARRAY_BUFFER, v.buf); gl.bufferSubData(gl.ARRAY_BUFFER, 0, data); e = {buf: v.buf, id}; }
  else e = {buf: G.buf(data, gl.ARRAY_BUFFER, gl.DYNAMIC_DRAW), id};
  keys.set(id, e); return e;
}

// ── airflow ──────────────────────────────────────────────────────────────────────────────────────────────────────────
// The path from the trachea at the neck's cut through the glottis, the airway's centreline and out at the lips; or,
// with the soft palate lowered for a nasal, up behind it, through the nose and out of the nostril. The speed is main's
// perceptual one (Chimera anatomy3d.ts drawParticles: 2.2 · ln(1 + |U/A| / 30) cm/s) for a fixed teaching flow U.
const FLOW = {voiced: 650, voiceless: 1300, nasal: 600, closed: 25, shut: 0, rest: 0};
const PATH_MAX = 48;
function newPath() { return {x: new Float32Array(PATH_MAX), y: new Float32Array(PATH_MAX), a: new Float32Array(PATH_MAX), L: new Float32Array(PATH_MAX), n: 0, len: 0}; }
function airPath(body, p, nasal, path) {
  const k = body.k, s = p.sc, gx = s[SC.glottisX], gy = s[SC.glottisY];
  let n = 0; const put = (x, y, a) => { path.x[n] = x; path.y[n] = y; path.a[n] = a; n++; };
  put(gx + .12 * k + .045 * (body.neck - gy), body.neck, 2.2 * k * k); put(gx + .12 * k, gy - 1.4 * k, 2.0 * k * k);
  if (!nasal) {
    for (let i = 0; i < NC; i++) put(p.cl[2 * i], p.cl[2 * i + 1], p.ar[i]);
    const ax = p.cl[2 * NC - 4], ay = p.cl[2 * NC - 3], bx = p.cl[2 * NC - 2], by = p.cl[2 * NC - 1], dx = bx - ax, dy = by - ay, l = Math.hypot(dx, dy) || 1;
    put(bx + (dx / l) * 1.2 * k, by + (dy / l) * 1.2 * k, 3); put(bx + (dx / l) * 3 * k, by + (dy / l) * 3 * k - .4 * k, 6);
  } else {
    // up the pharynx to the soft palate's level, then the nose
    for (let i = 0; i < NC; i++) { if (p.cl[2 * i + 1] > body.nose[0].y - .3 * k) break; put(p.cl[2 * i], p.cl[2 * i + 1], p.ar[i]); }
    for (const q of body.nose) put(q.x, q.y, .6 * k * k);
  }
  path.n = n; path.L[0] = 0;
  for (let i = 1; i < n; i++) path.L[i] = path.L[i - 1] + Math.hypot(path.x[i] - path.x[i - 1], path.y[i] - path.y[i - 1]);
  path.len = path.L[n - 1];
  // where the air leaves the head, as an arc length: the lips (the centreline's last point) or the nostril
  path.exit = nasal ? path.L[n - 2] : path.L[1 + NC];
  // where the mouth's way is narrowest (a closure: the tongue's tip on the ridge, the lips together), as an arc length
  path.stop = path.len;
  if (!nasal) { let m = 2; for (let i = 3; i < 2 + NC; i++) if (path.a[i] < path.a[m]) m = i; path.stop = path.L[m]; }
  return path;
}
const speed = (U, a, k) => 2.2 * Math.log1p(U / Math.max(.05, a) / 30) * k;
// the time the air takes from the windpipe to each point of the path (into tau when given), and to its end
function transit(path, U, k, tau) {
  let s = 0; if (tau) tau[0] = 0;
  for (let i = 1; i < path.n; i++) { s += (path.L[i] - path.L[i - 1]) / Math.max(1e-4, speed(U, (path.a[i - 1] + path.a[i]) / 2, k)); if (tau) tau[i] = s; }
  return s;
}
// a time taken from the windpipe → the arc length reached by then (piecewise linear over the path's points)
function arcAt(path, tau, s) { let i = 1; while (i < path.n - 1 && tau[i] < s) i++; const f = clamp((s - tau[i - 1]) / Math.max(1e-9, tau[i] - tau[i - 1]), 0, 1); return path.L[i - 1] + (path.L[i] - path.L[i - 1]) * f; }
function along(path, u, o) {
  const {x, y, a, L, n} = path; let i = 1; while (i < n - 1 && L[i] < u) i++;
  const t = clamp((u - L[i - 1]) / Math.max(1e-6, L[i] - L[i - 1]), 0, 1), dx = x[i] - x[i - 1], dy = y[i] - y[i - 1], l = Math.hypot(dx, dy) || 1;
  o.x = x[i - 1] + dx * t; o.y = y[i - 1] + dy * t; o.nx = -dy / l; o.ny = dx / l; o.a = a[i - 1] + (a[i] - a[i - 1]) * t;
  return o;
}

// ── the panel ────────────────────────────────────────────────────────────────────────────────────────────────────────
const LABEL = {male: 'Чоловік', female: 'Жінка'};
function attach(host) {
  const el = host.el, view = el.querySelector('.tract-view'), glc = el.querySelector('canvas.tract-gl'), c2d = el.querySelector('canvas.tract-2d'), sound = el.querySelector('.tract-sound');
  const st = {box: null, shown: false, bodies: {}, G: null, glFailed: false, lost: false, tl: null, tlKey: '', tex: {w: 0, h: 0}, painted: null, paintMs: 0, paintN: 0,
    bitmap: null, yaw: 15, pitch: 4, frames: 0, workMs: [], hz: 60, drawnAt: -Infinity, parts: null, lastT: null, cur: null, drag: null};
  const painter = makePainter((bmp, ms, seq) => {
    st.paintMs = ms; st.paintN++;
    if (st.bitmap && st.bitmap !== bmp && st.bitmap.close) st.bitmap.close();
    st.bitmap = bmp; st.fresh = true;
    if (!st.moving) requestAnimationFrame(() => { if (st.shown && !document.hidden) render(); });
  });
  c2d.hidden = true;
  glc.addEventListener('webglcontextlost', e => { e.preventDefault(); st.lost = true; st.G = null; glc.hidden = true; c2d.hidden = false; render(); });

  // A body is built once, off the first paint: the shared topology's subdivision in one idle slice, the body in the next
  // (each some tens of milliseconds); until then the panel draws nothing.
  function body() {
    const tag = host.body(); if (tag !== 'male' && tag !== 'female') return null;
    if (st.bodies[tag]) return st.bodies[tag];
    if (!st.building) {
      st.building = tag;
      const idle = f => (window.requestIdleCallback ? requestIdleCallback(f, {timeout: 300}) : setTimeout(f, 30));
      const t0 = performance.now(); let work = 0;
      idle(() => { const a = performance.now(); shared(); work += performance.now() - a;
        idle(() => { const a = performance.now(); st.bodies[tag] = makeBody(tag); work += performance.now() - a; st.buildMs = work; st.buildWall = performance.now() - t0; st.building = null;
          if (st.shown && !document.hidden) requestAnimationFrame(() => { if (st.shown) render(); }); }); });
    }
    return null;
  }
  // WebGL2 on a graphics processor draws the solid half-head. Without WebGL2, after a lost context, and on a renderer
  // that rasterises on the processor (SwiftShader, llvmpipe: its threads took frames from the roll under load), the panel
  // draws the cut face flat. (window.__lumaTractGL = 'force' keeps WebGL2 on such a renderer, and 'force-ms' its
  // multisampled framebuffer too: the tests' ways to reach them.)
  function ensureGL(b) {
    if (st.glFailed || st.lost) return null;
    if (!st.G) {
      if (!/^force/.test(window.__lumaTractGL || '') && softwareGL()) st.software = true;
      else try { st.G = makeGL(glc); } catch (_) { st.G = null; }
      if (!st.G) { st.glFailed = true; glc.hidden = true; c2d.hidden = false; return null; }
    }
    if (st.G.body?.tag !== b.tag) { if (st.G.body) for (const v of st.G.body.keys.values()) st.G.gl.deleteBuffer(v.buf); uploadBody(st.G, b); st.G.texReady = false; }
    return st.G;
  }
  function tl(b) {
    const song = host.song(), sig = b.tag + '|' + (song.lyrics?.length || 0) + '|' + (song.notes?.length || 0) + '|' + (song.notes?.[0]?.a ?? '') + '|' + st.songRev;
    if (st.tl && st.tlKey === sig) return st.tl;
    st.tl = timeline(song, window.LUMA_PHONES?.words || null, s => b.posture(s).sc[SC.dur], host.noteEligible); st.tlKey = sig; return st.tl;
  }
  // The posture due at t: ease in from the preceding sound, completing before the next sound starts.
  function postureAt(b, t) {
    const T = tl(b), i = segAt(T.segs, t), g = i >= 0 && t < T.segs[i].b ? T.segs[i] : null;
    if (!g) return {a: 'rest', b: 'rest', w: 0, seg: null, info: null};
    const prev = i > 0 && Math.abs(T.segs[i - 1].b - g.a) < 1e-6 ? T.segs[i - 1] : null;
    const ramp = Math.min(g.b - g.a, g.kind === 'rest' ? RAMP.rest : g.kind === 'vowel' ? RAMP.vowel : RAMP.cons);
    const from = prev ? prev.sym : 'rest', f = clamp((t - g.a) / ramp, 0, 1), w = .5 - .5 * Math.cos(Math.PI * f);
    return {a: f >= 1 ? g.sym : from, b: g.sym, w: f >= 1 ? 0 : w, seg: g, idx: i, info: g.word >= 0 ? T.words[g.word] : null};
  }
  // a keyframe of the skin: posed on first use, its GPU buffer kept among the last eight, its midline among the last 64
  const outlines = new Map();
  function keyframe(b, G, id) {
    const okey = b.tag + '|' + id; let outline = outlines.get(okey), posed = null;
    const make = () => (posed ??= b.pose(b.posture(id)));
    const e = G ? skinKey(G, b, id, make) : null;
    if (!outline) { outline = b.outline(make()); outlines.set(okey, outline); if (outlines.size > 64) outlines.delete(outlines.keys().next().value); }
    return {e, outline};
  }
  const pending = new Set();
  function ahead(b, G, id) {
    if (G.body.keys.has(id) || pending.has(id)) return;
    pending.add(id);
    const go = () => { pending.delete(id); if (st.shown && st.G === G && G.body?.tag === b.tag) keyframe(b, G, id); };
    if (window.requestIdleCallback) requestIdleCallback(go, {timeout: 250}); else setTimeout(go, 16);
  }
  // the blend of two postures, into arrays kept for it (a frame allocates nothing here)
  const mixed = {pts: new Float32Array(2 * NP), sc: new Float32Array(NS), cl: new Float32Array(2 * NC), ar: new Float32Array(NC)};
  function blended(b, q) {
    const A = b.posture(q.a), Bp = b.posture(q.b), w = q.a === q.b ? 0 : q.w;
    for (const key of ['pts', 'sc', 'cl', 'ar']) { const x = A[key], y = Bp[key], o = mixed[key]; for (let i = 0; i < o.length; i++) o[i] = x[i] + (y[i] - x[i]) * w; }
    return mixed;
  }
  // A playhead-time envelope, independent of draw order, pauses and frame rate. Notes are indexed once with tl().
  function pitchAt(b, t) {
    const notes = tl(b).notes, i = segAt(notes, t), n = notes[i];
    if (!n) return .5;
    const lo = b.tag === 'female' ? 57 : 48, norm = m => clamp((m + (host.octave?.() || 0) - lo) / 16, 0, 1);
    const released = (note, time) => .5 + (norm(note.m) - .5) * (1 - smooth((time - note.b) / RAMP.rest));
    if (t >= n.b) return notes[i + 1] && notes[i + 1].a - n.b <= .04 ? norm(n.m) : released(n, t);
    const prev = notes[i - 1], f = smooth((t - n.a) / Math.min(.15, n.b - n.a));
    const from = prev ? (n.a - prev.b <= .04 ? norm(prev.m) : released(prev, n.a)) : .5;
    return from + (norm(n.m) - from) * f;
  }
  function tune(b, p, q, t) {
    // Release pitch through silence independently of the sound: an anticipated consonant can begin in that silence.
    const pitch = pitchAt(b, t);
    const lift = (pitch - .5) * 1.4 * b.k;
    const gy = p.sc[SC.glottisY];
    // Move the glottis and neighbouring tube/tissue continuously, tapering to the stationary upper pharynx.
    for (const key of ['pts', 'cl']) for (let i = 1; i < p[key].length; i += 2) {
      const y = p[key][i], weight = clamp(1 - Math.abs(y - gy) / (5 * b.k), 0, 1);
      p[key][i] += lift * weight;
    }
    p.sc[SC.glottisY] += lift;
    p.sc[SC.larynx] += lift / (.6 * b.k);
    const vowel = (VOWELS.has(plain(q.a)) ? 1 - q.w : 0) + (VOWELS.has(plain(q.b)) ? q.w : 0);
    p.jawPitch = -.035 * pitch * vowel;
    p.sc[SC.jaw] += .08 * pitch * vowel; p.sc[SC.jawAngle] += p.jawPitch;
    // The lower mouth follows the extra jaw angle, on the cut as well as on the skin's existing jaw rig.
    const c = Math.cos(p.jawPitch), sn = Math.sin(p.jawPitch);
    for (const key of ['lips:lower', 'tissue:lowerLip', 'outline:lowerTeeth', 'outline:jawBone']) {
      const [offset, count] = SEG[key];
      for (let i = offset; i < offset + count; i++) { const dx = p.pts[2 * i] - b.pivot.x, dy = p.pts[2 * i + 1] - b.pivot.y;
        p.pts[2 * i] = b.pivot.x + dx * c - dy * sn; p.pts[2 * i + 1] = b.pivot.y + dx * sn + dy * c; }
    }
    const tx = p.sc[SC.lowTeethX] - b.pivot.x, ty = p.sc[SC.lowTeethY] - b.pivot.y;
    p.sc[SC.lowTeethX] = b.pivot.x + tx * c - ty * sn; p.sc[SC.lowTeethY] = b.pivot.y + tx * sn + ty * c;
    p.pitch = pitch; p.foldLength = 1 + .25 * (pitch - .5); p.foldThickness = 1 - .5 * (pitch - .5);
    return p;
  }
  function airState(q, p) {
    const g = q.seg; if (!g || g.kind === 'rest') return 'rest';
    const k = g.kind, s = plain(g.sym), ab = p.sc[SC.abduction];
    if (k === 'vowel' || k === 'approximant' || k === 'lateral' || k === 'trill') return 'voiced';
    if (k === 'nasal') return 'nasal';
    if (k === 'stop') return 'closed';
    // an affricate closes first and then hisses
    if (k === 'affricate') return (q.tIn ?? 0) < .5 ? 'closed' : ab >= .2 ? 'voiceless' : 'voiced';
    if (k === 'glottal') return s === 'ʔ' ? 'shut' : s === 'h' ? 'voiceless' : 'voiced';
    if (k === 'fricative') return ab >= .2 ? 'voiceless' : 'voiced';
    return 'voiced';
  }
  // the camera: a side view turned toward the face; the whole head fills the view (one frame for both bodies, the male's:
  // the female head stands 10 % smaller in it, as Chimera sizes them), or, in the phone's small overlay, each body's own
  // crop from the mouth to the larynx (cropBox)
  function camera(b, w, h) {
    const k = 1, crop = st.box?.crop, yaw = st.yaw * Math.PI / 180, pitch = st.pitch * Math.PI / 180;
    const box = crop ? cropBox(b, st.box.tight) : WHOLE;
    const cx = (box[0] + box[1]) / 2 * k, cy = (box[2] + box[3]) / 2 * k, hw = (box[1] - box[0]) / 2 * k, hh = (box[3] - box[2]) / 2 * k;
    const fov = 26 * Math.PI / 180, half = Math.tan(fov / 2), aspect = w / h;
    // turned, the head shows its depth: its width on screen is the box's width and the head's depth (±8 cm) mixed
    const across = hw * Math.abs(Math.cos(yaw)) + (crop ? 3 : 8) * k * Math.abs(Math.sin(yaw)), m = crop && st.box.tight ? 1 : 1.05;
    const dist = Math.max(hh / half, across / (half * aspect)) * m;
    // a crop in a view wider than itself keeps the face at the view's right edge and shows more of the neck behind it
    const extra = crop ? Math.max(0, dist * half * aspect - across * m) : 0;
    // the phone's small overlay stands its crop on the view's bottom (the neck runs on below it): the room a view taller
    // than the crop leaves goes above the head, in front of the forehead, where the enlarge mark stands (placeMark())
    const rise = crop && !st.box.tight ? Math.max(0, dist * half - hh) : 0;
    const dir = [Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch)];
    const target = [cx - extra * Math.cos(yaw), cy + rise, extra * Math.sin(yaw)], eye = [target[0] + dir[0] * dist, target[1] + dir[1] * dist, target[2] + dir[2] * dist];
    const v = lookAt(eye, target, [0, 1, 0]), pr = perspective(fov, aspect, Math.max(1, dist - 40 * k), dist + 40 * k);
    // the key light rides with the camera, from above its shoulder toward the face; a cool fill from below the other side
    const right = [Math.cos(yaw), 0, -Math.sin(yaw)], up = [0, 1, 0], nrm = a => { const l = Math.hypot(...a); return a.map(x => x / l); };
    const key = nrm(dir.map((d, i) => d * .8 + up[i] * .55 + right[i] * .35)), fill = nrm(dir.map((d, i) => d * .5 - up[i] * .3 - right[i] * .6));
    return {mvp: mul(pr, v), eye, key, fill, v, pr};
  }

  // The streaks of air. Particle i stands at a share of the time the air takes from the windpipe out of the head: its
  // own offset (i/n, a little shaken) plus one clock that runs at the flow's pace. The shares lie evenly over that time,
  // so the streaks crowd where the air runs slowly and thin out where it runs fast, and as many stand in front of the
  // mouth at a held note's end as at its start. How fast the air runs along the way is the voiced flow's; another flow on
  // the mouth's way (a hiss, a closure) changes only how fast the clock runs and moves no streak, while a turn between
  // the mouth's way and the nose's puts each streak at its share of the other way. Each time a particle leaves the head
  // it comes in again at the windpipe at a new place across it.
  function particles(n) { const r = rng(7919), out = []; for (let i = 0; i < n; i++) out.push({off: (i + .8 * (r() - .5)) / n, u: 0, v: 0, lap: NaN}); return out; }
  // the streaks, into a kept buffer as the GPU takes them: per particle its tail and its head, each x, y, alpha
  const airBuf = new Float32Array(6 * 120), path = newPath(), at = {}, tail = {}, tau = new Float32Array(PATH_MAX);
  function stepAir(b, p, air, dt, reduced) {
    const n = (st.box?.w || 300) < 260 ? 60 : 120, U = FLOW[air] ?? 0, k = b.k;
    if (!st.parts || st.parts.length !== n) st.parts = particles(n);
    airPath(b, p, air === 'nasal', path);
    const T = transit(path, FLOW.voiced, k, tau);
    if (!reduced && dt > 0 && U > 0) st.clock = (st.clock || 0) + dt / (U === FLOW.voiced ? T : transit(path, U, k, null));
    let m = 0, out = 0, i = 0;
    for (const q of st.parts) {
      const share = q.off + (st.clock || 0), lap = Math.floor(share);
      if (lap !== q.lap) { const h = Math.sin(i * 12.9898 + lap * 78.233) * 43758.5453; q.lap = lap; q.v = 2 * (h - Math.floor(h)) - 1; }
      i++;
      q.u = share - lap; const u = arcAt(path, tau, q.u * T);
      if (U <= 0 && air !== 'closed') continue;
      // while a closure holds no air passes it: what is beyond it is not drawn
      if (air === 'closed' && u > path.stop) continue;
      along(path, u, at); const half = .42 * Math.sqrt(Math.max(.05, at.a)) * .8, len = Math.min(.9 * k, .12 * k + (U > 0 ? .0006 * U * k : 0));
      along(path, Math.max(0, u - len), tail);
      // it fades in where the windpipe is cut and out over the last centimetre of the breath in front of the face
      const alpha = smooth(u / (.5 * k)) * smooth((path.len - u) / (1.2 * k)) * (air === 'closed' ? .35 : .8);
      if (u > path.exit && alpha > .1) out++;
      airBuf[m++] = tail.x + tail.nx * half * q.v; airBuf[m++] = tail.y + tail.ny * half * q.v; airBuf[m++] = alpha;
      airBuf[m++] = at.x + at.nx * half * q.v; airBuf[m++] = at.y + at.ny * half * q.v; airBuf[m++] = alpha;
    }
    st.airOut = out;
    return m;
  }

  function render(t = host.now ? host.now() : st.lastT ?? 0) {
    const b = body();
    if (!b || !st.shown || !st.box || document.hidden) return;
    st.frames++;
    const t0 = performance.now(), q = postureAt(b, t), p = tune(b, blended(b, q), q, t), reduced = host.reduced();
    if (q.seg) q.tIn = (t - q.seg.a) / Math.max(1e-6, q.seg.b - q.seg.a);
    const air = airState(q, p);
    st.cur = {q, p, air};
    const dt = st.lastT === null ? 0 : clamp(t - st.lastT, 0, .1); st.lastT = t;
    const lines = stepAir(b, p, air, st.moving ? dt : 0, reduced);   // floats in airBuf
    st.lines = lines;
    // the cut face: painted again when a point has moved more than 0.2 mm since the last painting, or the body changed
    const G = ensureGL(b), dpr = G?.software ? 1 : host.dpr(), w = Math.max(1, Math.round(st.box.w * dpr)), h = Math.max(1, Math.round(st.box.h * dpr));
    const sb = sectionBounds(b.k), texH = clamp(Math.round(h * 1.15 / 64) * 64, 384, 1024), texW = Math.round(texH * (sb.x1 - sb.x0) / (sb.y1 - sb.y0));
    if (st.tex.w !== texW || st.tex.h !== texH || st.tex.body !== b.tag) { st.tex = {w: texW, h: texH, body: b.tag}; painter.size(texW, texH); st.painted = null; }
    let moved = !st.painted || st.painted.body !== b.tag || Math.abs((st.painted.pitch ?? .5) - p.pitch) > .01;
    if (!moved) { const a = st.painted.pts, c = p.pts; for (let i = 0; i < c.length; i++) if (Math.abs(a[i] - c[i]) > .02) { moved = true; break; } }
    // (while a painting is under way the next waits: the frame after it ends asks again with the posture of that frame)
    st.paintWaiting = moved && painter.busy;
    if (st.paintWaiting) moved = false;
    // the skin: each keyframe posed once (its buffer on the GPU, eight at most; its midline kept here) and blended
    const ka = keyframe(b, G, q.a), kb = q.w > 0 && q.b !== q.a ? keyframe(b, G, q.b) : ka; st.cur.outline = ka.outline;
    if (moved) {
      const oa = ka.outline, ob = kb.outline, w2 = kb === ka ? 0 : q.w, mixP = (u, v) => { const o = new Float32Array(u.length); for (let i = 0; i < u.length; i++) o[i] = u[i] + (v[i] - u[i]) * w2; return o; };
      painter.request(paintInput(b, p, w2 ? mixP(oa.front, ob.front) : oa.front.slice(), w2 ? mixP(oa.back, ob.back) : oa.back.slice(), texH / (sb.y1 - sb.y0)));
      if (!st.painted || st.painted.body !== b.tag) st.painted = {body: b.tag, pts: new Float32Array(2 * NP)};
      st.painted.pts.set(p.pts); st.painted.pitch = p.pitch; st.paintWaiting = false;
    }
    if (G) {
      drawGL(G, b, q, p, lines, ka, kb, w, h);
      // the next two sounds' skins are posed ahead, in idle time, so a frame seldom poses one itself
      const T = st.tl, from = q.idx ?? segAt(T.segs, t);
      for (let j = from + 1; j <= from + 2 && j < T.segs.length; j++) if (j >= 0) ahead(b, G, T.segs[j].sym);
    } else draw2D(b, p, lines, w, h);
    placeMark(b);
    const cap = caption(q); if (cap !== st.caption) { st.caption = cap; sound.textContent = cap; }
    const ms = performance.now() - t0; st.workMs.push(ms); if (st.workMs.length > 120) st.workMs.shift();
  }
  function drawGL(G, b, q, p, lines, ka, kb, w, h) {
    const {gl} = G;
    if (glc.width !== w || glc.height !== h) { glc.width = w; glc.height = h; }
    if (st.fresh && st.bitmap) {
      // premultiplied, as a painted bitmap arrives (a canvas painted on the main thread is premultiplied on the way up)
      gl.bindTexture(gl.TEXTURE_2D, G.tex); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, st.bitmap); G.texReady = true; st.fresh = false;
    }
    const ck = w + '|' + h + '|' + st.yaw + '|' + !!st.box?.crop + '|' + !!st.box?.tight + '|' + b.tag; if (st.camKey !== ck) { st.cam = camera(b, w, h); st.camKey = ck; }
    { const M = st.cam.mvp; st.proj = (x, y) => { const cw = M[3] * x + M[7] * y + M[15]; return [((M[0] * x + M[4] * y + M[12]) / cw + 1) / 2 * w, (1 - (M[1] * x + M[5] * y + M[13]) / cw) / 2 * h]; }; }
    const cam = st.cam, M = G.mesh;
    const ms = target(G, w, h); gl.bindFramebuffer(gl.FRAMEBUFFER, ms ? ms.fb : null);
    gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.disable(gl.BLEND);
    gl.useProgram(M.p); gl.uniformMatrix4fv(M.u.uMVP, false, cam.mvp); gl.uniform3fv(M.u.uEye, cam.eye); gl.uniform3fv(M.u.uKey, cam.key); gl.uniform3fv(M.u.uFill, cam.fill);
    const bind = (loc, buffer, size, stride, off) => { gl.bindBuffer(gl.ARRAY_BUFFER, buffer); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride, off); };
    const Bd = G.body;
    // skin: two posed keyframes, mixed
    const A = ka.e, Bk = kb.e;
    bind(0, A.buf, 3, 24, 0); bind(1, A.buf, 3, 24, 12); bind(2, Bk.buf, 3, 24, 0); bind(3, Bk.buf, 3, 24, 12); bind(4, Bd.skinCol, 3, 12, 0);
    bind(5, Bd.skinJaw, 1, 4, 0);
    gl.uniform1f(M.u.uMix, Bk === A ? 0 : q.w); gl.uniform3f(M.u.uJaw, b.pivot.x, b.pivot.y, p.jawPitch); gl.uniform1i(M.u.uKind, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, Bd.skinIdx); gl.drawElements(gl.TRIANGLES, Bd.skinCount, gl.UNSIGNED_INT, 0);
    // hair
    gl.disableVertexAttribArray(5); gl.vertexAttrib1f(5, 0); gl.uniform3f(M.u.uJaw, 0, 0, 0);
    bind(0, Bd.hair, 3, 24, 0); bind(1, Bd.hair, 3, 24, 12); bind(2, Bd.hair, 3, 24, 0); bind(3, Bd.hairTan, 3, 12, 0); bind(4, Bd.hairCol, 3, 12, 0);
    gl.uniform1f(M.u.uMix, 0); gl.uniform1i(M.u.uKind, 1);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, Bd.hairIdx); gl.drawElements(gl.TRIANGLES, Bd.hairCount, gl.UNSIGNED_INT, 0);
    // the parts behind the cut, the lower ones turned with the jaw
    bind(0, Bd.still, 3, 24, 0); bind(1, Bd.still, 3, 24, 12); bind(2, Bd.still, 3, 24, 0); bind(3, Bd.still, 3, 24, 12); bind(4, Bd.stillCol, 3, 12, 0); bind(5, Bd.stillJaw, 1, 4, 0);
    gl.uniform1i(M.u.uKind, 2); gl.uniform3f(M.u.uJaw, b.pivot.x, b.pivot.y, p.sc[SC.jawAngle] - b.jawRest);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, Bd.stillIdx); gl.drawElements(gl.TRIANGLES, Bd.stillCount, gl.UNSIGNED_SHORT, 0);
    gl.disableVertexAttribArray(5);
    for (const i of [1, 2, 3, 4]) gl.disableVertexAttribArray(i);
    // the cut face
    if (G.texReady) {
      const Q = G.quad, sb = sectionBounds(b.k);
      gl.useProgram(Q.p); gl.uniformMatrix4fv(Q.u.uMVP, false, cam.mvp); gl.uniform4f(Q.u.uBox, sb.x0, sb.y0, sb.x1, sb.y1);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, G.tex); gl.uniform1i(Q.u.uTex, 0);
      // blended, so where the cut face fades (the larynx's lumen, its own edges) the far half shows through by degrees
      gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      bind(0, G.quadBuf, 2, 8, 0); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      gl.disable(gl.BLEND);
    }
    // the air, just in front of the cut
    if (lines) {
      const P = G.pts; gl.useProgram(P.p); gl.uniformMatrix4fv(P.u.uMVP, false, cam.mvp); gl.uniform3f(P.u.uColor, .91, .93, .96);
      gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); gl.disable(gl.DEPTH_TEST);
      gl.bindBuffer(gl.ARRAY_BUFFER, G.partBuf); gl.bufferSubData(gl.ARRAY_BUFFER, 0, airBuf, 0, lines);
      bind(0, G.partBuf, 3, 12, 0); gl.drawArrays(gl.LINES, 0, lines / 3);
      bind(0, G.partBuf, 3, 24, 12); gl.drawArrays(gl.POINTS, 0, lines / 6);
      gl.disable(gl.BLEND);
    }
    if (ms) { gl.bindFramebuffer(gl.READ_FRAMEBUFFER, ms.fb); gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, null); gl.blitFramebuffer(0, 0, w, h, 0, 0, w, h, gl.COLOR_BUFFER_BIT, gl.NEAREST); gl.bindFramebuffer(gl.FRAMEBUFFER, null); }
  }
  // without WebGL2: the cut face alone, with the air drawn on it
  function draw2D(b, p, lines, w, h) {
    const c = c2d.getContext('2d');
    if (c2d.width !== w || c2d.height !== h) { c2d.width = w; c2d.height = h; }
    c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, w, h);
    const cb = st.box?.crop ? cropBox(b, st.box.tight) : null, sb = sectionBounds(b.k), crop = cb ? {x0: cb[0], x1: cb[1], y0: cb[2], y1: cb[3]} : {x0: -14.6 * b.k, x1: 10 * b.k, y0: -5.2 * b.k, y1: 25.4 * b.k};
    // (the small overlay's crop at the scale the camera above gives it, turned to rest, and on the view's bottom; a crop in
    // a view wider than itself keeps the face at the view's right edge, as the camera does)
    const small = cb && !st.box.tight, S = small ? scaleIn(frameFit(cb, 3), w, h) : Math.min(w / (crop.x1 - crop.x0), h / (crop.y1 - crop.y0)) * (cb ? 1 : .96), edge = Math.min((w - (crop.x1 - crop.x0) * S) / 2, (h - (crop.y1 - crop.y0) * S) / 2);
    const oy = small ? h + crop.y0 * S : (h - (crop.y1 - crop.y0) * S) / 2 + crop.y1 * S;
    const ox = cb ? w - edge - crop.x1 * S : (w - (crop.x1 - crop.x0) * S) / 2 - crop.x0 * S;
    st.proj = (x, y) => [ox + x * S, oy - y * S];
    if (st.bitmap) c.drawImage(st.bitmap, ox + sb.x0 * S, oy - sb.y1 * S, (sb.x1 - sb.x0) * S, (sb.y1 - sb.y0) * S);
    c.strokeStyle = '#e8ecf4'; c.lineCap = 'round'; c.lineWidth = Math.max(1, 1.4 * host.dpr());
    for (let i = 0; i < lines; i += 6) { c.globalAlpha = airBuf[i + 2]; c.beginPath(); c.moveTo(ox + airBuf[i] * S, oy - airBuf[i + 1] * S); c.lineTo(ox + airBuf[i + 3] * S, oy - airBuf[i + 4] * S); c.stroke(); }
    c.globalAlpha = 1;
  }
  // The small overlay's enlarge mark, drawn in (app/head.html): its top (CSS px from the view's top) at the level under the
  // lips (UNDER_LIPS), or 27 px above the view's bottom where the picture leaves more room under the chin, and how far it
  // then hangs below the picture into the caption's band, which sets the band's text under it. The crop stands on the
  // view's bottom at the scale the camera fits it (camera(), draw2D() alike), so the level's place needs no frame drawn.
  function placeMark(b) {
    const x = st.box; if (!x || x.mode !== 'overlay' || !x.crop) return;
    const c = cropBox(b, false), S = scaleIn(frameFit(c, 3), x.w, x.h), under = x.h - (UNDER_LIPS * b.k - c[2]) * S;
    const top = Math.max(x.h - 27, under), hang = x.mark ? Math.max(0, top + 24 - x.h) : 0, key = top.toFixed(1) + '|' + hang.toFixed(1);
    st.hang = hang; if (key === st.markKey) return; st.markKey = key;
    el.style.setProperty('--tract-grow-top', top.toFixed(1) + 'px'); el.style.setProperty('--tract-hang', hang.toFixed(1) + 'px');
  }
  function caption(q) {
    const i = q.info; if (!i) return '';
    const cur = q.seg?.sym;
    // the word, «приблизно» when its sounds are a guess, then its sounds with the one due now in brackets; the small overlay
    // on a phone leaves the word to the lyric band above it
    // A syllable's sounds stand together as IPA writes them, the syllables apart (a line breaks only between them), so a
    // narrow box never separates a consonant from its vowel.
    const mark = s => { const plain = s.replace('+', ''); return plain === (cur || '') || s.split('+').includes(cur) ? '[' + plain + ']' : plain; };
    const syl = [[]]; for (const s of i.phones.split(' ').filter(Boolean)) { if (s === '·') syl.push([]); else syl[syl.length - 1].push(mark(s)); }
    // (a line breaks before a syllable's dot, never after it, so no line ends on one)
    const parts = syl.filter(a => a.length).map(a => a.join('')), sounds = parts.join(' ·\u00a0');
    if (st.box?.mode === 'overlay' && st.box.crop) {
      // the small overlay drawn in so far that its enlarge mark hangs into the caption's band holds one line: the syllable
      // due now
      if (st.hang > 4) return parts.find(a => a.includes('[')) ?? parts[0] ?? '';
      // otherwise «приблизно» alone on its first line, the sounds on the second
      return (i.approx ? 'приблизно\n' : '') + sounds;
    }
    // the word on the first line and its sounds on the second, so a narrow column cuts none of them
    return '«' + i.w + '»' + (i.approx ? ' приблизно' : '') + '\n' + sounds;
  }

  // a press anywhere on the panel is the panel's: it never scrubs the roll under it
  el.addEventListener('pointerdown', e => e.stopPropagation());
  // turning the head: a drag while idle, up to 60° either way; a double click returns to the side view
  view.addEventListener('pointerdown', e => { e.stopPropagation(); if (!host.idle() || e.button !== 0 || e.target.closest('button')) return; st.drag = {x: e.clientX, yaw: st.yaw, moved: false}; view.setPointerCapture(e.pointerId); });
  view.addEventListener('pointermove', e => { if (!st.drag) return; const dx = e.clientX - st.drag.x; if (Math.abs(dx) > 4) st.drag.moved = true; st.yaw = clamp(st.drag.yaw + dx * .45, -60, 60); render(); });
  view.addEventListener('pointerup', e => { const d = st.drag; st.drag = null; if (d && !d.moved && st.box?.mode === 'overlay' && host.idle()) host.enlarge?.(); });
  view.addEventListener('dblclick', e => { e.stopPropagation(); st.yaw = 15; render(); });
  // the picture's size follows its box (a long word's sounds can take the caption a line further)
  if (window.ResizeObserver) new ResizeObserver(() => { if (!st.box) return; const r = view.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return;
    if (Math.abs(r.width - st.box.w) > .5 || Math.abs(r.height - st.box.h) > .5) { st.box = {...st.box, w: r.width, h: r.height}; if (st.shown) render(); } }).observe(view);

  return {
    layout(box) { st.box = box; if (st.shown) render(); },
    show(on) { st.shown = !!on; if (!on) { st.parts = null; st.lastT = null; } },
    song() { st.songRev = (st.songRev || 0) + 1; st.tl = null; },
    frame(t, moving) {
      if (!st.shown || !body()) return false;
      st.moving = !!moving;
      // the step down to 30 Hz (§6): when the head's own work runs long, and on a renderer without a GPU (forced), where
      // every frame of the head is rasterised and read back on the processor; the head then draws at most 30 times a second
      if (st.G?.software && st.hz === 60) st.hz = 30;
      const wall = performance.now();
      if (moving && st.hz === 30 && wall - st.drawnAt < 1000 / 30 - 4) return false;
      st.drawnAt = wall; render(t); adapt(); return true;
    },
    yaw(v) { st.yaw = clamp(+v || 0, -60, 60); render(); },
    state(measure = false) {
      const b = st.shown ? body() : null, cur = st.cur, p = cur?.p, s = p?.sc;
      const lipAp = s ? s[SC.lipAp] : null, prot = s ? s[SC.lipProt] : null, width = s ? s[SC.lipWidth] : null;
      return {posture: measure && p ? {points: Array.from(p.pts), scalars: Array.from(p.sc)} : undefined,
        shown: st.shown, body: b?.tag || null, scale: b?.k ?? null, renderer: !b ? null : st.G ? 'webgl2' : '2d', frames: st.frames, hz: st.hz,
        phoneme: cur?.q.seg?.sym ?? null, from: cur?.q.a ?? null, mix: cur?.q.w ?? 0, kind: cur?.q.seg?.kind ?? null, air: cur ? cur.air : null,
        lips: s ? (lipAp <= 0 ? 'closed' : s[SC.labiodental] > .5 ? 'teeth' : prot > .45 && width < .45 ? 'rounded' : 'open') : null,
        velum: s ? (s[SC.port] > .05 || s[SC.velum] > .2 ? 'lowered' : 'raised') : null, jaw: s ? +s[SC.jaw].toFixed(3) : null,
        larynxPx: s && st.proj ? st.proj(s[SC.glottisX], s[SC.glottisY]).map(v => +(v / (st.G?.software ? 1 : host.dpr())).toFixed(2)) : null,
        larynxY: s ? +s[SC.glottisY].toFixed(4) : null, pitch: p?.pitch ?? null, foldLength: p?.foldLength ?? null, foldThickness: p?.foldThickness ?? null,
        word: cur?.q.info?.w ?? null, approx: !!cur?.q.info?.approx, sound: sound.textContent, painted: st.paintN, painting: painter.busy || st.paintWaiting, paintMs: +st.paintMs.toFixed(2), worker: painter.worker,
        software: !!(st.software || st.G?.software), workMs: st.workMs.slice(), buildMs: st.buildMs ?? null, yaw: st.yaw, outline: b ? outlineSummary(b) : null, particles: st.parts ? st.parts.map(q => +q.u.toFixed(5)) : [],
        crop: !!st.box?.crop, samples: st.G ? (st.G.ms ? st.G.samples : 0) : null, airOut: st.airOut ?? 0, streaks: Array.from({length: (st.lines || 0) / 6}, (_, i) => [+airBuf[6 * i + 3].toFixed(2), +airBuf[6 * i + 4].toFixed(2)]),
        skinKeys: st.G?.body ? [...st.G.body.keys.keys()] : [], segments: st.tl ? st.tl.segs.length : 0, tight: !!st.box?.tight, mouthPx: p ? mouthPx(p) : null, face: p ? faceMarks() : null};
    },
    timeline() { const b = body(); return b ? tl(b) : null; },
    close() { painter.close(); },
  };
  function adapt() {
    const a = st.workMs; if (a.length < 60) return;
    const z = a.slice(-60).sort((x, y) => x - y), p95 = z[Math.floor(.95 * z.length)];
    if (st.hz === 60 && p95 > 8) st.hz = 30; else if (st.hz === 30 && p95 < 3 && !st.G?.software) st.hz = 60;
  }
  // How wide the mouth to the pharynx is drawn, in CSS pixels across the screen: from the airway's hindmost point between
  // 2 and 6 cm above the glottis (the pharynx's back wall) to the lips (the airway's centreline ends between them).
  function mouthPx(p) {
    if (!st.proj) return null;
    const pts = key => { const [o, m] = SEG[key], out = []; for (let i = 0; i < m; i++) out.push({x: p.pts[2 * (o + i)], y: p.pts[2 * (o + i) + 1]}); return out; };
    const gy = p.sc[SC.glottisY], k = st.cur && body() ? body().k : 1;
    let back = null;
    for (const q of pts('air:envelope')) if (q.y > gy + 2 * k && q.y < gy + 6 * k && (!back || q.x < back.x)) back = q;
    if (!back) return null;
    const front = {x: p.cl[2 * NC - 2], y: p.cl[2 * NC - 1]};
    const dpr = st.G?.software ? 1 : host.dpr();
    return +(Math.abs(st.proj(front.x, front.y)[0] - st.proj(back.x, back.y)[0]) / dpr).toFixed(1);
  }
  // Where the face's working parts stand (test hook): the lips (the back midline from the mouth's corner to under the nose,
  // the front one from the fold under the lower lip to the mouth), the nostril (the back midline from under the nose to
  // its tip) and each streak of the breath in front of them; boxes [x0, y0, x1, y1] in CSS pixels from the view's top
  // left (px), and in body cm (cm). The suite keeps the enlarge mark off them.
  function faceMarks() {
    const o = st.cur?.outline, b = st.shown ? body() : null; if (!st.proj || !o || !b) return null;
    const dpr = st.G?.software ? 1 : host.dpr(), at = (x, y) => st.proj(x, y).map(v => v / dpr);
    const box = list => { let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity; for (const [x, y] of list) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); } return [x0, y0, x1, y1].map(v => +v.toFixed(2)); };
    const P = (a, i) => [a[2 * i], a[2 * i + 1]], n = a => a.length / 2;
    // back: the upper lip's front, then under the nose (the hindmost point before the tip), then the tip (the foremost)
    // (found on the resting face: the midlines keep their vertices, so the same indices hold in every posture)
    const idx = st.faceIdx?.[b.tag] ?? ((st.faceIdx ??= {})[b.tag] = (() => {
      const r = keyframe(b, null, 'rest').outline, B = r.back, F = r.front;
      let lipF = 0; while (lipF + 1 < n(B) && B[2 * lipF + 2] >= B[2 * lipF]) lipF++;
      let sub = lipF; while (sub + 1 < n(B) && B[2 * sub + 2] <= B[2 * sub]) sub++;
      let tip = sub; while (tip + 1 < n(B) && B[2 * tip + 2] >= B[2 * tip]) tip++;
      // front (neck, chin, lower lip): from the mouth back over the lower lip to the fold above the chin
      let fold = n(F) - 1; while (fold > 0 && F[2 * fold - 2] >= F[2 * fold]) fold--; while (fold > 0 && F[2 * fold - 2] <= F[2 * fold]) fold--;
      return {sub, tip, fold};
    })());
    const B = o.back, F = o.front, {sub, tip, fold} = idx;
    const cmLips = [], cmNose = [];
    for (let i = 0; i <= sub; i++) cmLips.push(P(B, i));
    for (let i = fold; i < n(F); i++) cmLips.push(P(F, i));
    for (let i = sub; i <= tip; i++) cmNose.push(P(B, i));
    const front = Math.max(...cmLips.map(q => q[0])), cmAir = [];
    for (let i = 0; i < (st.lines || 0); i += 6) if (airBuf[i + 2] > .1 && Math.max(airBuf[i], airBuf[i + 3]) > front - .3) cmAir.push(box([[airBuf[i], airBuf[i + 1]], [airBuf[i + 3], airBuf[i + 4]]]));
    const px = list => box(list.map(q => at(q[0], q[1])));
    return {lips: px(cmLips), nostril: px(cmNose), air: cmAir.map(a => px([[a[0], a[1]], [a[2], a[3]]])), cm: {lips: box(cmLips), nostril: box(cmNose), air: cmAir}};
  }
  function outlineSummary(b) { let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity; for (let i = 0; i < b.rest.length; i += 3) { x0 = Math.min(x0, b.rest[i]); x1 = Math.max(x1, b.rest[i]); y0 = Math.min(y0, b.rest[i + 1]); y1 = Math.max(y1, b.rest[i + 1]); } return {x0: +x0.toFixed(2), x1: +x1.toFixed(2), y0: +y0.toFixed(2), y1: +y1.toFixed(2)}; }
}

window.LumaTract = {attach, key, letterRules, syllables, timeline, LABEL, wholeScale};
})();
