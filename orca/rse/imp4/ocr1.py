"""OCR1 v2 frames. HPKE is pyhpke over cryptography (RFC 9180 Base).

cryptography 50's public HPKE helper is one-shot and has no AAD or sequence,
so it cannot express this profile. pyhpke is the library named in RSE12_04 §1.
Ephemeral keys come from its public ``derive_key_pair`` (not a test hook),
after the RFC 8937 hedge. Ed25519, X25519, HKDF and ChaCha20-Poly1305 are
the cryptography implementations underneath. This module does not reimplement them.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pyhpke import AEADId, CipherSuite, KDFId, KEMId
from pyhpke.kem_key import KEMKey

from orca.rse.imp1.codec import parse_grant
from orca.rse.imp1.profiles import ROLE_FORGE
from orca.rse.imp1.verdict import FailClosed, Quarantine
from orca.rse.imp3.egress import ZERO_ACCEPTANCE_AUTHORITY
from orca.rse.imp3.ledger import enrolment_key
from orca.rse.imp4.keyless_checker import judge

FRAME_PT = 1 << 20
HEADER_LEN = 210
TAG_LEN = 16
SIG_LEN = 64
MAX_FRAMES = 65536
P25519 = (1 << 255) - 19
_INFO = b"OCR1v2-info"
_SIG = b"OCR1v2-SIG"
_EPH = b"OCR1v2-EPH"
_SUITE = CipherSuite.new(KEMId.DHKEM_X25519_HKDF_SHA256, KDFId.HKDF_SHA256, AEADId.CHACHA20_POLY1305)

HPKE_PROFILE = {
    "mode": "base",
    "kem": 0x0020,
    "kdf": 0x0001,
    "aead": 0x0003,
    "library": "pyhpke",
    "primitives": "cryptography",
    "ikm": "RFC8937-HKDF-then-derive_key_pair",
    "residual": "R-RNG1-not-used",
}

# A Python subprocess with rlimits is not a sandbox and not a security boundary.
CHECKER_ISOLATION = "SYNTHETIC_NOT_A_SANDBOX"
_MAX_REPLAY = 4096
_MAX_COUNTERS = 4096


def _u32(value: int) -> bytes:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise FailClosed("RANGE")
    return value.to_bytes(4, "big")


def _u64(value: int) -> bytes:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise FailClosed("RANGE")
    return value.to_bytes(8, "big")


def frame_plain_len(index: int, count: int, total: int) -> int:
    if count < 1 or index < 0 or index >= count or total < 1:
        raise FailClosed("FRAME")
    size = FRAME_PT if index < count - 1 else total - (count - 1) * FRAME_PT
    if size < 1 or size > FRAME_PT:
        raise FailClosed("FRAME")
    return size


def expected_count(total: int) -> int:
    if total < 1:
        raise FailClosed("TOTAL_LEN")
    count = (total + FRAME_PT - 1) // FRAME_PT
    if not 1 <= count <= MAX_FRAMES:
        raise FailClosed("FRAME_COUNT")
    return count


def enc_canonical(enc: bytes) -> None:
    if not isinstance(enc, (bytes, bytearray)) or len(enc) != 32:
        raise FailClosed("ENC")
    enc = bytes(enc)
    if enc == bytes(32) or (enc[31] & 0x80) or int.from_bytes(enc, "little") >= P25519:
        raise FailClosed("ENC")


def build_header(*, typ: int, recipient_id: bytes, sender_id: bytes, grant_id: bytes, artifact_id: bytes,
                 bundle_digest: bytes, sequence: int, epoch: int, frame_index: int, frame_count: int,
                 total_len: int, enc: bytes) -> bytes:
    if typ not in (1, 2):
        raise FailClosed("TYPE")
    enc_canonical(enc)
    if expected_count(total_len) != frame_count:
        raise FailClosed("FRAME_COUNT")
    frame_plain_len(frame_index, frame_count, total_len)
    header = b"".join((
        b"OCR1", bytes([2, typ]),
        _exact(recipient_id, 32, "RECIPIENT"), _exact(sender_id, 32, "SENDER"),
        _exact(grant_id, 16, "GRANT_ID"), _exact(artifact_id, 32, "ARTIFACT"),
        _exact(bundle_digest, 32, "DIGEST"), _u64(sequence), _u32(epoch),
        _u32(frame_index), _u32(frame_count), _u64(total_len), bytes(enc),
    ))
    if len(header) != HEADER_LEN:
        raise FailClosed("HEADER")
    return header


def info_bytes(header: bytes) -> bytes:
    header = _exact(header, HEADER_LEN, "HEADER")
    return _INFO + b"\x00" + header[0:162] + header[166:178]


def _exact(buf: bytes, n: int, reason: str) -> bytes:
    if not isinstance(buf, (bytes, bytearray)) or len(buf) != n:
        raise FailClosed(reason)
    return bytes(buf)


@dataclass
class CounterJournal:
    """Hedge counter. Session-bound journals are committed before a seal returns.

    A ``CounterJournal`` that lives only on an unbound ``Sender`` does not
    survive a restart. That object is not durable replay enforcement.
    """

    nxt: int = 1
    used: dict[bytes, int] | None = None

    def __post_init__(self) -> None:
        if self.used is None:
            self.used = {}

    def take(self, grant_id: bytes, sequence: int) -> int:
        tag = _exact(grant_id, 16, "GRANT_ID") + _u64(sequence)
        if tag in self.used:
            raise FailClosed("COUNTER_REUSE")
        if len(self.used) >= _MAX_COUNTERS:
            raise FailClosed("JOURNAL")
        value = self.nxt
        if value < 1:
            raise FailClosed("COUNTER_REUSE")
        self.nxt += 1
        self.used[tag] = value
        return value

    def undo(self, grant_id: bytes, sequence: int) -> None:
        tag = _exact(grant_id, 16, "GRANT_ID") + _u64(sequence)
        value = self.used.pop(tag, None)
        if value is not None and self.nxt == value + 1:
            self.nxt = value

    def export(self) -> bytes:
        rows = bytearray()
        for tag, counter in sorted(self.used.items()):
            rows += tag + _u64(counter)
        return b"OCJ1" + bytes([1]) + _u64(self.nxt) + struct.pack(">I", len(self.used)) + bytes(rows)

    @classmethod
    def parse(cls, raw: bytes) -> "CounterJournal":
        data = bytes(raw)
        if len(data) < 4 + 1 + 8 + 4 or data[:4] != b"OCJ1" or data[4] != 1:
            raise FailClosed("JOURNAL")
        nxt = int.from_bytes(data[5:13], "big")
        count = int.from_bytes(data[13:17], "big")
        if count > _MAX_COUNTERS or nxt < 1 or len(data) != 17 + count * 32:
            raise FailClosed("JOURNAL")
        used: dict[bytes, int] = {}
        offset = 17
        for _ in range(count):
            tag = data[offset:offset + 24]
            counter = int.from_bytes(data[offset + 24:offset + 32], "big")
            offset += 32
            if tag in used or counter < 1 or counter >= nxt:
                raise FailClosed("JOURNAL")
            used[tag] = counter
        if used and max(used.values()) >= nxt:
            raise FailClosed("JOURNAL")
        return cls(nxt=nxt, used=used)


class Sender:
    def __init__(self, signing_key: Ed25519PrivateKey, sender_id: bytes, environment: bytes) -> None:
        self.signing_key = signing_key
        self.sender_id = _exact(sender_id, 32, "SENDER")
        self.environment = _exact(environment, 32, "ENVIRONMENT")
        self.counters = CounterJournal()
        self._cached_eph: bytes | None = None

    def _hedge_ikm(self, grant_id: bytes, sequence: int, os_entropy: bytes) -> bytes:
        if self._cached_eph is None:
            self._cached_eph = self.signing_key.sign(_EPH + b"\x00" + self.sender_id + self.environment)
        salt = hashlib.sha256(self._cached_eph).digest()
        counter = self.counters.take(grant_id, sequence)
        info = _exact(grant_id, 16, "GRANT_ID") + _u64(sequence) + _u64(counter)
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(_exact(os_entropy, 32, "ENTROPY"))

    def seal(self, plaintext: bytes, *, typ: int, recipient_id: bytes, recipient_public: bytes, grant_id: bytes,
             artifact_id: bytes, sequence: int, epoch: int, os_entropy: bytes | None = None,
             before_return=None) -> tuple[bytes, ...]:
        plaintext = bytes(plaintext)
        if not plaintext:
            raise FailClosed("TOTAL_LEN")
        self._counter_taken = None
        try:
            frames = self._seal_body(
                plaintext, typ=typ, recipient_id=recipient_id, recipient_public=recipient_public,
                grant_id=grant_id, artifact_id=artifact_id, sequence=sequence, epoch=epoch,
                os_entropy=os_entropy, before_return=before_return,
            )
        except Exception:
            if self._counter_taken is not None:
                self.counters.undo(grant_id, sequence)
                self._counter_taken = None
            raise
        self._counter_taken = None
        return frames

    def _seal_body(self, plaintext: bytes, *, typ: int, recipient_id: bytes, recipient_public: bytes,
                   grant_id: bytes, artifact_id: bytes, sequence: int, epoch: int,
                   os_entropy: bytes | None, before_return) -> tuple[bytes, ...]:
        digest = hashlib.sha256(plaintext).digest()
        count = expected_count(len(plaintext))
        skeleton = build_header(
            typ=typ, recipient_id=recipient_id, sender_id=self.sender_id, grant_id=grant_id,
            artifact_id=artifact_id, bundle_digest=digest, sequence=sequence, epoch=epoch,
            frame_index=0, frame_count=count, total_len=len(plaintext),
            enc=b"\x01" + bytes(31),
        )
        info = info_bytes(skeleton)
        entropy = os.urandom(32) if os_entropy is None else os_entropy
        ikm = self._hedge_ikm(grant_id, sequence, entropy)
        self._counter_taken = _exact(grant_id, 16, "GRANT_ID") + _u64(sequence)
        ephemeral = _SUITE.kem.derive_key_pair(ikm)
        recipient = KEMKey.from_pyca_cryptography_key(X25519PublicKey.from_public_bytes(_exact(recipient_public, 32, "KEM")))
        enc, context = _SUITE.create_sender_context(recipient, info, eks=ephemeral)
        enc_canonical(enc)
        frames = []
        cursor = 0
        for index in range(count):
            size = frame_plain_len(index, count, len(plaintext))
            header = build_header(
                typ=typ, recipient_id=recipient_id, sender_id=self.sender_id, grant_id=grant_id,
                artifact_id=artifact_id, bundle_digest=digest, sequence=sequence, epoch=epoch,
                frame_index=index, frame_count=count, total_len=len(plaintext), enc=enc,
            )
            ciphertext = context.seal(plaintext[cursor:cursor + size], header)
            cursor += size
            if len(ciphertext) != size + TAG_LEN:
                raise FailClosed("CIPHERTEXT")
            signature = self.signing_key.sign(_SIG + b"\x00" + header + ciphertext)
            frame = header + ciphertext + signature
            if len(frame) != HEADER_LEN + size + TAG_LEN + SIG_LEN:
                raise FailClosed("FRAME")
            frames.append(frame)
        if self._cached_eph is not None and any(self._cached_eph in frame for frame in frames):
            raise FailClosed("EPH_EXPOSED")
        if before_return is not None:
            before_return()
        return tuple(frames)


class RecipientJournal:
    """Session-owned replay journal. A caller-supplied replacement is not authoritative."""

    def __init__(self) -> None:
        self.last_sequence = 0
        self._seen_sequence: set[tuple[bytes, int]] = set()
        self._enc: dict[bytes, bytes] = {}
        self._quarantined: set[bytes] = set()
        self._rows: list[tuple[bytes, int, bytes, bytes]] = []

    def grant_quarantined(self, grant_id: bytes) -> bool:
        return bytes(grant_id) in self._quarantined

    def quarantine_grant(self, grant_id: bytes) -> None:
        self._quarantined.add(bytes(grant_id))

    def reject_replay(self, *, grant_id: bytes, sequence: int, enc: bytes, bundle_digest: bytes) -> None:
        grant_id = bytes(grant_id)
        if grant_id in self._quarantined:
            raise Quarantine("ENC_DIVERGENCE")
        key = (grant_id, sequence)
        if key in self._seen_sequence or (self._seen_sequence and sequence <= self.last_sequence):
            raise FailClosed("REPLAY")
        prior = self._enc.get(bytes(enc))
        if prior is not None and prior != bundle_digest:
            self._quarantined.add(grant_id)
            raise Quarantine("ENC_DIVERGENCE")
        if prior is not None:
            raise FailClosed("REPLAY")

    def admit(self, *, grant_id: bytes, sequence: int, enc: bytes, bundle_digest: bytes) -> None:
        self.reject_replay(grant_id=grant_id, sequence=sequence, enc=enc, bundle_digest=bundle_digest)
        if len(self._rows) >= _MAX_REPLAY:
            raise FailClosed("JOURNAL")
        self._enc[bytes(enc)] = bytes(bundle_digest)
        self._seen_sequence.add((bytes(grant_id), sequence))
        self._rows.append((bytes(grant_id), sequence, bytes(enc), bytes(bundle_digest)))
        self.last_sequence = sequence

    def forget(self, *, grant_id: bytes, sequence: int, enc: bytes) -> None:
        key = (bytes(grant_id), sequence)
        self._seen_sequence.discard(key)
        self._rows = [row for row in self._rows if (row[0], row[1]) != key]
        self._enc.pop(bytes(enc), None)
        self.last_sequence = max((row[1] for row in self._rows), default=0)

    def export(self) -> bytes:
        quarantined = b"".join(sorted(self._quarantined))
        rows = bytearray()
        for grant_id, sequence, enc, digest in self._rows:
            rows += grant_id + _u64(sequence) + enc + digest
        return b"".join((
            b"ORJ1", bytes([1]), _u64(self.last_sequence),
            struct.pack(">I", len(self._quarantined)), quarantined,
            struct.pack(">I", len(self._rows)), bytes(rows),
        ))

    @classmethod
    def parse(cls, raw: bytes) -> "RecipientJournal":
        data = bytes(raw)
        if len(data) < 4 + 1 + 8 + 8 or data[:4] != b"ORJ1" or data[4] != 1:
            raise FailClosed("JOURNAL")
        last_sequence = int.from_bytes(data[5:13], "big")
        offset = 13
        qcount = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if qcount > 256 or offset + qcount * 16 > len(data):
            raise FailClosed("JOURNAL")
        quarantined = set()
        for _ in range(qcount):
            grant_id = data[offset:offset + 16]
            offset += 16
            if grant_id in quarantined:
                raise FailClosed("JOURNAL")
            quarantined.add(grant_id)
        if offset + 4 > len(data):
            raise FailClosed("JOURNAL")
        count = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        row_len = 16 + 8 + 32 + 32
        if count > _MAX_REPLAY or offset + count * row_len != len(data):
            raise FailClosed("JOURNAL")
        journal = cls()
        journal._quarantined = quarantined
        highest = 0
        for _ in range(count):
            grant_id = data[offset:offset + 16]
            sequence = int.from_bytes(data[offset + 16:offset + 24], "big")
            enc = data[offset + 24:offset + 56]
            digest = data[offset + 56:offset + 88]
            offset += row_len
            key = (grant_id, sequence)
            if key in journal._seen_sequence or enc in journal._enc:
                raise FailClosed("JOURNAL")
            journal._seen_sequence.add(key)
            journal._enc[enc] = digest
            journal._rows.append((grant_id, sequence, enc, digest))
            highest = max(highest, sequence)
        if (count == 0 and last_sequence != 0) or (count and last_sequence != highest):
            raise FailClosed("JOURNAL")
        journal.last_sequence = last_sequence
        return journal


def parse_frame(frame: bytes) -> dict:
    if not isinstance(frame, (bytes, bytearray)) or len(frame) < HEADER_LEN + TAG_LEN + SIG_LEN:
        raise FailClosed("TRUNCATED")
    frame = bytes(frame)
    header = frame[:HEADER_LEN]
    if header[:4] != b"OCR1" or header[4] != 2:
        raise FailClosed("VERSION" if header[:4] == b"OCR1" else "MAGIC")
    typ = header[5]
    if typ not in (1, 2):
        raise FailClosed("TYPE")
    fields = {
        "type": typ,
        "recipient_id": header[6:38],
        "sender_id": header[38:70],
        "grant_id": header[70:86],
        "artifact_id": header[86:118],
        "bundle_digest": header[118:150],
        "sequence": int.from_bytes(header[150:158], "big"),
        "epoch": int.from_bytes(header[158:162], "big"),
        "frame_index": int.from_bytes(header[162:166], "big"),
        "frame_count": int.from_bytes(header[166:170], "big"),
        "total_len": int.from_bytes(header[170:178], "big"),
        "enc": header[178:210],
    }
    enc_canonical(fields["enc"])
    if expected_count(fields["total_len"]) != fields["frame_count"]:
        raise FailClosed("FRAME_COUNT")
    plain = frame_plain_len(fields["frame_index"], fields["frame_count"], fields["total_len"])
    expect = HEADER_LEN + plain + TAG_LEN + SIG_LEN
    if len(frame) != expect:
        raise FailClosed("FRAME")
    rebuilt = build_header(typ=typ, recipient_id=fields["recipient_id"], sender_id=fields["sender_id"],
                           grant_id=fields["grant_id"], artifact_id=fields["artifact_id"],
                           bundle_digest=fields["bundle_digest"], sequence=fields["sequence"],
                           epoch=fields["epoch"], frame_index=fields["frame_index"],
                           frame_count=fields["frame_count"], total_len=fields["total_len"], enc=fields["enc"])
    if rebuilt != header:
        raise FailClosed("NONCANONICAL")
    fields["header"] = header
    fields["ciphertext"] = frame[HEADER_LEN:-SIG_LEN]
    fields["signature"] = frame[-SIG_LEN:]
    fields["raw"] = frame
    return fields


def _same_bundle(frames: list[dict]) -> None:
    if len(frames) != frames[0]["frame_count"]:
        raise FailClosed("FRAME_COUNT")
    keys = ("type", "recipient_id", "sender_id", "grant_id", "artifact_id", "bundle_digest",
            "sequence", "epoch", "frame_count", "total_len", "enc")
    for index, frame in enumerate(frames):
        if frame["frame_index"] != index:
            raise FailClosed("FRAME_ORDER")
        if any(frame[key] != frames[0][key] for key in keys):
            raise FailClosed("CROSS_BUNDLE")


def verify_signatures(frames: list[dict], sender_public: bytes) -> None:
    key = Ed25519PublicKey.from_public_bytes(_exact(sender_public, 32, "SENDER_KEY"))
    for frame in frames:
        try:
            key.verify(frame["signature"], _SIG + b"\x00" + frame["header"] + frame["ciphertext"])
        except Exception as exc:
            raise FailClosed("BAD_SIGNATURE") from exc


def structural_phase(frames: tuple[bytes, ...] | list[bytes], *, sender_public: bytes) -> list[dict]:
    """Phase-1 checks. No private key and no HPKE open."""
    if not frames:
        raise FailClosed("FRAME")
    parsed = [parse_frame(frame) for frame in frames]
    _same_bundle(parsed)
    verify_signatures(parsed, sender_public)
    return parsed


def _reject_zero_shared(recipient_private: X25519PrivateKey, enc: bytes) -> None:
    """Map the library's low-order X25519 failure onto the frozen rejection.

    cryptography raises ``ValueError`` from ``exchange`` for a low-order
    public key. That exception is not a new primitive and it is not success.
    """
    try:
        public = X25519PublicKey.from_public_bytes(enc)
        shared = recipient_private.exchange(public)
    except FailClosed:
        raise
    except (ValueError, TypeError) as exc:
        raise FailClosed("ZERO_SHARED_SECRET") from exc
    if shared == bytes(32):
        raise FailClosed("ZERO_SHARED_SECRET")


def open_frames(frames: tuple[bytes, ...] | list[bytes], *, sender_public: bytes,
                recipient_private: X25519PrivateKey, journal: RecipientJournal) -> bytes:
    if not isinstance(journal, RecipientJournal):
        raise FailClosed("REPLAY")
    parsed = structural_phase(frames, sender_public=sender_public)
    first = parsed[0]
    journal.reject_replay(
        grant_id=first["grant_id"], sequence=first["sequence"], enc=first["enc"],
        bundle_digest=first["bundle_digest"],
    )
    _reject_zero_shared(recipient_private, first["enc"])
    info = info_bytes(first["header"])
    secret = KEMKey.from_pyca_cryptography_key(recipient_private)
    try:
        context = _SUITE.create_recipient_context(first["enc"], secret, info)
    except Exception as exc:
        raise FailClosed("HPKE") from exc
    chunks = []
    for frame in parsed:
        try:
            chunks.append(context.open(frame["ciphertext"], frame["header"]))
        except Exception as exc:
            raise FailClosed("AEAD") from exc
    plaintext = b"".join(chunks)
    if len(plaintext) != first["total_len"] or hashlib.sha256(plaintext).digest() != first["bundle_digest"]:
        raise FailClosed("DIGEST")
    journal.admit(
        grant_id=first["grant_id"], sequence=first["sequence"], enc=first["enc"],
        bundle_digest=first["bundle_digest"],
    )
    return plaintext


def run_keyless_checker(plaintext: bytes) -> str:
    """Synthetic checker. ``CHECKER_ISOLATION`` is not a sandbox.

    The child is a Python subprocess. Resource-limit failures fail closed
    instead of running with no limit. The temporary directory is removed
    before this function returns.
    """
    paths = [os.path.abspath(item or os.getcwd()) for item in sys.path]
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(paths),
        "PATH": "/usr/bin:/bin",
    }
    work = tempfile.mkdtemp(prefix="rse-keyless-")
    try:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "orca.rse.imp4.keyless_checker"],
                input=plaintext, capture_output=True, timeout=2, check=False, env=env,
                cwd=work, preexec_fn=_limits,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise FailClosed("CHECKER") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if proc.returncode != 0 or proc.stdout != judge(plaintext) or len(proc.stdout) > 64:
        raise FailClosed("CHECKER")
    text = proc.stdout.decode("ascii", "strict").strip()
    if text.startswith("STRUCTURAL_OK "):
        return "STRUCTURAL_OK"
    if text == "STRUCTURAL_REJECT":
        return "STRUCTURAL_REJECT"
    raise FailClosed("CHECKER")


def _limits() -> None:
    import resource
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
        resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024, 128 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    except (OSError, ValueError):
        # macOS can reject these limits. Do not continue unlimited.
        os._exit(71)


def ingest_phase1(session, grant_id: bytes, frames: list[bytes], **extra) -> dict:
    if extra:
        raise FailClosed("UNEXPECTED_ARGUMENT")
    grant, sender_public = _authorized_view(session, grant_id, allow_active=False)
    parsed = structural_phase(frames, sender_public=sender_public)
    _bind_grant(parsed, grant, session)
    return {
        "quarantine": hashlib.sha256(b"".join(frames)).digest(),
        "acceptance": ZERO_ACCEPTANCE_AUTHORITY,
        "decrypted": False,
    }


def ingest_phase2(session, grant_id: bytes, frames: list[bytes], *, recipient_private: X25519PrivateKey,
                  quarantine: bytes, **extra) -> dict:
    """Open a bundle with the session's recipient journal.

    A caller journal cannot be substituted or omitted. Replay admission is
    committed before this function returns success. ``ENC_DIVERGENCE`` is
    persisted before it is reported as handled.
    """
    if extra:
        raise FailClosed("UNEXPECTED_ARGUMENT")
    if session.recipient.grant_quarantined(grant_id):
        raise Quarantine("ENC_DIVERGENCE")
    if session.machine.get(grant_id).state != "ACTIVE":
        raise FailClosed("GRANT_STATE")
    if hashlib.sha256(b"".join(bytes(frame) for frame in frames)).digest() != bytes(quarantine):
        raise FailClosed("QUARANTINE")
    grant, sender_public = _authorized_view(session, grant_id, allow_active=True)
    parsed = structural_phase(frames, sender_public=sender_public)
    _bind_grant(parsed, grant, session)
    if session.freshness.sequence_forfeited(parsed[0]["sequence"]):
        raise FailClosed("FORFEITED_SEQUENCE")
    admitted = False
    try:
        try:
            plaintext = open_frames(
                frames, sender_public=sender_public, recipient_private=recipient_private,
                journal=session.recipient,
            )
        except Quarantine as exc:
            if str(exc) == "ENC_DIVERGENCE":
                session.durable_commit()
            raise
        admitted = True
        verdict = run_keyless_checker(plaintext)
        session.durable_commit()
    except FailClosed:
        if admitted:
            session.recipient.forget(
                grant_id=parsed[0]["grant_id"], sequence=parsed[0]["sequence"], enc=parsed[0]["enc"],
            )
        raise
    return {
        "verdict": verdict,
        "digest": hashlib.sha256(plaintext).digest(),
        "acceptance": ZERO_ACCEPTANCE_AUTHORITY,
        "executable": False,
    }


def _authorized_view(session, grant_id: bytes, *, allow_active: bool):
    from orca.rse.imp1.codec import parse_registry
    slot = session.machine.get(grant_id)
    allowed = {"ACTIVE"} if allow_active else {"CONSUMER_CONFIRMED", "ACTIVE"}
    if slot.state not in allowed:
        raise FailClosed("GRANT_STATE")
    grant = parse_grant(session._grants[bytes(grant_id)])
    if grant.klass != ord("V"):
        raise FailClosed("GRANT_CLASS")
    registry = parse_registry(session.registry_raw)
    sender_public = enrolment_key(registry, grant.tail["sender_role_id"], expect_type=ROLE_FORGE)
    return grant, sender_public


def _bind_grant(frames: list[dict], grant, session) -> None:
    first = frames[0]
    if first["grant_id"] != grant.grant_id or first["artifact_id"] != grant.tail["artifact_entry_id"]:
        raise FailClosed("BINDING")
    if first["sender_id"] != grant.tail["sender_role_id"] or first["recipient_id"] != session.role_id:
        raise FailClosed("BINDING")
    if first["epoch"] != session.epoch or first["epoch"] != grant.incident_epoch:
        raise FailClosed("EPOCH")
    if not grant.tail["seq_first"] <= first["sequence"] <= grant.tail["seq_last"]:
        raise FailClosed("SEQUENCE")


def ochk(payload: bytes) -> bytes:
    if not payload:
        raise FailClosed("PLAINTEXT")
    return b"OCHK" + bytes([1]) + len(payload).to_bytes(4, "big") + payload


def admit_rfc9180_base() -> None:
    """RFC 9180 A.2.1 base mode, sequences 0..2. Library admission, not a grant."""
    ikm_e = bytes.fromhex("909a9b35d3dc4713a5e72a4da274b55d3d3821a37e5d099e74a647db583a904b")
    ikm_r = bytes.fromhex("1ac01f181fdf9f352797655161c58b75c656a6cc2716dcb66372da835542e1df")
    info = bytes.fromhex("4f6465206f6e2061204772656369616e2055726e")
    pt = bytes.fromhex("4265617574792069732074727574682c20747275746820626561757479")
    aads = [bytes.fromhex(item) for item in ("436f756e742d30", "436f756e742d31", "436f756e742d32")]
    cts = [bytes.fromhex(item) for item in (
        "1c5250d8034ec2b784ba2cfd69dbdb8af406cfe3ff938e131f0def8c8b60b4db21993c62ce81883d2dd1b51a28",
        "6b53c051e4199c518de79594e1c4ab18b96f081549d45ce015be002090bb119e85285337cc95ba5f59992dc98c",
        "71146bd6795ccc9c49ce25dda112a48f202ad220559502cef1f34271e0cb4b02b4f10ecac6f48c32f878fae86b",
    )]
    enc_expect = bytes.fromhex("1afa08d3dec047a643885163f1180476fa7ddb54c6a8029ea33f95796bf2ac4a")
    sender_key = _SUITE.kem.derive_key_pair(ikm_e)
    recipient_key = _SUITE.kem.derive_key_pair(ikm_r)
    enc, context = _SUITE.create_sender_context(recipient_key.public_key, info, eks=sender_key)
    if enc != enc_expect:
        raise FailClosed("HPKE_VECTOR")
    opened = _SUITE.create_recipient_context(enc, recipient_key.private_key, info)
    for aad, ct in zip(aads, cts):
        if context.seal(pt, aad) != ct:
            raise FailClosed("HPKE_VECTOR")
        if opened.open(ct, aad) != pt:
            raise FailClosed("HPKE_VECTOR")
