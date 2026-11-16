#!/usr/bin/env python3
"""Numeric hypotheses for picture review; never changes a target.
Usage: python tools/song_qa/candidates.py PACKAGE FEATURES.npz OUTPUT.json
"""
import argparse
import json
from pathlib import Path
import numpy as np
import scipy.ndimage as ndi
from scipy.signal import stft, resample_poly
import soundfile as sf
from common import write_json

HOP = .02


def runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int)))
    return list(zip(edges[::2], edges[1::2]))


def audio_features(package):
    """20 ms frames; spectral harmonic comb and normalized autocorrelation.

    256 ms Hann windows distinguish partials at low voice frequencies. The
    comb uses six partials with decreasing weights; a subharmonic with missing
    odd partials loses to its octave. No trained model or download is involved.
    """
    y, sr = sf.read(Path(package) / 'vocals_44k.flac', dtype='float32', always_2d=True)
    y = y.mean(axis=1)
    y = resample_poly(y, 16000, sr).astype(np.float32)
    sr = 16000; size = 4096; hop = 320
    _, t, z = stft(y, sr, nperseg=size, noverlap=size-hop, boundary='zeros')
    s = np.abs(z).astype(np.float32)
    midi = np.arange(36., 90.01, .25)
    hz = 440 * 2 ** ((midi - 69) / 12)
    sal = np.zeros((len(midi), len(t)), np.float32)
    partials = []
    for h in range(1, 7):
        peak = np.zeros((len(midi),len(t)),np.float32)
        for factor in np.linspace(.97,1.03,13):
            idx = np.rint(hz * h * factor / (sr / size)).astype(int)
            np.maximum(peak,s[np.clip(idx,0,len(s)-1)],out=peak)
        partials.append(peak)
        sal += peak / h
    # The fundamental and odd partials prevent division by two winning a comb.
    odd = partials[0] + partials[2] + partials[4]
    even = partials[1] + partials[3] + partials[5]
    ratio = odd / (even + 1e-9)
    sal *= np.minimum(1, ratio / .3)
    best = sal.argmax(axis=0)
    f0 = midi[best]
    # A spectral comb is weak in broadband sound; autocorrelation provides an
    # independent periodicity witness, including breathy vowels.
    padded = np.pad(y, (size//2, size))
    frames = np.lib.stride_tricks.sliding_window_view(padded, size)[::hop][:len(t)]
    periodicity = np.empty(len(t)); energy = np.empty(len(t))
    window = np.hanning(size)
    for start in range(0,len(t),256):
        end = min(len(t),start+256); block = frames[start:end]
        power = np.abs(np.fft.rfft(block*window,n=8192,axis=1))**2
        ac = np.fft.irfft(power,axis=1)[:,:size]
        periodicity[start:end] = np.max(ac[:,16:230],axis=1)/(ac[:,0]+1e-12)
        energy[start:end] = np.sqrt(np.mean(block**2,axis=1))
    db = 20 * np.log10(energy + 1e-10)
    # Fraction of spectrum represented by peaks near six harmonics.
    concentration = sal[best, np.arange(len(t))] / (s.sum(axis=0) + 1e-9)
    return dict(t=t, midi=midi, sal=sal, ratio=ratio, f0=f0,
                periodicity=periodicity, db=db, concentration=concentration)


def evidence(F, midi):
    pitch = np.asarray(midi)
    supported = np.isfinite(pitch) & (pitch >= F['midi'][0]) & (pitch <= F['midi'][-1])
    indices = np.clip(np.rint((np.where(supported, pitch, F['midi'][0]) - F['midi'][0]) / .25).astype(int), 0, len(F['midi'])-1)
    cols = np.arange(len(F['t']))
    # Index clipping only makes the lookup safe; an absent pitch has no evidence.
    return (np.where(supported, F['sal'][indices, cols], 0),
            np.where(supported, F['ratio'][indices, cols], 0))


def spans(mask, F, category, confidence, support=None, **fields):
    out = []
    # Close tiny holes, retaining separate musical events.
    mask = ndi.binary_closing(mask, structure=np.ones(3))
    if support is not None: mask &= support
    for a, b in runs(mask):
        if b-a < 3: continue
        out.append(dict(type=category, a=round(float(F['t'][a]), 3),
                        b=round(float(F['t'][b-1]+HOP), 3),
                        confidence=round(float(np.clip(np.median(confidence[a:b]), 0, 1)), 3), **fields))
    return out


def melody_candidates(song, F):
    t = F['t']; points = song['points']
    if not points: return []
    pt = np.array([p[0] for p in points])
    index = np.clip(np.searchsorted(pt, t + .001)-1, 0, len(pt)-1)
    target = np.array([p[1] if p[1] is not None else np.nan for p in points])[index]
    present = np.isfinite(target) & (t <= song['duration'])
    pitch = np.nan_to_num(target, nan=60.)
    own, own_ratio = evidence(F, pitch)
    best = F['sal'].max(axis=0)
    loud = F['db'] > max(-65, float(np.percentile(F['db'], 95))-48)
    harmonic = (F['periodicity'] > .35) & (F['concentration'] > .035)
    out = []
    for shift in (-12, 12):
        alt, alt_ratio = evidence(F, pitch + shift)
        # Spectral disagreement is required; phrase context ranks its confidence.
        proposed = pitch + shift
        support = present & (proposed >= max(24, F['midi'][0])) & (proposed <= min(108, F['midi'][-1]))
        mask = support & loud & harmonic & (alt > best * .1)
        if shift == -12: mask &= alt_ratio > .07
        else: mask &= ((own_ratio < .2) | (alt > own * 1.2)) & (alt > own * 1.08)
        neighbours = ndi.median_filter(pitch, size=101, mode='nearest')
        context = np.abs(pitch + shift - neighbours) < np.abs(pitch-neighbours)
        conf = .4 + .25*np.minimum(1, alt/(best+1e-9)) + .15*context + .15*F['periodicity']
        out += spans(mask, F, 'octave', conf, support=support, shift=shift)
    # Low periodicity and weak harmonic concentration with audible energy.
    unpitched = loud & (~harmonic | (F['periodicity'] < .5)) & (t < song['duration'])
    confidence = .4 + .5*(1-F['periodicity'])
    out += spans(unpitched, F, 'unpitched', confidence, kind='noise')
    # Gaps and tails in the drawn contour with a continuing supported partial.
    # A local target band allows the faint fundamental under a stronger harmony.
    for a, b in runs(~present & (t < song['duration'])):
        if b-a < 1: continue
        left = target[max(0,a-30):a]; right = target[b:min(len(t),b+30)]
        anchors = np.r_[left[np.isfinite(left)], right[np.isfinite(right)]]
        if not len(anchors): continue
        m = float(np.median(anchors))
        band = (F['midi'] >= m-1.5) & (F['midi'] <= m+1.5)
        # The spectral cache has a narrower pitch range than valid targets.
        # No supported band means no held-note evidence for this gap.
        if not np.any(band): continue
        strength = F['sal'][band].max(axis=0)
        supported = loud & (F['periodicity'] > .25) & (strength > best*.2)
        mask = np.zeros(len(t), bool)
        aa,bb = max(0,a-6),min(len(t),b+6)
        # A short fragment on another partial can hide the gap in the lead
        # fundamental. Include adjacent off-band contour in the hypothesis.
        off_band = ~present | (np.abs(pitch-m)>2)
        mask[aa:bb] = supported[aa:bb] & off_band[aa:bb]
        # For a long gap only report the portion near the continuing note.
        if b-a > 350:
            mask[a+150:b-150] = False
        conf = .4 + .3*F['periodicity'] + .2*np.minimum(1,strength/(best+1e-9))
        out += spans(mask, F, 'broken', conf, m=round(m,2))
    return sorted(out, key=lambda c: (c['a'],c['type'],c.get('shift',0)))


def repeat_candidates(song, F):
    """Cross-correlate a wide context of repeated lyric lines against the stem.

    Relative 100 ms log-energy and pitch-independent spectral-envelope samples
    provide the recording's clock. A line's text is used only to select pairs.
    """
    import re
    groups = {}
    for i, line in enumerate(song.get('lyrics', [])):
        text = ' '.join(w['w'] for w in line['words']).lower().replace('’', "'")
        key = re.sub(r"[^\w' ]", '', text)
        tokens=key.split()
        if len(tokens) >= 2:
            keys=[key]
            # Existing alignment can split one occurrence into two rows. A
            # shared three-word prefix retains that repeat for clock checking.
            if len(tokens)>3: keys.append(' '.join(tokens[:3]))
            for group in keys: groups.setdefault(group, []).append((i,line))
    out = []; t = F['t']; seen=set()
    # Scalar envelope works with synthetic impulses and real syllable bursts.
    env = F['db'][::5]; grid = t[::5]
    def sample(a, rel): return np.interp(a+rel, grid, env)
    for occurrences in groups.values():
        if len(occurrences) < 2: continue
        refid, ref = occurrences[0]
        rel = np.arange(-3, min(9, max(4, ref['b']-ref['a']+2)), .1)
        x = sample(ref['a'],rel); x = x-x.mean()
        if np.linalg.norm(x) < 1: continue
        for lid, line in occurrences[1:]:
            if (refid,lid) in seen: continue
            seen.add((refid,lid))
            shifts = np.arange(-2.5,2.501,.1)
            scores = []
            for delta in shifts:
                y = sample(line['a']+delta,rel); y = y-y.mean()
                scores.append(float(x@y/(np.linalg.norm(x)*np.linalg.norm(y)+1e-9)))
            best = int(np.argmax(scores)); shift = float(shifts[best])
            if scores[best] >= .65 and abs(shift) >= .4:
                out.append(dict(type='repeat', a=line['a'], b=line['b'], line=lid,
                                reference_line=refid, shift=round(shift,3),
                                confidence=round(scores[best],3)))
    return out


def detect(song, F):
    return melody_candidates(song,F) + repeat_candidates(song,F)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package',type=Path); ap.add_argument('features',type=Path); ap.add_argument('output',type=Path)
    a = ap.parse_args(); song = json.loads((a.package/'target.json').read_text())
    F = {k[3:]: v for k, v in np.load(a.features).items() if k.startswith('qa_')}
    result = detect(song,F); write_json(a.output,result)
    for c in result:
        print(f"{c['type']:9} {c['a']:8.3f}..{c['b']:8.3f} confidence={c['confidence']:.3f}")

if __name__ == '__main__': main()
