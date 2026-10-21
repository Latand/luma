#!/usr/bin/env python3
"""Camera videos of a sitting (docs/design/CAMERA_VIDEO.md, docs/design/CAMERA_VIDEO_BUILD_BRIEF.md).

The trainer streams one camera webm per sitting and uploads each attempt's microphone WAV and a take record. This module
stores them under songs/videos/<id>/, places the camera on the song timeline by cross-correlating the webm's own audio
with the WAVs, has a headless browser draw the game layer with the trainer's own code (the render page encodes H.264 and
streams it back), and composes the MP4 with ffmpeg: the game full frame, the camera in a circle, the voice over the
instrumental. One worker thread owns the queue and the size budget; nothing here blocks a request on that work.

Timeline (brief §3 D9). Times are AudioContext seconds of the trainer. Segment k starts its music at when_k, its WAV starts
at when_k + lag_k and its stop is stop_k. Output second u shows the music and the game at when_1 + u, the voice and the
camera at when_1 + u + lag (the latency applied once). W0 is the AudioContext time of the webm's t = 0.
"""
from __future__ import annotations
import base64, hashlib, json, math, os, re, shutil, signal, subprocess, threading, time
from pathlib import Path

import numpy as np

SR = 48000; FPS = 30; W, H = 1920, 1080; ENC_THREADS = 4
CAM = {'x': 72, 'y': 570, 'size': 300}
ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
MAX_TAKE = 32 << 20; MAX_CHUNK = 16 << 20; MAX_VOICE = 700 << 20; MAX_GAME = 64 << 20; MAX_SEGMENTS = 64
STALE = 3600            # a folder with no take record and no write for an hour is a closed or crashed tab
SEARCH = .5             # how far from the stamp estimate the correlation looks for the webm's start, seconds
STAMP = .018            # the webm's t = 0 sits this long after recorder.start() on average (design §2.4)
BROWSERS = ('msedge', '/opt/microsoft/msedge/msedge', 'google-chrome', 'chromium')
SONG_MARK, ASSETS_MARK, END_MARK = b'<script>window.LUMA_SONG=', b';window.LUMA_ASSETS=', b'};</script>'

class Cancelled(Exception): pass
class Failed(Exception): pass

def run(cmd, **kw): return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
def nice(cmd): return ['nice', '-n', '19', *map(str, cmd)] if shutil.which('nice') else list(map(str, cmd))

# ── alignment ──────────────────────────────────────────────────────────────────────────────────────────────────────
def decode(path: Path, stream: str = 'a:0') -> np.ndarray:
    """Mono float32 at 48 kHz of one audio stream, from its first decoded sample."""
    out = run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(path), '-map', '0:' + stream, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-']).stdout
    return np.frombuffer(out, dtype='<f4').astype(np.float64)

def probe(path: Path) -> dict:
    return json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]).stdout)

def starts(path: Path) -> tuple[float, float]:
    """Where the audio and the video stream begin on the file's own timeline (ffmpeg subtracts the format start)."""
    p = probe(path); t0 = float(p.get('format', {}).get('start_time') or 0); a = v = 0.0
    for s in p.get('streams', []):
        st = float(s.get('start_time') or t0) - t0
        if s.get('codec_type') == 'audio': a = st
        elif s.get('codec_type') == 'video': v = st
    return a, v

def ncc(ref: np.ndarray, sig: np.ndarray) -> np.ndarray:
    """Normalized cross-correlation: c[d] is how well sig[d : d + len(ref)] matches ref, in −1…1."""
    n, m = len(ref), len(sig)
    if n == 0 or m < n: return np.zeros(0)
    size = 1 << int(math.ceil(math.log2(n + m)))
    c = np.fft.irfft(np.fft.rfft(sig, size) * np.conj(np.fft.rfft(ref, size)), size)[:m - n + 1]
    cs = np.concatenate(([0.0], np.cumsum(sig * sig))); energy = np.maximum(cs[n:] - cs[:-n], 0)
    norm = math.sqrt(float(ref @ ref)) * np.sqrt(energy)
    with np.errstate(divide='ignore', invalid='ignore'): out = np.where(norm > 1e-9, c / np.where(norm > 1e-9, norm, 1), 0.0)
    return out

def locate(ref: np.ndarray, pcm: np.ndarray, guess: float, search: float = SEARCH) -> dict:
    """Where ref starts in pcm (seconds), looked for within ±search of guess. peak: the best normalized correlation;
    second: the best one more than 50 ms away from it, which a periodic signal makes almost as high."""
    lo = max(0, int(round((guess - search) * SR))); hi = int(round((guess + search) * SR)) + len(ref)
    c = ncc(ref, pcm[lo:hi])
    if not len(c) or not np.isfinite(c).all(): return {'at': None, 'peak': 0.0, 'second': 0.0}
    k = int(np.argmax(c)); peak = float(c[k]); shift = 0.0
    if 0 < k < len(c) - 1:
        a, b, d = c[k - 1], c[k], c[k + 1]; den = a - 2 * b + d
        if abs(den) > 1e-12: shift = max(-1.0, min(1.0, .5 * (a - d) / den))
    away = int(.05 * SR); rest = np.concatenate((c[:max(0, k - away)], c[k + away + 1:]))
    return {'at': (lo + k + shift) / SR, 'peak': peak, 'second': float(rest.max()) if len(rest) else 0.0}

def align(pcm: np.ndarray, audio_start: float, wavs: list[np.ndarray], segments: list[dict], stamp: float) -> dict:
    """W0, the AudioContext time of the webm's t = 0 (its file timeline), from the webm's own microphone track.

    pcm: the webm's audio from its first sample, which sits at audio_start on the file timeline. wavs[k]: segment k's
    WAV, which starts at AudioContext time when_k + lag_k. The longest segment decides; the others report how far their
    own peaks fall from where W0 puts them (residuals, seconds). A weak or repeating peak falls back to the stamp."""
    guess_w0 = stamp + STAMP
    best = max(range(len(wavs)), key=lambda k: len(wavs[k])) if wavs else None
    out = {'stamp': stamp, 'W0': guess_w0, 'peak': 0.0, 'second': 0.0, 'approximateSync': True, 'residuals': [], 'spread': None, 'segment': best}
    if best is None: return out
    def place(k, w0):
        # the recorder stops when the attempt does, so its last chunk can end a little before the WAV: the tail stays out
        seg = segments[k]; start = seg['when'] + seg['latency'] / 1000; w = wavs[k]; ref = w[:min(30 * SR, max(len(w) * 3 // 4, len(w) - SR))]
        if len(ref) < SR // 2 or float(ref @ ref) < 1e-6: return None
        return locate(ref, pcm, start - w0 - audio_start)
    hit = place(best, guess_w0)
    if not hit or hit['at'] is None: return out
    out.update(peak=round(hit['peak'], 4), second=round(hit['second'], 4))
    if hit['peak'] < .5 or hit['second'] >= .7 * hit['peak']: return out
    seg = segments[best]; w0 = seg['when'] + seg['latency'] / 1000 - (hit['at'] + audio_start)
    res = []
    for k in range(len(wavs)):
        h = place(k, w0)
        if h and h['at'] is not None and h['peak'] >= .5:
            s = segments[k]; res.append(round((s['when'] + s['latency'] / 1000 - w0 - audio_start) - h['at'], 5))
    out.update(W0=w0, approximateSync=False, residuals=res, spread=round(max(res) - min(res), 5) if res else None)
    return out

def aligned(d: Path, take: dict) -> dict:
    """align() over a sitting's folder. The decoded audio (float64, about 200 MB for a 4-minute sitting) lives only in
    here, so none of it is held while the render and the compose run."""
    a0, _ = starts(d / 'camera.webm'); pcm = decode(d / 'camera.webm')
    wavs = [decode(d / f'voice-{k}.wav') for k in range(len(take['segments']))]
    return align(pcm, a0, wavs, take['segments'], float(take['ctxAtStart']))

# ── compose ────────────────────────────────────────────────────────────────────────────────────────────────────────
def compose_cmd(game: Path, camera: Path | None, voices: list[Path], stem: Path | None, take: dict, cam_offset: float, out: Path) -> list[str]:
    """One ffmpeg run. The game layer is the base; the camera, cut to its centre square, sits in a soft-edged circle at
    (72, 570) and holds its last frame; each voice and each instrumental piece is delayed to its segment's place."""
    segs = take['segments']; t1 = segs[0]['when']; dur = duration(take); back = float(take.get('back', .75)); n = len(segs)
    # x264 sizes its thread pool by the cores (24 threads on 16 cores, 0.8 GB at 1080p); four keep it near 0.4 GB and leave
    # the cores to a trainer that sings on while a video composes
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-threads', '2', '-f', 'h264', '-framerate', str(FPS), '-i', str(game)]
    graph = [f'[0:v]setpts=N/({FPS}*TB),scale=out_range=tv,format=yuv420p[g]']; i = 1
    if camera:
        cmd += ['-threads', '2', '-i', str(camera)]; r = CAM['size']; c = (r - 1) / 2
        graph.append(f'[{i}:v]setpts=PTS+({cam_offset:.6f})/TB,fps=fps={FPS}:start_time=0,crop=min(iw\\,ih):min(iw\\,ih),scale={r}:{r}:out_range=tv,format=yuva420p,'
                     f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='255*clip({r / 2:.1f}-hypot(X-{c},Y-{c}),0,1)',tpad=stop_mode=clone:stop_duration={dur + 1:.3f}[c]")
        graph.append(f"[g][c]overlay={CAM['x']}:{CAM['y']}:eof_action=repeat,format=yuv420p[v]"); i += 1
    else: graph.append('[g]null[v]')
    mix = []
    for k, path in enumerate(voices):
        cmd += ['-i', str(path)]; delay = round((segs[k]['when'] - t1) * SR)
        graph.append(f'[{i}:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.9,adelay=delays={delay}S:all=1[vo{k}]'); mix.append(f'[vo{k}]'); i += 1
    # one input of the stem per segment: an asplit of a single input would hold every later segment's copy in memory
    # until its delay ran out (about 1 GB for a 4-minute sitting of eight rewinds); separate inputs are read on demand
    for k, s in enumerate(segs if stem else []):
        cmd += ['-i', str(stem)]; delay = round((s['when'] - t1) * SR)
        graph.append(f"[{i}:a]aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=start={s['a'] / s['speed']:.6f}:duration={s['stop'] - s['when']:.6f},"
                     f"asetpts=PTS-STARTPTS,volume={back:.4f},adelay=delays={delay}S:all=1[bk{k}]"); mix.append(f'[bk{k}]'); i += 1
    if mix: graph.append(''.join(mix) + f'amix=inputs={len(mix)}:normalize=0:duration=longest,alimiter=limit=0.95:level=false:latency=true,apad[a]')
    else: graph.append(f'anullsrc=r={SR}:cl=stereo[a]')
    cmd += ['-filter_complex', ';'.join(graph), '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-threads', str(ENC_THREADS), '-preset', 'veryfast', '-crf', '22', '-maxrate', '5M', '-bufsize', '10M',
            '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-r', str(FPS), '-c:a', 'aac', '-b:a', '192k', '-ar', str(SR), '-ac', '2', '-movflags', '+faststart',
            '-t', f'{dur:.3f}', '-f', 'mp4', str(out)]
    return cmd

def duration(take: dict) -> float:
    s = take['segments']; return s[-1]['stop'] - s[0]['when']

def checked(path: Path, dur: float) -> dict:
    """ffprobe of a composed file: H.264 1920×1080 and AAC, the expected length. Failed when it is not."""
    p = probe(path); v = next((s for s in p['streams'] if s.get('codec_type') == 'video'), None); a = next((s for s in p['streams'] if s.get('codec_type') == 'audio'), None)
    got = float(p.get('format', {}).get('duration') or 0)
    if not v or not a or v.get('codec_name') != 'h264' or (v.get('width'), v.get('height')) != (W, H) or a.get('codec_name') != 'aac' or abs(got - dur) > .2:
        raise Failed('Готовий файл не пройшов перевірку')
    return {'duration': got}

# ── the instrumental: the trainer's own backing stem ───────────────────────────────────────────────────────────────
def backing_bytes(trainer: Path, speed: float) -> bytes:
    """LUMA_ASSETS[speed].backing of a trainer file: the exact audio the singer heard."""
    data = trainer.read_bytes(); a = data.find(ASSETS_MARK); e = data.find(END_MARK, a) if a >= 0 else -1
    if e < 0: raise Failed('У тренажері немає мінусу')
    assets = json.loads(data[a + len(ASSETS_MARK):e + 1]); key = '1' if speed == 1 else '0.8'
    try: return base64.b64decode(assets[key]['backing'])
    except (KeyError, TypeError, ValueError): raise Failed('У тренажері немає мінусу для цієї швидкості')

# ── the store ──────────────────────────────────────────────────────────────────────────────────────────────────────
def folder_bytes(d: Path) -> int:
    n = 0
    for root, _, files in os.walk(d):
        for f in files:
            try: n += os.lstat(os.path.join(root, f)).st_size
            except OSError: pass
    return n

def number(v, lo=-1e9, hi=1e9) -> bool: return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi

def valid_take(t: dict, vid: str) -> str:
    """'' when the take record can be composed, else what is wrong with it."""
    if not isinstance(t, dict) or t.get('v') != 1 or t.get('id') != vid: return 'id'
    if not isinstance(t.get('trainer'), str) or not t['trainer'] or len(t['trainer']) > 300: return 'trainer'
    for k in ('ctxAtStart', 'back'):
        if not number(t.get(k), -1, 1e7): return k
    segs = t.get('segments')
    if not isinstance(segs, list) or not 0 < len(segs) <= MAX_SEGMENTS: return 'segments'
    prev = -1e9
    for s in segs:
        if not isinstance(s, dict): return 'segment'
        for k in ('when', 'cin', 'stop', 'a', 'endSong'):
            if not number(s.get(k), -1, 1e7): return k
        if s.get('speed') not in (1, .8) or not number(s.get('latency'), -500, 1000): return 'speed'
        if not s['cin'] <= s['when'] < s['stop'] or s['when'] < prev or not isinstance(s.get('history'), dict): return 'times'
        if s.get('lives') is not None and not isinstance(s['lives'], dict): return 'lives'
        prev = s['stop']
    if duration(t) > 3600: return 'duration'
    if t.get('dust') is not None and not isinstance(t['dust'], dict): return 'dust'
    return ''

class Videos:
    """songs/videos: one folder per sitting. One worker thread composes the queue in order and keeps the budget."""
    def __init__(self, songs: Path, root: Path, base: str = '', budget: int = 5 << 30, min_seconds: float = 30, deadline_factor: float = 3,
                 deadline_extra: float = 60, browser: str | None = None):
        self.dir = songs / 'videos'; self.stems = self.dir / '.stems'; self.songs = songs; self.root = root; self.base = base
        self.budget = budget; self.min_seconds = min_seconds; self.deadline_factor = deadline_factor; self.deadline_extra = deadline_extra
        self.browser_override = browser
        self.lock = threading.Lock(); self.seq: dict[str, int] = {}; self.game_seq: dict[str, int] = {}; self.state: dict[str, dict] = {}
        self.queue: list[str] = []; self.wake = threading.Event(); self.current: str | None = None; self.cancel: set[str] = set()
        self.proc: subprocess.Popen | None = None; self.render_done = threading.Event(); self.render_error: str | None = None; self.cache: dict[str, tuple[float, dict]] = {}
        self.dir.mkdir(parents=True, exist_ok=True)

    # paths and record
    def path(self, vid: str) -> Path:
        if not ID.match(vid or ''): raise KeyError(vid)
        return self.dir / vid
    def take(self, vid: str) -> dict | None:
        p = self.path(vid) / 'take.json'
        try: m = p.stat().st_mtime
        except OSError: return None
        hit = self.cache.get(vid)
        if hit and hit[0] == m: return hit[1]
        try: t = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError): return None
        self.cache[vid] = (m, t); return t
    def trainer(self, take: dict) -> Path | None:
        name = take.get('trainer', '')
        if name == 'demo': p = self.root / 'examples' / 'demo' / 'Luma_Demo.html'
        else: p = self.songs / os.path.basename(name)
        return p if p.is_file() and p.suffix == '.html' else None

    # writes from the trainer
    def append_camera(self, vid: str, seq: int, body: bytes) -> int:
        d = self.path(vid)
        with self.lock:
            if (d / 'take.json').exists() or seq != self.seq.get(vid, 0) or (seq and not d.is_dir()): return 409
            try:
                d.mkdir(exist_ok=True)
                with open(d / 'camera.webm', 'ab') as f: f.write(body)
            except OSError: return 507
            self.seq[vid] = seq + 1
        return 200
    def put_voice(self, vid: str, k: int, rfile, n: int) -> int:
        d = self.path(vid)
        if not 0 <= k < MAX_SEGMENTS or not d.is_dir() or (d / 'take.json').exists(): return 409
        part = d / f'voice-{k}.wav.part'; left = n
        try:
            with open(part, 'wb') as f:
                while left:
                    chunk = rfile.read(min(left, 1 << 20))
                    if not chunk: break
                    f.write(chunk); left -= len(chunk)
            if left: part.unlink(missing_ok=True); return 400
            os.replace(part, d / f'voice-{k}.wav')
        except OSError: part.unlink(missing_ok=True); return 507
        return 200
    def put_take(self, vid: str, body: bytes) -> tuple[int, dict]:
        d = self.path(vid)
        try: t = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeError): t = None
        bad = valid_take(t, vid) if t is not None else 'json'
        if not bad and not (d / 'camera.webm').is_file(): bad = 'camera'
        if not bad and not all((d / f'voice-{k}.wav').is_file() for k in range(len(t['segments']))): bad = 'voice'
        if not bad and not self.trainer(t): bad = 'trainer'
        if bad: return 400, {'composed': False, 'reason': 'invalid', 'detail': bad}
        if duration(t) < self.min_seconds:
            self.remove(vid); return 200, {'composed': False, 'reason': 'short', 'duration': round(duration(t), 2)}
        try: (d / 'take.json.part').write_bytes(body); os.replace(d / 'take.json.part', d / 'take.json')
        except OSError: return 507, {'composed': False, 'reason': 'invalid', 'detail': 'write'}
        with self.lock: self.seq.pop(vid, None); self.state[vid] = {'state': 'queued', 'progress': 0}; self.queue.append(vid)
        self.wake.set(); return 200, {'composed': True, 'id': vid}
    def remove(self, vid: str) -> bool:
        d = self.path(vid)
        with self.lock:
            self.seq.pop(vid, None); self.state.pop(vid, None); self.cache.pop(vid, None)
            if vid in self.queue: self.queue.remove(vid)
            if self.current == vid: self.cancel.add(vid); self.stop_render()
        existed = d.exists(); shutil.rmtree(d, ignore_errors=True); return existed

    # writes from the render page
    def append_game(self, vid: str, seq: int, body: bytes, frames: int | None) -> int:
        d = self.path(vid)
        with self.lock:
            if self.current != vid or seq != self.game_seq.get(vid, 0): return 409
            try:
                with open(d / 'game.h264', 'ab') as f: f.write(body)
            except OSError: return 507
            self.game_seq[vid] = seq + 1
            if frames is not None and vid in self.state: self.state[vid]['frames'] = frames
        return 200
    def rendered(self, vid: str, error: str | None = None) -> int:
        with self.lock:
            if self.current != vid: return 409
            self.render_error = error; self.render_done.set()
        return 200

    # the listing
    def listing(self) -> dict:
        out = []
        for d in sorted(self.dir.iterdir()) if self.dir.is_dir() else []:
            if not d.is_dir() or not ID.match(d.name): continue
            vid = d.name; t = self.take(vid); st = dict(self.state.get(vid) or {})
            if (d / 'video.mp4').is_file(): state = 'ready'
            elif (d / 'failed.json').is_file():
                state = 'failed'
                try: st['error'] = json.loads((d / 'failed.json').read_text(encoding='utf-8')).get('error')
                except (OSError, ValueError): st['error'] = None
            elif t: state = st.get('state') or 'queued'
            else: state = 'recording'
            item = {'id': vid, 'state': state, 'bytes': folder_bytes(d), 'title': None, 'startedAt': None, 'duration': None, 'segments': 0, 'progress': None}
            if t: item.update(title=t.get('title'), startedAt=t.get('startedAt'), duration=round(duration(t), 2), segments=len(t['segments']))
            if state == 'rendering':
                exp = max(1, math.ceil((item['duration'] or 0) * FPS)); item['progress'] = min(.99, (st.get('frames') or 0) / exp)
            if state == 'failed': item['error'] = st.get('error')
            if (d / 'align.json').is_file():
                try: item['approximateSync'] = json.loads((d / 'align.json').read_text(encoding='utf-8')).get('approximateSync')
                except (OSError, ValueError): pass
            out.append(item)
        out.sort(key=lambda v: v['startedAt'] or '', reverse=True)
        return {'videos': out, 'used': folder_bytes(self.dir), 'budget': self.budget}

    # the budget
    def evict(self) -> list[str]:
        """Whole folders, oldest first, until everything under songs/videos (the stems cache included) fits the budget.
        Never the folder being composed, a sitting still recording, or the newest ready video; a stale incomplete folder
        (no take record, no write for an hour) goes first."""
        gone = []; now = time.time(); entries = []
        for d in self.dir.iterdir() if self.dir.is_dir() else []:
            if not d.is_dir() or not ID.match(d.name): continue
            t = self.take(d.name); ready = (d / 'video.mp4').is_file()
            try: touched = max((f.stat().st_mtime for f in d.iterdir()), default=d.stat().st_mtime)
            except OSError: touched = now
            entries.append({'id': d.name, 'take': t, 'ready': ready, 'stale': not t and now - touched > STALE, 'recording': not t and now - touched <= STALE,
                            'started': (t or {}).get('startedAt') or ''})
        for e in entries:
            if e['stale']: shutil.rmtree(self.dir / e['id'], ignore_errors=True); gone.append(e['id'])
        ready = sorted((e for e in entries if e['ready']), key=lambda e: e['started']); newest = ready[-1]['id'] if ready else None
        order = sorted((e for e in entries if not e['stale'] and not e['recording'] and e['id'] != self.current and e['id'] != newest), key=lambda e: e['started'])
        used = folder_bytes(self.dir)
        for e in order:
            if used <= self.budget: break
            d = self.dir / e['id']; n = folder_bytes(d); shutil.rmtree(d, ignore_errors=True); used -= n; gone.append(e['id'])
            with self.lock:
                if e['id'] in self.queue: self.queue.remove(e['id'])
                self.state.pop(e['id'], None)
        return gone

    # the worker
    def start(self):
        """At startup: drop stale incomplete folders, requeue every take record without an MP4 or a failure, keep the
        budget, then compose in the background."""
        folders = [d for d in self.dir.iterdir() if d.is_dir() and ID.match(d.name)] if self.dir.is_dir() else []
        for d in sorted(folders, key=lambda d: (self.take(d.name) or {}).get('startedAt') or ''):
            shutil.rmtree(d / '.profile', ignore_errors=True)
            for f in ('game.h264', 'video.mp4.part'): (d / f).unlink(missing_ok=True)
            if self.take(d.name) and not (d / 'video.mp4').is_file() and not (d / 'failed.json').is_file():
                self.state[d.name] = {'state': 'queued', 'progress': 0}; self.queue.append(d.name)
        self.evict()
        threading.Thread(target=self.loop, daemon=True, name='video').start()
    def loop(self):
        while True:
            with self.lock: vid = self.queue.pop(0) if self.queue else None; self.current = vid
            if not vid: self.wake.wait(5); self.wake.clear(); continue
            try: self.compose(vid)
            except Cancelled: shutil.rmtree(self.dir / vid, ignore_errors=True)
            except Exception as e:   # one broken video must not stop the queue; its folder says why
                self.fail(vid, str(e) if isinstance(e, Failed) else 'Монтаж зупинився: ' + type(e).__name__)
            finally:
                with self.lock: self.current = None; self.cancel.discard(vid); self.game_seq.pop(vid, None)
                try: self.evict()
                except OSError: pass
    def fail(self, vid: str, error: str):
        d = self.dir / vid
        if not d.is_dir(): return
        try: (d / 'failed.json').write_text(json.dumps({'error': error}, ensure_ascii=False), encoding='utf-8')
        except OSError: pass
        for f in ('game.h264', 'video.mp4.part'): (d / f).unlink(missing_ok=True)
        with self.lock: self.state[vid] = {'state': 'failed', 'error': error}
    def step(self, vid: str, state: str):
        with self.lock:
            if vid in self.cancel: raise Cancelled()
            self.state[vid] = {'state': state, 'progress': 0}

    def compose(self, vid: str):
        d = self.dir / vid; t = self.take(vid)
        if not t: raise Failed('Немає запису спроби')
        dur = duration(t); segs = t['segments']
        self.step(vid, 'aligning')
        al = aligned(d, t); (d / 'align.json').write_text(json.dumps(al), encoding='utf-8')
        self.step(vid, 'rendering'); self.render(vid, dur)
        game = d / 'game.h264'
        if not game.is_file() or game.stat().st_size == 0: raise Failed('Шар гри не намальовано')
        self.step(vid, 'composing')
        stem = self.stem(t)
        # camera frame at file time τ lands at output u = τ + W0 − when₁ − lag₁ (brief §5.4, step 3)
        offset = al['W0'] - segs[0]['when'] - segs[0]['latency'] / 1000
        part = d / 'video.mp4.part'
        try: run(nice(compose_cmd(game, d / 'camera.webm', [d / f'voice-{k}.wav' for k in range(len(segs))], stem, t, offset, part)))
        except subprocess.CalledProcessError as e: raise Failed('ffmpeg: ' + e.stderr.decode(errors='replace')[-300:])
        checked(part, dur)
        try: run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{dur * .4:.2f}', '-f', 'mp4', '-i', str(part), '-frames:v', '1', '-vf', 'scale=480:-2', '-q:v', '4', str(d / 'thumb.jpg')])
        except subprocess.CalledProcessError: pass
        for f in ['camera.webm', 'game.h264', *[f'voice-{k}.wav' for k in range(len(segs))]]: (d / f).unlink(missing_ok=True)
        # the MP4 arrives last: a folder with video.mp4 in it is a finished video, raw sources gone
        os.replace(part, d / 'video.mp4')
        with self.lock: self.state.pop(vid, None)

    def stem(self, t: dict) -> Path | None:
        """The instrumental at the take's speed, decoded once per (trainer file, mtime, speed) into songs/videos/.stems."""
        p = self.trainer(t)
        if not p: raise Failed('Тренажер цієї спроби не знайдено')
        st = p.stat(); speed = t['segments'][0]['speed']
        key = hashlib.sha1(f'{p.name}:{st.st_size}:{st.st_mtime}'.encode()).hexdigest()[:16]
        out = self.stems / f'{key}_{speed}.mp3'
        if not out.is_file():
            self.stems.mkdir(parents=True, exist_ok=True); part = out.with_name(out.name + '.part')
            part.write_bytes(backing_bytes(p, speed)); os.replace(part, out)
        return out

    def find_browser(self) -> str | None:
        for b in ([self.browser_override] if self.browser_override else []) + ([os.environ['LUMA_BROWSER']] if os.environ.get('LUMA_BROWSER') else []) + list(BROWSERS):
            p = b if os.path.isabs(b) else shutil.which(b)
            if p and os.access(p, os.X_OK): return p
        return None
    def deadline(self, dur: float) -> float: return self.deadline_factor * dur + self.deadline_extra
    def render(self, vid: str, dur: float):
        """The trainer in render mode, in a headless browser Studio starts itself. It ends at «rendered», at «render-failed»
        or at the deadline; the process group Studio started is ended either way and the profile removed."""
        browser = self.find_browser()
        if not browser: raise Failed('Для монтажу потрібен Edge або Chrome')
        d = self.dir / vid; profile = d / '.profile'; (d / 'game.h264').unlink(missing_ok=True)
        with self.lock: self.render_done.clear(); self.render_error = None; self.game_seq[vid] = 0
        cmd = nice([browser, '--headless=new', f'--user-data-dir={profile}', '--disable-gpu', '--mute-audio', '--no-first-run', '--no-default-browser-check', '--disable-extensions',
                    '--disable-background-networking', '--disable-component-update', '--disable-sync',
                    '--force-device-scale-factor=1', f'--window-size={W},{H}', '--no-sandbox', f'{self.base}/video/{vid}/render'])
        try: self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e: raise Failed('Браузер не запустився: ' + str(e))
        try:
            done = self.render_done.wait(self.deadline(dur))
            with self.lock:
                if vid in self.cancel: raise Cancelled()
            if not done: raise Failed('Шар гри не встиг намалюватися')
            if self.render_error: raise Failed('Шар гри: ' + self.render_error[:200])
        finally:
            self.stop_render(wait=True); shutil.rmtree(profile, ignore_errors=True)
    def stop_render(self, wait: bool = False):
        """End the process group of the browser this Studio started (its PID is the group's id), never anything else."""
        p = self.proc; self.render_done.set()
        if not p: return
        try: os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError): pass
        if wait:
            # The leader is left unreaped while the group is killed, so its id cannot pass to another process meanwhile.
            end = time.time() + 5
            while time.time() < end:
                try:
                    if os.waitid(os.P_PID, p.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT): break
                except ChildProcessError: break
                time.sleep(.05)
            try: os.killpg(p.pid, signal.SIGKILL)   # whatever of the group outlived the leader
            except (ProcessLookupError, PermissionError): pass
            p.wait()
            if self.proc is p: self.proc = None
