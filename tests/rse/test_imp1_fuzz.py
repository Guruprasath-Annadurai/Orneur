"""Deterministic mutations across every grant class.

A mutated or unauthorized object must not reach CHECKS_PASSED. Intact class G
and class V fixtures are checked outside the mutation loops. Deferred classes
are checked as unsupported before they are mutated. Iteration counts are fixed.
"""

from __future__ import annotations

from orca.rse.imp1.authority import ChallengeLedger, consumer_verify, crown_validate
from orca.rse.imp1.codec import build_grant_prefix, parse_grant, parse_registry, sign_grant
from orca.rse.imp1.profiles import UNSUPPORTED_CURRENT_MILESTONE
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, QUARANTINE
from tests.rse.support import (
    CHALLENGE,
    FLOORS,
    OWNER_A,
    OWNERS,
    TOKENS,
    bit,
    consumer_args,
    consumer_binding,
    dig,
    g_grant,
    g_intent,
    make_destination,
    policy_entry,
    world,
    base_entries,
)

SEEDS = (20261008, 0xC1A51F1E, 11, 99)
PER_SEED = 20
CLASSES = ("G", "V", "K", "Q", "T", "W", "D", "R")
SEMANTIC_KINDS = (
    "truncate",
    "trailing",
    "class",
    "registry_root",
    "version",
    "role",
    "environment",
    "artifact",
    "sequence",
    "signature",
    "registry_truncate",
    "registry_trailing",
    "registry_order",
    "registry_duplicate",
    "snapshot",
)
RANDOM_ITERATIONS = len(CLASSES) * len(SEEDS) * PER_SEED
SEMANTIC_ITERATIONS = len(CLASSES) * len(SEMANTIC_KINDS)
FUZZ_ITERATIONS = RANDOM_ITERATIONS + SEMANTIC_ITERATIONS


def _rng(seed: int):
    x = seed or 1

    def nxt():
        nonlocal x
        x ^= (x >> 12) & 0xFFFFFFFFFFFFFFFF
        x ^= (x << 25) & 0xFFFFFFFFFFFFFFFF
        x ^= (x >> 27) & 0xFFFFFFFFFFFFFFFF
        x = (x * 2685821657736338717) & 0xFFFFFFFFFFFFFFFF
        return x

    return nxt


def _mutate(blob: bytes, kind: int, nxt) -> bytes:
    data = bytearray(blob)
    if kind == 0:
        return bytes(data[: max(1, nxt() % len(data))])
    if kind == 1:
        return bytes(data) + bytes([nxt() & 0xFF])
    if kind == 2 and data:
        data[nxt() % len(data)] ^= 1 + (nxt() % 255)
        return bytes(data)
    if kind == 3 and len(data) > 5:
        data[5] = (data[5] + 1 + (nxt() % 20)) & 0xFF
        return bytes(data)
    if kind == 4 and len(data) > 45:
        data[30] ^= 0x01
        return bytes(data)
    if kind == 5 and len(data) > 80:
        data[45], data[46] = data[46], data[45]
        return bytes(data)
    if kind == 6:
        changed = bytes(data) + data[:32]
    else:
        changed = bytes(data[:-1] if data else b"")
    if changed == blob:
        changed = bytes(blob) + b"\xff"
    return changed


def _flip(blob: bytes, index: int) -> bytes:
    data = bytearray(blob)
    if not data:
        return b"\xff"
    data[index % len(data)] ^= 0xFF
    if bytes(data) == blob:
        return bytes(blob) + b"\xff"
    return bytes(data)


def _semantic(kind: str, grant: bytes, registry: bytes, other_registry: bytes) -> tuple[bytes, bytes]:
    if kind == "truncate":
        return grant[: len(grant) // 2], registry
    if kind == "trailing":
        return grant + b"\x00", registry
    if kind == "class":
        return _flip(grant, 5), registry
    if kind == "registry_root":
        return _flip(grant, 34), registry
    if kind == "version":
        return _flip(grant, 30), registry
    if kind == "role":
        return _flip(grant, 98), registry
    if kind == "environment":
        return _flip(grant, 130), registry
    if kind == "artifact":
        return _flip(grant, min(310, len(grant) - 1)), registry
    if kind == "sequence":
        return _flip(grant, min(342, len(grant) - 1)), registry
    if kind == "signature":
        return _flip(grant, len(grant) - 1), registry
    if kind == "registry_truncate":
        return grant, registry[: len(registry) // 2]
    if kind == "registry_trailing":
        return grant, registry + b"\xff"
    if kind == "registry_order":
        return grant, _flip(registry, 45) if len(registry) > 46 else registry + b"\x01"
    if kind == "registry_duplicate":
        return grant, registry + registry[:32]
    if kind == "snapshot":
        return grant, other_registry
    raise AssertionError(kind)


def _bundle():
    dest = make_destination("carried", "dest-id")
    mask = 0
    for name in CLASSES:
        mask |= bit(name)
    policy = policy_entry("all-caps", operations=mask, family=bytes(32), destinations=[dest.entry_id])
    parts = base_entries(policy, dest)
    registry = world(parts.values())
    from tests.rse.support import sign_entries
    other = sign_entries(list(parts.values()), version=2, previous=registry.registry_root)
    grants = {}
    common = dict(
        owner_authority_version=1, incident_epoch=1, registry_version=registry.registry_version,
        registry_root=registry.registry_root, policy_entry_id=parts["policy"].entry_id,
        target_role_id=parts["forge"].entry_id, env_measurement_digest=dig("env-forge"),
        code_entry_id=parts["code"].entry_id, challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"),
        created_at=0, not_after=0, max_runtime_s=20,
    )
    tails = {
        "K": {"scenario": 1, "new_authority_version": 2, "new_epoch": 2, "checkpoint_root": dig("root"),
              "revoked_count": 0, "revoked_ids": ()},
        "Q": {"candidate_model_entry_id": parts["corpus"].entry_id, "chamber_env_digest": dig("c"),
              "holdout_set_entry_id": parts["code"].entry_id, "run_budget": 1, "query_budget": 1, "bit_budget": 1},
        "T": {"corpus_entry_id": parts["corpus"].entry_id, "foundation_entry_id": parts["code"].entry_id,
              "family_id": dig("fam"), "spend_ceiling": 0, "run_ceiling": 1, "provider_env_digest": dig("p")},
        "W": {"model_entry_id": parts["corpus"].entry_id, "qualification_record_digest": dig("q"),
              "source_entry_id": parts["code"].entry_id, "destination_entry_id": parts["dest"].entry_id,
              "format": 1, "size_ceiling": 1, "recipient_role_id": parts["witness"].entry_id},
        "D": {"model_entry_id": parts["corpus"].entry_id, "serving_env_digest": dig("e"), "policy_digest": dig("p"),
              "tool_permission_digest": dig("t"), "data_scope_digest": dig("d"),
              "revocation_endpoint_entry_id": parts["dest"].entry_id, "spend_ceiling": 0, "run_ceiling": 1,
              "release_version": 1},
        "R": {"object_entry_id": parts["corpus"].entry_id, "reason": 1},
    }
    grants["G"] = g_grant(registry, parts)
    v_common = dict(common)
    v_common["target_role_id"] = parts["witness"].entry_id
    v_common["env_measurement_digest"] = dig("env-witness")
    v_prefix = build_grant_prefix(
        klass="V", grant_id=b"V" * 16,
        tail={"sender_role_id": parts["forge"].entry_id, "artifact_entry_id": parts["corpus"].entry_id,
              "seq_first": 1, "seq_last": 2},
        **v_common,
    )
    grants["V"] = sign_grant(v_prefix, [(1, OWNER_A)])
    for klass, tail in tails.items():
        prefix = build_grant_prefix(klass=klass, grant_id=klass.encode() * 16, tail=tail, **common)
        grants[klass] = sign_grant(prefix, OWNERS)
    return registry, other, parts, grants


def _closed(result) -> None:
    assert result.decision in {FAIL_CLOSED, QUARANTINE}
    assert result.decision != CHECKS_PASSED


def test_fuzz_mutations_do_not_reach_semantic_success():
    assert len(SEEDS) >= 4
    assert RANDOM_ITERATIONS == 640
    assert SEMANTIC_ITERATIONS == 120
    assert FUZZ_ITERATIONS == 760
    registry, other, parts, grants = _bundle()
    image = parts["image"].entry_id
    g_intent_sheet = g_intent(registry, grants["G"], parts)
    role, env = consumer_args(parts)
    witness_role, witness_env = consumer_args(parts, "witness")
    intact_g = crown_validate(grants["G"], registry.raw, TOKENS, FLOORS, image)
    assert intact_g.decision == CHECKS_PASSED
    assert consumer_verify(
        grants["G"], registry.raw, TOKENS, FLOORS, image, g_intent_sheet, CHALLENGE, role, env,
        **consumer_binding(registry),
    ).decision == CHECKS_PASSED
    v_parsed = parse_grant(grants["V"])
    from orca.rse.imp1.authority import IntentSheet, ceilings_of, grant_sas
    v_sheet = IntentSheet(
        "V", parts["corpus"].name, parts["corpus"].version, "", ceilings_of(v_parsed),
        grant_sas(v_parsed.klass, v_parsed.signed), target_role_name=parts["witness"].name,
        counterpart_name=parts["forge"].name, sequence=(1, 2),
    )
    assert crown_validate(grants["V"], registry.raw, TOKENS, FLOORS, image).decision == CHECKS_PASSED
    assert consumer_verify(
        grants["V"], registry.raw, TOKENS, FLOORS, image, v_sheet, CHALLENGE, witness_role, witness_env,
        **consumer_binding(registry),
    ).decision == CHECKS_PASSED
    for klass in ("K", "Q", "T", "W", "D", "R"):
        deferred = crown_validate(grants[klass], registry.raw, TOKENS, FLOORS, image)
        assert deferred.decision == FAIL_CLOSED
        assert deferred.reason == UNSUPPORTED_CURRENT_MILESTONE

    def exercise(grant_raw: bytes, registry_raw: bytes, sheet, who) -> None:
        binding = {
            "highest_authenticated_version": registry.registry_version,
            "challenge_ledger": ChallengeLedger(CHALLENGE),
        }
        crown = crown_validate(grant_raw, registry_raw, TOKENS, FLOORS, image)
        consumer = consumer_verify(
            grant_raw, registry_raw, TOKENS, FLOORS, image, sheet, CHALLENGE, who[0], who[1], **binding,
        )
        _closed(crown)
        _closed(consumer)

    semantic_count = 0
    for klass in CLASSES:
        grant = grants[klass]
        sheet = v_sheet if klass == "V" else g_intent_sheet
        who = (witness_role, witness_env) if klass == "V" else (role, env)
        for kind in SEMANTIC_KINDS:
            mutated_grant, mutated_registry = _semantic(kind, grant, registry.raw, other.raw)
            assert mutated_grant != grant or mutated_registry != registry.raw
            exercise(mutated_grant, mutated_registry, sheet, who)
            semantic_count += 1
    assert semantic_count == SEMANTIC_ITERATIONS

    random_count = 0
    for klass in CLASSES:
        grant = grants[klass]
        sheet = v_sheet if klass == "V" else g_intent_sheet
        who = (witness_role, witness_env) if klass == "V" else (role, env)
        for seed in SEEDS:
            nxt = _rng(seed + ord(klass))
            for _ in range(PER_SEED):
                kind = nxt() % 8
                target_grant = kind % 2 == 0
                raw = _mutate(grant if target_grant else registry.raw, kind, nxt)
                assert raw != (grant if target_grant else registry.raw)
                if target_grant:
                    exercise(raw, registry.raw, sheet, who)
                else:
                    exercise(grant, raw, sheet, who)
                random_count += 1
                for parser in (parse_registry, parse_grant):
                    try:
                        parser(raw)
                    except Exception:
                        pass
    assert random_count == RANDOM_ITERATIONS
    assert semantic_count + random_count == FUZZ_ITERATIONS
