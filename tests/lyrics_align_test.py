#!/usr/bin/env python3
"""The offline lyric re-aligner: word text, word order, neighbours, line breaks and the package round-trip.

Runs on synthetic audio it generates itself. No network call, no Soniox, no song package from the library.
"""
import ast
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
from prepare_song import merge_tokens

SR = 44100
BURSTS = [(.5, 2.0), (3.2, 4.6), (5.0, 7.4)]   # sung stretches of the synthetic stem, seconds
SYLLABLES = [(a, (a + b) / 2 - .02, (a + b) / 2 + .02, b) for a, b in BURSTS]   # two syllables per burst
DURATION = 8.0
TEXT = ['one', 'two', 'three', 'four', 'five', 'six.']
LATE = .22                                     # how late the pretend transcript places every word


def syllables():
    return [(a, b) for first_a, first_b, second_a, second_b in SYLLABLES for a, b in ((first_a, first_b), (second_a, second_b))]


def synthetic_package(directory: Path) -> Path:
    """A song package with three sung phrases of two syllables each and a matching pitch map, plus a transcript that
    is late everywhere, the way Soniox places words under a band."""
    pkg = directory / 'Synthetic'; pkg.mkdir(parents=True)
    t = np.arange(0, DURATION, 1 / SR); y = np.zeros_like(t)
    for i, (a, b) in enumerate(syllables()):
        w = (t >= a) & (t < b)
        env = np.minimum(1, (t[w] - a) * 40)                      # a sharp attack the onset detector can see
        y[w] = .3 * env * np.sin(2 * np.pi * (220 + 30 * i) * t[w])
    sf.write(pkg / 'vocals_44k.flac', y.astype(np.float32), SR)
    hop = .02; ts = np.arange(0, DURATION, hop)
    sung = np.any([(ts >= a) & (ts < b) for a, b in syllables()], axis=0)
    points = [[round(float(x), 3), 57.0 if v else None, .9 if v else 0, int(v)] for x, v in zip(ts, sung)]
    notes = [{'id': i, 'a': a, 'b': b, 'm': 57. + i, 'n': 57 + i, 'q': .9, 'ok': True, 'ignored': False} for i, (a, b) in enumerate(syllables())]
    words = [{'a': round(a + LATE, 2), 'b': round(a + LATE + .06, 2), 'w': w, 'c': .9} for (a, _), w in zip(syllables(), TEXT)]
    words[-1]['b'] = 7.9                                          # a merged last word claiming the rest of the song
    song = {'schema': 'luma.song.v1', 'title': 'Synthetic', 'artist': '', 'duration': DURATION, 'hop': hop, 'a4': 440,
            'points': points, 'notes': notes, 'phrases': [], 'waveform': [], 'id': 'synthetic', 'sourceId': 'synthetic',
            'lyricsSource': 'Soniox stt-async-v5 on the full mix, 2026-09-11, automatic word timings',
            'lyrics': [{'a': words[0]['a'], 'b': words[-1]['b'], 'words': words}]}
    (pkg / 'target.json').write_text(json.dumps(song, ensure_ascii=False), encoding='utf-8')
    return pkg


class AlignerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp(prefix='luma-align-')
        cls.pkg = synthetic_package(Path(cls.directory))
        cls.song = json.loads((cls.pkg / 'target.json').read_text(encoding='utf-8'))
        cls.ctx = al.context(cls.pkg, cls.song)
        cls.words = al.flat(cls.song['lyrics'])
        cls.lines = al.realign(cls.words, cls.ctx)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def test_the_stem_gives_one_voiced_region_per_sung_burst(self):
        self.assertEqual(len(self.ctx['phrases']), len(BURSTS))
        for (a, b), (want_a, want_b) in zip(self.ctx['phrases'], BURSTS):
            self.assertAlmostEqual(a, want_a, delta=.15); self.assertAlmostEqual(b, want_b, delta=.15)

    def test_word_text_and_order_survive(self):
        self.assertEqual([w['w'] for w in al.flat(self.lines)], [w['w'] for w in self.words])

    def test_starts_snap_to_vocal_onsets_within_the_window(self):
        moved = [abs(b['a'] - a['a']) for a, b in zip(self.words, al.flat(self.lines))]
        self.assertLessEqual(max(moved), al.SNAP + 1e-9, 'no word start may travel further than the snapping window')
        self.assertEqual(len(moved), len(TEXT))
        for word in al.flat(self.lines):                                     # every word lands on an attack of the voice
            self.assertLess(min(abs(word['a'] - o) for o in self.ctx['onsets']), .02, word['w'])
        first = al.flat(self.lines)[0]
        self.assertAlmostEqual(first['a'], BURSTS[0][0], delta=.1, msg='the first word starts where the voice starts')
        self.assertLess(first['a'], self.words[0]['a'], 'a late word is pulled back to the voice')

    def test_no_word_crosses_its_neighbour(self):
        words = al.flat(self.lines)
        for a, b in zip(words, words[1:]):
            self.assertLess(a['a'], b['a']); self.assertLessEqual(a['b'], b['a'])
        self.assertLessEqual(max(w['b'] for w in words), DURATION)
        self.assertTrue(all(w['b'] > w['a'] for w in words))

    def test_a_word_is_never_lit_past_the_voice_that_sings_it(self):
        for w in al.flat(self.lines):
            self.assertLess(al.silence_between(self.ctx['voiced'], w['a'], w['b']), al.GAP)

    def test_lines_break_at_vocal_silences(self):
        self.assertEqual(len(self.lines), len(BURSTS), 'one line per sung phrase')
        self.assertEqual([[w['w'] for w in l['words']] for l in self.lines], [['one', 'two'], ['three', 'four'], ['five', 'six.']])
        for line in self.lines:
            self.assertAlmostEqual(line['a'], line['words'][0]['a'], places=2)
            self.assertAlmostEqual(line['b'], line['words'][-1]['b'], places=2)
        for a, b in zip(self.lines, self.lines[1:]):
            self.assertLessEqual(a['b'], b['a'])

    def test_a_legato_run_is_cut_into_readable_lines(self):
        packed = [{'a': round(.55 + .1 * i, 2), 'b': round(.6 + .1 * i, 2), 'w': f'w{i}', 'c': .9} for i in range(14)]
        lines = al.realign(packed, self.ctx)
        self.assertTrue(all(len(l['words']) <= al.MAX_WORDS for l in lines))
        self.assertEqual([w['w'] for l in lines for w in l['words']], [w['w'] for w in packed])

    def test_a_long_stretch_without_a_single_word_breaks_the_line(self):
        held = [{'a': 5.2, 'b': 5.3, 'w': 'held', 'c': .9}, {'a': 7.3, 'b': 7.4, 'w': 'on', 'c': .9}]
        self.assertEqual(len(al.realign(held, self.ctx)), 2, 'the voice never stops, but no word arrives for two seconds')
        near = [held[0], {'a': 6.3, 'b': 6.4, 'w': 'on', 'c': .9}]
        self.assertEqual(len(al.realign(near, self.ctx)), 1, 'a held note inside one phrase keeps its words together')

    def test_a_word_far_from_every_onset_keeps_its_own_start(self):
        stray = [{'a': 2.6, 'b': 2.8, 'w': 'stray', 'c': .5}]                # deep in the silence after the first phrase
        self.assertEqual(al.flat(al.realign(stray, self.ctx))[0]['a'], 2.6)

    def test_re_aligning_twice_changes_nothing(self):
        again = al.realign(al.flat(self.lines), self.ctx)
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.lines, sort_keys=True))

    def test_dp_match_keeps_word_order_and_the_window(self):
        onsets = np.array([0., 1., 2., 3.])
        self.assertEqual(al.dp_match(np.array([1.02, 2.9]), onsets, .35, .3), [1, 3])
        self.assertEqual(al.dp_match(np.array([1.8]), onsets, .1, .3), [None], 'nothing within the window stays unmatched')
        matched = [j for j in al.dp_match(np.array([.1, .9, 1.05, 3.1]), onsets, .35, .3) if j is not None]
        self.assertEqual(matched, sorted(set(matched)), 'matches are strictly increasing, one onset each')

    def test_metrics_see_the_improvement(self):
        before = al.metrics(self.song['lyrics'], self.ctx); after = al.metrics(self.lines, self.ctx)
        self.assertGreater(before['boundary_misassignments'], after['boundary_misassignments'])
        self.assertEqual(after['boundary_misassignments'], 0)
        self.assertLess(abs(after['onset_error']['med']), abs(before['onset_error']['med']) + 1e-9)
        self.assertGreater(before['flashing_words'], after['flashing_words'])

    def test_the_pitch_map_check_is_independent_of_the_snapping(self):
        after = al.metrics(self.lines, self.ctx)
        self.assertEqual(after['onset_error'], {'n': len(TEXT), 'med': 0., 'p10': 0., 'p90': 0.},
                         'snapping makes the error against its own onsets zero, which is why it cannot be the headline')
        before = al.metrics(self.song['lyrics'], self.ctx)
        self.assertLess(abs(after['onset_error_pitchmap']['med']), abs(before['onset_error_pitchmap']['med']))
        self.assertLess(after['off_over_100ms_pitchmap'], before['off_over_100ms_pitchmap'])
        self.assertIn('pitch map', al.human({'package': 'x', 'source': 'mix', 'snapped': 1,
                                             'moved': al.stat([.1]), 'before': before, 'after': after}))

    def test_agreement_counts_shared_words(self):
        a = [{'w': 'Hold'}, {'w': 'me,'}, {'w': 'now'}]; b = [{'w': 'hold'}, {'w': 'me'}, {'w': 'right'}, {'w': 'now'}]
        self.assertEqual(al.agreement(a, b), {'words_a': 3, 'words_b': 4, 'shared': 3, 'only_a': 0, 'only_b': 1, 'agreement_pct': 85.7})


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-align-pkg-')
        self.pkg = synthetic_package(Path(self.directory))
        self.before = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_aligning_a_package_touches_only_words_and_lines(self):
        report = al.align_package(self.pkg, write=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k)), ['lyrics', 'lyricsSource'])
        self.assertEqual([w['w'] for w in al.flat(after['lyrics'])], [w['w'] for w in al.flat(self.before['lyrics'])])
        self.assertIn('aligned offline to vocal onsets', after['lyricsSource'])
        self.assertEqual(report['source'], 'mix')
        stored = json.loads((self.pkg / 'lyrics' / 'mix.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['lines'], self.before['lyrics'], 'the transcript is kept exactly as it arrived')

    def test_a_second_run_starts_from_the_stored_transcript(self):
        al.align_package(self.pkg, write=True, rebuild=False)
        once = (self.pkg / 'target.json').read_text(encoding='utf-8')
        al.align_package(self.pkg, write=True, rebuild=False)
        self.assertEqual(once, (self.pkg / 'target.json').read_text(encoding='utf-8'))

    def test_dry_run_writes_nothing(self):
        before = (self.pkg / 'target.json').read_text(encoding='utf-8')
        report = al.align_package(self.pkg, write=False)
        self.assertEqual(before, (self.pkg / 'target.json').read_text(encoding='utf-8'))
        self.assertFalse((self.pkg / 'lyrics').exists())
        self.assertEqual(report['after']['words'], report['before']['words'])
        self.assertIn('Synthetic', al.human(report))

    def test_the_operator_can_switch_between_the_stored_transcripts(self):
        al.align_package(self.pkg, write=True, rebuild=False)                # stores the mix transcript
        vocal = [dict(w) for w in al.flat(self.before['lyrics'])[:4]]
        for w in vocal: w['w'] = w['w'].upper()
        al.save_transcript(self.pkg, 'vocal', [{'a': vocal[0]['a'], 'b': vocal[-1]['b'], 'words': vocal}], 'vocal stem')
        self.assertEqual(al.align_package(self.pkg, write=True, rebuild=False)['source'], 'vocal', 'the vocal transcript wins by default')
        self.assertEqual([w['w'] for w in al.flat(json.loads((self.pkg / 'target.json').read_text())['lyrics'])], [w['w'] for w in vocal])
        back = al.align_package(self.pkg, write=True, rebuild=False, prefer='mix')
        self.assertEqual(back['source'], 'mix')
        self.assertEqual([w['w'] for w in al.flat(json.loads((self.pkg / 'target.json').read_text())['lyrics'])], TEXT,
                         'going back to the mix transcript costs nothing and loses no word')
        with self.assertRaises(SystemExit):
            al.align_package(self.pkg, write=False, prefer='nothing-stored-under-this-name')

    def test_pooled_totals_add_the_songs_up_instead_of_averaging_them(self):
        al.align_package(self.pkg, write=True, rebuild=False)
        one = al.variants(self.pkg); both = al.pooled([one, one])
        self.assertEqual(both['songs'], 2)
        self.assertEqual(both['original']['words'], 2 * one['original']['words'])
        self.assertEqual(both['original']['onset_error_pitchmap']['n'], 2 * one['original']['onset_error_pitchmap']['n'])
        self.assertEqual(both['original']['onset_error_pitchmap']['med'], one['original']['onset_error_pitchmap']['med'])
        self.assertNotIn('_off_pitchmap', json.dumps(al.strip_raw(one)), 'the per-word arrays never reach the printed report')

    def test_variants_compares_the_original_with_the_re_alignment(self):
        al.align_package(self.pkg, write=True, rebuild=False)
        vocal = [dict(w) for w in al.flat(self.before['lyrics'])[:3]] + [{'a': 5.1, 'b': 5.4, 'w': 'seven', 'c': .9}]
        al.save_transcript(self.pkg, 'vocal', [{'a': vocal[0]['a'], 'b': vocal[-1]['b'], 'words': vocal}], 'vocal stem')
        r = al.variants(self.pkg)
        self.assertEqual(set(r) - {'package'}, {'original', 'original_realigned', 'vocal_realigned', 'agreement_mix_vs_vocal'})
        self.assertEqual((r['original']['words'], r['vocal_realigned']['words']), (len(TEXT), len(vocal)))
        self.assertEqual(r['agreement_mix_vs_vocal'], {'words_a': 6, 'words_b': 4, 'shared': 3, 'only_a': 3, 'only_b': 1, 'agreement_pct': 60.0})


class CorrectionReplayTests(unittest.TestCase):
    """A cached lyrics correction (lyrics/source.txt) must replay through a plain re-alignment when it still passes
    the same checks a direct correction would, and must never be applied when it doesn't (round 2, finding 3)."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-align-correction-')
        self.pkg = synthetic_package(Path(self.directory))

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _cache_source(self, text):
        d = self.pkg / 'lyrics'; d.mkdir(exist_ok=True)
        (d / 'source.txt').write_text(text, encoding='utf-8')
        (d / 'source.meta.json').write_text(json.dumps({'title': '', 'artist': ''}), encoding='utf-8')   # no manifest.json here: empty title/artist is what it was "fetched" for

    def test_a_passing_correction_survives_realignment(self):
        self._cache_source('one two THREE four five six')
        report = al.align_package(self.pkg, write=True, rebuild=False)
        self.assertEqual(report['correction'], 'applied')
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        self.assertEqual([w['w'] for w in al.flat(after['lyrics'])], ['one', 'two', 'THREE', 'four', 'five', 'six'])

    def test_a_gate_failing_correction_leaves_align_package_on_the_transcript(self):
        self._cache_source('completely unrelated nonsense words sharing nothing with this transcript at all here')
        report = al.align_package(self.pkg, write=True, rebuild=False)
        self.assertTrue(report['correction'] and report['correction'].startswith('refused'))
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        self.assertEqual([w['w'] for w in al.flat(after['lyrics'])], TEXT, 'a refused correction must not touch the published words')

    def test_no_cached_source_leaves_correction_unset(self):
        report = al.align_package(self.pkg, write=True, rebuild=False)
        self.assertIsNone(report['correction'])


class TranscriptTests(unittest.TestCase):
    def test_a_full_stop_far_from_the_word_does_not_stretch_it(self):
        tokens = [{'text': 'hold', 'start_ms': 1000, 'end_ms': 1200, 'confidence': .9},
                  {'text': 'ing', 'start_ms': 1200, 'end_ms': 1400, 'confidence': .5},
                  {'text': '.', 'start_ms': 40000, 'end_ms': 40100, 'confidence': .9},
                  {'text': ' on', 'start_ms': 41000, 'end_ms': 41300, 'confidence': .8}]
        words = merge_tokens(tokens)
        self.assertEqual([w['w'] for w in words], ['holding.', 'on'])
        self.assertEqual(words[0]['b'], 1.4, 'the word ends where it was sung, not where the sentence ends')
        self.assertEqual(words[0]['c'], .5, 'a merged word carries the confidence of its weakest token')
        self.assertEqual((words[1]['a'], words[1]['b']), (41.0, 41.3))

    def test_a_close_continuation_still_extends_the_word(self):
        words = merge_tokens([{'text': 'no', 'start_ms': 0, 'end_ms': 200, 'confidence': .9},
                              {'text': 'w', 'start_ms': 200, 'end_ms': 500, 'confidence': .9}])
        self.assertEqual([(w['w'], w['b']) for w in words], [('now', .5)])

    def test_the_aligner_never_talks_to_the_network(self):
        tree = ast.parse((ROOT / 'studio' / 'align_lyrics.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imported.update(a.name.split('.')[0] for a in node.names)
            if isinstance(node, ast.ImportFrom) and node.module: imported.add(node.module.split('.')[0])
        self.assertFalse(imported & {'urllib', 'http', 'socket', 'ssl', 'requests', 'prepare_song', 'retranscribe_song'},
                         f'the offline aligner must not reach the network: {sorted(imported)}')


class PaidCallTests(unittest.TestCase):
    """The one command that spends the operator's money must be unreachable from anything but a shell."""

    def test_importing_the_command_cannot_pay(self):
        import retranscribe_song as rt
        self.assertFalse(rt.PAID_CALLS_ALLOWED, 'an import must never arm the paying branch')
        directory = tempfile.mkdtemp(prefix='luma-paid-')
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        pkg = synthetic_package(Path(directory))
        with self.assertRaises(SystemExit) as e:
            rt.transcribe(pkg, 'en', cache_only=False)
        self.assertIn('from a shell', str(e.exception))
        self.assertFalse((pkg / 'lyrics').exists(), 'a refused call leaves no audio and no cache behind')

    def test_the_command_refuses_to_arm_itself_under_a_test_runner(self):
        import retranscribe_song as rt
        with self.assertRaises(SystemExit) as e:
            rt.allow_paid_calls()
        self.assertIn('run it directly from a shell', str(e.exception))
        self.assertFalse(rt.PAID_CALLS_ALLOWED)

    def test_nothing_in_the_repo_invokes_the_command(self):
        allowed = {Path(__file__).name, 'retranscribe_song_test.py'}   # tests that deliberately audit the paid command
        callers = []
        for f in [*(ROOT / 'app').rglob('*'), *(ROOT / 'studio').rglob('*'), *(ROOT / 'tests').rglob('*')]:
            if not f.is_file() or f.suffix not in {'.py', '.js', '.mjs', '.html', '.sh'} or f.name == 'retranscribe_song.py': continue
            if 'retranscribe_song' in f.read_text(encoding='utf-8', errors='ignore'): callers.append(f.name)
        self.assertEqual(set(callers), allowed, f'only audited test files may name the paid command: {callers}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
