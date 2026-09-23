"""Phase 21B.4.15.1: Qwen3.8-27B serving-evidence reconciliation and
zero-cash documentation correction.

CPU/docs/tests-only corrective phase -- no GPU, no inference, no model
weights, no paid API. Proves (per the phase spec's required test list):
  A. Qwen runtime-state dimensions remain unchanged.
  B. Mistral formal production-serving status remains unchanged.
  C. GLM financial-failure state remains unchanged.
  D. Qwen3.8-Flash-Next remains license blocked.
  E. zero-cash control spec does NOT assert unverified Modal internal
     billing semantics as established fact.
  F. zero-cash control still requires owner_billed_delta_usd == 0.
  G. SGLang evidence records the official Qwen3.8-27B command/cookbook
     if current primary source still contains it.
  H. evidence no longer claims SGLang parser flags are unknown when
     current primary evidence establishes them.
  I. tool-parser source divergence is recorded.
  J. optional-feature version floors are not represented as base-serving
     floors.
  K. SHA-256 index matches actual final bytes.
  L. no GPU allocation/inference/model-download code is introduced.
"""

import ast
import hashlib
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import CandidateExecutionRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
PRIMARY_SOURCES_PATH = EVIDENCE_DIR / "QWEN3_8_27B_CURRENT_SERVING_PRIMARY_SOURCES_2026-09-23.json"
SUPPORT_MATRIX_PATH = EVIDENCE_DIR / "QWEN3_8_27B_RUNTIME_SUPPORT_MATRIX_2026-09-23.json"
ENGINE_DECISION_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_QWEN3_8_27B_PRODUCTION_SERVING_ENGINE_DECISION_2026-09-23.md"
QUAL_SPEC_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_QWEN3_8_27B_PRODUCTION_SERVING_QUALIFICATION_SPEC_2026-09-23.md"
ZERO_CASH_SPEC_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_ZERO_CASH_GPU_EXECUTION_CONTROL_SPEC_2026-09-23.md"
INDEX_PATH = EVIDENCE_DIR / "QWEN3_8_27B_SERVING_PREFLIGHT_SHA256_INDEX_2026-09-23.json"
SCRIPTS_DIR = REPO_ROOT / "scripts"


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


# ── A-D: unchanged runtime-state dimensions ─────────────────────────────


def test_qwen_runtime_state_dimensions_unchanged(registry):
    entry = registry.find_deployable("Qwen3.8-27B")
    assert entry["load_compatibility_status"] == "QUALIFIED"
    assert entry["production_serving_status"] == "NOT_TESTED"
    assert entry["financial_acceptance_status"] == "NOT_TESTED"
    assert entry["capability_status"] == "UNPROVEN"


def test_mistral_production_serving_status_unchanged(registry):
    entry = registry.find_deployable("Mistral Small 4")
    assert entry["production_serving_status"] == "QUALIFIED"


def test_glm_financial_failure_state_unchanged(registry):
    entry = registry.find_deployable("GLM-5.3-Flash")
    assert entry["production_serving_status"] == "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED"
    assert entry["financial_acceptance_status"] == "ZERO_OWNER_CASH_FAILED"


def test_qwen_flash_next_remains_license_blocked(registry):
    entry = registry.find_deployable("Qwen3.8-Flash-Next")
    assert entry["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert entry["runtime_smoke_eligibility"] == "BLOCKED"


# ── E/F: zero-cash spec wording correction ──────────────────────────────


def test_zero_cash_spec_does_not_assert_unverified_modal_mechanism_as_fact():
    text = ZERO_CASH_SPEC_PATH.read_text()
    # the corrected wording must explicitly flag the mechanism as unverified
    assert "unverified" in text.lower()
    assert "provider-side mechanism was not established" in text
    # must NOT contain the old unqualified assertion pattern
    assert "was shown by the GLM incident to prevent only NEW chargeable actions" not in text


def test_zero_cash_spec_still_requires_zero_owner_billed_delta():
    text = ZERO_CASH_SPEC_PATH.read_text()
    assert "owner_billed_delta_usd == 0" in text


def test_zero_cash_spec_records_exact_observed_incident_facts():
    """The canonical observed-fact wording (not the mechanism claim) must
    still be present -- correcting unverified semantics must not delete
    the genuinely observed numbers."""
    text = ZERO_CASH_SPEC_PATH.read_text()
    assert "$3.52" in text
    assert "$30.00" in text
    assert "$0" in text


# ── G/H: SGLang evidence correction ─────────────────────────────────────


def test_sglang_cookbook_recorded_as_primary_source():
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    urls = [s["url"] for s in sources["sources"]]
    assert "https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B" in urls


def test_sglang_parser_flags_no_longer_claimed_unknown():
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    tool_calling = sources["tool_calling"]
    assert tool_calling["sglang_tool_call_parser"].startswith("qwen3_coder")

    matrix = json.loads(SUPPORT_MATRIX_PATH.read_text())
    assert matrix["engines"]["sglang"]["reasoning_parser"] == "qwen3 -- explicitly standard in every cookbook recipe"
    assert "qwen3_coder" in matrix["engines"]["sglang"]["tool_call_parser"]
    # must not still claim SGLang evidence is thinner than vLLM's
    assert matrix["engines"]["sglang"]["evidence_strength"] != "CURRENT_PRIMARY_SOURCE_DOCUMENTED_THINNER_THAN_VLLM"


def test_engine_decision_does_not_claim_sglang_evidence_is_thin():
    text = ENGINE_DECISION_PATH.read_text()
    assert "No dedicated recipe page found" not in text
    assert "Not documented in the retrieved sources this phase" not in text
    assert "thin, generic" not in text
    # the corrected document should explicitly acknowledge the correction
    assert "correction" in text.lower()


def test_engine_decision_still_selects_vllm_primary_sglang_fallback():
    """The core decision is unchanged -- only the rationale is corrected."""
    text = ENGINE_DECISION_PATH.read_text()
    assert "PRIMARY FUTURE QUALIFICATION ENGINE: vLLM" in text
    assert "FALLBACK ENGINE: SGLang" in text


# ── I: tool-parser divergence recorded ──────────────────────────────────


def test_tool_call_parser_divergence_recorded():
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    tool_calling = sources["tool_calling"]
    assert "PRIMARY_SOURCE_CONFIGURATION_DIVERGENCE" in tool_calling["primary_source_configuration_divergence"]
    assert tool_calling["resolution_status"].startswith("TOOL_CALL_PARSER_SELECTION_REQUIRES_CPU_PREFLIGHT")


def test_qualification_spec_does_not_freeze_tool_call_parser_prematurely():
    text = QUAL_SPEC_PATH.read_text()
    assert "<TOOL_CALL_PARSER>" in text
    assert "not frozen" in text.lower() or "NOT frozen" in text


# ── J: optional-feature version floors separated from base floors ──────


def test_version_guidance_separates_base_from_optional():
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    facts = sources["dependency_and_version_facts"]
    assert "base_serving_version_guidance" in facts
    assert "optional_feature_version_requirements" in facts
    # the DFlash2-specific floor must live under optional, not base
    assert "0.28.0" in facts["optional_feature_version_requirements"]["vllm_dflash2_speculative_path"]
    assert "0.28.0" not in facts["base_serving_version_guidance"]["vllm_base_minimum"]


def test_base_vllm_version_floor_not_fabricated():
    """Re-verified: no general vLLM base-serving version floor is
    published by the current recipe -- this must be stated honestly as
    absent, not invented (e.g. as '0.17.0+')."""
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    base = sources["dependency_and_version_facts"]["base_serving_version_guidance"]["vllm_base_minimum"]
    assert "NOT explicitly published" in base
    # "0.17.0" may appear only inside a negation (explaining no such floor
    # exists), never asserted as an actual value
    assert not base.startswith("0.17.0") and ">=0.17.0" not in base


# ── K: SHA-256 index integrity ───────────────────────────────────────────


def test_serving_preflight_index_hashes_final_bytes_exactly():
    index = json.loads(INDEX_PATH.read_text())
    entries = index["entries"]
    assert len(entries) == 7
    for entry in entries:
        path = REPO_ROOT / entry["path"]
        assert path.is_file(), f"missing: {entry['path']}"
        actual_bytes = path.read_bytes()
        actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()
        assert actual_sha256 == entry["sha256"], f"hash mismatch for {entry['path']}"
        assert len(actual_bytes) == entry["size_bytes"]


# ── L: no GPU allocation/inference/model-download code introduced ──────


def test_new_cpu_preflight_script_has_no_gpu_allocation():
    script = SCRIPTS_DIR / "phase21b_4_15_1_qwen38_27b_cpu_preflight.py"
    assert script.is_file()
    tree = ast.parse(script.read_text())
    gpu_kwargs = [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "gpu"]
    assert gpu_kwargs == []


def test_new_cpu_preflight_script_does_not_download_model_weights():
    text = (SCRIPTS_DIR / "phase21b_4_15_1_qwen38_27b_cpu_preflight.py").read_text()
    # must inspect registries only, never call from_pretrained / load weights
    assert "from_pretrained" not in text
    assert "AutoModel" not in text
    assert ".generate(" not in text


def test_cpu_preflight_result_recorded_as_inconclusive_not_resolved():
    """The CPU preflight hit real import errors and did not conclusively
    resolve the parser registration question -- this must be recorded
    honestly, never silently treated as a pass."""
    output_path = EVIDENCE_DIR / "QWEN3_8_27B_CPU_PREFLIGHT_PARSER_REGISTRY_ATTEMPT_2026-09-23.txt"
    assert output_path.is_file()
    text = output_path.read_text()
    assert "torchvision::nms" in text or "No module named" in text
    assert "EXIT:0" in text  # the harness itself completed cleanly even though the checks were inconclusive


def test_registry_still_loads_and_validates_end_to_end():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {c["canonical_candidate_name"] for c in registry.deployable_candidates}
    assert {"Qwen3.8-27B", "Qwen3.8-Flash-Next", "Mistral Small 4", "GLM-5.3-Flash"} == names
