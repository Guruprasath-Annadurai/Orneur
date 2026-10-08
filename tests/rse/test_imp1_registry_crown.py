"""RSE-IMP-1 registry, Crown, consumer, SAS and intent checks."""

from __future__ import annotations

import hashlib
import inspect

from orca.rse.imp1 import (
    corpus_generation_authorized,
    gpu_authorized,
    model_selection_authorized,
    provider_authorized,
    qualification_authorized,
    spending_authorized,
    training_authorized,
)
from orca.rse.imp1.authority import (
    accept_registry,
    check_freshness,
    consumer_verify,
    crown_validate,
    effective_min_version,
    grant_sas,
    refuse_proposer_digest,
    registry_authenticity,
    registry_freshness,
)
from orca.rse.imp1.codec import (
    build_grant_prefix,
    build_registry_body,
    decode_entry,
    encode_entry,
    entry_id_of,
    name_skeleton,
    pack_corpus,
    pack_destination,
    pack_enrolment,
    pack_foundation,
    pack_holdout,
    pack_model,
    pack_name,
    pack_role_image,
    pack_tokenizer,
    parse_enrolment,
    parse_foundation,
    parse_grant,
    parse_registry,
    public_of,
    sign_grant,
    sign_registry,
    synthetic_family_id,
    unpack_name,
)
from orca.rse.imp1.locks import prove_authorization_locks
from orca.rse.imp1.profiles import (
    APPROVED,
    CODE,
    CORPUS,
    DEST_EXPORT_TARGET,
    DESTINATION,
    ENROLMENT,
    FOUNDATION_MODEL,
    HOLDOUT_SET,
    LIFECYCLE_ACCEPTED,
    LIFECYCLE_CANDIDATE,
    LIFECYCLE_EXPORTED,
    MODEL,
    PENDING,
    RETIREMENT_ACTIVE,
    RETIREMENT_RETIRED,
    REVOKED,
    ROLE_FORGE,
    ROLE_WITNESS,
    TOKENIZER,
)
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, QUARANTINE
from tests.rse.support import (
    CHALLENGE,
    FLOORS,
    OWNER_A,
    OWNERS,
    TOKENS,
    _entry,
    base_entries,
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

from orca.rse.imp1.authority import Floors


def test_entry_reencode_and_identity_tracks_security_fields():
    dest = make_destination("carried", "dest-id")
    policy = policy_entry("caps", operations=bit("G"), family=bytes(32), destinations=[dest.entry_id])
    parts = base_entries(policy, dest)
    code = parts["code"]
    again, consumed = decode_entry(code.canonical)
    assert consumed == len(code.canonical)
    assert again.canonical == code.canonical
    assert again.entry_id == entry_id_of(code.canonical)
    mutated = {
        "entry_type": MODEL,
        "name": "verifierX",
        "version": code.version + 1,
        "approval_state": REVOKED,
        "min_permitted_version": code.version + 1,
    }
    for field, value in mutated.items():
        kwargs = dict(
            entry_type=code.entry_type, name=code.name, version=code.version,
            artifact_digest=code.artifact_digest, provenance_digest=code.provenance_digest,
            producer_entry_id=code.producer_entry_id, approval_state=code.approval_state,
            min_permitted_version=code.min_permitted_version, policy_entry_id=code.policy_entry_id,
            signing_key_id=code.signing_key_id, approval_evidence_checkpoint=code.approval_evidence_checkpoint,
            not_after=code.not_after, tail=code.tail if field != "entry_type" else pack_model(
                family_id=synthetic_family_id("GENESIS"), parent_entry_id=dig("parent"),
                weights_digest=dig("weights"), lifecycle_state=LIFECYCLE_CANDIDATE,
                qualification_record_digest=dig("qual-rec"),
            ),
        )
        kwargs[field] = value
        if field == "version":
            kwargs["min_permitted_version"] = 1
        if field == "min_permitted_version":
            kwargs["version"] = value
        if field == "entry_type":
            kwargs["policy_entry_id"] = dig("model-policy")
        other = encode_entry(**kwargs)
        assert other.entry_id != code.entry_id


def test_names_reject_charset_and_confusables_without_broadening_dots():
    assert unpack_name(pack_name("A")) == "A"
    assert unpack_name(pack_name("a" * 64)) == "a" * 64
    assert unpack_name(pack_name("a.b")) == "a.b"
    for bad in ["", ".", "..", "a" * 65, "has space", "a/b", "a\\b", "a\nb", "a\t", "a\x00b", "café", "А", "ﬁ", "a b"]:
        try:
            pack_name(bad)
        except Exception as exc:
            assert getattr(exc, "reason", "") in {"NAME_CHARSET", "NAME_TYPE", "NAME_PADDING"}
        else:
            raise AssertionError(bad)
    padded = pack_name("ab")
    evil = bytearray(padded)
    evil[3] = ord("c")
    try:
        unpack_name(bytes(evil))
        raise AssertionError("padding")
    except Exception as exc:
        assert exc.reason == "NAME_PADDING"
    assert name_skeleton("a0") == name_skeleton("aO")
    assert name_skeleton("l1I") == "111"
    assert name_skeleton("file0") != name_skeleton("fileo")
    policy = policy_entry("caps", operations=bit("G"), family=bytes(32))
    pid = policy.entry_id
    first = _entry(CODE, "mod0", 1, b"", bytes(32))
    second = _entry(CODE, "modO", 1, b"", bytes(32))
    other_type = _entry(MODEL, "modO", 1, pack_model(
        family_id=synthetic_family_id("GENESIS"), parent_entry_id=dig("parent"),
        weights_digest=dig("weights"), lifecycle_state=LIFECYCLE_CANDIDATE,
        qualification_record_digest=dig("qual-rec"),
    ), pid)
    try:
        build_registry_body(1, bytes(32), [policy, first, second])
        raise AssertionError("confusable")
    except Exception as exc:
        assert exc.reason == "CONFUSABLE_NAME"
    try:
        build_registry_body(1, bytes(32), [policy, first, other_type])
        raise AssertionError("cross-type confusable")
    except Exception as exc:
        assert exc.reason == "CONFUSABLE_NAME"


def test_unknown_state_version_and_trailing_bytes_fail_closed():
    policy = policy_entry("caps", operations=bit("G"), family=bytes(32))
    try:
        encode_entry(
            CODE, "verifier", 1, artifact_digest=dig("a"), provenance_digest=dig("p"),
            producer_entry_id=bytes(32), approval_state=9, min_permitted_version=1,
            policy_entry_id=bytes(32), signing_key_id=dig("k"),
            approval_evidence_checkpoint=dig("c"), not_after=0, tail=b"",
        )
        raise AssertionError("state")
    except Exception as exc:
        assert exc.reason == "APPROVAL_STATE"
    historical = encode_entry(
        CODE, "verifier", 1, artifact_digest=dig("a"), provenance_digest=dig("p"),
        producer_entry_id=bytes(32), approval_state=APPROVED, min_permitted_version=2,
        policy_entry_id=bytes(32), signing_key_id=dig("k"),
        approval_evidence_checkpoint=dig("c"), not_after=0, tail=b"",
    )
    decoded, _consumed = decode_entry(historical.canonical)
    assert decoded.version == 1 and decoded.min_permitted_version == 2
    assert decoded.entry_id == historical.entry_id
    registry, _parts, _grant = simple_g()
    flipped = bytearray(registry.raw)
    flipped[4] = 9
    auth = registry_authenticity(bytes(flipped), TOKENS)
    assert auth.decision == FAIL_CLOSED
    assert auth.reason == "UNKNOWN_VERSION"
    trailing = registry_authenticity(registry.raw + b"\x00", TOKENS)
    assert trailing.decision == FAIL_CLOSED
    short = registry_authenticity(registry.raw[:-1], TOKENS)
    assert short.decision == FAIL_CLOSED
    typed = bytearray(registry.raw)
    typed[45] = 99
    assert registry_authenticity(bytes(typed), TOKENS).decision == FAIL_CLOSED


def test_minimum_version_old_revoked_and_rollback_are_separate_from_authenticity():
    dest = make_destination("carried", "dest-id")
    policy = policy_entry("caps", operations=bit("G"), family=bytes(32), destinations=[dest.entry_id])
    parts = base_entries(policy, dest)
    old = parts["corpus"]
    current = _entry(CORPUS, "batch", 2, old.tail, policy.entry_id, minimum=2)
    revoked = _entry(CORPUS, "batch", 3, old.tail, policy.entry_id, minimum=3, approval=REVOKED)
    registry = world([*parts.values(), current, revoked])
    assert effective_min_version(registry, CORPUS, "batch") == 3
    fresh = registry_authenticity(registry.raw, TOKENS)
    assert fresh.decision == CHECKS_PASSED
    assert fresh.executable is False
    grant_old = g_grant(registry, parts, corpus=old)
    refused = crown_validate(grant_old, registry.raw, TOKENS, FLOORS, parts["image"].entry_id)
    assert refused.decision == FAIL_CLOSED
    assert refused.reason == "BELOW_FLOOR"
    grant_revoked = g_grant(registry, parts, corpus=revoked)
    assert crown_validate(grant_revoked, registry.raw, TOKENS, FLOORS, parts["image"].entry_id).reason == "REVOKED"
    newer = _entry(CORPUS, "batch", 3, old.tail, policy.entry_id, minimum=3)
    current_reg = world([*parts.values(), newer])
    grant_new = g_grant(current_reg, parts, corpus=newer)
    assert crown_validate(grant_new, current_reg.raw, TOKENS, FLOORS, parts["image"].entry_id).decision == CHECKS_PASSED
    old_registry = sign_entries(list(parts.values()), version=1)
    assert registry_authenticity(old_registry.raw, TOKENS).decision == CHECKS_PASSED
    raised = Floors(2, 1, 1, 1)
    assert registry_freshness(old_registry, raised, None).decision == FAIL_CLOSED
    assert registry_freshness(old_registry, raised, None).reason == "REGISTRY_FLOOR"
    linked = sign_entries(list(parts.values()) + [newer], version=2, previous=old_registry.registry_root)
    assert accept_registry(linked.raw, TOKENS, raised, old_registry).decision == CHECKS_PASSED
    forked = bytearray(linked.raw)
    # previous root sits at offset 9; damage it and the signature or the root check must fail closed
    forked[9] ^= 0x01
    assert accept_registry(bytes(forked), TOKENS, raised, old_registry).decision == FAIL_CLOSED


def test_crown_refuses_raw_digest_wrong_type_and_unknown_object():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    ok = crown_validate(grant, registry.raw, TOKENS, FLOORS, image)
    assert ok.decision == CHECKS_PASSED
    assert ok.executable is False
    assert ok.payload["corpus_generation"] == "NOT_AUTHORIZED"
    raw = refuse_proposer_digest(hashlib.sha256(b"proposer-file").digest())
    assert raw.decision == FAIL_CLOSED
    assert raw.reason == "RAW_DIGEST"
    evil_prefix = build_grant_prefix(
        klass="G", grant_id=b"G" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=parts["policy"].entry_id, target_role_id=parts["forge"].entry_id,
        env_measurement_digest=dig("env-forge"), code_entry_id=parts["code"].entry_id,
        challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"), created_at=0, not_after=0,
        max_runtime_s=30,
        tail={
            "corpus_entry_id": hashlib.sha256(b"not-an-entry").digest(), "batch_count": 1,
            "batch_ceiling_bytes": 10, "recipient_role_id": parts["witness"].entry_id,
            "destination_entry_id": parts["dest"].entry_id, "source_provenance_digest": dig("corpus-source"),
        },
    )
    evil = sign_grant(evil_prefix, OWNERS)
    unknown = crown_validate(evil, registry.raw, TOKENS, FLOORS, image)
    assert unknown.decision == FAIL_CLOSED
    assert unknown.reason == "ABSENT"
    wrong = bytearray(parse_grant(grant).raw)
    # Use the code entry id where the corpus id belongs: still a real entry, wrong class.
    code_id = parts["code"].entry_id
    body = parse_grant(grant).signed
    # corpus id is the first 32 bytes of the tail, tail starts at 278
    swapped = body[:278] + code_id + body[310:]
    swapped_grant = sign_grant(swapped, OWNERS)
    assert crown_validate(swapped_grant, registry.raw, TOKENS, FLOORS, image).reason == "WRONG_TYPE"
    pending_corpus = _entry(CORPUS, "pending-batch", 1, parts["corpus"].tail, parts["policy"].entry_id, approval=PENDING)
    pending_reg = world([*parts.values(), pending_corpus])
    pending_grant = g_grant(pending_reg, parts, corpus=pending_corpus)
    assert crown_validate(pending_grant, pending_reg.raw, TOKENS, FLOORS, image).reason == "NOT_APPROVED"


def test_consumer_does_not_call_crown_and_rechecks(monkeypatch):
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)

    def explode(*_args, **_kwargs):
        raise AssertionError("consumer called crown")

    monkeypatch.setattr("orca.rse.imp1.authority.crown_validate", explode)
    checked = consumer_verify(grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, *consumer_args(parts), **consumer_binding(registry))
    assert checked.decision == CHECKS_PASSED
    assert checked.executable is False
    bad_root = bytearray(grant)
    # registry root is at offset 34 of the signed prefix; damaging it breaks the signature or the root
    bad_root[34] ^= 0xFF
    forged = sign_grant(bytes(bad_root[: -130]), OWNERS)
    assert consumer_verify(forged, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, *consumer_args(parts), **consumer_binding(registry)).decision == FAIL_CLOSED
    skipped = consumer_verify(grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, *consumer_args(parts), crown_already_checked=True)
    assert skipped.decision == FAIL_CLOSED
    assert skipped.reason == "UNEXPECTED_ARGUMENT"


def test_display_comes_from_registry_and_sas_matches_the_freeze():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    result = crown_validate(grant, registry.raw, TOKENS, FLOORS, image)
    card = result.payload["card"]
    assert "CORPUS GENERATION" in card
    assert "GENERATE" in card
    assert "batch v1 [APPROVED, min 1]" in card
    assert "carried" in card
    assert "forge v3" in card
    assert "EPOCH        1" in card
    assert "spend 0" in card
    assert "proposer" not in card.lower()
    parsed = parse_grant(grant)
    sas = grant_sas(parsed.klass, parsed.signed)
    assert sas == result.payload["sas"]
    assert sas.count("-") == 2
    groups = sas.split("-")
    assert [len(group) for group in groups] == [4, 4, 4]
    alphabet = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert all(char in alphabet for group in groups for char in group)
    # Independent construction of the first 60 bits.
    digest = hashlib.sha256(b"OCR-SAS-v1\x00" + bytes([parsed.klass]) + parsed.signed).digest()
    bits = int.from_bytes(digest, "big") >> (256 - 60)
    alphabet_text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    chars = "".join(alphabet_text[(bits >> (55 - 5 * i)) & 31] for i in range(12))
    assert sas == f"{chars[0:4]}-{chars[4:8]}-{chars[8:12]}"
    mutated = bytearray(parsed.signed)
    mutated[-1] ^= 0x01
    assert grant_sas(parsed.klass, bytes(mutated)) != sas
    assert grant_sas(ord("V"), parsed.signed) != sas
    signature = inspect.signature(crown_validate.__wrapped__)
    assert "display" not in signature.parameters
    assert "proposer" not in signature.parameters


def test_intent_mismatch_fails_and_signed_grant_stays_authoritative():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    good = g_intent(registry, grant, parts)
    assert consumer_verify(grant, registry.raw, TOKENS, FLOORS, image, good, CHALLENGE, *consumer_args(parts), **consumer_binding(registry)).decision == CHECKS_PASSED
    wrongs = [
        good.__class__("V", good.artifact_name, good.artifact_version, good.destination_name, good.ceilings, good.sas),
        good.__class__("G", "other", good.artifact_version, good.destination_name, good.ceilings, good.sas),
        good.__class__("G", good.artifact_name, 9, good.destination_name, good.ceilings, good.sas),
        good.__class__("G", good.artifact_name, good.artifact_version, "elsewhere", good.ceilings, good.sas),
        good.__class__("G", good.artifact_name, good.artifact_version, good.destination_name, (1, 1, 1), good.sas),
        good.__class__("G", good.artifact_name, good.artifact_version, good.destination_name, good.ceilings, "AAAA-AAAA-AAAA"),
    ]
    for sheet in wrongs:
        result = consumer_verify(grant, registry.raw, TOKENS, FLOORS, image, sheet, CHALLENGE, *consumer_args(parts), **consumer_binding(registry))
        assert result.decision == FAIL_CLOSED
        assert result.reason.startswith("INTENT") or result.reason == "SAS"
    assert consumer_verify(grant, registry.raw, TOKENS, FLOORS, image, good, dig("other-challenge"), *consumer_args(parts), **consumer_binding(registry)).reason == "CHALLENGE"


def test_policy_caps_are_synthetic_and_refuse_raises():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    over = g_grant(registry, parts, batch_bytes=5000)
    assert crown_validate(over, registry.raw, TOKENS, FLOORS, image).reason == "RESOURCE_CAP"
    over_run = g_grant(registry, parts, batch_count=11)
    assert crown_validate(over_run, registry.raw, TOKENS, FLOORS, image).reason == "RUN_CAP"
    over_time = g_grant(registry, parts, runtime=1000)
    assert crown_validate(over_time, registry.raw, TOKENS, FLOORS, image).reason == "RUNTIME_CAP"
    # A destination under a different policy is outside this policy's destination scope.
    foreign = _entry(DESTINATION, "foreign", 1, parts["dest"].tail, bytes(32))
    mixed = world([*parts.values(), foreign])
    # The grant still names the original policy, which does not list the foreign destination.
    scoped = g_grant(mixed, parts, dest=foreign)
    assert crown_validate(scoped, mixed.raw, TOKENS, FLOORS, image).reason == "DESTINATION_SCOPE"
    blocked = crown_validate(grant, registry.raw, TOKENS, FLOORS, image)
    assert blocked.payload["spending"] is False
    assert spending_authorized() is False
    assert training_authorized() is False


def test_family_isolation_and_foundation_tokenizer_binding():
    genesis = synthetic_family_id("GENESIS")
    novus = synthetic_family_id("NOVUS")
    aeternum = synthetic_family_id("AETERNUM")
    assert len({genesis, novus, aeternum}) == 3
    dest = make_destination("carried", "dest-id")
    g_policy = policy_entry("g-caps", operations=bit("G"), family=bytes(32), destinations=[dest.entry_id])
    n_policy = policy_entry("n-caps", operations=bit("G") | bit("T") | bit("W"), family=novus, spend=40, batch=5000)
    a_policy = policy_entry("a-caps", operations=bit("T"), family=aeternum, spend=40)
    base = base_entries(g_policy, dest)

    def foundation(name, family, policy, tok_name):
        tok = _entry(TOKENIZER, tok_name, 1, pack_tokenizer(dig(tok_name + "-id"), dig(tok_name + "-vocab")), policy.entry_id)
        found = _entry(FOUNDATION_MODEL, name, 1, pack_foundation(
            family_id=family, foundation_model_id=dig(name + "-id"), foundation_revision=revision(name),
            tokenizer_entry_id=tok.entry_id, weights_digest=dig(name + "-weights"),
            license_record_digest=dig(name + "-license"), architecture_config_digest=dig(name + "-config"),
            artifact_format=1, inspection_evidence_digest=dig(name + "-inspect"),
        ), policy.entry_id, producer=policy.entry_id)
        model = _entry(MODEL, name + "-model", 1, pack_model(
            family_id=family, parent_entry_id=found.entry_id, weights_digest=dig(name + "-model-weights"),
            lifecycle_state=LIFECYCLE_ACCEPTED, qualification_record_digest=dig(name + "-qual"),
        ), policy.entry_id)
        return tok, found, model

    n_tok, n_found, n_model = foundation("novus-base", novus, n_policy, "novus-tok")
    a_tok, a_found, a_model = foundation("aeternum-base", aeternum, a_policy, "aeternum-tok")
    genesis_policy = policy_entry("genesis-caps", operations=bit("G"), family=genesis)
    g_tok, g_found, g_model = foundation("genesis-base", genesis, genesis_policy, "genesis-tok")
    registry = world([
        *base.values(), n_policy, a_policy, genesis_policy,
        g_tok, g_found, g_model, n_tok, n_found, n_model, a_tok, a_found, a_model,
    ])
    assert registry_authenticity(registry.raw, TOKENS).decision == CHECKS_PASSED
    assert parse_foundation(n_found.tail)["tokenizer_entry_id"] == n_tok.entry_id
    assert parse_foundation(n_found.tail)["artifact_format"] == 1
    assert n_model.entry_id != a_model.entry_id
    assert registry.by_id(n_model.entry_id).policy_entry_id == n_policy.entry_id
    assert registry.by_id(a_model.entry_id).policy_entry_id != n_policy.entry_id
    # Same enrolment bytes keep one ROLE_ID no matter which family policy sits beside them.
    assert base["forge"].policy_entry_id == bytes(32)
    again = _entry(ENROLMENT, "forge", 1, base["forge"].tail, bytes(32))
    assert again.entry_id == base["forge"].entry_id

    cross = _entry(MODEL, "cross-family", 1, pack_model(
        family_id=genesis, parent_entry_id=n_found.entry_id, weights_digest=dig("cross-weights"),
        lifecycle_state=LIFECYCLE_CANDIDATE, qualification_record_digest=dig("cross-qual"),
    ), n_policy.entry_id)
    bad = sign_registry(build_registry_body(1, bytes(32), sorted(
        [n_policy, n_tok, n_found, cross], key=lambda item: item.entry_id,
    )), OWNERS)
    assert registry_authenticity(bad, TOKENS).reason == "FAMILY_LINEAGE"

    image = base["image"].entry_id
    prefix = build_grant_prefix(
        klass="T", grant_id=b"T" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=n_policy.entry_id, target_role_id=base["forge"].entry_id,
        env_measurement_digest=dig("env-forge"), code_entry_id=base["code"].entry_id,
        challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"), created_at=0, not_after=0,
        max_runtime_s=20,
        tail={
            "corpus_entry_id": base["corpus"].entry_id, "foundation_entry_id": n_found.entry_id,
            "family_id": novus, "spend_ceiling": 5, "run_ceiling": 1, "provider_env_digest": dig("provider-env"),
        },
    )
    deferred = crown_validate(sign_grant(prefix, OWNERS), registry.raw, TOKENS, FLOORS, image)
    assert deferred.decision == FAIL_CLOSED
    assert deferred.reason == "UNSUPPORTED_CURRENT_MILESTONE"
    assert model_selection_authorized() is False
    assert gpu_authorized() is False
    assert provider_authorized() is False


def test_enrolment_key_substitution_changes_role_id():
    dest = make_destination("carried", "dest-id")
    policy = policy_entry("caps", operations=bit("G"), family=bytes(32), destinations=[dest.entry_id])
    parts = base_entries(policy, dest)
    original = parts["forge"]
    fields = parse_enrolment(original.tail)
    swapped = pack_enrolment(
        role_type=fields["role_type"], ed25519_public_key=public_of(key("forged-forge")),
        x25519_public_key=fields["x25519_public_key"], environment_measurement=fields["environment_measurement"],
        key_version=fields["key_version"],
    )
    forged = _entry(ENROLMENT, "forge", 1, swapped, bytes(32))
    assert forged.entry_id != original.entry_id
    registry = world(parts.values())
    assert registry.by_id(forged.entry_id) is None
    grant = g_grant(registry, parts)
    # A grant that names the substituted enrolment id is absent from the approved registry.
    parsed = parse_grant(grant)
    body = parsed.signed
    # target role id is at offset 98
    renamed = body[:98] + forged.entry_id + body[130:]
    attacked = sign_grant(renamed, OWNERS)
    assert crown_validate(attacked, registry.raw, TOKENS, FLOORS, parts["image"].entry_id).reason == "ABSENT"


def test_class_confusion_and_duplicate_entry_are_rejected():
    registry, parts, grant = simple_g()
    code_bytes = bytearray(parts["code"].canonical)
    code_bytes[0] = MODEL
    try:
        decode_entry(bytes(code_bytes))
        raise AssertionError("confusion")
    except Exception as exc:
        assert exc.reason in {"TAIL_LEN", "TRUNCATED", "LIFECYCLE", "NONCANONICAL"}
    duplicated = parts["code"].canonical + parts["code"].canonical
    # A single-entry decode must consume only one entry; extra bytes are the caller's framing problem.
    entry, consumed = decode_entry(duplicated)
    assert consumed == len(parts["code"].canonical)
    assert entry.entry_id == parts["code"].entry_id
    try:
        build_registry_body(1, bytes(32), [parts["policy"], parts["code"], parts["code"]])
        raise AssertionError("duplicate")
    except Exception as exc:
        assert exc.reason == "DUPLICATE_ENTRY"
    holdout_policy = policy_entry("q-caps", operations=bit("Q"), family=synthetic_family_id("GENESIS"), query=4, bits=8)
    # Q policy family is set; a holdout does not carry a family. The negative format check is on W.
    bad_format = build_grant_prefix(
        klass="W", grant_id=b"W" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=1, registry_root=registry.registry_root, policy_entry_id=parts["policy"].entry_id,
        target_role_id=parts["forge"].entry_id, env_measurement_digest=dig("env-forge"),
        code_entry_id=parts["code"].entry_id, challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"),
        created_at=0, not_after=0, max_runtime_s=1,
        tail={
            "model_entry_id": dig("m"), "qualification_record_digest": dig("q"), "source_entry_id": dig("s"),
            "destination_entry_id": dig("d"), "format": 2, "size_ceiling": 1, "recipient_role_id": dig("r"),
        },
    )
    try:
        parse_grant(sign_grant(bad_format, OWNERS))
        raise AssertionError("format")
    except Exception as exc:
        assert exc.reason == "ARTIFACT_FORMAT"
    assert holdout_policy.entry_type == 8
    assert pack_holdout(holdout_id=dig("hold"), bit_budget_total=8, query_budget_total=4)


def test_authorization_locks_and_posture_stay_denied():
    proof = prove_authorization_locks()
    assert proof.decision == CHECKS_PASSED
    assert proof.reason == "LOCKS_INTACT"
    assert proof.executable is False
    assert corpus_generation_authorized() is False
    assert qualification_authorized() is False
    assert model_selection_authorized() is False
    assert gpu_authorized() is False
    assert provider_authorized() is False
    assert spending_authorized() is False
    assert training_authorized() is False
    for key_name, value in proof.posture:
        assert value in (False, "NOT_AUTHORIZED")
    registry, parts, grant = simple_g()
    result = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, parts["image"].entry_id, g_intent(registry, grant, parts), CHALLENGE,
        *consumer_args(parts), **consumer_binding(registry),
    )
    assert result.decision == CHECKS_PASSED
    assert result.payload["corpus_generation"] == "NOT_AUTHORIZED"
    assert result.payload["qualification"] == "NOT_AUTHORIZED"
    assert result.payload["training"] is False
    assert result.payload["gpu"] is False
    assert result.payload["provider"] is False
    assert result.payload["spending"] is False
    assert "hardware_anti_rollback" in result.payload["not_claimed"]


def test_unexpected_exception_is_fail_closed(monkeypatch):
    registry, parts, grant = simple_g()

    def boom(*_args, **_kwargs):
        raise RuntimeError("parser blew up")

    monkeypatch.setattr("orca.rse.imp1.authority.parse_grant", boom)
    result = crown_validate(grant, registry.raw, TOKENS, FLOORS, parts["image"].entry_id)
    assert result.decision == FAIL_CLOSED
    assert result.reason == "UNEXPECTED"
    assert result.decision not in {"ALLOW", "PASS", "APPROVED"}
    assert result.executable is False


def test_toctou_parse_copies_bytes_and_quarantines_duplicate_ids():
    registry, parts, _grant = simple_g()
    buf = bytearray(registry.raw)
    parsed = parse_registry(buf)
    buf[0] = 0
    assert parsed.raw[0:4] == b"OREG"
    assert parsed.entries[0].entry_id == parts["policy"].entry_id or parsed.by_id(parts["policy"].entry_id) is not None
    # Two different entry objects cannot share an id unless the bytes are identical.
    # A contradictory blob is quarantined or fail-closed, never accepted.
    doubled = bytearray(registry.raw)
    # Invalidate the root while leaving a duplicated name attempt to the builder, covered above.
    doubled[-131] ^= 0x01
    assert registry_authenticity(bytes(doubled), TOKENS).decision in {FAIL_CLOSED, QUARANTINE}


def test_operation_scope_and_retirement_and_role_type():
    registry, parts, grant = simple_g()
    prefix = build_grant_prefix(
        klass="T", grant_id=b"T" * 16, owner_authority_version=1, incident_epoch=1,
        registry_version=registry.registry_version, registry_root=registry.registry_root,
        policy_entry_id=parts["policy"].entry_id, target_role_id=parts["forge"].entry_id,
        env_measurement_digest=dig("env-forge"), code_entry_id=parts["code"].entry_id,
        challenge=CHALLENGE, prev_role_checkpoint=dig("prev-checkpoint"), created_at=0, not_after=0,
        max_runtime_s=1,
        tail={
            "corpus_entry_id": parts["corpus"].entry_id, "foundation_entry_id": dig("missing-foundation"),
            "family_id": synthetic_family_id("GENESIS"), "spend_ceiling": 0, "run_ceiling": 1,
            "provider_env_digest": dig("provider-env"),
        },
    )
    assert crown_validate(sign_grant(prefix, OWNERS), registry.raw, TOKENS, FLOORS, parts["image"].entry_id).reason == "UNSUPPORTED_CURRENT_MILESTONE"
    v_dest = make_destination("carried", "dest-id")
    v_policy = policy_entry("v-only", operations=bit("V"), family=bytes(32), destinations=[v_dest.entry_id])
    v_parts = base_entries(v_policy, v_dest)
    v_reg = world(v_parts.values())
    assert crown_validate(
        g_grant(v_reg, v_parts), v_reg.raw, TOKENS, FLOORS, v_parts["image"].entry_id,
    ).reason == "OPERATION_SCOPE"
    retired = _entry(CORPUS, "batch", 1, pack_corpus(
        corpus_id=dig("corpus-id"), corpus_version=1, manifest_digest=dig("manifest"),
        source_provenance_digest=dig("corpus-source"), witness_acceptance_record_digest=dig("witness-accept"),
        contamination_status_ref=dig("contamination"), retirement_state=RETIREMENT_RETIRED,
    ), parts["policy"].entry_id)
    # Same type, name and version as the approved corpus: duplicate, rejected at build.
    try:
        world([*parts.values(), retired])
        raise AssertionError("same version")
    except Exception:
        pass
    retired = _entry(CORPUS, "oldbatch", 1, retired.tail, parts["policy"].entry_id)
    reg2 = world([*parts.values(), retired])
    assert crown_validate(g_grant(reg2, parts, corpus=retired), reg2.raw, TOKENS, FLOORS, parts["image"].entry_id).reason == "RETIRED_CORPUS"
    assert parse_grant(grant).klass == ord("G")
    assert DEST_EXPORT_TARGET == 3
    assert ROLE_FORGE == 2 and ROLE_WITNESS == 3
    assert HOLDOUT_SET == 10 and LIFECYCLE_EXPORTED == 4
