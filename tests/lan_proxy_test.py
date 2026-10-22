#!/usr/bin/env python3
"""The LAN TLS proxy (studio/lan_proxy.py) as a real process: parallel keep-alive requests, downloads aborted and reset
mid-transfer, a client's EOF (close_notify or a bare FIN), a refused address and a dead upstream, after each of which
the same process still answers and has written nothing to stderr beyond the expected line. Uses a throwaway self-signed certificate (openssl) and a local upstream on a free port; no network.
"""
import http.client
import http.server
import ipaddress
import queue
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'studio'))
import lan_proxy

BIG = bytes(range(256)) * 16384  # 4 MiB
SMALL = b'luma ok\n'


class QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # the proxy resets Studio's side when a client aborts


class Upstream(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        body = BIG if self.path == '/big' else SMALL
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *a):
        pass


def counting_server(counts):
    """Raw upstream: reads until the client's EOF, then puts the byte count on `counts` and closes."""
    srv = socket.create_server(('127.0.0.1', 0))

    def run():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            with conn:
                n = 0
                while data := conn.recv(65536):
                    n += len(data)
                counts.put(n)
    threading.Thread(target=run, daemon=True).start()
    return srv


def free_port_closed():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    return port


class LanProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.cert, cls.key = d / 'cert.pem', d / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=test',
                        '-keyout', str(cls.key), '-out', str(cls.cert)], check=True, capture_output=True)
        cls.http = QuietServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.ctx = ssl.create_default_context()
        cls.ctx.check_hostname = False
        cls.ctx.verify_mode = ssl.CERT_NONE

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.tmp.cleanup()

    def start(self, upstream_port, *allow):
        cmd = [sys.executable, '-I', str(ROOT / 'studio' / 'lan_proxy.py'), '--cert', str(self.cert), '--key',
               str(self.key), '--listen', '127.0.0.1', '--port', '0', '--upstream', f'127.0.0.1:{upstream_port}']
        for a in allow:
            cmd += ['--allow', a]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop, proc)
        line = proc.stdout.readline()
        self.assertIn('listening on', line)
        return proc, int(line.split()[3].rsplit(':', 1)[1])

    def stop(self, proc):
        """Stops the proxy this test started and returns what it wrote to stderr."""
        if proc.stderr.closed:
            return self.stderr
        if proc.poll() is None:
            proc.terminate()
        proc.wait(5)
        proc.stdout.close()
        self.stderr = proc.stderr.read()
        proc.stderr.close()
        return self.stderr

    def get(self, port, path='/', conn=None):
        c = conn or http.client.HTTPSConnection('127.0.0.1', port, context=self.ctx, timeout=10)
        c.request('GET', path)
        r = c.getresponse()
        return r.status, r.read(), c

    def assert_alive(self, proc, port):
        self.assertIsNone(proc.poll(), 'the proxy exited')
        status, body, c = self.get(port)
        c.close()
        self.assertEqual((status, body), (200, SMALL))

    def test_allowed_networks(self):
        nets = [ipaddress.ip_network(n) for n in ('192.168.5.0/24', '127.0.0.0/8', '::1')]
        for peer, ok in [('192.168.5.7', True), ('127.0.0.1', True), ('::1', True), ('::ffff:192.168.5.3', True),
                         ('192.168.6.1', False), ('100.86.224.50', False), ('10.253.126.1', False),
                         ('fe80::1%eth0', False), ('?', False), ('', False)]:
            self.assertEqual(lan_proxy.allowed(peer, nets), ok, peer)

    def test_parallel_keep_alive_requests(self):
        proc, port = self.start(self.http.server_address[1])

        def client(i):
            conn = None
            out = []
            for path in ('/', '/big', '/') if i % 5 == 0 else ('/', '/', '/'):
                status, body, conn = self.get(port, path, conn)
                out.append((status, len(body)))
            conn.close()
            return out

        with ThreadPoolExecutor(60) as pool:
            results = list(pool.map(client, range(60)))
        for i, res in enumerate(results):
            expected_big = (200, len(BIG))
            self.assertEqual(res[1], expected_big if i % 5 == 0 else (200, len(SMALL)))
            self.assertEqual(res[0], (200, len(SMALL)))
        self.assert_alive(proc, port)
        self.assertEqual(self.stop(proc), '')

    def test_aborted_and_reset_downloads(self):
        proc, port = self.start(self.http.server_address[1])
        for linger in (False, True) * 10:
            raw = socket.create_connection(('127.0.0.1', port))
            tls = self.ctx.wrap_socket(raw)
            tls.sendall(b'GET /big HTTP/1.1\r\nHost: x\r\n\r\n')
            tls.recv(10000)
            if linger:  # close with RST
                tls.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            tls.close()
        # a client that drops before the handshake finishes
        socket.create_connection(('127.0.0.1', port)).close()
        s = socket.create_connection(('127.0.0.1', port)); s.sendall(b'\x16\x03\x01garbage'); s.close()
        time.sleep(0.3)
        self.assert_alive(proc, port)
        self.assertEqual(self.stop(proc), '')

    @unittest.skipUnless(Path('/proc/self/status').exists(), 'reads VmRSS from /proc')
    def test_aborted_downloads_give_their_memory_back(self):
        proc, port = self.start(self.http.server_address[1])

        def rss_kb():
            for line in Path(f'/proc/{proc.pid}/status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    return int(line.split()[1])

        def abort(_):
            tls = self.ctx.wrap_socket(socket.create_connection(('127.0.0.1', port), timeout=10))
            tls.sendall(b'GET /big HTTP/1.1\r\nHost: x\r\n\r\n')
            tls.recv(65536)
            time.sleep(0.3)  # let Studio's side fill the buffers
            tls.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            tls.close()

        def burst():
            with ThreadPoolExecutor(30) as pool:
                list(pool.map(abort, range(30)))
            time.sleep(lan_proxy.RECLAIM_EVERY + 1.5)
            return rss_kb()

        # The first burst sets the allocator's high-water mark; what it keeps after that is the peak of 30 connections
        # at once. Three more bursts must not add to it (before the reclaim each one added about 30 MB).
        first = burst()
        grown = max(burst() for _ in range(3)) - first
        self.assertLess(grown, 25_000, f'RSS grew by {grown} kB over three more bursts of 30 aborted downloads')
        self.assert_alive(proc, port)
        self.assertEqual(self.stop(proc), '')

    def client_eof(self, bare_fin):
        """Sends 5000 bytes over TLS, then EOF; returns what Studio's side counted before its EOF."""
        counts = queue.Queue()
        upstream = counting_server(counts)
        self.addCleanup(upstream.close)
        proc, port = self.start(upstream.getsockname()[1])
        raw = socket.create_connection(('127.0.0.1', port), timeout=10)
        inc, out = ssl.MemoryBIO(), ssl.MemoryBIO()
        obj = self.ctx.wrap_bio(inc, out)
        while True:
            try:
                obj.do_handshake()
                break
            except ssl.SSLWantReadError:
                raw.sendall(out.read())
                inc.write(raw.recv(65536))
        obj.write(b'x' * 5000)
        if not bare_fin:
            try:
                obj.unwrap()  # close_notify
            except ssl.SSLWantReadError:
                pass
        raw.sendall(out.read())
        raw.shutdown(socket.SHUT_WR)
        try:
            counted = counts.get(timeout=5)
        finally:
            raw.close()
        time.sleep(0.2)
        self.assertIsNone(proc.poll())
        self.assertEqual(self.stop(proc), '')
        return counted

    def test_client_close_notify_reaches_studio_as_eof(self):
        self.assertEqual(self.client_eof(bare_fin=False), 5000)

    def test_client_bare_fin_reaches_studio_as_eof(self):
        self.assertEqual(self.client_eof(bare_fin=True), 5000)

    def test_refused_address(self):
        proc, port = self.start(self.http.server_address[1], '192.168.5.0/24')
        with self.assertRaises((ssl.SSLError, OSError)):
            self.get(port)
        time.sleep(0.2)
        self.assertIsNone(proc.poll())
        self.stop(proc)
        self.assertEqual(self.stderr, 'lan_proxy: refused 127.0.0.1\n')

    def test_dead_upstream(self):
        proc, port = self.start(free_port_closed())
        for _ in range(3):
            with self.assertRaises((http.client.HTTPException, OSError)):
                self.get(port)
        self.assertIsNone(proc.poll())
        self.assertEqual(self.stop(proc), '')


if __name__ == '__main__':
    unittest.main()
