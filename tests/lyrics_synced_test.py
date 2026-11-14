#!/usr/bin/env python3
"""Synthetic timing evidence, unsafe timelines, cache replay and real CLI dry runs."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
sys.path.insert(0, str(ROOT / 'tests'))
import align_lyrics as al
import lyrics_text as lt
import lyrics_synced as sy
from lyrics_text_test import synthetic_package

PHRASES = ['flim borp dax', 'wug zant narf', 'bim zot plam', 'nuv rek vos']
TIMES = [1., 5., 9., 13.]
TEXT = '\n'.join(PHRASES)
LRC = '\n'.join(f'[00:{t:05.2f}] {p}' for t, p in zip(TIMES, PHRASES))


def fixture():
    voice = np.zeros(1700, dtype=bool)
    for t in TIMES:
        voice[int(t * 100):int((t + 2) * 100)] = True
    regs = al.regions(voice)
    ctx = {'voiced': voice, 'regions': regs, 'phrases': regs, 'duration': 17.,
           'onsets': np.array([t + d for t in TIMES for d in [0., .4, .8, 1.2, 1.6]]),
           'notes': np.array(TIMES)}
    words = [{'w': w, 'a': t + i * .4, 'b': t + i * .4 + .3, 'c': .9}
             for t, p in zip(TIMES, PHRASES) for i, w in enumerate(p.split())]
    song = {'lyrics': al.realign(words, ctx)}
    return ctx, words, song


def majority_fixture(shift=0., offset=0.):
    """Twelve independent phrases; only line six can contradict a stable clock."""
    phrases = [f'flim{i} borp{i} dax{i}' for i in range(12)]
    times = [i * 10 + 1. for i in range(12)]
    voice = np.zeros(12000, dtype=bool)
    db = np.full(12000, -100.)
    for t in times:
        voice[int(t * 100):int((t + 2) * 100)] = True
        db[int(t * 100):int((t + 2) * 100)] = -20.
    regs = al.regions(voice)
    ctx = {'voiced': voice, 'regions': regs, 'phrases': regs, 'duration': 120.,
           'onsets': np.array([t + j * .4 for t in times for j in range(5)]),
           'notes': np.array(times), 'energy_db': db, 'stem_onsets': np.array(times)}
    words = [{'w': w, 'a': t + j * .4, 'b': t + j * .4 + .3, 'c': .9}
             for t, phrase in zip(times, phrases) for j, w in enumerate(phrase.split())]
    stamps = [t - offset + (shift if i == 5 else 0.) for i, t in enumerate(times)]
    lrc = '\n'.join(f'[{int(t // 60):02}:{t % 60:05.2f}] {p}' for t, p in zip(stamps, phrases))
    return ctx, words, {'lyrics': al.realign(words, ctx)}, '\n'.join(phrases), lrc


def supported_majority_fixture(support, shift=-4., offset=0.):
    """Add an incidental attack at the disputed timestamp, independent of ASR."""
    ctx, words, song, text, lrc = majority_fixture(shift, offset)
    t = 51. + shift
    ctx['energy_db'][int(t * 100):int((t + 2) * 100)] = -20.
    ctx['stem_onsets'] = np.sort(np.r_[ctx['stem_onsets'], t])
    if support == 'pitch':
        ctx['voiced'][int(t * 100):int((t + 2) * 100)] = True
        ctx['onsets'] = np.sort(np.r_[ctx['onsets'], [t + j * .4 for j in range(5)]])
    else:
        ctx['voiced'][5100:5300] = False
        ctx['onsets'] = ctx['onsets'][(ctx['onsets'] < 51.) | (ctx['onsets'] >= 53.)]
    ctx['regions'] = al.regions(ctx['voiced'])
    ctx['phrases'] = al.sung_phrases(ctx['regions'])
    return ctx, words, song, text, lrc


class MajorityContradictionTests(unittest.TestCase):
    def correct(self, ctx, words, song, text, lrc):
        return lt.build_correction(Path('synthetic'), song, words, ctx, text, 'mix', lrc)

    def test_single_outlier_retains_its_own_clock_evidence(self):
        _, words, _, _, lrc = majority_fixture(shift=-4.)
        clock = sy.clock_offset(sy.parse_lrc(lrc), words)
        self.assertTrue(clock['validated_without_voice'])
        self.assertEqual(clock['coherent_matches'], 11)
        self.assertEqual(clock['residual_spread_s'], 0.)
        match = clock['line_evidence'][5]
        self.assertEqual(match, {'line': 6, 'synced_time_s': 47., 'asr_time_s': 51.,
                                 'asr_delta_s': 4., 'residual_s': 4., 'unambiguous': True})

    def test_single_early_or_late_line_cannot_use_majority_to_enter_quiet_fallback(self):
        for shift, stamp in [(-4., '47.00'), (4., '55.00')]:
            with self.subTest(shift=shift), self.assertRaisesRegex(
                    lt.LyricsSourceError, rf'line 6 at {stamp}s: phrase evidence contradicts timestamp: .*51.00s'):
                self.correct(*majority_fixture(shift=shift))

    def test_contradiction_is_checked_after_clock_compensation(self):
        # Negative offset keeps all supplied timestamps nonnegative.
        with self.assertRaisesRegex(lt.LyricsSourceError, r'line 6 at 47.00s: .*residual \+4.000s.*offset -4.000s'):
            self.correct(*majority_fixture(shift=-4., offset=-4.))

    def test_pitch_and_energy_cannot_bypass_contradictory_phrase_evidence(self):
        for support in ['pitch', 'energy']:
            for shift in [-4., 4.]:
                for offset in [0., -4.]:
                    with self.subTest(support=support, shift=shift, offset=offset), self.assertRaisesRegex(
                            lt.LyricsSourceError, r'line 6 at (47|55).00s: phrase evidence contradicts timestamp: .*51.00s'):
                        self.correct(*supported_majority_fixture(support, shift, offset))

    def test_supported_lines_accept_ordinary_latency_and_refuse_beyond_tolerances(self):
        # ASR can be early by the onset tolerance, or late by the song's normal
        # latency plus that tolerance. An incidental attack cannot expand it.
        for support in ['pitch', 'energy']:
            for latency, delta, accepted in [(0., 0., True), (.6, .6, True),
                                             (0., 1.5, True), (0., 1.51, False),
                                             (.6, -1.5, True), (.6, -1.51, False),
                                             (.6, 2.1, True), (.6, 2.11, False)]:
                with self.subTest(support=support, latency=latency, delta=delta):
                    ctx, words, song, text, lrc = supported_majority_fixture(support, shift=0.)
                    words = [dict(w, a=w['a'] + (delta if 15 <= i < 18 else latency),
                                  b=w['b'] + (delta if 15 <= i < 18 else latency))
                             for i, w in enumerate(words)]
                    if not accepted:
                        with self.assertRaisesRegex(lt.LyricsSourceError, r'line 6 at 51.00s: phrase evidence contradicts'):
                            self.correct(ctx, words, song, text, lrc)
                        continue
                    result = self.correct(ctx, words, song, text, lrc)
                    self.assertTrue(result['passed'], result['reason'])
                    row = result['anchor_checks'][5]
                    self.assertEqual(row['start'], 51.)
                    if support == 'energy':
                        self.assertEqual(row['timing_source'], 'vocal_stem_energy')
                    elif delta == latency:
                        self.assertEqual(row['timing_source'], 'pitch_supported')

    def test_correct_timestamp_and_missing_quiet_phrase_still_pass(self):
        ctx, words, song, text, lrc = majority_fixture()
        result = self.correct(ctx, words, song, text, lrc)
        self.assertTrue(result['passed'], result['reason'])
        ctx['voiced'][5100:5300] = False
        ctx['regions'] = al.regions(ctx['voiced'])
        ctx['onsets'] = ctx['onsets'][(ctx['onsets'] < 51.) | (ctx['onsets'] >= 53.)]
        ctx['energy_db'][5100:5300] = -100.
        delayed = [dict(w, a=w['a'] + .6, b=w['b'] + .6) for w in words]
        result = self.correct(ctx, delayed, song, text, lrc)
        self.assertTrue(result['passed'], result['reason'])
        self.assertEqual(result['anchor_checks'][5]['start'], 51.)
        self.assertEqual(result['anchor_checks'][5]['clock_evidence']['residual_s'], 0.)
        result = self.correct(ctx, words[:15] + words[18:], song, text, lrc)
        self.assertTrue(result['passed'], result['reason'])
        self.assertEqual(result['anchor_checks'][5]['timing_source'], 'synced_time_without_voice_support')
        self.assertEqual(result['anchor_checks'][5]['start'], 51.)

    def test_repeated_phrase_occurrences_are_explicitly_ambiguous(self):
        _, words, _, _, lrc = majority_fixture(shift=-4.)
        rows = sy.parse_lrc(lrc)
        repeated_asr = words + [dict(w, a=w['a'] + 60.) for w in words[15:18]]
        self.assertFalse(sy.clock_offset(rows, repeated_asr)['line_evidence'][5]['unambiguous'])
        rows[-1]['tokens'] = rows[5]['tokens']
        matches = sy.clock_offset(rows, words)['line_evidence']
        self.assertTrue(all(not m['unambiguous'] for m in matches if m['line'] in [6, 12]))

    def test_out_of_search_range_phrase_still_vetoes_quiet_placement(self):
        ctx, words, song, text, lrc = majority_fixture(shift=-4.)
        # An exact unique occurrence beyond the clock's 30 s search radius
        # retains its contradictory evidence without contributing to the clock.
        words = [dict(w, a=w['a'] + 43., b=w['b'] + 43.) if 15 <= i < 18 else w
                 for i, w in enumerate(words)]
        words.sort(key=lambda w: w['a'])
        with self.assertRaisesRegex(lt.LyricsSourceError, r'line 6 at 47.00s: .*94.00s'):
            self.correct(ctx, words, song, text, lrc)

    def test_cli_refuses_in_fresh_processes_including_force_and_keeps_package_unchanged(self):
        for support in ['quiet', 'pitch', 'energy']:
            with self.subTest(support=support):
                ctx, words, song, text, lrc = majority_fixture(shift=-4.)
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    bursts = [(i * 10 + 1., i * 10 + 3.) for i in range(12)]
                    if support != 'quiet':
                        bursts = sorted(bursts + [(47., 49.)])
                    pkg = synthetic_package(root, bursts=bursts,
                                            asr_words=[f'flim{i}' for i in range(len(bursts))], duration=120.)
                    target = json.loads((pkg / 'target.json').read_text())
                    target['lyrics'] = song['lyrics']
                    if support == 'energy':
                        for point in target['points']:
                            if 47. <= point[0] < 49.:
                                point[1:] = [None, 0., 0]
                        target['notes'] = [n for n in target['notes'] if n['a'] != 47.]
                    ctx = al.context(pkg, target)
                    (pkg / 'target.json').write_text(json.dumps(target))
                    (pkg / 'lyrics/mix.json').write_text(json.dumps({'source': 'mix', 'lines': song['lyrics']}))
                    verified = root / 'verified.txt'; verified.write_text(text)
                    timeline = root / 'lines.lrc'; timeline.write_text(lrc)
                    before = {str(p.relative_to(pkg)): p.read_bytes() for p in pkg.rglob('*') if p.is_file()}
                    command = [sys.executable, str(ROOT / 'studio/lyrics_text.py'), '--text', str(verified),
                               '--synced', str(timeline), '--json', str(pkg)]
                    reports = []
                    for flags in [['--dry-run'], ['--force'], ['--dry-run']]:
                        result = subprocess.run(command + flags, capture_output=True, timeout=90)
                        self.assertEqual(result.returncode, 0)  # Per-package refusal is returned as JSON.
                        report = json.loads(result.stdout)
                        self.assertRegex(report['error'], r'line 6 at 47.00s: phrase evidence contradicts timestamp: .*51.00s')
                        reports.append(result.stdout)
                        self.assertEqual({str(p.relative_to(pkg)): p.read_bytes() for p in pkg.rglob('*') if p.is_file()}, before)
                    self.assertEqual(reports[0], reports[2])
                    # Both realignment and retranscription replay this cache consumer.
                    (pkg / 'lyrics/source.txt').write_text(text)
                    (pkg / 'lyrics/source.meta.json').write_text(json.dumps({
                        'title': target['title'], 'artist': target['artist'], 'synced_lrc': lrc}))
                    cached_before = {str(p.relative_to(pkg)): p.read_bytes() for p in pkg.rglob('*') if p.is_file()}
                    cached_command = [sys.executable, str(ROOT / 'studio/lyrics_text.py'), '--json', str(pkg)]
                    cached_reports = []
                    for flags in [['--dry-run'], ['--force'], ['--dry-run']]:
                        result = subprocess.run(cached_command + flags, capture_output=True, timeout=90)
                        self.assertEqual(result.returncode, 0)
                        self.assertRegex(json.loads(result.stdout)['error'],
                                         r'line 6 at 47.00s: phrase evidence contradicts timestamp: .*51.00s')
                        cached_reports.append(result.stdout)
                        self.assertEqual({str(p.relative_to(pkg)): p.read_bytes() for p in pkg.rglob('*') if p.is_file()}, cached_before)
                    self.assertEqual(cached_reports[0], cached_reports[2])
                    with self.assertRaisesRegex(lt.LyricsSourceError, r'line 6 at 47.00s: phrase evidence contradicts'):
                        al.corrected_seed(pkg, target, words, ctx)
                    with patch.object(al, 'context', return_value=ctx), self.assertRaisesRegex(
                            lt.LyricsSourceError, r'line 6 at 47.00s: phrase evidence contradicts'):
                        lt.process_package(pkg, None, True, rebuild=False, force=True)
                    self.assertEqual({str(p.relative_to(pkg)): p.read_bytes() for p in pkg.rglob('*') if p.is_file()}, cached_before)


class ParserTests(unittest.TestCase):
    def test_metadata_offset_bom_empty_and_multiple_tags(self):
        rows = sy.parse_lrc('\ufeff[ar:synthetic]\n[offset:250]\n[00:01.00][00:02.00] (flim)\n[00:03.00]')
        self.assertEqual([r['a'] for r in rows], [1.25, 2.25, 3.25])
        self.assertEqual(rows[0]['tokens'], ['(flim)'])
        self.assertEqual(rows[-1]['tokens'], [])

    def test_invalid_empty_nonascii_reordered_and_negative_times_refuse(self):
        for text in ['', '[00:01.00]', 'flim', '[00:61] flim', '[00:١٢.00] flim',
                     'x[00:01.00] flim', '[00:02] flim\n[00:01] borp',
                     '[00:01] flim\n[00:01] borp', '[offset:-2000]\n[00:01] flim']:
            with self.subTest(text=text), self.assertRaisesRegex(sy.SyncedLyricsError, 'synced line'):
                sy.parse_lrc(text)


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.words, self.song = fixture()
        self.rows = sy.parse_lrc(LRC)

    def test_matching_clock_and_constant_offset(self):
        self.assertEqual(sy.clock_offset(self.rows, self.words)['offset_s'], 0.)
        shifted = [{**w, 'a': w['a'] + 4} for w in self.words]
        result = sy.clock_offset(self.rows, shifted)
        self.assertEqual(result['offset_s'], 4.)
        self.assertEqual(result['status'], 'offset compensated')

    def test_missing_phrase_evidence_refuses(self):
        with self.assertRaisesRegex(sy.SyncedLyricsError, 'insufficient independent'):
            sy.clock_offset(self.rows, self.words[:6])

    def test_one_heard_occurrence_cannot_validate_three_lines(self):
        rows = sy.parse_lrc('[00:01] flim borp dax\n[00:02] flim borp dax\n[00:03] flim borp dax')
        with self.assertRaisesRegex(sy.SyncedLyricsError, 'independent'):
            sy.clock_offset(rows, self.words[:3])

    def test_missing_early_repeat_cannot_consume_later_clock_evidence(self):
        phrases = [PHRASES[0]] * 3 + [PHRASES[-1]]
        rows = sy.parse_lrc('\n'.join(f'[00:{t:05.2f}] {p}' for t, p in zip(TIMES, phrases)))
        words = [{'w': w, 'a': t + i * .4, 'b': t + i * .4 + .3}
                 for t, phrase in zip(TIMES[1:], phrases[1:]) for i, w in enumerate(phrase.split())]
        clock = sy.clock_offset(rows, words)
        self.assertEqual(clock['offset_s'], 0.)
        self.assertEqual(clock['phrase_matches'], 3)


    def test_distributed_disagreement_refuses_different_edit(self):
        shifted = [{**w, 'a': w['a'] + (6 if i >= 6 else 0)} for i, w in enumerate(self.words)]
        with self.assertRaisesRegex(sy.SyncedLyricsError, 'different edit'):
            sy.clock_offset(self.rows, shifted)

    def test_changed_clock_cannot_hide_in_stable_majority(self):
        rows = [{'a': float(i * 10), 'tokens': [f'a{i}', f'b{i}', f'c{i}'], 'line': i + 1} for i in range(12)]
        words = [{'w': w, 'a': r['a'] + (3 if i >= 9 else 0), 'b': r['a'] + 4}
                 for i, r in enumerate(rows) for w in r['tokens']]
        with self.assertRaisesRegex(sy.SyncedLyricsError, 'clock changes'):
            sy.clock_offset(rows, words)

    def test_ordinary_recognizer_delay_is_not_a_clock_offset(self):
        words = [{**w, 'a': w['a'] + .4} for w in self.words]
        self.assertEqual(sy.clock_offset(self.rows, words)['offset_s'], 0.)


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.words, self.song = fixture()

    def correct(self, words=None, ctx=None, text=TEXT, lrc=LRC):
        return lt.build_correction(Path('synthetic'), self.song,
                                   self.words if words is None else words,
                                   self.ctx if ctx is None else ctx, text, 'mix', lrc)

    def test_success_preserves_text_and_every_boundary(self):
        c = self.correct()
        self.assertTrue(c['passed'], c['reason'])
        self.assertEqual([w['w'] for w in al.flat(c['lines'])], TEXT.split())
        self.assertEqual([c['entries'][i]['a'] for i in [0, 3, 6, 9]], TIMES)
        self.assertEqual(sy.placement_errors(c['anchor_checks'], al.flat(c['lines']), self.ctx), [])

    def test_missing_intro_is_placed_in_its_own_voiced_section(self):
        c = self.correct(words=self.words[3:])
        self.assertTrue(c['passed'], c['reason'])
        self.assertEqual(al.flat(c['lines'])[0]['a'], 1.)
        self.assertLess(al.flat(c['lines'])[2]['a'], 3.)

    def test_complete_performance_text_never_restores_asr_chatter(self):
        chatter = [dict(w, a=w['a'] + 2, b=w['b'] + 2) for w in self.words[:6]]
        c = self.correct(words=sorted(self.words + chatter, key=lambda w: w['a']))
        self.assertTrue(c['passed'], c['reason'])
        self.assertEqual(c['repeats_restored'], 0)
        self.assertEqual(len(c['entries']), 12)

    def test_repeated_word_cannot_steal_a_later_line(self):
        text = TEXT + '\n' + PHRASES[0]
        lrc = LRC + '\n[00:15.20] ' + PHRASES[0]
        ctx = copy.deepcopy(self.ctx)
        ctx['voiced'][1520:1680] = True
        ctx['regions'] = al.regions(ctx['voiced'])
        ctx['phrases'] = ctx['regions']
        ctx['onsets'] = np.r_[ctx['onsets'], [15.2, 15.6, 16.0]]
        c = self.correct(ctx=ctx, text=text, lrc=lrc)
        self.assertTrue(c['passed'], c['reason'])
        self.assertEqual(al.flat(c['lines'])[-3]['a'], 15.2)

    def test_word_order_mapping_handles_small_wording_changes(self):
        mapping = sy.token_mapping(['flim', 'borp', 'dax'], ['flim', 'narf', 'dax'])
        self.assertEqual(mapping, {2: 2, 1: 1, 0: 0})
        rows = sy.sections(sy.parse_lrc(LRC), TEXT.replace('borp', 'new').split())
        self.assertEqual([r['index'] for r in rows], [0, 3, 6, 9])

    def test_different_text_and_missing_line_start_refuse(self):
        with self.assertRaisesRegex(sy.SyncedLyricsError, 'differs'):
            sy.sections(sy.parse_lrc(LRC), ['unrelated'] * 12)
        with self.assertRaisesRegex(sy.SyncedLyricsError, 'line start has no counterpart'):
            sy.sections(sy.parse_lrc(LRC), TEXT.split()[1:])

    def test_unanchored_verified_prefix_refuses(self):
        with self.assertRaisesRegex(lt.LyricsSourceError, 'before the first timed line'):
            self.correct(text='new ' + TEXT)

    def test_offset_is_validated_on_voice_after_compensation(self):
        rows = LRC.replace('[00:01.00]', '[00:00.00]').replace('[00:05.00]', '[00:04.00]')
        # This is a changed edit, even though each phrase could find nearby voice.
        with self.assertRaisesRegex(lt.LyricsSourceError, 'synced line'):
            self.correct(lrc=rows.replace('[00:09.00]', '[00:01.50]'))

    def test_missing_voice_refuses_named_line_and_time(self):
        ctx = copy.deepcopy(self.ctx)
        ctx['onsets'] = ctx['onsets'][ctx['onsets'] >= 5]
        with self.assertRaisesRegex(lt.LyricsSourceError, 'synced line 1 at 1.00s: no vocal attack'):
            self.correct(ctx=ctx)

    def test_offset_is_reported_even_when_a_later_voice_check_refuses(self):
        ctx = copy.deepcopy(self.ctx)
        ctx['duration'] = 21.
        ctx['onsets'] = ctx['onsets'][(ctx['onsets'] < 5) | (ctx['onsets'] >= 9)]
        words = [dict(w, a=w['a'] + 4, b=w['b'] + 4) for w in self.words]
        with self.assertRaisesRegex(lt.LyricsSourceError, r'line 1 at 5.00s: .*offset \+4.000s'):
            self.correct(words=words, ctx=ctx)


    def test_raw_note_inside_instrumental_cannot_validate_an_anchor(self):
        ctx = copy.deepcopy(self.ctx)
        ctx['regions'] = ctx['regions'][1:]
        with self.assertRaisesRegex(lt.LyricsSourceError, 'synced line 1 at 1.00s'):
            self.correct(ctx=ctx)

    def test_timestamp_beyond_recording_refuses_even_if_empty(self):
        with self.assertRaisesRegex(lt.LyricsSourceError, 'outside the recording'):
            self.correct(lrc=LRC + '\n[00:18.00]')

    def test_empty_timed_row_bounds_an_instrumental_break(self):
        c = self.correct(lrc=LRC.replace('[00:05.00]', '[00:03.00]\n[00:05.00]'))
        self.assertTrue(c['passed'], c['reason'])
        self.assertEqual(c['anchor_checks'][0]['end_time'], 3.)
        self.assertLess(al.flat(c['lines'])[2]['a'], 3.)

    def test_too_short_voiced_section_refuses_crowded_words(self):
        ctx = copy.deepcopy(self.ctx)
        ctx['regions'][0] = (1., 1.1)
        with self.assertRaisesRegex(lt.LyricsSourceError, 'insufficient voiced time'):
            self.correct(words=self.words[3:], ctx=ctx)

    def test_crowded_section_reflows_without_moving_line_attack(self):
        words = copy.deepcopy(self.words)
        words[1]['a'], words[2]['a'] = 1.6, 1.61
        c = self.correct(words=words)
        self.assertTrue(c['passed'], c['reason'])
        self.assertEqual(c['entries'][0]['a'], 1.)
        starts = [e['a'] for e in c['entries'][:3]]
        self.assertTrue(all(b - a >= .1 for a, b in zip(starts, starts[1:])))

    def test_section_without_voice_after_anchor_refuses(self):
        ctx = copy.deepcopy(self.ctx)
        lrc = LRC.replace('[00:05.00]', '[00:01.02]')
        with self.assertRaisesRegex(lt.LyricsSourceError, 'no voiced time'):
            self.correct(ctx=ctx, lrc=lrc)

    def test_anchor_that_overlaps_next_row_refuses(self):
        lrc = LRC.replace('[00:05.00]', '[00:01.10]')
        ctx = copy.deepcopy(self.ctx)
        ctx['onsets'] = np.array([1.2, 5., 9., 13.])
        with self.assertRaisesRegex(lt.LyricsSourceError, 'overlaps its neighbour'):
            self.correct(ctx=ctx, lrc=lrc)

    def test_reflow_can_correct_a_matched_occurrence_inside_its_line(self):
        words = copy.deepcopy(self.words)
        words[1]['a'], words[2]['a'] = 2.99, 2.991
        c = self.correct(words=words)
        self.assertTrue(c['passed'], c['reason'])
        self.assertGreater(abs(c['entries'][1]['a'] - words[1]['a']), 1.25)
        self.assertEqual(al.flat(c['lines'])[0]['a'], 1.)
        self.assertLess(al.flat(c['lines'])[2]['a'], 3.)

    def test_reflow_retains_the_substituted_word_guard_after_snapping(self):
        words = copy.deepcopy(self.words)
        words[1].update(w='misheard', a=2.99)
        words[2]['a'] = 2.991
        ctx = copy.deepcopy(self.ctx)
        ctx['onsets'] = np.r_[1., 1.4, 2.2, 2.6, ctx['onsets'][ctx['onsets'] >= 5]]
        c = self.correct(words=words, ctx=ctx)
        self.assertFalse(c['passed'])
        self.assertIn('substituted word moved', c['reason'])
        self.assertIn('synced line 1 at 1.00s', c['reason'])


    def test_final_matched_word_off_voice_blocks_just_as_inserted_word(self):
        c = self.correct()
        words = al.flat(c['lines'])
        words[1]['a'] = 3.5
        errors = sy.placement_errors(c['anchor_checks'], words, self.ctx)
        self.assertTrue(any('line 1 at 1.00s' in e and 'off the sung voice' in e for e in errors))

    def test_final_snap_cannot_cross_boundary_or_move_line_start(self):
        c = self.correct()
        words = al.flat(c['lines'])
        words[0]['a'] = 2.8
        self.assertTrue(any('anchor tolerance' in e for e in sy.placement_errors(c['anchor_checks'], words, self.ctx)))
        words[0]['a'] = 1.
        words[2]['a'] = 5.1
        self.assertTrue(any('section boundary' in e for e in sy.placement_errors(c['anchor_checks'], words, self.ctx)))

    def test_early_next_attack_keeps_the_previous_words_in_their_own_line(self):
        ctx = copy.deepcopy(self.ctx)
        ctx['voiced'][100:700] = True
        ctx['regions'] = al.regions(ctx['voiced'])
        ctx['phrases'] = ctx['regions']
        ctx['onsets'] = np.r_[1., 1.4, 2.8, 4.2, 6.2, 6.6, ctx['onsets'][ctx['onsets'] >= 9]]
        words = copy.deepcopy(self.words)
        words[2]['a'] = 4.3
        result = self.correct(words=words, ctx=ctx)
        self.assertTrue(result['passed'], result['reason'])
        placed = al.flat(result['lines'])
        self.assertEqual(placed[3]['a'], 4.2)
        self.assertLessEqual(placed[2]['a'], placed[3]['a'] - lt.MIN_INSERTED_SPACING_S)

    def test_final_check_protects_the_room_reserved_for_the_next_actual_attack(self):
        result = self.correct()
        words = al.flat(result['lines'])
        ctx = {**self.ctx, 'regions': [(0., 17.)]}
        words[2]['a'] = 4.94
        self.assertEqual(sy.placement_errors(result['anchor_checks'], words, ctx), [])
        words[2]['a'] = 4.98
        self.assertTrue(any('section boundary' in e for e in sy.placement_errors(
            result['anchor_checks'], words, ctx)))


class UnpitchedTests(unittest.TestCase):
    def setUp(self):
        self.ctx, self.words, self.song = fixture()
        self.ctx['voiced'][:300] = False
        self.ctx['regions'] = al.regions(self.ctx['voiced'])
        self.ctx['phrases'] = self.ctx['regions']
        self.ctx['onsets'] = self.ctx['onsets'][self.ctx['onsets'] >= 5]
        self.ctx['energy_db'] = np.full(1700, -80.)
        for t in TIMES[1:]:
            self.ctx['energy_db'][int(t * 100):int((t + 2) * 100)] = -18.
        self.ctx['stem_onsets'] = np.array([1.1, 1.5, 1.9])

    def correct(self, words=None, lrc=LRC):
        return lt.build_correction(Path('synthetic'), self.song,
                                   self.words[3:] if words is None else words,
                                   self.ctx, TEXT, 'mix', lrc)

    def test_a_sustained_stem_energy_places_unpitched_line_on_its_attacks(self):
        self.ctx['energy_db'][110:280] = -20.
        result = self.correct()
        self.assertTrue(result['passed'], result['reason'])
        row = result['anchor_checks'][0]
        self.assertEqual(row['timing_source'], 'vocal_stem_energy')
        self.assertEqual(row['energy']['floor_db'], -80.)
        self.assertEqual(row['energy']['threshold_db'], -53.)
        self.assertEqual(al.flat(result['lines'])[0]['a'], 1.1)
        self.assertFalse(self.ctx['voiced'][:300].any(), 'caller pitch mask must remain untouched')

    def test_a_short_noise_spike_cannot_supply_voice_support(self):
        self.ctx['energy_db'][110:115] = -20.
        row = self.correct()['anchor_checks'][0]
        self.assertEqual(row['timing_source'], 'synced_time_without_voice_support')

    def test_continuous_loud_voice_is_not_mistaken_for_its_own_noise_floor(self):
        self.ctx['energy_db'][:] = -20.
        self.ctx['stem_onsets'] = np.array([1.1, 1.5, 1.9])
        result = self.correct()
        self.assertTrue(result['passed'], result['reason'])
        row = result['anchor_checks'][0]
        self.assertEqual(row['timing_source'], 'vocal_stem_energy')
        self.assertEqual(row['energy']['floor_db'], -40.)

    def test_sustained_voice_at_synced_time_is_energy_supported_without_a_new_attack(self):
        self.ctx['voiced'][500:700] = False
        self.ctx['regions'] = al.regions(self.ctx['voiced'])
        self.ctx['onsets'] = self.ctx['onsets'][self.ctx['onsets'] >= 9]
        self.ctx['energy_db'][:] = -20.
        self.ctx['stem_onsets'] = np.array([])
        result = self.correct(words=self.words)
        row = result['anchor_checks'][1]
        self.assertEqual(row['timing_source'], 'vocal_stem_energy')
        self.assertEqual(row['start'], 5.)
        self.assertTrue(row['energy']['sustained_at_synced_time'])

    def test_closer_stem_attack_replaces_a_pitch_attack_from_previous_phrase(self):
        self.ctx['voiced'][:80] = True
        self.ctx['regions'] = al.regions(self.ctx['voiced'])
        self.ctx['onsets'] = np.r_[.6, self.ctx['onsets']]
        self.ctx['energy_db'][110:280] = -20.
        result = self.correct()
        self.assertTrue(result['passed'], result['reason'])
        self.assertEqual(result['anchor_checks'][0]['start'], 1.1)

    def test_unrelated_asr_cannot_supply_substitution_times_in_a_verified_section(self):
        self.ctx['energy_db'][110:280] = -20.
        words = [dict(w, w='unrelated') if i < 3 else w for i, w in enumerate(self.words)]
        result = self.correct(words=words)
        self.assertTrue(result['passed'], result['reason'])
        self.assertEqual([e['kind'] for e in result['entries'][:3]], ['anchored', 'inserted', 'inserted'])

    def test_b_quiet_stem_uses_validated_clock_and_marks_every_word(self):
        result = self.correct()
        self.assertTrue(result['passed'], result['reason'])
        clock = result['synced_clock']
        self.assertTrue(clock['validated_without_voice'])
        self.assertEqual(clock['agreeing_line_share'], .75)
        self.assertEqual(clock['residual_spread_s'], 0.)
        words = al.flat(result['lines'])
        self.assertEqual(words[0]['a'], 1.)
        self.assertTrue(all(w['timing_source'] == 'synced_time_without_voice_support' for w in words[:3]))
        self.assertFalse(any(lt.in_voice(w['a'], self.ctx) for w in words[:3]))

    def test_b_separation_residue_below_dynamic_floor_stays_unsupported(self):
        self.ctx['energy_db'][100:300] = -65.
        self.assertEqual(self.correct()['anchor_checks'][0]['timing_source'],
                         'synced_time_without_voice_support')

    def test_numerical_silence_in_the_entire_stem_cannot_become_voice_support(self):
        self.ctx['energy_db'][:] = -240.
        result = self.correct()
        self.assertEqual(result['anchor_checks'][0]['timing_source'], 'synced_time_without_voice_support')
        self.assertEqual(result['anchor_checks'][0]['energy']['threshold_db'], -80.)

    def test_c_quiet_line_refuses_when_share_of_all_lines_is_insufficient(self):
        # Three coherent observations can validate local alignment, but cannot
        # authorize quiet passages across eight timed lines.
        rows = sy.parse_lrc(LRC)
        rows += [{'a': float(i), 'tokens': ['unheard', str(i), 'phrase'], 'line': i} for i in range(14, 18)]
        clock = sy.clock_offset(rows, self.words[3:])
        self.assertFalse(clock['validated_without_voice'])
        with patch.object(sy, 'clock_offset', return_value=clock):
            with self.assertRaisesRegex(lt.LyricsSourceError, 'line 1 at 1.00s: .*clock not validated'):
                self.correct()

    def test_c_missing_energy_measurement_cannot_authorize_silent_placement(self):
        del self.ctx['energy_db']
        with self.assertRaisesRegex(lt.LyricsSourceError, 'line 1 at 1.00s'):
            self.correct()

    def test_c_quiet_passage_cannot_count_itself_as_clock_evidence(self):
        with self.assertRaisesRegex(lt.LyricsSourceError, 'line 1 at 1.00s: clock not validated by the other lines'):
            lt.build_correction(Path('synthetic'), self.song, self.words[:9], self.ctx,
                                '\n'.join(PHRASES[:3]), 'mix', '\n'.join(LRC.splitlines()[:3]))

    def test_c_changed_edit_refuses_even_with_loud_unpitched_stem(self):
        self.ctx['energy_db'][110:280] = -20.
        changed = [dict(w, a=w['a'] + (6 if i >= 6 else 0)) for i, w in enumerate(self.words)]
        with self.assertRaisesRegex(lt.LyricsSourceError, 'synced line .*different edit'):
            self.correct(words=changed)

    def test_clock_fallback_requires_narrow_residuals_and_stable_group_medians(self):
        rows = [{'a': float(i * 10 + 1), 'tokens': [f'a{i}', f'b{i}', f'c{i}'], 'line': i + 1}
                for i in range(12)]
        for deltas in ([-.6, .6] * 6, [0.] * 6 + [1.] * 6):
            words = [{'w': w, 'a': r['a'] + d, 'b': r['a'] + d + .1}
                     for r, d in zip(rows, deltas) for w in r['tokens']]
            self.assertFalse(sy.clock_offset(rows, words)['validated_without_voice'])

    def test_quiet_placement_cannot_cross_next_line(self):
        result = self.correct()
        words = al.flat(result['lines'])
        words[2]['a'] = 5.1
        self.assertTrue(any('section boundary' in e for e in sy.placement_errors(
            result['anchor_checks'], words, self.ctx)))

    def test_quiet_first_word_cannot_move_away_from_the_published_time(self):
        result = self.correct()
        words = al.flat(result['lines'])
        words[0]['a'] += .2
        self.assertTrue(any('quiet line moved' in e for e in sy.placement_errors(
            result['anchor_checks'], words, self.ctx)))

    def test_section_snap_retains_a_seed_when_an_attack_would_crowd_its_neighbour(self):
        ctx = {**self.ctx, 'regions': [(1., 3.)], 'onsets': np.array([1., 1.02])}
        seed = [{'w': 'flim', 'a': 1., 'b': 1.2}, {'w': 'borp', 'a': 1.2, 'b': 1.4}]
        checks = [{'index': 0, 'end_index': 2, 'start': 1., 'placement_end': 3., 'timing_source': 'pitch_supported'}]
        placed = al.flat(sy.realign_sections(seed, checks, ctx))
        self.assertEqual([w['a'] for w in placed], [1., 1.2])

    def test_crowded_snap_uses_the_next_voice_attack_when_the_seed_is_in_a_gap(self):
        ctx = {**self.ctx, 'regions': [(1., 1.15), (1.8, 3.)],
               'onsets': np.array([1., 1.02, 1.8, 2.1])}
        seed = [{'w': 'flim', 'a': 1., 'b': 1.2}, {'w': 'borp', 'a': 1.2, 'b': 1.4}]
        checks = [{'index': 0, 'end_index': 2, 'start': 1., 'placement_end': 3., 'timing_source': 'pitch_supported'}]
        placed = al.flat(sy.realign_sections(seed, checks, ctx))
        self.assertEqual([w['a'] for w in placed], [1., 1.8])

    def test_seed_rounding_past_the_last_voiced_frame_uses_the_next_attack(self):
        ctx = {**self.ctx, 'regions': [(1., 1.21), (1.8, 3.)],
               'onsets': np.array([1., 1.02, 1.8])}
        seed = [{'w': 'flim', 'a': 1., 'b': 1.2}, {'w': 'borp', 'a': 1.207, 'b': 1.4}]
        checks = [{'index': 0, 'end_index': 2, 'start': 1., 'placement_end': 3., 'timing_source': 'pitch_supported'}]
        self.assertEqual(al.flat(sy.realign_sections(seed, checks, ctx))[1]['a'], 1.8)

    def test_text_only_retains_off_voice_and_hole_refusals(self):
        entries = [{'kind': 'inserted'}] * 2
        words = [{'a': 1.}, {'a': 2.}]
        faults, _ = lt.placement_problems(entries, words, self.ctx)
        self.assertTrue(any('off the sung voice' in e for e in faults))
        self.assertFalse(lt.gate_verdict('high', {'uncovered_seconds': 0., 'silent_holes': 0},
                                      {'uncovered_seconds': 0., 'silent_holes': 1})[0])

    def test_energy_window_clipping_cannot_create_a_false_attack(self):
        self.ctx['energy_db'][:700] = -20.
        self.ctx['stem_onsets'] = np.array([])
        _, _, attacks = sy.passage_energy({'a': 5.}, 9., self.ctx)
        self.assertFalse(any(abs(t - 5.) <= sy.START_TOLERANCE for t in attacks))

    def test_fallback_does_not_excuse_a_hole_outside_its_section(self):
        self.ctx['voiced'][1520:1690] = True
        self.ctx['regions'] = al.regions(self.ctx['voiced'])
        self.ctx['phrases'] = self.ctx['regions']
        self.song['lyrics'].append({'words': [{'w': 'old', 'a': 16., 'b': 16.5}]})
        result = self.correct()
        self.assertFalse(result['passed'])
        self.assertIn('silent hole', result['reason'])

    def test_validated_empty_timed_outro_does_not_require_invented_words(self):
        self.ctx['voiced'][1520:1690] = True
        self.ctx['regions'] = al.regions(self.ctx['voiced'])
        self.ctx['phrases'] = self.ctx['regions']
        self.song['lyrics'].append({'words': [{'w': 'old', 'a': 16., 'b': 16.5}]})
        result = self.correct(lrc=LRC + '\n[00:15.00]')
        self.assertTrue(result['passed'], result['reason'])
        self.assertTrue(all(w['a'] < 15 for w in al.flat(result['lines'])))


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pkg = synthetic_package(self.root, bursts=[(t, t + 2) for t in TIMES],
                                     asr_words=['flim', 'wug', 'bim', 'nuv'], duration=17)
        self.ctx, self.words, self.song = fixture()
        target = json.loads((self.pkg / 'target.json').read_text())
        target['lyrics'] = self.song['lyrics']
        (self.pkg / 'target.json').write_text(json.dumps(target))
        (self.pkg / 'lyrics/mix.json').write_text(json.dumps({'lines': self.song['lyrics'], 'source': 'mix'}))
        self.text = self.root / 'verified.txt'
        self.text.write_text(TEXT)
        self.lrc = self.root / 'lines.lrc'
        self.lrc.write_text(LRC)

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self):
        return {str(p.relative_to(self.pkg)): p.read_bytes() for p in self.pkg.rglob('*') if p.is_file()}

    def test_dry_run_is_read_only_and_reports_comparable_metrics(self):
        before = self.snapshot()
        with patch.object(al, 'context', return_value=self.ctx):
            result = lt.process_package(self.pkg, str(self.text), False, synced_file=str(self.lrc))
        self.assertNotIn('skipped', result)
        self.assertEqual(result['synced_clock']['status'], 'clock agrees')
        self.assertIn('sung_coverage_pct', result['after'])
        self.assertEqual(self.snapshot(), before)

    def test_successful_writer_output_replays_through_both_cache_readers(self):
        with patch.object(al, 'context', return_value=self.ctx):
            lt.process_package(self.pkg, str(self.text), True, rebuild=False, synced_file=str(self.lrc))
            target = json.loads((self.pkg / 'target.json').read_text())
            replay = al.corrected_seed(self.pkg, target, self.words, self.ctx)
            report = lt.process_package(self.pkg, None, False)
        self.assertEqual(lt.cached_synced_text(self.pkg), LRC)
        self.assertTrue(replay['passed'], replay['reason'])
        self.assertEqual(replay['lines'], target['lyrics'])
        self.assertNotIn('skipped', report)
        # Manifest changes invalidate words and their timing together.
        (self.pkg / 'manifest.json').write_text('{"title":"changed"}')
        self.assertIsNone(lt.cached_synced_text(self.pkg))

    def test_replacing_text_clears_timing_even_without_manifest_metadata(self):
        (self.pkg / 'manifest.json').unlink()
        with patch.object(al, 'context', return_value=self.ctx):
            lt.process_package(self.pkg, str(self.text), True, rebuild=False, synced_file=str(self.lrc))
            self.assertEqual(lt.cached_synced_text(self.pkg), LRC)
            replacement = TEXT.replace('flim', 'Flim,')
            self.text.write_text(replacement)
            lt.process_package(self.pkg, str(self.text), True, rebuild=False)
        self.assertIsNone(lt.cached_synced_text(self.pkg))
        self.assertEqual(lt.cached_source_text(self.pkg), replacement)


    def test_force_cannot_write_failed_synced_harm_gate(self):
        before = self.snapshot()
        with patch.object(al, 'context', return_value=self.ctx), patch.object(lt, 'gate_verdict', return_value=(False, 'synthetic harm')):
            result = lt.process_package(self.pkg, str(self.text), True, rebuild=False, force=True, synced_file=str(self.lrc))
        self.assertIn('cannot be forced', result['skipped'])
        self.assertEqual(self.snapshot(), before)

    def test_force_cannot_override_invalid_anchor(self):
        before = self.snapshot()
        self.lrc.write_text('[00:00.00] ' + PHRASES[0])
        with patch.object(al, 'context', return_value=self.ctx), self.assertRaises(lt.LyricsSourceError):
            lt.process_package(self.pkg, str(self.text), True, rebuild=False, force=True, synced_file=str(self.lrc))
        self.assertEqual(self.snapshot(), before)

    def test_old_cache_has_no_synced_input(self):
        with patch.object(al, 'context', return_value=self.ctx):
            lt.process_package(self.pkg, str(self.text), True, rebuild=False)
        self.assertIsNone(lt.cached_synced_text(self.pkg))

    def test_real_cli_restart_is_byte_identical_and_read_only(self):
        before = self.snapshot()
        command = [sys.executable, str(ROOT / 'studio/lyrics_text.py'), '--text', str(self.text),
                   '--synced', str(self.lrc), '--dry-run', '--json', str(self.pkg)]
        first = subprocess.run(command, capture_output=True, check=True, timeout=90)
        second = subprocess.run(command, capture_output=True, check=True, timeout=90)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertNotIn('error', result)
        self.assertNotIn('skipped', result)
        self.assertEqual(self.snapshot(), before)

    def test_cli_rejects_one_timeline_for_multiple_packages(self):
        result = subprocess.run([sys.executable, str(ROOT / 'studio/lyrics_text.py'), '--synced',
                                 str(self.lrc), '--dry-run', str(self.pkg), str(self.pkg)],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'--synced applies to a single package', result.stderr)

    def test_quiet_clock_fallback_survives_cli_restart_and_cache_replay(self):
        import soundfile as sf
        y, sr = sf.read(self.pkg / 'vocals_44k.flac')
        y[:int(3 * sr)] = 0
        sf.write(self.pkg / 'vocals_44k.flac', y, sr)
        song = json.loads((self.pkg / 'target.json').read_text())
        for p in song['points'][:150]:
            p[1] = None
        (self.pkg / 'target.json').write_text(json.dumps(song))
        snapshot = self.snapshot()
        command = [sys.executable, str(ROOT / 'studio/lyrics_text.py'), '--text', str(self.text),
                   '--synced', str(self.lrc), '--dry-run', '--json', str(self.pkg)]
        first = subprocess.run(command, capture_output=True, check=True, timeout=90)
        second = subprocess.run(command, capture_output=True, check=True, timeout=90)
        self.assertEqual(first.stdout, second.stdout)
        report = json.loads(first.stdout)
        self.assertNotIn('skipped', report)
        self.assertEqual(report['synced_lines'][0]['timing_source'], 'synced_time_without_voice_support')
        self.assertEqual(report['synced_lines'][0]['start'], 1.)
        self.assertEqual(self.snapshot(), snapshot)
        # Exercise the real cache writer and both replay consumers on this
        # synthetic package. The private-library campaign uses dry-run only.
        lt.process_package(self.pkg, str(self.text), True, rebuild=False, synced_file=str(self.lrc))
        saved = json.loads((self.pkg / 'target.json').read_text())
        words = al.flat(lt.resolve_transcript(self.pkg, saved, 'auto')[0])
        replay = al.corrected_seed(self.pkg, saved, words, al.context(self.pkg, saved))
        self.assertTrue(replay['passed'], replay['reason'])
        self.assertEqual(al.flat(saved['lyrics']), al.flat(replay['lines']))


if __name__ == '__main__':
    unittest.main()
