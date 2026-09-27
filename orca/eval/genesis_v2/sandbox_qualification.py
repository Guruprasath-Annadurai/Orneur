"""Builds SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json: evidence that the exact pinned image passed the full containment suite. This record is a
CANDIDATE for `sandbox_ready`, never `sandbox_ready` itself — that flag stays false until the preregistration binds this image and independent
audit approves it (see spec.freeze_status)."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from orca.eval.genesis_v2 import sandbox as SB

SCHEMA_VERSION = "genesis-v2-sandbox-qualification-candidate/1"
RECORD_PATH = "docs/orneur/phase-21/GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json"
DOCKERFILE_PATH = "docker/genesis_v2_sandbox/Dockerfile"
RUNTIME_KEY = "python3.11-qualification-candidate"


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _docker_version() -> str:
    r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _container_python_version(image: str) -> str:
    r = subprocess.run(["docker", "run", "--rm", "--network", "none", image, "python3", "--version"], capture_output=True, text=True, timeout=30)
    return (r.stdout or r.stderr).strip().removeprefix("Python ") if r.returncode == 0 else "unknown"


def build_record(root: Path, *, commit_sha: str, test_summary: str, runner_class: str) -> dict:
    image = SB.SUPPORTED_RUNTIMES[RUNTIME_KEY]
    return {
        "document": "GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD", "schema_version": SCHEMA_VERSION,
        "sandbox_policy_version": SB.POLICY_VERSION, "image_reference": image, "image_digest": image.split("@", 1)[1] if "@" in image else None,
        "dockerfile_sha256": _sha(Path(root) / DOCKERFILE_PATH), "base_image_digest": "sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e",
        "runtime_versions": {"python_in_container": _container_python_version(image), "docker_server": _docker_version()},
        "containment_test_result_digest": hashlib.sha256(test_summary.encode()).hexdigest(), "containment_test_summary": test_summary,
        "test_runner_class": runner_class, "exact_commit_sha": commit_sha,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sandbox_ready": False,
        "note": "Passing this containment run makes the image a QUALIFICATION CANDIDATE. sandbox_ready stays false until the preregistration binds this exact image_digest and independent audit approves it.",
    }
