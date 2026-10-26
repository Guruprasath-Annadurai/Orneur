"""Local proxy that rechecks each destination before it connects."""

from __future__ import annotations

import ipaddress
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from orca.browser_engine.policy import PolicyError, check_destination


def _peer_in_pins(peer: str, pins: tuple[str, ...]) -> bool:
    if peer in pins:
        return True
    try:
        mapped = getattr(ipaddress.ip_address(peer), "ipv4_mapped", None)
    except ValueError:
        return False
    return mapped is not None and str(mapped) in pins


def _ready(socks: list[socket.socket], timeout: float) -> list[socket.socket]:
    """Wait for readability. poll() accepts descriptors above select()'s 1024 limit."""
    poller = select.poll()
    by_fd: dict[int, socket.socket] = {}
    for sock in socks:
        descriptor = sock.fileno()
        by_fd[descriptor] = sock
        poller.register(descriptor, select.POLLIN | select.POLLERR | select.POLLHUP)
    events = poller.poll(int(timeout * 1000))
    return [by_fd[descriptor] for descriptor, _event in events if descriptor in by_fd]


def _connect_target(path: str) -> tuple[str | None, str | None]:
    if path.startswith("["):
        end = path.find("]")
        if end < 1 or not path[end + 1 :].startswith(":"):
            return None, None
        port = path[end + 2 :]
        if not port.isdigit():
            return None, None
        return path[1:end], port
    host, separator, port = path.rpartition(":")
    if not separator or not port.isdigit() or not host:
        return None, None
    return host, port


class FilteringProxy:
    def __init__(self, allow_loopback: frozenset[str], resolver=None):
        self.allow_loopback = allow_loopback
        self.resolver = resolver
        self.refusals: list[str] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="browser-proxy", daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self):
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                self._forward()

            def do_POST(self):
                self._forward()

            def do_HEAD(self):
                self._forward()

            def do_CONNECT(self):
                host, port_text = _connect_target(self.path)
                if host is None or port_text is None:
                    self._refuse("url_refused")
                    return
                netloc = f"[{host}]:{port_text}" if ":" in host else f"{host}:{port_text}"
                try:
                    pins = check_destination(
                        f"https://{netloc}/", proxy.allow_loopback, resolver=proxy.resolver
                    )
                except PolicyError as exc:
                    self._refuse(exc.code)
                    return
                upstream = self._connect_pinned(pins, int(port_text), "https")
                if upstream is None:
                    return
                self.send_response(200, "Connection Established")
                self.end_headers()
                self.wfile.flush()
                sockets = [self.connection, upstream]
                try:
                    while True:
                        ready = _ready(sockets, 5)
                        if not ready:
                            break
                        for item in ready:
                            chunk = item.recv(65536)
                            if not chunk:
                                return
                            other = upstream if item is self.connection else self.connection
                            other.sendall(chunk)
                except OSError:
                    return
                finally:
                    upstream.close()
                    self.close_connection = True

            def _forward(self):
                try:
                    pins = check_destination(self.path, proxy.allow_loopback, resolver=proxy.resolver)
                except PolicyError as exc:
                    self._refuse(exc.code)
                    return
                parts = urlsplit(self.path)
                port = parts.port or (443 if parts.scheme == "https" else 80)
                upstream = self._connect_pinned(pins, port, parts.scheme)
                if upstream is None:
                    return
                body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                path = parts.path or "/"
                if parts.query:
                    path = f"{path}?{parts.query}"
                header_lines = [f"{self.command} {path} HTTP/1.1", f"Host: {parts.hostname}:{port}", "Connection: close"]
                for name in ("Accept", "Accept-Language", "User-Agent", "Cookie", "Content-Type"):
                    value = self.headers.get(name)
                    if value:
                        header_lines.append(f"{name}: {value.replace(chr(10), '').replace(chr(13), '')}")
                if body:
                    header_lines.append(f"Content-Length: {len(body)}")
                request = ("\r\n".join(header_lines) + "\r\n\r\n").encode()
                try:
                    upstream.sendall(request + body)
                    self.wfile.write(self._read_response(upstream))
                    self.wfile.flush()
                finally:
                    upstream.close()
                self.close_connection = True

            def _connect_pinned(self, pins: tuple[str, ...], port: int, scheme: str):
                try:
                    upstream = socket.create_connection((pins[0], port), timeout=5)
                except OSError:
                    self._refuse("connect_refused")
                    return None
                peer = upstream.getpeername()[0].split("%", 1)[0]
                if not _peer_in_pins(peer, pins):
                    upstream.close()
                    self._refuse("dns_rebinding_refused")
                    return None
                try:
                    check_destination(
                        f"{scheme}://{peer}:{port}/", proxy.allow_loopback, resolver=proxy.resolver
                    )
                except PolicyError as exc:
                    upstream.close()
                    self._refuse(exc.code)
                    return None
                return upstream

            def _read_response(self, upstream: socket.socket) -> bytes:
                chunks = []
                while True:
                    if not _ready([upstream], 5):
                        break
                    chunk = upstream.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b"".join(chunks)

            def _refuse(self, code: str):
                proxy.refusals.append(code)
                payload = code.encode()
                try:
                    self.send_response(403)
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionError, OSError):
                    return
                self.close_connection = True

        return Handler
