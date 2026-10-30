"""C06 / C07 consumer verification — adversarial engineering probes.

C06 evidence_required: Rendered-card digest showing the consumer rendered the
received signed bytes.
C07 evidence_required: Typed-entry record for the SAS and the Intent Sheet fields.

These tests exercise the dedicated consumer-verification evidence path over
real IMP-1 codec / registry / Crown primitives. Parser unit tests alone are
not treated as C06 rendered-card evidence.
"""

from __future__ import annotations

import hashlib
import json

from orca.rse.imp1.authority import (
    ChallengeLedger,
    IntentSheet,
    authenticate_registry,
    consumer_verify,
    crown_validate,
    grant_sas,
    render_card,
)
from orca.rse.imp1.codec import parse_grant, sign_grant
from orca.rse.imp1.consumer_verification import (
    C06_CARD_DOMAIN,
    C07_TYPED_DOMAIN,
    consumer_confirm_from_signed_bytes,
    render_from_signed_bytes,
    verify_typed_sas_and_intent,
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
    simple_g,
)


# ---------------------------------------------------------------------------
# Negative probes first (must fail closed before any success is trusted)
# ---------------------------------------------------------------------------


def test_c06_refuses_malformed_truncated_grant():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    truncated = grant[:40]
    refused = render_from_signed_bytes(truncated, registry.raw, TOKENS, FLOORS, image)
    assert refused.decision == FAIL_CLOSED
    assert refused.payload is not None
    assert refused.payload["authority_usable"] is False
    assert refused.payload["requirement_id"] == "C06"
    assert refused.reason in {"TRUNCATED", "GRANT_LEN", "MAGIC", "UNEXPECTED"}
    assert refused.payload["rendered_card_evidence"]["card"] == ""
    assert refused.payload["rendered_card_evidence"]["binding_digest"] == ""


def test_c06_refuses_altered_byte_and_wrong_signature():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    altered = bytearray(grant)
    # Flip a byte inside the signed region (after magic/version/class).
    altered[40] ^= 0xFF
    refused = render_from_signed_bytes(bytes(altered), registry.raw, TOKENS, FLOORS, image)
    assert refused.decision == FAIL_CLOSED

    # Re-sign a mutated body so signatures verify but content differs from original.
    body = parse_grant(grant).signed
    mutated = bytearray(body)
    mutated[-1] ^= 0x01
    # Non-canonical / broken layout after flip should fail parse or signature path.
    try:
        forged = sign_grant(bytes(mutated), OWNERS)
    except Exception:
        forged = bytes(mutated) + grant[-130:]
    refused2 = render_from_signed_bytes(forged, registry.raw, TOKENS, FLOORS, image)
    assert refused2.decision == FAIL_CLOSED


def test_c06_refuses_crown_b1_card_when_received_bytes_are_b2():
    """Adversarial: Crown shows B1, signs B2 — consumer must not accept B1 card."""
    registry, parts, grant_b2 = simple_g()
    image = parts["image"].entry_id
    # B1 is a different valid grant (different ceilings) — distinct signed bytes.
    grant_b1 = g_grant(registry, parts, batch_bytes=50)
    assert grant_b1 != grant_b2
    card_b1 = crown_validate(grant_b1, registry.raw, TOKENS, FLOORS, image).payload["card"]
    card_b2 = crown_validate(grant_b2, registry.raw, TOKENS, FLOORS, image).payload["card"]
    assert card_b1 != card_b2

    # Consumer receives B2 but an attacker supplies Crown's B1 display string.
    refused = render_from_signed_bytes(
        grant_b2, registry.raw, TOKENS, FLOORS, image, claimed_card=card_b1,
    )
    assert refused.decision == FAIL_CLOSED
    assert refused.reason == "CARD_MISMATCH"

    # Rendering from B2 alone yields B2's card, not B1.
    ok = render_from_signed_bytes(grant_b2, registry.raw, TOKENS, FLOORS, image)
    assert ok.decision == CHECKS_PASSED
    assert ok.payload["card"] == card_b2
    assert ok.payload["card"] != card_b1


def test_c06_refuses_noncanonical_and_mismatched_raw():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    # Extra trailing byte → GRANT_LEN
    padded = grant + b"\x00"
    assert render_from_signed_bytes(padded, registry.raw, TOKENS, FLOORS, image).decision == FAIL_CLOSED
    # Wrong magic
    bad_magic = b"XXXX" + grant[4:]
    assert render_from_signed_bytes(bad_magic, registry.raw, TOKENS, FLOORS, image).decision == FAIL_CLOSED


def test_c07_refuses_incorrect_sas_unicode_confusable_and_form():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)

    wrong = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        "AAAA-AAAA-AAAA", intent, CHALLENGE, role, env, **binding,
    )
    assert wrong.decision == FAIL_CLOSED
    assert wrong.reason == "SAS"

    # Unicode lookalike hyphen / fullwidth characters
    computed = intent.sas
    unicode_hyphen = computed.replace("-", "\u2010")
    assert verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        unicode_hyphen, intent, CHALLENGE, role, env, **binding,
    ).reason == "SAS_UNICODE"

    # Confusable: digit/letter outside Base32 alphabet (e.g. 0, 1, 8, 9)
    confusable = "AAAA-AAA0-AAAA"
    assert verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        confusable, intent, CHALLENGE, role, env, **binding,
    ).reason == "SAS_ALPHABET"

    lowercase = computed.lower()
    assert verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        lowercase, intent, CHALLENGE, role, env, **binding,
    ).reason == "SAS_ALPHABET"

    nosep = computed.replace("-", "")
    assert verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        nosep, intent, CHALLENGE, role, env, **binding,
    ).reason == "SAS_FORM"


def test_c07_refuses_altered_intent_fields():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    good = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    wrongs = [
        IntentSheet("V", good.artifact_name, good.artifact_version, good.destination_name,
                    good.ceilings, good.sas, target_role_name=good.target_role_name,
                    counterpart_name=good.counterpart_name),
        IntentSheet("G", "other", good.artifact_version, good.destination_name,
                    good.ceilings, good.sas, target_role_name=good.target_role_name,
                    counterpart_name=good.counterpart_name),
        IntentSheet("G", good.artifact_name, 9, good.destination_name,
                    good.ceilings, good.sas, target_role_name=good.target_role_name,
                    counterpart_name=good.counterpart_name),
        IntentSheet("G", good.artifact_name, good.artifact_version, "elsewhere",
                    good.ceilings, good.sas, target_role_name=good.target_role_name,
                    counterpart_name=good.counterpart_name),
        IntentSheet("G", good.artifact_name, good.artifact_version, good.destination_name,
                    (1, 1, 1), good.sas, target_role_name=good.target_role_name,
                    counterpart_name=good.counterpart_name),
        IntentSheet("G", good.artifact_name, good.artifact_version, good.destination_name,
                    good.ceilings, good.sas, target_role_name="witness",
                    counterpart_name=good.counterpart_name),
    ]
    for sheet in wrongs:
        result = verify_typed_sas_and_intent(
            grant, registry.raw, TOKENS, FLOORS, image,
            good.sas, sheet, CHALLENGE, role, env, **binding,
        )
        assert result.decision == FAIL_CLOSED
        assert result.reason.startswith("INTENT") or result.reason == "SAS"


def test_c07_refuses_stale_grant_and_cross_session_challenge():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)

    # Wrong outstanding challenge (cross-session / stale).
    other = dig("other-session-challenge")
    stale = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        intent.sas, intent, other, role, env,
        highest_authenticated_version=registry.registry_version,
        challenge_ledger=ChallengeLedger(other),
    )
    assert stale.decision == FAIL_CLOSED
    assert stale.reason == "CHALLENGE"

    # Voided ledger after snapshot mismatch — sticky refuse.
    ledger = ChallengeLedger(CHALLENGE)
    # Force a higher authenticated version than the grant's registry version.
    superseded = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        intent.sas, intent, CHALLENGE, role, env,
        highest_authenticated_version=registry.registry_version + 1,
        challenge_ledger=ledger,
    )
    assert superseded.decision == FAIL_CLOSED
    assert superseded.reason == "SNAPSHOT"
    assert ledger.is_void(CHALLENGE)
    again = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        intent.sas, intent, CHALLENGE, role, env,
        highest_authenticated_version=registry.registry_version,
        challenge_ledger=ledger,
    )
    assert again.decision == FAIL_CLOSED
    assert again.reason == "CHALLENGE_VOID"


def test_c07_refuses_identity_and_environment_mismatch():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    binding = consumer_binding(registry)
    # Wrong role identity
    wrong_role = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        intent.sas, intent, CHALLENGE, parts["witness"].entry_id, dig("env-forge"),
        **binding,
    )
    assert wrong_role.reason == "ROLE_ID"
    # Wrong environment measurement
    wrong_env = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        intent.sas, intent, CHALLENGE, parts["forge"].entry_id, dig("env-witness"),
        **binding,
    )
    assert wrong_env.reason == "ENVIRONMENT"


def test_c06_c07_refuse_inconsistent_signed_bytes_substitution():
    """Replay/substitution: typed confirmation for grant A against grant B bytes."""
    registry, parts, grant_a = simple_g()
    grant_b = g_grant(registry, parts, batch_bytes=50)
    image = parts["image"].entry_id
    intent_a = g_intent(registry, grant_a, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)

    # Present B's bytes but type A's SAS / intent.
    swapped = verify_typed_sas_and_intent(
        grant_b, registry.raw, TOKENS, FLOORS, image,
        intent_a.sas, intent_a, CHALLENGE, role, env, **binding,
    )
    assert swapped.decision == FAIL_CLOSED
    assert swapped.reason in {"SAS", "INTENT_CEILINGS", "INTENT_ARTIFACT"}

    # Combined path must also refuse.
    combined = consumer_confirm_from_signed_bytes(
        grant_b, registry.raw, TOKENS, FLOORS, image,
        intent_a.sas, intent_a, CHALLENGE, role, env, **binding,
    )
    assert combined.decision == FAIL_CLOSED


# ---------------------------------------------------------------------------
# Positive probes — canonical rendered-card + typed-entry evidence
# ---------------------------------------------------------------------------


def test_c06_rendered_card_digest_binds_to_exact_verified_input():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    crown = crown_validate(grant, registry.raw, TOKENS, FLOORS, image)
    assert crown.decision == CHECKS_PASSED

    result = render_from_signed_bytes(grant, registry.raw, TOKENS, FLOORS, image)
    assert result.decision == CHECKS_PASSED
    assert result.executable is False
    assert result.payload["authority_usable"] is False
    assert result.payload["spending"] is False
    assert result.payload["training"] is False

    evidence = result.payload["rendered_card_evidence"]
    assert evidence["requirement_id"] == "C06"
    assert evidence["decision"] == CHECKS_PASSED
    assert evidence["card"] == crown.payload["card"]
    assert evidence["card"] == result.payload["card"]
    assert "GRANT SAS" in evidence["card"]
    assert evidence["grant_raw_digest"] == hashlib.sha256(grant).hexdigest()
    parsed = parse_grant(grant)
    assert evidence["signed_region_digest"] == hashlib.sha256(parsed.signed).hexdigest()
    assert evidence["card_digest"] == hashlib.sha256(evidence["card"].encode("utf-8")).hexdigest()

    expected_binding = hashlib.sha256(
        C06_CARD_DOMAIN + b"\x00" + grant + b"\x00" + evidence["card"].encode("utf-8")
    ).hexdigest()
    assert evidence["binding_digest"] == expected_binding

    # Any alteration of input bytes changes the binding (even if card text collided,
    # which it cannot for a content-bound render of a different grant).
    other = g_grant(registry, parts, batch_bytes=50)
    other_ev = render_from_signed_bytes(other, registry.raw, TOKENS, FLOORS, image)
    assert other_ev.decision == CHECKS_PASSED
    assert other_ev.payload["rendered_card_evidence"]["binding_digest"] != evidence["binding_digest"]
    assert other_ev.payload["rendered_card_evidence"]["card_digest"] != evidence["card_digest"]


def test_c06_evidence_is_reproducible_and_not_a_parser_unit_test_substitute():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    first = render_from_signed_bytes(grant, registry.raw, TOKENS, FLOORS, image)
    second = render_from_signed_bytes(grant, registry.raw, TOKENS, FLOORS, image)
    assert first.payload["rendered_card_evidence"] == second.payload["rendered_card_evidence"]
    # Card must come from render_card over verified grant — not from an injected string.
    grant_obj = parse_grant(grant)
    expected_card = render_card(
        grant_obj, authenticate_registry(registry.raw, TOKENS), FLOORS, image,
    )
    assert first.payload["card"] == expected_card


def test_c07_typed_entry_record_for_sas_and_intent_sheet():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)

    result = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        intent.sas, intent, CHALLENGE, role, env, **binding,
    )
    assert result.decision == CHECKS_PASSED
    assert result.executable is False
    assert result.payload["authority_usable"] is False

    record = result.payload["typed_entry_record"]
    assert record["requirement_id"] == "C07"
    assert record["typed_sas"] == intent.sas
    assert record["computed_sas"] == intent.sas
    assert record["typed_intent"]["grant_class"] == "G"
    assert record["typed_intent"]["artifact_name"] == parts["corpus"].name
    assert record["typed_intent"]["destination_name"] == parts["dest"].name
    assert record["grant_derived_intent"]["sas"] == intent.sas
    assert record["grant_raw_digest"] == hashlib.sha256(grant).hexdigest()

    # Record digest is deterministic over the public typed-entry body.
    body = {
        "typed_sas": record["typed_sas"],
        "computed_sas": record["computed_sas"],
        "typed_intent": record["typed_intent"],
        "grant_derived_intent": record["grant_derived_intent"],
        "grant_raw_digest": record["grant_raw_digest"],
        "signed_region_digest": hashlib.sha256(parse_grant(grant).signed).hexdigest(),
        "sas_domain": "OCR-SAS-v1",
        "sas_bits": 60,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    expected = hashlib.sha256(C07_TYPED_DOMAIN + b"\x00" + canonical.encode("ascii")).hexdigest()
    assert record["record_digest"] == expected

    # No secret material in the persisted record.
    blob = json.dumps(record)
    assert "private" not in blob.lower()
    assert "seed" not in blob.lower()


def test_c07_sas_is_sixty_bit_over_received_signed_bytes():
    registry, parts, grant = simple_g()
    parsed = parse_grant(grant)
    sas = grant_sas(parsed.klass, parsed.signed)
    digest = hashlib.sha256(b"OCR-SAS-v1\x00" + bytes([parsed.klass]) + parsed.signed).digest()
    bits = int.from_bytes(digest, "big") >> (256 - 60)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    chars = "".join(alphabet[(bits >> (55 - 5 * i)) & 31] for i in range(12))
    assert sas == f"{chars[0:4]}-{chars[4:8]}-{chars[8:12]}"
    # Mutating signed bytes changes SAS.
    mutated = bytearray(parsed.signed)
    mutated[-1] ^= 0x01
    assert grant_sas(parsed.klass, bytes(mutated)) != sas


def test_c06_c07_combined_confirm_preserves_imp1_consumer_semantics():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)

    # Baseline IMP-1 consumer_verify still passes for the same inputs.
    baseline = consumer_verify(
        grant, registry.raw, TOKENS, FLOORS, image, intent, CHALLENGE, role, env, **binding,
    )
    assert baseline.decision == CHECKS_PASSED

    combined = consumer_confirm_from_signed_bytes(
        grant, registry.raw, TOKENS, FLOORS, image,
        intent.sas, intent, CHALLENGE, role, env, **binding,
    )
    assert combined.decision == CHECKS_PASSED
    assert combined.reason == "C06_C07_CONFIRMED"
    assert combined.executable is False
    assert combined.payload["authority_usable"] is False
    assert "rendered_card_evidence" in combined.payload
    assert "typed_entry_record" in combined.payload
    assert combined.payload["card"] == baseline.payload["card"]
    assert combined.payload["sas"] == baseline.payload["sas"]


def test_c06_c07_unexpected_kwargs_fail_closed():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    assert render_from_signed_bytes(
        grant, registry.raw, TOKENS, FLOORS, image, crown_already_checked=True,
    ).reason == "UNEXPECTED_ARGUMENT"
    assert verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image,
        intent.sas, intent, CHALLENGE, role, env, crown_already_checked=True, **binding,
    ).reason == "UNEXPECTED_ARGUMENT"


def test_c06_claimed_card_matching_received_bytes_is_accepted():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    card = crown_validate(grant, registry.raw, TOKENS, FLOORS, image).payload["card"]
    ok = render_from_signed_bytes(
        grant, registry.raw, TOKENS, FLOORS, image, claimed_card=card,
    )
    assert ok.decision == CHECKS_PASSED
    assert ok.payload["rendered_card_evidence"]["card"] == card
