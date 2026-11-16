#!/usr/bin/env python3
"""Set a prepared song's artist the way the project stores it.
Usage: python tools/song_qa/set_artist.py --help


  set_artist.py <package_dir> "<Artist>" [--dry-run]

The artist lives in two places: manifest.json (`artist`, which lyrics_text.py reads for its source cache) and
target.json (`artist`, which the trainer and the Studio library show). prepare_song.py derives the map id from
title + artist + duration + method, so the id is recomputed the same way and written to target.json `id` and
manifest.json `map.id`: the package then equals what a preparation with the artist given would have produced.
A new id also means note edits a browser stored for the old map (localStorage luma.target.<old id>) do not shadow
the corrected notes; the practice history is keyed by sourceId and is kept. Run it before lyrics_text.py, because a
changed title/artist invalidates the cached lyrics source.
"""
import hashlib, json, sys
from common import backup_file, write_json
from pathlib import Path

def main():
    if '--help' in sys.argv: print(__doc__); return
    args = [a for a in sys.argv[1:] if a != '--dry-run']; dry = '--dry-run' in sys.argv
    if len(args) != 2: raise SystemExit(__doc__)
    pkg = Path(args[0]); artist = args[1].strip()
    tp, mp = pkg / 'target.json', pkg / 'manifest.json'
    song = json.loads(tp.read_text(encoding='utf-8')); manifest = json.loads(mp.read_text(encoding='utf-8'))
    old = {'artist': song.get('artist'), 'id': song.get('id')}
    new_id = hashlib.sha256((song['title'] + artist + str(song['duration']) + song['method']).encode()).hexdigest()[:20]
    check = hashlib.sha256((song['title'] + (song.get('artist') or '') + str(song['duration']) + song['method']).encode()).hexdigest()[:20]
    print(f"{pkg.name}: artist {old['artist']!r} -> {artist!r}; id {old['id']} -> {new_id}" + ('' if check == old['id'] else f'  (note: the old id was not the derived one, {check})'))
    if dry: return
    song['artist'] = artist; song['id'] = new_id
    manifest['artist'] = artist
    if isinstance(manifest.get('map'), dict): manifest['map']['id'] = new_id
    backup_file(tp); backup_file(mp)
    write_json(tp,song)
    write_json(mp,manifest)

if __name__ == '__main__': main()
