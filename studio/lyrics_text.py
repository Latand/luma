#!/usr/bin/env python3
"""Replace misheard word text with the real lyrics, keeping every word on the voice it was already snapped to.

  lyrics_text.py <package_dir>...             fetch/reuse the published lyrics, correct the text, rebuild the HTML
  lyrics_text.py --text lyrics.txt <package>  use lyrics supplied by the operator instead of fetching them
  lyrics_text.py --from mix|vocal <package>   correct against a specific stored transcript instead of the one the
                                               song is already published from
  lyrics_text.py --force <package>            write even when the completeness check would otherwise refuse
  lyrics_text.py --dry-run <package_dir>...   report what would change and write nothing
  lyrics_text.py --dry-run --json <pkg>...    the same report as machine-readable metrics

The ASR words in <package>/lyrics/{mix,vocal}.json are the only input read and are never modified, so every run
re-derives its output from the same source and two runs in a row are byte-identical. Correction starts from
whichever transcript the song is already published from (the 'vocal stem' marker in lyricsSource is the signal, or
--from to say so explicitly) — a song deliberately kept on the mix transcript never silently jumps to the other one.

The true lyric text is sequence-aligned against the normalized ASR words: a matched word keeps the ASR timing, a
substituted word takes the timing of the word(s) it replaces (spread across their whole span when one heard word
stands for several true words), a true word with no ASR counterpart gets its start interpolated inside the nearest
sung stretch, and an ASR word with no true counterpart is dropped — unless the dropped run is itself a repeat of a
span already used elsewhere in the true text (a chorus the source only writes out once), in which case that span is
duplicated back in rather than losing the words. Word order never changes within the true text as given (repeats
are the one place new text is added, and only text already present elsewhere in the same source). The seeded words
are then handed to align_lyrics.realign(), which snaps every start to a vocal onset and groups lines by real vocal
silence — the same onset detector and line-break rule align_lyrics itself uses, not a re-implementation of it.

Before writing, a completeness check refuses (or, with --force, warns and proceeds) when a contiguous run of dropped
ASR words covers substantial sung time, when the matched text ends well before the heard transcript does, or when an
inserted word lands outside the sung voice — signs that the source text is missing a section, not just imperfectly
matched.

Fetching is a single free lookup (api.lyrics.ovh, no key) keyed by the title/artist in <package>/manifest.json. The
raw text — fetched or operator-supplied — is cached in <package>/lyrics/source.txt (with the title/artist it was
fetched for, in lyrics/source.meta.json) once a run actually writes it, so a second run needs no network and a
changed manifest title/artist is not silently served the old text.

Safety guard: target.json fields other than `lyrics`/`lyricsSource`, and every audio file in the package, must stay
byte-for-byte identical to before the run; a change trips a loud failure instead of a silent write. The "before"
snapshot is re-read from disk immediately ahead of the write, never kept from the object this script itself loaded
and may have handed off elsewhere, so an in-place mutation to a nested field can't hide from the comparison. A song
whose lyrics source does not confidently match the recording (low agreement with the ASR transcript) is left
untouched.
"""
from __future__ import annotations
import argparse, difflib, json, re, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))
import align_lyrics as al
from prepare_song import sha256

AUDIO_EXTENSIONS = {'.flac', '.mp3', '.m4a', '.wav'}   # every audio file the safety guard must fingerprint
LYRICS_FIELDS = ('lyrics', 'lyricsSource')              # the only target.json fields this script is allowed to change
GUESS_SPAN = .15   # placeholder duration for an inserted word before realign() fits it to the voice
MIN_REPEAT_WORDS = 4      # a dropped run shorter than this is more likely noise than a missed repeat
MIN_REPEAT_SECONDS = 2.0  # ...and one covering less sung time than this isn't worth searching for
REPEAT_MATCH_RATIO = .7   # how much of a candidate span must match the dropped run to count as the same text
DROP_RUN_SECONDS = 3.0    # a contiguous dropped run spanning at least this much sung time blocks the write
TAIL_GAP_SECONDS = 10.0   # the matched text must reach within this much of the end of the heard transcript

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

def resolve_source_text(pkg: Path, text_file: str | None) -> tuple[str, str, dict | None]:
    """The raw lyric text to use, a short note of where it came from, and — only when the source was freshly
    fetched and should be cached once the run is confirmed to write — the manifest title/artist it was fetched for.
    None means nothing new needs caching: an operator-supplied file, or a cache hit whose stored title/artist still
    matches the manifest. Never touches the network before checking the cache, and never writes anything itself."""
    if text_file:
        text = Path(text_file).expanduser().read_text(encoding='utf-8')
        return text, f'operator-supplied lyrics ({Path(text_file).name})', None
    cache, meta_path = pkg / 'lyrics' / 'source.txt', pkg / 'lyrics' / 'source.meta.json'
    manifest_path = pkg / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    title, artist = manifest.get('title') or '', manifest.get('artist') or ''
    if cache.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        if meta.get('title') == title and meta.get('artist') == artist:
            return cache.read_text(encoding='utf-8'), 'cached lyrics (lyrics/source.txt)', None
    if not manifest_path.exists(): raise LyricsSourceError(f'{pkg.name}: no manifest.json to look up title/artist')
    if not title: raise LyricsSourceError(f'{pkg.name}: manifest.json has no title')
    text = fetch_lyrics(title, artist)
    return text, f'fetched lyrics for "{title}" by "{artist}" (api.lyrics.ovh)', {'title': title, 'artist': artist}

def preferred_source(song: dict) -> str:
    """Which transcript this song's published lyrics are already built from. A song deliberately left on the mix
    transcript (no 'vocal stem' marker) must keep starting from the mix, never silently move to the other one."""
    return 'vocal' if 'vocal stem' in (song.get('lyricsSource') or '') else 'mix'

def resolve_transcript(pkg: Path, song: dict, prefer: str) -> tuple[list[dict], str]:
    want = prefer if prefer != 'auto' else preferred_source(song)
    if not (pkg / 'lyrics' / f'{want}.json').exists(): want = 'auto'   # no stored copy of the preferred one: fall back
    lines, src, _ = al.transcript(pkg, song, prefer=want)
    return lines, src

ANNOTATION = re.compile(r'^\s*[\[(].*[\])]\s*$')   # a whole line like "[Chorus]" or "(Verse 2)" — not sung text

def tokenize(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if not ANNOTATION.match(ln)]
    return [t for t in ' '.join(lines).split() if t]

# ---------------------------------------------------------------- true text <-> ASR word alignment
def match_words(asr_words: list[dict], true_tokens: list[str]) -> list[dict]:
    """One entry per true token, in order: {'w', 'a' (seed time or None), 'kind', 'src' (matching ASR index or
    None)}. Built from the edit script between the normalized word sequences, so word order is inherited from the
    true lyrics and never changes. When one heard word stands for several true words, all of them get a seed time
    spread across that heard word's whole span rather than only the first one."""
    a_norm = [al.norm(w['w']) for w in asr_words]; t_norm = [al.norm(t) for t in true_tokens]
    sm = difflib.SequenceMatcher(a=a_norm, b=t_norm, autojunk=False)
    out: list[dict | None] = [None] * len(true_tokens)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                out[j1 + k] = {'w': true_tokens[j1 + k], 'a': asr_words[i1 + k]['a'], 'kind': 'matched', 'src': i1 + k}
        elif tag == 'replace':
            na, nt = i2 - i1, j2 - j1
            if na == 0:
                for x in range(nt):
                    out[j1 + x] = {'w': true_tokens[j1 + x], 'a': None, 'kind': 'inserted', 'src': None}
            else:
                t0, t1 = asr_words[i1]['a'], asr_words[i2 - 1]['b']
                for x in range(nt):
                    src = i1 + min(x, na - 1)
                    a_time = t0 if nt == 1 else round(t0 + (t1 - t0) * x / (nt - 1), 3)
                    out[j1 + x] = {'w': true_tokens[j1 + x], 'a': a_time, 'kind': 'substituted' if x < na else 'inserted',
                                    'src': src if x < na else None}
        elif tag == 'insert':
            for x in range(j1, j2):
                out[x] = {'w': true_tokens[x], 'a': None, 'kind': 'inserted', 'src': None}
        # 'delete': the ASR words in that range simply have no true counterpart and are dropped
    return out   # type: ignore[return-value]

def find_repeated_span(dropped_norm: list[str], t_norm: list[str]) -> tuple[int, int] | None:
    """A span in the true text whose words are (almost) the same as this dropped ASR run — the run is a repeat of
    that span (e.g. a chorus written out once but sung twice), not padding that should be dropped."""
    n = len(dropped_norm)
    if n > len(t_norm): return None
    best = None
    for start in range(len(t_norm) - n + 1):
        window = t_norm[start:start + n]
        ratio = sum(1 for a, b in zip(window, dropped_norm) if a == b) / n
        if ratio >= REPEAT_MATCH_RATIO and (best is None or ratio > best[1]):
            best = (start, ratio)
    return (best[0], best[0] + n) if best else None

def repeated_insertions(asr_words: list[dict], true_tokens: list[str]) -> list[tuple[int, list[str]]]:
    """Dropped ASR runs that are (almost) the same text as a span already used elsewhere in the true lyrics.
    Returns (position in true_tokens, tokens to duplicate there), so the caller can splice the repeat back into the
    true text instead of silently losing the words."""
    a_norm = [al.norm(w['w']) for w in asr_words]; t_norm = [al.norm(t) for t in true_tokens]
    sm = difflib.SequenceMatcher(a=a_norm, b=t_norm, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != 'delete': continue
        if i2 - i1 < MIN_REPEAT_WORDS: continue
        if asr_words[i2 - 1]['b'] - asr_words[i1]['a'] < MIN_REPEAT_SECONDS: continue
        found = find_repeated_span(a_norm[i1:i2], t_norm)
        if found: out.append((j1, true_tokens[found[0]:found[1]]))
    return out

def apply_repeats(true_tokens: list[str], insertions: list[tuple[int, list[str]]]) -> list[str]:
    for pos, tokens in sorted(insertions, key=lambda x: -x[0]):
        true_tokens = true_tokens[:pos] + list(tokens) + true_tokens[pos:]
    return true_tokens

def fill_gaps(entries: list[dict], ctx: dict) -> list[dict]:
    """Every 'inserted' entry without a seed time gets one, placed only inside sung stretches between its
    neighbours' times and never past the end of the last sung stretch; realign() snaps it to the nearest vocal onset
    afterwards. A group of entries is spread proportionally to the sung time available, not linearly across the raw
    gap (which can run through long silences). Never touches an entry that already has a time."""
    regions, duration = ctx['regions'], ctx['duration']
    last_voice_end = regions[-1][1] if regions else duration
    n = len(entries); i = 0
    while i < n:
        if entries[i]['a'] is not None: i += 1; continue
        j = i
        while j < n and entries[j]['a'] is None: j += 1
        prev_t = entries[i - 1]['a'] if i > 0 else 0.0
        next_t = entries[j]['a'] if j < n else last_voice_end
        if next_t > last_voice_end: next_t = last_voice_end
        if next_t <= prev_t: next_t = min(prev_t + .05 * (j - i + 1), last_voice_end)
        if next_t <= prev_t: next_t = prev_t + .01   # every sung stretch already behind us: keep entries ordered
        span_regions = [(max(a, prev_t), min(b, next_t)) for a, b in regions if b > prev_t and a < next_t]
        if not span_regions: span_regions = [(prev_t, next_t)]
        total = sum(b - a for a, b in span_regions) or 1e-6
        count = j - i
        for k, idx in enumerate(range(i, j)):
            target = total * (k + 1) / (count + 1)
            t, run = prev_t, 0.0
            for a, b in span_regions:
                seg = b - a
                if run + seg >= target: t = a + (target - run); break
                run += seg; t = b
            entries[idx]['a'] = round(t, 3)
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

# ---------------------------------------------------------------- completeness and placement checks
def completeness_issues(asr_words: list[dict], entries: list[dict]) -> list[str]:
    """Signs that the source text is missing a section, not just imperfectly matched: a long contiguous run of
    dropped ASR words, or matched text that stops well before the heard transcript does."""
    kept = sorted(e['src'] for e in entries if e['src'] is not None)
    issues, prev = [], -1
    for idx in kept + [len(asr_words)]:
        if idx - prev > 1:
            i1, i2 = prev + 1, idx
            span = asr_words[i2 - 1]['b'] - asr_words[i1]['a']
            if span >= DROP_RUN_SECONDS:
                issues.append(f'{i2 - i1} words dropped in a row, spanning {span:.1f}s of sung time')
        prev = idx
    if kept:
        tail = asr_words[-1]['b'] - asr_words[kept[-1]]['b']
        if tail >= TAIL_GAP_SECONDS:
            issues.append(f'the matched text ends {tail:.1f}s before the heard transcript does')
    return issues

def placement_issues(entries: list[dict], flat_words: list[dict], ctx: dict) -> tuple[int, int]:
    """How many inserted words ended up off a vocal onset, and how many landed outside the sung voice entirely."""
    v, onsets = ctx['voiced'], ctx['onsets']
    off_onset = in_silence = 0
    for e, w in zip(entries, flat_words):
        if e['kind'] != 'inserted': continue
        if not len(onsets) or min(abs(w['a'] - o) for o in onsets) > .05: off_onset += 1
        idx = int(w['a'] / al.HOP)
        if idx < 0 or idx >= len(v) or not v[idx]: in_silence += 1
    return off_onset, in_silence

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
            'words_dropped': dropped, 'wer_before': word_error_rate(a_norm, t_norm),
            'median_shift_changed_s': round(float(np.median(shifts)), 3) if shifts else 0.0, 'lines': len(lines)}

# ---------------------------------------------------------------- safety guard
def audio_fingerprint(pkg: Path) -> dict:
    return {p.name: sha256(p) for p in sorted(pkg.iterdir()) if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS}

def strip_lyrics(song: dict) -> dict:
    return {k: v for k, v in song.items() if k not in LYRICS_FIELDS}

def verify_guard(pkg: Path, before_song: dict, after_song: dict, before_audio: dict, after_audio: dict) -> None:
    """`before_song`/`after_song` must already have the lyrics fields stripped and, critically, must come from two
    independent reads of the JSON (never a shallow copy of the same in-memory object), so a nested field mutated in
    place anywhere else can't be invisible to both sides at once."""
    changed = sorted(k for k in set(before_song) | set(after_song) if before_song.get(k) != after_song.get(k))
    if changed:
        raise SystemExit(f'{pkg.name}: safety guard tripped, target.json changed outside lyrics: {changed}')
    if before_audio != after_audio:
        raise SystemExit(f'{pkg.name}: safety guard tripped, an audio file changed or went missing')

def corrected_note(existing: str, src: str) -> str:
    base = (existing or 'Soniox stt-async-v5').split('; corrected to published lyrics')[0]
    return base + f'; corrected to published lyrics from the {src} transcript (lyrics_text.py)'

# ---------------------------------------------------------------- package plumbing
def process_package(pkg: Path, text_file: str | None, write: bool, rebuild: bool = True, prefer: str = 'auto',
                     force: bool = False) -> dict:
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
    asr_lines, asr_src = resolve_transcript(pkg, song, prefer)
    asr_words = al.flat(asr_lines)
    raw_text, text_note, cache_meta = resolve_source_text(pkg, text_file)
    true_tokens = tokenize(raw_text)
    if not true_tokens: raise LyricsSourceError(f'{pkg.name}: no words found in the lyrics source')
    ctx = al.context(pkg, song)
    entries = match_words(asr_words, true_tokens)
    insertions = repeated_insertions(asr_words, true_tokens)
    if insertions:
        true_tokens = apply_repeats(true_tokens, insertions)
        entries = match_words(asr_words, true_tokens)
    entries = fill_gaps(entries, ctx)
    lines = al.realign(seed_words(entries, asr_words), ctx)
    assert [w['w'] for w in al.flat(lines)] == true_tokens, 'the true lyric text must survive re-alignment untouched'
    agreement = al.agreement(asr_words, [{'w': t} for t in true_tokens])
    conf = confidence(agreement['agreement_pct'], len(asr_words), len(true_tokens))
    off_onset, in_silence = placement_issues(entries, al.flat(lines), ctx)
    issues = completeness_issues(asr_words, entries)
    if in_silence: issues.append(f'{in_silence} inserted word(s) fall in silence outside the sung voice')
    out = {'package': pkg.name, 'asr_source': asr_src, 'lyrics_source': text_note, 'confidence': conf,
           'agreement_pct': agreement['agreement_pct'], 'words_inserted_off_onset': off_onset,
           'words_inserted_in_silence': in_silence, 'repeated_sections_recovered': len(insertions),
           **report_metrics(asr_words, true_tokens, entries, lines)}
    if write:
        if conf == 'low':
            out['skipped'] = 'low confidence that the lyrics source matches this recording; left untouched'
            return out
        if issues and not force:
            out['skipped'] = 'incomplete source: ' + '; '.join(issues) + ' (use --force to override)'
            return out
        before_audio = audio_fingerprint(pkg)
        before_snapshot = strip_lyrics(json.loads((pkg / 'target.json').read_text(encoding='utf-8')))
        note = corrected_note(song.get('lyricsSource') or '', asr_src)
        song['lyrics'] = lines; song['lyricsSource'] = note
        tmp = pkg / 'target.json.tmp'
        tmp.write_text(json.dumps(song, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        after_snapshot = strip_lyrics(json.loads(tmp.read_text(encoding='utf-8')))
        verify_guard(pkg, before_snapshot, after_snapshot, before_audio, audio_fingerprint(pkg))
        tmp.replace(pkg / 'target.json')
        if cache_meta is not None:
            cache_dir = pkg / 'lyrics'; cache_dir.mkdir(exist_ok=True)
            (cache_dir / 'source.txt').write_text(raw_text, encoding='utf-8')
            (cache_dir / 'source.meta.json').write_text(json.dumps(cache_meta, ensure_ascii=False), encoding='utf-8')
        if rebuild: out['html'] = str(al.build_html(pkg, pkg.parent / f'Luma_{pkg.name}.html'))
    return out

def human(r: dict) -> str:
    if 'error' in r: return f"{r['package']}: {r['error']}"
    if r.get('skipped'): return f"{r['package']}: {r['skipped']} (confidence {r['confidence']}, agreement {r['agreement_pct']}%)"
    return (f"{r['package']}: {r['words_true']} true words ({r['words_changed']} changed, {r['words_added']} added, "
            f"{r['words_dropped']} dropped from the ASR transcript), WER against the true text {r['wer_before']}, "
            f"median timing shift of changed words {r['median_shift_changed_s']:.2f} s, "
            f"confidence {r['confidence']} (agreement {r['agreement_pct']}%), lyrics source: {r['lyrics_source']}, "
            f"inserted words off onset {r['words_inserted_off_onset']}, in silence {r['words_inserted_in_silence']}, "
            f"repeated sections recovered {r['repeated_sections_recovered']}")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+')
    ap.add_argument('--text', help='lyrics file to use instead of fetching (only with a single package)')
    ap.add_argument('--from', dest='prefer', default='auto', choices=['auto', 'vocal', 'mix'],
                     help='which stored transcript to correct against (default: the one the song is already published from)')
    ap.add_argument('--force', action='store_true', help='write even when the completeness check would otherwise refuse')
    ap.add_argument('-n', '--dry-run', action='store_true', help='report only, write nothing')
    ap.add_argument('--json', action='store_true', help='print the report as JSON')
    ap.add_argument('--no-html', action='store_true', help='update target.json but do not rebuild the trainer')
    a = ap.parse_args()
    if a.text and len(a.package) > 1: ap.error('--text applies to a single package')
    report = []
    for p in a.package:
        pkg = Path(p).expanduser().resolve()
        try:
            r = process_package(pkg, a.text, write=not a.dry_run, rebuild=not a.no_html, prefer=a.prefer, force=a.force)
        except LyricsSourceError as e:
            r = {'package': pkg.name, 'error': str(e)}
        report.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else human(r))
        if not a.dry_run and 'html' in r: print(f"  wrote {pkg / 'target.json'} and rebuilt {r['html']}")
    return report

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: sys.exit(130)
