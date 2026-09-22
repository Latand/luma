#!/usr/bin/env python3
"""Label-free quality measurement of the target melody (docs/PITCH_ACCURACY.md).

Inputs per song: the shipped target.json and, for everything beyond `map`, a cache of the raw pYIN/CREPE frames made
by tools/pitch_frames.py (the pipeline deletes its own work/ files). Nothing here writes into a song package.

  pitch_quality.py map      songs/*                        metrics from target.json alone (uses points[] as the valid mask)
  pitch_quality.py package  --cache DIR songs/*            evaluate the notes/points a package actually ships (any pipeline
                                                           version), with the cache only for the pYIN/CREPE context: this
                                                           is the mode for comparing two prepared versions of a song
  pitch_quality.py frames   --cache DIR songs/*            rebuild the map from the cache with the shipped rules (a copy of
                                                           build_map) and add per-gate losses, boundary stability, truncation
  pitch_quality.py gates    --cache DIR songs/*            rebuild with one rule moved at a time: what each rule costs
  pitch_quality.py decode   --cache DIR --variant V songs/*  rebuild with another decoder / post-process
                                                           (V: redecode | no_dither | narrow | song_range | whole_song |
                                                           argmax | viterbi_norm | viterbi_octave | octave_fix)
  pitch_quality.py arbitrate --cache DIR [--variant V | --gate G | --shipped] songs/*
                                                           harmonic arbiter over octave disputes; --gate arbitrates the
                                                           notes a rule change promotes to ok; --shipped uses the package's notes
  --seed N   numpy seed for torchcrepe's ±20-cent dither (default 0: repeatable). --json prints JSON rows.

`frames`/`gates`/`decode` reconstruct notes with this file's copy of build_map(); they measure prototypes, never a
changed pipeline. `package` measures what a pipeline wrote. Every number is a proxy for accuracy; the doc says which."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, scipy.ndimage as ndi

HOP = .02
CENTS_OFFSET = 1997.3794084376191   # torchcrepe: cents = 20 * bin + offset

def runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int))); return list(zip(edges[::2], edges[1::2]))

def hz_to_midi(f):
    with np.errstate(divide='ignore', invalid='ignore'): return 69 + 12 * np.log2(np.asarray(f, dtype=float) / 440)

def midi_to_hz(m): return 440 * 2 ** ((np.asarray(m, dtype=float) - 69) / 12)

# ---------------------------------------------------------------- the map stage, copied from studio/prepare_song.py build_map()
# Same thresholds, filters and run rules, so the rebuilt notes equal the shipped ones up to the dither (see 4.3 of the doc);
# instrumented so every gate can be counted. Parameters exist only for the sensitivity and prototype runs.
def build(ct, f0, pd, P, duration, med_stable=11, med_run=5, split=.72, ok_ratio=.55, octave_fix=False,
          pd_strong=.45, db_strong=-43, min_run=5, pd_rel=.70, fill_holes=0, use_pyin=True):
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
    if fill_holes:   # prototype: close holes of at most `fill_holes` frames between two sung stretches
        for a, b in runs(~valid):
            if b - a <= fill_holes and a > 0 and b < len(valid): valid[a:b] = True
    pyin_ok = (np.isfinite(agree) & (agree < 50)) | (pdg >= .85) if use_pyin else np.ones(len(ts), bool)
    reliable = strong & (pdg >= pd_rel) & (db > -38) & pyin_ok
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
              'weak_raw': weak_raw, 'weak': weak, 'valid_raw': valid_raw, 'valid': valid, 'reliable': reliable, 'smooth': smooth,
              'pyin_prob': np.interp(ts, P[:, 0], np.nan_to_num(P[:, 2], nan=0))}
    return notes, frames

def fix_octaves(notes, window=.6, tol=1.5):
    """Octave-continuity post-process (prototype, measured harmful in the doc): a note whose centre is ~12 or ~24 semitones
    from the duration-weighted median of its neighbours within `window` s is moved by that many octaves. Any flag left by
    an earlier pass is cleared first, so counting the flags after a call measures this call only."""
    out = []
    for n in notes:
        d = dict(n); d.pop('octaveFixed', None); out.append(d)
    base = [dict(n) for n in out]
    for k, n in enumerate(out):
        nb = [x for j, x in enumerate(base) if j != k and x['a'] < n['b'] + window and x['b'] > n['a'] - window]
        if not nb: continue
        w = np.array([x['b'] - x['a'] for x in nb]); m = np.array([x['m'] for x in nb])
        order = np.argsort(m); cw = np.cumsum(w[order]); ref = float(m[order][np.searchsorted(cw, cw[-1] / 2)])
        d = n['m'] - ref
        for oct in (12, 24):
            if abs(abs(d) - oct) <= tol:
                shift = -np.sign(d) * oct; n['m'] = round(n['m'] + shift, 3); n['n'] = int(round(n['m'])); n['octaveFixed'] = int(shift); break
    return out

# ---------------------------------------------------------------- metrics on a note list
def note_index(notes, hop=HOP):
    """Frame index range of each note: build() records it; shipped notes get it from a/b (b = last frame start + hop)."""
    return [n['_i'] if '_i' in n else (int(round(n['a'] / hop)), int(round(n['b'] / hop))) for n in notes]

def note_metrics(notes, duration, valid=None, points=None):
    """`valid` (bool per frame on the HOP grid) classifies the gaps between notes by what the mask holds there; in `map`
    mode it comes from points[] (midi is null exactly where the frame is not valid)."""
    if valid is None and points is not None: valid = np.array([p[1] is not None for p in points])
    a = np.array([n['a'] for n in notes]); b = np.array([n['b'] for n in notes]); m = np.array([n['m'] for n in notes]); ok = np.array([n['ok'] for n in notes], bool)
    dur = b - a; gap = a[1:] - b[:-1]; dm = np.diff(m); adj = gap < .3
    oct_jump = adj & (np.abs(np.abs(dm) - 12) <= 1.0)
    sandwich = sum(1 for k in range(1, len(m) - 1) if abs(abs(m[k] - m[k - 1]) - 12) <= 1 and abs(abs(m[k] - m[k + 1]) - 12) <= 1 and abs(m[k - 1] - m[k + 1]) <= 2 and a[k] - b[k - 1] < .3 and a[k + 1] - b[k] < .3)
    outliers = sum(1 for n in fix_octaves(notes) if n.get('octaveFixed'))
    chains = []; cur = 1
    for i in range(1, len(notes)):
        if a[i] - b[i - 1] < 1e-3 and abs(m[i] - m[i - 1]) <= 1.0: cur += 1
        else: chains.append(cur); cur = 1
    chains.append(cur)
    # gap classes, read off the valid mask between the two notes
    cls = {'touch_same_semitone': 0, 'touch_new_semitone': 0, 'hole_1_2': 0, 'hole_3_10': 0, 'hole_gt10': 0, 'valid_gap_discarded': 0, 'mixed_gap_le10': 0, 'mixed_gap_gt10': 0}
    ix = note_index(notes)
    for i in range(1, len(notes)):
        e0 = ix[i - 1][1]; s1 = ix[i][0]; g = s1 - e0
        if g <= 0: cls['touch_same_semitone' if notes[i]['n'] == notes[i - 1]['n'] else 'touch_new_semitone'] += 1; continue
        if valid is None: cls['hole_1_2' if g <= 2 else 'hole_3_10' if g <= 10 else 'hole_gt10'] += 1; continue
        v = valid[e0:s1]
        if not v.any(): cls['hole_1_2' if g <= 2 else 'hole_3_10' if g <= 10 else 'hole_gt10'] += 1
        elif v.all(): cls['valid_gap_discarded'] += 1          # frames with pitch, but the note segment there was < 4 frames
        else: cls['mixed_gap_le10' if g <= 10 else 'mixed_gap_gt10'] += 1
    out = {'notes': len(notes), 'ok_notes': int(ok.sum()), 'ok_pct': round(100 * ok.mean(), 1) if len(ok) else 0,
           'note_med_dur_s': round(float(np.median(dur)), 3), 'notes_under_150ms_pct': round(100 * float((dur < .15).mean()), 1),
           'sustained_notes_ge600ms': int((dur >= .6).sum()), 'octave_jumps_adjacent': int(oct_jump.sum()), 'octave_sandwich': int(sandwich), 'octave_outliers_nbhd': int(outliers),
           'split_chains': int((np.array(chains) >= 2).sum()), 'pieces_in_chains': int(sum(c for c in chains if c >= 2)), **{'gap_' + k: v for k, v in cls.items()},
           'midi_p5': round(float(np.percentile(m, 5)), 1), 'midi_p50': round(float(np.percentile(m, 50)), 1), 'midi_p95': round(float(np.percentile(m, 95)), 1)}
    if points is not None:
        rel = np.array([p[3] for p in points], bool)
        out['candidate_pct'] = round(100 * valid.mean(), 1); out['comparable_pct'] = round(100 * rel.sum() * HOP / duration, 1)
    return out

# ---------------------------------------------------------------- frame-level metrics (need the cache)
def disagreement(fr, notes):
    """CREPE vs pYIN per frame and per note; `fr` needs midi, mp, pdg, db, pyin_prob."""
    midi, mp, pdg, db = fr['midi'], fr['mp'], fr['pdg'], fr['db']
    both = np.isfinite(midi) & np.isfinite(mp) & (pdg > .45) & (db > -43); d = np.abs(midi - mp)
    oct = both & ((np.abs(d - 12) <= 1.0) | (np.abs(d - 24) <= 1.0)); agree = both & (d <= .5)
    note_oct = note_cmp = crepe_low = 0
    for n, (s, e) in zip(notes, note_index(notes)):
        q = np.isfinite(mp[s:e]) & (fr['pyin_prob'][s:e] > .5)
        if q.sum() >= 4:
            note_cmp += 1; dd = abs(n['m'] - float(np.median(mp[s:e][q])))
            if abs(dd - 12) <= 1.0 or abs(dd - 24) <= 1.0: note_oct += 1; crepe_low += n['m'] < np.median(mp[s:e][q])
    return {'frames_both_confident': int(both.sum()), 'crepe_pyin_agree_50c_pct': round(100 * agree.sum() / max(both.sum(), 1), 1),
            'crepe_pyin_octave_pct': round(100 * oct.sum() / max(both.sum(), 1), 2), 'crepe_pyin_octave_frames': int(oct.sum()),
            'notes_compared_to_pyin': note_cmp, 'notes_octave_vs_pyin': note_oct, 'notes_octave_vs_pyin_crepe_lower': int(crepe_low)}

def losses(fr):
    """Where the loud frames (> -30 dBFS) without a valid pitch went. The classes partition `loud & ~valid` exactly:
    a frame is counted once, under the first rule that stopped it."""
    loud = fr['db'] > -30; lost = loud & ~fr['valid']; inr, strong, weak_raw, weak, valid_raw = fr['inrange'], fr['strong'], fr['weak_raw'], fr['weak'], fr['valid_raw']
    out = {'loud_frames': int(loud.sum()), 'loud_frames_no_pitch': int(lost.sum()), 'loud_frames_no_pitch_pct': round(100 * lost.sum() / max(loud.sum(), 1), 1),
           'lost_out_of_range': int((lost & ~inr).sum()),
           'lost_periodicity_never_candidate': int((lost & inr & ~strong & ~weak_raw & (fr['pdg'] <= .45)).sum()),
           'lost_level_never_candidate': int((lost & inr & ~strong & ~weak_raw & (fr['pdg'] > .45)).sum()),
           'lost_draft_run_lt8': int((lost & weak_raw & ~strong & ~weak).sum()),
           'lost_valid_run_lt5': int((lost & valid_raw & ~fr['valid']).sum()),
           'valid': int(fr['valid'].sum()), 'reliable': int(fr['reliable'].sum()), 'valid_not_reliable': int((fr['valid'] & ~fr['reliable']).sum())}
    out['lost_filled_hole'] = out['loud_frames_no_pitch'] - sum(out[k] for k in out if k.startswith('lost_'))   # 0 unless fill_holes reopened nothing
    return out

def truncation(fr):
    """Does the voice go on after a valid run ends? Loud frames (> -30 dBFS) directly after each run end, up to the next
    valid frame or 10 frames: the tail the note lost."""
    loud = fr['db'] > -30; tails = []
    for a, b in runs(fr['valid']):
        k = 0
        while b + k < len(loud) and k < 10 and loud[b + k] and not fr['valid'][b + k]: k += 1
        tails.append(k)
    t = np.array(tails)
    return {'runs': len(t), 'run_end_loud_tail_med_frames': float(np.median(t)) if len(t) else 0, 'runs_with_loud_tail_ge2_pct': round(100 * float((t >= 2).mean()), 1) if len(t) else 0,
            'loud_tail_frames_total': int(t.sum())}

GATES = [('baseline', {}), ('pd_strong .45->.35', {'pd_strong': .35}), ('pd_strong .45->.55', {'pd_strong': .55}), ('db_strong -43->-48', {'db_strong': -48}),
         ('min_run 5->3', {'min_run': 3}), ('min_run 5->8', {'min_run': 8}), ('fill_holes<=2', {'fill_holes': 2}), ('fill_holes<=5', {'fill_holes': 5}),
         ('pd_rel .70->.60', {'pd_rel': .60}), ('no_pyin_clause', {'use_pyin': False}), ('ok_ratio .55->.40', {'ok_ratio': .40}), ('split .72->1.0', {'split': 1.0}), ('med_run 5->9', {'med_run': 9})]
GATE_KW = dict(GATES)

def gates(ct, f0, pd, P, duration):
    out = {}
    for name, kw in GATES:
        ns, fr = build(ct, f0, pd, P, duration, **kw); nm = note_metrics(ns, duration, fr['valid'])
        out[name] = {'notes': len(ns), 'ok_notes': nm['ok_notes'], 'candidate_s': round(float(fr['valid'].sum() * HOP), 1), 'comparable_s': round(float(fr['reliable'].sum() * HOP), 1),
                     'sustained_notes_ge600ms': nm['sustained_notes_ge600ms'], 'notes_under_150ms': int(sum(1 for n in ns if n['b'] - n['a'] < .15)),
                     'octave_jumps_adjacent': nm['octave_jumps_adjacent'], 'octave_outliers_nbhd': nm['octave_outliers_nbhd'], 'split_chains': nm['split_chains']}
    return out

def stability(ct, f0, pd, P, duration, base_notes):
    def bounds(ns): return np.array(sorted(set([n['a'] for n in ns] + [n['b'] for n in ns])))
    b0 = bounds(base_notes); out = {}
    for name, kw in [('med11->9', {'med_stable': 9}), ('med11->13', {'med_stable': 13}), ('run5->3', {'med_run': 3}), ('run5->7', {'med_run': 7}), ('split.72->.6', {'split': .6}), ('split.72->.85', {'split': .85})]:
        ns, _ = build(ct, f0, pd, P, duration, **kw); b1 = bounds(ns)
        out[name] = {'notes': len(ns), 'boundaries_kept_pct': round(100 * float(np.isin(np.round(b0, 3), np.round(b1, 3)).mean()) if len(b0) else 100.0, 1)}
    return out

def boundaries_kept(ref_notes, notes):
    b0 = set(round(x, 3) for n in ref_notes for x in (n['a'], n['b'])); b1 = set(round(x, 3) for n in notes for x in (n['a'], n['b']))
    return round(100 * len(b0 & b1) / max(len(b0), 1), 1)

# ---------------------------------------------------------------- decoders (prototypes)
def bins_to_hz_no_dither(bins):
    import torch
    return 10 * 2 ** ((20 * bins.to(torch.float) + CENTS_OFFSET) / 1200)

def viterbi_no_dither(logits):
    """The pipeline's decoder without torchcrepe's ±20-cent triangular dither on the decoded bins."""
    import torchcrepe
    bins, _ = torchcrepe.decode.viterbi(logits); return bins, bins_to_hz_no_dither(bins)

def viterbi_normalised(logits):
    """torchcrepe's viterbi() runs softmax over sigmoid outputs (0..1), which flattens the emissions (peak ~.007 against
    .0028 uniform). This normalises the sigmoid outputs per frame instead; same transition matrix."""
    import torch, torchcrepe, librosa
    tv = torchcrepe.decode.viterbi
    if not hasattr(tv, 'transition'):
        xx, yy = np.meshgrid(range(360), range(360)); tr = np.maximum(12 - abs(xx - yy), 0); tv.transition = tr / tr.sum(axis=1, keepdims=True)
    probs = logits.clone(); probs[~torch.isfinite(probs)] = 0; probs = probs.clamp_min(1e-6); probs = probs / probs.sum(dim=1, keepdim=True)
    bins = torch.tensor(np.array([librosa.sequence.viterbi(seq, tv.transition).astype(np.int64) for seq in probs.cpu().numpy()]), device=logits.device)
    return bins, torchcrepe.convert.bins_to_frequency(bins)

def viterbi_octave(logits, eps=.02):
    """The pipeline's decoder plus a small probability of jumping exactly one octave (60 bins) in one frame."""
    import torch, torchcrepe, librosa
    if not hasattr(viterbi_octave, 'transition'):
        xx, yy = np.meshgrid(range(360), range(360)); tr = np.maximum(12 - abs(xx - yy), 0).astype(float)
        tr[abs(xx - yy) == 60] = 12 * eps; viterbi_octave.transition = tr / tr.sum(axis=1, keepdims=True)
    with torch.no_grad(): probs = torch.nn.functional.softmax(logits, dim=1)
    bins = torch.tensor(np.array([librosa.sequence.viterbi(seq, viterbi_octave.transition).astype(np.int64) for seq in probs.cpu().numpy()]), device=logits.device)
    return bins, torchcrepe.convert.bins_to_frequency(bins)

def decode_variant(cache, variant, song_notes, seed=0):
    """(ct, f0, pd, (fmin, fmax)) for a variant of stage [4/8] from the cached activations. `redecode` is the pipeline's
    own decoder run again (dither drawn from `seed`)."""
    import torch, torchcrepe
    if seed is not None: np.random.seed(seed)
    act = torch.from_numpy(cache['act'].astype(np.float32))[None]
    fmin, fmax = 50., 1500.
    if variant.startswith('narrow'): fmin, fmax = 65.4, 1046.5
    if variant.startswith('song_range'):
        m = np.array([n['m'] for n in song_notes if n['ok']]); lo, hi = np.percentile(m, 2) - 3, np.percentile(m, 98) + 3
        fmin, fmax = float(midi_to_hz(lo)), float(midi_to_hz(hi))
    decoder = {'argmax': torchcrepe.decode.argmax, 'viterbi_norm': viterbi_normalised, 'viterbi_octave': viterbi_octave, 'no_dither': viterbi_no_dither}.get(variant.split('+')[0], torchcrepe.decode.viterbi)
    T = act.shape[2]; step = T if 'whole_song' in variant else 1024; f0s, pds = [], []
    with torch.no_grad():
        for s in range(0, T, step):
            f, p = torchcrepe.postprocess(act[:, :, s:s + step].clone(), fmin, fmax, decoder, False, True); f0s.append(f); pds.append(p)
    f0 = torchcrepe.filter.mean(torch.cat(f0s, 1), 3)[0].numpy(); pd = torchcrepe.filter.median(torch.cat(pds, 1), 3)[0].numpy()
    return np.arange(len(f0)) * 160 / 16000, f0, pd, (round(fmin, 1), round(fmax, 1))

# ---------------------------------------------------------------- harmonic arbiter (heuristic; see doc 4.2 for what it can and cannot tell)
def odd_even(y, sr, t0, t1, f_low, nfft=8192, k=8):
    """On the 44.1 kHz stem: peak magnitude at the ODD harmonics of f_low (1,3,5,7x) over its EVEN harmonics (2,4,6,8x,
    the harmonics of the candidate one octave up), median over 30 ms hops of [t0, t1). Near zero means f_low is a
    sub-harmonic artefact and the real pitch is an octave higher. A heuristic, calibrated only on notes where CREPE and
    pYIN agree; it has no independent labels behind it."""
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

def judge(y, sr, n, th):
    """0 = the note's own octave is the plausible one, +1 = real pitch probably an octave HIGHER, -1 = probably LOWER."""
    if odd_even(y, sr, n['a'], n['b'], float(midi_to_hz(n['m']))) < th: return 1
    if odd_even(y, sr, n['a'], n['b'], float(midi_to_hz(n['m'] - 12))) > th: return -1
    return 0

def arbitrate(pkg, cache, variant='baseline', gate=None, shipped=False, th=.2, seed=0):
    """Per song: (1) note-level CREPE-vs-pYIN octave disputes, (2) neighbourhood outliers (what octave_fix would move),
    (3) sustained Viterbi-vs-argmax octave disagreements, (4) a scan of every note >= .3 s; with --gate also the notes
    that rule change promotes to ok. All verdicts come from odd_even(): heuristic decisions, not labels."""
    import soundfile as sf, torch, torchcrepe
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8')); c = cache
    ct = np.arange(len(c['f0'])) * 160 / 16000; f0, pd = c['f0'], c['pd']
    if variant != 'baseline': ct, f0, pd, _ = decode_variant(c, variant, song['notes'], seed)
    notes, fr = build(ct, f0, pd, c['P'], song['duration'])
    if shipped:
        notes = [dict(n) for n in song['notes']]; fr = package_frames(song, c['P'])
    yy, sr = sf.read(pkg / 'vocals_44k.flac', dtype='float32', always_2d=True); y = yy.mean(1); mp = fr['mp']
    r = {'package': pkg.name, 'variant': 'shipped' if shipped else variant, 'gate': gate}
    cr = py = lost = 0
    for n, (s, e) in zip(notes, note_index(notes)):
        q = np.isfinite(mp[s:e]) & (fr['pyin_prob'][s:e] > .5)
        if q.sum() < 4: continue
        pm = float(np.median(mp[s:e][q])); dd = n['m'] - pm
        if abs(abs(dd) - 12) <= 1.0 or abs(abs(dd) - 24) <= 1.0:
            lo = min(n['m'], pm); lower_real = odd_even(y, sr, n['a'], n['b'], float(midi_to_hz(lo))) > th; crepe_right = (n['m'] == lo) == lower_real
            cr += crepe_right; py += not crepe_right; lost += crepe_right and not n['ok'] and n['b'] - n['a'] >= .4
    r.update(disputes=cr + py, crepe_right=cr, pyin_right=py, crepe_right_but_not_ok_ge400ms=lost)
    good = bad = 0
    for n0, n1 in zip(notes, fix_octaves(notes)):
        if not n1.get('octaveFixed'): continue
        lo = min(n0['m'], n1['m']); lower_real = odd_even(y, sr, n0['a'], n0['b'], float(midi_to_hz(lo))) > th; fix_right = (n1['m'] == lo) == lower_real; good += fix_right; bad += not fix_right
    r.update(outliers=good + bad, fix_right=good, fix_wrong=bad)
    if not shipped:
        act = c['act'].astype(np.float32); bins = act.argmax(0); conf = act.max(0)
        m_arg = hz_to_midi(10 * 2 ** ((20 * bins + CENTS_OFFSET) / 1200)); m_vit = hz_to_midi(f0)
        d = np.abs(m_vit - m_arg); oc = ((np.abs(d - 12) <= 1.5) | (np.abs(d - 24) <= 1.5)) & (conf > .6) & (m_arg >= 36)
        vr = ar = frames_total = frames_lost = 0
        for a, b in runs(oc):
            if b - a < 10: continue
            lo = min(np.median(m_vit[a:b]), np.median(m_arg[a:b])); lower_real = odd_even(y, sr, a * .01, b * .01, float(midi_to_hz(lo))) > th
            v = (np.median(m_vit[a:b]) == lo) == lower_real; vr += v; ar += not v
            if not v: frames_total += b - a; frames_lost += int((pd[a:b] <= .45).sum())
        r.update(vit_vs_arg_runs=vr + ar, viterbi_right=vr, argmax_right=ar, frames_in_wrong_viterbi_runs=frames_total, of_them_below_periodicity_gate=frames_lost)
    scan = {'notes_ge300ms': 0, 'probably_octave_higher': 0, 'probably_octave_lower': 0, 'ok_ge500ms': 0, 'ok_ge500ms_probably_higher': 0, 'ok_ge500ms_probably_lower': 0}
    for n in notes:
        if n['b'] - n['a'] < .3: continue
        j = judge(y, sr, n, th); scan['notes_ge300ms'] += 1; scan['probably_octave_higher'] += j == 1; scan['probably_octave_lower'] += j == -1
        if n['ok'] and n['b'] - n['a'] >= .5: scan['ok_ge500ms'] += 1; scan['ok_ge500ms_probably_higher'] += j == 1; scan['ok_ge500ms_probably_lower'] += j == -1
    r.update(scan)
    if gate:
        ns2, _ = build(ct, f0, pd, c['P'], song['duration'], **GATE_KW[gate]); base_ok = {(n['a'], n['b']): n['ok'] for n in notes}
        promoted = [n for n in ns2 if n['ok'] and not base_ok.get((n['a'], n['b']), True)]
        flagged = sum(1 for n in promoted if judge(y, sr, n, th) != 0); sust = sum(1 for n in promoted if n['b'] - n['a'] >= .4)
        r.update(gate_promoted=len(promoted), gate_promoted_ge400ms=sust, gate_promoted_flagged_octave=flagged, gate_promoted_flagged_ge400ms=sum(1 for n in promoted if n['b'] - n['a'] >= .4 and judge(y, sr, n, th) != 0))
    return {k: (int(v) if isinstance(v, (np.integer, np.bool_)) else v) for k, v in r.items()}

# ---------------------------------------------------------------- evaluating what a package ships
def package_frames(song, P):
    """Frame context for a package's own points[]: midi/periodicity/valid/reliable from the package, pYIN and level from
    the cache. No gate masks: the candidate pipeline's rules are not known here."""
    pts = song['points']; ts = np.array([p[0] for p in pts]); midi = np.array([p[1] if p[1] is not None else np.nan for p in pts]); pdg = np.array([p[2] for p in pts], float)
    valid = np.isfinite(midi); reliable = np.array([p[3] for p in pts], bool)
    def nearest(src_t, vals):
        ii = np.clip(np.searchsorted(src_t, ts), 1, len(src_t) - 1); ii -= abs(src_t[ii - 1] - ts) < abs(src_t[ii] - ts); return vals[ii]
    mp = hz_to_midi(nearest(P[:, 0], P[:, 1])); rms = nearest(P[:, 0], P[:, 3])
    with np.errstate(divide='ignore', invalid='ignore'): db = 20 * np.log10(rms + 1e-12)
    return {'ts': ts, 'midi': midi, 'mp': mp, 'pdg': pdg, 'db': db, 'valid': valid, 'reliable': reliable, 'pyin_prob': np.interp(ts, P[:, 0], np.nan_to_num(P[:, 2], nan=0))}

def run_package(pkg, cache_dir):
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8')); c = load_cache(cache_dir, pkg)
    if c is None: return {'package': pkg.name, 'error': 'no cache'}
    fr = package_frames(song, c['P']); notes = song['notes']
    row = {'package': pkg.name, 'mode': 'package', 'duration_s': round(song['duration'], 1), 'map_id': song.get('id'), **note_metrics(notes, song['duration'], fr['valid'], song['points'])}
    row.update(disagreement(fr, notes)); loud = fr['db'] > -30
    row['loud_frames'] = int(loud.sum()); row['loud_frames_no_pitch'] = int((loud & ~fr['valid']).sum()); row['loud_frames_no_pitch_pct'] = round(100 * row['loud_frames_no_pitch'] / max(row['loud_frames'], 1), 1)
    row.update(truncation(fr)); return row

# ---------------------------------------------------------------- driver
def load_cache(cache_dir, pkg):
    f = Path(cache_dir) / (pkg.name + '.npz')
    return dict(np.load(f)) if f.exists() else None

def run_song(pkg, cache_dir, variant, with_stability, seed=0):
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8')); duration = song['duration']
    row = {'package': pkg.name, 'duration_s': round(duration, 1)}
    if cache_dir is None: return {**row, 'mode': 'map', **note_metrics(song['notes'], duration, points=song['points'])}
    c = load_cache(cache_dir, pkg)
    if c is None: return {**row, 'error': 'no cache'}
    P = c['P']; ct = np.arange(len(c['f0'])) * 160 / 16000; f0, pd = c['f0'], c['pd']; extra = {}
    if variant and variant != 'baseline':
        ct, f0, pd, rng = decode_variant(c, variant, song['notes'], seed); extra['fmin_fmax'] = rng
    notes, fr = build(ct, f0, pd, P, duration, octave_fix=variant is not None and 'octave_fix' in variant)
    row.update({'mode': 'rebuild', 'variant': variant or 'baseline', 'seed': seed, **extra, 'shipped_notes': len(song['notes']), 'boundaries_kept_vs_shipped_pct': boundaries_kept(song['notes'], notes)})
    row.update(note_metrics(notes, duration, fr['valid'])); row['candidate_pct'] = round(100 * fr['valid'].mean(), 1); row['comparable_pct'] = round(100 * fr['reliable'].sum() * HOP / duration, 1)
    row.update(disagreement(fr, notes)); row.update(losses(fr)); row.update(truncation(fr))
    if with_stability: row['stability'] = stability(ct, f0, pd, P, duration, notes)
    return row

COLS = ['notes', 'ok_pct', 'comparable_pct', 'candidate_pct', 'note_med_dur_s', 'notes_under_150ms_pct', 'sustained_notes_ge600ms', 'octave_jumps_adjacent', 'octave_outliers_nbhd', 'split_chains',
        'gap_hole_1_2', 'gap_hole_3_10', 'gap_valid_gap_discarded', 'gap_mixed_gap_le10', 'gap_touch_same_semitone', 'gap_touch_new_semitone', 'boundaries_kept_vs_shipped_pct',
        'crepe_pyin_agree_50c_pct', 'crepe_pyin_octave_pct', 'notes_octave_vs_pyin', 'loud_frames_no_pitch_pct', 'lost_periodicity_never_candidate', 'lost_draft_run_lt8', 'lost_valid_run_lt5', 'valid_not_reliable', 'runs_with_loud_tail_ge2_pct']

def fmt(r): return ' '.join([f"{r['package'][:24]:<24}"] + [f"{k}={r[k]}" for k in COLS if k in r])

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['map', 'package', 'frames', 'decode', 'gates', 'arbitrate']); ap.add_argument('package', nargs='+')
    ap.add_argument('--cache'); ap.add_argument('--variant', default='baseline'); ap.add_argument('--gate'); ap.add_argument('--shipped', action='store_true')
    ap.add_argument('--stability', action='store_true'); ap.add_argument('--seed', type=int, default=0); ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.mode != 'map' and not a.cache: ap.error('--cache is required for every mode except map')
    for p in a.package:
        pkg = Path(p).expanduser().resolve()
        if not (pkg / 'target.json').exists(): continue
        if a.mode == 'map': r = run_song(pkg, None, None, False)
        elif a.mode == 'package': r = run_package(pkg, a.cache)
        elif a.mode == 'arbitrate': r = arbitrate(pkg, load_cache(a.cache, pkg), a.variant, a.gate, a.shipped, seed=a.seed)
        elif a.mode == 'gates':
            c = load_cache(a.cache, pkg); song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
            r = {'package': pkg.name, 'gates': gates(np.arange(len(c['f0'])) * 160 / 16000, c['f0'], c['pd'], c['P'], song['duration'])}
            print(json.dumps(r, ensure_ascii=False) if a.json else '\n'.join(f"{pkg.name[:24]:<24} {k:<20} " + ' '.join(f'{kk}={vv}' for kk, vv in v.items()) for k, v in r['gates'].items()), flush=True); continue
        else: r = run_song(pkg, a.cache, a.variant if a.mode == 'decode' else 'baseline', a.stability, a.seed)
        print(json.dumps(r, ensure_ascii=False) if a.json else (fmt(r) if 'notes' in r else json.dumps(r, ensure_ascii=False)), flush=True)

if __name__ == '__main__':
    main()
