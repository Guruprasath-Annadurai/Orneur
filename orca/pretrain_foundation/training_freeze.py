"""Phase 9 training-freeze package builder.

Builds a NO-GO freeze candidate from digests and configuration. Never
authorizes training. Unauthorized execution must still refuse.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from orca.pretrain_foundation.compute_scenarios import frontier_pretraining_available
from orca.pretrain_foundation.readiness_gate import blocker_codes, production_observation


class TrainingFreezeError(Exception):
    """Freeze package is incomplete or training was requested without authorization."""


@dataclass(frozen=True)
class TrainingFreezePackage:
    status: str
    training_authorization: str
    code_sha: str
    model_configuration_digest: str | None
    tokenizer_digest: str | None
    dataset_digest: str | None
    evaluation_identity: str | None
    runtime_container_digest: str | None
    environment_identity: str | None
    resource_allocation: str
    maximum_permitted_spend: float
    checkpoint_schedule: str | None
    resume_policy: str | None
    incident_stop_conditions: tuple[str, ...]
    grant_identity: str | None
    readiness_blockers: tuple[str, ...]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_freeze_package(
    root: Path,
    code_sha: str,
    *,
    model_configuration: dict[str, Any] | None = None,
    tokenizer_digest: str | None = None,
    dataset_digest: str | None = None,
    evaluation_identity: str | None = None,
    runtime_container_digest: str | None = None,
    environment_identity: str | None = None,
) -> TrainingFreezePackage:
    """Assemble a freeze package that remains NOT_FROZEN / NO-GO without FINAL-2."""
    obs = production_observation()
    blockers = tuple(blocker_codes(obs))
    model_digest = (
        _sha256_text(json.dumps(model_configuration, sort_keys=True, separators=(",", ":")))
        if model_configuration
        else None
    )
    authorized = obs.training_authorized and not blockers
    status = "FROZEN_AUTHORIZED" if authorized else "NOT_FROZEN"
    return TrainingFreezePackage(
        status=status,
        training_authorization="AUTHORIZED" if authorized else "NO-GO",
        code_sha=code_sha,
        model_configuration_digest=model_digest,
        tokenizer_digest=tokenizer_digest,
        dataset_digest=dataset_digest,
        evaluation_identity=evaluation_identity,
        runtime_container_digest=runtime_container_digest,
        environment_identity=environment_identity,
        resource_allocation="synthetic_cpu_only" if not frontier_pretraining_available() else "unspecified",
        maximum_permitted_spend=0.0,
        checkpoint_schedule=None if not authorized else "per_grant",
        resume_policy=None if not authorized else "per_grant",
        incident_stop_conditions=(
            "security_or_integrity_violation",
            "authorization_revoked",
            "budget_exhausted",
            "unauthorized_scope_expansion",
        ),
        grant_identity=None,
        readiness_blockers=blockers,
        notes=(
            "Phase 9 freeze package prepared for founder FINAL-2. "
            "No training execution is authorized by building this artifact. "
            f"Repository root observed: {root}"
        ),
    )


def assert_unauthorized_execution_refused(package: TrainingFreezePackage, *, execute_requested: bool) -> None:
    if execute_requested and package.training_authorization != "AUTHORIZED":
        raise TrainingFreezeError(
            "unauthorized training execution refused; freeze package is "
            f"{package.status} / {package.training_authorization}"
        )
    if execute_requested and package.status != "FROZEN_AUTHORIZED":
        raise TrainingFreezeError("training execution refused: package is not FROZEN_AUTHORIZED")


def write_freeze_manifest(path: Path, package: TrainingFreezePackage) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "orneur-pretraining-closure-training-freeze-manifest/2",
        "phase": 9,
        "package": package.to_dict(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
