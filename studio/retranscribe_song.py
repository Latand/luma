#!/usr/bin/env python3
"""Transcribe the clean vocal of an already prepared song and put its words back where the voice sings them.

  retranscribe_song.py <package_dir>... [--lang en] [--cache-only] [--no-html]

This is the only command in the repo that spends money: it sends the song's own Demucs vocal stem to Soniox, which
hears the singer without the band on top of them. The raw response is cached next to the song in
<package>/lyrics/soniox-<sha>.json, keyed by the SHA-256 of the vocal stem it was made from, so running the command
again reads the cache and pays nothing; --cache-only refuses to pay at all. The words are then snapped to the voice
by align_lyrics. Only `lyrics` and `lyricsSource` in target.json change — audio, notes, phrases, fragments and ids
are left exactly as they were — and the trainer HTML is rebuilt around them.

The key comes from SONIOX_API_KEY or ~/.config/luma/soniox-api-key and is never written anywhere.

Nothing else in the repo may spend the operator's money: a paid call happens only when this file is run as a
program from a shell. Importing it — which is all Studio or a test could ever do — leaves `PAID_CALLS_ALLOWED`
false, and reading an existing cache stays free either way.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))
from align_lyrics import aligned_note, build_html, context, corrected_note_for, corrected_seed, flat, realign, save_transcript, write_song
from prepare_song import ffmpeg, group_lines, log, merge_tokens, sha256, soniox_key, soniox_tokens

MODEL = 'stt-async-v5'
PAID_CALLS_ALLOWED = False      # only main() flips this, so an import can never reach the paying branch

def allow_paid_calls():
    """Money is only ever spent when this very file is the program being run. Under a test runner or inside the
    Studio server this module is an import, so `sys.argv[0]` names something else and the branch stays closed.
    (Checking `sys.modules` instead would not work: librosa drags `unittest` in on every run.)"""
    program = Path(sys.argv[0] or '').resolve()
    if program != Path(__file__).resolve():
        raise SystemExit(f'retranscribe_song.py spends money per call: run it directly from a shell, not from {program.name or "an import"}')
    global PAID_CALLS_ALLOWED; PAID_CALLS_ALLOWED = True

def vocal_mono_mp3(pkg: Path, out: Path) -> Path:
    """The vocal stem as a small mono MP3 — the same shape of audio the preparation pipeline sends."""
    ffmpeg('-i', pkg / 'vocals_44k.flac', '-ac', '1', '-ar', '22050', '-c:a', 'libmp3lame', '-b:a', '96k', out)
    return out

def cached(pkg: Path, stem_sha: str) -> Path:
    return pkg / 'lyrics' / f'soniox-{stem_sha[:16]}.json'

def transcribe(pkg: Path, lang: str, cache_only: bool, transcription_id: str | None = None) -> dict:
    """The cached Soniox response for this vocal stem, paying for it exactly once."""
    stem_sha = sha256(pkg / 'vocals_44k.flac'); cache = cached(pkg, stem_sha)
    if cache.exists():
        log(f'  {pkg.name}: cached transcript {cache.name}, no API call'); return json.loads(cache.read_text(encoding='utf-8'))
    if cache_only: raise SystemExit(f'{pkg.name}: no cached transcript and --cache-only was given')
    if not PAID_CALLS_ALLOWED: raise SystemExit(f'{pkg.name}: a paid transcription may only be started by running retranscribe_song.py from a shell')
    key = soniox_key()
    if not key: raise SystemExit('no Soniox key: set SONIOX_API_KEY or write ~/.config/luma/soniox-api-key')
    cache.parent.mkdir(exist_ok=True); mp3 = vocal_mono_mp3(pkg, pkg / 'lyrics' / 'vocal_mono.mp3')
    try:
        log(f'  {pkg.name}: sending the vocal stem to Soniox ({mp3.stat().st_size >> 10} KiB, language {lang})')
        t0 = time.time(); tokens = soniox_tokens(mp3, key, lang, transcription_id)
        payload = {'model': MODEL, 'language': lang, 'audio': 'Demucs vocal stem (vocals_44k.flac) as mono 22 kHz 96 kb/s MP3',
                   'stem_sha256': stem_sha, 'audio_sha256': sha256(mp3), 'created': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                   'seconds': round(time.time() - t0, 1), 'tokens': tokens}
        cache.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
        log(f'  {pkg.name}: {len(tokens)} tokens in {payload["seconds"]} s, cached in {cache.name}')
        return payload
    finally:
        mp3.unlink(missing_ok=True)

def retranscribe(pkg: Path, lang: str, cache_only: bool = False, rebuild: bool = True, transcription_id: str | None = None) -> dict:
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
    before = song.get('lyrics') or []
    if before and 'vocal stem' not in (song.get('lyricsSource') or '') and not (pkg / 'lyrics' / 'mix.json').exists():
        save_transcript(pkg, 'mix', before, song.get('lyricsSource') or '')   # keep the mix transcript it replaces
    payload = transcribe(pkg, lang, cache_only, transcription_id)
    words = merge_tokens(payload['tokens'])
    note = f'Soniox {payload["model"]} on the Demucs vocal stem, {payload["created"][:10]}, automatic word timings'
    save_transcript(pkg, 'vocal', group_lines(words), note)
    ctx = context(pkg, song)
    corrected = corrected_seed(pkg, words, ctx)   # a stored lyrics correction must survive a fresh transcription too
    seed = corrected if corrected is not None else words
    lines = realign(seed, ctx)
    assert [w['w'] for w in flat(lines)] == [w['w'] for w in seed], 'the transcript text must survive re-alignment'
    write_song(pkg, song, lines, corrected_note_for(note, 'vocal') if corrected is not None else aligned_note(note))
    out = {'package': pkg.name, 'words': len(words), 'lines': len(lines), 'words_before': len(flat(before)), 'lines_before': len(before)}
    if rebuild: out['html'] = str(build_html(pkg, pkg.parent / f'Luma_{pkg.name}.html'))
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+'); ap.add_argument('--lang', default='en', help='language the song is sung in')
    ap.add_argument('--cache-only', action='store_true', help='never call the API: fail unless the response is already cached')
    ap.add_argument('--no-html', action='store_true', help='update target.json but do not rebuild the trainer')
    ap.add_argument('--transcription-id', help='fetch a transcription that was already paid for instead of sending the audio again')
    a = ap.parse_args()
    if not a.cache_only: allow_paid_calls()
    for p in a.package:
        r = retranscribe(Path(p).expanduser().resolve(), a.lang, a.cache_only, not a.no_html, a.transcription_id)
        log('DONE', json.dumps(r, ensure_ascii=False))

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: sys.exit(130)
