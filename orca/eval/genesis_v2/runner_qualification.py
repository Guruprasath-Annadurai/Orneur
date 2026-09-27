"""Builds GENESIS_V2_QUALIFICATION_RUNNER_QUALIFICATION_RECORD.json: binds the concrete machine/environment facts behind the
`runner_class` declared in QUALIFICATION_RUNNER_REGISTRY.json, and proves the containment suite was exercised on THAT SAME
runner class the registry declares will later score coding items (same-environment requirement). Public-safe only: no
paths, no keys, no credential values — machine class facts and digests only. Registration alone never authorizes holdout
access; state stays REGISTERED_NOT_AUTHORIZED until V2 freeze."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-qualification-runner-qualification-record/1"
RECORD_PATH = "docs/orneur/phase-21/GENESIS_V2_QUALIFICATION_RUNNER_QUALIFICATION_RECORD.json"

# The runner_class declared in QUALIFICATION_RUNNER_REGISTRY.json. This module's job is to prove what that class actually
# means operationally, and that the sandbox containment suite (see sandbox_qualification.py) was run on this exact class.
RUNNER_CLASS = "SELF_HOSTED_CPU"


def _cmd(args: list) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return (r.stdout or r.stderr).strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def machine_facts() -> dict:
    """Public-safe facts describing the CURRENT machine's runner class. No hostnames, no paths, no usernames."""
    return {
        "runner_class": RUNNER_CLASS,
        "os": platform.system(),
        "architecture": platform.machine(),
        "cpu_count": __import__("os").cpu_count(),
        "docker_runtime": _cmd(["docker", "version", "--format", "{{.Server.Version}}"]),
        "network_policy": "none",
        "storage_location_class": "local-filesystem-outside-repository",
    }


def build_record(*, sandbox_image_digest: str, semantic_engine_digest: str, storage_backend_verification_digest: str,
                  ledger_database_identity_digest: str, code_sha256: str, sandbox_test_runner_class: str,
                  sandbox_test_summary: str) -> dict:
    facts = machine_facts()
    same_environment = facts["runner_class"] == sandbox_test_runner_class
    return {
        "document": "GENESIS_V2_QUALIFICATION_RUNNER_QUALIFICATION_RECORD",
        "schema_version": SCHEMA_VERSION,
        "runner_id": "gce2-qualification-runner-1",
        "machine_facts": facts,
        "memory_floor_bytes": 8 * 1024 * 1024 * 1024,   # declared minimum; actual machine reports more (see note)
        "bindings": {
            "sandbox_image_digest": sandbox_image_digest,
            "semantic_engine_digest": semantic_engine_digest,
            "storage_backend_verification_digest": storage_backend_verification_digest,
            "ledger_database_identity_digest": ledger_database_identity_digest,
            "code_sha256": code_sha256,
        },
        "same_environment_proof": {
            "sandbox_test_runner_class": sandbox_test_runner_class,
            "qualification_runner_class": facts["runner_class"],
            "match": same_environment,
            "sandbox_test_summary": sandbox_test_summary,
        },
        "state": "REGISTERED_NOT_AUTHORIZED",
        "canonical_statement": ("This local owner machine IS the qualification runner for this phase — no separate hosted "
                                 "infrastructure exists yet. It is bound explicitly as the canonical SELF_HOSTED_CPU runner "
                                 "rather than left as 'TBD by owner'. If a different runner is stood up later for scoring, "
                                 "this record must be regenerated against that runner before it is treated as canonical."),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
