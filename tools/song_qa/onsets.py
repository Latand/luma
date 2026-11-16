#!/usr/bin/env python3
"""Print numbered onset times and strengths.
Usage: python tools/song_qa/onsets.py FEATURES.npz
"""
import argparse
import numpy as np

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('features'); a=ap.parse_args()
    with np.load(a.features) as f:
        for i,(t,s) in enumerate(zip(f['onset_start'],f['onset_strength'])):
            print(f'o{i} {t:.4f} strength={s:.3f}')
