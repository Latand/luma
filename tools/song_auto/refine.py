"""Conservative, offline boundary proposals. Thresholds are fixed before scoring.

Times are seconds; no reference timing or reference contour is accepted here.
"""
from __future__ import annotations

import copy
import re

import numpy as np

RADIUS = .25  # one half of QA's 500 ms held-note exclusion window
GAP = .04


def syllables(word):
    """First CMU pronunciation, including every component of a compound.

    Unknown spellings return None rather than a guessed vowel-letter count.
    """
    from studio.phonemes import dictionary, key
    if any(c.isdigit() for c in word):
        return None
    parts = re.findall(r"[a-z]+(?:'[a-z]+)*", key(word))
    if not parts or ''.join(parts) != re.sub(r"[-\s]", '', key(word)):
        return None
    counts = []
    for part in parts:
        phones = dictionary().get(part)
        if not phones:
            return None
        counts.append(sum(p[-1:] in ('0', '1', '2') for p in phones.split()))
    return sum(counts) or None


def boundaries(E):
    """Reuse QA edges/steps/onsets, rejecting held-note ticks and returning bends.

    A pitch step needs an 80 ms plateau on either side and must not return to
    the old pitch during the following 150 ms. This rejects vibrato cycles;
    short ambiguous scoops remain review items rather than extra syllables.
    """
    steps = []
    for at in E.starts:
        left = E.m[(E.t >= at-.08-1e-6) & (E.t < at)]
        right = E.m[(E.t >= at) & (E.t <= at+.08+1e-6)]
        tail = E.m[(E.t > at+.08+1e-6) & (E.t <= at+.15+1e-6)]
        if (len(left) >= 3 and len(right) >= 3 and
                np.isfinite(left).all() and np.isfinite(right).all() and
                abs(np.median(right)-np.median(left)) >= .8-1e-6 and
                np.ptp(left) <= .5+1e-6 and np.ptp(right) <= .5+1e-6 and
                not np.any(np.abs(tail-np.median(left)) <= .5+1e-6)):
            steps.append(float(at))
    gap_starts = [at for at in E.starts if np.any(abs(E.edges-at) < 1e-6)]
    segments = sorted(set(float(t) for t in np.r_[gap_starts, steps]
                          if not E.level(float(t)) and E.signs(float(t))))
    # Test the stored millisecond time, including at the held-window boundary.
    rounded = sorted(set(round(float(t), 3) for t in np.r_[E.edges, segments, E.strong]))
    signs = [t for t in rounded if not E.level(t) and E.signs(t)]
    return signs, segments


def refine(song, F, baseline=None):
    """Return a new target and audit flags, preserving text, order and word spans.

    Input words have already passed the command's order projection. Keeping
    every input start is always a feasible path. Dynamic programming selects
    supported signs in order, then minimizes displacement; ties prefer earlier
    starts. No later projection can move a selected boundary into a level note.
    """
    from placement import Evidence
    from .bench.score import matches, words
    result = copy.deepcopy(song)
    old, out = words(song), words(result)
    if any(b['a']-a['a'] < GAP-1e-6 for a, b in zip(old, old[1:])):
        raise ValueError('refinement requires ordered starts at least 40 ms apart')
    E = Evidence(song, F)
    signs, segments = boundaries(E)
    mapping = matches(old, words(baseline)) if baseline else {}
    base_words = words(baseline) if baseline else []
    preferred, reasons, counts_audit, offset = {}, {}, {}, 0
    # Only a unique exact count establishes a syllable-to-segment assignment.
    # Excess/missing segments, dictionary misses and melisma stay explicit.
    for line in song.get('lyrics', []):
        row = line['words']
        counts = [syllables(w['w']) for w in row]
        seg = [round(t, 3) for t in segments if row[0]['a']-RADIUS <= t < row[-1]['b']]
        chosen, k = [], 0
        if all(counts) and len(seg) == sum(counts):
            for n in counts:
                chosen.append(seg[k]); k += n
        feasible = (bool(chosen) and all(abs(t-w['a']) <= RADIUS+1e-6 for t,w in zip(chosen,row)) and
                    all(b-a >= GAP-1e-6 for a,b in zip(chosen,chosen[1:])))
        for j,w in enumerate(row):
            i = offset+j
            counts_audit[i] = dict(word_syllables=counts[j],
                                   phrase_syllables=sum(counts) if all(counts) else None,
                                   contour_segments=len(seg), exact_assignment=feasible)
            if feasible:
                preferred[i] = chosen[j]
            elif counts[j] is None or counts[j] > 1 or (all(counts) and len(seg) < sum(counts)):
                reasons[i] = 'syllable_unresolved'
        offset += len(row)
    options = []
    for i,w in enumerate(old):
        nearby = [t for t in signs if abs(t-w['a']) <= RADIUS+1e-6 and 0 <= t < song['duration']-.02]
        candidates = {w['a']: ('keep', True)}
        for at in nearby:
            candidates[at] = ('boundary', False)
        if i in preferred and preferred[i] in nearby:
            # Other candidates remain available when a neighbouring row collides.
            candidates[preferred[i]] = ('syllable_first', False)
        if i in mapping:
            at = round(base_words[mapping[i]]['a'], 3)
            if (abs(at-w['a']) <= RADIUS+1e-6 and E.signs(at) and not E.level(at) and
                    any(abs(t-at) <= .06+1e-6 for t in signs) and
                    0 <= at < song['duration']-.02):
                candidates[at] = ('baseline_boundary', False)
        options.append(sorted(candidates.items()))
    # Cost: unsupported starts, missed unique assignments/fallbacks, movement.
    layers = []
    for i,candidates in enumerate(options):
        layer = []
        has_fallback = any(v[0]=='baseline_boundary' for _,v in candidates)
        for at,(kind,bad) in candidates:
            penalty = int((has_fallback and kind != 'baseline_boundary') or
                          (not has_fallback and i in preferred and kind != 'syllable_first'))
            cost = (int(bad), penalty, abs(at-old[i]['a']))
            previous = [(entry[0],j) for j,entry in enumerate(layers[-1])
                        if entry is not None and at-options[i-1][j][0] >= GAP-1e-6] if i else [((0,0,0.), -1)]
            if not previous:
                layer.append(None); continue
            prev,j = min(previous)
            layer.append((tuple(a+b for a,b in zip(prev,cost)),j))
        layers.append(layer)
    if not old:
        return result, []
    _, j = min((entry[0],j) for j,entry in enumerate(layers[-1]) if entry is not None)
    selected = []
    for i in range(len(old)-1,-1,-1):
        selected.append(options[i][j]); j = layers[i][j][1]
    selected.reverse()
    flags = []
    for i,(w,(at,(kind,bad))) in enumerate(zip(out,selected)):
        limit = selected[i+1][0] if i+1 < len(out) else song['duration']
        w['a'] = at
        # Compounds retain the last subword's end unless the next word caps it.
        w['b'] = round(min(limit,max(at+.02,w['b'])),3)
        why = []
        if bad:
            why.append('inside_level_note' if E.level(at) else
                       'boundary_order_conflict' if any(kind != 'keep' for _,(kind,_) in options[i]) else
                       'no_boundary_in_reach')
        if i in reasons:
            why.append(reasons[i])
        if i in preferred and kind not in ('syllable_first','baseline_boundary'):
            why.append('syllable_order_conflict')
        if why:
            w['c'] = min(.4,w.get('c',1))
        if at != old[i]['a']:
            w['timing_source'] = 'mms_'+kind
        flags.append(dict(type='word_refinement',word=i,a=at,b=w['b'],previous=old[i]['a'],
                          decision=kind,reasons=why,doubtful=bool(why),**counts_audit[i]))
    for row in result.get('lyrics',[]):
        row.update(a=row['words'][0]['a'],b=row['words'][-1]['b'])
    return result, flags
