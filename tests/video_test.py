"""Camera videos (studio/video.py): alignment through Opus, the size budget and its eviction order, the render deadline
that ends the browser's whole process group, and the ffmpeg graph on synthetic inputs. No browser, no network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
import video  # noqa: E402
SR = video.SR
FF = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']


def bursts(seconds: float, seed: int = 7) -> np.ndarray:
    """Noise bursts of random length and level with random gaps: nothing in it repeats."""
    rng = np.random.default_rng(seed); n = int(seconds * SR); x = np.zeros(n); i = 0
    while i < n:
        i += int(rng.uniform(.05, .4) * SR); k = int(rng.uniform(.05, .3) * SR)
        if i + k > n: break
        x[i:i + k] = rng.standard_normal(k) * rng.uniform(.05, .3); i += k
    return x


def beeps(seconds: float) -> np.ndarray:
    """The same 200 ms tone every second: a periodic signal, like Chrome's own fake microphone."""
    t = np.arange(int(seconds * SR)) / SR; return np.where((t % 1) < .2, .3 * np.sin(2 * np.pi * 440 * t), 0)


def webm(path: Path, audio: np.ndarray, seconds: float):
    """A camera-like webm: VP8 test pattern + the given audio as Opus, as MediaRecorder writes it."""
    wav = path.with_suffix('.src.wav'); sf.write(wav, audio.astype(np.float32), SR)
    subprocess.run([*FF, '-f', 'lavfi', '-i', f'testsrc2=s=320x240:r=30:d={seconds}', '-i', str(wav), '-shortest', '-c:v', 'libvpx', '-b:v', '300k', '-c:a', 'libopus', '-b:a', '128k', str(path)], check=True)
    wav.unlink()


class Alignment(unittest.TestCase):
    def setUp(self): self.tmp = Path(tempfile.mkdtemp(prefix='luma-video-test-'))
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def place(self, mic: np.ndarray, off: float, lag: float = .1):
        """The microphone on the AudioContext clock; the webm starts at stamp + 18 ms + off, the attempt's WAV at when + lag."""
        stamp, when = 1.0, 3.1; w0 = stamp + video.STAMP + off
        path = self.tmp / f'cam{off}.webm'; webm(path, mic[int(round(w0 * SR)):int(round((w0 + 14) * SR))], 14)
        a0, _ = video.starts(path); pcm = video.decode(path)
        wav = mic[int(round((when + lag) * SR)):int(round((when + lag + 9) * SR))]
        seg = {'when': when, 'latency': lag * 1000}
        return video.align(pcm, a0, [wav], [seg], stamp), w0

    def test_recovers_known_offsets_through_opus(self):
        mic = bursts(30)
        for off in (-.4, -.25, -.1, 0, .05):
            al, w0 = self.place(mic, off)
            self.assertFalse(al['approximateSync'], (off, al))
            self.assertGreaterEqual(al['peak'], .5)
            self.assertLess(abs(al['W0'] - w0), .001, f'offset {off * 1000:+.0f} ms: W0 off by {(al["W0"] - w0) * 1000:.2f} ms')

    def test_webm_that_stops_before_the_wav_ends(self):
        # the recorder stops with the attempt, so its last chunk can end a few ms before the WAV does
        mic = bursts(30, seed=5); stamp, when, lag = 1.0, 3.1, .05; w0 = stamp + video.STAMP + .02
        wav = mic[int(round((when + lag) * SR)):int(round((when + lag + 4) * SR))]
        path = self.tmp / 'short.webm'; webm(path, mic[int(round(w0 * SR)):int(round((when + lag + 4 - .03) * SR))], 6.1)
        a0, _ = video.starts(path); al = video.align(video.decode(path), a0, [wav], [{'when': when, 'latency': lag * 1000}], stamp)
        self.assertFalse(al['approximateSync'], al); self.assertLess(abs(al['W0'] - w0), .001, al)

    def test_periodic_signal_falls_back_to_the_stamp(self):
        al, _ = self.place(beeps(30), .02)
        self.assertTrue(al['approximateSync'], al); self.assertAlmostEqual(al['W0'], 1.0 + video.STAMP, places=6)
        self.assertGreaterEqual(al['second'], .7 * al['peak'])

    def test_silence_falls_back_to_the_stamp(self):
        al, _ = self.place(np.zeros(30 * SR), 0)
        self.assertTrue(al['approximateSync']); self.assertAlmostEqual(al['W0'], 1.0 + video.STAMP, places=6)

    def test_segments_report_their_spread(self):
        mic = bursts(40, seed=3); stamp = 1.0; w0 = stamp + video.STAMP + .012
        path = self.tmp / 'multi.webm'; webm(path, mic[int(w0 * SR):int((w0 + 30) * SR)], 30)
        a0, _ = video.starts(path); pcm = video.decode(path); segs = [{'when': 3.1, 'latency': 50}, {'when': 15.4, 'latency': 50}]
        wavs = [mic[int(round((s['when'] + .05) * SR)):int(round((s['when'] + .05 + 8) * SR))] for s in segs]
        al = video.align(pcm, a0, wavs, segs, stamp)
        self.assertFalse(al['approximateSync']); self.assertEqual(len(al['residuals']), 2); self.assertLessEqual(al['spread'], .001, al)


def take_record(vid: str, started: str, segments=None) -> dict:
    segs = segments or [{'k': 0, 'runId': 'r', 'when': 10.0, 'cin': 7.9, 'stop': 50.0, 'a': 0, 'b': 40, 'endSong': 40, 'speed': 1, 'latency': 0, 'history': {}, 'lives': None, 'dust': []}]
    return {'v': 1, 'id': vid, 'trainer': 'Luma_Fixture.html', 'title': 'Fixture', 'startedAt': started, 'ctxAtStart': 7.8, 'back': .75, 'segments': segs, 'dust': {}}


def fake_video(store: video.Videos, n: int, started: str, size: int, ready=True, take=True, age=0.0) -> str:
    vid = f'{n:08x}-0000-4000-8000-000000000000'; d = store.dir / vid; d.mkdir(parents=True)
    if take: (d / 'take.json').write_text(json.dumps(take_record(vid, started)))
    (d / ('video.mp4' if ready else 'camera.webm')).write_bytes(b'\0' * size)
    if age:
        t = time.time() - age
        for f in [*d.iterdir(), d]: os.utime(f, (t, t))
    return vid


class Budget(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='luma-video-test-')); self.store = video.Videos(self.tmp, ROOT, budget=10 << 20)
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def test_size_counts_the_stems_cache(self):
        fake_video(self.store, 1, '2026-10-01T10:00:00Z', 1 << 20)
        self.store.stems.mkdir(); (self.store.stems / 'x_1.mp3').write_bytes(b'\0' * (3 << 20))
        self.assertGreaterEqual(self.store.listing()['used'], 4 << 20)

    def test_oldest_first_and_never_the_protected_ones(self):
        mb = 1 << 20; s = self.store
        stale = fake_video(s, 1, '', mb, ready=False, take=False, age=2 * video.STALE)
        old = fake_video(s, 2, '2026-10-01T10:00:00Z', 3 * mb)
        mid = fake_video(s, 3, '2026-10-02T10:00:00Z', 3 * mb)
        composing = fake_video(s, 4, '2026-09-01T10:00:00Z', 3 * mb, ready=False)   # oldest of all, but being composed
        recording = fake_video(s, 5, '', 3 * mb, ready=False, take=False)            # a sitting still being filmed
        newest = fake_video(s, 6, '2026-10-03T10:00:00Z', 3 * mb)
        s.current = composing; gone = s.evict()
        self.assertEqual(gone[:2], [stale, old], gone)                               # the stale folder first, then the oldest
        self.assertNotIn(composing, gone); self.assertNotIn(recording, gone); self.assertNotIn(newest, gone)
        left = {d.name for d in s.dir.iterdir() if d.name != '.stems'}
        self.assertTrue({composing, recording, newest} <= left)
        self.assertEqual(gone, [stale, old, mid])                                     # until it fits: 3 + 3 + 3 MiB over 10
        self.assertLessEqual(s.listing()['used'], s.budget)

    def test_listing_measures_a_finished_folder_once(self):
        # Studio's page polls /videos: a ready video is walked once; one still recording is measured on every poll
        s = self.store; ready = fake_video(s, 1, '2026-10-01T10:00:00Z', 1 << 20); rec = fake_video(s, 2, '', 1000, ready=False, take=False)
        walked = []; real = video.folder_bytes
        video.folder_bytes = lambda d: walked.append(Path(d).name) or real(d)
        try:
            first = s.listing(); second = s.listing()
            with open(s.dir / rec / 'camera.webm', 'ab') as f: f.write(b'\0' * 500)   # the camera chunks keep coming
            third = s.listing()
        finally: video.folder_bytes = real
        self.assertEqual(walked.count(ready), 1, walked); self.assertEqual(walked.count(rec), 3, walked)
        self.assertEqual(first, second); self.assertEqual(third['used'], first['used'] + 500)
        shutil.rmtree(s.dir / ready); after = s.listing()                             # a deleted folder leaves no row behind
        self.assertEqual([v['id'] for v in after['videos']], [rec]); self.assertNotIn(ready, s.rows)

    def test_newest_ready_survives_even_over_budget(self):
        only = fake_video(self.store, 7, '2026-10-05T10:00:00Z', 12 << 20)
        self.assertEqual(self.store.evict(), []); self.assertTrue((self.store.dir / only).is_dir())


STUB = """#!/bin/sh
# a browser that never renders: it starts a child and waits for it, so ending the leader alone would leave the child
sleep 600 &
echo $! > "{child}"
echo $$ > "{leader}"
wait
"""


class RenderDeadline(unittest.TestCase):
    def setUp(self): self.tmp = Path(tempfile.mkdtemp(prefix='luma-video-test-'))
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stub_browser_is_ended_by_its_process_group(self):
        stub = self.tmp / 'stub-browser'; child, leader = self.tmp / 'child.pid', self.tmp / 'leader.pid'
        stub.write_text(STUB.format(child=child, leader=leader)); stub.chmod(0o755)
        store = video.Videos(self.tmp, ROOT, base='http://127.0.0.1:9', deadline_factor=0, deadline_extra=1.5, browser=str(stub))
        vid = '00000001-0000-4000-8000-000000000000'; (store.dir / vid).mkdir(parents=True); store.current = vid
        t0 = time.time()
        with self.assertRaises(video.Failed) as e: store.render(vid, 10)
        self.assertIn('не встиг', str(e.exception)); self.assertLess(time.time() - t0, 12)
        pids = [int(child.read_text()), int(leader.read_text())]
        time.sleep(.2)
        for pid in pids: self.assertFalse(Path(f'/proc/{pid}').exists() and 'Z' not in Path(f'/proc/{pid}/stat').read_text().split()[2], f'pid {pid} outlived the deadline')
        self.assertFalse((store.dir / vid / '.profile').exists())

    def test_failed_render_marks_the_video_failed(self):
        stub = self.tmp / 'stub-browser'; stub.write_text(STUB.format(child=self.tmp / 'c', leader=self.tmp / 'l')); stub.chmod(0o755)
        store = video.Videos(self.tmp, ROOT, deadline_factor=0, deadline_extra=1, browser=str(stub))
        vid = '00000002-0000-4000-8000-000000000000'; d = store.dir / vid; d.mkdir(parents=True)
        mic = bursts(12); webm(d / 'camera.webm', mic, 8); sf.write(d / 'voice-0.wav', mic[SR:5 * SR].astype(np.float32), SR)
        (d / 'take.json').write_text(json.dumps(take_record(vid, '2026-10-01T10:00:00Z', [{'k': 0, 'runId': 'r', 'when': 2.0, 'cin': 0, 'stop': 6.0, 'a': 0, 'b': 4, 'endSong': 4, 'speed': 1, 'latency': 0, 'history': {}, 'lives': None, 'dust': []}])))
        store.start(); end = time.time() + 20
        while time.time() < end and store.listing()['videos'][0]['state'] != 'failed': time.sleep(.2)
        item = store.listing()['videos'][0]; self.assertEqual(item['state'], 'failed', item); self.assertIn('не встиг', item['error'])
        self.assertTrue((d / 'camera.webm').exists() and not (d / '.profile').exists())

    def test_restart_requeues_with_a_stems_cache_present(self):
        store = video.Videos(self.tmp, ROOT, browser='/nonexistent'); store.stems.mkdir(parents=True); (store.stems / 'x_1.mp3').write_bytes(b'0')
        vid = '00000003-0000-4000-8000-000000000000'; (store.dir / vid).mkdir(); (store.dir / vid / 'take.json').write_text(json.dumps(take_record(vid, '2026-10-01T10:00:00Z')))
        store.start(); end = time.time() + 10
        while time.time() < end and store.listing()['videos'][0]['state'] != 'failed': time.sleep(.1)
        self.assertEqual(store.listing()['videos'][0]['state'], 'failed')   # requeued at start, then refused: no camera


class Compose(unittest.TestCase):
    def setUp(self): self.tmp = Path(tempfile.mkdtemp(prefix='luma-video-test-'))
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def test_graph_places_every_voice_and_instrumental_piece(self):
        t = self.tmp; game = t / 'game.h264'; cam = t / 'camera.webm'; stem = t / 'stem.mp3'
        subprocess.run([*FF, '-f', 'lavfi', '-i', 'color=c=0x0e131c:s=1920x1080:r=30:d=3.2', '-c:v', 'libx264', '-preset', 'ultrafast', '-f', 'h264', str(game)], check=True)
        webm(cam, np.zeros(6 * SR), 6)
        click = lambda n, at: np.where(np.arange(n) == int(at * SR), 0.9, 0.0)
        sf.write(t / 'voice-0.wav', click(int(1.5 * SR), .1), SR); sf.write(t / 'voice-1.wav', click(SR, .3), SR)
        sf.write(t / 'stem.wav', np.zeros(20 * SR), SR); subprocess.run([*FF, '-i', str(t / 'stem.wav'), '-c:a', 'libmp3lame', '-b:a', '128k', str(stem)], check=True)
        segs = [{'when': 10.0, 'stop': 11.5, 'a': 2.0, 'speed': 1, 'latency': 0}, {'when': 12.0, 'stop': 13.0, 'a': 5.0, 'speed': 1, 'latency': 0}]
        take = {'segments': segs, 'back': .75}; out = t / 'out.mp4'
        subprocess.run(video.compose_cmd(game, cam, [t / 'voice-0.wav', t / 'voice-1.wav'], stem, take, -1.0, out), check=True)
        info = video.checked(out, 3.0); self.assertLess(abs(info['duration'] - 3.0), .1)
        p = video.probe(out); v = next(s for s in p['streams'] if s['codec_type'] == 'video'); a = next(s for s in p['streams'] if s['codec_type'] == 'audio')
        self.assertEqual((v['codec_name'], v['profile'], v['width'], v['height'], v['pix_fmt'], v['r_frame_rate']), ('h264', 'High', 1920, 1080, 'yuv420p', '30/1'))
        self.assertEqual((a['codec_name'], a['profile'], int(a['sample_rate']), a['channels']), ('aac', 'LC', 48000, 2))
        pcm = video.decode(out); env = np.abs(pcm)
        peaks = sorted(int(np.argmax(env[int(lo * SR):int(hi * SR)])) + int(lo * SR) for lo, hi in ((0, 1), (2, 3)))
        for got, want in zip(peaks, (.1, 2.0 + .3)):   # adelay of segment 2 is when₂ − when₁ = 2 s
            self.assertLess(abs(got / SR - want), .001, f'click at {got / SR:.4f} s, wanted {want} s')


if __name__ == '__main__':
    unittest.main(verbosity=1)
