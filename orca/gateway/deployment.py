"""
ModelDeployment -- the missing entity between ModelSpec/Checkpoint (Phase
1's orca/registry/) and an actual servable endpoint. A model may have
multiple deployments (e.g. Orneur Novus served both by a local Ollama
instance and, later, a vLLM GPU node) -- model identity must never equal
endpoint identity.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id
from orca.registry.model_spec import LifecycleState

DEPLOYMENT_DIR = ORCA_HOME / "registry" / "deployments"
DEPLOYMENT_DIR.mkdir(parents=True, exist_ok=True)


class DeploymentHealth(str, Enum):
    """
    Distinct from LifecycleState (is this checkpoint good enough to
    promote?) and from ArtifactAvailability (does the weight file exist?).
    This is: is this SPECIFIC serving endpoint currently able to answer
    requests? A deployment can be lifecycle=PRODUCTION yet health=DEGRADED
    (e.g. its Ollama host is slow to respond) -- all three axes are
    independent on purpose.
    """
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    DRAINING = "DRAINING"
    UNHEALTHY = "UNHEALTHY"
    OFFLINE = "OFFLINE"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ModelDeployment:
    deployment_id: str
    model_id: str                 # canonical family, e.g. "orneur-novus"
    model_version: str             # the specific checkpoint_id this deployment serves
    artifact_id: str                # matches CheckpointRecord.checkpoint_id
    runtime: str                    # "ollama" | "openai" | "anthropic" | future
    runtime_endpoint: str            # e.g. "http://localhost:11434", or a logical marker for API-based runtimes
    hardware_profile: str            # e.g. "local-cpu", "kaggle-t4", "unknown" -- descriptive, not enforced
    lifecycle: str = LifecycleState.EXPERIMENTAL.value
    health: str = DeploymentHealth.STARTING.value
    max_concurrency: int = 4
    context_limit: int = 8192
    capabilities: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    last_health_check_at: str | None = None
    warmup_completed: bool = False
    drain_requested_at: str | None = None

    def manifest_path(self) -> Path:
        validate_id(self.deployment_id, "deployment_id")
        return DEPLOYMENT_DIR / f"{self.deployment_id}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    @classmethod
    def load(cls, deployment_id: str) -> "ModelDeployment":
        validate_id(deployment_id, "deployment_id")
        path = DEPLOYMENT_DIR / f"{deployment_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No deployment record for '{deployment_id}'")
        with open(path) as f:
            return cls(**json.load(f))

    def is_routable(self, allow_experimental: bool = False) -> bool:
        """
        The single source of truth the Model Gateway must call before
        routing ANY request to this deployment. Refuses:
          - a REJECTED or RETIRED lifecycle (that checkpoint failed or was
            superseded)
          - EXPERIMENTAL lifecycle unless the caller explicitly opted in
            (allow_experimental=True) -- production traffic must never
            silently land on an experimental model
          - any health state other than READY or DEGRADED (DEGRADED is
            still routable -- slow but working; STARTING/DRAINING/
            UNHEALTHY/OFFLINE are not)
          - a deployment that hasn't completed warmup yet
        """
        if self.lifecycle in (LifecycleState.REJECTED.value, LifecycleState.RETIRED.value):
            return False
        if self.lifecycle == LifecycleState.EXPERIMENTAL.value and not allow_experimental:
            return False
        if self.health not in (DeploymentHealth.READY.value, DeploymentHealth.DEGRADED.value):
            return False
        if not self.warmup_completed:
            return False
        return True

    def request_drain(self) -> None:
        self.health = DeploymentHealth.DRAINING.value
        self.drain_requested_at = _now_iso()
        self.save()


def list_deployments(model_id: str | None = None) -> list[ModelDeployment]:
    deployments = []
    for p in sorted(DEPLOYMENT_DIR.glob("*.json")):
        with open(p) as f:
            d = ModelDeployment(**json.load(f))
        if model_id is None or d.model_id == model_id:
            deployments.append(d)
    return deployments
