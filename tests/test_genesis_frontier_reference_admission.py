"""Phase 21B.4.17: Genesis Frontier Reference identity + terms + access +
execution-admission qualification.

PRIMARY-SOURCE RESEARCH + CPU/METADATA ONLY -- no GPU, no frontier
inference, no paid API call, no benchmark, no holdout execution. Proves
(per the phase spec's required test list, A-V):
  A. exact frontier reference set remains exactly six.
  B. no substitutions.
  C. open-weight references have pinned 40-hex revisions.
  D. mutable Qwen3.8-Max does not fake an immutable revision.
  E. actual license/terms evidence exists for every reference.
  F. evaluation admission cannot pass with unresolved license/terms.
  G. teacher admission cannot pass without explicit evidence.
  H. evaluation and teacher statuses are independent.
  I. evidence-retention rights are checked.
  J. access path evidence exists.
  K. unverified third-party endpoints do not count toward quorum.
  L. quorum requires >=4 admitted references.
  M. quorum requires >=3 independent organizations/lineages.
  N. target remains 6.
  O. no post-hoc substitution.
  P. Qwen3.8-Max remains distinct from Qwen3.8-2.4T-A95B.
  Q. no frontier API call code introduced.
  R. no GPU code introduced.
  S. no model-weight download code introduced.
  T. deployable candidate states unchanged.
  U. control states unchanged.
  V. Phase 21C remains unauthorized.
"""

import ast
import hashlib
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import (
    CandidateExecutionRegistry,
    EXPECTED_REFERENCE_NAMES,
    REGISTRY_SCHEMA_VERSION,
    RegistrySchemaError,
    VALID_ACCESS_PREFLIGHT_STATUSES,
    VALID_EVIDENCE_RETENTION_STATUSES,
    VALID_MUTABLE_IDENTITY_STATUSES,
    VALID_REFERENCE_EVALUATION_ADMISSION_STATUSES,
    VALID_REFERENCE_TERMS_STATUSES,
    VALID_TEACHER_USE_STATUSES,
)
from orca.eval.frontier_reference_admission_quorum import (
    MINIMUM_INDEPENDENT_ORGANIZATIONS,
    MINIMUM_USABLE_REFERENCES,
    TARGET_REFERENCES,
    compute_admission_quorum,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
PRIMARY_SOURCES_PATH = EVIDENCE_DIR / "GENESIS_FRONTIER_REFERENCE_PRIMARY_SOURCES_2026-09-23.json"
INDEX_PATH = EVIDENCE_DIR / "GENESIS_FRONTIER_REFERENCE_SHA256_INDEX_2026-09-23.json"
ACCESS_MATRIX_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_REFERENCE_ACCESS_MATRIX_2026-09-23.md"
TERMS_MATRIX_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_REFERENCE_TERMS_MATRIX_2026-09-23.md"
FRONTIER_GATES_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_DECISION_GATES.md"
FRONTIER_REGISTRY_PY = REPO_ROOT / "orca/eval/candidate_registry.py"
FRONTIER_QUORUM_PY = REPO_ROOT / "orca/eval/frontier_reference_admission_quorum.py"

REFERENCE_ADMISSION_FILES = {
    "DeepSeek V4.1-Flash": EVIDENCE_DIR / "DEEPSEEK_V4_1_FLASH_REFERENCE_ADMISSION_2026-09-23.json",
    "GLM-5.3 (flagship)": EVIDENCE_DIR / "GLM_5_3_FLAGSHIP_REFERENCE_ADMISSION_2026-09-23.json",
    "Mistral Large 3": EVIDENCE_DIR / "MISTRAL_LARGE_3_REFERENCE_ADMISSION_2026-09-23.json",
    "MiniMax M3": EVIDENCE_DIR / "MINIMAX_M3_REFERENCE_ADMISSION_2026-09-23.json",
    "Qwen3.8-Max": EVIDENCE_DIR / "QWEN3_8_MAX_REFERENCE_ADMISSION_2026-09-23.json",
    "Kimi K3": EVIDENCE_DIR / "KIMI_K3_REFERENCE_ADMISSION_2026-09-23.json",
}


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


# ── A/N: exact frontier reference set remains exactly six ──────────────


def test_exact_reference_set_remains_six(registry):
    names = {r["reference_name"] for r in registry.frontier_references}
    assert names == set(EXPECTED_REFERENCE_NAMES)
    assert len(registry.frontier_references) == 6
    assert TARGET_REFERENCES == 6


# ── B/O: no substitutions ───────────────────────────────────────────────


def test_no_substitutions_locked_names(registry):
    names = {r["reference_name"] for r in registry.frontier_references}
    expected = {
        "DeepSeek V4.1-Flash", "GLM-5.3 (flagship)", "Mistral Large 3",
        "MiniMax M3", "Qwen3.8-Max", "Kimi K3",
    }
    assert names == expected
    forbidden = {"Claude", "GPT", "Gemini", "Grok", "Llama"}
    assert names.isdisjoint(forbidden)


def test_no_unrecognized_reference_name_accepted():
    data = json.loads(REGISTRY_PATH.read_text())
    data["frontier_references"][0]["reference_name"] = "Some Other Model"
    with pytest.raises(RegistrySchemaError, match="frontier_references names"):
        CandidateExecutionRegistry.from_dict(data)


# ── C: open-weight references have pinned 40-hex revisions ─────────────


def test_open_weight_references_have_pinned_40_hex_revisions(registry):
    import re
    hex40 = re.compile(r"^[0-9a-f]{40}$")
    for r in registry.frontier_references:
        if r["identity_type"] == "OPEN_WEIGHT":
            assert hex40.match(r["exact_immutable_revision"]), r["reference_name"]
            assert r["mutable_identity_status"] == "FIXED_IMMUTABLE", r["reference_name"]


def test_open_weight_cannot_claim_mutable_identity_status():
    data = json.loads(REGISTRY_PATH.read_text())
    deepseek = next(r for r in data["frontier_references"] if r["reference_name"] == "DeepSeek V4.1-Flash")
    deepseek["mutable_identity_status"] = "MUTABLE_REFERENCE_IDENTITY"
    with pytest.raises(RegistrySchemaError, match="mutable_identity_status"):
        CandidateExecutionRegistry.from_dict(data)


# ── D: mutable Qwen3.8-Max does not fake an immutable revision ─────────


def test_qwen3_8_max_is_mutable_hosted_api_with_no_fake_revision(registry):
    qwen_max = next(r for r in registry.frontier_references if r["reference_name"] == "Qwen3.8-Max")
    assert qwen_max["identity_type"] == "MUTABLE_HOSTED_API"
    assert "NOT_AVAILABLE" in qwen_max["exact_immutable_revision"]
    assert qwen_max["mutable_identity_status"] == "MUTABLE_REFERENCE_IDENTITY"


def test_mutable_hosted_api_cannot_claim_real_looking_revision():
    data = json.loads(REGISTRY_PATH.read_text())
    qwen_max = next(r for r in data["frontier_references"] if r["reference_name"] == "Qwen3.8-Max")
    qwen_max["exact_immutable_revision"] = "a" * 40
    with pytest.raises(RegistrySchemaError, match="MUTABLE_HOSTED_API"):
        CandidateExecutionRegistry.from_dict(data)


def test_mutable_hosted_api_cannot_claim_fixed_immutable_status():
    data = json.loads(REGISTRY_PATH.read_text())
    qwen_max = next(r for r in data["frontier_references"] if r["reference_name"] == "Qwen3.8-Max")
    qwen_max["mutable_identity_status"] = "FIXED_IMMUTABLE"
    with pytest.raises(RegistrySchemaError, match="MUTABLE_REFERENCE_IDENTITY"):
        CandidateExecutionRegistry.from_dict(data)


# ── E: actual license/terms evidence exists for every reference ────────


def test_actual_license_terms_evidence_exists_for_every_reference():
    for name, path in REFERENCE_ADMISSION_FILES.items():
        assert path.is_file(), f"missing admission evidence for {name}"
        data = json.loads(path.read_text())
        assert "D_license_or_terms" in data
        assert data["D_license_or_terms"].get("license_or_terms_status") in VALID_REFERENCE_TERMS_STATUSES


# ── F: evaluation admission cannot pass with unresolved license/terms ──


def test_evaluation_admission_requires_clear_terms(registry):
    for r in registry.frontier_references:
        if r["reference_evaluation_admission_status"] == "ADMITTED":
            assert r["license_or_terms_status"] == "CLEAR", r["reference_name"]


def test_admission_rejected_when_terms_review_required():
    data = json.loads(REGISTRY_PATH.read_text())
    deepseek = next(r for r in data["frontier_references"] if r["reference_name"] == "DeepSeek V4.1-Flash")
    deepseek["license_or_terms_status"] = "REVIEW_REQUIRED"
    # admission still claims ADMITTED -- must be rejected
    with pytest.raises(RegistrySchemaError, match="license_or_terms_status"):
        CandidateExecutionRegistry.from_dict(data)


def test_review_required_references_are_not_admitted(registry):
    for r in registry.frontier_references:
        if r["license_or_terms_status"] == "REVIEW_REQUIRED":
            assert r["reference_evaluation_admission_status"] != "ADMITTED", r["reference_name"]


# ── G: teacher admission cannot pass without explicit evidence ─────────


def test_teacher_admission_requires_evidence_reference(registry):
    for r in registry.frontier_references:
        if r["teacher_use_status"] == "ADMITTED":
            assert r["teacher_use_evidence_reference"], r["reference_name"]


def test_teacher_admission_rejected_without_evidence():
    data = json.loads(REGISTRY_PATH.read_text())
    deepseek = next(r for r in data["frontier_references"] if r["reference_name"] == "DeepSeek V4.1-Flash")
    deepseek["teacher_use_evidence_reference"] = None
    with pytest.raises(RegistrySchemaError, match="teacher_use_evidence_reference"):
        CandidateExecutionRegistry.from_dict(data)


def test_qwen3_8_max_teacher_use_blocked_with_rationale():
    """Qwen3.8-Max's teacher status is BLOCKED (not merely unresolved) --
    the anti-competing-product ToS clause is a real, named risk given
    Genesis's own training purpose, not silence."""
    data = json.loads(REFERENCE_ADMISSION_FILES["Qwen3.8-Max"].read_text())
    assert data["final_state"]["teacher_use_status"] == "BLOCKED"
    assert "compete" in data["P_teacher_distillation_synthetic_data_rights"]["rationale"].lower()


# ── H: evaluation and teacher statuses are independent ─────────────────


def test_evaluation_and_teacher_status_are_independent(registry):
    """At least one reference must be ADMITTED for evaluation while its
    teacher status is something other than ADMITTED, and vice versa is
    not required to be impossible -- this proves the two fields are not
    mechanically copied from each other."""
    eval_admitted_names = {r["reference_name"] for r in registry.frontier_references if r["reference_evaluation_admission_status"] == "ADMITTED"}
    teacher_admitted_names = {r["reference_name"] for r in registry.frontier_references if r["teacher_use_status"] == "ADMITTED"}
    assert eval_admitted_names != teacher_admitted_names, "evaluation and teacher admission sets must not be identical"
    # MiniMax M3, Kimi K3: evaluation ADMITTED but teacher NOT ADMITTED
    assert "MiniMax M3" in eval_admitted_names and "MiniMax M3" not in teacher_admitted_names
    assert "Kimi K3" in eval_admitted_names and "Kimi K3" not in teacher_admitted_names


def test_teacher_status_schema_values_are_valid(registry):
    for r in registry.frontier_references:
        assert r["teacher_use_status"] in VALID_TEACHER_USE_STATUSES
        assert r["reference_evaluation_admission_status"] in VALID_REFERENCE_EVALUATION_ADMISSION_STATUSES


# ── I: evidence-retention rights are checked ────────────────────────────


def test_evidence_retention_status_present_and_valid(registry):
    for r in registry.frontier_references:
        assert r["evidence_retention_status"] in VALID_EVIDENCE_RETENTION_STATUSES


def test_admission_requires_acceptable_evidence_retention():
    data = json.loads(REGISTRY_PATH.read_text())
    deepseek = next(r for r in data["frontier_references"] if r["reference_name"] == "DeepSeek V4.1-Flash")
    deepseek["evidence_retention_status"] = "PROHIBITED"
    with pytest.raises(RegistrySchemaError, match="evidence_retention_status"):
        CandidateExecutionRegistry.from_dict(data)


def test_kimi_k3_holdout_path_dependent_retention_documented():
    data = json.loads(REFERENCE_ADMISSION_FILES["Kimi K3"].read_text())
    holdout = data["H_private_holdout_compatibility"]
    assert holdout["status"] == "PATH_DEPENDENT"
    assert "hosted_api_path" in holdout and "self_host_path" in holdout


# ── J: access path evidence exists ──────────────────────────────────────


def test_access_path_evidence_exists_for_every_reference():
    for name, path in REFERENCE_ADMISSION_FILES.items():
        data = json.loads(path.read_text())
        assert "K_access_paths" in data, name
    assert ACCESS_MATRIX_PATH.is_file()
    text = ACCESS_MATRIX_PATH.read_text()
    for name in REFERENCE_ADMISSION_FILES:
        assert name.split(" (")[0] in text  # handles "GLM-5.3 (flagship)" heading variance


def test_access_preflight_status_valid_for_all(registry):
    for r in registry.frontier_references:
        assert r["access_preflight_status"] in VALID_ACCESS_PREFLIGHT_STATUSES


def test_admitted_reference_cannot_have_blocked_access_preflight():
    data = json.loads(REGISTRY_PATH.read_text())
    deepseek = next(r for r in data["frontier_references"] if r["reference_name"] == "DeepSeek V4.1-Flash")
    deepseek["access_preflight_status"] = "BLOCKED"
    with pytest.raises(RegistrySchemaError, match="access_preflight_status"):
        CandidateExecutionRegistry.from_dict(data)


# ── K: unverified third-party endpoints do not count toward quorum ─────


def test_unverified_third_party_shared_endpoints_marked_unqualified():
    """The Modal Shared Endpoint claims (GLM-5.3, Kimi K3, and the prior
    incorrect Qwen3.8-Max substitution) were explicitly NOT tested this
    phase -- their corresponding access_preflight_status must not be a
    counting status."""
    glm = json.loads(REFERENCE_ADMISSION_FILES["GLM-5.3 (flagship)"].read_text())
    assert glm["K_access_paths"]["third_party_shared_endpoint"]["access_path_status"] == "UNQUALIFIED"
    kimi = json.loads(REFERENCE_ADMISSION_FILES["Kimi K3"].read_text())
    assert kimi["final_state"]["access_preflight_status"] == "UNQUALIFIED"


def test_qwen3_8_max_zero_cash_field_no_longer_names_distinct_artifact(registry):
    """Phase 21B.4.17 correction: the registry's zero_cash_access_status
    for Qwen3.8-Max previously named the DISTINCT open-weight artifact
    Qwen/Qwen3.8-2.4T-A95B as its access path -- a silent substitution.
    This must be fixed."""
    qwen_max = next(r for r in registry.frontier_references if r["reference_name"] == "Qwen3.8-Max")
    assert "Qwen/Qwen3.8-2.4T-A95B" not in qwen_max["zero_cash_access_status"] or "correction" in qwen_max["zero_cash_access_status"].lower()


# ── L/M/N: quorum model ─────────────────────────────────────────────────


def test_quorum_constants_locked():
    assert TARGET_REFERENCES == 6
    assert MINIMUM_USABLE_REFERENCES == 4
    assert MINIMUM_INDEPENDENT_ORGANIZATIONS == 3


def test_quorum_report_matches_registry_evidence(registry):
    report = compute_admission_quorum(list(registry.frontier_references))
    assert report.admitted_reference_count == 4
    assert report.access_preflight_ready_count == 2
    assert report.quorum_counting_count == 2
    assert report.independent_lineage_count == 2
    assert report.quorum_status == "QUORUM_INCOMPLETE"


def test_quorum_requires_four_admitted_and_access_ready():
    fixture = [
        {"reference_name": "A", "organization": "OrgA", "reference_evaluation_admission_status": "ADMITTED", "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION"},
        {"reference_name": "B", "organization": "OrgB", "reference_evaluation_admission_status": "ADMITTED", "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION"},
        {"reference_name": "C", "organization": "OrgC", "reference_evaluation_admission_status": "ADMITTED", "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION"},
        {"reference_name": "D", "organization": "OrgD", "reference_evaluation_admission_status": "REVIEW_REQUIRED", "access_preflight_status": "UNQUALIFIED"},
    ]
    report = compute_admission_quorum(fixture)
    assert report.quorum_counting_count == 3
    assert report.quorum_status == "QUORUM_INCOMPLETE"  # below MINIMUM_USABLE_REFERENCES=4


def test_quorum_requires_three_independent_organizations():
    """4 admitted+ready references but only 2 distinct organizations
    must NOT satisfy MINIMUM_QUORUM_READY."""
    fixture = [
        {"reference_name": n, "organization": "OrgA" if i < 2 else "OrgB",
         "reference_evaluation_admission_status": "ADMITTED",
         "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION"}
        for i, n in enumerate(["A", "B", "C", "D"])
    ]
    report = compute_admission_quorum(fixture)
    assert report.quorum_counting_count == 4
    assert report.independent_lineage_count == 2
    assert report.quorum_status == "QUORUM_INCOMPLETE"


def test_minimum_quorum_ready_when_four_refs_three_orgs():
    fixture = [
        {"reference_name": "A", "organization": "OrgA", "reference_evaluation_admission_status": "ADMITTED", "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION"},
        {"reference_name": "B", "organization": "OrgB", "reference_evaluation_admission_status": "ADMITTED", "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION"},
        {"reference_name": "C", "organization": "OrgC", "reference_evaluation_admission_status": "ADMITTED", "access_preflight_status": "PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK"},
        {"reference_name": "D", "organization": "OrgC", "reference_evaluation_admission_status": "ADMITTED", "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION"},
    ]
    report = compute_admission_quorum(fixture)
    assert report.quorum_counting_count == 4
    assert report.independent_lineage_count == 3
    assert report.quorum_status == "MINIMUM_QUORUM_READY"


def test_target_ready_requires_all_six():
    fixture = [
        {"reference_name": n, "organization": f"Org{n}",
         "reference_evaluation_admission_status": "ADMITTED",
         "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION"}
        for n in "ABCDEF"
    ]
    report = compute_admission_quorum(fixture)
    assert report.quorum_status == "TARGET_READY"

    # five of six -- must NOT be TARGET_READY
    report5 = compute_admission_quorum(fixture[:5])
    assert report5.quorum_status != "TARGET_READY"


def test_zero_admitted_references_is_quorum_blocked():
    fixture = [
        {"reference_name": "A", "organization": "OrgA", "reference_evaluation_admission_status": "REVIEW_REQUIRED", "access_preflight_status": "UNQUALIFIED"},
    ]
    report = compute_admission_quorum(fixture)
    assert report.quorum_status == "QUORUM_BLOCKED"


# ── P: Qwen3.8-Max remains distinct from Qwen3.8-2.4T-A95B ─────────────


def test_qwen3_8_max_distinct_from_2_4t_a95b():
    data = json.loads(REFERENCE_ADMISSION_FILES["Qwen3.8-Max"].read_text())
    assert data["A2_relationship_to_qwen3_8_2_4t_a95b"]["distinctness_policy"].startswith("DISTINCT_REFERENCE_IDENTITIES")
    registry_data = json.loads(REGISTRY_PATH.read_text())
    qwen_max = next(r for r in registry_data["frontier_references"] if r["reference_name"] == "Qwen3.8-Max")
    assert qwen_max["artifact_repository"] != "Qwen/Qwen3.8-2.4T-A95B"
    assert "distinct" in qwen_max["artifact_repository"].lower() or "NOT_APPLICABLE" in qwen_max["artifact_repository"]


# ── Q/R/S: no frontier API call, GPU, or weight-download code ──────────


def test_no_frontier_api_call_code_introduced():
    for py_path in (FRONTIER_REGISTRY_PY, FRONTIER_QUORUM_PY):
        text = py_path.read_text()
        assert ".chat.completions.create(" not in text
        assert "requests.post(" not in text
        assert "openai.OpenAI(" not in text


def test_no_gpu_allocation_code_introduced():
    for py_path in (FRONTIER_REGISTRY_PY, FRONTIER_QUORUM_PY):
        tree = ast.parse(py_path.read_text())
        gpu_kwargs = [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "gpu"]
        assert gpu_kwargs == [], py_path


def test_no_model_weight_download_code_introduced():
    for py_path in (FRONTIER_REGISTRY_PY, FRONTIER_QUORUM_PY):
        text = py_path.read_text()
        assert "from_pretrained(" not in text
        assert ".generate(" not in text
        assert "snapshot_download(" not in text


# ── T/U: deployable candidate and control states unchanged ─────────────


def test_deployable_candidate_states_unchanged(registry):
    qwen38 = registry.find_deployable("Qwen3.8-27B")
    assert qwen38["load_compatibility_status"] == "QUALIFIED"
    assert qwen38["production_serving_status"] == "NOT_TESTED"

    mistral = registry.find_deployable("Mistral Small 4")
    assert mistral["production_serving_status"] == "QUALIFIED"

    glm = registry.find_deployable("GLM-5.3-Flash")
    assert glm["production_serving_status"] == "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED"
    assert glm["financial_acceptance_status"] == "ZERO_OWNER_CASH_FAILED"

    qwen_flash_next = registry.find_deployable("Qwen3.8-Flash-Next")
    assert qwen_flash_next["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert qwen_flash_next["runtime_smoke_eligibility"] == "BLOCKED"


def test_control_states_unchanged(registry):
    for c in registry.controls:
        assert c["control_admission_status"] == "ADMITTED"
        assert c["runtime_preflight_status"] == "READY"
        assert c["runtime_qualification_status"] == "NOT_TESTED"


# ── V: Phase 21C remains unauthorized ────────────────────────────────────


def test_phase_21c_still_unauthorized_and_frontier_lock_present():
    text = FRONTIER_GATES_PATH.read_text()
    assert "GENESIS FOUNDATION:" in text and "NOT YET SELECTED" in text
    assert "GENESIS FRONTIER STATUS:" in text and "UNPROVEN" in text
    assert "NO FOUNDATION HAS YET EARNED GENESIS SELECTION." in text


# ── Evidence integrity ────────────────────────────────────────────────


def test_frontier_reference_evidence_sha256_index_hashes_exactly():
    index = json.loads(INDEX_PATH.read_text())
    entries = index["entries"]
    assert len(entries) == 9
    for entry in entries:
        path = REPO_ROOT / entry["path"]
        assert path.is_file(), f"missing: {entry['path']}"
        actual_bytes = path.read_bytes()
        assert hashlib.sha256(actual_bytes).hexdigest() == entry["sha256"], f"hash mismatch for {entry['path']}"
        assert len(actual_bytes) == entry["size_bytes"]


def test_terms_matrix_separates_evaluation_and_teacher_admission():
    text = TERMS_MATRIX_PATH.read_text()
    assert "independent decisions" in text.lower() or "SEPARATE from evaluation admission" in text


# ── Regression lock: schema version ─────────────────────────────────────


def test_schema_version_bumped_to_v5():
    assert REGISTRY_SCHEMA_VERSION == "genesis-candidate-execution-registry-v5"
    data = json.loads(REGISTRY_PATH.read_text())
    assert data["schema_version"] == REGISTRY_SCHEMA_VERSION


def test_registry_still_loads_and_validates_end_to_end():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    assert len(registry.deployable_candidates) == 4
    assert len(registry.controls) == 3
    assert len(registry.frontier_references) == 6
