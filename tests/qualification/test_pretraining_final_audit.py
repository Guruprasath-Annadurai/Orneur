"""Independent final pretraining foundation audit tests.

Authority: Antigravity — Independent Qualification Authority
Candidate: PR #140 (HEAD 98069d833051c18a46f3fcfd42011cf7c83f7f6c)
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
    parse_pytest_summary,
)

# --- GATE B DEFECT REPRODUCTIONS ---

def test_reproduce_p1_mixed_passes_and_skips_qualifies_c02():
    """P1 Reproduction: 12 passed + 22 skipped qualifies without refusal."""
    verdict = classify_probe(
        exit_code=0,
        stdout="12 passed, 22 skipped in 0.73s\n",
        expected_candidate_sha="98069d8",
        recorded_candidate_sha="98069d8",
    )
    # The vulnerability: classify_probe issues passed_probe=True!
    assert verdict.passed_probe is True
    assert verdict.counts.passed == 12
    assert verdict.counts.skipped == 22
    assert verdict.refusal_codes == ()


def test_reproduce_p2_missing_candidate_sha_silent_pass():
    """P2 Reproduction: omitted or None candidate SHA fails to trigger refusal."""
    verdict = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.2s\n",
        expected_candidate_sha="98069d8",
        recorded_candidate_sha=None,
    )
    # The vulnerability: missing recorded SHA silently passes without CANDIDATE_SHA_MISMATCH
    assert verdict.passed_probe is True
    assert "CANDIDATE_SHA_MISMATCH" not in verdict.refusal_codes


# --- GATE A STALE EVIDENCE & DIGEST REPRODUCTIONS ---

def test_gate_a_candidate_sha_lag_in_probes_and_matrix():
    """Gate A: Probe and matrix documents record engineering SHA ad2b26f, lagging HEAD 98069d8."""
    matrix_path = CANDIDATE_ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json"
    probes_path = CANDIDATE_ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_VERIFICATION_PROBES.json"
    
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    probes = json.loads(probes_path.read_text(encoding="utf-8"))
    
    # Both documents record ad2b26f, NOT the actual commit tip 98069d8
    assert matrix["candidate_sha"] == "ad2b26fe054cad45c33f60da469fdbff31a9f652"
    assert probes["candidate_sha"] == "ad2b26fe054cad45c33f60da469fdbff31a9f652"


def test_gate_a_stale_implementation_digest_for_pipeline():
    """Gate A: orca/genesis/data/pipeline.py was modified in 98069d8, causing probe digest to be stale."""
    probes_path = CANDIDATE_ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_VERIFICATION_PROBES.json"
    probes = json.loads(probes_path.read_text(encoding="utf-8"))
    
    recorded_digest = probes["probes"]["DATA-1"]["implementation_sha256"]["orca/genesis/data/pipeline.py"]
    
    pipeline_file = CANDIDATE_ROOT / "orca/genesis/data/pipeline.py"
    actual_digest = hashlib.sha256(pipeline_file.read_bytes()).hexdigest()
    
    # Discrepancy proves the evidence in the candidate is stale relative to its own HEAD
    assert recorded_digest != actual_digest
    assert recorded_digest == "2a6d6f8ed1e99f5aeeaaecabfede9ad265086b2d9157cb0c433ef3f130e4ee7a"
    assert actual_digest == "7a846eccbefcc0b510772cef4767873889c9a4b7cdeeda00a0b2736f8968f548"


# --- GATE E & F INVARIANTS ---

def test_formal_acceptance_ledger_remains_strictly_empty():
    ledger_path = CANDIDATE_ROOT / "docs/orneur/acceptance/acceptance_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger == []


def test_authority_registry_remains_empty():
    reg_path = CANDIDATE_ROOT / "docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    assert reg.get("records") == []


def test_training_authorization_remains_not_authorized():
    auth_path = CANDIDATE_ROOT / "docs/orneur/authorization/TRAINING_AUTHORIZATION.json"
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    assert auth["status"] == "NOT_AUTHORIZED"
    assert auth["permissions"]["gpu_allowed"] is False
    assert auth["limits"]["max_spend_usd"] == 0
