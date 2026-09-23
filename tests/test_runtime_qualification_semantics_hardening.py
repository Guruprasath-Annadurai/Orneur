"""Phase 21B.4.15: Qwen3.8-27B runtime-qualification semantics hardening
and production-serving preflight.

CPU-only / documentation-only phase -- no GPU, no weight download, no
inference. Proves (per the phase spec's required test list, A-O):
  A. Qwen3.8-27B historical load qualification remains intact.
  B. Its historical qualification manifest digest is unchanged.
  C. Load compatibility and production-serving qualification are distinct.
  D. Qwen3.8-27B cannot be represented as production-serving-qualified
     without accepted production-serving evidence.
  E. Mistral Small 4 remains formally production-serving-runtime qualified.
  F. GLM-5.3-Flash remains NOT formally qualified (financial gate failed).
  G. Qwen3.8-Flash-Next remains license-blocked.
  H. No candidate's capability/frontier state is upgraded.
  I. Phase 21C remains unauthorized.
  J. No GPU allocation code is introduced for this phase.
  K. Serving evidence index hashes actual bytes exactly.
  L. Current serving source evidence is internally consistent.
  M. Future qualification spec requires owner_billed_delta_usd == 0.
  N. Future qualification spec requires network/API serving evidence.
  O. Legacy consumers either continue functioning correctly or fail with
     a clear migration error.
"""

import ast
import hashlib
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import (
    CandidateExecutionRegistry,
    RegistrySchemaError,
    REGISTRY_SCHEMA_VERSION,
    VALID_CAPABILITY_STATUSES,
    VALID_FINANCIAL_ACCEPTANCE_STATUSES,
    VALID_LOAD_COMPATIBILITY_STATUSES,
    VALID_PRODUCTION_SERVING_STATUSES,
    verify_candidate_qualification_end_to_end,
)
from orca.eval.runtime_qualification_manifest import load_manifest, sha256_of_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
QWEN_MANIFEST_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_QWEN3_8_27B.json"
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
PREFLIGHT_INDEX_PATH = EVIDENCE_DIR / "QWEN3_8_27B_SERVING_PREFLIGHT_SHA256_INDEX_2026-09-23.json"
PRIMARY_SOURCES_PATH = EVIDENCE_DIR / "QWEN3_8_27B_CURRENT_SERVING_PRIMARY_SOURCES_2026-09-23.json"
QUAL_SPEC_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_QWEN3_8_27B_PRODUCTION_SERVING_QUALIFICATION_SPEC_2026-09-23.md"
FRONTIER_GATES_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_DECISION_GATES.md"
SCRIPTS_DIR = REPO_ROOT / "scripts"

EXPECTED_QWEN_MANIFEST_DIGEST = "1d2093dc9af16c082a9e411ff4d27f114cc9596d46c6df3e5373792e60700feb"


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


# ── A/B: historical Qwen3.8-27B evidence untouched ─────────────────────


def test_qwen_historical_load_qualification_intact(registry):
    entry = registry.find_deployable("Qwen3.8-27B")
    assert entry["runtime_qualification_status"] == "QUALIFIED"
    assert entry["qualification_type"] == "RUNTIME_LOAD_COMPATIBILITY_QUALIFIED"
    assert entry["exact_immutable_revision"] == "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"


def test_qwen_historical_manifest_digest_unchanged(registry):
    entry = registry.find_deployable("Qwen3.8-27B")
    assert entry["qualification_manifest_digest_sha256"] == EXPECTED_QWEN_MANIFEST_DIGEST
    manifest = load_manifest(QWEN_MANIFEST_PATH)
    recomputed = sha256_of_manifest(manifest)
    assert recomputed == EXPECTED_QWEN_MANIFEST_DIGEST, (
        "the historical Qwen3.8-27B manifest's canonical digest must be byte-for-byte "
        "unchanged by this phase -- history must never be rewritten"
    )


# ── C/D: the core ambiguity this phase closes ──────────────────────────


def test_load_compatibility_and_production_serving_are_distinct_fields(registry):
    qwen = registry.find_deployable("Qwen3.8-27B")
    mistral = registry.find_deployable("Mistral Small 4")
    assert qwen["load_compatibility_status"] == "QUALIFIED"
    assert qwen["production_serving_status"] == "NOT_TESTED"
    assert mistral["load_compatibility_status"] == "QUALIFIED"
    assert mistral["production_serving_status"] == "QUALIFIED"
    # both achieve load compatibility but only Mistral achieves production serving --
    # proves the two dimensions genuinely vary independently, not just in theory
    assert qwen["production_serving_status"] != mistral["production_serving_status"]


def test_qwen_cannot_be_represented_as_production_serving_qualified(registry):
    """(D) The exact ambiguity this phase exists to close: a candidate with
    only RUNTIME_LOAD_COMPATIBILITY_QUALIFIED evidence must never be
    returned by the acceptance API as if it were production-serving
    qualified."""
    # legacy require_qualified=True still passes (backwards compatible --
    # some manifest-linked qualification exists)
    entry, manifest = verify_candidate_qualification_end_to_end(
        REGISTRY_PATH, "Qwen3.8-27B", require_qualified=True
    )
    assert manifest["qualification_type"] == "RUNTIME_LOAD_COMPATIBILITY_QUALIFIED"

    # but the NEW, stricter check correctly rejects it
    with pytest.raises(RegistrySchemaError, match="not production-serving qualified"):
        verify_candidate_qualification_end_to_end(
            REGISTRY_PATH, "Qwen3.8-27B", require_qualified=True, require_production_serving=True
        )


def test_mistral_passes_require_production_serving(registry):
    entry, manifest = verify_candidate_qualification_end_to_end(
        REGISTRY_PATH, "Mistral Small 4", require_qualified=True, require_production_serving=True
    )
    assert manifest["qualification_type"] == "PRODUCTION_SERVING_RUNTIME_QUALIFIED"


def test_production_serving_qualified_requires_matching_qualification_type():
    """Schema-level invariant: production_serving_status=QUALIFIED can
    never coexist with a qualification_type other than
    PRODUCTION_SERVING_RUNTIME_QUALIFIED."""
    data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    qwen["production_serving_status"] = "QUALIFIED"  # tamper: claim production serving
    # qualification_type is still RUNTIME_LOAD_COMPATIBILITY_QUALIFIED -- must reject
    with pytest.raises(RegistrySchemaError, match="production_serving_status=QUALIFIED"):
        CandidateExecutionRegistry.from_dict(data)


# ── E/F/G: other candidates unchanged in formal disposition ────────────


def test_mistral_remains_formally_production_serving_qualified(registry):
    entry = registry.find_deployable("Mistral Small 4")
    assert entry["runtime_qualification_status"] == "QUALIFIED"
    assert entry["qualification_type"] == "PRODUCTION_SERVING_RUNTIME_QUALIFIED"
    assert entry["production_serving_status"] == "QUALIFIED"
    assert entry["financial_acceptance_status"] == "ZERO_OWNER_CASH_PASSED"


def test_glm_remains_not_formally_qualified_financial_gate_failed(registry):
    entry = registry.find_deployable("GLM-5.3-Flash")
    assert entry["runtime_qualification_status"] == "UNQUALIFIED"
    assert entry["production_serving_status"] == "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED"
    assert entry["financial_acceptance_status"] == "ZERO_OWNER_CASH_FAILED"
    assert entry["runtime_smoke_eligibility"] == "ELIGIBLE"


def test_glm_cannot_simultaneously_claim_qualified_and_financial_failure():
    """Schema-level invariant: ZERO_OWNER_CASH_FAILED can never coexist
    with production_serving_status=QUALIFIED. Isolated from the (also
    independently enforced) qualification_type-match invariant by
    supplying otherwise-well-formed manifest-linkage fields, so this
    test proves specifically the financial cross-check fires."""
    data = json.loads(REGISTRY_PATH.read_text())
    glm = next(e for e in data["deployable_candidates"] if e["canonical_candidate_name"] == "GLM-5.3-Flash")
    glm["production_serving_status"] = "QUALIFIED"  # tamper
    glm["runtime_qualification_status"] = "QUALIFIED"
    glm["qualification_type"] = "PRODUCTION_SERVING_RUNTIME_QUALIFIED"
    glm["qualification_manifest_path"] = "docs/orneur/phase-21/GENESIS_RUNTIME_QUALIFICATION_MANIFEST_MISTRAL_SMALL_4_RETRY.json"
    glm["qualification_manifest_digest_sha256"] = "c4d4b24788146240ca5f3e7ef6521417a0f55fcc3847db8009a141d7b1bff8af"
    with pytest.raises(RegistrySchemaError, match="ZERO_OWNER_CASH_FAILED"):
        CandidateExecutionRegistry.from_dict(data)


def test_qwen_flash_next_remains_license_blocked(registry):
    entry = registry.find_deployable("Qwen3.8-Flash-Next")
    assert entry["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert entry["runtime_smoke_eligibility"] == "BLOCKED"
    assert entry["runtime_smoke_blocked_reason"] == "QWEN_COMMUNITY_LICENSE_COMMERCIAL_CLASSIFICATION_UNRESOLVED"


# ── H/I: no capability/frontier upgrade, Phase 21C still blocked ───────


def test_no_candidate_capability_status_upgraded(registry):
    for entry in registry.deployable_candidates:
        assert entry["capability_status"] == "UNPROVEN", (
            f"{entry['canonical_candidate_name']} has capability_status="
            f"{entry['capability_status']!r} -- no candidate may be upgraded beyond "
            "UNPROVEN by a license/schema/preflight phase"
        )


def test_frontier_lock_and_phase_21c_unauthorized_wording_present():
    text = FRONTIER_GATES_PATH.read_text()
    assert "GENESIS FOUNDATION:" in text and "NOT YET SELECTED" in text
    assert "GENESIS FRONTIER STATUS:" in text and "UNPROVEN" in text
    assert "NO FOUNDATION HAS YET EARNED GENESIS SELECTION." in text


# ── J: no GPU allocation code introduced ────────────────────────────────


def test_candidate_registry_module_introduces_no_gpu_code():
    tree = ast.parse((REPO_ROOT / "orca/eval/candidate_registry.py").read_text())
    gpu_kwargs = [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "gpu"]
    assert gpu_kwargs == []


def test_no_new_gpu_allocating_script_this_phase():
    for py_file in SCRIPTS_DIR.glob("*.py"):
        tree = ast.parse(py_file.read_text(errors="replace"))
        gpu_kwargs = [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "gpu"]
        # any script requesting gpu= must be pre-existing, historical, and
        # already-archived-pattern code -- none should exist for Qwen3.8-27B
        assert "qwen3_8_27b" not in py_file.name.lower() or gpu_kwargs == []


# ── K/L: serving evidence integrity ─────────────────────────────────────


def test_serving_preflight_sha256_index_hashes_exactly():
    index = json.loads(PREFLIGHT_INDEX_PATH.read_text())
    entries = index["entries"]
    assert len(entries) == 8  # 5 original + 2 Phase 21B.4.15.1 CPU preflight + 1 Phase 21B.4.15.3 structured recipe source
    for entry in entries:
        path = REPO_ROOT / entry["path"]
        assert path.is_file(), f"missing: {entry['path']}"
        actual_bytes = path.read_bytes()
        actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()
        assert actual_sha256 == entry["sha256"]
        assert len(actual_bytes) == entry["size_bytes"]


def test_primary_sources_identity_reverification_matches_registry(registry):
    """(L) The primary-source research's own identity reverification must
    agree with the registry's recorded identity -- internal consistency,
    not just internal-to-itself validity."""
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    qwen = registry.find_deployable("Qwen3.8-27B")
    reverify = sources["identity_reverification"]
    assert reverify["matches_pinned_revision"] is True
    assert reverify["hf_api_current_main_sha"] == qwen["exact_immutable_revision"]
    assert reverify["config_architectures"] == [qwen["architecture"]]


# ── M/N: future qualification spec content requirements ────────────────


def test_future_qualification_spec_requires_zero_owner_billed_delta():
    text = QUAL_SPEC_PATH.read_text()
    assert "owner_billed_delta_usd == 0" in text


def test_future_qualification_spec_requires_network_api_serving_evidence():
    text = QUAL_SPEC_PATH.read_text()
    assert "GET /v1/models" in text
    assert "POST /v1/chat/completions" in text
    assert "HTTP 200" in text


def test_future_qualification_spec_excludes_capability_benchmarks():
    text = QUAL_SPEC_PATH.read_text()
    assert "No coding benchmark" in text
    assert "No untrusted generated" in text


# ── O: legacy consumer / migration behavior ─────────────────────────────


def test_schema_version_bumped_and_enforced():
    assert REGISTRY_SCHEMA_VERSION == "genesis-candidate-execution-registry-v5"  # bumped again in Phase 21B.4.17
    data = json.loads(REGISTRY_PATH.read_text())
    assert data["schema_version"] == REGISTRY_SCHEMA_VERSION


def test_old_schema_version_rejected_with_clear_migration_error():
    data = json.loads(REGISTRY_PATH.read_text())
    data["schema_version"] = "genesis-candidate-execution-registry-v2"
    with pytest.raises(RegistrySchemaError, match="Unsupported registry schema_version"):
        CandidateExecutionRegistry.from_dict(data)


def test_entry_missing_new_dimension_fields_fails_with_clear_error():
    """A legacy-shaped deployable entry (missing the new v3 fields)
    fails closed with a clear missing-field error, not a silent pass or
    a confusing unrelated exception."""
    data = json.loads(REGISTRY_PATH.read_text())
    qwen = next(e for e in data["deployable_candidates"] if e["canonical_candidate_name"] == "Qwen3.8-27B")
    del qwen["production_serving_status"]
    with pytest.raises(RegistrySchemaError, match="missing required field"):
        CandidateExecutionRegistry.from_dict(data)


def test_legacy_runtime_qualification_status_field_still_functions(registry):
    """runtime_qualification_status is RETAINED (not removed) -- existing
    callers relying on it as a manifest-linkage-exists flag must keep
    working unchanged."""
    for entry in registry.deployable_candidates:
        assert entry["runtime_qualification_status"] in ("QUALIFIED", "UNQUALIFIED")


def test_all_four_new_enums_exported_and_populated():
    for status_set in (
        VALID_LOAD_COMPATIBILITY_STATUSES,
        VALID_PRODUCTION_SERVING_STATUSES,
        VALID_FINANCIAL_ACCEPTANCE_STATUSES,
        VALID_CAPABILITY_STATUSES,
    ):
        assert isinstance(status_set, tuple) and len(status_set) >= 3


def test_registry_still_loads_and_validates_end_to_end():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {c["canonical_candidate_name"] for c in registry.deployable_candidates}
    assert {"Qwen3.8-27B", "Qwen3.8-Flash-Next", "Mistral Small 4", "GLM-5.3-Flash"} == names
