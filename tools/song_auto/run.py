"""Offline lyric placement and melody with deterministic end checks.

python -m tools.song_auto.run PACKAGE [--scratch DIRECTORY] [--apply]
python -m tools.song_auto.run --download-models [--model-cache DIRECTORY]
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from .bench import run as bench

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/song_qa'))
from common import atomic_text, write_json
from apply_edits import derive, runs, update_unpitched, validate
from candidates import detect
from features import compute
from placement import screen


@contextmanager
def offline():
    """Deny network in the inference process, including a cache-miss download."""
    def denied(*args, **kwargs):
        raise RuntimeError('offline cache miss or network attempt; provision models first')
    previous = socket.socket.connect, socket.socket.connect_ex, socket.create_connection
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = denied
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection = previous


def ordered_starts(values, duration, gap=.04):
    """Least-squares isotonic projection in lyric order, with a 40 ms floor.

    PAVA is linear in the word count. Every adjusted word remains doubtful;
    ordering supplies a valid draft, and supplies no acoustic evidence.
    """
    if not values:
        return []
    upper = duration - len(values) * gap
    if upper < 0:
        raise ValueError('insufficient duration for lyric words')
    blocks = []
    for i, value in enumerate(values):
        if not math.isfinite(value) or not 0 <= value < duration:
            raise ValueError('invalid aligned start')
        blocks.append([value - i*gap, 1])
        while len(blocks) > 1 and blocks[-2][0]/blocks[-2][1] > blocks[-1][0]/blocks[-1][1]:
            total, n = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += n
    result = []
    for total, n in blocks:
        level = min(upper, max(0., total/n))
        for _ in range(n):
            result.append(round(level + len(result)*gap, 3))
    return result


def map_words(lyrics, proposals, duration):
    flat = [w for line in lyrics for w in line['words']]
    if len(flat) != len(proposals) or any(w['w'] != p['w'] for w, p in zip(flat, proposals)):
        raise ValueError('alignment ownership differs from package words')
    for p in proposals:
        if (not all(math.isfinite(p[k]) for k in ('a', 'b', 'confidence')) or
                not 0 <= p['a'] < p['b'] <= duration or not 0 <= p['confidence'] <= 1):
            raise ValueError('invalid alignment span or confidence')
    starts = ordered_starts([p['a'] for p in proposals], duration)
    out, flags, k = [], [], 0
    for line in lyrics:
        if not line['words']:
            raise ValueError('empty lyric row')
        row = []
        for word in line['words']:
            p = proposals[k]
            a = starts[k]
            limit = starts[k+1] - .005 if k+1 < len(starts) else duration
            b = round(min(limit, max(a+.02, p['b'])), 3)
            adjusted = abs(a-p['a']) > .001 or p['b'] > limit+.001
            c = min(.4, p['confidence']) if adjusted or p['confidence'] < .6 else p['confidence']
            row.append(dict(w=word['w'], a=a, b=b, c=round(c, 3), timing_source='mms_auto'))
            if adjusted:
                flags.append(dict(type='alignment_order', word=k, a=a, b=b, previous=p['a']))
            k += 1
        out.append(dict(a=row[0]['a'], b=row[-1]['b'], words=row))
    return out, flags


def unpitched(song, F):
    """Audible aperiodic *unvoiced* runs are generic noise, never guessed screams.

    This conservative annotation cannot erase a surviving pitch estimate.
    Silence and merely absent pitch supply no unpitched evidence.
    """
    import numpy as np
    t = np.array([p[0] for p in song['points']])
    index = np.clip(np.searchsorted(F['qa_t'], t), 0, len(F['qa_t'])-1)
    previous = np.maximum(0, index-1)
    index = np.where(abs(F['qa_t'][previous]-t) <= abs(F['qa_t'][index]-t), previous, index)
    db = F['qa_db'][index]
    audible = db > max(-65, float(np.percentile(F['qa_db'], 95))-48)
    mask = (np.array([p[1] is None for p in song['points']]) & audible &
            (F['qa_periodicity'][index] < .5) & (F['qa_concentration'][index] < .035))
    song['unpitched'] = []
    ops = [dict(op='clear', kind='noise', a=float(t[a]),
                b=min(song['duration'], round(float(t[b-1])+.02, 3)))
           for a, b in runs(mask) if b-a >= 6]
    update_unpitched(song, ops)


def pitch_target(package, base, device):
    import numpy as np
    import soundfile as sf
    sys.path.insert(0, str(ROOT / 'studio'))
    from prepare_song import track_pitch, build_map
    vocal, sr = sf.read(package/'vocals_44k.flac', dtype='float32', always_2d=True)
    if abs(len(vocal)/sr-base['duration']) > .1:
        raise ValueError('stem and target duration differ')
    manifest = bench.read(package/'manifest.json') if (package/'manifest.json').exists() else {}
    gain = manifest.get('audio', {}).get('gain', 1.)
    if not isinstance(gain, (int, float)) or not math.isfinite(gain) or gain <= 0:
        raise ValueError('invalid stem gain')
    ct, f0, pd, P, _ = track_pitch(vocal, sr, base['duration'], device, gain)
    # build_map uses this argument only for the waveform, retained from base.
    return build_map(ct, f0, pd, P, np.zeros((1000, 1)), base['duration'],
                     base.get('title', ''), base.get('artist', ''), 'pYIN + CREPE')


def place(package, base, seed, device, pitch_song=None):
    """Shared entry for existing packages and preparation's opt-in path."""
    proposals, _ = bench.align(package, base.get('lyrics', []), seed, 'mms', device) if base.get('lyrics') else ([], {})
    # The acoustic model is local to align(); collect it before pitch inference.
    import gc
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    melody = pitch_song if pitch_song is not None else pitch_target(package, base, device)
    song = copy.deepcopy(base)
    song['points'] = copy.deepcopy(melody['points'])
    song['lyrics'], flags = map_words(base.get('lyrics', []), proposals, base['duration'])
    F = compute(package)
    unpitched(song, F)
    song['notes'], song['phrases'], song['metrics'], song['initialTime'], _ = derive(song['points'], song['duration'], [])
    placement = screen(song, F)
    candidates = detect(song, {k[3:]: v for k, v in F.items() if k.startswith('qa_')})
    flags += placement['flags'] + candidates
    words = [w for line in song['lyrics'] for w in line['words']]
    for flag in flags:
        if 'word' in flag:
            words[flag['word']]['c'] = min(.4, words[flag['word']]['c'])
        elif flag['type'] in ('repeat', 'unpitched', 'parallel'):
            for w in words:
                if w['a'] < flag['b'] and w['b'] > flag['a']:
                    w['c'] = min(.4, w['c'])
    flags += [dict(type='word_confidence', word=i, a=w['a'], b=w['b'])
              for i, w in enumerate(words) if w['c'] <= .4]
    flags.sort(key=lambda f: (f['a'], f['type'], f.get('word', -1)))
    song.update(status='unverified_draft', createdBy='song_auto: MMS + pYIN + CREPE; deterministic QA; listening required',
                lyricsSource='Known package text; offline MMS forced alignment',
                method='MMS word placement + pYIN + CREPE melody')
    # A changed map gets a new edit namespace; identical outputs keep their id.
    content = {k: song[k] for k in ('points', 'lyrics', 'unpitched')}
    song['id'] = hashlib.sha256((str(base.get('sourceId', '')) + json.dumps(content, sort_keys=True)).encode()).hexdigest()[:20]
    if validate(song):
        raise ValueError('generated target fails schema validation')
    return song, dict(flags=flags, review_required=bool(flags), placement=placement,
                      models=dict(words='MMS_FA', melody='pYIN + CREPE full'))


def trainer_path(package, explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
    else:
        manifest = bench.read(package/'manifest.json') if (package/'manifest.json').exists() else {}
        recorded = manifest.get('html', {}).get('path')
        path = Path(recorded) if recorded else package.parent/f'Luma_{package.name}.html'
        if not path.is_absolute():
            path = package/path
        path = path.resolve()
    if path.suffix.lower() != '.html' or path.parent not in (package, package.parent):
        raise ValueError('trainer must be an HTML file beside or inside the package; pass --trainer')
    return path


def build_trainer(package, song, html):
    subprocess.run([sys.executable, str(ROOT/'studio/build_html.py'), str(package), '-o', str(html)],
                   check=True, capture_output=True)
    sys.path.insert(0, str(ROOT/'studio'))
    from build_html import embedded_song
    if json.loads(embedded_song(html)) != song:
        raise ValueError('trainer target differs')
    return html


def full_build(package, song, destination):
    """Build from the generated target plus package assets, never --rebuild."""
    staged = destination/'package'
    staged.mkdir()
    write_json(staged/'target.json', song)
    for name in ('foreground.mp3', 'backing.mp3', 'foreground_80.mp3', 'backing_80.mp3'):
        (staged/name).symlink_to((package/name).resolve(strict=True))
    html = destination/'trainer.html'
    return build_trainer(staged, song, html)


def apply(package, song, html, trainer, expected):
    """Backup all existing records before the first write; rollback on failure.

    A persistent nonblocking file lock serializes auto writers across atomic
    target replacements. Other writers are detected by the input hash guard.
    """
    lock = package/'.song-auto.lock'
    with open(lock, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if bench.digest(package/'target.json') != expected:
            raise ValueError('target changed during run')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        root = package.parent/'backups'/('song-auto-'+stamp)
        backup = root/package.name
        backup.mkdir(parents=True, exist_ok=False)
        paths = [package/'target.json', trainer, package/'manifest.json']
        saved = []
        for i, path in enumerate(paths):
            dest = backup/('target.json', 'trainer.html', 'manifest.json')[i]
            if path.exists():
                shutil.copy2(path, dest)
                saved.append((path, dest))
        # Persist recovery locations, including records which did not exist.
        write_json(backup/'restore.json', dict(paths=[str(p) for p in paths], existed=[p.exists() for p in paths]))
        try:
            write_json(paths[0], song)
            # Build with the actual package path after backup and target write.
            rebuilt = build_trainer(package, song, html.with_name('applied-trainer.html'))
            atomic_text(trainer, rebuilt.read_text(encoding='utf-8'))
            manifest = bench.read(paths[2]) if paths[2].exists() else {}
            manifest.update(map=dict(id=song['id'], metrics=song['metrics'], notes=len(song['notes']),
                                     ok_notes=sum(bool(n['ok']) for n in song['notes'])),
                            html=dict(path=str(trainer), bytes=trainer.stat().st_size, sha256=bench.digest(trainer)),
                            qa=dict(tool='song_auto', review='required'))
            write_json(paths[2], manifest)
        except BaseException:
            for path in paths:
                source = next((s for p, s in saved if p == path), None)
                if source:
                    atomic_text(path, source.read_text(encoding='utf-8'))
                else:
                    path.unlink(missing_ok=True)
            raise
        return backup


def print_checks(report):
    flags = report['flags']
    print(f'QA: {len(flags)} flags; draft requires listening')
    for flag in flags[:20]:
        print(f"  {flag['a']:.3f}..{flag['b']:.3f}s {flag['type']}")
    if len(flags) > 20:
        print(f'  +{len(flags)-20} in the full QA report')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package', nargs='?', type=Path)
    ap.add_argument('--scratch', type=Path, default=Path(tempfile.gettempdir())/'luma-song-auto')
    ap.add_argument('--seed-target', type=Path, help='optional coarse timing source; defaults to package target')
    ap.add_argument('--device', choices=('auto', 'cpu', 'cuda'), default='auto')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--trainer', type=Path, help='existing trainer to back up and replace with --apply')
    ap.add_argument('--download-models', action='store_true', help='one-time MMS download; checks CREPE installation')
    ap.add_argument('--model-cache', type=Path, default=Path(os.environ.get('TORCH_HOME', Path.home()/'.cache/luma-song-auto/torch')))
    args = ap.parse_args(argv)
    if args.download_models:
        if args.package or args.apply:
            ap.error('download mode takes no package or apply flag')
        cache = args.model_cache.expanduser().resolve()
        for source in (ROOT, Path(sys.prefix).resolve()):
            if cache == source or source in cache.parents or cache in source.parents:
                ap.error('model cache must be disjoint from the repository and Python environment')
        os.environ['TORCH_HOME'] = str(cache)
        import torchaudio
        import torchcrepe
        torchaudio.pipelines.MMS_FA.get_model(with_star=True)
        torchcrepe.load.model('cpu', 'full')
        print('Models provisioned. Inference runs offline.')
        return
    if not args.package:
        ap.error('package is required')
    package = args.package.expanduser().resolve(strict=True)
    seed = (args.seed_target or package/'target.json').expanduser().resolve(strict=True)
    scratch = bench.safe_scratch(package, seed, args.scratch)
    cache = bench.safe_scratch(package, seed, args.model_cache.expanduser())
    os.environ['TORCH_HOME'] = str(cache)
    scratch.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='song-auto-', dir=scratch))
    os.environ['NUMBA_CACHE_DIR'] = str(destination/'numba')
    started = time.perf_counter()
    inputs = {p: bench.digest(p) for p in (package/'target.json', seed, package/'vocals_44k.flac')}
    base = bench.read(package/'target.json')
    trainer = trainer_path(package, args.trainer) if args.apply else None
    with offline():
        import numpy as np
        import torch
        np.random.seed(0)
        torch.manual_seed(0)
        torch.set_num_threads(2)
        device = ('cuda' if torch.cuda.is_available() else 'cpu') if args.device == 'auto' else args.device
        song, report = place(package, base, bench.read(seed), device)
        html = full_build(package, song, destination)
    if any(bench.digest(p) != h for p, h in inputs.items()):
        raise ValueError('input changed during run')
    write_json(destination/'target.json', song)
    report.update(runtime_s=time.perf_counter()-started, device=device)
    output = bench.baseline(song)
    output.update(candidate='song_auto', measured_component='both', runtime_s=report['runtime_s'])
    bench.validate(output)
    write_json(destination/'output.json', output)
    write_json(destination/'checks.json', report)
    write_json(destination/'provenance.json', dict(inputs={str(k): v for k, v in inputs.items()}))
    if args.apply:
        backup = apply(package, song, html, trainer, inputs[package/'target.json'])
        print('Applied; dated backup:', backup)
    print_checks(report)
    print(json.dumps(dict(output=str(destination/'output.json'), target=str(destination/'target.json'),
                          checks=str(destination/'checks.json'), runtime_s=report['runtime_s'])))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
        # Detailed paths, lyrics and exceptions belong only in private evidence.
        print('song_auto failed: check inputs, cached models and writable scratch; package backup is retained after apply failure', file=sys.stderr)
        sys.exit(1)
