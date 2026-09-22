#!/usr/bin/env python3
"""Label-free quality measurement of the target melody (docs/PITCH_ACCURACY.md).

Two inputs per song: the shipped target.json and, optionally, a cache of the raw pYIN/CREPE frames produced by
tools/pitch_frames.py (never the package's own work/ files: the pipeline deletes them). Nothing here writes into a
song package.

  pitch_quality.py map    songs/*                       metrics from target.json alone (no cache needed)
  pitch_quality.py frames --cache DIR songs/*           add frame-level metrics: CREPE/pYIN disagreement, per-gate losses,
                                                        boundary stability, and rebuild the map to check it matches
  pitch_quality.py gates  --cache DIR songs/*           rebuild the map with one gate moved at a time: what each gate costs
  pitch_quality.py arbitrate --cache DIR [--variant V] songs/*   harmonic arbiter: who is right in octave disputes
  pitch_quality.py decode --cache DIR --variant V songs/*   rebuild the map with an alternative decoder / post-process and
                                                        print the same metrics (V: baseline | narrow | song_range |
                                                        whole_song | argmax | viterbi_norm | viterbi_octave | octave_fix | narrow+octave_fix)
  --json  print machine-readable rows instead of the table

Every number is a proxy for accuracy, not accuracy itself — the doc says which is which."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, scipy.ndimage as ndi

HOP = .02

def runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int))); return list(zip(edges[::2], edges[1::2]))

def hz_to_midi(f):
    with np.errstate(divide='ignore', invalid='ignore'): return 69 + 12 * np.log2(np.asarray(f, dtype=float) / 440)

# ---------------------------------------------------------------- the map stage, copied from studio/prepare_song.py build_map()
# Kept byte-for-byte in logic (thresholds, filters, run rules) so the rebuilt notes equal the shipped ones; instrumented
# so every gate can be counted. Parameters are exposed only for the sensitivity and prototype runs.
def build(ct, f0, pd, P, duration, med_stable=11, med_run=5, split=.72, ok_ratio=.55, octave_fix=False, pd_strong=.45, db_strong=-43, min_run=5, pd_rel=.70, fill_holes=0):
    ts = np.arange(0, duration, HOP)
    def nearest(src_t, vals):
        ii = np.clip(np.searchsorted(src_t, ts), 1, len(src_t) - 1); ii -= abs(src_t[ii - 1] - ts) < abs(src_t[ii] - ts); return vals[ii]
    fc = nearest(ct, f0); pdg = nearest(ct, pd); fp = nearest(P[:, 0], P[:, 1]); rms = nearest(P[:, 0], P[:, 3])
    midi = hz_to_midi(fc); mp = hz_to_midi(fp)
    with np.errstate(divide='ignore', invalid='ignore'): db = 20 * np.log10(rms + 1e-12); agree = np.abs(midi - mp) * 100
    inrange = np.isfinite(midi) & (midi >= 36) & (midi <= 90)
    strong = inrange & (pdg > pd_strong) & (db > db_strong)
    med = ndi.median_filter(np.nan_to_num(midi, nan=0), size=med_stable); stable = np.abs(midi - med) < 1.0
    weak_raw = inrange & (pdg > .25) & (db > -34) & stable; weak = weak_raw.copy()
    for a, b in runs(weak):
        if b - a < 8: weak[a:b] = False
    valid_raw = strong | weak; valid = valid_raw.copy()
    for a, b in runs(valid):
        if b - a < min_run: valid[a:b] = False
    if fill_holes:   # prototype: close holes of at most `fill_holes` frames inside a sung run
        for a, b in runs(~valid):
            if b - a <= fill_holes and a > 0 and b < len(valid): valid[a:b] = True
    reliable = strong & (pdg >= pd_rel) & (db > -38) & ((np.isfinite(agree) & (agree < 50)) | (pdg >= .85))
    for a, b in runs(valid): reliable[a:min(a + 2, b)] = False; reliable[max(a, b - 2):b] = False
    smooth = np.full(len(ts), np.nan)
    for a, b in runs(valid): smooth[a:b] = ndi.median_filter(midi[a:b], size=med_run, mode='nearest')
    notes = []
    for a, b in runs(valid):
        cur = int(round(smooth[a])); start = a
        for i in range(a + 1, b + 1):
            if i == b or abs(smooth[i] - cur) > split:
                if i - start >= 4:
                    center = float(np.median(midi[start:i])); elig = float(np.mean(reliable[start:i]))
                    notes.append({'id': len(notes), 'a': round(ts[start], 3), 'b': round(min(duration, ts[i - 1] + HOP), 3), 'm': round(center, 3), 'n': int(round(center)), 'q': round(float(np.median(pdg[start:i])), 3), 'ok': elig >= ok_ratio, 'ignored': False, '_i': (start, i)})
                if i < b: cur = int(round(smooth[i])); start = i
    if octave_fix: notes = fix_octaves(notes)
    frames = {'ts': ts, 'midi': midi, 'mp': mp, 'pdg': pdg, 'db': db, 'agree': agree, 'inrange': inrange, 'strong': strong, 'stable': stable,
              'weak_raw': weak_raw, 'weak': weak, 'valid_raw': valid_raw, 'valid': valid, 'reliable': reliable, 'smooth': smooth}
    return notes, frames

def fix_octaves(notes, window=.6, tol=1.5):
    """Octave-continuity post-process (prototype): a note whose centre is ~12 (or 24) semitones from the note-duration
    weighted median of its neighbours within `window` seconds on either side is moved by that many octaves. Only the
    octave changes; timing, q and ok stay. Iterated once. A run of consecutive notes that are all displaced together
    (the neighbourhood agrees with them) is left alone on purpose: without labels there is no way to tell whether a
    whole phrase moved."""
    out = [dict(n) for n in notes]
    for k, n in enumerate(out):
        nb = [x for x in notes if x is not notes[k] and x['a'] < n['b'] + window and x['b'] > n['a'] - window]
        if not nb: continue
        w = np.array([x['b'] - x['a'] for x in nb]); m = np.array([x['m'] for x in nb])
        order = np.argsort(m); cw = np.cumsum(w[order]); ref = float(m[order][np.searchsorted(cw, cw[-1] / 2)])
        d = n['m'] - ref
        for oct in (12, 24):
            if abs(abs(d) - oct) <= tol:
                shift = -np.sign(d) * oct; n['m'] = round(n['m'] + shift, 3); n['n'] = int(round(n['m'])); n['octaveFixed'] = int(shift); break
    return out

# ---------------------------------------------------------------- metrics on a note list (works on target.json alone)
def note_metrics(notes, duration, points=None):
    a = np.array([n['a'] for n in notes]); b = np.array([n['b'] for n in notes]); m = np.array([n['m'] for n in notes]); ok = np.array([n['ok'] for n in notes], bool)
    dur = b - a; gap = a[1:] - b[:-1]; dm = np.diff(m); adj = gap < .3
    oct_jump = adj & (np.abs(np.abs(dm) - 12) <= 1.0)
    sandwich = sum(1 for k in range(1, len(m) - 1) if abs(abs(m[k] - m[k - 1]) - 12) <= 1 and abs(abs(m[k] - m[k + 1]) - 12) <= 1 and abs(m[k - 1] - m[k + 1]) <= 2 and a[k] - b[k - 1] < .3 and a[k + 1] - b[k] < .3)
    # neighbourhood octave outliers: same rule fix_octaves uses, counted not applied
    outliers = sum(1 for n in fix_octaves(notes) if n.get('octaveFixed'))
    # fragmentation: chains of touching notes (gap <= 1 frame) within 1 semitone, i.e. one held tone cut into pieces
    chains = []; cur = 1
    for i in range(1, len(notes)):
        if a[i] - b[i - 1] <= .021 and abs(m[i] - m[i - 1]) <= 1.0: cur += 1
        else: chains.append(cur); cur = 1
    chains.append(cur)
    # boundary causes
    hole2 = hole10 = same_n = diff_n = far = 0
    for i in range(1, len(notes)):
        g = a[i] - b[i - 1]
        if g <= .021: same_n += notes[i]['n'] == notes[i - 1]['n']; diff_n += notes[i]['n'] != notes[i - 1]['n']
        else:
            k = int(round(g / HOP)); hole2 += k <= 2; hole10 += 2 < k <= 10; far += k > 10
    out = {'notes': len(notes), 'ok_notes': int(ok.sum()), 'ok_pct': round(100 * ok.mean(), 1) if len(ok) else 0,
           'note_med_dur_s': round(float(np.median(dur)), 3), 'notes_under_150ms_pct': round(100 * float((dur < .15).mean()), 1),
           'octave_jumps_adjacent': int(oct_jump.sum()), 'octave_sandwich': int(sandwich), 'octave_outliers_nbhd': int(outliers),
           'split_chains': int((np.array(chains) >= 2).sum()), 'pieces_in_chains': int(sum(c for c in chains if c >= 2)),
           'boundary_hole_le2': hole2, 'boundary_hole_3_10': hole10, 'boundary_same_semitone': same_n, 'boundary_new_semitone': diff_n, 'boundary_gap_gt200ms': far,
           'midi_p5': round(float(np.percentile(m, 5)), 1), 'midi_p50': round(float(np.percentile(m, 50)), 1), 'midi_p95': round(float(np.percentile(m, 95)), 1)}
    if points is not None:
        valid = np.array([p[1] is not None for p in points]); rel = np.array([p[3] for p in points], bool)
        out['candidate_pct'] = round(100 * valid.mean(), 1); out['comparable_pct'] = round(100 * rel.sum() * HOP / duration, 1)
    return out

# ---------------------------------------------------------------- frame-level metrics (need the cache)
def frame_metrics(fr, notes):
    midi, mp, pdg, db, valid, rel = fr['midi'], fr['mp'], fr['pdg'], fr['db'], fr['valid'], fr['reliable']
    both = np.isfinite(midi) & np.isfinite(mp) & (pdg > .45) & (db > -43)
    d = np.abs(midi - mp)
    oct12 = both & (np.abs(d - 12) <= 1.0); oct24 = both & (np.abs(d - 24) <= 1.0); agree = both & (d <= .5)
    # inside notes: does the note's median sit an octave from pYIN's median over the same frames?
    note_oct = 0; note_cmp = 0; crepe_low = 0
    for n in notes:
        s, e = n['_i']; q = np.isfinite(mp[s:e]) & (P_prob_ok(fr, s, e))
        if q.sum() >= 4:
            note_cmp += 1; dd = abs(n['m'] - float(np.median(mp[s:e][q])))
            if abs(dd - 12) <= 1.0 or abs(dd - 24) <= 1.0: note_oct += 1; crepe_low += n['m'] < np.median(mp[s:e][q])
    # coverage: loud frames of the stem (energy alone) that got no pitch
    loud = db > -30; loud_nopitch = loud & ~valid
    # per-gate losses among loud frames
    inr, strong, stable, weak_raw, weak, valid_raw = fr['inrange'], fr['strong'], fr['stable'], fr['weak_raw'], fr['weak'], fr['valid_raw']
    losses = {'loud_frames': int(loud.sum()),
              'lost_out_of_range': int((loud & ~inr).sum()),
              'lost_periodicity_le45_and_not_weak': int((loud & inr & (pdg <= .45) & ~weak).sum()),
              'lost_level_gate': int((loud & inr & (pdg > .45) & (db <= -43)).sum()),
              'lost_weak_run_lt8': int((loud & weak_raw & ~weak).sum()),
              'lost_valid_run_lt5': int((loud & valid_raw & ~valid).sum()),
              'valid_not_reliable': int((valid & ~rel).sum()), 'reliable': int(rel.sum()), 'valid': int(valid.sum())}
    return {'frames_both_confident': int(both.sum()), 'crepe_pyin_agree_50c_pct': round(100 * agree.sum() / max(both.sum(), 1), 1),
            'crepe_pyin_octave_pct': round(100 * (oct12 | oct24).sum() / max(both.sum(), 1), 2),
            'crepe_pyin_octave_frames': int((oct12 | oct24).sum()), 'crepe_below_pyin_frames': int(((oct12 | oct24) & (midi < mp)).sum()),
            'notes_compared_to_pyin': note_cmp, 'notes_octave_vs_pyin': note_oct, 'notes_octave_vs_pyin_crepe_lower': int(crepe_low),
            'loud_frames_no_pitch_pct': round(100 * loud_nopitch.sum() / max(loud.sum(), 1), 1), **losses}

def P_prob_ok(fr, s, e): return fr['pyin_prob'][s:e] > .5

GATES = [('baseline', {}), ('pd_strong .45->.35', {'pd_strong': .35}), ('pd_strong .45->.55', {'pd_strong': .55}), ('db_strong -43->-48', {'db_strong': -48}),
         ('min_run 5->3', {'min_run': 3}), ('min_run 5->8', {'min_run': 8}), ('fill_holes<=2', {'fill_holes': 2}), ('fill_holes<=5', {'fill_holes': 5}),
         ('pd_rel .70->.60', {'pd_rel': .60}), ('ok_ratio .55->.40', {'ok_ratio': .40}), ('split .72->1.0', {'split': 1.0}), ('med_run 5->9', {'med_run': 9})]

def gates(ct, f0, pd, P, duration):
    """What each gate of the map stage costs or buys: rebuild with one gate moved and report the note counts."""
    out = {}
    for name, kw in GATES:
        ns, fr = build(ct, f0, pd, P, duration, **kw); nm = note_metrics(ns, duration)
        out[name] = {'notes': len(ns), 'ok_notes': nm['ok_notes'], 'candidate_s': round(float(fr['valid'].sum() * HOP), 1), 'comparable_s': round(float(fr['reliable'].sum() * HOP), 1),
                     'sustained_notes_ge600ms': int(sum(1 for n in ns if n['b'] - n['a'] >= .6)), 'notes_under_150ms': int(sum(1 for n in ns if n['b'] - n['a'] < .15)),
                     'octave_jumps_adjacent': nm['octave_jumps_adjacent'], 'octave_outliers_nbhd': nm['octave_outliers_nbhd'], 'split_chains': nm['split_chains']}
    return out

def stability(ct, f0, pd, P, duration, base_notes):
    """How many note boundaries move when the map's own parameters are nudged: a proxy for how arbitrary they are."""
    def bounds(ns): return np.array(sorted(set([n['a'] for n in ns] + [n['b'] for n in ns])))
    b0 = bounds(base_notes); out = {}
    for name, kw in [('med11->9', {'med_stable': 9}), ('med11->13', {'med_stable': 13}), ('run5->3', {'med_run': 3}), ('run5->7', {'med_run': 7}), ('split.72->.6', {'split': .6}), ('split.72->.85', {'split': .85})]:
        ns, _ = build(ct, f0, pd, P, duration, **kw); b1 = bounds(ns)
        kept = np.isin(np.round(b0, 3), np.round(b1, 3)).mean() if len(b0) else 1.0
        out[name] = {'notes': len(ns), 'boundaries_kept_pct': round(100 * float(kept), 1)}
    return out

# ---------------------------------------------------------------- alternative decoders (prototypes for the doc)
def decode_variant(cache, variant, song_notes):
    """Return (ct, f0, pd) for a variant of stage [4/8] from the cached 360-bin activations."""
    import torch, torchcrepe
    act = torch.from_numpy(cache['act'].astype(np.float32))[None]  # (1, 360, T) sigmoid outputs
    fmin, fmax = 50., 1500.
    if variant.startswith('narrow'): fmin, fmax = 65.4, 1046.5     # C2..C6
    if variant.startswith('song_range'):
        m = np.array([n['m'] for n in song_notes if n['ok']]); lo, hi = np.percentile(m, 2) - 3, np.percentile(m, 98) + 3
        fmin, fmax = 440 * 2 ** ((lo - 69) / 12), 440 * 2 ** ((hi - 69) / 12)
    decoder = torchcrepe.decode.argmax if variant.startswith('argmax') else torchcrepe.decode.viterbi
    if variant.startswith('viterbi_norm'): decoder = viterbi_normalised
    if variant.startswith('viterbi_octave'): decoder = viterbi_octave
    T = act.shape[2]; f0s, pds = [], []
    step = T if variant.startswith('whole_song') else 1024   # the pipeline decodes 1024-frame batches independently
    with torch.no_grad():
        for s in range(0, T, step):
            f, p = torchcrepe.postprocess(act[:, :, s:s + step].clone(), fmin, fmax, decoder, False, True); f0s.append(f); pds.append(p)
    f0 = torch.cat(f0s, 1); pd = torch.cat(pds, 1)
    pd = torchcrepe.filter.median(pd, 3); f0 = torchcrepe.filter.mean(f0, 3)
    f0 = f0[0].numpy(); pd = pd[0].numpy(); return np.arange(len(f0)) * 160 / 16000, f0, pd, (round(fmin, 1), round(fmax, 1))

def viterbi_normalised(logits):
    """torchcrepe's viterbi() runs softmax over the network's sigmoid outputs (values in 0..1), which flattens every
    frame to nearly uniform emissions (peak ~0.007 against 0.0028 for uniform) so the transition prior dominates. This
    prototype normalises the sigmoid outputs to sum to one per frame instead and keeps the same transition matrix."""
    import torch, torchcrepe, librosa
    tv = torchcrepe.decode.viterbi
    if not hasattr(tv, 'transition'):
        xx, yy = np.meshgrid(range(360), range(360)); tr = np.maximum(12 - abs(xx - yy), 0); tv.transition = tr / tr.sum(axis=1, keepdims=True)
    probs = logits.clone(); probs[~torch.isfinite(probs)] = 0; probs = probs.clamp_min(1e-6); probs = probs / probs.sum(dim=1, keepdim=True)
    bins = np.array([librosa.sequence.viterbi(seq, tv.transition).astype(np.int64) for seq in probs.cpu().numpy()])
    bins = torch.tensor(bins, device=logits.device); return bins, torchcrepe.convert.bins_to_frequency(bins)

def viterbi_octave(logits, eps=.02):
    """Prototype: the pipeline's decoder (softmax emissions, same local transition prior) plus a small probability of
    jumping exactly one octave (60 bins) in one frame, so a real octave leap of the voice does not need six frames of
    maximal steps that the prior makes almost impossible."""
    import torch, torchcrepe, librosa
    if not hasattr(viterbi_octave, 'transition'):
        xx, yy = np.meshgrid(range(360), range(360)); tr = np.maximum(12 - abs(xx - yy), 0).astype(float)
        tr[abs(xx - yy) == 60] = 12 * eps; viterbi_octave.transition = tr / tr.sum(axis=1, keepdims=True)
    with torch.no_grad(): probs = torch.nn.functional.softmax(logits, dim=1)
    bins = np.array([librosa.sequence.viterbi(seq, viterbi_octave.transition).astype(np.int64) for seq in probs.cpu().numpy()])
    bins = torch.tensor(bins, device=logits.device); return bins, torchcrepe.convert.bins_to_frequency(bins)

# ---------------------------------------------------------------- harmonic arbiter for octave disputes (heuristic ground truth)
def odd_even(y, sr, t0, t1, f_low, nfft=8192, k=8):
    """On the 44.1 kHz stem, the ratio of peak magnitude at the ODD harmonics of `f_low` (1,3,5,7 x) to its EVEN
    harmonics (2,4,6,8 x = the harmonics of the candidate one octave up), median over 30 ms hops of [t0, t1). When the
    odd harmonics are (nearly) absent, `f_low` is a sub-harmonic artefact and the real pitch is an octave higher.
    Calibrated in docs/PITCH_ACCURACY.md 4.2: at the true pitch the ratio is ~1 (p5 .35); one octave below ~.03 (p95 .13)."""
    win = np.hanning(nfft); out = []
    for t in np.arange(t0, t1, .03):
        c = int(t * sr); a = c - nfft // 2
        if a < 0 or a + nfft > len(y): continue
        mag = np.abs(np.fft.rfft(y[a:a + nfft] * win)); peaks = []
        for h in range(1, k + 1):
            f = h * f_low; lo = int((f * .97) * nfft / sr); hi = int((f * 1.03) * nfft / sr) + 1
            peaks.append(mag[lo:hi].max() if hi > lo and hi < len(mag) else 0)
        out.append(sum(peaks[0::2]) / (sum(peaks[1::2]) + 1e-9))
    return float(np.median(out)) if out else np.nan

def midi_to_hz(m): return 440 * 2 ** ((m - 69) / 12)

def arbitrate(pkg, cache, variant='baseline', th=.2):
    """Per song: (1) note-level CREPE-vs-pYIN octave disputes, (2) neighbourhood octave outliers (what octave_fix would
    move), (3) sustained Viterbi-vs-argmax octave disagreements, each judged by odd_even(); plus (4) a scan of every note
    >= .3 s for a probable wrong octave. Threshold `th` on the odd/even ratio; .2 misjudges ~1 % of agreed notes."""
    import soundfile as sf, torch, torchcrepe
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8')); c = cache
    ct = np.arange(len(c['f0'])) * 160 / 16000; f0, pd = c['f0'], c['pd']
    if variant != 'baseline': ct, f0, pd, _ = decode_variant(c, variant, song['notes'])
    notes, fr = build(ct, f0, pd, c['P'], song['duration']); yy, sr = sf.read(pkg / 'vocals_44k.flac', dtype='float32', always_2d=True); y = yy.mean(1)
    P = c['P']; prob = np.interp(fr['ts'], P[:, 0], np.nan_to_num(P[:, 2], nan=0)); mp = fr['mp']
    r = {'package': pkg.name, 'variant': variant}
    cr = py = 0; lost = 0
    for n in notes:
        s, e = n['_i']; q = np.isfinite(mp[s:e]) & (prob[s:e] > .5)
        if q.sum() < 4: continue
        pm = float(np.median(mp[s:e][q])); dd = n['m'] - pm
        if abs(abs(dd) - 12) <= 1.0 or abs(abs(dd) - 24) <= 1.0:
            lo = min(n['m'], pm); lower_real = odd_even(y, sr, n['a'], n['b'], midi_to_hz(lo)) > th; crepe_right = (n['m'] == lo) == lower_real
            cr += crepe_right; py += not crepe_right; lost += crepe_right and not n['ok'] and n['b'] - n['a'] >= .4
    r.update(disputes=cr + py, crepe_right=cr, pyin_right=py, crepe_right_but_not_ok_ge400ms=lost)
    good = bad = 0
    for n0, n1 in zip(notes, fix_octaves(notes)):
        if not n1.get('octaveFixed'): continue
        lo = min(n0['m'], n1['m']); lower_real = odd_even(y, sr, n0['a'], n0['b'], midi_to_hz(lo)) > th; fix_right = (n1['m'] == lo) == lower_real; good += fix_right; bad += not fix_right
    r.update(outliers=good + bad, fix_right=good, fix_wrong=bad)
    act = c['act'].astype(np.float32); bins = act.argmax(0); conf = act.max(0)
    m_arg = hz_to_midi(10 * 2 ** (torchcrepe.convert.bins_to_cents(torch.from_numpy(bins)).numpy() / 1200)); m_vit = hz_to_midi(f0)
    d = np.abs(m_vit - m_arg); oc = ((np.abs(d - 12) <= 1.5) | (np.abs(d - 24) <= 1.5)) & (conf > .6) & (m_arg >= 36)
    vr = ar = frames_total = frames_lost = 0
    for a, b in runs(oc):
        if b - a < 10: continue
        lo = min(np.median(m_vit[a:b]), np.median(m_arg[a:b])); lower_real = odd_even(y, sr, a * .01, b * .01, midi_to_hz(lo)) > th
        v = (np.median(m_vit[a:b]) == lo) == lower_real; vr += v; ar += not v
        if not v: frames_total += b - a; frames_lost += int((pd[a:b] <= .45).sum())
    r.update(vit_vs_arg_runs=vr + ar, viterbi_right=vr, argmax_right=ar, frames_in_wrong_viterbi_runs=frames_total, of_them_below_periodicity_gate=frames_lost)
    scan = {'notes_ge300ms': 0, 'probably_octave_higher': 0, 'probably_octave_lower': 0}
    for n in notes:
        if n['b'] - n['a'] < .3: continue
        scan['notes_ge300ms'] += 1
        if odd_even(y, sr, n['a'], n['b'], midi_to_hz(n['m'])) < th: scan['probably_octave_higher'] += 1
        elif odd_even(y, sr, n['a'], n['b'], midi_to_hz(n['m'] - 12)) > th: scan['probably_octave_lower'] += 1
    r.update(scan); return {k: (int(v) if isinstance(v, (np.integer, np.bool_)) else v) for k, v in r.items()}

# ---------------------------------------------------------------- driver
def load_cache(cache_dir, pkg):
    f = Path(cache_dir) / (pkg.name + '.npz')
    return dict(np.load(f)) if f.exists() else None

def run_song(pkg, cache_dir, variant, with_stability):
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8')); duration = song['duration']
    row = {'package': pkg.name, 'duration_s': round(duration, 1)}
    if cache_dir is None: return {**row, **note_metrics(song['notes'], duration, song['points'])}
    c = load_cache(cache_dir, pkg)
    if c is None: return {**row, 'error': 'no cache'}
    P = c['P']; ct = np.arange(len(c['f0'])) * 160 / 16000; f0, pd = c['f0'], c['pd']; extra = {}
    if variant and variant != 'baseline':
        ct, f0, pd, rng = decode_variant(c, variant, song['notes']); extra['fmin_fmax'] = rng
    notes, fr = build(ct, f0, pd, P, duration, octave_fix=variant is not None and 'octave_fix' in variant)
    fr['pyin_prob'] = fr['ts'] * 0 + np.interp(fr['ts'], P[:, 0], np.nan_to_num(P[:, 2], nan=0))
    ship = song['notes']
    same = len(notes) == len(ship) and all(abs(x['a'] - y['a']) < 1e-6 and abs(x['b'] - y['b']) < 1e-6 and x['n'] == y['n'] for x, y in zip(notes, ship))
    b0 = set(round(x, 3) for n in ship for x in (n['a'], n['b'])); b1 = set(round(x, 3) for n in notes for x in (n['a'], n['b']))
    row.update({'variant': variant or 'baseline', **extra, 'rebuild_equals_shipped': same, 'shipped_notes': len(ship), 'boundaries_kept_vs_shipped_pct': round(100 * len(b0 & b1) / max(len(b0), 1), 1)})
    row.update(note_metrics(notes, duration)); row['candidate_pct'] = round(100 * fr['valid'].mean(), 1); row['comparable_pct'] = round(100 * fr['reliable'].sum() * HOP / duration, 1)
    row.update(frame_metrics(fr, notes))
    if with_stability: row['stability'] = stability(ct, f0, pd, P, duration, notes)
    return row

COLS_MAP = ['notes', 'ok_pct', 'comparable_pct', 'candidate_pct', 'note_med_dur_s', 'notes_under_150ms_pct', 'octave_jumps_adjacent', 'octave_outliers_nbhd', 'split_chains', 'boundary_hole_le2', 'boundary_hole_3_10', 'boundary_same_semitone']
COLS_FR = ['rebuild_equals_shipped', 'notes', 'comparable_pct', 'crepe_pyin_agree_50c_pct', 'crepe_pyin_octave_pct', 'notes_octave_vs_pyin', 'notes_octave_vs_pyin_crepe_lower', 'octave_outliers_nbhd', 'loud_frames_no_pitch_pct', 'lost_periodicity_le45_and_not_weak', 'lost_level_gate', 'lost_valid_run_lt5', 'valid_not_reliable']

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['map', 'frames', 'decode', 'gates', 'arbitrate']); ap.add_argument('package', nargs='+')
    ap.add_argument('--cache'); ap.add_argument('--variant', default='baseline'); ap.add_argument('--stability', action='store_true'); ap.add_argument('--json', action='store_true')
    a = ap.parse_args(); rows = []
    for p in a.package:
        pkg = Path(p).expanduser().resolve()
        if not (pkg / 'target.json').exists(): continue
        if a.mode == 'map': rows.append(run_song(pkg, None, None, False))
        else:
            if not a.cache: ap.error('--cache is required for frames/decode')
            if a.mode == 'arbitrate':
                rows.append(arbitrate(pkg, load_cache(a.cache, pkg), a.variant)); print(json.dumps(rows[-1], ensure_ascii=False) if a.json else ' '.join(f'{k}={v}' for k, v in rows[-1].items()), flush=True); continue
            if a.mode == 'gates':
                c = load_cache(a.cache, pkg); song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
                g = gates(np.arange(len(c['f0'])) * 160 / 16000, c['f0'], c['pd'], c['P'], song['duration']); rows.append({'package': pkg.name, 'gates': g})
                print(json.dumps(rows[-1], ensure_ascii=False) if a.json else '\n'.join(f"{pkg.name[:24]:<24} {k:<20} " + ' '.join(f'{kk}={vv}' for kk, vv in v.items()) for k, v in g.items()), flush=True); continue
            rows.append(run_song(pkg, a.cache, a.variant if a.mode == 'decode' else 'baseline', a.stability))
        print(json.dumps(rows[-1], ensure_ascii=False) if a.json else fmt(rows[-1], COLS_MAP if a.mode == 'map' else COLS_FR), flush=True)
    if not a.json and len(rows) > 1 and a.mode not in ('gates', 'arbitrate'): print(fmt(pooled(rows), COLS_MAP if a.mode == 'map' else COLS_FR))

def fmt(r, cols):
    return ' '.join([f"{r['package'][:24]:<24}"] + [f"{k.split('_')[0][:6]}={r.get(k)}" for k in cols if k in r])

def pooled(rows):
    out = {'package': 'ALL'}
    for k in rows[0]:
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)]
        if len(vals) == len(rows): out[k] = round(float(np.sum(vals) if k.endswith(('_frames', 'notes', 'chains', 'jumps_adjacent', 'sandwich', 'nbhd', 'le2', '3_10', 'semitone', 'gt200ms', 'pieces_in_chains', 'pyin', 'lower', 'lt8', 'lt5', 'reliable', 'valid', 'compared_to_pyin')) or k.startswith('lost') else np.median(vals)), 2)
    return out

if __name__ == '__main__':
    main()
