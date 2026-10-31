"""C01 / C02 acceptance-condition probes (signed registry path).

C01 evidence_required: Refusal log from the signed registry path showing an
unregistered id refused.
C02 evidence_required: Consumer refusal record for a stale or unknown registry.

These tests exercise the real IMP-1 Crown / consumer paths — not transformer
or tokenizer suites previously mis-mapped to these IDs.
"""
from __future__ import annotations

import hashlib

from orca.rse.imp1.authority import (
    Floors,
    accept_registry,
    consumer_verify,
    crown_validate,
    registry_authenticity,
    registry_freshness,
)
from orca.rse.imp1.codec import (
    build_grant_prefix,
    parse_grant,
    sign_grant,
)
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED
from tests.rse.support import (
    CHALLENGE,
    FLOORS,
    OWNERS,
    TOKENS,
    consumer_args,
    consumer_binding,
    dig,
    g_grant,
    g_intent,
    sign_entries,
    simple_g,
    world,
)


def test_c01_signed_registry_path_refuses_unregistered_entry_id():
    """C01: Crown validation on the signed registry refuses an ABSENT id."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    assert crown_validate(grant, registry.raw, TOKENS, FLOORS, image).decision == CHECKS_PASSED

    evil_prefix = build_grant_prefix(
        klass="G",
        grant_id=b"G" * 16,
        owner_authority_version=1,
        incident_epoch=1,
        registry_version=registry.registry_version,
        registry_root=registry.registry_root,
        policy_entry_id=parts["policy"].entry_id,
        target_role_id=parts["forge"].entry_id,
        env_measurement_digest=dig("env-forge"),
        code_entry_id=parts["code"].entry_id,
        challenge=CHALLENGE,
        prev_role_checkpoint=dig("prev-checkpoint"),
        created_at=0,
        not_after=0,
        max_runtime_s=30,
        tail={
            "corpus_entry_id": hashlib.sha256(b"c01-unregistered-id").digest(),
            "batch_count": 1,
            "batch_ceiling_bytes": 10,
            "recipient_role_id": parts["witness"].entry_id,
            "destination_entry_id": parts["dest"].entry_id,
            "source_provenance_digest": dig("corpus-source"),
        },
    )
    evil = sign_grant(evil_prefix, OWNERS)
    refused = crown_validate(evil, registry.raw, TOKENS, FLOORS, image)
    assert refused.decision == FAIL_CLOSED
    assert refused.reason == "ABSENT"


def test_c01_wrong_type_registered_id_is_not_an_unregistered_pass():
    """A present-but-wrong-type id is WRONG_TYPE, distinct from ABSENT."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    body = parse_grant(grant).signed
    code_id = parts["code"].entry_id
    swapped = body[:278] + code_id + body[310:]
    swapped_grant = sign_grant(swapped, OWNERS)
    refused = crown_validate(swapped_grant, registry.raw, TOKENS, FLOORS, image)
    assert refused.decision == FAIL_CLOSED
    assert refused.reason == "WRONG_TYPE"


def test_c02_consumer_refuses_stale_authenticated_registry_version():
    """C02: consumer_verify fails closed on stale / non-current registry binding."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    ok = consumer_verify(
        grant,
        registry.raw,
        TOKENS,
        FLOORS,
        image,
        intent,
        CHALLENGE,
        *consumer_args(parts),
        **consumer_binding(registry),
    )
    assert ok.decision == CHECKS_PASSED

    # Omit authenticated-version ledger → consumer must refuse.
    omitted = consumer_verify(
        grant,
        registry.raw,
        TOKENS,
        FLOORS,
        image,
        intent,
        CHALLENGE,
        *consumer_args(parts),
    )
    assert omitted.decision == FAIL_CLOSED
    assert omitted.reason == "AUTHENTICATED_VERSION"


def test_c02_accept_registry_refuses_unknown_or_forked_successor():
    """C02: accept_registry refuses a forged/unknown successor of a known registry."""
    registry, parts, _grant = simple_g()
    old = sign_entries(list(parts.values()), version=1)
    assert registry_authenticity(old.raw, TOKENS).decision == CHECKS_PASSED
    raised = Floors(2, 1, 1, 1)
    assert registry_freshness(old, raised, None).decision == FAIL_CLOSED
    assert registry_freshness(old, raised, None).reason == "REGISTRY_FLOOR"

    linked = sign_entries(list(parts.values()), version=2, previous=old.registry_root)
    assert accept_registry(linked.raw, TOKENS, raised, old).decision == CHECKS_PASSED
    forked = bytearray(linked.raw)
    forked[9] ^= 0x01
    refused = accept_registry(bytes(forked), TOKENS, raised, old)
    assert refused.decision == FAIL_CLOSED
