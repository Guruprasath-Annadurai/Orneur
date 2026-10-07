"""Synthetic IMP-1 fixtures. Keys are derived from labelled test seeds, never from a real owner."""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from orca.rse.imp1.authority import Floors, IntentSheet, ceilings_of, grant_sas
from orca.rse.imp1.codec import (
    OwnerToken,
    build_grant_prefix,
    build_registry_body,
    encode_entry,
    pack_corpus,
    pack_destination,
    pack_enrolment,
    pack_foundation,
    pack_holdout,
    pack_model,
    pack_policy,
    pack_role_image,
    pack_tokenizer,
    parse_registry,
    public_of,
    sign_grant,
    sign_registry,
    token_id,
)
from orca.rse.imp1.profiles import (
    APPROVED,
    CLASS_BITS,
    CODE,
    CORPUS,
    DEST_MEDIUM,
    DESTINATION,
    ENROLMENT,
    FOUNDATION_MODEL,
    HOLDOUT_SET,
    LIFECYCLE_ACCEPTED,
    LIFECYCLE_CANDIDATE,
    LIFECYCLE_EXPORTED,
    MODEL,
    PENDING,
    POLICY,
    RETIREMENT_ACTIVE,
    REVOKED,
    ROLE_FORGE,
    ROLE_IMAGE,
    ROLE_WITNESS,
    TOKENIZER,
    WITNESS_ROUTINE,
)

SEED_DOMAIN = b"SYNTHETIC-RSE-IMP1-TEST-ONLY\x00"


def key(label: str) -> Ed25519PrivateKey:
    seed = hashlib.sha256(SEED_DOMAIN + label.encode("ascii")).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def dig(label: str) -> bytes:
    return hashlib.sha256(b"SYNTHETIC-DIGEST\x00" + label.encode("ascii")).digest()


def rev(label: str) -> bytes:
    return dig("rev-a-" + label) + dig("rev-b-" + label)


OWNER_A = key("owner-token-a")
OWNER_B = key("owner-token-b")
OWNERS = [(1, OWNER_A), (2, OWNER_B)]
TOKENS = [OwnerToken(1, public_of(OWNER_A)), OwnerToken(2, public_of(OWNER_B))]
FLOORS = Floors(1, 1, 1, 1)
CHALLENGE = dig("outstanding-challenge")


def _entry(entry_type, name, version, tail, policy_id, *, approval=APPROVED, minimum=None, producer=None, artifact=None):
    if minimum is None:
        minimum = version
    if producer is None:
        producer = policy_id
    return encode_entry(
        entry_type, name, version,
        artifact_digest=artifact if artifact is not None else dig(name + ":artifact"),
        provenance_digest=dig(name + ":provenance"),
        producer_entry_id=producer,
        approval_state=approval,
        min_permitted_version=minimum,
        policy_entry_id=policy_id,
        signing_key_id=token_id(public_of(OWNER_A)),
        approval_evidence_checkpoint=dig(name + ":checkpoint"),
        not_after=0,
        tail=tail,
    )


def policy_entry(name, *, operations: int, family: bytes, spend: int = 0, query: int = 0, bits: int = 0, batch: int = 1000):
    tail = pack_policy(
        max_batch_bytes=batch, max_runtime_s=100, max_spend=spend, max_run=10,
        max_query_budget=query, max_bit_budget=bits, min_grant_schema_version=1,
        witness_requirement=WITNESS_ROUTINE, allowed_operations=operations, required_family_id=family,
    )
    return _entry(POLICY, name, 1, tail, bytes(32), producer=bytes(32))


def sign_entries(entries, version=1, previous=None):
    if previous is None:
        previous = bytes(32)
    body = build_registry_body(version, previous, entries)
    raw = sign_registry(body, OWNERS)
    return parse_registry(raw)


def base_entries(policy):
    pid = policy.entry_id
    image = _entry(ROLE_IMAGE, "crown", 1, pack_role_image(1, dig("crown-measurement")), pid)
    code = _entry(CODE, "verifier", 1, b"", pid)
    forge = _entry(ENROLMENT, "forge", 1, pack_enrolment(
        role_type=ROLE_FORGE, ed25519_public_key=public_of(key("forge-role")),
        x25519_public_key=dig("forge-x25519"), environment_measurement=dig("env-forge"), key_version=3,
    ), pid)
    witness = _entry(ENROLMENT, "witness", 1, pack_enrolment(
        role_type=ROLE_WITNESS, ed25519_public_key=public_of(key("witness-role")),
        x25519_public_key=dig("witness-x25519"), environment_measurement=dig("env-witness"), key_version=4,
    ), pid)
    dest = _entry(DESTINATION, "carried", 1, pack_destination(
        kind=DEST_MEDIUM, identifier_digest=dig("dest-id"), recipient_role_entry_id=bytes(32),
    ), pid)
    corpus = _entry(CORPUS, "batch", 1, pack_corpus(
        corpus_id=dig("corpus-id"), corpus_version=1, manifest_digest=dig("manifest"),
        source_provenance_digest=dig("corpus-source"), witness_acceptance_record_digest=dig("witness-accept"),
        contamination_status_ref=dig("contamination"), retirement_state=RETIREMENT_ACTIVE,
    ), pid)
    return {
        "policy": policy, "image": image, "code": code, "forge": forge, "witness": witness,
        "dest": dest, "corpus": corpus,
    }


def world(entries):
    ordered = list(entries)
    registry = sign_entries(ordered)
    return registry


def g_grant(registry, parts, *, corpus=None, dest=None, batch_count=2, batch_bytes=100, runtime=30, challenge=None):
    corpus = parts["corpus"] if corpus is None else corpus
    dest = parts["dest"] if dest is None else dest
    prefix = build_grant_prefix(
        klass="G", grant_id=b"G" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=parts["policy"].entry_id, target_role_id=parts["forge"].entry_id,
        env_measurement_digest=dig("env-forge"), code_entry_id=parts["code"].entry_id,
        challenge=CHALLENGE if challenge is None else challenge, prev_role_checkpoint=dig("prev-checkpoint"),
        created_at=0, not_after=0, max_runtime_s=runtime,
        tail={
            "corpus_entry_id": corpus.entry_id, "batch_count": batch_count, "batch_ceiling_bytes": batch_bytes,
            "recipient_role_id": parts["witness"].entry_id, "destination_entry_id": dest.entry_id,
            "source_provenance_digest": dig("corpus-source"),
        },
    )
    return sign_grant(prefix, OWNERS)


def g_intent(registry, grant_raw, parts):
    from orca.rse.imp1.codec import parse_grant

    grant = parse_grant(grant_raw)
    return IntentSheet(
        "G", parts["corpus"].name, parts["corpus"].version, parts["dest"].name,
        ceilings_of(grant), grant_sas(grant.klass, grant.signed),
    )


def simple_g():
    policy = policy_entry("caps", operations=1 << CLASS_BITS[ord("G")], family=bytes(32))
    parts = base_entries(policy)
    registry = world(parts.values())
    grant = g_grant(registry, parts)
    return registry, parts, grant


def bit(klass: str) -> int:
    return 1 << CLASS_BITS[ord(klass)]
