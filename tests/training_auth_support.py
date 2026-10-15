"""Test-only helpers: build a SYNTHETIC TrainingGrant for tests of the training pipeline that are about something other than authorization
(dataset snapshots, ordering of model/dataset loading, identity validation). The gate itself is exercised, with real signature verification and
synthetic keys, in tests/test_training_authorization_gate.py. These helpers are never autouse and are never imported by production code."""
from __future__ import annotations

from pathlib import Path

import orca.train.authorization as A

ENV = "SELF_HOSTED_GPU"


def synthetic_grant(cfg, *, train_path=None, eval_path=None, environment_class: str = ENV) -> A.TrainingGrant:
    from orca.train.config import resolve_training_data_inputs

    if train_path is None:
        resolved = resolve_training_data_inputs(cfg)
        train_path = resolved.train_path
        eval_path = resolved.eval_path if eval_path is None else eval_path
    train_sha = A.file_sha256(train_path) if Path(train_path).is_file() else "0" * 64
    eval_sha = A.file_sha256(eval_path) if eval_path is not None and Path(eval_path).is_file() else None
    return A.TrainingGrant(
        authorization_id="tauth-" + "0" * 16, key_id="synthetic-test-key", record_sha256="0" * 64, run_slot=0,
        expires_at="2099-01-01T00:00:00Z", max_wall_clock_minutes=1, cfg_fingerprint=A._cfg_fingerprint(cfg),
        train_sha256=train_sha, eval_sha256=eval_sha, environment_class=environment_class, _seal=A._SEAL,
    )


def grant_for_manifest(cfg, manifest) -> A.TrainingGrant:
    """Grant matching the run-scoped snapshot files a canonical manifest points at (or the config's own files for a generic run)."""
    snaps = getattr(manifest, "dataset_snapshot_paths", None) or {}
    if snaps.get("train"):
        return synthetic_grant(cfg, train_path=snaps["train"], eval_path=snaps.get("validation"))
    return synthetic_grant(cfg)


def stub_authorize(monkeypatch) -> None:
    """Replace finetune.train()'s call to the gate with a synthetic grant for THIS test only."""
    monkeypatch.setattr("orca.train.finetune.authorize_training", lambda cfg, **kw: synthetic_grant(cfg))
