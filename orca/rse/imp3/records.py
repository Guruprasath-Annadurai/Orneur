"""Fixed carried-medium records from RSE12_02 §3.

OCA1 states its signature domain. OCK1 and OCH1 use that same
``"<magic>-SIG" || 0x00 || prefix`` pattern. The leaf record OEL1 and the
OCI1 width are the recommended fixed layouts where the freeze names the
fields but does not number every width. See the block-1 evidence note.
"""

from __future__ import annotations

import hashlib
import struct

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from orca.rse.imp1.verdict import FailClosed

OEL1_LEN = 102
OCK1_LEN = 181
OCA1_LEN = 217
OCH1_LEN = 181
OCI1_LEN = 2102
OCP1_LEN = 2315
PROOF_SLOTS = 64

KIND_BOOT = 1
KIND_CHALLENGE = 2
KIND_MAINTENANCE = 3
KIND_GRANT = 4
KIND_CONSUMPTION = 5
KIND_RESULT = 6
KIND_ACCEPTANCE = 7
KIND_INTERRUPTION = 8
KIND_REVOCATION = 9
KINDS = frozenset(range(1, 10))
NON_STATE_CHANGING = frozenset({KIND_BOOT, KIND_CHALLENGE, KIND_MAINTENANCE})

_OCK1_SIG = b"OCK1-SIG"
_OCA1_SIG = b"OCA1-SIG"
_OCH1_SIG = b"OCH1-SIG"


def _u32(value: int) -> bytes:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise FailClosed("RANGE")
    return struct.pack(">I", value)


def _u64(value: int) -> bytes:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFFFFFFFFFF:
        raise FailClosed("RANGE")
    return struct.pack(">Q", value)


def _b32(buf: bytes, reason: str) -> bytes:
    if not isinstance(buf, (bytes, bytearray)) or len(buf) != 32:
        raise FailClosed(reason)
    return bytes(buf)


def _exact(buf: bytes, n: int, reason: str) -> bytes:
    if not isinstance(buf, (bytes, bytearray)) or len(buf) != n:
        raise FailClosed(reason)
    return bytes(buf)


def _sign(key: Ed25519PrivateKey, domain: bytes, body: bytes) -> bytes:
    return key.sign(domain + b"\x00" + body)


def _verify(public: bytes, domain: bytes, body: bytes, signature: bytes) -> None:
    if len(public) != 32 or len(signature) != 64:
        raise FailClosed("SIG_LEN")
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, domain + b"\x00" + body)
    except Exception as exc:
        raise FailClosed("BAD_SIGNATURE") from exc


def record_id(record: bytes) -> bytes:
    """Identity of the canonical record bytes. Not the Merkle leaf hash."""
    return hashlib.sha256(bytes(record)).digest()


def pack_record(*, kind: int, index: int, payload_digest: bytes, grant_id: bytes, epoch: int,
                registry_version: int, prev_digest: bytes) -> bytes:
    if kind not in KINDS:
        raise FailClosed("RECORD_KIND")
    body = b"".join((
        b"OEL1", bytes([1, kind]), _u64(index), _b32(payload_digest, "PAYLOAD"),
        _exact(grant_id, 16, "GRANT_ID"), _u32(epoch), _u32(registry_version), _b32(prev_digest, "PREV"),
    ))
    if len(body) != OEL1_LEN:
        raise FailClosed("RECORD_LEN")
    return body


def parse_record(raw: bytes) -> dict:
    data = _exact(raw, OEL1_LEN, "RECORD_LEN")
    if data[:4] != b"OEL1" or data[4] != 1:
        raise FailClosed("RECORD")
    kind = data[5]
    if kind not in KINDS:
        raise FailClosed("RECORD_KIND")
    parsed = {
        "kind": kind,
        "index": struct.unpack_from(">Q", data, 6)[0],
        "payload_digest": data[14:46],
        "grant_id": data[46:62],
        "epoch": struct.unpack_from(">I", data, 62)[0],
        "registry_version": struct.unpack_from(">I", data, 66)[0],
        "prev_digest": data[70:102],
        "raw": data,
    }
    if pack_record(**{k: parsed[k] for k in (
        "kind", "index", "payload_digest", "grant_id", "epoch", "registry_version", "prev_digest",
    )}) != data:
        raise FailClosed("NONCANONICAL")
    return parsed


def pack_checkpoint(*, log_id: bytes, tree_size: int, root: bytes, epoch: int, registry_version: int,
                    prev_checkpoint_digest: bytes, role_key: Ed25519PrivateKey) -> bytes:
    if tree_size < 1:
        raise FailClosed("EMPTY_TREE")
    body = b"".join((
        b"OCK1", bytes([1]), _b32(log_id, "LOG_ID"), _u64(tree_size), _b32(root, "ROOT"),
        _u32(epoch), _u32(registry_version), _b32(prev_checkpoint_digest, "PREV_CHECKPOINT"),
    ))
    signed = body + _sign(role_key, _OCK1_SIG, body)
    if len(signed) != OCK1_LEN:
        raise FailClosed("CHECKPOINT_LEN")
    return signed


def parse_checkpoint(raw: bytes, public_key: bytes | None = None) -> dict:
    data = _exact(raw, OCK1_LEN, "CHECKPOINT_LEN")
    if data[:4] != b"OCK1" or data[4] != 1:
        raise FailClosed("CHECKPOINT")
    body, signature = data[:-64], data[-64:]
    if public_key is not None:
        _verify(public_key, _OCK1_SIG, body, signature)
    tree_size = struct.unpack_from(">Q", body, 37)[0]
    if tree_size < 1:
        raise FailClosed("EMPTY_TREE")
    return {
        "log_id": body[5:37],
        "tree_size": tree_size,
        "root": body[45:77],
        "epoch": struct.unpack_from(">I", body, 77)[0],
        "registry_version": struct.unpack_from(">I", body, 81)[0],
        "prev_checkpoint_digest": body[85:117],
        "body": body,
        "digest": hashlib.sha256(body).digest(),
        "raw": data,
    }


def pack_ack(*, witness_id: bytes, source_role_id: bytes, log_id: bytes, tree_size: int, root: bytes,
             epoch: int, witness_time: int, witness_key: Ed25519PrivateKey) -> bytes:
    body = b"".join((
        b"OCA1", bytes([1]), _b32(witness_id, "WITNESS"), _b32(source_role_id, "SOURCE"),
        _b32(log_id, "LOG_ID"), _u64(tree_size), _b32(root, "ROOT"), _u32(epoch), _u64(witness_time),
    ))
    signed = body + _sign(witness_key, _OCA1_SIG, body)
    if len(signed) != OCA1_LEN:
        raise FailClosed("ACK_LEN")
    return signed


def parse_ack(raw: bytes, public_key: bytes | None = None) -> dict:
    data = _exact(raw, OCA1_LEN, "ACK_LEN")
    if data[:4] != b"OCA1" or data[4] != 1:
        raise FailClosed("ACK")
    body, signature = data[:-64], data[-64:]
    if public_key is not None:
        _verify(public_key, _OCA1_SIG, body, signature)
    return {
        "witness_id": body[5:37],
        "source_role_id": body[37:69],
        "log_id": body[69:101],
        "tree_size": struct.unpack_from(">Q", body, 101)[0],
        "root": body[109:141],
        "epoch": struct.unpack_from(">I", body, 141)[0],
        "witness_time": struct.unpack_from(">Q", body, 145)[0],
        "raw": data,
    }


def pack_challenge(*, role_id: bytes, challenge: bytes, challenge_seq: int, next_sequence: int,
                   role_log_head: bytes, role_key: Ed25519PrivateKey) -> bytes:
    body = b"".join((
        b"OCH1", bytes([1]), _b32(role_id, "ROLE"), _b32(challenge, "CHALLENGE"),
        _u64(challenge_seq), _u64(next_sequence), _b32(role_log_head, "HEAD"),
    ))
    signed = body + _sign(role_key, _OCH1_SIG, body)
    if len(signed) != OCH1_LEN:
        raise FailClosed("CHALLENGE_LEN")
    return signed


def parse_challenge(raw: bytes, public_key: bytes | None = None) -> dict:
    data = _exact(raw, OCH1_LEN, "CHALLENGE_LEN")
    if data[:4] != b"OCH1" or data[4] != 1:
        raise FailClosed("CHALLENGE_RECORD")
    body, signature = data[:-64], data[-64:]
    if public_key is not None:
        _verify(public_key, _OCH1_SIG, body, signature)
    return {
        "role_id": body[5:37],
        "challenge": body[37:69],
        "challenge_seq": struct.unpack_from(">Q", body, 69)[0],
        "next_sequence": struct.unpack_from(">Q", body, 77)[0],
        "role_log_head": body[85:117],
        "raw": data,
    }


def pack_inclusion(*, leaf: bytes, index: int, tree_size: int, proof: tuple[bytes, ...]) -> bytes:
    if len(proof) > PROOF_SLOTS:
        raise FailClosed("PROOF")
    slots = b"".join(proof) + bytes(32 * (PROOF_SLOTS - len(proof)))
    body = b"".join((
        b"OCI1", bytes([1]), _b32(leaf, "LEAF"), _u64(index), _u64(tree_size), bytes([len(proof)]), slots,
    ))
    if len(body) != OCI1_LEN:
        raise FailClosed("INCLUSION_LEN")
    return body


def parse_inclusion(raw: bytes) -> dict:
    data = _exact(raw, OCI1_LEN, "INCLUSION_LEN")
    if data[:4] != b"OCI1" or data[4] != 1:
        raise FailClosed("INCLUSION")
    count = data[53]
    if count > PROOF_SLOTS:
        raise FailClosed("PROOF")
    slots = data[54:]
    if len(slots) != PROOF_SLOTS * 32:
        raise FailClosed("INCLUSION_LEN")
    proof = tuple(slots[i * 32:(i + 1) * 32] for i in range(count))
    rest = slots[count * 32:]
    if rest != bytes(len(rest)):
        raise FailClosed("PROOF_PADDING")
    return {
        "leaf": data[5:37],
        "index": struct.unpack_from(">Q", data, 37)[0],
        "tree_size": struct.unpack_from(">Q", data, 45)[0],
        "proof": proof,
        "raw": data,
    }


def pack_witness_request(*, packet_seq: int, source_role_id: bytes, target_witness_id: bytes, checkpoint: bytes,
                         old_tree_size: int, proof: tuple[bytes, ...]) -> bytes:
    checkpoint = _exact(checkpoint, OCK1_LEN, "CHECKPOINT_LEN")
    if len(proof) > PROOF_SLOTS:
        raise FailClosed("PROOF")
    slots = b"".join(proof) + bytes(32 * (PROOF_SLOTS - len(proof)))
    body = b"".join((
        b"OCP1", bytes([1]), _u64(packet_seq), _b32(source_role_id, "SOURCE"),
        _b32(target_witness_id, "WITNESS"), checkpoint, _u64(old_tree_size), bytes([len(proof)]), slots,
    ))
    if len(body) != OCP1_LEN:
        raise FailClosed("REQUEST_LEN")
    return body


def parse_witness_request(raw: bytes) -> dict:
    data = _exact(raw, OCP1_LEN, "REQUEST_LEN")
    if data[:4] != b"OCP1" or data[4] != 1:
        raise FailClosed("REQUEST")
    count = data[266]
    if count > PROOF_SLOTS:
        raise FailClosed("PROOF")
    slots = data[267:]
    if slots[count * 32:] != bytes(len(slots) - count * 32):
        raise FailClosed("PROOF_PADDING")
    return {
        "packet_seq": struct.unpack_from(">Q", data, 5)[0],
        "source_role_id": data[13:45],
        "target_witness_id": data[45:77],
        "checkpoint": data[77:77 + OCK1_LEN],
        "old_tree_size": struct.unpack_from(">Q", data, 258)[0],
        "proof": tuple(slots[i * 32:(i + 1) * 32] for i in range(count)),
        "raw": data,
    }
