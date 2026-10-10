"""RFC 6962 / RFC 9162 Merkle tree over evidence-log records.

This is the transparency-log tree. It is not the registry tree in
``orca.rse.imp1.merkle`` (that one hashes 32-byte entry ids only).
"""

from __future__ import annotations

import hashlib

from orca.rse.imp1.verdict import FailClosed

PROFILE = "RFC6962-SHA256-RECORD-LEAF"


def leaf_hash(record: bytes) -> bytes:
    if not isinstance(record, (bytes, bytearray)) or not record:
        raise FailClosed("LEAF")
    return hashlib.sha256(b"\x00" + bytes(record)).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    """Largest power of two strictly less than n. n > 1."""
    if n <= 1:
        raise FailClosed("TREE")
    k = 1 << (n.bit_length() - 1)
    if k == n:
        k >>= 1
    return k


def tree_hash(leaves: list[bytes]) -> bytes:
    if not leaves:
        raise FailClosed("EMPTY_TREE")

    def mth(start: int, end: int) -> bytes:
        count = end - start
        if count == 1:
            return leaves[start]
        k = _split(count)
        return _node(mth(start, start + k), mth(start + k, end))

    return mth(0, len(leaves))


def inclusion_proof(leaves: list[bytes], index: int) -> tuple[bytes, ...]:
    size = len(leaves)
    if index < 0 or index >= size:
        raise FailClosed("PROOF")
    if size == 1:
        return ()

    def path(start: int, end: int, target: int) -> tuple[bytes, ...]:
        count = end - start
        if count == 1:
            return ()
        k = _split(count)
        if target < start + k:
            return path(start, start + k, target) + (tree_hash(leaves[start + k:end]),)
        return path(start + k, end, target) + (tree_hash(leaves[start:start + k]),)

    return path(0, size, index)


def verify_inclusion(leaf: bytes, index: int, tree_size: int, proof: tuple[bytes, ...], root: bytes) -> None:
    """RFC 9162 §2.1.3.2. ``leaf`` is the RFC 6962 leaf hash, not the raw record."""
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise FailClosed("PROOF")
    if not isinstance(tree_size, int) or isinstance(tree_size, bool) or tree_size < 1 or index >= tree_size:
        raise FailClosed("PROOF")
    if len(leaf) != 32 or len(root) != 32:
        raise FailClosed("PROOF")
    fn = index
    sn = tree_size - 1
    running = leaf
    for item in proof:
        if not isinstance(item, (bytes, bytearray)) or len(item) != 32:
            raise FailClosed("PROOF")
        if sn == 0:
            raise FailClosed("PROOF")
        sibling = bytes(item)
        if (fn & 1) or fn == sn:
            running = _node(sibling, running)
            if (fn & 1) == 0:
                while (fn & 1) == 0 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            running = _node(running, sibling)
        fn >>= 1
        sn >>= 1
    if sn != 0 or running != root:
        raise FailClosed("PROOF")


def _is_pow2(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def consistency_proof(old_size: int, leaves: list[bytes]) -> tuple[bytes, ...]:
    """RFC 9162 §2.1.4.1. ``old_size`` is exclusive of the new tail."""
    size = len(leaves)
    if not isinstance(old_size, int) or isinstance(old_size, bool):
        raise FailClosed("PROOF")
    if old_size <= 0 or old_size >= size:
        raise FailClosed("PROOF")

    def subproof(m: int, start: int, end: int, complete: bool) -> tuple[bytes, ...]:
        count = end - start
        if m == count:
            if complete:
                return ()
            return (tree_hash(leaves[start:end]),)
        k = _split(count)
        if m <= k:
            return subproof(m, start, start + k, complete) + (tree_hash(leaves[start + k:end]),)
        return subproof(m - k, start + k, end, False) + (tree_hash(leaves[start:start + k]),)

    return subproof(old_size, 0, size, True)


def verify_consistency(old_size: int, new_size: int, old_root: bytes, new_root: bytes, proof: tuple[bytes, ...]) -> None:
    """RFC 9162 §2.1.4.2. Equal sizes are not a proof: the roots must already be identical."""
    if not isinstance(old_size, int) or isinstance(old_size, bool) or not isinstance(new_size, int) or isinstance(new_size, bool):
        raise FailClosed("PROOF")
    if old_size <= 0 or new_size <= 0 or len(old_root) != 32 or len(new_root) != 32:
        raise FailClosed("PROOF")
    if old_size > new_size:
        raise FailClosed("ROLLBACK")
    if old_size == new_size:
        if proof or old_root != new_root:
            raise FailClosed("FORK")
        return
    path = list(proof)
    if not path:
        raise FailClosed("PROOF")
    if _is_pow2(old_size):
        path = [old_root, *path]
    fn = old_size - 1
    sn = new_size - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1
    first = path[0]
    if len(first) != 32:
        raise FailClosed("PROOF")
    fr = sr = first
    for item in path[1:]:
        if len(item) != 32:
            raise FailClosed("PROOF")
        if sn == 0:
            raise FailClosed("PROOF")
        if (fn & 1) or fn == sn:
            fr = _node(item, fr)
            sr = _node(item, sr)
            if (fn & 1) == 0:
                while (fn & 1) == 0 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            sr = _node(sr, item)
        fn >>= 1
        sn >>= 1
    if sn != 0 or fr != old_root or sr != new_root:
        raise FailClosed("PROOF")
