#!/usr/bin/env python3
"""Build a standalone Luma trainer (one self-contained HTML file) from a song package, or rebuild an existing trainer
with the current app code while keeping its embedded song data byte-for-byte.

  build_html.py <package_dir> [-o out.html]      package_dir holds target.json + foreground.mp3, backing.mp3,
                                                 foreground_80.mp3, backing_80.mp3
  build_html.py --rebuild <trainer.html> [...]   re-wrap the data line of existing trainers with app/ parts
"""
from __future__ import annotations
import argparse, base64, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'app'

def parts():
    head = (APP / 'head.html').read_text(encoding='utf-8'); workers = (APP / 'workers.html').read_text(encoding='utf-8')
    script = '<script>' + (APP / 'app.js').read_text(encoding='utf-8') + '</script></body></html>'
    return head, workers, script

def wrap(song: dict, data_line: str) -> str:
    head, workers, script = parts()
    head = head.replace('{{TITLE}}', song.get('title', 'Luma')).replace('{{ARTIST}}', song.get('artist', '') or '')
    return head + workers + data_line + '\n' + script

def build(package: Path, out: Path) -> Path:
    song = json.loads((package / 'target.json').read_text(encoding='utf-8'))
    b64 = lambda name: base64.b64encode((package / name).read_bytes()).decode()
    assets = {'1': {'backing': b64('backing.mp3'), 'foreground': b64('foreground.mp3')}, '0.8': {'backing': b64('backing_80.mp3'), 'foreground': b64('foreground_80.mp3')}}
    data = '<script>window.LUMA_SONG=' + json.dumps(song, ensure_ascii=False, separators=(',', ':')) + ';window.LUMA_ASSETS=' + json.dumps(assets, separators=(',', ':')) + ';</script>'
    out.write_text(wrap(song, data), encoding='utf-8'); return out

def rebuild(html: Path) -> Path:
    cur = html.read_text(encoding='utf-8')
    a = cur.find('<script>window.LUMA_SONG='); b = cur.find(';window.LUMA_ASSETS=', a); e = cur.find('};</script>', b) + len('};</script>')
    if a < 0 or b < 0 or e < 0: raise SystemExit(f'{html}: no embedded song data found')
    song = json.loads(cur[a + len('<script>window.LUMA_SONG='):b])
    html.write_text(wrap(song, cur[a:e]), encoding='utf-8'); return html

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('target', nargs='+'); ap.add_argument('-o', '--out'); ap.add_argument('--rebuild', action='store_true')
    a = ap.parse_args()
    if a.rebuild:
        for t in a.target: print('rebuilt', rebuild(Path(t)))
    else:
        pkg = Path(a.target[0]); out = Path(a.out) if a.out else pkg.parent / f'Luma_{pkg.name}.html'
        p = build(pkg, out); print('built', p, p.stat().st_size, 'bytes')
