// Camera video of a sitting (docs/design/CAMERA_VIDEO_BUILD_BRIEF.md §8): the switch off by default and off outside
// Studio, one prompt and one recorder per sitting, the capture Studio stores, the alignment by the webm's own audio, the
// latency applied once, the composed MP4, what its frames show (no chrome, the camera in its circle, the burn, the
// count-in of a rewind, the dust), the 30 s rule inside a «Заняття» session, the budget across a Studio restart, a camera
// refused, missing, busy or unplugged, Range and the player, the layout at 390, 900 and 1440 px, and no process left.
// Its own Studio processes on free ports, each with its own temporary library; Chromium's fake camera and microphone fed
// with files the suite generates (noise and tone bursts that never repeat, a small testsrc2 clip).
//
// Memory: a render browser drawing 1080p and an ffmpeg compose run beside the suite's own browser, so every scenario
// launches one browser of its own and closes it before the next, closes it before waiting on a render wherever the page
// is no longer needed, and never runs two of its own browsers at once. The fake camera is 320×180.
import {execFileSync, spawn, spawnSync} from 'node:child_process';
import {copyFileSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import http from 'node:http';
import net from 'node:net';
import {chromium} from 'playwright';
import {launch, assert} from './lib.mjs';

// Run as a whole, the suite runs each group of scenarios in a fresh process of its own, one after another: its browsers,
// its Studios and its memory end with it. (One long-lived bun process that launched a browser per scenario lost the
// DevTools pipe of a fresh browser after some fifteen launches.)
const GROUPS = ['basic', 'capture', 'sync', 'lives', 'lost', 'refused', 'session', 'budget'];
if (!process.env.VIDEO_ONLY) {
  let failed = 0;
  for (const g of GROUPS) { console.log('-- video:' + g); const r = spawnSync(process.execPath, [process.argv[1]], {env: {...process.env, VIDEO_ONLY: g}, stdio: 'inherit'}); if (r.status !== 0) failed = 1; }
  process.exit(failed);
}
const py = process.env.LUMA_PY || '.venv/bin/python', plain = process.env.LUMA_URL || 'http://127.0.0.1:8791/Luma_Demo.html';
const ONLY = process.env.VIDEO_ONLY ? new Set(process.env.VIDEO_ONLY.split(',')) : null, want = k => !ONLY || ONLY.has(k);
const tmp = mkdtempSync(join(tmpdir(), 'luma-video-')), browserPath = process.env.LUMA_BROWSER || chromium.executablePath();
const sleep = ms => new Promise(r => setTimeout(r, ms));
const ff = (...a) => execFileSync('ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-y', ...a]);
const shot = name => process.env.LUMA_SHOT ? `tests/e2e/shot_video_${name}.png` : null;
const WIDTHS = [{width: 390, height: 844}, {width: 900, height: 900}, {width: 1440, height: 900}];

// ── fixtures: a microphone that never repeats (noise and tone bursts, fixed seed), a silent one, a moving camera ────────
const voiceWav = join(tmp, 'voice.wav'), silentWav = join(tmp, 'silent.wav'), camClip = join(tmp, 'camera.mjpeg');
execFileSync(py, ['-c', `
import sys, numpy as np, soundfile as sf
sr = 48000; rng = np.random.default_rng(11); n = sr * 120; x = np.zeros(n); i = 0
while i < n:
    i += int(rng.uniform(.05, .35) * sr); k = int(rng.uniform(.08, .5) * sr)
    if i + k > n: break
    t = np.arange(k) / sr
    x[i:i + k] = rng.standard_normal(k) * rng.uniform(.05, .2) if rng.random() < .5 else rng.uniform(.1, .3) * np.sin(2 * np.pi * 440 * 2 ** ((rng.integers(55, 80) - 69) / 12) * t)
    i += k
sf.write(sys.argv[1], x.astype(np.float32), sr, subtype='PCM_16'); sf.write(sys.argv[2], np.zeros(sr * 120, np.float32), sr, subtype='PCM_16')
`, voiceWav, silentWav]);
ff('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30', '-t', '6', '-c:v', 'mjpeg', '-q:v', '6', camClip);
const media = (audio, ui = true) => ['--use-fake-device-for-media-stream', ...(ui ? ['--use-fake-ui-for-media-stream'] : []), '--autoplay-policy=no-user-gesture-required',
  '--use-file-for-fake-audio-capture=' + audio, '--use-file-for-fake-video-capture=' + camClip];
// a browser that never renders, for looking at a sitting's raw files before Studio composes them away
const stub = join(tmp, 'stub-browser'); writeFileSync(stub, '#!/bin/sh\nsleep 600 &\nwait\n', {mode: 0o755});

// ── Studio processes of our own: free ports, own libraries, PIDs recorded, only those stopped ─────────────────────────
const studios = [], browsers = new Set();
// a suite that dies still stops the Studios it started (each ends its own render browser on SIGTERM)
process.on('exit', () => { for (const st of studios) if (st.proc.exitCode === null) st.proc.kill('SIGTERM'); });
for (const ev of ['uncaughtException', 'unhandledRejection']) process.on(ev, e => { console.error('FAIL', e?.stack || e); process.exit(1); });
const freePort = () => new Promise(ok => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); }); });
async function studio(name, extra = [], env = {}, lib = join(tmp, name)) {
  const port = await freePort(), proc = spawn(py, ['studio/studio_server.py', '--port', String(port), '--songs', lib, ...extra], {env: {...process.env, LUMA_BROWSER: browserPath, ...env}, stdio: ['ignore', 'ignore', 'inherit']});
  const st = {name, port, base: `http://127.0.0.1:${port}`, proc, lib, pid: proc.pid}; studios.push(st);
  for (let i = 0; i < 100; i++) { try { if ((await fetch(st.base + '/videos')).ok) return st; } catch (_) {} await sleep(100); }
  throw Error('studio ' + name + ' did not start');
}
async function stopStudio(st) { if (st.proc.exitCode === null) { st.proc.kill('SIGTERM'); await new Promise(r => st.proc.exitCode !== null ? r() : st.proc.once('exit', r)); } }
// One browser at a time: launched for a scenario, closed by it (and by the end of the suite if a scenario threw).
async function open(args = media(voiceWav), how = null) { const b = how ? await how() : await launch(args); browsers.add(b);
  b.on('disconnected', () => { if (browsers.has(b)) console.error('browser disconnected unasked (crashed or killed from outside)'); }); return b; }
async function close(b) { if (b && browsers.delete(b)) await b.close(); }
const listing = st => fetch(st.base + '/videos').then(r => r.json());
async function settle(st, id, ms = 120000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { const v = (await listing(st)).videos.find(x => x.id === id); if (!v || ['ready', 'failed'].includes(v.state)) return v || null; await sleep(500); }
  return (await listing(st)).videos.find(x => x.id === id) || null;
}
const ffprobe = file => JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_format', '-show_streams', '-of', 'json', file], {encoding: 'utf8'}));
function rawRequest(st, method, path, body, headers = {}) {
  return new Promise((ok, no) => { const r = http.request({host: '127.0.0.1', port: st.port, method, path, headers: {'Content-Length': body ? body.length : 0, ...headers}}, res => {
    const parts = []; res.on('data', c => parts.push(c)); res.on('end', () => ok({status: res.statusCode, headers: res.headers, body: Buffer.concat(parts)})); }); r.on('error', no); if (body) r.write(body); r.end(); });
}

// ── a trainer page: getUserMedia calls and /video requests recorded by an init script, nothing run through evaluate ───
const spy = failVideo => { window.__gum = []; const md = navigator.mediaDevices; if (!md?.getUserMedia) return; const orig = md.getUserMedia.bind(md);
  md.getUserMedia = c => { window.__gum.push({audio: !!c?.audio, video: !!c?.video}); if (failVideo && c?.video) return Promise.reject(new DOMException('fake ' + failVideo, failVideo)); return orig(c); }; };
async function trainer(browser, target, {viewport = {width: 1440, height: 900}, failVideo = null, context = null} = {}) {
  // a context of its own: a page never shares a renderer with one closed before it while its microphone was open
  const page = await (context || await browser.newContext({viewport})).newPage(context ? {viewport} : {}), logs = [], video = [], other = [];
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) logs.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', e => logs.push('PAGEERROR ' + e.message)); page.on('crash', () => { logs.push('CRASH'); console.error('page crashed: ' + target); });
  page.on('request', r => { const u = new URL(r.url()); if (u.pathname.startsWith('/video')) video.push(r.method() + ' ' + u.pathname + u.search); if (!['127.0.0.1', ''].includes(u.hostname) && !u.protocol.startsWith('data') && !u.protocol.startsWith('blob')) other.push(r.url()); });
  await page.addInitScript(spy, failVideo);
  try { await page.goto(target); } catch (e) {   // say whether the server answered at all, or only the page never loaded
    const t = Date.now(), r = target.startsWith('http') ? await fetch(target).then(x => x.status, x => String(x)) : 'file';
    throw Error(e.message.split('\n')[0] + ` · the same URL from the suite: ${r} in ${Date.now() - t} ms`); }
  await page.waitForTimeout(500);
  return {page, logs, video, other};
}
const setCamera = (page, on) => page.evaluate(v => { const c = document.getElementById('cameraMode'); c.checked = v; c.dispatchEvent(new Event('change')); }, on);
const setLatency = (page, ms) => page.evaluate(v => { const c = document.getElementById('latency'); c.value = String(v); c.dispatchEvent(new Event('change')); }, ms);
const camera = page => page.evaluate(() => window.Luma.test.camera());
// One sitting through the real transport: «Співати», `seconds` of singing after the 2.1 s count-in, «Завершити»; then
// what Studio answered for the take record.
async function sit(page, {from = 2, seconds = 4, during = null} = {}) {
  await page.evaluate(t => window.Luma.test.seek(t), from);
  await page.locator('#singBtn').click();
  // generous waits: the machine running the suite may be busy, and a start or a stop is not what this measures
  await page.waitForFunction(() => window.Luma.test.state().mode === 'singing', null, {timeout: 30000});
  await page.waitForTimeout(2100 + seconds * 1000 * (during ? .5 : 1));
  const mid = during ? await during() : null; if (during) await page.waitForTimeout(seconds * 500);
  await page.locator('#stopBtn').click();
  await page.waitForFunction(() => { const s = window.Luma.test.state(); return s.mode === 'idle' && !window.Luma.diagnostics().pending; }, null, {timeout: 30000});
  const answer = await page.evaluate(() => window.Luma.test.closing());
  const cam = await camera(page), id = cam.takes[0]?.videoId || null;
  return {answer, id, cam, mid};
}
const toastText = page => page.evaluate(() => document.getElementById('toast').textContent);
const readJson = (...p) => JSON.parse(readFileSync(join(...p), 'utf8'));

// Text-range rectangles of everything readable inside root that a control does not own, against each control's box:
// no overlap, every control inside the viewport, big enough to tap. scrollWidth tells a horizontal overflow.
const audit = (page, {root, controls, min}) => page.evaluate(({root, controls, min}) => {
  const R = document.querySelector(root), out = {overflow: document.documentElement.scrollWidth > innerWidth + 1 || (R && R.scrollWidth > R.clientWidth + 1), bad: []};
  if (!R) return {...out, bad: ['no ' + root]};
  // the text is measured after each control is scrolled into view, so both sides of a comparison share one scroll
  const measure = () => { const texts = [], walk = document.createTreeWalker(R, NodeFilter.SHOW_TEXT);
    for (let n; (n = walk.nextNode());) { if (!n.textContent.trim()) continue; const el = n.parentElement; if (!el.checkVisibility?.() || el.closest('[hidden]')) continue;
      const r = document.createRange(); r.selectNodeContents(n); for (const q of r.getClientRects()) if (q.width && q.height) texts.push({el, q, text: n.textContent.trim().slice(0, 30)}); }
    return texts; };
  for (const sel of controls) for (const c of document.querySelectorAll(sel)) {
    if (!c.checkVisibility?.()) continue; c.scrollIntoView({block: 'nearest'}); const b = c.getBoundingClientRect(), texts = measure();
    if (b.left < -.5 || b.right > innerWidth + .5 || b.top < -.5 || b.bottom > innerHeight + .5) out.bad.push(sel + ' leaves the viewport ' + JSON.stringify([b.left, b.top, b.right, b.bottom].map(Math.round)));
    if (min && (b.width < min[sel] - .5 || b.height < min[sel] - .5)) out.bad.push(sel + ' is ' + Math.round(b.width) + '×' + Math.round(b.height));
    for (const t of texts) { if (c.contains(t.el) || t.el.contains(c)) continue; const q = t.q;
      const x = Math.min(b.right, q.right) - Math.max(b.left, q.left), y = Math.min(b.bottom, q.bottom) - Math.max(b.top, q.top);
      if (x > .5 && y > .5) out.bad.push(sel + ' covers «' + t.text + '»'); }
  }
  return out;
}, {root, controls, min});

// 17 · the settings field in one state at 390, 900 and 1440 px: nothing overflows or covers text, a 44 px row on a
// phone, the preview a centred 120 px circle when the camera shows, the state line exactly when the state has one.
async function settingsLayout(page, name, on) {
  for (const vp of WIDTHS) {
    await page.setViewportSize(vp); if (await page.locator('#settingsDialog').evaluate(d => d.open)) await page.locator('#settingsDialog [data-close]').first().click();
    if (name !== 'not-studio' && await page.locator('#cameraMode').isChecked() !== on) await setCamera(page, on);
    await page.locator('#settingsBtn').click(); await page.waitForTimeout(name === 'on' ? 900 : 300);
    await page.locator('#cameraMode').scrollIntoViewIfNeeded();
    const a = await audit(page, {root: '#settingsDialog .cam-field', controls: ['#cameraMode', '#camPreviewBox', '#camState'], min: null});
    const row = await page.evaluate(() => { const r = document.querySelector('.cam-field .check').getBoundingClientRect(), p = document.getElementById('camPreviewBox'), s = document.getElementById('camState');
      return {row: Math.round(r.height), preview: p.hidden ? null : [Math.round(p.getBoundingClientRect().width), Math.round(p.getBoundingClientRect().left + p.getBoundingClientRect().width / 2)], state: s.hidden ? null : s.textContent.slice(0, 40)}; });
    // the gap from the toggle's text to the first line of its description, in the WAV field and in the camera field
    const gaps = await page.evaluate(() => ['recordAudio', 'cameraMode'].map(id => { const f = document.getElementById(id).closest('.field'), r = n => { const q = document.createRange(); q.selectNodeContents(n); return q.getClientRects()[0]; };
      return +(r(f.querySelector('p').firstChild).top - r(f.querySelector('.check span')).bottom).toFixed(1); }));
    assert(Math.abs(gaps[0] - gaps[1]) < 1, `settings «${name}» at ${vp.width}px: the camera row sits as close to its description as the WAV row does ` + JSON.stringify({wav: gaps[0], camera: gaps[1]}));
    const okRow = vp.width > 720 || row.row >= 44, okPreview = name !== 'on' || (row.preview && row.preview[0] === 120 && (vp.width > 720 || Math.abs(row.preview[1] - vp.width / 2) < 30));
    assert(!a.overflow && a.bad.length === 0 && okRow && okPreview && (name === 'off' ? row.state === null : !!row.state), `settings «${name}» at ${vp.width}px: nothing overflows or covers text, the row is a ${row.row}px target, preview ${JSON.stringify(row.preview)} ` + JSON.stringify(a.bad));
    if (shot(`settings_${name}_${vp.width}`)) await page.screenshot({path: shot(`settings_${name}_${vp.width}`)});
    await page.locator('#settingsDialog [data-close]').first().click();
  }
  await page.setViewportSize({width: 1440, height: 900});
}

const A = ['basic', 'sync', 'lives', 'lost', 'refused'].some(want) ? await studio('A', ['--video-min-seconds', '3']) : null;
const demoA = A && A.base + '/demo';
let basicId = null;

// ── 1 · off by default; 3 · one prompt, one recorder; the badge; 17 · the settings field, the badge and the card ────────
if (want('basic')) {
  const browser = await open(), {page, logs, video} = await trainer(browser, demoA);
  assert(!(await page.locator('#cameraMode').isChecked()) && !(await page.locator('#cameraMode').isDisabled()), 'the camera switch is off by default and can be turned on in a Studio trainer');
  await settingsLayout(page, 'off', false);
  const off = await sit(page, {seconds: 2});
  const gum0 = await page.evaluate(() => window.__gum);
  assert(gum0.length === 1 && gum0[0].audio && !gum0[0].video && video.length === 0 && off.answer === null,
    'switch off: one getUserMedia call with video:false and no /video request ' + JSON.stringify({gum0, video}));
  const plainCard = await page.evaluate(() => [...document.querySelectorAll('#takesList .take-actions > button')].map(b => b.className || b.textContent));
  assert(!plainCard.includes('take-video') && await page.locator('.take-video').count() === 0, 'the attempt card looks as it always did ' + JSON.stringify(plainCard));
  await setCamera(page, true);
  // the badge while singing, at each width: on the bar's first row beside the icon buttons, off the title
  const badge = async () => {
    const out = {badge: await page.locator('#camBadge').isVisible(), text: await page.locator('#camBadge').textContent(), cam: await camera(page), widths: []};
    for (const vp of WIDTHS) {
      await page.setViewportSize(vp); await page.waitForTimeout(200);
      out.widths.push(await page.evaluate(() => { const r = id => { const q = document.getElementById(id).getBoundingClientRect(); return {l: q.left, r: q.right, t: q.top, b: q.bottom, w: q.width, h: q.height}; };
        return {vw: innerWidth, sw: document.documentElement.scrollWidth, badge: r('camBadge'), settings: r('settingsBtn'), import: r('importBtn'), title: r('songTitle')}; }));
      if (shot(`badge_${vp.width}`)) await page.screenshot({path: shot(`badge_${vp.width}`), clip: {x: 0, y: 0, width: vp.width, height: 140}});
    }
    await page.setViewportSize({width: 1440, height: 900}); return out;
  };
  const one = await sit(page, {seconds: 6, during: badge});
  const gum = await page.evaluate(() => window.__gum);
  assert(gum.length === 2 && gum[1].audio && gum[1].video, 'turned on after an audio-only attempt: exactly one more call, with audio and video, for the whole sitting ' + JSON.stringify(gum));
  assert(one.mid.badge && /ВІДЕО/.test(one.mid.text) && one.mid.cam.sitting?.recording, '«● ВІДЕО» shows while the sitting records ' + JSON.stringify({...one.mid, widths: undefined}));
  for (const g of one.mid.widths) {
    const sameRow = Math.abs((g.badge.t + g.badge.b) / 2 - (g.settings.t + g.settings.b) / 2) < 2 && Math.abs(g.settings.t - g.import.t) < 1;
    const clear = g.badge.r <= g.import.l + .5 && (g.badge.b <= g.title.t + .5 || g.badge.r <= g.title.l || g.badge.l >= g.title.r);
    assert(g.badge.w > 0 && sameRow && clear && g.sw <= g.vw && g.badge.r <= g.vw, `«● ВІДЕО» at ${g.vw}px sits on the bar's first row beside the icon buttons, off the title ` + JSON.stringify(g));
  }
  assert(!(await page.locator('#camBadge').isVisible()), 'and is gone after it');
  assert(one.answer?.composed === true && one.id && /монтується/.test(await toastText(page)), 'Studio takes the sitting for composing and the trainer says so ' + JSON.stringify(one.answer));
  await page.waitForTimeout(300);
  assert(await page.locator('.take-video').count() === 1 && (await page.locator('.take-video').textContent()).includes('Відео'), 'its attempt card has «Відео»');
  assert(logs.length === 0, 'trainer console clean through the sittings ' + JSON.stringify(logs));
  await close(browser);   // Studio renders as soon as it has the take record: the render runs with no page of ours open
  const v = await settle(A, one.id);
  assert(v?.state === 'ready', 'the sitting is composed into a video ' + JSON.stringify(v));
  basicId = one.id;
}

// ── 2 · not Studio: the plain demo server and file:// ──────────────────────────────────────────────────────────────
if (want('basic')) {
  const browser = await open([]);
  for (const target of [plain, 'file://' + resolve('examples/demo/Luma_Demo.html')]) {
    const {page, logs} = await trainer(browser, target);
    await page.locator('#settingsBtn').click();
    const st = await page.evaluate(() => ({disabled: document.getElementById('cameraMode').disabled, text: document.getElementById('camState').textContent, shown: !document.getElementById('camState').hidden}));
    assert(st.disabled && st.shown && st.text === 'Відео працює, коли пісню відкрито з бібліотеки Studio.', `${target.startsWith('file') ? 'file://' : 'another server'}: the switch is disabled with its reason ` + JSON.stringify(st));
    await page.locator('#settingsDialog [data-close]').first().click();
    if (!target.startsWith('file')) { await settingsLayout(page, 'not-studio', false); assert(logs.length === 0, 'console clean on the plain server ' + JSON.stringify(logs)); }
    await page.close();
  }
  await close(browser);
}

// ── 16 · Range and the Studio player; 17 · «Мої відео» and the open player ──────────────────────────────────────────
if (want('basic') && basicId) {
  const id = basicId, file = readFileSync(join(A.lib, 'videos', id, 'video.mp4'));
  const r = await rawRequest(A, 'GET', `/video/${id}/video.mp4`, null, {Range: 'bytes=1000-1999'});
  assert(r.status === 206 && r.body.length === 1000 && r.body.equals(file.subarray(1000, 2000)) && r.headers['content-range'] === `bytes 1000-1999/${file.length}`, 'Range bytes=1000-1999 → 206 with exactly those bytes');
  const browser = await open([]), page = await browser.newPage({viewport: {width: 1440, height: 900}}), logs = [];
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) logs.push(m.type() + ': ' + m.text()); });
  await page.goto(A.base + '/#video/' + id); await page.waitForFunction(() => document.getElementById('player').open && document.getElementById('playerVideo').readyState >= 1, null, {timeout: 10000});
  const play = await page.evaluate(async () => { const v = document.getElementById('playerVideo'); v.muted = true; v.currentTime = v.duration * .75; await new Promise(r => v.addEventListener('seeked', r, {once: true}));
    const at = v.currentTime; await v.play(); await new Promise(r => setTimeout(r, 700)); return {at, now: v.currentTime, d: v.duration, name: document.getElementById('playerDownload').download}; });
  assert(play.at >= play.d * .7 && play.now > play.at + .2 && /^Luma_Demo_\d{4}-\d\d-\d\d_\d\d-\d\d\.mp4$/.test(play.name), 'the player seeks to 75 % and plays on; the download is named after the song and the time ' + JSON.stringify(play));
  const inert = await page.evaluate(() => { const b = document.getElementById('addSong'); return document.elementFromPoint(b.getBoundingClientRect().left + 4, b.getBoundingClientRect().top + 4) === b; });
  assert(!inert, 'the player is modal: the page behind it takes no pointer');
  await page.locator('#playerClose').click();
  for (const vp of WIDTHS) {
    await page.setViewportSize(vp); await page.waitForTimeout(300); await page.locator('#videosSection').scrollIntoViewIfNeeded();
    const sec = await audit(page, {root: '#videosSection', controls: ['#videos .vid:first-child .actions .primary', '#videos .vid:first-child .vthumb'], min: vp.width === 390 ? {'#videos .vid:first-child .actions .primary': 44, '#videos .vid:first-child .vthumb': 44} : null});
    const head = await page.evaluate(() => ({h: document.getElementById('videosTitle').textContent, used: document.getElementById('videosUsed').textContent, cols: getComputedStyle(document.getElementById('videos')).gridTemplateColumns.split(' ').length}));
    assert(!sec.overflow && sec.bad.length === 0 && /^Мої відео \d+$/.test(head.h) && /^Займають ([1-9]\d* МБ|\d+,\d ГБ) з 5,0 ГБ · найстаріші видаляються самі$/.test(head.used) && (vp.width > 560 || head.cols === 1),
      `«Мої відео» at ${vp.width}px: ${head.cols} column(s), «${head.used}», nothing overflows ` + JSON.stringify(sec.bad));
    // one length per card, cut as the player's clock cuts it; the «·» with the same 6 px on both sides
    const card = await page.evaluate(() => { const len = document.querySelector('#videos .vid .len'), cs = getComputedStyle(len, '::before'), facts = getComputedStyle(len.parentElement);
      return {len: len.textContent, dot: cs.content, after: cs.marginRight, gap: facts.columnGap}; });
    const listed = (await listing(A)).videos[0], want = Math.floor(listed.duration);
    assert(card.len === Math.floor(want / 60) + ':' + String(want % 60).padStart(2, '0') && card.dot === '"·"' && card.after === card.gap,
      `the card at ${vp.width}px shows the length as the player does (${listed.duration} s → ${card.len}), «·» spaced evenly ` + JSON.stringify(card));
    if (shot(`studio_${vp.width}`)) await page.locator('#videosSection').screenshot({path: shot(`studio_${vp.width}`)});
    await page.locator('#videos .vid .actions .primary').first().click(); await page.waitForFunction(() => document.getElementById('player').open);
    const pl = await audit(page, {root: '#player', controls: ['#playerClose', '#playerDownload', '#playerDelete'], min: vp.width === 390 ? {'#playerClose': 44, '#playerDownload': 44, '#playerDelete': 44} : null});
    const box = await page.evaluate(() => { const q = document.getElementById('player').getBoundingClientRect(), v = document.getElementById('playerVideo').getBoundingClientRect(); return {l: q.left, r: q.right, t: q.top, b: q.bottom, vw: innerWidth, vh: innerHeight, video: Math.round(v.width)}; });
    assert(pl.bad.length === 0 && box.l >= 0 && box.r <= box.vw && box.t >= 0 && box.b <= box.vh, `the player at ${vp.width}px fits the window, buttons clear of text and ≥ 44 px on a phone ` + JSON.stringify({bad: pl.bad, box}));
    // the browser's control bar (about 73 px) has a strip of its own under the picture; the caption leaves the length to it
    const strip = await page.evaluate(() => { const v = document.getElementById('playerVideo'), r = v.getBoundingClientRect(); return {strip: +(r.height - r.width * 9 / 16).toFixed(1), pos: getComputedStyle(v).objectPosition, meta: document.getElementById('playerMeta').textContent, d: v.duration}; });
    assert(strip.strip >= 76 && strip.pos === '50% 0%' && strip.meta.split(' · ').every(x => !/^\d+:\d\d$/.test(x)),
      `the player at ${vp.width}px: the picture on top, ${strip.strip} px for the controls under it, no second length in the caption ` + JSON.stringify(strip));
    if (shot(`player_${vp.width}`)) await page.screenshot({path: shot(`player_${vp.width}`)});
    await page.locator('#playerClose').click();
  }
  assert(logs.length === 0, 'Studio console clean ' + JSON.stringify(logs));
  await close(browser);
}

// ── 4 · capture: what Studio holds before composing it (a browser that never renders keeps the raw files) ───────────
if (want('capture')) {
  const R = await studio('R', ['--video-min-seconds', '3'], {LUMA_BROWSER: stub});
  const browser = await open(), {page, logs, video} = await trainer(browser, R.base + '/demo');
  await setCamera(page, true);
  const r = await sit(page, {seconds: 4});
  const tabs = await page.evaluate(() => window.Luma.test.takes());
  // 17 · the card's «Відео» and the field with the camera on, here because this Studio never starts a render beside us;
  // the card's pictures wait for the «монтується» toast to go, so they show the card as it stays
  await page.waitForFunction(() => !document.getElementById('toast').classList.contains('show'), null, {timeout: 10000}); await page.waitForTimeout(300);
  for (const vp of WIDTHS) {
    await page.setViewportSize(vp); await page.waitForTimeout(250); await page.locator('#tabTakes').click();
    const card = await page.evaluate(() => { const b = document.querySelector('#takesList .take .take-video'); b.scrollIntoView({block: 'nearest'}); const q = b.getBoundingClientRect();
      return {w: q.width, h: q.height, r: q.right, vw: innerWidth, sw: document.documentElement.scrollWidth, label: b.textContent}; });
    const a = await audit(page, {root: '#takesList .take', controls: ['#takesList .take:first-child .take-video', '#takesList .take:first-child .take-export'], min: null});
    assert(card.label === 'Відео' && card.h >= (vp.width <= 720 ? 40 : 28) && card.r <= card.vw && card.sw <= card.vw && a.bad.length === 0, `the card's «Відео» at ${vp.width}px: ${Math.round(card.w)}×${Math.round(card.h)}, inside, covering nothing ` + JSON.stringify(a.bad));
    if (shot(`card_${vp.width}`)) await page.locator('#takesList .take').first().screenshot({path: shot(`card_${vp.width}`)});
  }
  await settingsLayout(page, 'on', true);
  await close(browser);
  await sleep(1500);   // alignment, then the stub «render» starts
  const d = join(R.lib, 'videos', r.id), take = readJson(d, 'take.json');
  const probe = ffprobe(join(d, 'camera.webm')), kinds = probe.streams.map(s => s.codec_type + ':' + s.codec_name);
  const audioSec = +execFileSync(py, ['-c', 'import sys;sys.path.insert(0,"studio");import video;print(len(video.decode(__import__("pathlib").Path(sys.argv[1])))/48000)', join(d, 'camera.webm')], {encoding: 'utf8'});
  const sitting = take.segments.at(-1).stop - take.segments[0].when;
  assert(kinds.some(k => k.startsWith('video:')) && kinds.includes('audio:opus') && audioSec >= sitting, 'camera.webm holds video and Opus and covers the sitting ' + JSON.stringify({kinds, audioSec, sitting}));
  assert(existsSync(join(d, 'voice-0.wav')) && take.segments.length === 1 && take.segments[0].runId === tabs.find(t => t.id === r.cam.takes[0].id)?.runId,
    'one voice WAV per segment, and the take record\'s run ids are the tab\'s attempts ' + JSON.stringify(take.segments.map(s => s.runId)));
  const fresh = '0f0e0d0c-0b0a-4908-8706-050403020100', chunk = Buffer.from('webm');
  const seq = [await rawRequest(R, 'PUT', `/video/${fresh}/camera?seq=0`, chunk), await rawRequest(R, 'PUT', `/video/${fresh}/camera?seq=0`, chunk), await rawRequest(R, 'PUT', `/video/${fresh}/camera?seq=2`, chunk), await rawRequest(R, 'PUT', `/video/${fresh}/camera?seq=1`, chunk)].map(x => x.status);
  const foreign = (await rawRequest(R, 'PUT', `/video/${fresh}/camera?seq=2`, chunk, {Origin: 'http://evil.example'})).status;
  const foreignDel = (await rawRequest(R, 'DELETE', `/video/${r.id}`, null, {Origin: 'http://evil.example'})).status;
  assert(JSON.stringify(seq) === '[200,409,409,200]' && foreign === 403 && foreignDel === 403, 'a repeated or skipped seq gets 409; a write from another origin gets 403 ' + JSON.stringify({seq, foreign, foreignDel}));
  const stubs = () => readdirSync('/proc').filter(p => /^\d+$/.test(p)).filter(p => { try { return readFileSync(`/proc/${p}/cmdline`, 'utf8').includes(join(R.lib, 'videos', r.id)); } catch (_) { return false; } });
  const before = stubs(); await rawRequest(R, 'DELETE', `/video/${fresh}`); const del = await rawRequest(R, 'DELETE', `/video/${r.id}`); await sleep(500);
  assert(before.length >= 1 && del.status === 200 && !existsSync(d) && stubs().length === 0, '«Видалити» while rendering ends the render Studio started and removes the folder ' + JSON.stringify({before, after: stubs()}));
  assert(video.every(v => v.startsWith('PUT /video/' + r.id) || v.startsWith('DELETE')) && logs.length === 0, 'the trainer talked only to its own sitting, console clean ' + JSON.stringify(logs));
  await stopStudio(R);
}

// ── 5, 6, 7 · alignment, the latency applied once, the composed file ─────────────────────────────────────────────────
const decodeCode = `
import sys, json, numpy as np, base64, subprocess, pathlib
sys.path.insert(0, 'studio'); import video
mp4, wav, trainer, a, speed, back = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6])
out = video.decode(pathlib.Path(mp4)); voice = video.decode(pathlib.Path(wav))
stem = pathlib.Path(sys.argv[7]); stem.write_bytes(video.backing_bytes(pathlib.Path(trainer), speed)); inst = video.decode(stem)[int(round(a / speed * 48000)):]
n = min(len(out) - 48000, len(voice), len(inst), 6 * 48000)
def where(ref):
    h = video.locate(ref[:n], out, 0.2, 0.2); return h['at'], h['peak']
print(json.dumps({'voice': where(voice), 'inst': where(inst)}))`;
if (want('sync')) {
  // one browser per sitting, closed before its render starts
  const runs = [];
  for (const lag of [0, 150]) {
    const browser = await open(), {page, logs} = await trainer(browser, demoA); await setCamera(page, true);
    await setLatency(page, lag); const r = await sit(page, {seconds: 4});
    const tk = await page.evaluate(() => window.Luma.test.takes()[0]), wav = await page.evaluate(id => window.Luma.test.wav(id), tk.id);
    assert(logs.length === 0, `latency ${lag}: console clean through the sitting ` + JSON.stringify(logs));
    await close(browser);
    const wavPath = join(tmp, `voice-${lag}.wav`); writeFileSync(wavPath, Buffer.from(wav, 'base64')); runs.push({lag, ...r, wavPath, a: tk.a, v: await settle(A, r.id)});
  }
  for (const run of runs) {
    const v = run.v, d = join(A.lib, 'videos', run.id), take = readJson(d, 'take.json'), al = readJson(d, 'align.json');
    assert(v.state === 'ready' && al.peak >= .5 && !al.approximateSync && (al.spread ?? 0) <= .033, `latency ${run.lag}: alignment by the webm's own audio, peak ${al.peak} ` + JSON.stringify(al));
    const mp4 = join(d, 'video.mp4'), p = ffprobe(mp4), vs = p.streams.find(s => s.codec_type === 'video'), as = p.streams.find(s => s.codec_type === 'audio');
    const bytes = readFileSync(mp4), moov = bytes.indexOf('moov'), mdat = bytes.indexOf('mdat'), expect = take.segments.at(-1).stop - take.segments[0].when;
    assert(vs.codec_name === 'h264' && vs.profile === 'High' && vs.width === 1920 && vs.height === 1080 && vs.r_frame_rate === '30/1' && vs.pix_fmt === 'yuv420p'
      && as.codec_name === 'aac' && as.profile === 'LC' && +as.sample_rate === 48000 && as.channels === 2 && moov > 0 && moov < mdat && Math.abs(+p.format.duration - expect) <= .1,
      `latency ${run.lag}: H.264 High 1920×1080 30 fps yuv420p, AAC LC 48 kHz stereo, moov first, ${(+p.format.duration).toFixed(3)} s for ${expect.toFixed(3)} s`);
    const got = JSON.parse(execFileSync(py, ['-c', decodeCode, mp4, run.wavPath, 'examples/demo/Luma_Demo.html', String(run.a), '1', String(take.back), join(tmp, 'stem.mp3')], {encoding: 'utf8'}));
    // the WAV starts `lag` after the music (the worker records from when + lag); Studio puts it on the instrumental as it is
    run.placed = got.voice[0] - got.inst[0]; run.captured = take.segments[0].latency / 1000; run.got = got;
  }
  const [l0, l150] = runs, shift = (l0.placed - l0.captured) - (l150.placed - l150.captured);
  assert(runs.every(r => r.got.voice[1] > .3 && r.got.inst[1] > .1 && Math.abs(r.placed) <= .002) && Math.abs(shift - .15) <= .002,
    'the voice sits on the instrumental exactly where the trainer recorded it: latency applied once, so voice-to-instrumental differs by 150 ± 2 ms against the microphone ' + JSON.stringify(runs.map(r => ({lag: r.lag, placed: +r.placed.toFixed(4), got: r.got}))));
}
if (want('sync')) {
  // a silent microphone: no peak to trust, so the stamp places the camera
  const quiet = await open(media(silentWav)), {page} = await trainer(quiet, demoA); await setCamera(page, true);
  const r = await sit(page, {seconds: 4}); await close(quiet);
  const v = await settle(A, r.id), d = join(A.lib, 'videos', r.id), al = readJson(d, 'align.json'), take = readJson(d, 'take.json');
  assert(v.state === 'ready' && al.approximateSync && Math.abs(al.W0 - take.ctxAtStart) <= .04, 'a silent microphone falls back to the stamp, within 40 ms of it ' + JSON.stringify(al));
}

// ── 9, 10, 8 · a lives sitting with dust: one video across two rewinds; its frames; the render page itself ────────────
if (want('lives')) {
  const browser = await open(), {page, logs} = await trainer(browser, demoA); await setCamera(page, true);
  await page.evaluate(() => { const T = window.Luma.test, H = T.history;   // three past attempts for the dust
    for (const [k, lag] of [[1, 0], [2, 40], [3, -30]]) T.injectTake({a: 0, b: 20, points: H.synthPoints({lag, seed: k}, 0, 20), startedAt: '2026-10-0' + k + 'T10:00:00Z'});
    const c = document.getElementById('livesMode'); c.checked = true; c.dispatchEvent(new Event('change')); const n = document.getElementById('livesCount'); n.value = '3'; n.dispatchEvent(new Event('change'));
    T.closeTrace(); T.clearRange(); T.seek(0); window.__off = 1.5;
    window.__voice = setInterval(() => { const s = T.state(); if (s.mode !== 'singing') return; const ref = window.Luma.targetAt(s.time);
      T.livePush(ref ? {t: T.ctxTime(), f: 440 * Math.pow(2, (ref.m + window.__off - 69) / 12), confidence: .95, db: -20, rms: .1, peak: .3} : {t: T.ctxTime(), f: null, confidence: 0, db: -70, rms: 0, peak: 0}); }, 20); });
  await page.locator('#singBtn').click();
  await page.waitForFunction(() => { const c = window.Luma.test.camera(); return c.sitting && c.sitting.segments >= 2 && window.Luma.test.state().mode === 'singing' && !window.Luma.test.state().lives.countdown; }, null, {timeout: 60000});
  const mid = await camera(page);
  await page.waitForTimeout(1500); await page.locator('#stopBtn').click();
  await page.waitForFunction(() => window.Luma.test.state().mode === 'idle' && !window.Luma.diagnostics().pending, null, {timeout: 30000});
  await page.evaluate(() => clearInterval(window.__voice));
  const answer = await page.evaluate(() => window.Luma.test.closing()), id = (await camera(page)).takes[0].videoId;
  assert(mid.sitting.recording && answer.composed && id, 'the rewinds kept one recorder going and the sitting composes ' + JSON.stringify({mid: mid.sitting, answer}));
  // where the trainer's own chrome sits at 1440 × 900, for the frame comparison below
  const geo = await page.evaluate(() => { const r = e => { const q = document.querySelector(e).getBoundingClientRect(); return [q.left + q.width / 2, q.top + q.height / 2].map(Math.round); };
    return {rail: r('#stageRail .stage-tools'), level: r('#levelSeg'), timeline: r('#timelineWrap')}; });
  assert(logs.length === 0, 'trainer console clean through the lives sitting ' + JSON.stringify(logs));
  await close(browser);   // before the render runs; the render page below gets a browser of its own afterwards
  const v = await settle(A, id), d = join(A.lib, 'videos', id), take = readJson(d, 'take.json'), segs = take.segments, t1 = segs[0].when;
  const p = ffprobe(join(d, 'video.mp4')), expect = segs.at(-1).stop - t1;
  assert(v.state === 'ready' && segs.length === 3 && Math.abs(+p.format.duration - expect) <= .1,
    'two rewinds, then «Завершити»: one folder, three segments, one MP4 of stop₃ − when₁ ' + JSON.stringify({segments: segs.length, duration: +p.format.duration, expect}));
  const al = readJson(d, 'align.json');
  assert(!al.approximateSync && al.residuals.length === 3 && al.spread <= .033, 'every segment lands where W0 puts it, within a frame ' + JSON.stringify(al));
  // the burn, at each recorded loss, in the composed frames: fire colours at that heart 0.2 s after the loss
  const losses = segs.flatMap(s => (s.lives?.losses || []).map(x => ({...x, u: s.when - t1 + (x.at - s.a) / s.speed, total: s.lives.total})));
  const fire = [];
  for (const x of losses) {
    const png = join(tmp, `burn-${x.u.toFixed(2)}.png`); ff('-ss', (x.u + .2).toFixed(3), '-i', join(d, 'video.mp4'), '-frames:v', '1', png);
    const cx = 1636 - (x.total - 1 - x.left) * 44, out = execFileSync(py, ['-c', `
import sys, numpy as np, subprocess
raw = subprocess.run(['ffmpeg','-v','error','-i',sys.argv[1],'-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
img = np.frombuffer(raw, np.uint8).reshape(1080, 1920, 3).astype(int); x, y = int(sys.argv[2]), 92
box = img[max(0,y-70):y+70, x-60:x+60]; r, g, b = box[...,0], box[...,1], box[...,2]
print(int(((r > 200) & (g > 90) & (g < 215) & (b < 140)).sum()))`, png, String(cx)], {encoding: 'utf8'});
    fire.push({u: +x.u.toFixed(2), heart: x.left, orange: +out}); rmSync(png);
  }
  assert(losses.length >= 6 && fire.every(f => f.orange > 30), 'each recorded loss burns at its heart in the video, in fire colours ' + JSON.stringify(fire));
  // the voice is silent between two segments, as it was in the room
  const gap = execFileSync(py, ['-c', `
import sys, json, pathlib; sys.path.insert(0, 'studio'); import video, numpy as np
x = video.decode(pathlib.Path(sys.argv[1])); r = lambda a, b: float(np.sqrt(np.mean(x[int(a*48000):int(b*48000)]**2)))
print(json.dumps({'gap': r(float(sys.argv[2]) + .1, float(sys.argv[3]) - .1), 'sung': r(float(sys.argv[4]), float(sys.argv[2]) - .1)}))`, join(d, 'video.mp4'), String(segs[0].stop - t1), String(segs[1].when - t1), String(segs[0].stop - t1 - 2)], {encoding: 'utf8'});
  const g = JSON.parse(gap);
  assert(g.gap < g.sung / 20, 'between the segments voice and instrumental are silent ' + JSON.stringify(g));

  // 8 · the render page itself: no chrome, the canvas, note states and lives as the take implies, the dust
  const viewer = await open([]), ctx = await viewer.newContext({viewport: {width: 1920, height: 1080}, deviceScaleFactor: 1}), hold = await ctx.newPage(), hlogs = [], hosts = new Set();
  hold.on('console', m => hlogs.push(m.type() + ': ' + m.text())); hold.on('pageerror', e => hlogs.push('PAGEERROR ' + e.message)); hold.on('request', r => { const u = new URL(r.url()); if (!['blob:', 'data:'].includes(u.protocol)) hosts.add(u.host); });
  await hold.goto(`${A.base}/video/${id}/render?hold=1`);
  await hold.waitForFunction(() => window.LumaRender?.ready, null, {timeout: 15000});
  const dom = await hold.evaluate(() => { const vis = s => [...document.querySelectorAll(s)].some(e => e.checkVisibility()); const c = document.getElementById('chart');
    return {render: document.documentElement.dataset.render, w: c.width, h: c.height, css: [c.clientWidth, c.clientHeight], dpr: window.Luma.test.dpr(),
      chrome: ['.bar', '.transport', '.stage-head', '.stage-rail', '.takes', '#countdown', '#lyricBand', 'dialog'].filter(vis)}; });
  assert(dom.render === '1' && dom.w === 1920 && dom.h === 1080 && dom.dpr === 2 && dom.chrome.length === 0, 'render mode: html[data-render], a 1920×1080 canvas drawn at DPR 2 (the roll\'s type twice the trainer\'s), no chrome rendered ' + JSON.stringify(dom));
  // the roll never runs under the hearts, their burn, the % box or the camera: the plot (every note, word and line is
  // clipped to it), the ЗАРАЗ caption and the note names beside the plot, against the HUD at its widest (10 lives)
  const clear = await hold.evaluate(async () => { const out = [], c = document.createElement('canvas').getContext('2d'), mono = getComputedStyle(document.body).getPropertyValue('--mono');
    for (const u of [0, 3, 6]) { await window.Luma.render.frame(u); const b = window.Luma.test.plot(), k = window.Luma.test.dpr(), now = b.left + (b.right - b.left) * .34;
      c.font = '600 ' + 11 * k + 'px ' + mono; const name = c.measureText('D♯5').width; c.font = '600 ' + 11 * k + 'px sans-serif'; const cap = c.measureText('ЗАРАЗ').width / 2 + 12;
      out.push({plot: [b.left * k, b.top * k, b.right * k, b.bottom * k], caption: [now * k - cap, (b.laneTop - 15) * k - 14, now * k + cap, (b.laneTop - 15) * k + 14], names: [(b.left - 11) * k - name, b.top * k, (b.left - 11) * k, b.bottom * k]}); }
    return {frames: out, hud: window.LumaRender.hud(10)}; });
  const meet = (p, q) => p[0] < q[2] && q[0] < p[2] && p[1] < q[3] && q[1] < p[3], disc = (r, c) => { const x = Math.max(r[0], Math.min(c.x, r[2])), y = Math.max(r[1], Math.min(c.y, r[3])); return Math.hypot(x - c.x, y - c.y) < c.r; };
  assert(clear.frames.every(f => ['plot', 'caption', 'names'].every(k => !meet(f[k], clear.hud.hearts) && !meet(f[k], clear.hud.pct) && !disc(f[k], clear.hud.seat))) && clear.frames.every(f => f.plot[1] === clear.frames[0].plot[1] && f.plot[0] === clear.frames[0].plot[0]),
    'the plot, the ЗАРАЗ caption and the note names stay clear of the hearts with their burn, the % box and the camera circle ' + JSON.stringify(clear));
  // what the take record implies, decoded here from its packed trace and scored in one pass by the trainer's pure engine
  const LV = {easy: {slack: .12, ratio: .35, octaveFree: true}, normal: {slack: .06, ratio: .5, octaveFree: false}, strict: {slack: .05, ratio: .65, octaveFree: false}};
  const stored = segs.map(s => { const run = s.history.runs[0], tr = s.history.traces[0], pts = [];
    const arr = (b, T) => { const u = Buffer.from(b, 'base64'); return new T(u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength)); };
    for (const g of tr.segments) { const c = arr(g.cents, Int16Array), q = arr(g.conf, Uint8Array), db = arr(g.db, Int8Array);
      for (let i = 0; i < c.length; i++) { const m = c[i] === -32768 ? null : c[i] / 100; pts.push({songT: s.a + (g.t0 + i * tr.hop) * s.speed, m, raw: m, confidence: q[i] / 255, db: db[i]}); } }
    return {points: pts, meta: {a: s.a, octave: run.octave || 0, view: run.view, tolerance: run.tolerance, level: run.level, ...(LV[run.level] || LV.normal)}}; });
  const times = [], frames = [];
  for (const s of segs) for (const q of [.3, .6, .97]) times.push(s.when - t1 + (s.stop - s.when) * q);
  const segLosses = segs.map(s => (s.lives?.losses || []).map(x => ({...x, u: s.when - t1 + (x.at - s.a) / s.speed})));
  for (const u of times.sort((a, b) => a - b)) {
    const f = await hold.evaluate(u => window.Luma.render.frame(u), u), s = segs[f.segment];
    const want_ = await hold.evaluate(([pts, meta, upTo]) => { const r = window.Luma.test.score(pts, meta, upTo);
      return {pct: r.pct, kinds: r.notes.map(([id, n]) => [id, n.frames < 3 ? null : n.hit / n.frames >= meta.ratio ? 'hit' : n.sung > 0 ? 'miss' : 'silent']).filter(k => k[1])}; },
      [stored[f.segment].points, stored[f.segment].meta, Math.min(f.t - .18 * s.speed, s.b)]);
    const kinds = new Map(want_.kinds), lost = segLosses[f.segment].filter(x => x.u <= u).length;
    frames.push({u: +u.toFixed(2), k: f.segment, pct: f.pct, want: want_.pct, left: f.left, wantLeft: s.lives.total - lost, notes: f.notes.length, same: f.notes.every(n => kinds.get(n.id) === n.kind), diff: f.notes.filter(n => kinds.get(n.id) !== n.kind).map(n => [n.id, n.kind, kinds.get(n.id) ?? null]), dust: f.dust});
  }
  assert(frames.every(f => f.pct === f.want && f.same && f.left === f.wantLeft), 'frame(u) shows the note states, the % and the lives the stored take implies ' + JSON.stringify(frames.map(({dust, ...f}) => f)));
  assert(frames.every(f => f.dust.drawn && f.dust.specks > 0) && segs[0].dust.length === 3 && segs[1].dust.length === 4 && segs[0].dust.every(x => segs[1].dust.includes(x)),
    'the dust is drawn on every sampled frame; the re-sing\'s dust holds the attempt that ended in the rewind ' + JSON.stringify({dust: frames.map(f => f.dust), sets: segs.map(s => s.dust)}));
  const gapU = (segs[1].cin + segs[1].when) / 2 - t1, gapF = await hold.evaluate(u => window.Luma.render.frame(u), gapU);
  const panel = await hold.evaluate(() => window.LumaRender.panel), plotNow = await hold.evaluate(() => { const b = window.Luma.test.plot(); return [b.left * 2, b.top * 2, b.right * 2, b.bottom * 2]; });
  assert(gapF.gap && /^Ще раз з \d\d:\d\d$/.test(gapF.notice) && gapF.count >= 1 && gapF.left === gapF.total && panel && panel[0] > 0 && panel[2] < 1920 && panel[1] > plotNow[1] && panel[3] < plotNow[3],
    'inside the gap: «Ще раз з …», the count and the refilled hearts, on an opaque panel over the roll ' + JSON.stringify({notice: gapF.notice, count: gapF.count, left: gapF.left, panel}));
  if (shot('render_gap')) await hold.screenshot({path: shot('render_gap')});
  // the composed frame against the render's own frame: where the trainer's transport and rail would be the video shows
  // the stage as the render drew it, and inside the circle the camera
  // drawn frame by frame from 0, as the encoder draws them: the pitch range eases between frames, a jump frames it at once
  const u = Math.round((segs[0].when - t1 + 2.5) * 30) / 30; await hold.evaluate(async n => { for (let f = 0; f <= n; f++) await window.Luma.render.frame(f / 30); }, Math.round(u * 30));
  const gamePng = join(tmp, 'game.png'), mp4Png = join(tmp, 'frame.png');
  await hold.screenshot({path: gamePng, clip: {x: 0, y: 0, width: 1920, height: 1080}});
  ff('-ss', u.toFixed(3), '-i', join(d, 'video.mp4'), '-frames:v', '1', mp4Png);
  const cmp = JSON.parse(execFileSync(py, ['-c', `
import sys, json, subprocess, numpy as np
def img(p): return np.frombuffer(subprocess.run(['ffmpeg','-v','error','-i',p,'-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout, np.uint8).reshape(1080,1920,3).astype(int)
g = img(sys.argv[1]); v = img(sys.argv[2]); pts = json.loads(sys.argv[3])
def d(x, y, r=10): return float(np.abs(g[y-r:y+r, x-r:x+r] - v[y-r:y+r, x-r:x+r]).mean())
print(json.dumps({'chrome': {k: d(*p) for k, p in pts.items()}, 'circle': d(222, 720, 60), 'outside': d(1100, 300, 60)}))`, gamePng, mp4Png, JSON.stringify(geo)], {encoding: 'utf8'}));
  assert(Object.values(cmp.chrome).every(x => x < 12) && cmp.outside < 12 && cmp.circle > 30, 'the MP4 is the render where the trainer has chrome, and the camera inside the circle ' + JSON.stringify(cmp));
  const clean = hlogs.filter(l => !/^(log|debug|info):/.test(l));
  assert(clean.length === 0 && [...hosts].every(h => h === '127.0.0.1:' + A.port), 'the render page logs nothing and asks only 127.0.0.1 ' + JSON.stringify({clean, hosts: [...hosts]}));
  await close(viewer);
}

// ── 14 · the camera unplugged mid-take ───────────────────────────────────────────────────────────────────────────────
if (want('lost')) {
  const browser = await open(), {page, logs} = await trainer(browser, demoA); await setCamera(page, true);
  const r = await sit(page, {seconds: 6, during: async () => { const lost = await page.evaluate(() => window.Luma.test.loseCamera()); await page.waitForTimeout(800);
    return {lost, toast: await toastText(page), mode: (await page.evaluate(() => window.Luma.test.state())).mode, badge: await page.locator('#camBadge').isVisible(), err: await page.locator('#errorBanner').isVisible()}; }});
  assert(r.mid.lost && r.mid.mode === 'singing' && !r.mid.err && !r.mid.badge && r.mid.toast === 'Камера від’єдналась: відео цієї спроби закінчується тут, спів триває.',
    'a lost camera ends the footage, says so, and the attempt sings on ' + JSON.stringify(r.mid));
  assert(logs.length === 0, 'console clean ' + JSON.stringify(logs));
  await close(browser);
  const v = await settle(A, r.id), d = join(A.lib, 'videos', r.id), take = readJson(d, 'take.json'), dur = take.segments[0].stop - take.segments[0].when;
  const held = JSON.parse(execFileSync(py, ['-c', `
import sys, json, subprocess, numpy as np
def at(t): return np.frombuffer(subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i',sys.argv[1],'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout,np.uint8).reshape(1080,1920,3).astype(int)[620:820,122:322]
d = float(sys.argv[2]); a, b, c, e = at(1.0), at(1.6), at(d - 1.2), at(d - .4)
print(json.dumps({'before': float(np.abs(a-b).mean()), 'after': float(np.abs(c-e).mean())}))`, join(d, 'video.mp4'), String(dur)], {encoding: 'utf8'}));
  assert(v.state === 'ready' && held.before > 3 && held.after < 1.5, 'the video composes and holds the last camera frame to the end ' + JSON.stringify(held));
}

// ── 13 · camera denied, absent, busy: audio-only, a clear message, no /video request; 17 · the field in each state ──────
if (want('refused')) {
  // a silent microphone, so the attempt with the camera refused and the one with the switch off score the same
  const text = {denied: 'Доступ до камери заборонено. Дозволь камеру для цієї сторінки біля адреси; поки що спроби йдуть без відео.', absent: 'Камеру не знайдено. Підключи її; поки що спроби йдуть без відео.', busy: 'Камера зайнята іншою програмою або вкладкою; спроби йдуть без відео.'};
  async function refused(c, plainScore) {
    await setCamera(c.page, true);
    const r = await sit(c.page, {seconds: 2, during: async () => toastText(c.page)});
    const gum = await c.page.evaluate(() => window.__gum.filter(x => x.audio)), tk = await c.page.evaluate(() => window.Luma.test.takes()[0]);
    await c.page.evaluate(() => window.LumaActivity.flush()); await sleep(300);
    const events = readdirSync(join(A.lib, 'logs', 'activity')).flatMap(f => readFileSync(join(A.lib, 'logs', 'activity', f), 'utf8').trim().split('\n')).map(l => JSON.parse(l)).filter(e => e.type === 'video_capture' && e.data.reason === c.why);
    await c.page.locator('#settingsBtn').click(); await c.page.waitForTimeout(300);
    const line = await c.page.evaluate(() => document.getElementById('camState').textContent);
    await c.page.locator('#settingsDialog [data-close]').first().click();
    assert(gum.length === 2 && gum[0].video && !gum[1].video && r.mid === 'Камера недоступна: спроба без відео.' && line === text[c.why] && events.length >= 1 && c.video.length === 0,
      `camera ${c.why}: sings audio-only, the toast, the state line, video_capture {ok:false, reason:'${c.why}'}, no /video request ` + JSON.stringify({gum, toast: r.mid, line, events: events.length, video: c.video}));
    assert(!tk.hasAudio && tk.pct === plainScore.pct && tk.points > 0, `camera ${c.why}: the attempt is what it is with the switch off (no WAV forced, score ${tk.pct} = ${plainScore.pct})`);
    await settingsLayout(c.page, c.why, true);
    assert(c.logs.length === 0, `camera ${c.why}: console clean ` + JSON.stringify(c.logs));
    await c.page.close();
  }
  const quiet = await open(media(silentWav));
  const plainScore = await (async () => { const {page} = await trainer(quiet, demoA); await sit(page, {seconds: 2}); const t = await page.evaluate(() => window.Luma.test.takes()[0]); await page.close(); return t; })();
  for (const why of ['absent', 'busy']) await refused({why, ...await trainer(quiet, demoA, {failVideo: why === 'absent' ? 'NotFoundError' : 'NotReadableError'})}, plainScore);
  // on a phone the toast of a refused camera rises above the transport and the stage rail during the count-in
  { const c = await trainer(quiet, demoA, {viewport: {width: 390, height: 844}, failVideo: 'NotReadableError'}); await setCamera(c.page, true);
    await c.page.locator('#singBtn').click(); await c.page.waitForFunction(() => document.getElementById('toast').classList.contains('show'), null, {timeout: 10000}); await c.page.waitForTimeout(400);
    const t = await c.page.evaluate(() => { const r = e => { const q = e.getBoundingClientRect(); return [q.left, q.top, q.right, q.bottom]; }, el = document.getElementById('toast'), tr = r(el);
      const under = [...document.querySelectorAll('button, select, input')].filter(b => b.checkVisibility() && b.getBoundingClientRect().width).map(b => ({id: b.id || b.textContent.trim().slice(0, 16), r: r(b)}))
        .filter(b => b.r[0] < tr[2] && tr[0] < b.r[2] && b.r[1] < tr[3] && tr[1] < b.r[3]);
      return {text: el.textContent, toast: tr.map(Math.round), under, mode: window.Luma.test.state().mode}; });
    if (shot('toast_390')) await c.page.screenshot({path: shot('toast_390')});
    assert(t.text === 'Камера недоступна: спроба без відео.' && t.under.length === 0 && t.toast[1] >= 0, 'at 390 px the camera toast covers no control during the count-in ' + JSON.stringify(t));
    await c.page.locator('#stopBtn').click(); await c.page.waitForFunction(() => window.Luma.test.state().mode === 'idle' && !window.Luma.diagnostics().pending, null, {timeout: 30000});
    assert(c.logs.length === 0, 'console clean through the phone toast ' + JSON.stringify(c.logs)); await c.page.close(); }
  await close(quiet);
  // denied: full Chromium in its new headless mode, which asks for permissions as a window does (the default headless
  // shell refuses every prompt as unsupported); the context grants the microphone only
  const denied = await open(null, () => chromium.launch({headless: true, ...(process.env.LUMA_BROWSER ? {executablePath: process.env.LUMA_BROWSER} : {channel: 'chromium'}), args: ['--no-sandbox', '--disable-gpu', ...media(silentWav, false)]}));
  const ctx = await denied.newContext({viewport: {width: 1440, height: 900}}); await ctx.grantPermissions(['microphone'], {origin: A.base});
  await refused({why: 'denied', ...await trainer(denied, demoA, {context: ctx})}, plainScore);
  await close(denied);
}

// ── 11, 15 · a «Заняття» session against Studio's 30 s rule: a full demo pass is 29.96 s ───────────────────────────────
if (want('session')) {
  const B = await studio('B'); for (const n of ['Luma_Video_One.html', 'Luma_Video_Two.html']) copyFileSync('examples/demo/Luma_Demo.html', join(B.lib, n));
  const browser = await open(), page = await browser.newPage({viewport: {width: 1440, height: 900}}), logs = [], takes = [], cams = new Set();
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) logs.push(m.type() + ': ' + m.text()); });
  page.on('requestfinished', async r => { const u = new URL(r.url()); if (/\/take$/.test(u.pathname) && r.method() === 'PUT') { const res = await r.response(); takes.push({at: Date.now(), path: u.pathname, body: await res.json().catch(() => null)}); }
    const m = /^\/video\/([0-9a-f-]{36})\/camera$/.exec(u.pathname); if (m) cams.add(m[1]); });
  // both clocks in the browser: when the trainer had Studio's answer to its take record, when Studio got luma:finished
  await page.addInitScript(() => {
    if (window !== window.top) { const f = window.fetch; window.fetch = async (u, o) => { const r = await f(u, o); if (o?.method === 'PUT' && /\/take$/.test(String(u))) window.top.__took.push(Date.now()); return r; }; return; }
    window.__fin = []; window.__took = []; addEventListener('message', e => { if (e.data?.type === 'luma:finished') window.__fin.push(Date.now()); }); });
  await page.goto(B.base + '/'); await page.evaluate(() => localStorage.setItem('luma.trainer.settings', JSON.stringify({camera: true, audioNotice: true})));
  await page.waitForFunction(() => document.querySelectorAll('#lib .song').length === 2, null, {timeout: 10000});
  await page.evaluate(() => { openSession([]); showPicker(); });
  await page.locator('#sessionBody .song button.primary').first().click();
  await page.waitForFunction(() => window.__fin.length >= 1, null, {timeout: 70000});
  const {fin, took} = await page.evaluate(() => ({fin: window.__fin[0], took: window.__took[0]})), first = [...cams][0];
  const allow = await page.evaluate(() => document.querySelector('#session iframe')?.allow || '');
  assert(takes.length === 1 && took && took <= fin && takes[0].body?.composed === false && takes[0].body?.reason === 'short' && !existsSync(join(B.lib, 'videos', first)),
    'a full demo pass (29.96 s) is under Studio\'s 30 s: refused as short and deleted, and the answer reached the trainer before luma:finished reached Studio ' + JSON.stringify({takes, took, fin}));
  assert(/\bcamera\b/.test(allow), 'the session frame allows the camera: ' + allow);
  const toasts = await page.evaluate(() => [...document.querySelectorAll('#session iframe')].map(f => f.contentDocument?.getElementById('toast')?.textContent));
  assert(toasts.includes('Спроба коротша за 30 с: відео не змонтовано.'), 'and the trainer said so ' + JSON.stringify(toasts));
  const deadline = Date.now() + 20000; while (cams.size < 2 && Date.now() < deadline) await sleep(250);
  const second = [...cams].find(x => x !== first);
  assert(second && existsSync(join(B.lib, 'videos', second)), 'the next step films into a new folder ' + JSON.stringify([...cams]));
  await page.evaluate(() => leaveSession()); await sleep(800);
  assert(logs.length === 0, 'console clean through the session ' + JSON.stringify(logs));
  await close(browser);
  for (const id of cams) await rawRequest(B, 'DELETE', '/video/' + id);
}

// ── 12 · the 5 GB rule in small: a budget that fits two videos, a restart, the oldest goes ──────────────────────────────
if (want('budget')) {
  const libC = join(tmp, 'C');
  // each sitting in a browser of its own, closed before its video composes
  const sitting = async st => { const b = await open(), {page} = await trainer(b, st.base + '/demo'); await setCamera(page, true); const r = await sit(page, {seconds: 3}); await close(b); await settle(st, r.id); return r; };
  let C = await studio('C', ['--video-min-seconds', '3'], {}, libC);
  const first = await sitting(C);
  const one = await listing(C), size = one.videos[0].bytes, budget = one.used + Math.round(1.5 * size);
  await stopStudio(C);   // the budget is the new process's: it is read again at start, and nothing here is kept in memory
  C = await studio('C2', ['--video-min-seconds', '3', '--video-budget', String(budget)], {}, libC);
  const restarted = await listing(C);
  const second = await sitting(C), two = await listing(C);
  const third = await sitting(C); await sleep(500);
  const three = await listing(C), ids = three.videos.map(v => v.id);
  assert(restarted.videos.length === 1 && restarted.budget === budget && two.videos.length === 2, 'after a restart with the new budget the first video stays, and two fit ' + JSON.stringify({budget, two: two.used}));
  assert(ids.length === 2 && ids[0] === third.id && ids[1] === second.id && three.used <= three.budget && !existsSync(join(libC, 'videos', first.id)),
    'the third compose deletes the oldest: /videos lists the two newest and used ≤ budget ' + JSON.stringify({ids, used: three.used, budget: three.budget}));
  const browser = await open([]), studioPage = await browser.newPage({viewport: {width: 1440, height: 900}});
  await studioPage.goto(C.base + '/#video/' + first.id); await studioPage.waitForFunction(() => document.getElementById('player').open, null, {timeout: 8000});
  const gone = await studioPage.evaluate(() => ({meta: document.getElementById('playerMeta').textContent, video: !document.getElementById('playerVideo').hidden}));
  assert(gone.meta === 'Цього відео вже немає: найстаріші видаляються самі, щоб відео займали не більше 5 ГБ.' && !gone.video, 'a link to an evicted video says why it is gone ' + JSON.stringify(gone));
  await close(browser);
}

// ── 18 · process hygiene ───────────────────────────────────────────────────────────────────────────────────────────
for (const b of [...browsers]) await close(b);
for (const st of studios) { const busy = (await listing(st).catch(() => ({videos: []}))).videos.filter(v => !['ready', 'failed', 'recording'].includes(v.state)); for (const v of busy) await settle(st, v.id); }
for (const st of studios) await stopStudio(st);
await sleep(300);
const leftover = readdirSync('/proc').filter(p => /^\d+$/.test(p)).filter(p => { try { return readFileSync(`/proc/${p}/cmdline`, 'utf8').includes(tmp); } catch (_) { return false; } });
const profiles = execFileSync('find', [tmp, '-name', '.profile'], {encoding: 'utf8'}).trim();
assert(leftover.length === 0 && !profiles, 'no process of the suite outlives it and no render profile is left ' + JSON.stringify({leftover, profiles}));
if (!process.env.VIDEO_KEEP) rmSync(tmp, {recursive: true, force: true}); else console.log('kept', tmp);
