"""Cross-IMP rehearsal. ACTIVE is a lifecycle state, not an authorization."""

from __future__ import annotations

import hashlib

from orca.rse.imp1.locks import (
    corpus_generation_authorized,
    gpu_authorized,
    model_selection_authorized,
    prove_authorization_locks,
    qualification_authorized,
    spending_authorized,
    training_authorized,
)
from orca.rse.imp1.profiles import DEFERRED_CLASSES
from orca.rse.imp1.verdict import CHECKS_PASSED, FailClosed
from orca.rse.imp4.ocr1 import ingest_phase1, ingest_phase2, ochk
from orca.rse.imp2.machine import GrantMachine
from tests.rse.block1_support import authorize, ed_key, g_intent, g_tail, grant_for, open_role, v_intent, v_tail, world, x_key
from tests.rse.test_imp4_ocr1 import _seal
import pytest


def test_g_then_v_rehearsal_leaves_every_lock_denied():
    registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"integration-g").digest(),
    )
    assert forge.activate(b"G" * 16) == "ACTIVE"
    assert forge.rehearse(b"G" * 16) == "NOT_AUTHORIZED"
    assert corpus_generation_authorized() is False
    _crown_v, witness, _vraw, _vdelivery = authorize(
        registry, parts, klass="V", target="witness", tail=v_tail(parts, 1, 2), intent_for=v_intent,
        grant_id=b"V" * 16, entropy=hashlib.sha256(b"integration-v").digest(),
    )
    frames = list(_seal(parts, ochk(b"integration-transfer"), entropy=hashlib.sha256(b"integration-entropy").digest()))
    phase1 = ingest_phase1(witness, b"V" * 16, frames)
    assert phase1["decrypted"] is False
    assert witness.activate(b"V" * 16) == "ACTIVE"
    opened = ingest_phase2(
        witness, b"V" * 16, frames, recipient_private=x_key("witness"),
        quarantine=phase1["quarantine"],
    )
    assert opened["acceptance"] == "ZERO_ACCEPTANCE_AUTHORITY"
    assert opened["executable"] is False
    locks = prove_authorization_locks()
    assert locks.decision == CHECKS_PASSED
    assert locks.reason == "LOCKS_INTACT"
    assert qualification_authorized() is False
    assert training_authorized() is False
    assert model_selection_authorized() is False
    assert gpu_authorized() is False
    assert spending_authorized() is False


def test_deferred_grant_cannot_leave_proposed_except_terminal_refusal():
    registry, parts = world()
    crown = open_role(registry, parts, "crown")
    raw = grant_for(
        registry, parts, klass="K", target="forge", challenge=hashlib.sha256(b"deferred-k").digest(),
        prev=bytes(32), grant_id=b"K" * 16,
        tail={
            "scenario": 1, "new_authority_version": 2, "new_epoch": 2,
            "checkpoint_root": hashlib.sha256(b"k-root").digest(), "revoked_count": 0, "revoked_ids": (),
        },
    )
    assert crown.propose(raw) == "PROPOSED"
    with pytest.raises(FailClosed, match="UNSUPPORTED_CURRENT_MILESTONE"):
        crown.owner_verify(b"K" * 16)
    assert crown.revoke(b"K" * 16) == "REVOKED"
    machine = GrantMachine()
    for klass in DEFERRED_CLASSES:
        assert klass in {ord("K"), ord("Q"), ord("T"), ord("W"), ord("D"), ord("R")}
