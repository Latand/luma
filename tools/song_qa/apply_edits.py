#!/usr/bin/env python3
"""Write the eye pass into a song package: word and line times from a timing sheet, melody fixes as frame edits.
Usage: python tools/song_qa/apply_edits.py --help


  apply_edits.py <package_dir> <features.npz> --base <target.json> [--words sheet.txt] [--melody melody.json]
                 [--report out.json] [--dry-run]

--base is the target.json the edits are made against: the package's target.json as lyrics_text.py left it (its
words and their order are the text that is kept) and with the contour as prepared. Every run starts from that base,
so running twice gives the same file, and a sheet can be corrected and applied again.

TIMING SHEET (--words): one word per row, in sung order, a blank row where a new line starts (where the singer
breathes).  Columns:  index  word  start  [end]  [?]
  start/end   12.34   seconds, used as given
              ~12.3   seconds read off the picture: snapped to the nearest onset candidate within 70 ms (the
                      detector's time is finer than the eye); kept as given when no candidate is that near
              o123    onset candidate number 123 of features.npz
  end         left out: the word ends where the level of the stem falls (20 dB under the word's own level for
              60 ms), or 10 ms before the next word when the voice does not let go (legato)
  ?           the placement is doubtful: the word is stored with confidence 0.4 (the trainer draws it dimmer and
              the head marks it «приблизно») and listed in the report for the operator to listen to
The word text of every row must equal the base word in that position; order and text never change here.
Rows starting with # are notes to the reader.

MELODY (--melody): a JSON list of frame edits, applied in order to `points` (the contour, 20 ms frames):
  {"op": "fill",   "a": s, "b": s, "m": midi, "tol": 1.5}   frames with no target in [a, b) get the fundamental
        tracked on the stem inside m ± tol semitones (harmonic sum, smoothed); "over": true also replaces frames
        that already hold a pitch. New frames are draft (ok 0, confidence 0.5): pending visual and listening verification.
  {"op": "octave", "a": s, "b": s, "shift": -12, "lo": midi, "hi": midi}   frames in [a, b) whose pitch lies in
        lo..hi (optional) move by `shift` semitones
  {"op": "clear",  "a": s, "b": s, "lo": midi, "hi": midi}   frames in [a, b) (in lo..hi when given) lose their target
  each edit may carry "why": the sign it was judged by; it is copied into the report.
Notes, phrases, metrics and initialTime are then derived again from the frames by the rule of
studio/prepare_song.py build_map (median-of-5 contour, a new note where it moves more than 0.72 semitones, a note is
confident when 55 % of its frames are), so the notes view, the word anchors and the scoring agree with the contour.
A note whose span, centre and reliability did not change keeps its other values; ids are renumbered in time order.

Validation follows docs/TARGET_MAP_SCHEMA.md; a file that fails it is not written. Audio and every other key stay
as they are. The trainer is rebuilt separately with studio/build_html.py <package_dir>.
"""
from __future__ import annotations
import json, re, sys, math
from common import backup_file, write_json
from pathlib import Path
import numpy as np
import scipy.ndimage as ndi

HOP = .02
STAMP = 'song-qa'

def runs(mask):
    d = np.diff(np.concatenate([[0], mask.astype(int), [0]])); return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))

# ------------------------------------------------------------------ words
def parse_sheet(path: Path):
    rows = []; new_line = True
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].rstrip() if not raw.lstrip().startswith('#') else ''
        if raw.lstrip().startswith('#'): continue
        if not line.strip(): new_line = True; continue
        parts = line.split(); doubt = parts[-1] == '?'
        if doubt: parts = parts[:-1]
        if len(parts) < 3: raise SystemExit(f'sheet row needs index, word, start: {raw!r}')
        rows.append({'k': int(parts[0]), 'w': parts[1], 'a': parts[2], 'b': parts[3] if len(parts) > 3 else None, 'doubt': doubt, 'first': new_line}); new_line = False
    return rows

def resolve(spec: str, F, what: str):
    if spec.startswith('o'):
        if not re.fullmatch(r'o[0-9]+', spec) or int(spec[1:]) >= len(F['onset_start']):
            raise ValueError('invalid onset index')
        return float(F['onset_start'][int(spec[1:])]), 'onset'
    if spec.startswith('~'):
        t = float(spec[1:]); c = F['onset_start']
        if len(c) == 0: return t, 'eye'
        i = int(np.argmin(np.abs(c - t)))
        return (float(c[i]), 'snapped') if abs(c[i] - t) <= .07 else (t, 'eye')
    return float(spec), 'given'

def release(F, a: float, limit: float) -> float:
    """Where the voice lets go after a word that starts at a, or just before `limit` when it never does."""
    t = F['t']; i0, i1 = np.searchsorted(t, [a, limit]); lv = F['rms'][i0:i1]
    if len(lv) < 8: return max(a + .06, limit - .01)
    ref = np.percentile(lv[:max(8, int(.6 / (t[1] - t[0])))], 90); floor = np.percentile(F['rms'], 99.9) - 48
    thr = max(ref - 20, floor); need = int(round(.06 / (t[1] - t[0]))); low = lv < thr; start = int(round(.1 / (t[1] - t[0])))
    for j in range(start, len(lv) - need):
        if low[j:j + need].all(): return float(t[i0 + j])
    return limit - .01

def build_lyrics(base_lines, rows, F, duration):
    import copy
    base = [w for line in base_lines for w in line['words']]
    if len(rows) != len(base):
        raise ValueError('sheet word count differs from base')
    starts, kinds, untouched = [], [], []
    for i, (row, word) in enumerate(zip(rows, base)):
        if row['k'] != i or row['w'] != word['w']:
            raise ValueError(f'sheet row {i} differs from base')
        keep = row['a'] == '='
        start, kind = (word['a'], 'unchanged') if keep else resolve(row['a'], F, 'start')
        if not math.isfinite(start) or not 0 <= start < duration:
            raise ValueError(f'invalid start at row {i}')
        starts.append(start); kinds.append(kind); untouched.append(keep)
    # A snap may consume the space of a neighbouring word. Fall back to the
    # supplied eye times for those snaps, then validate the whole sheet again.
    collisions = []
    for _ in range(len(rows) + 1):
        bad = [i for i in range(len(starts) - 1) if starts[i + 1] - starts[i] <= .03]
        if not bad: break
        changed = False
        for i in bad:
            for j in (i, i + 1):
                if kinds[j] == 'snapped':
                    starts[j] = float(rows[j]['a'][1:]); kinds[j] = 'eye_collision'
                    collisions.append(j); changed = True
        if not changed:
            raise ValueError(f'word starts collide at rows {bad}; use distinct explicit times')
    out = []; lines = []
    for i, (row, word) in enumerate(zip(rows, base)):
        nxt = starts[i + 1] if i + 1 < len(starts) else duration
        w = copy.deepcopy(word)
        if not untouched[i]:
            end = (word['b'] if row['b'] == '=' else
                   resolve(row['b'], F, 'end')[0] if row['b'] is not None else
                   release(F, starts[i], min(nxt, starts[i] + 12)))
            w.update(a=round(starts[i], 3), b=round(min(end, nxt - .005), 3),
                     c=.4 if row['doubt'] else .95, timing_source='reviewed_spectrogram')
        elif row['b'] not in (None, '='):
            raise ValueError(f'row {i}: unchanged start requires unchanged end')
        if row['doubt']: w['c'] = .4
        # Untouched words keep every value; refuse edits that overlap them.
        if not (0 <= w['a'] < w['b'] <= duration) or w['b'] > nxt:
            raise ValueError(f'invalid or overlapping word at row {i}')
        if row['first'] or not lines: lines.append([])
        lines[-1].append(w); out.append(w)
    moves = [abs(w['a'] - old['a']) for w, old in zip(out, base)]
    return ([{'a': line[0]['a'], 'b': line[-1]['b'], 'words': line} for line in lines],
            {'words': len(out), 'lines': len(lines), 'collisions': sorted(set(collisions)),
             'start_kinds': {k: kinds.count(k) for k in sorted(set(kinds))},
             'moved_over_20ms': sum(m > .02 for m in moves),
             'move_median_s': round(float(np.median(moves)), 3) if moves else 0,
             'move_max_s': round(max(moves, default=0), 3),
             'doubtful': [{'k': i, 'a': out[i]['a']} for i, r in enumerate(rows) if r['doubt']]})

# ------------------------------------------------------------------ melody
def track_f0(pkg: Path, a: float, b: float, m: float, tol: float):
    """The fundamental on the 20 ms grid of [a, b), searched only inside m ± tol semitones: harmonic sum over the
    stem's spectrum (8 partials), then a path that prefers small steps. The band is the judgement made by eye; the
    tracker only follows the partial inside it."""
    import soundfile as sf, librosa
    info = sf.info(pkg / 'vocals_44k.flac'); sr = info.samplerate; pad = .2
    s0 = max(0, int((a - pad) * sr)); y, _ = sf.read(pkg / 'vocals_44k.flac', start=s0, stop=int((b + pad) * sr), dtype='float32', always_2d=True); y = y.mean(axis=1)
    n_fft = 4096; S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=441, window='hann')); freqs = np.fft.rfftfreq(n_fft, 1 / sr); st = s0 / sr + np.arange(S.shape[1]) * 441 / sr
    cand = m + np.arange(-tol, tol + 1e-9, .05); f = 440 * 2 ** ((cand - 69) / 12)
    sal = np.zeros((len(cand), S.shape[1]))
    for h in range(1, 9):
        idx = np.clip(f * h / (sr / n_fft), 0, len(freqs) - 2); lo = np.floor(idx).astype(int); fr = (idx - lo)[:, None]
        sal += .8 ** (h - 1) * (S[lo] * (1 - fr) + S[lo + 1] * fr)
    grid = np.arange(int(round(a / HOP)), int(round(b / HOP))) * HOP
    cols = np.clip(np.searchsorted(st, grid), 0, S.shape[1] - 1); sal = np.log(sal[:, cols] + 1e-6)
    # Viterbi: a step of one candidate (5 cents) costs little, a jump across the band costs a lot
    n, T = sal.shape; pen = .08 * np.abs(np.arange(n)[:, None] - np.arange(n)[None, :]); cost = -sal[:, 0]; back = np.zeros((n, T), int)
    for j in range(1, T):
        tot = cost[None, :] + pen; back[:, j] = np.argmin(tot, axis=1); cost = tot[np.arange(n), back[:, j]] - sal[:, j]
    path = np.zeros(T, int); path[-1] = int(np.argmin(cost))
    for j in range(T - 1, 0, -1): path[j - 1] = back[path[j], j]
    mid = cand[path]; edge = float(np.mean((path <= 1) | (path >= n - 2)))
    return grid, ndi.median_filter(mid, size=5, mode='nearest'), edge

def apply_melody(pkg: Path, points, ops):
    log = []
    for op in ops:
        kind = op['op']; a, b = float(op['a']), float(op['b'])
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a < b):
            raise ValueError('invalid melody interval')
        duration = points[-1][0] + HOP if points else 0
        # The final frame can fall just before an audio boundary.
        if a >= duration or b > duration + HOP:
            raise ValueError('melody interval outside contour')
        if 'kind' in op and (kind != 'clear' or op['kind'] not in ('scream', 'noise')):
            raise ValueError('unpitched kind requires clear and scream/noise')
        if kind == 'octave' and op.get('shift') not in (-12, 12):
            raise ValueError('octave shift must be -12 or 12')
        if 'kind' in op and ('lo' in op or 'hi' in op):
            raise ValueError('unpitched clear must remove the whole pitch range')
        if op.get('kind'): a = math.floor((a + 1e-9) / HOP) * HOP
        i0, i1 = np.searchsorted([p[0] for p in points], [a, b]); i0, i1 = int(i0), int(i1)
        lo, hi = op.get('lo', -1e9), op.get('hi', 1e9); n = 0
        if kind == 'fill':
            m, tol = float(op['m']), float(op.get('tol', 1.5))
            if not (math.isfinite(m) and 24 <= m <= 108 and math.isfinite(tol) and 0 < tol <= 12):
                raise ValueError('fill needs a finite MIDI pitch and tolerance in (0, 12]')
            if i0 == i1: raise ValueError('fill interval contains no contour frames')
            grid, mid, edge = track_f0(pkg, i0 * HOP, i1 * HOP, float(op['m']), float(op.get('tol', 1.5)))
            for k, i in enumerate(range(i0, i1)):
                if points[i][1] is None or op.get('over'): points[i] = [points[i][0], round(float(mid[k]), 3), .5, 0]; n += 1
            log.append({**op, 'frames': n, 'seconds': round(n * HOP, 2), 'median_midi': round(float(np.median(mid)), 2), 'at_band_edge': round(edge, 2)})
        elif kind == 'octave':
            for i in range(i0, i1):
                p = points[i]
                if p[1] is not None and lo <= p[1] <= hi:
                    v = p[1] + float(op['shift'])
                    if not 24 <= v <= 108: raise SystemExit(f'octave edit at {p[0]} leaves the MIDI range')
                    points[i] = [p[0], round(v, 3), p[2], p[3]]; n += 1
            log.append({**op, 'frames': n, 'seconds': round(n * HOP, 2)})
        elif kind == 'clear':
            for i in range(i0, i1):
                p = points[i]
                if p[1] is not None and lo <= p[1] <= hi: points[i] = [p[0], None, 0, 0]; n += 1
            log.append({**op, 'frames': n, 'seconds': round(n * HOP, 2)})
        else: raise SystemExit(f'unknown melody op {kind!r}')
    return log

def derive(points, duration, old_notes):
    """Notes, phrases, metrics and initialTime from the frames, by the rule of prepare_song.build_map."""
    ts = np.array([p[0] for p in points]); valid = np.array([p[1] is not None for p in points]); midi = np.array([p[1] if p[1] is not None else np.nan for p in points])
    pdg = np.array([p[2] for p in points]); rel = np.array([p[3] for p in points]).astype(bool)
    for a, b in runs(valid):  # the build drops runs under 5 frames; an edit must not leave one behind
        if b - a < 5:
            for i in range(a, b): points[i] = [points[i][0], None, 0, 0]
            valid[a:b] = False; rel[a:b] = False; midi[a:b] = np.nan
    smooth = np.full(len(ts), np.nan)
    for a, b in runs(valid): smooth[a:b] = ndi.median_filter(midi[a:b], size=5, mode='nearest')
    old = {(n['a'], n['b']): n for n in old_notes}; notes = []; kept = 0
    for a, b in runs(valid):
        cur = int(round(smooth[a])); start = a
        for i in range(a + 1, b + 1):
            if i == b or abs(smooth[i] - cur) > .72:
                if i - start >= 4:
                    c = float(np.median(midi[start:i])); e = float(np.mean(rel[start:i]))
                    n = {'id': 0, 'a': round(float(ts[start]), 3), 'b': round(min(duration, float(ts[i - 1]) + HOP), 3), 'm': round(c, 3), 'n': int(round(c)), 'q': round(float(np.median(pdg[start:i])), 3), 'ok': bool(e >= .55), 'ignored': False}
                    o = old.get((n['a'], n['b']))
                    if o and abs(o['m'] - n['m']) < .002 and o['ok'] == n['ok'] and not o.get('manual'): n = dict(o); kept += 1
                    notes.append(n)
                if i < b: cur = int(round(smooth[i])); start = i
    for k, n in enumerate(notes): n['id'] = k
    intervals = []
    for n in notes:
        if not intervals or n['a'] - intervals[-1][1] > .85: intervals.append([n['a'], n['b']])
        else: intervals[-1][1] = n['b']
    phrases = []
    for a, b in intervals:
        if b - a < .65: continue
        chunks = max(1, int(np.ceil((b - a) / 8)))
        for k in range(chunks):
            aa = a + (b - a) * k / chunks; bb = a + (b - a) * (k + 1) / chunks
            if k and phrases and aa - phrases[-1]['b'] < 0: aa = phrases[-1]['b']
            phrases.append({'id': len(phrases) + 1, 'a': round(max(0, aa - .45), 2), 'b': round(min(duration, bb + .45), 2), 'label': f'Фрагмент {len(phrases) + 1:02d}', 'verified': False})
    comparable = float(rel.sum() * HOP); initial = next((n['a'] for n in notes if n['ok'] and n['b'] - n['a'] > .2), 0)
    metrics = {'notes': len(notes), 'candidateSeconds': round(float(valid.sum() * HOP), 2), 'comparableSeconds': round(comparable, 2), 'comparablePercentOfTrack': round(100 * comparable / duration, 1)}
    return notes, phrases, metrics, max(0, initial - .75), kept

def update_unpitched(song, ops):
    spans = [dict(s) for s in song.get('unpitched', [])]
    for op in ops:
        # Only restored pitched frames or an explicit classification can
        # replace annotations. Octave shifts and ordinary clears keep them.
        if op['op'] != 'fill' and not op.get('kind'): continue
        a, b = max(0, op['a']), min(song['duration'], op['b'])
        if op.get('kind'): a = math.floor((a + 1e-9) / HOP) * HOP
        times = [p[0] for p in song['points']]
        i0, i1 = np.searchsorted(times, [a, b])
        if i0 == i1: continue
        coverage = [(i0, i1)] if op.get('kind') else [
            (i0 + left, i0 + right)
            for left, right in runs(np.array([p[1] is not None for p in song['points'][i0:i1]]))]
        for left, right in coverage:
            # Match full frame coverage so a derived note cannot extend into
            # a retained fractional annotation.
            a, b = times[left], min(song['duration'], round(times[right-1] + HOP, 9))
            kept = []
            for span in spans:
                if span['b'] <= a or span['a'] >= b:
                    kept.append(span); continue
                if span['a'] < a: kept.append({**span, 'b': a})
                if span['b'] > b: kept.append({**span, 'a': b})
            spans = kept
            if op.get('kind'):
                spans.append({'a': a, 'b': b, 'kind': op['kind']})
    spans.sort(key=lambda s: s['a'])
    merged = []
    for span in spans:
        if merged and merged[-1]['kind'] == span['kind'] and span['a'] <= merged[-1]['b']:
            merged[-1]['b'] = max(merged[-1]['b'], span['b'])
        else: merged.append(span)
    if merged or 'unpitched' in song: song['unpitched'] = merged


# ------------------------------------------------------------------ schema
def validate(song):
    d = song['duration']; errs = []
    if not isinstance(d, (int, float)) or not math.isfinite(d) or not 1 <= d <= 2400:
        return ['duration']
    if song.get('hop') != HOP: errs.append('hop must be 0.02')
    spans = song.get('unpitched', [])
    if not isinstance(spans, list): return ['unpitched must be a list']
    previous = 0
    for span in spans:
        if (not isinstance(span, dict) or set(span) != {'a', 'b', 'kind'} or
            span.get('kind') not in ('scream', 'noise') or
            any(not isinstance(span.get(k), (float, int)) or isinstance(span[k], bool) or not math.isfinite(span[k]) for k in ('a', 'b'))):
            errs.append('invalid unpitched span'); continue
        if not 0 <= span['a'] < span['b'] <= d or span['a'] < previous:
            errs.append('unpitched order/range')
        previous = span['b']
        if any(span['a'] <= p[0] < span['b'] and p[1] is not None for p in song['points']):
            errs.append('unpitched overlaps contour')
        if any(n['a'] < span['b'] and n['b'] > span['a'] for n in song['notes']):
            errs.append('unpitched overlaps notes')
    if song.get('schema') != 'luma.song.v1': errs.append('schema')
    P = song['points']
    if len(P) > 300000 or any(P[i][0] >= P[i + 1][0] for i in range(len(P) - 1)): errs.append('points order/count')
    for p in P:
        if len(p) != 4 or not math.isfinite(p[0]) or abs(p[0] / HOP - round(p[0] / HOP)) > .001 or not 0 <= p[2] <= 1 or not (p[1] is None or 24 <= p[1] <= 108) or p[3] not in (0, 1) or not 0 <= p[0] <= d + .02: errs.append(f'point {p}'); break
    N = song['notes']
    if len(N) > 20000: errs.append('too many notes')
    for i, n in enumerate(N):
        if not (0 <= n['a'] < n['b'] <= d + 1e-6) or not 24 <= n['m'] <= 108 or n['n'] != round(n['m']) or n['id'] != i: errs.append(f'note {n}'); break
        if i and n['a'] < N[i - 1]['b'] - 1e-9: errs.append(f'notes overlap at {n["a"]}'); break
    for ph in song.get('phrases', []):
        if not (0 <= ph['a'] < ph['b'] <= d + 1e-6) or ph['id'] < 1: errs.append(f'phrase {ph}'); break
    prev = -1; prev_line = -1
    for l in song.get('lyrics', []):
        # align_lyrics.realign rounds line bounds to 2 decimals and words to 3.
        if not l['words'] or abs(l['a'] - l['words'][0]['a']) > .005000001 or abs(l['b'] - l['words'][-1]['b']) > .005000001 or l['a'] < prev_line: errs.append(f'line at {l["a"]}'); break
        prev_line = l['a']
        for w in l['words']:
            if not (0 <= w['a'] < w['b'] <= d + 1e-6) or w['a'] < prev - 1e-9 or not w['w'] or not 0 <= w['c'] <= 1: errs.append(f'word {w}'); break
            prev = w['b']
    m = song['metrics']
    if m['notes'] != len(N): errs.append('metrics.notes')
    return errs

def main():
    a = sys.argv[1:]
    if '--help' in a: print(__doc__); return
    pos = []; o = {}; i = 0
    while i < len(a):
        if a[i] == '--dry-run': o['dry'] = True; i += 1
        elif a[i].startswith('--'): o[a[i][2:]] = a[i + 1]; i += 2
        else: pos.append(a[i]); i += 1
    if len(pos) != 2 or 'base' not in o: raise SystemExit(__doc__)
    pkg = Path(pos[0]); F = dict(np.load(pos[1])); base = json.loads(Path(o['base']).read_text(encoding='utf-8'))
    cur = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
    for k in ('title', 'artist', 'duration', 'sourceId', 'id'):
        if cur[k] != base[k]: raise SystemExit(f'base and package disagree on {k}')
    song = json.loads(json.dumps(base)); report = {'package': pkg.name}
    if 'words' in o:
        song['lyrics'], report['words'] = build_lyrics(base.get('lyrics', []), parse_sheet(Path(o['words'])), F, song['duration'])
        note = f'word and line times placed by eye on the vocal-stem spectrogram ({STAMP})'
        if note not in song.setdefault('lyricsSource', ''): song['lyricsSource'] += '; ' + note
    if 'melody' in o:
        ops = json.loads(Path(o['melody']).read_text(encoding='utf-8')); before_valid = sum(p[1] is not None for p in song['points'])
        report['melody'] = apply_melody(pkg, song['points'], ops)
        song['notes'], song['phrases'], song['metrics'], song['initialTime'], kept = derive(song['points'], song['duration'], base['notes'])
        update_unpitched(song, ops)
        report['melody_totals'] = {'frames_with_target_before': before_valid, 'after': sum(p[1] is not None for p in song['points']), 'notes_before': len(base['notes']), 'notes_after': len(song['notes']), 'notes_unchanged': kept,
                                   'filled_s': round(sum(x['seconds'] for x in report['melody'] if x['op'] == 'fill'), 2), 'octave_s': round(sum(x['seconds'] for x in report['melody'] if x['op'] == 'octave'), 2), 'cleared_s': round(sum(x['seconds'] for x in report['melody'] if x['op'] == 'clear'), 2)}
        note = f'contour corrected by eye against the vocal-stem spectrogram ({STAMP}), not verified by ear'
        if note not in song.setdefault('createdBy', ''): song['createdBy'] += '; ' + note
    errs = validate(song); report['schema_errors'] = errs
    if 'report' in o: write_json(o['report'], report)
    print(json.dumps({k: v for k, v in report.items() if k != 'melody'}, ensure_ascii=False)[:1500])
    if errs: raise SystemExit('schema errors, nothing written: ' + '; '.join(errs))
    if not o.get('dry'):
        backup_file(pkg / 'target.json')
        write_json(pkg / 'target.json', song)
        print('wrote', pkg / 'target.json')

if __name__ == '__main__': main()
