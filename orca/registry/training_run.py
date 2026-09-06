"""
Training run manifest -- immutable provenance record for a single training
run. Answers: what code, what config, what data, what hardware, what seed,
produced this checkpoint, and (if resumed) from what parent.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id

TRAINING_RUN_DIR = ORCA_HOME / "registry" / "training_runs"
TRAINING_RUN_DIR.mkdir(parents=True, exist_ok=True)


def _current_git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


@dataclass
class TrainingRunManifest:
    run_id: str
    model_id: str
    base_model: str
    dataset_manifest_ids: list[str]
    training_config: dict
    hyperparameters: dict
    seed: int | None
    precision: str
    hardware_info: str
    git_sha: str = field(default_factory=_current_git_sha)
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    end_time: str | None = None
    checkpoint_outputs: list[str] = field(default_factory=list)
    failure_state: str | None = None   # None if still running/succeeded, else an error summary
    resume_parent_run_id: str | None = None
    resume_parent_checkpoint_id: str | None = None

    def manifest_path(self) -> Path:
        validate_id(self.run_id, "run_id")
        return TRAINING_RUN_DIR / f"{self.run_id}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    def mark_complete(self, checkpoint_id: str) -> None:
        self.end_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.checkpoint_outputs.append(checkpoint_id)
        self.save()

    def mark_failed(self, reason: str) -> None:
        self.end_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.failure_state = reason
        self.save()

    @classmethod
    def load(cls, run_id: str) -> "TrainingRunManifest":
        validate_id(run_id, "run_id")
        path = TRAINING_RUN_DIR / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No training run manifest for '{run_id}'")
        with open(path) as f:
            return cls(**json.load(f))


def list_runs(model_id: str | None = None) -> list[TrainingRunManifest]:
    runs = []
    for p in sorted(TRAINING_RUN_DIR.glob("*.json")):
        with open(p) as f:
            run = TrainingRunManifest(**json.load(f))
        if model_id is None or run.model_id == model_id:
            runs.append(run)
    return runs
