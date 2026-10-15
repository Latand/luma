'use strict';
// The burn of a lost life (docs/design/LIFE_BURN.md). One pure draw function, so the trainer while singing and the camera
// video's render draw the same pixels: state + time → canvas 2D. No DOM, no clock, no storage, no Math.random; every
// flicker and every ember comes from `ms` and `seed`.
//
// drawHeart(ctx, x, y, size, state, ms, seed)
//   x, y   centre of the heart's square, in the context's current units; size = the side of that square (the trainer's
//          DOM heart is 13–14 px, its <svg> viewBox is 24)
//   state  'full' | 'lost' | 'burn'
//   ms     for 'burn': milliseconds since the life was lost; below 0 draws 'full', from BURN.ms on draws 'lost'
//   seed   the heart's index in its row, so neighbouring hearts burn differently and a replay burns the same
// BURN.box: how far the burn paints around the centre, in heart sizes (left, right, up, down): a caller sizes its canvas
// or clears its region from it.
(() => {
const BURN = {ms: 800, box: {l: 3, r: 3, t: 5.6, b: 1.8}};
// i-heart in app/head.html, and the colours of .life .full / .life .shell
const HEART = 'M12 20.5s-7.6-4.7-9.4-9.4C1.4 7.9 3.5 4.3 7.1 4.3c2.1 0 3.6 1.2 4.9 3 1.3-1.8 2.8-3 4.9-3 3.6 0 5.7 3.6 4.5 6.8-1.8 4.7-9.4 9.4-9.4 9.4z';
const ROSE = '#f3a1b5', SHELL = '#76839b', ASH = '#1b1a22', RIM = '#e9b98a';
const HOT = '#fff4dc', GOLD = '#ffd27a', FLAME = '#ff9a3c', EMBER = '#ff6a2b';
let path = null; const heart = () => path || (path = new Path2D(HEART));
// mulberry32: a small seeded generator, the same sequence in every browser
const rng = seed => { let a = (seed * 2654435761 + 0x9e3779b9) >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; };
const seg = (ms, a, b) => Math.max(0, Math.min(1, (ms - a) / (b - a)));
const easeOut = p => 1 - (1 - p) ** 3, easeIn = p => p * p;

// the heart in its 24-unit box centred on 0,0 of the current transform
function shape(ctx, fill, stroke) {
  ctx.save(); ctx.translate(-12, -12);
  if (fill) { ctx.fillStyle = fill; ctx.fill(heart()); }
  if (stroke) { ctx.lineWidth = 1.6; ctx.strokeStyle = stroke; ctx.stroke(heart()); }
  ctx.restore();
}
function still(ctx, x, y, size, full, alpha = 1) {
  if (alpha <= 0) return; ctx.save(); ctx.globalAlpha = alpha; ctx.translate(x, y); ctx.scale(size / 24, size / 24);
  shape(ctx, null, SHELL); if (full) shape(ctx, ROSE, ROSE); ctx.restore();
}
function glow(ctx, x, y, r, color, alpha) {
  if (alpha <= 0 || r <= 0) return; const g = ctx.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, color); g.addColorStop(1, 'rgba(255,140,60,0)');
  ctx.save(); ctx.globalAlpha = alpha; ctx.globalCompositeOperation = 'lighter'; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill(); ctx.restore();
}
function ember(ctx, x, y, r, alpha, hot) {
  if (alpha <= 0) return; ctx.save(); ctx.globalAlpha = alpha; ctx.globalCompositeOperation = 'lighter';
  ctx.fillStyle = hot ? GOLD : EMBER; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill(); ctx.restore();
  glow(ctx, x, y, r * 3, hot ? GOLD : FLAME, alpha * .45);
}
// three flame tongues standing on the char line y0 (24-unit box, centred), height scaled by `h`, flickering with ms
function flames(ctx, y0, ms, seed, h) {
  if (h <= 0) return; const R = rng(seed + 7);
  for (let k = 0; k < 3; k++) {
    const cx = (k - 1) * 5.2 + (R() - .5) * 1.5, ph = R() * 6.28, f = .75 + .25 * Math.sin(ms / 38 + ph) * Math.sin(ms / 23 + ph * 1.7);
    const tall = (k === 1 ? 12 : 9) * h * f, w = 5.6 * Math.min(1, h + .3), lean = Math.sin(ms / 55 + ph) * 1.4;
    if (tall <= .2) continue;
    const g = ctx.createLinearGradient(0, y0, 0, y0 - tall);
    g.addColorStop(0, GOLD); g.addColorStop(.4, FLAME); g.addColorStop(.8, EMBER); g.addColorStop(1, 'rgba(255,106,43,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(cx - w / 2, y0 + .6);
    ctx.bezierCurveTo(cx - w / 2, y0 - tall * .45, cx + lean * .4 - w * .18, y0 - tall * .7, cx + lean, y0 - tall);
    ctx.bezierCurveTo(cx + lean * .4 + w * .2, y0 - tall * .7, cx + w / 2, y0 - tall * .45, cx + w / 2, y0 + .6); ctx.closePath(); ctx.fill();
  }
}

// 0–90 ms a white-hot flash swells the heart to 2.4×, it shakes until 300 ms; 70–560 ms fire takes it from the tip up
// (a glowing char line climbs, ash below it, three flame tongues ride it); 140–800 ms eight embers rise and fade;
// 480–760 ms it shrinks back and the outline of a lost heart is left.
// shadowBlur is in device pixels and ignores the transform, so the char line's glow takes the transform's scale: the
// same glow at every devicePixelRatio and in any caller's units.
function burn(ctx, x, y, size, ms, seed) {
  const u = size / 24;
  const pop = ms < 90 ? 1 + 1.4 * easeOut(ms / 90) : 2.4 - .3 * seg(ms, 90, 480) - 1.1 * easeIn(seg(ms, 480, 760));
  const shake = ms < 300 ? Math.sin(ms / 14 + seed) * (1 - ms / 300) * 1.2 : 0;
  const p = seg(ms, 70, 560), charY = 8.5 - (easeIn(p) * .8 + p * .2) * 17;   // from the tip (+8.5) up past the top
  const out = seg(ms, 600, 800);
  still(ctx, x, y, size, false, seg(ms, 520, 760));
  glow(ctx, x, y, size * (1.2 + 1.2 * easeOut(seg(ms, 0, 160))), FLAME, (ms < 160 ? 1 : 1 - seg(ms, 160, 640)) * .7);
  ctx.save(); ctx.translate(x + shake * u * pop, y); ctx.scale(u * pop, u * pop); ctx.globalAlpha = 1 - out;
  ctx.save(); ctx.translate(-12, -12); ctx.clip(heart()); ctx.translate(12, 12);
  ctx.fillStyle = ASH; ctx.fillRect(-14, -14, 28, 28);
  ctx.fillStyle = ROSE; ctx.fillRect(-14, -14, 28, charY + 14);
  const white = 1 - seg(ms, 40, 200);
  if (white > 0) { ctx.globalAlpha = (1 - out) * white; ctx.fillStyle = HOT; ctx.fillRect(-14, -14, 28, 28); ctx.globalAlpha = 1 - out; }
  const R = rng(seed + 3); ctx.beginPath(); ctx.moveTo(-14, charY);
  for (let k = 0; k <= 8; k++) ctx.lineTo(-12 + k * 3, charY + (R() - .5) * 2.2 + Math.sin(ms / 30 + k) * .4);
  ctx.lineWidth = 1.8; ctx.strokeStyle = GOLD; ctx.shadowColor = FLAME; const m = ctx.getTransform(); ctx.shadowBlur = 6 * Math.hypot(m.a, m.b); ctx.stroke(); ctx.shadowBlur = 0;
  ctx.restore();
  shape(ctx, null, ms < 200 ? HOT : RIM);
  flames(ctx, charY, ms, seed, seg(ms, 60, 160) * (1 - seg(ms, 520, 760)));
  ctx.restore();
  const R2 = rng(seed + 11), U = u * 2;
  for (let k = 0; k < 8; k++) {
    const t0 = 140 + R2() * 260, life = 380 + R2() * 260, q = (ms - t0) / life, x0 = (R2() - .5) * 14, vy = 26 + R2() * 30, dx = (R2() - .5) * 16, r = .8 + R2() * 1.1;
    if (q <= 0 || q >= 1) continue;
    ember(ctx, x + (x0 + dx * q + Math.sin(q * 6 + k) * 1.5) * U, y + (4 - vy * easeOut(q)) * U, r * U, (1 - q) * Math.min(1, q * 10), k % 3 === 0);
  }
}

function drawHeart(ctx, x, y, size, state, ms = 0, seed = 0) {
  if (state === 'burn' && ms >= 0 && ms < BURN.ms) return burn(ctx, x, y, size, ms, seed);
  still(ctx, x, y, size, state === 'full' || (state === 'burn' && ms < 0));
}
window.LumaBurn = Object.freeze({ms: BURN.ms, box: Object.freeze(BURN.box), drawHeart});
})();
