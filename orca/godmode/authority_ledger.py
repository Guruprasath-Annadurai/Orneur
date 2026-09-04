"""
Phase 14A.1 -- shared low-level primitive for append-only authority-
event ledgers, factored out of `orca.godmode.revocation_ledger` (Phase
14A's original stale-restore fix) so `orca.godmode.kill_switch_ledger`
(this phase's kill-switch stale-restore fix) reuses the exact same,
already-tested file-I/O mechanics instead of duplicating them -- per
this phase's own governing spec: "Do not blindly duplicate code if a
shared durable authority-event abstraction would be cleaner."

What is intentionally NOT shared: the two ledgers' reconciliation
semantics differ (revocation is per-lease-id, "any lease_id ever
recorded here is revoked"; kill-switch is a singleton, "the
LATEST-BY-SEQUENCE event here is the authoritative current state") --
those stay in their own modules, since collapsing them into one
abstraction would obscure that real semantic difference rather than
simplify anything.

Every path here is resolved by a CALLER-SUPPLIED function, never a
module-level constant -- this directly addresses the real bug Phase 14A
found in the first version of `revocation_ledger.py` (a module-level
`LEDGER_PATH = ORCA_HOME / ...` bound stale `ORCA_HOME` for the whole
pytest session). There is no module-level path anywhere in this file.
"""
from __future__ import annotations

import json
from pathlib import Path


def append_entry(path: Path, entry: dict) -> None:
    """Append-only by construction -- always opens in append mode,
    never truncates or rewrites."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def read_all_entries(path: Path) -> list[dict]:
    """Every entry ever appended, in file order. Malformed/truncated
    lines are skipped, not treated as ledger corruption -- a truncated
    last line from a crash mid-write only loses that one entry, not the
    ones recorded before it (fail-closed in the sense of 'never lose
    real prior entries over one bad line', not 'ignore entries')."""
    if not path.exists():
        return []
    entries: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return entries
