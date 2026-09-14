"""Playback stems at 44.1 kHz: the demo trainer's, the encoder's, and upgrade_audio rebuilding a prepared song in place.
Synthetic audio only; no Demucs and no network."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy import signal
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
import stems  # noqa: E402
import upgrade_audio  # noqa: E402
from build_html import build, embedded_song  # noqa: E402
from measure_audio import measure  # noqa: E402

SR = stems.SAMPLE_RATE


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tree(d):
    return {str(p.relative_to(d)): digest(p) for p in sorted(Path(d).rglob('*')) if p.is_file()}


def voice_and_band(seconds=8.0, seed=0):
    """Music-like test audio that an MP3 encoder can code as closely as a real song. The 'voice' sings random notes with
    vibrato and a little breath and air above 12 kHz, which keeps it aperiodic for the alignment; the 'band' is a held chord,
    a 15 kHz shimmer and hi-hat-like bursts of noise above 8 kHz."""
    rng = np.random.default_rng(seed); n = int(seconds * SR); t = np.arange(n) / SR
    syllable = .4 + .2 * seed; notes = rng.integers(57, 70, int(seconds / syllable) + 1)
    f0 = 440 * 2 ** ((notes[(t // syllable).astype(int)] - 69) / 12) * (1 + .006 * np.sin(2 * np.pi * 5.5 * t))
    phase = 2 * np.pi * np.cumsum(f0) / SR; envelope = np.sin(np.pi * (t % syllable) / syllable) ** 2
    noise = lambda kind, hz: signal.sosfilt(signal.butter(4, hz, kind, fs=SR, output='sos'), rng.standard_normal((n, 2)), axis=0)
    voice = envelope[:, None] * (sum(np.sin(k * phase)[:, None] / k for k in range(1, 7)) * .12 + .01 * noise('bandpass', [300, 3000]) + .004 * noise('highpass', 12000))
    chord = sum(np.sin(2 * np.pi * hz * t) for hz in (110, 164.8, 220, 277.2, 329.6)) * .03 * (1 + .2 * np.sin(2 * np.pi * .3 * t))
    hats = np.exp(-((t % .25) / .03))[:, None] * .03 * noise('highpass', 8000)
    band = (chord + .01 * np.sin(2 * np.pi * 15000 * t))[:, None] + hats
    return voice.astype(np.float32), band.astype(np.float32)


def library(root, lag=0, wrong_vocal=False, with_original=True):
    """A library with one song prepared the old way: 22 kHz 128 kb/s stems, the upload in inbox/, a trainer next to it."""
    lib = Path(root) / 'songs'; pkg = lib / 'Song'; (pkg / 'lyrics').mkdir(parents=True); (lib / 'inbox').mkdir()
    voice, band = voice_and_band(); mix = voice + band
    upload = lib / 'inbox' / '0f00_Song - Band.flac'
    padded = np.concatenate([np.zeros((max(lag, 0), 2), np.float32), mix])[max(-lag, 0):]
    sf.write(upload, padded, SR, subtype='PCM_24'); sha = digest(upload)
    sf.write(pkg / 'vocals_44k.flac', voice_and_band(seed=1)[0] if wrong_vocal else voice, SR, subtype='PCM_24')
    duration = len(mix) / SR
    song = {'schema': 'luma.song.v1', 'title': 'Song', 'artist': 'Band', 'duration': duration, 'a4': 440, 'hop': .02, 'points': [], 'phrases': [],
            'notes': [{'id': 0, 'a': 1.0, 'b': 2.0, 'm': 69.0, 'n': 69, 'q': .9, 'ok': True, 'ignored': False}],
            'lyrics': [{'a': 1.0, 'b': 2.0, 'words': [{'a': 1.0, 'b': 2.0, 'w': 'la', 'c': .9}]}], 'sourceId': sha, 'id': 'abcdef0123456789abcd'}
    (pkg / 'target.json').write_text(json.dumps(song, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (pkg / 'lyrics' / 'vocal.json').write_text('{"note":"transcript","lines":[]}', encoding='utf-8')
    (pkg / 'manifest.json').write_text(json.dumps({'source': str(Path(root) / 'elsewhere' / 'Song - Band.flac'), 'source_sha256': sha}), encoding='utf-8')
    gain = stems.joint_gain(voice, band)
    for role, x in (('foreground', voice), ('backing', band)):
        sf.write(pkg / f'{role}.wav', x * gain, SR, subtype='FLOAT')
        for speed, suffix in ((1, ''), (.8, '_80')):
            stems.ffmpeg('-i', pkg / f'{role}.wav', '-af', f'atempo={speed},apad,atrim=duration={duration / speed:.9f}', '-ar', '22050',
                         '-c:a', 'libmp3lame', '-b:a', '128k', '-write_xing', '1', pkg / f'{role}{suffix}.mp3')
        (pkg / f'{role}.wav').unlink()
    if not with_original: upload.unlink()
    build(pkg, lib / 'Luma_Song.html')
    return lib, pkg, upload, band * gain


def error_db(decoded, reference):
    """How far a decoded stem is from the exact signal on the same timeline, in dB below it."""
    n = min(len(decoded), len(reference)); d = decoded[:n].astype(np.float64); r = reference[:n].astype(np.float64)
    return 10 * np.log10(np.sum((d - r) ** 2) / np.sum(r ** 2))


class DemoStemsTest(unittest.TestCase):
    def test_demo_trainer_plays_44k_stereo_stems(self):
        demo = ROOT / 'examples' / 'demo'
        if not (demo / 'Demo' / 'target.json').is_file():
            subprocess.run([sys.executable, str(ROOT / 'examples' / 'make_demo.py')], check=True, capture_output=True)
        for name in stems.FILES:
            p = stems.probe(demo / 'Demo' / name)
            self.assertEqual((p['codec'], p['sample_rate'], p['channels']), ('mp3', SR, 2), name)
        page = (demo / 'Luma_Demo.html').read_text(encoding='utf-8')
        start = page.index(';window.LUMA_ASSETS=') + len(';window.LUMA_ASSETS=')
        assets = json.loads(page[start:page.index(';</script>', start)])
        with tempfile.TemporaryDirectory() as tmp:
            for speed, pair in assets.items():
                for role, data in pair.items():
                    f = Path(tmp) / f'{role}_{speed}.mp3'; f.write_bytes(base64.b64decode(data))
                    self.assertEqual(stems.probe(f)['sample_rate'], SR, f'{role} at {speed}x as embedded in the trainer')


class EncoderTest(unittest.TestCase):
    def test_both_speeds_are_44k_equal_length_and_keep_the_top_octave(self):
        voice, band = voice_and_band(4.0)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); sf.write(tmp / 'f.wav', voice, SR, subtype='FLOAT'); sf.write(tmp / 'b.wav', band, SR, subtype='FLOAT')
            stems.encode({'foreground': tmp / 'f.wav', 'backing': tmp / 'b.wav'}, 4.0, tmp)
            for speed, suffix, _ in stems.SPEEDS:
                for role in stems.ROLES:
                    p = stems.probe(tmp / f'{role}{suffix}.mp3')
                    self.assertEqual((p['sample_rate'], p['channels']), (SR, 2), f'{role} {speed}x')
                    self.assertAlmostEqual(p['duration'], 4.0 / speed, delta=.03, msg=f'{role} {speed}x')
            f, p = signal.welch(stems.decode(tmp / 'backing.mp3'), SR, nperseg=4096, axis=0); f0, p0 = signal.welch(band, SR, nperseg=4096, axis=0)
            self.assertGreater(10 * np.log10(p[f > 11000].sum() / p0[f0 > 11000].sum()), -3, 'energy above 11 kHz survives the encoder')


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='luma-upgrade-'); self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('upgrade_audio must not touch the network'))
        network.start(); self.addCleanup(network.stop)

    def test_dry_run_reports_the_source_and_writes_nothing(self):
        lib, pkg, _, _ = library(self.root); before = tree(lib)
        r = upgrade_audio.upgrade(pkg, dry_run=True)
        self.assertEqual((r['source'], r['found_in'], r['alignment']['lag'], r['alignment']['ok']), ('original', 'inbox', 0, True), r)
        self.assertEqual(r['before']['sample_rates'], [22050])
        self.assertEqual(tree(lib), before)

    def test_upgrade_rebuilds_the_audio_and_keeps_what_the_history_needs(self):
        lib, pkg, upload, backing = library(self.root); html = lib / 'Luma_Song.html'
        kept = {n: digest(pkg / n) for n in ('target.json', 'lyrics/vocal.json', 'vocals_44k.flac')}; song_text = embedded_song(html); page = html.read_text()
        old = measure(pkg)
        self.assertLess(old['bands']['above_11k']['relative_db'], -20, 'the old stems really lack the top octave')
        r = upgrade_audio.upgrade(pkg)
        self.assertEqual((r['source'], r['checks']['kept_files_identical'], r['checks']['song_data_identical']), ('original', True, True), r)
        for name in stems.FILES:
            p = stems.probe(pkg / name); self.assertEqual((p['codec'], p['sample_rate'], p['channels']), ('mp3', SR, 2), name)
        self.assertEqual({n: digest(pkg / n) for n in kept}, kept, 'notes, lyrics and the analysis stem stay byte-identical')
        self.assertEqual(embedded_song(html), song_text, 'the song data inside the trainer is the same text')
        self.assertEqual([p.name for p in lib.glob('Luma_*')], ['Luma_Song.html'])
        self.assertNotEqual(html.read_text(), page)
        self.assertEqual(digest(pkg / 'original.flac'), digest(upload), 'the upload is kept in the package')
        self.assertEqual(sorted(p.name for p in pkg.iterdir() if p.name.startswith('.')), [], 'no scratch directory left behind')
        new = measure(pkg)
        self.assertGreater(new['bands']['above_11k']['relative_db'], -3)
        self.assertLess(new['null_db'], -25)
        self.assertLess(error_db(stems.decode(pkg / 'backing.mp3'), backing), -20, 'backing alone is the band without the voice')
        self.assertEqual(upgrade_audio.upgrade(pkg, dry_run=True)['source'], 'current')

    def test_a_constant_offset_is_measured_and_corrected(self):
        lib, pkg, _, backing = library(self.root, lag=300)
        r = upgrade_audio.upgrade(pkg)
        self.assertEqual((r['source'], r['alignment']['lag']), ('original', 300), r)
        self.assertLess(error_db(stems.decode(pkg / 'backing.mp3'), backing), -20, 'the voice cancels on the song timeline')

    def test_a_vocal_that_does_not_line_up_needs_demucs_and_no_original_leaves_the_song_alone(self):
        lib, pkg, _, _ = library(self.root / 'a', wrong_vocal=True); before = tree(lib)
        self.assertEqual(upgrade_audio.upgrade(pkg, dry_run=True)['source'], 'demucs')
        self.assertIn('skipped', upgrade_audio.upgrade(pkg, allow_demucs=False))
        self.assertEqual(tree(lib), before)
        lib, pkg, _, _ = library(self.root / 'b', with_original=False); before = tree(lib)
        self.assertEqual(upgrade_audio.upgrade(pkg)['source'], 'none')
        self.assertEqual(tree(lib), before)


if __name__ == '__main__':
    unittest.main()
