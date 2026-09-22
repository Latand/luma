#!/usr/bin/env python3
"""Cache the raw pitch frames of prepared song packages for tools/pitch_quality.py.

  pitch_frames.py --out CACHE_DIR songs/*

Re-runs stages [3/8] pYIN and [4/8] CREPE of studio/prepare_song.py on <package>/vocals_44k.flac with the same settings
(22.05 kHz mono scaled by the package's joint gain for pYIN; 16 kHz, hop 160, CREPE full, Viterbi per 1024-frame batch,
fmin 50 / fmax 1500 for CREPE) and writes <CACHE_DIR>/<package>.npz with:
  P    pYIN rows [t, f0, voiced prob, rms, yin f0]     f0, pd  CREPE pitch and periodicity after the pipeline's filters
  act  CREPE's 360-bin activations (float16), so other decoders can be tried without re-running the network
The package itself is never written. One song takes 2-3 minutes of CPU (pYIN) plus a few seconds of GPU (CREPE)."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import numpy as np, soundfile as sf, librosa

def extract(pkg: Path, out: Path, force: bool = False) -> Path | None:
    import torch, torchcrepe
    dst = out / (pkg.name + '.npz')
    if dst.exists() and not force: print('skip (cached)', pkg.name, flush=True); return dst
    man = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8')); gain = man['audio']['gain']
    vocal, sr = sf.read(pkg / 'vocals_44k.flac', dtype='float32', always_2d=True); duration = len(vocal) / sr
    t0 = time.time(); y = librosa.resample(vocal.T, orig_sr=sr, target_sr=22050).T * gain; y = y.mean(axis=1); sr2 = 22050; rows = []; hop = 256
    for start in np.arange(0, duration, 25):
        lo = max(0, int(round((start - .5) * sr2))); hi = min(len(y), int(round((start + 25.5) * sr2))); z = y[lo:hi]
        f, _, prob = librosa.pyin(z, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('E6'), sr=sr2, frame_length=4096, hop_length=hop, fill_na=np.nan)
        yf = librosa.yin(z, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('E6'), sr=sr2, frame_length=4096, hop_length=hop)
        rms = librosa.feature.rms(y=z, frame_length=2048, hop_length=hop)[0]; tt = lo / sr2 + np.arange(len(f)) * hop / sr2; keep = (tt >= start) & (tt < min(start + 25, duration))
        rows.extend(zip(tt[keep], f[keep], prob[keep], rms[keep], yf[keep]))
    P = np.array(rows); pyin_s = time.time() - t0
    t0 = time.time(); device = 'cuda' if torch.cuda.is_available() else 'cpu'
    y16 = librosa.resample(vocal.mean(1), orig_sr=sr, target_sr=16000); audio = torch.from_numpy(y16)[None]
    acts, f0s, pds = [], [], []
    with torch.no_grad():
        for frames in torchcrepe.preprocess(audio, 16000, 160, 1024, device, True):
            prob = torchcrepe.infer(frames, 'full', device, embed=False).reshape(1, -1, 360).transpose(1, 2)
            acts.append(prob.detach().cpu().half().numpy()[0])
            f, p = torchcrepe.postprocess(prob.clone(), 50, 1500, torchcrepe.decode.viterbi, False, True); f0s.append(f.cpu()); pds.append(p.cpu())
    f0 = torch.cat(f0s, 1); pd = torch.cat(pds, 1); pd = torchcrepe.filter.median(pd, 3); f0 = torchcrepe.filter.mean(f0, 3)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(dst, P=P, f0=f0[0].numpy(), pd=pd[0].numpy(), act=np.concatenate(acts, axis=1), duration=duration, gain=gain, pyin_s=pyin_s, crepe_s=time.time() - t0)
    print(f'done {pkg.name}: {len(f0[0])} frames, pYIN {pyin_s:.0f} s, CREPE {time.time() - t0:.0f} s', flush=True); return dst

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+'); ap.add_argument('--out', required=True, help='cache directory (outside the song packages)'); ap.add_argument('--force', action='store_true')
    a = ap.parse_args(); out = Path(a.out).expanduser().resolve()
    for p in a.package:
        pkg = Path(p).expanduser().resolve()
        if not (pkg / 'vocals_44k.flac').exists() or not (pkg / 'manifest.json').exists(): print('skip (not a package)', pkg.name, flush=True); continue
        if out == pkg or out.is_relative_to(pkg): raise SystemExit('the cache must live outside the song package')
        extract(pkg, out, a.force)

if __name__ == '__main__':
    main()
