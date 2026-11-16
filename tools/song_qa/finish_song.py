#!/usr/bin/env python3
"""Rebuild and verify a copied package without opening a browser.
Usage: python tools/song_qa/finish_song.py PACKAGE OUTPUT.html
"""
import argparse
import json
import os
import sys
from pathlib import Path
from finalize import finalize
from common import backup_file
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'studio'))
from build_html import build


def finish(package, html):
    # Build to a complete sibling; the existing artifact survives a failed build.
    temp=html.with_name(html.name+'.new')
    try:
        build(package,temp)
        backup_file(html)
        os.chmod(temp,html.stat().st_mode & 0o777 if html.exists() else 0o600)
        temp.replace(html)
    finally:
        temp.unlink(missing_ok=True)
    return finalize(package,html)

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package',type=Path); ap.add_argument('html',type=Path)
    a=ap.parse_args(); print(json.dumps(finish(a.package,a.html)))
