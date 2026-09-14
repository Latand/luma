#!/usr/bin/env python3
"""Build a standalone Luma trainer (one self-contained HTML file) from a song package, or rebuild an existing trainer
with the current app code while keeping its embedded song data byte-for-byte.

  build_html.py <package_dir> [-o out.html]      package_dir holds target.json + foreground.mp3, backing.mp3,
                                                 foreground_80.mp3, backing_80.mp3
  build_html.py --rebuild <trainer.html> [...]   re-wrap the data line of existing trainers with app/ parts

studio/upgrade_audio.py puts new stems into existing trainers with reassets(), which keeps the song data the same way.
"""
from __future__ import annotations
import argparse, base64, html, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'app'
SONG = '<script>window.LUMA_SONG='
ASSETS = ';window.LUMA_ASSETS='
END = '};</script>'

def parts():
    head = (APP / 'head.html').read_text(encoding='utf-8'); workers = (APP / 'workers.html').read_text(encoding='utf-8')
    script = '<script>' + (APP / 'app.js').read_text(encoding='utf-8') + '</script></body></html>'
    return head, workers, script

def wrap(song: dict, data_line: str) -> str:
    head, workers, script = parts()
    head = head.replace('{{TITLE}}', html.escape(str(song.get('title', 'Luma')))).replace('{{ARTIST}}', html.escape(str(song.get('artist', '') or '')))
    return head + workers + data_line + '\n' + script

def assets(package: Path) -> str:
    b64 = lambda name: base64.b64encode((package / name).read_bytes()).decode()
    return json.dumps({'1': {'backing': b64('backing.mp3'), 'foreground': b64('foreground.mp3')}, '0.8': {'backing': b64('backing_80.mp3'), 'foreground': b64('foreground_80.mp3')}}, separators=(',', ':'))

def build(package: Path, out: Path) -> Path:
    song = json.loads((package / 'target.json').read_text(encoding='utf-8'))
    data = SONG + json.dumps(song, ensure_ascii=False, separators=(',', ':')) + ASSETS + assets(package) + ';</script>'
    out.write_text(wrap(song, data), encoding='utf-8'); return out

def data_span(cur: str, html: Path) -> tuple[int, int, int]:
    a = cur.find(SONG); b = cur.find(ASSETS, a + 1) if a >= 0 else -1; e = cur.find(END, b) if b >= 0 else -1
    if e < 0: raise SystemExit(f'{html}: no embedded song data found')
    return a, b, e + len(END)

def embedded_song(html: Path) -> str:
    """The song JSON inside a trainer, exactly as it is written there."""
    cur = html.read_text(encoding='utf-8'); a, b, _ = data_span(cur, html)
    return cur[a + len(SONG):b]

def rebuild(html: Path) -> Path:
    cur = html.read_text(encoding='utf-8'); a, b, e = data_span(cur, html)
    song = json.loads(cur[a + len(SONG):b])
    html.write_text(wrap(song, cur[a:e]), encoding='utf-8'); return html

def reassets(html: Path, package: Path) -> Path:
    """Put the package's current stems into an existing trainer. The song data (notes, lyrics, ids) is carried over as the
    exact text it was, the page is wrapped with the current app/ parts, and the finished file replaces the old one whole,
    so a server reading the library never sees half of it."""
    cur = html.read_text(encoding='utf-8'); a, b, _ = data_span(cur, html); song_text = cur[a + len(SONG):b]
    tmp = html.with_name(html.name + '.tmp')
    tmp.write_text(wrap(json.loads(song_text), SONG + song_text + ASSETS + assets(package) + ';</script>'), encoding='utf-8')
    os.replace(tmp, html); return html

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('target', nargs='+'); ap.add_argument('-o', '--out'); ap.add_argument('--rebuild', action='store_true')
    a = ap.parse_args()
    if a.rebuild:
        for t in a.target: print('rebuilt', rebuild(Path(t)))
    else:
        pkg = Path(a.target[0]); out = Path(a.out) if a.out else pkg.parent / f'Luma_{pkg.name}.html'
        p = build(pkg, out); print('built', p, p.stat().st_size, 'bytes')
