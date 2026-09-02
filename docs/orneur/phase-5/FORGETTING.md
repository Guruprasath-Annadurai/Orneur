# Deliberate Forgetting (Phase 5)

## Lifecycle states (spec §29)

`MemoryLifecycleState`: `ACTIVE` → `DORMANT` → `ARCHIVED` → `PURGED`.
This phase's code paths that transition state:

- `orca/memory/deletion.py::delete_episode_and_reevaluate()` sets
  `ARCHIVED` on a semantic memory whose sole supporting episode was
  deleted and no other evidence remains.
- `orca/memory/episodic.py::delete_episode()` sets `PURGED` on the
  episode itself, as a **tombstone** (content redacted, the ledger line
  kept) — not a silent full removal (spec §29's own instruction:
  "forgetting is not silent evidence destruction").
- `orca/memory/deletion.py::delete_scope()` / `store.delete_scope()` /
  `episodic.delete_ledger()` perform genuine, full removal — used only
  for right-to-delete cascades (spec §38), where the operator's
  retention policy has already decided full erasure is required, not
  merely a lifecycle downgrade.

## Retention decisions this phase actually makes

- **Privacy / user deletion**: `orca/serve/account_delete.py`'s existing
  cascade (real, pre-Phase-5) now also calls
  `orca.memory.deletion.delete_scope()` and
  `orca.brain.memory.SemanticMemory.delete_session_facts()` — see
  [PHASE_5_CLOSURE.md](PHASE_5_CLOSURE.md) for the audit finding this
  closes.
- **Staleness**: see [TEMPORAL_MEMORY.md](TEMPORAL_MEMORY.md) and the
  decay section below — a stale memory is flagged, not deleted.
- **Legal requirement / retention policy**: this phase implements the
  *mechanism* (lifecycle states, tombstones, cascade deletion); it does
  not implement a jurisdiction-specific legal retention *policy engine*
  — same posture as `orca/serve/account_delete.py`'s own documented
  scope (a policy/legal judgment call for the operator, not something
  resolved automatically in code).

## Decay policy depends on memory class (spec §30)

`orca/memory/salience.py::is_stale()`:

- Volatile facts (pricing/version/availability/personnel/deployment —
  matched via `_VOLATILE_FACT_RE`) get a **3-day** TTL.
- Everything else gets a **90-day** TTL.
- A claim matching `_NEVER_DECAY_RE` ("always", "permanently", "by
  definition", "is defined as") **never** decays — approximating spec
  §30's "mathematical truths, verified historical events, explicit
  long-term user decisions" exception. This is a heuristic on the claim
  text, not a separate flag the codebase tracks elsewhere; documented as
  such rather than claimed as precise classification.
- `DISPROVEN` records are never marked stale (staleness is about
  *currency*, not correctness — a disproven fact doesn't need a
  freshness check, it needs the Memory Firewall's separate DISPROVEN
  block, see [MEMORY_FIREWALL.md](MEMORY_FIREWALL.md)).

## What this phase does NOT implement

An automated background sweep that walks every stored memory and
transitions lifecycle states on a schedule. Staleness/decay are computed
**on recall** (lazily), not via a cron-like process — consistent with
spec §48's "memory must not blindly add another path to every request"
philosophy applied in reverse: no new always-on background job either.
A future phase could add scheduled sweeps without changing
`is_stale()`'s contract.
