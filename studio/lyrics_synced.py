"""Optional LRC boundaries for text correction, validated against the stored recording.

LRC supplies section boundaries; the verified text supplies words. A coherent clock
offset needs several independent phrase matches. Every placement first checks its
own phrase evidence against the timestamp and ordinary ASR latency. Unpitched
passages use stem energy; quiet passages may use a separately validated clock.
Changed edits, unsupported clocks and unplaceable text raise
SyncedLyricsError with a line number and recording time.
No file access or network access occurs here.
"""
from __future__ import annotations

import re
import numpy as np
import align_lyrics as al

START_TOLERANCE = 1.5
CLOCK_TOLERANCE = 1.5
MAX_CLOCK_OFFSET = 30.0
MAX_PHRASE_PAUSE_S = 3.0
ENERGY_MARGIN_DB = 10.0
ENERGY_DYNAMIC_DB = 35.0
ENERGY_MIN_RUN_S = .12
ENERGY_ABSOLUTE_DB = -80.0


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
    """Check phrase occurrences against ASR, independently of corrected word seeds.

    Ordinary ASR latency is retained. Large, consistent offsets are reported and
    compensated. Distributed disagreement refuses an offset or a different edit.
    Retain each line's evidence, including outliers, for every placement branch.
    """
    norms = [al.norm(w['w']) for w in words]
    phrases = [tuple(al.norm(w) for w in r['tokens']) for r in rows]
    prefixes = [p[:3] for p in phrases]

    def continuous(left, right):
        # Token durations can cover an entire ASR pause. Cap them as the aligner
        # does; allow slow sung phrases while separating distant fragments.
        return (left['a'] <= right['a']
                and right['a'] - min(left['b'], left['a'] + al.MAX_DUR) <= MAX_PHRASE_PAUSE_S)

    def occurrences(phrase):
        return [i for i in range(len(words) - len(phrase) + 1)
                if tuple(norms[i:i + len(phrase)]) == phrase
                and all(continuous(left, right)
                        for left, right in zip(words[i:i + len(phrase) - 1], words[i + 1:i + len(phrase)]))]

    def contains(phrase, text):
        return any(text[i:i + len(phrase)] == phrase for i in range(len(text) - len(phrase) + 1))

    by_occurrence = {}
    clock_candidates = []
    line_evidence = []
    for row, phrase, prefix in zip(rows, phrases, prefixes):
        if not prefix:
            continue
        clock_occurrences = occurrences(prefix)
        # Extend a shared prefix through the first distinguishing word. Exact
        # repeats still retain every occurrence. A fragment inside another line
        # also needs distinguishing words before it identifies this line.
        length = len(prefix)
        while length < len(phrase) and any(p != phrase and contains(phrase[:length], p) for p in phrases):
            length += 1
        matches = occurrences(phrase[:length]) if length > len(prefix) else clock_occurrences
        if clock_occurrences:
            index = min(matches or clock_occurrences, key=lambda i: (abs(words[i]['a'] - row['a']), i))
            line_evidence.append({'line': row['line'], 'synced_time_s': row['a'],
                                  'asr_time_s': words[index]['a'], 'asr_delta_s': words[index]['a'] - row['a'],
                                  'unambiguous': len(matches) == 1 and sum(contains(phrase[:length], p) for p in phrases) == 1,
                                  '_indices': matches, '_phrase': phrase[:length],
                                  'occurrences': [{'asr_time_s': words[i]['a'],
                                                   'asr_delta_s': words[i]['a'] - row['a']} for i in matches]})
            if length > len(prefix):
                # Preserve broad observations even when they identify only a
                # different phrase. They still contribute to the global clock.
                line_evidence[-1]['prefix_occurrences_s'] = [words[i]['a'] for i in clock_occurrences]
        # Short lines supply veto evidence, but cannot validate the global clock.
        if len(prefix) < 3:
            continue
        clock_candidates.extend((i, row, words[i]['a'] - row['a']) for i in clock_occurrences)
        candidates = [(i, words[i]['a'] - row['a']) for i in clock_occurrences
                      if abs(words[i]['a'] - row['a']) <= MAX_CLOCK_OFFSET]
        if candidates:
            index, delta = min(candidates, key=lambda pair: (abs(pair[1]), pair[0]))
            previous = by_occurrence.get(index)
            if previous is None or abs(delta) < abs(previous[1]):
                by_occurrence[index] = (row, delta)
    # A missed early repeat must not consume the ASR occurrence whose own
    # timed row arrives later. Pick each occurrence's closest row, then count
    # those distinct observations in chronological order.
    evidence = sorted(by_occurrence.values(), key=lambda item: item[0]['a'])
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
    residuals = [d - median for _, d in coherent]
    spread = float(np.percentile(residuals, 90) - np.percentile(residuals, 10))
    group_spread = float(np.ptp([np.median(g) for g in groups]))
    timed = [r for r in rows if r['tokens']]
    share = len(coherent) / len(timed)
    span = (coherent[-1][0]['a'] - coherent[0][0]['a']) / max(timed[-1]['a'] - timed[0]['a'], .01)
    # Silence needs stronger evidence than local onset placement. Count every
    # timed line in the denominator, including short lines and missed ASR lines.
    validated = (share >= .5 and len(coherent) >= .8 * len(evidence)
                 and spread <= 1.0 and group_spread <= .75 and span >= .5)
    explained_spans = []
    # Raw source times can put an occurrence closer to a missing earlier repeat.
    # Reassign all observations against the inferred clock before explaining any
    # other line's evidence, including separate tags on the same physical row.
    owners = {}
    for index, row, delta in clock_candidates:
        previous = owners.get(index)
        if previous is None or abs(delta - median) < abs(previous[1] - median):
            owners[index] = (row, delta)
    for index, (other, delta) in owners.items():
        if abs(delta - median) <= CLOCK_TOLERANCE or abs(delta - offset) <= START_TOLERANCE:
            end = index
            for token in other['tokens']:
                if (end >= len(norms) or norms[end] != al.norm(token)
                        or (end > index and not continuous(words[end - 1], words[end]))):
                    break
                end += 1
            explained_spans.append((index, end, other['line'], other['a']))
    for match in line_evidence:
        match['residual_s'] = round(match['asr_delta_s'] - median, 3)
        phrase = match.pop('_phrase')
        for occurrence, index in zip(match['occurrences'], match.pop('_indices')):
            occurrence['residual_s'] = round(occurrence['asr_delta_s'] - median, 3)
            for lo, hi, owner_line, owner_time in explained_spans:
                # Multiple timestamp tags on one physical LRC line are distinct
                # timed occurrences, just like the same tags on separate lines.
                if ((owner_line, owner_time) != (match['line'], match['synced_time_s'])
                        and lo <= index and index + len(phrase) <= hi):
                    # A missed repeat cannot consume evidence already explained
                    # by another coherently timed row. Keep that observation and
                    # its owner; it supplies no negative evidence for this row.
                    occurrence['explained_by_line'] = owner_line
                    break
    return {'offset_s': round(offset, 3), 'phrase_matches': len(evidence),
            'line_evidence': line_evidence,
            'coherent_matches': len(coherent), 'timed_lines': len(timed),
            'agreeing_line_share': round(share, 4), 'median_asr_delta_s': round(median, 3),
            'residual_p10_s': round(float(np.percentile(residuals, 10)), 3),
            'residual_p90_s': round(float(np.percentile(residuals, 90)), 3),
            'residual_spread_s': round(spread, 3), 'group_median_spread_s': round(group_spread, 3),
            'evidence_span_share': round(span, 4), 'validated_without_voice': bool(validated),
            'status': 'offset compensated' if offset else 'clock agrees'}


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


def passage_energy(row: dict, hi: float, ctx: dict) -> tuple[dict, list, list]:
    """Local floor (p20 within 8 s), sustained energy and independent stem attacks.

    Cap the local floor at stem p95 minus 20 dB for continuous singing.
    Require 10 dB above that floor and within 35 dB of the stem's p95. This
    rejects separation residue in quiet intros. Energy support is confined to
    the supplied line window and never changes the text-only pitch mask.
    """
    db = ctx.get('energy_db')
    if db is None:
        return {'available': False}, [], []
    t = row['a']
    around = db[max(0, int((t - 8) / al.HOP)):min(len(db), int((t + 8) / al.HOP))]
    near = db[max(0, int((t - START_TOLERANCE) / al.HOP)):
              min(len(db), int(min(hi, t + START_TOLERANCE) / al.HOP))]
    if not len(around) or not len(near):
        return {'available': False}, [], []
    local_floor = float(np.percentile(around, 20))
    stem_p95 = float(np.percentile(db, 95))
    # Continuous singing can occupy the whole neighbourhood. Its lower
    # percentile then measures the voice itself; cap that noise estimate.
    floor = min(local_floor, stem_p95 - 20.)
    threshold = max(floor + ENERGY_MARGIN_DB, stem_p95 - ENERGY_DYNAMIC_DB, ENERGY_ABSOLUTE_DB)
    mask = db > threshold
    for a, b in al.runs(mask):
        if (b - a) * al.HOP < ENERGY_MIN_RUN_S:
            mask[a:b] = False
    full_regs = al.regions(mask)
    regs = [(max(a, t - START_TOLERANCE, 0.), min(b, hi - .05)) for a, b in full_regs
            if min(b, hi - .05) > max(a, t - START_TOLERANCE, 0.)]
    # Clipping a continuous sound at the search boundary must not create an attack.
    attacks = sorted(set([a for a, _ in full_regs if t - START_TOLERANCE <= a < hi - .05]
                         + [round(float(o), 3) for o in ctx.get('stem_onsets', [])
                     if any(a - .05 <= o < b for a, b in regs)]))
    evidence = {'available': True, 'local_p20_db': round(local_floor, 3),
                'floor_db': round(floor, 3), 'threshold_db': round(threshold, 3),
                'near_median_db': round(float(np.median(near)), 3),
                'near_p95_db': round(float(np.percentile(near, 95)), 3)}
    return evidence, regs, attacks


def seed_sections(tokens: list[str], words: list[dict], ctx: dict, lrc: str,
                  fill_gaps) -> tuple[list[dict], list[dict], dict, dict]:
    """Match inside validated windows using pitch, stem energy or a quiet clock.

    Repeat restoration is deliberately absent: the supplied performance text is
    complete. Unmatched ASR chatter cannot manufacture another repeated phrase.
    """
    clock_rows = parse_lrc(lrc)
    clock = clock_offset(clock_rows, words)
    evidence = {(m['line'], m['synced_time_s']): m for m in clock['line_evidence']}
    rows = [{**r, 'a': r['a'] + clock['offset_s'], 'clock_offset_s': clock['offset_s'],
             'clock_evidence': evidence.get((r['line'], r['a']))} for r in clock_rows]
    for row in rows:
        if not 0 <= row['a'] <= ctx['duration']:
            fail(row, 'timestamp is outside the recording after clock correction')
    bounds = sections(rows, tokens)
    pitch_regs = ctx['regions']
    ctx = {**ctx, 'voiced': ctx['voiced'].copy(), 'regions': list(ctx['regions']),
           'synced_silences': [(r['a'], bounds[i + 1]['a'] if i + 1 < len(bounds) else ctx['duration'])
                              for i, r in enumerate(bounds) if r['index'] is None],
           'onsets': np.array([o for o in ctx['onsets']
           if any(a - .05 <= o < b for a, b in ctx['regions'])])}
    sung = [r for r in bounds if r['index'] is not None]
    if sung[0]['index'] != 0:
        fail(sung[0], 'verified text before the first timed line needs an anchor')
    entries, checks = [], []
    for k, row in enumerate(sung):
        lo = row['a']
        # Check before any voice branch can discard or overwrite known times.
        # Allow ASR near the compensated timestamp or its normal latency; an
        # early ASR estimate within the onset tolerance is not a contradiction
        # merely because the song-wide median is positive. Ambiguity alone cannot
        # waive unexplained negative evidence for a repeated phrase.
        # Short fragments also occur inside unrelated phrases. Their complete
        # one-/two-word match identifies a line only when it is unique.
        match = row['clock_evidence']
        identified = match and (len(row['tokens']) >= 3 or match['unambiguous'])
        known = [m for m in match['occurrences'] if 'explained_by_line' not in m] if identified else []
        if known and all(abs(m['residual_s']) > CLOCK_TOLERANCE
                         and abs(m['asr_time_s'] - lo) > START_TOLERANCE for m in match['occurrences']):
            closest = min(known, key=lambda m: (abs(m['asr_time_s'] - lo), m['asr_time_s']))
            fail(row, f"phrase evidence contradicts timestamp: closest ASR occurrence at "
                 f"{closest['asr_time_s']:.2f}s; clock residual {closest['residual_s']:+.3f}s; "
                 f"all {len(known)} known occurrences conflict")
        next_row = next((r for r in bounds if r['a'] > lo), None)
        hi = next_row['a'] if next_row else ctx['duration']
        end = sung[k + 1]['index'] if k + 1 < len(sung) else len(tokens)
        energy, energy_regs, energy_attacks = passage_energy(row, hi, ctx)
        source = 'pitch_supported'
        try:
            start = anchor_start(row, ctx)
            room = sum(max(0, min(b, hi - .05) - max(a, start)) for a, b in ctx['regions'])
            if energy['available'] and end - row['index'] > 1 and room < .1 * (end - row['index']):
                fail(row, 'pitch mask has insufficient time inside the line')
            if abs(start - lo) > al.SNAP and any(abs(o - lo) < abs(start - lo) for o in energy_attacks):
                fail(row, 'a closer stem attack supports the line')
        except SyncedLyricsError:
            near = [o for o in energy_attacks if abs(o - lo) <= START_TOLERANCE]
            # A word can begin within a sustained voice without producing a
            # spectral-flux peak. Keep the verified timestamp on that voice;
            # distinguish this from the quiet-clock fallback in the evidence.
            sustained = not near and any(a <= lo and b >= lo + ENERGY_MIN_RUN_S for a, b in energy_regs)
            if sustained:
                near = [lo]
                energy_attacks = sorted(set(energy_attacks + [lo]))
                energy['sustained_at_synced_time'] = True
            if near:
                start = min(near, key=lambda o: (abs(o - lo), o))
                source = 'vocal_stem_energy'
                for a, b in energy_regs:
                    ctx['voiced'][int(round(a / al.HOP)):int(round(b / al.HOP))] = True
                ctx['regions'] = al.regions(ctx['voiced'])
                ctx['onsets'] = np.array(sorted(set(ctx['onsets']) | set(energy_attacks)))
            elif energy['available'] and clock['validated_without_voice']:
                # The quiet passage cannot validate its own clock. Recheck the
                # other lines, including stability of the inferred offset.
                try:
                    other_clock = clock_offset([
                        r for r in clock_rows
                        if (r['line'], r['a'] + clock['offset_s']) != (row['line'], row['a'])], words)
                except SyncedLyricsError:
                    fail(row, 'clock not validated by the other lines; no voice support')
                if (not other_clock['validated_without_voice'] or
                        abs(other_clock['median_asr_delta_s'] - clock['median_asr_delta_s']) > .75):
                    fail(row, 'clock not validated by the other lines; no voice support')
                start = lo
                source = 'synced_time_without_voice_support'
            else:
                fail(row, 'no vocal attack or sustained stem energy; clock not validated for placement without voice support')
        if not 0 <= start < hi <= ctx['duration']:
            fail(row, 'section is outside the recording or overlaps its neighbour')
        indices = [i for i, w in enumerate(words) if max(0, lo - .35) <= w['a'] < hi - .05
                   and any(a - .05 <= w['a'] < b for a, b in ctx['regions'])]
        if source == 'synced_time_without_voice_support':
            indices = []
        local_words = [words[i] for i in indices]
        local_tokens = tokens[row['index']:end]
        if not local_tokens:
            fail(row, 'timed line has no verified words')
        mapping = token_mapping([w['w'] for w in local_words], local_tokens)
        shared = sum(al.norm(local_words[i]['w']) == al.norm(local_tokens[j]) for i, j in mapping.items())
        if shared / max(len(local_words), len(local_tokens)) < .35:
            # Unrelated ASR chatter is missing text, with no replacement times
            # to preserve. Independent line evidence supplies its placement.
            indices, local_words, mapping = [], [], {}
            if source == 'pitch_supported' and energy_regs and any(abs(o - lo) <= START_TOLERANCE for o in energy_attacks):
                source = 'vocal_stem_energy'
                for a, b in energy_regs:
                    ctx['voiced'][int(round(a / al.HOP)):int(round(b / al.HOP))] = True
                ctx['regions'] = al.regions(ctx['voiced'])
                ctx['onsets'] = np.array(sorted(set(ctx['onsets']) | set(energy_attacks)))
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
                if (entry['kind'] == 'substituted' and not any(a - .05 <= entry['a'] < b for a, b in pitch_regs)):
                    # An unpitched, nonmatching ASR token is not a heard timing
                    # anchor for a different word. Let this line's stem place it.
                    entry.update(a=None, kind='inserted', src=None)
        # The LRC boundary supplies the missing intro/phrase attack. A late ASR
        # match cannot drag that attack into a later repeated occurrence.
        local[0].update(a=start, kind='matched', src=None)
        for entry in local[1:]:
            if entry['a'] is not None and entry['a'] <= start:
                entry.update(a=None, kind='inserted', src=None)
        regs = [(max(a, start), min(b, hi - .05)) for a, b in ctx['regions']
                if min(b, hi - .05) > max(a, start)]
        if source == 'synced_time_without_voice_support':
            # Published line time is authoritative only under the stronger clock
            # test. Do not manufacture a pitch region or snap to spurious notes.
            regs = [(start, hi - .05)]
            ctx['onsets'] = np.array([o for o in ctx['onsets'] if not start <= o < hi])
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
        for entry in local:
            entry['timing_source'] = source
        entries.extend(local)
        checks.append({**row, 'end_index': end, 'end_time': hi, 'start': start,
                       'timing_source': source, 'energy': energy,
                       'start_residual_s': round(start - lo, 3)})
    # An onset may precede its published timestamp. Reserve room for the actual
    # next attack before snapping; nominal LRC windows alone can overlap there.
    for k, row in enumerate(checks):
        hi = min(row['end_time'], checks[k + 1]['start'] if k + 1 < len(checks) else ctx['duration']) - .05
        row['placement_end'] = hi
        if hi <= row['start']:
            fail(row, 'vocal attack overlaps the next line')
        local = entries[row['index']:row['end_index']]
        if any(e['a'] >= hi for e in local):
            regs = ([(row['start'], hi)] if row['timing_source'] == 'synced_time_without_voice_support' else
                    [(max(a, row['start']), min(b, hi)) for a, b in ctx['regions']
                     if min(b, hi) > max(a, row['start'])])
            total = sum(b - a for a, b in regs)
            if total / len(local) < .1:
                fail(row, 'insufficient voiced time before the next line attack')
            for i, entry in enumerate(local[1:], 1):
                target, used = total * i / len(local), 0.
                for a, b in regs:
                    if used + b - a >= target:
                        entry['a'] = a + target - used
                        break
                    used += b - a
    return entries, checks, clock, ctx


def realign_sections(seed: list[dict], checks: list[dict], ctx: dict) -> list[dict]:
    """Snap within each line, preserving its first attack and the next line's room."""
    result = []
    for row in checks:
        lo, hi = row['start'], row['placement_end']
        attacks = (np.array([]) if row['timing_source'] == 'synced_time_without_voice_support' else
                   np.array([o for o in ctx['onsets'] if lo <= o < hi]))
        local_ctx = {**ctx, 'onsets': attacks, 'duration': hi, 'min_word_spacing_s': .05}
        result.extend(al.realign(seed[row['index']:row['end_index']], local_ctx))
    return result


def placement_errors(checks: list[dict], words: list[dict], ctx: dict) -> list[str]:
    """Check final, snapped words; a snap must not cross a section boundary."""
    errors = []
    for row in checks:
        local = words[row['index']:row['end_index']]
        if (row.get('timing_source') == 'synced_time_without_voice_support'
                and abs(local[0]['a'] - row['a']) > .001):
            errors.append(f"synced line {row['line']} at {row['a']:.2f}s: quiet line moved from validated synced time")
        if abs(local[0]['a'] - row['a']) > CLOCK_TOLERANCE:
            errors.append(f"synced line {row['line']} at {row['a']:.2f}s: first word outside anchor tolerance")
        for word in local:
            if (row.get('timing_source') != 'synced_time_without_voice_support'
                    and not any(a - .05 <= word['a'] < b for a, b in ctx['regions'])):
                errors.append(f"synced line {row['line']} at {row['a']:.2f}s: word at {word['a']:.2f}s is off the sung voice")
                break
            if (word['a'] < row['a'] - CLOCK_TOLERANCE or word['a'] >= row['end_time']
                    or word['a'] > row.get('placement_end', row['end_time']) + .001):
                errors.append(f"synced line {row['line']} at {row['a']:.2f}s: word crosses section boundary")
                break
    return errors
