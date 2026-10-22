'use strict';
// Camera video of a sitting (docs/design/CAMERA_VIDEO_BUILD_BRIEF.md §5.1): one MediaRecorder per sitting over the camera
// + microphone stream, its 1 s chunks streamed to the Studio that served the page, in order, while the singer sings.
// No DOM and no clock of its own: the trainer passes its AudioContext clock and decides when a sitting opens and ends.
//
// LumaCamera.open(stream, {id, now, onfail}) → recorder
//   .start()           begin recording; stamps ctxAtStart (at the call) and ctxAtOnstart (at the onstart event)
//   .stop()            stop recording; resolves once the last chunk has been sent (or refused)
//   .voice(k, blob)    upload segment k's microphone WAV
//   .finish(take)      stop, wait for every upload, send the take record → {ok, composed, reason, status}
//   .abort()           stop and ask Studio to delete what it has
//   .failed            null, 'slow' (more than 8 chunks waiting) or 'refused' (Studio answered with an error or is gone)
// The tick loop never waits on any of it: uploads run on the recorder's own promise chain.
(() => {
const QUEUE = 8, TYPES = ['video/webm;codecs=h264,opus', 'video/webm;codecs=vp8,opus'];
function mime() { if (typeof MediaRecorder === 'undefined') return ''; return TYPES.find(t => MediaRecorder.isTypeSupported(t)) || ''; }
function open(stream, {id, now, onfail}) {
  const base = '/video/' + id + '/', type = mime();
  const rec = new MediaRecorder(stream, {mimeType: type, videoBitsPerSecond: 2.5e6, audioBitsPerSecond: 128e3});
  let seq = 0, waiting = 0, chain = Promise.resolve(), stopped = null, ended = false;
  const r = {id, mime: type, ctxAtStart: null, ctxAtOnstart: null, failed: null, bytes: 0, chunks: 0, uploads: [],
    get recording() { return rec.state === 'recording'; }};
  const fail = why => { if (r.failed) return; r.failed = why; try { if (rec.state !== 'inactive') rec.stop(); } catch (_) {} onfail?.(why); };
  rec.ondataavailable = e => {
    if (!e.data || !e.data.size || r.failed) return;
    if (waiting >= QUEUE) { fail('slow'); return; }
    const n = seq++, blob = e.data; waiting++; r.bytes += blob.size;
    chain = chain.then(async () => {
      if (r.failed) return;
      try { const res = await fetch(base + 'camera?seq=' + n, {method: 'PUT', body: blob}); if (!res.ok) throw Error(String(res.status)); r.chunks++; }
      catch (_) { fail('refused'); }
      finally { waiting--; }
    });
  };
  rec.onstart = () => { r.ctxAtOnstart = now(); };
  rec.onerror = () => fail('refused');
  r.start = () => { r.ctxAtStart = now(); rec.start(1000); };
  r.stop = () => {
    if (!stopped) stopped = new Promise(done => {
      if (rec.state === 'inactive') { done(); return; }
      rec.addEventListener('stop', () => done(), {once: true});
      try { rec.stop(); } catch (_) { done(); }
    }).then(() => chain);
    return stopped;
  };
  // the recorder can stop without being asked: its track ended (a camera unplugged); the chunks so far stand
  rec.addEventListener('stop', () => { ended = true; });
  r.ended = () => ended;
  r.voice = (k, blob) => { const p = fetch(base + 'voice?seg=' + k, {method: 'PUT', body: blob}).then(res => res.ok, () => false); r.uploads.push(p); return p; };
  r.finish = async take => {
    await r.stop(); const voices = await Promise.all(r.uploads);
    if (!r.chunks || voices.some(ok => !ok)) { r.abort(); return {ok: false, composed: false, reason: 'upload'}; }
    try {
      const res = await fetch(base + 'take', {method: 'PUT', body: JSON.stringify(take), headers: {'Content-Type': 'application/json'}});
      const out = await res.json().catch(() => ({}));
      return {ok: res.ok, composed: !!out.composed, reason: out.reason || (res.ok ? null : 'invalid'), status: res.status};
    } catch (_) { return {ok: false, composed: false, reason: 'offline'}; }
  };
  r.abort = () => { r.failed = r.failed || 'aborted'; try { if (rec.state !== 'inactive') rec.stop(); } catch (_) {}
    return chain.then(() => fetch(base.slice(0, -1), {method: 'DELETE'})).catch(() => {}); };
  return r;
}
window.LumaCamera = Object.freeze({open, mime});
})();
