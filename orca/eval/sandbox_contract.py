"""
Sandbox security contract (Phase 21B.4.1, spec §4) -- a versioned,
explicit record of exactly what isolation was in force when a
candidate's coding/debugging tasks were scored. Persisted alongside
evaluation results so a future reviewer can answer "what protected this
run?" without re-deriving it from source, and so results scored under
different sandbox versions are never silently compared as if they used
the same security boundary.
"""
from __future__ import annotations

import platform
import sys
from dataclasses import asdict, dataclass

from orca.eval.sandbox_docker import (
    DEFAULT_CPU_LIMIT,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_PIDS_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_OUTPUT_BYTES,
    SANDBOX_IMAGE_TAG,
    is_docker_available,
    resolve_image_digest,
)

SANDBOX_CONTRACT_VERSION = "docker-v1"


@dataclass(frozen=True)
class SandboxContract:
    contract_version: str
    execution_backend: str            # "docker" | "subprocess-only (WEAK, deprecated for real scoring)"
    container_image_tag: str | None
    container_image_digest: str | None
    network_policy: str
    filesystem_policy: str
    cpu_limit: str
    memory_limit: str
    pids_limit: int
    timeout_seconds: float
    output_byte_limit: int
    environment_policy: str
    mounted_paths: list[str]
    python_runtime_version: str
    host_platform: str
    docker_available_at_contract_time: bool

    def is_strong_backend(self) -> bool:
        return self.execution_backend == "docker"


def current_docker_contract() -> SandboxContract:
    """The contract in force for orca.eval.genesis_suite.score_unit_test()
    right now, on THIS host. `container_image_digest` is None if the
    image has never been pulled locally -- callers that require a
    reproducible contract for a real baseline should treat a None
    digest as a preflight failure (the image must be pulled and its
    digest resolved before it's trustworthy to record)."""
    return SandboxContract(
        contract_version=SANDBOX_CONTRACT_VERSION,
        execution_backend="docker",
        container_image_tag=SANDBOX_IMAGE_TAG,
        container_image_digest=resolve_image_digest(SANDBOX_IMAGE_TAG),
        network_policy="none (--network none; no virtual network interface exists inside the container)",
        filesystem_policy=(
            "read-only root filesystem; no bind mounts of host paths (candidate code delivered via stdin, "
            "never written to a mounted path); ephemeral --tmpfs /tmp (rw,exec,size=64m), destroyed with "
            "the container on exit"
        ),
        cpu_limit=DEFAULT_CPU_LIMIT,
        memory_limit=DEFAULT_MEMORY_LIMIT,
        pids_limit=DEFAULT_PIDS_LIMIT,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        output_byte_limit=MAX_OUTPUT_BYTES,
        environment_policy="minimal (HOME=/tmp, PYTHONDONTWRITEBYTECODE=1 only); no host env vars, no secrets",
        mounted_paths=[],
        python_runtime_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        host_platform=platform.platform(),
        docker_available_at_contract_time=is_docker_available(),
    )


def contract_id(contract: SandboxContract) -> str:
    """Deterministic identity for a contract instance -- used to detect
    when a future run's actual sandbox configuration has drifted from
    what an earlier result claims was used."""
    import hashlib
    import json

    payload = json.dumps(asdict(contract), sort_keys=True, separators=(",", ":"))
    return f"{contract.contract_version}-{hashlib.sha256(payload.encode()).hexdigest()[:16]}"
