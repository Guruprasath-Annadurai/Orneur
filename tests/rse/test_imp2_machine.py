"""IMP-2 grant state machine. Transitions that are not listed are impossible."""

from __future__ import annotations

import pytest

from orca.rse.imp1.verdict import FailClosed
from orca.rse.imp2.machine import (
    ACTIVE,
    COMPLETE,
    CONSUMED,
    CONSUMER_CONFIRMED,
    EXPIRED,
    INTERRUPTED,
    PRE_ACTIVE,
    PROPOSED,
    QUARANTINED,
    REVOKED,
    SIGNED,
    GrantMachine,
    promotes,
)

ROLE = bytes(range(32))
OTHER = bytes(range(32, 64))


def _machine(klass: int = ord("G")) -> tuple[GrantMachine, bytes]:
    machine = GrantMachine()
    grant_id = b"G" * 16
    machine.add(grant_id, ROLE, klass)
    return machine, grant_id


def test_happy_path_reaches_complete_once():
    machine, grant_id = _machine()
    for state in (
        "OWNER_VERIFIED", SIGNED, "APPENDED", "CHECKPOINT_CREATED",
        "REQUIRED_WITNESS_ACKNOWLEDGED", "CHECKPOINTED", "DELIVERED",
        CONSUMER_CONFIRMED, ACTIVE, CONSUMED, "EVIDENCE_PENDING", COMPLETE,
    ):
        machine.move(grant_id, state)
    assert machine.get(grant_id).state == COMPLETE
    assert machine.get(grant_id).consumption_started is True
    assert machine.get(grant_id).evidence_durable is True
    with pytest.raises(FailClosed, match="FORBIDDEN_TRANSITION"):
        machine.move(grant_id, ACTIVE)


def _walk(machine: GrantMachine, grant_id: bytes, dest: str) -> None:
    order = (
        "OWNER_VERIFIED", SIGNED, "APPENDED", "CHECKPOINT_CREATED",
        "REQUIRED_WITNESS_ACKNOWLEDGED", "CHECKPOINTED", "DELIVERED",
        CONSUMER_CONFIRMED, ACTIVE, CONSUMED, "EVIDENCE_PENDING", COMPLETE,
    )
    if dest == PROPOSED:
        return
    if dest in {EXPIRED, REVOKED}:
        machine.move(grant_id, dest)
        return
    if dest == INTERRUPTED:
        for state in order:
            machine.move(grant_id, state)
            if state == ACTIVE:
                break
        machine.move(grant_id, INTERRUPTED)
        return
    for state in order:
        machine.move(grant_id, state)
        if state == dest:
            return
    raise AssertionError(dest)


@pytest.mark.parametrize("origin", [PROPOSED, SIGNED, EXPIRED, REVOKED, COMPLETE, INTERRUPTED])
def test_forbidden_activation(origin):
    machine, grant_id = _machine()
    _walk(machine, grant_id, origin)
    assert machine.get(grant_id).state == origin
    with pytest.raises(FailClosed, match="FORBIDDEN_TRANSITION"):
        machine.move(grant_id, ACTIVE)


def test_interrupted_cannot_return_to_active_without_a_new_grant():
    machine, grant_id = _machine()
    for state in ("OWNER_VERIFIED", SIGNED, "APPENDED", "CHECKPOINT_CREATED",
                  "REQUIRED_WITNESS_ACKNOWLEDGED", "CHECKPOINTED", "DELIVERED",
                  CONSUMER_CONFIRMED, ACTIVE):
        machine.move(grant_id, state)
    machine.move(grant_id, INTERRUPTED)
    assert machine.get(grant_id).sequences_forfeited is True
    with pytest.raises(FailClosed, match="FORBIDDEN_TRANSITION"):
        machine.move(grant_id, ACTIVE)
    with pytest.raises(FailClosed, match="REPLAY"):
        machine.add(grant_id, ROLE, ord("G"))
    machine.add(b"H" * 16, ROLE, ord("G"))
    assert machine.get(b"H" * 16).state == PROPOSED


def test_deferred_classes_stay_fail_closed():
    for klass in (ord("K"), ord("Q"), ord("T"), ord("W"), ord("D"), ord("R")):
        machine = GrantMachine()
        grant_id = bytes([klass]) + b"\x01" * 15
        machine.add(grant_id, ROLE, klass)
        with pytest.raises(FailClosed, match="UNSUPPORTED_CURRENT_MILESTONE"):
            machine.move(grant_id, "OWNER_VERIFIED")
        machine.move(grant_id, REVOKED)
        assert machine.get(grant_id).state == REVOKED


def test_one_outstanding_grant_includes_quarantine_and_replay():
    machine, grant_id = _machine()
    with pytest.raises(FailClosed, match="REPLAY"):
        machine.add(grant_id, OTHER, ord("V"))
    with pytest.raises(FailClosed, match="OUTSTANDING_GRANT"):
        machine.add(b"Z" * 16, ROLE, ord("V"))
    machine.move(grant_id, QUARANTINED)
    with pytest.raises(FailClosed, match="OUTSTANDING_GRANT"):
        machine.add(b"Z" * 16, ROLE, ord("V"))
    assert machine.outstanding(ROLE).state == QUARANTINED


def test_class_completion_does_not_authorize_another_class():
    with pytest.raises(FailClosed, match="CLASS_DOES_NOT_AUTHORIZE"):
        promotes("T", "W")
    with pytest.raises(FailClosed, match="CLASS_DOES_NOT_AUTHORIZE"):
        promotes("W", "D")
    with pytest.raises(FailClosed, match="CLASS_DOES_NOT_AUTHORIZE"):
        promotes("G", "V")
    with pytest.raises(FailClosed, match="CLASS_CONFUSION"):
        promotes("G", "G")


def test_journal_roundtrip_rejects_conflict_and_trailing():
    machine, grant_id = _machine()
    machine.move(grant_id, "OWNER_VERIFIED")
    machine.note_wall_expired(grant_id)
    restored = GrantMachine.parse(machine.export())
    assert restored.get(grant_id).state == "OWNER_VERIFIED"
    assert restored.get(grant_id).wall_expired is True
    blob = machine.export()
    with pytest.raises(FailClosed, match="TRAILING"):
        GrantMachine.parse(blob + b"\x00")
    conflict = GrantMachine()
    conflict.add(b"A" * 16, ROLE, ord("G"))
    conflict.add(b"B" * 16, OTHER, ord("V"))
    raw = bytearray(conflict.export())
    # Second role id sits after the first 16+3+32+8 record. Point it at the first role.
    start = 9 + 16 + 3 + 32 + 8 + 16 + 3
    raw[start:start + 32] = ROLE
    with pytest.raises(FailClosed, match="GRANT_CONFLICT"):
        GrantMachine.parse(bytes(raw))


def test_pre_active_set_excludes_execution_states():
    assert ACTIVE not in PRE_ACTIVE
    assert CONSUMED not in PRE_ACTIVE
    assert PROPOSED in PRE_ACTIVE
    assert CONSUMER_CONFIRMED in PRE_ACTIVE
