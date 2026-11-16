"""Score neutral benchmark JSON against a target. No audio/model dependencies.

python -m tools.song_auto.bench.score OUTPUT.json REFERENCE.json
"""
import argparse
import bisect
import json
import math
import statistics
import unicodedata


def norm(word):
    return ''.join(c for c in unicodedata.normalize('NFC', word.lower().replace('’', "'"))
                   if c.isalnum() or c == "'").strip("'")


def words(target):
    return [w for line in target.get('lyrics', []) for w in line['words']]


def matches(reference, predicted):
    """Maximum ordered exact-token matches, independent of reference times.

    On equal suffix scores skip a prediction first. This fixed tie rule retains
    the earliest reference occurrence; ambiguous repeated text remains a limit.
    """
    a, b = [norm(w['w']) for w in reference], [norm(w['w']) for w in predicted]
    table = [[0]*(len(b)+1) for _ in range(len(a)+1)]
    for i in range(len(a)-1, -1, -1):
        for j in range(len(b)-1, -1, -1):
            table[i][j] = 1+table[i+1][j+1] if a[i] == b[j] else max(table[i+1][j], table[i][j+1])
    result = {}; i = j = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]: result[i] = j; i += 1; j += 1
        elif table[i][j+1] >= table[i+1][j]: j += 1
        else: i += 1
    return result


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate(output):
    if output.get('schema') != 'song-auto-bench.v1': raise ValueError('unknown neutral schema')
    if not finite(output.get('duration')) or output['duration'] <= 0: raise ValueError('invalid duration')
    if not finite(output.get('hop')) or output['hop'] <= 0: raise ValueError('invalid hop')
    for field in ('words', 'pitch'):
        if output.get(field) is None: continue  # component was not run
        previous = -1
        for item in output[field]:
            at = item.get('a' if field == 'words' else 't')
            if not finite(at) or not 0 <= at < output['duration'] or (field == 'pitch' and at < previous):
                raise ValueError('invalid or unordered time')
            if field == 'pitch' and at == previous: raise ValueError('duplicate pitch time')
            previous = at
            confidence = item.get('confidence')
            if not finite(confidence) or not 0 <= confidence <= 1: raise ValueError('invalid confidence')
            if field == 'words':
                if not isinstance(item.get('w'), str) or not norm(item['w']): raise ValueError('invalid word')
                if not finite(item.get('b')) or not at < item['b'] <= output['duration']+.005:
                    raise ValueError('invalid word end')
            else:
                voiced, hz = item.get('voiced'), item.get('hz')
                if type(voiced) is not bool or (voiced and (not finite(hz) or hz <= 0)) or (not voiced and hz is not None):
                    raise ValueError('inconsistent voicing')


def pickup_indices(reference):
    """Reproducible proxy: short word(s) immediately before a held-note word.

    Reference timing defines the evaluation subset only, never model inputs.
    This cannot establish syllable counts or a musically annotated pickup set.
    """
    ws = words(reference)
    held = [n for n in reference.get('notes', []) if not n.get('ignored') and n['b']-n['a'] >= .6-1e-9]
    result = set()
    for j, w in enumerate(ws):
        if not any(abs(n['a']-w['a']) <= .12+1e-9 and n['b'] <= w['b']+.2 for n in held): continue
        for i in range(j-1, max(-1, j-3), -1):
            if ws[i]['b']-ws[i]['a'] > .3+1e-9 or ws[i+1]['a']-ws[i]['b'] > .15+1e-9: break
            result.add(i)
    return result


def word_metrics(reference, predicted, exclude_low=False, pickups=False, common=None):
    refs = words(reference); mapping = matches(refs, predicted)
    subset = pickup_indices(reference) if pickups else set(range(len(refs)))
    if common is not None: subset &= common
    indices = [i for i in sorted(subset) if not exclude_low or refs[i].get('c', 1) > .4]
    errors = [abs(refs[i]['a']-predicted[mapping[i]]['a']) if i in mapping else math.inf for i in indices]
    median = statistics.median(errors) if errors else None
    return dict(n=len(errors), matched=sum(math.isfinite(e) for e in errors),
                median_ms=1000*median if median is not None and math.isfinite(median) else None,
                within80=sum(e <= .08+1e-9 for e in errors)/len(errors) if errors else None,
                within200=sum(e <= .2+1e-9 for e in errors)/len(errors) if errors else None,
                extra=len(predicted)-len(mapping),
                crossing_starts=sum(b['a'] < a['a'] for a,b in zip(predicted,predicted[1:])),
                errors_s=[e if math.isfinite(e) else None for e in errors])


def sample_pitch(output, at):
    times = [p['t'] for p in output['pitch']]
    result = []
    for t in at:
        i = bisect.bisect_left(times, t)
        candidates = [j for j in (i-1, i) if 0 <= j < len(times)]
        j = min(candidates, key=lambda j: abs(times[j]-t)) if candidates else None
        p = output['pitch'][j] if j is not None and abs(times[j]-t) <= output['hop']/2+1e-7 else None
        result.append(69+12*math.log2(p['hz']/440) if p and p['voiced'] else None)
    return result


def runs(mask):
    start = None
    for i, value in enumerate([*mask, False]):
        if value and start is None: start = i
        if not value and start is not None:
            yield start, i
            start = None


def pitch_metrics(reference, output):
    points = reference['points']; ts = [p[0] for p in points]
    predicted = sample_pitch(output, ts)
    spans = reference.get('unpitched', [])
    unpitched = [any(s['a'] <= t < s['b'] for s in spans) for t in ts]
    eligible = [i for i, p in enumerate(points) if p[1] is not None and not unpitched[i]]
    errors = [abs(predicted[i]-points[i][1]) if predicted[i] is not None else math.inf for i in eligible]
    good = sum(e <= .5+1e-9 for e in errors)
    octave = sum(any(abs(e-12*k) <= .5+1e-9 for k in range(1, 8)) for e in errors)
    false = sum(p is not None and u for p, u in zip(predicted, unpitched))
    held = broken = gaps = missed = long_gaps = 0
    hop = reference['hop']
    for n in reference.get('notes', []):
        if n.get('ignored') or n['b']-n['a'] < .6-1e-9: continue
        ids = [i for i, t in enumerate(ts) if n['a'] <= t < n['b']-1e-7]
        if not ids or any(points[i][1] is None or unpitched[i] for i in ids): continue
        held += 1
        present = [predicted[i] is not None for i in ids]
        if not any(present): missed += 1
        internal = [(a, b) for a, b in runs([not v for v in present]) if a > 0 and b < len(ids)]
        broken += bool(internal); gaps += len(internal)
        long_gaps += sum((b-a)*hop >= .06-1e-9 for a,b in internal)
    return dict(voiced_frames=len(errors), within50_frames=good,
                within50=good/len(errors) if errors else None, octave_frames=octave,
                octave=octave/len(errors) if errors else None,
                unpitched_frames=sum(unpitched), false_unpitched_frames=false,
                false_unpitched=false/sum(unpitched) if any(unpitched) else None,
                held_notes=held, broken_held=broken, internal_gaps=gaps, gaps_ge60ms=long_gaps, missed_held=missed,
                voiced_recall=sum(math.isfinite(e) for e in errors)/len(errors) if errors else None)


def score(reference, output, baseline_target=None):
    validate(output)
    if abs(reference['duration']-output['duration']) > .1: raise ValueError('duration mismatch')
    result = dict(words={name: word_metrics(reference, output['words'], low, pickup)
                       for name, low, pickup in [('all', False, False), ('confident', True, False),
                                                 ('pickup_all', False, True), ('pickup_confident', True, True)]}
                if output.get('words') is not None else None,
                pitch=pitch_metrics(reference, output) if output.get('pitch') is not None else None)
    if baseline_target is not None and result['words'] is not None:
        common = set(matches(words(reference), words(baseline_target)))
        result['words'].update({name: word_metrics(reference, output['words'], low, False, common)
                               for name,low in [('common_all',False),('common_confident',True)]})
    return result


def pool_scores(scores):
    """Pool word errors and frame/event counts, never average song medians."""
    result = dict(words={}, pitch=None)
    modes = sorted({mode for s in scores for mode in (s.get('words') or {})})
    for mode in modes:
        items = [s['words'][mode] for s in scores if s.get('words') and mode in s['words']]
        errors = [math.inf if e is None else e for item in items for e in item['errors_s']]
        median = statistics.median(errors) if errors else math.inf
        result['words'][mode] = dict(n=len(errors), matched=sum(math.isfinite(e) for e in errors),
            median_ms=median*1000 if math.isfinite(median) else None,
            within80=sum(e <= .08+1e-9 for e in errors)/len(errors) if errors else None,
            within200=sum(e <= .2+1e-9 for e in errors)/len(errors) if errors else None,
            extra=sum(i['extra'] for i in items), crossing_starts=sum(i.get('crossing_starts',0) for i in items))
    items = [s['pitch'] for s in scores if s.get('pitch') is not None]
    if items:
        fields = ('voiced_frames','within50_frames','octave_frames','unpitched_frames','false_unpitched_frames',
                  'held_notes','broken_held','internal_gaps','gaps_ge60ms','missed_held')
        p = {key:sum(i[key] for i in items) for key in fields}
        for key, numerator, denominator in [('within50','within50_frames','voiced_frames'),
                                            ('octave','octave_frames','voiced_frames'),
                                            ('false_unpitched','false_unpitched_frames','unpitched_frames')]:
            p[key] = p[numerator]/p[denominator] if p[denominator] else None
        p['voiced_recall'] = sum(i['voiced_recall']*i['voiced_frames'] for i in items if i['voiced_recall'] is not None)/p['voiced_frames'] if p['voiced_frames'] else None
        result['pitch'] = p
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output'); ap.add_argument('reference')
    ap.add_argument('--baseline', help='optional saved target for common-text sensitivity')
    args = ap.parse_args()
    with open(args.output) as f: output = json.load(f)
    with open(args.reference) as f: reference = json.load(f)
    baseline_target = None
    if args.baseline:
        with open(args.baseline) as f: baseline_target = json.load(f)
    print(json.dumps(score(reference, output, baseline_target), allow_nan=False))


if __name__ == '__main__': main()
