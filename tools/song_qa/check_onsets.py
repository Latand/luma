#!/usr/bin/env python3
"""Spot check of word starts against onsets measured a second way.
Usage: python tools/song_qa/check_onsets.py --help


  check_onsets.py <package_dir> [--n 12] [--tol 0.08]

Takes --n words spread evenly over the song and, for each, the nearest rise of the stem's level: the frame where
the 10 ms level envelope climbs fastest inside a short window around the word (a different measure from the
spectral-flux candidates the starts were snapped to). Prints the distance for each word and how many lie inside
--tol. A word sung legato on a continuing vowel has no level rise of its own; such a word shows as "no rise" and is
judged on the picture instead.
"""
import json, sys
from pathlib import Path
import numpy as np, soundfile as sf

def main():
    a = sys.argv[1:]
    if not a or '--help' in a: print(__doc__); return
    pkg = Path(a[0]); n = int(a[a.index('--n') + 1]) if '--n' in a else 12; tol = float(a[a.index('--tol') + 1]) if '--tol' in a else .08
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8')); words = [w for l in song['lyrics'] for w in l['words']]
    y, sr = sf.read(pkg / 'vocals_44k.flac', dtype='float32', always_2d=True); y = y.mean(axis=1)
    hop = int(sr * .005); win = int(sr * .02); frames = 1 + (len(y) - win) // hop
    view = np.lib.stride_tricks.sliding_window_view(y,win)[::hop]
    lv = np.concatenate([10*np.log10(np.mean(view[i:i+256]**2,axis=1)+1e-10) for i in range(0,len(view),256)])
    sm = np.convolve(lv, np.ones(3) / 3, mode='same'); rise = np.concatenate([[0], sm[4:] - sm[:-4], [0, 0, 0]])  # dB per 20 ms
    tt = (np.arange(frames) * hop + win / 2) / sr
    if not words: print('0 words; no onset check'); return
    pick = [words[int(round(k))] for k in np.linspace(0, len(words) - 1, n)]; ok = 0; judged = 0
    for w in pick:
        i0, i1 = np.searchsorted(tt, [w['a'] - .2, w['a'] + .2]); seg = rise[i0:i1]
        peaks = [j for j in range(1, len(seg) - 1) if seg[j] >= seg[j - 1] and seg[j] >= seg[j + 1] and seg[j] > 3.0]
        if not peaks: print(f"{w['a']:8.3f}  {w['w']:<12} no level rise within 0.2 s (legato or soft start: judge on the picture)"); continue
        j = min(peaks, key=lambda j: abs(tt[i0 + j] - .01 - w['a'])); dt = float(tt[i0 + j] - .01 - w['a']); judged += 1; ok += abs(dt) <= tol
        print(f"{w['a']:8.3f}  {w['w']:<12} nearest level rise {dt * 1000:+5.0f} ms  {'ok' if abs(dt) <= tol else 'OUTSIDE'}")
    print(f'{ok} of {judged} measured words within {tol * 1000:.0f} ms ({n - judged} without a level rise)')

if __name__ == '__main__': main()
