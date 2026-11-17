"""Synthetic LRC, audio and stub aligner tests; no weights or network."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.song_auto import run, synced
from tools.song_auto.bench import run as bench, score


def lyrics():
    # Deliberately different package row grouping and unusable reference clocks.
    return [dict(words=[dict(w='aa', a=99, b=100), dict(w='bb', a=99, b=100),
                        dict(w='cc', a=99, b=100)]), dict(words=[dict(w='dd', a=99, b=100)])]


LRC = '[00:01.00] aa bb\n[00:02.00] cc dd\n[00:03.00]'


class Plans(unittest.TestCase):
    def test_matches_regrouped_text_without_reference_times(self):
        plan = synced.line_plan(lyrics(), LRC, 4.)
        self.assertEqual([(r['start'], r['end']) for r in plan], [(0, 2), (2, 4)])
        self.assertEqual([(r['lo'], r['hi']) for r in plan], [(.75, 2.), (2., 3.)])
        changed = lyrics()
        for row in changed:
            for word in row['words']: word.update(a=-100, b=-99)
        self.assertEqual(synced.word_bounds(synced.line_plan(changed, LRC, 4.)), synced.word_bounds(plan))

    def test_offsets_punctuation_and_repeated_occurrences(self):
        rows = [dict(words=[dict(w=w) for w in ('AA!', 'bb', 'AA!', 'bb')])]
        plan = synced.line_plan(rows, '[offset:100]\n[00:01] aa bb\n[00:02] aa bb', 4.)
        self.assertEqual([r['a'] for r in plan], [1.1, 2.1])
        self.assertEqual([(r['start'], r['end']) for r in plan], [(0, 2), (2, 4)])

    def test_small_text_difference_and_source_only_row_reserve_time(self):
        rows = [dict(words=[dict(w=f'w{i}') for i in range(10)])]
        text = '[00:00] '+' '.join(f'w{i}' for i in range(5))+'\n[00:02] extra\n[00:03] '+' '.join(f'w{i}' for i in range(5, 10))
        plan = synced.line_plan(rows, text, 6.)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]['hi'], 2.)
        self.assertEqual(plan[1]['lo'], 3.)
        text = text.replace('w8', 'changed')
        self.assertEqual(len(synced.line_plan(rows, text, 6.)), 2)

    def test_refuses_unmatched_text_and_unanchored_prefix(self):
        for text in ('[00:01] other text', '[00:01] bb cc dd'):
            with self.subTest(text=text), self.assertRaises(synced.AnchorError):
                synced.line_plan(lyrics(), text, 4.)
        tokens = 'alpha beta gamma delta echo foxtrot golf hotel india juliet'.split()
        rows = [dict(words=[dict(w=w) for w in tokens])]
        with self.assertRaisesRegex(synced.AnchorError, 'cover known lyric text'):
            synced.line_plan(rows, '[00:01] '+' '.join(tokens[1:]), 4.)

    def test_refuses_invalid_duplicate_reversed_out_of_recording_and_empty_rows(self):
        for text in ('garbage', '[00:01] aa bb\n[00:01] cc dd',
                     '[00:02] aa bb\n[00:01] cc dd', '[00:04] aa bb cc dd',
                     '[00:01]', '[00:01] <00:01.01>aa bb cc dd'):
            with self.subTest(text=text), self.assertRaises(synced.AnchorError):
                synced.line_plan(lyrics(), text, 4.)
        with self.assertRaises(synced.AnchorError): synced.line_plan([], LRC, 4.)
        with self.assertRaises(synced.AnchorError): synced.line_plan(lyrics()+[dict(words=[])], LRC, 4.)
        for duration in (0, -1, float('nan')):
            with self.assertRaises(synced.AnchorError): synced.line_plan(lyrics(), LRC, duration)

    def test_refuses_missing_words_at_every_line_position(self):
        # The review's missing final row (80%) and next-row prefix (90%),
        # plus the same class at a first/middle row and a last-word boundary.
        rows = [dict(words=[dict(w=f'w{i}') for i in range(5)]),
                dict(words=[dict(w=f'w{i}') for i in range(5, 10)])]
        sources = [
            '[00:01] w0 w1 w2 w3 w4\n[00:10] w6 w7 w8 w9',
            '[00:01] w0 w1 w2 w3\n[00:10] w5 w6 w7 w8 w9',
            '[00:01] w1 w2 w3 w4\n[00:10] w5 w6 w7 w8 w9',
            '[00:01] w0 w1 w2 w3 w4\n[00:10] w5 w6 w7 w8',
        ]
        for text in sources:
            with self.subTest(text=text), self.assertRaisesRegex(synced.AnchorError, 'unmatched words'):
                synced.line_plan(rows, text, 15.)
        for missing in range(3):
            known = [dict(words=[dict(w=f'w{i}') for i in range(a, b)])
                     for a, b in ((0, 8), (8, 9), (9, 10))]
            text = '\n'.join(f'[00:{1+4*i:02}] ' + ' '.join(w['w'] for w in row['words'])
                             for i, row in enumerate(known) if i != missing)
            with self.subTest(missing=missing), self.assertRaises(synced.AnchorError):
                synced.line_plan(known, text, 15.)
        known = [dict(words=[dict(w=f'w{i}') for i in range(8)]),
                 dict(words=[dict(w='w8'), dict(w='w9')])]
        with self.assertRaisesRegex(synced.AnchorError, 'unmatched words'):
            synced.line_plan(known, '[00:01] w0 w1 w2 w3 w4 w5 w6 w7\n[00:03]', 12.)

    def test_only_interior_substitutions_have_supported_boundaries(self):
        rows = [dict(words=[dict(w=f'w{i}') for i in range(10)])]
        for index in (0, 4, 5, 9):
            words = [f'w{i}' if i != index else 'changed' for i in range(10)]
            text = '[00:01] '+' '.join(words[:5])+'\n[00:03] '+' '.join(words[5:])
            with self.subTest(index=index), self.assertRaisesRegex(synced.AnchorError, 'line boundary'):
                synced.line_plan(rows, text, 6.)
        text = '[00:01] w0 changed w2 w3 w4\n[00:03] w5 w6 w7 w8 w9'
        self.assertEqual([r['end'] for r in synced.line_plan(rows, text, 6.)], [5, 10])
        # Extra source tokens may be omitted only inside a supported row;
        # deleting a source edge would leave its timestamp unverified.
        for line, index in ((0, 0), (0, 5), (1, 0), (1, 5)):
            first, second = [f'w{i}' for i in range(5)], [f'w{i}' for i in range(5, 10)]
            (first, second)[line].insert(index, 'extra')
            text = '[00:01] '+' '.join(first)+'\n[00:03] '+' '.join(second)
            with self.subTest(extra_edge=(line, index)), self.assertRaisesRegex(synced.AnchorError, 'line boundary'):
                synced.line_plan(rows, text, 6.)
        text = '[00:01] w0 extra w1 w2 w3 w4\n[00:03] w5 w6 w7 w8 w9'
        self.assertEqual([r['end'] for r in synced.line_plan(rows, text, 6.)], [5, 10])
        # A whole known row replaced inside an otherwise matching source row.
        known = [dict(words=[dict(w=f'w{i}') for i in range(8)]), dict(words=[dict(w='w8')]),
                 dict(words=[dict(w='w9')])]
        with self.assertRaisesRegex(synced.AnchorError, 'known lyric row'):
            synced.line_plan(known, '[00:01] w0 w1 w2 w3 w4 w5 w6 w7 changed w9', 6.)

    def test_adjacent_rows_keep_the_previous_vocal_tail(self):
        plan = synced.line_plan(lyrics(), '[00:01] aa bb\n[00:02] cc dd', 3.)
        self.assertTrue(plan[0]['lo'] <= 1.90 < plan[0]['hi'])
        self.assertFalse(plan[1]['lo'] <= 1.90 < plan[1]['hi'])
        self.assertEqual(plan[0]['hi'], plan[1]['lo'])

    def test_early_padding_uses_only_an_explicit_instrumental_gap(self):
        for gap in (1.5, 1.9):
            text = f'[00:01] aa bb\n[00:{gap:05.2f}]\n[00:02] cc dd'
            plan = synced.line_plan(lyrics(), text, 4.)
            self.assertEqual(plan[0]['hi'], gap)
            self.assertEqual(plan[1]['lo'], max(gap, 1.75))
            self.assertLessEqual(plan[0]['hi'], plan[1]['lo'])
        plan = synced.line_plan(lyrics(), '[00:00.90]\n[00:01] aa bb\n[00:02] cc dd', 4.)
        self.assertEqual(plan[0]['lo'], .9)

    def test_window_budget_and_recording_edges(self):
        plan = synced.line_plan(lyrics(), '[00:00] aa bb\n[00:50] cc dd', 100.)
        self.assertEqual(plan[0]['lo'], 0.)
        self.assertLessEqual(plan[0]['hi']-plan[0]['lo'], 30.)
        self.assertLessEqual(plan[-1]['hi'], 100.)
        with self.assertRaisesRegex(synced.AnchorError, 'insufficient room'):
            synced.line_plan(lyrics(), '[00:00] aa bb\n[00:00.01] cc dd', 4.)

    def test_trivial_even_spread_starts_at_published_anchor(self):
        p = synced.even_words(synced.line_plan(lyrics(), LRC, 4.))
        self.assertEqual([w['a'] for w in p], [1., 1.5, 2., 2.5])
        self.assertTrue(all(w['confidence'] == 0 for w in p))
        plan = synced.line_plan(lyrics(), LRC, 4.)
        plan[0]['hi'] = plan[0]['a']
        with self.assertRaisesRegex(synced.AnchorError, 'no time after'):
            synced.even_words(plan)


class Bounds(unittest.TestCase):
    def test_order_projection_preserves_each_synced_window_and_original_rows(self):
        plan = synced.line_plan(lyrics(), LRC, 4.)
        p = synced.even_words(plan)
        p[0].update(a=1.70, b=1.74); p[1].update(a=.76, b=1.5)
        p[2].update(a=2.70, b=2.74); p[3].update(a=2.01, b=2.5)
        mapped, flags = run.map_words(lyrics(), p, 4., synced.word_bounds(plan))
        ws = score.words(dict(lyrics=mapped))
        self.assertEqual([len(row['words']) for row in mapped], [3, 1])
        self.assertTrue(flags)
        for w, (lo, hi) in zip(ws, synced.word_bounds(plan)):
            self.assertTrue(lo <= w['a'] < w['b'] <= hi)
        self.assertTrue(all(a['b'] <= b['a'] for a, b in zip(ws, ws[1:])))

    def test_rejects_outside_stub_output_and_overlapping_windows(self):
        plan = synced.line_plan(lyrics(), LRC, 4.); p = synced.even_words(plan)
        bounds = synced.word_bounds(plan)
        for index, value in [(0, .7), (2, 1.7)]:
            bad = copy.deepcopy(p); bad[index]['a'] = value
            with self.assertRaisesRegex(ValueError, 'crosses synced'):
                run.map_words(lyrics(), bad, 4., bounds)
        with self.assertRaises(ValueError): run.map_words(lyrics(), p, 4., bounds[:-1])
        with self.assertRaises(ValueError): run.map_words(lyrics(), p, 4., bounds[:2]+[(1.5, 2.75)]*2)

    def test_place_passes_plan_to_aligner_and_keeps_default_call(self):
        from song_auto_test import target, package
        import numpy as np
        with tempfile.TemporaryDirectory() as temp:
            pkg = package(Path(temp)); base = target()
            text = '[00:00.20] ab-cd ef\n[00:01.50]'
            plan = synced.line_plan(base['lyrics'], text, 2.)
            def aligned(*args, **kwargs):
                self.assertEqual(kwargs['synced_plan'], plan)
                return synced.even_words(plan), {}
            features = dict(qa_t=np.arange(0, 2, .02), qa_db=np.full(100, -90.),
                            qa_periodicity=np.zeros(100), qa_concentration=np.zeros(100))
            with patch.object(bench, 'align', side_effect=aligned), patch.object(run, 'compute', return_value=features), \
                    patch.object(run, 'screen', return_value={'flags': []}), patch.object(run, 'detect', return_value=[]):
                result, report = run.place(pkg, base, base, 'cpu', pitch_song=base, synced_text=text)
            self.assertEqual(report['anchor_source'], 'synced')
            self.assertEqual([w['w'] for w in score.words(result)], ['ab-cd', 'ef'])
            with patch.object(bench, 'align') as aligner, self.assertRaises(synced.AnchorError):
                run.place(pkg, base, base, 'cpu', synced_text='[00:00] wrong')
            aligner.assert_not_called()
            with self.assertRaises(synced.AnchorError):
                run.place(pkg, base, base, 'cpu', synced_text=text, refinement='boundary')

    def test_aligner_receives_synthetic_audio_crops_in_synced_windows(self):
        import numpy as np
        import torch
        import torchaudio
        from types import SimpleNamespace
        import soundfile as sf
        plan = synced.line_plan(lyrics(), LRC, 4.)
        sizes, tails = [], []
        class Model:
            def to(self, device): return self
            def eval(self): return self
            def __call__(self, wave):
                sizes.append(wave.shape[-1]); tails.append(bool(wave.abs().max() > .5))
                return torch.zeros(1, 50, 30), None
        def runs(*args):
            return [SimpleNamespace(start=i*5, end=i*5+2, score=.9) for i in range(6)]
        with tempfile.TemporaryDirectory() as temp:
            pkg = Path(temp)
            audio = np.zeros(64000); audio[int(1.90*16000)] = .9
            sf.write(pkg/'vocals_44k.flac', audio, 16000)
            with patch.object(torchaudio.pipelines.MMS_FA, 'get_model', return_value=Model()), \
                    patch.object(torchaudio.functional, 'forced_align', return_value=(torch.zeros(1, 50), torch.zeros(1, 50))), \
                    patch.object(torchaudio.functional, 'merge_tokens', side_effect=runs):
                p, meta = bench.align(pkg, lyrics(), dict(duration=4.), 'mms', 'cpu', plan)
        self.assertEqual(sizes, [20000, 16000])
        self.assertEqual(tails, [True, False])
        self.assertEqual(meta['windows'], [(.75, 2.), (2., 3.)])
        for w, (lo, hi) in zip(p, synced.word_bounds(plan)):
            self.assertTrue(lo <= w['a'] < w['b'] <= hi)


class Commands(unittest.TestCase):
    def test_full_command_stub_builds_trainer_watches_source_and_refuses_mismatch(self):
        from song_auto_test import package
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pkg = package(root); lrc = root/'input.lrc'
            lrc.write_text('[00:00.20] ab-cd ef\n[00:01.50]')
            runner = root/'stub.py'
            runner.write_text('import sys, os\nfrom pathlib import Path\nsys.path.insert(0, '+repr(str(ROOT))+')\n'
                'from tools.song_auto import run, synced\n'
                'def align(package, lyrics, seed, candidate, device, synced_plan=None):\n'
                '    assert synced_plan is not None\n'
                '    if os.environ.get("CHANGE_SOURCE"): Path(os.environ["SOURCE"]).write_text("changed")\n'
                '    return synced.even_words(synced_plan), {}\n'
                'run.bench.align=align\nrun.pitch_target=lambda package,base,device: base\nrun.main()\n')
            cmd = [sys.executable, '-B', str(runner), str(pkg), '--device', 'cpu', '--scratch', str(root/'out'),
                   '--model-cache', str(root/'models'), '--synced-lyrics', str(lrc)]
            env = {**os.environ, 'SOURCE': str(lrc)}
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = Path(json.loads(r.stdout.splitlines()[-1])['output'])
            self.assertTrue((out.parent/'trainer.html').exists())
            self.assertEqual(json.loads((out.parent/'checks.json').read_text())['anchor_source'], 'synced')
            r = subprocess.run(cmd, cwd=ROOT, env={**env, 'CHANGE_SOURCE': '1'}, capture_output=True, text=True, timeout=90)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('input changed during run', r.stderr)
            lrc.write_text('[00:00] unrelated words')
            # Exercise the real module's public, lyric-free error message.
            cmd = [sys.executable, '-B', '-m', 'tools.song_auto.run', *cmd[3:]]
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(r.stderr.strip(), 'synced lyrics: rows cannot be matched to known lyric text (80% exact tokens required)')

    def test_harness_even_real_process_restarts_and_refuses_bad_file(self):
        from song_auto_test import package, target
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pkg = package(root); lrc = root/'input.lrc'
            lrc.write_text('[00:00.20] ab-cd ef\n[00:01.50]')
            cmd = [sys.executable, '-B', '-m', 'tools.song_auto.bench.run', str(pkg), 'synced-even',
                   '--seed-target', str(pkg/'target.json'), '--scratch', str(root/'out'), '--synced-lyrics', str(lrc)]
            env = {**os.environ, **{k: str(root/k) for k in ('TORCH_HOME', 'HF_HOME', 'NUMBA_CACHE_DIR')}}
            outputs = []
            for _ in range(2):
                r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                outputs.append(Path(json.loads(r.stdout)['output']))
                score.validate(json.loads(outputs[-1].read_text()))
                provenance = json.loads((outputs[-1].parent/'provenance.json').read_text())
                self.assertIn(str(lrc), provenance['inputs'])
            self.assertNotEqual(*outputs)
            self.assertEqual(json.loads((pkg/'target.json').read_text()), target())
            lrc.write_text('[00:00] unrelated words')
            r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('rows cannot be matched', r.stderr)

    def test_both_commands_refuse_missing_rows_and_boundary_words_before_inference(self):
        from song_auto_test import package, target
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); pkg = package(root); lrc = root/'input.lrc'
            base = target()
            base['lyrics'] = [dict(a=.1, b=.9, words=[dict(w=f'w{i}', a=.1+i*.05, b=.14+i*.05)
                               for i in range(a, b)]) for a, b in ((0, 8), (8, 10))]
            (pkg/'target.json').write_text(json.dumps(base))
            texts = ['[00:00.10] w0 w1 w2 w3 w4 w5 w6 w7\n[00:01.20]',
                     '[00:00.10] w0 w1 w2 w3 w4 w5 w6 w7\n[00:01.20] w9']
            for text in texts:
                lrc.write_text(text)
                with patch.object(bench, 'align') as aligner, self.assertRaisesRegex(synced.AnchorError, 'unmatched words'):
                    run.place(pkg, base, base, 'cpu', synced_text=text)
                aligner.assert_not_called()
                for module, extra in [('tools.song_auto.run', ['--model-cache', str(root/'models')]),
                                      ('tools.song_auto.bench.run', ['mms', '--seed-target', str(pkg/'target.json')])]:
                    cmd = [sys.executable, '-B', '-m', module, str(pkg), *extra, '--scratch', str(root/'out'),
                           '--synced-lyrics', str(lrc)]
                    env = {**os.environ, **{k: str(root/k) for k in ('TORCH_HOME', 'HF_HOME', 'NUMBA_CACHE_DIR')}}
                    result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
                    with self.subTest(module=module, text=text):
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('unmatched words need anchors', result.stderr)
                        self.assertNotIn('w0', result.stdout + result.stderr)
                self.assertFalse(list((root/'out').glob('*/output.json')))

    def test_command_rejects_incompatible_refinement_before_work(self):
        for args in (['--word-refinement', 'boundary'], ['--download-models']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                run.main(['--synced-lyrics', 'synthetic.lrc', *args])
            self.assertEqual(error.exception.code, 2)
        for args in (['baseline', '--synced-lyrics', 'synthetic.lrc'],
                     ['synced-even'], ['baseline', '--ordered-words']):
            argv = ['bench', 'synthetic-package', *args, '--seed-target', 'synthetic.json', '--scratch', 'synthetic-output']
            with patch.object(sys, 'argv', argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                bench.main()
            self.assertEqual(error.exception.code, 2)


if __name__ == '__main__': unittest.main()
