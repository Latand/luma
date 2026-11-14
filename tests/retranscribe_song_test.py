#!/usr/bin/env python3
"""retranscribe_song.py's correction replay: a cached, passing lyrics correction must survive a fresh
transcription (round 2, finding 3). Uses a pre-populated Soniox response cache and --cache-only, so no network call
and no payment happen.
"""
import json
import shutil
import subprocess
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
from lyrics_synced_test import phrase_identity_fixture, synthetic_package as timed_package
from prepare_song import sha256


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
        self.assertEqual(out['correction'], 'applied', "the result must say so, not just leave it to be inferred from the words")

    def test_retranscribe_ignores_a_correction_that_fails_the_gate(self):
        self._cache_source('completely unrelated nonsense words sharing nothing with this transcript at all here')
        out = rt.retranscribe(self.pkg, 'en', cache_only=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        words = [w['w'] for w in al.flat(after['lyrics'])]
        self.assertEqual(words, ['one', 'two', 'THREE', 'four', 'five', 'six.'], 'a refused correction must not reach the fresh transcript')
        self.assertTrue(out['correction'] and out['correction'].startswith('refused'), "the result must say why, not just leave the words to speak for it")

    def test_retranscribe_without_a_correction_uses_the_fresh_transcript(self):
        out = rt.retranscribe(self.pkg, 'en', cache_only=True, rebuild=False)
        after = json.loads((self.pkg / 'target.json').read_text(encoding='utf-8'))
        words = [w['w'] for w in al.flat(after['lyrics'])]
        self.assertEqual(words, ['one', 'two', 'THREE', 'four', 'five', 'six.'])
        self.assertIsNone(out['correction'], "with no cached source, the result must say there was no correction, not omit the key")


class SyncedRetranscriptionCliTests(unittest.TestCase):
    def test_cache_only_refusal_preserves_existing_and_absent_transcripts(self):
        for kind in ['repeat', 'short2']:
            for vocal_exists in [False, True]:
                for mix_exists in [False, True]:
                    with self.subTest(kind=kind, vocal_exists=vocal_exists, mix_exists=mix_exists):
                        self.check_cli(kind, vocal_exists, mix_exists, shift=-4.)

    def test_cache_only_valid_control_saves_transcripts_and_corrected_words(self):
        for kind in ['repeat', 'short2']:
            with self.subTest(kind=kind):
                self.check_cli(kind, False, False, shift=0.)

    def check_cli(self, kind, vocal_exists, mix_exists, shift):
        _, words, song, text, lrc = phrase_identity_fixture(kind, 'pitch', shift=shift)
        words = [dict(w, a=w['a'] + .6, b=w['b'] + .6) for w in words]
        with tempfile.TemporaryDirectory() as tmp:
            pkg = timed_package(Path(tmp), bursts=[(i * 10 + 1., i * 10 + 3.) for i in range(12)],
                                asr_words=['flim'] * 12, duration=120.)
            target = json.loads((pkg / 'target.json').read_text())
            target['lyrics'] = song['lyrics']
            target['lyricsSource'] = 'synthetic mix transcript'
            (pkg / 'target.json').write_text(json.dumps(target))
            mix = pkg / 'lyrics/mix.json'
            if mix_exists:
                mix.write_text(json.dumps({'source': 'mix', 'lines': song['lyrics']}))
            else:
                mix.unlink(missing_ok=True)
            vocal = pkg / 'lyrics/vocal.json'
            if vocal_exists:
                vocal.write_text(json.dumps({'source': 'old vocal', 'lines': song['lyrics']}))
            else:
                vocal.unlink(missing_ok=True)
            (pkg / 'lyrics/source.txt').write_text(text)
            (pkg / 'lyrics/source.meta.json').write_text(json.dumps({
                'title': target['title'], 'artist': target['artist'], 'synced_lrc': lrc}))
            tokens = [{'text': (' ' if i else '') + w['w'], 'start_ms': round(w['a'] * 1000),
                       'end_ms': round(w['b'] * 1000), 'confidence': .9} for i, w in enumerate(words)]
            payload = {'model': 'stt-async-v5', 'created': '2026-01-01T00:00:00', 'tokens': tokens}
            (pkg / 'lyrics' / f'soniox-{sha256(pkg / "vocals_44k.flac")[:16]}.json').write_text(json.dumps(payload))
            def snapshot():
                return {str(p.relative_to(pkg)): p.read_bytes() for p in pkg.rglob('*') if p.is_file()}
            before = snapshot()
            command = [sys.executable, str(ROOT / 'studio/retranscribe_song.py'), '--cache-only', '--no-html', str(pkg)]
            for _ in range(2):  # Restart the actual consumer; no in-memory state may mask a write.
                result = subprocess.run(command, capture_output=True, timeout=90)
                if shift:
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertRegex(result.stderr.decode(), r'line 6 at 47.00s: .*contradicts.*51.60s')
                    self.assertEqual(snapshot(), before)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('"correction": "applied"', result.stdout.decode())
                    saved = json.loads((pkg / 'target.json').read_text())
                    self.assertEqual([w['w'] for w in al.flat(saved['lyrics'])], text.split())
                    self.assertTrue(mix.exists())
                    self.assertTrue(vocal.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
