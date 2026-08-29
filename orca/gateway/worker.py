"""
Worker abstraction, suitable for future distributed execution but not
requiring multi-host hardware to exist today -- the current machine
represents exactly one worker. A worker hosts one or more deployments and
tracks its own liveness/capacity; the gateway consults this before routing
to any deployment on it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id

WORKER_DIR = ORCA_HOME / "registry" / "workers"
WORKER_DIR.mkdir(parents=True, exist_ok=True)

# A worker is considered unreachable if its last successful heartbeat is
# older than this -- deliberately simple (no distributed consensus, no
# gossip protocol) per explicit instruction not to over-engineer this.
_HEARTBEAT_STALE_SECONDS = 30.0


class WorkerHealth(str, Enum):
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    DRAINING = "DRAINING"
    UNHEALTHY = "UNHEALTHY"
    OFFLINE = "OFFLINE"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


@dataclass
class Worker:
    worker_id: str
    runtime: str
    hardware: str                     # descriptive, e.g. "local-cpu-16gb", "kaggle-t4"
    available_models: list[str] = field(default_factory=list)   # deployment_ids this worker can serve
    status: str = WorkerHealth.STARTING.value
    capacity: int = 4                  # max concurrent requests this worker can take
    active_requests: int = 0
    queue_depth: int = 0
    last_heartbeat: str = field(default_factory=_now_iso)

    def manifest_path(self) -> Path:
        validate_id(self.worker_id, "worker_id")
        return WORKER_DIR / f"{self.worker_id}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    @classmethod
    def load(cls, worker_id: str) -> "Worker":
        validate_id(worker_id, "worker_id")
        path = WORKER_DIR / f"{worker_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No worker record for '{worker_id}'")
        with open(path) as f:
            return cls(**json.load(f))

    def heartbeat(self) -> None:
        self.last_heartbeat = _now_iso()
        self.save()

    def is_stale(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        age = (now - _parse_iso(self.last_heartbeat)).total_seconds()
        return age > _HEARTBEAT_STALE_SECONDS

    def has_capacity(self) -> bool:
        return self.active_requests < self.capacity

    def is_available_for_routing(self) -> bool:
        if self.status not in (WorkerHealth.READY.value, WorkerHealth.DEGRADED.value):
            return False
        if self.is_stale():
            return False
        return self.has_capacity()


def list_workers() -> list[Worker]:
    workers = []
    for p in sorted(WORKER_DIR.glob("*.json")):
        with open(p) as f:
            workers.append(Worker(**json.load(f)))
    return workers
