"""HTTP contracts with the preparation worker disabled; no audio processing or paid APIs."""
import json
from pathlib import Path
import runpy
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


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

    def test_status_lists_library_metadata(self):
        trainer = Path(self.directory.name) / 'Luma_Test.html'
        trainer.write_text('<html>' + 'x' * 100 + '<script>window.LUMA_SONG={"schema":"luma.song.v1","title":"T\u00e9st \\"q\\"","artist":"Band","duration":123.4,"points":[]};window.LUMA_ASSETS={};</script>', encoding='utf-8')
        status, body = self.request('/status')
        song = json.loads(body)['songs'][0]
        self.assertEqual((status, song['title'], song['artist'], song['duration']), (200, 'T\u00e9st "q"', 'Band', 123.4))


if __name__ == '__main__':
    unittest.main()
