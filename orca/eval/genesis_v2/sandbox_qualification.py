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

SCHEMA_VERSION = "genesis-v2-sandbox-qualification-candidate/2"
RECORD_PATH = "docs/orneur/phase-21/GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json"
DOCKERFILE_PATH = "docker/genesis_v2_sandbox/Dockerfile"
CONTAINMENT_TEST_PATH = "tests/test_genesis_v2_sandbox_containment.py"
RUNTIME_KEY = "python3.11-qualification-candidate"


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _docker_version() -> str:
    r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _container_python_version(image: str) -> str:
    r = subprocess.run(["docker", "run", "--rm", "--network", "none", image, "python3", "--version"], capture_output=True, text=True, timeout=30)
    return (r.stdout or r.stderr).strip().removeprefix("Python ") if r.returncode == 0 else "unknown"


def build_record(root: Path, *, tested_implementation_sha: str, tested_implementation_parent_sha: str, test_summary: str, runner_class: str) -> dict:
    """`tested_implementation_sha` MUST be an already-existing, immutable commit that contains the exact sandbox policy/Dockerfile/
    qualification code that was actually exercised (never the not-yet-created evidence commit itself — that would be circular). The
    commit that ADDS this JSON record (the "evidence-record commit") is a later, separate commit; its SHA is reported in the phase's
    final report after push, not embedded here, precisely to avoid a record claiming to know its own future hash."""
    image = SB.SUPPORTED_RUNTIMES[RUNTIME_KEY]
    return {
        "document": "GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD", "schema_version": SCHEMA_VERSION,
        "sandbox_policy_version": SB.POLICY_VERSION, "image_reference": image, "image_digest": image.split("@", 1)[1] if "@" in image else None,
        "dockerfile_sha256": _sha(Path(root) / DOCKERFILE_PATH), "base_image_digest": "sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e",
        "containment_test_code_hash": _sha(Path(root) / CONTAINMENT_TEST_PATH),
        "runtime_versions": {"python_in_container": _container_python_version(image), "docker_server": _docker_version()},
        "containment_test_result_digest": hashlib.sha256(test_summary.encode()).hexdigest(), "containment_test_summary": test_summary,
        "test_runner_class": runner_class,
        "tested_implementation_sha": tested_implementation_sha,
        "tested_implementation_parent_sha": tested_implementation_parent_sha,
        "evidence_record_commit": None,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sandbox_ready": False,
        "sandbox_qualification_status": "QUALIFICATION_CANDIDATE_PENDING_FREEZE",
        "note": ("Passing this containment run makes the image a QUALIFICATION CANDIDATE, evaluated against tested_implementation_sha "
                 "(an already-existing, CI-verified commit). evidence_record_commit is intentionally null here: it is the commit that "
                 "introduces this exact file and is only knowable after that commit is made; it is reported separately in the phase's "
                 "final report, not self-referenced. sandbox_ready stays false until the preregistration binds this exact image_digest, "
                 "the qualification runner class matches the tested runner class, and independent audit approves it."),
    }
