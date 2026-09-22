"""Phase 21B.4.13.2: GLM-5.3-Flash historical-harness quarantine and
evidence-integrity closure.

Proves (per the phase spec's required test list):
  A. GLM registry remains UNQUALIFIED.
  B. GLM remains ELIGIBLE.
  C. formal qualification manifest linkage for GLM is absent.
  D. owner_billed_delta_usd == 3.52 remains preserved in the technical result.
  E. the existing strict manifest validator still rejects owner_billed_delta_usd > 0.
  F. every path/hash in GLM_5_3_FLASH_EVIDENCE_SHA256_INDEX_2026-09-23.json
     exists and hashes exactly.
  G. the archived historical GPU harnesses match the original historical
     bytes recorded in the SHA-256 index.
  H. no active runnable Phase 21B.4.13 GPU script remains under scripts/
     that can request H200:4.
  I. Genesis frontier-selection fail-closed wording remains present.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

from orca.eval.candidate_registry import (
    CandidateExecutionRegistry,
    RegistrySchemaError,
    verify_candidate_qualification_end_to_end,
    verify_recorded_manifest_linkage,
)
from orca.eval.runtime_qualification_manifest import (
    RuntimeQualificationManifestError,
    validate_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
TECHNICAL_RESULT_PATH = REPO_ROOT / "docs/orneur/phase-21/GLM_5_3_FLASH_TECHNICAL_RUNTIME_RESULT_2026-09-22.json"
EVIDENCE_INDEX_PATH = REPO_ROOT / "docs/orneur/phase-21/evidence/GLM_5_3_FLASH_EVIDENCE_SHA256_INDEX_2026-09-23.json"
FRONTIER_GATES_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_DECISION_GATES.md"
SCRIPTS_DIR = REPO_ROOT / "scripts"


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


@pytest.fixture(scope="module")
def glm_entry(registry):
    return registry.find_deployable("GLM-5.3-Flash")


def test_glm_registry_remains_unqualified(glm_entry):
    assert glm_entry["runtime_qualification_status"] == "UNQUALIFIED"


def test_glm_registry_remains_eligible(glm_entry):
    assert glm_entry["runtime_smoke_eligibility"] == "ELIGIBLE"
    assert glm_entry["runtime_smoke_blocked_reason"] == "ZERO_CASH_COMPUTE_REQUIRED_FOR_FORMAL_REQUALIFICATION"


def test_glm_has_no_qualification_manifest_linkage_fields(glm_entry):
    assert "qualification_type" not in glm_entry
    assert "qualification_manifest_path" not in glm_entry
    assert "qualification_manifest_digest_sha256" not in glm_entry


def test_glm_recorded_manifest_linkage_is_none(glm_entry):
    linkage = verify_recorded_manifest_linkage(glm_entry, REPO_ROOT)
    assert linkage is None


def test_glm_end_to_end_verifier_rejects_require_qualified(registry):
    with pytest.raises(RegistrySchemaError, match="UNQUALIFIED"):
        verify_candidate_qualification_end_to_end(
            REGISTRY_PATH, "GLM-5.3-Flash", require_qualified=True
        )


def test_glm_end_to_end_verifier_inspect_only_returns_no_manifest(registry):
    entry, manifest = verify_candidate_qualification_end_to_end(
        REGISTRY_PATH, "GLM-5.3-Flash", require_qualified=False
    )
    assert entry["canonical_candidate_name"] == "GLM-5.3-Flash"
    assert manifest is None


def test_technical_result_preserves_owner_billed_delta():
    data = json.loads(TECHNICAL_RESULT_PATH.read_text())
    assert data["owner_billed_delta_usd"] == 3.52
    assert data["formal_runtime_qualification"] == "NOT_ACCEPTED"
    assert data["formal_acceptance_blocker"] == "ZERO_OWNER_CASH_FINANCIAL_GATE_VIOLATION"
    assert data["technical_runtime_result"] == "SUCCESS"
    assert data["candidate_eliminated"] is False
    assert data["runtime_defect_demonstrated"] is False
    assert data["capability_status"] == "UNPROVEN BY ORNEUR"
    assert data["frontier_status"] == "UNPROVEN BY ORNEUR"
    assert data["phase_21c_authorized"] is False


def test_strict_manifest_validator_still_rejects_nonzero_owner_billed_delta():
    """(E) Regression: the pre-existing strict acceptance invariant in
    orca.eval.runtime_qualification_manifest must remain completely
    unweakened by this phase's changes."""
    from tests.test_runtime_qualification_manifest import _strict_manifest

    data = _strict_manifest()
    data["billed_before_usd"] = 0.0
    data["billed_after_usd"] = 3.52
    data["owner_billed_delta_usd"] = 3.52
    data["billing_gate_reconciliation"]["owner_billed_result"] = "$3.52 REPORTED"
    data["billing_gate_reconciliation"]["financial_impact"] = "OWNER_CHARGED_3_52_USD"
    with pytest.raises(RuntimeQualificationManifestError, match="owner_billed_delta_usd must be exactly 0"):
        validate_manifest(data)


def test_evidence_sha256_index_entries_exist_and_hash_exactly():
    """(F) Every path/hash in the evidence index must exist and match
    the file's actual bytes -- computed live, not trusted from the file."""
    index = json.loads(EVIDENCE_INDEX_PATH.read_text())
    entries = index["entries"]
    assert len(entries) >= 14

    seen_roles = set()
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
        seen_roles.add(entry["evidence_role"])

    required_roles = {
        "billing_gate", "billing_before", "billing_after",
        "model_identity", "runtime_environment", "generation_result", "cleanup",
        "invocation1_structured_result", "invocation1_execution_log",
        "invocation2_structured_successful_result", "invocation2_execution_log",
        "archived_historical_gpu_harness_attempt1", "archived_historical_gpu_harness_run2",
        "archived_cpu_preflight_harness",
    }
    assert required_roles.issubset(seen_roles)


def test_archived_historical_gpu_harnesses_match_recorded_hashes():
    """(G) The archived copies must be byte-identical to what the index
    (and, transitively, the original historical execution) recorded --
    this test would fail if anyone "fixed" the archived historical bytes."""
    index = json.loads(EVIDENCE_INDEX_PATH.read_text())
    by_role = {e["evidence_role"]: e for e in index["entries"]}

    for role in ("archived_historical_gpu_harness_attempt1", "archived_historical_gpu_harness_run2"):
        entry = by_role[role]
        path = REPO_ROOT / entry["path"]
        assert path.is_file()
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual_sha256 == entry["sha256"]
        # archived copies must physically live under evidence/harnesses/, not scripts/
        assert "evidence/harnesses/" in entry["path"]


def test_no_active_h200_4_gpu_script_remains_under_scripts_dir():
    """(H) No active runnable script under scripts/ may request a
    gpu="H200:4" Modal allocation."""
    offending = []
    for py_file in SCRIPTS_DIR.glob("*.py"):
        text = py_file.read_text(errors="replace")
        if re.search(r'gpu\s*=\s*["\']H200:4["\']', text):
            offending.append(py_file.name)
    assert offending == [], f"active scripts still request H200:4 GPU allocation: {offending}"

    # the two historical GPU launch scripts must no longer exist under scripts/
    assert not (SCRIPTS_DIR / "phase21b_4_13_glm_gpu_attempt1.py").exists()
    assert not (SCRIPTS_DIR / "phase21b_4_13_glm_gpu_run2.py").exists()


def test_cpu_preflight_script_structurally_cannot_allocate_gpu():
    """The one Phase 21B.4.13 script still active under scripts/ must be
    verifiably GPU-incapable, not merely described as such."""
    import ast

    cpu_preflight = SCRIPTS_DIR / "phase21b_4_13_glm_cpu_preflight.py"
    assert cpu_preflight.exists()
    tree = ast.parse(cpu_preflight.read_text())
    gpu_kwargs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword) and node.arg == "gpu"
    ]
    assert gpu_kwargs == [], "found a gpu= keyword argument in actual code (AST-level check)"


def test_frontier_fail_closed_wording_present():
    """(I) Genesis frontier-selection fail-closed wording remains present."""
    text = FRONTIER_GATES_PATH.read_text()
    assert "ORNEUR Genesis shall not enter foundation freeze or Phase 21C merely" in text
    assert "GENESIS FOUNDATION:" in text
    assert "NOT YET SELECTED" in text
    assert "GENESIS FRONTIER STATUS:" in text
    assert "UNPROVEN" in text
    assert "NO FOUNDATION HAS YET EARNED GENESIS SELECTION." in text


def test_registry_still_loads_and_validates_end_to_end():
    """Sanity: the full registry (all candidates, not just GLM) still
    loads and schema-validates cleanly after this phase's edits."""
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    names = {c["canonical_candidate_name"] for c in registry.deployable_candidates}
    assert "GLM-5.3-Flash" in names
    assert "Mistral Small 4" in names
