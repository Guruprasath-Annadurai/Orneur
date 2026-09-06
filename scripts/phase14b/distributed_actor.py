#!/usr/bin/env python3
"""
Phase 14B distributed qualification actor.

Runs as either HOST_A (inside the Northflank orneur-api-a container, via
`northflank command-exec`) or HOST_B (directly on a GitHub-hosted
ephemeral Actions runner). Both roles run this exact same script against
the exact same shared Supabase backends (core/authority/security-root),
distinguished only by --role for barrier naming and result labeling --
there is no special-cased "Mac" code path, and this script has no local
persistence: every durable read/write goes through `orca.godmode`'s own
Postgres-backed stores (`ORNEUR_DEPLOYMENT_PROFILE=DISTRIBUTED` is
required; the script refuses to run under SOVEREIGN).

All test state (tenants, leases, barrier rows) is namespaced by
--run-id and cleaned up by `action=cleanup` at the end of a
qualification run. This script never touches production data -- it
only ever creates and consumes its own run-scoped fixtures through the
real `orca.godmode.issuance` / `orca.godmode.resolution` /
`orca.godmode.durable_audit` APIs.

Output is always a single line of JSON to stdout so a calling
orchestrator (the GitHub Actions job, or `northflank command-exec`'s
own stdout capture) can parse the result mechanically. No secret value
is ever printed.
"""
from __future__ import annotations

import argparse
import json
import sys

import barrier as barrier_mod


def _require_distributed() -> None:
    from orca.godmode.deployment_profile import get_profile
    if get_profile() != "DISTRIBUTED":
        print(json.dumps({"error": "REFUSED_NOT_DISTRIBUTED", "profile": get_profile()}))
        sys.exit(1)


def _tenant_id(run_id: str) -> str:
    return f"phase14b-{run_id}"


def action_setup_lease(run_id: str, max_uses: int) -> None:
    """Issues one real lease via the actual issuance authority
    (orca.godmode.issuance.issue_lease), run-scoped. Prints only the
    lease_id (not a secret -- an opaque identifier, same class of value
    already returned by every existing Phase 10-14 test in this repo)."""
    from datetime import datetime, timedelta, timezone
    from orca.godmode.canonical import hash_arguments
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease

    tenant_id = _tenant_id(run_id)
    approval = GodmodeApproval(
        approval_id=f"ap-{run_id}", principal_id="phase14b-qualification", tenant_id=tenant_id,
        capability_domain=CapabilityDomain.CONNECTOR, capability="CONNECTOR_WRITE",
        resource_scope=f"phase14b-{run_id}", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=900, reason="Phase 14B distributed qualification -- one-use lease race",
        approved_by="human:phase14b-qualification",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:phase14b-qualification", max_uses=max_uses)
    print(json.dumps({"lease_id": lease.lease_id, "tenant_id": tenant_id, "max_uses": max_uses}))


def action_race(run_id: str, role: str, lease_id: str) -> None:
    """The mandatory one-use lease race gate. Announces READY on the
    shared barrier, waits for the OTHER actor, then both attempt
    resolve_and_consume_lease() as close to simultaneously as a
    cross-network barrier release permits -- not a blind sleep."""
    from orca.godmode.contracts import CapabilityDomain
    from orca.godmode.resolution import resolve_and_consume_lease

    tenant_id = _tenant_id(run_id)
    barrier_mod.announce_ready(run_id, role, payload=lease_id)
    released = barrier_mod.wait_for_both(run_id, ("HOST_A", "HOST_B"), timeout_s=45)
    if not released:
        print(json.dumps({"role": role, "error": "BARRIER_TIMEOUT"}))
        sys.exit(1)

    decision = resolve_and_consume_lease(
        lease_id, tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope=f"phase14b-{run_id}", operation_scope="write",
        arguments={}, principal_id=f"phase14b-{role.lower()}", trace_id=f"phase14b-{run_id}-{role}",
    )
    print(json.dumps({
        "role": role, "state": decision.state.value, "reasons": decision.reasons,
        "lease_id": lease_id, "run_id": run_id,
    }))


def action_read_audit(run_id: str) -> None:
    """Reads back the durable audit trail for this run's tenant --
    used to verify cross-host durable-audit visibility (spec §11) and
    the GODMODE_FALSE_COMMITTED_AUDIT invariant."""
    from orca.godmode.durable_audit import count_false_committed_audit, list_events_for_tenant

    tenant_id = _tenant_id(run_id)
    events = list_events_for_tenant(tenant_id)
    committed = [e for e in events if e["event_type"] == "AUTHORIZATION_COMMITTED"]
    lost_race = [e for e in events if e["event_type"] == "AUTHORIZATION_LOST_RACE"]
    print(json.dumps({
        "run_id": run_id, "tenant_id": tenant_id, "total_events": len(events),
        "committed": len(committed), "lost_race": len(lost_race),
        "false_committed_audit": count_false_committed_audit(events),
    }))


def action_security_root_epoch(run_id: str) -> None:
    from orca.godmode.security_root import get_epoch_and_state
    epoch, active = get_epoch_and_state()
    print(json.dumps({"run_id": run_id, "epoch": epoch, "kill_switch_active": active}))


def action_security_root_advance(run_id: str, new_state: str) -> None:
    """The legitimate control path (spec Step 3): kill_switch.activate()/
    deactivate() writes through to the real security root first, then
    the authority-DB mirror -- not a raw SQL UPDATE."""
    from orca.godmode import kill_switch
    status = kill_switch.activate(reason=f"phase14b-{run_id}") if new_state == "ACTIVE" else kill_switch.deactivate()
    from orca.godmode.security_root import get_epoch_and_state
    epoch, state = get_epoch_and_state()
    print(json.dumps({"run_id": run_id, "epoch": epoch, "state": state, "kill_switch_active": status.active}))


def action_write_tenant_state(run_id: str, tenant_suffix: str, role: str) -> None:
    """Writes one real, durable, tenant-scoped record via the actual
    ORNEUR durable-audit abstraction (orca.godmode.durable_audit),
    the same durable-state system this whole phase's authority race
    already depends on -- not a raw SQL INSERT standing in for
    'application state'. Used for both cross-host state visibility
    (spec Step 1) and tenant isolation (spec Step 2): the tenant_id is
    parameterized so the SAME primitive proves both."""
    from orca.godmode.contracts import ElevationAuditEvent, ElevationAuditEventType
    from orca.godmode.durable_audit import record_event_durable

    tenant_id = f"phase14b-{run_id}-{tenant_suffix}"
    event = ElevationAuditEvent(
        event_type=ElevationAuditEventType.AUTHORIZATION_ATTEMPT,
        principal_id=f"written-by-{role}", tenant_id=tenant_id,
        lease_id=f"state-{run_id}-{tenant_suffix}", result="PENDING_CONSUME",
        trace_id=f"phase14b-{run_id}-{tenant_suffix}-{role}",
    )
    ok = record_event_durable(event)
    print(json.dumps({"run_id": run_id, "tenant_suffix": tenant_suffix, "role": role, "written": ok, "tenant_id": tenant_id}))


def action_read_tenant_state(run_id: str, tenant_suffix: str, role: str) -> None:
    """Reads back tenant-scoped durable state via the same real
    abstraction. The caller (orchestrator) compares which `written-by-*`
    principals appear here against what was actually written to THIS
    tenant_suffix, proving both cross-host visibility (same tenant,
    different host) and tenant isolation (different tenant, must be
    empty/absent) with the same primitive."""
    from orca.godmode.durable_audit import list_events_for_tenant

    tenant_id = f"phase14b-{run_id}-{tenant_suffix}"
    events = list_events_for_tenant(tenant_id)
    principals = sorted({e["principal_id"] for e in events})
    print(json.dumps({"run_id": run_id, "tenant_suffix": tenant_suffix, "role": role, "tenant_id": tenant_id, "principals_seen": principals, "count": len(events)}))


def action_stale_worker(run_id: str, lease_id: str) -> None:
    """Spec Step 5: this actor observes/records the kill-switch state it
    believes is current, PAUSES on the shared barrier (giving the
    orchestrator a window to revoke/advance security-root state through
    the legitimate control path -- action_security_root_advance, called
    separately), then resumes and attempts the SAME privileged action
    using only its (now provably stale) prior knowledge. The real
    is_active()/resolve_and_consume_lease() call is what must
    reject it -- this script never fabricates a rejection reason."""
    from orca.godmode.contracts import CapabilityDomain
    from orca.godmode.resolution import resolve_and_consume_lease
    from orca.godmode.security_root import get_epoch_and_state

    observed_epoch, observed_state = get_epoch_and_state()
    barrier_mod.announce_ready(run_id, "STALE_WORKER_OBSERVED", payload=str(observed_epoch))
    released = barrier_mod.wait_for_both(run_id, ("STALE_WORKER_OBSERVED", "REVOKER_DONE"), timeout_s=45)
    if not released:
        print(json.dumps({"error": "BARRIER_TIMEOUT", "observed_epoch": observed_epoch}))
        sys.exit(1)

    tenant_id = _tenant_id(run_id)
    decision = resolve_and_consume_lease(
        lease_id, tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope=f"phase14b-{run_id}", operation_scope="write",
        arguments={}, principal_id="phase14b-stale-worker", trace_id=f"phase14b-{run_id}-stale",
    )
    print(json.dumps({
        "run_id": run_id, "observed_epoch_before_pause": observed_epoch,
        "state": decision.state.value, "reasons": decision.reasons,
    }))


def action_revoker_signal(run_id: str) -> None:
    """The other half of the stale-worker scenario: announces
    REVOKER_DONE on the barrier only AFTER the caller has already
    performed a real security_root_advance -- ordering is enforced by
    the orchestrator calling this action strictly after the advance
    action returns, not by anything inside this script."""
    barrier_mod.announce_ready(run_id, "REVOKER_DONE", payload="done")
    print(json.dumps({"run_id": run_id, "signaled": "REVOKER_DONE"}))


def action_deadline_test(run_id: str) -> None:
    """Spec Step 10: issues a lease with a real, short (2s) expires_at,
    waits past it, then attempts resolve_and_consume_lease() -- the
    real is_expired() check (orca/godmode/lease_store.py) must reject
    it, not a fabricated timeout."""
    import time
    from datetime import datetime, timedelta, timezone
    from orca.godmode.canonical import hash_arguments
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.resolution import resolve_and_consume_lease

    tenant_id = _tenant_id(run_id)
    approval = GodmodeApproval(
        approval_id=f"ap-deadline-{run_id}", principal_id="phase14b-qualification", tenant_id=tenant_id,
        capability_domain=CapabilityDomain.CONNECTOR, capability="CONNECTOR_WRITE",
        resource_scope=f"phase14b-deadline-{run_id}", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=2, reason="Phase 14B deadline test -- deliberately short-lived",
        approved_by="human:phase14b-qualification",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:phase14b-qualification", max_uses=1)
    time.sleep(4)
    decision = resolve_and_consume_lease(
        lease.lease_id, tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope=f"phase14b-deadline-{run_id}", operation_scope="write",
        arguments={}, principal_id="phase14b-deadline-test", trace_id=f"phase14b-{run_id}-deadline",
    )
    print(json.dumps({"run_id": run_id, "state": decision.state.value, "reasons": decision.reasons}))


def action_resolve_once(run_id: str, lease_id: str, principal_suffix: str) -> None:
    """Spec Step 4 (fresh-runner/disposable-compute recovery): a single,
    non-racing resolve_and_consume_lease() attempt against a lease_id
    that was created by a DIFFERENT, already-dead process -- possibly a
    prior, now-terminated GitHub Actions runner. This process has no
    filesystem or memory continuity with whatever created the lease;
    every fact it needs (lease existence, uses remaining, expiry,
    tenant/scope binding) comes only from the shared Postgres-backed
    orca.godmode stores. Used twice across two separate workflow
    dispatches with the SAME lease_id to prove both "a fresh runner can
    recover real prior state" and "a consumed one-use lease cannot be
    replayed by yet another fresh runner."."""
    from orca.godmode.contracts import CapabilityDomain
    from orca.godmode.resolution import resolve_and_consume_lease

    tenant_id = _tenant_id(run_id)
    decision = resolve_and_consume_lease(
        lease_id, tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope=f"phase14b-{run_id}", operation_scope="write",
        arguments={}, principal_id=f"phase14b-freshrunner-{principal_suffix}", trace_id=f"phase14b-{run_id}-freshrunner-{principal_suffix}",
    )
    print(json.dumps({"run_id": run_id, "lease_id": lease_id, "state": decision.state.value, "reasons": decision.reasons}))


def action_budget_test(run_id: str) -> None:
    """Spec Step 11: single-actor, sequential proof that a lease's
    max_uses budget is enforced -- consume once (must succeed), then
    attempt a second consumption of the SAME lease (must be denied,
    budget exhausted). No race/barrier needed -- this is deliberately
    sequential to isolate budget enforcement from race-timing."""
    from orca.godmode.canonical import hash_arguments
    from datetime import datetime, timedelta, timezone
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.resolution import resolve_and_consume_lease

    tenant_id = _tenant_id(run_id)
    approval = GodmodeApproval(
        approval_id=f"ap-budget-{run_id}", principal_id="phase14b-qualification", tenant_id=tenant_id,
        capability_domain=CapabilityDomain.CONNECTOR, capability="CONNECTOR_WRITE",
        resource_scope=f"phase14b-budget-{run_id}", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=900, reason="Phase 14B budget test", approved_by="human:phase14b-qualification",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:phase14b-qualification", max_uses=1)

    def _attempt():
        return resolve_and_consume_lease(
            lease.lease_id, tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
            capability="CONNECTOR_WRITE", resource_scope=f"phase14b-budget-{run_id}", operation_scope="write",
            arguments={}, principal_id="phase14b-budget-test", trace_id=f"phase14b-{run_id}-budget",
        )

    first = _attempt()
    second = _attempt()
    print(json.dumps({
        "run_id": run_id,
        "first_state": first.state.value, "first_reasons": first.reasons,
        "second_state": second.state.value, "second_reasons": second.reasons,
    }))


def action_outage_sim(run_id: str, target: str) -> None:
    """Spec Steps 6-8: CLIENT_PATH_OUTAGE_SIMULATION only -- makes the
    named backend's own env var unreachable/invalid for THIS isolated
    process only (never touches the real shared Supabase infrastructure)
    and attempts a real operation against it, confirming fail-closed
    behavior via the real deployment_profile/security_root/lease_store
    code paths (never a SQLite/SOVEREIGN fallback). `target` is one of
    authority | security_root | core_db."""
    import os
    import importlib

    env_var = {
        "authority": "ORNEUR_GODMODE_DATABASE_URL",
        "security_root": "ORNEUR_SECURITY_ROOT_DATABASE_URL",
        "core_db": "ORNEUR_DATABASE_URL",
    }[target]
    os.environ[env_var] = "postgresql://nonexistent-host-for-phase14b-outage-sim:5432/nope"

    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.security_root as security_root_mod
    importlib.reload(security_root_mod)

    result = {"run_id": run_id, "target": target}
    try:
        if target == "authority":
            from orca.godmode.contracts import CapabilityLease
            probe = CapabilityLease(lease_id=f"phase14b-outage-probe-{run_id}", tenant_id=f"phase14b-{run_id}")
            lease_store_mod.save(probe)
            result["unexpected_success"] = True
        elif target == "security_root":
            epoch, state = security_root_mod.get_epoch_and_state()
            result["epoch"] = epoch
            result["state"] = state
            result["fails_closed"] = (state != "INACTIVE")
        elif target == "core_db":
            from orca.godmode.deployment_profile import require_distributed_core_db_url
            import psycopg
            url = require_distributed_core_db_url()
            try:
                conn = psycopg.connect(url, connect_timeout=5)
                conn.close()
                result["unexpected_connect_success"] = True
            except psycopg.Error:
                result["classification"] = "CONNECTION_FAILURE_AS_EXPECTED"
    except Exception as e:
        result["classification"] = type(e).__name__
        result["fails_closed"] = True

    print(json.dumps(result))


def action_cleanup(run_id: str) -> None:
    """Deletes only this run's barrier rows. Leases/audit rows are left
    in place deliberately -- durable audit is append-only by design
    (spec §19: 'do not delete immutable audit evidence')."""
    barrier_mod.cleanup(run_id)
    print(json.dumps({"run_id": run_id, "cleaned_up": "barrier_only"}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["HOST_A", "HOST_B", "ORCHESTRATOR"], required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--action", required=True, choices=[
        "setup_lease", "race", "read_audit", "security_root_epoch", "cleanup",
        "security_root_advance", "write_tenant_state", "read_tenant_state",
        "stale_worker", "revoker_signal", "deadline_test", "budget_test",
        "outage_sim", "resolve_once",
    ])
    parser.add_argument("--lease-id", default=None)
    parser.add_argument("--max-uses", type=int, default=1)
    parser.add_argument("--new-state", choices=["ACTIVE", "INACTIVE"], default=None)
    parser.add_argument("--tenant-suffix", default=None)
    parser.add_argument("--role-label", default=None)
    parser.add_argument("--target", choices=["authority", "security_root", "core_db"], default=None)
    parser.add_argument("--principal-suffix", default=None)
    args = parser.parse_args()

    _require_distributed()

    if args.action == "setup_lease":
        action_setup_lease(args.run_id, args.max_uses)
    elif args.action == "race":
        if not args.lease_id:
            print(json.dumps({"error": "MISSING_LEASE_ID"}))
            sys.exit(1)
        action_race(args.run_id, args.role, args.lease_id)
    elif args.action == "read_audit":
        action_read_audit(args.run_id)
    elif args.action == "security_root_epoch":
        action_security_root_epoch(args.run_id)
    elif args.action == "security_root_advance":
        if not args.new_state:
            print(json.dumps({"error": "MISSING_NEW_STATE"}))
            sys.exit(1)
        action_security_root_advance(args.run_id, args.new_state)
    elif args.action == "write_tenant_state":
        if not args.tenant_suffix or not args.role_label:
            print(json.dumps({"error": "MISSING_TENANT_SUFFIX_OR_ROLE_LABEL"}))
            sys.exit(1)
        action_write_tenant_state(args.run_id, args.tenant_suffix, args.role_label)
    elif args.action == "read_tenant_state":
        if not args.tenant_suffix or not args.role_label:
            print(json.dumps({"error": "MISSING_TENANT_SUFFIX_OR_ROLE_LABEL"}))
            sys.exit(1)
        action_read_tenant_state(args.run_id, args.tenant_suffix, args.role_label)
    elif args.action == "stale_worker":
        if not args.lease_id:
            print(json.dumps({"error": "MISSING_LEASE_ID"}))
            sys.exit(1)
        action_stale_worker(args.run_id, args.lease_id)
    elif args.action == "revoker_signal":
        action_revoker_signal(args.run_id)
    elif args.action == "deadline_test":
        action_deadline_test(args.run_id)
    elif args.action == "budget_test":
        action_budget_test(args.run_id)
    elif args.action == "outage_sim":
        if not args.target:
            print(json.dumps({"error": "MISSING_TARGET"}))
            sys.exit(1)
        action_outage_sim(args.run_id, args.target)
    elif args.action == "resolve_once":
        if not args.lease_id or not args.principal_suffix:
            print(json.dumps({"error": "MISSING_LEASE_ID_OR_PRINCIPAL_SUFFIX"}))
            sys.exit(1)
        action_resolve_once(args.run_id, args.lease_id, args.principal_suffix)
    elif args.action == "cleanup":
        action_cleanup(args.run_id)


if __name__ == "__main__":
    main()
