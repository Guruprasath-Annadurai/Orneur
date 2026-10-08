"""Authoritative challenge and registry-generation state.

N-1: presenting a stale grant does not void a different outstanding challenge,
and it does not poison later challenges. A challenge is voided when this role
authenticates a successor registry, which is the accepted availability cost
of exact snapshot binding.

N-2: ``highest_authenticated_version`` and the consumed/voided sets live here.
Callers cannot supply a replacement ledger or a lower generation.
"""

from __future__ import annotations

import struct

from orca.rse.imp1.authority import Floors, accept_registry
from orca.rse.imp1.codec import OwnerToken, Registry
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, FailClosed

_MAGIC = b"OFJ1"


class RoleFreshness:
    def __init__(self, role_id: bytes) -> None:
        if not isinstance(role_id, (bytes, bytearray)) or len(role_id) != 32:
            raise FailClosed("ROLE_ID")
        self.role_id = bytes(role_id)
        self._outstanding: bytes | None = None
        self._voided: set[bytes] = set()
        self._consumed: set[bytes] = set()
        self._dead_grants: set[bytes] = set()
        self._forfeited_sequences: set[int] = set()
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
            self._voided.add(self._outstanding)
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
            self._voided.add(self._outstanding)
        self._outstanding = entropy
        self._challenge_seq += 1
        self.set_head(head)
        return entropy

    def note_dead_grant(self, grant_id: bytes) -> None:
        self._dead_grants.add(bytes(grant_id))

    def forfeit_sequences(self, first: int, last: int) -> None:
        if last < first:
            raise FailClosed("SEQUENCE")
        for value in range(first, last + 1):
            self._forfeited_sequences.add(value)

    def sequence_forfeited(self, value: int) -> bool:
        return value in self._forfeited_sequences

    def consume_sequence(self) -> int:
        value = self._next_sequence
        if value in self._forfeited_sequences:
            raise FailClosed("FORFEITED_SEQUENCE")
        self._next_sequence = value + 1
        return value

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
        self._consumed.add(challenge)
        self._outstanding = None

    def export(self) -> bytes:
        voided = b"".join(sorted(self._voided))
        consumed = b"".join(sorted(self._consumed))
        dead = b"".join(sorted(self._dead_grants))
        forfeited = b"".join(struct.pack(">Q", item) for item in sorted(self._forfeited_sequences))
        outstanding = self._outstanding if self._outstanding is not None else bytes(32)
        flag = 1 if self._outstanding is not None else 0
        body = b"".join((
            _MAGIC, bytes([1, flag]), self.role_id, outstanding, self._root, self._head,
            struct.pack(">III", self._highest, self._challenge_seq, self._next_sequence),
            struct.pack(">I", len(self._voided)), voided,
            struct.pack(">I", len(self._consumed)), consumed,
            struct.pack(">I", len(self._dead_grants)), dead,
            struct.pack(">I", len(self._forfeited_sequences)), forfeited,
        ))
        return body

    @classmethod
    def parse(cls, raw: bytes) -> "RoleFreshness":
        data = bytes(raw)
        if len(data) < 4 + 2 + 32 + 32 + 32 + 32 + 12 or data[:4] != _MAGIC or data[4] != 1:
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
            if count > 4096 or offset + count * width > len(data):
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
        raw_sequences = take_set(8)
        obj._forfeited_sequences = {struct.unpack(">Q", item)[0] for item in raw_sequences}
        if offset != len(data):
            raise FailClosed("TRAILING")
        if obj._outstanding is not None and obj._outstanding in obj._voided | obj._consumed:
            raise FailClosed("FRESHNESS")
        return obj
