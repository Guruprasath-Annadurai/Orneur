"""Synthetic IMP-2/3/4 fixtures. Seeds are labels, not owner secrets."""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from orca.rse.imp1.authority import IntentSheet, ceilings_of, grant_sas
from orca.rse.imp1.codec import build_grant_prefix, parse_grant, public_of, sign_grant
from orca.rse.imp1.profiles import ROLE_CROWN, ROLE_FORGE, ROLE_MONITOR_LITE, ROLE_WITNESS
from orca.rse.imp3.journal import MemorySink, SyntheticFence
from orca.rse.imp3.ledger import Monitor
from orca.rse.imp3.session import Session
from tests.rse.support import (
    FLOORS,
    OWNERS,
    TOKENS,
    bit,
    dig,
    make_destination,
    pack_enrolment,
    policy_entry,
    sign_entries,
    _entry,
)

_SEED = b"SYNTHETIC-RSE-BLOCK1-TEST-ONLY\x00"


def ed_key(label: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(_SEED + b"ed\x00" + label.encode("ascii")).digest())


def x_key(label: str) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(hashlib.sha256(_SEED + b"x\x00" + label.encode("ascii")).digest())


def x_pub(label: str) -> bytes:
    return x_key(label).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def world(*, m2_label: str = "m2", m2_env: str = "env-m2"):
    dest = make_destination("carried", "block1-dest")
    policy = policy_entry(
        "block1-caps", operations=bit("G") | bit("V"), family=bytes(32), destinations=[dest.entry_id],
    )
    zero = bytes(32)
    image = _entry(2, "crown", 1, __import__("orca.rse.imp1.codec", fromlist=["pack_role_image"]).pack_role_image(1, dig("crown-measurement")), zero)
    code = _entry(1, "verifier", 1, b"", zero)
    crown = _entry(7, "crown-role", 1, pack_enrolment(
        role_type=ROLE_CROWN, ed25519_public_key=public_of(ed_key("crown")), x25519_public_key=x_pub("crown"),
        environment_measurement=dig("env-crown"), key_version=1,
    ), zero)
    forge = _entry(7, "forge", 1, pack_enrolment(
        role_type=ROLE_FORGE, ed25519_public_key=public_of(ed_key("forge")), x25519_public_key=x_pub("forge"),
        environment_measurement=dig("env-forge"), key_version=2,
    ), zero)
    witness = _entry(7, "witness", 1, pack_enrolment(
        role_type=ROLE_WITNESS, ed25519_public_key=public_of(ed_key("witness")), x25519_public_key=x_pub("witness"),
        environment_measurement=dig("env-witness"), key_version=3,
    ), zero)
    m1 = _entry(7, "m1", 1, pack_enrolment(
        role_type=ROLE_MONITOR_LITE, ed25519_public_key=public_of(ed_key("m1")), x25519_public_key=x_pub("m1"),
        environment_measurement=dig("env-m1"), key_version=4,
    ), zero)
    m2 = _entry(7, "m2", 1, pack_enrolment(
        role_type=ROLE_MONITOR_LITE, ed25519_public_key=public_of(ed_key(m2_label)), x25519_public_key=x_pub(m2_label),
        environment_measurement=dig(m2_env), key_version=5,
    ), zero)
    from orca.rse.imp1.codec import pack_corpus
    from orca.rse.imp1.profiles import RETIREMENT_ACTIVE
    corpus = _entry(6, "batch", 1, pack_corpus(
        corpus_id=dig("corpus-id"), corpus_version=1, manifest_digest=dig("manifest"),
        source_provenance_digest=dig("corpus-source"), witness_acceptance_record_digest=dig("witness-accept"),
        contamination_status_ref=dig("contamination"), retirement_state=RETIREMENT_ACTIVE,
    ), policy.entry_id)
    parts = {
        "policy": policy, "image": image, "code": code, "crown": crown, "forge": forge,
        "witness": witness, "m1": m1, "m2": m2, "dest": dest, "corpus": corpus,
    }
    registry = sign_entries(list(parts.values()))
    return registry, parts


def open_role(registry, parts, name: str) -> Session:
    return Session(
        role_id=parts[name].entry_id, role_key=ed_key(name if name != "crown" else "crown"),
        epoch=1, authority_version=1, floors=FLOORS, tokens=TOKENS, registry_raw=registry.raw,
        crown_image_id=parts["image"].entry_id, m1_id=parts["m1"].entry_id, m2_id=parts["m2"].entry_id,
        sink=MemorySink(), fence=SyntheticFence(),
    )


def open_monitor(parts, label: str = "m1") -> Monitor:
    return Monitor(
        parts[label].entry_id, ed_key(label), epoch_floor=1, sink=MemorySink(), fence=SyntheticFence(),
    )


def reboot(session: Session, blob: bytes | None = None) -> Session:
    """Boot the committed journal with the same synthetic fence."""
    return Session.boot(
        session.sink.blob if blob is None else blob,
        role_key=session.role_key, floors=session.floors, tokens=session.tokens,
        sink=MemorySink(), fence=session.fence,
    )


def grant_for(registry, parts, *, klass: str, target: str, challenge: bytes, prev: bytes, grant_id: bytes, tail: dict,
              runtime: int = 30, not_after: int = 0):
    env = {
        "forge": dig("env-forge"), "witness": dig("env-witness"), "crown": dig("env-crown"),
    }[target]
    prefix = build_grant_prefix(
        klass=klass, grant_id=grant_id, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=parts["policy"].entry_id, target_role_id=parts[target].entry_id,
        env_measurement_digest=env, code_entry_id=parts["code"].entry_id, challenge=challenge,
        prev_role_checkpoint=prev, created_at=0, not_after=not_after, max_runtime_s=runtime, tail=tail,
    )
    signers = [(1, OWNERS[0][1])] if klass == "V" else list(OWNERS)
    return sign_grant(prefix, signers)


def g_tail(parts):
    return {
        "corpus_entry_id": parts["corpus"].entry_id, "batch_count": 2, "batch_ceiling_bytes": 100,
        "recipient_role_id": parts["witness"].entry_id, "destination_entry_id": parts["dest"].entry_id,
        "source_provenance_digest": dig("corpus-source"),
    }


def g_intent(registry, grant_raw, parts):
    grant = parse_grant(grant_raw)
    return IntentSheet(
        "G", parts["corpus"].name, parts["corpus"].version, parts["dest"].name,
        ceilings_of(grant), grant_sas(grant.klass, grant.signed),
        target_role_name=parts["forge"].name, counterpart_name=parts["witness"].name,
    )


def v_tail(parts, seq_first: int = 1, seq_last: int = 4):
    return {
        "sender_role_id": parts["forge"].entry_id, "artifact_entry_id": parts["corpus"].entry_id,
        "seq_first": seq_first, "seq_last": seq_last,
    }


def v_intent(registry, grant_raw, parts):
    grant = parse_grant(grant_raw)
    return IntentSheet(
        "V", parts["corpus"].name, parts["corpus"].version, "",
        ceilings_of(grant), grant_sas(grant.klass, grant.signed),
        target_role_name=parts["witness"].name, counterpart_name=parts["forge"].name,
        sequence=(grant.tail["seq_first"], grant.tail["seq_last"]),
    )


def authorize(registry, parts, *, klass: str, target: str, tail: dict, intent_for, grant_id: bytes,
              entropy: bytes, runtime: int = 30, not_after: int = 0, consumer: Session | None = None):
    """Crown append, M1 acknowledgement, and consumer confirmation. Synthetic keys only.

    Pass ``consumer`` to authorize another grant on a role that already has a journal.
    """
    crown = open_role(registry, parts, "crown")
    if consumer is None:
        consumer = open_role(registry, parts, target)
    challenge = consumer.issue_challenge(entropy)
    raw = grant_for(
        registry, parts, klass=klass, target=target, challenge=challenge, prev=consumer.freshness.head,
        grant_id=grant_id, tail=tail, runtime=runtime, not_after=not_after,
    )
    assert crown.propose(raw) == "PROPOSED"
    assert crown.owner_verify(grant_id) == "OWNER_VERIFIED"
    assert crown.mark_signed(grant_id) == "SIGNED"
    assert crown.append_authorization(grant_id) == "APPENDED"
    checkpoint = crown.checkpoint_authorization(grant_id)
    packet = crown.log.witness_request(
        checkpoint, source_role_id=crown.role_id, witness_id=parts["m1"].entry_id, packet_seq=1, old_tree_size=0,
    )
    monitor = open_monitor(parts, "m1")
    ack = monitor.consider(
        packet, source_public=public_of(ed_key("crown")), witness_public=public_of(ed_key("m1")),
        sink=monitor.sink, fence=monitor.fence,
    )
    assert crown.accept_ack(grant_id, ack) == "CHECKPOINTED"
    delivery = crown.deliver(grant_id)
    assert consumer.confirm(delivery, intent_for(registry, raw, parts)) == "CONSUMER_CONFIRMED"
    return crown, consumer, raw, delivery
