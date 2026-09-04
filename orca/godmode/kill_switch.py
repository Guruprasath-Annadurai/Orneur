"""
System-level Godmode kill switch (Phase 10 spec §15; Phase 14A.1
stale-restore closure).

Phase 14A.1 rewrite: state now lives in the SAME authority database as
Godmode leases (`orca.godmode.lease_store`'s `kill_switch_state` table
-- SQLite file or Postgres, whichever backend is configured) rather
than a standalone flag file. This closes two things at once:

1. Cross-worker/cross-host visibility (spec §21) comes for free in the
   Postgres/DISTRIBUTED profile -- every worker querying the same
   shared database sees the same row, live, exactly like leases
   already do.
2. It puts kill-switch state changes through the SAME atomic
   transaction discipline (`BEGIN IMMEDIATE` / `SELECT...FOR UPDATE`)
   Phase 13's lease work already proved cross-process-safe.

The REAL vulnerability this phase found and fixed: restoring an old
backup of that same database silently reverts kill-switch state too --
reproduced directly (kill switch OFF -> backup -> activate -> confirmed
DENY -> restore old backup -> kill switch reads INACTIVE again ->
elevated authorization ALLOWS). Fixed via `orca.godmode.kill_switch_ledger`,
an append-only event ledger kept deliberately separate from the state
table's own backup unit, plus a mandatory `reconcile_after_restore()`
call every restore procedure must run (see
docs/orneur/phase-14/KILL_SWITCH_DURABILITY.md).

Every `activate()`/`deactivate()` call here writes to BOTH the live
state table (so `is_active()` stays a fast, single-row read) AND the
ledger (so a later stale restore can be caught and corrected) -- same
two-layer pattern already proven for lease revocation in Phase 14A.

The kill switch itself never depends on model behavior -- it is
checked by Python code only; no tool exposes this module to
`AgentToolRegistry` at all (see AGENT_INTEGRATION.md).
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.godmode.contracts import now_iso


@dataclass
class KillSwitchStatus:
    active: bool
    activated_at: str | None
    reason: str | None


def activate(*, reason: str = "") -> KillSwitchStatus:
    from orca.godmode.lease_store import ks_set_state
    from orca.godmode.kill_switch_ledger import record_event

    at = now_iso()
    ks_set_state("ACTIVE", at, reason)
    record_event("ACTIVATE", reason=reason)
    return status()


def deactivate() -> KillSwitchStatus:
    from orca.godmode.lease_store import ks_set_state
    from orca.godmode.kill_switch_ledger import record_event

    ks_set_state("INACTIVE", None, None)
    record_event("DEACTIVATE")
    return status()


def is_active() -> bool:
    """Fail-closed (spec §19): if the authority store cannot be reached
    at all, `ks_get_state()` returns "UNKNOWN" -- treated here as
    active, since an uncertain kill-switch state must never be
    interpreted as permission to proceed with elevated actions."""
    from orca.godmode.lease_store import ks_get_state

    state, _, _ = ks_get_state()
    return state != "INACTIVE"


def status() -> KillSwitchStatus:
    from orca.godmode.lease_store import ks_get_state

    state, activated_at, reason = ks_get_state()
    if state == "UNKNOWN":
        # Store unreachable -- report as active/unknown-reason rather
        # than fabricating a specific activation time, but the boolean
        # itself must still say "assume active" (spec §19).
        return KillSwitchStatus(active=True, activated_at=None, reason="AUTHORITY_STORE_UNAVAILABLE")
    if state != "ACTIVE":
        return KillSwitchStatus(active=False, activated_at=None, reason=None)
    return KillSwitchStatus(active=True, activated_at=activated_at, reason=reason)
