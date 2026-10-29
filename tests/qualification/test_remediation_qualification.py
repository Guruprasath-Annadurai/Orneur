"""Independent remediation qualification test suite for PR #140.

Authority: Antigravity — Independent Engineering, Security and Qualification Authority
Candidate: PR #140 (Code SHA 78e6ad65617741cd92af6df4b4a37543930e4ced, HEAD 97d4c83a16f56fca3c934cd7954ae8db6cfeb6d1)
CI: Run 40894646633 (9/9 green)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
import pytest

CANDIDATE_ROOT = Path(os.environ.get("CANDIDATE_PATH", "/home/pc/projects/Orneur-pr140-phase01")).resolve()
if str(CANDIDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(CANDIDATE_ROOT))

from orca.pretrain_foundation.probe_honesty import (
    classify_probe,
    is_complete_candidate_sha,
    normalize_candidate_sha,
    parse_pytest_summary,
)
from orca.genesis.data.pipeline import (
    CorpusBoundaryError,
    process_corpus,
    process_training_bound_corpus,
)
from orca.pretrain_foundation.corpus_controls import (
    CorpusControlError,
    training_bound_reader_kwargs,
)
from orca.train.authorization import TrainingNotAuthorized, authorize_training, require_grant
from orca.train.config import TrainingConfig
from orca.pretrain_foundation.training_freeze import (
    TrainingFreezeError,
    assert_unauthorized_execution_refused,
    build_freeze_package,
)

VALID_SHA = "78e6ad65617741cd92af6df4b4a37543930e4ced"
ALT_SHA = "a" * 40


# --- 1. RETEST P1: MIXED SKIPS & MANDATORY COVERAGE ---

def test_p1_remediation_refuses_mixed_passes_and_skips():
    """Verify 12 passed + 22 skipped now strictly refused with SKIPS_PRESENT."""
    v = classify_probe(
        exit_code=0,
        stdout="12 passed, 22 skipped in 0.73s\n",
        expected_candidate_sha=VALID_SHA,
        recorded_candidate_sha=VALID_SHA,
    )
    assert v.passed_probe is False
    assert "SKIPS_PRESENT" in v.refusal_codes


def test_p1_remediation_refuses_single_skip():
    """Verify 1 passed + 1 skipped strictly refused with SKIPS_PRESENT."""
    v = classify_probe(
        exit_code=0,
        stdout="1 passed, 1 skipped in 0.05s\n",
        expected_candidate_sha=VALID_SHA,
        recorded_candidate_sha=VALID_SHA,
    )
    assert v.passed_probe is False
    assert "SKIPS_PRESENT" in v.refusal_codes


def test_p1_remediation_refuses_skip_only():
    """Verify skip-only strictly refused with SKIP_ONLY and SKIPS_PRESENT."""
    v = classify_probe(
        exit_code=0,
        stdout="15 skipped in 0.05s\n",
        expected_candidate_sha=VALID_SHA,
        recorded_candidate_sha=VALID_SHA,
    )
    assert v.passed_probe is False
    assert "SKIP_ONLY" in v.refusal_codes
    assert "SKIPS_PRESENT" in v.refusal_codes


def test_p1_remediation_refuses_zero_collected():
    """Verify zero-collected strictly refused."""
    v = classify_probe(
        exit_code=0,
        stdout="collected 0 items\nno tests ran in 0.01s\n",
        expected_candidate_sha=VALID_SHA,
        recorded_candidate_sha=VALID_SHA,
    )
    assert v.passed_probe is False
    assert "ZERO_COLLECTED" in v.refusal_codes or "NO_PASSES" in v.refusal_codes


def test_p1_remediation_refuses_xfail_only():
    """Verify xfail-only strictly refused."""
    v = classify_probe(
        exit_code=0,
        stdout="5 xfailed in 0.10s\n",
        expected_candidate_sha=VALID_SHA,
        recorded_candidate_sha=VALID_SHA,
    )
    assert v.passed_probe is False
    assert "XFAIL_ONLY" in v.refusal_codes


# --- 2. RETEST P2: CANDIDATE SHA INTEGRITY ---

def test_p2_remediation_refuses_missing_recorded_sha():
    v = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.1s\n",
        expected_candidate_sha=VALID_SHA,
        recorded_candidate_sha=None,
    )
    assert v.passed_probe is False
    assert "CANDIDATE_SHA_MISSING" in v.refusal_codes


def test_p2_remediation_refuses_missing_expected_sha():
    v = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.1s\n",
        expected_candidate_sha=None,
        recorded_candidate_sha=VALID_SHA,
    )
    assert v.passed_probe is False
    assert "CANDIDATE_SHA_MISSING" in v.refusal_codes


def test_p2_remediation_refuses_empty_sha():
    v = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.1s\n",
        expected_candidate_sha="   ",
        recorded_candidate_sha=VALID_SHA,
    )
    assert v.passed_probe is False
    assert "CANDIDATE_SHA_MISSING" in v.refusal_codes


def test_p2_remediation_refuses_truncated_sha():
    v = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.1s\n",
        expected_candidate_sha="78e6ad6",
        recorded_candidate_sha="78e6ad6",
    )
    assert v.passed_probe is False
    assert "CANDIDATE_SHA_MALFORMED" in v.refusal_codes


def test_p2_remediation_refuses_invalid_hex():
    v = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.1s\n",
        expected_candidate_sha="z" * 40,
        recorded_candidate_sha="z" * 40,
    )
    assert v.passed_probe is False
    assert "CANDIDATE_SHA_MALFORMED" in v.refusal_codes


def test_p2_remediation_refuses_mismatched_sha():
    v = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.1s\n",
        expected_candidate_sha=VALID_SHA,
        recorded_candidate_sha=ALT_SHA,
    )
    assert v.passed_probe is False
    assert "CANDIDATE_SHA_MISMATCH" in v.refusal_codes


def test_p2_remediation_accepts_valid_40_hex_case_insensitive():
    v = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.1s\n",
        expected_candidate_sha=VALID_SHA.lower(),
        recorded_candidate_sha=VALID_SHA.upper(),
    )
    assert v.passed_probe is True
    assert v.refusal_codes == ()


# --- 3. EVIDENCE SYNCHRONIZATION ---

def test_evidence_manifest_and_pipeline_digest_synchronized():
    matrix_path = CANDIDATE_ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json"
    probes_path = CANDIDATE_ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_VERIFICATION_PROBES.json"
    report_path = CANDIDATE_ROOT / "docs/orneur/programmes/pretraining-closure/engineering/ORNEUR_PRETRAINING_FOUNDATION_FINAL_MASTER_ENGINEERING_REPORT.json"
    
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    probes = json.loads(probes_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    
    assert matrix["candidate_sha"] == VALID_SHA
    assert probes["candidate_sha"] == VALID_SHA
    assert report["final_engineering_sha"] == VALID_SHA
    
    pipeline_file = CANDIDATE_ROOT / "orca/genesis/data/pipeline.py"
    actual_hash = hashlib.sha256(pipeline_file.read_bytes()).hexdigest()
    recorded_hash = probes["probes"]["DATA-1"]["implementation_sha256"]["orca/genesis/data/pipeline.py"]
    
    assert actual_hash == recorded_hash


# --- 4. OPERATIONAL CALL-CHAIN CONTROLS ---

def test_operational_corpus_rejects_remote(tmp_path):
    with pytest.raises(CorpusBoundaryError, match="remote corpus origin"):
        process_corpus("https://evil.com/corpus.jsonl", tmp_path / "out", num_shards=1)


def test_operational_training_bound_reader_rejects_kwarg_bypass(tmp_path):
    path = tmp_path / "in.jsonl"
    path.write_text(json.dumps({"text": "test", "license": "Apache-2.0"}) + "\n", encoding="utf-8")
    with pytest.raises(CorpusControlError, match="cannot disable require_license"):
        training_bound_reader_kwargs(require_license=False)


def test_operational_training_auth_fails_closed(tmp_path, monkeypatch):
    import orca.config as orca_config
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    cfg = TrainingConfig()
    train_file = tmp_path / "t.jsonl"
    train_file.write_text("{}\n", encoding="utf-8")
    cfg.train_file = str(train_file)
    with pytest.raises(TrainingNotAuthorized):
        authorize_training(cfg, environment_class="SELF_HOSTED_GPU")


def test_operational_freeze_package_refuses_unauthorized_execution():
    pkg = build_freeze_package(CANDIDATE_ROOT, code_sha=VALID_SHA, model_configuration={"arch": "test"})
    assert pkg.status == "NOT_FROZEN"
    assert pkg.training_authorization == "NO-GO"
    with pytest.raises(TrainingFreezeError, match="unauthorized"):
        assert_unauthorized_execution_refused(pkg, execute_requested=True)


# --- 5. GOVERNANCE INVARIANTS ---

def test_acceptance_ledger_remains_strictly_empty():
    ledger_path = CANDIDATE_ROOT / "docs/orneur/acceptance/acceptance_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger == []


def test_authority_registry_remains_empty():
    reg_path = CANDIDATE_ROOT / "docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    assert reg.get("records") == []
