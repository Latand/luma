"""How hard a song is to sing, from its target map: D 0…100, the mean of five features mapped onto fixed anchors.

The anchors are constants, so adding a song never moves another song's D. Studio's «Обери за мене» walks the library
from easy to hard by it (docs/design/AUTOPICK.md). Only non-ignored notes count: the same notes the score counts.
"""
from __future__ import annotations
import json
from pathlib import Path

COMFORT = (57, 74)        # A3–D5: the range of built-in lesson 2, which the operator sings comfortably
JOIN = .3                 # a gap shorter than this joins two notes into one move
LEAP = 5                  # semitones: a move this wide is a jump
# feature: (value that scores 0, value that scores 1); clipped outside
ANCHORS = {'span': (7, 20), 'out': (0, .4), 'rate': (2.5, 4.8), 'leaps': (.03, .2), 'sung': (75, 270)}
MARK = 'window.LUMA_SONG='


def quantile(values: list[float], weights: list[float], q: float) -> float:
    """The first value whose cumulative weight reaches q of the total."""
    pairs = sorted(zip(values, weights)); total = sum(weights); acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total: return v
    return pairs[-1][0]


def measure(song: dict) -> dict | None:
    """{D, span, out, rate, leaps, sung} for a song map, or None when it has no notes to sing."""
    notes = [n for n in song.get('notes') or [] if not n.get('ignored') and n['b'] > n['a']]
    if not notes: return None
    lengths = [n['b'] - n['a'] for n in notes]; pitch = [n['m'] for n in notes]; sung = sum(lengths)
    moves = [(a, b) for a, b in zip(notes, notes[1:]) if b['a'] - a['b'] < JOIN]
    f = {'span': quantile(pitch, lengths, .9) - quantile(pitch, lengths, .1),
         'out': sum(d for n, d in zip(notes, lengths) if n['m'] < COMFORT[0] - .5 or n['m'] > COMFORT[1] + .5) / sung,
         'rate': len(notes) / sung,
         'leaps': sum(1 for a, b in moves if abs(b['n'] - a['n']) >= LEAP) / max(1, len(moves)),
         'sung': sung}
    parts = [min(1.0, max(0.0, (f[k] - lo) / (hi - lo))) for k, (lo, hi) in ANCHORS.items()]
    return {'D': round(100 * sum(parts) / len(parts)), **{k: round(v, 4) for k, v in f.items()}}


def of_file(path: Path) -> dict:
    """{songHash, D, …} for a trainer HTML; ValueError when its LUMA_SONG cannot be read. The song hash (sourceId) sits
    after the long arrays, so the whole data line is parsed: about 0.15 s for a typical song."""
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    i = text.find(MARK)
    if i < 0: raise ValueError('no LUMA_SONG')
    song, _ = json.JSONDecoder().raw_decode(text, i + len(MARK))
    if not isinstance(song, dict) or song.get('schema') != 'luma.song.v1': raise ValueError('schema')
    m = measure(song)
    return {'songHash': song.get('sourceId') or song.get('id'), **(m or {'D': None})}
