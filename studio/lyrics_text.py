#!/usr/bin/env python3
"""Replace misheard word text with the real lyrics, keeping every word on the voice it was already snapped to.

  lyrics_text.py <package_dir>...             fetch/reuse the published lyrics, correct the text, rebuild the HTML
  lyrics_text.py --text lyrics.txt <package>  use lyrics supplied by the operator instead of fetching them
  lyrics_text.py --from mix|vocal <package>   correct against a specific stored transcript instead of the one the
                                               song is already published from
  lyrics_text.py --force <package>            write even when the gate would otherwise refuse
  lyrics_text.py --dry-run <package_dir>...   report what would change and write nothing
  lyrics_text.py --dry-run --json <pkg>...    the same report as machine-readable metrics

The ASR words in <package>/lyrics/{mix,vocal}.json are the only input read and are never modified, so every run
re-derives its output from the same source and two runs in a row are byte-identical. Correction starts from
whichever transcript the song is already published from (the 'vocal stem' marker in lyricsSource is the signal, or
--from to say so explicitly) — a song deliberately kept on the mix transcript never silently jumps to the other one.

build_correction() is the one path from a lyrics source to seeded, realigned lines: align_lyrics.py and the vocal
retranscription command call it too (replaying from the transcript the song is already published from, not
whichever one a plain re-align would otherwise default to), so a realignment or a fresh transcription can never
regress a correction back to the raw ASR transcript, and never applies one that would make things worse either. The
true lyric text is sequence-aligned against the normalized ASR words: a matched word keeps the ASR timing, a
substituted word takes the timing of the word(s) it replaces, a true word with no ASR counterpart gets its start
interpolated inside the nearest sung stretch when there is one (off the voice entirely, clustered right after the
previous word, only when there is none at all), and a heard word with no true counterpart is dropped — unless it is
part of a run that repeats a span already used elsewhere in the true text (a chorus the source only writes out
once, from either end of the run, whichever agrees better), in which case that span is duplicated back in rather
than losing the words. Word order never changes within the true text as given; repeats are the one place new text
is added, and only text already present elsewhere in the same source. Seeded words are handed to
align_lyrics.realign(), which snaps every start to a vocal onset and groups lines by real vocal silence.

Before writing, the gate compares align_lyrics.metrics() for the corrected lines against the lines already
published: it refuses (or, with --force, warns and proceeds) when the correction would leave more than
UNCOVERED_TOLERANCE_S seconds more of the singing uncovered, or open a silent hole that wasn't there before — a sign
the source text doesn't actually match what's sung, not just imperfectly. Low agreement with the ASR transcript
refuses outright, same as before. Placement is checked separately, on the realigned words: an inserted word landing
off the sung voice, one landing within MIN_INSERTED_SPACING_S of a neighbour (the onset detector's own dedup
window — not a real, distinguishable placement), or a correction that grows metrics()['flashing_words'] by more
than FLASHING_WORDS_TOLERANCE also refuses; spacing tighter than MIN_WORD_SPACING_S but past that 50ms line is only
reported, since a crowded sung stretch can genuinely leave no better placement. Every reason that applies is named
in the refusal, not just the first one found.

Fetching is a single free lookup (api.lyrics.ovh, no key) keyed by the title/artist in <package>/manifest.json. The
raw text — fetched or operator-supplied — is cached in <package>/lyrics/source.txt (with the title/artist it was
fetched for, in lyrics/source.meta.json) once a run actually writes it, so a second run needs no network and a
changed manifest title/artist is not silently served the old text. A source that fails the gate is never cached,
unless the operator forces the write through with --force, which caches it like any other write.

Safety guard: target.json fields other than `lyrics`/`lyricsSource`, and every audio file in the package, must stay
byte-for-byte identical to before the run; a change trips a loud failure instead of a silent write. The "before"
snapshot is re-read from disk immediately ahead of the write, never kept from the object this script itself loaded
and may have handed off elsewhere, so an in-place mutation to a nested field can't hide from the comparison.
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
GUESS_SPAN = .15          # placeholder duration for an inserted word before realign() fits it to the voice
MIN_REPEAT_WORDS = 4      # a leftover run shorter than this is more likely noise than a missed repeat
MIN_REPEAT_SECONDS = 2.0  # ...and one covering less sung time than this isn't worth searching for
REPEAT_MATCH_RATIO = .7   # how similar a candidate span must be to the leftover run to count as the same text
MAX_REPEAT_ROUNDS = 5     # a song can repeat a chorus more than once; keep restoring until nothing new is found
SILENCE_MARGIN_S = .05    # an onset this much before a voice region still counts as landing on the voice — the
                           # same early-onset margin align_lyrics.onsets() accepts when snapping
MIN_WORD_SPACING_S = .18  # inserted words closer together than this aren't real, distinguishable placements
UNCOVERED_TOLERANCE_S = 6.0   # a correction may leave up to this many more seconds of singing uncovered than the
                               # lyrics already published before the gate refuses it
MIN_INSERTED_SPACING_S = .05  # onset candidates closer than this are one attack (align_lyrics.onsets' own dedup
                               # window): an inserted word landing this close to a neighbour, after realignment, is
                               # not a placement at all, just the harm gate's squeeze packing words onto the voice
FLASHING_WORDS_TOLERANCE = 5  # a correction may add up to this many more flashing words (align_lyrics.metrics) than
                               # the lyrics already published before the gate refuses it as a placement fault, even
                               # when no single gap trips the 50ms check above

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

def _manifest_title_artist(pkg: Path) -> tuple[str, str]:
    manifest_path = pkg / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    return manifest.get('title') or '', manifest.get('artist') or ''

def cached_source_text(pkg: Path) -> str | None:
    """The cached lyrics source for this package if the manifest still matches what it was fetched for — otherwise
    None. Never fetches, never touches the network: the safe, read-only source align_lyrics.py and the vocal
    retranscription command use to replay a correction."""
    cache, meta_path = pkg / 'lyrics' / 'source.txt', pkg / 'lyrics' / 'source.meta.json'
    if not (cache.exists() and meta_path.exists()): return None
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    title, artist = _manifest_title_artist(pkg)
    if meta.get('title') != title or meta.get('artist') != artist: return None
    return cache.read_text(encoding='utf-8')

def resolve_source_text(pkg: Path, text_file: str | None) -> tuple[str, str, dict | None]:
    """The raw lyric text to use, a short note of where it came from, and — only when the source should be cached
    once the run is confirmed to write — the manifest title/artist it was fetched or supplied for. None means
    nothing new needs caching: a cache hit whose stored title/artist still matches the manifest, or an
    operator-supplied file with no manifest to validate a cache against. Never touches the network before checking
    the cache, and never writes anything itself."""
    title, artist = _manifest_title_artist(pkg)
    if text_file:
        text = Path(text_file).expanduser().read_text(encoding='utf-8')
        meta = {'title': title, 'artist': artist} if title else None
        return text, f'operator-supplied lyrics ({Path(text_file).name})', meta
    cached = cached_source_text(pkg)
    if cached is not None: return cached, 'cached lyrics (lyrics/source.txt)', None
    manifest_path = pkg / 'manifest.json'
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
    true lyrics and never changes. When one heard word stands for several true words, each of the extra ones is left
    with no seed time (kind 'inserted'), so fill_gaps places it inside the actual sung voice around it instead of a
    blind interpolation across the whole replaced span."""
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
            # when na > nt, the na - k leftover heard words (i1+k .. i2) have no true counterpart in this pass —
            # find_leftover_runs() below picks them up as repeat candidates, same as a pure 'delete'
        elif tag == 'insert':
            for x in range(j1, j2):
                out[x] = {'w': true_tokens[x], 'a': None, 'kind': 'inserted', 'src': None}
        # 'delete': the ASR words in that range simply have no true counterpart in this pass
    return out   # type: ignore[return-value]

def find_leftover_runs(asr_words: list[dict], true_tokens: list[str]) -> list[tuple[tuple[int, int, int], ...]]:
    """Every contiguous stretch of heard words this pass of matching has no place for, grouped by the opcode it
    came from. A 'delete' opcode has one candidate: (asr_start, asr_end, true_position). A 'replace' opcode with
    leftover heard words has two mirror candidates — the leftover taken from the tail once the first few heard
    words have taken the true words there (inserting at the block's end), and taken from the head instead, letting
    the true words there be taken by the *last* few heard words (inserting at its start). Which side the leftover
    actually belongs to depends only on whether the shared word at the seam happens to land on the first or the
    last section — repeated_insertions() tries both and keeps whichever agrees better with the true text."""
    a_norm = [al.norm(w['w']) for w in asr_words]; t_norm = [al.norm(t) for t in true_tokens]
    sm = difflib.SequenceMatcher(a=a_norm, b=t_norm, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'delete':
            out.append(((i1, i2, j1),))
        elif tag == 'replace':
            na, nt = i2 - i1, j2 - j1
            if na > nt: out.append(((i1 + nt, i2, j2), (i1, i1 + (na - nt), j1)))
    return out

def find_repeated_span(leftover_norm: list[str], t_norm: list[str]) -> tuple[int, int, float] | None:
    """A span in the true text whose words are (almost) the same as a *prefix* of this leftover heard run — the
    prefix is a repeat of that span (e.g. a chorus written out once but sung twice), not padding that should be
    dropped. Matching a prefix rather than the whole run handles both a single repeat with one missing or extra
    word at the seam, and several repeats concatenated into one leftover run (restore_repeats() recovers the rest
    on its next pass, once the first one is spliced back in and the run shrinks). The agreement ratio is returned
    too, so a caller weighing this candidate against a mirror one can keep whichever fits better."""
    max_len = min(len(t_norm), len(leftover_norm))
    for span_len in range(max_len, MIN_REPEAT_WORDS - 1, -1):   # longest prefix first, and never a span so short it's
                                                                 # more likely noise than a missed repeat
        prefix = leftover_norm[:span_len]
        best = None
        for start in range(len(t_norm) - span_len + 1):
            window = t_norm[start:start + span_len]
            ratio = difflib.SequenceMatcher(a=window, b=prefix, autojunk=False).ratio()
            if ratio >= REPEAT_MATCH_RATIO and (best is None or ratio > best[1]):
                best = (start, ratio)
        if best is not None: return (best[0], best[0] + span_len, best[1])
    return None

def repeated_insertions(asr_words: list[dict], true_tokens: list[str]) -> list[tuple[int, list[str]]]:
    """Leftover heard runs that are (almost) the same text as a span already used elsewhere in the true lyrics.
    Returns (position in true_tokens, tokens to duplicate there), so the caller can splice the repeat back into the
    true text instead of silently losing the words. When a 'replace' block offers two mirror candidates (the
    leftover taken from its head or its tail), only the one with the higher agreement ratio is kept — never both,
    which would duplicate the same repeat twice."""
    a_norm = [al.norm(w['w']) for w in asr_words]; t_norm = [al.norm(t) for t in true_tokens]
    out = []
    for candidates in find_leftover_runs(asr_words, true_tokens):
        best = None   # (pos, tokens, ratio)
        for i1, i2, pos in candidates:
            if i2 - i1 < MIN_REPEAT_WORDS: continue
            if asr_words[i2 - 1]['b'] - asr_words[i1]['a'] < MIN_REPEAT_SECONDS: continue
            found = find_repeated_span(a_norm[i1:i2], t_norm)
            if found and (best is None or found[2] > best[2]):
                best = (pos, true_tokens[found[0]:found[1]], found[2])
        if best is not None: out.append((best[0], best[1]))
    return out

def apply_repeats(true_tokens: list[str], insertions: list[tuple[int, list[str]]]) -> list[str]:
    for pos, tokens in sorted(insertions, key=lambda x: -x[0]):
        true_tokens = true_tokens[:pos] + list(tokens) + true_tokens[pos:]
    return true_tokens

def restore_repeats(asr_words: list[dict], true_tokens: list[str]) -> tuple[list[str], list[dict], int]:
    """Matches, then repeatedly looks for a leftover run that repeats an earlier span and splices it back in,
    re-matching each time — a song can repeat a chorus more than once — until nothing new is found or the round cap
    is hit. Returns the (possibly extended) true tokens, the final match entries, and how many spans were restored."""
    entries = match_words(asr_words, true_tokens)
    restored = 0
    for _ in range(MAX_REPEAT_ROUNDS):
        insertions = repeated_insertions(asr_words, true_tokens)
        if not insertions: break
        true_tokens = apply_repeats(true_tokens, insertions)
        entries = match_words(asr_words, true_tokens)
        restored += len(insertions)
    return true_tokens, entries, restored

def fill_gaps(entries: list[dict], ctx: dict) -> list[dict]:
    """Every 'inserted' entry without a seed time gets one, placed only inside sung stretches between its
    neighbours' times and never past the end of the last sung stretch; realign() snaps it to the nearest vocal onset
    afterwards. A group of entries is spread proportionally to the sung time available, not linearly across the raw
    gap (which can run through long silences), and never closer together than MIN_WORD_SPACING_S. When there is no
    sung time at all between the neighbours, the group is clustered right after the previous one instead of spread
    blindly across the silence — still off the voice, but not scattered to an arbitrary point in the gap. Never
    touches an entry that already has a time."""
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
        count = j - i
        span_regions = [(max(a, prev_t), min(b, next_t)) for a, b in regions if b > prev_t and a < next_t] if next_t > prev_t else []
        if not span_regions:
            for k, idx in enumerate(range(i, j)):
                entries[idx]['a'] = round(min(prev_t + MIN_WORD_SPACING_S * (k + 1), max(next_t, prev_t)), 3)
            i = j; continue
        total = sum(b - a for a, b in span_regions)
        placed = []
        for k in range(count):
            target = total * (k + 1) / (count + 1)
            t, run = prev_t, 0.0
            for a, b in span_regions:
                seg = b - a
                if run + seg >= target: t = a + (target - run); break
                run += seg; t = b
            placed.append(t)
        if total >= count * MIN_WORD_SPACING_S:   # only worth enforcing when the window can actually fit it —
            for k in range(1, len(placed)):       # otherwise forcing it would push later words past the window
                if placed[k] - placed[k - 1] < MIN_WORD_SPACING_S: placed[k] = placed[k - 1] + MIN_WORD_SPACING_S
        for k, idx in enumerate(range(i, j)): entries[idx]['a'] = round(min(placed[k], next_t), 3)
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

# ---------------------------------------------------------------- placement and harm checks
def in_voice(t: float, ctx: dict, margin: float = SILENCE_MARGIN_S) -> bool:
    """Whether a word starting at `t` lands on the sung voice, allowing the same early-onset margin the onset
    detector itself accepts when snapping a word to an onset just before a voice region begins — checked across the
    whole margin window, not a single frame, so a word landing a couple of milliseconds past the edge of that
    window still counts."""
    v = ctx['voiced']
    lo, hi = int(round(t / al.HOP)), int(round((t + margin) / al.HOP))
    lo, hi = max(0, lo), min(len(v) - 1, hi)
    return lo <= hi and bool(v[lo:hi + 1].any())

def placement_problems(entries: list[dict], flat_words: list[dict], ctx: dict,
                        before_metrics: dict | None = None, after_metrics: dict | None = None) -> tuple[list[str], list[str]]:
    """Three placement faults, all measured on the realigned words (flat_words), never a pre-snap estimate:

    - an inserted word off the sung voice — always worth refusing over;
    - an inserted word starting within MIN_INSERTED_SPACING_S of a neighbour (either side, any kind) — the onset
      detector's own dedup window (align_lyrics.onsets), so no two distinguishable placements can really be this
      close; this is the harm gate's squeeze packing words onto the voice to shrink uncovered_seconds, not a
      legitimate crowded phrase, and blocks the write;
    - a correction that grows metrics()['flashing_words'] by more than FLASHING_WORDS_TOLERANCE — the same squeeze
      tallied by word visibility instead of gap size, catching a crowd that stays just past the 50ms line but is
      still unreadable end to end.

    Separately, inserted words packed closer together than MIN_WORD_SPACING_S but not within the 50ms line above
    are only ever informational: when a large block of words has to share a short sung stretch, no placement can
    keep them that far apart, so it is reported but does not by itself block the write.

    Returns (blocking, informational)."""
    blocking, info = [], []
    off_voice = sum(1 for e, w in zip(entries, flat_words) if e['kind'] == 'inserted' and not in_voice(w['a'], ctx))
    if off_voice: blocking.append(f'{off_voice} inserted word(s) placed off the sung voice')
    crowded = 0
    for i, e in enumerate(entries):
        if e['kind'] != 'inserted': continue
        near_prev = i > 0 and flat_words[i]['a'] - flat_words[i - 1]['a'] < MIN_INSERTED_SPACING_S
        near_next = i + 1 < len(flat_words) and flat_words[i + 1]['a'] - flat_words[i]['a'] < MIN_INSERTED_SPACING_S
        if near_prev or near_next: crowded += 1
    if crowded: blocking.append(f'{crowded} inserted word(s) placed within {MIN_INSERTED_SPACING_S}s of a neighbour')
    if before_metrics is not None and after_metrics is not None:
        grown = after_metrics['flashing_words'] - before_metrics['flashing_words']
        if grown > FLASHING_WORDS_TOLERANCE:
            blocking.append(f'flashing words grew by {grown} (tolerance {FLASHING_WORDS_TOLERANCE})')
    # only two words the placer itself just chose a time for are checked — real fast singing can legitimately
    # place ASR-anchored (matched/substituted) words closer together than this
    close = sum(1 for ea, eb, a, b in zip(entries, entries[1:], flat_words, flat_words[1:])
                if ea['kind'] == 'inserted' and eb['kind'] == 'inserted' and MIN_INSERTED_SPACING_S <= b['a'] - a['a'] < MIN_WORD_SPACING_S)
    if close: info.append(f'{close} inserted word(s) placed less than {MIN_WORD_SPACING_S}s apart')
    return blocking, info

def gate_verdict(conf: str, before_metrics: dict | None, after_metrics: dict) -> tuple[bool, str | None]:
    """Whether writing the correction would make the song worse than what's already published, judged the way the
    numbers are actually measured (align_lyrics.metrics()) rather than a re-derived estimate."""
    if conf == 'low':
        return False, 'low confidence that the lyrics source matches this recording'
    if before_metrics is None: return True, None
    grown = round(after_metrics['uncovered_seconds'] - before_metrics['uncovered_seconds'], 1)
    new_holes = after_metrics['silent_holes'] > before_metrics['silent_holes']
    if grown > UNCOVERED_TOLERANCE_S or new_holes:
        msg = f'would leave {grown:.1f}s more of the singing uncovered than the lyrics published now'
        if new_holes: msg += ' and opens a silent hole that is not there now'
        return False, msg
    return True, None

# ---------------------------------------------------------------- the shared correction pipeline
def build_correction(pkg: Path, song: dict, asr_words: list[dict], ctx: dict, raw_text: str, asr_src: str) -> dict:
    """The one path from a lyrics source to seeded, realigned lines, used by lyrics_text.py, align_lyrics.py and the
    vocal retranscription command alike, so a realignment or a fresh transcription always runs the same checks a
    direct correction would and never regresses or over-applies one."""
    true_tokens = tokenize(raw_text)
    if not true_tokens: raise LyricsSourceError(f'{pkg.name}: no words found in the lyrics source')
    true_tokens, entries, repeats_restored = restore_repeats(asr_words, true_tokens)
    entries = fill_gaps(entries, ctx)
    seed = seed_words(entries, asr_words)
    lines = al.realign(seed, ctx)
    assert [w['w'] for w in al.flat(lines)] == true_tokens, 'the true lyric text must survive re-alignment untouched'
    agreement = al.agreement(asr_words, [{'w': t} for t in true_tokens])
    conf = confidence(agreement['agreement_pct'], len(asr_words), len(true_tokens))
    before_lines = song.get('lyrics') or []
    before_m = al.metrics(before_lines, ctx) if before_lines else None
    after_m = al.metrics(lines, ctx)
    passed, reason = gate_verdict(conf, before_m, after_m)
    blocking, info = placement_problems(entries, al.flat(lines), ctx, before_m, after_m)
    # every blocking reason is named, not just the first one found: a harm-gate refusal and a placement refusal can
    # both apply to the same correction, and an operator deciding whether --force is safe needs to see both
    reasons = ([reason] if reason else []) + (['placement: ' + '; '.join(blocking)] if blocking else [])
    if reasons: passed, reason = False, '; '.join(reasons)
    return {'true_tokens': true_tokens, 'entries': entries, 'seed': seed, 'lines': lines, 'confidence': conf,
            'agreement_pct': agreement['agreement_pct'], 'repeats_restored': repeats_restored,
            'before_metrics': before_m, 'after_metrics': after_m, 'passed': passed, 'reason': reason,
            'placement_problems': blocking + info, 'asr_source': asr_src}

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
    ctx = al.context(pkg, song)
    c = build_correction(pkg, song, asr_words, ctx, raw_text, asr_src)
    out = {'package': pkg.name, 'asr_source': c['asr_source'], 'lyrics_source': text_note, 'confidence': c['confidence'],
           'agreement_pct': c['agreement_pct'], 'repeated_sections_recovered': c['repeats_restored'],
           'placement_problems': c['placement_problems'],
           **report_metrics(asr_words, c['true_tokens'], c['entries'], c['lines'])}
    if not c['passed']:
        out['skipped'] = c['reason'] + ' (use --force to override)'
    if write and (c['passed'] or force):
        before_audio = audio_fingerprint(pkg)
        before_snapshot = strip_lyrics(json.loads((pkg / 'target.json').read_text(encoding='utf-8')))
        note = corrected_note(song.get('lyricsSource') or '', c['asr_source'])
        song['lyrics'] = c['lines']; song['lyricsSource'] = note
        tmp = pkg / 'target.json.tmp'
        try:
            tmp.write_text(json.dumps(song, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            after_snapshot = strip_lyrics(json.loads(tmp.read_text(encoding='utf-8')))
            verify_guard(pkg, before_snapshot, after_snapshot, before_audio, audio_fingerprint(pkg))
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(pkg / 'target.json')
        out.pop('skipped', None)
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
            f"placement problems: {'; '.join(r['placement_problems']) or 'none'}, "
            f"repeated sections recovered {r['repeated_sections_recovered']}")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+')
    ap.add_argument('--text', help='lyrics file to use instead of fetching (only with a single package)')
    ap.add_argument('--from', dest='prefer', default='auto', choices=['auto', 'vocal', 'mix'],
                     help='which stored transcript to correct against (default: the one the song is already published from)')
    ap.add_argument('--force', action='store_true', help='write even when the gate would otherwise refuse')
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
