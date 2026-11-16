#!/usr/bin/env python3
"""Generate a timing sheet whose untouched rows preserve word values.
Usage: python tools/song_qa/make_sheet.py TARGET.json [--fa ALIGNMENT.json]
Change '=' starts to exact seconds, ~seconds, or an onset ID. Blank rows start
lines. Remove the end '=' to infer a changed word's release, or supply seconds.
"""
import argparse
import json
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('target',type=Path); ap.add_argument('--fa',type=Path); a=ap.parse_args()
    song=json.loads(a.target.read_text())
    fa=[w for line in json.loads(a.fa.read_text()) for w in line['words']] if a.fa else []
    k=0
    for line in song.get('lyrics',[]):
        for word in line['words']:
            hint=f" fa {fa[k]['a']}..{fa[k]['b']}" if k<len(fa) else ''
            print(f"{k} {word['w']} = = # current {word['a']:.3f}..{word['b']:.3f}{hint}")
            k+=1
        print()

if __name__=='__main__': main()
