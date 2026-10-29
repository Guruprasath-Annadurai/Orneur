"""TRAIN-2 acceptance-condition evidence (synthetic dry-run locks remain false).

evidence_required: A synthetic dry-run log showing corpus, qualification,
model-selection, GPU, and training locks still false afterward.

Uses in-process dry-run APIs and the committed sample result. Does not train,
allocate GPU, generate corpus, or flip authorization files.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.train.dryrun import cli
from orca.train.dryrun.canon import file_sha256, hash_obj
from orca.rse.imp1 import locks as L

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "docs/orneur/status/trainprep/dryrun_result.json"


def test_train2_committed_sample_is_synthetic_and_locks_remain_false():
    doc = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert doc["schema"] == cli.RESULT_SCHEMA
    assert doc["synthetic"] is True
    assert doc["status"] == "OK"
    assert len(doc["git_sha"]) == 40
    assert doc["result_sha256"] == hash_obj({k: v for k, v in doc.items() if k != "result_sha256"})
    auth = doc["authorization"]
    assert auth["authorization_files_byte_identical"] is True
    assert auth["locks_still_false"] is True
    assert auth["locks_before"] == auth["locks_after"]
    functions = auth["locks_after"]["functions"]
    for name in (
        "corpus_generation_authorized",
        "qualification_authorized",
        "model_selection_authorized",
        "gpu_authorized",
        "provider_authorized",
        "spending_authorized",
        "training_authorized",
    ):
        assert functions[name] is False, name
    assert auth["locks_after"]["training_authorization_status"] == "NOT_AUTHORIZED"
    assert doc["gate_probe"] == {"authorized": False, "reasons": ["NOT_AUTHORIZED"]}
    assert doc["lock"]["structure_ok"] is True
    assert doc["lock"]["path"] == "requirements/train.txt"


def test_train2_live_lock_snapshot_matches_denied_posture():
    snap = cli.lock_snapshot(REPO)
    assert cli.locks_all_denied(snap)
    assert L.corpus_generation_authorized() is False
    assert L.qualification_authorized() is False
    assert L.model_selection_authorized() is False
    assert L.gpu_authorized() is False
    assert L.training_authorized() is False
    assert L.spending_authorized() is False
    assert L.provider_authorized() is False


def test_train2_inprocess_dryrun_does_not_flip_locks(tmp_path):
    """In-process run_cli (no scrubbed child) still proves locks unchanged."""
    before = cli.lock_snapshot(REPO)
    out = tmp_path / "dryrun.json"
    code = cli.run_cli(["--max-steps", "4", "--max-tokens", "40", "--out", str(out)], repo=REPO)
    # Dirty trees refuse binding (exit 3); clean trees return 0.
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["synthetic"] is True
    assert doc["authorization"]["locks_still_false"] is True
    assert doc["authorization"]["authorization_files_byte_identical"] is True
    assert cli.lock_snapshot(REPO) == before
    if code == 0:
        assert doc["status"] in {"OK", "OK_BUDGET_LIMITED"}
        assert doc["gate_probe"]["authorized"] is False
    else:
        assert code == 3
        assert doc["status"] == "REFUSED_BINDING"


def test_train2_sample_auth_hashes_match_committed_authorization_files():
    import orca.train.authorization as A

    doc = json.loads(SAMPLE.read_text(encoding="utf-8"))
    after = doc["authorization"]["locks_after"]
    assert after["training_authorization_sha256"] == file_sha256(REPO / A.RECORD_PATH)
    assert after["authorization_json_sha256"]["TRAINING_AUTHORITY_REGISTRY.json"] == file_sha256(
        REPO / A.REGISTRY_PATH
    )
