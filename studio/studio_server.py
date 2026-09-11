#!/usr/bin/env python3
"""Luma Studio: drop a song in the browser, get a standalone trainer. Local only, standard library, one job at a time.

  GET  /                         drop zone, queue, library
  PUT  /upload?name=&title=&artist=   raw file body -> inbox/, job queued
  GET  /status                   jobs and log tails
  GET  /song/<name>.html         generated trainers (served over http so the microphone works)

Run: python studio/studio_server.py [--port 8792] [--songs DIR] [--copy-to DIR]
"""
from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser(); ap.add_argument('--port', type=int, default=int(os.environ.get('LUMA_STUDIO_PORT', '8792'))); ap.add_argument('--songs', default=str(ROOT / 'songs')); ap.add_argument('--copy-to', default=os.environ.get('LUMA_COPY_TO', ''))
args = ap.parse_args()
SONGS = Path(args.songs).expanduser().resolve(); INBOX = SONGS / 'inbox'; LOGS = SONGS / 'logs'
for d in (SONGS, INBOX, LOGS): d.mkdir(parents=True, exist_ok=True)
COPY_TO = Path(args.copy_to).expanduser() if args.copy_to else None
PREP = ROOT / 'studio' / 'prepare_song.py'
jobs: list[dict] = []; lock = threading.Lock()

def slugify(t): return ''.join(c if c.isalnum() else '_' for c in t).strip('_') or 'song'
def guess(name):
    stem = Path(name).stem; m = re.match(r'^(.*?)\s+-\s+(.*)$', stem)
    return (m.group(1).strip(), m.group(2).strip()) if m else (stem.strip(), '')

def worker():
    while True:
        job = None
        with lock:
            job = next((j for j in jobs if j['state'] == 'queued'), None)
        if not job: time.sleep(1); continue
        job['state'] = 'running'; job['started'] = time.time(); log = LOGS / (job['id'] + '.log'); job['log'] = str(log)
        out_html = SONGS / f"Luma_{slugify(job['title'])}.html"
        with open(log, 'w') as f:
            p = subprocess.run([sys.executable, str(PREP), job['path'], '--title', job['title'], '--artist', job['artist'], '--out', str(SONGS), '--out-html', str(out_html)], stdout=f, stderr=subprocess.STDOUT, env={**os.environ, 'PYTHONUNBUFFERED': '1'})
        job['finished'] = time.time(); job['state'] = 'done' if p.returncode == 0 and out_html.exists() else 'failed'
        if job['state'] == 'done':
            job['html'] = out_html.name
            if COPY_TO:
                try: COPY_TO.mkdir(parents=True, exist_ok=True); shutil.copy2(out_html, COPY_TO / out_html.name); job['copy'] = str(COPY_TO / out_html.name)
                except OSError as e: job['copy_error'] = str(e)
threading.Thread(target=worker, daemon=True).start()

PAGE = (ROOT / 'studio' / 'studio.html').read_text(encoding='utf-8')

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype='text/html; charset=utf-8'):
        b = body if isinstance(body, bytes) else body.encode(); self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/': return self.send(200, PAGE)
        if u.path == '/status':
            with lock:
                js = []
                for j in jobs:
                    d = {k: j.get(k) for k in ['id', 'title', 'artist', 'state', 'started', 'finished', 'html', 'copy']}
                    if j.get('log') and j['state'] in ('running', 'failed'):
                        try: d['tail'] = '\n'.join(Path(j['log']).read_text(errors='replace').splitlines()[-6:])
                        except OSError: pass
                    js.append(d)
            songs = [{'name': p.name, 'bytes': p.stat().st_size, 'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))} for p in sorted(SONGS.glob('Luma_*.html'), key=lambda p: -p.stat().st_mtime)]
            return self.send(200, json.dumps({'jobs': js, 'songs': songs}), 'application/json')
        if u.path.startswith('/song/'):
            name = os.path.basename(urllib.parse.unquote(u.path[6:])); p = SONGS / name
            if p.is_file() and name.endswith('.html'): return self.send(200, p.read_bytes())
        return self.send(404, 'not found', 'text/plain')
    def do_PUT(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != '/upload': return self.send(404, 'not found', 'text/plain')
        q = urllib.parse.parse_qs(u.query); name = os.path.basename(q.get('name', ['song'])[0]); n = int(self.headers.get('Content-Length', '0'))
        if n <= 0 or n > 200 * 1024 * 1024: return self.send(400, 'bad size', 'text/plain')
        data = self.rfile.read(n); dst = INBOX / (time.strftime('%Y%m%d-%H%M%S') + '_' + name); dst.write_bytes(data)
        t, a = guess(name); title = q.get('title', [t])[0].strip() or t; artist = q.get('artist', [a])[0].strip() or a
        with lock: jobs.append({'id': dst.stem, 'path': str(dst), 'title': title, 'artist': artist, 'state': 'queued'})
        return self.send(200, json.dumps({'queued': dst.name, 'title': title, 'artist': artist}), 'application/json')

if __name__ == '__main__':
    print(f'Luma Studio on http://127.0.0.1:{args.port}/  (songs: {SONGS})', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
