#!/usr/bin/env python3
"""TLS on the LAN in front of Luma Studio, so the Quest Browser gets a secure context (microphone, WebXR).

A byte relay: each accepted connection from an allowed address gets TLS, then its bytes go to 127.0.0.1:8792 and back.
Standard library only, one asyncio loop. A connection that fails (reset, aborted download, bad handshake) closes only
itself; the server never exits because of one. An EOF from either side ends the exchange: Studio's EOF reaches the
client as close_notify after the last byte, and a client's EOF (close_notify or a bare FIN) reaches Studio as a TCP
shutdown before both close. asyncio's TLS layer keeps no half-open state, and browsers never wait for an answer after
their own EOF.

Run: python3 -I studio/lan_proxy.py --cert cert.pem --key key.pem [--listen 0.0.0.0] [--port 8790]
       [--upstream 127.0.0.1:8792] [--allow 192.168.5.0/24 --allow 127.0.0.0/8 --allow ::1] [--max-conns 400]
       [--handshake-timeout 10] [--reclaim-every 5]
"""
from __future__ import annotations
import argparse, asyncio, gc, ipaddress, logging, socket, ssl, sys

CHUNK = 64 * 1024
HANDSHAKE_TIMEOUT = 10.0
CONNECT_TIMEOUT = 5.0
CLOSE_TIMEOUT = 5.0
RECLAIM_EVERY = 5.0
QUIET = (OSError, EOFError, asyncio.IncompleteReadError, asyncio.TimeoutError)  # ssl.SSLError is an OSError


def log(*parts: object) -> None:
    print('lan_proxy:', *parts, file=sys.stderr, flush=True)


def allowed(peer: str, nets: list) -> bool:
    try:
        ip = ipaddress.ip_address(peer.split('%', 1)[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip.version == net.version and ip in net for net in nets)


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    """Copy until EOF. True on a clean EOF (passed on as a TCP shutdown where the transport has one), False on an error."""
    try:
        while data := await reader.read(CHUNK):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
        return True
    except QUIET:
        return False


async def close(writer: asyncio.StreamWriter | None, clean: bool) -> None:
    if writer is None:
        return
    if not clean:
        writer.transport.abort()
        return
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), CLOSE_TIMEOUT)
    except QUIET:
        writer.transport.abort()


class Proxy:
    def __init__(self, ctx: ssl.SSLContext, upstream: tuple[str, int], nets: list, max_conns: int,
                 handshake_timeout: float = HANDSHAKE_TIMEOUT, reclaim_every: float = RECLAIM_EVERY):
        self.ctx, self.upstream, self.nets, self.max_conns = ctx, upstream, nets, max_conns
        self.handshake_timeout, self.reclaim_every = handshake_timeout, reclaim_every
        self.open = 0
        self.unclean = 0  # connections closed by an error since the last reclaim()

    async def handle(self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        peer = (client_w.get_extra_info('peername') or ('?',))[0]
        if not allowed(peer, self.nets):
            log('refused', peer)
            client_w.transport.abort()
            return
        if self.open >= self.max_conns:
            log('busy, dropped', peer, f'({self.open} open)')
            client_w.transport.abort()
            return
        self.open += 1
        up_w = None
        clean = False
        try:
            sock = client_w.get_extra_info('socket')
            if sock is not None:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            await client_w.start_tls(self.ctx, ssl_handshake_timeout=self.handshake_timeout)
            up_r, up_w = await asyncio.wait_for(asyncio.open_connection(*self.upstream), CONNECT_TIMEOUT)
            to_up = asyncio.create_task(pipe(client_r, up_w))
            to_client = asyncio.create_task(pipe(up_r, client_w))
            try:
                done, _ = await asyncio.wait({to_up, to_client}, return_when=asyncio.FIRST_COMPLETED)
                clean = all(task.result() for task in done)
            finally:
                for task in (to_up, to_client):
                    task.cancel()
                await asyncio.gather(to_up, to_client, return_exceptions=True)
        except QUIET:
            pass
        except Exception as exc:  # one connection never takes the server down
            log('connection error', peer, type(exc).__name__, exc)
        finally:
            self.open -= 1
            self.unclean += not clean
            await close(up_w, clean)
            await close(client_w, clean)


    async def reclaim(self) -> None:
        """A connection that died keeps its error, whose traceback points back at the TLS buffers (about 1 MB each),
        and only a full collection finds such cycles; without it 30 aborted downloads held 30 MB until much later."""
        while True:
            await asyncio.sleep(self.reclaim_every)
            if self.unclean:
                self.unclean = 0
                gc.collect()


def quiet_loop_errors(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    exc = context.get('exception')
    if isinstance(exc, QUIET):
        return
    log('loop:', context.get('message'), type(exc).__name__ if exc else '', exc or '')


async def serve(args: argparse.Namespace) -> None:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(args.cert, args.key)
    host, _, port = args.upstream.rpartition(':')
    nets = [ipaddress.ip_network(a, strict=False) for a in args.allow]
    proxy = Proxy(ctx, (host, int(port)), nets, args.max_conns, args.handshake_timeout, args.reclaim_every)
    asyncio.get_running_loop().set_exception_handler(quiet_loop_errors)
    # A client that sends close_notify right after its handshake reaches the stream before start_tls() has marked it as
    # TLS, and asyncio warns that a half-open EOF has no effect over TLS; the connection still closes correctly.
    logging.getLogger('asyncio').addFilter(lambda rec: 'eof_received() has no effect' not in rec.getMessage())
    server = await asyncio.start_server(proxy.handle, args.listen, args.port, backlog=256, reuse_address=True)
    bound = server.sockets[0].getsockname()
    print(f'lan_proxy: listening on {bound[0]}:{bound[1]} -> {args.upstream}, allow {", ".join(args.allow)}', flush=True)
    reclaim = asyncio.create_task(proxy.reclaim())
    async with server:
        await server.serve_forever()
    reclaim.cancel()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--cert', required=True)
    ap.add_argument('--key', required=True)
    ap.add_argument('--listen', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=8790)
    ap.add_argument('--upstream', default='127.0.0.1:8792')
    ap.add_argument('--allow', action='append', help='network that may connect (repeatable); '
                    'default 192.168.5.0/24, 127.0.0.0/8 and ::1')
    ap.add_argument('--max-conns', type=int, default=400, help='open connections at once; more are dropped')
    ap.add_argument('--handshake-timeout', type=float, default=HANDSHAKE_TIMEOUT,
                    help='seconds a client may take to finish its TLS handshake before it is dropped')
    ap.add_argument('--reclaim-every', type=float, default=RECLAIM_EVERY,
                    help='seconds between collections of the memory that failed connections left behind')
    args = ap.parse_args()
    args.allow = args.allow or ['192.168.5.0/24', '127.0.0.0/8', '::1']
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
