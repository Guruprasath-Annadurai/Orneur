"""Phase 7/G12 training-infrastructure software identity record.

Pins software digests and optional dry-run log pointers. Does not claim a
P2 environment id is accepted, does not provision GPUs, and does not
authorize training.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class InfraRecordError(Exception):
    """Infrastructure record is incomplete or over-claims readiness."""


@dataclass(frozen=True)
class TrainingInfraRecord:
    code_sha: str
    lockfile_digests: dict[str, str]
    dry_run_log_pointer: str | None
    p2_environment_id: str | None
    gpu_provisioned: bool
    training_authorized: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_infra_record(
    root: Path,
    *,
    code_sha: str,
    dry_run_log_pointer: str | None = None,
    p2_environment_id: str | None = None,
    gpu_provisioned: bool = False,
    training_authorized: bool = False,
) -> TrainingInfraRecord:
    locks = {}
    for name in ("uv.lock", "pyproject.toml"):
        path = root / name
        if path.is_file():
            locks[name] = _digest_file(path)
    if not locks:
        raise InfraRecordError("no lockfile digests available")
    if p2_environment_id and not (gpu_provisioned or training_authorized):
        # Allow recording a candidate id string, but note it is not acceptance.
        notes = (
            "P2 environment id recorded as a pointer only; not an accepted "
            "attested training environment. GPU not provisioned; training NO-GO."
        )
    else:
        notes = "Pinned software identity for synthetic/CPU dry-run only."
    if training_authorized and not gpu_provisioned:
        # Still allowed to record; caller must not claim hardware PASS.
        notes += " Training authorized flag set by caller — verify against authorization module separately."
    return TrainingInfraRecord(
        code_sha=code_sha,
        lockfile_digests=locks,
        dry_run_log_pointer=dry_run_log_pointer,
        p2_environment_id=p2_environment_id,
        gpu_provisioned=gpu_provisioned,
        training_authorized=training_authorized,
        notes=notes,
    )


def refuse_hardware_pass_from_record(record: TrainingInfraRecord) -> None:
    if record.gpu_provisioned is False and record.p2_environment_id:
        # Pointer without provisioned GPU cannot satisfy P2 physical gates.
        raise InfraRecordError(
            "infra record has a P2 environment pointer but GPU is not provisioned; "
            "cannot mark hardware-dependent gates as PASS"
        )


def write_infra_record(path: Path, record: TrainingInfraRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
