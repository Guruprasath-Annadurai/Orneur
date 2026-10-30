"""Minimal Chrome DevTools Protocol client over a raw WebSocket."""

from __future__ import annotations

import base64
import json
import os
import select
import socket
import struct
import time
from urllib.parse import urlsplit

from orca.browser_engine.policy import PolicyError


class CdpError(PolicyError):
    pass


class CdpClient:
    def __init__(self, websocket_url: str):
        parts = urlsplit(websocket_url)
        if parts.scheme != "ws" or parts.hostname not in {"127.0.0.1", "::1"}:
            raise CdpError("cdp_endpoint_refused")
        self._socket = socket.create_connection((parts.hostname, parts.port), timeout=5)
        self._socket.settimeout(10)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {parts.path or '/'} HTTP/1.1\r\n"
            f"Host: {parts.hostname}:{parts.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(request.encode())
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise CdpError("cdp_handshake_refused")
            buffer += chunk
        if b" 101 " not in buffer.split(b"\r\n", 1)[0]:
            raise CdpError("cdp_handshake_refused")
        self._next = 0

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass

    def call(self, method: str, params: dict | None = None, session_id: str | None = None, timeout: float = 10) -> dict:
        self._next += 1
        message = {"id": self._next, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        self._send(json.dumps(message).encode())
        self._socket.settimeout(timeout)
        while True:
            payload = self._recv()
            if payload.get("id") != message["id"]:
                continue
            if "error" in payload:
                raise CdpError("cdp_command_refused")
            return payload.get("result") or {}

    def _send(self, payload: bytes, opcode: int = 0x1) -> None:
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(bytes(header) + mask + masked)

    def _recv(self) -> dict:
        fragments = bytearray()
        kind = 0
        while True:
            first = self._read_exact(2)
            fin = first[0] & 0x80
            opcode = first[0] & 0x0F
            masked = first[1] & 0x80
            length = first[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > 8_000_000 or len(fragments) + length > 8_000_000:
                raise CdpError("cdp_frame_refused")
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length) if length else b""
            if mask:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x9:
                self._send(payload, opcode=0xA)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                raise CdpError("cdp_closed")
            if opcode in {0x1, 0x0}:
                if opcode == 0x1:
                    fragments = bytearray()
                    kind = 0x1
                if kind != 0x1:
                    continue
                fragments.extend(payload)
                if fin:
                    return json.loads(bytes(fragments).decode())
                continue
            if fin:
                return {}

    def _read_exact(self, size: int) -> bytes:
        buffer = b""
        while len(buffer) < size:
            chunk = self._socket.recv(size - len(buffer))
            if not chunk:
                raise CdpError("cdp_closed")
            buffer += chunk
        return buffer


class CdpPipe:
    """DevTools over the browser's private pipe. There is no TCP listener."""

    def __init__(self, read_fd: int, write_fd: int):
        self._read = os.fdopen(read_fd, "rb", buffering=0)
        self._write = os.fdopen(write_fd, "wb", buffering=0)
        self._buffer = b""
        self._next = 0

    def close(self) -> None:
        for stream in (self._read, self._write):
            try:
                stream.close()
            except OSError:
                pass

    def call(self, method: str, params: dict | None = None, session_id: str | None = None, timeout: float = 10) -> dict:
        self._next += 1
        message = {"id": self._next, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        self._write.write(json.dumps(message).encode() + b"\0")
        self._write.flush()
        deadline = time.monotonic() + timeout
        while True:
            payload = self._read_message(deadline)
            if payload.get("id") != message["id"]:
                continue
            if "error" in payload:
                raise CdpError("cdp_command_refused")
            return payload.get("result") or {}

    def _read_message(self, deadline: float) -> dict:
        while b"\0" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError("cdp_closed")
            # poll() accepts descriptors above select()'s 1024 limit (a busy server process legitimately holds more than that)
            poller = select.poll()
            poller.register(self._read.fileno(), select.POLLIN | select.POLLERR | select.POLLHUP)
            ready = poller.poll(int(remaining * 1000) + 1)
            if not ready:
                raise CdpError("cdp_closed")
            chunk = self._read.read(65536)
            if not chunk:
                raise CdpError("cdp_closed")
            self._buffer += chunk
            if len(self._buffer) > 8_000_000:
                raise CdpError("cdp_frame_refused")
        raw, _, self._buffer = self._buffer.partition(b"\0")
        return json.loads(raw.decode())
