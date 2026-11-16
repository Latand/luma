#!/usr/bin/env python3
"""Generate a timing sheet whose untouched rows preserve word values.
Usage: python tools/song_qa/make_sheet.py TARGET.json [--fa ALIGNMENT.json]
Change '=' starts to exact seconds, ~seconds, or an onset ID. Blank rows start
lines. Remove the end '=' to infer a changed word's release, or supply seconds.
"""
import argparse
import json
from pathlib import Path
from fa_align import sheet_hints


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('target',type=Path); ap.add_argument('--fa',type=Path); a=ap.parse_args()
    song=json.loads(a.target.read_text())
    lyrics = song.get('lyrics', [])
    hints = sheet_hints(lyrics, json.loads(a.fa.read_text())) if a.fa else {}
    k=0
    for i, line in enumerate(lyrics):
        for j, word in enumerate(line['words']):
            hint=f" fa {hints[i,j][0]}..{hints[i,j][1]}" if (i,j) in hints else ''
            print(f"{k} {word['w']} = = # current {word['a']:.3f}..{word['b']:.3f}{hint}")
            k+=1
        print()

if __name__=='__main__':
    try: main()
    except ValueError as error: raise SystemExit(str(error))
