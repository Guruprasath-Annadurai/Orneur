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
    ])
    parser.add_argument("--lease-id", default=None)
    parser.add_argument("--max-uses", type=int, default=1)
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
    elif args.action == "cleanup":
        action_cleanup(args.run_id)


if __name__ == "__main__":
    main()
