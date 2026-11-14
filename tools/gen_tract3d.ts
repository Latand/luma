// Carries values and rules from the Chimera vocal synth (its scene's material colours, its sung consonant length, its
// /əCə/ consonant postures), under its licence:
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

/**
 * Bakes the 3D cut-away head of the trainer's «Голова» panel (app/tract3d.js) into app/tract3d.data.js, from a checkout of
 * the Chimera vocal synth (MIT) at a pinned commit:
 *
 *   bun tools/gen_tract3d.ts <chimera checkout> [-o app/tract3d.data.js]
 *
 * The checkout must have its engine built first (`bun run wasm` there). The generator loads that engine the way
 * Chimera's own tests do (tests/harness.ts), asks it for every posture the trainer can show and writes plain data: the
 * trainer never runs the engine. Nothing in the output depends on the time, the machine or the order of a map, so two
 * runs against one commit write the same bytes. docs/design/VOCAL_TRACT_3D.md §3 explains what is baked and why.
 *
 * Per body (male and female, Chimera's two adult bodies):
 *   - postures: the 22 vowels Chimera calibrates per body, 33 consonants laid over a schwa (the planner's targets for
 *     /əCə/), and the resting posture. Each holds 461 midline points at fixed counts per named polygon (resampled by arc
 *     length, so that two postures blend point by point; the lips' two edges stay as the engine samples them, by
 *     lateral offset, because the skin's rig reads them that way), 32 numbers (the jaw's turn, the glottis, the lips'
 *     width, the velopharyngeal port, the voicing flags, the articulators, the sung length of the sound), a
 *     24-point centreline of the airway and 24 area samples along it, from the 3D model's own area function;
 *   - the skin: MakeHuman's base mesh as Chimera bakes it (head.generated.bin), without the display stand, at the
 *     body's own size; its topology and per-vertex weights are shared by both bodies;
 *   - the hair: a shell grown from the scalp along the skin's normals (short for the male body, longer for the female
 *     body, with a drape down the back of the neck), on the same topology;
 *   - the far half of the parts that do not change shape (the hard palate, the teeth with the gums, the cheeks), with
 *     each vertex's share of the jaw's turn, for what shows through the air in the cut;
 *   - the nasal path the air takes when the soft palate is lowered.
 */
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const args = process.argv.slice(2);
const CH = args[0] && !args[0].startsWith("-") ? resolve(args[0]) : null;
if (!CH) throw new Error("usage: bun tools/gen_tract3d.ts <chimera checkout> [-o app/tract3d.data.js]");
const OUT = args.includes("-o") ? resolve(args[args.indexOf("-o") + 1]) : join(import.meta.dir, "..", "app", "tract3d.data.js");

// ---------------------------------------------------------------- provenance
const git = (...a: string[]) => {
  const r = spawnSync("git", ["-C", CH, ...a], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`git ${a.join(" ")}: ${r.stderr.trim()}`);
  return r.stdout.trim();
};
const COMMIT = git("rev-parse", "HEAD");
const dirty = git("status", "--porcelain", "--untracked-files=no");
if (dirty) throw new Error(`the Chimera checkout has local changes; bake from a clean commit:\n${dirty}`);
const headDoc = readFileSync(join(CH, "docs", "tract3d", "head-asset.md"), "utf8");
const MAKEHUMAN = headDoc.match(/commit\s+`([0-9a-f]{40})`/)?.[1];
if (!MAKEHUMAN) throw new Error("docs/tract3d/head-asset.md names no MakeHuman commit");
const LICENSE = readFileSync(join(CH, "LICENSE"), "utf8").trim();

// ---------------------------------------------------------------- the engine
const { initEngine } = await import(join(CH, "tests", "harness.ts"));
await initEngine();
const api = await import(join(CH, "src", "wasm", "engine.ts"));
const { call } = await import(join(CH, "src", "wasm", "chimera.ts"));
const { readHead } = await import(join(CH, "src", "ui", "render", "head", "asset.ts"));
const cat: any = call("catalog");

type P = { x: number; y: number };
const VOWELS = "a e i o u y æ ø œ ɐ ɑ ɒ ɔ ə ɛ ɝ ɤ ɨ ɪ ɯ ʊ ʌ".split(" ");
const CONSONANTS = "p b t d k g ʔ m n ŋ f v θ ð s z ʃ ʒ x h ɦ ts tʃ dʒ w ʋ ɹ j l r ɲ ʎ ç".split(" ");
const SYMBOLS = [...VOWELS, ...CONSONANTS, "rest"];
const ARTIC = ["jaw", "tbX", "tbY", "ttX", "ttY", "ttCurl", "root", "lipAp", "lipProt", "lipWidth", "labiodental", "velum", "larynx", "epilarynx", "ventricular", "lateral", "dorsum"];
const SCALARS = ["jawAngle", "glottisX", "glottisY", "lipHalf", "lipZ", "upTeethX", "upTeethY", "lowTeethX", "lowTeethY", "port", "lipArea", "minArea", "abduction", "closure", "dur", ...ARTIC];
if (SCALARS.length !== 32) throw new Error("32 scalars per posture");
/** the midline polygons and how many points each keeps (the order of the posture's points) */
const LAYOUT: [string, number][] = [
  ["air:envelope", 64], ["air:tube", 48], ["air:vallecula", 20],
  ["tissue:tongue", 56], ["tissue:epiglottis", 8], ["tissue:upperLip", 12], ["tissue:lowerLip", 14], ["tissue:pharynxWall", 60], ["tissue:uvula", 12],
  ["outline:tongue", 56], ["outline:velum", 24], ["outline:upperTeeth", 6], ["outline:lowerTeeth", 5], ["outline:jawBone", 8], ["outline:nasalCavity", 18],
  ["lips:upper", 25], ["lips:lower", 25],
];
const NPTS = LAYOUT.reduce((s, [, n]) => s + n, 0);
if (NPTS !== 461) throw new Error(`461 points per posture, not ${NPTS}`);
const CL = 24;

const r4 = (v: number) => Math.round(v * 1e4) / 1e4;
/** the polyline resampled to n points at equal arc length (its two ends kept) */
function resample(p: P[], n: number): P[] {
  const c = [0];
  for (let i = 1; i < p.length; i++) c.push(c[i - 1] + Math.hypot(p[i].x - p[i - 1].x, p[i].y - p[i - 1].y));
  const L = c[c.length - 1], o: P[] = [];
  let j = 0;
  for (let i = 0; i < n; i++) {
    const s = (L * i) / (n - 1);
    while (j < p.length - 2 && c[j + 1] < s) j++;
    const t = (s - c[j]) / Math.max(1e-9, c[j + 1] - c[j]);
    o.push({ x: p[j].x + (p[j + 1].x - p[j].x) * t, y: p[j].y + (p[j + 1].y - p[j].y) * t });
  }
  return o;
}
function midline(d: any, sym: string): P[] {
  const out: P[] = [];
  for (const [key, n] of LAYOUT) {
    const [kind, name] = key.split(":");
    let pts: P[] | undefined;
    if (kind === "lips") pts = d.lips[name];
    else pts = d[kind === "outline" ? "outlines" : kind].find((q: any) => q.name === name)?.points;
    if (!pts || pts.length < 2) throw new Error(`${sym}: no ${key} in the engine's view`);
    if (kind === "lips") {
      if (pts.length !== n) throw new Error(`${sym}: ${key} has ${pts.length} samples, not ${n}`);
      out.push(...pts);
    } else out.push(...resample(pts, n));
  }
  return out;
}

/** a consonant over a schwa: the planner's gestures for /əCə/ during the consonant, laid on the schwa's posture */
function consonant(body: any, schwa: Record<string, number>, c: string) {
  const plan: any = api.planUtterance(api.tokenizeIpa("ə" + c + "ə"), { body, t0: 0 });
  const seg = plan.segments[1];
  if (!seg || seg.ipa !== c) throw new Error(`the planner did not read /${c}/ as one segment`);
  const a = { ...schwa };
  const flags: Record<string, number> = {};
  // (the gestures in time order; a later one wins a key, as the planner's own blend lets the stronger gesture win)
  for (const g of plan.gestures) {
    if (g.t1 < seg.t0 || g.t0 > seg.t1) continue;
    if (g.label === "ə" || g.label === "pitch" || g.label === "breath") continue;
    for (const [k, v] of Object.entries(g.targets) as [string, number][]) {
      if (k in a) a[k] = v;
      else flags[k] = v;
    }
  }
  return { a, flags, kind: seg.kind as string, dur: seg.t1 - seg.t0 };
}

// ---------------------------------------------------------------- the skin, shared
const head = readHead(readFileSync(join(CH, "src", "ui", "render", "head", "head.generated.bin")).buffer);
const SKIN_N = head.skin;
const keepPoly = head.polys.filter((p: number[]) => p.every((i) => i < SKIN_N));
const used = new Uint8Array(SKIN_N);
for (const p of keepPoly) for (const i of p) used[i] = 1;
const remap = new Int32Array(SKIN_N).fill(-1);
let nSkin = 0;
for (let i = 0; i < SKIN_N; i++) if (used[i]) remap[i] = nSkin++;
const polys: number[][] = keepPoly.map((p: number[]) => p.map((i) => remap[i]));
const loopOf = (l: number[]) => l.filter((i) => i < SKIN_N && remap[i] >= 0).map((i) => remap[i]);
const loops = { lipLine: loopOf(head.loops.lipLine), rim: loopOf(head.loops.rim), midFront: loopOf(head.loops.midFront), midBack: loopOf(head.loops.midBack) };
const keepIdx: number[] = [];
for (let i = 0; i < SKIN_N; i++) if (remap[i] >= 0) keepIdx.push(i);
const attrs = head.attrs.map((a: Float32Array) => Uint8Array.from(keepIdx, (i) => Math.round(a[i] * 255)));

/** vertex normals of a polygon mesh (area-weighted, Newell) */
function normals(pos: Float64Array, ps: number[][], n: number): Float64Array {
  const out = new Float64Array(3 * n);
  for (const p of ps) {
    let nx = 0, ny = 0, nz = 0;
    for (let i = 0; i < p.length; i++) {
      const a = p[i], b = p[(i + 1) % p.length];
      nx += (pos[3 * a + 1] - pos[3 * b + 1]) * (pos[3 * a + 2] + pos[3 * b + 2]);
      ny += (pos[3 * a + 2] - pos[3 * b + 2]) * (pos[3 * a] + pos[3 * b]);
      nz += (pos[3 * a] - pos[3 * b]) * (pos[3 * a + 1] + pos[3 * b + 1]);
    }
    for (const i of p) (out[3 * i] += nx), (out[3 * i + 1] += ny), (out[3 * i + 2] += nz);
  }
  for (let i = 0; i < n; i++) {
    const l = Math.hypot(out[3 * i], out[3 * i + 1], out[3 * i + 2]) || 1;
    for (let c = 0; c < 3; c++) out[3 * i + c] /= l;
  }
  return out;
}
const smooth = (t: number) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
/** piecewise-linear, x ascending */
const pwl = (xs: number[], ys: number[], x: number) => {
  if (x <= xs[0]) return ys[0];
  for (let i = 1; i < xs.length; i++) if (x <= xs[i]) return ys[i - 1] + ((ys[i] - ys[i - 1]) * (x - xs[i - 1])) / (xs[i] - xs[i - 1]);
  return ys[ys.length - 1];
};
/**
 * The hairline over the template head (cm, the male template, x forward, y up): its height by the angle round the
 * skull's upright axis (0 the forehead, 90° above the ear, 180° the nape). It keeps 0.5 cm above the ear's top
 * (17.5 cm) where the ear is (80°–125°).
 */
const HAIR_ANG = [0, 35, 60, 80, 125, 140, 160, 180];
const HAIR_Y = [19.6, 19.2, 18.5, 18.1, 18.1, 15.2, 11.0, 9.2];
const SKULL_X = -2.4;

function hairShell(rest: Float64Array, k: number, female: boolean) {
  const nrm = normals(rest, polys, nSkin);
  const thick = new Float64Array(nSkin);
  for (let i = 0; i < nSkin; i++) {
    const x = rest[3 * i] / k, y = rest[3 * i + 1] / k, z = rest[3 * i + 2] / k;
    const ang = (Math.abs(Math.atan2(z, x - SKULL_X)) * 180) / Math.PI;
    const above = y - pwl(HAIR_ANG, HAIR_Y, ang);
    let t = 0;
    if (!female) {
      // short: 0.8 cm at the crown, 0.25 cm at the hairline (the design's 0.6 cm read as a line at panel size)
      t = smooth(above / 1.0) * (0.25 + 0.55 * smooth(above / 4.5));
    } else {
      // 1.2 cm over the scalp; at the back a drape down the neck to the larynx' height, thicker as it falls
      t = smooth(above / 1.4) * 1.2;
      if (ang > 115) {
        const side = smooth((ang - 115) / 25);
        const fall = smooth((y - 1.6) / 1.6) * (1 - smooth((y - 12) / 2));
        t = Math.max(t, side * fall * (1.5 + 0.9 * smooth((11 - y) / 8)));
      }
    }
    thick[i] = t;
  }
  // the hair's polygons: every skin polygon with some thickness; its vertices that have none lie on the skin
  const inHair = (p: number[]) => p.some((i) => thick[i] > 0.02);
  const hp = polys.filter(inHair);
  const map = new Int32Array(nSkin).fill(-1);
  const verts: number[] = [];
  for (const p of hp) for (const i of p) if (map[i] < 0) (map[i] = verts.length), verts.push(i);
  const pos = new Float64Array(3 * verts.length);
  verts.forEach((i, j) => {
    const t = Math.max(0.03, thick[i]) * k;
    for (let c = 0; c < 3; c++) pos[3 * j + c] = rest[3 * i + c] + nrm[3 * i + c] * t;
  });
  // the female drape hangs: its outer surface at the back does not come forward of a line falling from the occiput
  if (female) {
    let occ = Infinity;
    for (let j = 0; j < verts.length; j++) if (Math.abs(pos[3 * j + 2]) < 0.6 * k && pos[3 * j + 1] > 9 * k && pos[3 * j + 1] < 15 * k) occ = Math.min(occ, pos[3 * j]);
    for (let j = 0; j < verts.length; j++) {
      const i = verts[j], y = rest[3 * i + 1] / k;
      if (thick[i] <= 0.02 || y > 12 || rest[3 * i] / k > SKULL_X - 3) continue;
      const hang = occ + 0.18 * (12 * k - pos[3 * j + 1]);
      const lateral = 1 - smooth((Math.abs(pos[3 * j + 2]) / k - 3.5) / 2.5);
      if (pos[3 * j] > hang) pos[3 * j] += (hang - pos[3 * j]) * lateral * smooth((12 - y) / 3) * smooth(thick[i] / 0.8);
    }
  }
  // the hair's midline: the skin's back midline where it has hair
  const mid = loops.midBack.filter((i) => map[i] >= 0).map((i) => map[i]);
  const skinMid = loops.midBack.filter((i) => map[i] >= 0);
  return { pos, polys: hp.map((p) => p.map((i) => map[i])), mid, skinMid, n: verts.length };
}

// ---------------------------------------------------------------- encoding
const b64 = (a: ArrayBufferView) => Buffer.from(a.buffer, a.byteOffset, a.byteLength).toString("base64");
const i16 = (vals: ArrayLike<number>, scale: number) => {
  const o = new Int16Array(vals.length);
  for (let i = 0; i < vals.length; i++) {
    const v = Math.round(vals[i] * scale);
    if (v < -32768 || v > 32767) throw new Error(`value ${vals[i]} out of 16-bit range at scale ${scale}`);
    o[i] = v;
  }
  return o;
};
/** polygons as [count, i…] runs in 16 bits */
const packPolys = (ps: number[][]) => Uint16Array.from(ps.flatMap((p) => [p.length, ...p]));

// ---------------------------------------------------------------- per body
const STATIC = ["palate", "teethJaw", "cheeks"];
/** the scene's material colours (Chimera src/ui/render/head/scene.ts, MATERIALS), sRGB */
const MATERIAL: Record<string, number> = { palate: 0xe0a39a, enamel: 0xf4efe3, gum: 0xdc8d92, cheek: 0xc0606a };
const MATS = Object.keys(MATERIAL);

const bodies: Record<string, any> = {};
const counts: Record<string, any> = {};
for (const [tag, mix] of [["male", { female: 0, child: 0 }], ["female", { female: 1, child: 0 }]] as const) {
  const spec = cat.bodies[tag];
  const k: number = spec.scale, ph: number = spec.pharynx;
  const model = api.airwayModel(mix, 48000);
  const vt = cat.vowelTargets[tag];
  for (const v of VOWELS) if (!vt[v]) throw new Error(`${tag}: Chimera calibrates no /${v}/`);
  const neutral = { ...api.NEUTRAL };
  const schwa = { ...neutral, ...vt["ə"].artic };
  const postures: { sym: string; a: Record<string, number>; flags: Record<string, number>; kind: string; dur: number }[] = [];
  for (const v of VOWELS) postures.push({ sym: v, a: { ...neutral, ...vt[v].artic }, flags: {}, kind: "vowel", dur: 0 });
  for (const c of CONSONANTS) {
    const r = consonant(mix, schwa, c);
    // sung consonants are a little shorter than spoken ones (Chimera crates/chimera/src/phonetics/sing.rs, cdur)
    postures.push({ sym: c, a: r.a, flags: r.flags, kind: r.kind, dur: r.dur * 0.8 });
  }
  postures.push({ sym: "rest", a: neutral, flags: {}, kind: "rest", dur: 0 });

  const pts: number[] = [], sc: number[] = [], cl: number[] = [], ar: number[] = [];
  let pivot: P | null = null;
  for (const p of postures) {
    const view = api.tract3dView(model, p.a, {}, false);
    const d = view.display;
    pivot ??= d.jaw.pivot;
    if (Math.abs(d.jaw.pivot.x - pivot!.x) > 1e-9 || Math.abs(d.jaw.pivot.y - pivot!.y) > 1e-9) throw new Error(`${tag} /${p.sym}/: the jaw's pivot moved`);
    const m = midline(d, p.sym);
    for (const q of m) pts.push(q.x, q.y);
    const z = d.lips.z;
    for (let i = 0; i < z.length; i++) if (Math.abs(z[i] - (z[z.length - 1] * i) / (z.length - 1)) > 1e-6) throw new Error(`${tag} /${p.sym}/: the lips' samples are not evenly spaced`);
    const tooth = (name: string) => d.outlines.find((o: any) => o.name === name).points[2];
    const frame = api.airwayFrame(model, p.a);
    const f = api.tract3d(model, p.a, {}, { meshes: false });
    const values: Record<string, number> = {
      jawAngle: d.jaw.angle, glottisX: d.glottis.x, glottisY: d.glottis.y, lipHalf: d.lips.halfWidth, lipZ: z[z.length - 1],
      upTeethX: tooth("upperTeeth").x, upTeethY: tooth("upperTeeth").y, lowTeethX: tooth("lowerTeeth").x, lowTeethY: tooth("lowerTeeth").y,
      port: frame.velumPort, lipArea: frame.lipArea, minArea: f.areaFn.minArea, abduction: p.flags.abduction ?? 0, closure: p.flags.closure ?? 0, dur: p.dur,
    };
    for (const key of ARTIC) values[key] = p.a[key] ?? 0;
    for (const key of SCALARS) {
      if (!Number.isFinite(values[key])) throw new Error(`${tag} /${p.sym}/: ${key} is ${values[key]}`);
      sc.push(values[key]);
    }
    for (const q of resample(f.centreline, CL)) cl.push(q.x, q.y);
    // the area function at 24 points evenly along the centreline
    const S = f.areaFn.s, A = f.areaFn.area, L = S[S.length - 1];
    for (let i = 0; i < CL; i++) ar.push(pwl(S, A, (L * i) / (CL - 1)));
  }

  // the skin at the body's own size (the engine's template map: scale, and the pharynx below 7 cm)
  const rest = new Float64Array(3 * nSkin);
  const bi = ["male", "female", "child"].indexOf(tag);
  keepIdx.forEach((i, j) => {
    const y = head.bodies[bi][3 * i + 1];
    rest[3 * j] = head.bodies[bi][3 * i] * k;
    rest[3 * j + 1] = (y < 7 ? 7 - (7 - y) * ph : y) * k;
    rest[3 * j + 2] = head.bodies[bi][3 * i + 2] * k;
  });
  const hair = hairShell(rest, k, tag === "female");

  // the far half of the parts that keep their shape, at rest; each vertex's share of the jaw's turn from how far it
  // follows a turn of the open jaw (1: with the lower teeth, 0: with the skull)
  const restA = postures[postures.length - 1].a;
  const openA = { ...restA, jaw: 2.2 };
  const vRest = api.tract3dView(model, restA, {}, true), vOpen = api.tract3dView(model, openA, {}, true);
  const th0 = vRest.display.jaw.angle, th1 = vOpen.display.jaw.angle, dth = th1 - th0;
  const sp: number[] = [], sjaw: number[] = [], smat: number[] = [], sidx: number[] = [];
  let svert = 0;
  for (const m of vRest.meshes) {
    if (!STATIC.includes(m.element)) continue;
    const mo = vOpen.meshes.find((q: any) => q.element === m.element);
    const P0 = vRest.positions.subarray(3 * m.start, 3 * (m.start + m.count)), P1 = vOpen.positions.subarray(3 * mo.start, 3 * (mo.start + mo.count));
    const idx: number[] = Array.from(m.indices);
    const mat = new Int32Array(m.count).fill(-1);
    for (const g of m.groups) {
      const mi = MATS.indexOf(g.material === "cheek" ? "cheek" : g.material);
      if (mi < 0) throw new Error(`no colour for ${g.material}`);
      for (let t = g.start; t < g.start + g.count; t++) if (mat[idx[t]] < 0) mat[idx[t]] = mi;
    }
    const keep = new Int32Array(m.count).fill(-1);
    for (let t = 0; t < idx.length; t += 3) {
      const tri = [idx[t], idx[t + 1], idx[t + 2]];
      if (Math.min(...tri.map((i) => P0[3 * i + 2])) > 0.02) continue;
      for (const i of tri) {
        if (keep[i] < 0) {
          keep[i] = svert++;
          const x = P0[3 * i], y = P0[3 * i + 1], z = P0[3 * i + 2];
          sp.push(x, y, z);
          const dx = x - pivot!.x, dy = y - pivot!.y;
          const rx = pivot!.x + dx * Math.cos(dth) - dy * Math.sin(dth) - x, ry = pivot!.y + dx * Math.sin(dth) + dy * Math.cos(dth) - y;
          const mx = P1[3 * i] - x, my = P1[3 * i + 1] - y;
          const rr = rx * rx + ry * ry;
          sjaw.push(rr > 1e-8 ? Math.min(1, Math.max(0, (mx * rx + my * ry) / rr)) : 0);
          smat.push(Math.max(0, mat[i]));
        }
        sidx.push(keep[i]);
      }
    }
  }
  if (svert > 65535) throw new Error("static meshes need 32-bit indices");

  // the nasal path: up behind the soft palate, through the middle of the nasal cavity the cut face paints (Chimera
  // section.ts: its outline runs from 10.25 to 13.9 cm; the engine's nasalCavity outline is the cavity's floor, on the
  // hard palate), out at the nostril under the tip of the nose
  const NOSE_T: [number, number][] = [[-0.8, 9.2], [-0.5, 10.6], [0.4, 11.5], [1.8, 11.9], [3.6, 12.1], [5.4, 11.9], [6.9, 11.4], [7.7, 10.6], [8.5, 9.9], [10.0, 9.3]];
  const nose: P[] = NOSE_T.map(([x, y]) => ({ x: x * k, y: y * k }));

  bodies[tag] = {
    scale: k, pharynx: ph, pivot: [r4(pivot!.x), r4(pivot!.y)], jawRest: r4(th0),
    pts: b64(i16(pts, 100)), sc: b64(Float32Array.from(sc)), cl: b64(i16(cl, 100)), ar: b64(Uint16Array.from(ar, (v) => Math.min(65535, Math.round(v * 100)))),
    skin: b64(i16(rest, 100)),
    hair: { n: hair.n, pos: b64(i16(hair.pos, 100)), polys: b64(packPolys(hair.polys)), np: hair.polys.length, mid: hair.mid, skinMid: hair.skinMid },
    still: { n: svert, pos: b64(i16(sp, 100)), jaw: b64(Uint8Array.from(sjaw, (v) => Math.round(v * 255))), mat: b64(Uint8Array.from(smat)), idx: b64(Uint16Array.from(sidx)) },
    nose: nose.flatMap((q) => [r4(q.x), r4(q.y)]),
  };
  counts[tag] = { postures: postures.length, points: NPTS, hair: hair.n, hairPolys: hair.polys.length, still: svert, stillTris: sidx.length / 3 };
  if (tag === "male") counts.kinds = postures.map((p) => p.kind);
}

const kinds = counts.kinds as string[];
delete counts.kinds;
const data = {
  v: 1,
  source: { chimera: COMMIT, makehuman: MAKEHUMAN },
  symbols: SYMBOLS,
  kinds,
  scalars: SCALARS,
  layout: LAYOUT,
  centreline: CL,
  materials: MATS.map((m) => "#" + MATERIAL[m].toString(16).padStart(6, "0")),
  skin: {
    n: nSkin,
    polys: b64(packPolys(polys)),
    np: polys.length,
    jaw: b64(attrs[0]), upper: b64(attrs[1]), lower: b64(attrs[2]), tint: b64(attrs[3]), inside: b64(attrs[4]),
    loops,
  },
  male: bodies.male,
  female: bodies.female,
};
const json = JSON.stringify(data);
const header = `// GENERATED by tools/gen_tract3d.ts from the Chimera vocal synth at commit ${COMMIT}. Do not edit: regenerate.
//   bun tools/gen_tract3d.ts <chimera checkout at that commit, after its \`bun run wasm\`>
// What it holds (docs/design/VOCAL_TRACT_3D.md §3.3): for the male and the female body, ${counts.male.postures} postures each
// (22 vowels, 33 consonants over a schwa, rest) of ${NPTS} midline points, 32 values, a ${CL}-point centreline and ${CL} areas; the skin
// (${nSkin} vertices, ${polys.length} polygons, shared topology); the hair (${counts.male.hair} and ${counts.female.hair} vertices); the far half
// of the hard palate, the teeth with the gums and the cheeks (${counts.male.still} and ${counts.female.still} vertices); the nasal path.
// The skin is MakeHuman's base mesh as Chimera bakes it (head.generated.bin): MakeHuman commit ${MAKEHUMAN},
// its assets released under CC0 1.0 Universal. The postures, the cut's geometry and the rig's inputs are Chimera's, under
// its licence:
//
${LICENSE.split("\n").map((l) => ("// " + l).trimEnd()).join("\n")}
`;
const text = header + "window.LUMA_TRACT3D=" + json + ";\n";
writeFileSync(OUT, text);
console.log(`wrote ${OUT}: ${text.length} bytes, chimera ${COMMIT.slice(0, 7)}`, JSON.stringify(counts));
