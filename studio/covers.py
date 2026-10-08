#!/usr/bin/env python3
"""Album covers for the Studio library: the picture embedded in songs/<slug>/original.*, cached as cover.jpg beside it.

  extract(package)        -> cover.jpg, or None when the original carries no picture (marked by cover.none)
  backfill(songs)         -> {'extracted', 'cached', 'none', 'failed'} over every package; prints counts, never names
  cover_for(songs, html)  -> the cached cover of a trainer Luma_<slug>.html, or None

Run: python studio/covers.py [--songs DIR]
"""
from __future__ import annotations
import argparse, json, os, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAINER_RE = re.compile(r'^Luma_([^/\\]+)\.html$')

def _fresh(p: Path, original: Path) -> bool:
    try: return p.stat().st_mtime >= original.stat().st_mtime
    except OSError: return False

def _settle(p: Path, original: Path) -> None:
    """Never older than the original, so an original with a clock-skewed mtime does not look newer forever."""
    t = original.stat().st_mtime
    if p.stat().st_mtime < t: os.utime(p, (t, t))

def _mark_none(package: Path, original: Path) -> None:
    (package / 'cover.none').touch(); _settle(package / 'cover.none', original); (package / 'cover.jpg').unlink(missing_ok=True)

def extract(package: Path) -> Path | None:
    """Write package/cover.jpg (at most 512 px) from the most nearly square picture in the original; cached by mtime."""
    original = next(iter(sorted(package.glob('original.*'))), None)
    if original is None: return None
    cover, none_marker, part = package / 'cover.jpg', package / 'cover.none', package / f'cover.{os.getpid()}.part'  # the server and a preparation may race
    if _fresh(cover, original): return cover
    if _fresh(none_marker, original): return None
    try:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=index,width,height:stream_disposition=attached_pic', '-of', 'json', str(original)], capture_output=True, text=True)
        if probe.returncode: _mark_none(package, original); return None
        streams = [s for s in json.loads(probe.stdout or '{}').get('streams', []) if s.get('width') and s.get('height')]
        flagged = [s for s in streams if s.get('disposition', {}).get('attached_pic')]
        candidates = flagged or streams
        # Some files carry a letterboxed 16:9 thumbnail before the square album art: the squarest picture wins, then the largest.
        if not candidates: _mark_none(package, original); return None
        pick = min(candidates, key=lambda s: (abs(s['width'] / s['height'] - 1), -s['width'] * s['height']))
        done = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(original), '-map', f"0:{pick['index']}", '-frames:v', '1', '-vf', "scale='min(512,iw)':-2", '-q:v', '3', '-f', 'mjpeg', str(part)], capture_output=True)
        if done.returncode or not part.is_file() or not part.stat().st_size: part.unlink(missing_ok=True); _mark_none(package, original); return None
        os.replace(part, cover); _settle(cover, original); none_marker.unlink(missing_ok=True); return cover
    except FileNotFoundError:  # no ffmpeg on this machine: try again on the next start, leave no marker
        part.unlink(missing_ok=True); return None
    except (OSError, ValueError):
        part.unlink(missing_ok=True); return None

def backfill(songs: Path) -> dict:
    counts = {'extracted': 0, 'cached': 0, 'none': 0, 'failed': 0}
    packages = sorted(p for p in Path(songs).iterdir() if p.is_dir()) if Path(songs).is_dir() else []
    for package in packages:
        original = next(iter(sorted(package.glob('original.*'))), None)
        if original is None: continue
        cached = _fresh(package / 'cover.jpg', original)
        cover = extract(package)
        if cover: counts['cached' if cached else 'extracted'] += 1
        elif (package / 'cover.none').exists(): counts['none'] += 1
        else: counts['failed'] += 1
    print('covers: ' + ', '.join(f'{k} {v}' for k, v in counts.items()), flush=True)
    return counts

def cover_for(songs: Path, html_name: str) -> Path | None:
    m = TRAINER_RE.match(html_name)
    if not m: return None
    root = Path(songs).resolve(); path = root / m.group(1) / 'cover.jpg'
    try:
        if path.resolve().parent.parent == root and path.is_file(): return path
    except OSError: pass
    return None

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--songs', default=str(ROOT / 'songs'))
    backfill(Path(ap.parse_args().songs).expanduser())
