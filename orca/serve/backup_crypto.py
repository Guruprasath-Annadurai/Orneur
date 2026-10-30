"""L02-B6: authenticated, streaming encryption for backup archives. No custom cryptography: AES-256-GCM and HKDF-SHA256 from the `cryptography` package.

Key custody is NOT decided here. The caller must provide a 32-byte key (``load_key``); this module never generates, stores or caches a key on its own, and refuses a key
file that other local users can read.

Archive layout::

    b"ORBK" | version(1) | salt(16) | chunk_size(4, big endian)          header (authenticated as AAD of every frame)
    repeat:  frame_len(4) | AES-GCM(ciphertext + tag)                      one frame per chunk

Every frame is encrypted under ``HKDF(key, salt)`` with a unique nonce (the frame counter) and AAD = header | counter | final-flag, so frames cannot be reordered, dropped,
duplicated, truncated (the last frame must carry the final flag) or extended. A wrong key and a modified archive are indistinguishable by design (both fail authentication).
"""
from __future__ import annotations

import base64
import os
import stat
import struct
from pathlib import Path

from orca.serve.backup_errors import BackupAuthError, BackupError, BackupKeyError  # noqa: F401  (re-exported)

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"ORBK"
VERSION = 1
CHUNK = 1 << 20
_MAX_FRAME = CHUNK + 16 + 1024


def load_key(path: str | os.PathLike | None = None, *, forbid_inside: list[Path] | None = None) -> bytes:
    """Read a base64-encoded 32-byte key from a file the operator provisioned. Refuses a missing path, a file readable by group/other, a wrong length, and a location inside
    any directory in ``forbid_inside`` (the data directory, the backup destination): the key must not travel with what it protects."""
    path = path or os.environ.get("ORNEUR_BACKUP_KEY_FILE")
    if not path:
        raise BackupKeyError("no backup key provisioned: pass --key-file or set ORNEUR_BACKUP_KEY_FILE (the key is never generated implicitly)")
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        raise BackupKeyError("backup key file is missing or unreadable") from None
    if not stat.S_ISREG(st.st_mode):
        raise BackupKeyError("backup key path is not a regular file")
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise BackupKeyError("backup key file must not be accessible by group or other users (chmod 600)")
    real = p.resolve()
    for root in forbid_inside or []:
        try:
            real.relative_to(Path(root).resolve())
        except ValueError:
            continue
        raise BackupKeyError("backup key file must not be stored inside the data directory or the backup location")
    try:
        key = base64.urlsafe_b64decode(p.read_text().strip() + "==")
    except Exception:
        raise BackupKeyError("backup key file is not valid base64") from None
    if len(key) != 32:
        raise BackupKeyError("backup key must be exactly 32 bytes")
    return key


def write_new_key(path: str | os.PathLike) -> None:
    """Explicit operator action (``orca data-backup keygen``): write a fresh random key to a path the operator chose. Refuses to overwrite. Custody stays with the operator."""
    p = Path(path)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=") + "\n")


def derive(key: bytes, salt: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(key)


def _nonce(counter: int) -> bytes:
    return b"\0\0\0\0" + struct.pack(">Q", counter)


class EncryptedWriter:
    """File-like writer: ``write`` bytes, ``close`` finishes the stream (writes the final frame). Plaintext is buffered one chunk at a time."""

    def __init__(self, raw, key: bytes):
        self._raw = raw
        salt = os.urandom(16)
        self._header = MAGIC + bytes([VERSION]) + salt + struct.pack(">I", CHUNK)
        self._aead = AESGCM(derive(key, salt, b"orneur-backup-v1"))
        self._buf = bytearray()
        self._counter = 0
        self._pending: bytes | None = None          # one frame is held back so the LAST one can be marked final
        raw.write(self._header)

    def _emit(self, plain: bytes, final: bool) -> None:
        aad = self._header + struct.pack(">QB", self._counter, 1 if final else 0)
        ct = self._aead.encrypt(_nonce(self._counter), plain, aad)
        self._raw.write(struct.pack(">I", len(ct)) + ct)
        self._counter += 1

    def write(self, data: bytes) -> None:
        self._buf += data
        while len(self._buf) > CHUNK:               # strictly greater: the tail stays buffered so close() can finalise it
            chunk, self._buf = bytes(self._buf[:CHUNK]), self._buf[CHUNK:]
            self._emit(chunk, final=False)

    def close(self) -> None:
        self._emit(bytes(self._buf), final=True)
        self._buf = bytearray()


class DecryptedReader:
    """File-like reader over an archive. Raises ``BackupAuthError`` on any authentication failure, including truncation and trailing data."""

    def __init__(self, raw, key: bytes):
        self._raw = raw
        head = raw.read(len(MAGIC) + 1 + 16 + 4)
        if len(head) != 25 or head[:4] != MAGIC or head[4] != VERSION:
            raise BackupAuthError("not an ORNEUR backup archive (or an unsupported version)")
        self._header = head
        (chunk,) = struct.unpack(">I", head[21:25])
        if chunk != CHUNK:
            raise BackupAuthError("unsupported chunk size")
        self._aead = AESGCM(derive(key, head[5:21], b"orneur-backup-v1"))
        self._counter = 0
        self._buf = bytearray()
        self._done = False
        self._next_len = self._read_len()

    def _read_len(self):
        b = self._raw.read(4)
        if not b:
            return None
        if len(b) != 4:
            raise BackupAuthError("archive is truncated")
        (n,) = struct.unpack(">I", b)
        if n < 16 or n > _MAX_FRAME:
            raise BackupAuthError("archive is corrupt")
        return n

    def _fill(self) -> bool:
        if self._done:
            return False
        if self._next_len is None:
            raise BackupAuthError("archive is truncated (no final frame)")
        ct = self._raw.read(self._next_len)
        if len(ct) != self._next_len:
            raise BackupAuthError("archive is truncated")
        following = self._read_len()
        final = following is None
        aad = self._header + struct.pack(">QB", self._counter, 1 if final else 0)
        try:
            plain = self._aead.decrypt(_nonce(self._counter), ct, aad)
        except InvalidTag:
            raise BackupAuthError("authentication failed: wrong key, or the archive was modified or truncated") from None
        self._counter += 1
        self._buf += plain
        self._next_len = following
        self._done = final
        return True

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            while self._fill():
                pass
            out, self._buf = bytes(self._buf), bytearray()
            return out
        while len(self._buf) < n and self._fill():
            pass
        out, self._buf = bytes(self._buf[:n]), self._buf[n:]
        return out

    def at_end(self) -> bool:
        while not self._buf and self._fill():
            pass
        return not self._buf and self._done
