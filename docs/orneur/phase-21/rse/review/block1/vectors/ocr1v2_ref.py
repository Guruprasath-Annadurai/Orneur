"""REVIEW_REFERENCE_ONLY: independent OCR1 v2 reference written from RSE12_04 sections 2-7 (frozen text).

Purpose: derive EXPECTED known-answer values and negative-test outcomes for the audit of IMP-4
without using the implementation under audit. Synthetic TEST-ONLY keys (public, deterministic labels).
Never import from production code. Not a substitute for the implementation; not a security boundary.

Spec references (docs/orneur/phase-21/rse/v1.2/RSE12_04_OCR1_GRANTS_ENROLMENT.md):
  section 2 profile, section 3 layout, section 4 sender, section 5 ephemeral wrapper (RFC 8937), section 6 receiver, section 7 frame rules.
"""
import hashlib
import hmac
import struct

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

import hpke_ref as H

HDR = 210
TAG = 16
SIG = 64
FRAME_PT = 1 << 20          # frozen production value (section 3)
MAXF = 65536
P25519 = (1 << 255) - 19
MAGIC = b"OCR1"
VERSION = 2
INFO_DOMAIN = b"OCR1v2-info" + b"\x00"
SIG_DOMAIN = b"OCR1v2-SIG" + b"\x00"
EPH_DOMAIN = b"OCR1v2-EPH" + b"\x00"


def sha256(b):
    return hashlib.sha256(b).digest()


def test_seed(label: str) -> bytes:
    """Public, deterministic TEST-ONLY seed. Nothing here is secret."""
    return sha256(b"RSE-REVIEW-BLOCK1-TEST-ONLY|" + label.encode())


def ed25519_from_label(label):
    return Ed25519PrivateKey.from_private_bytes(test_seed(label))


def ed_pub(sk):
    return sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def x25519_from_label(label):
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    return X25519PrivateKey.from_private_bytes(test_seed(label))


def hkdf_extract(salt, ikm):
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk, info, n):
    return H.expand(prk, info, n)


def ephemeral_ikm(sender_ed_sk, sender_id, env_digest, grant_id, sequence, counter, g32):
    """RFC 8937 randomness wrapper as pinned by RSE12_04 section 5.
    ikm = Expand(Extract(salt=SHA256(Sig(sk, tag1)), IKM=G(32)), tag2, 32); tag1/tag2 as in the spec."""
    tag1 = EPH_DOMAIN + sender_id + env_digest
    tag2 = grant_id + struct.pack(">Q", sequence) + struct.pack(">Q", counter)
    salt = sha256(sender_ed_sk.sign(tag1))
    return hkdf_expand(hkdf_extract(salt, g32), tag2, 32)


def header(typ, recipient_id, sender_id, grant_id, artifact_id, bundle_digest, sequence, epoch, idx, count, total, enc):
    h = (MAGIC + bytes([VERSION, typ]) + recipient_id + sender_id + grant_id + artifact_id + bundle_digest
         + struct.pack(">Q", sequence) + struct.pack(">I", epoch) + struct.pack(">I", idx)
         + struct.pack(">I", count) + struct.pack(">Q", total) + enc)
    assert len(h) == HDR
    return h


def info_of(h):
    return INFO_DOMAIN + h[0:162] + h[166:178]


def pt_len(i, count, total):
    return FRAME_PT if i < count - 1 else total - (count - 1) * FRAME_PT


def seal_bundle(plaintext, *, typ, recipient_id, sender_id, grant_id, artifact_id, sequence, epoch,
                sender_sk, recipient_kem_pk, ikm_e, frame_pt=None):
    global FRAME_PT
    saved = FRAME_PT
    if frame_pt:
        FRAME_PT = frame_pt
    try:
        total = len(plaintext)
        count = -(-total // FRAME_PT)
        digest = sha256(plaintext)
        ss, enc = H.encap(recipient_kem_pk, ikm_e)
        h0 = header(typ, recipient_id, sender_id, grant_id, artifact_id, digest, sequence, epoch, 0, count, total, enc)
        key, base_nonce, _, _ = H.key_schedule(ss, info_of(h0))
        frames = []
        for i in range(count):
            hi = header(typ, recipient_id, sender_id, grant_id, artifact_id, digest, sequence, epoch, i, count, total, enc)
            chunk = plaintext[i * FRAME_PT:(i + 1) * FRAME_PT]
            ct = H.seal(key, base_nonce, i, hi, chunk)
            sig = sender_sk.sign(SIG_DOMAIN + hi + ct)
            frames.append(hi + ct + sig)
        return frames
    finally:
        FRAME_PT = saved


# ---------------- receiver (Phase 1 key-absent, Phase 2 key-present) ----------------

class Reject(Exception):
    def __init__(self, phase, reason):
        super().__init__(f"{phase}:{reason}")
        self.phase, self.reason = phase, reason


def parse_header(frame, frame_pt=None):
    fp = frame_pt or FRAME_PT
    if len(frame) < HDR + TAG + SIG:
        raise Reject(1, "TRUNCATED")
    h = frame[:HDR]
    if h[0:4] != MAGIC:
        raise Reject(1, "MAGIC")
    if h[4] != VERSION:
        raise Reject(1, "UNKNOWN_VERSION")
    typ = h[5]
    if typ not in (1, 2):
        raise Reject(1, "TYPE")
    f = dict(typ=typ, recipient=h[6:38], sender=h[38:70], grant=h[70:86], artifact=h[86:118], digest=h[118:150],
             seq=struct.unpack(">Q", h[150:158])[0], epoch=struct.unpack(">I", h[158:162])[0],
             idx=struct.unpack(">I", h[162:166])[0], count=struct.unpack(">I", h[166:170])[0],
             total=struct.unpack(">Q", h[170:178])[0], enc=h[178:210], header=h)
    if not (1 <= f["count"] <= MAXF) or f["total"] < 1 or f["idx"] >= f["count"]:
        raise Reject(1, "COUNT_OR_INDEX")
    if f["count"] != -(-f["total"] // fp):
        raise Reject(1, "COUNT_TOTAL_MISMATCH")
    e = f["enc"]
    if e == bytes(32) or (e[31] & 0x80) or int.from_bytes(e, "little") >= P25519:
        raise Reject(1, "ENC_NONCANONICAL")
    pl = fp if f["idx"] < f["count"] - 1 else f["total"] - (f["count"] - 1) * fp
    if len(frame) != HDR + pl + TAG + SIG:
        raise Reject(1, "LENGTH")
    f["ct"] = frame[HDR:HDR + pl + TAG]
    f["sig"] = frame[HDR + pl + TAG:]
    return f


def phase1(frames, *, self_id, enrolled_senders, expected_grant, frame_pt=None):
    """Key-absent checks from RSE12_04 section 6 Phase 1 (a)-(f) restricted to what a reference can state.
    enrolled_senders: {sender_id: ed25519_public_key_bytes}. expected_grant: dict(sender, artifact, seq_first, seq_last, epoch, grant_id)."""
    fs = [parse_header(fr, frame_pt) for fr in frames]
    if not fs or len(fs) != fs[0]["count"]:
        raise Reject(1, "FRAME_COUNT")
    for i, f in enumerate(fs):
        if f["idx"] != i:
            raise Reject(1, "FRAME_ORDER")
        for k in ("typ", "recipient", "sender", "grant", "artifact", "digest", "seq", "epoch", "count", "total", "enc"):
            if f[k] != fs[0][k]:
                raise Reject(1, "CROSS_BUNDLE")
    f0 = fs[0]
    if f0["recipient"] != self_id:
        raise Reject(1, "RECIPIENT")
    pk = enrolled_senders.get(f0["sender"])
    if pk is None:
        raise Reject(1, "SENDER_UNKNOWN")
    g = expected_grant
    if (f0["sender"] != g["sender"] or f0["artifact"] != g["artifact"] or f0["grant"] != g["grant_id"]
            or not (g["seq_first"] <= f0["seq"] <= g["seq_last"]) or f0["epoch"] != g["epoch"]):
        raise Reject(1, "GRANT_MISMATCH")
    for f in fs:
        try:
            Ed25519PublicKey.from_public_bytes(pk).verify(f["sig"], SIG_DOMAIN + f["header"] + f["ct"])
        except InvalidSignature:
            raise Reject(1, "SIGNATURE")
    return fs


def phase2(fs, recipient_kem_sk):
    f0 = fs[0]
    try:
        ss = H.decap(f0["enc"], recipient_kem_sk)
    except ValueError:
        raise Reject(2, "ZERO_SHARED_SECRET")
    key, base_nonce, _, _ = H.key_schedule(ss, info_of(f0["header"]))
    out = b""
    for f in fs:
        try:
            out += H.open_(key, base_nonce, f["idx"], f["header"], f["ct"])
        except InvalidTag:
            raise Reject(2, "AEAD")
    if sha256(out) != f0["digest"]:
        raise Reject(2, "DIGEST")
    if len(out) != f0["total"]:
        raise Reject(2, "LENGTH")
    return out
