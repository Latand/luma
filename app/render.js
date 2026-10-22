'use strict';
// The game layer of a camera video (docs/design/CAMERA_VIDEO_BUILD_BRIEF.md §5.3). Studio opens the trainer at
// /video/<id>/render in a headless browser; app.js draws the stage of each frame with its own code (Luma.render), this file
// draws on the same canvas what the trainer shows in the DOM — the hearts with the burn of app/burn.js, the match %, the
// lyric band, the count-in of a lives rewind — plus the dark seat of the camera circle, encodes every frame with
// WebCodecs H.264 and streams it to Studio. On every other page it only defines LumaRender and does nothing.
// ?hold=1 loads the take and stops, so a test can call Luma.render.frame(u) itself.
(() => {
const FPS = 30, W = 1920, H = 1080, SEAT = {x: 222, y: 720, r: 150};
// the last heart's burn glow reaches 2.4 sizes (86 px) from its centre and must end before the box of the match %
const HEART = {size: 36, pitch: 44, y: 92, last: 1636}, PCT = {x: 1740, y: 84};
const BAND = {top: 900, bottom: 1060, max: 1700, now: 44, min: 30, next: 30};
const font = (w, px) => w + ' ' + px + 'px ' + (getComputedStyle(document.body).getPropertyValue('--sans') || 'sans-serif');
const mono = (w, px) => w + ' ' + px + 'px ' + (getComputedStyle(document.body).getPropertyValue('--mono') || 'monospace');
// the lifeRefill keyframes of app/head.html: 0 % → opacity 0, ×0.3; 70 % → 1, ×1.25; 100 % → ×1, eased like var(--ease)
const ease = x => 1 - (1 - Math.max(0, Math.min(1, x))) ** 3;
function refillPose(ms) {
  const p = ms / 450; if (p <= 0) return {a: 0, k: .3}; if (p >= 1) return {a: 1, k: 1};
  if (p < .7) { const q = ease(p / .7); return {a: q, k: .3 + .95 * q}; }
  return {a: 1, k: 1.25 - .25 * ease((p - .7) / .3)};
}
let row = null;
function hearts(g, info) {
  const B = window.LumaBurn; if (!B || !info.total) return;
  const n = info.total, s = HEART.size, bw = (n - 1) * HEART.pitch + (B.box.l + B.box.r) * s, bh = (B.box.t + B.box.b) * s;
  if (!row || row.width !== Math.ceil(bw) || row.height !== Math.ceil(bh)) { row = document.createElement('canvas'); row.width = Math.ceil(bw); row.height = Math.ceil(bh); }
  // the burn's glow composites with 'lighter': drawn into a transparent row first, then onto the frame (LIFE_BURN.md §4)
  const c = row.getContext('2d'); c.clearRect(0, 0, row.width, row.height);
  const x0 = B.box.l * s, y0 = B.box.t * s, burns = new Map(info.burns.map(b => [b.i, b.ms])), wait = new Map((info.refill?.wait || []).map(w => [w.i, w.ms]));
  for (let i = 0; i < n; i++) {
    const x = x0 + i * HEART.pitch, burning = burns.has(i) && burns.get(i) < B.ms;
    if (info.refill) {
      B.drawHeart(c, x, y0, s, 'lost');
      const pose = refillPose(info.refill.ms - i * 45 - (wait.get(i) || 0));
      if (pose.a > 0) { c.save(); c.globalAlpha = pose.a; c.translate(x, y0 + s * .1); c.scale(pose.k, pose.k); c.translate(-x, -(y0 + s * .1)); B.drawHeart(c, x, y0, s, 'full'); c.restore(); }
      if (burning) B.drawHeart(c, x, y0, s, 'burn', burns.get(i), i);
    } else if (burning) B.drawHeart(c, x, y0, s, 'burn', burns.get(i), i);
    else B.drawHeart(c, x, y0, s, i < info.left ? 'full' : 'lost');
  }
  g.drawImage(row, HEART.last - (n - 1) * HEART.pitch - x0, HEART.y - y0);
}
function match(g, info) {
  const pct = info.pct; g.save(); g.textAlign = 'left'; g.textBaseline = 'middle';
  g.font = font(500, 60); g.fontVariantNumeric = 'tabular-nums'; g.letterSpacing = '-2px';
  g.fillStyle = pct === null ? '#eaf1fa' : pct >= 70 ? '#b7f3e1' : pct < 40 ? '#f0b5bb' : '#eaf1fa';
  // the halo the stage gives words riding the melody, so the number reads over a note bar as well
  const text = pct === null ? '—' : pct + '%', w = Math.max(g.measureText(text).width, 40), ink = g.fillStyle;
  g.fillStyle = '#0c111aec'; g.beginPath(); g.roundRect(PCT.x - 12, PCT.y - 40, w + 24, 98, 8); g.fill();
  g.fillStyle = ink; g.fillText(text, PCT.x, PCT.y);
  g.letterSpacing = '2px'; g.font = font(400, 22); g.fillStyle = '#a3b1c6'; g.fillText('ЗБІГ', PCT.x + 2, PCT.y + 42); g.restore();
}
// The current line with the sung word lit and underlined, the next line dimmed; a line too long for 1700 px shrinks to
// 30 px, then wraps onto two lines and the next line steps aside. Never an ellipsis.
function band(g, info) {
  const L = info.lyric; if (!L || !L.words.length) return;
  g.save(); g.textBaseline = 'middle'; g.textAlign = 'left'; g.shadowColor = '#0b0e15'; g.shadowBlur = 14; g.shadowOffsetY = 2;
  const color = st => st === 'on' ? '#f2f8ff' : st === 'past' || st === 'soon' ? '#98a6bc' : '#b3c0d2';
  const width = (px, ws) => { let w = 0; for (const x of ws) { g.font = font(x.state === 'on' ? 600 : 400, px); w += g.measureText(x.w + ' ').width; } return w; };
  let px = BAND.now; while (px > BAND.min && width(px, L.words) > BAND.max) px--;
  let lines = [L.words];
  if (width(px, L.words) > BAND.max) { lines = [[]]; for (const w of L.words) { const cur = lines.at(-1); if (cur.length && width(px, [...cur, w]) > BAND.max) lines.push([w]); else cur.push(w); } }
  const next = lines.length === 1 && L.next ? L.next : '', lh = px * 1.3, total = lines.length * lh + (next ? 6 + BAND.next * 1.35 : 0);
  let y = BAND.top + (BAND.bottom - BAND.top - total) / 2 + lh / 2;
  for (const ln of lines) {
    let x = (W - width(px, ln)) / 2;
    for (const w of ln) {
      g.font = font(w.state === 'on' ? 600 : 400, px); g.fillStyle = color(w.state); g.fillText(w.w, x, y);
      const tw = g.measureText(w.w).width; if (w.state === 'on') { g.fillStyle = '#a1eed8'; g.fillRect(x, y + px * .55, tw, Math.max(2, px / 16)); }
      x += g.measureText(w.w + ' ').width;
    }
    y += lh;
  }
  if (next) {
    g.font = font(400, BAND.next); let text = next;
    if (g.measureText(text).width > BAND.max) { const ws = text.split(' '); while (ws.length > 1 && g.measureText(ws.join(' ')).width > BAND.max) ws.pop(); text = ws.join(' '); }
    g.fillStyle = '#96a4ba'; g.textAlign = 'center'; g.fillText(text, W / 2, y - lh / 2 + 6 + BAND.next * 1.35 / 2);
  }
  g.restore();
}
// Where the camera sits: a dark disc and its ring, every frame, so the circle reads even where the camera has ended.
function seat(g) {
  g.save(); g.shadowColor = '#000000a0'; g.shadowBlur = 28; g.fillStyle = '#0b0e15';
  g.beginPath(); g.arc(SEAT.x, SEAT.y, SEAT.r + 5, 0, Math.PI * 2); g.fill(); g.shadowBlur = 0;
  g.strokeStyle = '#a1eed8aa'; g.lineWidth = 5; g.beginPath(); g.arc(SEAT.x, SEAT.y, SEAT.r + 2.5, 0, Math.PI * 2); g.stroke(); g.restore();
}
// The count-in of a lives rewind, the trainer's #countdown scaled for 1080p, on a panel of its own so no note or word of
// the dimmed roll runs through its text.
function countIn(g, info) {
  if (info.count === null) return;
  g.save(); const wash = g.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, W * .64 / 2 * 1.15);
  wash.addColorStop(0, '#0f1723e0'); wash.addColorStop(1, '#0b0f1700'); g.fillStyle = wash; g.fillRect(0, 0, W, H);
  const lines = [], prompt = 'Приготуйся. Вдихни спокійно.';
  let y = 420;
  if (info.notice) { lines.push([font(600, 40), '#f3a1b5', info.notice, y], [font(400, 24), '#c8d8dc', 'Забагато промахів поспіль · життя відновлено', y + 48]); y += 92; }
  lines.push([mono(300, 110), '#a1eed8', String(info.count), y + 70], [font(400, 24), '#c8d8dc', prompt, y + 158]);
  let w = 0; for (const [f, , text] of lines) { g.font = f; w = Math.max(w, g.measureText(text).width); }
  const top = lines[0][3] - 50, bottom = lines.at(-1)[3] + 36;
  g.fillStyle = '#0c111a'; g.beginPath(); g.roundRect(W / 2 - w / 2 - 48, top, w + 96, bottom - top, 8); g.fill();
  g.textAlign = 'center'; g.textBaseline = 'middle';
  for (const [f, ink, text, ly] of lines) { g.font = f; g.fillStyle = ink; g.fillText(text, W / 2, ly); }
  window.LumaRender.panel = [W / 2 - w / 2 - 48, top, W / 2 + w / 2 + 48, bottom];
  g.restore();
}
// app.js draws the stage at 960×540 and DPR 2; the overlays are laid out in the frame's own 1920×1080 pixels
function overlay(g, info) { g.save(); g.setTransform(1, 0, 0, 1, 0, 0); window.LumaRender.panel = null; seat(g); hearts(g, info); match(g, info); band(g, info); countIn(g, info); g.restore(); }
// What the roll must stay clear of, in frame pixels: the heart row with the whole box its burn paints, the % box, the circle.
function hud(total) {
  const B = window.LumaBurn, s = HEART.size, first = HEART.last - (total - 1) * HEART.pitch;
  return {hearts: [first - B.box.l * s, HEART.y - B.box.t * s, HEART.last + B.box.r * s, HEART.y + B.box.b * s], pct: [PCT.x - 12, PCT.y - 40, W, PCT.y + 58], seat: {...SEAT, r: SEAT.r + 5}};
}
window.LumaRender = {overlay, hud, panel: null, ready: null, done: false};

if (!/^\/video\/[0-9a-f-]{36}\/render$/.test(location.pathname) || !window.Luma?.render) return;
const base = location.pathname.replace(/render$/, ''), hold = new URLSearchParams(location.search).has('hold');
async function put(seq, parts, frames) {
  const res = await fetch(base + 'game?seq=' + seq + '&frames=' + frames, {method: 'PUT', body: new Blob(parts)});
  if (!res.ok) throw Error('Studio відмовив у шарі гри: ' + res.status);
}
(async () => {
  try {
    const res = await fetch(base + 'take'); if (!res.ok) throw Error('немає запису спроби: ' + res.status);
    const plan = window.Luma.render.load(await res.json()); window.LumaRender.ready = plan;
    if (hold) return;
    if (typeof VideoEncoder === 'undefined') throw Error('VideoEncoder недоступний');
    let config = {codec: 'avc1.640028', avc: {format: 'annexb'}, width: W, height: H, bitrate: 6e6, framerate: FPS, latencyMode: 'quality'};
    if (!(await VideoEncoder.isConfigSupported(config)).supported) config = {...config, codec: 'avc1.4D0028'};
    let failed = null, parts = [], size = 0, seq = 0, sending = Promise.resolve();
    const enc = new VideoEncoder({output: chunk => { const b = new Uint8Array(chunk.byteLength); chunk.copyTo(b); parts.push(b); size += b.byteLength; }, error: e => { failed = e; }});
    enc.configure(config);
    const canvas = document.getElementById('chart'), flush = frames => { const p = parts; parts = []; size = 0; const n = seq++; sending = sending.then(() => put(n, p, frames)); return sending; };
    for (let f = 0; f < plan.frames; f++) {
      if (failed) throw failed;
      await window.Luma.render.frame(f / FPS);
      const vf = new VideoFrame(canvas, {timestamp: Math.round(f * 1e6 / FPS), duration: Math.round(1e6 / FPS)});
      enc.encode(vf, {keyFrame: f % 60 === 0}); vf.close();
      while (enc.encodeQueueSize > 8) await new Promise(ok => enc.addEventListener('dequeue', ok, {once: true}));
      if (size > 1 << 20) await flush(f + 1);
    }
    await enc.flush(); if (failed) throw failed; await flush(plan.frames); enc.close();
    const ok = await fetch(base + 'rendered', {method: 'POST'}); if (!ok.ok) throw Error('Studio не прийняв кінець: ' + ok.status);
    window.LumaRender.done = true;
  } catch (e) {
    await fetch(base + 'render-failed', {method: 'POST', body: String(e && e.message || e)}).catch(() => {});
  }
})();
})();
