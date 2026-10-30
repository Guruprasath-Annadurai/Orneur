"""
ORNEUR FOUNDATION-03 INDEPENDENT QUALIFICATION TEST SUITE
Candidate: PR #142 (cursor/foundation-03-rse-consumer-verification-9658)
Candidate Engineering SHA: 0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51
Qualified Parent PR #140 HEAD: 649d90f84069fc618ba4d69b4c26a66bed731caa

Audited Scope:
- C06: Signed-byte consumer rendering and SHA-256 evidence binding
- C07: 60-bit SAS (OCR-SAS-v1) and independent Intent Sheet comparison
- Preserved Governance & Formal Acceptance Ledger (0/95)
- Training Lock & Spending Denial Verification
"""

import sys
sys.path.insert(0, '/home/pc/projects/Orneur-pr142-f03')

import hashlib
import json
import os
import subprocess
from pathlib import Path
import pytest

from orca.rse.imp1.authority import (
    ChallengeLedger,
    IntentSheet,
    authenticate_registry,
    crown_validate,
    grant_sas,
    render_card,
)
from orca.rse.imp1.codec import parse_grant
from orca.rse.imp1.consumer_verification import (
    C06_CARD_DOMAIN,
    C07_TYPED_DOMAIN,
    RenderedCardEvidence,
    TypedEntryRecord,
    consumer_confirm_from_signed_bytes,
    render_from_signed_bytes,
    verify_typed_sas_and_intent,
    _card_binding,
    _typed_record_digest,
    _normalize_typed_sas,
    _grant_derived_intent,
)
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, FailClosed
from tests.rse.support import (
    CHALLENGE,
    FLOORS,
    OWNERS,
    TOKENS,
    consumer_args,
    consumer_binding,
    g_grant,
    g_intent,
    simple_g,
)

CANDIDATE_SHA = "0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51"
PARENT_SHA = "649d90f84069fc618ba4d69b4c26a66bed731caa"
CANDIDATE_WORKTREE = Path("/home/pc/projects/Orneur-pr142-f03")


# ===========================================================================
# Gate 1: Candidate Lineage, Worktree Integrity, and Missing Handoff Docs
# ===========================================================================


def test_candidate_sha_and_parent_lineage():
    """Verify candidate commit SHA, base parent commit, and clean worktree."""
    assert CANDIDATE_WORKTREE.is_dir(), f"Worktree missing: {CANDIDATE_WORKTREE}"

    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=CANDIDATE_WORKTREE, text=True
    ).strip()
    assert head == CANDIDATE_SHA, f"Candidate HEAD mismatch: {head} != {CANDIDATE_SHA}"

    parent = subprocess.check_output(
        ["git", "rev-parse", f"{CANDIDATE_SHA}~1"], cwd=CANDIDATE_WORKTREE, text=True
    ).strip()
    assert parent == PARENT_SHA, f"Candidate parent mismatch: {parent} != {PARENT_SHA}"

    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=CANDIDATE_WORKTREE, text=True
    ).strip()
    assert status == "", f"Candidate worktree must be pristine clean, found: {status}"

    diff_files = subprocess.check_output(
        ["git", "diff", "--name-only", PARENT_SHA, CANDIDATE_SHA],
        cwd=CANDIDATE_WORKTREE,
        text=True,
    ).strip().splitlines()
    expected_files = [
        "orca/rse/imp1/consumer_verification.py",
        "tests/rse/test_c06_c07_consumer_verification.py",
    ]
    assert sorted(diff_files) == sorted(expected_files), f"Unexpected file diff: {diff_files}"


def test_missing_in_repo_handoff_documentation_finding():
    """Verify that Cursor referenced external ephemeral docs not present in git."""
    assert not Path("/cursor/stores").exists(), "/cursor/stores should not exist on host"
    repo_matches = list(CANDIDATE_WORKTREE.glob("**/foundation-03*.md"))
    assert len(repo_matches) == 0, (
        f"Handoff documents unexpectedly present in git: {repo_matches}"
    )


def test_governance_immutability_and_formal_acceptance_zero():
    """Confirm protected governance files are 0 diff and acceptance remains 0/95."""
    governance_files = [
        "acceptance_ledger.json",
        "TRAINING_AUTHORITY_REGISTRY.json",
        "TRAINING_AUTHORIZATION.json",
        "orca/training/authorization.py",
        "orca/training/training_freeze.py",
    ]
    for gf in governance_files:
        diff = subprocess.check_output(
            ["git", "diff", PARENT_SHA, CANDIDATE_SHA, "--", gf],
            cwd=CANDIDATE_WORKTREE,
            text=True,
        ).strip()
        assert diff == "", f"Governance file {gf} was modified between parent and candidate!"

    res = subprocess.check_output(
        ["python3", "scripts/acceptance/validate_register_graph.py", "--check"],
        cwd=CANDIDATE_WORKTREE,
        text=True,
    ).strip()
    assert "pretraining=95 numerator=0" in res, f"Formal acceptance not 0/95: {res}"


# ===========================================================================
# Gate 2: C06 Adversarial Challenges (Signed-Byte Consumer Rendering)
# ===========================================================================


def test_c06_adversarial_crown_b1_b2_substitution():
    """Challenge C06: Attacker/Crown displays card B1 while sending grant bytes B2."""
    registry, parts, grant_b2 = simple_g()
    image = parts["image"].entry_id

    # batch_bytes=50 creates distinct signed bytes from simple_g()'s batch_bytes=100
    grant_b1 = g_grant(registry, parts, batch_bytes=50)
    assert grant_b1 != grant_b2

    card_b1 = crown_validate(grant_b1, registry.raw, TOKENS, FLOORS, image).payload["card"]
    card_b2 = crown_validate(grant_b2, registry.raw, TOKENS, FLOORS, image).payload["card"]
    assert card_b1 != card_b2

    res = render_from_signed_bytes(
        grant_b2, registry.raw, TOKENS, FLOORS, image, claimed_card=card_b1
    )
    assert res.decision == FAIL_CLOSED
    assert res.reason == "CARD_MISMATCH"
    assert res.payload["authority_usable"] is False

    res_valid = render_from_signed_bytes(
        grant_b2, registry.raw, TOKENS, FLOORS, image, claimed_card=card_b2
    )
    assert res_valid.decision == CHECKS_PASSED
    assert res_valid.reason == "C06_RENDERED_CARD"
    assert res_valid.payload["rendered_card_evidence"]["card"] == card_b2


def test_c06_adversarial_tampered_bytes_and_noncanonical():
    """Challenge C06: Tampered grant bytes, trailing bytes, and non-canonical payloads."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id

    tampered = bytearray(grant)
    tampered[35] ^= 0x01
    res_tampered = render_from_signed_bytes(bytes(tampered), registry.raw, TOKENS, FLOORS, image)
    assert res_tampered.decision == FAIL_CLOSED

    trailing = grant + b"\x00"
    res_trailing = render_from_signed_bytes(trailing, registry.raw, TOKENS, FLOORS, image)
    assert res_trailing.decision == FAIL_CLOSED
    assert res_trailing.reason in {"RAW_MISMATCH", "UNEXPECTED", "GRANT_LEN"}

    truncated = grant[:20]
    res_truncated = render_from_signed_bytes(truncated, registry.raw, TOKENS, FLOORS, image)
    assert res_truncated.decision == FAIL_CLOSED


def test_c06_cryptographic_evidence_binding():
    """Challenge C06: Validate SHA-256 card-binding domain and byte-reproducibility."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id

    res = render_from_signed_bytes(grant, registry.raw, TOKENS, FLOORS, image)
    assert res.decision == CHECKS_PASSED
    card = res.payload["card"]
    binding = res.payload["rendered_card_evidence"]["binding_digest"]

    expected_material = C06_CARD_DOMAIN + b"\x00" + grant + b"\x00" + card.encode("utf-8")
    expected_digest = hashlib.sha256(expected_material).hexdigest()
    assert binding == expected_digest, f"Binding mismatch: {binding} != {expected_digest}"

    tampered_card = card + " "
    tampered_material = C06_CARD_DOMAIN + b"\x00" + grant + b"\x00" + tampered_card.encode("utf-8")
    tampered_digest = hashlib.sha256(tampered_material).hexdigest()
    assert tampered_digest != binding


def test_c06_scope_is_in_memory_formatting_only():
    """Document scope limit: C06 produces in-memory formatted text, not GUI/TUI display confirmation."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    res = render_from_signed_bytes(grant, registry.raw, TOKENS, FLOORS, image)
    assert res.decision == CHECKS_PASSED
    card = res.payload["card"]
    assert isinstance(card, str)
    assert "GRANT SAS" in card
    assert res.payload["authority_usable"] is False


# ===========================================================================
# Gate 3: C07 Adversarial Challenges (60-bit SAS & Intent Sheet)
# ===========================================================================


def test_c07_adversarial_sas_unicode_and_confusable_homoglyphs():
    """Challenge C07: Homoglyphs, unicode variants, lowercase, and malformed delimiters."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas

    valid_res = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent, CHALLENGE, role, env,
        **binding
    )
    assert valid_res.decision == CHECKS_PASSED

    # 1. Cyrillic homoglyphs
    confusable_sas = sas.replace("A", "\u0410")
    if confusable_sas != sas:
        res = verify_typed_sas_and_intent(
            grant, registry.raw, TOKENS, FLOORS, image, confusable_sas, intent, CHALLENGE, role, env,
            **binding
        )
        assert res.decision == FAIL_CLOSED
        assert res.reason == "SAS_UNICODE"

    # 2. Lowercase letters
    lowercase_sas = sas.lower()
    res_lower = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, lowercase_sas, intent, CHALLENGE, role, env,
        **binding
    )
    assert res_lower.decision == FAIL_CLOSED
    assert res_lower.reason == "SAS_ALPHABET"

    # 3. Leading/trailing whitespace
    padded_sas = " " + sas + " "
    res_padded = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, padded_sas, intent, CHALLENGE, role, env,
        **binding
    )
    assert res_padded.decision == FAIL_CLOSED
    assert res_padded.reason == "SAS_FORM"

    # 4. Wrong delimiter (e.g. colon instead of hyphen)
    colon_sas = sas.replace("-", ":")
    res_colon = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, colon_sas, intent, CHALLENGE, role, env,
        **binding
    )
    assert res_colon.decision == FAIL_CLOSED
    assert res_colon.reason == "SAS_FORM"


def test_c07_sas_60bit_entropy_guarantee():
    """Verify 60-bit SAS generation, format XXXX-XXXX-XXXX, and domain separation."""
    registry, parts, grant = simple_g()
    intent = g_intent(registry, grant, parts)
    sas = intent.sas

    parsed = parse_grant(grant)
    computed_sas = grant_sas(parsed.klass, parsed.signed)

    assert computed_sas == sas
    segments = computed_sas.split("-")
    assert len(segments) == 3
    assert all(len(p) == 4 for p in segments)
    assert len("".join(segments)) == 12


def test_c07_adversarial_intent_sheet_tampering():
    """Challenge C07: Mutating each field of IntentSheet must fail closed."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas

    bad_artifact = IntentSheet(
        grant_class=intent.grant_class,
        artifact_name="malicious_model_weights",
        artifact_version=intent.artifact_version,
        destination_name=intent.destination_name,
        ceilings=intent.ceilings,
        sas=intent.sas,
        target_role_name=intent.target_role_name,
        counterpart_name=intent.counterpart_name,
        sequence=intent.sequence,
    )
    res_bad_art = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, bad_artifact, CHALLENGE, role, env,
        **binding
    )
    assert res_bad_art.decision == FAIL_CLOSED
    assert res_bad_art.reason == "INTENT_ARTIFACT"

    bad_ceilings = IntentSheet(
        grant_class=intent.grant_class,
        artifact_name=intent.artifact_name,
        artifact_version=intent.artifact_version,
        destination_name=intent.destination_name,
        ceilings=(("batch_bytes", 9999999),),
        sas=intent.sas,
        target_role_name=intent.target_role_name,
        counterpart_name=intent.counterpart_name,
        sequence=intent.sequence,
    )
    res_bad_ceil = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, bad_ceilings, CHALLENGE, role, env,
        **binding
    )
    assert res_bad_ceil.decision == FAIL_CLOSED
    assert res_bad_ceil.reason == "INTENT_CEILINGS"


def test_c07_stale_and_voided_challenge_replay():
    """Challenge C07: Replaying a voided challenge or mismatched environment fails closed."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas

    # Void the challenge in the ledger
    ledger = binding["challenge_ledger"]
    ledger.void_challenge(CHALLENGE)
    assert ledger.is_void(CHALLENGE)

    res_void = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent, CHALLENGE, role, env,
        **binding
    )
    assert res_void.decision == FAIL_CLOSED
    assert res_void.reason == "CHALLENGE_VOID"

    # Environment measurement mismatch
    fresh_binding = consumer_binding(registry)
    res_bad_env = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent, CHALLENGE, role, b"X" * 32,
        **fresh_binding
    )
    assert res_bad_env.decision == FAIL_CLOSED
    assert res_bad_env.reason == "ENVIRONMENT"


def test_c07_tautological_intent_derivation_risk():
    """Audit finding: If caller derives IntentSheet from grant, operator confirmation is bypassed."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas

    parsed = parse_grant(grant)
    reg = authenticate_registry(registry.raw, TOKENS)

    derived = _grant_derived_intent(parsed, reg)
    tautological_intent = IntentSheet(
        grant_class=derived["grant_class"],
        artifact_name=derived["artifact_name"],
        artifact_version=derived["artifact_version"],
        destination_name=derived["destination_name"],
        ceilings=tuple(derived["ceilings"]),
        sas=derived["sas"],
        target_role_name=derived["target_role_name"],
        counterpart_name=derived["counterpart_name"],
        sequence=tuple(derived["sequence"]),
    )

    res = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, tautological_intent, CHALLENGE, role, env,
        **binding
    )
    assert res.decision == CHECKS_PASSED

    assert res.payload["authority_usable"] is False
    assert res.payload["spending"] is False
    assert res.payload["training"] is False
    assert res.payload["gpu"] is False
    assert res.payload["corpus_generation"] == "NOT_AUTHORIZED"
    assert res.payload["qualification"] == "NOT_AUTHORIZED"


# ===========================================================================
# Gate 4: Combined Confirmation and Non-Authoritative Lockout
# ===========================================================================


def test_combined_confirm_and_authority_lockout():
    """Verify consumer_confirm_from_signed_bytes enforces strict non-authoritative boundary."""
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas

    res = consumer_confirm_from_signed_bytes(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent, CHALLENGE, role, env,
        **binding
    )
    assert res.decision == CHECKS_PASSED
    assert res.reason == "C06_C07_CONFIRMED"

    p = res.payload
    assert p["authority_usable"] is False
    assert p["spending"] is False
    assert p["training"] is False
    assert p["model_selection"] is False
    assert p["gpu"] is False
    assert p["provider"] is False
    assert p["executable"] is False
    assert p["corpus_generation"] == "NOT_AUTHORIZED"
    assert p["qualification"] == "NOT_AUTHORIZED"
    assert "G3" in p["unresolved_deps"]
    assert "training_authorization_absent" in p["unresolved_deps"]

