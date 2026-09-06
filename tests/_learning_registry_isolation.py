"""
Shared helper (not a conftest.py -- deliberately not repo-wide, see
test_learning_phase12.py's `_isolate_learning_registry_dirs` docstring for
why) for the three orca/learning test files to isolate
orca.registry.{dataset_manifest,training_run,checkpoint,evaluation_registry}
directories without touching the developer's real ~/.orca/registry/.
"""
from __future__ import annotations

from pathlib import Path


def isolate_registry_dirs(tmp_path: Path, monkeypatch) -> None:
    import orca.registry.dataset_manifest as dataset_manifest_mod
    import orca.registry.training_run as training_run_mod
    import orca.registry.checkpoint as checkpoint_mod
    import orca.registry.evaluation_registry as evaluation_registry_mod
    registry_tmp = tmp_path / "registry"
    monkeypatch.setattr(dataset_manifest_mod, "DATASET_MANIFEST_DIR", registry_tmp / "datasets")
    monkeypatch.setattr(training_run_mod, "TRAINING_RUN_DIR", registry_tmp / "training_runs")
    monkeypatch.setattr(checkpoint_mod, "CHECKPOINT_DIR", registry_tmp / "checkpoints")
    monkeypatch.setattr(evaluation_registry_mod, "EVALUATION_REGISTRY_DIR", registry_tmp / "evaluations")
    for d in (registry_tmp / "datasets", registry_tmp / "training_runs", registry_tmp / "checkpoints", registry_tmp / "evaluations"):
        d.mkdir(parents=True, exist_ok=True)
