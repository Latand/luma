#!/usr/bin/env python3
"""Objective numbers for the audio a trainer plays, measured against the original upload. Reads only.

  measure_audio.py <package_dir>... [--originals DIR]...

One JSON line per package:
  stems              codec, sample rate, channels, duration and average kb/s of each of the four MP3s
  html_bytes         size of the trainer next to the package
  bands              spectral energy above 11 kHz and above 16 kHz in foreground + backing: relative_db against the same
                     band of the original (0 = all of it is there), and each band's share of the original's total energy
  null_db            foreground + backing minus the original, in dB below the original (more negative = closer). Measured
                     in 10-second blocks, each aligned to the original on its own, with one gain for the whole song (the
                     stems carry stems.joint_gain); lags_ms is the range of the block offsets, so drift in time shows up.
  null_below_11k_db  the same test under 11 kHz: what changed inside the band that the old 22 kHz stems kept.
The original is found the way upgrade_audio finds it.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np
from scipy import signal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))
import stems  # noqa: E402
from upgrade_audio import find_original  # noqa: E402

SR = stems.SAMPLE_RATE

def spectrum(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    f, p = signal.welch(x.astype(np.float64), SR, nperseg=8192, axis=0); return f, p.sum(axis=1)

def null_residual(s: np.ndarray, o: np.ndarray, block_s: float = 10.0, max_lag_s: float = .05) -> tuple[float, float, list[int]]:
    n = min(len(s), len(o)); block = int(min(block_s * SR, n // 3)); max_lag = int(min(max_lag_s * SR, block // 4))
    sm = s.mean(axis=1); om = o.mean(axis=1); xx = xz = zz = 0.0; lags = []
    for i in range(max_lag, n - block - max_lag + 1, block):
        c = signal.correlate(sm[i - max_lag:i + block + max_lag], om[i:i + block], mode='valid', method='fft'); lag = int(np.argmax(c)) - max_lag; lags.append(lag)
        x = o[i:i + block].astype(np.float64); z = s[i + lag:i + lag + block].astype(np.float64)
        xx += float(np.sum(x * x)); xz += float(np.sum(x * z)); zz += float(np.sum(z * z))
    gain = xz / xx
    return 10 * np.log10(max(zz - xz * xz / xx, 1e-30) / (gain * gain * xx)), gain, lags

def measure(pkg: Path, original: Path | None = None, extra: list[Path] = ()) -> dict:
    pkg = Path(pkg).resolve(); html = pkg.parent / f'Luma_{pkg.name}.html'
    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8')) if (pkg / 'manifest.json').is_file() else {}
    out = {'package': pkg.name, 'stems': {n: stems.probe(pkg / n) for n in stems.FILES}, 'html_bytes': html.stat().st_size if html.is_file() else None}
    if original is None: original = (find_original(pkg, manifest, extra) or (None,))[0]
    if original is None: return {**out, 'original': None}
    o = stems.decode(original); fore = stems.decode(pkg / 'foreground.mp3'); back = stems.decode(pkg / 'backing.mp3')
    k = min(len(fore), len(back)); s = fore[:k] + back[:k]; del fore, back
    fo, po = spectrum(o); fs, ps = spectrum(s); total = po.sum(); bands = {}
    for hz in (11000, 16000):
        eo = float(po[fo >= hz].sum()); es = float(ps[fs >= hz].sum())
        bands[f'above_{hz // 1000}k'] = {'relative_db': round(10 * np.log10(es / eo), 1), 'original_share_db': round(10 * np.log10(eo / total), 1), 'stems_share_db': round(10 * np.log10(es / total), 1)}
    null, gain, lags = null_residual(s, o)
    sos = signal.butter(10, 11000, fs=SR, output='sos'); low, _, _ = null_residual(signal.sosfiltfilt(sos, s, axis=0), signal.sosfiltfilt(sos, o, axis=0))
    return {**out, 'original': original.name, 'bands': bands, 'null_db': round(float(null), 1), 'null_below_11k_db': round(float(low), 1), 'gain': round(float(gain), 4),
            'lags_ms': [round(min(lags) / SR * 1000, 2), round(max(lags) / SR * 1000, 2)]}

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+'); ap.add_argument('--originals', action='append', default=[], metavar='DIR')
    a = ap.parse_args()
    for p in map(Path, a.package):
        if (p / 'target.json').is_file(): print(json.dumps(measure(p, extra=[Path(d) for d in a.originals]), ensure_ascii=False), flush=True)
