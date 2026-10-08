"""Keyless plaintext checker. Stdlib only: no HPKE, no signing keys, no network.

The parent process pipes plaintext in and accepts only this verdict line.
"""

from __future__ import annotations

import sys

MAX_IN = 2 * 1024 * 1024
_MAGIC = b"OCHK"


def judge(plaintext: bytes) -> bytes:
    if not isinstance(plaintext, (bytes, bytearray)) or len(plaintext) > MAX_IN:
        return b"STRUCTURAL_REJECT\n"
    data = bytes(plaintext)
    if len(data) < 9 or data[:4] != _MAGIC or data[4] != 1:
        return b"STRUCTURAL_REJECT\n"
    length = int.from_bytes(data[5:9], "big")
    payload = data[9:]
    if length != len(payload) or length < 1 or length > MAX_IN:
        return b"STRUCTURAL_REJECT\n"
    return b"STRUCTURAL_OK " + str(length).encode("ascii") + b"\n"


def main() -> int:
    blob = sys.stdin.buffer.read(MAX_IN + 1)
    sys.stdout.buffer.write(judge(blob))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
