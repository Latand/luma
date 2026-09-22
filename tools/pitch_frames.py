#!/usr/bin/env python3
"""Cache the raw pitch frames of prepared song packages for tools/pitch_quality.py.

  pitch_frames.py --out CACHE_DIR [--seed N] songs/*

Re-runs stages [3/8] pYIN and [4/8] CREPE of studio/prepare_song.py on <package>/vocals_44k.flac with the same settings
(22.05 kHz mono scaled by the package's joint gain for pYIN; 16 kHz, hop 160, CREPE full, Viterbi per 1024-frame batch,
fmin 50 / fmax 1500 for CREPE) and writes <CACHE_DIR>/<package>.npz with:
  P    pYIN rows [t, f0, voiced prob, rms, yin f0]     f0, pd  CREPE pitch and periodicity after the pipeline's filters
  act  CREPE's 360-bin activations (float16), so other decoders can be tried without re-running the network
  meta JSON: sha256 and size of the stem, the gain, SETTINGS, the dither seed and the library versions
torchcrepe adds a ±20-cent dither to every decoded frame from numpy's global generator; the pipeline leaves it unseeded,
this cache seeds it with --seed (default 0), so two extractions of the same stem give the same f0 bit for bit.
A cache is reused only if its stem hash, gain, settings and seed match; otherwise it is extracted again. load() refuses
a cache that does not match the package. The package itself is never written. One song takes 2-3 minutes of CPU (pYIN)
plus a few seconds of GPU (CREPE)."""
from __future__ import annotations
import argparse, hashlib, json, time
from pathlib import Path
import numpy as np

STEM = 'vocals_44k.flac'
# Everything the frames depend on besides the stem, the gain and the seed. Bump 'format' when extract() changes.
SETTINGS = {'format': 2,
            'pyin': {'sr': 22050, 'fmin': 'C2', 'fmax': 'E6', 'frame_length': 4096, 'hop': 256, 'chunk_s': 25, 'context_s': .5, 'rms_frame': 2048},
            'crepe': {'sr': 16000, 'hop': 160, 'model': 'full', 'batch': 1024, 'fmin': 50, 'fmax': 1500, 'decoder': 'viterbi',
                      'pd_median': 3, 'f0_mean': 3, 'act_dtype': 'float16'}}

class CacheError(Exception):
    """The cache is missing or does not belong to the package as it is now."""

def stem_fingerprint(pkg: Path) -> dict:
    h = hashlib.sha256(); f = pkg / STEM
    with open(f, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''): h.update(block)
    return {'stem_sha256': h.hexdigest(), 'stem_bytes': f.stat().st_size}

def package_gain(pkg: Path) -> float:
    return float(json.loads((pkg / 'manifest.json').read_text(encoding='utf-8'))['audio']['gain'])

def mismatch(meta: dict | None, pkg: Path, seed: int | None = None, check_seed: bool = False) -> str | None:
    """Why a cache with this `meta` cannot stand for `pkg` now, or None when it can."""
    if not meta: return 'no metadata (made before stem fingerprints were recorded)'
    if meta.get('settings') != SETTINGS: return 'extraction settings differ'
    fp = stem_fingerprint(pkg)
    if meta.get('stem_bytes') != fp['stem_bytes'] or meta.get('stem_sha256') != fp['stem_sha256']: return f'{STEM} changed'
    if meta.get('gain') is None or not np.isclose(meta['gain'], package_gain(pkg), rtol=0, atol=1e-12): return 'gain in manifest.json changed'
    if check_seed and meta.get('seed') != seed: return f"dither seed {meta.get('seed')} != {seed}"
    return None

def read_meta(c) -> dict | None:
    return json.loads(str(c['meta'])) if 'meta' in c else None

def load(cache_dir, pkg: Path) -> dict:
    """The cached frames of `pkg`, with meta decoded. Raises CacheError when there is no cache or it is stale."""
    f = Path(cache_dir) / (pkg.name + '.npz')
    if not f.exists(): raise CacheError('no cache')
    c = dict(np.load(f)); meta = read_meta(c); why = mismatch(meta, pkg)
    if why: raise CacheError(f'stale cache {f}: {why}; re-run tools/pitch_frames.py --out {cache_dir} {pkg}')
    c['meta'] = meta; return c

def decode(acts, seed: int | None, device: str = 'cpu'):
    """Stage [4/8]'s post-processing of CREPE activations (one array [360, frames] per 1024-frame batch) on `device`:
    Viterbi per batch, then median 3 on periodicity and mean 3 on pitch. `seed` seeds the dither; None leaves it
    unseeded, as the pipeline does."""
    import torch, torchcrepe
    if seed is not None: np.random.seed(seed)
    f0s, pds = [], []
    with torch.no_grad():
        for a in acts:
            f, p = torchcrepe.postprocess(torch.as_tensor(a, device=device)[None].clone(), 50, 1500, torchcrepe.decode.viterbi, False, True); f0s.append(f.cpu()); pds.append(p.cpu())
    pd = torchcrepe.filter.median(torch.cat(pds, 1), 3); f0 = torchcrepe.filter.mean(torch.cat(f0s, 1), 3)
    return f0[0].numpy(), pd[0].numpy()

def extract(pkg: Path, out: Path, force: bool = False, seed: int | None = 0) -> Path | None:
    import torch, torchcrepe, soundfile as sf, librosa, scipy, importlib.metadata as md
    dst = out / (pkg.name + '.npz')
    if dst.exists() and not force:
        why = mismatch(read_meta(np.load(dst)), pkg, seed, check_seed=True)
        if not why: print('skip (cached)', pkg.name, flush=True); return dst
        print(f're-extract {pkg.name}: {why}', flush=True)
    fp = stem_fingerprint(pkg); gain = package_gain(pkg)
    vocal, sr = sf.read(pkg / STEM, dtype='float32', always_2d=True); duration = len(vocal) / sr
    t0 = time.time(); y = librosa.resample(vocal.T, orig_sr=sr, target_sr=22050).T * gain; y = y.mean(axis=1); sr2 = 22050; rows = []; hop = 256
    for start in np.arange(0, duration, 25):
        lo = max(0, int(round((start - .5) * sr2))); hi = min(len(y), int(round((start + 25.5) * sr2))); z = y[lo:hi]
        f, _, prob = librosa.pyin(z, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('E6'), sr=sr2, frame_length=4096, hop_length=hop, fill_na=np.nan)
        yf = librosa.yin(z, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('E6'), sr=sr2, frame_length=4096, hop_length=hop)
        rms = librosa.feature.rms(y=z, frame_length=2048, hop_length=hop)[0]; tt = lo / sr2 + np.arange(len(f)) * hop / sr2; keep = (tt >= start) & (tt < min(start + 25, duration))
        rows.extend(zip(tt[keep], f[keep], prob[keep], rms[keep], yf[keep]))
    P = np.array(rows); pyin_s = time.time() - t0
    t0 = time.time(); device = 'cuda' if torch.cuda.is_available() else 'cpu'
    y16 = librosa.resample(vocal.mean(1), orig_sr=sr, target_sr=16000); audio = torch.from_numpy(y16)[None]; acts = []
    with torch.no_grad():
        for frames in torchcrepe.preprocess(audio, 16000, 160, 1024, device, True):
            acts.append(torchcrepe.infer(frames, 'full', device, embed=False).reshape(1, -1, 360).transpose(1, 2)[0].cpu().numpy())
    f0, pd = decode(acts, seed, device)   # the pipeline decodes the float32 activations; only the cached copy is float16
    meta = {**fp, 'gain': gain, 'settings': SETTINGS, 'seed': seed,
            'libs': {'librosa': librosa.__version__, 'torchcrepe': md.version('torchcrepe'), 'torch': torch.__version__, 'scipy': scipy.__version__, 'numpy': np.__version__}}
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, P=P, f0=f0, pd=pd, act=np.concatenate(acts, axis=1).astype(np.float16), duration=duration, gain=gain,
                        pyin_s=pyin_s, crepe_s=time.time() - t0, meta=np.array(json.dumps(meta)))
    print(f'done {pkg.name}: {len(f0)} frames, pYIN {pyin_s:.0f} s, CREPE {time.time() - t0:.0f} s, seed {seed}', flush=True); return dst

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+'); ap.add_argument('--out', required=True, help='cache directory (outside the song packages)'); ap.add_argument('--force', action='store_true')
    ap.add_argument('--seed', type=int, default=0, help="numpy seed for torchcrepe's dither (default 0)")
    a = ap.parse_args(); out = Path(a.out).expanduser().resolve()
    for p in a.package:
        pkg = Path(p).expanduser().resolve()
        if not (pkg / STEM).exists() or not (pkg / 'manifest.json').exists(): print('skip (not a package)', pkg.name, flush=True); continue
        if out == pkg or out.is_relative_to(pkg): raise SystemExit('the cache must live outside the song package')
        extract(pkg, out, a.force, a.seed)

if __name__ == '__main__':
    main()
