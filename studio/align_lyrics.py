#!/usr/bin/env python3
"""Put lyric words where the voice actually sings them. Offline: no network call and no paid API — everything needed
is already in the song package, the Demucs vocal stem (vocals_44k.flac) and the pitch map in target.json.

  align_lyrics.py <package_dir>...              re-align words and lines in place, then rebuild the trainer HTML
  align_lyrics.py --dry-run <package_dir>...    report what would change and write nothing
  align_lyrics.py --dry-run --json <pkg>...     the same report as machine-readable metrics
  align_lyrics.py --from mix <package_dir>...   re-align the stored mix transcript instead of the vocal-stem one

Word starts are snapped to vocal onsets inside a bounded window, word order and word count never change, no word
crosses a neighbour and the transcript text is kept letter for letter. Lines are broken at real silences of the
voice. Audio, notes, phrases, ids and every other field of target.json stay byte-for-byte as they were.

The transcript as it arrived from Soniox is kept in <package>/lyrics/{mix,vocal}.json, so re-aligning twice gives
exactly the same result and never compounds.
"""
from __future__ import annotations
import argparse, difflib, json, sys
from pathlib import Path
import numpy as np, soundfile as sf, librosa

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'studio'))
from build_html import build as build_html

HOP = .01        # analysis frame step, seconds
SNAP = .35       # how far a word start may travel to reach an onset
SKIP = .30       # cost of leaving a word (or an onset) unmatched, in the same units as the distance
GAP = .25        # a silence of the voice at least this long is a real phrase boundary
MIN_DUR = .18    # shortest word we keep (the trainer lights a word for .08 s more)
MAX_DUR = 1.5    # longest word we keep; merged Soniox tokens can claim tens of seconds
MAX_WORDS = 9    # longest line when the voice never pauses
HOLE = 2.0       # a stretch this long without a single word breaks the line even when the voice never stops
LEAD = .08       # a word always ends this long before the next one starts

# ---------------------------------------------------------------- vocal stem: energy, voiced frames, onsets
def runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(int))); return list(zip(edges[::2], edges[1::2]))

def stem(path: Path):
    """Mono vocal stem: frame energy in dB on the HOP grid, plus a 22 kHz copy for onset detection."""
    y, sr = sf.read(path, dtype='float32', always_2d=True); m = y.mean(1)
    hop = int(round(sr * HOP)); flen = int(round(sr * .032)); n = 1 + (len(m) - flen) // hop; rms = np.empty(n)
    for i in range(0, n, 20000):
        j = min(n, i + 20000); ix = np.arange(i, j)[:, None] * hop + np.arange(flen)[None, :]
        rms[i:j] = np.sqrt((m[ix] ** 2).mean(1))
    return 20 * np.log10(rms + 1e-12), librosa.resample(m, orig_sr=sr, target_sr=22050), 22050, len(m) / sr

def voiced(db, song, energy_off=-24, grow=.20, close=.12, min_run=.12):
    """Voiced frames = the pipeline's own pitch decision, grown over adjacent loud frames so a region starts at the
    audible attack and not at the pitch. Energy alone cannot seed this: Demucs stems carry constant instrument bleed."""
    pitched = np.array([p[1] is not None for p in song['points']])
    ix = np.clip((np.arange(len(db)) * HOP / song.get('hop', .02)).astype(int), 0, len(pitched) - 1)
    core = pitched[ix]; loud = db > np.percentile(db, 95) + energy_off; keep = core.copy(); g = int(round(grow / HOP))
    for a, b in runs(core):
        i = a
        while i > max(0, a - g) and loud[i - 1]: i -= 1
        keep[i:a] = True
        j = b
        while j < min(len(db), b + g) and loud[j]: j += 1
        keep[b:j] = True
    for a, b in runs(~keep):
        if (b - a) * HOP < close and a > 0 and b < len(keep): keep[a:b] = True
    for a, b in runs(keep):
        if (b - a) * HOP < min_run: keep[a:b] = False
    return keep

def regions(mask): return [(float(a * HOP), float(b * HOP)) for a, b in runs(mask)]

def sung_phrases(regs, gap=GAP):
    """Voiced regions closer than `gap` belong to one sung phrase; anything wider is a breath the singer takes."""
    out = []
    for a, b in regs:
        if out and a - out[-1][1] < gap: out[-1][1] = b
        else: out.append([a, b])
    return [tuple(p) for p in out]

def onsets(y, sr, v, song):
    """Onset candidates on the stem: spectral-flux attacks inside voiced regions, region starts, note re-attacks."""
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256, aggregate=np.median)
    fr = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=256, backtrack=True, units='frames',
                                    pre_max=3, post_max=3, pre_avg=10, post_avg=10, delta=.08, wait=3)
    regs = regions(v); flux = [float(t) for t in librosa.frames_to_time(fr, sr=sr, hop_length=256) if any(a - .05 <= t <= b for a, b in regs)]
    notes = [n['a'] for i, n in enumerate(song['notes']) if i == 0 or n['a'] - song['notes'][i - 1]['b'] >= .06]
    cands = sorted(set(round(float(x), 3) for x in flux + [a for a, _ in regs] + notes))
    out = cands[:1]
    for x in cands[1:]:                                   # candidates closer than 50 ms are one attack
        if x - out[-1] >= .05: out.append(x)
    return np.array(out)

def silence_between(v, t0, t1):
    """Longest stretch of non-voiced frames between two moments of the stem."""
    i = max(0, int(max(0., t0) / HOP)); j = min(len(v), max(i + 1, int(t1 / HOP)))
    return float(max((b - a for a, b in runs(~v[i:j])), default=0) * HOP)

# ---------------------------------------------------------------- monotone word -> onset matching
def dp_match(starts, cands, cap=SNAP, skip=SKIP):
    """Cheapest monotone assignment of word starts to onsets: words keep their order, each one gets at most one
    onset, and a word with no onset within `cap` stays unmatched. Returns an onset index or None per word.

    The row recurrence C[i,j] = min(C[i,j-1], C[i-1,j-1]+cost, C[i-1,j]+skip) is a running minimum along the row,
    so every row is one vectorised pass instead of a Python loop over the onsets."""
    n, m = len(starts), len(cands)
    if not n or not m: return [None] * n
    prev = np.zeros(m + 1); back = np.zeros((n + 1, m + 1), dtype=np.int8)   # 0 onset unused, 1 match, 2 word unmatched
    for i in range(1, n + 1):
        cost = np.abs(starts[i - 1] - cands); cost[cost > cap] = np.inf
        matched = prev[:-1] + cost; unmatched = prev[1:] + skip
        base = np.minimum(matched, unmatched); choice = np.where(matched <= unmatched, 1, 2)
        cur = np.empty(m + 1); cur[0] = prev[0] + skip
        cur[1:] = np.minimum(cur[0], np.minimum.accumulate(base))
        back[i, 1:] = np.where(cur[:-1] <= base, 0, choice); prev = cur
    out = [None] * n; i, j = n, m
    while i > 0:
        if j == 0: i -= 1; continue
        b = back[i, j]
        if b == 1: out[i - 1] = j - 1; i -= 1; j -= 1
        elif b == 2: i -= 1
        else: j -= 1
    return out

# ---------------------------------------------------------------- the re-alignment itself
def flat(lines): return [w for l in lines for w in l['words']]

def realign(words, ctx):
    """Words in, lines out. Only `a`, `b` and the grouping change; `w` and the order are carried over untouched."""
    v, o, dur = ctx['voiced'], ctx['onsets'], ctx['duration']
    ws = [dict(w) for w in words]
    if not ws: return []
    match = dp_match(np.array([w['a'] for w in ws], dtype=float), o)
    prev = -1e9
    for i, w in enumerate(ws):
        start = float(o[match[i]]) if match[i] is not None else float(w['a'])
        if start <= prev: start = prev + .02                      # order is never traded for a closer onset
        w['span'] = min(max(float(w['b']) - float(w['a']), MIN_DUR), MAX_DUR); w['a'] = round(start, 3); prev = start
    ra = np.array([r[0] for r in ctx['regions']] or [0.]); rb = np.array([r[1] for r in ctx['regions']] or [dur])
    for i, w in enumerate(ws):                                    # readable length, never into the next word
        nxt = ws[i + 1]['a'] if i + 1 < len(ws) else dur + LEAD
        k = int(np.searchsorted(ra, w['a'] + 1e-9)) - 1
        voice_end = float(rb[k]) if 0 <= k < len(rb) and rb[k] >= w['a'] else float(rb[min(k + 1, len(rb) - 1)])
        end = max(min(w['a'] + w['span'], voice_end + .12), w['a'] + MIN_DUR)   # a word is never lit past the voice singing it
        w['b'] = round(min(max(w['a'] + .06, min(end, nxt - LEAD)), nxt, dur), 3); w.pop('span')
    groups = [[ws[0]]]
    for a, b in zip(ws, ws[1:]):
        if silence_between(v, a['b'], b['a']) >= GAP or b['a'] - a['b'] > HOLE: groups.append([b])
        else: groups[-1].append(b)
    lines = []
    for g in groups:
        while len(g) > MAX_WORDS:                                 # legato run with no breath: cut at its widest gap
            k = max(range(1, MAX_WORDS + 1), key=lambda i: g[i]['a'] - g[i - 1]['b'])
            lines.append(g[:k]); g = g[k:]
        lines.append(g)
    return [{'a': round(g[0]['a'], 2), 'b': round(g[-1]['b'], 2), 'words': g} for g in lines]

def context(pkg: Path, song: dict) -> dict:
    db, y, sr, dur = stem(pkg / 'vocals_44k.flac')
    v = voiced(db, song); regs = regions(v)
    return {'voiced': v, 'regions': regs, 'phrases': sung_phrases(regs), 'onsets': onsets(y, sr, v, song),
            'notes': np.array(sorted(set(round(n['a'], 3) for n in song['notes']))), 'duration': min(dur, song['duration'])}

# ---------------------------------------------------------------- measurement
def stat(v):
    v = np.asarray(v, dtype=float)
    if not len(v): return {'n': 0}
    return {'n': len(v), 'med': round(float(np.median(v)), 3), 'p10': round(float(np.percentile(v, 10)), 3), 'p90': round(float(np.percentile(v, 90)), 3)}

def metrics(lines, ctx):
    """Everything the report and docs/LYRICS_TIMING.md quote, measured against the stem and the pitch map."""
    v, ph, o, notes, regs = ctx['voiced'], ctx['phrases'], ctx['onsets'], ctx['notes'], ctx['regions']
    ws = flat(lines); starts = np.array([w['a'] for w in ws], dtype=float)
    line_of = {id(w): i for i, l in enumerate(lines) for w in l['words']}
    def offsets(cands, cap=.8, skip=.6):
        mi = dp_match(starts, cands, cap, skip)
        return np.array([starts[i] - cands[j] for i, j in enumerate(mi) if j is not None]), sum(1 for j in mi if j is None)
    off, unmatched = offsets(o); offn, unmatched_notes = offsets(notes)
    swallowed = misassigned = breaks_in_voice = breaks_on_silence = 0
    for i in range(len(ws) - 1):
        gap = silence_between(v, ws[i]['b'], ws[i + 1]['a']) if ws[i + 1]['a'] > ws[i]['b'] else 0.
        same = line_of[id(ws[i])] == line_of[id(ws[i + 1])]
        if same and gap >= GAP: swallowed += 1; misassigned += 1          # a phrase boundary buried inside a line
        if not same: breaks_on_silence += gap >= GAP; breaks_in_voice += gap < GAP
    # first word of every sung phrase: how late it is, and whether the voice sang attacks before it
    lag, late_attacks = [], []
    for a, b in ph:
        inside = [w['a'] for w in ws if a <= w['a'] <= b]
        if not inside: continue
        lag.append(min(inside) - a); late_attacks.append(int(((o > a + .02) & (o < min(inside) - .12)).sum()))
    late_attacks = np.array(late_attacks)
    holes = [(a, b) for a, b in regs if b - a >= 1.2 and not any(a <= w['a'] <= b for w in ws)]
    # the other reading of "nothing moves on screen": singing that no word interval covers, however the words around
    # it are grouped. Stricter than `holes`, because a word only covers the moment it is actually lit.
    covered = np.zeros(len(v), dtype=bool)
    for w in ws: covered[max(0, int(w['a'] / HOP)):min(len(v), int(np.ceil(w['b'] / HOP)))] = True
    uncovered = [(a, b) for a, b in runs(v & ~covered) if (b - a) * HOP >= 1.2]
    merged = [(w['b'] - w['a'], silence_between(v, w['a'], w['b'])) for w in ws if silence_between(v, w['a'], w['b']) >= GAP]
    # `onset_error` is measured against the very onsets the aligner snaps to, so after alignment it is zero by
    # construction and says nothing. `*_pitchmap` repeats the same measurement against the note starts of the pitch
    # map — a signal the aligner never reads — and that is the number the report quotes.
    return {'words': len(ws), 'lines': len(lines), 'onset_error': stat(off), 'onset_error_pitchmap': stat(offn),
            'off_over_100ms': round(float((np.abs(off) > .1).mean()), 3) if len(off) else None,
            'off_over_100ms_pitchmap': round(float((np.abs(offn) > .1).mean()), 3) if len(offn) else None,
            'unmatched_words': unmatched, 'unmatched_words_pitchmap': unmatched_notes,
            'phrase_lag': stat(lag), 'phrase_boundaries': len(lag), '_lag': [round(float(x), 4) for x in lag],
            'phrases_missing_first_syllables': int((late_attacks >= 1).sum()) if len(late_attacks) else 0,
            'boundary_misassignments': misassigned, 'breaks_on_silence': int(breaks_on_silence), 'breaks_inside_singing': int(breaks_in_voice),
            'silent_holes': len(holes), 'silent_hole_seconds': round(sum(b - a for a, b in holes), 1),
            'uncovered_stretches': len(uncovered), 'uncovered_seconds': round(sum(b - a for a, b in uncovered) * HOP, 1),
            'merged_words': len(merged), 'worst_merged_silence': round(float(max((s for _, s in merged), default=0)), 2),
            'flashing_words': sum(1 for w in ws if w['b'] + .08 - w['a'] < .25),
            'sung_coverage_pct': round(100 * sum(w['b'] - w['a'] for w in ws) / max(sum(b - a for a, b in regs), 1e-9), 1),
            'sung_seconds': round(sum(b - a for a, b in regs), 1), '_off_pitchmap': [round(float(x), 4) for x in offn]}

def norm(word): return ''.join(c for c in word.lower() if c.isalnum() or c == "'").strip("'")

def agreement(a_words, b_words):
    """How much of the two transcripts is the same text, in the same order."""
    A = [norm(w['w']) for w in a_words]; B = [norm(w['w']) for w in b_words]
    shared = sum(bl.size for bl in difflib.SequenceMatcher(a=A, b=B, autojunk=False).get_matching_blocks())
    return {'words_a': len(A), 'words_b': len(B), 'shared': shared, 'only_a': len(A) - shared, 'only_b': len(B) - shared,
            'agreement_pct': round(200 * shared / max(len(A) + len(B), 1), 1)}

# ---------------------------------------------------------------- package plumbing
def transcript(pkg: Path, song: dict, prefer: str = 'auto'):
    """The words as the transcript delivered them, before any re-alignment, with the source it came from. Seeded
    from target.json the first time, so re-aligning an aligned package starts from the transcript again and is
    idempotent rather than compounding.

    Both transcripts a song has ever had stay on disk, so `prefer` switches a song between them for free: the two
    are close enough in the measurements that which one reads better is a judgement call, not a calculation."""
    for src in (('vocal', 'mix') if prefer == 'auto' else (prefer,)):
        f = pkg / 'lyrics' / f'{src}.json'
        if f.exists():
            saved = json.loads(f.read_text(encoding='utf-8')); return saved['lines'], src, saved.get('lyricsSource') or ''
    if prefer != 'auto': raise SystemExit(f'{pkg.name}: no stored {prefer} transcript in {pkg / "lyrics"}')
    note = song.get('lyricsSource') or ''
    return song.get('lyrics') or [], ('vocal' if 'vocal stem' in note else 'mix'), note

def save_transcript(pkg: Path, src: str, lines: list[dict], lyrics_source: str):
    d = pkg / 'lyrics'; d.mkdir(exist_ok=True)
    (d / f'{src}.json').write_text(json.dumps({'source': src, 'lyricsSource': lyrics_source, 'lines': lines}, ensure_ascii=False, indent=1), encoding='utf-8')

def write_song(pkg: Path, song: dict, lines: list[dict], note: str):
    """Only `lyrics` and the `lyricsSource` note change; every other field keeps the value it was loaded with."""
    song['lyrics'] = lines; song['lyricsSource'] = note
    (pkg / 'target.json').write_text(json.dumps(song, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

def aligned_note(lyrics_source: str) -> str:
    base = (lyrics_source or 'Soniox stt-async-v5').split('; aligned')[0]
    return base + '; aligned offline to vocal onsets (align_lyrics.py)'

def corrected_seed(pkg: Path, asr_words: list[dict], ctx: dict) -> list[dict] | None:
    """If lyrics_text.py has a cached lyrics source for this package, the seed words re-derived from applying that
    correction to `asr_words` — otherwise None. A plain re-alignment must never regress a text correction back to
    the raw ASR transcript, so every write path that seeds from a stored transcript checks this first. Imported
    lazily: lyrics_text.py imports this module at load time, so importing it back here has to wait until the first
    call, by which point this module has already finished loading."""
    cache = pkg / 'lyrics' / 'source.txt'
    if not cache.exists(): return None
    import lyrics_text as lt
    true_tokens = lt.tokenize(cache.read_text(encoding='utf-8'))
    if not true_tokens: return None
    entries = lt.match_words(asr_words, true_tokens)
    insertions = lt.repeated_insertions(asr_words, true_tokens)
    if insertions:
        true_tokens = lt.apply_repeats(true_tokens, insertions)
        entries = lt.match_words(asr_words, true_tokens)
    return lt.seed_words(lt.fill_gaps(entries, ctx), asr_words)

def corrected_note_for(existing: str, src: str) -> str:
    import lyrics_text as lt
    return lt.corrected_note(existing, src)

def align_package(pkg: Path, write: bool, rebuild: bool = True, prefer: str = 'auto') -> dict:
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
    words, src, note = transcript(pkg, song, prefer)
    ctx = context(pkg, song)
    before = song.get('lyrics') or []
    raw_words = flat(words)
    corrected = corrected_seed(pkg, raw_words, ctx)
    seed = corrected if corrected is not None else raw_words
    after = realign(seed, ctx)
    assert [w['w'] for w in flat(after)] == [w['w'] for w in seed], 'the transcript text must survive re-alignment'
    moved = [abs(b['a'] - a['a']) for a, b in zip(seed, flat(after))]
    out = {'package': pkg.name, 'source': src, 'moved': stat(moved), 'snapped': sum(1 for m in moved if m > 1e-9),
           'before': metrics(before, ctx) if before else None, 'after': metrics(after, ctx),
           'corrected_from_source': corrected is not None}
    if write:
        save_transcript(pkg, src, words, note)
        out_note = corrected_note_for(note, src) if corrected is not None else aligned_note(note)
        write_song(pkg, song, after, out_note)
        if rebuild: out['html'] = str(build_html(pkg, pkg.parent / f'Luma_{pkg.name}.html'))
    return out

POOLED_SUMS = ['words', 'lines', 'phrase_boundaries', 'phrases_missing_first_syllables', 'boundary_misassignments',
               'breaks_on_silence', 'breaks_inside_singing', 'silent_holes', 'silent_hole_seconds', 'merged_words',
               'flashing_words', 'sung_seconds', 'uncovered_stretches', 'uncovered_seconds']

def pooled(per_song: list[dict]) -> dict:
    """One set of numbers over every song: counters added up and the per-word offsets pooled, so the totals are not
    an average of medians. Word agreement is pooled the same way, over the two transcripts of all songs together."""
    out = {'songs': len(per_song)}
    for variant in ('original', 'original_realigned', 'vocal_realigned'):
        ms = [v[variant] for v in per_song if v.get(variant)]
        if not ms: continue
        off = np.array([x for m in ms for x in m['_off_pitchmap']])
        agg = {k: round(sum(m.get(k) or 0 for m in ms), 1) for k in POOLED_SUMS if any(k in m for m in ms)}
        agg['onset_error_pitchmap'] = stat(off)
        agg['off_over_100ms_pitchmap'] = round(float((np.abs(off) > .1).mean()), 3) if len(off) else None
        agg['phrase_lag'] = stat([x for m in ms for x in m['_lag']])
        out[variant] = agg
    ag = [v['agreement_mix_vs_vocal'] for v in per_song if v.get('agreement_mix_vs_vocal')]
    if ag:
        t = {k: sum(a[k] for a in ag) for k in ('words_a', 'words_b', 'shared', 'only_a', 'only_b')}
        t['agreement_pct'] = round(200 * t['shared'] / max(t['words_a'] + t['words_b'], 1), 1)
        out['agreement_mix_vs_vocal'] = t
    return out

def strip_raw(x):
    """The per-word arrays the pooling needs are useful in memory and noise on a terminal."""
    if isinstance(x, dict): return {k: strip_raw(v) for k, v in x.items() if not k.startswith('_')}
    if isinstance(x, list): return [strip_raw(v) for v in x]
    return x

def variants(pkg: Path):
    """The three variants docs/LYRICS_TIMING.md compares: the original transcript as shipped, the same transcript
    re-aligned, and the vocal-stem transcript re-aligned."""
    song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
    ctx = context(pkg, song); out = {'package': pkg.name}
    mix = pkg / 'lyrics' / 'mix.json'; vocal = pkg / 'lyrics' / 'vocal.json'
    original = json.loads(mix.read_text(encoding='utf-8'))['lines'] if mix.exists() else (song.get('lyrics') or [])
    out['original'] = metrics(original, ctx)
    out['original_realigned'] = metrics(realign(flat(original), ctx), ctx)
    if vocal.exists():
        vw = flat(json.loads(vocal.read_text(encoding='utf-8'))['lines'])
        out['vocal_realigned'] = metrics(realign(vw, ctx), ctx)
        out['agreement_mix_vs_vocal'] = agreement(flat(original), vw)
    return out

def human(r: dict) -> str:
    b, a = r['before'], r['after']
    lines = [f"{r['package']}: {a['words']} words from the {r['source']} transcript, {r['snapped']} starts snapped to a vocal onset "
             f"(median move {r['moved']['med']:.2f} s, p90 {r['moved']['p90']:.2f} s)"]
    if b:
        lines += [f"  onset error vs the pitch map (independent of the onsets used for snapping) median "
                  f"{b['onset_error_pitchmap']['med']:+.3f} -> {a['onset_error_pitchmap']['med']:+.3f} s, "
                  f"p10/p90 {b['onset_error_pitchmap']['p10']:+.2f}/{b['onset_error_pitchmap']['p90']:+.2f} -> "
                  f"{a['onset_error_pitchmap']['p10']:+.2f}/{a['onset_error_pitchmap']['p90']:+.2f} s, "
                  f"further than 100 ms {b['off_over_100ms_pitchmap']:.0%} -> {a['off_over_100ms_pitchmap']:.0%}",
                  f"  phrase lag median {b['phrase_lag']['med']:.2f} -> {a['phrase_lag']['med']:.2f} s over {a['phrase_lag']['n']} sung phrases",
                  f"  lines {b['lines']} -> {a['lines']}, breaks on a real silence {b['breaks_on_silence']} -> {a['breaks_on_silence']}, "
                  f"inside singing {b['breaks_inside_singing']} -> {a['breaks_inside_singing']}",
                  f"  phrase boundaries buried inside a line {b['boundary_misassignments']} -> {a['boundary_misassignments']}, "
                  f"words spanning a silence {b['merged_words']} -> {a['merged_words']}, flashing words {b['flashing_words']} -> {a['flashing_words']}"]
    return '\n'.join(lines)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('package', nargs='+'); ap.add_argument('-n', '--dry-run', action='store_true', help='report only, write nothing')
    ap.add_argument('--json', action='store_true', help='print the metrics as JSON'); ap.add_argument('--no-html', action='store_true', help='update target.json but do not rebuild the trainer')
    ap.add_argument('--variants', action='store_true', help='compare the original, the original re-aligned and the vocal transcript re-aligned')
    ap.add_argument('--from', dest='prefer', default='auto', choices=['auto', 'vocal', 'mix'], help='which stored transcript to re-align (default: the vocal-stem one when the song has it)')
    a = ap.parse_args(); report = []
    for p in a.package:
        pkg = Path(p).expanduser().resolve()
        if a.variants: r = variants(pkg); report.append(r); print(json.dumps(strip_raw(r), ensure_ascii=False, indent=1)); continue
        r = align_package(pkg, write=not a.dry_run, rebuild=not a.no_html, prefer=a.prefer)
        report.append(r); print(human(r) if not a.json else json.dumps(strip_raw(r), ensure_ascii=False, indent=1))
        if not a.dry_run: print(f"  wrote {pkg / 'target.json'}" + (f" and rebuilt {r['html']}" if 'html' in r else ''))
    if a.variants and len(report) > 1: print(json.dumps({'pooled': pooled(report)}, ensure_ascii=False, indent=1))
    return report

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: sys.exit(130)
