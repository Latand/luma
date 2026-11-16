#!/usr/bin/env python3
"""Spectrogram and onset features of a song's vocal stem, cached for the picture tools.
Usage: python tools/song_qa/features.py --help


  features.py <package_dir> <cache.npz>

Reads <package>/vocals_44k.flac. Writes: a log-frequency magnitude picture (70 Hz .. 4 kHz, 5.8 ms hop), the
spectral-flux onset strength, the onset candidates picked from it (with their strength), the broadband level and the
4..10 kHz level (sibilants and plosive bursts, which a 4 kHz picture cuts off).
"""
import sys
from candidates import audio_features
from pathlib import Path
import numpy as np, soundfile as sf, librosa

SR, NFFT, HOP = 44100, 2048, 256
FMIN, FMAX, NBINS = 70.0, 4000.0, 320

def compute(pkg: Path) -> dict:
    y, sr = sf.read(pkg / 'vocals_44k.flac', dtype='float32', always_2d=True); y = y.mean(axis=1)
    if sr != SR: y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    S = np.abs(librosa.stft(y, n_fft=NFFT, hop_length=HOP, window='hann')); freqs = np.fft.rfftfreq(NFFT, 1 / SR)
    t = np.arange(S.shape[1]) * HOP / SR
    logf = np.geomspace(FMIN, FMAX, NBINS)
    idx = np.interp(logf, freqs, np.arange(len(freqs))); lo = np.floor(idx).astype(int); fr = (idx - lo)[:, None]
    L = S[lo] * (1 - fr) + S[np.minimum(lo + 1, len(freqs) - 1)] * fr
    db = 20 * np.log10(L + 1e-7); ref = np.percentile(db, 99.7); pic = np.clip((db - (ref - 70)) / 70, 0, 1)
    env = librosa.onset.onset_strength(S=librosa.power_to_db(librosa.feature.melspectrogram(S=S ** 2, sr=SR, n_mels=96, fmax=8000)), sr=SR, hop_length=HOP, lag=2, max_size=3)
    on = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, backtrack=False, units='frames', delta=.03, wait=5)
    bt = librosa.onset.onset_backtrack(on, env)
    rms = 20 * np.log10(np.sqrt(np.mean(S ** 2, axis=0)) + 1e-9)
    hf = 20 * np.log10(np.sqrt(np.mean(S[(freqs >= 4000) & (freqs <= 10000)] ** 2, axis=0)) + 1e-9)
    out = {'t': t.astype(np.float32), 'logf': logf.astype(np.float32), 'pic': (pic * 255).astype(np.uint8), 'env': env.astype(np.float32),
            'onset_peak': t[on].astype(np.float32), 'onset_start': t[bt].astype(np.float32), 'onset_strength': env[on].astype(np.float32),
            'rms': rms.astype(np.float32), 'hf': hf.astype(np.float32), 'duration': np.float32(len(y) / SR)}
    out.update({'qa_' + k: v for k, v in audio_features(pkg).items()})
    return out

if __name__ == '__main__':
    if '--help' in sys.argv: print(__doc__); raise SystemExit(0)
    if len(sys.argv) != 3: raise SystemExit(__doc__)
    f = compute(Path(sys.argv[1])); np.savez_compressed(sys.argv[2], **f)
    print(sys.argv[2], 'frames', len(f['t']), 'onsets', len(f['onset_peak']), 'duration', float(f['duration']))
