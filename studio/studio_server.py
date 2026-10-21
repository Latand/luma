#!/usr/bin/env python3
"""Luma Studio: drop a song in the browser, get a standalone trainer. Local only, standard library, one job at a time.

  GET  /                         drop zone, queue, library
  PUT  /upload?name=&title=&artist=   raw file body -> inbox/, job queued
  PUT  /import?name=             finished trainer HTML -> re-wrapped with the current app, added to the library
  POST /retry?id=                queue a failed job again
  POST /activity                 {"events":[…]} from Studio and its trainers -> songs/logs/activity/<day>.jsonl
  GET  /status                   jobs with stage progress, library with title / artist / duration / songHash / difficulty
  GET  /targets?ids=<hash,…>     compact melody of each library trainer by song hash, for the latency estimate
  GET  /song/<name>.html         generated trainers (served over http so the microphone works)
  GET  /cover/<name>.html        the album cover cached beside that trainer's package (studio/covers.py)
  GET  /demo                     the synthetic demo trainer, if it has been built
  GET  /activity.js              the activity logger Studio shares with the trainers (docs/ACTIVITY_LOG.md)
  /video/<id>/…, GET /videos     camera videos of a sitting (studio/video.py, docs/design/CAMERA_VIDEO_BUILD_BRIEF.md §5.4)

Run: python studio/studio_server.py [--port 8792] [--songs DIR] [--copy-to DIR] [--video-budget BYTES] [--video-min-seconds S]
     [--render-deadline-factor F]
"""
from __future__ import annotations
import argparse, base64, datetime, json, os, re, shutil, subprocess, sys, threading, time, urllib.parse, uuid
import covers, difficulty, video
from array import array
from concurrent.futures import ThreadPoolExecutor
from build_html import wrap
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser(); ap.add_argument('--port', type=int, default=int(os.environ.get('LUMA_STUDIO_PORT', '8792'))); ap.add_argument('--songs', default=str(ROOT / 'songs')); ap.add_argument('--copy-to', default=os.environ.get('LUMA_COPY_TO', ''))
ap.add_argument('--video-budget', type=int, default=5 << 30, help='bytes all camera videos may take together (default 5 GiB)')
ap.add_argument('--video-min-seconds', type=float, default=30, help='a sitting shorter than this is not composed')
ap.add_argument('--render-deadline-factor', type=float, default=3, help='render deadline = factor × video length + 60 s')
args = ap.parse_args()
SONGS = Path(args.songs).expanduser().resolve(); INBOX = SONGS / 'inbox'; LOGS = SONGS / 'logs'
for d in (SONGS, INBOX, LOGS): d.mkdir(parents=True, exist_ok=True)
COPY_TO = Path(args.copy_to).expanduser() if args.copy_to else None
PREP = ROOT / 'studio' / 'prepare_song.py'
jobs: list[dict] = []; lock = threading.Lock(); upload_lock = threading.Lock()
# prepare_song.py takes songs up to 40 minutes: an uncompressed 40-minute WAV (48 kHz, 24 bit) is under 700 MB, a trainer
# of that length 350 MiB (measured). Imports are parsed in memory, uploads are streamed to disk.
MAX_UPLOAD = 1024 << 20; MAX_IMPORT = 512 << 20

# Activity log (docs/ACTIVITY_LOG.md): append-only JSONL, one file per local day. A batch is at most 64 KiB and 200
# events; anything malformed is refused whole, so a line in the file is always one well-formed event.
ACTIVITY = LOGS / 'activity'; MAX_ACTIVITY = 64 << 10; MAX_EVENTS = 200; MAX_EVENT = 16 << 10
EVENT_TYPE = re.compile(r'^[a-z][a-z0-9_]{0,39}$'); activity_lock = threading.Lock()

def activity_events(body: bytes) -> list[str]:
    """The JSONL lines of one client batch; ValueError when any event is malformed."""
    events = json.loads(body.decode('utf-8')).get('events')
    if not isinstance(events, list) or not 0 < len(events) <= MAX_EVENTS: raise ValueError('events')
    lines = []
    for e in events:
        if not isinstance(e, dict): raise ValueError('event')
        for key, n in (('ts', 40), ('session', 64), ('page', 200)):
            if not isinstance(e.get(key), str) or not 0 < len(e[key]) <= n: raise ValueError(key)
        if not isinstance(e.get('type'), str) or not EVENT_TYPE.match(e['type']): raise ValueError('type')
        data = e.get('data', {}); seq = e.get('seq')
        if not isinstance(data, dict) or (seq is not None and (not isinstance(seq, int) or isinstance(seq, bool))): raise ValueError('data')
        line = json.dumps({'v': 1, 'ts': e['ts'], 'session': e['session'], 'page': e['page'], 'seq': seq, 'type': e['type'], 'data': data}, ensure_ascii=False, separators=(',', ':'))
        if len(line.encode()) > MAX_EVENT: raise ValueError('size')
        lines.append(line)
    return lines

# Pipeline stages as prepare_song.py logs them ("[n/8] name"), with typical seconds for a 5-minute song on a mid-range GPU.
# The weights only shape the progress bar and the rough ETA; a slower machine stretches them by the observed pace.
STAGES = [('decode', 'Декодування', 3), ('separation', 'Розділення вокалу (Demucs)', 45), ('pYIN', 'Висота голосу: pYIN', 105), ('CREPE', 'Висота голосу: CREPE', 27), ('map', 'Карта мелодії', 2), ('stems', 'Доріжки MP3', 12), ('lyrics', 'Слова (Soniox)', 10), ('html', 'Збирання тренажера', 6)]
STAGE_RE = re.compile(r'^(\d\d):(\d\d):(\d\d) \[(\d)/8\] ')
TOTAL_WEIGHT = sum(w for _, _, w in STAGES)

def slugify(t): return ''.join(c if c.isalnum() else '_' for c in t).strip('_') or 'song'
def guess(name):
    stem = Path(name).stem; m = re.match(r'^(.*?)\s+-\s+(.*)$', stem)
    return (m.group(1).strip(), m.group(2).strip()) if m else (stem.strip(), '')

def read_log(job: dict) -> list[str] | None:
    try: return Path(job['log']).read_text(errors='replace').splitlines()
    except (KeyError, OSError, TypeError): return None

def stage_info(job: dict, now: float, lines: list[str] | None = None) -> dict | None:
    """Latest stage marker in the job log, with progress 0..1 and a rough ETA in seconds."""
    if lines is None: lines = read_log(job)
    if lines is None: return None
    last = None
    for line in lines:
        m = STAGE_RE.match(line)
        if m: last = (int(m.group(4)), int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if not last: return None
    n, hh, mm, ss = last; n = max(1, min(8, n)); key, name, weight = STAGES[n - 1]
    stamp = datetime.datetime.combine(datetime.date.today(), datetime.time(hh, mm, ss)).timestamp()
    if stamp > now + 60: stamp -= 86400  # the log line was written before midnight
    in_stage = max(0.0, now - stamp); done = sum(w for _, _, w in STAGES[:n - 1]); started = job.get('started') or stamp
    expected_so_far = done + min(in_stage, weight); pace = max(1.0, (now - started) / expected_so_far) if expected_so_far > 20 else 1.0
    progress = min(.99, (done + min(in_stage, weight * pace) / pace) / TOTAL_WEIGHT)
    eta = max(0.0, (TOTAL_WEIGHT - done) * pace - in_stage)
    return {'n': n, 'total': 8, 'key': key, 'name': name, 'progress': round(progress, 3), 'eta': round(eta), 'stalled': in_stage > weight * pace * 3 + 60}

_meta_cache: dict[str, tuple[tuple[int, float], dict]] = {}
_HEAD_RE = re.compile(r'window\.LUMA_SONG=\{"schema":"luma\.song\.v1"')
_STR = r'("(?:[^"\\]|\\.)*")'
def song_meta(p: Path) -> dict:
    """Title, artist and duration from the head of a trainer file; cached by size and mtime, so /status stays cheap.

    Contract with prepare_song.py and build_html.py: both write ``window.LUMA_SONG`` as compact JSON whose top-level
    scalars (title, artist, duration, a4, hop, status, neuralSeparation, method, warning) precede the long arrays.
    The search window below is 4096 bytes, which those fields fit into with room to spare; key order inside the window
    does not matter. A writer that moves title, artist or duration behind ``points``/``notes`` must widen this window.
    """
    st = p.stat(); sig = (st.st_size, st.st_mtime); hit = _meta_cache.get(p.name)
    if hit and hit[0] == sig: return hit[1]
    meta = {}
    try:
        with open(p, 'rb') as f: head = f.read(512 * 1024).decode('utf-8', errors='replace')
        m = _HEAD_RE.search(head)
        if m:
            obj = head[m.end():m.end() + 4096]; field = lambda key, pat: (re.search(r'"' + key + r'":' + pat, obj) or [None, None])[1]
            title, artist, duration = field('title', _STR), field('artist', _STR), field('duration', r'([0-9.]+)')
            if title: meta = {'title': json.loads(title), 'artist': json.loads(artist) if artist else '', 'duration': float(duration) if duration else None}
    except (OSError, ValueError): meta = {}
    _meta_cache[p.name] = (sig, meta); return meta

# Difficulty for «Обери за мене» (studio/difficulty.py, docs/design/AUTOPICK.md): the song hash sits after the long arrays,
# so the whole data line is parsed, about 0.15 s a song. One worker does it off the request thread; /status says null
# until it is done, and the next poll carries the number. A file that cannot be read is cached as null and never picked.
_difficulty: dict[str, tuple[tuple[int, float], dict | None]] = {}; _measuring: set[str] = set()
_measure_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='difficulty'); _difficulty_lock = threading.Lock()
def _measure(p: Path, sig: tuple[int, float]):
    try: value = difficulty.of_file(p)
    except (OSError, ValueError, KeyError, TypeError): value = None
    with _difficulty_lock: _difficulty[p.name] = (sig, value); _measuring.discard(p.name)
def song_difficulty(p: Path, st: os.stat_result) -> dict:
    """{songHash, difficulty} for /status: both null while the file is being measured or when it cannot be read."""
    sig = (st.st_size, st.st_mtime)
    with _difficulty_lock:
        hit = _difficulty.get(p.name)
        if hit and hit[0] == sig: return {'songHash': hit[1] and hit[1]['songHash'], 'difficulty': hit[1] and hit[1]['D']}
        if p.name not in _measuring: _measuring.add(p.name); _measure_pool.submit(_measure, p, sig)
    return {'songHash': None, 'difficulty': None}

# Targets for «Розрахувати затримку» (docs/design/LATENCY_AUTOCAL.md §5): the melody of every trainer Studio serves, by
# song hash, in the form the trainer matches attempts against. Only LUMA_SONG is read, never the audio after it; each
# file is parsed once per (size, mtime). The contour is Int16 cents on the song's hop grid, -32768 where there is no
# confident pitch; notes carry what the trainer needs to apply ignored notes and manual shifts; lyric lines are times only.
SONG_MARK, ASSETS_MARK = b'<script>window.LUMA_SONG=', b';window.LUMA_ASSETS='
TARGET_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$'); MAX_TARGET_IDS = 400
_targets: dict[Path, tuple[tuple[int, float], dict | None]] = {}; _targets_lock = threading.Lock()

def read_song(p: Path) -> dict:
    """The LUMA_SONG object of a trainer, read in 1 MiB pieces up to the assets marker; ValueError when it has none."""
    buf = bytearray(); start = -1
    with open(p, 'rb') as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk: raise ValueError('no LUMA_SONG')
            buf += chunk
            if start < 0: start = buf.find(SONG_MARK)
            if start >= 0:
                end = buf.find(ASSETS_MARK, max(start + len(SONG_MARK), len(buf) - len(chunk) - len(ASSETS_MARK)))
                if end >= 0: break
    song = json.loads(bytes(buf[start + len(SONG_MARK):end]).decode('utf-8'))
    if not isinstance(song, dict) or song.get('schema') != 'luma.song.v1': raise ValueError('schema')
    return song

def compact_target(song: dict) -> dict:
    hop = float(song['hop']); n = int(round(float(song['duration']) / hop)) + 1; cents = array('h', [-32768]) * n
    for p in song.get('points') or []:
        if p[1] is None or not p[3]: continue
        i = int(round(p[0] / hop))
        if 0 <= i < n: cents[i] = max(-32767, min(32767, int(round(p[1] * 100))))
    if sys.byteorder != 'little': cents.byteswap()
    lyrics = song.get('lyrics') or []
    return {'id': song.get('id'), 'hop': hop, 'duration': song['duration'], 'cents': base64.b64encode(cents.tobytes()).decode('ascii'),
            'notes': [{k: x[k] for k in ('a', 'b', 'm', 'ignored', 'manual', 'originalM') if k in x} for x in song.get('notes') or []],
            'lines': [[line['a'], line['b']] for line in lyrics], 'words': any(line.get('words') for line in lyrics), 'lesson': bool(song.get('lesson'))}

def library_targets() -> dict[str, dict]:
    """{songHash: target} over the library and the demo; when two trainers share a song hash, the newer file wins."""
    files = sorted(SONGS.glob('Luma_*.html')); demo = ROOT / 'examples' / 'demo' / 'Luma_Demo.html'
    if demo.is_file(): files.append(demo)
    found: dict[str, tuple[float, dict]] = {}
    for p in files:
        try: st = p.stat()
        except OSError: continue
        sig = (st.st_size, st.st_mtime)
        with _targets_lock: hit = _targets.get(p)
        if hit and hit[0] == sig: entry = hit[1]
        else:
            try: song = read_song(p); entry = {'hash': song.get('sourceId') or song.get('id'), 'target': compact_target(song)}
            except (OSError, ValueError, KeyError, TypeError, IndexError): entry = None
            with _targets_lock: _targets[p] = (sig, entry)
        if entry and isinstance(entry['hash'], str) and (entry['hash'] not in found or found[entry['hash']][0] < st.st_mtime):
            found[entry['hash']] = (st.st_mtime, entry['target'])
    return {k: v for k, (_, v) in found.items()}

def cover_stamp(name: str) -> int | None:
    """The cover's mtime for /status: Studio asks for /cover/<name>?v=<stamp>, so a re-extracted cover is a new URL."""
    cover = covers.cover_for(SONGS, name)
    try: return int(cover.stat().st_mtime) if cover else None
    except OSError: return None

def worker():
    while True:
        job = None
        with lock:
            job = next((j for j in jobs if j['state'] == 'queued'), None)
        if not job: time.sleep(1); continue
        with lock:
            job['state'] = 'running'; job['started'] = time.time(); log = LOGS / (job['id'] + '.log'); job['log'] = str(log)
        out_html = SONGS / f"Luma_{slugify(job['title'])}.html"
        try:
            with open(log, 'w') as f:
                p = subprocess.run([sys.executable, str(PREP), job['path'], '--title', job['title'], '--artist', job['artist'], '--out', str(SONGS), '--out-html', str(out_html)], stdout=f, stderr=subprocess.STDOUT, env={**os.environ, 'PYTHONUNBUFFERED': '1'})
            succeeded = p.returncode == 0 and out_html.exists()
        except OSError as e:
            succeeded = False
            job['error'] = str(e)
        with lock:
            job['finished'] = time.time(); job['state'] = 'done' if succeeded else 'failed'
            if succeeded: job['html'] = out_html.name
        if job['state'] == 'done':
            if COPY_TO:
                try: COPY_TO.mkdir(parents=True, exist_ok=True); shutil.copy2(out_html, COPY_TO / out_html.name); job['copy'] = str(COPY_TO / out_html.name)
                except OSError as e: job['copy_error'] = str(e)
threading.Thread(target=worker, daemon=True).start()
threading.Thread(target=covers.backfill, args=(SONGS,), daemon=True).start()  # covers of songs prepared before covers existed
VIDEOS = video.Videos(SONGS, ROOT, base=f'http://127.0.0.1:{args.port}', budget=args.video_budget, min_seconds=args.video_min_seconds, deadline_factor=args.render_deadline_factor)
VIDEO_PATH = re.compile(r'^/video/([0-9a-f-]{36})(?:/([a-z0-9.-]+))?$')

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype='text/html; charset=utf-8'):
        b = body if isinstance(body, bytes) else body.encode(); self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/': return self.send(200, (ROOT / 'studio' / 'studio.html').read_text(encoding='utf-8'))
        if u.path == '/demo':
            demo = ROOT / 'examples' / 'demo' / 'Luma_Demo.html'
            if demo.is_file(): return self.send(200, demo.read_bytes())
            return self.send(404, 'Демо ще не зібрано. Додай готовий тренажер до бібліотеки.', 'text/plain; charset=utf-8')
        if u.path == '/videos': return self.send(200, json.dumps(VIDEOS.listing()), 'application/json')
        if u.path.startswith('/video/'): return self.video_get(u)
        if u.path == '/activity.js': return self.send(200, (ROOT / 'app' / 'activity.js').read_bytes(), 'text/javascript; charset=utf-8')
        if u.path == '/status':
            now = time.time()
            with lock: snapshot = [dict(j) for j in jobs]
            js = []
            for j in snapshot:  # logs are read outside the lock, once per job
                d = {k: j.get(k) for k in ['id', 'title', 'artist', 'state', 'started', 'finished', 'html', 'copy', 'requestId']}
                if j.get('error'): d['tail'] = j['error']
                if j.get('log') and j['state'] in ('running', 'failed'):
                    lines = read_log(j)
                    if lines is not None: d['tail'] = '\n'.join(lines[-6:]); d['stage'] = stage_info(j, now, lines)
                js.append(d)
            songs = []
            for p in sorted(SONGS.glob('Luma_*.html'), key=lambda p: -p.stat().st_mtime):
                st = p.stat()
                songs.append({'name': p.name, 'bytes': st.st_size, 'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime)), 'cover': cover_stamp(p.name), **song_meta(p), **song_difficulty(p, st)})
            return self.send(200, json.dumps({'jobs': js, 'songs': songs}), 'application/json')
        if u.path == '/targets':
            ids = urllib.parse.parse_qs(u.query).get('ids', [''])[0].split(',')
            if not ids or len(ids) > MAX_TARGET_IDS or not all(TARGET_ID.match(i) for i in ids): return self.send(400, 'bad ids', 'text/plain')
            known = library_targets()
            return self.send(200, json.dumps({i: known[i] for i in dict.fromkeys(ids) if i in known}, separators=(',', ':')), 'application/json')
        if u.path.startswith('/song/'):
            name = os.path.basename(urllib.parse.unquote(u.path[6:])); p = SONGS / name
            if p.is_file() and name.endswith('.html'): return self.send(200, p.read_bytes())
        if u.path.startswith('/cover/'):
            name = urllib.parse.unquote(u.path[7:]); cover = covers.cover_for(SONGS, name) if '/' not in name and '\\' not in name else None
            if cover:
                try: b = cover.read_bytes()
                except OSError: b = None
                if b:
                    self.send_response(200); self.send_header('Content-Type', 'image/jpeg'); self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'max-age=86400'); self.end_headers(); self.wfile.write(b); return
        return self.send(404, 'not found', 'text/plain')
    def do_PUT(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith('/video/'): return self.video_write(u, 'PUT')
        if u.path not in ('/upload', '/import'): return self.send(404, 'not found', 'text/plain')
        q = urllib.parse.parse_qs(u.query); name = os.path.basename(q.get('name', ['song'])[0]); n = int(self.headers.get('Content-Length', '0'))
        limit = MAX_IMPORT if u.path == '/import' else MAX_UPLOAD
        if n <= 0 or n > limit: return self.send(400, f'Розмір файлу має бути від 1 байта до {limit >> 20} МБ.', 'text/plain; charset=utf-8')
        if u.path == '/upload': return self.upload(q, name, n)
        data = self.rfile.read(n)
        if len(data) != n: return self.send(400, 'Файл отримано не повністю.', 'text/plain; charset=utf-8')
        if u.path == '/import':
            # Keep only the embedded data and wrap it in our current app, never imported scripts.
            try:
                source = data.decode('utf-8'); prefix = '<script>window.LUMA_SONG='
                a = source.index(prefix); b = source.index(';window.LUMA_ASSETS=', a)
                end = source.index('};</script>', b) + len('};</script>')
                song = json.loads(source[a + len(prefix):b])
                if not isinstance(song, dict) or song.get('schema') != 'luma.song.v1': raise ValueError('schema')
                assets = json.loads(source[b + len(';window.LUMA_ASSETS='):end - len(';</script>')])
                if not isinstance(assets, dict) or '1' not in assets: raise ValueError('assets')
                # JSON must not be able to close the enclosing script element.
                # Compact separators, like build_html.build, so the library can read title / artist / duration from the head.
                packed = prefix + json.dumps(song, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + ';window.LUMA_ASSETS=' + json.dumps(assets, separators=(',', ':')).replace('<', '\\u003c') + ';</script>'
                output = SONGS / ('Luma_' + slugify(str(song.get('title', 'song')))[:100] + '_' + uuid.uuid4().hex[:8] + '.html')
                with output.open('x', encoding='utf-8') as f: f.write(wrap(song, packed))
            except (ValueError, KeyError, TypeError, UnicodeError):
                return self.send(400, 'Потрібен готовий HTML-тренажер Luma з мелодією та аудіо.', 'text/plain; charset=utf-8')
            except OSError:
                return self.send(500, 'Не вдалося зберегти тренажер. Перевір вільне місце та доступ до каталогу songs.', 'text/plain; charset=utf-8')
            return self.send(200, json.dumps({'html': output.name}), 'application/json')

    def upload(self, q, name, n):
        """The audio body goes straight to the inbox in 1 MiB pieces: a 40-minute WAV never sits in memory."""
        t, a = guess(name); title = q.get('title', [t])[0].strip() or t; artist = q.get('artist', [a])[0].strip() or a
        request_id = q.get('requestId', [''])[0]
        dst = INBOX / (uuid.uuid4().hex + '_' + name); part = dst.with_name(dst.name + '.part'); left = n
        try:
            with part.open('xb') as f:
                while left:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk: break
                    f.write(chunk); left -= len(chunk)
        except OSError:
            part.unlink(missing_ok=True); return self.send(500, 'Не вдалося зберегти аудіофайл.', 'text/plain; charset=utf-8')
        if left: part.unlink(missing_ok=True); return self.send(400, 'Файл отримано не повністю.', 'text/plain; charset=utf-8')
        with upload_lock:
            with lock:
                previous = next((j for j in jobs if request_id and j.get('requestId') == request_id), None)
            if previous:
                part.unlink(missing_ok=True); return self.send(200, json.dumps({'queued': previous['id']}), 'application/json')
            try: part.rename(dst)
            except OSError: part.unlink(missing_ok=True); return self.send(500, 'Не вдалося зберегти аудіофайл.', 'text/plain; charset=utf-8')
            with lock: jobs.append({'id': dst.stem, 'path': str(dst), 'title': title, 'artist': artist, 'state': 'queued', 'requestId': request_id})
        return self.send(200, json.dumps({'queued': dst.name, 'title': title, 'artist': artist}), 'application/json')

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/activity': return self.activity()
        if u.path.startswith('/video/'): return self.video_write(u, 'POST')
        if u.path != '/retry': return self.send(404, 'not found', 'text/plain')
        job_id = urllib.parse.parse_qs(u.query).get('id', [''])[0]
        with lock:
            job = next((j for j in jobs if j['id'] == job_id), None)
            if not job or job['state'] != 'failed': return self.send(409, 'Цю підготовку зараз не можна повторити.', 'text/plain; charset=utf-8')
            job['state'] = 'queued'
            for key in ('started', 'finished', 'error', 'log'): job.pop(key, None)
        return self.send(200, '{}', 'application/json')

    def do_DELETE(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.startswith('/video/'): return self.video_write(u, 'DELETE')
        return self.send(404, 'not found', 'text/plain')

    # ── camera videos (studio/video.py) ──
    def same_origin(self) -> bool:
        origin = self.headers.get('Origin'); return not origin or origin == 'http://' + (self.headers.get('Host') or '')
    def body(self, limit: int) -> bytes | None:
        try: n = int(self.headers.get('Content-Length') or 0)
        except ValueError: return None
        if n <= 0 or n > limit: return None
        data = self.rfile.read(n); return data if len(data) == n else None
    def video_get(self, u):
        m = VIDEO_PATH.match(u.path)
        if not m or not video.ID.match(m.group(1)): return self.send(404, 'not found', 'text/plain')
        vid, what = m.group(1), m.group(2); d = VIDEOS.path(vid); take = VIDEOS.take(vid)
        if what == 'take' and take: return self.send(200, (d / 'take.json').read_bytes(), 'application/json')
        if what == 'render' and take:
            p = VIDEOS.trainer(take)
            if p: return self.send(200, p.read_bytes())
        if what == 'video.mp4': return self.send_file(d / 'video.mp4', 'video/mp4')
        if what == 'thumb.jpg': return self.send_file(d / 'thumb.jpg', 'image/jpeg')
        return self.send(404, 'not found', 'text/plain')
    def send_file(self, p: Path, ctype: str):
        """A file with HTTP Range (206), so a player can seek without loading the whole video."""
        try: f = open(p, 'rb'); size = os.fstat(f.fileno()).st_size
        except OSError: return self.send(404, 'not found', 'text/plain')
        with f:
            a, b, code = 0, size - 1, 200; rng = re.match(r'^bytes=(\d*)-(\d*)$', self.headers.get('Range') or '')
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1): a = int(rng.group(1)); b = min(size - 1, int(rng.group(2))) if rng.group(2) else size - 1
                else: a = max(0, size - int(rng.group(2)))
                if a > b or a >= size:
                    self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); self.send_header('Content-Length', '0'); self.end_headers(); return
                code = 206
            self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Accept-Ranges', 'bytes'); self.send_header('Content-Length', str(b - a + 1))
            if code == 206: self.send_header('Content-Range', f'bytes {a}-{b}/{size}')
            self.end_headers(); f.seek(a); left = b - a + 1
            try:
                while left:
                    chunk = f.read(min(left, 1 << 20))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError): pass
    def video_write(self, u, method: str):
        m = VIDEO_PATH.match(u.path)
        if not m: return self.send(404, 'not found', 'text/plain')
        if not self.same_origin(): return self.send(403, 'origin', 'text/plain')
        vid, what = m.group(1), m.group(2); q = urllib.parse.parse_qs(u.query)
        if not video.ID.match(vid): return self.send(404, 'not found', 'text/plain')
        def num(key):
            try: return int(q.get(key, [''])[0])
            except ValueError: return None
        if method == 'DELETE' and what is None:
            return self.send(200 if VIDEOS.remove(vid) else 404, '{}', 'application/json')
        if method == 'PUT' and what in ('camera', 'game'):
            seq = num('seq'); data = self.body(video.MAX_CHUNK if what == 'camera' else video.MAX_GAME)
            if seq is None or data is None: return self.send(400, 'bad chunk', 'text/plain')
            code = VIDEOS.append_camera(vid, seq, data) if what == 'camera' else VIDEOS.append_game(vid, seq, data, num('frames'))
            return self.send(code, '{}', 'application/json')
        if method == 'PUT' and what == 'voice':
            k = num('seg')
            try: n = int(self.headers.get('Content-Length') or 0)
            except ValueError: n = 0
            if k is None or not 0 < n <= video.MAX_VOICE: return self.send(400, 'bad voice', 'text/plain')
            return self.send(VIDEOS.put_voice(vid, k, self.rfile, n), '{}', 'application/json')
        if method == 'PUT' and what == 'take':
            data = self.body(video.MAX_TAKE)
            if data is None: return self.send(400, json.dumps({'composed': False, 'reason': 'invalid'}), 'application/json')
            code, out = VIDEOS.put_take(vid, data); return self.send(code, json.dumps(out), 'application/json')
        if method == 'POST' and what in ('rendered', 'render-failed'):
            error = None
            if what == 'render-failed':
                data = self.body(64 << 10) or b''; error = data.decode('utf-8', errors='replace') or 'render failed'
            return self.send(VIDEOS.rendered(vid, error), '{}', 'application/json')
        return self.send(404, 'not found', 'text/plain')

    def activity(self):
        """Append a batch of activity events. Pages of another origin may not write here; a request without an Origin
        header (a local script, a test) may."""
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + (self.headers.get('Host') or ''): return self.send(403, 'origin', 'text/plain')
        try: n = int(self.headers.get('Content-Length') or 0)
        except ValueError: n = -1
        if n > MAX_ACTIVITY: return self.send(413, 'too large', 'text/plain')
        if n <= 0: return self.send(400, 'empty', 'text/plain')
        body = self.rfile.read(n)
        try:
            if len(body) != n: raise ValueError('short')
            lines = activity_events(body)
        except (ValueError, AttributeError, UnicodeError): return self.send(400, 'bad events', 'text/plain')
        try:
            ACTIVITY.mkdir(parents=True, exist_ok=True)
            with activity_lock, open(ACTIVITY / (datetime.date.today().isoformat() + '.jsonl'), 'a', encoding='utf-8') as f: f.write('\n'.join(lines) + '\n')
        except OSError: return self.send(500, 'not written', 'text/plain')
        self.send_response(204); self.end_headers()

def shutdown(*_):
    """A Studio that stops ends the render browser it started, so no headless browser outlives it."""
    VIDEOS.stop_render(wait=True); os._exit(0)

if __name__ == '__main__':
    import signal
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, shutdown)
    VIDEOS.start()
    print(f'Luma Studio on http://127.0.0.1:{args.port}/  (songs: {SONGS})', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
