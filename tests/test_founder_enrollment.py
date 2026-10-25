"""Founder enrollment is prepared and is not operational authority.

Synthetic keys exist only inside this process. A cryptographic accept does
not change the governance test and does not authorize training.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from orca.founder_enrollment import (
    AWAITING,
    BASELINE,
    ENROLL_DOMAIN,
    OPERATIONAL_OBSERVATION_SHA256,
    PROPOSAL_SHA256,
    SCHEMA_ENROLLMENT,
    SCHEMA_LOSS,
    SCHEMA_REVOCATION,
    SCHEMA_REVOCATION_LIST,
    SCOPE,
    accept_presented_public_key,
    establish,
    fingerprint_of,
    founder_signing_bytes,
    future_exception_applies,
    gate_problems,
    load_operational_anchor,
    loss_signing_bytes,
    observation_of,
    observation_sha256,
    review_approval_binding,
    review_enrollment,
    review_loss,
    review_rotation,
    revocation_signing_bytes,
    witness_signing_bytes,
)
from orca.freeze_amendment import (
    DECISION,
    PERMITTED,
    SCHEMA_APPROVAL,
    TRUST_ROOT_CODE_SHA256,
    UNCHANGED_PATHS,
    assess_approvals,
    canonical_approval_bytes,
    classify_diff,
    evaluate,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
CHANNEL = "https://github.com/Guruprasath-Annadurai/Orneur/commit/abc1234def5"


def _private():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


def _public(private) -> bytes:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _enrollment(founder, witness, **overrides):
    founder_public = _public(founder)
    witness_public = _public(witness)
    provenance = {
        "channel": "founder-controlled-git-commit",
        "channel_uri": CHANNEL,
        "observation_sha256": "11" * 32,
    }
    witness_body = {
        "identity": "synthetic-witness",
        "key_id": "synthetic-witness-key",
        "public_key_hex": witness_public.hex(),
        "signature": "22" * 64,
    }
    document = {
        "schema_version": SCHEMA_ENROLLMENT,
        "identity": "synthetic-founder",
        "key_id": "synthetic-founder-key",
        "public_key_hex": founder_public.hex(),
        "fingerprint_sha256": fingerprint_of(founder_public),
        "scope": SCOPE,
        "enrolled_at": "2026-10-01T00:00:00Z",
        "expires_at": "2027-10-01T00:00:00Z",
        "provenance": provenance,
        "founder_signature": "33" * 64,
        "witness": witness_body,
    }
    for key, value in overrides.items():
        if key == "provenance":
            document["provenance"].update(value)
        elif key == "witness":
            document["witness"].update(value)
        else:
            document[key] = value
    document["provenance"]["observation_sha256"] = observation_sha256(document)
    document["founder_signature"] = founder.sign(founder_signing_bytes(document)).hex()
    document["witness"]["signature"] = witness.sign(witness_signing_bytes(document)).hex()
    return document


def _approval(signer, enrollment, founder_claim=None, **overrides):
    document = {
        "schema_version": SCHEMA_APPROVAL,
        "proposal_sha256": PROPOSAL_SHA256,
        "baseline": BASELINE,
        "decision": DECISION,
        "paths": [{"path": path, "sha256": digest} for path, digest in PERMITTED],
        "founder": founder_claim or {"identity": enrollment["identity"], "key_id": enrollment["key_id"]},
        "signature": "44" * 64,
    }
    document.update(overrides)
    document["signature"] = signer.sign(canonical_approval_bytes(document)).hex()
    return document


def _revocation(founder, enrollment, when="2026-10-20T00:00:00Z"):
    item = {
        "schema_version": SCHEMA_REVOCATION,
        "identity": enrollment["identity"],
        "key_id": enrollment["key_id"],
        "fingerprint_sha256": enrollment["fingerprint_sha256"],
        "revoked_at": when,
        "signature": "55" * 64,
    }
    item["signature"] = founder.sign(revocation_signing_bytes(item)).hex()
    return item


def _clean_diff(**overrides):
    payload = {
        "baseline_present": True,
        "introducing_present": True,
        "entries": [("A", path) for path, _digest in PERMITTED],
        "digests": {path: digest for path, digest in PERMITTED},
        "historical_digests": {path: digest for path, digest in PERMITTED},
        "unchanged": {path: ("same", "same") for path in UNCHANGED_PATHS},
        "trust_code_sha256": TRUST_ROOT_CODE_SHA256,
    }
    payload.update(overrides)
    return payload


def test_operational_anchor_is_absent_and_live_tree_is_not_enrolled():
    assert OPERATIONAL_OBSERVATION_SHA256 is None
    assert load_operational_anchor()["established"] is False
    review = establish(ROOT, now=NOW)
    assert review.status == AWAITING
    assert review.reason == "enrollment_absent"
    assert review.operational_authority is False
    assert review.governance_exception_active is False
    assert review.cryptographic_accept is False
    verdict = evaluate(ROOT)
    assert verdict.activated is False
    assert verdict.status == "AWAITING_FOUNDER_SIGNED_APPROVAL"


def test_presented_key_and_empty_registry_are_refused():
    assert accept_presented_public_key(b"\x01" * 32) == "caller_supplied_key_refused"
    assert accept_presented_public_key({"records": [], "public_key_hex": "ab" * 32}) == "caller_supplied_key_refused"
    assert accept_presented_public_key(None) == "independent_anchor_absent"


def test_synthetic_enrollment_verifies_and_does_not_open_the_gate():
    founder, witness = _private(), _private()
    document = _enrollment(founder, witness)
    review = review_enrollment(document, now=NOW, synthetic_context=True)
    assert review.cryptographic_accept is True
    assert review.signature_checked is True
    assert review.synthetic is True
    assert review.operational_authority is False
    assert review.governance_exception_active is False
    assert review.reason == "independent_anchor_absent"
    assert observation_of(document)["proposal_sha256"] == PROPOSAL_SHA256
    assert observation_of(document)["baseline"] == BASELINE
    assert observation_of(document)["scope"] == SCOPE
    problems = gate_problems(review)
    assert problems[0] == "synthetic_key_refused"
    assert future_exception_applies((), (), problems) is False
    assert future_exception_applies((), (), ()) is False


def test_same_key_cannot_witness_itself_and_production_refuses_synthetic_names():
    founder = _private()
    document = _enrollment(founder, founder)
    review = review_enrollment(document, now=NOW, synthetic_context=True)
    assert review.reason == "witness_not_independent"
    assert review.cryptographic_accept is False
    produced = review_enrollment(document, now=NOW, synthetic_context=False)
    assert produced.reason == "synthetic_key_refused"
    assert future_exception_applies((), (), produced.reasons) is False


def test_synthetic_context_refuses_a_non_synthetic_identity():
    founder, witness = _private(), _private()
    document = _enrollment(founder, witness, identity="founder.example")
    review = review_enrollment(document, now=NOW, synthetic_context=True)
    assert review.reason == "synthetic_context_refused"
    assert review.operational_authority is False


def test_scope_provenance_channel_and_foreign_domain_are_rejected():
    founder, witness = _private(), _private()
    widened = _enrollment(founder, witness, scope="native-pretraining")
    assert review_enrollment(widened, now=NOW, synthetic_context=True).reason == "scope_rejected"
    rebound = _enrollment(founder, witness)
    rebound["provenance"]["observation_sha256"] = "ab" * 32
    assert review_enrollment(rebound, now=NOW, synthetic_context=True).reason == "provenance_not_bound"
    agent_channel = _enrollment(founder, witness, provenance={"channel_uri": "https://github.com/Guruprasath-Annadurai/Orneur/commit/cursoragent1"})
    assert review_enrollment(agent_channel, now=NOW, synthetic_context=True).reason == "channel_rejected"
    foreign = _enrollment(founder, witness)
    foreign["founder_signature"] = founder.sign(b"orneur-training-authorization/1\n" + founder_signing_bytes(foreign)[len(ENROLL_DOMAIN):]).hex()
    assert review_enrollment(foreign, now=NOW, synthetic_context=True).reason == "signature_invalid"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda document: document.update(expires_at="2026-10-20T00:00:00Z"), "stale_enrollment"),
        (lambda document: document.update(enrolled_at="2026-12-01T00:00:00Z"), "enrollment_not_yet_valid"),
        (lambda document: document.update(expires_at="2028-01-01T00:00:00Z"), "validity_window_rejected"),
    ],
)
def test_time_bounds_reject_before_the_gate(mutate, reason):
    founder, witness = _private(), _private()
    document = _enrollment(founder, witness)
    mutate(document)
    document["provenance"]["observation_sha256"] = observation_sha256(document)
    document["founder_signature"] = founder.sign(founder_signing_bytes(document)).hex()
    document["witness"]["signature"] = witness.sign(witness_signing_bytes(document)).hex()
    review = review_enrollment(document, now=NOW, synthetic_context=True)
    assert review.reason == reason
    assert review.governance_exception_active is False


def test_revocation_and_bad_revocation_fail_closed():
    founder, witness = _private(), _private()
    document = _enrollment(founder, witness)
    revoked = review_enrollment(document, (_revocation(founder, document),), now=NOW, synthetic_context=True)
    assert revoked.reason == "key_revoked"
    assert revoked.cryptographic_accept is False
    bad = _revocation(founder, document)
    bad["signature"] = ("00" + bad["signature"][2:])
    assert review_enrollment(document, (bad,), now=NOW, synthetic_context=True).reason == "revocation_invalid"


def test_approval_binds_the_enrolled_key_and_rejects_mismatch_forgery_and_replay():
    founder, witness, other = _private(), _private(), _private()
    document = _enrollment(founder, witness)
    review = review_enrollment(document, now=NOW, synthetic_context=True)
    approval = _approval(founder, document)
    assert review_approval_binding(approval, document, review) == ()
    assert future_exception_applies((), (), gate_problems(review)) is False
    mismatched = _approval(founder, document, founder_claim={"identity": "synthetic-other", "key_id": document["key_id"]})
    assert review_approval_binding(mismatched, document, review) == ("identity_mismatch",)
    unknown = _approval(other, document, founder_claim={"identity": document["identity"], "key_id": "synthetic-unknown"})
    assert review_approval_binding(unknown, document, review) == ("unknown_key",)
    forged = _approval(founder, document)
    forged["signature"] = ("00" + forged["signature"][2:])
    assert review_approval_binding(forged, document, review) == ("signature_invalid",)
    replayed = _approval(founder, document, proposal_sha256="22" * 32)
    assert review_approval_binding(replayed, document, review) == ("proposal_not_bound",)
    duplicate = assess_approvals([approval, approval])
    assert duplicate == ("duplicate_approvals",)
    assert future_exception_applies((), duplicate, ()) is False


def test_loss_and_rotation_do_not_enroll_a_replacement():
    founder, witness = _private(), _private()
    enrolled = _enrollment(founder, witness)
    loss = {
        "schema_version": SCHEMA_LOSS,
        "lost_key_id": enrolled["key_id"],
        "lost_fingerprint_sha256": enrolled["fingerprint_sha256"],
        "attested_at": "2026-10-24T00:00:00Z",
        "witness": {
            "identity": "synthetic-witness",
            "key_id": "synthetic-witness-key",
            "public_key_hex": enrolled["witness"]["public_key_hex"],
            "signature": "66" * 64,
        },
    }
    loss["witness"]["signature"] = witness.sign(loss_signing_bytes(loss)).hex()
    recorded = review_loss(loss, now=NOW)
    assert recorded.reason == "recovery_requires_new_enrollment"
    assert recorded.signature_ok is True
    assert recorded.operational_authority is False
    assert recorded.governance_exception_active is False
    loss["replacement_public_key_hex"] = "ab" * 32
    assert review_loss(loss, now=NOW).reason == "recovery_cannot_bind_replacement"
    assert review_rotation({"scope": "native-pretraining", "activates": True}) == "rotation_cannot_activate"
    assert review_rotation({"previous_key_id": enrolled["key_id"]}) == "rotation_requires_new_enrollment"


def test_enrollment_store_refuses_symlinks_and_a_valid_file_stays_inactive(tmp_path):
    import json

    founder, witness = _private(), _private()
    directory = tmp_path / "docs" / "orneur" / "cursor" / "founder_enrollment"
    directory.mkdir(parents=True)
    target = tmp_path / "elsewhere.json"
    target.write_text("{}", encoding="utf-8")
    (directory / "enrollment.json").symlink_to(target)
    assert establish(tmp_path, now=NOW).reason == "enrollment_store_refused"
    (directory / "enrollment.json").unlink()
    document = _enrollment(founder, witness, identity="founder.example")
    (directory / "enrollment.json").write_text(json.dumps(document), encoding="utf-8")
    (directory / "revocations.json").write_text(
        json.dumps({"schema_version": SCHEMA_REVOCATION_LIST, "records": []}),
        encoding="utf-8",
    )
    stored = establish(tmp_path, now=NOW)
    assert stored.cryptographic_accept is True
    assert stored.operational_authority is False
    assert stored.governance_exception_active is False
    assert stored.reason == "independent_anchor_absent"


def test_substituted_anchor_cannot_apply_the_exception(monkeypatch):
    monkeypatch.setattr(
        "orca.founder_enrollment.load_operational_anchor",
        lambda: {"established": True, "observation_sha256": "ab" * 32, "reason": None},
    )
    assert future_exception_applies((), (), ()) is False
    assert establish(ROOT, now=NOW).reason == "caller_supplied_anchor_refused"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda payload: payload["entries"].append(("A", "docs/orneur/authorization/EXTRA.json")), "unauthorized_path"),
        (lambda payload: payload.update(digests={**payload["digests"], PERMITTED[0][0]: "00" * 32}), "permitted_bytes_modified"),
        (lambda payload: payload["entries"].append(("D", "docs/orneur/phase-21/rse/gone.json")), "frozen_deletion"),
        (lambda payload: payload["entries"].append(("M", "docs/orneur/acceptance/acceptance_ledger.json")), "acceptance_ledger_changed"),
        (lambda payload: payload["entries"].append(("M", "orca/train/authorization.py")), "training_authorization_changed"),
        (lambda payload: payload.update(trust_code_sha256="ff" * 32), "trust_root_changed"),
        (lambda payload: payload.update(baseline_present=False), "missing_historical_commit"),
    ],
)
def test_prepared_gate_rejects_frozen_diff_defects(mutate, reason):
    payload = _clean_diff()
    mutate(payload)
    reasons = classify_diff(**payload)
    assert reasons[0] == reason
    assert future_exception_applies(reasons, (), ()) is False


def test_live_diff_is_the_three_files_and_the_governance_test_is_unwired():
    reasons = classify_diff(**_clean_diff())
    assert reasons == ()
    observed = classify_diff(
        baseline_present=True,
        introducing_present=True,
        entries=[("A", path) for path, _digest in PERMITTED],
        digests={path: digest for path, digest in PERMITTED},
        historical_digests={path: digest for path, digest in PERMITTED},
        unchanged={path: ("same", "same") for path in UNCHANGED_PATHS},
        trust_code_sha256=TRUST_ROOT_CODE_SHA256,
    )
    assert observed == ()
    source = (ROOT / "tests" / "test_evalinfra_governance.py").read_text(encoding="utf-8")
    assert "founder_enrollment" not in source
    assert "future_exception_applies" not in source
    assert 'out.stdout.strip() == ""' in source
    assert "pytest.skip" not in source[source.index("def test_no_frozen_or_private_path_differs_from_the_branch_point"):]
    module = (ROOT / "orca" / "founder_enrollment.py").read_text(encoding="utf-8")
    assert "OPERATIONAL_OBSERVATION_SHA256: str | None = None" in module
    assert "operational_authority=True" not in module
    assert "governance_exception_active=True" not in module


def test_procedure_documents_keep_the_key_off_the_agent_and_name_the_pins():
    enrollment = (ROOT / "docs/orneur/cursor/FOUNDER_AUTHORITY_ENROLLMENT.md").read_text(encoding="utf-8")
    activation = (ROOT / "docs/orneur/cursor/FREEZE_ACTIVATION_PREPARATION.md").read_text(encoding="utf-8")
    handover = (ROOT / "docs/orneur/cursor/FOUNDER_BOOTSTRAP_HANDOFF.md").read_text(encoding="utf-8")
    for text in (enrollment, activation, handover):
        assert PROPOSAL_SHA256 in text
        assert BASELINE in text
        for path, digest in PERMITTED:
            assert path in text and digest in text
    assert "outside the repository" in enrollment
    assert "Do not generate the key" in enrollment
    assert "revocation" in enrollment.casefold()
    assert "rotation" in enrollment.casefold()
    assert "recovery" in enrollment.casefold()
    assert "NOT_ACTIVATED" in activation
    assert "test_no_frozen_or_private_path_differs_from_the_branch_point" in activation
    assert "AWAITING_INDEPENDENT_ENROLLMENT" in handover
