#!/usr/bin/env python3
"""The pitch research tools: the frame cache's fingerprint and seed (tools/pitch_frames.py) and the metrics of
tools/pitch_quality.py on edge cases.

Runs on a synthetic two-second stem it generates itself; no song package from the operator's library. CREPE runs on
the CPU when there is no GPU (a few seconds for this stem).
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
sys.path.insert(0, str(ROOT / 'tools'))
import pitch_frames as pf
import pitch_quality as pq

SR = 44100
DURATION = 2.0


def make_package(root: Path, gain=.8, name='Synthetic') -> Path:
    pkg = root / name; pkg.mkdir()
    t = np.arange(int(SR * DURATION)) / SR
    y = .3 * np.sin(2 * np.pi * 220 * t * (1 + .01 * np.sin(2 * np.pi * 5 * t)))   # A3 with a little vibrato
    sf.write(pkg / pf.STEM, np.stack([y, y], 1).astype(np.float32), SR, subtype='PCM_16')
    (pkg / 'manifest.json').write_text(json.dumps({'audio': {'gain': gain}}), encoding='utf-8')
    return pkg


def write_target(pkg: Path, notes):
    ts = np.arange(0, DURATION, pq.HOP)
    points = [[round(float(t), 3), None, 0.0, False] for t in ts]
    (pkg / 'target.json').write_text(json.dumps({'id': 'x', 'duration': DURATION, 'notes': notes, 'points': points}), encoding='utf-8')


class EmptyNotes(unittest.TestCase):
    """A candidate pipeline that ships no notes is a regression to report, never a crash."""

    def test_note_metrics_without_notes(self):
        valid = np.zeros(100, bool)
        m = pq.note_metrics([], 2.0, valid)
        self.assertEqual(m['notes'], 0); self.assertEqual(m['ok_notes'], 0); self.assertEqual(m['sustained_notes_ge600ms'], 0)
        self.assertEqual(m['octave_jumps_adjacent'], 0); self.assertEqual(m['split_chains'], 0); self.assertEqual(m['pieces_in_chains'], 0)
        self.assertTrue(all(v == 0 for k, v in m.items() if k.startswith('gap_')))
        for k in ('ok_pct', 'note_med_dur_s', 'notes_under_150ms_pct', 'midi_p5', 'midi_p50', 'midi_p95'):
            self.assertIn(k, m); self.assertIsNone(m[k], k)
        json.dumps(m)   # the --json rows stay serialisable

    def test_note_metrics_from_points_without_notes(self):
        points = [[i * pq.HOP, None, 0.0, False] for i in range(100)]
        m = pq.note_metrics([], 2.0, points=points)
        self.assertEqual(m['notes'], 0); self.assertEqual(m['candidate_pct'], 0.0); self.assertEqual(m['comparable_pct'], 0.0)

    def test_package_mode_without_notes(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            pkg = make_package(tmp); write_target(pkg, [])
            t = np.arange(0, DURATION, .0116)
            P = np.stack([t, np.full_like(t, 220.0), np.full_like(t, .9), np.full_like(t, .1), np.full_like(t, 220.0)], 1)
            row = pq.run_package(pkg, {'P': P})
            self.assertEqual(row['notes'], 0); self.assertIsNone(row['midi_p50']); self.assertEqual(row['notes_compared_to_pyin'], 0)
            self.assertGreater(row['loud_frames_no_pitch'], 0)   # the loud stem with no pitch is what the row reports
        finally:
            shutil.rmtree(tmp)


class CacheFingerprint(unittest.TestCase):
    """A cache stands for one stem, gain, settings and seed. Anything else is refused or extracted again."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()); cls.pkg = make_package(cls.tmp); cls.out = cls.tmp / 'cache'
        write_target(cls.pkg, [])
        cls.dst = pf.extract(cls.pkg, cls.out, seed=0)
        cls.first = dict(np.load(cls.dst))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def fresh_copy(self, name):
        """A package and cache pair that a test may damage."""
        root = self.tmp / name; root.mkdir()
        pkg = root / self.pkg.name; shutil.copytree(self.pkg, pkg)
        cache = root / 'cache'; cache.mkdir(); shutil.copy(self.dst, cache / self.dst.name)
        return pkg, cache

    def test_meta_is_recorded(self):
        meta = pf.load(self.out, self.pkg)['meta']
        self.assertEqual(meta['seed'], 0); self.assertEqual(meta['settings'], pf.SETTINGS); self.assertEqual(meta['gain'], .8)
        self.assertEqual(meta['stem_sha256'], pf.stem_fingerprint(self.pkg)['stem_sha256'])

    def test_seed_controls_the_dither(self):
        again = dict(np.load(pf.extract(self.pkg, self.tmp / 'again', seed=0)))
        np.testing.assert_array_equal(again['f0'], self.first['f0'])
        np.testing.assert_array_equal(again['act'], self.first['act'])
        other = dict(np.load(pf.extract(self.pkg, self.tmp / 'other', seed=1)))
        self.assertGreater(np.abs(other['f0'] - self.first['f0']).max(), 0)   # the dither is real, and only the seed moved it

    def test_valid_cache_is_reused(self):
        pkg, cache = self.fresh_copy('reuse')
        before = (cache / self.dst.name).stat().st_mtime_ns
        pf.extract(pkg, cache, seed=0)
        self.assertEqual((cache / self.dst.name).stat().st_mtime_ns, before)

    def test_changed_stem_is_refused_and_re_extracted(self):
        pkg, cache = self.fresh_copy('stem')
        y, sr = sf.read(pkg / pf.STEM); sf.write(pkg / pf.STEM, y * .5, sr, subtype='PCM_16')
        with self.assertRaisesRegex(pf.CacheError, 'vocals_44k.flac changed'): pf.load(cache, pkg)
        with self.assertRaisesRegex(pf.CacheError, 'vocals_44k.flac changed'): pq.load_cache(cache, pkg)
        pf.extract(pkg, cache, seed=0)
        self.assertEqual(pf.load(cache, pkg)['meta']['stem_sha256'], pf.stem_fingerprint(pkg)['stem_sha256'])

    def test_changed_gain_is_refused(self):
        pkg, cache = self.fresh_copy('gain')
        (pkg / 'manifest.json').write_text(json.dumps({'audio': {'gain': .7}}), encoding='utf-8')
        with self.assertRaisesRegex(pf.CacheError, 'gain'): pf.load(cache, pkg)

    def test_changed_settings_or_seed_are_refused(self):
        meta = pf.read_meta(self.first)
        self.assertIsNone(pf.mismatch(meta, self.pkg))
        self.assertRegex(pf.mismatch({**meta, 'settings': {**pf.SETTINGS, 'format': 1}}, self.pkg), 'settings')
        self.assertRegex(pf.mismatch(meta, self.pkg, seed=1, check_seed=True), 'seed')

    def test_cache_without_meta_is_refused(self):
        pkg, cache = self.fresh_copy('legacy')
        legacy = {k: v for k, v in self.first.items() if k != 'meta'}; np.savez_compressed(cache / self.dst.name, **legacy)
        with self.assertRaisesRegex(pf.CacheError, 'no metadata'): pf.load(cache, pkg)

    def test_missing_cache(self):
        with self.assertRaisesRegex(pf.CacheError, 'no cache'): pf.load(self.tmp / 'nowhere', self.pkg)

    def test_rows_report_the_seed_behind_their_f0(self):
        c = pf.load(self.out, self.pkg)
        self.assertEqual(pq.run_song(self.pkg, c, 'baseline', False, seed=5)['seed'], 0)      # cached f0: the cache's seed
        self.assertEqual(pq.run_song(self.pkg, c, 'redecode', False, seed=5)['seed'], 5)      # re-decoded: the given seed


if __name__ == '__main__':
    unittest.main(verbosity=2)
