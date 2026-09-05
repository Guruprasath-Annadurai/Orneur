#!/usr/bin/env python3
"""
Phase 14B distributed qualification orchestrator. Runs ON the GitHub
Actions ephemeral runner (Host B's own process host) and drives:

  - Host B's own race attempt, directly in a subprocess on this runner
    (no special code path -- same distributed_actor.py every role uses).
  - Host A's race attempt via `northflank command-exec`, targeting the
    real orneur-api-a container -- a genuinely separate machine.

Both race attempts are launched as concurrent OS subprocesses (not
sequential calls) so the shared barrier in `scripts/phase14b/barrier.py`
is what actually synchronizes them, not this script's own timing.

Fails closed: any iteration that violates the one-use-lease invariant
(exactly one COMMITTED, exactly one LOST_RACE, zero false-committed
audit rows) marks the whole qualification run FAILED. One intermittent
violation across all iterations is enough to fail -- this script does
not average results away.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
_NORTHFLANK_PROJECT = os.environ.get("NORTHFLANK_PROJECT", "orneur-phase14b-staging")
_NORTHFLANK_SERVICE = os.environ.get("NORTHFLANK_SERVICE", "orneur-api-a")


def _run_local(args: list[str]) -> dict:
    """Runs distributed_actor.py directly on THIS runner (Host B)."""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT_DIR / "distributed_actor.py"), *args],
        cwd=str(_SCRIPT_DIR), capture_output=True, text=True, timeout=90,
    )
    if not proc.stdout.strip():
        return {"error": "NO_OUTPUT", "stderr": proc.stderr[-2000:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return {"error": "PARSE_ERROR", "raw": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}


def _start_remote(args: list[str]) -> subprocess.Popen:
    """Starts distributed_actor.py on Host A (the real Northflank pod)
    via `northflank command-exec`, as a background OS process on THIS
    runner that itself blocks on the remote exec -- giving true
    concurrency with Host B's own subprocess below."""
    cmd = "cd /tmp/phase14b && python3 distributed_actor.py " + " ".join(args)
    return subprocess.Popen(
        ["npx", "--yes", "@northflank/cli", "command-exec", "service",
         "--project", _NORTHFLANK_PROJECT, "--service", _NORTHFLANK_SERVICE,
         "--cmd", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _finish_remote(proc: subprocess.Popen) -> dict:
    out, err = proc.communicate(timeout=90)
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"error": "NO_JSON_OUTPUT", "stdout_tail": out[-2000:], "stderr_tail": err[-2000:]}


def run_one_race(run_id: str) -> dict:
    setup = _run_local(["--role", "ORCHESTRATOR", "--run-id", run_id, "--action", "setup_lease", "--max-uses", "1"])
    if "lease_id" not in setup:
        return {"run_id": run_id, "error": "SETUP_FAILED", "detail": setup}
    lease_id = setup["lease_id"]

    remote_proc = _start_remote(["--role", "HOST_A", "--run-id", run_id, "--action", "race", "--lease-id", lease_id])
    local_result = _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "race", "--lease-id", lease_id])
    remote_result = _finish_remote(remote_proc)

    audit = _run_local(["--role", "ORCHESTRATOR", "--run-id", run_id, "--action", "read_audit"])
    _run_local(["--role", "ORCHESTRATOR", "--run-id", run_id, "--action", "cleanup"])

    results = {"HOST_A": remote_result, "HOST_B": local_result}
    allow_count = sum(1 for r in results.values() if r.get("state") == "ALLOW")
    deny_count = sum(1 for r in results.values() if r.get("state") == "DENY")

    invariant_ok = (
        allow_count == 1 and deny_count == 1
        and audit.get("committed") == 1 and audit.get("lost_race") == 1
        and audit.get("false_committed_audit", -1) == 0
    )
    return {
        "run_id": run_id, "lease_id": lease_id, "results": results,
        "audit": audit, "allow_count": allow_count, "deny_count": deny_count,
        "invariant_ok": invariant_ok,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--race-runs", type=int, default=10)
    args = parser.parse_args()

    all_results = []
    for i in range(args.race_runs):
        run_id = f"race-{uuid.uuid4().hex[:12]}"
        print(f"::group::Race {i + 1}/{args.race_runs} (run_id={run_id})")
        result = run_one_race(run_id)
        print(json.dumps(result, indent=2))
        print("::endgroup::")
        all_results.append(result)

    out_path = _SCRIPT_DIR / "qualification_results.json"
    out_path.write_text(json.dumps(all_results, indent=2))

    failures = [r for r in all_results if not r.get("invariant_ok")]
    print(f"\n{len(all_results) - len(failures)}/{len(all_results)} races satisfied the one-use-lease invariant.")
    if failures:
        print(f"::error::{len(failures)} race(s) violated the invariant -- see qualification_results.json")
        sys.exit(1)


if __name__ == "__main__":
    main()
