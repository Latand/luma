"""Optional LRC boundaries for text correction, validated against the stored recording.

LRC supplies section boundaries; the verified text supplies words. A coherent clock
offset needs several independent phrase matches. Changed edits, unsupported starts
and unplaceable text raise SyncedLyricsError with a line number and recording time.
No file access or network access occurs here.
"""
from __future__ import annotations

import re
import numpy as np
import align_lyrics as al

START_TOLERANCE = 1.5
CLOCK_TOLERANCE = 1.5
MAX_CLOCK_OFFSET = 30.0


class SyncedLyricsError(ValueError):
    """The supplied timeline cannot safely anchor this recording."""


def fail(line: dict, reason: str):
    offset = line.get('clock_offset_s', 0.)
    clock = f'; compensated clock offset {offset:+.3f}s' if offset else ''
    raise SyncedLyricsError(f"synced line {line['line']} at {line['a']:.2f}s: {reason}{clock}")


def parse_lrc(text: str) -> list[dict]:
    """Parse ordinary/multiple LRC tags and millisecond offset metadata.

    Empty timed rows mark instrumental boundaries. Parentheses contain sung words.
    Input order must already be chronological; sorting could hide a different edit.
    """
    result = []
    offset = 0.0
    stamp = re.compile(r'\[([0-9]+):([0-5][0-9](?:\.[0-9]+)?)\]')
    for number, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip().lstrip('\ufeff')
        if not raw:
            continue
        meta = re.fullmatch(r'\[offset:([+-]?[0-9]+)\]', raw, re.I)
        if meta:
            offset = int(meta[1]) / 1000
            continue
        tags = list(stamp.finditer(raw))
        if not tags:
            if re.fullmatch(r'\[[a-zA-Z]+:.*\]', raw):
                continue
            raise SyncedLyricsError(f'synced line {number} at unknown time: invalid LRC timestamp')
        prefix = ''.join(m[0] for m in tags)
        if not raw.startswith(prefix):
            raise SyncedLyricsError(f'synced line {number} at unknown time: invalid LRC row')
        tokens = raw[len(prefix):].split()
        for tag in tags:
            result.append({'a': 60 * int(tag[1]) + float(tag[2]), 'tokens': tokens, 'line': number})
    for row in result:
        row['a'] += offset
        if row['a'] < 0 or not np.isfinite(row['a']):
            fail(row, 'invalid recording time')
    for left, right in zip(result, result[1:]):
        if right['a'] <= left['a']:
            fail(right, 'timestamps must increase; overlapping lines need separate timing')
    if not any(r['tokens'] for r in result):
        raise SyncedLyricsError('synced line 1 at unknown time: no timed words')
    return result


def clock_offset(rows: list[dict], words: list[dict]) -> dict:
    """Check three-word prefixes against ASR, independently of corrected word seeds.

    Ordinary ASR latency is retained. Large, consistent offsets are reported and
    compensated. Distributed disagreement refuses an offset or a different edit.
    """
    norms = [al.norm(w['w']) for w in words]
    evidence, used = [], set()
    for row in rows:
        prefix = [al.norm(w) for w in row['tokens'][:3]]
        if len(prefix) < 3:
            continue
        candidates = [(i, words[i]['a'] - row['a']) for i in range(len(words) - 2)
                      if norms[i:i + 3] == prefix and i not in used
                      and abs(words[i]['a'] - row['a']) <= MAX_CLOCK_OFFSET]
        if candidates:
            index, delta = min(candidates, key=lambda pair: (abs(pair[1]), pair[0]))
            used.add(index)
            evidence.append((row, delta))
    if len(evidence) < 3:
        fail(next(r for r in rows if r['tokens']), 'insufficient independent phrase evidence for the clock')
    median = float(np.median([d for _, d in evidence]))
    coherent = [(r, d) for r, d in evidence if abs(d - median) <= CLOCK_TOLERANCE]
    if len(coherent) < max(3, .7 * len(evidence)):
        row, _ = max(evidence, key=lambda rd: abs(rd[1] - median))
        fail(row, 'inconsistent clock; possible different edit')
    # A stable majority alone can conceal an inserted/deleted section. Compare
    # chronological groups including outliers before accepting that majority.
    groups = np.array_split(np.array([d for _, d in evidence]), min(3, len(evidence) // 3))
    if len(groups) > 1 and np.ptp([np.median(g) for g in groups]) > CLOCK_TOLERANCE:
        fail(evidence[-1][0], 'clock changes during recording; possible different edit')
    offset = median if abs(median) > CLOCK_TOLERANCE else 0.0
    return {'offset_s': round(offset, 3), 'phrase_matches': len(evidence),
            'coherent_matches': len(coherent), 'status': 'offset compensated' if offset else 'clock agrees'}


def token_mapping(source: list[str], target: list[str]) -> dict[int, int]:
    """Monotone minimum-edit correspondence, including small wording differences.

    A global longest block can steal repeated lines from an adjacent section.
    Minimum edits keep each line boundary attached to its occurrence in the text.
    Ties consistently prefer a diagonal, then deletion, then insertion.
    """
    a, b = [al.norm(w) for w in source], [al.norm(w) for w in target]
    cost = np.zeros((len(a) + 1, len(b) + 1), dtype=np.int32)
    cost[:, 0] = np.arange(len(a) + 1)
    cost[0, :] = np.arange(len(b) + 1)
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            cost[i, j] = min(cost[i - 1, j - 1] + (x != y), cost[i - 1, j] + 1, cost[i, j - 1] + 1)
    mapping = {}
    i, j = len(a), len(b)
    while i and j:
        if cost[i, j] == cost[i - 1, j - 1] + (a[i - 1] != b[j - 1]):
            mapping[i - 1] = j - 1
            i -= 1
            j -= 1
        elif cost[i, j] == cost[i - 1, j] + 1:
            i -= 1
        else:
            j -= 1
    return mapping


def sections(rows: list[dict], tokens: list[str]) -> list[dict]:
    """Map timed rows to verified token boundaries; never add or remove text."""
    source = [t for r in rows for t in r['tokens']]
    mapping = token_mapping(source, tokens)
    shared = sum(al.norm(source[i]) == al.norm(tokens[j]) for i, j in mapping.items())
    if shared / max(len(source), len(tokens), 1) < .8:
        fail(next(r for r in rows if r['tokens']), 'timed text differs from verified text')
    result, cursor = [], 0
    for row in rows:
        if not row['tokens']:
            result.append({**row, 'index': None})
            continue
        if cursor not in mapping:
            fail(row, 'line start has no counterpart in verified text')
        result.append({**row, 'index': mapping[cursor]})
        cursor += len(row['tokens'])
    return result


def anchor_start(row: dict, ctx: dict) -> float:
    """Require an actual vocal onset within the LRC tolerance of each predicted start."""
    t = row['a']
    candidates = [float(o) for o in ctx['onsets'] if abs(float(o) - t) <= START_TOLERANCE
                  and any(a - .05 <= o < b for a, b in ctx['regions'])]
    if not candidates:
        fail(row, 'no vocal attack near the predicted line start')
    return min(candidates, key=lambda o: (abs(o - t), o))


def seed_sections(tokens: list[str], words: list[dict], ctx: dict, lrc: str,
                  fill_gaps) -> tuple[list[dict], list[dict], dict, dict]:
    """Match inside validated section windows, then fill only their voiced time.

    Repeat restoration is deliberately absent: the supplied performance text is
    complete. Unmatched ASR chatter cannot manufacture another repeated phrase.
    """
    rows = parse_lrc(lrc)
    clock = clock_offset(rows, words)
    rows = [{**r, 'a': r['a'] + clock['offset_s'], 'clock_offset_s': clock['offset_s']} for r in rows]
    for row in rows:
        if not 0 <= row['a'] <= ctx['duration']:
            fail(row, 'timestamp is outside the recording after clock correction')
    bounds = sections(rows, tokens)
    ctx = {**ctx, 'onsets': np.array([o for o in ctx['onsets']
           if any(a - .05 <= o < b for a, b in ctx['regions'])])}
    sung = [r for r in bounds if r['index'] is not None]
    if sung[0]['index'] != 0:
        fail(sung[0], 'verified text before the first timed line needs an anchor')
    entries, checks = [], []
    for k, row in enumerate(sung):
        lo = row['a']
        next_row = next((r for r in bounds if r['a'] > lo), None)
        hi = next_row['a'] if next_row else ctx['duration']
        end = sung[k + 1]['index'] if k + 1 < len(sung) else len(tokens)
        start = anchor_start(row, ctx)
        if not 0 <= start < hi <= ctx['duration']:
            fail(row, 'section is outside the recording or overlaps its neighbour')
        indices = [i for i, w in enumerate(words) if max(0, lo - .35) <= w['a'] < hi - .05
                   and any(a - .05 <= w['a'] < b for a, b in ctx['regions'])]
        local_words = [words[i] for i in indices]
        local_tokens = tokens[row['index']:end]
        if not local_tokens:
            fail(row, 'timed line has no verified words')
        mapping = token_mapping([w['w'] for w in local_words], local_tokens)
        inverse = {j: i for i, j in mapping.items()}
        local = []
        for j, token in enumerate(local_tokens):
            i = inverse.get(j)
            local.append({'w': token, 'a': local_words[i]['a'] if i is not None else None,
                          'src': i, 'kind': ('matched' if al.norm(token) == al.norm(local_words[i]['w'])
                                             else 'substituted') if i is not None else 'inserted'})
        for entry in local:
            if entry['src'] is not None:
                entry['src'] = indices[entry['src']]
        # The LRC boundary supplies the missing intro/phrase attack. A late ASR
        # match cannot drag that attack into a later repeated occurrence.
        local[0].update(a=start, kind='matched', src=None)
        for entry in local[1:]:
            if entry['a'] is not None and entry['a'] <= start:
                entry.update(a=None, kind='inserted', src=None)
        regs = [(max(a, start), min(b, hi - .05)) for a, b in ctx['regions']
                if min(b, hi - .05) > max(a, start)]
        if not regs:
            fail(row, 'no voiced time inside the section')
        local_ctx = {**ctx, 'regions': regs, 'duration': hi - .05}
        local = fill_gaps(local, local_ctx)
        # A short section can pack all missing words onto its first attack.
        # Retry inside this same section, retaining the line attack. The final placement gate
        # checks substituted-word displacement. Never borrow room from another line.
        if any(b['a'] - a['a'] < .05 for a, b in zip(local, local[1:])):
            total = sum(b - a for a, b in regs)
            if len(local) > 1 and total / len(local) >= .1:
                for i, entry in enumerate(local[1:], 1):
                    target = total * i / len(local)
                    used = 0.
                    for a, b in regs:
                        if used + b - a >= target:
                            entry['a'] = a + target - used
                            break
                        used += b - a
            else:
                fail(row, 'insufficient voiced time for distinguishable words')
        local[0]['kind'] = 'anchored'
        entries.extend(local)
        checks.append({**row, 'end_index': end, 'end_time': hi})
    return entries, checks, clock, ctx


def placement_errors(checks: list[dict], words: list[dict], ctx: dict) -> list[str]:
    """Check final, snapped words; a snap must not cross a section boundary."""
    errors = []
    for row in checks:
        local = words[row['index']:row['end_index']]
        if abs(local[0]['a'] - row['a']) > CLOCK_TOLERANCE:
            errors.append(f"synced line {row['line']} at {row['a']:.2f}s: first word outside anchor tolerance")
        for word in local:
            if not any(a - .05 <= word['a'] < b for a, b in ctx['regions']):
                errors.append(f"synced line {row['line']} at {row['a']:.2f}s: word at {word['a']:.2f}s is off the sung voice")
                break
            if word['a'] < row['a'] - CLOCK_TOLERANCE or word['a'] >= row['end_time']:
                errors.append(f"synced line {row['line']} at {row['a']:.2f}s: word crosses section boundary")
                break
    return errors
