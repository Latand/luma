#!/usr/bin/env python3
"""The lyric text corrector: word matching, repeat restoration, gap/placement, the harm gate, the report, the cache
and the safety guard.

Runs on synthetic audio and invented nonsense words it generates itself. No network call, no Soniox, no song
package from the operator's library.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
import align_lyrics as al
import lyrics_text as lt

SR = 44100
DURATION = 8.0
BURSTS = [(.5, .9), (2.0, 2.4), (3.5, 3.9), (5.0, 5.4), (6.5, 6.9)]   # one nonsense word per burst

# ASR heard: flim, borp, dax, oops, shuzzle. Published lyrics: flim, dax, wug, shuzzle, zant.
#   flim/dax/shuzzle match, borp is an ASR hallucination (dropped), oops->wug is a mishearing (substituted),
#   zant is a syllable ASR never heard at all (inserted, interpolated after the last burst).
ASR_WORDS = ['flim', 'borp', 'dax', 'oops', 'shuzzle']
TRUE_TOKENS = ['flim', 'dax', 'wug', 'shuzzle', 'zant']


def burst_song(pkg: Path, bursts: list[tuple[float, float]], asr_words: list[str], duration: float,
               lyrics_source: str) -> dict:
    t = np.arange(0, duration, 1 / SR); y = np.zeros_like(t)
    for i, (a, b) in enumerate(bursts):
        w = (t >= a) & (t < b)
        env = np.minimum(1, (t[w] - a) * 40)
        y[w] = .3 * env * np.sin(2 * np.pi * (220 + 30 * i) * t[w])
    sf.write(pkg / 'vocals_44k.flac', y.astype(np.float32), SR)
    hop = .02; ts = np.arange(0, duration, hop)
    sung = np.any([(ts >= a) & (ts < b) for a, b in bursts], axis=0)
    points = [[round(float(x), 3), 57.0 if v else None, .9 if v else 0, int(v)] for x, v in zip(ts, sung)]
    notes = [{'id': i, 'a': a, 'b': b, 'm': 57. + i, 'n': 57 + i, 'q': .9, 'ok': True, 'ignored': False} for i, (a, b) in enumerate(bursts)]
    asr = [{'a': round(a + .02, 2), 'b': round(a + .08, 2), 'w': w, 'c': .9} for (a, _), w in zip(bursts, asr_words)]
    return {'schema': 'luma.song.v1', 'title': 'Synthetic Song', 'artist': 'Synthetic Artist', 'duration': duration,
            'hop': hop, 'a4': 440, 'points': points, 'notes': notes, 'phrases': [], 'waveform': [],
            'id': 'synthetic', 'sourceId': 'synthetic', 'lyricsSource': lyrics_source,
            'lyrics': [{'a': asr[0]['a'], 'b': asr[-1]['b'], 'words': asr}]}, asr


def synthetic_package(directory: Path, name: str = 'Synthetic', bursts=BURSTS, asr_words=ASR_WORDS,
                       duration=DURATION, lyrics_source='Soniox stt-async-v5 on the full mix, 2026-09-11, automatic word timings') -> Path:
    pkg = directory / name; pkg.mkdir(parents=True)
    song, asr = burst_song(pkg, bursts, asr_words, duration, lyrics_source)
    (pkg / 'target.json').write_text(json.dumps(song, ensure_ascii=False), encoding='utf-8')
    (pkg / 'lyrics').mkdir()
    (pkg / 'lyrics' / 'mix.json').write_text(json.dumps({'source': 'mix', 'lyricsSource': lyrics_source,
        'lines': song['lyrics']}, ensure_ascii=False), encoding='utf-8')
    (pkg / 'manifest.json').write_text(json.dumps({'title': 'Synthetic Song', 'artist': 'Synthetic Artist'}), encoding='utf-8')
    return pkg


class MatchWordsTests(unittest.TestCase):
    def setUp(self):
        self.asr = [{'a': round(a + .02, 2), 'b': round(a + .08, 2), 'w': w, 'c': .9} for (a, _), w in zip(BURSTS, ASR_WORDS)]

    def test_matched_substituted_dropped_and_inserted_are_classified_correctly(self):
        entries = lt.match_words(self.asr, TRUE_TOKENS)
        kinds = [e['kind'] for e in entries]
        self.assertEqual(kinds, ['matched', 'matched', 'substituted', 'matched', 'inserted'])
        self.assertEqual([e['w'] for e in entries], TRUE_TOKENS)
        self.assertEqual(entries[0]['src'], 0); self.assertEqual(entries[1]['src'], 2)
        self.assertEqual(entries[2]['src'], 3, 'wug takes the timing slot of the misheard oops')
        self.assertEqual(entries[3]['src'], 4); self.assertIsNone(entries[4]['src'])
        self.assertEqual(entries[0]['a'], self.asr[0]['a']); self.assertEqual(entries[2]['a'], self.asr[3]['a'])
        self.assertIsNone(entries[4]['a'], 'the inserted word has no seed time until fill_gaps runs')

    def test_word_order_never_changes_regardless_of_kind(self):
        entries = lt.match_words(self.asr, TRUE_TOKENS)
        self.assertEqual([e['w'] for e in entries], TRUE_TOKENS)

    def test_text_sharing_no_word_with_the_asr_transcript_has_no_matches(self):
        entries = lt.match_words(self.asr, ['zzq', 'vworp'])
        self.assertTrue(all(e['kind'] != 'matched' for e in entries))
        self.assertEqual([e['w'] for e in entries], ['zzq', 'vworp'])

    def test_matching_ignores_case_and_punctuation(self):
        entries = lt.match_words(self.asr, ['Flim,', 'DAX!', "wug?", 'Shuzzle.', 'zant'])
        kinds = [e['kind'] for e in entries]
        self.assertEqual(kinds, ['matched', 'matched', 'substituted', 'matched', 'inserted'],
                          'a case/punctuation difference must not turn a real match into a substitution')

    def test_extra_true_words_in_a_replace_block_are_left_for_fill_gaps_not_interpolated_blindly(self):
        asr = [{'a': 10.0, 'b': 10.3, 'w': 'aa', 'c': .9}, {'a': 15.0, 'b': 15.3, 'w': 'bb', 'c': .9}]
        true = ['xx', 'yy', 'zz', 'ww']
        entries = lt.match_words(asr, true)
        self.assertEqual(entries[0]['a'], 10.0); self.assertEqual(entries[0]['kind'], 'substituted')
        self.assertEqual(entries[1]['a'], 15.0); self.assertEqual(entries[1]['kind'], 'substituted')
        self.assertIsNone(entries[2]['a']); self.assertEqual(entries[2]['kind'], 'inserted')
        self.assertIsNone(entries[3]['a']); self.assertEqual(entries[3]['kind'], 'inserted')

    def test_leftover_heard_words_in_a_replace_block_are_reported_by_find_leftover_runs(self):
        # 5 heard words but only 1 true word there: 4 heard words are leftover, a repeat candidate shape, offered
        # as two mirror candidates (leftover from the tail, inserted at the end; from the head, at the start)
        asr = [{'a': float(i), 'b': i + .3, 'w': f'h{i}', 'c': .9} for i in range(5)]
        runs = lt.find_leftover_runs(asr, ['one'])
        self.assertEqual(runs, [((1, 5, 1), (0, 4, 0))])


class RepeatedSectionTests(unittest.TestCase):
    def test_a_dropped_run_matching_an_earlier_true_span_is_recovered_not_deleted(self):
        words = ['aa', 'bb', 'cc', 'dd']
        asr = [{'a': float(i) * 4, 'b': float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(words)]
        asr += [{'a': 30 + float(i) * 4, 'b': 30 + float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(words)]
        insertions = lt.repeated_insertions(asr, words)
        self.assertTrue(insertions, 'the second, unwritten chorus should be recognised as a repeat')
        pos, tokens = insertions[0]
        self.assertEqual(tokens, words)
        self.assertEqual(lt.apply_repeats(words, insertions), words + words)

    def test_a_short_or_unrelated_dropped_run_is_not_treated_as_a_repeat(self):
        words = ['aa', 'bb', 'cc', 'dd']
        asr = [{'a': float(i) * 4, 'b': float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(words)]
        asr += [{'a': 30 + float(i) * 4, 'b': 30 + float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(['qq', 'zz', 'pp', 'rr'])]
        self.assertFalse(lt.repeated_insertions(asr, words))

    def test_a_replace_shaped_leftover_is_recovered_not_just_a_pure_delete(self):
        # the word at the join was MISHEARD (asr text 'zjoin' vs published 'join'), so difflib cannot match it and
        # reports a real 'replace' (5 heard words for 1 true word) spanning the seam — not a clean 'delete' next to
        # an 'equal' on a shared word, which collapses to two independent opcodes and tests nothing about the
        # replace shape. This is the shape a chorus written out once but sung twice takes when the join word is
        # heard differently from how it is published, and the repeat happens to belong on the tail side.
        words = ['aa', 'bb', 'cc', 'dd']
        asr = [{'a': float(i) * 4, 'b': float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(words)]
        asr += [{'a': 20.0, 'b': 20.3, 'w': 'zjoin', 'c': .9}]   # misheard: the published text says 'join'
        asr += [{'a': 24 + float(i) * 4, 'b': 24 + float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(words)]
        text = words + ['join']
        insertions = lt.repeated_insertions(asr, text)
        self.assertTrue(insertions, 'a replace-shaped leftover run must still be recognised as a repeat')
        pos, tokens = insertions[0]
        self.assertEqual(tokens, words)
        self.assertEqual(lt.apply_repeats(text, insertions), words + ['join'] + words,
                          'the repeat belongs next to its twin, on the tail side of the seam')

    def test_a_replace_shaped_leftover_can_belong_on_the_head_side_of_the_seam(self):
        # mirror of the case above: the chorus is sung TWICE before the misheard word, against a source that writes
        # the chorus once and the word once — the leftover chorus repeat must be spliced in next to its twin
        # (chorus, chorus, word), not stranded on the far side of the word (finding 5: round 2 always took the
        # leftover from the block's tail, which here would produce chorus, word, chorus).
        chorus = ['flim', 'borp', 'vex', 'zant']
        text = chorus + ['glorp']
        asr = [{'a': float(i) * 4, 'b': float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(chorus)]
        asr += [{'a': 20 + float(i) * 4, 'b': 20 + float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(chorus)]
        asr += [{'a': 40.0, 'b': 40.3, 'w': 'gwomp', 'c': .9}]   # misheard: the published text says 'glorp'
        insertions = lt.repeated_insertions(asr, text)
        self.assertTrue(insertions, 'the second chorus must still be recognised as a repeat')
        pos, tokens = insertions[0]
        self.assertEqual(tokens, chorus)
        self.assertEqual(lt.apply_repeats(text, insertions), chorus + chorus + ['glorp'],
                          'the restored chorus must land next to its twin, not on the far side of the misheard word')

    def test_fuzzy_matching_tolerates_one_missing_word_at_the_seam(self):
        words = ['aa', 'bb', 'cc', 'dd', 'ee']
        asr = [{'a': float(i) * 4, 'b': float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(words)]
        repeat = words[1:]   # the second time through, the first word of the phrase is missing/inaudible
        asr += [{'a': 30 + float(i) * 4, 'b': 30 + float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(repeat)]
        insertions = lt.repeated_insertions(asr, words)
        self.assertTrue(insertions, 'a repeat missing one word must still be found')

    def test_multiple_repeats_of_the_same_chorus_are_all_restored(self):
        words = ['aa', 'bb', 'cc', 'dd']
        asr = [{'a': float(i) * 4, 'b': float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(words)]
        for rep in (1, 2):
            base = 30 * rep
            asr += [{'a': base + float(i) * 4, 'b': base + float(i) * 4 + 3.5, 'w': w, 'c': .9} for i, w in enumerate(words)]
        text, entries, restored = lt.restore_repeats(asr, list(words))
        self.assertEqual(restored, 2, 'both repeats of the chorus should be restored, not just the first')
        self.assertEqual(text, words + words + words)


class FillGapsTests(unittest.TestCase):
    def test_an_inserted_run_is_spaced_strictly_increasing_between_its_neighbours(self):
        entries = [{'a': 1.0, 'kind': 'matched'}, {'a': None, 'kind': 'inserted'}, {'a': None, 'kind': 'inserted'}, {'a': 2.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, {'regions': [(0.0, 10.0)], 'duration': 10.0})
        times = [e['a'] for e in out]
        self.assertEqual(times, sorted(times))
        self.assertLess(1.0, times[1]); self.assertLess(times[2], 2.0)

    def test_a_trailing_insert_is_spaced_before_the_song_ends(self):
        entries = [{'a': 7.5, 'kind': 'matched'}, {'a': None, 'kind': 'inserted'}]
        out = lt.fill_gaps(entries, {'regions': [(0.0, 8.0)], 'duration': 8.0})
        self.assertGreater(out[1]['a'], 7.5); self.assertLessEqual(out[1]['a'], 8.0)

    def test_a_leading_insert_is_spaced_from_the_start_of_the_song(self):
        entries = [{'a': None, 'kind': 'inserted'}, {'a': 3.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, {'regions': [(0.0, 8.0)], 'duration': 8.0})
        self.assertGreater(out[0]['a'], 0); self.assertLess(out[0]['a'], 3.0)

    def test_gap_words_are_never_placed_past_the_last_sung_region(self):
        entries = [{'a': 7.5, 'kind': 'matched'}, {'a': None, 'kind': 'inserted'}, {'a': None, 'kind': 'inserted'}]
        out = lt.fill_gaps(entries, {'regions': [(0.0, 7.6)], 'duration': 400.0})
        for e in out[1:]:
            self.assertLessEqual(e['a'], 7.6, 'a trailing insert must stay inside the sung voice, not spread to the end of the track')

    def test_gap_words_prefer_sung_stretches_over_a_wide_silent_gap(self):
        # two matched words 100s apart, with the only singing in a short stretch right after the first one
        entries = [{'a': 10.0, 'kind': 'matched'}, {'a': None, 'kind': 'inserted'}, {'a': 110.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, {'regions': [(10.0, 12.0), (108.0, 110.0)], 'duration': 200.0})
        self.assertLessEqual(out[1]['a'], 12.0, 'the inserted word must land in a real sung stretch, not the middle of a 100s silence')

    def test_extra_true_words_from_a_replace_are_spread_across_the_voiced_region_not_squeezed(self):
        entries = [{'a': 0.0, 'kind': 'matched'}] + [{'a': None, 'kind': 'inserted'} for _ in range(3)] + [{'a': 10.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, {'regions': [(0.0, 10.0)], 'duration': 10.0})
        times = [e['a'] for e in out[1:-1]]
        self.assertEqual(times, sorted(times))
        self.assertGreater(times[-1] - times[0], 3.0, 'they must spread across the voiced span, not squeeze together')

    def test_a_group_with_no_voice_between_its_neighbours_clusters_instead_of_a_straight_line_through_silence(self):
        entries = [{'a': 0.0, 'kind': 'matched'}] + [{'a': None, 'kind': 'inserted'} for _ in range(3)] + [{'a': 10.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, {'regions': [], 'duration': 10.0})
        times = [e['a'] for e in out[1:-1]]
        self.assertLess(times[-1] - times[0], 1.0, 'with no voice at all between the neighbours, cluster tightly rather than spread through silence')

    def test_gap_words_are_never_closer_together_than_the_minimum_spacing_when_the_window_can_fit_it(self):
        # 3 inserted words need at least 3 * MIN_WORD_SPACING_S; the window here (2.0s) has plenty of room
        entries = [{'a': 0.0, 'kind': 'matched'}] + [{'a': None, 'kind': 'inserted'} for _ in range(3)] + [{'a': 2.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, {'regions': [(0.0, 2.0)], 'duration': 2.0})
        times = [e['a'] for e in out]
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(g >= lt.MIN_WORD_SPACING_S - 1e-9 for g in gaps), gaps)

    def test_gap_words_stay_ordered_even_when_the_window_cannot_fit_the_minimum_spacing(self):
        # 6 inserted words in a 1.0s window can't all be MIN_WORD_SPACING_S apart (6 * .18 > 1.0): the minimum
        # spacing is not enforced here (fill_gaps only enforces it when the window can fit it), but order must hold
        entries = [{'a': 0.0, 'kind': 'matched'}] + [{'a': None, 'kind': 'inserted'} for _ in range(6)] + [{'a': 1.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, {'regions': [(0.0, 1.0)], 'duration': 1.0})
        times = [e['a'] for e in out]
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(g >= 0 for g in gaps))


class SilenceMarginTests(unittest.TestCase):
    def _ctx(self, voiced_from: float):
        v = np.zeros(2000, dtype=bool)
        v[int(voiced_from / al.HOP):] = True
        return {'voiced': v}

    def test_a_word_on_an_onset_40ms_before_a_voice_region_does_not_count_as_silence(self):
        ctx = self._ctx(voiced_from=1.0)
        self.assertTrue(lt.in_voice(1.0 - .04, ctx), 'the early-onset margin must cover a word 40ms before the voice starts')

    def test_a_word_60ms_before_a_voice_region_still_counts_as_silence(self):
        ctx = self._ctx(voiced_from=1.0)
        self.assertFalse(lt.in_voice(1.0 - .06, ctx), 'beyond the margin, it really is silence')


class TokenizeTests(unittest.TestCase):
    def test_bracketed_annotation_lines_are_dropped(self):
        text = '[Chorus]\nwug fep\n(Verse 2)\nzorp mun\n'
        self.assertEqual(lt.tokenize(text), ['wug', 'fep', 'zorp', 'mun'])

    def test_punctuation_is_kept_on_the_word(self):
        self.assertEqual(lt.tokenize("wug, fep!\nzorp?"), ['wug,', 'fep!', 'zorp?'])


class GateVerdictTests(unittest.TestCase):
    def _m(self, uncovered, holes):
        return {'uncovered_seconds': uncovered, 'silent_holes': holes}

    def test_low_confidence_always_refuses(self):
        passed, reason = lt.gate_verdict('low', self._m(0, 0), self._m(0, 0))
        self.assertFalse(passed); self.assertIn('confidence', reason)

    def test_nothing_published_yet_always_passes(self):
        passed, reason = lt.gate_verdict('high', None, self._m(999, 99))
        self.assertTrue(passed)

    def test_a_small_growth_in_uncovered_singing_passes(self):
        passed, reason = lt.gate_verdict('high', self._m(10.0, 2), self._m(10.0 + lt.UNCOVERED_TOLERANCE_S - 1, 2))
        self.assertTrue(passed)

    def test_a_large_growth_in_uncovered_singing_refuses(self):
        passed, reason = lt.gate_verdict('high', self._m(10.0, 2), self._m(10.0 + lt.UNCOVERED_TOLERANCE_S + 1, 2))
        self.assertFalse(passed); self.assertIn('uncovered', reason)

    def test_a_new_silent_hole_refuses_even_with_a_small_growth(self):
        passed, reason = lt.gate_verdict('high', self._m(10.0, 2), self._m(10.1, 3))
        self.assertFalse(passed); self.assertIn('hole', reason)


class ProcessPackageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-lyrics-text-')
        self.pkg = synthetic_package(Path(self.directory))
        self.before = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        self.text_file = Path(self.directory) / 'lyrics.txt'
        self.text_file.write_text(' '.join(TRUE_TOKENS), encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_dry_run_writes_nothing(self):
        r = lt.process_package(self.pkg, str(self.text_file), write=False)
        self.assertEqual((self.pkg / 'target.json').read_text(encoding='utf-8'), json.dumps(self.before, ensure_ascii=False))
        self.assertFalse((self.pkg / 'lyrics' / 'source.txt').exists())
        self.assertEqual(r['words_changed'], 1); self.assertEqual(r['words_added'], 1); self.assertEqual(r['words_dropped'], 1)
        self.assertAlmostEqual(r['wer_before'], .6)

    def test_dry_run_still_reports_a_refusal_and_its_reason(self):
        unrelated = Path(self.directory) / 'unrelated.txt'
        unrelated.write_text('qzk vroom nbly wexil ptang jorf mmk zzq vworp klor', encoding='utf-8')
        r = lt.process_package(self.pkg, str(unrelated), write=False)
        self.assertIn('skipped', r, 'a dry run must show that a write would be refused, and why')
        self.assertIn('confidence', r['skipped'])

    def test_writing_replaces_only_lyrics_and_lyrics_source(self):
        r = lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        changed = sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k))
        self.assertEqual(changed, ['lyrics', 'lyricsSource'])
        self.assertEqual([w['w'] for w in al.flat(after['lyrics'])], TRUE_TOKENS)
        self.assertIn('corrected to published lyrics', after['lyricsSource'])
        self.assertIn('mix', after['lyricsSource'], 'the transcript actually used should be named in the note')
        self.assertEqual(r['confidence'], 'medium')
        self.assertNotIn('skipped', r)

    def test_word_order_and_text_are_exactly_the_true_lyrics(self):
        lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        words = al.flat(after['lyrics'])
        self.assertEqual([w['w'] for w in words], TRUE_TOKENS)
        for a, b in zip(words, words[1:]):
            self.assertLess(a['a'], b['a']); self.assertLessEqual(a['b'], b['a'])

    def test_re_running_is_byte_identical(self):
        lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        once = (self.pkg / 'target.json').read_text(encoding='utf-8')
        lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        self.assertEqual(once, (self.pkg / 'target.json').read_text(encoding='utf-8'))

    def test_words_are_snapped_to_a_real_onset_not_left_at_the_raw_asr_seed(self):
        lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        dax = al.flat(after['lyrics'])[1]   # matched, its raw ASR seed is BURSTS[2][0] + .02 exactly
        self.assertEqual(dax['w'], 'dax')
        raw_asr_seed = round(BURSTS[2][0] + .02, 2)
        self.assertNotEqual(dax['a'], raw_asr_seed, 'a real onset detector moves the word off its raw ASR seed')
        self.assertLess(abs(dax['a'] - BURSTS[2][0]), .05, 'and lands close to the actual burst it belongs to')

    def test_the_cache_is_used_on_a_second_run_without_a_network_call(self):
        called = []
        original = lt.fetch_lyrics
        def fake_fetch(title, artist):
            called.append((title, artist)); return ' '.join(TRUE_TOKENS)
        lt.fetch_lyrics = fake_fetch
        try:
            r1 = lt.process_package(self.pkg, None, write=True, rebuild=False)
            self.assertEqual(called, [('Synthetic Song', 'Synthetic Artist')])
            self.assertTrue((self.pkg / 'lyrics' / 'source.txt').exists())
            self.assertTrue((self.pkg / 'lyrics' / 'source.meta.json').exists())
            self.assertEqual((self.pkg / 'lyrics' / 'source.txt').read_text(encoding='utf-8'), ' '.join(TRUE_TOKENS))
            r2 = lt.process_package(self.pkg, None, write=True, rebuild=False)
            self.assertEqual(called, [('Synthetic Song', 'Synthetic Artist')], 'a second run must not touch the network again')
            self.assertEqual(r1['words_true'], r2['words_true'])
        finally:
            lt.fetch_lyrics = original

    def test_a_rejected_fetched_source_is_never_cached(self):
        original = lt.fetch_lyrics
        def fake_fetch(title, artist):
            return 'qzk vroom nbly wexil ptang jorf mmk zzq vworp klor'   # shares nothing with the ASR transcript
        lt.fetch_lyrics = fake_fetch
        try:
            r = lt.process_package(self.pkg, None, write=True, rebuild=False)
            self.assertEqual(r['confidence'], 'low')
            self.assertIn('skipped', r)
            self.assertFalse((self.pkg / 'lyrics' / 'source.txt').exists(), 'a rejected fetched source must not be cached')
            self.assertFalse((self.pkg / 'lyrics' / 'source.meta.json').exists())
        finally:
            lt.fetch_lyrics = original

    def test_a_text_supplied_source_is_cached_once_it_passes_and_writes(self):
        lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        self.assertTrue((self.pkg / 'lyrics' / 'source.txt').exists(), '--text sources must be cached too, once they write')
        self.assertEqual((self.pkg / 'lyrics' / 'source.txt').read_text(encoding='utf-8'), ' '.join(TRUE_TOKENS))

    def test_a_changed_manifest_title_invalidates_the_cache(self):
        original = lt.fetch_lyrics
        calls = []
        def fake_fetch(title, artist):
            calls.append((title, artist)); return ' '.join(TRUE_TOKENS)
        lt.fetch_lyrics = fake_fetch
        try:
            lt.process_package(self.pkg, None, write=True, rebuild=False)
            manifest = json.loads((self.pkg / 'manifest.json').read_text(encoding='utf-8'))
            manifest['title'] = 'A Different Song'
            (self.pkg / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            lt.process_package(self.pkg, None, write=True, rebuild=False)
            self.assertEqual(calls, [('Synthetic Song', 'Synthetic Artist'), ('A Different Song', 'Synthetic Artist')],
                              'a changed manifest title must not be silently served the old cached text')
        finally:
            lt.fetch_lyrics = original

    def test_low_confidence_source_is_left_untouched(self):
        unrelated = Path(self.directory) / 'unrelated.txt'
        unrelated.write_text('qzk vroom nbly wexil ptang jorf mmk zzq vworp klor', encoding='utf-8')
        r = lt.process_package(self.pkg, str(unrelated), write=True, rebuild=False)
        self.assertEqual(r['confidence'], 'low')
        self.assertIn('skipped', r)
        self.assertEqual((self.pkg / 'target.json').read_text(encoding='utf-8'), json.dumps(self.before, ensure_ascii=False))
        self.assertFalse((self.pkg / 'lyrics' / 'source.txt').exists(), 'a rejected source must not be cached')

    def test_a_small_leftover_run_from_a_replace_does_not_trip_the_gate(self):
        # 3 heard words (borp, dax, oops) become 2 published words in one 'replace' opcode (neither shares text with
        # the other, so this is a genuine merge, not two independent single-word deletes around a matching 'dax'):
        # 1 leftover heard word, far below MIN_REPEAT_WORDS and negligible sung time — must not read as a missing
        # section.
        text_file = Path(self.directory) / 'small.txt'
        text_file.write_text('flim newa newb shuzzle', encoding='utf-8')
        r = lt.process_package(self.pkg, str(text_file), write=True, rebuild=False)
        self.assertNotIn('skipped', r)

    def test_the_report_carries_the_metrics_the_operator_needs(self):
        r = lt.process_package(self.pkg, str(self.text_file), write=False)
        for key in ('words_changed', 'words_added', 'words_dropped', 'wer_before', 'median_shift_changed_s',
                    'confidence', 'agreement_pct', 'placement_problems', 'repeated_sections_recovered'):
            self.assertIn(key, r)

    def test_rebuild_writes_the_trainer_html(self):
        for name in ('backing.mp3', 'foreground.mp3', 'backing_80.mp3', 'foreground_80.mp3'):
            (self.pkg / name).write_bytes(b'\xff\xfb\x90\x00' + b'\x00' * 32)   # minimal stub, build_html only base64-embeds it
        r = lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=True)
        self.assertIn('html', r)
        html_path = Path(r['html'])
        self.assertTrue(html_path.exists())
        self.assertGreater(html_path.stat().st_size, 1000)


class ReplaceShapedRepeatIntegrationTests(unittest.TestCase):
    """A chorus written once but sung twice, with the join word MISHEARD (asr text differs from the published word),
    so difflib reports the leftover as a real 'replace' rather than a clean 'delete' next to an 'equal' on a shared
    word — restored end to end through process_package (round 2, finding 1; genuine replace seam, round 3 finding 4)."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-lyrics-repeat-')
        # burst[0..3]: first chorus (flim/dax/wug/zant); burst 4: the seam word, misheard; burst[5..8]: the repeat
        self.repeat_bursts = [(.5, .9), (1.4, 1.8), (2.3, 2.7), (3.2, 3.6), (4.1, 4.5),
                               (5.4, 5.8), (6.3, 6.7), (7.2, 7.6), (8.1, 8.5)]
        heard = ['flim', 'dax', 'wug', 'zant', 'mishear', 'flim', 'dax', 'wug', 'zant']
        self.pkg = synthetic_package(Path(self.directory), name='Repeat', bursts=self.repeat_bursts, asr_words=heard,
                                      duration=9.0)
        self.text_file = Path(self.directory) / 'lyrics.txt'
        self.text_file.write_text('flim dax wug zant join', encoding='utf-8')   # the repeat is only written once

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_the_repeat_is_restored_through_process_package(self):
        r = lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        self.assertGreaterEqual(r['repeated_sections_recovered'], 1)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        words = [w['w'] for w in al.flat(after['lyrics'])]
        self.assertEqual(words, ['flim', 'dax', 'wug', 'zant', 'join', 'flim', 'dax', 'wug', 'zant'])


class SourcePreferenceTests(unittest.TestCase):
    """A song already published from the mix transcript must keep starting from the mix, even when a vocal-stem
    transcript is also cached for it — never silently jump to the other one (finding 1)."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-lyrics-source-')

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _package_with_both_transcripts(self, mix_words, vocal_words, lyrics_source):
        pkg = synthetic_package(Path(self.directory), name='Both', asr_words=mix_words, lyrics_source=lyrics_source)
        vocal_asr = [{'a': round(a + .02, 2), 'b': round(a + .08, 2), 'w': w, 'c': .9} for (a, _), w in zip(BURSTS, vocal_words)]
        (pkg / 'lyrics' / 'vocal.json').write_text(json.dumps({'source': 'vocal', 'lyricsSource': 'vocal note',
            'lines': [{'a': vocal_asr[0]['a'], 'b': vocal_asr[-1]['b'], 'words': vocal_asr}]}, ensure_ascii=False), encoding='utf-8')
        return pkg

    def test_a_mix_published_song_corrects_from_the_mix_transcript_even_when_a_vocal_one_exists(self):
        # the vocal transcript deliberately has a word the mix doesn't, so we can tell which one was used
        pkg = self._package_with_both_transcripts(ASR_WORDS, ['flim', 'zqx', 'dax', 'oops', 'shuzzle'],
                                                    'Soniox stt-async-v5 on the full mix, 2026-09-11, automatic word timings')
        text_file = Path(self.directory) / 'lyrics.txt'; text_file.write_text(' '.join(TRUE_TOKENS), encoding='utf-8')
        r = lt.process_package(pkg, str(text_file), write=True, rebuild=False)
        self.assertEqual(r['asr_source'], 'mix')
        after = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
        self.assertIn('from the mix transcript', after['lyricsSource'])

    def test_a_vocal_published_song_corrects_from_the_vocal_transcript(self):
        pkg = self._package_with_both_transcripts(['flim', 'zqx', 'dax', 'oops', 'shuzzle'], ASR_WORDS,
                                                    'Soniox stt-async-v5 on the Demucs vocal stem, 2026-09-14, automatic word timings')
        text_file = Path(self.directory) / 'lyrics.txt'; text_file.write_text(' '.join(TRUE_TOKENS), encoding='utf-8')
        r = lt.process_package(pkg, str(text_file), write=True, rebuild=False)
        self.assertEqual(r['asr_source'], 'vocal')

    def test_from_flag_overrides_the_published_source(self):
        pkg = self._package_with_both_transcripts(ASR_WORDS, ['flim', 'zqx', 'dax', 'oops', 'shuzzle'],
                                                    'Soniox stt-async-v5 on the full mix, 2026-09-11, automatic word timings')
        text_file = Path(self.directory) / 'lyrics.txt'; text_file.write_text(' '.join(TRUE_TOKENS), encoding='utf-8')
        r = lt.process_package(pkg, str(text_file), write=True, rebuild=False, prefer='vocal')
        self.assertEqual(r['asr_source'], 'vocal')


class PlacementGateTests(unittest.TestCase):
    def test_an_off_voice_inserted_word_blocks(self):
        v = np.zeros(1000, dtype=bool)   # nothing is voiced anywhere: any inserted word lands off the voice
        blocking, info = lt.placement_problems([{'kind': 'inserted', 'src': None}], [{'a': 5.0}], {'voiced': v})
        self.assertTrue(blocking)
        blocking, info = lt.placement_problems([{'kind': 'matched', 'src': 0}], [{'a': 5.0}], {'voiced': v})
        self.assertFalse(blocking, 'a matched word, anchored to a real ASR time, is never judged by the voice check')

    def test_tight_spacing_alone_is_informational_not_blocking(self):
        v = np.ones(1000, dtype=bool)
        entries = [{'kind': 'inserted', 'src': None}, {'kind': 'inserted', 'src': None}]
        words = [{'a': 5.0}, {'a': 5.1}]   # well inside the voice, closer than MIN_WORD_SPACING_S but past the 50ms line
        blocking, info = lt.placement_problems(entries, words, {'voiced': v})
        self.assertFalse(blocking, 'tight spacing forced by a crowded sung stretch must not refuse a correction that is otherwise safe')
        self.assertTrue(info)

    def test_crowding_under_the_onset_dedup_window_blocks(self):
        v = np.ones(1000, dtype=bool)
        entries = [{'kind': 'inserted', 'src': None}, {'kind': 'inserted', 'src': None}]
        words = [{'a': 5.0}, {'a': 5.02}]   # closer than MIN_INSERTED_SPACING_S: not a real, distinguishable placement
        blocking, info = lt.placement_problems(entries, words, {'voiced': v})
        self.assertTrue(blocking, 'crowding this tight must refuse, the same squeeze that shrinks uncovered_seconds')

    def test_a_neighbour_of_any_kind_counts_for_the_dedup_window_check(self):
        v = np.ones(1000, dtype=bool)
        # the inserted word is crowded against a MATCHED neighbour, not another inserted word
        entries = [{'kind': 'matched', 'src': 0}, {'kind': 'inserted', 'src': None}]
        words = [{'a': 5.0}, {'a': 5.02}]
        blocking, info = lt.placement_problems(entries, words, {'voiced': v})
        self.assertTrue(blocking, 'the 50ms check looks at any neighbour, not only another inserted word')

    def test_flashing_word_growth_past_the_tolerance_blocks(self):
        before = {'flashing_words': 10}
        after = {'flashing_words': 10 + lt.FLASHING_WORDS_TOLERANCE + 1}
        blocking, info = lt.placement_problems([], [], {'voiced': np.ones(10, dtype=bool)}, before, after)
        self.assertTrue(blocking)
        self.assertIn('flashing', blocking[0])

    def test_flashing_word_growth_within_the_tolerance_does_not_block(self):
        before = {'flashing_words': 10}
        after = {'flashing_words': 10 + lt.FLASHING_WORDS_TOLERANCE}
        blocking, info = lt.placement_problems([], [], {'voiced': np.ones(10, dtype=bool)}, before, after)
        self.assertFalse(blocking)


class HarmGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-lyrics-harm-')
        self.pkg = synthetic_package(Path(self.directory))
        self.before = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_force_writes_through_a_refusal(self):
        unrelated = Path(self.directory) / 'unrelated.txt'
        unrelated.write_text('qzk vroom nbly wexil ptang jorf mmk zzq vworp klor', encoding='utf-8')
        r = lt.process_package(self.pkg, str(unrelated), write=True, rebuild=False, force=True)
        self.assertNotIn('skipped', r)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        self.assertNotEqual(after['lyrics'], self.before['lyrics'])

    def test_process_package_refuses_on_real_harm(self):
        # 'before' is a synthetic wide-span word covering a long burst end to end — decoupled from the raw ASR
        # transcript used for matching, so this measures the harm gate on its own, not confidence or placement.
        # The correction drops that burst's word entirely, leaving far more of it uncovered than before.
        directory = Path(tempfile.mkdtemp(prefix='luma-lyrics-harm2-'))
        bursts = BURSTS + [(9.0, 17.0)]
        asr_words = ASR_WORDS + ['holdnote']
        pkg = synthetic_package(directory, bursts=bursts, asr_words=asr_words, duration=18.0)
        song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
        song['lyrics'][0]['words'][-1]['b'] = 17.0; song['lyrics'][0]['b'] = 17.0
        (pkg / 'target.json').write_text(json.dumps(song, ensure_ascii=False), encoding='utf-8')
        text_file = directory / 'harm.txt'; text_file.write_text(' '.join(TRUE_TOKENS), encoding='utf-8')
        try:
            r = lt.process_package(pkg, str(text_file), write=True, rebuild=False)
            self.assertIn('skipped', r)
            self.assertIn('uncovered', r['skipped'])
            self.assertNotIn('placement', r['skipped'], 'this refusal must be about harm, not a placement fault')
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_process_package_refuses_on_placement_alone(self):
        # a crowd of published words with no ASR counterpart nearby all have to squeeze into one short sung pocket;
        # enough real matched words surround them to keep confidence at 'medium' and coverage never gets worse, so
        # this measures the placement gate on its own.
        directory = Path(tempfile.mkdtemp(prefix='luma-lyrics-placement2-'))
        bursts = [(.5, .9), (2.0, 2.4), (3.5, 3.54), (4.5, 4.65), (5.0, 5.4), (6.5, 6.9),
                  (8.0, 8.4), (9.0, 9.4), (10.0, 10.4), (11.0, 11.4)]
        asr_words = ['flim', 'borp', 'dax', 'junkblip', 'oops', 'shuzzle', 'quor', 'lomp', 'fenn', 'trask']
        pkg = synthetic_package(directory, bursts=bursts, asr_words=asr_words, duration=12.0)
        text_file = directory / 'crowd.txt'
        text_file.write_text('flim dax zog vlim quip jarn ozzo plix trin bozz fexx wug shuzzle zant quor lomp fenn trask',
                              encoding='utf-8')
        try:
            r = lt.process_package(pkg, str(text_file), write=True, rebuild=False)
            self.assertIn('skipped', r)
            self.assertIn('placement', r['skipped'])
            self.assertNotIn('uncovered', r['skipped'], 'this refusal must be about placement, not harm')
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-lyrics-guard-')
        self.pkg = synthetic_package(Path(self.directory))

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_a_change_outside_lyrics_trips_the_guard(self):
        before = {'a': 1, 'notes': [1, 2]}; after = {'a': 2, 'notes': [1, 2]}
        with self.assertRaises(SystemExit):
            lt.verify_guard(self.pkg, before, after, {}, {})

    def test_a_changed_audio_file_trips_the_guard(self):
        before = {'a': 1}; after = {'a': 1}
        with self.assertRaises(SystemExit):
            lt.verify_guard(self.pkg, before, after, {'vocals_44k.flac': 'x'}, {'vocals_44k.flac': 'y'})

    def test_non_lyrics_fields_matching_pass(self):
        lt.verify_guard(self.pkg, {'a': 1}, {'a': 1}, {'v': 'x'}, {'v': 'x'})   # must not raise

    def test_a_mutation_between_load_and_write_still_trips_the_guard(self):
        """A shallow 'before' snapshot captured at load time (dict(song)) would share nested objects with an
        in-place mutation applied anywhere before the write. process_package instead re-reads 'before' fresh from
        disk right before writing, so it can't be fooled that way — even a mutation to the very `song` object it is
        about to write from is caught."""
        pkg = synthetic_package(Path(tempfile.mkdtemp(prefix='luma-lyrics-guard2-')))
        text_file = pkg.parent / 'lyrics.txt'; text_file.write_text(' '.join(TRUE_TOKENS), encoding='utf-8')
        original_context = al.context
        def mutating_context(p, song):
            song['notes'][0]['a'] = 999.0   # an in-place mutation to the loaded object, from anywhere in the pipeline
            return original_context(p, song)
        al.context = mutating_context
        try:
            with self.assertRaises(SystemExit):
                lt.process_package(pkg, str(text_file), write=True, rebuild=False)
        finally:
            al.context = original_context
            shutil.rmtree(pkg.parent, ignore_errors=True)

    def test_a_nested_field_mutated_in_place_still_trips_the_guard(self):
        """The old shallow-copy 'before' snapshot shared nested objects with 'after', so an in-place mutation to a
        nested field was invisible to the comparison. Two independent JSON reads (what process_package now takes)
        never share references, so the same mutation must still be caught."""
        shared = {'notes': [{'a': 1.0}]}
        before = json.loads(json.dumps(shared))
        shared['notes'][0]['a'] = 123.0   # mutated in place, simulating a bug elsewhere touching the loaded object
        after = json.loads(json.dumps(shared))
        with self.assertRaises(SystemExit):
            lt.verify_guard(self.pkg, before, after, {}, {})

    def test_the_tmp_file_is_removed_when_the_guard_trips(self):
        pkg = synthetic_package(Path(tempfile.mkdtemp(prefix='luma-lyrics-guard3-')))
        text_file = pkg.parent / 'lyrics.txt'; text_file.write_text(' '.join(TRUE_TOKENS), encoding='utf-8')
        original_context = al.context
        def mutating_context(p, song):
            song['notes'][0]['a'] = 999.0
            return original_context(p, song)
        al.context = mutating_context
        try:
            with self.assertRaises(SystemExit):
                lt.process_package(pkg, str(text_file), write=True, rebuild=False)
            self.assertFalse((pkg / 'target.json.tmp').exists(), 'a tripped guard must not leave target.json.tmp behind')
        finally:
            al.context = original_context
            shutil.rmtree(pkg.parent, ignore_errors=True)

    def test_target_json_is_unchanged_when_the_guard_trips(self):
        """The write goes to a temp file and is only compared and renamed after — never written in place and
        compared afterwards, which could leave a half-applied target.json behind a trip."""
        pkg = synthetic_package(Path(tempfile.mkdtemp(prefix='luma-lyrics-guard4-')))
        before = (pkg / 'target.json').read_text(encoding='utf-8')
        text_file = pkg.parent / 'lyrics.txt'; text_file.write_text(' '.join(TRUE_TOKENS), encoding='utf-8')
        original_context = al.context
        def mutating_context(p, song):
            song['notes'][0]['a'] = 999.0
            return original_context(p, song)
        al.context = mutating_context
        try:
            with self.assertRaises(SystemExit):
                lt.process_package(pkg, str(text_file), write=True, rebuild=False)
            self.assertEqual((pkg / 'target.json').read_text(encoding='utf-8'), before)
        finally:
            al.context = original_context
            shutil.rmtree(pkg.parent, ignore_errors=True)

    def test_the_audio_fingerprint_covers_the_files_present(self):
        fp = lt.audio_fingerprint(self.pkg)
        self.assertEqual(set(fp), {'vocals_44k.flac'})

    def test_the_audio_fingerprint_covers_original_m4a(self):
        (self.pkg / 'original.m4a').write_bytes(b'not real audio, just a fingerprint target')
        fp = lt.audio_fingerprint(self.pkg)
        self.assertIn('original.m4a', fp)

    def test_strip_lyrics_removes_only_the_lyrics_fields(self):
        song = {'a': 1, 'lyrics': [1], 'lyricsSource': 'x'}
        self.assertEqual(lt.strip_lyrics(song), {'a': 1})


if __name__ == '__main__':
    unittest.main(verbosity=2)
