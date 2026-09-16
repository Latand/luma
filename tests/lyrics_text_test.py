#!/usr/bin/env python3
"""The lyric text corrector: word matching, gap interpolation, completeness/placement checks, the report, the cache
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

    def test_extra_replacement_words_spread_across_the_whole_replaced_span_not_squeezed_at_one_end(self):
        asr = [{'a': 10.0, 'b': 10.3, 'w': 'aa', 'c': .9}, {'a': 15.0, 'b': 15.3, 'w': 'bb', 'c': .9}]
        true = ['xx', 'yy', 'zz', 'ww']
        entries = lt.match_words(asr, true)
        times = [e['a'] for e in entries]
        self.assertTrue(all(t is not None for t in times), 'every word in the replaced block already has a seed time')
        self.assertEqual(times, sorted(times))
        self.assertGreaterEqual(times[-1] - times[0], 3.0,
                                 'the extra words must be spread across the whole replaced span, not squeezed at one end')


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


class TokenizeTests(unittest.TestCase):
    def test_bracketed_annotation_lines_are_dropped(self):
        text = '[Chorus]\nwug fep\n(Verse 2)\nzorp mun\n'
        self.assertEqual(lt.tokenize(text), ['wug', 'fep', 'zorp', 'mun'])

    def test_punctuation_is_kept_on_the_word(self):
        self.assertEqual(lt.tokenize("wug, fep!\nzorp?"), ['wug,', 'fep!', 'zorp?'])


class CompletenessIssuesTests(unittest.TestCase):
    def test_a_long_dropped_run_is_flagged(self):
        asr = [{'a': float(i), 'b': i + .3, 'w': f'w{i}', 'c': .9} for i in range(6)]
        entries = [{'src': 0, 'kind': 'matched'}, {'src': 5, 'kind': 'matched'}]
        self.assertTrue(lt.completeness_issues(asr, entries))

    def test_a_short_dropped_run_is_not_flagged(self):
        asr = [{'a': float(i), 'b': i + .1, 'w': f'w{i}', 'c': .9} for i in range(3)]
        entries = [{'src': 0, 'kind': 'matched'}, {'src': 2, 'kind': 'matched'}]
        self.assertFalse(lt.completeness_issues(asr, entries))

    def test_a_large_tail_gap_is_flagged(self):
        asr = [{'a': float(i), 'b': i + .3, 'w': f'w{i}', 'c': .9} for i in range(20)]
        entries = [{'src': 0, 'kind': 'matched'}]
        self.assertTrue(lt.completeness_issues(asr, entries))


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

    def test_writing_replaces_only_lyrics_and_lyrics_source(self):
        r = lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        changed = sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k))
        self.assertEqual(changed, ['lyrics', 'lyricsSource'])
        self.assertEqual([w['w'] for w in al.flat(after['lyrics'])], TRUE_TOKENS)
        self.assertIn('corrected to published lyrics', after['lyricsSource'])
        self.assertIn('mix', after['lyricsSource'], 'the transcript actually used should be named in the note')
        self.assertEqual(r['confidence'], 'medium')

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

    def test_the_report_carries_the_metrics_the_operator_needs(self):
        r = lt.process_package(self.pkg, str(self.text_file), write=False)
        for key in ('words_changed', 'words_added', 'words_dropped', 'wer_before',
                    'median_shift_changed_s', 'confidence', 'agreement_pct',
                    'words_inserted_off_onset', 'words_inserted_in_silence', 'repeated_sections_recovered'):
            self.assertIn(key, r)

    def test_rebuild_writes_the_trainer_html(self):
        for name in ('backing.mp3', 'foreground.mp3', 'backing_80.mp3', 'foreground_80.mp3'):
            (self.pkg / name).write_bytes(b'\xff\xfb\x90\x00' + b'\x00' * 32)   # minimal stub, build_html only base64-embeds it
        r = lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=True)
        self.assertIn('html', r)
        html_path = Path(r['html'])
        self.assertTrue(html_path.exists())
        self.assertGreater(html_path.stat().st_size, 1000)


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


class CompletenessGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-lyrics-complete-')
        self.pkg = synthetic_package(Path(self.directory))
        self.before = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_a_source_missing_a_long_middle_run_is_left_untouched(self):
        source = Path(self.directory) / 'partial.txt'; source.write_text('flim shuzzle', encoding='utf-8')
        r = lt.process_package(self.pkg, str(source), write=True, rebuild=False)
        self.assertEqual(r['confidence'], 'medium', 'the refusal here must come from the completeness check, not low confidence')
        self.assertIn('skipped', r)
        self.assertEqual((self.pkg / 'target.json').read_text(encoding='utf-8'), json.dumps(self.before, ensure_ascii=False))

    def test_force_overrides_the_completeness_refusal(self):
        source = Path(self.directory) / 'partial.txt'; source.write_text('flim shuzzle', encoding='utf-8')
        r = lt.process_package(self.pkg, str(source), write=True, rebuild=False, force=True)
        self.assertNotIn('skipped', r)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        self.assertNotEqual(after['lyrics'], self.before['lyrics'])


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
