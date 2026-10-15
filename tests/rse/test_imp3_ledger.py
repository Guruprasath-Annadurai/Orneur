"""IMP-3 evidence log, witness quorum, freshness, and the N-1 / N-2 boundary."""

from __future__ import annotations

import hashlib

import pytest

from orca.rse.imp1.authority import ChallengeLedger
from orca.rse.imp1.codec import parse_grant, public_of
from orca.rse.imp1.profiles import ROLE_MONITOR_LITE
from orca.rse.imp1.verdict import CHECKS_PASSED, FailClosed, Quarantine
from orca.rse.imp1.locks import prove_authorization_locks
from orca.rse.imp3.freshness import RoleFreshness
from orca.rse.imp3.ledger import EvidenceLog, require_monitor
from orca.rse.imp3.merkle import (
    consistency_proof,
    inclusion_proof,
    leaf_hash,
    tree_hash,
    verify_consistency,
    verify_inclusion,
)
from orca.rse.imp3.records import KIND_GRANT, pack_ack, pack_checkpoint, pack_witness_request
from orca.rse.imp3.session import Session
from tests.rse.block1_support import (
    authorize, dig, ed_key, g_intent, g_tail, grant_for, open_monitor, open_role, reboot, world,
)
from tests.rse.support import sign_entries


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _stack_root(records: list[bytes]) -> bytes:
    """RFC 9162 §2.1.2, independent of the recursive implementation."""
    stack: list[bytes] = []
    for index, entry in enumerate(records):
        stack.append(hashlib.sha256(b"\x00" + entry).digest())
        merge = 0
        cursor = index
        while cursor & 1:
            merge += 1
            cursor >>= 1
        for _ in range(merge):
            right = stack.pop()
            left = stack.pop()
            stack.append(_node(left, right))
    while len(stack) > 1:
        right = stack.pop()
        left = stack.pop()
        stack.append(_node(left, right))
    return stack[0]


def test_rfc9162_seven_leaf_shape_and_stack_root():
    leaves = [hashlib.sha256(bytes([index])).digest() for index in range(7)]
    a, b, c, d, e, f, d6 = leaves
    g = _node(a, b)
    h = _node(c, d)
    i = _node(e, f)
    j = d6
    k = _node(g, h)
    l = _node(i, j)
    root = _node(k, l)
    assert tree_hash(leaves) == root
    assert inclusion_proof(leaves, 0) == (b, h, l)
    assert inclusion_proof(leaves, 3) == (c, g, l)
    assert inclusion_proof(leaves, 4) == (f, j, k)
    assert inclusion_proof(leaves, 6) == (i, k)
    for index, proof in enumerate(inclusion_proof(leaves, n) for n in range(7)):
        verify_inclusion(leaves[index], index, 7, proof, root)
    assert consistency_proof(3, leaves) == (c, d, g, l)
    assert consistency_proof(4, leaves) == (l,)
    assert consistency_proof(6, leaves) == (i, j, k)
    verify_consistency(3, 7, tree_hash(leaves[:3]), root, consistency_proof(3, leaves))
    verify_consistency(4, 7, k, root, consistency_proof(4, leaves))
    verify_consistency(6, 7, tree_hash(leaves[:6]), root, consistency_proof(6, leaves))
    records = [bytes([index]) * 8 for index in range(1, 8)]
    hashed = [leaf_hash(item) for item in records]
    assert tree_hash(hashed) == _stack_root(records)


def test_equal_size_fork_and_rollback_are_not_proofs():
    root = hashlib.sha256(b"root").digest()
    other = hashlib.sha256(b"other").digest()
    verify_consistency(4, 4, root, root, ())
    with pytest.raises(FailClosed, match="FORK"):
        verify_consistency(4, 4, root, other, ())
    with pytest.raises(FailClosed, match="ROLLBACK"):
        verify_consistency(5, 4, root, root, ())


def test_monitor_fork_rollback_and_idempotent_ack():
    registry, parts = world()
    crown = open_role(registry, parts, "crown")
    crown.log.append(kind=1, payload_digest=dig("boot"), grant_id=bytes(16), epoch=1, registry_version=1)
    first = crown.log.checkpoint(crown.role_key, epoch=1, registry_version=1)
    monitor = open_monitor(parts, "m1")
    source = public_of(ed_key("crown"))
    witness = public_of(ed_key("m1"))
    request = crown.log.witness_request(
        first, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=1, old_tree_size=0,
    )
    bound = dict(sink=monitor.sink, fence=monitor.fence)
    ack = monitor.consider(request, source_public=source, witness_public=witness, **bound)
    assert monitor.consider(request, source_public=source, witness_public=witness, **bound) == ack
    replay = bytearray(request)
    replay[12] = 0
    with pytest.raises(FailClosed, match="PACKET_REPLAY"):
        monitor.consider(bytes(replay), source_public=source, witness_public=witness, **bound)
    forged = pack_checkpoint(
        log_id=crown.role_id, tree_size=1, root=bytes(31) + b"\xff", epoch=1, registry_version=1,
        prev_checkpoint_digest=bytes(32), role_key=ed_key("crown"),
    )
    fork_request = pack_witness_request(
        packet_seq=2, source_role_id=crown.role_id, target_witness_id=parts["m1"].entry_id,
        checkpoint=forged, old_tree_size=1, proof=(),
    )
    with pytest.raises(Quarantine, match="FORK"):
        monitor.consider(fork_request, source_public=source, witness_public=witness, **bound)
    rolled = pack_checkpoint(
        log_id=crown.role_id, tree_size=1, root=crown.log.root, epoch=1, registry_version=1,
        prev_checkpoint_digest=bytes(32), role_key=ed_key("crown"),
    )
    # A smaller tree than the witness has already stored is rollback once a larger head exists.
    crown.log.append(kind=3, payload_digest=dig("tail"), grant_id=bytes(16), epoch=1, registry_version=1)
    second = crown.log.checkpoint(crown.role_key, epoch=1, registry_version=1)
    grown = crown.log.witness_request(
        second, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=3, old_tree_size=1,
    )
    monitor.consider(grown, source_public=source, witness_public=witness, **bound)
    rollback = pack_witness_request(
        packet_seq=4, source_role_id=crown.role_id, target_witness_id=parts["m1"].entry_id,
        checkpoint=rolled, old_tree_size=crown.log.size, proof=(),
    )
    with pytest.raises(FailClosed, match="ROLLBACK"):
        monitor.consider(rollback, source_public=source, witness_public=witness, **bound)


def forge_registry(session: Session):
    from orca.rse.imp1.codec import parse_registry
    return parse_registry(session.registry_raw)


def test_docker_and_same_key_are_not_witnesses():
    registry, parts = world()
    with pytest.raises(FailClosed, match="ROLE_TYPE"):
        require_monitor(registry, parts["forge"].entry_id)
    with pytest.raises(FailClosed, match="ENROLMENT"):
        require_monitor(registry, parts["code"].entry_id)
    same_key_registry, same_key_parts = world(m2_label="m1")
    with pytest.raises(FailClosed, match="INDEPENDENT_WITNESS"):
        open_role(same_key_registry, same_key_parts, "crown")
    same_env_registry, same_env_parts = world(m2_env="env-m1")
    with pytest.raises(FailClosed, match="INDEPENDENT_WITNESS"):
        open_role(same_env_registry, same_env_parts, "crown")
    assert ROLE_MONITOR_LITE == 4


def test_m2_cannot_replace_m1_and_later_checkpoint_is_not_the_ack():
    registry, parts = world()
    crown = open_role(registry, parts, "crown")
    forge = open_role(registry, parts, "forge")
    challenge = forge.issue_challenge(hashlib.sha256(b"m1-boundary").digest())
    raw = grant_for(
        registry, parts, klass="G", target="forge", challenge=challenge, prev=forge.freshness.head,
        grant_id=b"G" * 16, tail=g_tail(parts),
    )
    crown.propose(raw)
    crown.owner_verify(b"G" * 16)
    crown.mark_signed(b"G" * 16)
    with pytest.raises(FailClosed, match="FORBIDDEN_TRANSITION"):
        crown.activate(b"G" * 16)
    crown.append_authorization(b"G" * 16)
    first = crown.checkpoint_authorization(b"G" * 16)
    m2 = open_monitor(parts, "m2")
    packet = crown.log.witness_request(
        first, source_role_id=crown.role_id, witness_id=parts["m2"].entry_id, packet_seq=1, old_tree_size=0,
    )
    ack = m2.consider(
        packet, source_public=public_of(ed_key("crown")), witness_public=public_of(ed_key("m2")),
        sink=m2.sink, fence=m2.fence,
    )
    assert crown.accept_ack(b"G" * 16, ack) == "CHECKPOINT_CREATED"
    with pytest.raises(FailClosed, match="GRANT_STATE"):
        crown.deliver(b"G" * 16)
    crown.log.append(kind=3, payload_digest=dig("later"), grant_id=bytes(16), epoch=1, registry_version=1)
    later = crown.log.checkpoint(crown.role_key, epoch=1, registry_version=1)
    later_packet = crown.log.witness_request(
        later, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=2, old_tree_size=0,
    )
    # The witness has not seen the first tree, so an old_tree_size of 0 is its genesis.
    # A later checkpoint still does not acknowledge the earlier one.
    m1 = open_monitor(parts, "m1")
    later_ack = m1.consider(
        later_packet, source_public=public_of(ed_key("crown")), witness_public=public_of(ed_key("m1")),
        sink=m1.sink, fence=m1.fence,
    )
    with pytest.raises(FailClosed, match="STALE_CHECKPOINT"):
        crown.accept_ack(b"G" * 16, later_ack)
    with pytest.raises(FailClosed, match="CHECKPOINT"):
        crown.log.witness_request(
            first, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=4, old_tree_size=0,
        )
    assert later != first


def test_stale_grant_does_not_void_a_different_challenge():
    registry, parts = world()
    forge = open_role(registry, parts, "forge")
    live = forge.issue_challenge(hashlib.sha256(b"live-challenge").digest())
    stale_registry = sign_entries(list(parts.values()), version=2, previous=registry.registry_root)
    stale = grant_for(
        stale_registry, parts, klass="G", target="forge", challenge=live, prev=forge.freshness.head,
        grant_id=b"S" * 16, tail=g_tail(parts),
    )
    with pytest.raises(FailClosed, match="SNAPSHOT"):
        forge.freshness.evaluate(parse_grant(stale), registry)
    assert forge.freshness.outstanding == live
    corrected = grant_for(
        registry, parts, klass="G", target="forge", challenge=live, prev=forge.freshness.head,
        grant_id=b"C" * 16, tail=g_tail(parts),
    )
    forge.freshness.evaluate(parse_grant(corrected), registry)
    forge.advance_registry(stale_registry.raw, registry.raw)
    assert forge.freshness.outstanding is None
    with pytest.raises(FailClosed, match="CHALLENGE_REPLAY"):
        forge.issue_challenge(live)
    successor = forge.issue_challenge(hashlib.sha256(b"successor-challenge").digest())
    with pytest.raises(FailClosed, match="CHALLENGE_VOID"):
        forge.freshness.evaluate(parse_grant(corrected), forge_registry(forge))
    assert forge.freshness.outstanding == successor


def test_caller_cannot_supply_replay_state():
    registry, parts = world()
    crown, forge, raw, delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"n2-challenge").digest(),
    )
    replacement = RoleFreshness(forge.role_id)
    with pytest.raises(FailClosed, match="FRESHNESS"):
        forge.freshness = replacement
    with pytest.raises(FailClosed, match="UNEXPECTED_ARGUMENT"):
        forge.confirm(
            delivery, g_intent(registry, raw, parts),
            challenge_ledger=ChallengeLedger(hashlib.sha256(b"forged").digest()),
            highest_authenticated_version=0,
        )
    assert forge.machine.get(b"G" * 16).state == "CONSUMER_CONFIRMED"
    assert forge.freshness.highest == 1
    assert prove_authorization_locks().decision == CHECKS_PASSED
    assert crown.machine.get(b"G" * 16).state == "DELIVERED"


def test_tail_suppression_and_checkpoint_substitution():
    registry, parts = world()
    crown = open_role(registry, parts, "crown")
    forge = open_role(registry, parts, "forge")
    challenge = forge.issue_challenge(hashlib.sha256(b"tail").digest())
    forge.log.append(kind=KIND_GRANT, payload_digest=dig("hidden"), grant_id=b"H" * 16, epoch=1, registry_version=1)
    raw = grant_for(
        registry, parts, klass="G", target="forge", challenge=challenge, prev=forge.freshness.head,
        grant_id=b"G" * 16, tail=g_tail(parts),
    )
    crown.propose(raw)
    crown.owner_verify(b"G" * 16)
    crown.mark_signed(b"G" * 16)
    crown.append_authorization(b"G" * 16)
    checkpoint = crown.checkpoint_authorization(b"G" * 16)
    packet = crown.log.witness_request(
        checkpoint, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=1, old_tree_size=0,
    )
    monitor = open_monitor(parts, "m1")
    ack = monitor.consider(
        packet, source_public=public_of(ed_key("crown")), witness_public=public_of(ed_key("m1")),
        sink=monitor.sink, fence=monitor.fence,
    )
    crown.accept_ack(b"G" * 16, ack)
    delivery = crown.deliver(b"G" * 16)
    with pytest.raises(FailClosed, match="STALE_HEAD"):
        forge.confirm(delivery, g_intent(registry, raw, parts))
    mutated = bytearray(delivery)
    mutated[mutated.find(b"OCK1") + 10] ^= 1
    with pytest.raises(FailClosed):
        forge.confirm(bytes(mutated), g_intent(registry, raw, parts))


def test_signed_is_not_usable_and_result_label_does_not_open_locks():
    registry, parts = world()
    crown, forge, raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"egress").digest(),
    )
    digest = hashlib.sha256(b"synthetic-staged-output").digest()
    assert forge.stage_output(digest) == "ZERO_ACCEPTANCE_AUTHORITY"
    for status in ("APPROVED", "ACCEPTED", "QUALIFICATION_INPUT", "TRAINING_INPUT", "EXPORTABLE", "DEPLOYABLE"):
        with pytest.raises(FailClosed, match="ZERO_ACCEPTANCE_AUTHORITY"):
            forge.classify(digest, status)
    assert forge.activate(b"G" * 16) == "ACTIVE"
    assert forge.rehearse(b"G" * 16) == "NOT_AUTHORIZED"
    with pytest.raises(FailClosed, match="DOUBLE_EXECUTION"):
        forge.rehearse(b"G" * 16)
    forge.consume(b"G" * 16)
    forge.commit_evidence(b"G" * 16, digest)
    checkpoint = forge.log.checkpoint(forge.role_key, epoch=1, registry_version=1)
    index = forge.log.size - 1
    record = forge.log.record(index)
    inclusion = forge.log.prove_inclusion_at(index, forge.log.size)
    packet = forge.log.witness_request(
        checkpoint, source_role_id=forge.role_id, witness_id=parts["m1"].entry_id, packet_seq=7, old_tree_size=0,
    )
    monitor = open_monitor(parts, "m1")
    ack = monitor.consider(
        packet, source_public=public_of(ed_key("forge")), witness_public=public_of(ed_key("m1")),
        sink=monitor.sink, fence=monitor.fence,
    )
    forge.accept_result(digest, record=record, inclusion=inclusion, checkpoint=checkpoint, ack=ack)
    assert forge.classify(digest, "ACCEPTED") == "ACCEPTED"
    assert prove_authorization_locks().decision == CHECKS_PASSED
    with pytest.raises(FailClosed, match="CLASS_DOES_NOT_AUTHORIZE"):
        crown.promote("T", "W")
    assert forge.finish(b"G" * 16) == "COMPLETE"


def test_crash_recovery_matrix():
    registry, parts = world()
    _crown, forge, raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"crash").digest(), runtime=30,
    )
    intent = g_intent(registry, raw, parts)
    booted = reboot(forge)
    assert booted.machine.get(b"G" * 16).reconfirm_required is True
    with pytest.raises(FailClosed, match="RECONFIRM"):
        booted.activate(b"G" * 16)
    booted.reconfirm(b"G" * 16, intent)
    assert booted.activate(b"G" * 16) == "ACTIVE"
    interrupted = reboot(booted)
    assert interrupted.machine.get(b"G" * 16).state == "INTERRUPTED"
    with pytest.raises(FailClosed, match="INTERRUPTED"):
        interrupted.rehearse(b"G" * 16)
    with pytest.raises(FailClosed, match="DOUBLE_EXECUTION"):
        interrupted.rerun(b"G" * 16)


def test_evidence_pending_crash_is_not_a_rerun():
    registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"evidence-crash").digest(),
    )
    forge.activate(b"G" * 16)
    forge.consume(b"G" * 16)
    digest = hashlib.sha256(b"synthetic-evidence").digest()
    forge.commit_evidence(b"G" * 16, digest)
    restored = reboot(forge)
    assert restored.machine.get(b"G" * 16).state == "EVIDENCE_PENDING"
    with pytest.raises(FailClosed, match="GRANT_STATE"):
        restored.rehearse(b"G" * 16)
    assert restored.finish(b"G" * 16) == "COMPLETE"


def test_clock_is_advisory_and_ticks_are_monotonic():
    registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"clock").digest(), runtime=30, not_after=50,
    )
    forge.observe_clock(40)
    assert forge.machine.get(b"G" * 16).state == "CONSUMER_CONFIRMED"
    forge.observe_clock(10)
    assert forge.machine.get(b"G" * 16).state == "CONSUMER_CONFIRMED"
    forge.observe_clock(51)
    assert forge.machine.get(b"G" * 16).state == "EXPIRED"
    _crown2, live, _raw2, _delivery2 = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"H" * 16, entropy=hashlib.sha256(b"ticks").digest(), runtime=30, not_after=5,
    )
    assert live.activate(b"H" * 16) == "ACTIVE"
    live.observe_clock(10**12)
    assert live.machine.get(b"H" * 16).state == "ACTIVE"
    live.observe_ticks(30)
    assert live.machine.get(b"H" * 16).state == "ACTIVE"
    live.observe_ticks(31)
    assert live.machine.get(b"H" * 16).state == "INTERRUPTED"
    with pytest.raises(FailClosed, match="MONOTONIC"):
        live.observe_ticks(30)


def test_revocation_releases_the_role_slot():
    registry, parts = world()
    crown = open_role(registry, parts, "crown")
    raw = grant_for(
        registry, parts, klass="G", target="forge", challenge=hashlib.sha256(b"revoke").digest(),
        prev=bytes(32), grant_id=b"R" * 16, tail=g_tail(parts),
    )
    crown.propose(raw)
    assert crown.revoke(b"R" * 16) == "REVOKED"
    other = grant_for(
        registry, parts, klass="G", target="forge", challenge=hashlib.sha256(b"next").digest(),
        prev=bytes(32), grant_id=b"N" * 16, tail=g_tail(parts),
    )
    assert crown.propose(other) == "PROPOSED"


def test_tampered_consumer_confirmed_with_consumption_is_quarantined():
    registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"quarantine-flag").digest(),
    )
    blob = bytearray(forge.dump())
    at = blob.find(b"OGJ1")
    blob[at + 5 + 4 + 16 + 2] |= 1
    with pytest.raises(FailClosed, match="FENCE"):
        reboot(forge, bytes(blob))


def test_empty_log_parses_and_duplicate_ack_conflicts():
    log = EvidenceLog(bytes(range(32)), 1)
    restored = EvidenceLog.parse(log.export(), bytes(32))
    assert restored.size == 0
    log.append(kind=1, payload_digest=dig("one"), grant_id=bytes(16), epoch=1, registry_version=1)
    checkpoint = log.checkpoint(ed_key("crown"), epoch=1, registry_version=1)
    assert len(checkpoint) == 181
    ack = pack_ack(
        witness_id=bytes([7]) * 32, source_role_id=log.log_id, log_id=log.log_id,
        tree_size=1, root=log.root, epoch=1, witness_time=0, witness_key=ed_key("m1"),
    )
    log.store_ack(ack)
    log.store_ack(ack)
    conflict = pack_ack(
        witness_id=bytes([7]) * 32, source_role_id=log.log_id, log_id=log.log_id,
        tree_size=1, root=log.root, epoch=1, witness_time=1, witness_key=ed_key("m1"),
    )
    with pytest.raises(FailClosed, match="ACK_CONFLICT"):
        log.store_ack(conflict)
