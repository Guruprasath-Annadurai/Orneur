"""
Artifact retention/eviction policy -- the minimal safeguard needed to
prevent a recurrence of Phase 0.5's incident, where two Novus-family
Ollama artifacts (orca-core:latest, orca-core-dpo:latest) were deleted
directly via `ollama rm` under disk pressure, with no registry record of
the deletion at the time it happened.

From this point forward, evicting a registered checkpoint's local artifact
MUST go through evict_artifact() below -- never a bare `ollama rm` /
os.remove() on a path that has a CheckpointRecord. This does not stop
someone from deleting the file outside this code path (this is a registry,
not a filesystem permission system), but it is the single point that:
  - refuses to evict a PRODUCTION checkpoint or a rollback target,
  - always records who/why/when,
  - always updates availability state instead of leaving it stale.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id
from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord

EVICTION_LOG_PATH = ORCA_HOME / "registry" / "eviction_log.jsonl"
EVICTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


class EvictionRefused(Exception):
    pass


@dataclass
class EvictionRecord:
    checkpoint_id: str
    reason: str
    actor: str                 # who/what initiated the eviction (human name, script name, process id, etc.)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    checksum_preserved: str = ""
    availability_before: str = ""
    availability_after: str = ArtifactAvailability.MISSING.value


def _append_eviction_log(record: EvictionRecord) -> None:
    with open(EVICTION_LOG_PATH, "a") as f:
        f.write(json.dumps(asdict(record)) + "\n")


def read_eviction_log() -> list[EvictionRecord]:
    if not EVICTION_LOG_PATH.exists():
        return []
    records = []
    with open(EVICTION_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(EvictionRecord(**json.loads(line)))
    return records


def evict_artifact(
    checkpoint: CheckpointRecord,
    reason: str,
    actor: str,
    registry=None,
    force: bool = False,
) -> CheckpointRecord:
    """
    The only sanctioned path for evicting a checkpoint's local artifact
    under this registry. Refuses (raises EvictionRefused) if:
      - the checkpoint is the current PRODUCTION entry for its family, or
      - the checkpoint is the current rollback_target for its family,
    unless force=True is explicitly passed (an escape hatch for a human
    decision, not a default).

    Does NOT delete the file itself -- that remains the caller's job (e.g.
    `ollama rm`, or removing a local path) -- this function is the
    bookkeeping gate that must wrap that action, recording the eviction and
    updating availability so the registry never silently drifts from
    reality the way it did in Phase 0.5.
    """
    validate_id(checkpoint.checkpoint_id, "checkpoint_id")

    if registry is not None and not force:
        production = registry.lookup_production(checkpoint.model_id.removeprefix("orneur-"))
        if production and production.checkpoint_id == checkpoint.checkpoint_id:
            raise EvictionRefused(
                f"Refusing to evict '{checkpoint.checkpoint_id}': it is the current "
                f"PRODUCTION checkpoint for its family. Pass force=True if this is a "
                f"deliberate, authorized decision."
            )
        rollback = registry.rollback_target(checkpoint.model_id.removeprefix("orneur-"))
        if rollback and rollback.checkpoint_id == checkpoint.checkpoint_id:
            raise EvictionRefused(
                f"Refusing to evict '{checkpoint.checkpoint_id}': it is the designated "
                f"rollback target for its family. Pass force=True if this is a "
                f"deliberate, authorized decision."
            )

    availability_before = checkpoint.availability
    eviction = EvictionRecord(
        checkpoint_id=checkpoint.checkpoint_id,
        reason=reason,
        actor=actor,
        checksum_preserved=checkpoint.artifact_checksum,
        availability_before=availability_before,
        availability_after=ArtifactAvailability.MISSING.value,
    )
    _append_eviction_log(eviction)

    checkpoint.availability = ArtifactAvailability.MISSING.value
    checkpoint.availability_note = f"Evicted {eviction.timestamp} by {actor}: {reason}"
    checkpoint.save()
    return checkpoint
