"""
Phase 14A.1 -- append-only kill-switch event ledger, closing the exact
stale-restore vulnerability the Phase 14 report explicitly flagged as
still open for the kill switch (the same class already fixed for lease
revocation in `revocation_ledger.py`).

Reproduced directly before any fix: kill switch OFF, back up the
`godmode` directory, activate the kill switch (confirmed: an elevated
authorization attempt now DENIES), restore the pre-activation backup,
and the kill switch reads back INACTIVE -- elevated authorization
ALLOWS again. Full reproduction steps in
tests/test_kill_switch_stale_restore.py's first test, which deliberately
keeps reproducing the raw bug (with reconciliation skipped) so a future
change cannot silently regress this fix unnoticed.

Design (spec §3, §6): every activate/deactivate call appends a
monotonically-increasing-by-append-order event to this ledger, kept
deliberately separate from `orca.godmode.lease_store`'s
`kill_switch_state` table/row so restoring a backup of THAT table does
not touch this file. The CURRENT AUTHORITATIVE state after any restore
is "whichever event was appended LAST" -- not a counter that could be
confused with a lease's own numeric `uses_remaining`, and not something
a restored `kill_switch_state` row can override, since reconciliation
always re-derives effective state from this ledger's own last entry and
writes it back into `kill_switch_state`, never the other way around.

This does NOT use a numeric epoch/generation counter (spec §6 offers
this as an option). Reasoning: file append order under a single-writer-
per-event-at-a-time discipline (each `activate()`/`deactivate()` call
appends exactly one line before returning) already gives a total order
without needing a separate counter to get wrong -- "the last line in
the file" IS the epoch. A numeric epoch column would add a place to
introduce an off-by-one or a race in computing "next epoch," for no
extra safety this design doesn't already have. If cross-host
concurrent activate/deactivate calls ever need a stronger total order
than "each host's local append order," which they don't for a single
authoritative kill switch this codebase does not yet distribute writes
to, the ledger schema has room to grow a Lamport-clock-style field
later without breaking this file's format.

Same disclosed limit as `revocation_ledger.py`: if this ledger file is
part of the SAME backup/restore unit as `kill_switch_state`'s own
database, both restore stale together and this protection does
nothing. Operational requirement: back this ledger up on at least as
frequent, ideally independent, a cadence -- see
docs/orneur/phase-14/KILL_SWITCH_DURABILITY.md.
"""
from __future__ import annotations

from pathlib import Path

from orca.godmode.authority_ledger import append_entry, read_all_entries
from orca.godmode.contracts import now_iso


def _ledger_path() -> Path:
    """Recomputed on every call -- never a module-level constant, and
    deliberately derived from `orca.godmode.lease_store.LEASE_DIR`
    (co-located next to `leases.db`, not inside it) rather than reading
    `orca.config.ORCA_HOME` independently. See
    `orca.godmode.revocation_ledger._ledger_path()`'s docstring for the
    exact real bug (and the real isolation gap this specific choice of
    `LEASE_DIR` over `ORCA_HOME` closes) this convention exists to
    prevent."""
    import orca.godmode.lease_store as lease_store_mod

    return lease_store_mod.LEASE_DIR.parent / "kill_switch_ledger.jsonl"


def record_event(event: str, *, reason: str = "") -> None:
    """`event` is "ACTIVATE" or "DEACTIVATE". Append-only -- this is the
    durable history reconciliation reads back from."""
    append_entry(_ledger_path(), {"event": event, "at": now_iso(), "reason": reason})


def latest_authoritative_state() -> str | None:
    """The event type of the LAST entry ever appended -- "ACTIVATE",
    "DEACTIVATE", or None if the ledger has never recorded anything
    (a system that has never activated its kill switch, ever)."""
    entries = read_all_entries(_ledger_path())
    if not entries:
        return None
    return entries[-1].get("event")


def reconcile_after_restore() -> dict:
    """
    Mandatory post-restore step (spec §7, §13; see
    KILL_SWITCH_DURABILITY.md): re-derives effective kill-switch state
    from THIS ledger's last event, regardless of what the restored
    `kill_switch_state` row currently says, and writes that back via
    `orca.godmode.lease_store.ks_set_state()`. "The ledger's last event
    wins" -- a restored row claiming INACTIVE is overridden if the
    ledger's last recorded event was ACTIVATE, and vice versa.

    Fail-closed on write failure (spec §7's "fail closed if
    reconciliation cannot be performed"): if the authority store cannot
    be written to at all, this raises rather than returning a
    misleadingly-successful summary -- a caller silently swallowing
    that exception would otherwise proceed as if reconciliation
    succeeded when the store might still be serving a stale row.
    """
    from orca.godmode.lease_store import ks_set_state

    last_event = latest_authoritative_state()
    if last_event is None:
        return {"ledger_entries": 0, "action": "no_op_never_activated"}

    target_state = "ACTIVE" if last_event == "ACTIVATE" else "INACTIVE"
    ok = ks_set_state(target_state, now_iso() if target_state == "ACTIVE" else None, "reconciled from ledger after restore")
    if not ok:
        raise RuntimeError("kill-switch reconciliation could not write the authoritative state -- failing closed, not silently succeeding")
    return {"ledger_entries": len(read_all_entries(_ledger_path())), "action": f"reconciled_to_{target_state}"}
