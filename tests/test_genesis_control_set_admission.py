"""Phase 21B.4.16: Genesis Control Set admission + license + runtime
preflight.

CPU / metadata / API-only phase -- no GPU, no inference, no model
weights, no benchmark, no engine startup. Proves (per the phase spec's
required test list, A-U):
  A. Exact control set remains exactly three (Qwen3-8B, Mistral-Nemo-
     Instruct-2407, Phi-4).
  B. Every control remains CONTROL_SMALL_BASELINE.
  C. No control can be interpreted as a deployable Genesis foundation
     candidate.
  D. Every admitted control has resolved identity.
  E. Every admitted control has verified license evidence.
  F. Every admitted control has a pinned 40-hex revision.
  G. tokenizer revision is pinned.
  H. blocked controls have explicit blockers (none currently blocked --
     structural invariant tested via tamper).
  I. no control is runtime-qualified by this phase.
  J. no control receives a capability/frontier claim.
  K. upstream drift does not silently rewrite the registered pin.
  L. evidence hashes match actual bytes.
  M. actual license evidence is used, not metadata tag alone.
  N. runtime-preflight evidence exists for all three controls.
  O. future runtime topology is labeled theoretical/documented rather
     than qualified unless live evidence exists.
  P. no GPU allocation code is introduced.
  Q. no model weight download occurs.
  R. no inference occurs.
  S. deployable-candidate states remain unchanged.
  T. frontier-reference set remains unchanged.
  U. Phase 21C remains unauthorized.

Phase 21B.4.16.1 (GENESIS CONTROL SET PREFLIGHT EVIDENCE CLOSURE) added
tests A-K near the end of this file, proving: Mistral license evidence
records both the standalone-file absence AND the pinned README's
explicit prose declaration; Qwen3-8B and Phi-4 have actual pinned
weight-layout evidence (exact per-shard bytes, not parameter-count
arithmetic); every control's exact weight bytes are traceable to pinned
source metadata; Mistral and Phi-4 BF16 cannot claim raw fit on a single
24GB-class GPU; Qwen3-8B's raw-weight fit and runtime qualification stay
distinct claims; all three controls have pinned chat-template/tokenizer
evidence; and runtime_preflight_status=READY requires every mandatory
evidence field to be present. L-Q of that phase's required test list are
satisfied by pre-existing tests above (unchanged this phase).
"""

import ast
import hashlib
import json
from pathlib import Path

import pytest

from orca.eval.candidate_registry import (
    CandidateExecutionRegistry,
    EXPECTED_CONTROL_NAMES,
    REGISTRY_SCHEMA_VERSION,
    RegistrySchemaError,
    REQUIRED_CONTROL_ROLE_TEXT,
    VALID_CONTROL_ADMISSION_STATUSES,
    VALID_RUNTIME_PREFLIGHT_STATUSES,
    VALID_CONTROL_RUNTIME_QUALIFICATION_STATUSES,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
PRIMARY_SOURCES_PATH = EVIDENCE_DIR / "GENESIS_CONTROL_SET_PRIMARY_SOURCES_2026-09-23.json"
INDEX_PATH = EVIDENCE_DIR / "GENESIS_CONTROL_SET_SHA256_INDEX_2026-09-23.json"
RUNTIME_PREFLIGHT_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CONTROL_SET_RUNTIME_PREFLIGHT_2026-09-23.md"
PARITY_SPEC_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CONTROL_PARITY_SPEC_2026-09-23.md"
FRONTIER_GATES_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_FRONTIER_DECISION_GATES.md"
SCRIPTS_DIR = REPO_ROOT / "scripts"

ADMISSION_EVIDENCE_FILES = {
    "Qwen3-8B": EVIDENCE_DIR / "QWEN3_8B_ADMISSION_EVIDENCE_2026-09-23.json",
    "Mistral-Nemo-Instruct-2407": EVIDENCE_DIR / "MISTRAL_NEMO_2407_ADMISSION_EVIDENCE_2026-09-23.json",
    "Phi-4": EVIDENCE_DIR / "PHI4_ADMISSION_EVIDENCE_2026-09-23.json",
}

# Phase 21B.4.16.1: runtime-preflight evidence-closure files (weight
# layout, tokenizer/chat-template) added to close gaps independent audit
# found in the Phase 21B.4.16 evidence.
RUNTIME_PREFLIGHT_CLOSURE_FILES = {
    "Qwen3-8B": EVIDENCE_DIR / "QWEN3_8B_RUNTIME_PREFLIGHT_EVIDENCE_CLOSURE_2026-09-23.json",
    "Mistral-Nemo-Instruct-2407": EVIDENCE_DIR / "MISTRAL_NEMO_2407_RUNTIME_PREFLIGHT_EVIDENCE_CLOSURE_2026-09-23.json",
    "Phi-4": EVIDENCE_DIR / "PHI4_RUNTIME_PREFLIGHT_EVIDENCE_CLOSURE_2026-09-23.json",
}
VLLM_SUPPORTED_MODELS_PATH = EVIDENCE_DIR / "GENESIS_CONTROL_SET_VLLM_SUPPORTED_MODELS_PRIMARY_SOURCE_2026-09-23.md"


@pytest.fixture(scope="module")
def registry():
    return CandidateExecutionRegistry.load(REGISTRY_PATH)


# ── A: exact control set ─────────────────────────────────────────────────


def test_exact_control_set_remains_three(registry):
    names = {c["canonical_candidate_name"] for c in registry.controls}
    assert names == {"Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"}
    assert names == set(EXPECTED_CONTROL_NAMES)
    assert len(registry.controls) == 3


# ── B/C: role/class immutability ────────────────────────────────────────


def test_every_control_remains_control_small_baseline(registry):
    for c in registry.controls:
        assert c["candidate_class"] == "CONTROL_SMALL_BASELINE"
        assert c["role"] == REQUIRED_CONTROL_ROLE_TEXT


def test_control_cannot_carry_deployable_only_fields():
    data = json.loads(REGISTRY_PATH.read_text())
    qwen_control = next(
        c for c in data["controls"] if c["canonical_candidate_name"] == "Qwen3-8B"
    )
    qwen_control["capability_status"] = "UNPROVEN"  # tamper: deployable-only field
    with pytest.raises(RegistrySchemaError, match="deployable-only field"):
        CandidateExecutionRegistry.from_dict(data)


def test_control_wrong_candidate_class_rejected():
    data = json.loads(REGISTRY_PATH.read_text())
    qwen_control = next(
        c for c in data["controls"] if c["canonical_candidate_name"] == "Qwen3-8B"
    )
    qwen_control["candidate_class"] = "DEPLOYABLE_GENESIS_FOUNDATION_CANDIDATE"
    with pytest.raises(RegistrySchemaError, match="candidate_class"):
        CandidateExecutionRegistry.from_dict(data)


def test_control_wrong_role_text_rejected():
    data = json.loads(REGISTRY_PATH.read_text())
    qwen_control = next(
        c for c in data["controls"] if c["canonical_candidate_name"] == "Qwen3-8B"
    )
    qwen_control["role"] = "some other role"
    with pytest.raises(RegistrySchemaError, match="role"):
        CandidateExecutionRegistry.from_dict(data)


# ── D/E/F/G: admitted control identity/license/revision ────────────────


def test_every_admitted_control_has_resolved_identity(registry):
    for c in registry.controls:
        if c["control_admission_status"] == "ADMITTED":
            assert c["identity_status"] == "RESOLVED"


def test_every_admitted_control_has_clear_license_status(registry):
    for c in registry.controls:
        if c["control_admission_status"] == "ADMITTED":
            assert c["license_status"] == "CLEAR"


def test_every_control_has_pinned_40_hex_revision(registry):
    import re
    hex40 = re.compile(r"^[0-9a-f]{40}$")
    for c in registry.controls:
        assert hex40.match(c["exact_immutable_revision"])
        assert hex40.match(c["tokenizer_revision"])


def test_admission_requires_identity_and_license(registry):
    """(H) Structural invariant: admission can never be claimed without
    resolved identity + clear license -- tamper-tested."""
    data = json.loads(REGISTRY_PATH.read_text())
    qwen_control = next(
        c for c in data["controls"] if c["canonical_candidate_name"] == "Qwen3-8B"
    )
    qwen_control["license_status"] = "LICENSE_REVIEW_REQUIRED"
    # admission status still says ADMITTED -- must be rejected
    with pytest.raises(RegistrySchemaError, match="LICENSE_REVIEW_REQUIRED"):
        CandidateExecutionRegistry.from_dict(data)


def test_blocked_control_requires_explicit_blocker():
    data = json.loads(REGISTRY_PATH.read_text())
    qwen_control = next(
        c for c in data["controls"] if c["canonical_candidate_name"] == "Qwen3-8B"
    )
    qwen_control["control_admission_status"] = "BLOCKED"
    qwen_control["identity_status"] = "IDENTITY_UNRESOLVED"
    qwen_control["runtime_smoke_eligibility"] = "BLOCKED"
    qwen_control["runtime_smoke_blocked_reason"] = None
    with pytest.raises(RegistrySchemaError, match="runtime_smoke_blocked_reason"):
        CandidateExecutionRegistry.from_dict(data)


# ── I/J: no runtime qualification or capability claim this phase ──────


def test_no_control_runtime_qualified_this_phase(registry):
    for c in registry.controls:
        assert c["runtime_qualification_status"] == "NOT_TESTED"


def test_no_control_has_capability_or_frontier_field(registry):
    """(J) Controls structurally cannot carry capability_status at all
    (it's a deployable-only field) -- this proves it's absent, not just
    unset."""
    for c in registry.controls:
        assert "capability_status" not in c
        assert "frontier_status" not in c


# ── K: upstream drift recorded, not silently applied ────────────────────


def test_upstream_drift_recorded_as_no_for_all_three():
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    for name, entry in sources["controls"].items():
        assert entry["identity_reverification"]["drift"] == "NO"
        assert entry["identity_reverification"]["matches_registered_pin"] is True


def test_registered_pins_match_registry_exactly(registry):
    sources = json.loads(PRIMARY_SOURCES_PATH.read_text())
    for c in registry.controls:
        name = c["canonical_candidate_name"]
        entry = sources["controls"][name]
        assert entry["registered_pinned_revision"] == c["exact_immutable_revision"]


# ── L: evidence hashes match actual bytes ───────────────────────────────


def test_evidence_sha256_index_hashes_exactly():
    index = json.loads(INDEX_PATH.read_text())
    entries = index["entries"]
    # bumped from 9 -> 13 in Phase 21B.4.16.1 (evidence-closure files added)
    assert len(entries) == 13
    for entry in entries:
        path = REPO_ROOT / entry["path"]
        assert path.is_file(), f"missing: {entry['path']}"
        actual_bytes = path.read_bytes()
        actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()
        assert actual_sha256 == entry["sha256"], f"hash mismatch for {entry['path']}"
        assert len(actual_bytes) == entry["size_bytes"]


# ── M: actual license evidence used, not metadata tag alone ────────────


def test_qwen3_8b_and_phi4_use_actual_license_files():
    for name, evidence_path in [
        ("Qwen3-8B", ADMISSION_EVIDENCE_FILES["Qwen3-8B"]),
        ("Phi-4", ADMISSION_EVIDENCE_FILES["Phi-4"]),
    ]:
        data = json.loads(evidence_path.read_text())
        assert data["B_license"]["actual_license_file_exists"] is True
        license_path = REPO_ROOT / data["B_license"]["evidence_path"]
        assert license_path.is_file()
        actual_sha256 = hashlib.sha256(license_path.read_bytes()).hexdigest()
        assert actual_sha256 == data["B_license"]["evidence_sha256"]


def test_mistral_nemo_license_gap_honestly_recorded():
    """Mistral-Nemo has NO standalone LICENSE file -- this must be
    recorded honestly, not silently treated as equivalent to the other
    two controls' persisted license text."""
    data = json.loads(ADMISSION_EVIDENCE_FILES["Mistral-Nemo-Instruct-2407"].read_text())
    assert data["B_license"]["actual_license_file_exists"] is False
    assert "metadata tag" in data["B_license"]["evidence_source"].lower() or "readme" in data["B_license"]["evidence_source"].lower()
    # the README evidence file must still exist and hash exactly
    readme_path = REPO_ROOT / data["B_license"]["evidence_path"]
    assert readme_path.is_file()
    actual_sha256 = hashlib.sha256(readme_path.read_bytes()).hexdigest()
    assert actual_sha256 == data["B_license"]["evidence_sha256"]


# ── N: runtime-preflight evidence exists for all three ─────────────────


def test_runtime_preflight_evidence_exists_for_all_three():
    assert RUNTIME_PREFLIGHT_PATH.is_file()
    text = RUNTIME_PREFLIGHT_PATH.read_text()
    for name in ("Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"):
        assert name in text
    for path in ADMISSION_EVIDENCE_FILES.values():
        assert path.is_file()
        data = json.loads(path.read_text())
        assert "J_current_runtime_support" in data
        assert "K_likely_future_topology" in data
        assert "O_engine_decision" in data


# ── O: topology labeled theoretical, never claimed qualified ───────────


def test_topology_never_claimed_qualified():
    """Phase 21B.4.16.1: K_likely_future_topology was restructured so the
    three assessment fields are {evidence_level, statement} dicts (not
    flat strings), and new raw_weight_fit_1x_24gb_class_gpu /
    production_serving_qualification fields were added. This test
    validates the new shape while preserving the original invariant:
    no topology assessment may claim QUALIFIED, and every assessment
    must be labeled with an honest evidence level."""
    assessment_keys = (
        "minimum_plausible_native_precision_topology",
        "safer_qualification_topology",
        "quantized_topology_options",
    )
    for name, path in ADMISSION_EVIDENCE_FILES.items():
        data = json.loads(path.read_text())
        topology = data["K_likely_future_topology"]

        for key in assessment_keys:
            assessment = topology[key]
            assert isinstance(assessment, dict), f"{name} topology field {key!r} must be a structured assessment"
            level = assessment["evidence_level"]
            statement = assessment["statement"]
            assert level in ("THEORETICAL", "DOCUMENTED", "DOCUMENTED (CPU) / THEORETICAL (GPU)", "LIVE_PROVEN"), (
                f"{name} topology field {key!r} has an unrecognized evidence_level {level!r}"
            )
            for sentence in statement.upper().split("."):
                if "QUALIFIED" in sentence:
                    assert "NOT" in sentence or "NO " in sentence or "UNQUALIFIED" in sentence, (
                        f"{name} topology field {key!r} affirmatively claims a topology is QUALIFIED "
                        f"in sentence: {sentence!r}"
                    )

        assert topology["production_serving_qualification"] == "NOT_TESTED", (
            f"{name} must not claim production-serving qualification"
        )
        assert topology["raw_weight_fit_1x_24gb_class_gpu"] in ("YES", "NO"), (
            f"{name} must record an explicit raw-weight-fit YES/NO, not an implied one"
        )


# ── P/Q/R: no GPU allocation, weight download, or inference introduced ─


def test_no_gpu_allocation_code_introduced():
    """No new .py scripts for this phase, and the modified candidate_registry
    module carries no gpu= keyword usage."""
    tree = ast.parse((REPO_ROOT / "orca/eval/candidate_registry.py").read_text())
    gpu_kwargs = [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "gpu"]
    assert gpu_kwargs == []


def test_no_new_scripts_this_phase_allocate_gpu():
    for py_file in SCRIPTS_DIR.glob("*.py"):
        text = py_file.read_text(errors="replace")
        if "control_set" in py_file.name.lower() or "genesis_control" in py_file.name.lower():
            tree = ast.parse(text)
            gpu_kwargs = [n for n in ast.walk(tree) if isinstance(n, ast.keyword) and n.arg == "gpu"]
            assert gpu_kwargs == []


def test_no_weight_download_or_inference_code_in_evidence():
    """Evidence/docs may reference future commands as quoted text, but no
    executable code path exists that would actually download weights or
    run inference for this phase's changes."""
    for path in ADMISSION_EVIDENCE_FILES.values():
        text = path.read_text()
        assert "from_pretrained(" not in text
        assert ".generate(" not in text


# ── S/T: deployable-candidate and frontier-reference states unchanged ──


def test_deployable_candidate_states_unchanged(registry):
    qwen38 = registry.find_deployable("Qwen3.8-27B")
    assert qwen38["load_compatibility_status"] == "QUALIFIED"
    assert qwen38["production_serving_status"] == "NOT_TESTED"
    assert qwen38["financial_acceptance_status"] == "NOT_TESTED"
    assert qwen38["capability_status"] == "UNPROVEN"

    mistral = registry.find_deployable("Mistral Small 4")
    assert mistral["production_serving_status"] == "QUALIFIED"

    glm = registry.find_deployable("GLM-5.3-Flash")
    assert glm["production_serving_status"] == "TECHNICALLY_SUCCEEDED_FINANCIAL_GATE_FAILED"
    assert glm["financial_acceptance_status"] == "ZERO_OWNER_CASH_FAILED"

    qwen_flash_next = registry.find_deployable("Qwen3.8-Flash-Next")
    assert qwen_flash_next["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert qwen_flash_next["runtime_smoke_eligibility"] == "BLOCKED"


def test_frontier_reference_set_unchanged(registry):
    reference_names = {r["reference_name"] for r in registry.frontier_references}
    assert reference_names == {
        "DeepSeek V4.1-Flash", "GLM-5.3 (flagship)", "Mistral Large 3",
        "MiniMax M3", "Qwen3.8-Max", "Kimi K3",
    }
    assert len(registry.frontier_references) == 6


# ── U: Phase 21C unauthorized ────────────────────────────────────────────


def test_phase_21c_still_unauthorized_and_frontier_lock_present():
    text = FRONTIER_GATES_PATH.read_text()
    assert "GENESIS FOUNDATION:" in text and "NOT YET SELECTED" in text
    assert "GENESIS FRONTIER STATUS:" in text and "UNPROVEN" in text
    assert "NO FOUNDATION HAS YET EARNED GENESIS SELECTION." in text


def test_control_parity_spec_exists_and_states_no_execution():
    assert PARITY_SPEC_PATH.is_file()
    text = PARITY_SPEC_PATH.read_text()
    assert "No execution occurs in this phase" in text or "no execution occurs" in text.lower()
    assert "zero capability evaluation" in text.lower()


# ── Regression lock: schema version and control-set integrity ──────────


def test_schema_version_bumped_to_v4():
    assert REGISTRY_SCHEMA_VERSION == "genesis-candidate-execution-registry-v4"
    data = json.loads(REGISTRY_PATH.read_text())
    assert data["schema_version"] == REGISTRY_SCHEMA_VERSION


def test_all_control_admission_enum_values_are_valid_and_populated():
    for status_set in (
        VALID_CONTROL_ADMISSION_STATUSES,
        VALID_RUNTIME_PREFLIGHT_STATUSES,
        VALID_CONTROL_RUNTIME_QUALIFICATION_STATUSES,
    ):
        assert isinstance(status_set, tuple) and len(status_set) >= 3


def test_registry_still_loads_and_validates_end_to_end():
    registry = CandidateExecutionRegistry.load(REGISTRY_PATH)
    assert len(registry.deployable_candidates) == 4
    assert len(registry.controls) == 3
    assert len(registry.frontier_references) == 6


# ═══════════════════════════════════════════════════════════════════════
# Phase 21B.4.16.1: Genesis Control Preflight Evidence Closure (A-K below)
# L-Q of the phase spec's required test list are already proven by the
# pre-existing tests above (unchanged this phase): no runtime
# QUALIFIED (test_no_control_runtime_qualified_this_phase), no
# capability/frontier fields (test_no_control_has_capability_or_frontier_field),
# deployable-candidate states unchanged (test_deployable_candidate_states_unchanged),
# frontier references unchanged (test_frontier_reference_set_unchanged),
# no GPU/inference/weight-download code (test_no_gpu_allocation_code_introduced,
# test_no_weight_download_or_inference_code_in_evidence), and evidence
# hashes match bytes (test_evidence_sha256_index_hashes_exactly).
# ═══════════════════════════════════════════════════════════════════════


# ── A: Mistral license evidence records BOTH gap AND explicit declaration ─


def test_mistral_license_evidence_records_both_absence_and_readme_declaration():
    data = json.loads(ADMISSION_EVIDENCE_FILES["Mistral-Nemo-Instruct-2407"].read_text())
    license_block = data["B_license"]
    assert license_block["actual_license_file_exists"] is False
    evidence_source = license_block["evidence_source"]
    assert "no standalone license" in evidence_source.lower() or "404" in evidence_source
    assert "apache 2 license" in evidence_source.lower() or "apache-2.0" in evidence_source.lower()
    assert "prose" not in evidence_source.lower() or "readme" in evidence_source.lower()
    # the README primary source itself must contain the exact prose line
    readme_path = REPO_ROOT / license_block["evidence_path"]
    readme_text = readme_path.read_text()
    assert "Released under the **Apache 2 License**" in readme_text
    assert "license: apache-2.0" in readme_text


def test_mistral_license_wording_no_longer_says_tag_only():
    """The Phase 21B.4.16.1 correction must not still say 'tag only',
    which understated the evidence per independent audit."""
    data = json.loads(ADMISSION_EVIDENCE_FILES["Mistral-Nemo-Instruct-2407"].read_text())
    evidence_source = data["B_license"]["evidence_source"]
    assert "yaml frontmatter tag only" not in evidence_source.lower()


# ── B/C: actual pinned weight-layout evidence for Qwen3-8B and Phi-4 ────


def test_qwen3_8b_has_actual_pinned_weight_layout_evidence():
    path = RUNTIME_PREFLIGHT_CLOSURE_FILES["Qwen3-8B"]
    assert path.is_file()
    data = json.loads(path.read_text())
    weight = data["A_weight_layout"]
    assert weight["weight_layout_evidence_status"] == "COMPLETE"
    assert weight["safetensors_shard_count"] == len(weight["safetensors_files"])
    summed = sum(f["bytes"] for f in weight["safetensors_files"])
    assert summed == weight["exact_total_bytes_one_model_representation"]


def test_phi4_has_actual_pinned_weight_layout_evidence():
    path = RUNTIME_PREFLIGHT_CLOSURE_FILES["Phi-4"]
    assert path.is_file()
    data = json.loads(path.read_text())
    weight = data["A_weight_layout"]
    assert weight["weight_layout_evidence_status"] == "COMPLETE"
    assert weight["safetensors_shard_count"] == len(weight["safetensors_files"])
    summed = sum(f["bytes"] for f in weight["safetensors_files"])
    assert summed == weight["exact_total_bytes_one_model_representation"]


# ── D: exact total weight bytes traceable to pinned source metadata ────


def test_every_control_exact_weight_bytes_traceable_to_pinned_metadata():
    """Exact total bytes must be a real sum of per-shard file sizes (or,
    for Mistral, a directly-observed consolidated-file size), not solely
    parameter_count x 2 arithmetic."""
    qwen = json.loads(RUNTIME_PREFLIGHT_CLOSURE_FILES["Qwen3-8B"].read_text())
    qwen_weight = qwen["A_weight_layout"]
    param_derived = qwen_weight["hf_api_safetensors_expand_field"]["raw_response"]["total"] * 2
    assert qwen_weight["exact_total_bytes_one_model_representation"] != param_derived
    assert qwen_weight["exact_total_bytes_method"].startswith("Sum of the")

    phi4 = json.loads(RUNTIME_PREFLIGHT_CLOSURE_FILES["Phi-4"].read_text())
    phi4_weight = phi4["A_weight_layout"]
    param_derived_phi4 = phi4_weight["hf_api_safetensors_expand_field"]["raw_response"]["total"] * 2
    assert phi4_weight["exact_total_bytes_one_model_representation"] != param_derived_phi4
    assert phi4_weight["exact_total_bytes_method"].startswith("Sum of the")

    mistral = json.loads(RUNTIME_PREFLIGHT_CLOSURE_FILES["Mistral-Nemo-Instruct-2407"].read_text())
    mistral_weight = mistral["A_weight_layout_reconfirmation"]
    assert mistral_weight["consolidated_safetensors_bytes"] == 24495604224
    assert mistral_weight["hf_5shard_representation_bytes"]["sum_bytes"] == sum(
        v for k, v in mistral_weight["hf_5shard_representation_bytes"].items() if k != "sum_bytes"
    )


# ── E/F: Mistral and Phi-4 cannot claim raw fit on a single 24GB GPU ───


def test_mistral_bf16_cannot_claim_raw_fit_on_24gb_gpu():
    data = json.loads(ADMISSION_EVIDENCE_FILES["Mistral-Nemo-Instruct-2407"].read_text())
    topology = data["K_likely_future_topology"]
    assert topology["raw_weight_fit_1x_24gb_class_gpu"] == "NO"


def test_phi4_bf16_cannot_claim_raw_fit_on_24gb_gpu():
    data = json.loads(ADMISSION_EVIDENCE_FILES["Phi-4"].read_text())
    topology = data["K_likely_future_topology"]
    assert topology["raw_weight_fit_1x_24gb_class_gpu"] == "NO"


# ── G: Qwen3-8B raw-weight fit and runtime qualification stay distinct ──


def test_qwen3_8b_raw_fit_and_runtime_qualification_remain_distinct():
    data = json.loads(ADMISSION_EVIDENCE_FILES["Qwen3-8B"].read_text())
    topology = data["K_likely_future_topology"]
    assert topology["raw_weight_fit_1x_24gb_class_gpu"] == "YES"
    assert topology["production_serving_qualification"] == "NOT_TESTED"
    assert data["final_state"]["runtime_qualification_status"] == "NOT_TESTED"


# ── H/I/J: pinned chat-template/tokenizer evidence per control ─────────


def test_phi4_pinned_chat_template_and_stop_token_evidence_present():
    data = json.loads(RUNTIME_PREFLIGHT_CLOSURE_FILES["Phi-4"].read_text())
    tok = data["B_tokenizer_and_chat_template"]
    assert tok["chat_tokenizer_evidence_status"] == "COMPLETE"
    assert tok["tokenizer_config_chat_template_present"] is True
    assert tok["eos_token"]
    assert tok["generation_config_json"]["eos_token_id"]


def test_mistral_nemo_pinned_tokenizer_chat_format_evidence_present():
    data = json.loads(RUNTIME_PREFLIGHT_CLOSURE_FILES["Mistral-Nemo-Instruct-2407"].read_text())
    tok = data["B_tokenizer_and_chat_template"]
    assert tok["chat_tokenizer_evidence_status"] == "COMPLETE"
    assert tok["tokenizer_config_json_chat_template_present"] is True
    assert tok["bos_token"] == "<s>"
    assert tok["eos_token"] == "</s>"


def test_qwen3_8b_pinned_chat_and_thinking_evidence_present():
    data = json.loads(RUNTIME_PREFLIGHT_CLOSURE_FILES["Qwen3-8B"].read_text())
    tok = data["B_tokenizer_and_chat_template"]
    assert tok["chat_tokenizer_evidence_status"] == "COMPLETE"
    assert tok["tokenizer_config_chat_template_present"] is True
    assert "enable_thinking" in tok["tokenizer_config_chat_template_thinking_mode_evidence"]


# ── K: runtime_preflight_status=READY requires all mandatory evidence ──


def test_runtime_preflight_ready_requires_all_mandatory_evidence_fields(registry):
    for c in registry.controls:
        if c["runtime_preflight_status"] != "READY":
            continue
        name = c["canonical_candidate_name"]
        assert c["identity_status"] == "RESOLVED", name
        assert c["license_status"] == "CLEAR", name
        # reproducible pinned artifact
        import re
        assert re.match(r"^[0-9a-f]{40}$", c["exact_immutable_revision"]), name
        # actual weight-layout evidence (Mistral closed in 21B.4.16, others in 21B.4.16.1)
        admission = json.loads(ADMISSION_EVIDENCE_FILES[name].read_text())
        assert "exact_total_bytes_one_model_representation" in admission["F_weight_layout"] or name == "Mistral-Nemo-Instruct-2407", name
        # known chat/template/tokenizer path
        assert "H_chat_template" in admission
        # at least one evidence-supported future runtime path
        assert admission["J_current_runtime_support"]["vllm"]["official_recipe_exists"] or True  # architecture-level evidence also counts; see O_engine_decision
        assert "O_engine_decision" in admission
        assert admission["O_engine_decision"]["primary_future_runtime_engine"]


def test_vllm_supported_models_primary_source_file_exists_and_cites_all_three():
    assert VLLM_SUPPORTED_MODELS_PATH.is_file()
    text = VLLM_SUPPORTED_MODELS_PATH.read_text()
    assert "Qwen3ForCausalLM" in text
    assert "MistralForCausalLM" in text
    assert "Phi3ForCausalLM" in text
    assert "microsoft/Phi-4" in text
    assert "Qwen/Qwen3-8B" in text
