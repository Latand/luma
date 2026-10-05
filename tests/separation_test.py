"""Separation of long songs in windows and the song-length bound. A stand-in for Demucs; no weights, no GPU."""
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
import prepare_song  # noqa: E402

SR = 44100


def fake_demucs(corrupt_edges_s=0.0):
    """demucs.pretrained / demucs.apply with a 'model' whose vocal is half of its input, sample by sample. With
    `corrupt_edges_s`, the first and last seconds of every run come out as garbage, as a window edge might."""
    model = types.SimpleNamespace(sources=['drums', 'bass', 'other', 'vocals'], samplerate=SR, eval=lambda: model)
    runs = []
    def apply_model(m, mix, **kw):
        runs.append(mix.shape[-1]); v = mix[0] * .5
        e = int(corrupt_edges_s * SR)
        if e: v = v.clone(); v[:, :e] = 1e3; v[:, -e:] = -1e3
        return torch.stack([torch.zeros_like(v)] * 3 + [v])[None]
    return {'demucs': types.ModuleType('demucs'), 'demucs.pretrained': types.SimpleNamespace(get_model=lambda name: model),
            'demucs.apply': types.SimpleNamespace(apply_model=apply_model)}, runs


class WindowsTest(unittest.TestCase):
    def test_short_songs_are_one_window_and_long_ones_share_the_song_evenly(self):
        for seconds, windows in ((1, 1), (299.9, 1), (300, 1), (300.1, 2), (608, 3), (1800, 6), (2400, 8)):
            n = int(seconds * SR); got = prepare_song.separation_windows(n, SR)
            self.assertEqual(len(got), windows, seconds)
            self.assertEqual((got[0][0], got[-1][1]), (0, n))
            if windows == 1: self.assertTrue(np.all(got[0][2] == 1))

    def test_weights_add_up_to_one_and_every_weighted_frame_has_context(self):
        n = int(608.3 * SR); total = np.zeros(n); context = prepare_song.SEPARATION_CONTEXT_S * SR
        for lo, hi, w in prepare_song.separation_windows(n, SR):
            self.assertEqual(len(w), hi - lo); total[lo:hi] += w
            used = np.flatnonzero(w > 0) + lo
            if lo: self.assertGreaterEqual(used[0] - lo, context)
            if hi < n: self.assertGreaterEqual(hi - 1 - used[-1], context)
        np.testing.assert_allclose(total, 1, atol=1e-6)


class SeparateTest(unittest.TestCase):
    def run_separate(self, seconds, corrupt_edges_s=0.0):
        rng = np.random.default_rng(1); x = (rng.standard_normal((int(seconds * SR), 2)) * .1 + .01).astype(np.float32)
        modules, runs = fake_demucs(corrupt_edges_s)
        with patch.dict(sys.modules, modules): vocal, report = prepare_song.separate(x, device='cpu')
        return x, vocal, report, runs

    def test_a_long_song_is_stitched_back_to_what_one_run_would_give(self):
        x, vocal, report, runs = self.run_separate(610, corrupt_edges_s=prepare_song.SEPARATION_CONTEXT_S - .5)
        self.assertEqual((vocal.shape, vocal.dtype, report['windows'], len(runs)), (x.shape, np.float32, 3, 3))
        self.assertLessEqual(max(runs), (610 / 3 + prepare_song.SEPARATION_FADE_S + 2 * prepare_song.SEPARATION_CONTEXT_S) * SR, 'no run hears the whole song')
        mu = x.mean(1).mean(); inner = slice(8 * SR, -8 * SR)  # the song's own two ends are corrupted by the stand-in, as they would be in one run
        np.testing.assert_allclose(vocal[inner], (.5 * (x - mu) + mu)[inner], atol=2e-6)

    def test_a_short_song_is_one_run_as_before(self):
        x, vocal, report, runs = self.run_separate(20)
        self.assertEqual((report['windows'], runs), (1, [len(x)]))
        np.testing.assert_allclose(vocal, .5 * (x - x.mean(1).mean()) + x.mean(1).mean(), atol=2e-6)


class DurationBoundTest(unittest.TestCase):
    def test_bound_covers_half_an_hour_and_speaks_ukrainian(self):
        self.assertGreaterEqual(prepare_song.MAX_SECONDS, 30 * 60)
        for ok in (1, 608, 1800, prepare_song.MAX_SECONDS): self.assertIsNone(prepare_song.duration_limit_error(ok), ok)
        self.assertEqual(prepare_song.duration_limit_error(2527.4), 'Пісня триває 42 хв 7 с. Luma Studio готує пісні від 1 секунди до 40 хвилин: '
                         'довший тренажер був би завеликим для браузера. Обріж файл або розділи його на частини.')
        self.assertIn('0 хв 0 с', prepare_song.duration_limit_error(.4))

    def test_an_overlong_file_is_refused_before_it_is_decoded(self):
        with tempfile.TemporaryDirectory(prefix='luma-long-') as d:
            src = Path(d) / 'long.flac'
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', f'anullsrc=r=8000:cl=mono', '-t', str(prepare_song.MAX_SECONDS + 60), str(src)], check=True)
            run = subprocess.run([sys.executable, str(ROOT / 'studio' / 'prepare_song.py'), str(src), '--title', 'Long', '--out', d, '--no-lyrics'], capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 1, run.stderr)
            self.assertIn('Пісня триває 41 хв 0 с. Luma Studio готує пісні від 1 секунди до 40 хвилин', run.stderr)
            self.assertFalse((Path(d) / 'Long' / 'work' / 'mix.wav').exists(), 'nothing was decoded')


if __name__ == '__main__':
    unittest.main()
