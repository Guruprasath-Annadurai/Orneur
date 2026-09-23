"""Phase 21B.4.14: Qwen3.8-Flash-Next Genesis license admission gate.

LICENSE / TERMS / IDENTITY / DOCUMENTATION ONLY -- no GPU, no weight
download, no inference. Proves the registry's disposition matches the
documented LICENSE_UNRESOLVED analysis outcome, that the blocked state
cannot silently become eligible, that evidence exists and hashes
exactly, and that nothing outside license admission was touched.
"""

import hashlib
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import CandidateExecutionRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
EVIDENCE_INDEX_PATH = EVIDENCE_DIR / "QWEN3_8_FLASH_NEXT_LICENSE_EVIDENCE_SHA256_INDEX_2026-09-23.json"
CLASSIFICATION_PATH = EVIDENCE_DIR / "QWEN3_8_FLASH_NEXT_PRODUCT_CLASSIFICATION_2026-09-23.json"
FRONTIER_GATES_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_DECISION_GATES.md"


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def qwen_entry(registry):
    return registry.find_deployable("Qwen3.8-Flash-Next")


def test_license_status_reflects_unresolved_outcome(qwen_entry):
    assert qwen_entry["license_status"] == "LICENSE_REVIEW_REQUIRED"


def test_runtime_smoke_eligibility_remains_blocked(qwen_entry):
    assert qwen_entry["runtime_smoke_eligibility"] == "BLOCKED"
    assert qwen_entry["runtime_smoke_blocked_reason"] == (
        "QWEN_COMMUNITY_LICENSE_COMMERCIAL_CLASSIFICATION_UNRESOLVED"
    )


def test_blocked_candidate_cannot_appear_eligible_for_runtime_smoke(registry):
    eligible_names = {e["canonical_candidate_name"] for e in registry.eligible_for_runtime_smoke()}
    assert "Qwen3.8-Flash-Next" not in eligible_names


def test_pinned_revision_preserved(qwen_entry):
    assert qwen_entry["exact_immutable_revision"] == "de4b8e4d43b917e7706784d8bb445c9af86a3540"
    assert qwen_entry["tokenizer_revision"] == "de4b8e4d43b917e7706784d8bb445c9af86a3540"


def test_runtime_qualification_and_identity_unchanged(qwen_entry):
    """This is a license-admission phase, not a capability phase -- these
    fields must be exactly what they were before this phase."""
    assert qwen_entry["runtime_qualification_status"] == "UNQUALIFIED"
    assert qwen_entry["identity_status"] == "RESOLVED"
    assert qwen_entry["architecture"] == "Qwen4ExpForConditionalGeneration"
    assert qwen_entry["total_parameters"] == 179999981459


def test_candidate_is_not_eliminated(registry):
    names = {c["canonical_candidate_name"] for c in registry.deployable_candidates}
    assert "Qwen3.8-Flash-Next" in names


def test_license_evidence_files_exist():
    expected = [
        "QWEN3_8_FLASH_NEXT_LICENSE_PRIMARY_SOURCE_2026-09-23.txt",
        "QWEN3_8_FLASH_NEXT_LICENSE_ANALYSIS_2026-09-23.md",
        "QWEN3_8_FLASH_NEXT_PRODUCT_CLASSIFICATION_2026-09-23.json",
        "QWEN3_8_FLASH_NEXT_QWEN_CLEARANCE_REQUEST_DRAFT_2026-09-23.md",
        "QWEN3_8_FLASH_NEXT_LICENSE_EVIDENCE_SHA256_INDEX_2026-09-23.json",
    ]
    for name in expected:
        assert (EVIDENCE_DIR / name).is_file(), f"missing evidence file: {name}"


def test_evidence_sha256_index_entries_exist_and_hash_exactly():
    index = json.loads(EVIDENCE_INDEX_PATH.read_text())
    entries = index["entries"]
    assert len(entries) == 4
    for entry in entries:
        path = REPO_ROOT / entry["path"]
        assert path.is_file(), f"evidence file missing: {entry['path']}"
        actual_bytes = path.read_bytes()
        actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()
        assert actual_sha256 == entry["sha256"], (
            f"hash mismatch for {entry['path']}: index says {entry['sha256']!r}, "
            f"actual bytes hash to {actual_sha256!r}"
        )
        assert len(actual_bytes) == entry["size_bytes"]


def test_pinned_and_main_license_bytes_are_identical():
    """The analysis found main HEAD == pinned revision, so pinned and
    current license text must be byte-identical -- this hash is recorded
    as fact in the classification file and must match the persisted
    primary-source file's actual bytes."""
    classification = json.loads(CLASSIFICATION_PATH.read_text())
    license_path = REPO_ROOT / classification["license_primary_source_path"]
    actual_sha256 = hashlib.sha256(license_path.read_bytes()).hexdigest()
    assert actual_sha256 == classification["license_primary_source_sha256"]
    assert actual_sha256 == "a0dc422560841fd68e06d974907f8b4c709bca44a67daad2b528437bdf676c08"


def test_product_classification_determination_is_unresolved():
    classification = json.loads(CLASSIFICATION_PATH.read_text())
    assert classification["determination"] == "LICENSE_UNRESOLVED"
    # no clause claims a clean MATCH for the MaaS gate -- ambiguity must
    # never be silently recorded as permission
    maas_entries = [
        c for c in classification["clause_mapping"]
        if "Model as a Service" in c["license_term"]
    ]
    assert maas_entries
    for entry in maas_entries:
        assert entry["match"] != "MATCH", (
            "MaaS clause must not be recorded as a clean MATCH while the "
            "determination is LICENSE_UNRESOLVED"
        )


def test_no_gpu_execution_introduced():
    """This phase is license/docs only -- no scripts requesting GPU
    allocation may exist for this candidate."""
    scripts_dir = REPO_ROOT / "scripts"
    for py_file in scripts_dir.glob("*qwen3_8_flash_next*"):
        text = py_file.read_text(errors="replace")
        assert "gpu=" not in text


def test_frontier_lock_and_phase_21c_status_unchanged():
    text = FRONTIER_GATES_PATH.read_text()
    assert "GENESIS FOUNDATION:" in text
    assert "NOT YET SELECTED" in text
    assert "GENESIS FRONTIER STATUS:" in text
    assert "UNPROVEN" in text
    assert "NO FOUNDATION HAS YET EARNED GENESIS SELECTION." in text


def test_registry_still_loads_and_validates_end_to_end():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {c["canonical_candidate_name"] for c in registry.deployable_candidates}
    assert {"Qwen3.8-Flash-Next", "Mistral Small 4", "GLM-5.3-Flash"}.issubset(names)
