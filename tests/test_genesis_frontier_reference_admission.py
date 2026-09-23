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
    AccessReadinessError,
    _entry_passes_full_protocol_validation,
    compute_admission_quorum,
    compute_public_eval_ready_count,
    validate_full_protocol_access_readiness,
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
    # Kimi K3, Mistral Large 3: evaluation ADMITTED but teacher NOT ADMITTED
    # (Phase 21B.4.17.1: Mistral Large 3's teacher status was corrected
    # from ADMITTED to NOT_EVALUATED -- Apache-2.0's derivative-works
    # grant over the weights does not itself license generated outputs)
    assert "Kimi K3" in eval_admitted_names and "Kimi K3" not in teacher_admitted_names
    assert "Mistral Large 3" in eval_admitted_names and "Mistral Large 3" not in teacher_admitted_names
    # DeepSeek is the only reference with BOTH evaluation and teacher ADMITTED
    assert "DeepSeek V4.1-Flash" in eval_admitted_names and "DeepSeek V4.1-Flash" in teacher_admitted_names


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
    """Phase 21B.4.17.2 (K): after correcting DeepSeek's
    access_preflight_status to reflect that FULL-PROTOCOL readiness
    requires PERMITTED private-holdout compatibility (which DeepSeek
    does not yet have -- REVIEW_REQUIRED), the full-protocol
    quorum-counting count drops from the prior (still-too-generous) 1
    to 0. This test intentionally does NOT preserve the old number
    merely because a prior phase reported it (per phase instruction
    §10/§6: report the truth, QUORUM_BLOCKED remains acceptable)."""
    report = compute_admission_quorum(list(registry.frontier_references))
    assert report.admitted_reference_count == 3  # DeepSeek, Mistral Large 3, Kimi K3
    assert report.access_preflight_ready_count == 0  # no reference is full-protocol ready
    assert report.quorum_counting_count == 0
    assert report.quorum_counting_references == ()
    assert report.independent_lineage_count == 0
    assert report.quorum_status == "QUORUM_BLOCKED"


def test_public_eval_ready_count_is_separate_and_nonzero(registry):
    """(C/§9) DeepSeek is public-eval-ready even though it is not
    full-protocol quorum-ready -- these are separate, both-tracked
    counts, and the narrower one is never conflated with the
    quorum-determining one."""
    refs = list(registry.frontier_references)
    public_count = compute_public_eval_ready_count(refs)
    full_protocol_count = compute_admission_quorum(refs).quorum_counting_count
    assert public_count == 1
    assert full_protocol_count == 0
    assert public_count != full_protocol_count


# Phase 21B.4.18 §22: a synthetic fixture must carry FULLY-PASSING
# evidence for `_entry_passes_full_protocol_validation()` -- a naked
# reference_evaluation_admission_status/access_preflight_status pair is
# no longer sufficient to count toward quorum. These threshold-logic
# tests are about the 4/3/6 counting rules, not the evidence gate
# itself (which has its own dedicated tamper tests below), so every
# fixture entry that is meant to count gets a fully-valid evidence
# overlay via this helper.
def _counting_entry(name: str, organization: str, access_preflight_status: str) -> dict:
    return {
        "reference_name": name,
        "organization": organization,
        "reference_evaluation_admission_status": "ADMITTED",
        "access_preflight_status": access_preflight_status,
        "license_or_terms_status": "CLEAR",
        "evidence_retention_status": "PERMITTED",
        "automated_evaluation_status": "CLEAR",
        "private_holdout_status": "PERMITTED",
        "access_path_identified": True,
        "model_identity_attributable": True,
        "non_financial_blocker_status": "NONE",
    }


def test_quorum_requires_four_admitted_and_access_ready():
    fixture = [
        _counting_entry("A", "OrgA", "QUALIFIED_FOR_FUTURE_EXECUTION"),
        _counting_entry("B", "OrgB", "QUALIFIED_FOR_FUTURE_EXECUTION"),
        _counting_entry("C", "OrgC", "QUALIFIED_FOR_FUTURE_EXECUTION"),
        {"reference_name": "D", "organization": "OrgD", "reference_evaluation_admission_status": "REVIEW_REQUIRED", "access_preflight_status": "UNQUALIFIED"},
    ]
    report = compute_admission_quorum(fixture)
    assert report.quorum_counting_count == 3
    assert report.quorum_status == "QUORUM_INCOMPLETE"  # below MINIMUM_USABLE_REFERENCES=4


def test_quorum_requires_three_independent_organizations():
    """4 admitted+ready references but only 2 distinct organizations
    must NOT satisfy MINIMUM_QUORUM_READY."""
    fixture = [
        _counting_entry(n, "OrgA" if i < 2 else "OrgB", "QUALIFIED_FOR_FUTURE_EXECUTION")
        for i, n in enumerate(["A", "B", "C", "D"])
    ]
    report = compute_admission_quorum(fixture)
    assert report.quorum_counting_count == 4
    assert report.independent_lineage_count == 2
    assert report.quorum_status == "QUORUM_INCOMPLETE"


def test_minimum_quorum_ready_when_four_refs_three_orgs():
    fixture = [
        _counting_entry("A", "OrgA", "QUALIFIED_FOR_FUTURE_EXECUTION"),
        _counting_entry("B", "OrgB", "QUALIFIED_FOR_FUTURE_EXECUTION"),
        _counting_entry("C", "OrgC", "PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK"),
        _counting_entry("D", "OrgC", "QUALIFIED_FOR_FUTURE_EXECUTION"),
    ]
    report = compute_admission_quorum(fixture)
    assert report.quorum_counting_count == 4
    assert report.independent_lineage_count == 3
    assert report.quorum_status == "MINIMUM_QUORUM_READY"


def test_target_ready_requires_all_six():
    fixture = [_counting_entry(n, f"Org{n}", "QUALIFIED_FOR_FUTURE_EXECUTION") for n in "ABCDEF"]
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


def test_frontier_reference_evidence_sha256_index_2026_09_24_hashes_exactly():
    index_path = EVIDENCE_DIR / "GENESIS_FRONTIER_REFERENCE_SHA256_INDEX_2026-09-24.json"
    index = json.loads(index_path.read_text())
    entries = index["entries"]
    assert len(entries) == 3
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
    assert REGISTRY_SCHEMA_VERSION == "genesis-candidate-execution-registry-v6"
    data = json.loads(REGISTRY_PATH.read_text())
    assert data["schema_version"] == REGISTRY_SCHEMA_VERSION


def test_registry_still_loads_and_validates_end_to_end():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    assert len(registry.deployable_candidates) == 4
    assert len(registry.controls) == 3
    assert len(registry.frontier_references) == 6


# ═══════════════════════════════════════════════════════════════════════
# Phase 21B.4.17.1: Frontier Reference Terms + Access + Quorum
# Reconciliation (A-N below). G/H/I/K/L/M/N of the phase spec's required
# test list are already proven by the updated tests above (unchanged
# assertion targets, just corrected expected values): quorum matches
# corrected registry state (test_quorum_report_matches_registry_evidence),
# no reference promoted merely to preserve quorum (same test, honest
# count of 1), Qwen3.8-Max distinctness (test_qwen3_8_max_distinct_from_2_4t_a95b),
# Kimi holdout path-dependence (test_kimi_k3_holdout_path_dependent_retention_documented),
# no frontier API/GPU/weight code (test_no_frontier_api_call_code_introduced
# etc.), deployable/control states unchanged (test_deployable_candidate_states_unchanged,
# test_control_states_unchanged), Phase 21C unauthorized
# (test_phase_21c_still_unauthorized_and_frontier_lock_present).
# ═══════════════════════════════════════════════════════════════════════


# ── A: DeepSeek cannot be access-ready while automated eval is unresolved ─


def test_deepseek_automated_evaluation_now_clear():
    data = json.loads(REFERENCE_ADMISSION_FILES["DeepSeek V4.1-Flash"].read_text())
    assert data["I_automated_evaluation_allowed"]["status"] == "CLEAR"


def _deepseek_current_readiness_kwargs():
    """Build the real kwargs for validate_full_protocol_access_readiness
    from DeepSeek's actual current (corrected) evidence file -- used as
    the baseline that tamper tests below mutate in memory."""
    data = json.loads(REFERENCE_ADMISSION_FILES["DeepSeek V4.1-Flash"].read_text())
    fs = data["final_state"]
    return dict(
        reference_evaluation_admission_status=fs["reference_evaluation_admission_status"],
        license_or_terms_status=fs["license_or_terms_status"],
        evidence_retention_status=fs["evidence_retention_status"],
        automated_evaluation_status=data["I_automated_evaluation_allowed"]["status"],
        private_holdout_status=data["H_private_holdout_compatibility"]["private_holdout_compatibility"]["status"],
        access_path_identified=True,
        model_identity_attributable=True,
    )


def test_deepseek_current_state_is_internally_consistent():
    """DeepSeek's real current final_state (access_preflight_status=
    UNQUALIFIED for full-protocol purposes) must not trip the gate --
    it does not claim readiness in the first place."""
    kwargs = _deepseek_current_readiness_kwargs()
    validate_full_protocol_access_readiness("UNQUALIFIED", **kwargs)  # no-op, must not raise


def test_access_ready_requires_automated_evaluation_not_review_required():
    """(A/E) Real fail-closed tamper test: claim a counting access
    status while automated-evaluation is REVIEW_REQUIRED, in an
    IN-MEMORY copy of DeepSeek's real evidence values -- must raise.
    Committed evidence is never mutated."""
    kwargs = _deepseek_current_readiness_kwargs()
    kwargs["automated_evaluation_status"] = "REVIEW_REQUIRED"  # tamper, in-memory only
    with pytest.raises(AccessReadinessError, match="automated_evaluation_status"):
        validate_full_protocol_access_readiness("PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK", **kwargs)


def test_private_holdout_review_required_fails_full_protocol_gate():
    """(B/F) Real fail-closed tamper test: claim a counting access
    status while private-holdout compatibility is REVIEW_REQUIRED --
    must raise, proving REVIEW_REQUIRED holdout status cannot count
    toward full-protocol quorum even if every other gate is satisfied."""
    kwargs = _deepseek_current_readiness_kwargs()
    kwargs["private_holdout_status"] = "REVIEW_REQUIRED"  # this IS DeepSeek's real current value
    with pytest.raises(AccessReadinessError, match="private_holdout_status"):
        validate_full_protocol_access_readiness("QUALIFIED_FOR_FUTURE_EXECUTION", **kwargs)
    # and confirm PERMITTED would pass every other real gate (sanity check
    # that the function isn't trivially always-raising)
    kwargs["private_holdout_status"] = "PERMITTED"
    validate_full_protocol_access_readiness("QUALIFIED_FOR_FUTURE_EXECUTION", **kwargs)  # must not raise


def test_non_counting_status_never_triggers_the_gate():
    """A reference not claiming readiness at all (UNQUALIFIED, BLOCKED,
    NOT_TESTED) is never checked -- there's nothing to validate."""
    kwargs = _deepseek_current_readiness_kwargs()
    kwargs["automated_evaluation_status"] = "REVIEW_REQUIRED"
    kwargs["private_holdout_status"] = "REVIEW_REQUIRED"
    for status in ("UNQUALIFIED", "BLOCKED", "NOT_TESTED"):
        validate_full_protocol_access_readiness(status, **kwargs)  # must not raise


# ── B: MiniMax cannot be access-ready solely because a repo exists ─────


def test_minimax_m3_access_preflight_is_unqualified_not_ready(registry):
    minimax = next(r for r in registry.frontier_references if r["reference_name"] == "MiniMax M3")
    assert minimax["access_preflight_status"] == "UNQUALIFIED"
    data = json.loads(REFERENCE_ADMISSION_FILES["MiniMax M3"].read_text())
    assert data["K_access_paths"]["self_host"]["status"] == "COMPUTE_PROHIBITIVE"
    assert data["final_state"]["access_preflight_status"] == "UNQUALIFIED"


# ── C: MiniMax commercial-use classification supported by actual text ──


def test_minimax_commercial_use_classification_cites_actual_license_clause():
    data = json.loads(REFERENCE_ADMISSION_FILES["MiniMax M3"].read_text())
    d = data["D_license_or_terms"]
    assert "primarily intended for commercial advantage" in d["commercial_use_definition_verbatim"]
    assert d["license_or_terms_status"] == "REVIEW_REQUIRED"
    # must not merely assert "internal == non-commercial"
    assert "not sufficiently supported" in d.get("evaluation_use_reassessment_21b4171", "") or \
           "genuinely ambiguous" in d["status_rationale"]


def test_minimax_registry_status_matches_corrected_evidence(registry):
    minimax = next(r for r in registry.frontier_references if r["reference_name"] == "MiniMax M3")
    assert minimax["license_or_terms_status"] == "REVIEW_REQUIRED"
    assert minimax["reference_evaluation_admission_status"] == "REVIEW_REQUIRED"


# ── D/E: Mistral Large 3 teacher admission cannot rely solely on Apache-2.0 ──


def test_mistral_large_3_teacher_status_corrected_to_not_evaluated(registry):
    mistral = next(r for r in registry.frontier_references if r["reference_name"] == "Mistral Large 3")
    assert mistral["teacher_use_status"] == "NOT_EVALUATED"
    assert mistral["teacher_use_evidence_reference"] is None
    data = json.loads(REFERENCE_ADMISSION_FILES["Mistral Large 3"].read_text())
    assert data["final_state"]["teacher_use_status"] == "NOT_EVALUATED"
    # evaluation admission (weight-license-based) is unaffected
    assert data["final_state"]["reference_evaluation_admission_status"] == "ADMITTED"


def test_teacher_admitted_requires_output_specific_evidence_not_bare_weight_license():
    """Only DeepSeek V4.1-Flash has TEACHER_USE_ADMITTED this phase --
    verify its evidence specifically names output/training/distillation
    use (not merely a permissive weight license), and verify no other
    reference achieves ADMITTED without an equivalent named clause."""
    for name, path in REFERENCE_ADMISSION_FILES.items():
        data = json.loads(path.read_text())
        if data["final_state"]["teacher_use_status"] == "ADMITTED":
            evidence_ref = data["final_state"]["teacher_use_evidence_reference"]
            assert evidence_ref, name
            lowered = evidence_ref.lower()
            assert "tos" in lowered or "terms of service" in lowered or "distillation" in lowered, (
                f"{name}: teacher_use_evidence_reference must cite output/training/distillation-specific "
                f"terms, not merely a general weight license -- got {evidence_ref!r}"
            )


# ── F: ADMITTED + access UNQUALIFIED never produces a "counts toward quorum" gate ──


def test_no_admitted_but_unqualified_reference_claims_quorum_counting():
    for name, path in REFERENCE_ADMISSION_FILES.items():
        data = json.loads(path.read_text())
        fs = data["final_state"]
        gate = data["gate"]
        if fs["reference_evaluation_admission_status"] == "ADMITTED" and fs["access_preflight_status"] not in (
            "QUALIFIED_FOR_FUTURE_EXECUTION", "PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK",
        ):
            assert "COUNTS_TOWARD_EXECUTION_QUORUM" not in gate or "DOES_NOT" in gate, (
                f"{name}: ADMITTED-but-access-UNQUALIFIED reference must not claim to count toward quorum "
                f"in its gate string -- got {gate!r}"
            )
            # Phase 21B.4.17.2: DeepSeek's gate uses the dedicated
            # public-eval/full-protocol-split wording (§11); every other
            # reference uses the plain "DOES_NOT_CURRENTLY_COUNT_TOWARD_EXECUTION_QUORUM" form.
            assert (
                "DOES_NOT_CURRENTLY_COUNT_TOWARD_EXECUTION_QUORUM" in gate
                or "DOES_NOT_CURRENTLY_COUNT_TOWARD_FULL_PROTOCOL_EXECUTION_QUORUM" in gate
            ), name


def test_review_required_gate_never_claims_counting():
    for name, path in REFERENCE_ADMISSION_FILES.items():
        data = json.loads(path.read_text())
        if data["final_state"]["reference_evaluation_admission_status"] == "REVIEW_REQUIRED":
            assert "DOES_NOT_COUNT_TOWARD_EXECUTION_QUORUM" in data["gate"], name


# ── J: GLM remains REVIEW_REQUIRED unless independently resolved ───────


def test_glm_5_3_remains_review_required(registry):
    glm = next(r for r in registry.frontier_references if r["reference_name"] == "GLM-5.3 (flagship)")
    assert glm["license_or_terms_status"] == "REVIEW_REQUIRED"
    assert glm["reference_evaluation_admission_status"] == "REVIEW_REQUIRED"
    assert glm["access_preflight_status"] == "UNQUALIFIED"


# ═══════════════════════════════════════════════════════════════════════
# Phase 21B.4.17.2: Frontier Private-Holdout + Access-Gate Fail-Closed
# Closure (remaining letters). J (no API/GPU/inference execution) and L
# (Phase 21C unauthorized) are already proven by
# test_no_frontier_api_call_code_introduced /
# test_no_gpu_allocation_code_introduced /
# test_no_model_weight_download_code_introduced and
# test_phase_21c_still_unauthorized_and_frontier_lock_present above.
# ═══════════════════════════════════════════════════════════════════════


# ── C: public-eval vs private-holdout separately represented ───────────


def test_deepseek_public_and_private_compatibility_separately_represented():
    data = json.loads(REFERENCE_ADMISSION_FILES["DeepSeek V4.1-Flash"].read_text())
    h = data["H_private_holdout_compatibility"]
    assert "public_evaluation_compatibility" in h
    assert "private_holdout_compatibility" in h
    assert h["public_evaluation_compatibility"]["status"] == "PERMITTED"
    assert h["private_holdout_compatibility"]["status"] == "REVIEW_REQUIRED"
    assert h["public_evaluation_compatibility"]["status"] != h["private_holdout_compatibility"]["status"]


# ── D: model-release identity vs exact HF revision kept distinct ───────


def test_deepseek_api_model_identity_distinguishes_release_from_exact_revision():
    data = json.loads(REFERENCE_ADMISSION_FILES["DeepSeek V4.1-Flash"].read_text())
    identity = data["K_access_paths"]["first_party_api"]["model_identity_precision"]
    assert identity["model_release_identity"].startswith("MATCHES_DEEPSEEK_V4_1_FLASH")
    assert identity["exact_hosted_revision"].startswith("NOT_PROVIDER_EXPOSED")
    # must NOT claim the pinned HF revision itself is what the phrase asserts as exposed
    assert "is exposed" not in identity["exact_hosted_revision"].lower()
    assert "provider exposes" not in identity["exact_hosted_revision"].lower()


# ── G: MiniMax correction remains unchanged ─────────────────────────────


def test_minimax_correction_still_in_place(registry):
    minimax = next(r for r in registry.frontier_references if r["reference_name"] == "MiniMax M3")
    assert minimax["license_or_terms_status"] == "REVIEW_REQUIRED"
    assert minimax["reference_evaluation_admission_status"] == "REVIEW_REQUIRED"
    assert minimax["access_preflight_status"] == "UNQUALIFIED"


# ── H: Mistral teacher correction remains unchanged ─────────────────────


def test_mistral_teacher_correction_still_in_place(registry):
    mistral = next(r for r in registry.frontier_references if r["reference_name"] == "Mistral Large 3")
    assert mistral["reference_evaluation_admission_status"] == "ADMITTED"
    assert mistral["teacher_use_status"] == "NOT_EVALUATED"
    assert mistral["access_preflight_status"] == "UNQUALIFIED"


# ── I: GLM/Qwen/Kimi states remain unchanged ────────────────────────────


def test_qwen_and_kimi_states_unchanged(registry):
    qwen_max = next(r for r in registry.frontier_references if r["reference_name"] == "Qwen3.8-Max")
    assert qwen_max["reference_evaluation_admission_status"] == "REVIEW_REQUIRED"
    assert qwen_max["access_preflight_status"] == "UNQUALIFIED"

    kimi = next(r for r in registry.frontier_references if r["reference_name"] == "Kimi K3")
    assert kimi["reference_evaluation_admission_status"] == "ADMITTED"
    assert kimi["access_preflight_status"] == "UNQUALIFIED"


# =========================================================================
# Phase 21B.4.18: quorum-recovery blocker research + machine-enforced
# promotion gate hardening. See orca/eval/frontier_reference_admission_
# quorum.py's Phase 21B.4.18 docstring addendum and candidate_registry.py's
# matching addendum for the full design rationale.
# =========================================================================


def _passing_evidence(**overrides) -> dict:
    base = {
        "reference_name": "Synthetic",
        "organization": "SyntheticOrg",
        "reference_evaluation_admission_status": "ADMITTED",
        "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION",
        "license_or_terms_status": "CLEAR",
        "evidence_retention_status": "PERMITTED",
        "automated_evaluation_status": "CLEAR",
        "private_holdout_status": "PERMITTED",
        "access_path_identified": True,
        "model_identity_attributable": True,
        "non_financial_blocker_status": "NONE",
    }
    base.update(overrides)
    return base


# ── F: naked access status string alone cannot force quorum counting ────


def test_naked_status_string_without_evidence_cannot_count():
    """A dict claiming QUALIFIED_FOR_FUTURE_EXECUTION with no supporting
    evidence fields at all must not count -- compute_admission_quorum()
    must never trust the status string alone."""
    forged = {
        "reference_name": "Forged",
        "organization": "ForgedOrg",
        "reference_evaluation_admission_status": "ADMITTED",
        "access_preflight_status": "QUALIFIED_FOR_FUTURE_EXECUTION",
    }
    report = compute_admission_quorum([forged])
    assert report.quorum_counting_count == 0
    assert report.quorum_counting_references == ()
    assert not _entry_passes_full_protocol_validation(forged)


# ── G: terms REVIEW_REQUIRED cannot count ────────────────────────────────


def test_terms_review_required_cannot_count():
    entry = _passing_evidence(license_or_terms_status="REVIEW_REQUIRED")
    report = compute_admission_quorum([entry])
    assert report.quorum_counting_count == 0


# ── H: evidence-retention REVIEW_REQUIRED cannot count ──────────────────


def test_evidence_retention_review_required_cannot_count():
    entry = _passing_evidence(evidence_retention_status="REVIEW_REQUIRED")
    report = compute_admission_quorum([entry])
    assert report.quorum_counting_count == 0


# ── I: unattributable model identity cannot count ───────────────────────


def test_unattributable_model_identity_cannot_count():
    entry = _passing_evidence(model_identity_attributable=False)
    report = compute_admission_quorum([entry])
    assert report.quorum_counting_count == 0


# ── J: missing access path cannot count ──────────────────────────────────


def test_missing_access_path_cannot_count():
    entry = _passing_evidence(access_path_identified=False)
    report = compute_admission_quorum([entry])
    assert report.quorum_counting_count == 0


# ── additional evidence-dimension tamper coverage ────────────────────────


def test_automated_evaluation_not_clear_cannot_count():
    entry = _passing_evidence(automated_evaluation_status="REVIEW_REQUIRED")
    report = compute_admission_quorum([entry])
    assert report.quorum_counting_count == 0


def test_private_holdout_not_permitted_cannot_count():
    entry = _passing_evidence(private_holdout_status="REVIEW_REQUIRED")
    report = compute_admission_quorum([entry])
    assert report.quorum_counting_count == 0


def test_unresolved_non_financial_blocker_cannot_count():
    entry = _passing_evidence(non_financial_blocker_status="TERMS_AMBIGUITY")
    report = compute_admission_quorum([entry])
    assert report.quorum_counting_count == 0


# ── K: only zero-cash unresolved MAY still allow READY_PENDING ──────────


def test_only_zero_cash_unresolved_still_counts():
    """A reference passing EVERY non-financial dimension, with only the
    status itself expressing 'pending a fresh zero-cash check', must
    still be accepted as counting -- that is exactly what
    PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK means."""
    entry = _passing_evidence(access_preflight_status="PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK")
    report = compute_admission_quorum([entry])
    assert report.quorum_counting_count == 1
    assert _entry_passes_full_protocol_validation(entry)


# ── registry-level: schema rejects a forged counting status ─────────────


def test_registry_rejects_reference_claiming_readiness_without_evidence():
    """Phase 21B.4.18 §7: a reference cannot even LOAD into a valid
    registry while claiming a counting access_preflight_status unless
    its own recorded evidence actually supports it."""
    data = json.loads(REGISTRY_PATH.read_text())
    tampered = json.loads(json.dumps(data))
    deepseek = next(r for r in tampered["frontier_references"] if r["reference_name"] == "DeepSeek V4.1-Flash")
    deepseek["access_preflight_status"] = "QUALIFIED_FOR_FUTURE_EXECUTION"
    # private_holdout_status is left REVIEW_REQUIRED -- this must fail.
    with pytest.raises(RegistrySchemaError, match="full-protocol access validation"):
        CandidateExecutionRegistry.from_dict(tampered)


def test_registry_rejects_full_protocol_access_validation_mismatch():
    """A reference honestly UNQUALIFIED must never carry
    full_protocol_access_validation=PASSED -- the audit field must agree
    with the status it accompanies."""
    data = json.loads(REGISTRY_PATH.read_text())
    tampered = json.loads(json.dumps(data))
    deepseek = next(r for r in tampered["frontier_references"] if r["reference_name"] == "DeepSeek V4.1-Flash")
    assert deepseek["access_preflight_status"] == "UNQUALIFIED"
    deepseek["full_protocol_access_validation"] = "PASSED"
    with pytest.raises(RegistrySchemaError, match="full_protocol_access_validation"):
        CandidateExecutionRegistry.from_dict(tampered)


# ── Phase 21B.4.18 promotion-gate evidence fields present on all six ────


def test_all_six_references_carry_promotion_gate_evidence_fields(registry):
    required = (
        "automated_evaluation_status", "private_holdout_status",
        "access_path_identified", "model_identity_attributable",
        "non_financial_blocker_status", "full_protocol_access_validation",
    )
    for entry in registry.frontier_references:
        for field in required:
            assert field in entry, f"{entry['reference_name']} missing {field}"


def test_schema_version_bumped_to_v6():
    assert REGISTRY_SCHEMA_VERSION == "genesis-candidate-execution-registry-v6"


# ── Phase 21B.4.18 quorum-recovery research: no reference was fake-promoted ──


def test_no_reference_promoted_to_counting_status_this_phase(registry):
    """§20/§28: none of the six references may claim a counting
    access_preflight_status this phase -- research narrowed blockers but
    did not resolve any reference's full non-financial evidence set."""
    for entry in registry.frontier_references:
        assert entry["access_preflight_status"] in ("UNQUALIFIED", "BLOCKED", "NOT_TESTED"), entry["reference_name"]
        assert entry["full_protocol_access_validation"] == "FAILED", entry["reference_name"]
    report = compute_admission_quorum(list(registry.frontier_references))
    assert report.quorum_counting_count == 0
    assert report.quorum_status == "QUORUM_BLOCKED"


def test_qwen_private_holdout_improved_with_primary_source_evidence(registry):
    """Phase 21B.4.18 §14: strong direct primary-source evidence
    (Alibaba Cloud Model Studio's own 'Customer data policy' and FAQ
    page) narrows Qwen3.8-Max's private-holdout blocker, even though the
    reference does not reach full-protocol counting this phase (terms
    ambiguity and mutable identity remain unresolved)."""
    qwen_max = next(r for r in registry.frontier_references if r["reference_name"] == "Qwen3.8-Max")
    assert qwen_max["private_holdout_status"] == "PERMITTED"
    assert qwen_max["reference_evaluation_admission_status"] == "REVIEW_REQUIRED"
    assert qwen_max["model_identity_attributable"] is False


def test_kimi_hosted_api_private_holdout_confirmed_blocked(registry):
    """Phase 21B.4.18 §10: live re-verification of platform.kimi.ai's own
    Terms of Service §4 (Content) confirms the hosted API trains on
    Customer Content by default with no self-service opt-out -- only a
    negotiated enterprise arrangement, which this phase does not pursue."""
    kimi = next(r for r in registry.frontier_references if r["reference_name"] == "Kimi K3")
    assert kimi["private_holdout_status"] == "BLOCKED"
    assert "WRITTEN_PROVIDER_CLARIFICATION_REQUIRED" in kimi["non_financial_blocker_status"]


def test_mistral_holdout_path_resolvable_by_provider_setting_not_exercised(registry):
    """Phase 21B.4.18 §9: Mistral's own help-center article establishes an
    Admin-panel opt-out toggle exists for API/Studio training use, but
    this phase does not exercise it (no provider account action
    authorized) -- private_holdout_status stays REVIEW_REQUIRED."""
    mistral = next(r for r in registry.frontier_references if r["reference_name"] == "Mistral Large 3")
    assert mistral["private_holdout_status"] == "REVIEW_REQUIRED"
    assert "PROVIDER_ACCOUNT_SETTING_REQUIRED" in mistral["non_financial_blocker_status"]


# ── Phase 21B.4.18 blocker/clarification artifacts exist ────────────────


def test_blocker_matrix_artifact_exists():
    path = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_REFERENCE_BLOCKER_MATRIX_2026-09-24.md"
    assert path.is_file()
    text = path.read_text()
    for name in EXPECTED_REFERENCE_NAMES:
        assert name in text


def test_provider_clarification_artifact_exists_and_sends_nothing():
    path = REPO_ROOT / "docs/orneur/phase-21/evidence/GENESIS_FRONTIER_REFERENCE_PROVIDER_CLARIFICATIONS_2026-09-24.md"
    assert path.is_file()
    text = path.read_text()
    assert "NO message is sent" in text or "Messages sent: NO" in text or "not sent" in text.lower()


def test_access_matrix_v2_artifact_exists():
    path = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_REFERENCE_ACCESS_MATRIX_2026-09-24.md"
    assert path.is_file()


# ── Phase 21C / Genesis program-state regression lock ────────────────────


def test_phase_21c_still_not_authorized():
    text = (REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_REFERENCE_BLOCKER_MATRIX_2026-09-24.md").read_text()
    assert "PHASE 21C" in text
    assert "NOT AUTHORIZED" in text
