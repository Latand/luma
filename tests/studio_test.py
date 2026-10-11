"""HTTP contracts with the preparation worker disabled; no audio processing or paid APIs."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
import covers  # noqa: E402
HAS_FFMPEG = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def make_original(package: Path, pictures: bool) -> Path:
    """A 1 s m4a like the real library's: a letterboxed 64×36 PNG attached first, the square 48×48 JPEG after it."""
    package.mkdir(parents=True, exist_ok=True); ff = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    original = package / 'original.m4a'
    if not pictures:
        subprocess.run([*ff, '-f', 'lavfi', '-i', 'sine=d=1', '-c:a', 'aac', str(original)], check=True); return original
    wide, square = package / 'wide.png', package / 'square.jpg'
    subprocess.run([*ff, '-f', 'lavfi', '-i', 'color=red:s=64x36', '-frames:v', '1', str(wide)], check=True)
    subprocess.run([*ff, '-f', 'lavfi', '-i', 'color=blue:s=48x48', '-frames:v', '1', str(square)], check=True)
    subprocess.run([*ff, '-f', 'lavfi', '-i', 'sine=d=1', '-i', str(wide), '-i', str(square), '-map', '0', '-map', '1', '-map', '2', '-c:a', 'aac', '-c:v:0', 'png', '-c:v:1', 'mjpeg', '-disposition:v', 'attached_pic', str(original)], check=True)
    wide.unlink(); square.unlink(); return original


def image_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(path)], capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(','); return int(w), int(h)


@unittest.skipUnless(HAS_FFMPEG, 'ffmpeg/ffprobe are not installed')
class CoverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='luma-covers-'); self.songs = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_cover_prefers_square_attached_picture(self):
        make_original(self.songs / 'Fixture', True)
        cover = covers.extract(self.songs / 'Fixture')
        self.assertEqual(cover, self.songs / 'Fixture' / 'cover.jpg')
        self.assertEqual(cover.read_bytes()[:2], b'\xff\xd8', 'a JPEG')
        self.assertEqual(image_size(cover), (48, 48), 'the square album art, not the letterboxed thumbnail before it')
        self.assertEqual(list((self.songs / 'Fixture').glob('*.part')), [])

    def test_cover_is_cached_and_refreshed_by_mtime(self):
        original = make_original(self.songs / 'Fixture', True)
        cover = covers.extract(self.songs / 'Fixture')
        with patch.object(covers.subprocess, 'run', side_effect=AssertionError('probed a cached cover')):
            self.assertEqual(covers.extract(self.songs / 'Fixture'), cover)
        later = cover.stat().st_mtime + 10; os.utime(original, (later, later))
        with patch.object(covers.subprocess, 'run', wraps=subprocess.run) as run:
            self.assertEqual(covers.extract(self.songs / 'Fixture'), cover)
        self.assertEqual(run.call_count, 2, 'a newer original is probed and extracted again')
        self.assertGreaterEqual(cover.stat().st_mtime, later)

    def test_song_without_picture_gets_a_marker(self):
        make_original(self.songs / 'Plain', False)
        self.assertIsNone(covers.extract(self.songs / 'Plain'))
        self.assertTrue((self.songs / 'Plain' / 'cover.none').exists())
        self.assertFalse((self.songs / 'Plain' / 'cover.jpg').exists())
        with patch.object(covers.subprocess, 'run', side_effect=AssertionError('probed a song known to have no picture')):
            self.assertIsNone(covers.extract(self.songs / 'Plain'))

    def test_backfill_counts_without_names(self):
        make_original(self.songs / 'Secret_Title_One', True); make_original(self.songs / 'Secret_Title_Two', False)
        (self.songs / 'inbox').mkdir(); (self.songs / 'Luma_Secret_Title_One.html').write_text('<html>')
        out = io.StringIO()
        with contextlib.redirect_stdout(out): counts = covers.backfill(self.songs)
        self.assertEqual(counts, {'extracted': 1, 'cached': 0, 'none': 1, 'failed': 0})
        self.assertNotIn('Secret', out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(covers.backfill(self.songs)['cached'], 1)

    def test_missing_ffmpeg_leaves_no_marker(self):
        make_original(self.songs / 'Fixture', True)
        with patch.object(covers.subprocess, 'run', side_effect=FileNotFoundError('ffprobe')):
            self.assertIsNone(covers.extract(self.songs / 'Fixture'))
        self.assertEqual(sorted(p.name for p in (self.songs / 'Fixture').iterdir()), ['original.m4a'], 'retried on the next start')



class StudioHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='luma-http-')
        with patch.object(sys, 'argv', ['studio_server.py', '--songs', self.directory.name]), patch.object(threading.Thread, 'start'), patch.object(sys, 'path', [str(ROOT / 'studio'), *sys.path]):
            self.module = runpy.run_path(str(ROOT / 'studio' / 'studio_server.py'))
        self.server = self.module['ThreadingHTTPServer'](('127.0.0.1', 0), self.module['Handler'])
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, path, body=None, method=None):
        try:
            with urlopen(Request(self.url + path, data=body, method=method), timeout=3) as response:
                return response.status, response.read()
        except HTTPError as response:
            return response.code, response.read()

    def test_duplicate_upload_is_only_queued_once(self):
        path = '/upload?name=demo.wav&title=Demo&requestId=stable-operation'
        first = self.request(path, b'fake audio', 'PUT')
        second = self.request(path, b'fake audio', 'PUT')
        self.assertEqual((first[0], second[0]), (200, 200))
        self.assertEqual(len(self.module['jobs']), 1)
        self.assertEqual(len(list((Path(self.directory.name) / 'inbox').iterdir())), 1)

    def test_upload_is_streamed_to_the_inbox_whole(self):
        body = bytes(range(256)) * (3 * 4096) + b'tail'  # three 1 MiB pieces and a remainder
        status, _ = self.request('/upload?name=long.wav&title=Long', body, 'PUT')
        self.assertEqual(status, 200)
        files = list((Path(self.directory.name) / 'inbox').iterdir())
        self.assertEqual(len(files), 1, 'no .part file is left behind')
        self.assertEqual(files[0].read_bytes(), body)
        self.assertEqual(self.module['jobs'][0]['path'], str(files[0]))

    def test_upload_limits_and_a_body_cut_short(self):
        def raw(length, body):
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as sock:
                sock.sendall(f'PUT /upload?name=cut.wav&title=Cut HTTP/1.1\r\nHost: x\r\nContent-Length: {length}\r\n\r\n'.encode() + body)
                sock.shutdown(socket.SHUT_WR); reply = b''
                while chunk := sock.recv(65536): reply += chunk
            return int(reply.split(b' ', 2)[1]), reply.split(b'\r\n\r\n', 1)[1].decode()
        self.assertEqual(self.module['MAX_UPLOAD'], 1 << 30, 'a 40-minute uncompressed song fits')
        status, text = raw(self.module['MAX_UPLOAD'] + 1, b'x')
        self.assertEqual((status, text), (400, 'Розмір файлу має бути від 1 байта до 1024 МБ.'))
        self.assertEqual(raw(100, b'only ten b'), (400, 'Файл отримано не повністю.'))
        self.assertEqual((self.module['jobs'], list((Path(self.directory.name) / 'inbox').iterdir())), ([], []))

    def test_import_uses_our_app_and_never_overwrites(self):
        song = {'schema': 'luma.song.v1', 'title': '<img src=x onerror=alert(1)>', 'artist': 'A', 'duration': 4, 'notes': [], 'points': [], 'phrases': [], 'lyrics': [], 'hop': .02}
        assets = {'1': {'backing': 'test', 'foreground': 'test'}}
        source = ('<script>alert("foreign")</script><script>window.LUMA_SONG=' + json.dumps(song) + ';window.LUMA_ASSETS=' + json.dumps(assets) + ';</script>').encode()
        filenames = []
        for _ in range(2):
            status, body = self.request('/import?name=old.html', source, 'PUT')
            self.assertEqual(status, 200, body)
            filenames.append(json.loads(body)['html'])
        self.assertNotEqual(*filenames)
        content = (Path(self.directory.name) / filenames[0]).read_text()
        self.assertNotIn('<script>alert("foreign")', content)
        self.assertNotIn('<img src=x', content)
        self.assertIn('scaleSelect', content)
        status, _ = self.request('/import?name=bad.html', b'<html>no trainer data</html>', 'PUT')
        self.assertEqual(status, 400)
        status, body = self.request('/status')
        self.assertEqual({(s['title'], s['artist'], s['duration']) for s in json.loads(body)['songs']}, {('<img src=x onerror=alert(1)>', 'A', 4.0)}, 'imported trainers keep their metadata in the library')

    def test_retry_only_transitions_a_failed_job_once(self):
        self.request('/upload?name=demo.wav', b'fake audio', 'PUT')
        job = self.module['jobs'][0]
        path = '/retry?id=' + job['id']
        self.assertEqual(self.request(path, b'', 'POST')[0], 409)
        job.update(state='failed', finished=1, error='test failure')
        self.assertEqual(self.request(path, b'', 'POST')[0], 200)
        self.assertEqual(job['state'], 'queued')
        self.assertNotIn('error', job)
        self.assertEqual(self.request(path, b'', 'POST')[0], 409)

    def test_stage_info_reads_the_latest_marker(self):
        now = time.time(); stamp = lambda ago: time.strftime('%H:%M:%S', time.localtime(now - ago))
        log = Path(self.directory.name) / 'job.log'
        log.write_text(stamp(100) + ' [1/8] decode\n' + stamp(95) + ' [2/8] separation htdemucs_ft\nsome warning without a marker\n' + stamp(40) + ' [3/8] pYIN\n')
        info = self.module['stage_info']({'log': str(log), 'started': now - 100}, now)
        self.assertEqual((info['n'], info['total'], info['key']), (3, 8, 'pYIN'))
        self.assertTrue(0 < info['progress'] < 1)
        self.assertGreater(info['eta'], 0)
        self.assertIsNone(self.module['stage_info']({'log': str(log) + '.missing'}, now))

    def test_status_and_cover_route(self):
        songs = Path(self.directory.name); (songs / 'Fixture').mkdir(); jpeg = b'\xff\xd8fake jpeg\xff\xd9'
        (songs / 'Fixture' / 'cover.jpg').write_bytes(jpeg)
        for name in ('Luma_Fixture.html', 'Luma_Lesson_1_Novachok.html', 'Luma_Imported_0123abcd.html'): (songs / name).write_text('<html>')
        (songs / 'Lesson_1_Novachok').mkdir()
        status, body = self.request('/status')
        listed = {s['name']: s['cover'] for s in json.loads(body)['songs']}
        self.assertIsInstance(listed['Luma_Fixture.html'], int)
        self.assertEqual((listed['Luma_Lesson_1_Novachok.html'], listed['Luma_Imported_0123abcd.html']), (None, None))
        with urlopen(self.url + '/cover/Luma_Fixture.html?v=1', timeout=3) as response:
            self.assertEqual((response.status, response.headers['Content-Type'], response.read()), (200, 'image/jpeg', jpeg))
            self.assertIn('max-age', response.headers['Cache-Control'])
        (songs / 'secret.jpg').write_bytes(b'private')
        for path in ('Luma_Missing.html', 'Luma_Lesson_1_Novachok.html', 'Luma_Imported_0123abcd.html', '..%2F..%2Fetc%2Fpasswd', '%2e%2e/cover.jpg', 'Fixture/cover.jpg', 'Luma_..html', 'Luma_Fixture%2F..%2F.html', '..%2Fsecret.jpg'):
            self.assertEqual(self.request('/cover/' + path)[0], 404, path)

    def test_status_lists_library_metadata(self):
        trainer = Path(self.directory.name) / 'Luma_Test.html'
        trainer.write_text('<html>' + 'x' * 100 + '<script>window.LUMA_SONG={"schema":"luma.song.v1","title":"T\u00e9st \\"q\\"","artist":"Band","duration":123.4,"points":[]};window.LUMA_ASSETS={};</script>', encoding='utf-8')
        status, body = self.request('/status')
        song = json.loads(body)['songs'][0]
        self.assertEqual((status, song['title'], song['artist'], song['duration']), (200, 'T\u00e9st "q"', 'Band', 123.4))

    def test_activity_is_appended_as_jsonl(self):
        event = lambda n, kind: {'ts': '2026-10-07T10:00:0%dZ' % n, 'session': 's1', 'page': 'Luma_Test', 'seq': n, 'type': kind, 'data': {'id': 'singBtn', 'extra': 'кліки'}, 'junk': 1}
        for batch in ([event(1, 'page_open'), event(2, 'click')], [event(3, 'attempt')]):
            status, _ = self.request('/activity', json.dumps({'events': batch}).encode(), 'POST')
            self.assertEqual(status, 204)
        files = list((Path(self.directory.name) / 'logs' / 'activity').iterdir())
        self.assertEqual([f.name for f in files], [time.strftime('%Y-%m-%d') + '.jsonl'], 'one file per local day')
        lines = [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]
        self.assertEqual([e['type'] for e in lines], ['page_open', 'click', 'attempt'], 'batches are appended in order')
        self.assertEqual(lines[1], {'v': 1, 'ts': '2026-10-07T10:00:02Z', 'session': 's1', 'page': 'Luma_Test', 'seq': 2, 'type': 'click', 'data': {'id': 'singBtn', 'extra': 'кліки'}}, 'unknown top-level keys are dropped')

    def test_activity_refuses_oversize_malformed_and_foreign_batches(self):
        folder = Path(self.directory.name) / 'logs' / 'activity'
        ok = {'ts': '2026-10-07T10:00:00Z', 'session': 's', 'page': 'studio', 'type': 'click', 'data': {}}
        big = json.dumps({'events': [{**ok, 'data': {'pad': 'x' * (self.module['MAX_ACTIVITY'])}}]}).encode()
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3) as sock:
            sock.sendall(f'POST /activity HTTP/1.1\r\nHost: x\r\nContent-Length: {len(big)}\r\n\r\n'.encode())
            reply = sock.recv(65536)
        self.assertEqual(int(reply.split(b' ', 2)[1]), 413, 'a body over 64 KiB is refused before it is read')
        for body in (b'not json', b'[]', json.dumps({'events': []}).encode(), json.dumps({'events': [{**ok, 'type': 'Bad Type'}]}).encode(),
                     json.dumps({'events': [{**ok, 'data': 'text'}]}).encode(), json.dumps({'events': [ok] * 201}).encode(),
                     json.dumps({'events': [ok, {**ok, 'data': {'pad': 'x' * 17000}}]}).encode()):
            self.assertEqual(self.request('/activity', body, 'POST')[0], 400, body[:60])
        foreign = Request(self.url + '/activity', data=json.dumps({'events': [ok]}).encode(), method='POST', headers={'Origin': 'https://example.com'})
        with self.assertRaises(HTTPError) as refused: urlopen(foreign, timeout=3)
        self.assertEqual(refused.exception.code, 403, 'another site cannot write into the log')
        self.assertFalse(folder.exists() and any(folder.iterdir()), 'nothing refused reaches the file')
        same = Request(self.url + '/activity', data=json.dumps({'events': [ok]}).encode(), method='POST', headers={'Origin': self.url})
        with urlopen(same, timeout=3) as response: self.assertEqual(response.status, 204, 'the Studio origin may write')

    def test_activity_script_is_served(self):
        status, body = self.request('/activity.js')
        self.assertEqual(status, 200)
        self.assertIn(b'window.LumaActivity', body)


if __name__ == '__main__':
    unittest.main()
