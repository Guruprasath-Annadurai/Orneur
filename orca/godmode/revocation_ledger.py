"""
Phase 14 §67-68 -- append-only revocation ledger, the mitigation for a
REAL, CONFIRMED finding made during this phase's backup/restore testing:

    Restoring a leases.db (or leases table) backup taken BEFORE a
    revocation occurred silently un-revokes that lease -- the restored
    row's `revocation_state` reads back as ACTIVE, and `consume_use()`
    then genuinely succeeds again. Reproduced directly: issue a 5-use
    lease, back up the store, revoke the lease (confirmed REVOKED),
    restore the pre-revocation backup, and `consume_use()` returns
    True. This is exactly the risk Phase 14's governing spec calls out
    as "critical" (§67: "Restoring an old authority snapshot must not
    silently resurrect expired/revoked privilege").

Why this can't be fully solved by application code alone: a restore
from a backup necessarily loses anything written after that backup was
taken, including a revocation event. No code running AFTER a restore
can un-lose data that was never captured. Encryption/signing of the
leases table doesn't help either -- the OLD signed row is still validly
signed, just stale.

The mitigation here is the standard pattern for exactly this class of
problem: an APPEND-ONLY ledger of revocation events, deliberately kept
separate from the mutable `leases` table so it is not silently
overwritten by copying an old leases.db file over the new one, and a
`reconcile_after_restore()` function that MUST be run as a mandatory
step of any authority-store restore procedure (documented in
docs/orneur/phase-14/BACKUP_AND_RECOVERY.md) -- it re-applies every
revocation the ledger has ever recorded, regardless of the restored
row's own state, so "the ledger says revoked" always wins over "the
restored row says active."

This still has a real, disclosed limit: if the ledger file ITSELF is
part of the same backup/restore unit as leases.db and both are restored
from the same stale snapshot, the ledger is stale too, and this
mitigation does nothing -- the fix only works if the ledger is kept on
storage with an independent (ideally more frequent, or continuously
replicated/shipped-off-host) backup cadence than the leases table
itself. This is an operational requirement, not something code can
enforce by itself; it is stated explicitly, not silently assumed, in
BACKUP_AND_RECOVERY.md.
"""
from __future__ import annotations

from pathlib import Path

from orca.godmode.authority_ledger import append_entry, read_all_entries
from orca.godmode.contracts import now_iso


def _ledger_path() -> Path:
    """Recomputed on every call, never cached at import time -- this is
    the EXACT bug class this codebase has hit before (kill_switch's old
    `_KILL_SWITCH_FILE`, and lease_store's own `LEASE_DIR`/`_db_path()`
    split, whose docstring explains this precisely) and a real instance
    of it was found during this phase's own final leakage check with an
    earlier version of this function that read `orca.config.ORCA_HOME`
    directly as a plain module-level constant.

    Deliberately derived from `orca.godmode.lease_store.LEASE_DIR`
    (co-located as a sibling file next to `leases.db`, not inside it --
    that separation is the whole point of this ledger) rather than
    reading `orca.config.ORCA_HOME` independently: `LEASE_DIR` is
    already the established, monkeypatchable isolation point every test
    in this codebase's `tests/conftest.py` autouse fixture redirects --
    reading `ORCA_HOME` separately here would silently bypass that
    isolation for any test that patches `LEASE_DIR` without ALSO
    reloading `orca.config`, exactly the gap Phase 14A.1 found and
    closed for the new `kill_switch_ledger.py` sibling module."""
    import orca.godmode.lease_store as lease_store_mod

    return lease_store_mod.LEASE_DIR.parent / "revocation_ledger.jsonl"


def record_revocation(lease_id: str) -> None:
    """Append-only by construction. Safe to call more than once for the
    same lease_id (idempotent from the reconciler's point of view -- it
    just re-applies REVOKED, which is already a no-op if already
    REVOKED)."""
    append_entry(_ledger_path(), {"lease_id": lease_id, "revoked_at": now_iso()})


def revoked_lease_ids() -> set[str]:
    """Every lease_id this ledger has EVER recorded a revocation for."""
    return {entry["lease_id"] for entry in read_all_entries(_ledger_path()) if "lease_id" in entry}


def reconcile_after_restore() -> dict:
    """
    Mandatory post-restore step (see BACKUP_AND_RECOVERY.md): re-applies
    `revoke()` for every lease_id this ledger has ever recorded, so a
    restored leases table that shows a stale ACTIVE state for a lease
    the ledger says was revoked gets corrected before any elevated
    traffic resumes. Returns a summary for the operator to confirm the
    reconciliation actually did something (or correctly did nothing).
    """
    from orca.godmode.lease_store import get, revoke

    ledger_ids = revoked_lease_ids()
    reconciled = []
    already_consistent = []
    not_found = []
    for lease_id in ledger_ids:
        lease = get(lease_id)
        if lease is None:
            not_found.append(lease_id)
            continue
        if lease.revocation_state.value == "REVOKED":
            already_consistent.append(lease_id)
            continue
        revoke(lease_id)
        reconciled.append(lease_id)
    return {
        "ledger_entries": len(ledger_ids),
        "reconciled": reconciled,
        "already_consistent": already_consistent,
        "not_found_in_restored_store": not_found,
    }
