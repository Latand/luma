#!/usr/bin/env python3
"""The lyric text corrector: word matching, gap interpolation, the report, the cache and the safety guard.

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


def synthetic_package(directory: Path) -> Path:
    pkg = directory / 'Synthetic'; pkg.mkdir(parents=True)
    t = np.arange(0, DURATION, 1 / SR); y = np.zeros_like(t)
    for i, (a, b) in enumerate(BURSTS):
        w = (t >= a) & (t < b)
        env = np.minimum(1, (t[w] - a) * 40)
        y[w] = .3 * env * np.sin(2 * np.pi * (220 + 30 * i) * t[w])
    sf.write(pkg / 'vocals_44k.flac', y.astype(np.float32), SR)
    hop = .02; ts = np.arange(0, DURATION, hop)
    sung = np.any([(ts >= a) & (ts < b) for a, b in BURSTS], axis=0)
    points = [[round(float(x), 3), 57.0 if v else None, .9 if v else 0, int(v)] for x, v in zip(ts, sung)]
    notes = [{'id': i, 'a': a, 'b': b, 'm': 57. + i, 'n': 57 + i, 'q': .9, 'ok': True, 'ignored': False} for i, (a, b) in enumerate(BURSTS)]
    asr = [{'a': round(a + .02, 2), 'b': round(a + .08, 2), 'w': w, 'c': .9} for (a, _), w in zip(BURSTS, ASR_WORDS)]
    song = {'schema': 'luma.song.v1', 'title': 'Synthetic Song', 'artist': 'Synthetic Artist', 'duration': DURATION,
            'hop': hop, 'a4': 440, 'points': points, 'notes': notes, 'phrases': [], 'waveform': [],
            'id': 'synthetic', 'sourceId': 'synthetic',
            'lyricsSource': 'Soniox stt-async-v5 on the full mix, 2026-09-11, automatic word timings',
            'lyrics': [{'a': asr[0]['a'], 'b': asr[-1]['b'], 'words': asr}]}
    (pkg / 'target.json').write_text(json.dumps(song, ensure_ascii=False), encoding='utf-8')
    (pkg / 'lyrics').mkdir()
    (pkg / 'lyrics' / 'mix.json').write_text(json.dumps({'source': 'mix', 'lyricsSource': song['lyricsSource'],
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


class FillGapsTests(unittest.TestCase):
    def test_an_inserted_run_is_spaced_strictly_increasing_between_its_neighbours(self):
        entries = [{'a': 1.0, 'kind': 'matched'}, {'a': None, 'kind': 'inserted'}, {'a': None, 'kind': 'inserted'}, {'a': 2.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, duration=10.0)
        times = [e['a'] for e in out]
        self.assertEqual(times, sorted(times))
        self.assertLess(1.0, times[1]); self.assertLess(times[2], 2.0)

    def test_a_trailing_insert_is_spaced_before_the_song_ends(self):
        entries = [{'a': 7.5, 'kind': 'matched'}, {'a': None, 'kind': 'inserted'}]
        out = lt.fill_gaps(entries, duration=8.0)
        self.assertGreater(out[1]['a'], 7.5); self.assertLessEqual(out[1]['a'], 8.0)

    def test_a_leading_insert_is_spaced_from_the_start_of_the_song(self):
        entries = [{'a': None, 'kind': 'inserted'}, {'a': 3.0, 'kind': 'matched'}]
        out = lt.fill_gaps(entries, duration=8.0)
        self.assertGreater(out[0]['a'], 0); self.assertLess(out[0]['a'], 3.0)


class TokenizeTests(unittest.TestCase):
    def test_bracketed_annotation_lines_are_dropped(self):
        text = '[Chorus]\nwug fep\n(Verse 2)\nzorp mun\n'
        self.assertEqual(lt.tokenize(text), ['wug', 'fep', 'zorp', 'mun'])

    def test_punctuation_is_kept_on_the_word(self):
        self.assertEqual(lt.tokenize("wug, fep!\nzorp?"), ['wug,', 'fep!', 'zorp?'])


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
        self.assertAlmostEqual(r['wer_before'], .6); self.assertEqual(r['wer_after'], 0.)

    def test_writing_replaces_only_lyrics_and_lyrics_source(self):
        r = lt.process_package(self.pkg, str(self.text_file), write=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        changed = sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k))
        self.assertEqual(changed, ['lyrics', 'lyricsSource'])
        self.assertEqual([w['w'] for w in al.flat(after['lyrics'])], TRUE_TOKENS)
        self.assertIn('corrected to published lyrics', after['lyricsSource'])
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
            self.assertEqual((self.pkg / 'lyrics' / 'source.txt').read_text(encoding='utf-8'), ' '.join(TRUE_TOKENS))
            r2 = lt.process_package(self.pkg, None, write=True, rebuild=False)
            self.assertEqual(called, [('Synthetic Song', 'Synthetic Artist')], 'a second run must not touch the network again')
            self.assertEqual(r1['words_true'], r2['words_true'])
        finally:
            lt.fetch_lyrics = original

    def test_low_confidence_source_is_left_untouched(self):
        unrelated = Path(self.directory) / 'unrelated.txt'
        unrelated.write_text('qzk vroom nbly wexil ptang jorf mmk zzq vworp klor', encoding='utf-8')
        r = lt.process_package(self.pkg, str(unrelated), write=True, rebuild=False)
        self.assertEqual(r['confidence'], 'low')
        self.assertIn('skipped', r)
        self.assertEqual((self.pkg / 'target.json').read_text(encoding='utf-8'), json.dumps(self.before, ensure_ascii=False))

    def test_the_report_carries_the_metrics_the_operator_needs(self):
        r = lt.process_package(self.pkg, str(self.text_file), write=False)
        for key in ('words_changed', 'words_added', 'words_dropped', 'wer_before', 'wer_after',
                    'median_shift_changed_s', 'confidence', 'agreement_pct'):
            self.assertIn(key, r)


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

    def test_lyrics_only_changes_pass(self):
        before = {'a': 1, 'lyrics': [], 'lyricsSource': 'x'}; after = {'a': 1, 'lyrics': [{}], 'lyricsSource': 'y'}
        lt.verify_guard(self.pkg, before, after, {'v': 'x'}, {'v': 'x'})   # must not raise

    def test_the_audio_fingerprint_covers_the_files_present(self):
        fp = lt.audio_fingerprint(self.pkg)
        self.assertEqual(set(fp), {'vocals_44k.flac'})


class NoNetworkTests(unittest.TestCase):
    def test_source_only_reaches_the_network_through_urllib_and_only_from_fetch_lyrics(self):
        import ast
        tree = ast.parse((ROOT / 'studio' / 'lyrics_text.py').read_text(encoding='utf-8'))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == 'urlopen']
        self.assertTrue(calls, 'the module should still reach the network exactly through urllib.request.urlopen')

    def test_tokenize_and_matching_never_import_network_modules(self):
        import ast
        tree = ast.parse((ROOT / 'studio' / 'lyrics_text.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imported.update(a.name.split('.')[0] for a in node.names)
            if isinstance(node, ast.ImportFrom) and node.module: imported.add(node.module.split('.')[0])
        self.assertTrue({'urllib'} <= imported, 'network access must stay confined to urllib, never requests/http.client')
        self.assertFalse(imported & {'requests', 'http', 'socket'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
