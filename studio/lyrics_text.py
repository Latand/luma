#!/usr/bin/env python3
"""Replace misheard word text with the real lyrics, keeping every word on the voice it was already snapped to.

  lyrics_text.py <package_dir>...             fetch/reuse the published lyrics, correct the text, rebuild the HTML
  lyrics_text.py --text lyrics.txt <package>  use lyrics supplied by the operator instead of fetching them
  lyrics_text.py --dry-run <package_dir>...   report what would change and write nothing
  lyrics_text.py --dry-run --json <pkg>...    the same report as machine-readable metrics

The ASR words in <package>/lyrics/{mix,vocal}.json are the only input read and are never modified, so every run
re-derives its output from the same source and two runs in a row are byte-identical. The true lyric text is
sequence-aligned against the normalized ASR words: a matched word keeps the ASR timing, a substituted word takes the
timing of the word it replaces, a true word with no ASR counterpart gets its start interpolated in the surrounding
gap, and an ASR word with no true counterpart is dropped. Word order never changes. The seeded words are then handed
to align_lyrics.realign(), which snaps every start to a vocal onset and groups lines by real vocal silence — the
same onset detector and line-break rule align_lyrics itself uses, not a re-implementation of it.

Fetching is a single free lookup (api.lyrics.ovh, no key) keyed by the title/artist in <package>/manifest.json. The
raw text — fetched or operator-supplied — is cached in <package>/lyrics/source.txt so a second run needs no network.

Safety guard: target.json fields other than `lyrics`/`lyricsSource`, and every audio file in the package, must stay
byte-for-byte identical to before the run; a change trips a loud failure instead of a silent write. A song whose
lyrics source does not confidently match the recording (low agreement with the ASR transcript) is left untouched.
"""
from __future__ import annotations
import argparse, difflib, json, re, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))
import align_lyrics as al
from prepare_song import sha256

AUDIO_FILES = ['vocals_44k.flac', 'foreground.mp3', 'backing.mp3', 'foreground_80.mp3', 'backing_80.mp3']
GUESS_SPAN = .15   # placeholder duration for an inserted word before realign() fits it to the voice

class LyricsSourceError(RuntimeError):
    """The true lyric text could not be obtained: no manifest, no network, or the fetch came back empty."""

# ---------------------------------------------------------------- lyrics text: fetch, cache, tokenize
def fetch_lyrics(title: str, artist: str) -> str:
    url = f'https://api.lyrics.ovh/v1/{urllib.parse.quote(artist)}/{urllib.parse.quote(title)}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'luma-lyrics-text/1.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode('utf-8'))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        raise LyricsSourceError(f'could not fetch lyrics for "{title}" by "{artist}": {e}') from e
    text = (data.get('lyrics') or '').strip()
    if not text: raise LyricsSourceError(f'no lyrics found for "{title}" by "{artist}"')
    return text

def resolve_source_text(pkg: Path, text_file: str | None, write: bool) -> tuple[str, str]:
    """The raw lyric text to use, and a short note of where it came from. Reads the cache before touching the
    network; writes the cache only when the run is allowed to write at all."""
    cache = pkg / 'lyrics' / 'source.txt'
    if text_file:
        text = Path(text_file).expanduser().read_text(encoding='utf-8')
        note = f'operator-supplied lyrics ({Path(text_file).name})'
    elif cache.exists() and not text_file:
        return cache.read_text(encoding='utf-8'), 'cached lyrics (lyrics/source.txt)'
    else:
        manifest_path = pkg / 'manifest.json'
        if not manifest_path.exists(): raise LyricsSourceError(f'{pkg.name}: no manifest.json to look up title/artist')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        title, artist = manifest.get('title') or '', manifest.get('artist') or ''
        if not title: raise LyricsSourceError(f'{pkg.name}: manifest.json has no title')
        text = fetch_lyrics(title, artist)
        note = f'fetched lyrics for "{title}" by "{artist}" (api.lyrics.ovh)'
    if write:
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(text, encoding='utf-8')
    return text, note

ANNOTATION = re.compile(r'^\s*[\[(].*[\])]\s*$')   # a whole line like "[Chorus]" or "(Verse 2)" — not sung text

def tokenize(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ANNOTATION.match(ln)]
    return [t for t in ' '.join(lines).split() if t]

# ---------------------------------------------------------------- true text <-> ASR word alignment
def match_words(asr_words: list[dict], true_tokens: list[str]) -> list[dict]:
    """One entry per true token, in order: {'w', 'a' (seed time or None), 'kind', 'src' (matching ASR index or
    None)}. Built from the edit script between the normalized word sequences, so word order is inherited from the
    true lyrics and never changes."""
    a_norm = [al.norm(w['w']) for w in asr_words]; t_norm = [al.norm(t) for t in true_tokens]
    sm = difflib.SequenceMatcher(a=a_norm, b=t_norm, autojunk=False)
    out: list[dict | None] = [None] * len(true_tokens)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                out[j1 + k] = {'w': true_tokens[j1 + k], 'a': asr_words[i1 + k]['a'], 'kind': 'matched', 'src': i1 + k}
        elif tag == 'replace':
            na, nt = i2 - i1, j2 - j1; k = min(na, nt)
            for x in range(k):
                out[j1 + x] = {'w': true_tokens[j1 + x], 'a': asr_words[i1 + x]['a'], 'kind': 'substituted', 'src': i1 + x}
            for x in range(k, nt):
                out[j1 + x] = {'w': true_tokens[j1 + x], 'a': None, 'kind': 'inserted', 'src': None}
        elif tag == 'insert':
            for x in range(j1, j2):
                out[x] = {'w': true_tokens[x], 'a': None, 'kind': 'inserted', 'src': None}
        # 'delete': the ASR words in that range simply have no true counterpart and are dropped
    return out   # type: ignore[return-value]

def fill_gaps(entries: list[dict], duration: float) -> list[dict]:
    """Every 'inserted' entry without a seed time gets one, spaced evenly between its neighbours' times; realign()
    snaps it to the nearest vocal onset afterwards. Never touches an entry that already has a time."""
    n = len(entries); i = 0
    while i < n:
        if entries[i]['a'] is not None: i += 1; continue
        j = i
        while j < n and entries[j]['a'] is None: j += 1
        prev_t = entries[i - 1]['a'] if i > 0 else 0.0
        next_t = entries[j]['a'] if j < n else duration
        if next_t <= prev_t: next_t = prev_t + .05 * (j - i + 1)
        step = (next_t - prev_t) / (j - i + 1)
        for k, idx in enumerate(range(i, j)): entries[idx]['a'] = round(prev_t + step * (k + 1), 3)
        i = j
    return entries

def seed_words(entries: list[dict], asr_words: list[dict]) -> list[dict]:
    """One word dict per true token, in the shape align_lyrics.realign() expects: `a` seeds the onset snap, `b`
    seeds the duration hint (carried over from the ASR word it replaces, or a short guess for an inserted word)."""
    ws = []
    for e in entries:
        if e['src'] is not None:
            src = asr_words[e['src']]; span = max(src['b'] - src['a'], .01); conf = src.get('c', .5)
        else:
            span, conf = GUESS_SPAN, .3
        ws.append({'a': round(e['a'], 3), 'b': round(e['a'] + span, 3), 'w': e['w'], 'c': conf})
    return ws

# ---------------------------------------------------------------- report
def word_error_rate(a_norm: list[str], t_norm: list[str]) -> float:
    sm = difflib.SequenceMatcher(a=a_norm, b=t_norm, autojunk=False); s = d = ins = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'replace':
            k = min(i2 - i1, j2 - j1); s += k; d += (i2 - i1 - k); ins += (j2 - j1 - k)
        elif tag == 'delete': d += i2 - i1
        elif tag == 'insert': ins += j2 - j1
    return round((s + d + ins) / max(len(t_norm), 1), 3)

def confidence(agreement_pct: float, asr_len: int, true_len: int) -> str:
    ratio = min(asr_len, true_len) / max(asr_len, true_len, 1)
    if agreement_pct >= 65 and ratio >= .6: return 'high'
    if agreement_pct >= 35 and ratio >= .4: return 'medium'
    return 'low'

def report_metrics(asr_words: list[dict], true_tokens: list[str], entries: list[dict], lines: list[dict]) -> dict:
    flat_words = al.flat(lines)
    changed = sum(1 for e in entries if e['kind'] == 'substituted')
    added = sum(1 for e in entries if e['kind'] == 'inserted')
    kept = {e['src'] for e in entries if e['src'] is not None}
    dropped = len(asr_words) - len(kept)
    a_norm = [al.norm(w['w']) for w in asr_words]; t_norm = [al.norm(t) for t in true_tokens]
    shifts = [abs(flat_words[i]['a'] - asr_words[e['src']]['a']) for i, e in enumerate(entries)
              if e['kind'] == 'substituted' and e['src'] is not None]
    return {'words_true': len(true_tokens), 'words_asr': len(asr_words), 'words_changed': changed, 'words_added': added,
            'words_dropped': dropped, 'wer_before': word_error_rate(a_norm, t_norm), 'wer_after': 0.0,
            'median_shift_changed_s': round(float(np.median(shifts)), 3) if shifts else 0.0, 'lines': len(lines)}

# ---------------------------------------------------------------- safety guard
def audio_fingerprint(pkg: Path) -> dict:
    return {name: sha256(pkg / name) for name in AUDIO_FILES if (pkg / name).exists()}

def verify_guard(pkg: Path, before_song: dict, after_song: dict, before_audio: dict, after_audio: dict) -> None:
    changed = sorted(k for k in set(before_song) | set(after_song) if before_song.get(k) != after_song.get(k))
    if set(changed) - {'lyrics', 'lyricsSource'}:
        raise SystemExit(f'{pkg.name}: safety guard tripped, target.json changed outside lyrics: {changed}')
    if before_audio != after_audio:
        raise SystemExit(f'{pkg.name}: safety guard tripped, an audio file changed or went missing')

def corrected_note(existing: str) -> str:
    base = (existing or 'Soniox stt-async-v5').split('; corrected to published lyrics')[0]
    return base + '; corrected to published lyrics (lyrics_text.py)'

# ---------------------------------------------------------------- package plumbing
def process_package(pkg: Path, text_file: str | None, write: bool, rebuild: bool = True) -> dict:
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
    before_song = dict(song)
    asr_lines, asr_src, _ = al.transcript(pkg, song, prefer='auto')
    asr_words = al.flat(asr_lines)
    raw_text, text_note = resolve_source_text(pkg, text_file, write)
    true_tokens = tokenize(raw_text)
    if not true_tokens: raise LyricsSourceError(f'{pkg.name}: no words found in the lyrics source')
    ctx = al.context(pkg, song)
    entries = fill_gaps(match_words(asr_words, true_tokens), ctx['duration'])
    lines = al.realign(seed_words(entries, asr_words), ctx)
    assert [w['w'] for w in al.flat(lines)] == true_tokens, 'the true lyric text must survive re-alignment untouched'
    agreement = al.agreement(asr_words, [{'w': t} for t in true_tokens])
    conf = confidence(agreement['agreement_pct'], len(asr_words), len(true_tokens))
    out = {'package': pkg.name, 'asr_source': asr_src, 'lyrics_source': text_note, 'confidence': conf,
           'agreement_pct': agreement['agreement_pct'], **report_metrics(asr_words, true_tokens, entries, lines)}
    if write:
        if conf == 'low':
            out['skipped'] = 'low confidence that the lyrics source matches this recording; left untouched'
            return out
        before_audio = audio_fingerprint(pkg)
        al.write_song(pkg, song, lines, corrected_note(song.get('lyricsSource') or ''))
        after_song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
        verify_guard(pkg, before_song, after_song, before_audio, audio_fingerprint(pkg))
        if rebuild: out['html'] = str(al.build_html(pkg, pkg.parent / f'Luma_{pkg.name}.html'))
    return out

def human(r: dict) -> str:
    if 'error' in r: return f"{r['package']}: {r['error']}"
    if r.get('skipped'): return f"{r['package']}: {r['skipped']} (confidence {r['confidence']}, agreement {r['agreement_pct']}%)"
    return (f"{r['package']}: {r['words_true']} true words ({r['words_changed']} changed, {r['words_added']} added, "
            f"{r['words_dropped']} dropped from the ASR transcript), WER against the true text {r['wer_before']} -> {r['wer_after']}, "
            f"median timing shift of changed words {r['median_shift_changed_s']:.2f} s, "
            f"confidence {r['confidence']} (agreement {r['agreement_pct']}%), lyrics source: {r['lyrics_source']}")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+')
    ap.add_argument('--text', help='lyrics file to use instead of fetching (only with a single package)')
    ap.add_argument('-n', '--dry-run', action='store_true', help='report only, write nothing')
    ap.add_argument('--json', action='store_true', help='print the report as JSON')
    ap.add_argument('--no-html', action='store_true', help='update target.json but do not rebuild the trainer')
    a = ap.parse_args()
    if a.text and len(a.package) > 1: ap.error('--text applies to a single package')
    report = []
    for p in a.package:
        pkg = Path(p).expanduser().resolve()
        try:
            r = process_package(pkg, a.text, write=not a.dry_run, rebuild=not a.no_html)
        except LyricsSourceError as e:
            r = {'package': pkg.name, 'error': str(e)}
        report.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else human(r))
        if not a.dry_run and 'html' in r: print(f"  wrote {pkg / 'target.json'} and rebuilt {r['html']}")
    return report

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: sys.exit(130)
