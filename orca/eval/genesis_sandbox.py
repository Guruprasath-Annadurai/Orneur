"""Requirements and attestation gate for the FUTURE hermetic code-execution sandbox (Genesis Capability Eval V1, `coding`).

This module executes nothing. Candidate-generated code is never run by this phase's CPU harness: coding items score PENDING_SANDBOX (and the
category INCOMPLETE) until an executor whose attestation satisfies SANDBOX_REQUIREMENTS is supplied.
"""
from __future__ import annotations

from typing import Any, Mapping

SANDBOX_VERSION = "genesis-sandbox-requirements/1"

SANDBOX_REQUIREMENTS: dict[str, Any] = {
    "network": "DISABLED (no interfaces except loopback; DNS and egress blocked)",
    "filesystem": "read-only root; single ephemeral writable tmpfs; no host mounts; no access to the corpus, the repository, credentials or environment secrets",
    "resource_limits": {"cpu_seconds_per_test": 5, "wall_seconds_per_test": 10, "memory_bytes": 512 * 1024 * 1024, "max_processes": 32,
                        "max_open_files": 64, "max_output_bytes": 65536, "max_file_size_bytes": 1024 * 1024},
    "isolation": "one fresh container/VM per candidate response; no state shared between candidates; killed and destroyed after scoring",
    "process_limits": "no fork bombs (process cap), no privilege escalation (non-root, no-new-privileges, dropped capabilities, seccomp allow-list)",
    "timeout": "hard wall-clock kill per test and per response; a timeout scores the test as failed and is recorded",
    "captured_streams": "stdout and stderr captured separately, truncated at max_output_bytes, stored in the evidence record",
    "test_result_evidence": ["per-test pass/fail", "exit status or signal", "wall and cpu time", "stdout/stderr digests", "sandbox image digest",
                             "executor version", "the exact code digest that ran"],
    "determinism": "fixed hash seed, fixed locale and timezone, no clock or randomness access beyond what tests supply",
    "supported_language": "Python 3, standard library only",
}

_REQUIRED_ATTESTATION_KEYS = ("sandbox_version", "network_disabled", "read_only_root", "non_root", "no_new_privileges", "cpu_seconds_per_test",
                              "wall_seconds_per_test", "memory_bytes", "max_processes", "max_output_bytes", "executor_version", "image_digest")


class SandboxUnavailable(RuntimeError):
    """The default executor: coding items cannot be scored without an attested hermetic sandbox."""


class NoSandbox:
    def run_tests(self, code: str, function_name: str, tests: list[dict]) -> dict:
        raise SandboxUnavailable("no hermetic sandbox is configured; candidate code is never executed by the CPU-only harness")


def validate_attestation(att: Mapping[str, Any]) -> list[str]:
    """Problems with an executor's attestation (empty list == it satisfies the requirements). Trust in the attestation itself is a later concern."""
    p: list[str] = []
    for k in _REQUIRED_ATTESTATION_KEYS:
        if k not in att:
            p.append(f"missing attestation field {k}")
    if p:
        return p
    r = SANDBOX_REQUIREMENTS["resource_limits"]
    if att["sandbox_version"] != SANDBOX_VERSION:
        p.append("sandbox_version mismatch")
    for k in ("network_disabled", "read_only_root", "non_root", "no_new_privileges"):
        if att[k] is not True:
            p.append(f"{k} must be True")
    for k, key in (("cpu_seconds_per_test", "cpu_seconds_per_test"), ("wall_seconds_per_test", "wall_seconds_per_test"), ("memory_bytes", "memory_bytes"),
                   ("max_processes", "max_processes"), ("max_output_bytes", "max_output_bytes")):
        if not isinstance(att[k], (int, float)) or isinstance(att[k], bool) or att[k] > r[key] or att[k] <= 0:
            p.append(f"{k} must be a positive value no larger than {r[key]}")
    if not isinstance(att["image_digest"], str) or not att["image_digest"]:
        p.append("image_digest required")
    return p
