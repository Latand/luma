#!/usr/bin/env python3
"""Word-level comparison of lyric sources against each other and against the song's ASR transcript.
Usage: compare_sources.py <package_dir> name=file.txt [name=file.txt ...]
Section tags like [Chorus] and a leading 'N Contributors… Lyrics' header are ignored."""
import difflib, json, re, sys
from pathlib import Path
def norm(w):
    return ''.join(c for c in w.lower().replace('’', "'").replace('‘', "'") if c.isalnum() or c == "'").strip("'")


def words(text, include_echoes=False):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or re.search(r'Contributors.*Lyrics$', line): continue
        line = re.sub(r'^\[\d+:\d+(\.\d+)?\]\s*', '', line)
        if re.fullmatch(r'\[[^]]*\]',line): continue
        if not include_echoes: line = re.sub(r'\[[^]]*\]|\([^)]*\)', '', line)
        out += [n for n in (norm(w) for w in re.split(r'[\s—–-]+',line)) if n]
    return out


def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package',type=Path); ap.add_argument('sources',nargs='+')
    ap.add_argument('--include-echoes',action='store_true')
    a=ap.parse_args(); srcs={}
    for spec in a.sources:
        name, file = spec.split('=',1)
        srcs[name]=words(Path(file).read_text(),a.include_echoes)
    transcript=a.package/'lyrics'/'vocal.json'
    if transcript.exists():
        srcs['ASR']=[norm(w['w']) for line in json.loads(transcript.read_text())['lines'] for w in line['words']]
    names=list(srcs)
    for name in names: print(f'{name}: {len(srcs[name])} words')
    for i,name in enumerate(names):
        for other in names[i+1:]:
            matcher=difflib.SequenceMatcher(None,srcs[name],srcs[other],autojunk=False)
            print(f'{name} / {other}: {matcher.ratio():.3f}')
            for tag,a0,a1,b0,b1 in matcher.get_opcodes():
                if tag != 'equal': print(tag, [a0,a1], [b0,b1])

if __name__ == '__main__': main()
