"""Clarification 1 conformance. Expected vectors are literals, not calls to the code under test."""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from orca.rse.imp1.authority import (
    ChallengeLedger,
    IntentSheet,
    ceilings_of,
    consumer_verify,
    crown_validate,
    grant_sas,
    render_card,
    registry_authenticity,
)
from orca.rse.imp1.codec import (
    build_grant_prefix,
    build_registry_body,
    decode_entry,
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
    parse_destination,
    parse_foundation,
    parse_grant,
    parse_policy,
    public_of,
    sign_grant,
    token_id,
)
from orca.rse.imp1.merkle import merkle_root as production_root
from orca.rse.imp1.profiles import (
    CARRY_FORWARD,
    DATA_ONLY_TENSOR_V1,
    EXECUTABLE_OR_CODE_LOADING,
    K_SCENARIO_NAME,
    UNINSPECTED,
    UNSUPPORTED_CURRENT_MILESTONE,
)
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED
from tests.rse.support import (
    CHALLENGE,
    FLOORS,
    OWNER_A,
    OWNERS,
    TOKENS,
    _entry,
    bit,
    consumer_args,
    consumer_binding,
    dig,
    g_grant,
    g_intent,
    key,
    make_destination,
    policy_entry,
    revision,
    sign_entries,
    simple_g,
    world,
)
from orca.rse.imp1.codec import GRANT_SIG_DOMAIN, REG_SIG_DOMAIN
from orca.rse.imp1.profiles import (
    CODE,
    CORPUS,
    DEST_RECIPIENT_ROLE,
    DESTINATION,
    ENROLMENT,
    FOUNDATION_MODEL,
    HOLDOUT_SET,
    LIFECYCLE_CANDIDATE,
    MODEL,
    PENDING,
    POLICY,
    RETIREMENT_ACTIVE,
    ROLE_FORGE,
    ROLE_IMAGE,
    ROLE_WITNESS,
    TOKENIZER,
)

# Published in Clarification 1 §17. Not computed by grant_sas or merkle_root.
MERKLE_VECTORS = {
    1: "d9de27625445003d8a9739a851e3ff8d41c0683630b4d63a88327a6aaa37c409",
    2: "604d540f09268b91672ab011394d5266ccd7d4484d0d109411a55848126a1b2c",
    3: "d1f13800048f5909d4043fc0c152f6643280cba608b672715e56ce159a20629f",
    5: "6b313b611b40676b9e1dfd70c4503f2379f88f0f1c2740fb7e1cacc32c113465",
    8: "80e139b44c90f91edebec705cc7586c3d90f4bdadd49628d25c20d4b03419287",
    9: "aaba260cc2c4084b1d745f8817ad3d3350c5b005d8283bc3246396eee0ad9538",
}
SAS_G_EMPTY = "W2BQ-3RAG-W5U3"
SAS_T_PREFIX = "FLC7-AFYI-RPWJ"
SAS_V_EMPTY = "OLKD-CB7H-I65G"
KEYID_VECTOR = "a43087ff40fd894549ae4283ba15466b00fa89847631ecc9323789cda4b72719"


def _ids(n: int) -> list[bytes]:
    return [hashlib.sha256(bytes([i])).digest() for i in range(n)]


def test_known_answer_merkle_sas_and_keyid_are_literals():
    for n, hex_root in MERKLE_VECTORS.items():
        assert production_root(_ids(n)).hex() == hex_root
    assert grant_sas(ord("G"), b"") == SAS_G_EMPTY
    assert grant_sas(ord("T"), bytes(range(16))) == SAS_T_PREFIX
    assert grant_sas(ord("V"), b"") == SAS_V_EMPTY
    assert token_id(bytes(range(32))).hex() == KEYID_VECTOR
    assert SAS_G_EMPTY != SAS_V_EMPTY != SAS_T_PREFIX


def test_registry_order_is_strictly_ascending_and_unique():
    registry, parts, _grant = simple_g()
    entries = list(parts.values())
    ordered = sorted(entries, key=lambda item: item.entry_id)
    assert [item.entry_id for item in registry.entries] == [item.entry_id for item in ordered]
    swapped = list(ordered)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    try:
        build_registry_body(1, bytes(32), swapped)
        raise AssertionError("order")
    except Exception as exc:
        assert exc.reason == "ENTRY_ORDER"
    try:
        build_registry_body(1, bytes(32), [])
        raise AssertionError("empty")
    except Exception as exc:
        assert exc.reason == "ENTRY_COUNT"
    try:
        build_registry_body(1, bytes(32), [ordered[0], ordered[0]])
        raise AssertionError("duplicate")
    except Exception as exc:
        assert exc.reason == "DUPLICATE_ENTRY"


def test_round_trip_every_canonical_type_and_reject_noncanonical():
    registry, parts, _grant = simple_g()
    policy = parts["policy"]
    samples = [
        parts["code"], parts["image"], parts["corpus"], parts["forge"], parts["dest"], policy,
    ]
    family = hashlib.sha256(b"SYNTHETIC-RSE-FAMILY\x00GENESIS").digest()
    tok = _entry(TOKENIZER, "tok", 1, pack_tokenizer(dig("tid"), dig("vocab")), policy.entry_id)
    found = _entry(FOUNDATION_MODEL, "found", 1, pack_foundation(
        family_id=family, foundation_model_id=dig("fid"), foundation_revision=revision("found"),
        tokenizer_entry_id=tok.entry_id, weights_digest=dig("w"), license_record_digest=dig("lic"),
        architecture_config_digest=dig("cfg"), inspection_evidence_digest=dig("inspect"),
    ), policy.entry_id, producer=policy.entry_id)
    # Foundation approval also requires the policy family to match; the bytes still round-trip.
    model = _entry(MODEL, "model", 1, pack_model(
        family_id=family, parent_entry_id=found.entry_id, weights_digest=dig("mw"),
        lifecycle_state=LIFECYCLE_CANDIDATE, qualification_record_digest=dig("q"),
    ), policy.entry_id)
    hold = _entry(HOLDOUT_SET, "hold", 1, pack_holdout(holdout_id=dig("h"), bit_budget_total=4, query_budget_total=4), policy.entry_id)
    samples.extend([tok, found, model, hold])
    seen = set()
    for entry in samples:
        seen.add(entry.entry_type)
        decoded, consumed = decode_entry(entry.canonical)
        assert consumed == len(entry.canonical)
        assert decoded.canonical == entry.canonical
        assert encode_entry(
            decoded.entry_type, decoded.name, decoded.version,
            artifact_digest=decoded.artifact_digest, provenance_digest=decoded.provenance_digest,
            producer_entry_id=decoded.producer_entry_id, approval_state=decoded.approval_state,
            min_permitted_version=decoded.min_permitted_version, policy_entry_id=decoded.policy_entry_id,
            signing_key_id=decoded.signing_key_id, approval_evidence_checkpoint=decoded.approval_evidence_checkpoint,
            not_after=decoded.not_after, tail=decoded.tail,
        ).canonical == entry.canonical
    assert seen == set(range(1, 11))
    wide = pack_destination(kind=1, identifier_digest=dig("x")) + bytes(32)
    try:
        encode_entry(
            DESTINATION, "wide", 1, artifact_digest=dig("a"), provenance_digest=dig("p"),
            producer_entry_id=bytes(32), approval_state=2, min_permitted_version=1,
            policy_entry_id=bytes(32), signing_key_id=dig("k"), approval_evidence_checkpoint=dig("c"),
            not_after=0, tail=wide,
        )
        raise AssertionError("65-byte destination")
    except Exception as exc:
        assert exc.reason == "TAIL_LEN"


def test_policy_tail_is_199_bytes_and_zero_is_not_unlimited():
    dest = make_destination("carried", "dest-id")
    tail = pack_policy(
        max_batch_bytes=0, max_runtime_s=100, max_spend=0, max_run=10, max_query_budget=0,
        max_bit_budget=0, min_grant_schema_version=1, witness_requirement=1, allowed_operations=bit("G"),
        family_scope=bytes(32), destination_ids=[dest.entry_id],
    )
    assert len(tail) == 199
    parsed = parse_policy(tail)
    assert parsed["max_batch_bytes"] == 0
    assert parsed["permitted_destinations"] == (dest.entry_id,)
    policy = _entry(POLICY, "zero-cap", 1, tail, bytes(32), producer=bytes(32))
    parts_dest = dest
    from tests.rse.support import base_entries
    parts = base_entries(policy, parts_dest)
    registry = world(parts.values())
    assert crown_validate(
        g_grant(registry, parts, batch_bytes=0), registry.raw, TOKENS, FLOORS, parts["image"].entry_id,
    ).reason == "RESOURCE_CAP"
    assert crown_validate(
        g_grant(registry, parts, batch_bytes=1), registry.raw, TOKENS, FLOORS, parts["image"].entry_id,
    ).reason == "RESOURCE_CAP"


def test_foundation_format_revision_and_lineage_rules():
    family = hashlib.sha256(b"SYNTHETIC-RSE-FAMILY\x00GENESIS").digest()
    policy = policy_entry("gen", operations=bit("G"), family=family)
    tok = _entry(TOKENIZER, "tok", 1, pack_tokenizer(dig("tid"), dig("vocab")), policy.entry_id)

    def found(fmt, approval=2, revision_text="rev.1", inspection=None):
        return _entry(FOUNDATION_MODEL, "base", 1, pack_foundation(
            family_id=family, foundation_model_id=dig("fid"), foundation_revision=revision_text,
            tokenizer_entry_id=tok.entry_id, weights_digest=dig("w"), license_record_digest=dig("lic"),
            architecture_config_digest=dig("cfg"), artifact_format=fmt,
            inspection_evidence_digest=dig("inspect") if inspection is None else inspection,
        ), policy.entry_id, producer=policy.entry_id, approval=approval)

    good = found(DATA_ONLY_TENSOR_V1)
    assert len(good.tail) == 289
    pending_exec = found(EXECUTABLE_OR_CODE_LOADING, approval=PENDING)
    pending_none = found(UNINSPECTED, approval=PENDING)
    assert decode_entry(pending_exec.canonical)[0].tail[256] == 128
    assert decode_entry(pending_none.canonical)[0].tail[256] == 255
    for fmt in (EXECUTABLE_OR_CODE_LOADING, UNINSPECTED, 0, 2):
        try:
            found(fmt, approval=2)
            raise AssertionError(fmt)
        except Exception as exc:
            assert exc.reason == "ARTIFACT_FORMAT"
    try:
        found(DATA_ONLY_TENSOR_V1, revision_text="rev\nbad")
        raise AssertionError("control")
    except Exception as exc:
        assert exc.reason == "REVISION_CHARSET"
    registry = world([policy, tok, good])
    assert registry_authenticity(registry.raw, TOKENS).decision == CHECKS_PASSED
    from orca.rse.imp1.profiles import NOT_CLAIMED
    assert "foundation_backdoor_absence" in NOT_CLAIMED


def test_role_identity_is_independent_of_family_and_policy():
    enrolment = pack_enrolment(
        role_type=ROLE_FORGE, ed25519_public_key=public_of(key("forge-role")),
        x25519_public_key=dig("forge-x25519"), environment_measurement=dig("env-forge"), key_version=3,
    )
    first = _entry(ENROLMENT, "forge", 1, enrolment, bytes(32))
    second = _entry(ENROLMENT, "forge", 1, enrolment, bytes(32))
    assert first.entry_id == second.entry_id
    changed = pack_enrolment(
        role_type=ROLE_WITNESS, ed25519_public_key=public_of(key("forge-role")),
        x25519_public_key=dig("forge-x25519"), environment_measurement=dig("env-forge"), key_version=3,
    )
    assert _entry(ENROLMENT, "forge", 1, changed, bytes(32)).entry_id != first.entry_id
    try:
        _entry(ENROLMENT, "forge", 1, enrolment, dig("policy"))
        raise AssertionError("policy on enrolment")
    except Exception as exc:
        assert exc.reason == "POLICY_NEUTRAL"


def test_consumer_binds_role_and_environment_and_exact_snapshot():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    assert consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        **consumer_binding(registry),
    ).decision == CHECKS_PASSED
    assert consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, parts["witness"].entry_id, env,
        **consumer_binding(registry),
    ).reason == "ROLE_ID"
    assert consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, dig("other-env"),
        **consumer_binding(registry),
    ).reason == "ENVIRONMENT"
    body = parse_grant(grant).signed
    witness_env = dig("env-witness")
    moved = body[:98] + parts["witness"].entry_id + witness_env + body[162:]
    wrong_type = sign_grant(moved, OWNERS)
    assert crown_validate(wrong_type, registry.raw, TOKENS, FLOORS, image).reason == "ROLE_TYPE"
    revoked = _entry(ENROLMENT, "forge", 1, parts["forge"].tail, bytes(32), approval=4)
    # A second enrolment with the same name and version is a duplicate. Revoke by a higher version.
    revoked = _entry(ENROLMENT, "forge", 2, parts["forge"].tail, bytes(32), approval=4, minimum=2)
    reg_revoked = world([*[item for item in parts.values() if item.name != "forge"], revoked])
    # The original grant names the old forge id, which is absent from the revoked snapshot.
    assert crown_validate(grant, reg_revoked.raw, TOKENS, FLOORS, image).reason == "SNAPSHOT"
    stale = g_grant(reg_revoked, {**parts, "forge": revoked})
    assert crown_validate(stale, reg_revoked.raw, TOKENS, FLOORS, image).reason == "REVOKED"
    newer = sign_entries(list(parts.values()), version=2, previous=registry.registry_root)
    ledger = ChallengeLedger(CHALLENGE)
    raced = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=newer.registry_version, challenge_ledger=ledger,
    )
    assert raced.reason == "SNAPSHOT"
    assert ledger.void is True and ledger.challenge is None
    ledger2 = ChallengeLedger(CHALLENGE)
    replaced = consumer_verify(
        grant, newer.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=newer.registry_version, challenge_ledger=ledger2,
    )
    assert replaced.reason == "SNAPSHOT" and ledger2.void is True


def test_deferred_classes_parse_and_display_but_do_not_succeed():
    registry, parts, _grant = simple_g()
    image = parts["image"].entry_id
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
    signers = {"K": OWNERS, "Q": OWNERS, "T": OWNERS, "W": OWNERS, "D": OWNERS, "R": OWNERS}
    for klass, tail in tails.items():
        raw = sign_grant(build_grant_prefix(klass=klass, grant_id=klass.encode() * 16, tail=tail, **common), signers[klass])
        parsed = parse_grant(raw)
        card = render_card(parsed, registry, FLOORS, image)
        assert "UNSUPPORTED CURRENT MILESTONE" in card
        if klass == "K":
            assert "EPOCH RAISE" in card
            assert card.count("RE-ROOT") == 0
        result = crown_validate(raw, registry.raw, TOKENS, FLOORS, image)
        assert result.decision == FAIL_CLOSED and result.reason == UNSUPPORTED_CURRENT_MILESTONE
        intent = IntentSheet(klass, "batch", 1, "carried", ceilings_of(parsed), grant_sas(parsed.klass, parsed.signed))
        consumer = consumer_verify(
            raw, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, *consumer_args(parts),
            **consumer_binding(registry),
        )
        assert consumer.reason == UNSUPPORTED_CURRENT_MILESTONE
    for bad in (0, 14, 255):
        try:
            build_grant_prefix(
                klass="K", grant_id=b"K" * 16, tail={
                    "scenario": bad, "new_authority_version": 2, "new_epoch": 2,
                    "checkpoint_root": dig("root"), "revoked_count": 0, "revoked_ids": (),
                }, **common,
            )
            parse_grant(sign_grant(build_grant_prefix(
                klass="K", grant_id=b"K" * 16, tail={
                    "scenario": bad, "new_authority_version": 2, "new_epoch": 2,
                    "checkpoint_root": dig("root"), "revoked_count": 0, "revoked_ids": (),
                }, **common,
            ), OWNERS))
            raise AssertionError(bad)
        except Exception as exc:
            assert exc.reason == "SCENARIO"
    assert K_SCENARIO_NAME[13] == "RE-ROOT"
    assert len(K_SCENARIO_NAME) == 13
    assert "W must equal the model entry qualification_record_digest" in CARRY_FORWARD


def test_grant_tail_is_immutable_and_signing_key_is_not_authority():
    registry, parts, grant = simple_g()
    parsed = parse_grant(grant)
    try:
        parsed.tail["batch_count"] = 9
        raise AssertionError("mutable")
    except TypeError:
        pass
    other = encode_entry(
        CODE, parts["code"].name, 1, artifact_digest=parts["code"].artifact_digest,
        provenance_digest=parts["code"].provenance_digest, producer_entry_id=parts["code"].producer_entry_id,
        approval_state=2, min_permitted_version=1, policy_entry_id=bytes(32),
        signing_key_id=b"\x11" * 32, approval_evidence_checkpoint=parts["code"].approval_evidence_checkpoint,
        not_after=0, tail=b"",
    )
    assert other.entry_id != parts["code"].entry_id
    replaced = [other if item.entry_type == CODE else item for item in parts.values()]
    reg2 = world(replaced)
    moved = parse_grant(grant).signed
    retarget = moved[:162] + other.entry_id + moved[194:]
    retarget = retarget[:30] + reg2.registry_version.to_bytes(4, "big") + reg2.registry_root + retarget[66:]
    resigned = sign_grant(retarget, OWNERS)
    assert crown_validate(resigned, reg2.raw, TOKENS, FLOORS, parts["image"].entry_id).decision == CHECKS_PASSED


def test_class_g_and_v_role_matrix_and_cross_protocol_replay():
    dest = make_destination("carried", "dest-id")
    policy = policy_entry("both", operations=bit("G") | bit("V"), family=bytes(32), destinations=[dest.entry_id])
    from tests.rse.support import base_entries
    parts = base_entries(policy, dest)
    registry = world(parts.values())
    image = parts["image"].entry_id
    g_raw = g_grant(registry, parts)
    assert crown_validate(g_raw, registry.raw, TOKENS, FLOORS, image).decision == CHECKS_PASSED
    v_prefix = build_grant_prefix(
        klass="V", grant_id=b"V" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=policy.entry_id, target_role_id=parts["witness"].entry_id,
        env_measurement_digest=dig("env-witness"), code_entry_id=parts["code"].entry_id,
        challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"), created_at=0, not_after=0,
        max_runtime_s=20,
        tail={"sender_role_id": parts["forge"].entry_id, "artifact_entry_id": parts["corpus"].entry_id,
              "seq_first": 1, "seq_last": 2},
    )
    v_raw = sign_grant(v_prefix, [(1, OWNER_A)])
    parsed = parse_grant(v_raw)
    sheet = IntentSheet(
        "V", parts["corpus"].name, parts["corpus"].version, "", ceilings_of(parsed),
        grant_sas(parsed.klass, parsed.signed), target_role_name=parts["witness"].name,
        counterpart_name=parts["forge"].name, sequence=(1, 2),
    )
    assert consumer_verify(
        v_raw, registry.raw, TOKENS, FLOORS, image, sheet, CHALLENGE, *consumer_args(parts, "witness"),
        **consumer_binding(registry),
    ).decision == CHECKS_PASSED
    bad_sender = build_grant_prefix(
        klass="V", grant_id=b"V" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=policy.entry_id, target_role_id=parts["witness"].entry_id,
        env_measurement_digest=dig("env-witness"), code_entry_id=parts["code"].entry_id,
        challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"), created_at=0, not_after=0,
        max_runtime_s=20,
        tail={"sender_role_id": parts["witness"].entry_id, "artifact_entry_id": parts["corpus"].entry_id,
              "seq_first": 1, "seq_last": 2},
    )
    assert crown_validate(sign_grant(bad_sender, [(1, OWNER_A)]), registry.raw, TOKENS, FLOORS, image).reason == "ROLE_TYPE"
    slot, signature = registry.signatures[0]
    pubkey = Ed25519PublicKey.from_public_bytes(public_of(OWNER_A) if slot == 1 else public_of(key("owner-token-b")))
    pubkey.verify(signature, REG_SIG_DOMAIN + b"\x00" + bytes([registry.format_version]) + registry.body)
    try:
        pubkey.verify(signature, GRANT_SIG_DOMAIN + b"\x00" + b"G" + registry.body)
        raise AssertionError("replay")
    except Exception:
        pass
    assert parse_destination(parts["dest"].tail)["kind"] == 1
    assert DEST_RECIPIENT_ROLE == 2
    assert "recipient_role_entry_id" not in parse_destination(parts["dest"].tail)


def test_reserved_codes_fail_closed():
    for bad in (0, 7, 255):
        try:
            pack_model(family_id=dig("f"), parent_entry_id=dig("p"), weights_digest=dig("w"),
                       lifecycle_state=bad, qualification_record_digest=dig("q"))
            raise AssertionError(bad)
        except Exception as exc:
            assert exc.reason == "LIFECYCLE"
    for bad in (0, 3, 255):
        try:
            pack_corpus(
                corpus_id=dig("c"), corpus_version=1, manifest_digest=dig("m"),
                source_provenance_digest=dig("s"), witness_acceptance_record_digest=dig("w"),
                contamination_status_ref=dig("k"), retirement_state=bad,
            )
            raise AssertionError(bad)
        except Exception as exc:
            assert exc.reason == "RETIREMENT"
    for bad in (0, 5, 255):
        try:
            pack_enrolment(role_type=bad, ed25519_public_key=dig("e"), x25519_public_key=dig("x"),
                           environment_measurement=dig("m"), key_version=1)
            raise AssertionError(bad)
        except Exception as exc:
            assert exc.reason == "ROLE_TYPE"
    for bad in (0, 4, 255):
        try:
            pack_destination(kind=bad, identifier_digest=dig("d"))
            raise AssertionError(bad)
        except Exception as exc:
            assert exc.reason == "DESTINATION_KIND"
    for bad in (0, 4, 255):
        try:
            pack_policy(
                max_batch_bytes=1, max_runtime_s=1, max_spend=0, max_run=1, max_query_budget=0,
                max_bit_budget=0, min_grant_schema_version=1, witness_requirement=bad, allowed_operations=1,
                family_scope=bytes(32),
            )
            raise AssertionError(bad)
        except Exception as exc:
            assert exc.reason == "WITNESS_REQUIREMENT"
