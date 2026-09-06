"""
Model registry -- a real registry distinct from orca/serve/registry.py's
existing "resolve whichever Ollama model is currently installed" logic.
That resolver remains the serving-time fallback path (untouched by this
module); this is the lifecycle layer: what checkpoints exist, which one is
promoted to PRODUCTION for a family, and how to roll back if a promotion
regresses.

Persistence is a simple JSON-file store under ORCA_HOME/registry/ --
deliberately not a new database, matching the instruction to use "a simple
robust local implementation" and keep the interface swappable for a future
remote registry.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry.checkpoint import CheckpointRecord
from orca.registry.model_spec import LifecycleState, MODEL_SPECS

REGISTRY_STATE_PATH = ORCA_HOME / "registry" / "registry_state.json"
REGISTRY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class RegistryEntry:
    checkpoint_id: str
    family: str                    # "genesis" | "novus" | "aeternum"
    lifecycle_state: str = LifecycleState.EXPERIMENTAL.value
    ollama_alias: str | None = None      # legacy or new Ollama tag this maps to, if any
    promoted_at: str | None = None
    promoted_by: str | None = None
    demoted_reason: str | None = None


class ModelRegistry:
    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or REGISTRY_STATE_PATH
        self._entries: dict[str, RegistryEntry] = {}
        self._load()

    def _load(self) -> None:
        if self.state_path.exists():
            with open(self.state_path) as f:
                raw = json.load(f)
            self._entries = {k: RegistryEntry(**v) for k, v in raw.items()}

    def _save(self) -> None:
        with open(self.state_path, "w") as f:
            json.dump({k: asdict(v) for k, v in self._entries.items()}, f, indent=2)

    def register(self, checkpoint: CheckpointRecord, family: str, ollama_alias: str | None = None) -> RegistryEntry:
        if family not in MODEL_SPECS:
            raise ValueError(f"Unknown family '{family}'. Available: {list(MODEL_SPECS)}")
        entry = RegistryEntry(checkpoint_id=checkpoint.checkpoint_id, family=family, ollama_alias=ollama_alias)
        self._entries[checkpoint.checkpoint_id] = entry
        self._save()
        return entry

    def lookup(self, checkpoint_id: str) -> RegistryEntry | None:
        return self._entries.get(checkpoint_id)

    def lookup_latest_candidate(self, family: str) -> RegistryEntry | None:
        candidates = [e for e in self._entries.values() if e.family == family and e.lifecycle_state == LifecycleState.CANDIDATE.value]
        if not candidates:
            return None
        return candidates[-1]

    def lookup_production(self, family: str) -> RegistryEntry | None:
        """
        Returns the current PRODUCTION entry for a family, or None if none
        exists -- e.g. Aeternum, which has a family definition but no
        trained checkpoint at all, must return None here, never a fake or
        substituted entry. Callers must treat None as "not available", not
        silently fall back to a different family's model.
        """
        for e in self._entries.values():
            if e.family == family and e.lifecycle_state == LifecycleState.PRODUCTION.value:
                return e
        return None

    def list_evaluation_reports(self, checkpoint_id: str):
        from orca.registry.evaluation_registry import list_evaluations
        return list_evaluations(checkpoint_id)

    def promote(self, checkpoint_id: str, evaluation_report, promoted_by: str = "manual") -> RegistryEntry:
        """
        Promotion REQUIRES a PROMOTABLE evaluation decision -- this is the
        actual enforcement point. No string is ever hand-edited to make a
        model "production"; this function is the only path, and it refuses
        if the evidence doesn't support it.
        """
        entry = self._entries.get(checkpoint_id)
        if entry is None:
            raise ValueError(f"No registry entry for checkpoint '{checkpoint_id}' -- register it first")
        if evaluation_report.checkpoint_id != checkpoint_id:
            raise ValueError("Evaluation report does not match this checkpoint")
        if evaluation_report.pass_fail_status != "PROMOTABLE":
            raise PromotionDenied(
                f"Checkpoint '{checkpoint_id}' is NOT_PROMOTABLE: {'; '.join(evaluation_report.failure_reasons)}"
            )
        # Demote any existing production entry for this family first -- only
        # one PRODUCTION entry per family at a time.
        for other in self._entries.values():
            if other.family == entry.family and other.lifecycle_state == LifecycleState.PRODUCTION.value:
                other.lifecycle_state = LifecycleState.RETIRED.value
                other.demoted_reason = f"superseded by {checkpoint_id}"
        entry.lifecycle_state = LifecycleState.PRODUCTION.value
        entry.promoted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry.promoted_by = promoted_by
        self._save()
        return entry

    def reject(self, checkpoint_id: str, reason: str) -> RegistryEntry:
        entry = self._entries.get(checkpoint_id)
        if entry is None:
            raise ValueError(f"No registry entry for checkpoint '{checkpoint_id}'")
        entry.lifecycle_state = LifecycleState.REJECTED.value
        entry.demoted_reason = reason
        self._save()
        return entry

    def retire(self, checkpoint_id: str, reason: str) -> RegistryEntry:
        entry = self._entries.get(checkpoint_id)
        if entry is None:
            raise ValueError(f"No registry entry for checkpoint '{checkpoint_id}'")
        entry.lifecycle_state = LifecycleState.RETIRED.value
        entry.demoted_reason = reason
        self._save()
        return entry

    def rollback_target(self, family: str) -> RegistryEntry | None:
        """
        The most recently retired-from-production entry for a family, i.e.
        the safe thing to roll back TO if the current production checkpoint
        regresses. Never returns a REJECTED entry (those failed evaluation
        outright, never should have been promoted) -- only a RETIRED one
        that was once genuinely PRODUCTION.
        """
        retired = [
            e for e in self._entries.values()
            if e.family == family
            and e.lifecycle_state == LifecycleState.RETIRED.value
            and e.demoted_reason
            and e.demoted_reason.startswith("superseded by")
        ]
        if not retired:
            return None
        return retired[-1]

    def mark_family_absent(self, family: str) -> None:
        """No-op placeholder registration ensuring an absent-checkpoint
        family (Aeternum) is explicitly represented, not silently missing."""
        if family not in MODEL_SPECS:
            raise ValueError(f"Unknown family '{family}'")


class PromotionDenied(Exception):
    pass
