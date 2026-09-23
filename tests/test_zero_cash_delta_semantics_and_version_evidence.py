"""Phase 21B.4.15.2: Qwen3.8-27B preflight final closure -- zero-cash
delta-semantics hardening and vLLM version-evidence re-verification.

CPU/repository/docs/tests-only. No GPU, no inference, no model weights,
no paid frontier API.

Proves (per the phase spec's required test list, sections 11-12):
  D. Existing accepted zero/zero historical manifests still validate.
  E. Mistral's existing accepted manifest remains accepted.
  F. Qwen3.8-27B historical load-compatibility manifest remains accepted
     and its digest is unchanged.
  G. GLM remains financially rejected and is NOT upgraded.
  (version evidence) The current primary source was re-verified this
  phase and does NOT contain a "vLLM 0.17.0+" base-floor statement --
  the requested "correction" was not applied because it would have
  introduced a claim unsupported by the actual current primary source.
  This is recorded and tested explicitly so the discrepancy is never
  silently dropped.
"""

import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import CandidateExecutionRegistry
from orca.eval.runtime_qualification_manifest import load_manifest, validate_manifest, sha256_of_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
QWEN_MANIFEST_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_QWEN3_8_27B.json"
MISTRAL_MANIFEST_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_MISTRAL_SMALL_4_RETRY.json"
PRIMARY_SOURCES_PATH = REPO_ROOT / "docs/orneur/phase-21/evidence/QWEN3_8_27B_CURRENT_SERVING_PRIMARY_SOURCES_2026-09-23.json"

EXPECTED_QWEN_MANIFEST_DIGEST = "1d2093dc9af16c082a9e411ff4d27f114cc9596d46c6df3e5373792e60700feb"
EXPECTED_MISTRAL_MANIFEST_DIGEST = "c4d4b24788146240ca5f3e7ef6521417a0f55fcc3847db8009a141d7b1bff8af"


# ── D/F: Qwen3.8-27B historical zero/zero manifest still validates, digest unchanged ──


def test_qwen_historical_zero_zero_manifest_still_validates():
    manifest = load_manifest(QWEN_MANIFEST_PATH)
    assert manifest["billed_before_usd"] == 0
    assert manifest["billed_after_usd"] == 0
    validate_manifest(manifest)  # must not raise under the new delta-based rule


def test_qwen_historical_manifest_digest_unchanged():
    manifest = load_manifest(QWEN_MANIFEST_PATH)
    assert sha256_of_manifest(manifest) == EXPECTED_QWEN_MANIFEST_DIGEST


# ── D/E: Mistral historical zero/zero manifest still validates, digest unchanged ──


def test_mistral_historical_zero_zero_manifest_still_validates():
    manifest = load_manifest(MISTRAL_MANIFEST_PATH)
    assert manifest["billed_before_usd"] == 0
    assert manifest["billed_after_usd"] == 0
    validate_manifest(manifest)  # must not raise under the new delta-based rule


def test_mistral_historical_manifest_digest_unchanged():
    manifest = load_manifest(MISTRAL_MANIFEST_PATH)
    assert sha256_of_manifest(manifest) == EXPECTED_MISTRAL_MANIFEST_DIGEST


def test_mistral_registry_entry_remains_production_serving_qualified():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    entry = registry.find_deployable("Mistral Small 4")
    assert entry["production_serving_status"] == "QUALIFIED"
    assert entry["financial_acceptance_status"] == "ZERO_OWNER_CASH_PASSED"


# ── G: GLM remains financially rejected, not upgraded ───────────────────


def test_glm_remains_financially_rejected_not_upgraded():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    entry = registry.find_deployable("GLM-5.3-Flash")
    assert entry["production_serving_status"] == "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED"
    assert entry["financial_acceptance_status"] == "ZERO_OWNER_CASH_FAILED"
    assert entry["runtime_qualification_status"] == "UNQUALIFIED"
    assert entry.get("qualification_type") is None
    assert entry.get("qualification_manifest_path") is None


def test_glm_incident_evidence_preserves_exact_3_52_delta():
    technical_result_path = REPO_ROOT / "docs/orneur/phase-21/GLM_5_3_FLASH_TECHNICAL_RUNTIME_RESULT_2026-09-22.json"
    data = json.loads(technical_result_path.read_text())
    assert data["owner_billed_delta_usd"] == 3.52
    assert data["formal_runtime_qualification"] == "NOT_ACCEPTED"
    assert data["candidate_eliminated"] is False


def test_delta_semantics_do_not_retroactively_qualify_glm():
    """Sanity: the new delta-based billing rule must not be (mis)read as
    grounds to retroactively accept GLM's historical $3.52 run -- that
    run's OWN owner_billed_delta_usd was 3.52, nonzero, which still
    fails the (unweakened) owner_billed_delta_usd == 0 requirement
    regardless of what the account's billing baseline was before or
    after it."""
    from orca.eval.runtime_qualification_manifest import RuntimeQualificationManifestError
    from tests.test_runtime_qualification_manifest import _valid_manifest

    data = _valid_manifest()
    data["billed_before_usd"] = 0.0
    data["billed_after_usd"] = 3.52
    data["owner_billed_delta_usd"] = 3.52
    with pytest.raises(RuntimeQualificationManifestError, match="owner_billed_delta_usd must be exactly 0"):
        validate_manifest(data)


# ── Candidate states unchanged by this phase ─────────────────────────────


def test_qwen_candidate_state_unchanged():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    entry = registry.find_deployable("Qwen3.8-27B")
    assert entry["load_compatibility_status"] == "QUALIFIED"
    assert entry["production_serving_status"] == "NOT_TESTED"
    assert entry["financial_acceptance_status"] == "NOT_TESTED"
    assert entry["capability_status"] == "UNPROVEN"


def test_qwen_flash_next_state_unchanged():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    entry = registry.find_deployable("Qwen3.8-Flash-Next")
    assert entry["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert entry["runtime_smoke_eligibility"] == "BLOCKED"


def test_no_candidate_capability_upgraded():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    for entry in registry.deployable_candidates:
        assert entry["capability_status"] == "UNPROVEN"


# ── vLLM version evidence: re-verification result, NOT a fabricated correction ──


def test_vllm_base_version_floor_still_not_published_per_live_reverification():
    """Phase 21B.4.15.2 was asked to record a 'vLLM 0.17.0+' base-serving
    floor if the current primary source still states it. Live
    re-verification this phase (fetching https://recipes.vllm.ai/Qwen/
    Qwen3.8-27B fresh and searching its full text) found NO such
    statement anywhere on the page -- the Prerequisites section still
    lists only transformers>=5.8.0, and the only explicit vLLM version
    floor on the entire page remains the DFlash2-specific >=0.28.0
    figure. The requested correction is NOT applied because it would
    introduce a claim the primary source does not support. This is
    recorded explicitly rather than silently ignored."""
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    base = sources["dependency_and_version_facts"]["base_serving_version_guidance"]["vllm_base_minimum"]
    assert "NOT explicitly published" in base
    assert "0.17.0" not in base or "re-verified" in base.lower() or "Phase 21B.4.15.2" in base


def test_optional_dflash2_floor_still_separate_from_base():
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    optional = sources["dependency_and_version_facts"]["optional_feature_version_requirements"]
    assert "0.28.0" in optional["vllm_dflash2_speculative_path"]


def test_registry_still_loads_and_validates_end_to_end():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {c["canonical_candidate_name"] for c in registry.deployable_candidates}
    assert {"Qwen3.8-27B", "Qwen3.8-Flash-Next", "Mistral Small 4", "GLM-5.3-Flash"} == names
