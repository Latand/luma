#!/usr/bin/env python3
"""Rebuild the playback audio of songs that are already prepared, in place, at 44.1 kHz.

  upgrade_audio.py <package_dir>... [--dry-run] [--originals DIR]... [--no-demucs] [--device auto|cpu|cuda] [--force]

Songs prepared before studio/stems.py play stems resampled to 22 kHz and encoded at 128 kb/s, which removes everything
above 11 kHz. This replaces foreground.mp3, backing.mp3, foreground_80.mp3 and backing_80.mp3 with stems from
studio/stems.py and swaps the audio inside the trainer (Luma_<package>.html next to the package). target.json, lyrics/,
vocals_44k.flac and the song data embedded in the trainer (notes, lyrics, ids) stay byte-identical and every file keeps its
name, so the practice history the browser keeps for the song still finds it. manifest.json gains an "audio" record, and
the original upload is copied into the package as original.<ext> when it lived somewhere else.

Where the new audio comes from, in this order:
  original  the original upload, looked up in <package>/original.*, the library's inbox/, the path in manifest.json and
            every --originals directory, and accepted only when its SHA-256 equals manifest.json's source_sha256. Then
            foreground = vocals_44k.flac and backing = original − vocals_44k.flac, once stems.alignment has shown that the
            two line up to the sample (a constant offset is measured and corrected).
  demucs    the original is there, but the stored vocal is missing or does not line up with it: Demucs separates the
            original again on this machine (GPU when available), for that song only. An existing vocals_44k.flac is kept
            as it is, because the cached transcripts in lyrics/ are keyed by its hash.
  none      no original: the song is reported and left untouched.

Songs whose stems already come from this encoder are reported as current and skipped (--force rebuilds them).
--dry-run decodes and measures the alignment, prints the plan per song and writes nothing. Nothing here uses the network.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sys, tempfile, time
from pathlib import Path
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))
import stems  # noqa: E402
from build_html import build as build_html, embedded_song, reassets  # noqa: E402

AUDIO = {'.aac', '.aif', '.aiff', '.flac', '.m4a', '.mka', '.mp3', '.mp4', '.oga', '.ogg', '.opus', '.wav', '.webm', '.wma'}

def log(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()

_seen: dict[tuple[Path, int, float], str] = {}
def sha256_cached(p: Path) -> str:
    st = p.stat(); key = (p.resolve(), st.st_size, st.st_mtime)
    if key not in _seen: _seen[key] = sha256(p)
    return _seen[key]

def find_original(pkg: Path, manifest: dict, extra: list[Path] = ()) -> tuple[Path, str] | None:
    """The original upload of a package and where it was found, or None. With a source_sha256 in manifest.json only a file
    with that hash counts; without one only <package>/original.* does."""
    want = manifest.get('source_sha256')
    places = [('package', sorted(pkg.glob('original.*'))), ('inbox', sorted((pkg.parent / 'inbox').glob('*')))]
    if manifest.get('source'): places.append(('manifest', [Path(manifest['source'])]))
    places += [('--originals', sorted(Path(d).expanduser().rglob('*'))) for d in extra]
    for where, paths in places:
        for p in paths:
            if not p.is_file() or (where != 'package' and p.suffix.lower() not in AUDIO): continue
            if (sha256_cached(p) == want) if want else where == 'package': return p, where
    return None

def stems_now(pkg: Path) -> dict:
    found = {name: stems.probe(pkg / name) for name in stems.FILES if (pkg / name).is_file()}
    return {'files': len(found), 'sample_rates': sorted({p['sample_rate'] for p in found.values()}), 'kbps': {n: p['kbps'] for n, p in found.items()}}

def fingerprint(pkg: Path) -> dict:
    """Hashes of everything the upgrade promises to leave alone."""
    keep = [pkg / 'target.json', pkg / 'vocals_44k.flac', *sorted((pkg / 'lyrics').rglob('*'))]
    return {str(p.relative_to(pkg)): sha256(p) for p in keep if p.is_file()}

def upgrade(pkg: Path, extra: list[Path] = (), dry_run: bool = False, allow_demucs: bool = True, device: str = 'auto', force: bool = False) -> dict:
    pkg = Path(pkg).expanduser().resolve(); html = pkg.parent / f'Luma_{pkg.name}.html'; report = {'package': pkg.name}
    if not (pkg / 'target.json').is_file(): return {**report, 'source': 'none', 'reason': 'not a song package (no target.json)'}
    manifest = json.loads((pkg / 'manifest.json').read_text(encoding='utf-8')) if (pkg / 'manifest.json').is_file() else {}
    report['before'] = before = stems_now(pkg)
    if not force and before['files'] == len(stems.FILES) and before['sample_rates'] == [stems.SAMPLE_RATE] and manifest.get('audio', {}).get('encoder') == stems.ENCODER:
        return {**report, 'source': 'current', 'reason': 'the stems already come from this encoder'}
    found = find_original(pkg, manifest, extra)
    if not found: return {**report, 'source': 'none', 'reason': 'no original upload with the SHA-256 recorded in manifest.json'}
    original, where = found; report.update(original=original.name, found_in=where)
    duration = float(json.loads((pkg / 'target.json').read_text(encoding='utf-8'))['duration'])
    mix = stems.decode(original); vocal = al = None
    if (pkg / 'vocals_44k.flac').is_file():
        vocal, sr = sf.read(pkg / 'vocals_44k.flac', dtype='float32', always_2d=True)
        if sr == stems.SAMPLE_RATE: al = stems.alignment(mix, vocal)
    report.update(alignment=al, source='original' if al and al['ok'] else 'demucs')
    if dry_run: return {**report, 'dry_run': True}
    if report['source'] == 'demucs' and not allow_demucs: return {**report, 'skipped': 'needs Demucs and --no-demucs was given'}

    kept = fingerprint(pkg); exempt: set[str] = set(); song_text = embedded_song(html) if html.is_file() else None
    work = Path(tempfile.mkdtemp(prefix='.audio-upgrade-', dir=pkg))
    try:
        if report['source'] == 'original':
            fore, back = stems.split(mix, vocal, al['lag'])
        else:
            from prepare_song import separate
            model = manifest.get('steps', {}).get('separation', {}).get('model') or 'htdemucs_ft'
            log(f'  {pkg.name}: {model} on the original')
            fore, report['separation'] = separate(mix, model, device); back = mix - fore
            if not (pkg / 'vocals_44k.flac').is_file():
                sf.write(work / 'vocals44.wav', fore, stems.SAMPLE_RATE, subtype='FLOAT'); stems.ffmpeg('-i', work / 'vocals44.wav', '-c:a', 'flac', pkg / 'vocals_44k.flac')
                exempt.add('vocals_44k.flac')  # written by this run, so it is not one of the files the upgrade promises to leave alone
        gain = stems.joint_gain(fore, back)
        sf.write(work / 'foreground.wav', fore * gain, stems.SAMPLE_RATE, subtype='FLOAT'); sf.write(work / 'backing.wav', back * gain, stems.SAMPLE_RATE, subtype='FLOAT')
        del fore, back, mix, vocal
        info = stems.encode({'foreground': work / 'foreground.wav', 'backing': work / 'backing.wav'}, duration, work)
        for name in stems.FILES:
            p = stems.probe(work / name); speed = .8 if name.endswith('_80.mp3') else 1
            if (p['codec'], p['sample_rate'], p['channels']) != ('mp3', stems.SAMPLE_RATE, 2) or abs(p['duration'] - duration / speed) > .05:
                raise RuntimeError(f'{name} came out as {p}')
        for name in stems.FILES: os.replace(work / name, pkg / name)
        copy = pkg / ('original' + original.suffix.lower())
        if where != 'package':
            shutil.copyfile(original, work / copy.name); os.replace(work / copy.name, copy)
        if html.is_file(): reassets(html, pkg)
        else: build_html(pkg, html)
        manifest['audio'] = {**info, 'source': report['source'], 'original': copy.name if where != 'package' else original.name, 'original_sha256': sha256(original),
                             'alignment': al, 'gain': round(gain, 6), 'upgraded': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
        (work / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8'); os.replace(work / 'manifest.json', pkg / 'manifest.json')
    finally:
        shutil.rmtree(work, ignore_errors=True)
    without = lambda d: {k: v for k, v in d.items() if k not in exempt}
    checks = {'kept_files_identical': without(fingerprint(pkg)) == without(kept), 'song_data_identical': song_text is None or embedded_song(html) == song_text, 'html': html.name}
    report.update(after=stems_now(pkg), checks=checks)
    if not (checks['kept_files_identical'] and checks['song_data_identical']): raise RuntimeError(f'{pkg.name}: data that must stay identical changed: {checks}')
    return report

def summary(r: dict) -> str:
    if 'error' in r: return f"{r['package']}: FAILED {r['error']}"
    rates = lambda s: '/'.join(map(str, s.get('sample_rates') or [])) or '-'
    now = f"stems {rates(r.get('before', {}))} Hz"
    if r['source'] in ('none', 'current'): return f"{r['package']}: {r['source']}, {r['reason']}; {now}"
    al = r.get('alignment')
    how = f"lag {al['lag']} in {al['agree']}/{al['blocks']} blocks, vocal gain {al['gain']} (1 ms later: {al['gain_1ms']})" if al and 'lag' in al else 'no usable vocals_44k.flac'
    if r.get('dry_run'): return f"{r['package']}: would use {r['source']}: {r['original']} from {r['found_in']}; {how}; {now}"
    if r.get('skipped'): return f"{r['package']}: skipped, {r['skipped']}"
    return f"{r['package']}: used {r['source']}: {r['original']} from {r['found_in']}; {how}; {now} -> {rates(r['after'])} Hz"

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+', help='song package directories; a library glob such as songs/* is fine, anything without target.json is skipped')
    ap.add_argument('--dry-run', action='store_true', help='decode, measure the alignment and print the plan without writing anything')
    ap.add_argument('--originals', action='append', default=[], metavar='DIR', help='one more directory to search, recursively, for original uploads')
    ap.add_argument('--no-demucs', action='store_true', help='leave songs that would need Demucs untouched')
    ap.add_argument('--device', default='auto', choices=['auto', 'cpu', 'cuda']); ap.add_argument('--force', action='store_true', help='rebuild stems that are already current')
    a = ap.parse_args(); failed = 0
    for p in map(Path, a.package):
        if not (p / 'target.json').is_file(): continue
        t0 = time.time()
        try: r = upgrade(p, [Path(d) for d in a.originals], a.dry_run, not a.no_demucs, a.device, a.force)
        # SystemExit too: build_html.data_span and prepare_song.separate raise it as CLIs would, and one damaged song must not
        # end the batch. KeyboardInterrupt is a BaseException of its own and still stops the run.
        except (Exception, SystemExit) as e: failed += 1; r = {'package': p.name, 'error': f'{type(e).__name__}: {e}'}
        r['seconds'] = round(time.time() - t0, 1); log(summary(r)); print(json.dumps(r, ensure_ascii=False), flush=True)
    sys.exit(1 if failed else 0)

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: sys.exit(130)
