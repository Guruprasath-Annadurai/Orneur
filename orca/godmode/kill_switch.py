"""
System-level Godmode kill switch (Phase 10 spec §15; Phase 14A.1
authority-database migration; Phase 14A.2 security-root closure).

Phase 14A.2 rewrite: `is_active()` now consults
`orca.godmode.security_root` as GROUND TRUTH -- a store that lives
structurally outside `ORCA_HOME` and outside the Godmode authority
database (SQLite or Postgres), specifically so that restoring EITHER
of those together, in any combination, including the append-only
ledger Phase 14A.1 added, can never roll effective kill-switch state
backward. This closes the REAL vulnerability Phase 14A.1's own closure
disclosed as a known limitation: restoring the kill-switch ledger
TOGETHER WITH the stale authority database restores both to the same
old state, defeating stale-restore protection entirely. Reproduced
directly before this fix (see
`orca.godmode.security_root`'s module docstring and
`tests/test_security_root_whole_snapshot.py`'s first test).

`activate()`/`deactivate()` write to the security root FIRST (the
authoritative write), then to the Phase 14A.1 authority-database mirror
and ledger SECOND (spec §16's crash-safety ordering: if a crash happens
between the two, the security root -- ground truth -- is already
correct; the mirror catching up late is a display/audit-convenience
gap, never a security gap). The mirror is kept for two reasons: (1)
`orca.godmode.lease_store.ks_get_state()` remains available for
`/readyz`'s existing "authority_store" reporting field without a
behavior change there, and (2) `kill_switch_ledger.py`'s
`reconcile_after_restore()` (Phase 14A.1's own fix) remains meaningful
defense-in-depth for the case where the SECURITY ROOT is fine but the
ordinary authority database was restored stale on its own (the
originally-fixed, narrower scenario) -- it is simply no longer the
ONLY layer of protection.

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
    from orca.godmode import security_root
    from orca.godmode.lease_store import ks_set_state
    from orca.godmode.kill_switch_ledger import record_event

    security_root.advance("ACTIVE", reason=reason)
    at = now_iso()
    ks_set_state("ACTIVE", at, reason)
    record_event("ACTIVATE", reason=reason)
    return status()


def deactivate() -> KillSwitchStatus:
    from orca.godmode import security_root
    from orca.godmode.lease_store import ks_set_state
    from orca.godmode.kill_switch_ledger import record_event

    security_root.advance("INACTIVE")
    ks_set_state("INACTIVE", None, None)
    record_event("DEACTIVATE")
    return status()


def is_active() -> bool:
    """Ground truth is the security root (Phase 14A.2) -- fail-closed
    (spec §9/§19): an unreachable root, or any state other than the
    exact string "INACTIVE", is treated as active."""
    from orca.godmode import security_root

    return security_root.is_active()


def status() -> KillSwitchStatus:
    from orca.godmode import security_root

    epoch, state = security_root.get_epoch_and_state()
    if state == "UNKNOWN":
        return KillSwitchStatus(active=True, activated_at=None, reason="SECURITY_ROOT_UNAVAILABLE")
    if state != "ACTIVE":
        return KillSwitchStatus(active=False, activated_at=None, reason=None)
    # activated_at/reason are cosmetic display fields -- read from the
    # authority-database mirror (Phase 14A.1) since the security root
    # itself stores only epoch/state/updated_at/reason, not a separate
    # human-facing "activated_at" distinct from its own updated_at.
    from orca.godmode.lease_store import ks_get_state
    _, activated_at, reason = ks_get_state()
    return KillSwitchStatus(active=True, activated_at=activated_at, reason=reason)
