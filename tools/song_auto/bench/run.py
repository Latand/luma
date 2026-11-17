"""Run one candidate, with one model resident, into a fresh private directory.

python -m tools.song_auto.bench.run PACKAGE CANDIDATE --seed-target BEFORE/target.json --scratch SCRATCH
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from .score import matches, validate, words

ROOT = Path(__file__).resolve().parents[3]
QA = ROOT / 'tools/song_qa'
CANDIDATES = ('baseline', 'mms', 'wav2vec2', 'sofa', 'fcpe', 'penn', 'synced-even')


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def baseline(target):
    return dict(schema='song-auto-bench.v1', duration=target['duration'], hop=target['hop'],
                words=[dict(w=w['w'], a=w['a'], b=w['b'], confidence=w.get('c', 1)) for w in words(target)],
                pitch=[dict(t=p[0], hz=440*2**((p[1]-69)/12) if p[1] is not None else None,
                            voiced=p[1] is not None, confidence=p[2]) for p in target['points']])


def seed_windows(lyrics, seed, duration):
    """Use text/order plus BEFORE clocks only; corrected word times are ignored.

    Missing seed words receive interpolated coarse clocks. Windows are split at
    lyric row boundaries and capped by refusal, never by cutting away words.
    """
    import numpy as np
    flat = [w for line in lyrics for w in line['words']]
    old = words(seed); mapping = matches(flat, old)
    if not mapping: raise ValueError('no seed text matches')
    anchors = sorted(mapping)
    clocks = np.interp(np.arange(len(flat)), anchors, [old[mapping[i]]['a'] for i in anchors])
    offset = 0; result = []
    for line in lyrics:
        n = len(line['words'])
        if not n: raise ValueError('empty lyric row')
        last = offset+n-1
        next_clock = clocks[last+1] if last+1 < len(flat) else min(duration, clocks[last]+4)
        end = max(min(next_clock+1, clocks[last]+4), clocks[last]+2.5)
        a, b = max(0., float(clocks[offset])-1.5), min(duration, float(end))
        if not 0 < b-a <= 30: raise ValueError('seed window outside 30-second budget')
        result.append((a, b)); offset += n
    return result


def audio(package, sr):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    y, source_sr = sf.read(package/'vocals_44k.flac', dtype='float32', always_2d=True)
    y = y.mean(axis=1)
    divisor = __import__('math').gcd(sr, source_sr)
    return resample_poly(y, sr//divisor, source_sr//divisor).astype(np.float32)


def align(package, lyrics, seed, candidate, device, synced_plan=None):
    import numpy as np
    import torch
    import torchaudio
    sys.path.insert(0, str(QA))
    from fa_align import model_word_owners, norm as fa_norm, sheet_hints
    # Validate all tokens before downloading/loading anything.
    if synced_plan is not None:
        lyrics = [dict(words=row['words']) for row in synced_plan]
    ownership = [model_word_owners(' '.join(w['w'] for w in line['words']), i) for i, line in enumerate(lyrics)]
    windows = ([(row['lo'], row['hi']) for row in synced_plan] if synced_plan is not None
               else seed_windows(lyrics, seed, seed['duration']))
    y = audio(package, 16000)
    bundle = torchaudio.pipelines.MMS_FA if candidate == 'mms' else torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    model = (bundle.get_model(with_star=True) if candidate == 'mms' else bundle.get_model()).to(device).eval()
    labels = bundle.get_dict(star='*') if candidate == 'mms' else {s: i for i, s in enumerate(bundle.get_labels())}
    proposals = []
    for i, ((a, b), owners) in enumerate(zip(windows, ownership)):
        ids = [labels['*']] if candidate == 'mms' else []
        spans = []
        for owner in owners:
            if ids and candidate != 'mms': ids.append(labels['|'])
            token = fa_norm(owner['w'])
            encoded = [labels[c if candidate == 'mms' else c.upper()] for c in token]
            spans.append((len(ids), len(ids)+len(encoded))); ids.extend(encoded)
        if candidate == 'mms': ids.append(labels['*'])
        lo, hi = int(a*16000), int(b*16000)
        segment = torch.from_numpy(y[lo:hi].copy())
        segment = segment/(segment.abs().max()+1e-6)*.7
        with torch.inference_mode():
            emission, _ = model(segment[None].to(device))
            # MMS already returns log probabilities with a zero-score wildcard.
            # Renormalizing that extended vocabulary halves every letter score.
            emission = emission.cpu()
            if candidate != 'mms':
                emission = emission.log_softmax(-1)
            alignment, scores = torchaudio.functional.forced_align(emission, torch.tensor([ids]), blank=0)
        runs = torchaudio.functional.merge_tokens(alignment[0], scores[0].exp())
        if len(runs) != len(ids): raise ValueError('CTC token count differs')
        ratio = (hi-lo)/16000/emission.shape[1]
        row = dict(line=i, words=[])
        for owner, (s, e) in zip(owners, spans):
            part = runs[s:e]
            row['words'].append(dict(**owner, a=lo/16000+part[0].start*ratio,
                                     b=lo/16000+part[-1].end*ratio,
                                     score=float(np.mean([p.score for p in part]))))
        proposals.append(row)
    hints = sheet_hints(lyrics, proposals)
    result = []
    for i, line in enumerate(lyrics):
        for j, word in enumerate(line['words']):
            a, b = hints[i, j]
            group = [w for w in proposals[i]['words'] if w['target_token'] == j]
            result.append(dict(w=word['w'], a=a, b=b, confidence=min(w['score'] for w in group)))
    # Keep crossing proposals in lyric order so the scorer can measure them.
    return result, dict(windows=windows, model=str(bundle._path),
                        anchor_source='synced' if synced_plan is not None else 'stored')


def sofa_row(row, owners, expected, aligned, intervals, confidence, offset):
    if list(aligned) != expected or len(intervals) != len(owners):
        raise ValueError('SOFA word ownership differs')
    return dict(line=row, words=[dict(**owner, a=offset+float(span[0]), b=offset+float(span[1]),
                                     score=float(confidence)) for owner,span in zip(owners,intervals)])


def sofa_align(package, lyrics, seed, device, source, checkpoint, dictionary, work):
    """Use upstream inference and project token ownership; never drop OOV words."""
    import torch
    import soundfile as sf
    sys.path.insert(0, str(QA))
    from fa_align import model_word_owners, norm as fa_norm, sheet_hints
    sys.path.insert(0, str(source))
    from modules.g2p.dictionary_g2p import DictionaryG2P
    import modules.task.forced_alignment as upstream
    from modules.task.forced_alignment import LitForcedAlignmentTask
    from modules.utils.get_melspec import MelSpecExtractor
    # Upstream torchaudio.load now requires an optional decoder. The window WAVs
    # are already mono at the model's rate; soundfile preserves those samples.
    def load_window(path, device, sample_rate):
        waveform, sr = sf.read(path, dtype='float32')
        if sr != sample_rate or waveform.ndim != 1: raise ValueError('invalid SOFA window audio')
        return torch.from_numpy(waveform).to(device)
    upstream.load_wav = load_window
    g2p = DictionaryG2P(dictionary=str(dictionary))
    ownership = [model_word_owners(' '.join(w['w'] for w in line['words']), i) for i, line in enumerate(lyrics)]
    encoded = []
    for owners in ownership:
        tokens = [fa_norm(o['w']) for o in owners]
        if any(t not in g2p.dictionary for t in tokens): raise ValueError('SOFA dictionary lacks a target token')
        encoded.append(g2p(' '.join(tokens)))
    model = LitForcedAlignmentTask.load_from_checkpoint(str(checkpoint), map_location='cpu', weights_only=False).to(device).eval()
    model.get_melspec = MelSpecExtractor(**model.melspec_config, device=device)
    model.set_inference_mode('force'); model.on_predict_start()
    windows = seed_windows(lyrics, seed, seed['duration'])
    sr = model.melspec_config['sample_rate']; y = audio(package, sr)
    proposals = []
    for i, ((a, b), owners, data) in enumerate(zip(windows, ownership, encoded)):
        wave = work/f'row-{i:03d}.wav'
        sf.write(wave, y[int(a*sr):int(b*sr)], sr, subtype='FLOAT')
        with torch.inference_mode(): result = model.predict_step((wave, *data), i)
        _, _, confidence, _, _, aligned_words, intervals = result
        proposals.append(sofa_row(i,owners,data[1],aligned_words,intervals,confidence,a))
    hints = sheet_hints(lyrics, proposals)
    return [dict(w=w['w'], a=hints[i,j][0], b=hints[i,j][1], confidence=proposals[i]['words'][0]['score'])
            for i, line in enumerate(lyrics) for j, w in enumerate(line['words'])], dict(windows=windows)


def pitch(package, candidate, device, duration, checkpoint=None):
    import numpy as np
    import torch
    sr = 16000 if candidate == 'fcpe' else 8000
    y = audio(package, sr)
    if candidate == 'fcpe':
        import torchfcpe
        model = torchfcpe.spawn_bundled_infer_model(device=device)
        hop = model.get_hop_size()/model.get_model_sr()
        settings = dict(threshold=.006, decoder='local_argmax', context_s=1, window_s=20)
    else:
        import penn
        hop = .01
        settings = dict(threshold=.065, decoder='viterbi', context_s=1, window_s=20)
    result = []
    # 20 s owned intervals with 1 s context; retain native model clocks.
    for start in np.arange(0, duration, 20):
        lo = int(max(0, start-1)*sr); hi = min(len(y), int((start+21)*sr))
        segment = torch.from_numpy(y[lo:hi].copy())[None].to(device)
        with torch.inference_mode():
            if candidate == 'fcpe':
                f = model.infer(segment[..., None], sr=sr, threshold=.006, interp_uv=False).flatten().cpu().numpy()
                q = (f > 0).astype(float)  # API returns a decision, no calibrated probability
            else:
                f, q = penn.from_audio(segment.cpu(), sr, hopsize=hop, center='zero', decoder='viterbi',
                                       checkpoint=checkpoint, interp_unvoiced_at=None, batch_size=512,
                                       gpu=0 if device == 'cuda' else None)
                f, q = f.flatten().cpu().numpy(), q.flatten().cpu().numpy()
        for j, (hz, confidence) in enumerate(zip(f, q)):
            t = lo/sr+j*hop
            if t < start-1e-7 or t >= min(start+20, duration)-1e-7: continue
            voiced = bool(np.isfinite(hz) and hz > 0 and confidence >= (0.5 if candidate == 'fcpe' else .065))
            result.append(dict(t=round(t, 8), hz=float(hz) if voiced else None,
                               voiced=voiced, confidence=float(confidence)))
    return result, hop, settings


def safe_scratch(package, seed_path, scratch):
    package, seed_path, scratch = package.resolve(), seed_path.resolve(), scratch.resolve()
    for source in (package, seed_path.parent, ROOT, Path(sys.prefix).resolve()):
        if scratch == source or source in scratch.parents or scratch in source.parents:
            raise ValueError('scratch/cache must be disjoint from inputs, repository and Python environment')
    return scratch


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package', type=Path); ap.add_argument('candidate', choices=CANDIDATES)
    ap.add_argument('--seed-target', required=True, type=Path, help='immutable BEFORE target; supplies baseline and coarse clocks')
    ap.add_argument('--scratch', required=True, type=Path)
    ap.add_argument('--device', choices=('auto', 'cpu', 'cuda'), default='auto')
    ap.add_argument('--checkpoint', type=Path, help='PENN or SOFA local checkpoint')
    ap.add_argument('--sofa-source', type=Path, help='upstream SOFA checkout outside the repository')
    ap.add_argument('--dictionary', type=Path, help='SOFA English dictionary')
    ap.add_argument('--synced-lyrics', type=Path, help='optional published LRC file; MMS or synced-even only')
    ap.add_argument('--ordered-words', action='store_true', help='apply the command word-order guard to MMS proposals')
    args = ap.parse_args()
    if args.synced_lyrics and args.candidate not in ('mms', 'synced-even'):
        ap.error('--synced-lyrics requires mms or synced-even')
    if args.candidate == 'synced-even' and not args.synced_lyrics:
        ap.error('synced-even requires --synced-lyrics')
    if args.ordered_words and args.candidate != 'mms':
        ap.error('--ordered-words requires mms')
    scratch = safe_scratch(args.package, args.seed_target, args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix=args.candidate+'-', dir=scratch))
    # Inherited cache overrides receive the same read-only fence as scratch.
    for key, directory in [('TORCH_HOME', 'torch'), ('HF_HOME', 'hf'), ('NUMBA_CACHE_DIR', 'numba')]:
        cache = Path(os.environ.get(key, str(scratch/directory)))
        os.environ[key] = str(safe_scratch(args.package, args.seed_target, cache))
    os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
    inputs = [args.package/'target.json', args.seed_target, args.package/'vocals_44k.flac']
    if args.synced_lyrics:
        inputs.append(args.synced_lyrics)
    hashes = {str(p.resolve()): digest(p) for p in inputs}
    started = time.perf_counter()
    seed = read(args.seed_target); target = read(args.package/'target.json')
    output = baseline(seed); metadata = {}
    plan = None
    if args.synced_lyrics:
        from ..synced import line_plan
        plan = line_plan(target['lyrics'], args.synced_lyrics.read_text(encoding='utf-8-sig'), target['duration'])
    if args.candidate == 'synced-even':
        from ..synced import even_words
        output['words'] = even_words(plan)
        metadata = dict(device='none', anchor_source='synced', windows=[(r['lo'], r['hi']) for r in plan])
    elif args.candidate != 'baseline':
        import numpy as np
        import torch
        np.random.seed(0); torch.manual_seed(0); torch.set_num_threads(2)
        device = ('cuda' if torch.cuda.is_available() else 'cpu') if args.device == 'auto' else args.device
        if args.candidate in ('mms', 'wav2vec2'):
            output['words'], metadata = align(args.package, target['lyrics'], seed, args.candidate, device, plan)
            if args.ordered_words:
                from ..run import map_words
                from ..synced import word_bounds
                mapped, flags = map_words(target['lyrics'], output['words'], target['duration'],
                                          word_bounds(plan) if plan is not None else None)
                output['words'] = [dict(w=w['w'], a=w['a'], b=w['b'], confidence=w['c'])
                                   for w in words(dict(lyrics=mapped))]
                metadata.update(ordered_words=True, order_flags=flags)
        elif args.candidate == 'sofa':
            if not all((args.sofa_source, args.checkpoint, args.dictionary)): ap.error('SOFA requires source, checkpoint and dictionary')
            output['words'], metadata = sofa_align(args.package, target['lyrics'], seed, device,
                                                  args.sofa_source, args.checkpoint, args.dictionary, destination)
        else:
            output['pitch'], output['hop'], metadata = pitch(args.package, args.candidate, device, target['duration'], args.checkpoint)
        if device == 'cuda': torch.cuda.synchronize()
        metadata['device'] = device
    else:
        metadata['device'] = 'saved'
    output['candidate'] = args.candidate
    output['measured_component'] = 'both' if args.candidate == 'baseline' else 'words' if args.candidate in ('mms','wav2vec2','sofa','synced-even') else 'pitch'
    output['runtime_s'] = time.perf_counter()-started
    validate(output)
    if any(digest(p) != h for p, h in hashes.items()): raise ValueError('input changed during run')
    (destination/'output.json').write_text(json.dumps(output, allow_nan=False))
    (destination/'provenance.json').write_text(json.dumps(dict(inputs=hashes, settings=metadata), indent=2))
    print(json.dumps(dict(output=str(destination/'output.json'), runtime_s=output['runtime_s'])))


if __name__ == '__main__': main()
