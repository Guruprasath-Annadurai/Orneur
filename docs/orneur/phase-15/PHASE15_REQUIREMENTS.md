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

_None yet implemented. First entries are compiled in Phase 15.1._
