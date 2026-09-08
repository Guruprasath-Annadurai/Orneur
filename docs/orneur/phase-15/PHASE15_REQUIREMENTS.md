# Phase 15 Requirements Registry

Stable requirement IDs, per master spec §5. Populated incrementally as
each subphase defines and implements requirements — this file is the
traceability root: every requirement here must map to implementation,
tests, and evidence (spec §5, §36).

Format per entry:

```
REQ-<AREA>-<NAME>-<NNN>
  Source: <spec section>
  Statement: <what must be true>
  Acceptance criteria: <testable conditions>
  Status: UNIMPLEMENTED | IMPLEMENTED | VERIFIED
  Implementation: <file(s)>
  Tests: <test file(s)>
  Evidence: <PHASE15_EVIDENCE.md checkpoint reference>
```

## Areas (reserved prefixes)

- `REQ-MISSION-*` — Mission Engine (spec §6)
- `REQ-WINDOW-*` — Six-hour autonomous mission window (spec §7)
- `REQ-AUTONOMY-*` — Autonomy levels L0-L4 (spec §8)
- `REQ-STATE-*` — Durable mission state (spec §9)
- `REQ-CKPT-*` — Checkpoint system (spec §10)
- `REQ-OPIDEM-*` — Operation idempotency (spec §11)
- `REQ-SANDBOX-*` — Execution sandbox (spec §12)
- `REQ-SECRET-*` — Secrets handling (spec §13)
- `REQ-AUTH-*` — Authority engine (spec §14)
- `REQ-ANTIGAME-*` — Anti-test-gaming (spec §15)
- `REQ-COURT-*` — Cognitive Court (spec §16)
- `REQ-NOFAKE-*` — No fake completion (spec §17)
- `REQ-PROOF-*` — Production Proof (spec §18)
- `REQ-SUPPLY-*` — Supply chain / licensing (spec §19)
- `REQ-DEPLOY-*` — Deployment + rollback (spec §20)
- `REQ-OUTCOME-*` — Post-launch outcome loop interface (spec §21)
- `REQ-RELAY-*` — Relay core (spec §22)
- `REQ-RELAYMODE-*` — Relay modes (spec §23)
- `REQ-THREAT-*` — Relay threat model (spec §24)
- `REQ-DEVICE-*` — Device trust / session revocation (spec §25)
- `REQ-RECONNECT-*` — Network loss / reconnect truthfulness (spec §26)
- `REQ-MULTIDEV-*` — Multi-device consistency (spec §27)

## Entries

The requirement registry is real, executable code, not static prose —
this file is the index, not the source of truth (a markdown copy
would drift from the enforced lifecycle in code). See:

- `orca/mission/requirements.py` — the compiler itself: `Requirement`
  dataclass (ID format enforced by regex, non-empty acceptance
  criteria enforced at construction), `RequirementStatus`
  (`UNIMPLEMENTED` → `IMPLEMENTED` → `VERIFIED`, forward-only,
  enforced by `transition()` — `IMPLEMENTED` requires an
  implementation-file reference, `VERIFIED` requires both a test-file
  reference and an evidence reference).
- `orca/mission/requirements_seed.py` — the Phase 15.1 initial
  compilation: 19 requirements spanning Mission Engine, the six-hour
  window, autonomy levels, durable state, checkpoints, operation
  idempotency, the execution sandbox, the authority engine,
  anti-test-gaming, no-fake-completion, Production Proof, Relay core,
  device trust, and reconnect truthfulness. Grows across later
  subphases as they define their own requirements — not finalized in
  one pass.
- `tests/test_mission_requirements.py` — 19 tests proving the
  lifecycle enforcement is real (malformed IDs rejected, empty
  acceptance criteria rejected, `IMPLEMENTED` without an
  implementation file rejected, `VERIFIED` without both a test file
  and evidence reference rejected, no skipping `UNIMPLEMENTED` →
  `VERIFIED`, no backward/duplicate transitions, `VERIFIED` is
  terminal) and that the seed data itself is well-formed (no
  duplicate IDs, broad spec-area coverage).

To inspect current requirement status programmatically:

```python
from orca.mission.requirements_seed import seed_registry
from orca.mission.requirements import all_requirements, by_status, RequirementStatus

seed_registry()
for req in all_requirements():
    print(req.id, req.status.value)
```
