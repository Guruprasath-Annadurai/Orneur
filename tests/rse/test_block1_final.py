"""B-1, B-2, and B-3 regressions.

Synthetic fences only. Nothing here is a TPM NV index or a class-K recovery.
"""

from __future__ import annotations

import hashlib

import pytest

from orca.rse.imp1.verdict import FailClosed, Quarantine
from orca.rse.imp3.journal import SYNTHETIC_NOT_REAL_HARDWARE_PROOF, MemorySink, SyntheticFence
from orca.rse.imp3.ledger import Monitor
from orca.rse.imp3.records import KIND_CONSUMPTION, KIND_INTERRUPTION, parse_record
from orca.rse.imp3.session import Session
from orca.rse.imp4.ocr1 import ingest_phase1, ingest_phase2, ochk
from tests.rse.block1_support import (
    authorize,
    ed_key,
    g_intent,
    g_tail,
    grant_for,
    open_monitor,
    open_role,
    reboot,
    v_intent,
    v_tail,
    world,
    x_key,
)
from tests.rse.test_imp4_ocr1 import _seal


def test_missing_and_virgin_fence_cannot_restore_history():
    registry, parts = world()
    forge = open_role(registry, parts, "forge")
    assert forge.fence.label == SYNTHETIC_NOT_REAL_HARDWARE_PROOF
    assert forge.fence.floor == 1
    blob = forge.sink.blob
    with pytest.raises(FailClosed, match="FENCE"):
        Session(
            role_id=parts["forge"].entry_id, role_key=ed_key("forge"), epoch=1, authority_version=1,
            floors=forge.floors, tokens=forge.tokens, registry_raw=registry.raw,
            crown_image_id=parts["image"].entry_id, m1_id=parts["m1"].entry_id, m2_id=parts["m2"].entry_id,
        )
    with pytest.raises(FailClosed, match="FENCE"):
        Session.boot(blob, role_key=ed_key("forge"), floors=forge.floors, tokens=forge.tokens)
    with pytest.raises(FailClosed, match="FENCE"):
        Session.boot(
            blob, role_key=ed_key("forge"), floors=forge.floors, tokens=forge.tokens,
            sink=MemorySink(), fence=SyntheticFence(),
        )
    with pytest.raises(FailClosed, match="FENCE"):
        forge.fence.pin_observed(1, hashlib.sha256(blob).digest())
    forged = SyntheticFence()
    with pytest.raises(FailClosed, match="FENCE"):
        forged.advance(2, hashlib.sha256(blob).digest())
    assert reboot(forge).role_id == forge.role_id


def test_old_journal_invalid_generation_and_monitor_rollback():
    registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"old-journal").digest(),
    )
    before = forge.sink.blob
    forge.activate(b"G" * 16)
    with pytest.raises(FailClosed, match="FENCE"):
        reboot(forge, before)
    with pytest.raises(FailClosed, match="FENCE"):
        forge.fence.authenticate(0, forge.fence.digest)
    with pytest.raises(FailClosed, match="FENCE"):
        forge.fence.authenticate(forge.fence.floor + 1, forge.fence.digest)
    restarted = reboot(forge)
    assert restarted.machine.get(b"G" * 16).state == "INTERRUPTED"
    with pytest.raises(FailClosed, match="INTERRUPTED"):
        restarted.rehearse(b"G" * 16)

    monitor = open_monitor(parts, "m1")
    crown = open_role(registry, parts, "crown")
    crown.log.append(kind=1, payload_digest=hashlib.sha256(b"boot").digest(), grant_id=bytes(16), epoch=1, registry_version=1)
    first = crown.log.checkpoint(crown.role_key, epoch=1, registry_version=1)
    from orca.rse.imp1.codec import public_of
    from orca.rse.imp3.records import pack_witness_request
    source = public_of(ed_key("crown"))
    witness = public_of(ed_key("m1"))
    request = crown.log.witness_request(
        first, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=1, old_tree_size=0,
    )
    ack = monitor.consider(request, source_public=source, witness_public=witness, sink=monitor.sink, fence=monitor.fence)
    assert monitor.consider(
        request, source_public=source, witness_public=witness, sink=monitor.sink, fence=monitor.fence,
    ) == ack
    saved = monitor.sink.blob
    crown.log.append(kind=3, payload_digest=hashlib.sha256(b"tail").digest(), grant_id=bytes(16), epoch=1, registry_version=1)
    second = crown.log.checkpoint(crown.role_key, epoch=1, registry_version=1)
    grown = crown.log.witness_request(
        second, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=2, old_tree_size=1,
    )
    monitor.consider(grown, source_public=source, witness_public=witness, sink=monitor.sink, fence=monitor.fence)
    with pytest.raises(FailClosed, match="FENCE"):
        Monitor.boot(saved, ed_key("m1"), sink=MemorySink(), fence=monitor.fence)
    booted = Monitor.boot(monitor.sink.blob, ed_key("m1"), sink=MemorySink(), fence=monitor.fence)
    replay = pack_witness_request(
        packet_seq=1, source_role_id=crown.role_id, target_witness_id=parts["m1"].entry_id,
        checkpoint=first, old_tree_size=1, proof=(),
    )
    with pytest.raises(FailClosed, match="PACKET_REPLAY"):
        booted.consider(replay, source_public=source, witness_public=witness, sink=booted.sink, fence=booted.fence)


def test_persistence_failure_closes_the_session():
    _registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        _registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"persist-fail").digest(),
    )

    class _Boom:
        def commit(self, _blob: bytes) -> None:
            raise OSError("disk")

    authenticated = forge.sink.blob
    forge.sink = _Boom()
    with pytest.raises(FailClosed, match="JOURNAL_COMMIT"):
        forge.issue_challenge(hashlib.sha256(b"next-entropy-is-32-bytes!!").digest()[:32])
    with pytest.raises(FailClosed, match="JOURNAL_COMMIT"):
        forge.revoke(b"G" * 16)
    recovered = reboot(forge, authenticated)
    assert recovered.machine.get(b"G" * 16).state == "CONSUMER_CONFIRMED"


def test_second_grant_covers_consumption_and_refuses_stale_heads():
    registry, parts = world()
    _crown, forge, raw, delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"first-grant").digest(),
    )
    first_head = parse_grant_head(raw)
    forge.activate(b"G" * 16)
    forge.consume(b"G" * 16)
    forge.commit_evidence(b"G" * 16, hashlib.sha256(b"done").digest())
    assert forge.finish(b"G" * 16) == "COMPLETE"
    with pytest.raises(FailClosed, match="CHALLENGE_REPLAY"):
        forge.issue_challenge(hashlib.sha256(b"first-grant").digest())
    second_entropy = hashlib.sha256(b"second-grant").digest()
    challenge = forge.issue_challenge(second_entropy)
    assert forge.freshness.head != first_head
    assert KIND_CONSUMPTION in {parse_record(item)["kind"] for item in forge.log.records_since(0)}
    stale = grant_for(
        registry, parts, klass="G", target="forge", challenge=challenge, prev=first_head,
        grant_id=b"S" * 16, tail=g_tail(parts),
    )
    with pytest.raises(FailClosed, match="STALE_HEAD"):
        forge.confirm(delivery_of(registry, parts, stale), g_intent(registry, stale, parts))
    forked = grant_for(
        registry, parts, klass="G", target="forge", challenge=challenge,
        prev=hashlib.sha256(b"not-an-ancestor").digest(), grant_id=b"F" * 16, tail=g_tail(parts),
    )
    with pytest.raises(FailClosed, match="STALE_HEAD"):
        forge.confirm(delivery_of(registry, parts, forked), g_intent(registry, forked, parts))
    fresh = grant_for(
        registry, parts, klass="G", target="forge", challenge=challenge, prev=forge.freshness.head,
        grant_id=b"H" * 16, tail=g_tail(parts),
    )
    assert forge.confirm(delivery_of(registry, parts, fresh), g_intent(registry, fresh, parts)) == "CONSUMER_CONFIRMED"
    with pytest.raises(FailClosed, match="CHALLENGE|STALE_HEAD"):
        forge.confirm(delivery, g_intent(registry, raw, parts))
    assert forge.activate(b"H" * 16) == "ACTIVE"


def test_interrupted_grant_needs_a_new_authorized_grant():
    registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"interrupt-grant").digest(),
    )
    assert forge.activate(b"G" * 16) == "ACTIVE"
    assert forge.incident(b"G" * 16) == "INTERRUPTED"
    assert any(parse_record(item)["kind"] == KIND_INTERRUPTION for item in forge.log.records_since(0))
    with pytest.raises(FailClosed, match="INTERRUPTED|FORBIDDEN_TRANSITION|GRANT_STATE"):
        forge.activate(b"G" * 16)
    restarted = reboot(forge)
    assert restarted.machine.get(b"G" * 16).state == "INTERRUPTED"
    _crown2, restarted, _raw2, _delivery2 = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"I" * 16, entropy=hashlib.sha256(b"after-interrupt").digest(), consumer=restarted,
    )
    assert restarted.activate(b"I" * 16) == "ACTIVE"
    crashed = reboot(restarted)
    assert crashed.machine.get(b"I" * 16).state == "INTERRUPTED"
    with pytest.raises(FailClosed, match="INTERRUPTED"):
        crashed.rehearse(b"I" * 16)


def test_missing_witness_and_forked_history_stay_refused():
    registry, parts = world()
    crown = open_role(registry, parts, "crown")
    forge = open_role(registry, parts, "forge")
    challenge = forge.issue_challenge(hashlib.sha256(b"missing-witness").digest())
    raw = grant_for(
        registry, parts, klass="G", target="forge", challenge=challenge, prev=forge.freshness.head,
        grant_id=b"G" * 16, tail=g_tail(parts),
    )
    crown.propose(raw)
    crown.owner_verify(b"G" * 16)
    crown.mark_signed(b"G" * 16)
    crown.append_authorization(b"G" * 16)
    checkpoint = crown.checkpoint_authorization(b"G" * 16)
    with pytest.raises(FailClosed, match="GRANT_STATE"):
        crown.deliver(b"G" * 16)
    packet = crown.log.witness_request(
        checkpoint, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=1, old_tree_size=0,
    )
    from orca.rse.imp1.codec import public_of
    monitor = open_monitor(parts, "m1")
    ack = monitor.consider(
        packet, source_public=public_of(ed_key("crown")), witness_public=public_of(ed_key("m1")),
        sink=monitor.sink, fence=monitor.fence,
    )
    assert crown.accept_ack(b"G" * 16, ack) == "CHECKPOINTED"
    other = hashlib.sha256(b"different-root").digest()
    from orca.rse.imp3.records import pack_checkpoint, pack_witness_request
    forged = pack_checkpoint(
        log_id=crown.role_id, tree_size=crown.log.size, root=other, epoch=1, registry_version=1,
        prev_checkpoint_digest=crown.log.head, role_key=ed_key("crown"),
    )
    fork = pack_witness_request(
        packet_seq=2, source_role_id=crown.role_id, target_witness_id=parts["m1"].entry_id,
        checkpoint=forged, old_tree_size=crown.log.size, proof=(),
    )
    with pytest.raises(Quarantine, match="FORK"):
        monitor.consider(
            fork, source_public=public_of(ed_key("crown")), witness_public=public_of(ed_key("m1")),
            sink=monitor.sink, fence=monitor.fence,
        )


def test_enc_divergence_quarantines_the_grant_and_the_sender():
    registry, parts = world()
    _crown, witness, _raw, _delivery = authorize(
        registry, parts, klass="V", target="witness", tail=v_tail(parts, 1, 4), intent_for=v_intent,
        grant_id=b"V" * 16, entropy=hashlib.sha256(b"quarantine-sender").digest(),
    )
    frames = list(_seal(parts, ochk(b"bundle"), entropy=hashlib.sha256(b"quarantine-entropy").digest()))
    phase1 = ingest_phase1(witness, b"V" * 16, frames)
    witness.activate(b"V" * 16)
    ingest_phase2(witness, b"V" * 16, frames, recipient_private=x_key("witness"), quarantine=phase1["quarantine"])
    mutant = bytearray(frames[0])
    mutant[118:150] = b"\x11" * 32
    mutant[150:158] = (2).to_bytes(8, "big")
    header = bytes(mutant[:210])
    body = header + bytes(mutant[210:-64])
    diverged = [body + ed_key("forge").sign(b"OCR1v2-SIG\x00" + body)]
    phase = ingest_phase1(witness, b"V" * 16, diverged)
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        ingest_phase2(
            witness, b"V" * 16, diverged, recipient_private=x_key("witness"), quarantine=phase["quarantine"],
        )
    assert witness.machine.get(b"V" * 16).state == "QUARANTINED"
    assert witness.recipient.sender_quarantined(parts["forge"].entry_id) is True
    for call in (
        lambda: ingest_phase1(witness, b"V" * 16, diverged),
        lambda: witness.consume(b"V" * 16),
        lambda: witness.commit_evidence(b"V" * 16, hashlib.sha256(b"nope").digest()),
        lambda: witness.finish(b"V" * 16),
        lambda: witness.rehearse(b"V" * 16),
    ):
        with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
            call()
    with pytest.raises(FailClosed, match="OUTSTANDING_GRANT"):
        witness.machine.add(b"W" * 16, witness.role_id, ord("V"))
    restored = reboot(witness)
    assert restored.machine.get(b"V" * 16).state == "QUARANTINED"
    assert restored.recipient.sender_quarantined(parts["forge"].entry_id) is True
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        ingest_phase1(restored, b"V" * 16, frames)
    with pytest.raises(FailClosed, match="OUTSTANDING_GRANT"):
        restored.machine.add(b"W" * 16, restored.role_id, ord("V"))


def parse_grant_head(raw: bytes) -> bytes:
    from orca.rse.imp1.codec import parse_grant
    return parse_grant(raw).prev_role_checkpoint


def delivery_of(registry, parts, raw: bytes) -> bytes:
    """Build a crown delivery for a grant that must still fail ancestor checks."""
    from orca.rse.imp1.codec import public_of
    crown = open_role(registry, parts, "crown")
    grant_id = raw[6:22]
    crown.propose(raw)
    crown.owner_verify(grant_id)
    crown.mark_signed(grant_id)
    crown.append_authorization(grant_id)
    checkpoint = crown.checkpoint_authorization(grant_id)
    packet = crown.log.witness_request(
        checkpoint, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=1, old_tree_size=0,
    )
    monitor = open_monitor(parts, "m1")
    ack = monitor.consider(
        packet, source_public=public_of(ed_key("crown")), witness_public=public_of(ed_key("m1")),
        sink=monitor.sink, fence=monitor.fence,
    )
    crown.accept_ack(grant_id, ack)
    return crown.deliver(grant_id)
