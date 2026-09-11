#!/usr/bin/env python3
"""Luma Studio: drop a song in the browser, get a standalone trainer. Local only, standard library, one job at a time.

  GET  /                         drop zone, queue, library
  PUT  /upload?name=&title=&artist=   raw file body -> inbox/, job queued
  PUT  /import?name=             finished trainer HTML -> re-wrapped with the current app, added to the library
  POST /retry?id=                queue a failed job again
  GET  /status                   jobs with stage progress, library with title / artist / duration
  GET  /song/<name>.html         generated trainers (served over http so the microphone works)
  GET  /demo                     the synthetic demo trainer, if it has been built

Run: python studio/studio_server.py [--port 8792] [--songs DIR] [--copy-to DIR]
"""
from __future__ import annotations
import argparse, datetime, json, os, re, shutil, subprocess, sys, threading, time, urllib.parse, uuid
from build_html import wrap
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser(); ap.add_argument('--port', type=int, default=int(os.environ.get('LUMA_STUDIO_PORT', '8792'))); ap.add_argument('--songs', default=str(ROOT / 'songs')); ap.add_argument('--copy-to', default=os.environ.get('LUMA_COPY_TO', ''))
args = ap.parse_args()
SONGS = Path(args.songs).expanduser().resolve(); INBOX = SONGS / 'inbox'; LOGS = SONGS / 'logs'
for d in (SONGS, INBOX, LOGS): d.mkdir(parents=True, exist_ok=True)
COPY_TO = Path(args.copy_to).expanduser() if args.copy_to else None
PREP = ROOT / 'studio' / 'prepare_song.py'
jobs: list[dict] = []; lock = threading.Lock(); upload_lock = threading.Lock()

# Pipeline stages as prepare_song.py logs them ("[n/8] name"), with typical seconds for a 5-minute song on a mid-range GPU.
# The weights only shape the progress bar and the rough ETA; a slower machine stretches them by the observed pace.
STAGES = [('decode', 'Декодування', 3), ('separation', 'Розділення вокалу (Demucs)', 45), ('pYIN', 'Висота голосу: pYIN', 105), ('CREPE', 'Висота голосу: CREPE', 27), ('map', 'Карта мелодії', 2), ('stems', 'Доріжки MP3', 12), ('lyrics', 'Слова (Soniox)', 10), ('html', 'Збирання тренажера', 6)]
STAGE_RE = re.compile(r'^(\d\d):(\d\d):(\d\d) \[(\d)/8\] ')
TOTAL_WEIGHT = sum(w for _, _, w in STAGES)

def slugify(t): return ''.join(c if c.isalnum() else '_' for c in t).strip('_') or 'song'
def guess(name):
    stem = Path(name).stem; m = re.match(r'^(.*?)\s+-\s+(.*)$', stem)
    return (m.group(1).strip(), m.group(2).strip()) if m else (stem.strip(), '')

def stage_info(job: dict, now: float) -> dict | None:
    """Latest stage marker in the job log, with progress 0..1 and a rough ETA in seconds."""
    try: lines = Path(job['log']).read_text(errors='replace').splitlines()
    except (KeyError, OSError, TypeError): return None
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
_META_RE = re.compile(r'window\.LUMA_SONG=\{"schema":"luma\.song\.v1","title":("(?:[^"\\]|\\.)*"),"artist":("(?:[^"\\]|\\.)*"),"duration":([0-9.]+)')
def song_meta(p: Path) -> dict:
    """Title, artist and duration from the head of a trainer file; cached by size and mtime, so /status stays cheap."""
    st = p.stat(); sig = (st.st_size, st.st_mtime); hit = _meta_cache.get(p.name)
    if hit and hit[0] == sig: return hit[1]
    meta = {}
    try:
        with open(p, 'rb') as f: head = f.read(512 * 1024).decode('utf-8', errors='replace')
        m = _META_RE.search(head)
        if m: meta = {'title': json.loads(m.group(1)), 'artist': json.loads(m.group(2)), 'duration': float(m.group(3))}
    except (OSError, ValueError): meta = {}
    _meta_cache[p.name] = (sig, meta); return meta

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
            job['html'] = out_html.name
            if COPY_TO:
                try: COPY_TO.mkdir(parents=True, exist_ok=True); shutil.copy2(out_html, COPY_TO / out_html.name); job['copy'] = str(COPY_TO / out_html.name)
                except OSError as e: job['copy_error'] = str(e)
threading.Thread(target=worker, daemon=True).start()

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
        if u.path == '/status':
            now = time.time()
            with lock:
                js = []
                for j in jobs:
                    d = {k: j.get(k) for k in ['id', 'title', 'artist', 'state', 'started', 'finished', 'html', 'copy', 'requestId']}
                    if j.get('error'): d['tail'] = j['error']
                    if j.get('log') and j['state'] in ('running', 'failed'):
                        try: d['tail'] = '\n'.join(Path(j['log']).read_text(errors='replace').splitlines()[-6:])
                        except OSError: pass
                        d['stage'] = stage_info(j, now)
                    js.append(d)
            songs = []
            for p in sorted(SONGS.glob('Luma_*.html'), key=lambda p: -p.stat().st_mtime):
                songs.append({'name': p.name, 'bytes': p.stat().st_size, 'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime)), **song_meta(p)})
            return self.send(200, json.dumps({'jobs': js, 'songs': songs}), 'application/json')
        if u.path.startswith('/song/'):
            name = os.path.basename(urllib.parse.unquote(u.path[6:])); p = SONGS / name
            if p.is_file() and name.endswith('.html'): return self.send(200, p.read_bytes())
        return self.send(404, 'not found', 'text/plain')
    def do_PUT(self):
        u = urllib.parse.urlparse(self.path)
        if u.path not in ('/upload', '/import'): return self.send(404, 'not found', 'text/plain')
        q = urllib.parse.parse_qs(u.query); name = os.path.basename(q.get('name', ['song'])[0]); n = int(self.headers.get('Content-Length', '0'))
        if n <= 0 or n > 200 * 1024 * 1024: return self.send(400, 'Розмір файлу має бути від 1 байта до 200 МБ.', 'text/plain; charset=utf-8')
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
                packed = prefix + json.dumps(song, ensure_ascii=False).replace('<', '\\u003c') + ';window.LUMA_ASSETS=' + json.dumps(assets).replace('<', '\\u003c') + ';</script>'
                output = SONGS / ('Luma_' + slugify(str(song.get('title', 'song')))[:100] + '_' + uuid.uuid4().hex[:8] + '.html')
                with output.open('x', encoding='utf-8') as f: f.write(wrap(song, packed))
            except (ValueError, KeyError, TypeError, UnicodeError):
                return self.send(400, 'Потрібен готовий HTML-тренажер Luma з мелодією та аудіо.', 'text/plain; charset=utf-8')
            except OSError:
                return self.send(500, 'Не вдалося зберегти тренажер. Перевір вільне місце та доступ до каталогу songs.', 'text/plain; charset=utf-8')
            return self.send(200, json.dumps({'html': output.name}), 'application/json')
        t, a = guess(name); title = q.get('title', [t])[0].strip() or t; artist = q.get('artist', [a])[0].strip() or a
        request_id = q.get('requestId', [''])[0]
        with upload_lock:
            with lock:
                previous = next((j for j in jobs if request_id and j.get('requestId') == request_id), None)
            if previous:
                return self.send(200, json.dumps({'queued': previous['id']}), 'application/json')
            dst = INBOX / (uuid.uuid4().hex + '_' + name)
            try: dst.write_bytes(data)
            except OSError: return self.send(500, 'Не вдалося зберегти аудіофайл.', 'text/plain; charset=utf-8')
            with lock: jobs.append({'id': dst.stem, 'path': str(dst), 'title': title, 'artist': artist, 'state': 'queued', 'requestId': request_id})
        return self.send(200, json.dumps({'queued': dst.name, 'title': title, 'artist': artist}), 'application/json')

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != '/retry': return self.send(404, 'not found', 'text/plain')
        job_id = urllib.parse.parse_qs(u.query).get('id', [''])[0]
        with lock:
            job = next((j for j in jobs if j['id'] == job_id), None)
            if not job or job['state'] != 'failed': return self.send(409, 'Цю підготовку зараз не можна повторити.', 'text/plain; charset=utf-8')
            job['state'] = 'queued'
            for key in ('started', 'finished', 'error', 'log'): job.pop(key, None)
        return self.send(200, '{}', 'application/json')

if __name__ == '__main__':
    print(f'Luma Studio on http://127.0.0.1:{args.port}/  (songs: {SONGS})', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
