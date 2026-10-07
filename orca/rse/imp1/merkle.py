"""Registry root: Merkle root over entry IDs.

Profile ``RFC6962-SHA256-ENTRY-ID-LEAF`` (recommended; see the IMP-1 report).
Leaf data is the 32-byte entry ID. Leaf hash is SHA-256(0x00 || entry_id).
An internal node is SHA-256(0x01 || left || right). The split ``k`` is the
largest power of two strictly less than the node count (RFC 6962 §2.1).
"""

from __future__ import annotations

import hashlib

from orca.rse.imp1.profiles import MERKLE_PROFILE
from orca.rse.imp1.verdict import FailClosed

assert MERKLE_PROFILE == "RFC6962-SHA256-ENTRY-ID-LEAF"


def _hash_leaf(entry_id: bytes) -> bytes:
    if len(entry_id) != 32:
        raise FailClosed("ENTRY_ID_LEN")
    return hashlib.sha256(b"\x00" + entry_id).digest()


def _mth(leaves: list[bytes]) -> bytes:
    n = len(leaves)
    if n == 1:
        return leaves[0]
    k = 1 << (n.bit_length() - 1)
    if k == n:
        k >>= 1
    return hashlib.sha256(b"\x01" + _mth(leaves[:k]) + _mth(leaves[k:])).digest()


def merkle_root(entry_ids: list[bytes]) -> bytes:
    if not entry_ids:
        raise FailClosed("EMPTY_REGISTRY")
    return _mth([_hash_leaf(item) for item in entry_ids])
