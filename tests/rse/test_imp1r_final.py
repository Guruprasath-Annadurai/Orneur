"""Reproductions for the R-1, R-2, and R-3 re-audit findings.

Expected card lines are literals. They are not built by the renderer under test.
"""

from __future__ import annotations

from orca.rse.imp1 import authority
from orca.rse.imp1.authority import ChallengeLedger, IntentSheet, ceilings_of, consumer_verify, crown_validate, grant_sas, render_card
from orca.rse.imp1.codec import build_grant_prefix, pack_foundation, pack_model, pack_tokenizer, parse_grant, sign_grant, synthetic_family_id
from orca.rse.imp1.profiles import CARRY_FORWARD, CODE, CORPUS, DESTINATION, ENROLMENT, FOUNDATION_MODEL, MODEL, POLICY, ROLE_IMAGE, TOKENIZER, UNSUPPORTED_CURRENT_MILESTONE
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED
from tests.rse.support import (
    CHALLENGE,
    FLOORS,
    OWNER_A,
    TOKENS,
    _entry,
    base_entries,
    bit,
    consumer_args,
    consumer_binding,
    dig,
    g_grant,
    g_intent,
    make_destination,
    policy_entry,
    revision,
    sign_entries,
    simple_g,
    world,
)

SEQUENCE_ONE_TO_TWO = "SEQUENCE     1..2"
SEQUENCE_ONE_TO_THREE = "SEQUENCE     1..3"
SEQUENCE_FOUR_TO_TWO = "SEQUENCE     4..2"


def _verify(grant, registry, parts, intent, challenge=CHALLENGE, **kwargs):
    image = parts["image"].entry_id
    role, env = consumer_args(parts)
    binding = consumer_binding(registry, challenge)
    binding.update(kwargs)
    return consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, challenge, role, env, **binding,
    )


def test_r1_omitted_stale_newer_and_void_retry_never_succeed():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    live = ChallengeLedger(CHALLENGE)
    assert consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=registry.registry_version, challenge_ledger=live,
    ).decision == CHECKS_PASSED

    omitted = consumer_verify(grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env)
    assert omitted.decision == FAIL_CLOSED
    assert omitted.reason == "AUTHENTICATED_VERSION"

    for bad in (None, True, False, 0, -1, "1"):
        result = consumer_verify(
            grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
            highest_authenticated_version=bad, challenge_ledger=ChallengeLedger(CHALLENGE),
        )
        assert result.decision == FAIL_CLOSED
        assert result.reason == "AUTHENTICATED_VERSION"
        assert result.decision != CHECKS_PASSED

    missing_ledger = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=registry.registry_version,
    )
    assert missing_ledger.reason == "AUTHENTICATED_VERSION"

    newer = sign_entries(list(parts.values()), version=2, previous=registry.registry_root)
    challenge_v2 = dig("challenge-v2")
    grant_v2 = g_grant(newer, parts, challenge=challenge_v2)
    intent_v2 = g_intent(newer, grant_v2, parts)
    stale = consumer_verify(
        grant_v2, newer.raw, TOKENS, FLOORS, image, intent_v2, challenge_v2, role, env,
        highest_authenticated_version=1, challenge_ledger=ChallengeLedger(challenge_v2),
    )
    assert stale.reason == "AUTHENTICATED_VERSION"
    assert stale.decision != CHECKS_PASSED

    seen = ChallengeLedger(CHALLENGE)
    newer_exists = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=newer.registry_version, challenge_ledger=seen,
    )
    assert newer_exists.reason == "SNAPSHOT"
    assert seen.void is True
    assert CHALLENGE in seen.voided_challenges

    mismatch = ChallengeLedger(CHALLENGE)
    replaced = consumer_verify(
        grant, newer.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=newer.registry_version, challenge_ledger=mismatch,
    )
    assert replaced.reason == "SNAPSHOT"
    assert mismatch.void is True

    retry_old = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=registry.registry_version, challenge_ledger=mismatch,
    )
    assert retry_old.reason == "CHALLENGE_VOID"
    assert retry_old.decision != CHECKS_PASSED

    retry_grant = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=registry.registry_version, challenge_ledger=seen,
    )
    assert retry_grant.reason == "CHALLENGE_VOID"

    for _ in range(3):
        again = consumer_verify(
            grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
            highest_authenticated_version=registry.registry_version, challenge_ledger=seen,
        )
        assert again.reason == "CHALLENGE_VOID"
        assert again.decision != CHECKS_PASSED

    truthful_new_ledger = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=newer.registry_version, challenge_ledger=ChallengeLedger(CHALLENGE),
    )
    assert truthful_new_ledger.reason == "SNAPSHOT"
    assert truthful_new_ledger.decision != CHECKS_PASSED

    seen.void = False
    cleared = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env,
        highest_authenticated_version=registry.registry_version, challenge_ledger=seen,
    )
    assert cleared.reason == "CHALLENGE_VOID"

    fresh = dig("fresh-challenge")
    grant_fresh = g_grant(registry, parts, challenge=fresh)
    intent_fresh = g_intent(registry, grant_fresh, parts)
    opened = consumer_verify(
        grant_fresh, registry.raw, TOKENS, FLOORS, image, intent_fresh, fresh, role, env,
        highest_authenticated_version=registry.registry_version, challenge_ledger=ChallengeLedger(fresh),
    )
    assert opened.decision == CHECKS_PASSED
    corrected = consumer_verify(
        grant_v2, newer.raw, TOKENS, FLOORS, image, intent_v2, challenge_v2, role, env,
        highest_authenticated_version=newer.registry_version, challenge_ledger=ChallengeLedger(challenge_v2),
    )
    assert corrected.decision == CHECKS_PASSED


def _v_grant(registry, parts, artifact_id, seq_first=1, seq_last=2, challenge=CHALLENGE):
    prefix = build_grant_prefix(
        klass="V", grant_id=b"V" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=parts["policy"].entry_id, target_role_id=parts["witness"].entry_id,
        env_measurement_digest=dig("env-witness"), code_entry_id=parts["code"].entry_id,
        challenge=challenge, prev_role_checkpoint=dig("prev-checkpoint"), created_at=0, not_after=0,
        max_runtime_s=20,
        tail={
            "sender_role_id": parts["forge"].entry_id, "artifact_entry_id": artifact_id,
            "seq_first": seq_first, "seq_last": seq_last,
        },
    )
    return sign_grant(prefix, [(1, OWNER_A)])


def _v_sheet(registry, grant, parts, seq):
    parsed = parse_grant(grant)
    return IntentSheet(
        "V", parts["corpus"].name, parts["corpus"].version, "", ceilings_of(parsed),
        grant_sas(parsed.klass, parsed.signed), target_role_name=parts["witness"].name,
        counterpart_name=parts["forge"].name, sequence=seq,
    )


def _v_registry():
    dest = make_destination("carried", "dest-id")
    policy = policy_entry("v-caps", operations=bit("V") | bit("G"), family=bytes(32), destinations=[dest.entry_id])
    parts = base_entries(policy, dest)
    family = synthetic_family_id("GENESIS")
    fam = policy_entry("fam-caps", operations=bit("G"), family=family)
    tok = _entry(TOKENIZER, "tok", 1, pack_tokenizer(dig("tok-id"), dig("tok-vocab")), fam.entry_id)
    found = _entry(FOUNDATION_MODEL, "found", 1, pack_foundation(
        family_id=family, foundation_model_id=dig("found-id"), foundation_revision=revision("found"),
        tokenizer_entry_id=tok.entry_id, weights_digest=dig("found-weights"),
        license_record_digest=dig("found-license"), architecture_config_digest=dig("found-config"),
        artifact_format=1, inspection_evidence_digest=dig("found-inspect"),
    ), fam.entry_id, producer=fam.entry_id)
    model = _entry(MODEL, "mdl", 1, pack_model(
        family_id=family, parent_entry_id=found.entry_id, weights_digest=dig("mdl-weights"),
        lifecycle_state=3, qualification_record_digest=dig("mdl-qual"),
    ), fam.entry_id)
    extra = {"tokenizer": tok, "foundation": found, "model": model, "fam": fam}
    registry = world([*parts.values(), fam, tok, found, model])
    return registry, parts, extra


def test_r2_class_v_accepts_only_corpus():
    registry, parts, extra = _v_registry()
    image = parts["image"].entry_id
    good = _v_grant(registry, parts, parts["corpus"].entry_id)
    sheet = _v_sheet(registry, good, parts, (1, 2))
    assert crown_validate(good, registry.raw, TOKENS, FLOORS, image).decision == CHECKS_PASSED
    assert consumer_verify(
        good, registry.raw, TOKENS, FLOORS, image, sheet, CHALLENGE, *consumer_args(parts, "witness"),
        **consumer_binding(registry),
    ).decision == CHECKS_PASSED

    rejected = {
        "code": parts["code"].entry_id,
        "foundation": extra["foundation"].entry_id,
        "model": extra["model"].entry_id,
        "tokenizer": extra["tokenizer"].entry_id,
        "destination": parts["dest"].entry_id,
        "role": parts["forge"].entry_id,
        "role_image": parts["image"].entry_id,
        "policy": parts["policy"].entry_id,
    }
    assert {CODE, FOUNDATION_MODEL, MODEL, TOKENIZER, DESTINATION, ENROLMENT, ROLE_IMAGE, POLICY}
    for name, entry_id in rejected.items():
        raw = _v_grant(registry, parts, entry_id)
        result = crown_validate(raw, registry.raw, TOKENS, FLOORS, image)
        assert result.decision == FAIL_CLOSED, name
        assert result.reason == "WRONG_TYPE", name
        assert result.decision != CHECKS_PASSED
    absent = crown_validate(_v_grant(registry, parts, dig("not-an-entry")), registry.raw, TOKENS, FLOORS, image)
    assert absent.reason == "ABSENT"
    malformed = crown_validate(
        _v_grant(registry, parts, parts["corpus"].entry_id, seq_first=5, seq_last=1),
        registry.raw, TOKENS, FLOORS, image,
    )
    assert malformed.decision == FAIL_CLOSED
    assert malformed.reason == "SEQUENCE"


def test_r3_v_card_shows_signed_sequence_and_intent_mismatch_fails():
    registry, parts, _extra = _v_registry()
    image = parts["image"].entry_id
    grant = _v_grant(registry, parts, parts["corpus"].entry_id, seq_first=1, seq_last=2)
    parsed = parse_grant(grant)
    card = render_card(parsed, registry, FLOORS, image)
    crown = crown_validate(grant, registry.raw, TOKENS, FLOORS, image)
    assert crown.decision == CHECKS_PASSED
    assert card == crown.payload["card"]
    assert SEQUENCE_ONE_TO_TWO in card
    assert "SEQUENCE     " in card

    moved_last = _v_grant(registry, parts, parts["corpus"].entry_id, seq_first=1, seq_last=3)
    card_last = render_card(parse_grant(moved_last), registry, FLOORS, image)
    assert SEQUENCE_ONE_TO_THREE in card_last
    assert SEQUENCE_ONE_TO_TWO not in card_last
    assert card_last != card

    moved_first = _v_grant(registry, parts, parts["corpus"].entry_id, seq_first=4, seq_last=2)
    card_first = render_card(parse_grant(moved_first), registry, FLOORS, image)
    assert SEQUENCE_FOUR_TO_TWO in card_first
    assert SEQUENCE_ONE_TO_TWO not in card_first

    sheet = _v_sheet(registry, grant, parts, (1, 2))
    assert consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, sheet, CHALLENGE, *consumer_args(parts, "witness"),
        **consumer_binding(registry),
    ).decision == CHECKS_PASSED
    mismatched = _v_sheet(registry, grant, parts, (1, 3))
    refused = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, mismatched, CHALLENGE, *consumer_args(parts, "witness"),
        **consumer_binding(registry),
    )
    assert refused.decision == FAIL_CLOSED
    assert refused.reason == "INTENT_SEQUENCE"
    assert "K Q T and D Crown cards omit future signed fields; those classes stay unsupported and are not executable" in CARRY_FORWARD


def test_r4_retire_path_is_gone_and_deferred_r_stays_unsupported():
    assert not hasattr(authority, "_retire_object")
    assert not hasattr(authority, "_family_absent")
    registry, parts, _grant = simple_g()
    image = parts["image"].entry_id
    prefix = build_grant_prefix(
        klass="R", grant_id=b"R" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=parts["policy"].entry_id, target_role_id=parts["forge"].entry_id,
        env_measurement_digest=dig("env-forge"), code_entry_id=parts["code"].entry_id,
        challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"), created_at=0, not_after=0,
        max_runtime_s=20, tail={"object_entry_id": parts["corpus"].entry_id, "reason": 1},
    )
    from tests.rse.support import OWNERS
    raw = sign_grant(prefix, OWNERS)
    result = crown_validate(raw, registry.raw, TOKENS, FLOORS, image)
    assert result.decision == FAIL_CLOSED
    assert result.reason == UNSUPPORTED_CURRENT_MILESTONE
    card = render_card(parse_grant(raw), registry, FLOORS, image)
    assert "UNSUPPORTED CURRENT MILESTONE" in card
    assert "SUPERSEDED" in card
