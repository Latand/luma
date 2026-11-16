#!/usr/bin/env python3
"""Verify the rebuilt trainer and update its scratch manifest.
Usage: python tools/song_qa/finalize.py PACKAGE TRAINER.html
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from common import backup_file, write_json
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'studio'))
from build_html import embedded_song


def finalize(package, html):
    song=json.loads((package/'target.json').read_text())
    if json.loads(embedded_song(html)) != song: raise ValueError('embedded target differs')
    manifest_path=package/'manifest.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest['map']={'id':song['id'],'metrics':song['metrics'],'notes':len(song['notes']),
                     'ok_notes':sum(bool(n['ok']) for n in song['notes'])}
    manifest['html']={'path':html.name,'bytes':html.stat().st_size,
                      'sha256':hashlib.sha256(html.read_bytes()).hexdigest()}
    # Machine steps do not assert that a reviewer verified the pictures.
    manifest['qa']={'tool':'song_qa','review':'required'}
    backup_file(manifest_path); write_json(manifest_path,manifest)
    return {'embedded_target_equal':True,'html_bytes':html.stat().st_size}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package',type=Path); ap.add_argument('html',type=Path)
    a=ap.parse_args(); print(json.dumps(finalize(a.package,a.html)))

if __name__ == '__main__': main()
