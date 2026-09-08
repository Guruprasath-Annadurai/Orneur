# Phase 15 Implementation Plan

Derived from real repository inspection performed at the start of
Phase 15.0 (branch `session-update-2026-08-25`, HEAD `d0ee011`, clean
working tree). This is a dependency map, not a rewrite plan — Phase 15
builds ORNEUR Code + ORNEUR Relay on top of what already exists in
`orca/`, per the master spec's explicit "do not recreate solved
infrastructure" instruction.

## What already exists (do not replace)

| Spec concept | Existing code | Notes |
|---|---|---|
| Authority Engine (§14) | `orca/godmode/` — `authority_ledger.py`, `capability.py`, `delegation.py`, `policy.py`, `resolution.py`, `revocation_ledger.py`, `kill_switch.py`, `kill_switch_ledger.py`, `lease_store.py`, `durable_audit.py`, `security_root.py`, `cancellation.py`, `session.py`, `deployment_profile.py` | Mature, tested across Phases 9-14C.1 (184/184 in the Godmode/cancellation/authority subset per Phase 14C.1 evidence). Phase 15.5 must integrate with this, not build a parallel authority system. |
| Execution sandbox precedent (§12) | `orca/code/sandbox.py` | AST-static-analysis + subprocess isolation + timeout, used by `/api/code/run`. A real, narrow precedent (single-language, no container isolation) — Phase 15.6 extends this pattern for a broader governed execution boundary rather than discarding it. |
| Durable table pattern | `orca/auth/db.py` (`CREATE TABLE IF NOT EXISTS ...` embedded in Python, applied idempotently) | No Alembic/SQLAlchemy migration framework exists anywhere in this repo (confirmed via `pyproject.toml` — only `psycopg[binary]`). Phase 15.2's schema follows this same established convention rather than introducing a new migration framework. |
| Session/state store | `orca/serve/session_store.py` | In-process `_Session` object + Redis-backed cross-instance continuity for chat sessions (Phase 2.1 Model Gateway cutover). Distinct from the Phase 15 Mission concept — a chat session is not a mission. Relay's `relay_sessions`/`devices` domains are new, not a rename of this. |
| Deployment/edge evidence | `docs/orneur/phase-14/PHASE14C_EDGE_EVIDENCE.md`, `.github/workflows/phase14b-distributed-qualification.yml` | Full Cloudflare Tunnel + Northflank private-origin architecture, closed Phase 14C.1. Non-regression invariants (spec §32) all traced to this document — Phase 15 must not weaken any of it. |
| Auth/session/tenant model | `orca/auth/` (routes, store, db, tokens, privacy) | Real users/orgs/API-keys already exist on Supabase-backed Postgres (`ORNEUR_DATABASE_URL`). Phase 15's `users`/`organizations` durable domains (spec §9) likely reference this existing identity system rather than duplicating it — resolved concretely in Phase 15.2 schema design. |
| CI regression harness | `.github/workflows/test.yml` (pytest + Docker build/boot smoke, runs on every push to this branch) | Real, already running automatically — confirmed independently catching Phase 14C.1's deliberate bad rollback candidate as a CI failure. Phase 15.15's regression/Docker-boot requirement is largely already covered by this existing pipeline. |

## What is genuinely new for Phase 15

- **Neon Postgres** (`orneur-core`, project `little-boat-61470844`, `production` branch, `ap-southeast-1`) — confirmed real and live via the Neon MCP tools available in this session (`describe_project`/`list_branches`), currently empty (`written_data_bytes: 0`). This is a **separate** database from the existing Supabase-backed CORE/SECURITY ROOT/GODMODE databases — Phase 15's new mission/relay/evidence domains live here; Phase 14's authority/tenant data is untouched.
- Mission engine, state machine, and its 15 canonical states (§6) — no equivalent exists today; chat sessions are not missions.
- Checkpoint/resume system (§10) — no equivalent; Redis session continuity (Phase 2.1) covers chat history replay only, not a full mission's requirement/test/evidence state.
- Operation idempotency ledger (§11) — no equivalent; existing rate-limiting/audit code does not track a durable operation-lifecycle state machine.
- Product Contract / Requirement Compiler (§4-5) — no equivalent.
- Production Proof generator (§18) — no equivalent (Phase 14's evidence docs are hand-written Markdown, not a structured, machine-readable artifact schema).
- ORNEUR Relay in its entirety (§22-27) — no equivalent; nothing in this repo does cross-device mission continuation, device trust, or public-device mode today.
- Anti-test-gaming detection (§15) and Cognitive Court software abstraction (§16) — no equivalent (the "Court" name exists only as `orca/agent/court_hook.py`, a narrow existing hook — inspected separately before Phase 15.9 to determine reuse potential).

## Subphase sequencing (per spec §30, executed in order, no skipping)

15.0 Baseline → 15.1 Spec+Requirements → 15.2 Durable schema → 15.3
Mission state machine → 15.4 Checkpoint/resume → 15.5 Operation/
authority integration → 15.6 Execution sandbox → 15.7 Product/
Requirement compilers → 15.8 Verification engine → 15.9 Anti-test-
gaming + Court → 15.10 Production Proof → 15.11 Relay session core →
15.12 Relay security modes → 15.13 Reconnect/idempotency → 15.14
Six-hour mission governance → 15.15 Integrated qualification.

Each subphase ends with an evidence checkpoint in
`docs/orneur/phase-15/PHASE15_EVIDENCE.md`, per spec §36, before the
next subphase begins.

## Scope honesty note

This implementation program (16 subphases spanning a durable
Postgres-backed mission/checkpoint/operation engine, a full Relay
security system with device trust and public-device mode, a
requirement-traceability compiler, and a Production Proof generator)
is genuinely large — comparable in scope to several of the prior
14 phases combined. It will be executed across multiple work sessions,
each producing real, verified evidence for the subphase(s) completed
in that session, rather than a single pass that would have to fake
completeness to appear finished in one turn. This note itself is
required by the spec's own §17 (No Fake Completion) and §36 (Evidence
Policy) — better to state this plainly now than to produce a false
"Phase 15 complete" claim later.
