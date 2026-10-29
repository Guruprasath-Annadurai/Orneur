"""TRAIN-2 acceptance-condition evidence (synthetic dry-run locks remain false).

evidence_required: A synthetic dry-run log showing corpus, qualification,
model-selection, GPU, and training locks still false afterward.

This suite validates the committed SHA-pinned dry-run sample and the live
authorization lock snapshot. The scrubbed live CLI path is covered by
``tests/test_trainprep_cli.py`` in CI and is intentionally not invoked here:
in-process dry-run trips SyntheticOnlyGuard once ``tokenizers`` (or similar)
is already imported by earlier suite modules.

Does not train, allocate GPU, generate corpus, or flip authorization files.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.train.dryrun import cli
from orca.train.dryrun.canon import file_sha256, hash_obj
from orca.rse.imp1 import locks as L

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "docs/orneur/status/trainprep/dryrun_result.json"

_LOCK_NAMES = (
    "corpus_generation_authorized",
    "qualification_authorized",
    "model_selection_authorized",
    "gpu_authorized",
    "provider_authorized",
    "spending_authorized",
    "training_authorized",
)


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
    for name in _LOCK_NAMES:
        assert functions[name] is False, name
    assert auth["locks_after"]["training_authorization_status"] == "NOT_AUTHORIZED"
    assert doc["gate_probe"] == {"authorized": False, "reasons": ["NOT_AUTHORIZED"]}
    assert doc["lock"]["structure_ok"] is True
    assert doc["lock"]["path"] == "requirements/train.txt"
    assert doc["runs"]["zero_budget"]["status"] == "REFUSED"


def test_train2_live_lock_snapshot_matches_denied_posture():
    snap = cli.lock_snapshot(REPO)
    assert cli.locks_all_denied(snap)
    assert snap["training_authorization_status"] == "NOT_AUTHORIZED"
    for name in _LOCK_NAMES:
        assert snap["functions"][name] is False, name
    assert L.corpus_generation_authorized() is False
    assert L.qualification_authorized() is False
    assert L.model_selection_authorized() is False
    assert L.gpu_authorized() is False
    assert L.training_authorized() is False
    assert L.spending_authorized() is False
    assert L.provider_authorized() is False


def test_train2_sample_auth_hashes_match_committed_authorization_files():
    import orca.train.authorization as A

    doc = json.loads(SAMPLE.read_text(encoding="utf-8"))
    after = doc["authorization"]["locks_after"]
    assert after["training_authorization_sha256"] == file_sha256(REPO / A.RECORD_PATH)
    assert after["authorization_json_sha256"]["TRAINING_AUTHORITY_REGISTRY.json"] == file_sha256(
        REPO / A.REGISTRY_PATH
    )


def test_train2_gate_probe_denies_without_writing_state(tmp_path, monkeypatch):
    import orca.config as orca_config

    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "home")
    before = cli.lock_snapshot(REPO)
    probe = cli.gate_probe(REPO, "a" * 40, cli.Plan())
    assert probe == {"authorized": False, "reasons": ["NOT_AUTHORIZED"]}
    assert cli.lock_snapshot(REPO) == before
    assert not (tmp_path / "home").exists()
