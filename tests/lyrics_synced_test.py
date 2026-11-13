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


if __name__ == '__main__':
    unittest.main()
