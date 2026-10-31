"""Length-prefixed JSON frames over a stream socket. No pickle: a frame can only ever be data. Standard library only."""
from __future__ import annotations

import json
import socket
import struct
import time

MAX_FRAME = 64 * 1024 * 1024


class FrameError(Exception):
    pass


def send(sock: socket.socket, obj: dict) -> None:
    body = json.dumps(obj, separators=(",", ":")).encode()
    if len(body) > MAX_FRAME:
        raise FrameError("frame too large")
    sock.sendall(struct.pack(">I", len(body)) + body)


def _read_exact(sock: socket.socket, n: int, deadline: float | None) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise socket.timeout("deadline")
            sock.settimeout(left)
        chunk = sock.recv(min(1 << 20, n - len(buf)))
        if not chunk:
            raise FrameError("connection closed")
        buf += chunk
    return bytes(buf)


def recv(sock: socket.socket, deadline: float | None = None) -> dict:
    """Read one frame. ``deadline`` is an absolute ``time.monotonic()`` value; ``socket.timeout`` is raised when it passes (the caller is freed whatever the peer is doing)."""
    (n,) = struct.unpack(">I", _read_exact(sock, 4, deadline))
    if n > MAX_FRAME:
        raise FrameError("frame too large")
    try:
        obj = json.loads(_read_exact(sock, n, deadline).decode())
    except ValueError:
        raise FrameError("malformed frame") from None
    if not isinstance(obj, dict):
        raise FrameError("malformed frame")
    return obj
