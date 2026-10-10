"""Authoritative challenge and registry-generation state.

N-1: presenting a stale grant does not void a different outstanding challenge,
and it does not poison later challenges. A challenge is voided when this role
authenticates a successor registry, which is the accepted availability cost
of exact snapshot binding.

N-2: ``highest_authenticated_version`` and the consumed/voided sets live here.
Callers cannot supply a replacement ledger or a lower generation.

Forfeited sequences are merged inclusive intervals. Set sections and the
export share one cap so a journal this object writes can be parsed again.
"""

from __future__ import annotations

import struct

from orca.rse.imp1.authority import Floors, accept_registry
from orca.rse.imp1.codec import OwnerToken, Registry
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, FailClosed

_MAGIC = b"OFJ1"
MAX_SET = 8192
MAX_INTERVALS = 4096


class RoleFreshness:
    def __init__(self, role_id: bytes) -> None:
        if not isinstance(role_id, (bytes, bytearray)) or len(role_id) != 32:
            raise FailClosed("ROLE_ID")
        self.role_id = bytes(role_id)
        self._outstanding: bytes | None = None
        self._voided: set[bytes] = set()
        self._consumed: set[bytes] = set()
        self._dead_grants: set[bytes] = set()
        self._forfeited: list[tuple[int, int]] = []
        self._highest = 0
        self._root = bytes(32)
        self._challenge_seq = 0
        self._next_sequence = 1
        self._head = bytes(32)

    @property
    def highest(self) -> int:
        return self._highest

    @property
    def root(self) -> bytes:
        return self._root

    @property
    def outstanding(self) -> bytes | None:
        return self._outstanding

    @property
    def head(self) -> bytes:
        return self._head

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    def set_head(self, head: bytes) -> None:
        if not isinstance(head, (bytes, bytearray)) or len(head) != 32:
            raise FailClosed("HEAD")
        self._head = bytes(head)

    def authenticate(self, registry_raw: bytes, tokens: list[OwnerToken], floors: Floors, prior: Registry | None) -> Registry:
        """Move the authenticated generation only forward, and only after IMP-1 accepts it."""
        if not isinstance(registry_raw, (bytes, bytearray)):
            raise FailClosed("REGISTRY")
        result = accept_registry(bytes(registry_raw), tokens, floors, prior)
        if result.decision != CHECKS_PASSED:
            raise FailClosed(result.reason if result.decision == FAIL_CLOSED else "REGISTRY")
        from orca.rse.imp1.codec import parse_registry
        registry = parse_registry(bytes(registry_raw))
        if registry.registry_version < self._highest:
            raise FailClosed("REGISTRY_ROLLBACK")
        if registry.registry_version == self._highest:
            if self._highest == 0:
                self._highest = registry.registry_version
                self._root = registry.registry_root
                return registry
            if registry.registry_root != self._root:
                raise FailClosed("REGISTRY_FORK")
            return registry
        if self._outstanding is not None:
            self._remember(self._voided, self._outstanding)
            self._outstanding = None
        self._highest = registry.registry_version
        self._root = registry.registry_root
        return registry

    def issue(self, entropy: bytes, *, head: bytes) -> bytes:
        if not isinstance(entropy, (bytes, bytearray)) or len(entropy) != 32 or entropy == bytes(32):
            raise FailClosed("CHALLENGE")
        entropy = bytes(entropy)
        if entropy in self._voided or entropy in self._consumed:
            raise FailClosed("CHALLENGE_REPLAY")
        if self._outstanding is not None:
            self._remember(self._voided, self._outstanding)
        self._outstanding = entropy
        self._challenge_seq += 1
        self.set_head(head)
        return entropy

    def note_dead_grant(self, grant_id: bytes) -> None:
        if not isinstance(grant_id, (bytes, bytearray)) or len(grant_id) != 16:
            raise FailClosed("GRANT_ID")
        self._remember(self._dead_grants, bytes(grant_id))

    def forfeit_sequences(self, first: int, last: int) -> None:
        self._forfeited = _add_interval(self._forfeited, first, last)

    def sequence_forfeited(self, value: int) -> bool:
        for start, end in self._forfeited:
            if start <= value <= end:
                return True
            if start > value:
                return False
        return False

    def consume_sequence(self) -> int:
        value = self._next_sequence
        if self.sequence_forfeited(value):
            raise FailClosed("FORFEITED_SEQUENCE")
        self._next_sequence = value + 1
        return value

    def _remember(self, bucket: set[bytes], item: bytes) -> None:
        if item in bucket:
            return
        bucket.add(item)
        try:
            self._compact_sets()
        except FailClosed:
            bucket.discard(item)
            raise

    def _compact_sets(self) -> None:
        """Drop a voided challenge that is already consumed. Consumed still rejects replay."""
        overlap = self._voided & self._consumed
        if overlap:
            self._voided -= overlap
        if (
            len(self._voided) > MAX_SET
            or len(self._consumed) > MAX_SET
            or len(self._dead_grants) > MAX_SET
            or len(self._forfeited) > MAX_INTERVALS
        ):
            raise FailClosed("FRESHNESS")

    def evaluate(self, grant, registry: Registry) -> None:
        """Refuse stale grants without burning a challenge they do not carry."""
        if grant.grant_id in self._dead_grants:
            raise FailClosed("GRANT_DEAD")
        if registry.registry_version != self._highest or registry.registry_root != self._root:
            self.note_dead_grant(grant.grant_id)
            raise FailClosed("SNAPSHOT")
        challenge = bytes(grant.challenge)
        if challenge in self._consumed:
            raise FailClosed("CHALLENGE_REPLAY")
        if challenge in self._voided:
            raise FailClosed("CHALLENGE_VOID")
        if self._outstanding is None or challenge != self._outstanding:
            self.note_dead_grant(grant.grant_id)
            raise FailClosed("CHALLENGE")
        if grant.registry_version != self._highest or grant.registry_root != self._root:
            self.note_dead_grant(grant.grant_id)
            raise FailClosed("SNAPSHOT")
        if grant.target_role_id != self.role_id:
            raise FailClosed("ROLE_ID")

    def consume(self, challenge: bytes) -> None:
        challenge = bytes(challenge)
        if challenge != self._outstanding:
            raise FailClosed("CHALLENGE")
        self._remember(self._consumed, challenge)
        self._outstanding = None

    def export(self) -> bytes:
        self._compact_sets()
        voided = b"".join(sorted(self._voided))
        consumed = b"".join(sorted(self._consumed))
        dead = b"".join(sorted(self._dead_grants))
        intervals = b"".join(struct.pack(">QQ", start, end) for start, end in self._forfeited)
        outstanding = self._outstanding if self._outstanding is not None else bytes(32)
        flag = 1 if self._outstanding is not None else 0
        body = b"".join((
            _MAGIC, bytes([2, flag]), self.role_id, outstanding, self._root, self._head,
            struct.pack(">III", self._highest, self._challenge_seq, self._next_sequence),
            struct.pack(">I", len(self._voided)), voided,
            struct.pack(">I", len(self._consumed)), consumed,
            struct.pack(">I", len(self._dead_grants)), dead,
            struct.pack(">I", len(self._forfeited)), intervals,
        ))
        return body

    @classmethod
    def parse(cls, raw: bytes) -> "RoleFreshness":
        data = bytes(raw)
        if len(data) < 4 + 2 + 32 + 32 + 32 + 32 + 12 or data[:4] != _MAGIC or data[4] != 2:
            raise FailClosed("FRESHNESS")
        offset = 5
        flag = data[offset]
        offset += 1
        role_id = data[offset:offset + 32]
        offset += 32
        outstanding = data[offset:offset + 32]
        offset += 32
        root = data[offset:offset + 32]
        offset += 32
        head = data[offset:offset + 32]
        offset += 32
        highest, challenge_seq, next_sequence = struct.unpack_from(">III", data, offset)
        offset += 12
        obj = cls(role_id)
        obj._highest = highest
        obj._root = root
        obj._head = head
        obj._challenge_seq = challenge_seq
        obj._next_sequence = next_sequence
        obj._outstanding = outstanding if flag == 1 else None
        if flag not in (0, 1):
            raise FailClosed("FRESHNESS")
        if flag == 0 and outstanding != bytes(32):
            raise FailClosed("FRESHNESS")

        def take_set(width: int) -> set[bytes]:
            nonlocal offset
            if offset + 4 > len(data):
                raise FailClosed("FRESHNESS")
            count = struct.unpack_from(">I", data, offset)[0]
            offset += 4
            if count > MAX_SET or offset + count * width > len(data):
                raise FailClosed("FRESHNESS")
            out = set()
            for _ in range(count):
                item = data[offset:offset + width]
                offset += width
                if item in out:
                    raise FailClosed("FRESHNESS")
                out.add(item)
            return out

        obj._voided = take_set(32)
        obj._consumed = take_set(32)
        obj._dead_grants = take_set(16)
        if offset + 4 > len(data):
            raise FailClosed("FRESHNESS")
        count = struct.unpack_from(">I", data, offset)[0]
        offset += 4
        if count > MAX_INTERVALS or offset + count * 16 > len(data):
            raise FailClosed("FRESHNESS")
        intervals: list[tuple[int, int]] = []
        previous_end: int | None = None
        for _ in range(count):
            start, end = struct.unpack_from(">QQ", data, offset)
            offset += 16
            if end < start or (previous_end is not None and start <= previous_end + 1):
                raise FailClosed("FRESHNESS")
            intervals.append((start, end))
            previous_end = end
        obj._forfeited = intervals
        if offset != len(data):
            raise FailClosed("TRAILING")
        if obj._outstanding is not None and obj._outstanding in obj._voided | obj._consumed:
            raise FailClosed("FRESHNESS")
        obj._compact_sets()
        return obj


def _add_interval(intervals: list[tuple[int, int]], first: int, last: int) -> list[tuple[int, int]]:
    if (
        not isinstance(first, int) or not isinstance(last, int)
        or isinstance(first, bool) or isinstance(last, bool)
        or first < 0 or last < first
    ):
        raise FailClosed("SEQUENCE")
    start, end = first, last
    merged: list[tuple[int, int]] = []
    placed = False
    for left, right in intervals:
        if right + 1 < start:
            merged.append((left, right))
            continue
        if end + 1 < left:
            if not placed:
                merged.append((start, end))
                placed = True
            merged.append((left, right))
            continue
        start = min(start, left)
        end = max(end, right)
    if not placed:
        merged.append((start, end))
    if len(merged) > MAX_INTERVALS:
        raise FailClosed("FRESHNESS")
    return merged
