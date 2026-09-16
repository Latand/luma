#!/usr/bin/env python3
"""retranscribe_song.py's correction replay: a cached, passing lyrics correction must survive a fresh
transcription (round 2, finding 3). Uses a pre-populated Soniox response cache and --cache-only, so no network call
and no payment happen.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
sys.path.insert(0, str(ROOT / 'tests'))
import align_lyrics as al
import retranscribe_song as rt
from lyrics_align_test import synthetic_package, TEXT


class RetranscribeCorrectionReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='luma-retranscribe-')
        self.pkg = synthetic_package(Path(self.directory))
        stem_sha = __import__('prepare_song').sha256(self.pkg / 'vocals_44k.flac')
        tokens = [{'text': w if i == 0 else ' ' + w, 'start_ms': int(a * 1000), 'end_ms': int((a + .3) * 1000), 'confidence': .9}
                   for i, (w, a) in enumerate(zip(['one', 'two', 'THREE', 'four', 'five', 'six.'],
                                                   [.5, 1.3, 3.2, 3.9, 5.0, 6.5]))]
        payload = {'model': 'stt-async-v5', 'language': 'en', 'audio': 'test', 'stem_sha256': stem_sha,
                   'audio_sha256': 'x', 'created': '2026-09-16T00:00:00', 'seconds': 1.0, 'tokens': tokens}
        (self.pkg / 'lyrics').mkdir(exist_ok=True)
        (self.pkg / 'lyrics' / f'soniox-{stem_sha[:16]}.json').write_text(json.dumps(payload), encoding='utf-8')

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _cache_source(self, text):
        d = self.pkg / 'lyrics'; d.mkdir(exist_ok=True)
        (d / 'source.txt').write_text(text, encoding='utf-8')
        (d / 'source.meta.json').write_text(json.dumps({'title': '', 'artist': ''}), encoding='utf-8')

    def test_retranscribe_keeps_a_correction_that_passes(self):
        self._cache_source('one two THREE-CORRECTED four five six')
        out = rt.retranscribe(self.pkg, 'en', cache_only=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        words = [w['w'] for w in al.flat(after['lyrics'])]
        self.assertIn('THREE-CORRECTED', words)
        self.assertIn('corrected to published lyrics', after['lyricsSource'])

    def test_retranscribe_ignores_a_correction_that_fails_the_gate(self):
        self._cache_source('completely unrelated nonsense words sharing nothing with this transcript at all here')
        rt.retranscribe(self.pkg, 'en', cache_only=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        words = [w['w'] for w in al.flat(after['lyrics'])]
        self.assertEqual(words, ['one', 'two', 'THREE', 'four', 'five', 'six.'], 'a refused correction must not reach the fresh transcript')

    def test_retranscribe_without_a_correction_uses_the_fresh_transcript(self):
        out = rt.retranscribe(self.pkg, 'en', cache_only=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        words = [w['w'] for w in al.flat(after['lyrics'])]
        self.assertEqual(words, ['one', 'two', 'THREE', 'four', 'five', 'six.'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
