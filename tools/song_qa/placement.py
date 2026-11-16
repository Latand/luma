#!/usr/bin/env python3
"""Read-only placement screens; all times are seconds and indices are zero based.
Usage: python tools/song_qa/placement.py PACKAGE FEATURES.npz OUTPUT.json
       [--review SPANS.json] [--synced SOURCE.lrc] [--base ORIGINAL.json]

Review spans: [{"a":0,"b":2,"syllables":4,"role":"intro"}].
Roles: intro, response, scream, phrase. Optional synced and burst_start
supply explicit line-clock comparisons. See docs/SONG_QA.md for interpretation.
Output contains indices and times. Confidence ranks picture-review candidates.
"""
import argparse
import json
import math
import re
from pathlib import Path
import numpy as np
from common import write_json
from candidates import runs


def rounded(value):
    return round(float(value), 3)


class Evidence:
    def __init__(self, song, features):
        self.song, self.F = song, features
        self.audio_t = features['qa_t']
        loud = features['qa_db'] > max(-65, float(np.percentile(features['qa_db'], 95))-48)
        self.harmonic = loud & (features['qa_periodicity'] > .35) & (features['qa_concentration'] > .035)
        points = song.get('points', [])
        self.t = np.array([p[0] for p in points])
        self.m = np.array([np.nan if p[1] is None else p[1] for p in points])
        self.voiced = np.isfinite(self.m)
        self.strong = np.array([], dtype=float)
        env = features['env']
        threshold = .25 * np.percentile(env, 99.5) if len(env) else 0
        self.strong_threshold=float(threshold)
        if threshold > 0:
            self.strong = features['onset_start'][features['onset_strength'] >= threshold]
        # Absence alone supplies no edge: require an actual contour transition.
        changes = np.flatnonzero(self.voiced[1:] != self.voiced[:-1]) + 1
        self.edges = self.t[changes]
        if len(self.t) and self.voiced[0]: self.edges = np.r_[self.t[0], self.edges]
        self.starts = []
        for a, b in runs(self.voiced):
            if a == 0 or self.t[a] - self.t[a-1] + self._gap(a) >= .04-1e-6:
                self.starts.append(float(self.t[a]))
            last = float(self.t[a])
            for i in range(a+1, b):
                j = max(a, int(np.searchsorted(self.t, self.t[i]-.15-1e-6)))
                if (abs(self.m[i]-self.m[j]) >= .8-1e-6 and
                    (self.t[i]-last >= .15-1e-6 or abs(self.m[i]-self.m[i-1]) >= .8-1e-6)):
                    self.starts.append(float(self.t[i])); last = float(self.t[i])
        self.starts = np.array(sorted(set(self.starts)))

    def _gap(self, a):
        j = a-1
        while j >= 0 and not self.voiced[j]: j -= 1
        return self.t[a-1] - self.t[j+1] if j+1 < a else 0

    def signs(self, at):
        result = []
        if np.any(np.abs(self.edges-at) <= .08+1e-6): result.append('gap')
        local = self.m[np.abs(self.t-at) <= .08+1e-6]
        local = local[np.isfinite(local)]
        if len(local) >= 4 and np.ptp(local) >= .8-1e-6: result.append('step')
        if np.any(np.abs(self.strong-at) <= .06+1e-6): result.append('burst')
        return result

    def level(self, at):
        local = self.m[np.abs(self.t-at) <= .25+1e-6]
        return (at >= .25 and at+.25 <= self.song['duration'] and
                len(local) >= 20 and np.isfinite(local).all() and
                np.max(np.abs(local-np.median(local))) <= .5+1e-6)

    def density(self, a, b):
        return float(np.sum((self.strong >= a) & (self.strong < b))/(b-a))

    def span(self, a, b):
        density = self.density(a, b)
        mask = (self.t >= a) & (self.t < b)
        pitches = self.m[mask]
        fixed = np.rint(pitches[np.isfinite(pitches)])
        short = []
        # Rounded-pitch runs describe hopping; simultaneous partials still need eyes.
        q = np.where(np.isfinite(pitches), np.rint(np.nan_to_num(pitches)), -999)
        edges = np.r_[0, np.flatnonzero(np.diff(q)) + 1, len(q)]
        for lo, hi in zip(edges[:-1], edges[1:]):
            if hi > lo and q[lo] != -999: short.append((hi-lo)*.02 < .5)
        hopping = len(set(fixed)) >= 2 and bool(short) and np.mean(short) >= .6
        band = 'articulated' if density >= 1.5-1e-6 else 'sparse' if density <= .6+1e-6 else 'uncertain'
        return dict(a=rounded(a), b=rounded(b), density=rounded(density),
                    segments=int(np.sum((self.starts >= a) & (self.starts < b))),
                    band=band, hopping=bool(hopping),
                    decision='inspect_formants' if band=='articulated' else
                             'inspect_parallel_partials_for_pad' if band=='sparse' and hopping else 'operator_review',
                    confidence=.6 if band!='uncertain' else .3)

    def harmonic_fraction(self, a, b):
        lo, hi = np.searchsorted(self.audio_t, [a, b])
        return rounded(np.mean(self.harmonic[lo:hi])) if hi > lo else 0.


def read_synced(path):
    out = []
    for raw in Path(path).read_text().splitlines():
        match = re.match(r'^\[(\d+):(\d+(?:\.\d+)?)\](.*)$', raw)
        if match and match[3].strip():
            out.append({'a': int(match[1])*60+float(match[2]), 'text': match[3]})
    if not out: raise ValueError('synced source contains no timed nonempty rows')
    return out


def key(text):
    return re.findall(r"[\w']+", text.lower().replace('’', "'"))


def clock_check(E, spec):
    stamp, proposed = spec['synced'], spec['burst_start']
    signs = np.unique(np.r_[E.edges, E.starts, E.strong])
    nearby = [float(t) for t in signs if abs(t-stamp) <= .5+1e-6 and E.signs(t)]
    strong = [t for t in nearby if np.any(np.abs(E.strong-t) < 1e-6)]
    chosen = min(strong or nearby, key=lambda t: abs(t-stamp)) if nearby else stamp
    match = spec['syllables'] == E.span(spec['a'], spec['b'])['segments']
    # A witness stores a measured independent word/section clock.
    witness = spec.get('witness', {})
    if not isinstance(witness, dict): witness = {}
    witness_ok = (witness.get('kind') in ('recognizer', 'repeat', 'section') and
                  isinstance(witness.get('a'), (int, float)) and
                  not isinstance(witness['a'], bool) and math.isfinite(witness['a']) and abs(witness['a']-proposed) <= .3+1e-6)
    can_override = (not nearby and abs(proposed-stamp) <= 3+1e-6 and
                    spec['a'] <= proposed < spec['b'] and bool(E.signs(proposed)) and match and witness_ok)
    return dict(type='synced_clock', a=rounded(min(stamp,proposed)), b=rounded(max(stamp,spec['b'])), synced=rounded(stamp),
                proposed=rounded(proposed), delta=rounded(proposed-stamp),
                conflict=abs(proposed-stamp) > .5+1e-6,
                boundary_near_stamp=bool(nearby), segment_match=match, witness=witness_ok,
                decision='keep_nearest_sign' if nearby else 'override_candidate' if can_override else 'keep_stamp_doubtful',
                chosen=rounded(proposed if can_override else chosen), confidence=.7 if nearby or can_override else .3)


def validate_spans(spans, duration):
    for s in spans:
        if (s.get('role') not in ('intro', 'response', 'scream', 'phrase') or
            not all(isinstance(s.get(k), (int, float)) and not isinstance(s[k], bool) and math.isfinite(s[k]) for k in ('a','b')) or
            not 0 <= s['a'] < s['b'] <= duration or
            type(s.get('syllables')) is not int or s['syllables'] < 1):
            raise ValueError('review span requires role, bounded times and positive syllables')
        for field in ('synced', 'burst_start'):
            if field in s and (not isinstance(s[field], (int,float)) or not math.isfinite(s[field]) or not 0 <= s[field] < duration):
                raise ValueError('clock time outside song')
        if ('synced' in s) != ('burst_start' in s):
            raise ValueError('clock comparison needs synced and burst_start')


def parallel_candidates(F, duration):
    """Two competing non-octave combs; voice identity requires the picture."""
    if 'qa_sal' not in F: return []
    sal, midi, t = F['qa_sal'], F['qa_midi'], F['qa_t']
    best = sal.argmax(axis=0); lead = midi[best]
    distance = np.abs(midi[:, None]-lead)
    eligible = (distance >= 2) & (distance <= 10) & (F['qa_ratio'] > .2)
    competing = np.where(eligible, sal, 0)
    second = competing.argmax(axis=0)
    columns = np.arange(len(t))
    ratio = competing[second, columns]/(sal[best, columns]+1e-9)
    loud = F['qa_db'] > max(-65, float(np.percentile(F['qa_db'],95))-48)
    mask = loud & (F['qa_periodicity'] > .35) & (F['qa_concentration'] > .035) & (ratio >= .55) & (t < duration)
    out=[]
    for a,b in runs(mask):
        if t[b-1]+.02-t[a] < .2-1e-6: continue
        out.append(dict(type='parallel_harmonics',a=rounded(t[a]),b=rounded(t[b-1]+.02),
                        pitches=[rounded(np.median(lead[a:b])),rounded(np.median(midi[second[a:b]]))],
                        confidence=rounded(.5+.2*min(1,float(np.median(ratio[a:b])))),
                        decision='inspect_lead_and_second_voice'))
    return out


def screen(song, F, spans=(), synced=(), base=None):
    validate_spans(spans, song['duration'])
    E = Evidence(song, F)
    words = [w for l in song.get('lyrics', []) for w in l['words']]
    old = [w for l in (base or song).get('lyrics', []) for w in l['words']]
    comparable = len(old)==len(words) and all(w['w']==o['w'] for w,o in zip(words,old))
    flags, missing = [], 0
    for i, w in enumerate(words):
        signs = E.signs(w['a']); missing += not bool(signs)
        reasons = []
        if not signs: reasons.append('no_boundary')
        if E.level(w['a']): reasons.append('inside_level_note')
        if w.get('c',1) <= .3 or w.get('timing_source')=='vocal_stem_energy': reasons.append('unplaced_origin')
        if any(s['a'] <= w['a'] < s['b'] for s in song.get('unpitched',[]) if s['kind']=='scream') or any(s['role']=='scream' and s['a'] <= w['a'] < s['b'] for s in spans): reasons.append('scream_doubtful')
        if reasons:
            nearest = float(E.starts[np.argmin(abs(E.starts-w['a']))]) if len(E.starts) else None
            flags.append(dict(type='word_start', word=i, a=w['a'], b=w['b'], reasons=reasons, signs=signs,
                              nearest_segment=rounded(nearest) if nearest is not None else None, confidence=.7 if not signs else .4))
        if comparable and abs(w['a']-old[i]['a']) > .1+1e-6:
            flags.append(dict(type='moved_word', word=i, a=w['a'], b=w['b'], previous=old[i]['a'], signs=signs,
                              decision='record_sign' if signs else 'supply_vowel_change_or_review', confidence=.5))
    # A sustained harmonic tail after a line's final word deserves an end check.
    for line in song.get('lyrics', []):
        if not line['words']: continue
        w = line['words'][-1]; a=w['b']; t=F['qa_t']
        if E.harmonic_fraction(max(w['a'],a-.2),a) < .6: continue
        end=a
        for j in np.flatnonzero((t >= a) & (t < min(song['duration'],a+3))):
            if E.harmonic_fraction(float(t[j]),float(t[j])+.02) < .5: break
            end=float(t[j])+.02
        if end-a >= .25:
            flags.append(dict(type='held_word_tail', a=rounded(a), b=rounded(end), confidence=.5,
                              decision='extend_only_if_same_partial_continues'))
    intros = []
    for a in np.arange(0, min(20, song['duration']), 2):
        b=min(float(a+4),song['duration'])
        if b>a:
            item=E.span(float(a),b); item['harmonic_fraction']=E.harmonic_fraction(a,b); intros.append(item)
    for spec in spans:
        item=E.span(spec['a'],spec['b']); item.update(type=spec['role'],syllables=spec['syllables'])
        if spec['role']=='response':
            held_pitch=E.m[(E.t >= spec['a']-.08) & (E.t < spec['b'])]
            held=bool(len(held_pitch) and np.isfinite(held_pitch).all() and np.max(np.abs(held_pitch-np.median(held_pitch))) <= .5+1e-6)
            item.update(room=spec['b']-spec['a'] >= .15*spec['syllables']-1e-6,
                        articulation=item['density'] >= 1.5-1e-6 or item['segments'] >= spec['syllables'], lead_continues=bool(held))
            item['decision']='inspect_independent_lead' if item['room'] and item['articulation'] and not held else 'exclude_if_absent_from_synced'
        flags.append(item)
        if 'synced' in spec: flags.append(clock_check(E,spec))
    # Exact normalized row matching is deliberately conservative; unmatched text is listed.
    used=set()
    for rowid,row in enumerate(synced):
        matches=[(i,l) for i,l in enumerate(song.get('lyrics',[])) if i not in used and key(' '.join(w['w'] for w in l['words']))==key(row['text'])]
        if not matches:
            flags.append(dict(type='synced_unmatched', row=rowid, a=row['a'], b=row['a'],confidence=.3)); continue
        lid,line=min(matches,key=lambda pair:abs(pair[1]['a']-row['a'])); used.add(lid)
        delta=line['a']-row['a']
        if abs(delta) > .5+1e-6:
            flags.append(dict(type='synced_disagreement',line=lid,a=min(row['a'],line['a']),b=max(row['a'],line['b']),synced=row['a'],proposed=line['a'],delta=rounded(delta),confidence=.6,decision='requires_segment_count_and_witness'))
    first_candidates=[]
    for at in E.strong[E.strong < min(20, song['duration'])]:
        end=min(float(at+2),song['duration'])
        if end<=at: continue
        density=E.density(float(at),end); harmonic=E.harmonic_fraction(float(at),end)
        if density >= 1.5-1e-6 and harmonic > 0:
            stamp=synced[0]['a'] if synced else None
            first_candidates.append(dict(a=rounded(at),b=rounded(end),density=rounded(density),harmonic_fraction=harmonic,
                synced=stamp,delta=rounded(at-stamp) if stamp is not None else None,
                decision='confirm_moving_formants',confidence=.6))
    if synced:
        for lid,line in enumerate(song.get('lyrics',[])):
            if lid not in used:
                item=E.span(line['a'],line['b'])
                item.update(type='target_unsynced',line=lid,decision='count_syllables_and_check_independent_lead')
                flags.append(item)
    flags.extend(parallel_candidates(F,song['duration']))
    return dict(strong_onsets=[rounded(t) for t in E.strong],onset_strength_threshold=rounded(E.strong_threshold),
                first_word_candidates=first_candidates,thresholds=dict(strong_onset_p995=.25,boundary_edge_s=.08,boundary_step_semitones=.8,boundary_burst_s=.06,review_share=.2),
                words=len(words),without_boundary=missing,without_boundary_share=round(missing/len(words),4) if words else 0,
                review_required=bool(words and missing/len(words)>.2),base_comparable=comparable,
                flags=flags,intro_windows=intros,segment_starts=[rounded(t) for t in E.starts])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('package',type=Path); ap.add_argument('features',type=Path); ap.add_argument('output',type=Path)
    ap.add_argument('--review',type=Path); ap.add_argument('--synced',type=Path); ap.add_argument('--base',type=Path)
    a=ap.parse_args()
    output=a.output.resolve(); package=a.package.resolve()
    inputs=[p.resolve() for p in (a.features,a.review,a.synced,a.base) if p]
    if output==package or package in output.parents or output in inputs:
        ap.error('output must be outside the package and distinct from input files')
    song=json.loads((a.package/'target.json').read_text())
    with np.load(a.features) as F:
        report=screen(song,F,json.loads(a.review.read_text()) if a.review else [],read_synced(a.synced) if a.synced else [],json.loads(a.base.read_text()) if a.base else None)
    write_json(a.output,report)
    print(json.dumps({k:report[k] for k in ('words','without_boundary','without_boundary_share','review_required')}))

if __name__=='__main__': main()
