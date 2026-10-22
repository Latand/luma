'use strict';
// Luma in the headset (Quest Browser): an immersive-ar session, so the room stays in view through the passthrough, and
// one panel in Luma's own look 1.5 m in front of the eyes, with the song and its status, the readout, the words, the
// chart and the controls. The panel mirrors the page: every label and state on it is read from the page's own elements,
// and a press clicks the page's own button, so the trainer's state stays in app.js alone. The chart is the page's own
// canvas, which app.js draws at the size of its place on the panel on the headset's frames (the window's animation
// frames stop during an immersive session).
//
// A controller's or a hand's ray points. The trigger, a pinch (read from the finger joints) or the session's select
// presses what it points at. The grip, B / Y, a pressed thumbstick or «Сюди» bring the panel in front of the eyes again.
//
// LumaXR.attach(host): app.js hands over what only it can do.
//   chart         the chart's canvas
//   begin(place)  the session started: place = {chart: {width, height}, dpr}, the size to draw the chart at
//   end()         the session ended
//   frame(time)   one frame of the trainer (scoring, readout, chart); true when the chart was drawn again
//   audio()       make and resume the audio context: called inside the click that enters
//   hidden()      the session is hidden (the headset taken off, the Quest menu): stop what plays
//   time()        {t, duration, range: {a, b} or null for the whole song}
//   seek(t), say(text)
(() => {
const $ = id => document.getElementById(id);
const SESSION = {requiredFeatures: [], optionalFeatures: ['local-floor', 'hand-tracking']};
// The panel is laid out in page pixels, UW × UH of them, and is WIDTH metres wide; textures carry PX pixels per page pixel.
const UW = 1280, UH = 800, WIDTH = 1.5, M = WIDTH / UW, PX = 1.6;
const DISTANCE = 1.5, DROP = 0.12;   // in front of the eyes, its centre this far below them (vrplay's cards stand at 1.5 m too)
const CHART = {x: 20, y: 246, w: 1240, h: 342};
const BAR = {x: 92, y: 606, w: 1096, h: 14}, BAR_HIT = {y0: 594, y1: 632};   // the song's progress: a press on it seeks
const ROW1 = 646, ROW2 = 716, BH = 56;
// thumb tip to index tip, metres: a hand pinches below ON and lets go above OFF (the piano trainer's thresholds)
const PINCH_ON = 0.02, PINCH_OFF = 0.04;
const LOOK_BACK = 90;   // ms: a press takes what its ray pointed at this long before; closing a pinch or pulling a trigger jolts it
// app/head.html: :root, .primary, .secondary, .big-note, .pct, .lyric-line
const C = {bg: '#0b0e15', rail: '#0c1018', stage: '#0e131c', border: '#ffffff10', ink1: '#dde5f1', ink2: '#b3c0d2',
  ink3: '#a3b1c6', text: '#e9edf5', mint: '#a1eed8', rose: '#f3a1b5', lav: '#c9bbed', lavInk: '#211a30'};
const WAVE = 'M3 22c5 0 4-14 8-14s3 19 7 19 3-13 7-13 3 5 5 5';   // the brand mark in the page's header

let host = null, run = null, entering = false;

const off = id => { const b = $(id); return !b || b.disabled || b.hidden; };
const click = id => () => { if (!off(id)) $(id).click(); };
const pressed = el => el?.getAttribute('aria-pressed') === 'true';
const busy = () => off('listenBtn');   // the page is preparing or saving: no seeking
const level = (name, label, x) => ({id: 'level-' + name, x, y: ROW2, w: 84, kind: 'seg', label: () => label,
  on: () => pressed(document.querySelector(`[data-level="${name}"]`)),
  off: () => document.querySelector(`[data-level="${name}"]`)?.disabled ?? true,
  press: () => { const b = document.querySelector(`[data-level="${name}"]`); if (b && !b.disabled) b.click(); }});
const BUTTONS = [
  {id: 'sing', x: 20, y: ROW1, w: 230, kind: 'primary', label: () => $('singLabel').textContent, off: () => off('singBtn'),
    rec: () => $('singBtn').classList.contains('recording'), press: click('singBtn')},
  {id: 'listen', x: 260, y: ROW1, w: 170, label: () => $('listenLabel').textContent, off: () => off('listenBtn'), press: click('listenBtn')},
  {id: 'start', x: 440, y: ROW1, w: 150, label: () => 'Спочатку', off: busy, press: () => { const r = host.time(); host.seek(r.range ? r.range.a : 0); }},
  {id: 'back', x: 600, y: ROW1, w: 100, label: () => '−5 с', off: busy, press: () => host.seek(host.time().t - 5)},
  {id: 'ahead', x: 710, y: ROW1, w: 100, label: () => '+5 с', off: busy, press: () => host.seek(host.time().t + 5)},
  {id: 'vocal', x: 840, y: ROW1, w: 140, kind: 'toggle', label: () => $('vocalLabel').textContent, on: () => pressed($('vocalBtn')), press: click('vocalBtn')},
  {id: 'loop', x: 990, y: ROW1, w: 150, kind: 'toggle', label: () => 'Повтор', on: () => pressed($('loopBtn')), press: click('loopBtn')},
  {id: 'speed', x: 1150, y: ROW1, w: 110, label: () => $('speedSelect').value + '×', off: () => $('speedSelect').disabled,
    press: () => { const sel = $('speedSelect'); if (sel.disabled) return; sel.value = sel.value === '1' ? '0.8' : '1'; sel.dispatchEvent(new Event('change')); }},
  {id: 'prev', x: 20, y: ROW2, w: 58, label: () => '‹', off: () => off('prevPhrase'), press: click('prevPhrase')},
  {id: 'next', x: 514, y: ROW2, w: 58, label: () => '›', off: () => off('nextPhrase'), press: click('nextPhrase')},
  {id: 'whole', x: 582, y: ROW2, w: 150, label: () => 'Вся пісня', off: () => off('clearRange'), hide: true, press: click('clearRange')},   // only with a fragment
  level('easy', 'Легко', 762), level('normal', 'Звично', 846), level('strict', 'Точно', 930),
  {id: 'here', x: 1040, y: ROW2, w: 120, label: () => 'Сюди', press: () => { if (run) run.placeWanted = true; }},
  {id: 'exit', x: 1170, y: ROW2, w: 90, label: () => 'Вийти', press: () => run?.session.end().catch(() => {})},
];

function buttonAt(u, v) { return BUTTONS.find(b => u >= b.x && u <= b.x + b.w && v >= b.y && v <= b.y + BH) || null; }
function targetAt(u, v) {
  const button = buttonAt(u, v);
  if (button) return {button};
  if (v >= BAR_HIT.y0 && v <= BAR_HIT.y1 && u >= BAR.x - 8 && u <= BAR.x + BAR.w + 8) return {bar: Math.max(0, Math.min(1, (u - BAR.x) / BAR.w))};
  return null;
}

// ---- what the page shows, read from its elements
function readPage() {
  const status = $('status');
  return {
    title: $('songTitle').textContent, artist: $('artistName').textContent, status: $('statusText').textContent,
    statusKind: status.classList.contains('rec') ? 'rec' : status.classList.contains('live') ? 'live' : '',
    invite: $('invite').hidden ? '' : $('invite').textContent.trim(),
    live: $('liveNote').textContent, liveDesc: $('liveDesc').textContent, liveFreq: $('liveFreq').textContent,
    target: $('targetNote').textContent, deviation: $('deviation').textContent,
    scoreLabel: $('scoreLabel').textContent, pct: $('matchPct').textContent, detail: $('matchDetail').textContent,
    lyrics: !$('lyricBand').hidden, words: [...$('lyricNow').children].map(w => [w.textContent, w.className]), next: $('lyricNext').textContent,
    timeNow: $('timeNow').textContent, timeEnd: $('timeEnd').textContent,
    range: $('rangeText').classList.contains('on') ? $('rangeText').textContent : 'Вся пісня',
    buttons: BUTTONS.map(b => [b.label(), !!b.on?.(), !!b.off?.(), !!b.rec?.()]),
  };
}
function readOver() {
  const count = !$('countdown').hidden, notice = $('livesNotice');
  return {
    count: count ? $('countNumber').textContent : '', hint: count ? $('countdown').querySelector(':scope > span')?.textContent || '' : '',
    notice: count && notice && !notice.hidden ? [$('livesFrom').textContent, notice.querySelector('small')?.textContent || ''] : null,
    error: $('errorBanner').hidden ? '' : $('errorText').textContent,
    toast: $('toast').classList.contains('show') ? $('toast').textContent : '',
  };
}

// ---- drawing the panel in 2D, in page pixels
const fonts = () => { const css = getComputedStyle(document.body); return {sans: css.getPropertyValue('--sans') || 'system-ui', mono: css.getPropertyValue('--mono') || 'monospace'}; };
function fit(g, text, max) {
  if (g.measureText(text).width <= max) return text;
  let lo = 0, hi = text.length;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (g.measureText(text.slice(0, mid) + '…').width <= max) lo = mid; else hi = mid - 1; }
  return text.slice(0, lo).trimEnd() + '…';
}
function lines(g, text, max, count) {
  const out = []; let line = '';
  for (const word of text.split(/\s+/)) {
    const next = line ? line + ' ' + word : word;
    if (g.measureText(next).width <= max || !line) line = next;
    else { out.push(line); line = word; }
  }
  if (line) out.push(line);
  if (out.length > count) { out.length = count; out[count - 1] = fit(g, out[count - 1] + ' …', max); }
  return out;
}
function rr(g, x, y, w, h, r) { g.beginPath(); g.roundRect(x, y, w, h, r); }
function spaced(g, px) { if ('letterSpacing' in g) g.letterSpacing = px + 'px'; }

function drawBase(g, st, hovered, flash) {
  const {sans, mono} = fonts();
  g.clearRect(0, 0, UW, UH);
  g.save(); rr(g, 0, 0, UW, UH, 22); g.clip();
  g.fillStyle = C.bg; g.fillRect(0, 0, UW, UH);
  g.fillStyle = C.rail; g.fillRect(0, 0, UW, 60);
  g.fillStyle = C.stage; g.fillRect(0, 60, UW, 532);
  g.fillStyle = C.border; g.fillRect(0, 59, UW, 1); g.fillRect(0, 592, UW, 1);
  g.restore();
  g.strokeStyle = '#ffffff1c'; g.lineWidth = 1.5; rr(g, .75, .75, UW - 1.5, UH - 1.5, 22); g.stroke();
  g.textBaseline = 'alphabetic';

  // the header: the brand, the song, the status
  g.save(); g.translate(20, 13); g.scale(32 / 34, 32 / 34); g.strokeStyle = C.mint; g.lineWidth = 1.8; g.lineCap = 'round'; g.stroke(new Path2D(WAVE)); g.restore();
  g.font = '500 22px ' + sans; spaced(g, -.6); g.fillStyle = '#e4ecf6'; g.textAlign = 'left'; g.fillText('luma', 60, 38); spaced(g, 0);
  g.font = '600 13px ' + sans; spaced(g, 1.1);
  const sw = g.measureText(st.status).width + 40, sx = UW - 20 - sw;
  g.strokeStyle = C.border; g.lineWidth = 1; rr(g, sx, 12, sw, 36, 8); g.stroke();
  g.fillStyle = st.statusKind === 'rec' ? C.rose : st.statusKind === 'live' ? C.mint : '#8493ab';
  g.beginPath(); g.arc(sx + 17, 30, 3.5, 0, Math.PI * 2); g.fill();
  g.fillStyle = C.ink3; g.fillText(st.status, sx + 28, 35); spaced(g, 0);
  g.font = '700 18px ' + sans; g.fillStyle = C.text;
  const title = fit(g, st.title, sx - 160 - 120); g.fillText(title, 130, 37);
  if (st.artist) {
    const tx = 130 + g.measureText(title).width; g.font = '400 16px ' + sans; g.fillStyle = C.ink3;
    g.fillText(fit(g, '  ·  ' + st.artist, Math.max(0, sx - 24 - tx)), tx, 37);
  }

  // the readout: your voice, the target, the match; or the page's invitation before the first take
  if (st.invite) {
    g.font = '400 18px ' + sans; g.fillStyle = C.ink2;
    lines(g, st.invite, UW - 80, 3).forEach((l, i) => g.fillText(l, 40, 100 + i * 26));
  } else {
    g.save(); g.font = '300 56px ' + sans; spaced(g, -2.4); g.fillStyle = '#cdf3ea'; g.shadowColor = '#a1eed829'; g.shadowBlur = 34;
    g.textAlign = 'center'; g.fillText(st.live, 86, 138); g.restore();
    const kicker = (text, x, align = 'left') => { g.font = '600 12px ' + sans; spaced(g, 1.3); g.fillStyle = C.ink3; g.textAlign = align; g.fillText(text.toUpperCase(), x, 92); spaced(g, 0); };
    kicker('Твій голос', 162);
    g.textAlign = 'left'; g.font = '500 17px ' + sans; g.fillStyle = C.text; g.fillText(fit(g, st.liveDesc, 250), 162, 118);
    g.font = '400 14px ' + mono; g.fillStyle = C.ink3; g.fillText(fit(g, st.liveFreq, 250), 162, 142);
    g.fillStyle = '#ffffff14'; g.fillRect(430, 82, 1, 66);
    kicker('Ціль', 456);
    g.textAlign = 'left'; g.font = '700 19px ' + sans; g.fillStyle = C.text; g.fillText(st.target, 456, 119);
    g.font = '400 15px ' + sans; g.fillStyle = C.ink2; g.fillText(fit(g, st.deviation, 400), 456, 143);
    kicker(st.scoreLabel, 1244, 'right');
    g.textAlign = 'right'; g.font = '500 52px ' + sans; spaced(g, -2.4); g.fillStyle = '#eaf1fa'; g.fillText(st.pct, 1244, 142); spaced(g, 0);
    g.font = '400 13px ' + sans; g.fillStyle = C.ink3; g.fillText(fit(g, st.detail, 360), 1244, 175);   // the level meter runs above it (Run.draw)
  }

  // the words: the line now, each word lit as it is sung, and the next line
  if (st.lyrics && st.words.length) {
    const parts = st.words.map(([w, cls]) => ({w, cls, font: (cls === 'on' ? '600 ' : '400 ') + '28px ' + sans}));
    let total = 0; for (const p of parts) { g.font = p.font; p.width = g.measureText(p.w).width; total += p.width; }
    const k = Math.min(1, (UW - 80) / total);
    g.save(); g.translate(UW / 2 - total * k / 2, 212); g.scale(k, k); g.textAlign = 'left'; let x = 0;
    for (const p of parts) { g.font = p.font; g.fillStyle = p.cls === 'on' ? '#f2f8ff' : p.cls ? '#98a6bc' : C.ink2; g.fillText(p.w, x, 0); x += p.width; }
    g.restore();
  }
  if (st.lyrics && st.next) { g.textAlign = 'center'; g.font = '400 19px ' + sans; g.fillStyle = '#96a4ba'; g.fillText(fit(g, st.next, UW - 120), UW / 2, 239); }

  // the song's time and the track of its progress bar (the bar itself moves with the frames)
  g.font = '400 15px ' + mono; g.fillStyle = C.ink2; g.textAlign = 'left'; g.fillText(st.timeNow, 20, 619);
  g.textAlign = 'right'; g.fillText(st.timeEnd, UW - 20, 619);
  g.fillStyle = '#ffffff0d'; rr(g, BAR.x, BAR.y, BAR.w, BAR.h, 7); g.fill();

  // the controls
  g.font = '400 15px ' + sans; g.fillStyle = C.ink2; g.textAlign = 'center';
  g.fillText(fit(g, st.range, 420), (78 + 514) / 2 + 3, ROW2 + 34);
  g.strokeStyle = '#ffffff1c'; g.lineWidth = 1; rr(g, 760, ROW2, 256, BH, 10); g.stroke();
  BUTTONS.forEach((b, i) => {
    const [label, on, disabled, rec] = st.buttons[i], hover = hovered.has(b.id) && !disabled, lit = flash === b.id;
    if (disabled && b.hide) return;
    g.save(); if (disabled) g.globalAlpha = .4;
    let fill = '#ffffff05', stroke = '#ffffff1c', ink = '#c8d2e2';
    if (b.kind === 'primary') { fill = rec ? '#3b2736' : hover ? '#d8ccf5' : C.lav; stroke = rec ? '#f3a1b552' : null; ink = rec ? '#ffdae3' : C.lavInk; }
    else if (b.kind === 'seg') { fill = on ? '#ffffff17' : hover ? '#ffffff0c' : null; stroke = null; ink = on ? C.text : C.ink3; }
    else { if (on) { fill = '#a1eed814'; stroke = '#a1eed855'; ink = C.mint; } if (hover) { fill = on ? '#a1eed826' : '#ffffff14'; stroke = '#ffffff40'; } }
    if (lit) fill = b.kind === 'primary' && !rec ? '#efe8ff' : '#ffffff2e';
    const inset = b.kind === 'seg' ? 4 : 0;
    if (fill) { g.fillStyle = fill; rr(g, b.x + inset, b.y + inset, b.w - 2 * inset, BH - 2 * inset, b.kind === 'seg' ? 7 : 10); g.fill(); }
    if (stroke) { g.strokeStyle = stroke; g.lineWidth = 1.2; rr(g, b.x + .6, b.y + .6, b.w - 1.2, BH - 1.2, 10); g.stroke(); }
    g.fillStyle = ink; g.font = (b.kind === 'primary' ? '700 ' : '600 ') + (b.id === 'prev' || b.id === 'next' ? '28px ' : '17px ') + sans;
    g.textAlign = 'center'; g.fillText(fit(g, label, b.w - 20), b.x + b.w / 2, b.y + BH / 2 + (b.id === 'prev' || b.id === 'next' ? 9 : 6));
    g.restore();
  });
}

// what lies over the chart: the countdown, an error and the page's toast; transparent elsewhere
function drawOver(g, st) {
  const {sans, mono} = fonts(), w = CHART.w, h = CHART.h;
  g.clearRect(0, 0, w, h);
  if (st.count) {
    const r = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, h * .9);
    r.addColorStop(0, '#0f1723e0'); r.addColorStop(.64, '#0b0f1700'); g.fillStyle = r; g.fillRect(0, 0, w, h);
    g.textAlign = 'center';
    if (st.notice) { g.font = '700 20px ' + sans; g.fillStyle = C.rose; g.fillText(st.notice[0], w / 2, h / 2 - 78); g.font = '400 14px ' + sans; g.fillStyle = '#c8d8dc'; g.fillText(st.notice[1], w / 2, h / 2 - 56); }
    g.font = '300 84px ' + mono; g.fillStyle = C.mint; g.fillText(st.count, w / 2, h / 2 + 22);
    g.font = '400 16px ' + sans; g.fillStyle = '#c8d8dc'; g.fillText(st.hint, w / 2, h / 2 + 58);
  }
  if (st.error) {
    g.font = '500 16px ' + sans; const text = lines(g, st.error, w - 80, 2);
    g.fillStyle = '#2a1820f0'; rr(g, 16, 12, w - 32, 24 + text.length * 22, 10); g.fill();
    g.strokeStyle = '#f3a1b566'; g.lineWidth = 1; g.stroke();
    g.fillStyle = '#ffd6df'; g.textAlign = 'left'; text.forEach((l, i) => g.fillText(l, 36, 40 + i * 22));
  }
  if (st.toast) {
    g.font = '500 16px ' + sans; const text = lines(g, st.toast, 860, 2), tw = Math.max(...text.map(l => g.measureText(l).width)) + 44, th = 22 + text.length * 22;
    g.fillStyle = '#141a26f2'; rr(g, (w - tw) / 2, h - th - 16, tw, th, 12); g.fill();
    g.strokeStyle = '#ffffff1f'; g.lineWidth = 1; g.stroke();
    g.fillStyle = C.ink1; g.textAlign = 'center'; text.forEach((l, i) => g.fillText(l, w / 2, h - th - 16 + 27 + i * 22));
  }
}

// ---- WebGL: textured and plain quads in the panel's plane, the rays in the room
const VS = `#version 300 es
layout(location=0) in vec2 aPos;
uniform mat4 uProj, uView, uModel;
uniform vec4 uRect, uUv;
uniform float uZ;
out vec2 vUv;
void main() { vUv = mix(uUv.xy, uUv.zw, aPos); gl_Position = uProj * uView * uModel * vec4(mix(uRect.xy, uRect.zw, aPos), uZ, 1.0); }`;
const FS = `#version 300 es
precision mediump float;
in vec2 vUv;
uniform sampler2D uTex;
uniform vec4 uColor;
out vec4 outColor;
void main() { outColor = texture(uTex, vUv) * vec4(uColor.rgb * uColor.a, uColor.a); }`;
const rgba = (hex, a = 1) => [parseInt(hex.slice(1, 3), 16) / 255, parseInt(hex.slice(3, 5), 16) / 255, parseInt(hex.slice(5, 7), 16) / 255, a];

class Gl {
  constructor(gl) {
    this.gl = gl;
    const shader = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s)); return s; };
    const p = this.program = gl.createProgram();
    gl.attachShader(p, shader(gl.VERTEX_SHADER, VS)); gl.attachShader(p, shader(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(p));
    this.u = {}; for (const n of ['uProj', 'uView', 'uModel', 'uRect', 'uUv', 'uZ', 'uTex', 'uColor']) this.u[n] = gl.getUniformLocation(p, n);
    this.vao = gl.createVertexArray(); gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    this.aniso = gl.getExtension('EXT_texture_filter_anisotropic');
    this.white = this.texture(); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([255, 255, 255, 255]));
    const dot = document.createElement('canvas'); dot.width = dot.height = 64; const d = dot.getContext('2d');
    const r = d.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, '#fff'); r.addColorStop(.45, '#fff'); r.addColorStop(.62, '#ffffff66'); r.addColorStop(1, '#fff0');
    d.fillStyle = r; d.fillRect(0, 0, 64, 64); this.dot = this.texture(); this.upload(this.dot, dot);
  }
  texture() {
    const gl = this.gl, t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    return t;
  }
  // a canvas into a texture, premultiplied, with mipmaps: the panel is seen smaller than its texture. The chart, sent
  // again on every frame that redraws it (every frame while the song plays), goes without: on the emulator its mipmaps
  // cost a fifth of the frame rate (tests/e2e/xr_perf.mjs), and a Quest 3 shows it at about 1.5–2 texels a pixel.
  upload(t, canvas, mip = true) {
    const gl = this.gl; gl.bindTexture(gl.TEXTURE_2D, t);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    if (mip) gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mip ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
    if (this.aniso) gl.texParameterf(gl.TEXTURE_2D, this.aniso.TEXTURE_MAX_ANISOTROPY_EXT, 4);
  }
  begin(proj, view) {
    const gl = this.gl; gl.useProgram(this.program); gl.bindVertexArray(this.vao);
    gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniformMatrix4fv(this.u.uProj, false, proj); gl.uniformMatrix4fv(this.u.uView, false, view); gl.uniform1i(this.u.uTex, 0); gl.activeTexture(gl.TEXTURE0);
  }
  // rect: x0, y0 (the texture's top left), x1, y1 in the model's plane
  quad(model, rect, tex, color = [1, 1, 1, 1], z = 0, uv = [0, 0, 1, 1]) {
    const gl = this.gl; gl.uniformMatrix4fv(this.u.uModel, false, model); gl.uniform4fv(this.u.uRect, rect); gl.uniform4fv(this.u.uUv, uv);
    gl.uniform1f(this.u.uZ, z); gl.uniform4fv(this.u.uColor, color); gl.bindTexture(gl.TEXTURE_2D, tex); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
}

// page pixels on the panel → its plane, metres, y up
const px = (x, y, w, h) => [(x - UW / 2) * M, (UH / 2 - y) * M, (x + w - UW / 2) * M, (UH / 2 - y - h) * M];
const IDENTITY = new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

class Run {
  constructor(session, gl, view) {
    this.session = session; this.view = view; this.gl = gl; this.r = new Gl(gl);
    this.space = null; this.panel = null; this.placeWanted = true; this.frames = 0;
    this.sources = new Map();   // input source → {down, pinch, events, tapped, here, history: [{t, target}]}
    this.hovered = new Set(); this.flash = null; this.rays = [];
    const canvas = (w, h) => { const c = document.createElement('canvas'); c.width = Math.round(w * PX); c.height = Math.round(h * PX); const g = c.getContext('2d'); g.scale(PX, PX); return {c, g}; };
    this.base = canvas(UW, UH); this.over = canvas(CHART.w, CHART.h);
    this.baseTex = this.r.texture(); this.overTex = this.r.texture(); this.chartTex = this.r.texture();
    this.baseKey = ''; this.overKey = ''; this.overShown = false; this.chartReady = false;
    if (typeof window !== 'undefined') window.__lumaXr = this;
  }

  async start() {
    const {session, gl} = this;
    await gl.makeXRCompatible();
    session.updateRenderState({baseLayer: new XRWebGLLayer(session, gl, {alpha: true, antialias: true})});
    try { this.space = await session.requestReferenceSpace('local-floor'); } catch { this.space = await session.requestReferenceSpace('local'); }
    this.space.addEventListener?.('reset', () => { this.placeWanted = true; });
    const source = e => { let st = this.sources.get(e.inputSource); if (!st) this.sources.set(e.inputSource, st = {down: false, pinch: false, events: 0, tapped: false, here: false, history: []}); return st; };
    session.addEventListener('selectstart', e => { const st = source(e); st.events++; st.tapped = true; });
    session.addEventListener('selectend', e => { const st = source(e); st.events = Math.max(0, st.events - 1); });
    session.addEventListener('squeezestart', () => { this.placeWanted = true; });
    session.addEventListener('inputsourceschange', e => { for (const s of e.removed || []) this.sources.delete(s); });
    session.addEventListener('visibilitychange', () => { if (session.visibilityState === 'hidden') host.hidden(); for (const st of this.sources.values()) { st.events = 0; st.tapped = false; } });
    session.addEventListener('end', () => this.ended());
    document.body.classList.add('in-xr');
    host.begin({chart: {width: CHART.w, height: CHART.h}, dpr: PX});
    session.requestAnimationFrame((t, f) => this.frame(t, f));
  }

  ended() {
    document.body.classList.remove('in-xr');
    if (run === this) run = null;
    host.end();
  }

  // the panel 1.5 m along the gaze, levelled, a little below the eyes and facing them
  place(head) {
    const m = head.matrix, p = [m[12], m[13], m[14]];
    let f = [-m[8], 0, -m[10]]; if (Math.hypot(f[0], f[2]) < 1e-3) f = [0, 0, -1]; f = unit(f);
    const c = [p[0] + f[0] * DISTANCE, p[1] - DROP, p[2] + f[2] * DISTANCE], yaw = Math.atan2(-f[0], -f[2]);
    const cs = Math.cos(yaw), sn = Math.sin(yaw);
    this.panel = {c, cs, sn, model: new Float32Array([cs, 0, -sn, 0, 0, 1, 0, 0, sn, 0, cs, 0, c[0], c[1], c[2], 1])};
    this.placeWanted = false;
  }

  // a ray in the room against the panel's face → {u, v} in page pixels and the point, or null
  hit(o, d) {
    const {c, cs, sn} = this.panel, q = sub(o, c);
    const lo = [cs * q[0] - sn * q[2], q[1], sn * q[0] + cs * q[2]], ld = [cs * d[0] - sn * d[2], d[1], sn * d[0] + cs * d[2]];
    if (ld[2] >= -1e-6 || lo[2] <= 0) return null;
    const k = -lo[2] / ld[2], u = (lo[0] + k * ld[0]) / M + UW / 2, v = UH / 2 - (lo[1] + k * ld[1]) / M;
    if (u < 0 || u > UW || v < 0 || v > UH) return null;
    return {u, v, point: [o[0] + k * d[0], o[1] + k * d[1], o[2] + k * d[2]]};
  }

  input(f, time) {
    this.hovered = new Set(); this.rays = [];
    const seen = new Set();
    for (const src of this.session.inputSources) {
      seen.add(src);
      let st = this.sources.get(src);
      if (!st) this.sources.set(src, st = {down: false, pinch: false, events: 0, tapped: false, here: false, history: []});
      const pose = src.targetRaySpace && f.getPose(src.targetRaySpace, this.space);
      let target = null;
      if (pose) {
        const m = pose.transform.matrix, o = [m[12], m[13], m[14]], d = unit([-m[8], -m[9], -m[10]]), hit = this.hit(o, d);
        target = hit && targetAt(hit.u, hit.v);
        this.rays.push({o, d, hit, on: !!target});
        if (target?.button) this.hovered.add(target.button.id);
      }
      st.history.push({t: time, target}); while (st.history.length > 1 && st.history[0].t < time - 300) st.history.shift();
      let trigger = false, here = false;
      if (src.hand) {
        const tip = n => { const j = src.hand.get(n); return j && f.getJointPose(j, this.space); }, a = tip('thumb-tip'), b = tip('index-finger-tip');
        if (a && b) { const pa = a.transform.position, pb = b.transform.position, gap = Math.hypot(pa.x - pb.x, pa.y - pb.y, pa.z - pb.z); st.pinch = st.pinch ? gap < PINCH_OFF : gap < PINCH_ON; }
      } else if (src.gamepad) {
        const b = src.gamepad.buttons; trigger = !!b[0]?.pressed; here = !!(b[1]?.pressed || b[3]?.pressed || b[5]?.pressed);
      }
      const down = st.pinch || trigger || st.events > 0 || st.tapped; st.tapped = false;
      if (down && !st.down) this.press(st.history, time);
      st.down = down;
      if (here && !st.here) this.placeWanted = true;
      st.here = here;
    }
    for (const src of [...this.sources.keys()]) if (!seen.has(src)) this.sources.delete(src);
  }

  // what the ray pointed at just before the press; what it points at now when it pointed at nothing then
  press(history, time) {
    let then = null; for (const h of history) if (h.t <= time - LOOK_BACK) then = h;
    const target = then?.target || history[history.length - 1]?.target;
    if (!target) return;
    if (target.bar !== undefined) { if (!busy()) host.seek(target.bar * host.time().duration); return; }
    const b = target.button; if (b.off?.()) return;
    this.flash = {id: b.id, until: time + 160};
    b.press();
  }

  frame(time, f) {
    const {session, gl, r} = this;
    if (run !== this) return;
    session.requestAnimationFrame((t, fr) => this.frame(t, fr));
    const pose = f.getViewerPose(this.space);
    if (!pose) return;
    if (this.placeWanted || !this.panel) this.place(pose.transform);
    this.input(f, time);
    if (host.frame(time) || !this.chartReady) { r.upload(this.chartTex, host.chart, false); this.chartReady = true; }
    if (this.flash && time > this.flash.until) this.flash = null;
    const st = readPage(), key = JSON.stringify(st) + [...this.hovered].join() + (this.flash?.id || '');
    if (key !== this.baseKey) { this.baseKey = key; drawBase(this.base.g, st, this.hovered, this.flash?.id); r.upload(this.baseTex, this.base.c); }
    const ov = readOver(), okey = JSON.stringify(ov);
    if (okey !== this.overKey) { this.overKey = okey; this.overShown = !!(ov.count || ov.error || ov.toast); drawOver(this.over.g, ov); if (this.overShown) r.upload(this.overTex, this.over.c); }
    this.frames++;

    const layer = session.renderState.baseLayer;
    gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    const head = pose.transform.position, eye = [head.x, head.y, head.z];
    for (const view of pose.views) {
      const vp = layer.getViewport(view); gl.viewport(vp.x, vp.y, vp.width, vp.height);
      r.begin(view.projectionMatrix, view.transform.inverse.matrix);
      this.draw(eye);
    }
  }

  draw(eye) {
    const {r} = this, m = this.panel.model, time = host.time();
    r.quad(m, px(0, 0, UW, UH), this.baseTex);
    r.quad(m, px(CHART.x, CHART.y, CHART.w, CHART.h), this.chartTex, undefined, .001);
    if (this.overShown) r.quad(m, px(CHART.x, CHART.y, CHART.w, CHART.h), this.overTex, undefined, .002);
    // the progress bar: the fragment that repeats, what has played, the playhead
    const x = t => BAR.x + BAR.w * Math.max(0, Math.min(1, t / time.duration));
    if (time.range) r.quad(m, px(x(time.range.a), BAR.y, x(time.range.b) - x(time.range.a), BAR.h), r.white, rgba(C.lav, .35), .001);
    r.quad(m, px(BAR.x, BAR.y + 4, x(time.t) - BAR.x, BAR.h - 8), r.white, rgba(C.mint, .55), .0012);
    r.quad(m, px(x(time.t) - 1.5, BAR.y - 6, 3, BAR.h + 12), r.white, rgba('#eaf1fa', .95), .0014);
    // the voice's level, under the match, as the page's meter
    if ($('invite').hidden) {
      const lv = $('level'), w = parseFloat(lv.style.width) || 0;
      r.quad(m, px(900, 154, 344, 4), r.white, rgba('#ffffff', .06), .001);
      if (w > 0) r.quad(m, px(900, 154, 344 * w / 100, 4), r.white, clipped(lv) ? rgba(C.rose, .9) : rgba(C.mint, .9), .0012);
    }
    // where each ray meets the panel, and the rays themselves
    for (const ray of this.rays) {
      const end = ray.hit ? ray.hit.point : [ray.o[0] + ray.d[0] * 3, ray.o[1] + ray.d[1] * 3, ray.o[2] + ray.d[2] * 3];
      const len = Math.hypot(...sub(end, ray.o)), side = unit(cross(ray.d, sub(eye, ray.o))), n = cross(side, ray.d), wd = .003;
      const model = new Float32Array([side[0] * wd, side[1] * wd, side[2] * wd, 0, ray.d[0] * len, ray.d[1] * len, ray.d[2] * len, 0, n[0], n[1], n[2], 0,
        ray.o[0] - side[0] * wd / 2, ray.o[1] - side[1] * wd / 2, ray.o[2] - side[2] * wd / 2, 1]);
      r.quad(model, [0, 0, 1, 1], r.white, ray.on ? rgba(C.mint, .75) : rgba('#ffffff', .3));
      if (ray.hit) { const s = 9; r.quad(m, px(ray.hit.u - s, ray.hit.v - s, 2 * s, 2 * s), r.dot, ray.on ? rgba(C.mint, 1) : rgba('#ffffff', .85), .003); }
    }
  }
}
// the page paints its meter rose when the voice clips (app.js updateReadout); the browser keeps the colour as rgb()
const clipped = el => /243,\s*161,\s*181|f3a1b5/i.test(el.style.background);

async function micAllowed() {
  try { return (await navigator.permissions.query({name: 'microphone'})).state === 'granted'; } catch { return false; }
}

// Inside the click: the audio context is made and resumed here, so presses in the headset need no click of their own.
// The headset cannot ask for the microphone inside the session, so it is asked first; when that took long enough for
// the click to lapse, the session is refused and the next press of «VR» enters.
async function enter() {
  if (run || entering || !host) return;
  entering = true;
  host.audio()?.catch?.(() => {});
  try {
    let mic = 'allowed';   // before this press; 'asked' when it was just granted, 'denied' when it was refused
    if (!(await micAllowed())) {
      try { const stream = await navigator.mediaDevices.getUserMedia({audio: true}); stream.getTracks().forEach(t => t.stop()); mic = 'asked'; }
      catch (_) { mic = 'denied'; host.say('Без мікрофона в шоломі можна тільки слухати. Дозволь мікрофон для цієї сторінки, щоб співати.'); }
    }
    let session;
    try { session = await navigator.xr.requestSession('immersive-ar', SESSION); }
    catch (e) {
      // one toast at a time: the refusal's replaces the microphone's, so it repeats what the microphone allows
      host.say(e?.name === 'NotSupportedError' ? 'Цей браузер не відкриває VR з видом кімнати.'
        : (mic === 'asked' ? 'Мікрофон дозволено. ' : mic === 'denied' ? 'Без мікрофона в шоломі можна тільки слухати. ' : 'VR не відкрився. ') + 'Натисни «VR» ще раз, щоб увійти.');
      return;
    }
    const view = $('xrView'), gl = view.getContext('webgl2', {xrCompatible: true, alpha: true, antialias: true});
    if (!gl) { session.end().catch(() => {}); host.say('Немає WebGL2: VR не запуститься.'); return; }
    view.width = Math.round(innerWidth * (devicePixelRatio || 1)); view.height = Math.round(innerHeight * (devicePixelRatio || 1));
    run = new Run(session, gl, view);
    try { await run.start(); } catch (e) { run = null; session.end().catch(() => {}); host.say('VR не запустився: ' + (e?.message || e)); }
  } finally { entering = false; }
}

async function attach(h) {
  host = h;
  const btn = $('xrBtn');
  if (!btn) return;
  btn.onclick = enter;
  let ok = false;
  try { ok = !!(navigator.xr && await navigator.xr.isSessionSupported('immersive-ar')); } catch (_) {}
  btn.hidden = !ok;
}

window.LumaXR = {attach, layout: {UW, UH, CHART, BAR, BUTTONS: BUTTONS.map(b => ({id: b.id, x: b.x, y: b.y, w: b.w, h: BH}))}};
})();
