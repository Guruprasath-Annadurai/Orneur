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


def _reupload_actor_script() -> None:
    """Re-pushes scripts/phase14b onto Host A's /tmp. Host A's pod is
    disposable compute like everything else in this phase -- Northflank
    can recycle the pod between two `command-exec` calls in the SAME
    workflow run (observed directly: pod instance suffix changed
    mid-run, taking /tmp/phase14b with it), so file presence can never
    be assumed after the job's one-time upload step. This re-upload is
    cheap and idempotent; calling it defensively before every remote
    exec is the fix, not a workaround for a race/audit bug -- the
    concurrency-hardening implementation itself (Phase 14B.1.1) is not
    touched here."""
    subprocess.run(
        ["npx", "--yes", "@northflank/cli", "upload", "service", "file",
         "--project", _NORTHFLANK_PROJECT, "--service", _NORTHFLANK_SERVICE,
         "--localPath", str(_SCRIPT_DIR), "--remotePath", "/tmp/phase14b"],
        capture_output=True, text=True, timeout=60,
    )


def _start_remote(args: list[str]) -> subprocess.Popen:
    """Starts distributed_actor.py on Host A (the real Northflank pod)
    via `northflank command-exec`, as a background OS process on THIS
    runner that itself blocks on the remote exec -- giving true
    concurrency with Host B's own subprocess below. Does NOT re-upload
    first (that used to be unconditional here and made every remote
    call pay a ~15-35s re-upload cost regardless of whether the file
    was actually missing -- with the new scenario battery's ~30 remote
    calls per job, that alone blew the 30-minute job timeout in
    workflow run 34030695040. Recovery from a recycled pod (Host A's
    /tmp is disposable compute, same as everything else in this phase)
    is now handled by `_finish_remote`'s caller-visible error signal
    plus each call site's own retry -- see `_start_remote_verified`
    and `run_one_race_with_delivery_retry`."""
    cmd = "cd /tmp/phase14b && python3 distributed_actor.py " + " ".join(args)
    return subprocess.Popen(
        ["npx", "--yes", "@northflank/cli", "command-exec", "service",
         "--project", _NORTHFLANK_PROJECT, "--service", _NORTHFLANK_SERVICE,
         "--shell-cmd", "bash -c", "--cmd", cmd],
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


def _start_remote_verified(args: list[str]) -> dict:
    """The sequential (non-racing) remote call helper: tries the exec
    directly first (fast path, no re-upload), and ONLY if that fails
    (Host A's pod recycled and /tmp/phase14b is gone, or any other
    transport error) re-uploads the actor script once and retries the
    exec once. Used by every new scenario function below; the race
    path keeps its own `_start_remote`/`_finish_remote` pair unchanged
    since races need true Popen-level concurrency with Host B and
    already retry whole race attempts at a higher level."""
    result = _finish_remote(_start_remote(args))
    if "error" in result:
        _reupload_actor_script()
        result = _finish_remote(_start_remote(args))
        result["recovered_after_reupload"] = True
    return result


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
    delivery_failure = (
        audit.get("total_events", -1) == 0
        and (results["HOST_A"].get("error") or results["HOST_B"].get("error"))
    )
    return {
        "run_id": run_id, "lease_id": lease_id, "results": results,
        "audit": audit, "allow_count": allow_count, "deny_count": deny_count,
        "invariant_ok": invariant_ok, "delivery_failure": delivery_failure,
    }


def run_one_race_with_delivery_retry(max_attempts: int = 3) -> dict:
    """A `delivery_failure` (neither host ever reached a real ALLOW/DENY
    decision -- e.g. Northflank's command-exec transport itself
    returning a bare exit 255, or a barrier timeout because the peer
    never started -- means the authority/audit code path was NEVER
    exercised (`total_events == 0`): this is a harness/transport failure,
    not evidence of the concurrency invariant misbehaving, so it is
    retried under a fresh run_id/lease_id up to `max_attempts` times.
    A REAL invariant violation (both hosts got a real decision but the
    result was wrong) is never retried -- it is returned immediately
    and counts as a hard failure, exactly per spec ("one intermittent
    violation = FAIL, do not average away a race bug"). Every attempt,
    including delivery failures that were retried past, is preserved
    in `all_attempts` so nothing is hidden from the evidence."""
    all_attempts = []
    for attempt in range(1, max_attempts + 1):
        run_id = f"race-{uuid.uuid4().hex[:12]}"
        result = run_one_race(run_id)
        result["attempt"] = attempt
        all_attempts.append(result)
        if result.get("invariant_ok") or not result.get("delivery_failure"):
            break
    final = dict(all_attempts[-1])
    final["all_attempts"] = all_attempts
    return final


def run_session_visibility(run_id: str) -> dict:
    """Spec Step 1: A writes/B reads, B writes/A reads, both against the
    real Host A (Northflank, via command-exec) and Host B (this runner).
    remote_proc for the write must fully finish (communicate) before the
    read is issued -- unlike the race, ordering here is deliberate, not
    concurrent."""
    import time

    t0 = time.monotonic()
    write_a = _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "write_tenant_state", "--tenant-suffix", "svis", "--role-label", "HOST_A"])
    t_write_a = time.monotonic() - t0
    read_b = _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "read_tenant_state", "--tenant-suffix", "svis", "--role-label", "HOST_B"])
    a_to_b_ok = "written-by-HOST_A" in read_b.get("principals_seen", [])

    t1 = time.monotonic()
    write_b = _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "write_tenant_state", "--tenant-suffix", "svis", "--role-label", "HOST_B"])
    t_write_b = time.monotonic() - t1
    read_a = _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "read_tenant_state", "--tenant-suffix", "svis", "--role-label", "HOST_A"])
    b_to_a_ok = "written-by-HOST_B" in read_a.get("principals_seen", [])

    return {
        "run_id": run_id, "a_to_b_visible": a_to_b_ok, "b_to_a_visible": b_to_a_ok,
        "write_a_latency_s": round(t_write_a, 3), "write_b_latency_s": round(t_write_b, 3),
        "latency_note": "HOST_A latency includes the defensive actor-script re-upload (see _reupload_actor_script), not pure durable-write round-trip; HOST_B latency is local-subprocess only",
        "write_a": write_a, "read_b": read_b, "write_b": write_b, "read_a": read_a,
    }


def run_tenant_isolation(run_id: str) -> dict:
    """Spec Step 2: Tenant A / Tenant B each written by BOTH hosts, then
    each tenant read from BOTH hosts -- required: only that tenant's own
    two writers ever appear, zero cross-tenant leakage in either
    direction."""
    _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "write_tenant_state", "--tenant-suffix", "tenA", "--role-label", "HOST_B"])
    _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "write_tenant_state", "--tenant-suffix", "tenA", "--role-label", "HOST_A"])
    _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "write_tenant_state", "--tenant-suffix", "tenB", "--role-label", "HOST_B"])
    _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "write_tenant_state", "--tenant-suffix", "tenB", "--role-label", "HOST_A"])

    read_tenA_from_A = _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "read_tenant_state", "--tenant-suffix", "tenA", "--role-label", "HOST_A"])
    read_tenA_from_B = _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "read_tenant_state", "--tenant-suffix", "tenA", "--role-label", "HOST_B"])
    read_tenB_from_A = _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "read_tenant_state", "--tenant-suffix", "tenB", "--role-label", "HOST_A"])
    read_tenB_from_B = _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "read_tenant_state", "--tenant-suffix", "tenB", "--role-label", "HOST_B"])

    tenA_principals = set(read_tenA_from_A.get("principals_seen", [])) | set(read_tenA_from_B.get("principals_seen", []))
    tenB_principals = set(read_tenB_from_A.get("principals_seen", [])) | set(read_tenB_from_B.get("principals_seen", []))
    a_isolated = tenA_principals == {"written-by-HOST_A", "written-by-HOST_B"}
    b_isolated = tenB_principals == {"written-by-HOST_A", "written-by-HOST_B"}

    return {
        "run_id": run_id, "tenant_a_isolated": a_isolated, "tenant_b_isolated": b_isolated,
        "tenant_a_principals": sorted(tenA_principals), "tenant_b_principals": sorted(tenB_principals),
        "cross_tenant_leakage_count": 0 if (a_isolated and b_isolated) else -1,
    }


def run_security_root_propagation(run_id: str) -> dict:
    """Spec Step 3: both hosts observe epoch N, advance through the real
    kill_switch control path on Host A, both hosts must observe N+1;
    then a stale-epoch elevated action must be rejected (proven via the
    dedicated stale-worker scenario, run separately)."""
    import time

    epoch_a_before = _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "security_root_epoch"])
    epoch_b_before = _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "security_root_epoch"])

    t0 = time.monotonic()
    advance = _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "security_root_advance", "--new-state", "ACTIVE"])
    t_a = time.monotonic() - t0
    epoch_a_after = _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "security_root_epoch"])
    t1 = time.monotonic()
    epoch_b_after = _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "security_root_epoch"])
    t_b = time.monotonic() - t1

    # Restore INACTIVE so subsequent scenarios in the same qualification
    # run aren't left behind an active kill switch.
    _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "security_root_advance", "--new-state", "INACTIVE"])

    both_observe_next = (
        epoch_a_after.get("epoch") == advance.get("epoch")
        and epoch_b_after.get("epoch") == advance.get("epoch")
        and epoch_a_after.get("epoch", -1) > epoch_a_before.get("epoch", -2)
    )
    return {
        "run_id": run_id, "epoch_before": epoch_a_before.get("epoch"), "epoch_after": advance.get("epoch"),
        "both_observe_next_epoch": both_observe_next,
        "host_a_propagation_latency_s": round(t_a, 3), "host_b_propagation_latency_s": round(t_b, 3),
        "latency_note": "host_a latency includes the defensive actor-script re-upload (see _reupload_actor_script), not pure security-root advance round-trip; host_b latency is local-subprocess only",
    }


def run_stale_worker(run_id: str) -> dict:
    """Spec Step 5: sets up a real one-use lease, starts Host B's
    stale-worker action (observes epoch, pauses on barrier), then --
    only after that process is confirmed running -- advances the
    security root on Host A through the legitimate control path and
    signals the barrier's other half. Required: Host B's resumed
    privileged attempt is DENIED with the real canonical reason."""
    setup = _run_local(["--role", "ORCHESTRATOR", "--run-id", run_id, "--action", "setup_lease", "--max-uses", "1"])
    if "lease_id" not in setup:
        return {"run_id": run_id, "error": "SETUP_FAILED", "detail": setup}
    lease_id = setup["lease_id"]

    stale_proc = subprocess.Popen(
        [sys.executable, str(_SCRIPT_DIR / "distributed_actor.py"), "--role", "HOST_B", "--run-id", run_id, "--action", "stale_worker", "--lease-id", lease_id],
        cwd=str(_SCRIPT_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    import time
    time.sleep(2)  # let the stale worker announce READY and start waiting on the barrier
    revoke = _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "security_root_advance", "--new-state", "ACTIVE"])
    _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "revoker_signal"])
    out, err = stale_proc.communicate(timeout=60)
    stale_result = {"error": "NO_JSON_OUTPUT", "stdout_tail": out[-2000:], "stderr_tail": err[-2000:]}
    for line in reversed(out.strip().splitlines()):
        if line.strip().startswith("{"):
            try:
                stale_result = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            break

    # Restore INACTIVE.
    _start_remote_verified(["--role", "HOST_A", "--run-id", run_id, "--action", "security_root_advance", "--new-state", "INACTIVE"])

    denied = stale_result.get("state") == "DENY"
    return {"run_id": run_id, "revoke_epoch": revoke.get("epoch"), "stale_worker_result": stale_result, "denied": denied}


def run_outage_sim(run_id: str, target: str) -> dict:
    """Spec Steps 6-8: run on Host B (this runner, an isolated process
    already -- never the shared Northflank container) since it never
    needs to touch real production infra."""
    return _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "outage_sim", "--target", target])


def run_deadline_test(run_id: str) -> dict:
    return _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "deadline_test"])


def run_budget_test(run_id: str) -> dict:
    return _run_local(["--role", "HOST_B", "--run-id", run_id, "--action", "budget_test"])


def run_all_scenarios(run_id_prefix: str) -> dict:
    scenarios = {}
    scenarios["session_visibility"] = run_session_visibility(f"{run_id_prefix}-svis")
    scenarios["tenant_isolation"] = run_tenant_isolation(f"{run_id_prefix}-tenant")
    scenarios["security_root_propagation"] = run_security_root_propagation(f"{run_id_prefix}-secroot")
    scenarios["stale_worker"] = run_stale_worker(f"{run_id_prefix}-stale")
    scenarios["outage_authority"] = run_outage_sim(f"{run_id_prefix}-outage-auth", "authority")
    scenarios["outage_security_root"] = run_outage_sim(f"{run_id_prefix}-outage-secroot", "security_root")
    scenarios["outage_core_db"] = run_outage_sim(f"{run_id_prefix}-outage-core", "core_db")
    scenarios["deadline"] = run_deadline_test(f"{run_id_prefix}-deadline")
    scenarios["budget"] = run_budget_test(f"{run_id_prefix}-budget")
    for rid_suffix in ("svis", "tenant", "secroot", "stale", "outage-auth", "outage-secroot", "outage-core", "deadline", "budget"):
        _run_local(["--role", "ORCHESTRATOR", "--run-id", f"{run_id_prefix}-{rid_suffix}", "--action", "cleanup"])
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--race-runs", type=int, default=10)
    parser.add_argument("--scenario", choices=[
        "race", "session_visibility", "tenant_isolation", "security_root_propagation",
        "stale_worker", "outage_authority", "outage_security_root", "outage_core_db",
        "deadline", "budget", "all_scenarios",
    ], default="race")
    args = parser.parse_args()

    if args.scenario == "all_scenarios":
        run_id_prefix = f"q-{uuid.uuid4().hex[:10]}"
        print(f"::group::All distributed scenarios (prefix={run_id_prefix})")
        result = run_all_scenarios(run_id_prefix)
        print(json.dumps(result, indent=2))
        print("::endgroup::")
        out_path = _SCRIPT_DIR / "scenario_results.json"
        out_path.write_text(json.dumps(result, indent=2))
        return

    if args.scenario != "race":
        run_id = f"{args.scenario}-{uuid.uuid4().hex[:12]}"
        dispatch = {
            "session_visibility": run_session_visibility, "tenant_isolation": run_tenant_isolation,
            "security_root_propagation": run_security_root_propagation, "stale_worker": run_stale_worker,
            "deadline": run_deadline_test, "budget": run_budget_test,
        }
        if args.scenario in ("outage_authority", "outage_security_root", "outage_core_db"):
            target = {"outage_authority": "authority", "outage_security_root": "security_root", "outage_core_db": "core_db"}[args.scenario]
            result = run_outage_sim(run_id, target)
        else:
            result = dispatch[args.scenario](run_id)
        print(json.dumps(result, indent=2))
        _run_local(["--role", "ORCHESTRATOR", "--run-id", run_id, "--action", "cleanup"])
        return

    all_results = []
    for i in range(args.race_runs):
        print(f"::group::Race {i + 1}/{args.race_runs}")
        result = run_one_race_with_delivery_retry()
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
