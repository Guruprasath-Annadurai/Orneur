"""
MASTER-02 portable re-execution harness for FOUNDATION-03 C06/C07 qualification.

Purpose
-------
The original Antigravity suite at commit 75a7a648984d9883774292f35a511089e6ffd474
hardcodes ``/home/pc/projects/Orneur-pr142-f03`` and asserts HEAD == engineering
SHA ``0fe98e04…``. That lineage gate is intentionally **not** true on a multi-PR
integration tip. This harness:

1. Does **not** rewrite the original audit evidence (verbatim copy lives under
   ``docs/orneur/milestones/master-02/evidence/antigravity-original/``).
2. Rebinds the worktree via ``ORNEUR_AUDIT_WORKTREE`` (default: repo root).
3. Re-checks that the original engineering SHA is an **ancestor** of HEAD and
   that ``orca/rse/imp1/consumer_verification.py`` blob matches ``0fe98e04…``.
4. Re-executes the software adversarial C06/C07 body against the integrated tree.

This is **engineering re-execution on the integrated tip**, not a substitute for
independent Antigravity OWN_EVIDENCE / formal acceptance.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from orca.rse.imp1.authority import (
    IntentSheet,
    authenticate_registry,
    crown_validate,
    grant_sas,
    render_card,  # noqa: F401 — parity with original imports
)
from orca.rse.imp1.codec import parse_grant
from orca.rse.imp1.consumer_verification import (
    C06_CARD_DOMAIN,
    consumer_confirm_from_signed_bytes,
    render_from_signed_bytes,
    verify_typed_sas_and_intent,
    _grant_derived_intent,
)
from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED
from tests.rse.support import (
    CHALLENGE,
    FLOORS,
    TOKENS,
    consumer_args,
    consumer_binding,
    g_grant,
    g_intent,
    simple_g,
)

ORIGINAL_AUDIT_SHA = "75a7a648984d9883774292f35a511089e6ffd474"
ENGINEERING_SHA = "0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51"
PARENT_SHA = "649d90f84069fc618ba4d69b4c26a66bed731caa"
CONSUMER_PATH = "orca/rse/imp1/consumer_verification.py"


def _worktree() -> Path:
    env = os.environ.get("ORNEUR_AUDIT_WORKTREE")
    if env:
        return Path(env).resolve()
    # tests/qualification/ -> repo root
    return Path(__file__).resolve().parents[2]


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd or _worktree()), text=True
    ).strip()


# ---------------------------------------------------------------------------
# Gate A: integrated-tip lineage (portable substitute for hardcoded worktree)
# ---------------------------------------------------------------------------


def test_portable_worktree_resolves():
    wt = _worktree()
    assert wt.is_dir(), f"Worktree missing: {wt}"
    assert (wt / "orca" / "rse" / "imp1" / "consumer_verification.py").is_file()


def test_engineering_sha_is_ancestor_of_integrated_head():
    wt = _worktree()
    head = _git("rev-parse", "HEAD", cwd=wt)
    assert head != ENGINEERING_SHA, (
        "Integrated tip unexpectedly equals lone F03 engineering SHA; "
        "MASTER-02 tip must be a multi-PR merge commit."
    )
    rc = subprocess.call(
        ["git", "merge-base", "--is-ancestor", ENGINEERING_SHA, head],
        cwd=str(wt),
    )
    assert rc == 0, f"{ENGINEERING_SHA} is not an ancestor of integrated HEAD {head}"


def test_parent_and_engineering_blob_identity_preserved():
    """consumer_verification.py blob at HEAD must match engineering SHA blob."""
    wt = _worktree()
    tip_blob = _git("rev-parse", f"HEAD:{CONSUMER_PATH}", cwd=wt)
    eng_blob = _git("rev-parse", f"{ENGINEERING_SHA}:{CONSUMER_PATH}", cwd=wt)
    assert tip_blob == eng_blob, (
        f"consumer_verification.py diverged from engineering SHA: "
        f"tip={tip_blob} eng={eng_blob}"
    )
    # Parent→engineering file set remains the F03 code delta (docs may exist later).
    code_diff = _git(
        "diff", "--name-only", PARENT_SHA, ENGINEERING_SHA, "--",
        "orca/rse/imp1/consumer_verification.py",
        "tests/rse/test_c06_c07_consumer_verification.py",
        cwd=wt,
    ).splitlines()
    assert set(code_diff) == {
        "orca/rse/imp1/consumer_verification.py",
        "tests/rse/test_c06_c07_consumer_verification.py",
    }


def test_formal_acceptance_still_zero_on_integrated_tip():
    wt = _worktree()
    res = subprocess.check_output(
        ["python3", "scripts/acceptance/validate_register_graph.py", "--check"],
        cwd=str(wt),
        text=True,
    ).strip()
    assert "pretraining=95 numerator=0" in res, f"Formal acceptance not 0/95: {res}"


def test_original_audit_suite_preserved_verbatim_in_evidence():
    """Ensure MASTER-02 did not silently edit the archived original suite."""
    wt = _worktree()
    archived = (
        wt
        / "docs/orneur/milestones/master-02/evidence/antigravity-original"
        / "test_foundation03_c06_c07_qualification.py"
    )
    assert archived.is_file(), "Original suite archive missing"
    archived_bytes = archived.read_bytes()
    archived_text = archived_bytes.decode("utf-8")
    assert "/home/pc/projects/Orneur-pr142-f03" in archived_text
    assert "0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51" in archived_text
    # Byte-compare against original commit (do not strip — trailing newline is meaningful).
    try:
        original = subprocess.check_output(
            [
                "git",
                "show",
                f"{ORIGINAL_AUDIT_SHA}:tests/qualification/"
                "test_foundation03_c06_c07_qualification.py",
            ],
            cwd=str(wt),
        )
    except subprocess.CalledProcessError:
        pytest.skip(f"Original audit commit {ORIGINAL_AUDIT_SHA} not fetchable")
    assert archived_bytes == original, "Archived suite diverged from original audit commit"


# ---------------------------------------------------------------------------
# Gate B: C06 adversarial body (software scope) on integrated tree
# ---------------------------------------------------------------------------


def test_c06_adversarial_crown_b1_b2_substitution():
    registry, parts, grant_b2 = simple_g()
    image = parts["image"].entry_id
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
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    tampered = bytearray(grant)
    tampered[35] ^= 0x01
    assert render_from_signed_bytes(
        bytes(tampered), registry.raw, TOKENS, FLOORS, image
    ).decision == FAIL_CLOSED
    trailing = grant + b"\x00"
    res_trailing = render_from_signed_bytes(trailing, registry.raw, TOKENS, FLOORS, image)
    assert res_trailing.decision == FAIL_CLOSED
    assert res_trailing.reason in {"RAW_MISMATCH", "UNEXPECTED", "GRANT_LEN"}
    truncated = grant[:20]
    assert render_from_signed_bytes(
        truncated, registry.raw, TOKENS, FLOORS, image
    ).decision == FAIL_CLOSED


def test_c06_cryptographic_evidence_binding():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    res = render_from_signed_bytes(grant, registry.raw, TOKENS, FLOORS, image)
    assert res.decision == CHECKS_PASSED
    card = res.payload["card"]
    binding = res.payload["rendered_card_evidence"]["binding_digest"]
    expected_material = C06_CARD_DOMAIN + b"\x00" + grant + b"\x00" + card.encode("utf-8")
    assert binding == hashlib.sha256(expected_material).hexdigest()
    tampered_card = card + " "
    tampered_material = (
        C06_CARD_DOMAIN + b"\x00" + grant + b"\x00" + tampered_card.encode("utf-8")
    )
    assert hashlib.sha256(tampered_material).hexdigest() != binding


def test_c06_scope_is_in_memory_formatting_only():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    res = render_from_signed_bytes(grant, registry.raw, TOKENS, FLOORS, image)
    assert res.decision == CHECKS_PASSED
    assert isinstance(res.payload["card"], str)
    assert "GRANT SAS" in res.payload["card"]
    assert res.payload["authority_usable"] is False


# ---------------------------------------------------------------------------
# Gate C: C07 adversarial body on integrated tree
# ---------------------------------------------------------------------------


def test_c07_adversarial_sas_unicode_and_confusable_homoglyphs():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas
    assert verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent, CHALLENGE, role, env,
        **binding,
    ).decision == CHECKS_PASSED
    confusable_sas = sas.replace("A", "\u0410")
    if confusable_sas != sas:
        res = verify_typed_sas_and_intent(
            grant, registry.raw, TOKENS, FLOORS, image, confusable_sas, intent,
            CHALLENGE, role, env, **binding,
        )
        assert res.decision == FAIL_CLOSED
        assert res.reason == "SAS_UNICODE"
    res_lower = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas.lower(), intent,
        CHALLENGE, role, env, **binding,
    )
    assert res_lower.decision == FAIL_CLOSED
    assert res_lower.reason == "SAS_ALPHABET"
    res_padded = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, " " + sas + " ", intent,
        CHALLENGE, role, env, **binding,
    )
    assert res_padded.decision == FAIL_CLOSED
    assert res_padded.reason == "SAS_FORM"
    res_colon = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas.replace("-", ":"), intent,
        CHALLENGE, role, env, **binding,
    )
    assert res_colon.decision == FAIL_CLOSED
    assert res_colon.reason == "SAS_FORM"


def test_c07_sas_60bit_entropy_guarantee():
    registry, parts, grant = simple_g()
    intent = g_intent(registry, grant, parts)
    parsed = parse_grant(grant)
    computed_sas = grant_sas(parsed.klass, parsed.signed)
    assert computed_sas == intent.sas
    segments = computed_sas.split("-")
    assert len(segments) == 3
    assert all(len(p) == 4 for p in segments)
    assert len("".join(segments)) == 12


def test_c07_adversarial_intent_sheet_tampering():
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
        grant, registry.raw, TOKENS, FLOORS, image, sas, bad_artifact,
        CHALLENGE, role, env, **binding,
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
        grant, registry.raw, TOKENS, FLOORS, image, sas, bad_ceilings,
        CHALLENGE, role, env, **binding,
    )
    assert res_bad_ceil.decision == FAIL_CLOSED
    assert res_bad_ceil.reason == "INTENT_CEILINGS"


def test_c07_stale_and_voided_challenge_replay():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas
    ledger = binding["challenge_ledger"]
    ledger.void_challenge(CHALLENGE)
    assert ledger.is_void(CHALLENGE)
    res_void = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent,
        CHALLENGE, role, env, **binding,
    )
    assert res_void.decision == FAIL_CLOSED
    assert res_void.reason == "CHALLENGE_VOID"
    fresh_binding = consumer_binding(registry)
    res_bad_env = verify_typed_sas_and_intent(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent,
        CHALLENGE, role, b"X" * 32, **fresh_binding,
    )
    assert res_bad_env.decision == FAIL_CLOSED
    assert res_bad_env.reason == "ENVIRONMENT"


def test_c07_tautological_intent_derivation_risk():
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
        grant, registry.raw, TOKENS, FLOORS, image, sas, tautological_intent,
        CHALLENGE, role, env, **binding,
    )
    assert res.decision == CHECKS_PASSED
    assert res.payload["authority_usable"] is False
    assert res.payload["spending"] is False
    assert res.payload["training"] is False
    assert res.payload["gpu"] is False
    assert res.payload["corpus_generation"] == "NOT_AUTHORIZED"
    assert res.payload["qualification"] == "NOT_AUTHORIZED"


def test_combined_confirm_and_authority_lockout():
    registry, parts, grant = simple_g()
    image = parts["image"].entry_id
    intent = g_intent(registry, grant, parts)
    role, env = consumer_args(parts)
    binding = consumer_binding(registry)
    sas = intent.sas
    res = consumer_confirm_from_signed_bytes(
        grant, registry.raw, TOKENS, FLOORS, image, sas, intent,
        CHALLENGE, role, env, **binding,
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
