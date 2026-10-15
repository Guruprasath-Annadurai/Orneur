"""Grant lifecycle table. A transition that is not listed is impossible.

Checkpoint and consumer checks live in the session. This table is what makes
skipping, revival, and class promotion fail closed even if a caller names the
destination state.
"""

from __future__ import annotations

import struct

from orca.rse.imp1.profiles import DEFERRED_CLASSES, KNOWN_CLASSES
from orca.rse.imp1.verdict import FailClosed

PROPOSED = "PROPOSED"
OWNER_VERIFIED = "OWNER_VERIFIED"
SIGNED = "SIGNED"
APPENDED = "APPENDED"
CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
REQUIRED_WITNESS_ACKNOWLEDGED = "REQUIRED_WITNESS_ACKNOWLEDGED"
CHECKPOINTED = "CHECKPOINTED"
DELIVERED = "DELIVERED"
CONSUMER_CONFIRMED = "CONSUMER_CONFIRMED"
ACTIVE = "ACTIVE"
CONSUMED = "CONSUMED"
EVIDENCE_PENDING = "EVIDENCE_PENDING"
COMPLETE = "COMPLETE"
EXPIRED = "EXPIRED"
REVOKED = "REVOKED"
INTERRUPTED = "INTERRUPTED"
QUARANTINED = "QUARANTINED"

_ORDER = (
    PROPOSED, OWNER_VERIFIED, SIGNED, APPENDED, CHECKPOINT_CREATED,
    REQUIRED_WITNESS_ACKNOWLEDGED, CHECKPOINTED, DELIVERED, CONSUMER_CONFIRMED,
    ACTIVE, CONSUMED, EVIDENCE_PENDING, COMPLETE, EXPIRED, REVOKED, INTERRUPTED, QUARANTINED,
)
_CODE = {name: index + 1 for index, name in enumerate(_ORDER)}
_NAME = {code: name for name, code in _CODE.items()}

TERMINAL = frozenset({COMPLETE, EXPIRED, REVOKED, INTERRUPTED})
# QUARANTINED is not a free slot. Recovery is a K grant and is not executable here.
RELEASED = TERMINAL

ALLOWED = {
    PROPOSED: frozenset({OWNER_VERIFIED, EXPIRED, REVOKED, QUARANTINED}),
    OWNER_VERIFIED: frozenset({SIGNED, EXPIRED, REVOKED, QUARANTINED}),
    SIGNED: frozenset({APPENDED, EXPIRED, REVOKED, QUARANTINED}),
    APPENDED: frozenset({CHECKPOINT_CREATED, EXPIRED, REVOKED, QUARANTINED}),
    CHECKPOINT_CREATED: frozenset({REQUIRED_WITNESS_ACKNOWLEDGED, EXPIRED, REVOKED, QUARANTINED}),
    REQUIRED_WITNESS_ACKNOWLEDGED: frozenset({CHECKPOINTED, EXPIRED, REVOKED, QUARANTINED}),
    CHECKPOINTED: frozenset({DELIVERED, EXPIRED, REVOKED, QUARANTINED}),
    DELIVERED: frozenset({CONSUMER_CONFIRMED, EXPIRED, REVOKED, QUARANTINED}),
    CONSUMER_CONFIRMED: frozenset({ACTIVE, EXPIRED, REVOKED, QUARANTINED}),
    ACTIVE: frozenset({CONSUMED, INTERRUPTED, QUARANTINED}),
    CONSUMED: frozenset({EVIDENCE_PENDING, INTERRUPTED, QUARANTINED}),
    EVIDENCE_PENDING: frozenset({COMPLETE, QUARANTINED}),
    COMPLETE: frozenset(),
    EXPIRED: frozenset(),
    REVOKED: frozenset(),
    INTERRUPTED: frozenset(),
    QUARANTINED: frozenset(),
}

PRE_ACTIVE = frozenset({
    PROPOSED, OWNER_VERIFIED, SIGNED, APPENDED, CHECKPOINT_CREATED,
    REQUIRED_WITNESS_ACKNOWLEDGED, CHECKPOINTED, DELIVERED, CONSUMER_CONFIRMED,
})


class GrantSlot:
    def __init__(self, grant_id: bytes, role_id: bytes, klass: int, state: str = PROPOSED) -> None:
        self.grant_id = bytes(grant_id)
        self.role_id = bytes(role_id)
        self.klass = klass
        self.state = state
        self.consumption_started = False
        self.evidence_durable = False
        self.reconfirm_required = False
        self.sequences_forfeited = False
        self.wall_expired = False
        self.activation_tick: int | None = None

    def copy(self) -> "GrantSlot":
        other = GrantSlot(self.grant_id, self.role_id, self.klass, self.state)
        other.consumption_started = self.consumption_started
        other.evidence_durable = self.evidence_durable
        other.reconfirm_required = self.reconfirm_required
        other.sequences_forfeited = self.sequences_forfeited
        other.wall_expired = self.wall_expired
        other.activation_tick = self.activation_tick
        return other


class GrantMachine:
    def __init__(self) -> None:
        self._slots: dict[bytes, GrantSlot] = {}

    def slots(self) -> tuple[GrantSlot, ...]:
        return tuple(self._slots[key].copy() for key in sorted(self._slots))

    def get(self, grant_id: bytes) -> GrantSlot:
        try:
            return self._slots[bytes(grant_id)]
        except KeyError as exc:
            raise FailClosed("GRANT_ABSENT") from exc

    def outstanding(self, role_id: bytes) -> GrantSlot | None:
        role_id = bytes(role_id)
        found = None
        for slot in self._slots.values():
            if slot.role_id == role_id and slot.state not in RELEASED:
                if found is not None:
                    raise FailClosed("GRANT_CONFLICT")
                found = slot
        return None if found is None else found.copy()

    def add(self, grant_id: bytes, role_id: bytes, klass: int) -> None:
        if klass not in KNOWN_CLASSES:
            raise FailClosed("GRANT_CLASS")
        grant_id = bytes(grant_id)
        if grant_id in self._slots:
            raise FailClosed("REPLAY")
        role_id = bytes(role_id)
        if self.outstanding(role_id) is not None:
            raise FailClosed("OUTSTANDING_GRANT")
        self._slots[grant_id] = GrantSlot(grant_id, role_id, klass, PROPOSED)

    def move(self, grant_id: bytes, new: str) -> GrantSlot:
        if new not in _CODE:
            raise FailClosed("GRANT_STATE")
        slot = self.get(grant_id)
        if new not in ALLOWED[slot.state]:
            raise FailClosed("FORBIDDEN_TRANSITION")
        if slot.klass in DEFERRED_CLASSES and new not in {EXPIRED, REVOKED, QUARANTINED}:
            raise FailClosed("UNSUPPORTED_CURRENT_MILESTONE")
        updated = slot.copy()
        updated.state = new
        if new == ACTIVE:
            updated.consumption_started = True
            updated.reconfirm_required = False
        if new == EVIDENCE_PENDING:
            updated.evidence_durable = True
        if new == INTERRUPTED:
            updated.sequences_forfeited = True
        self._slots[bytes(grant_id)] = updated
        return updated.copy()

    def require_reconfirm(self, grant_id: bytes) -> None:
        slot = self.get(grant_id).copy()
        if slot.state != CONSUMER_CONFIRMED or slot.consumption_started:
            raise FailClosed("GRANT_STATE")
        slot.reconfirm_required = True
        self._slots[bytes(grant_id)] = slot

    def clear_reconfirm(self, grant_id: bytes) -> None:
        slot = self.get(grant_id).copy()
        slot.reconfirm_required = False
        self._slots[bytes(grant_id)] = slot

    def note_activation_tick(self, grant_id: bytes, tick: int) -> None:
        slot = self.get(grant_id).copy()
        if slot.activation_tick is None:
            slot.activation_tick = tick
            self._slots[bytes(grant_id)] = slot

    def note_wall_expired(self, grant_id: bytes) -> None:
        slot = self.get(grant_id).copy()
        slot.wall_expired = True
        self._slots[bytes(grant_id)] = slot

    def export(self) -> bytes:
        parts = [b"OGJ1", bytes([1]), struct.pack(">I", len(self._slots))]
        for grant_id in sorted(self._slots):
            slot = self._slots[grant_id]
            flags = (
                (1 if slot.consumption_started else 0)
                | (2 if slot.evidence_durable else 0)
                | (4 if slot.reconfirm_required else 0)
                | (8 if slot.sequences_forfeited else 0)
                | (16 if slot.wall_expired else 0)
            )
            tick = 0 if slot.activation_tick is None else slot.activation_tick + 1
            parts.append(b"".join((
                slot.grant_id, bytes([_CODE[slot.state], slot.klass, flags]), slot.role_id,
                struct.pack(">Q", tick),
            )))
        return b"".join(parts)

    @classmethod
    def parse(cls, raw: bytes) -> "GrantMachine":
        data = bytes(raw)
        if len(data) < 9 or data[:4] != b"OGJ1" or data[4] != 1:
            raise FailClosed("GRANT_JOURNAL")
        count = struct.unpack_from(">I", data, 5)[0]
        offset = 9
        machine = cls()
        seen_roles: dict[bytes, int] = {}
        for _ in range(count):
            if offset + 16 + 3 + 32 + 8 > len(data):
                raise FailClosed("GRANT_JOURNAL")
            grant_id = data[offset:offset + 16]
            offset += 16
            state_code, klass, flags = data[offset], data[offset + 1], data[offset + 2]
            offset += 3
            role_id = data[offset:offset + 32]
            offset += 32
            tick = struct.unpack_from(">Q", data, offset)[0]
            offset += 8
            if state_code not in _NAME or klass not in KNOWN_CLASSES or grant_id in machine._slots:
                raise FailClosed("GRANT_JOURNAL")
            slot = GrantSlot(grant_id, role_id, klass, _NAME[state_code])
            slot.consumption_started = bool(flags & 1)
            slot.evidence_durable = bool(flags & 2)
            slot.reconfirm_required = bool(flags & 4)
            slot.sequences_forfeited = bool(flags & 8)
            slot.wall_expired = bool(flags & 16)
            slot.activation_tick = None if tick == 0 else tick - 1
            if flags & ~31:
                raise FailClosed("GRANT_JOURNAL")
            if slot.state not in RELEASED:
                seen_roles[role_id] = seen_roles.get(role_id, 0) + 1
                if seen_roles[role_id] > 1:
                    raise FailClosed("GRANT_CONFLICT")
            machine._slots[grant_id] = slot
        if offset != len(data):
            raise FailClosed("TRAILING")
        return machine


def promotes(source_class: str, target_class: str) -> None:
    """No class completion authorizes another class. T does not authorize W. W does not authorize D."""
    if source_class == target_class:
        raise FailClosed("CLASS_CONFUSION")
    raise FailClosed("CLASS_DOES_NOT_AUTHORIZE")
