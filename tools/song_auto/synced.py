"""Published LRC line clocks; text correspondence never consults word times."""
from __future__ import annotations

import math
from pathlib import Path
import re
import sys

from .bench.score import norm

MARGIN = .25
MAX_WINDOW = 30.
MIN_SHARED = .8


class AnchorError(ValueError):
    """A public, lyric-free refusal suitable for command output."""


def line_plan(lyrics, text, duration):
    """Partition known text in published row order, retaining original spelling.

    Use the correction tool's minimum-edit correspondence and 80% exact-token
    floor. Source-only rows reserve time but receive no invented package words.
    Inserted package tokens belong to the preceding matched row. All package
    words must be covered, with an anchor for the first. No reference clocks
    or per-recording clock compensation are used.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'studio'))
    from lyrics_synced import parse_lrc, token_mapping, SyncedLyricsError
    if re.search(r'<\d+:', text):
        raise AnchorError('synced lyrics: enhanced word timestamps need a separate word-time adapter')
    try:
        rows = parse_lrc(text)
    except SyncedLyricsError:
        raise AnchorError('synced lyrics: invalid or unordered LRC rows') from None
    flat = [w for row in lyrics for w in row['words']]
    source = [w for row in rows for w in row['tokens']]
    if (not flat or any(not row['words'] for row in lyrics) or
            not math.isfinite(duration) or duration <= 0 or
            any(not 0 <= row['a'] < duration for row in rows)):
        raise AnchorError('synced lyrics: empty lyrics or timestamps outside recording')
    mapping = token_mapping(source, [w['w'] for w in flat])
    shared = sum(norm(source[i]) == norm(flat[j]['w']) for i, j in mapping.items())
    if shared / max(len(source), len(flat)) < MIN_SHARED:
        raise AnchorError('synced lyrics: rows cannot be matched to known lyric text (80% exact tokens required)')
    cursor = 0
    bounds = []
    for row in rows:
        indices = [mapping[i] for i in range(cursor, cursor + len(row['tokens'])) if i in mapping]
        bounds.append(min(indices) if indices else None)
        cursor += len(row['tokens'])
    sung = [(i, j) for i, j in enumerate(bounds) if j is not None]
    if not sung or sung[0][1] != 0 or any(b[1] <= a[1] for a, b in zip(sung, sung[1:])):
        raise AnchorError('synced lyrics: rows cannot cover known lyric text in order')
    result = []
    for k, (i, start) in enumerate(sung):
        end = sung[k+1][1] if k+1 < len(sung) else len(flat)
        at = rows[i]['a']
        # Each next row owns its 250 ms early context. Source-only and empty
        # rows also close the preceding window. There is no overlap to repair.
        stop = rows[i+1]['a'] if i+1 < len(rows) else duration
        lo = max(0., at-MARGIN)
        hi = min(duration, stop-MARGIN if i+1 < len(rows) else duration,
                 at+MAX_WINDOW-MARGIN)
        # Millisecond storage must preserve the same exclusive boundaries.
        lo, hi = math.ceil((lo-1e-9)*1000)/1000, math.floor((hi+1e-9)*1000)/1000
        if hi-lo < (end-start)*.04+.02:
            raise AnchorError('synced lyrics: line window has insufficient room for known words')
        result.append(dict(start=start, end=end, a=at, lo=lo, hi=hi,
                           words=flat[start:end], source_line=rows[i]['line']))
    return result


def word_bounds(plan):
    return [(row['lo'], row['hi']) for row in plan for _ in row['words']]


def even_words(plan):
    """A deliberately trivial comparison; source timing has no acoustic score."""
    result = []
    for row in plan:
        a, b = row['a'], row['hi']
        if b <= a:
            raise AnchorError('synced lyrics: line has no time after its anchor')
        step = (b-a)/len(row['words'])
        for j, word in enumerate(row['words']):
            result.append(dict(w=word['w'], a=a+j*step, b=a+(j+1)*step, confidence=0.))
    return result
