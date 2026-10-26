"""Local proxy that rechecks each destination before it connects."""

from __future__ import annotations

import ipaddress
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from orca.browser_engine.policy import PolicyError, check_destination


def _same_address(left: str, right: str) -> bool:
    try:
        first = ipaddress.ip_address(left.split("%", 1)[0])
        second = ipaddress.ip_address(right.split("%", 1)[0])
    except ValueError:
        return left == right
    first_mapped = getattr(first, "ipv4_mapped", None) or first
    second_mapped = getattr(second, "ipv4_mapped", None) or second
    return first_mapped == second_mapped


def _peer_in_pins(peer: str, pins: tuple[str, ...]) -> bool:
    return any(_same_address(peer, pin) for pin in pins)


def _authority(host: str, port: int) -> str:
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"


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
    """Parse a CONNECT authority. Unbracketed IPv6 is ambiguous and refused."""
    if path.startswith("["):
        end = path.find("]")
        if end < 1 or not path[end + 1 :].startswith(":"):
            return None, None
        port = path[end + 2 :]
        if not port.isdigit() or ":" in port:
            return None, None
        return path[1:end], port
    if path.count(":") != 1:
        return None, None
    host, port = path.split(":", 1)
    if not port.isdigit() or not host or ":" in host:
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
                try:
                    port_number = int(port_text)
                except ValueError:
                    self._refuse("url_refused")
                    return
                netloc = _authority(host, port_number)
                try:
                    pins = check_destination(
                        f"https://{netloc}/", proxy.allow_loopback, resolver=proxy.resolver
                    )
                except PolicyError as exc:
                    self._refuse(exc.code)
                    return
                upstream = self._connect_pinned(pins, port_number, "https")
                if upstream is None:
                    return
                self.send_response(200, "Connection Established")
                self.end_headers()
                self.wfile.flush()
                sockets = [self.connection, upstream]
                idle_deadline = time.monotonic() + 60
                try:
                    while time.monotonic() < idle_deadline:
                        ready = _ready(sockets, min(5, idle_deadline - time.monotonic()))
                        if not ready:
                            continue
                        idle_deadline = time.monotonic() + 60
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
                raw_length = self.headers.get("Content-Length", "0") or "0"
                try:
                    length = int(raw_length)
                except ValueError:
                    self._refuse("url_refused")
                    upstream.close()
                    return
                if length < 0 or length > 1_000_000:
                    self._refuse("url_refused")
                    upstream.close()
                    return
                body = self._read_exact(length)
                path = parts.path or "/"
                if parts.query:
                    path = f"{path}?{parts.query}"
                host = parts.hostname or ""
                header_lines = [f"{self.command} {path} HTTP/1.1", f"Host: {_authority(host, port)}", "Connection: close"]
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
                except (TimeoutError, OSError):
                    self._refuse("connect_refused")
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
                        f"{scheme}://{_authority(peer, port)}/", proxy.allow_loopback, resolver=proxy.resolver
                    )
                except PolicyError as exc:
                    upstream.close()
                    self._refuse(exc.code)
                    return None
                return upstream

            def _read_exact(self, size: int) -> bytes:
                previous = self.connection.gettimeout()
                self.connection.settimeout(5)
                try:
                    chunks = []
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(remaining)
                        if not chunk:
                            raise TimeoutError
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    return b"".join(chunks)
                finally:
                    self.connection.settimeout(previous)

            def _read_response(self, upstream: socket.socket) -> bytes:
                """Read until the upstream closes. An idle gap is not a complete body."""
                chunks = []
                total = 0
                deadline = time.monotonic() + 20
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    if not _ready([upstream], min(remaining, 20)):
                        raise TimeoutError
                    chunk = upstream.recv(65536)
                    if not chunk:
                        return b"".join(chunks)
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > 8_000_000:
                        raise TimeoutError

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
