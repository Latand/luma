#!/usr/bin/env python3
"""The lyric text corrector: word matching, repeat restoration, gap/placement, the harm gate, the report, the cache
and the safety guard.

Runs on synthetic audio and invented nonsense words it generates itself. No network call, no Soniox, no song
package from the operator's library.
"""
import json
import re
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


def _flashing_growth(report: dict) -> int:
    """The song-wide flashing_words growth reported in a process_package() report's placement_problems, or 0 if
    none is listed (growth of 0 is never listed, see placement_problems)."""
    for line in report.get('placement_problems', []):
        m = re.match(r'flashing words grew by (\d+)', line)
        if m: return int(m.group(1))
    return 0


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

    def test_a_leftover_shorter_than_the_minimum_is_not_restored_even_if_a_short_prefix_of_it_would_match(self):
        # the leftover run is exactly MIN_REPEAT_WORDS long, and its first 2 words happen to exactly repeat the
        # start of the true text, but the other 2 are unrelated garbage, so the whole run's agreement with any
        # true-text window falls well short of REPEAT_MATCH_RATIO: find_repeated_span must never fall back to
        # trying a shorter, 2-word-only prefix just because that alone would match well.
        words = ['aa', 'bb', 'cc', 'dd', 'ee']
        t_norm = [al.norm(w) for w in words]
        leftover = ['aa', 'bb', 'xx', 'yy']
        self.assertIsNone(lt.find_repeated_span(leftover, t_norm), 'a leftover this short, with this little real agreement, must not be restored')
        leftover_full = ['aa', 'bb', 'cc', 'dd']
        self.assertIsNotNone(lt.find_repeated_span(leftover_full, t_norm), 'a full MIN_REPEAT_WORDS-long, well-matching prefix must still be found')

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

    def test_widening_keeps_substituted_words_anchored_near_their_heard_time_not_respread_from_scratch(self):
        # the reviewer's round-4-followup failure case (finding 1): continuous voice 0.5-31s; 3 substituted words
        # heard close together at 1.0/1.5/2.0s, 3 inserted words with no heard time at all, a 4th substituted word
        # heard at 2.1s, and the first matched word all the way out at 30s. The old, purely-proportional widened
        # respread scattered the heard words across the full 30s window (up to ~24s from where they were heard);
        # anchored spread must leave the close-together ones alone and move the crowd-adjacent one only a little.
        entries = [
            {'a': 1.0, 'kind': 'substituted', 'w': 'sub1'}, {'a': 1.5, 'kind': 'substituted', 'w': 'sub2'},
            {'a': 2.0, 'kind': 'substituted', 'w': 'sub3'}, {'a': None, 'kind': 'inserted', 'w': 'i1'},
            {'a': None, 'kind': 'inserted', 'w': 'i2'}, {'a': None, 'kind': 'inserted', 'w': 'i3'},
            {'a': 2.1, 'kind': 'substituted', 'w': 'sub4'}, {'a': 30.0, 'kind': 'matched', 'w': 'm1'},
        ]
        heard = {e['w']: e['a'] for e in entries if e['kind'] == 'substituted'}
        out = lt.fill_gaps([dict(e) for e in entries], {'regions': [(0.5, 31.0)], 'duration': 32.0})
        shifts = {e['w']: abs(e['a'] - heard[e['w']]) for e in out if e['kind'] == 'substituted'}
        self.assertTrue(all(s <= lt.MAX_SUBSTITUTED_SHIFT_S for s in shifts.values()), shifts)
        times = [e['a'] for e in out]
        self.assertEqual(times, sorted(times), 'word order must survive the widened spread')
        self.assertEqual(out[-1]['a'], 30.0, "widening must never move the matched word it widened up to")

    def test_a_near_matched_word_with_room_below_it_is_never_absorbed_into_widening(self):
        # the near matched word here sits at 5.0, away from the window's own start (unlike a neighbour pinned at
        # t=0, which has no room to move and so can't tell absorption apart from correct behaviour): if widening's
        # boundary search ever included it in the movable span by one entry too many, the forward-spacing cascade
        # that legitimately nudges 'sub' would visibly carry 'near' away from 5.0 too.
        entries = ([{'a': 5.0, 'kind': 'matched', 'w': 'near'}] +
                   [{'a': None, 'kind': 'inserted', 'w': f'i{k}'} for k in range(3)] +
                   [{'a': 5.05, 'kind': 'substituted', 'w': 'sub'}, {'a': 5.5, 'kind': 'matched', 'w': 'far'}])
        out = lt.fill_gaps([dict(e) for e in entries], {'regions': [(0.0, 100.0)], 'duration': 101.0})
        self.assertEqual(out[0]['a'], 5.0, "widening must never move the matched word on the near side")
        self.assertEqual(out[-1]['a'], 5.5, "widening must never move the matched word on the far side")
        self.assertEqual([e['w'] for e in out], [e['w'] for e in entries], 'word order must survive widening')

    def test_widening_never_moves_a_matched_word_even_under_crowding_pressure(self):
        # the immediate window ('sub' to 'far') can't fit 3 inserted words, so fill_gaps widens on the right past
        # 'sub' (substituted) — but must stop there. A boundary bug that widens one entry too far, absorbing
        # 'far' (matched) into the movable span too, lets the forward spacing cascade push it off its heard time,
        # the way it pushes 'sub'.
        entries = ([{'a': 0.0, 'kind': 'matched', 'w': 'dax'}] +
                   [{'a': None, 'kind': 'inserted', 'w': f'i{k}'} for k in range(3)] +
                   [{'a': 0.05, 'kind': 'substituted', 'w': 'sub'}, {'a': 0.5, 'kind': 'matched', 'w': 'far'}])
        out = lt.fill_gaps([dict(e) for e in entries], {'regions': [(0.0, 100.0)], 'duration': 101.0})
        self.assertEqual(out[0]['a'], 0.0, "widening must never move the matched word on the near side")
        self.assertEqual(out[-1]['a'], 0.5, "widening must never move the matched word on the far side")
        self.assertEqual([e['w'] for e in out], [e['w'] for e in entries], 'word order must survive widening')


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

    def test_flashing_word_growth_never_blocks_on_its_own(self):
        # a large, song-wide growth in flashing_words alone must never refuse: it refuses an ordinarily dense song
        # on its everyday density (see new_crowd_runs, which catches the real, local crowd instead)
        before = {'flashing_words': 10}
        after = {'flashing_words': 10 + 1000}
        blocking, info = lt.placement_problems([], [], {'voiced': np.ones(10, dtype=bool)},
                                                before_metrics=before, after_metrics=after)
        self.assertFalse(blocking)
        self.assertIn('flashing', info[0])

    def test_flashing_word_growth_is_omitted_when_there_is_none(self):
        before = {'flashing_words': 10}
        after = {'flashing_words': 10}
        blocking, info = lt.placement_problems([], [], {'voiced': np.ones(10, dtype=bool)},
                                                before_metrics=before, after_metrics=after)
        self.assertFalse(blocking); self.assertFalse(info)

    def test_a_new_crowd_run_containing_an_inserted_word_blocks(self):
        v = np.ones(1000, dtype=bool)
        entries = [{'kind': 'matched', 'src': 0}] + [{'kind': 'inserted', 'src': None} for _ in range(3)]
        words = [{'a': 5.00}, {'a': 5.06}, {'a': 5.12}, {'a': 5.18}]   # 4 starts, each < CROWD_RUN_GAP_S apart
        blocking, info = lt.placement_problems(entries, words, {'voiced': v})
        self.assertTrue(blocking)
        self.assertIn('4 words', blocking[-1]); self.assertIn('5.0s', blocking[-1])

    def test_a_crowd_run_already_in_the_published_lyrics_does_not_block(self):
        v = np.ones(1000, dtype=bool)
        entries = [{'kind': 'matched', 'src': 0}] + [{'kind': 'inserted', 'src': None} for _ in range(3)]
        words = [{'a': 5.00}, {'a': 5.06}, {'a': 5.12}, {'a': 5.18}]
        before_lines = [{'words': [{'w': f'x{i}', 'a': w['a'], 'b': w['a'] + .05} for i, w in enumerate(words)]}]
        blocking, info = lt.placement_problems(entries, words, {'voiced': v}, before_lines=before_lines)
        self.assertFalse(blocking, 'a crowd already in the lyrics published now is not one this correction introduced')

    def test_a_crowd_run_of_only_matched_or_substituted_words_does_not_block(self):
        v = np.ones(1000, dtype=bool)
        entries = [{'kind': 'matched', 'src': i} for i in range(4)]   # real fast singing, nothing inserted
        words = [{'a': 5.00}, {'a': 5.06}, {'a': 5.12}, {'a': 5.18}]
        blocking, info = lt.placement_problems(entries, words, {'voiced': v})
        self.assertFalse(blocking, 'a tight run with no inserted word in it is real fast singing, not a placement fault')

    def test_starts_exactly_crowd_run_gap_apart_are_not_a_crowd_run(self):
        # each successive pair here is exactly CROWD_RUN_GAP_S apart, but repeatedly adding 0.1 in raw binary
        # float lands each step a hair under it (0.09999999999999998, not 0.1) — crowd_runs must round to the
        # same 3 decimals every 'a' is stored at before comparing, or this reads as one long crowd run purely from
        # float noise, never from an actual gap tighter than the gate's own floor.
        starts = [0.24]
        for _ in range(5): starts.append(starts[-1] + 0.1)
        self.assertTrue(all(0 < (b - a) < lt.CROWD_RUN_GAP_S for a, b in zip(starts, starts[1:])),
                         'this fixture must reproduce the float artifact, or it is not testing the rounding at all')
        entries = [{'kind': 'matched', 'src': 0}] + [{'kind': 'inserted', 'src': None} for _ in range(len(starts) - 1)]
        words = [{'a': s} for s in starts]
        blocking, info = lt.placement_problems(entries, words, {'voiced': np.ones(1000, dtype=bool)})
        self.assertFalse(blocking, 'starts exactly CROWD_RUN_GAP_S apart must never register as a crowd run')


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
            self.assertNotIn('uncovered', r['skipped'], 'this refusal must be about harm, not placement')
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_five_inserted_words_close_together_are_gated_locally_not_by_song_wide_flashing_growth(self):
        # 5 words with no ASR counterpart squeeze into one continuously sung pocket between two real ASR words —
        # each lands roughly 90ms after the previous, well past the 50ms dedup window and (flashing growth of 1)
        # within the old, now-removed FLASHING_WORDS_TOLERANCE (5), so nothing about this shape ever tripped the
        # old gate; only the local crowd-run check (new in this round) catches it.
        directory = Path(tempfile.mkdtemp(prefix='luma-lyrics-crowd85-'))
        bursts = [(.5, .9), (2.0, 2.4), (3.50, 4.01), (6.01, 6.41)]
        asr_words = ['flim', 'borp', 'dax', 'shuzzle']
        pkg = synthetic_package(directory, bursts=bursts, asr_words=asr_words, duration=8.0)
        text_file = directory / 'crowd85.txt'
        text_file.write_text('flim dax nix vop tez rull sump shuzzle', encoding='utf-8')
        try:
            r = lt.process_package(pkg, str(text_file), write=True, rebuild=False)
            self.assertLessEqual(_flashing_growth(r), 5, 'this case must stay within the old, now-removed song-wide tolerance')
            if 'skipped' in r:
                self.assertIn('a run of', r['skipped'], 'this must be the new local crowd-run check, not any older reason')
            else:
                after_words = al.flat(json.loads((pkg / 'target.json').read_text(encoding='utf-8'))['lyrics'])
                self.assertFalse(lt.crowd_runs(after_words), 'if written, the crowd must have been genuinely spread out')
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_widening_reaches_a_far_matched_word_and_writes_every_word_spaced_on_the_voice(self):
        # 4 inserted words plus one substituted word ('subw', misheard as 'heardS') have almost no sung time in
        # their immediate window (between the substituted word and the next matched word, 'trask') — that alone
        # cannot fit even CROWD_RUN_GAP_S, so fill_gaps widens all the way back to 'dax'. The wider span holds
        # 1.22s of continuous voice (the two bursts merge into one detected region), enough to legalize all 5
        # moved entries at MIN_WORD_SPACING_S with both matched neighbours — 'dax' and 'trask', which the widening
        # must never move — held as occupied bounds too (finding 1): this must write, not refuse on an artifact of
        # a seed landing exactly on a neighbour's time.
        directory = Path(tempfile.mkdtemp(prefix='luma-lyrics-widen-'))
        bursts = [(.5, .9), (2.0, 2.4), (3.50, 4.50), (4.6, 4.7), (6.0, 6.4)]
        asr_words = ['flim', 'borp', 'dax', 'heardS', 'trask']
        pkg = synthetic_package(directory, bursts=bursts, asr_words=asr_words, duration=8.0)
        text_file = directory / 'widen.txt'
        text_file.write_text('flim dax subw nix vop tez rull trask', encoding='utf-8')
        try:
            song = json.loads((pkg / 'target.json').read_text(encoding='utf-8'))
            ctx = al.context(pkg, song)
            asr_lines, asr_src = lt.resolve_transcript(pkg, song, 'auto')
            asr_words_flat = al.flat(asr_lines)
            raw_text = text_file.read_text(encoding='utf-8')
            c = lt.build_correction(pkg, song, asr_words_flat, ctx, raw_text, asr_src)
            for e in c['entries']:
                if e['kind'] == 'matched':
                    self.assertEqual(e['a'], asr_words_flat[e['src']]['a'],
                                      "widening must never move a matched entry's seed off its heard start")
            self.assertEqual([e['w'] for e in c['entries']], lt.tokenize(raw_text), 'word order must survive widening')
            self.assertIsNone(c['reason'], 'a widened window with enough voice for every moved word must write')
            seeds = [e['a'] for e in c['entries']]
            gaps = [round(b - a, 3) for a, b in zip(seeds, seeds[1:])]
            self.assertTrue(all(g >= lt.MIN_INSERTED_SPACING_S for g in gaps),
                             'no seed may land within MIN_INSERTED_SPACING_S of its neighbour, including dax and trask')
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_widening_that_would_move_a_substituted_word_past_the_bound_refuses_naming_it(self):
        # 8 substituted words ('s0'..'s7') are all heard bunched within ~0.45s right after 'dax', followed by 2
        # inserted words with no ASR counterpart and almost no sung time before the far matched word 'trask' — so
        # fill_gaps widens all the way back to 'dax' and has to spread all 10 moved entries at MIN_WORD_SPACING_S
        # across a window whose voice is concentrated at the far end. The forward/backward legalizing pass this
        # requires carries the earliest substituted word ('s0') well past MAX_SUBSTITUTED_SHIFT_S from where it was
        # actually heard: this must refuse, and the refusal must name the bound, not a placement collision.
        directory = Path(tempfile.mkdtemp(prefix='luma-lyrics-boundshift-'))
        pad_bursts = [(0.5 + 0.3 * i, 0.5 + 0.3 * i + 0.1) for i in range(8)]
        pad_words = [f'p{i}' for i in range(8)]
        t0 = 0.5 + 0.3 * 8 + 1.0
        bursts = (pad_bursts + [(t0, t0 + 0.04), (t0 + 0.1, t0 + 3.1)]
                  + [(t0 + 3.2 + 0.05 * i, t0 + 3.2 + 0.05 * i + 0.025) for i in range(8)]
                  + [(t0 + 4.5, t0 + 4.9)])
        asr_words = pad_words + ['dax', 'bigp'] + [f'h{i}' for i in range(8)] + ['trask']
        duration = t0 + 6.0
        pkg = synthetic_package(directory, bursts=bursts, asr_words=asr_words, duration=duration)
        for path, key in ((pkg / 'target.json', 'lyrics'), (pkg / 'lyrics' / 'mix.json', 'lines')):
            data = json.loads(path.read_text(encoding='utf-8'))
            for line in data[key]: line['words'] = [w for w in line['words'] if w['w'] != 'bigp']
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        text_file = directory / 'boundshift.txt'
        words = pad_words + ['dax'] + [f's{i}' for i in range(8)] + ['i0', 'i1', 'trask']
        text_file.write_text(' '.join(words), encoding='utf-8')
        try:
            r = lt.process_package(pkg, str(text_file), write=False, rebuild=False)
            self.assertIn('skipped', r)
            self.assertIn('placement', r['skipped'])
            self.assertIn(f'more than {lt.MAX_SUBSTITUTED_SHIFT_S}s', r['skipped'],
                           'the refusal must name the bound, not an unrelated placement fault')
            self.assertGreater(r['max_shift_changed_s'], lt.MAX_SUBSTITUTED_SHIFT_S)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_a_substituted_word_well_away_from_the_crowd_keeps_its_heard_seed_through_process_package(self):
        # 'sfar', 'sfiller' and 'snear' are heard close together right after 'dax'; between 'snear' and the far
        # matched word 'trask' there is too little sung time for even CROWD_RUN_GAP_S to fit the 2 inserted words
        # that follow, so fill_gaps genuinely widens all the way back past all three substituted words to 'dax'
        # (unlike an earlier version of this scenario, whose immediate window already had enough voice on its own
        # and so never actually exercised widening at all). 'sfar' sits 3 words from the crowd (sfiller, snear,
        # then the 2 inserted words) — a purely proportional respread over the whole widened window (round 4's
        # bug) would have carried it seconds from where it was actually heard, since most of that window's sung
        # time is one long early stretch, not where 'sfar' actually sits.
        directory = Path(tempfile.mkdtemp(prefix='luma-lyrics-farsub-'))
        bursts = [(.5, .9), (2.0, 2.4), (3.50, 3.54), (3.60, 6.60), (6.70, 6.75), (6.85, 6.90), (7.00, 7.06),
                  (7.90, 8.30)]
        asr_words = ['flim', 'borp', 'dax', 'bigp', 'h1', 'h2', 'h3', 'trask']
        pkg = synthetic_package(directory, bursts=bursts, asr_words=asr_words, duration=10.0)
        for path, key in ((pkg / 'target.json', 'lyrics'), (pkg / 'lyrics' / 'mix.json', 'lines')):
            data = json.loads(path.read_text(encoding='utf-8'))
            for line in data[key]: line['words'] = [w for w in line['words'] if w['w'] != 'bigp']
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        text_file = directory / 'farsub.txt'
        text_file.write_text('flim dax sfar sfiller snear i1 i2 trask', encoding='utf-8')
        try:
            r = lt.process_package(pkg, str(text_file), write=False, rebuild=False)
            self.assertLessEqual(r['max_shift_changed_s'], lt.MAX_SUBSTITUTED_SHIFT_S,
                                  "'sfar' must keep close to its heard time, not be carried off by the crowd's squeeze")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_a_run_that_fits_100ms_spacing_but_not_180ms_is_written_with_no_crowd_run(self):
        # 6 words with no ASR counterpart share one continuous ~0.73s sung stretch between two matched words —
        # too little for MIN_WORD_SPACING_S (0.18s: 6 * .18 == 1.08s) or even a bare proportional spread (0.73 / 7
        # ~= 0.104s, under MIN_WORD_SPACING_S), but CROWD_RUN_GAP_S (0.1s), held against both matched neighbours
        # too (7 gaps of 0.1s == 0.7s, just inside the window), fits, with nothing to widen into (both neighbours
        # are already matched). Finding 2: this is the one thing that flipped one library song from refused into
        # written, and nothing guarded it.
        directory = Path(tempfile.mkdtemp(prefix='luma-lyrics-tier01-'))
        bursts = [(.5, .9), (2.0, 2.4), (3.50, 3.54), (3.85, 4.55), (4.75, 5.15)]
        asr_words = ['flim', 'borp', 'dax', 'filler', 'trask']
        pkg = synthetic_package(directory, bursts=bursts, asr_words=asr_words, duration=6.0)
        for path, key in ((pkg / 'target.json', 'lyrics'), (pkg / 'lyrics' / 'mix.json', 'lines')):
            data = json.loads(path.read_text(encoding='utf-8'))
            for line in data[key]: line['words'] = [w for w in line['words'] if w['w'] != 'filler']
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        text_file = directory / 'tier01.txt'
        text_file.write_text('flim dax i0 i1 i2 i3 i4 i5 trask', encoding='utf-8')
        try:
            r = lt.process_package(pkg, str(text_file), write=True, rebuild=False)
            self.assertNotIn('skipped', r, 'a run that fits the 100ms tier must be written, not refused')
            after_words = al.flat(json.loads((pkg / 'target.json').read_text(encoding='utf-8'))['lyrics'])
            self.assertFalse(lt.crowd_runs(after_words), 'a run the 100ms tier legalized must not still show up as a crowd')
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_scattered_inserted_words_that_grow_flashing_past_the_old_tolerance_are_written(self):
        # 10 words with no ASR counterpart, each in its own separated sung stretch roughly 0.2s from its
        # neighbours — ordinary density, not a crowd — grows metrics()['flashing_words'] by more than the old,
        # now-removed FLASHING_WORDS_TOLERANCE (5), which used to refuse this on song-wide density alone. An
        # 8-word matched run at the start of the song is there only to keep confidence at 'medium' or better.
        directory = Path(tempfile.mkdtemp(prefix='luma-lyrics-scattered-'))
        t, pad_bursts = .5, []
        for _ in range(8): pad_bursts.append((round(t, 2), round(t + .15, 2))); t += .2
        t += 1.0
        dax_burst = (t, t + .35); t += .4
        mid = []
        for _ in range(10): mid.append((round(t, 2), round(t + .15, 2))); t += .2
        shuzzle_burst = (t + .3, t + .7)
        bursts = pad_bursts + [dax_burst] + mid + [shuzzle_burst]
        pad_words = [f'sh{i}' for i in range(8)]
        asr_words = pad_words + ['dax'] + [f'q{i}' for i in range(10)] + ['shuzzle']
        pkg = synthetic_package(directory, bursts=bursts, asr_words=asr_words, duration=t + 2.0)
        for path, key in ((pkg / 'target.json', 'lyrics'), (pkg / 'lyrics' / 'mix.json', 'lines')):
            data = json.loads(path.read_text(encoding='utf-8'))
            for line in data[key]: line['words'] = [w for w in line['words'] if not w['w'].startswith('q')]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        text_file = directory / 'scattered.txt'
        words = pad_words + ['dax'] + [f'w{i}' for i in range(10)] + ['shuzzle']
        text_file.write_text(' '.join(words), encoding='utf-8')
        try:
            r = lt.process_package(pkg, str(text_file), write=True, rebuild=False)
            self.assertGreater(_flashing_growth(r), 5, 'this case must actually exceed the old, now-removed tolerance')
            self.assertNotIn('skipped', r, 'ordinary scattered density must not be refused')
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
