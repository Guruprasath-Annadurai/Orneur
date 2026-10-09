"""Adversarial campaign for the master-block-1 remediation.

Synthetic fixtures only. The fence and the checker are software. They are
not a TPM and they are not a sandbox.
"""

from __future__ import annotations

import hashlib
import os
import resource
import tempfile

import pytest
from orca.rse.imp1.codec import public_of
from orca.rse.imp1.locks import prove_authorization_locks
from orca.rse.imp1.verdict import CHECKS_PASSED, FailClosed, Quarantine
from orca.rse.imp2.machine import INTERRUPTED
from orca.rse.imp3.freshness import MAX_SET, RoleFreshness
from orca.rse.imp3.journal import SYNTHETIC_NOT_REAL_HARDWARE_PROOF, MemorySink, SyntheticFence
from orca.rse.imp3.ledger import EvidenceLog, Monitor, verify_grant_inclusion
from orca.rse.imp3.records import KIND_GRANT, pack_checkpoint, pack_witness_request
from orca.rse.imp3.session import Session
from orca.rse.imp4.ocr1 import (
    CHECKER_ISOLATION,
    RecipientJournal,
    Sender,
    build_header,
    ingest_phase1,
    ingest_phase2,
    ochk,
    run_keyless_checker,
)
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
    x_pub,
)
from tests.rse.support import dig
from tests.rse.test_imp4_ocr1 import _seal


class _Boom:
    def commit(self, _blob: bytes) -> None:
        raise OSError("commit failed")


class _Partial:
    def __init__(self) -> None:
        self.blob = b""

    def commit(self, blob: bytes) -> None:
        self.blob = bytes(blob[:12])
        raise OSError("short write")


class _StoreThenFail:
    def __init__(self) -> None:
        self.blob = b""

    def commit(self, blob: bytes) -> None:
        self.blob = bytes(blob)
        raise OSError("after write")


class _Hold:
    def __init__(self) -> None:
        self.blob = b""

    def commit(self, blob: bytes) -> None:
        self.blob = bytes(blob)


def _confirmed(label: bytes = b"fence"):
    registry, parts = world()
    _crown, forge, raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(label).digest(),
    )
    return registry, parts, forge, raw


def test_commit_before_active_and_rollback_cannot_execute_twice():
    _registry, _parts, forge, _raw = _confirmed(b"pre-activation")
    pre = forge.sink.blob
    fence = forge.fence
    floor = fence.floor
    assert fence.label == SYNTHETIC_NOT_REAL_HARDWARE_PROOF
    assert floor >= 1
    assert forge.activate(b"G" * 16) == "ACTIVE"
    assert forge.fence.floor == floor + 1
    assert forge.sink.blob.startswith(b"OBS1")
    assert forge.rehearse(b"G" * 16) == "NOT_AUTHORIZED"
    with pytest.raises(FailClosed, match="FENCE"):
        reboot(forge, pre)
    with pytest.raises(FailClosed, match="DOUBLE_EXECUTION"):
        forge.rehearse(b"G" * 16)
    restored = reboot(forge)
    assert restored.machine.get(b"G" * 16).state == INTERRUPTED
    with pytest.raises(FailClosed, match="INTERRUPTED"):
        restored.rehearse(b"G" * 16)


def test_failed_and_partial_commit_do_not_return_active():
    _registry, _parts, forge, _raw = _confirmed(b"failed-commit")
    floor = forge.fence.floor
    forge.sink = _Boom()
    with pytest.raises(FailClosed, match="JOURNAL_COMMIT"):
        forge.activate(b"G" * 16)
    assert forge.machine.get(b"G" * 16).state == INTERRUPTED
    assert forge.fence.floor == floor
    with pytest.raises(FailClosed, match="INTERRUPTED"):
        forge.rehearse(b"G" * 16)
    with pytest.raises(FailClosed, match="JOURNAL_COMMIT"):
        forge.activate(b"G" * 16)

    _registry, _parts, live, _raw = _confirmed(b"partial-commit")
    pre = live.sink.blob
    floor = live.fence.floor
    partial = _Partial()
    live.sink = partial
    with pytest.raises(FailClosed, match="JOURNAL_COMMIT"):
        live.activate(b"G" * 16)
    assert live.fence.floor == floor
    with pytest.raises(FailClosed, match="JOURNAL"):
        reboot(live, partial.blob)
    retried = reboot(live, pre)
    assert retried.machine.get(b"G" * 16).state == "CONSUMER_CONFIRMED"

    _registry, _parts, stored, _raw = _confirmed(b"store-then-fail")
    authenticated = stored.sink.blob
    floor = stored.fence.floor
    holder = _StoreThenFail()
    stored.sink = holder
    with pytest.raises(FailClosed, match="JOURNAL_COMMIT"):
        stored.activate(b"G" * 16)
    assert stored.fence.floor == floor
    with pytest.raises(FailClosed, match="FENCE"):
        reboot(stored, holder.blob)
    booted = reboot(stored, authenticated)
    assert booted.machine.get(b"G" * 16).state == "CONSUMER_CONFIRMED"
    with pytest.raises(FailClosed, match="INTERRUPTED"):
        stored.rehearse(b"G" * 16)


def test_recipient_journal_is_session_owned_and_survives_restart():
    registry, parts = world()
    _crown, witness, _raw, _delivery = authorize(
        registry, parts, klass="V", target="witness", tail=v_tail(parts), intent_for=v_intent,
        grant_id=b"V" * 16, entropy=hashlib.sha256(b"replay-journal").digest(),
    )
    frames = list(_seal(parts, ochk(b"durable-replay"), entropy=hashlib.sha256(b"durable-replay-entropy").digest()))
    phase1 = ingest_phase1(witness, b"V" * 16, frames)
    assert witness.activate(b"V" * 16) == "ACTIVE"
    pre = witness.sink.blob
    fence = witness.fence
    with pytest.raises(FailClosed, match="UNEXPECTED_ARGUMENT"):
        ingest_phase2(
            witness, b"V" * 16, frames, recipient_private=x_key("witness"),
            quarantine=phase1["quarantine"], journal=RecipientJournal(),
        )
    opened = ingest_phase2(
        witness, b"V" * 16, frames, recipient_private=x_key("witness"), quarantine=phase1["quarantine"],
    )
    assert opened["acceptance"] == "ZERO_ACCEPTANCE_AUTHORITY"
    with pytest.raises(FailClosed, match="REPLAY"):
        ingest_phase2(
            witness, b"V" * 16, frames, recipient_private=x_key("witness"), quarantine=phase1["quarantine"],
        )
    with pytest.raises(FailClosed, match="FENCE"):
        reboot(witness, pre)
    restored = reboot(witness)
    with pytest.raises(FailClosed, match="REPLAY"):
        restored.recipient.reject_replay(
            grant_id=b"V" * 16, sequence=1, enc=frames[0][178:210], bundle_digest=frames[0][118:150],
            sender_id=parts["forge"].entry_id,
        )
    with pytest.raises(FailClosed):
        ingest_phase2(
            restored, b"V" * 16, frames, recipient_private=x_key("witness"), quarantine=phase1["quarantine"],
        )


def test_monitor_journal_keeps_fork_history_across_restart():
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
    fence = monitor.fence
    sink = monitor.sink
    bound = dict(sink=sink, fence=fence)
    ack = monitor.consider(request, source_public=source, witness_public=witness, **bound)
    assert ack == monitor.consider(request, source_public=source, witness_public=witness, **bound)
    fresh = open_monitor(parts, "m1")
    assert fresh._last == {}
    with pytest.raises(FailClosed, match="FENCE"):
        Monitor.boot(monitor.export(), ed_key("m1"), sink=MemorySink(), fence=fresh.fence)
    with pytest.raises(FailClosed, match="FENCE"):
        Monitor.boot(monitor.export(), ed_key("m1"), sink=MemorySink(), fence=SyntheticFence())
    restored = Monitor.boot(monitor.export(), ed_key("m1"), sink=MemorySink(), fence=fence)
    assert restored.registry_version == 1
    assert restored.log_root == crown.log.root
    assert restored.generation == fence.floor
    restored_bound = dict(sink=restored.sink, fence=restored.fence)
    genesis_again = pack_witness_request(
        packet_seq=2, source_role_id=crown.role_id, target_witness_id=parts["m1"].entry_id,
        checkpoint=first, old_tree_size=0, proof=(),
    )
    with pytest.raises(FailClosed, match="CONSISTENCY"):
        restored.consider(genesis_again, source_public=source, witness_public=witness, **restored_bound)
    replay = bytearray(request)
    replay[12] = 0
    with pytest.raises(FailClosed, match="PACKET_REPLAY"):
        restored.consider(bytes(replay), source_public=source, witness_public=witness, **restored_bound)
    forged = pack_checkpoint(
        log_id=crown.role_id, tree_size=1, root=bytes(31) + b"\xff", epoch=1, registry_version=1,
        prev_checkpoint_digest=bytes(32), role_key=ed_key("crown"),
    )
    fork_request = pack_witness_request(
        packet_seq=2, source_role_id=crown.role_id, target_witness_id=parts["m1"].entry_id,
        checkpoint=forged, old_tree_size=1, proof=(),
    )
    with pytest.raises(Quarantine, match="FORK"):
        restored.consider(fork_request, source_public=source, witness_public=witness, **restored_bound)
    crown.log.append(kind=3, payload_digest=dig("tail"), grant_id=bytes(16), epoch=1, registry_version=1)
    second = crown.log.checkpoint(crown.role_key, epoch=1, registry_version=1)
    grown = crown.log.witness_request(
        second, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=3, old_tree_size=1,
    )
    first_journal = bytes(sink.blob)
    restored.consider(grown, source_public=source, witness_public=witness, **restored_bound)
    rolled = pack_checkpoint(
        log_id=crown.role_id, tree_size=1, root=first[45:77], epoch=1, registry_version=1,
        prev_checkpoint_digest=bytes(32), role_key=ed_key("crown"),
    )
    rollback = pack_witness_request(
        packet_seq=4, source_role_id=crown.role_id, target_witness_id=parts["m1"].entry_id,
        checkpoint=rolled, old_tree_size=crown.log.size, proof=(),
    )
    again = Monitor.boot(restored.export(), ed_key("m1"), sink=MemorySink(), fence=restored.fence)
    with pytest.raises(FailClosed, match="ROLLBACK"):
        again.consider(
            rollback, source_public=source, witness_public=witness, sink=again.sink, fence=again.fence,
        )
    with pytest.raises(FailClosed, match="FENCE"):
        Monitor.boot(first_journal, ed_key("m1"), sink=MemorySink(), fence=restored.fence)


def test_freshness_ranges_round_trip_and_excess_fails_closed():
    role = bytes(range(32))
    freshness = RoleFreshness(role)
    freshness.forfeit_sequences(1, 5000)
    restored = RoleFreshness.parse(freshness.export())
    assert restored.sequence_forfeited(1) and restored.sequence_forfeited(5000)
    assert restored.sequence_forfeited(5001) is False
    assert len(restored._forfeited) == 1
    wide = RoleFreshness(role)
    for index in range(4101):
        wide.issue(hashlib.sha256(index.to_bytes(4, "big")).digest(), head=bytes(32))
    assert len(wide._voided) == 4100
    parsed = RoleFreshness.parse(wide.export())
    assert len(parsed._voided) == 4100
    capped = RoleFreshness(role)
    for index in range(MAX_SET):
        capped.note_dead_grant(index.to_bytes(16, "big"))
    RoleFreshness.parse(capped.export())
    with pytest.raises(FailClosed, match="FRESHNESS"):
        capped.note_dead_grant(MAX_SET.to_bytes(16, "big"))
    RoleFreshness.parse(capped.export())
    broken = bytearray(freshness.export())
    broken[4] = 1
    with pytest.raises(FailClosed, match="FRESHNESS"):
        RoleFreshness.parse(bytes(broken))
    overlap = bytearray(freshness.export())
    overlap += bytes(16)
    with pytest.raises(FailClosed, match="TRAILING|FRESHNESS"):
        RoleFreshness.parse(bytes(overlap))


def test_enc_divergence_quarantine_is_committed_before_it_is_reported():
    registry, parts = world()
    _crown, witness, _raw, _delivery = authorize(
        registry, parts, klass="V", target="witness", tail=v_tail(parts, 1, 4), intent_for=v_intent,
        grant_id=b"V" * 16, entropy=hashlib.sha256(b"divergence").digest(),
    )
    frames = list(_seal(parts, ochk(b"first-bundle"), entropy=hashlib.sha256(b"div-entropy").digest()))
    phase1 = ingest_phase1(witness, b"V" * 16, frames)
    witness.activate(b"V" * 16)
    ingest_phase2(witness, b"V" * 16, frames, recipient_private=x_key("witness"), quarantine=phase1["quarantine"])
    mutant = bytearray(frames[0])
    mutant[118:150] = b"\x02" * 32
    mutant[150:158] = (2).to_bytes(8, "big")
    header = bytes(mutant[:210])
    ciphertext = bytes(mutant[210:-64])
    signature = ed_key("forge").sign(b"OCR1v2-SIG\x00" + header + ciphertext)
    diverged = [header + ciphertext + signature]
    phase = ingest_phase1(witness, b"V" * 16, diverged)
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        ingest_phase2(
            witness, b"V" * 16, diverged, recipient_private=x_key("witness"), quarantine=phase["quarantine"],
        )
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        ingest_phase2(
            witness, b"V" * 16, diverged, recipient_private=x_key("witness"), quarantine=phase["quarantine"],
        )
    assert witness.machine.get(b"V" * 16).state == "QUARANTINED"
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        ingest_phase1(witness, b"V" * 16, diverged)
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        witness.consume(b"V" * 16)
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        witness.commit_evidence(b"V" * 16, bytes(32))
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        witness.finish(b"V" * 16)
    with pytest.raises(FailClosed, match="OUTSTANDING_GRANT"):
        witness.machine.add(b"N" * 16, witness.role_id, ord("V"))
    restored = reboot(witness)
    assert restored.machine.get(b"V" * 16).state == "QUARANTINED"
    assert restored.recipient.grant_quarantined(b"V" * 16) is True
    assert restored.recipient.sender_quarantined(parts["forge"].entry_id) is True
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        ingest_phase2(
            restored, b"V" * 16, diverged, recipient_private=x_key("witness"), quarantine=phase["quarantine"],
        )
    with pytest.raises(Quarantine, match="ENC_DIVERGENCE"):
        restored.recipient.reject_replay(
            grant_id=b"Z" * 16, sequence=9, enc=bytes([9]) + bytes(31), bundle_digest=bytes([4]) * 32,
            sender_id=parts["forge"].entry_id,
        )
    restored.recipient.reject_replay(
        grant_id=b"Y" * 16, sequence=9, enc=bytes([8]) + bytes(31), bundle_digest=bytes([5]) * 32,
        sender_id=bytes([9]) * 32,
    )


def test_grant_epoch_and_registry_are_bound_into_inclusion():
    registry, parts = world()
    raw = grant_for(
        registry, parts, klass="G", target="forge", challenge=hashlib.sha256(b"bind").digest(),
        prev=bytes(32), grant_id=b"G" * 16, tail=g_tail(parts),
    )
    log = EvidenceLog(parts["crown"].entry_id, 1)
    log.append(
        kind=KIND_GRANT, payload_digest=hashlib.sha256(raw).digest(), grant_id=b"G" * 16,
        epoch=9, registry_version=registry.registry_version,
    )
    checkpoint = log.checkpoint(ed_key("crown"), epoch=9, registry_version=registry.registry_version)
    with pytest.raises(FailClosed, match="EPOCH"):
        verify_grant_inclusion(
            grant_raw=raw, record=log.record(0), inclusion=log.prove_inclusion_at(0, 1),
            checkpoint=checkpoint, crown_public=public_of(ed_key("crown")),
        )
    other = EvidenceLog(parts["crown"].entry_id, 1)
    other.append(
        kind=KIND_GRANT, payload_digest=hashlib.sha256(raw).digest(), grant_id=b"G" * 16,
        epoch=1, registry_version=9,
    )
    other_head = other.checkpoint(ed_key("crown"), epoch=1, registry_version=9)
    with pytest.raises(FailClosed, match="REGISTRY"):
        verify_grant_inclusion(
            grant_raw=raw, record=other.record(0), inclusion=other.prove_inclusion_at(0, 1),
            checkpoint=other_head, crown_public=public_of(ed_key("crown")),
        )


def test_note_witnessed_is_not_acceptance_and_tree_size_is_checked():
    registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"egress-guard").digest(),
    )
    digest = hashlib.sha256(b"synthetic-staged-output").digest()
    with pytest.raises(FailClosed, match="RESULT_EGRESS"):
        forge.egress.note_witnessed(digest)
    with pytest.raises(FailClosed, match="ZERO_ACCEPTANCE_AUTHORITY"):
        forge.classify(digest, "TRAINING_INPUT")
    forge.activate(b"G" * 16)
    forge.consume(b"G" * 16)
    forge.commit_evidence(b"G" * 16, digest)
    checkpoint = forge.log.checkpoint(forge.role_key, epoch=1, registry_version=1)
    record = forge.log.record(forge.log.size - 1)
    inclusion = forge.log.prove_inclusion_at(forge.log.size - 1, forge.log.size)
    packet = forge.log.witness_request(
        checkpoint, source_role_id=forge.role_id, witness_id=parts["m1"].entry_id, packet_seq=7, old_tree_size=0,
    )
    monitor = open_monitor(parts, "m1")
    ack = monitor.consider(
        packet, source_public=public_of(ed_key("forge")), witness_public=public_of(ed_key("m1")),
        sink=monitor.sink, fence=monitor.fence,
    )
    forged = bytearray(inclusion)
    forged[45:53] = (99).to_bytes(8, "big")
    with pytest.raises(FailClosed, match="CHECKPOINT"):
        forge.accept_result(digest, record=record, inclusion=bytes(forged), checkpoint=checkpoint, ack=ack)
    forge.accept_result(digest, record=record, inclusion=inclusion, checkpoint=checkpoint, ack=ack)
    assert forge.classify(digest, "ACCEPTED") == "ACCEPTED"
    assert prove_authorization_locks().decision == CHECKS_PASSED


def test_checker_is_labeled_synthetic_and_cleans_its_directory(monkeypatch):
    assert CHECKER_ISOLATION == "SYNTHETIC_NOT_A_SANDBOX"
    before = {name for name in os.listdir(tempfile.gettempdir()) if name.startswith("rse-keyless-")}
    assert run_keyless_checker(ochk(b"ok")) == "STRUCTURAL_OK"
    after = {name for name in os.listdir(tempfile.gettempdir()) if name.startswith("rse-keyless-")}
    assert after <= before

    def refuse(*_args, **_kwargs):
        raise OSError("setrlimit refused")

    monkeypatch.setattr(resource, "setrlimit", refuse)
    with pytest.raises(FailClosed, match="CHECKER"):
        run_keyless_checker(ochk(b"limited"))


def test_malformed_session_journal_fails_closed():
    _registry, _parts, forge, _raw = _confirmed(b"malformed")
    with pytest.raises(FailClosed, match="GRANT_ABSENT"):
        forge._forfeit(b"\x11" * 16)
    with pytest.raises(FailClosed, match="FENCE"):
        Session.boot(forge.sink.blob, role_key=ed_key("forge"), floors=forge.floors, tokens=forge.tokens)
    with pytest.raises(FailClosed, match="FENCE"):
        Session.boot(
            forge.sink.blob, role_key=ed_key("forge"), floors=forge.floors, tokens=forge.tokens,
            sink=MemorySink(), fence=SyntheticFence(),
        )
    with pytest.raises(FailClosed, match="JOURNAL"):
        reboot(forge, forge.sink.blob[:40])
    broken = bytearray(forge.sink.blob)
    broken[4] = 9
    with pytest.raises(FailClosed, match="JOURNAL|FENCE"):
        reboot(forge, bytes(broken))
    replaced = bytearray(forge.sink.blob)
    at = replaced.find(b"OFJ1")
    replaced[at + 4] = 0
    with pytest.raises(FailClosed, match="JOURNAL|FRESHNESS|FENCE"):
        reboot(forge, bytes(replaced))


def test_hedge_counter_is_committed_before_seal_returns():
    registry, parts = world()
    _crown, forge, _raw, _delivery = authorize(
        registry, parts, klass="G", target="forge", tail=g_tail(parts), intent_for=g_intent,
        grant_id=b"G" * 16, entropy=hashlib.sha256(b"hedge").digest(),
    )
    sender = Sender(ed_key("forge"), parts["forge"].entry_id, dig("env-forge"))
    kwargs = dict(
        plaintext=ochk(b"hedged"), typ=1, recipient_id=parts["witness"].entry_id,
        recipient_public=x_pub("witness"), grant_id=b"V" * 16, artifact_id=parts["corpus"].entry_id,
        sequence=1, epoch=1, os_entropy=bytes([2]) * 32,
    )
    authenticated = forge.sink.blob
    forge.sink = _Boom()
    with pytest.raises(FailClosed, match="JOURNAL_COMMIT"):
        forge.seal_frames(sender, **kwargs)
    assert forge.counters.nxt == 1
    with pytest.raises(FailClosed, match="JOURNAL_COMMIT"):
        forge.seal_frames(sender, **kwargs)
    restored = reboot(forge, authenticated)
    frames = restored.seal_frames(sender, **kwargs)
    assert frames[0][:4] == b"OCR1"
    restarted = reboot(restored)
    again = Sender(ed_key("forge"), parts["forge"].entry_id, dig("env-forge"))
    with pytest.raises(FailClosed, match="COUNTER_REUSE"):
        restarted.seal_frames(again, **kwargs)


def test_authorization_locks_remain_denied_after_the_campaign():
    assert prove_authorization_locks().decision == CHECKS_PASSED
