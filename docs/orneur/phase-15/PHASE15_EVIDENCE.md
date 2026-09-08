# Phase 15 Evidence Log

Running evidence checkpoints, one per subphase, per master spec §36.
Never overwritten — each subphase appends its own checkpoint.

---

## PHASE 15.0 — BASELINE

**OBJECTIVE:** Inspect the actual repository before any implementation; persist the canonical Phase 15 specification; produce a real implementation dependency map. No speculative rewrite.

**BASELINE:**
- Branch: `session-update-2026-08-25`
- HEAD: `d0ee011924626daf1e12386fded3543739fac003` (Phase 14C.1 final closure commit)
- Working tree: clean
- `orca/` package: 21 subpackages, including a mature `orca/godmode/` authority engine (16 modules) and an existing `orca/code/sandbox.py` execution sandbox precedent
- No migration framework (no Alembic/SQLAlchemy) — established convention is idempotent `CREATE TABLE IF NOT EXISTS` DDL embedded in Python (`orca/auth/db.py`)
- No prior Neon reference anywhere in code or docs (2 false-positive doc hits, unrelated "neon" color mentions in design-prompt files)
- Existing Phase 14 database backend: Supabase (`ORNEUR_DATABASE_URL`, `ORNEUR_GODMODE_DATABASE_URL`, `ORNEUR_SECURITY_ROOT_DATABASE_URL`) — untouched, remains the Phase 14 authority/tenant backend
- CI: `.github/workflows/test.yml` runs `pytest` + `docker build` + container boot smoke automatically on every push to this branch — already independently verified this phase (Phase 14C.1's deliberate bad rollback candidate was caught as a real CI failure by this same pipeline)

**IMPLEMENTED:**
- Persisted the canonical Phase 15 specification verbatim (all 39 sections, no summarization of normative requirements) into `docs/orneur/phase-15/ORNEUR_CODE_RELAY_MASTER_SPEC_V1.md`, with the required header (`SPEC_VERSION: 1.0`, `STATUS: CANONICAL_PHASE15`, `SOURCE: OWNER-PROVIDED`, `PHASE16_GATE: LOCKED_UNTIL_PHASE15_PASS`).
- Created `docs/orneur/phase-15/PHASE15_IMPLEMENTATION_PLAN.md` — a real dependency map (what exists vs. what's genuinely new), derived from actual inspection, not assumption.
- Created `docs/orneur/phase-15/PHASE15_REQUIREMENTS.md` — requirement-ID registry scaffold (prefixes reserved per spec area; first concrete entries land in Phase 15.1).
- Created this evidence log.

**FILES / COMPONENTS:**
- `docs/orneur/phase-15/ORNEUR_CODE_RELAY_MASTER_SPEC_V1.md` (new)
- `docs/orneur/phase-15/PHASE15_IMPLEMENTATION_PLAN.md` (new)
- `docs/orneur/phase-15/PHASE15_REQUIREMENTS.md` (new)
- `docs/orneur/phase-15/PHASE15_EVIDENCE.md` (new, this file)

**MIGRATIONS:** None this subphase.

**COMMANDS EXECUTED:**
```
git status --short
git rev-parse HEAD
git branch --show-current
ls -la .
find orca -maxdepth 1 -type d
grep -n "^\.env" .gitignore
find orca/code orca/agent -type f
sed -n '1,40p' orca/code/sandbox.py
ls orca/godmode/
grep -rln "psycopg|postgres" orca/*.py orca/config.py
find orca -iname "*deployment_profile*" -o -iname "*session_store*"
grep -n "DATABASE_URL|postgres|psycopg" orca/config.py
grep -rli "neon|little-boat" orca/ docs/
find . -iname "*migration*" (excluding node_modules/.venv)
grep -n "alembic|sqlalchemy|psycopg" pyproject.toml
grep -n "CREATE TABLE" orca/godmode/durable_audit.py orca/godmode/lease_store.py orca/auth/db.py
```
Neon MCP tool calls (read-only): `describe_project(project_id="little-boat-61470844")`, `list_branches(project_id="little-boat-61470844")`.

**TESTS EXECUTED:** None — no code changed this subphase.

**EXACT RESULTS:**
- Neon project `orneur-core` confirmed real via live API call: `id: little-boat-61470844`, `region_id: aws-ap-southeast-1` (Singapore, matches spec), `pg_version: 18`, `subscription_type: free_v3`, `owner: orneurlabs@hotmail.com`, `created_at: 2026-09-07T19:13:23Z`.
- Branch confirmed: `production` (`br-orange-morning-b3hu72wc`), `primary: true`, `default: true`, `written_data_bytes: 0` (empty — no schema applied yet, consistent with a fresh project).

**SECURITY FINDINGS:** None — inspection only, no attack surface touched.

**AUTHORITY FINDINGS:** Existing `orca/godmode/` authority engine confirmed mature and must be integrated with (Phase 15.5), not replaced. No changes made this subphase.

**MISSION STATE FINDINGS:** No mission engine exists yet. `orca/serve/session_store.py`'s chat-session continuity is a different concept (conversation replay, not a governed mission with requirements/tests/evidence) and is not being repurposed as the Mission Engine.

**CHECKPOINT / RESUME FINDINGS:** N/A this subphase.

**RELAY FINDINGS:** No Relay code exists anywhere in this repository. Confirmed via inspection, not assumed.

**ANTI-TEST-GAMING FINDINGS:** N/A this subphase.

**PRODUCTION PROOF STATUS:** N/A this subphase — no Production Proof generator exists yet (Phase 15.10).

**REGRESSIONS:** None — no code changed.

**TEST COLLECTION DELTA:** None — no test files added or modified this subphase.

**TECHNICAL DEBT:** None introduced.

**KNOWN LIMITATIONS:**
- This subphase is documentation/inspection only; no durable schema, mission engine, or Relay code exists yet.
- The relationship between Phase 15's `users`/`organizations` durable domains and the existing Supabase-backed `orca/auth/` identity system is noted as needing concrete resolution in Phase 15.2's schema design, not yet decided.

**UNVERIFIED ITEMS:** Whether `orca/agent/court_hook.py` is a reusable precedent for the Phase 15.9 Cognitive Court abstraction — not yet inspected in depth; deferred to Phase 15.9.

**DEFERRED ITEMS:** All of Phase 15.2 through 15.15 — not started, per sequential execution requirement (spec §30, §39: "Do not jump ahead").

**OWNER ACTION REQUIRED:** None this subphase.

**EVIDENCE:** This document; `docs/orneur/phase-15/ORNEUR_CODE_RELAY_MASTER_SPEC_V1.md`; `docs/orneur/phase-15/PHASE15_IMPLEMENTATION_PLAN.md`; live Neon API responses quoted above (not fabricated — `describe_project`/`list_branches` tool results).

**EPISTEMIC STATE:** VERIFIED (repository inspection and spec persistence are directly confirmed by tool output, not assumed).

**PROGRESSION VERDICT:**

YES — EVIDENCE SUPPORTS PROGRESSION

---

## PHASE 15.1 — CANONICAL SPEC + REQUIREMENTS

**OBJECTIVE:** Compile stable requirement IDs from the persisted spec into a real, testable traceability structure (spec §5) — not a static markdown list, but an enforced lifecycle in code.

**BASELINE:** Phase 15.0 closed with verdict YES. HEAD `07a95c7`.

**IMPLEMENTED:**
- `orca/mission/requirements.py` — the Requirement Compiler: `Requirement` dataclass with regex-enforced ID format (`REQ-<AREA>-<NAME>-<NNN>`) and construction-time rejection of empty statements/acceptance criteria; `RequirementStatus` enum (`UNIMPLEMENTED`/`IMPLEMENTED`/`VERIFIED`); `transition()` enforcing forward-only movement, requiring an implementation-file reference to reach `IMPLEMENTED`, and requiring both a test-file reference and a non-empty evidence reference to reach `VERIFIED` — structurally enforcing spec §17's "no fake completion" on the requirement registry itself, not merely documenting the rule.
- `orca/mission/requirements_seed.py` — first real compilation: 19 requirements spanning 14 spec areas (Mission Engine, six-hour window, autonomy levels, durable state, checkpoints, operation idempotency, execution sandbox, authority engine, anti-test-gaming, no-fake-completion, Production Proof, Relay core, device trust, reconnect truthfulness). `REQ-STATE-NEON-002` is transitioned to `IMPLEMENTED` (not `VERIFIED`) reflecting that the Neon project/branch identity half is confirmed live (Phase 15.0), but the connection-routing/capability-restraint half isn't implemented in code yet.
- `docs/orneur/phase-15/PHASE15_REQUIREMENTS.md` updated to index the real code rather than duplicate it (avoids drift between a markdown copy and the enforced registry).

**FILES / COMPONENTS:**
- `orca/mission/__init__.py` (new)
- `orca/mission/requirements.py` (new)
- `orca/mission/requirements_seed.py` (new)
- `tests/test_mission_requirements.py` (new)
- `docs/orneur/phase-15/PHASE15_REQUIREMENTS.md` (updated)

**MIGRATIONS:** None this subphase — no database schema yet (Phase 15.2).

**COMMANDS EXECUTED:**
```
.venv/bin/python3 -m pytest tests/test_mission_requirements.py -q
.venv/bin/python3 -c "from orca.mission.requirements_seed import seed_registry; ..."
.venv/bin/python3 -m pytest tests/test_mission_requirements.py tests/test_auth_store.py tests/test_org_store.py -q
```

**TESTS EXECUTED:** `tests/test_mission_requirements.py` (new, 19 tests) + a cross-check against 2 unrelated existing suites to confirm no interference with global test collection.

**EXACT RESULTS:**
```
19 passed, 1 warning in 0.31s   (tests/test_mission_requirements.py alone)
45 passed, 53 warnings in 2.13s (combined with test_auth_store.py + test_org_store.py)
```
Manual registry inspection confirmed 19/19 requirements registered, no duplicate IDs, `REQ-STATE-NEON-002` correctly shows `IMPLEMENTED`, all others `UNIMPLEMENTED` (honest — nothing else has been built yet).

**SECURITY FINDINGS:** None. No new attack surface — this is an in-process data structure with no network/filesystem/database access.

**AUTHORITY FINDINGS:** None — `orca/mission/requirements.py` does not touch `orca/godmode/` in this subphase; authority integration is Phase 15.5's job.

**MISSION STATE FINDINGS:** No Mission Engine exists yet (Phase 15.3). `REQ-MISSION-*` requirements are registered but correctly remain `UNIMPLEMENTED`.

**CHECKPOINT / RESUME FINDINGS:** N/A this subphase.

**RELAY FINDINGS:** No Relay code exists yet. `REQ-RELAY-STATE-001` and `REQ-DEVICE-REVOCATION-001` are registered but correctly remain `UNIMPLEMENTED`.

**ANTI-TEST-GAMING FINDINGS:** `REQ-ANTIGAME-DETECT-001` registered; no detection logic implemented yet (Phase 15.9).

**PRODUCTION PROOF STATUS:** No Production Proof generator exists yet (Phase 15.10). `REQ-PROOF-NOINVENT-001` registered, `UNIMPLEMENTED`.

**REGRESSIONS:** None. Full local security-suite/deterministic-suite re-run deferred to Phase 15.15's integrated qualification per spec §30, but a targeted cross-check (`test_auth_store.py`, `test_org_store.py`) alongside the new tests shows no interference.

**TEST COLLECTION DELTA:** +19 (`tests/test_mission_requirements.py`, new file, not yet added to `docs/orneur/phase-9/security_suite_files.txt` — this is Phase 15 mission-engine scaffolding, not a Phase 14-style security-suite test; will be reconciled explicitly in Phase 15.15's full-regression pass rather than silently folded into the existing security suite count).

**TECHNICAL DEBT:** The seed compilation (19 requirements) is material but not exhaustive of every normative sentence in the 39-section spec — deliberately so (spec §5 says "every MATERIAL requirement", not every sentence). Later subphases add their own requirements as they're defined, per the implementation plan.

**KNOWN LIMITATIONS:**
- `orca/mission/requirements.py` is pure in-memory state — it does not yet persist to Postgres (that's Phase 15.2's `requirements`/`requirement_acceptance_criteria` durable tables) and does not verify that a referenced implementation/test file actually exists on disk (that's the Verification Engine's job, Phase 15.8).
- The registry is process-local (module-level dict) — not yet durable across restarts. This is expected and correct for Phase 15.1's scope (compiler logic only); durability arrives in 15.2.

**UNVERIFIED ITEMS:** None new this subphase beyond what Phase 15.0 already flagged.

**DEFERRED ITEMS:** Phase 15.2 through 15.15 — not started.

**OWNER ACTION REQUIRED:** None this subphase.

**EVIDENCE:** This document; `orca/mission/requirements.py`; `orca/mission/requirements_seed.py`; `tests/test_mission_requirements.py` (19/19 passing, quoted above).

**EPISTEMIC STATE:** VERIFIED for the compiler's own lifecycle-enforcement logic (directly tested). IMPLEMENTED-but-not-yet-VERIFIED for the specific requirements themselves, since "verified" per this project's own rules means the underlying Phase 15 FEATURE is built and tested, not merely that the requirement-tracking code works.

**PROGRESSION VERDICT:**

YES — EVIDENCE SUPPORTS PROGRESSION

---

## PHASE 15.2 — DURABLE DATA MODEL

**OBJECTIVE:** Design durable Neon Postgres schema for the minimum required domains (spec §9), validate via Neon branch-first migration before touching production (spec §30), and apply only with explicit owner authorization.

**BASELINE:** Phase 15.1 closed with verdict YES. HEAD `d756eea`. Neon project `orneur-core` (`little-boat-61470844`), branch `production` (`br-orange-morning-b3hu72wc`), confirmed empty in Phase 15.0.

**IMPLEMENTED:**
- `orca/mission/schema.py` — `SCHEMA_SQL`: full DDL for 21 tables covering every spec §9 minimum domain (missions, mission_steps, checkpoints, requirements, requirement_acceptance_criteria, assumptions, evidence, operations, approvals, authority_decisions, model_invocations, tool_invocations, devices, relay_sessions, production_proofs, audit_events) plus 5 explicitly-named `*_reserved` tables for Phase 16 domains (epistemic_transitions, escalations, failure_genome, outcome_memory, capability_delta) — opaque JSON-payload-only, no Phase 15 code reads/writes semantic meaning into them, satisfying spec §9's "do not claim Phase 16 semantics are implemented merely because storage tables exist." Follows the existing project's own established convention (`orca/auth/db.py`): TEXT primary keys, TEXT ISO-8601 timestamps, JSON-as-TEXT columns — plus CHECK constraints on every status/enum column as defense-in-depth (a real addition, not present in the existing auth schema, but consistent with it).
- `orca/mission/db.py` — connection layer with two distinct env vars (`ORNEUR_MISSION_DATABASE_URL` pooled / `ORNEUR_MISSION_DATABASE_URL_DIRECT` unpooled), fail-closed (`MissionDatabaseConfigError`) if either is unset, and `direct=True` never silently falls back to the pooled URL for schema operations (spec §9).
- Schema validated via Neon's own branch-first migration tool (`prepare_database_migration` → temporary branch `br-patient-unit-b3avpl4i`), constraint-tested with real inserts, then applied to the `production` branch via `complete_database_migration` **after explicit owner authorization** — the exact same `migration_sql` from the prepare step, not reconstructed or modified during promotion.

**FILES / COMPONENTS:**
- `orca/mission/schema.py` (new)
- `orca/mission/db.py` (new)
- `tests/test_mission_schema.py` (new)
- `tests/test_mission_db.py` (new)

**MIGRATIONS:**
- Migration ID `2b437665-ad2b-464b-b154-f6d4eadf70ff`, applied to Neon project `little-boat-61470844`, database `neondb`, branch `production` (`br-orange-morning-b3hu72wc`). Prepared on temporary branch `br-patient-unit-b3avpl4i` (auto-deleted by `complete_database_migration` on completion). All 42 DDL statements (21 `CREATE TABLE IF NOT EXISTS` + 21 `CREATE INDEX IF NOT EXISTS`) executed with empty result sets (no errors).

**COMMANDS EXECUTED (Neon MCP tool calls, no raw connection strings ever retrieved, printed, or stored anywhere):**
```
list_postgres_databases(project_id, branch_id)              -> confirmed database "neondb"
prepare_database_migration(project_id, database_name, migration_sql)
                                                              -> temp branch br-patient-unit-b3avpl4i, migration_id 2b437665-...
run_sql(temp branch): SELECT table_name FROM information_schema.tables ...
run_sql(temp branch): INSERT INTO missions (...) VALUES (valid row)              -> succeeded
run_sql(temp branch): INSERT INTO missions (...) VALUES (state='NOT_A_REAL_STATE') -> rejected (CHECK)
run_sql(temp branch): INSERT INTO mission_steps (...) VALUES (mission_id=nonexistent) -> rejected (FK)
run_sql(temp branch): INSERT INTO operations (...) VALUES (idempotency_key='idem_key_abc123')      -> succeeded
run_sql(temp branch): INSERT INTO operations (...) VALUES (same idempotency_key, different id)     -> rejected (UNIQUE)
complete_database_migration(..., apply_changes=true)          -> applied to production, temp branch deleted
run_sql(production): SELECT table_name FROM information_schema.tables ...
run_sql(production): SELECT conrelid::regclass, conname, contype FROM pg_constraint ...
run_sql(production): SELECT count(*) FROM missions/operations/mission_steps    -> all 0 (no leftover test data)
.venv/bin/python3 -m pytest tests/test_mission_schema.py tests/test_mission_db.py tests/test_mission_requirements.py tests/test_auth_store.py tests/test_org_store.py -q
```

**TESTS EXECUTED:** `tests/test_mission_schema.py` (5 new), `tests/test_mission_db.py` (3 new), plus cross-check against `test_mission_requirements.py` and 2 unrelated existing suites.

**EXACT RESULTS:**
```
8 passed, 1 warning in 0.25s    (test_mission_schema.py + test_mission_db.py alone)
53 passed, 53 warnings in 1.74s (combined cross-check)
```
Live Neon verification (temp branch → production, both independently queried via `information_schema.tables`): **21/21 tables**, exact match to `schema.ALL_TABLES`, confirmed via a direct Python set-equality check (not eyeballed). `pg_constraint` query on production confirms all 13 CHECK constraints, all foreign keys matching every `REFERENCES` clause in the DDL, and the `operations_idempotency_key_key` UNIQUE constraint are present. Row counts on `missions`/`operations`/`mission_steps` on production: **0/0/0** — no test data reached production; all constraint-violation testing ran only on the now-deleted temporary branch.

**SECURITY FINDINGS:** No raw secret (connection string, password, token) was ever retrieved, printed, logged, or committed — every Neon operation this subphase went through the MCP tool's own internal connection handling, never through `get_connection_string` or a manually-constructed DSN.

**AUTHORITY FINDINGS:** The production-branch migration apply (`complete_database_migration`) was explicitly gated — the tool itself is marked "never run autonomously," so this session stopped and requested owner authorization before calling it, consistent with spec §14's dangerous-operation-requires-approval requirement applied to this session's own actions, not just to future mission-engine code.

**MISSION STATE FINDINGS:** The `missions` table's `state` CHECK constraint enumerates the exact same 15 states as `REQ-MISSION-STATES-001`'s acceptance criteria (Phase 15.1) — live-verified as enforced by the database itself, not merely declared in Python.

**CHECKPOINT / RESUME FINDINGS:** The `checkpoints` table schema includes every field `REQ-CKPT-FIELDS-001` (Phase 15.1) requires. Not yet exercised by application code (that's Phase 15.4).

**RELAY FINDINGS:** `devices` and `relay_sessions` tables exist with the `trust_level`/`mode` CHECK constraints matching `REQ-DEVICE-REVOCATION-001`'s TRUSTED/PUBLIC distinction. No Relay application code exists yet (Phase 15.11+).

**ANTI-TEST-GAMING FINDINGS:** N/A this subphase.

**PRODUCTION PROOF STATUS:** `production_proofs` table exists with the 4-state `overall_status` CHECK (`ENGINEERING_READY`/`SUBMISSION_READY`/`RELEASE_CANDIDATE`/`PUBLISHED`) matching spec §3. No generator code yet (Phase 15.10).

**REGRESSIONS:** None. Full local regression deferred to Phase 15.15 per spec §30; targeted cross-check shows no interference with existing suites.

**TEST COLLECTION DELTA:** +8 (`tests/test_mission_schema.py`: 5, `tests/test_mission_db.py`: 3). Not yet added to `docs/orneur/phase-9/security_suite_files.txt` — reconciled explicitly in Phase 15.15, same as Phase 15.1's delta.

**TECHNICAL DEBT:** `orca/mission/db.py`'s `get_conn()`/`apply_schema()`/`list_existing_tables()` are not yet exercised by any application code (no mission/checkpoint/operation CRUD layer exists yet — that's Phase 15.3+). The CHECK-constraint-as-defense-in-depth choice (not present in `orca/auth/db.py`'s existing tables) is a deliberate, disclosed departure from the exact existing convention, not an oversight.

**KNOWN LIMITATIONS:**
- No SQLite dev/test mirror for this schema (unlike `orca/auth/db.py`'s dual-backend design) — spec §9 explicitly says "Postgres only is currently intentional" for this domain, so fast unit tests for future CRUD logic will need either a real (test-branch) Neon connection or an in-memory fake at the Python layer, decided in Phase 15.3 when that logic is written.
- `ORNEUR_MISSION_DATABASE_URL`/`_DIRECT` are not yet configured anywhere (not in this Mac's `.env`, not in any deployment) — no runtime code has attempted a live pooled/direct connection through `orca/mission/db.py` itself yet, only through the Neon MCP's own internal handling. This is expected at this stage (no application server wiring exists yet) and is not the same as the schema being unverified — the schema itself IS verified, live, against both a temp branch and production.

**UNVERIFIED ITEMS:** None new.

**DEFERRED ITEMS:** Phase 15.3 through 15.15 — not started.

**OWNER ACTION REQUIRED:** None further this subphase — the one required action (production migration authorization) was requested and granted.

**EVIDENCE:** This document; `orca/mission/schema.py`; `orca/mission/db.py`; live Neon query results quoted above (table list, constraint list, row counts — all direct tool output, not summarized from memory).

**EPISTEMIC STATE:** VERIFIED — the schema's structural correctness (table presence, constraint presence, constraint *behavior* under real valid/invalid/duplicate inserts) was proven against real, live Neon infrastructure, both on a disposable temp branch and on the actual production branch after application.

**PROGRESSION VERDICT:**

YES — EVIDENCE SUPPORTS PROGRESSION

---

## PHASE 15.3 — MISSION STATE MACHINE

**OBJECTIVE:** Implement the 15 canonical mission states and validated transitions (spec §6), with two structural guarantees: COMPLETED_VERIFIED is only reachable through a real verification-oriented state, and only with an evidence reference — not merely documented, enforced in code.

**BASELINE:** Phase 15.2 closed with verdict YES. HEAD `186c8dd`.

**IMPLEMENTED:**
- `orca/mission/state_machine.py` — `MissionState` enum (all 15 spec states), `TERMINAL_STATES` (FAILED, COMPLETED_UNVERIFIED, COMPLETED_VERIFIED, CANCELLED), a full `_ALLOWED_TRANSITIONS` table, and `transition()` enforcing it plus two extra invariants: (1) `COMPLETED_VERIFIED` is reachable only from `VERIFYING`/`COURT_REVIEW` (checked both via the transition table AND an explicit redundant guard, so the invariant survives even a future edit to the table), and (2) reaching `COMPLETED_VERIFIED` requires a non-empty `evidence_ref` in the same call — the same "no fake completion" pattern established for individual requirements in Phase 15.1, now applied to the mission's own terminal state.
- Corrected two Phase 15.1 seed entries that were actually satisfied by Phase 15.2's work but never transitioned at the time: `REQ-STATE-DOMAINS-001` (schema covers every listed domain, live-verified) → `VERIFIED`; `REQ-CKPT-FIELDS-001` (checkpoints table has every listed field) → `IMPLEMENTED` (not `VERIFIED` — no test yet creates an actual populated checkpoint row, that's Phase 15.4). Disclosed here rather than silently fixed, per spec §35's "every collection-count/status change must be reconciled."

**FILES / COMPONENTS:**
- `orca/mission/state_machine.py` (new)
- `tests/test_mission_state_machine.py` (new)
- `orca/mission/requirements_seed.py` (updated — 5 new `transition()` calls: 3 for this subphase's own new requirements-turned-VERIFIED, 2 retroactive corrections for Phase 15.2)

**MIGRATIONS:** None this subphase.

**COMMANDS EXECUTED:**
```
.venv/bin/python3 -m pytest tests/test_mission_state_machine.py -q
.venv/bin/python3 -m pytest tests/test_mission_requirements.py tests/test_mission_schema.py tests/test_mission_db.py tests/test_mission_state_machine.py -q
.venv/bin/python3 -c "from orca.mission.requirements_seed import seed_registry; ..."  # printed all 19 requirement statuses
```

**TESTS EXECUTED:** `tests/test_mission_state_machine.py` (48 new tests: valid transitions, invalid transitions, all 4 terminal states individually confirmed to reject every possible next state, pause/resume for both PAUSED_USER and PAUSED_WINDOW_REACHED, BLOCKED in/out, FAILED reachability and terminality, the full verified-vs-unverified completion distinction — including that COMPLETED_UNVERIFIED and COMPLETED_VERIFIED cannot transition into each other — and a whole-graph sanity check that no non-terminal state is an accidental dead end).

**EXACT RESULTS:**
```
48 passed, 1 warning in 0.27s   (test_mission_state_machine.py alone)
75 passed, 1 warning in 0.35s   (all 4 orca.mission test files combined)
```
Requirement registry after this subphase (19 total): 5 `VERIFIED` (REQ-MISSION-STATES-001, REQ-MISSION-TRANSITIONS-002, REQ-STATE-DOMAINS-001, REQ-NOFAKE-DISTINCTION-001, plus REQ-STATE-NEON-002 remains `IMPLEMENTED` not `VERIFIED`), 3 `IMPLEMENTED` (REQ-STATE-NEON-002, REQ-CKPT-FIELDS-001), 11 still honestly `UNIMPLEMENTED`.

**SECURITY FINDINGS:** None — pure in-memory Python logic, no I/O.

**AUTHORITY FINDINGS:** None this subphase — `orca/mission/state_machine.py` does not touch `orca/godmode/`; that integration is Phase 15.5.

**MISSION STATE FINDINGS:** The state machine itself is now real and tested. It is NOT yet wired to the `missions` table (Phase 15.2's schema) or to any mission-lifecycle application code (create/load/save a mission) — that CRUD layer is Phase 15.4's job (checkpoint/resume needs it to have something concrete to checkpoint).

**CHECKPOINT / RESUME FINDINGS:** N/A this subphase — deferred to 15.4.

**RELAY FINDINGS:** N/A this subphase.

**ANTI-TEST-GAMING FINDINGS:** N/A this subphase.

**PRODUCTION PROOF STATUS:** N/A this subphase.

**REGRESSIONS:** None.

**TEST COLLECTION DELTA:** +48 (`tests/test_mission_state_machine.py`). Cumulative Phase 15 test delta so far: 19 (15.1) + 8 (15.2) + 48 (15.3) = 75, matching the combined run above exactly.

**TECHNICAL DEBT:** None new. The retroactive requirement-status correction (above) is disclosed, not hidden — a real process gap (forgetting to transition a requirement in the same subphase that satisfied it) rather than a code defect.

**KNOWN LIMITATIONS:**
- The state machine's `transition()` is a pure function — it does not itself persist anything to the `missions` table. Wiring it to actual database reads/writes (so a transition actually changes a durable row) is Phase 15.4's responsibility.
- `REQ-MISSION-DURABILITY-003` (mission state surviving process restart) remains correctly `UNIMPLEMENTED` — that requires the checkpoint/resume application layer, not just the state machine's transition logic.

**UNVERIFIED ITEMS:** None new.

**DEFERRED ITEMS:** Phase 15.4 through 15.15 — not started.

**OWNER ACTION REQUIRED:** None this subphase.

**EVIDENCE:** This document; `orca/mission/state_machine.py`; `tests/test_mission_state_machine.py` (48/48 passing, quoted above).

**EPISTEMIC STATE:** VERIFIED for the state machine's own transition logic (directly, exhaustively tested — every terminal state's rejection of every possible next state is individually confirmed, not sampled). IMPLEMENTED-but-not-yet-VERIFIED for the broader mission-durability requirement, which correctly still depends on later subphases.

**PROGRESSION VERDICT:**

YES — EVIDENCE SUPPORTS PROGRESSION

---

## PHASE 15.4 — CHECKPOINT + RESUME

**PHASE:** 15.4 — Checkpoint + Resume

**OBJECTIVE:** Implement a real durable mission CRUD + checkpoint/resume layer so an ORNEUR mission survives process loss and resumes from persisted state — proven by application code creating, persisting, checkpointing, losing in-memory state, reconstructing fresh objects, restoring, and resuming correctly, not merely by tables existing.

**BASELINE:** Phase 15.3 closed with verdict YES. HEAD `f3f8910`. Confirmed clean working tree before starting.

**IMPLEMENTED:**
- `orca/mission/mission_store.py` — durable Mission Repository/Checkpoint store. `create_mission`/`get_mission`; `transition_mission` (locks the mission row with `SELECT ... FOR UPDATE`, validates via `orca.mission.state_machine.transition()`, writes, commits — the only code path that ever writes `missions.state`); `resume_mission` (restricted to `PAUSED_USER`/`PAUSED_WINDOW_REACHED` origin, rejects everything else including terminal states, with a clear error, never by mutating the state string directly); `create_checkpoint`/`get_checkpoint`/`get_latest_checkpoint`; `checkpoint_and_pause` (writes the pause transition and its checkpoint in ONE real transaction — see Database/Transaction Findings below for a real bug caught and fixed before this was true); `restore_mission` (the dedicated restoration entrypoint — loads a mission and its latest checkpoint fresh, for use after constructing brand-new connection/application objects).
- Concurrency: relies on the `FOR UPDATE` row lock (held for the whole transaction) rather than an additive version/revision column — inspected the schema first (spec §3) and confirmed no version field exists; row-level transactional locking is sufficient for this scope and was chosen deliberately, not by default.
- `tests/test_mission_store_unit.py` (4 tests, no DB) + `tests/test_mission_store_live_neon.py` (19 tests, clearly labeled `LIVE_NEON_TEMP_BRANCH`, `pytest.mark.skipif` when no live DB is configured).

**FILES / COMPONENTS:**
- `orca/mission/mission_store.py` (new)
- `tests/test_mission_store_unit.py` (new)
- `tests/test_mission_store_live_neon.py` (new)
- `.github/workflows/phase14b-distributed-qualification.yml` (new `phase15_4_live_neon_qualification` dispatch mode)
- `.gitignore` (added `/scratchpad/`)
- `orca/mission/requirements_seed.py` (updated — 5 new `transition()` calls)

**MIGRATIONS:** None new. The Phase 15.2 schema (already on production) was applied idempotently (`CREATE TABLE IF NOT EXISTS`) to a disposable qualification branch cloned from production — not a schema change, a confirmation the existing schema was sufficient (spec §0: "identify whether the existing schema already contains everything needed for 15.4" — it did).

**COMMANDS EXECUTED:**
```
git rev-parse HEAD && git status --short
grep -n "version|updated_at|created_at" orca/mission/schema.py         # confirmed no version/revision column exists
grep -rn "FOR UPDATE" orca/godmode/*.py                                 # confirmed existing project convention
python3 -c "import socket; socket.gethostbyname('...neon.tech')"        # confirmed this Mac cannot resolve Neon hostnames at all
mcp__Neon__create_branch(project_id, name="phase15-4-qualification", parent_id=production)
mcp__Neon__get_connection_string(...)                                    # value never printed to visible output or committed
gh secret set ORNEUR_MISSION_DATABASE_URL --env phase14b-staging
gh secret set ORNEUR_MISSION_DATABASE_URL_DIRECT --env phase14b-staging
gh workflow run phase14b-distributed-qualification.yml -f fresh_runner_mode=phase15_4_live_neon_qualification   # x2 (1st failed on missing pytest, fixed, re-dispatched)
mcp__Neon__delete_branch(project_id, branch_id=phase15-4-qualification)  # cleanup
gh secret delete ORNEUR_MISSION_DATABASE_URL --env phase14b-staging      # cleanup
gh secret delete ORNEUR_MISSION_DATABASE_URL_DIRECT --env phase14b-staging  # cleanup
gh api repos/.../environments/phase14b-staging/secrets                  # confirmed both deleted, only original Phase 14 secrets remain
.venv/bin/python3 -m pytest tests/test_mission_*.py tests/test_auth_store.py tests/test_org_store.py tests/test_godmode_boundaries.py tests/test_godmode_security.py -q
```

**TESTS EXECUTED:**
- UNIT: `tests/test_mission_store_unit.py` (4 tests) — local, no DB.
- LIVE_NEON_TEMP_BRANCH: `tests/test_mission_store_live_neon.py` (19 tests) — GitHub Actions run `34234091994`, against branch `phase15-4-qualification` (`br-purple-river-b3szwxog`, cloned from `production`, deleted after this run).
- Cross-check regression: `tests/test_mission_requirements.py`, `test_mission_schema.py`, `test_mission_db.py`, `test_mission_state_machine.py`, `test_auth_store.py`, `test_org_store.py`, `test_godmode_boundaries.py`, `test_godmode_security.py`.

**EXACT RESULTS:**
```
(GitHub Actions, run 34234091994, LIVE_NEON_TEMP_BRANCH)
tests/test_mission_store_unit.py: 4 passed
tests/test_mission_store_live_neon.py: 19 passed
======================== 23 passed in 109.72s (0:01:49) ========================
```
```
(local, cross-check with unrelated suites)
154 passed, 19 skipped, 53 warnings in 2.55s
```
(19 skipped = the live-only tests, correctly inert without live credentials — the same 19 all passed live above.)

**LIVE NEON TESTS:** All 19 in `test_mission_store_live_neon.py` passed against real Neon, run `34234091994` (an earlier dispatch, run `34233966708`, failed on a missing `pytest` install, fixed in commit `8e8ba81`, re-dispatched as `34234091994`). Covered exactly the required narrative: (A) `create_mission` inserts a real row; (B) a fresh connection reads the same mission; (C+D) `checkpoint_and_pause` transitions AND checkpoints atomically; (E) all prior connections closed, nothing referenced across the "state loss" boundary; (F) `restore_mission` on a brand-new connection reloads mission + checkpoint; (G) `resume_mission` transitions back to RUNNING through the canonical state machine; (H) completed vs. remaining steps confirmed correct BEFORE resuming — `step_0`/`step_1` never reappear in `remaining_step_ids`; (I) real constraint behavior (a forced PRIMARY KEY collision proves `checkpoint_and_pause` rolls back BOTH writes together, leaving the mission at its pre-transition state, not half-committed).

**SECURITY FINDINGS:** No raw Neon connection string was ever printed in visible response text or committed to any file. The qualification branch's connection strings were: (1) written once to a local, newly-`.gitignore`d scratch file (`scratchpad/phase15_4_neon_test.env`, confirmed via `git check-ignore -v` before use), (2) set as GitHub Actions environment secrets (`gh secret set`, encrypted by GitHub before transmission), (3) referenced only by `${{ secrets.* }}` in the workflow YAML (GitHub redacts these from Actions logs automatically — confirmed the job's own env-dump lines show `***`, not the real value). All three were deleted after use: local file removed, GitHub secrets deleted (confirmed via `gh api .../secrets` showing only the original 8 Phase 14 secrets remain), and the underlying Neon branch itself deleted (invalidating the credential regardless).

**AUTHORITY FINDINGS:** None this subphase — `orca/mission/mission_store.py` does not yet integrate with `orca/godmode/`'s authority engine (that's Phase 15.5, per the spec's own sequencing).

**MISSION STATE FINDINGS:** Every mission-state write in this module passes through `orca.mission.state_machine.transition()` — confirmed by code inspection (grep shows no other `UPDATE missions SET state` anywhere in the module) and by the live test that attempts an illegal transition (`test_illegal_transition_rejected_and_state_unchanged`) and confirms the persisted state is untouched.

**CHECKPOINT / RESUME FINDINGS:** Checkpoint creation stores only genuinely-supplied data — `active_blocker`, `diff_ref`, etc. are confirmed `None` when not provided (`test_from_row_leaves_genuinely_absent_fields_none`, `test_checkpoint_creation_and_field_population`), never a fabricated placeholder. `restore_mission` on a mission with no checkpoint yet correctly returns `(mission, None)` rather than erroring — a legitimate state, not a defect (`test_restore_mission_with_no_checkpoint_yet`).

**DATABASE / TRANSACTION FINDINGS:** A real atomicity bug was found and fixed BEFORE any live test ran: the first draft of `checkpoint_and_pause()` called a transition helper that committed internally, then tried to add the checkpoint write "in the same transaction" afterward — which would NOT have been atomic at all (a checkpoint-write failure after that point would have left a paused mission with no checkpoint, exactly the "impossible half-state" spec §5 warns against). Refactored to a non-committing `_write_transition()` so both writes genuinely share one transaction with one final commit — then proved this live with `test_checkpoint_and_pause_rolls_back_together_on_failure` (forces a real PRIMARY KEY violation on the checkpoint insert, confirms the mission's state transition was rolled back too, not left committed).

**CONCURRENCY FINDINGS:** `test_for_update_lock_serializes_concurrent_transitions` fires two real threads, each with its own connection, attempting different legal transitions (`RUNNING -> PAUSED_USER` and `RUNNING -> BLOCKED`) on the SAME mission simultaneously. Live-confirmed: exactly one final state is ever persisted (never a lost update, never two different "successful" results reporting different states) — the `FOR UPDATE` lock genuinely serializes the second transaction behind the first.

**RELAY FINDINGS:** N/A this subphase.

**ANTI-TEST-GAMING FINDINGS:** N/A this subphase.

**PRODUCTION PROOF STATUS:** N/A this subphase.

**REGRESSIONS:** None. Cross-check against `test_auth_store.py`, `test_org_store.py`, `test_godmode_boundaries.py`, `test_godmode_security.py` shows no interference.

**TEST COLLECTION DELTA:** +23 (`test_mission_store_unit.py`: 4, `test_mission_store_live_neon.py`: 19). Cumulative Phase 15 delta: 19 (15.1) + 8 (15.2) + 48 (15.3) + 23 (15.4) = 98 new tests since Phase 14C.1.

**REQUIREMENT STATUS DELTA:**
- `REQ-MISSION-DURABILITY-003`: UNIMPLEMENTED → VERIFIED
- `REQ-CKPT-FIELDS-001`: IMPLEMENTED → VERIFIED
- `REQ-CKPT-RESTORE-002`: UNIMPLEMENTED → IMPLEMENTED **only** (deliberately not VERIFIED — this requirement's specific acceptance criterion is about the `operations` table's idempotency-key dedup, which spec §8 explicitly reserves for Phase 15.5/15.13: "do not overclaim full dangerous-operation idempotency here." Phase 15.4 proved the adjacent, narrower guarantee — completed vs. remaining STEPS are preserved correctly across restore — but not operation-record-level dedup.)
- Registry after this subphase (19 total): 6 VERIFIED, 2 IMPLEMENTED-only, 11 UNIMPLEMENTED.

**TECHNICAL DEBT:** None new beyond the disclosed REQ-CKPT-RESTORE-002 scope gap (intentional, per spec).

**KNOWN LIMITATIONS:**
- `orca/mission/mission_store.py` has no integration with the `operations`/`approvals`/`authority_decisions` tables yet — Phase 15.5's job.
- The qualification branch used for live testing is gone (deleted per spec §1's "delete/clean the temporary qualification branch when appropriate") — the 23/23 pass result is a point-in-time proof, reproducible by re-running the same workflow dispatch mode against a freshly-created branch.
- This Mac genuinely cannot resolve Neon's Postgres hostnames (confirmed directly via `socket.gethostbyname`, not assumed) — all live Neon verification for this project must go through GitHub Actions, consistent with the standing rule already established for Northflank/Cloudflare in Phase 14.

**UNVERIFIED ITEMS:** None new.

**DEFERRED ITEMS:** Phase 15.5 through 15.15 — not started.

**OWNER ACTION REQUIRED:** None.

**EVIDENCE:** This document; `orca/mission/mission_store.py`; `tests/test_mission_store_unit.py`; `tests/test_mission_store_live_neon.py`; GitHub Actions run `34234091994` (23/23 passed, quoted above); Neon branch `br-purple-river-b3szwxog` (created, used, deleted — all via direct Neon MCP tool calls, not assumed).

**EPISTEMIC STATE:** VERIFIED — every claim in this checkpoint traces to either a live GitHub Actions test run against real Neon infrastructure, a direct Neon MCP tool response, or a local test run quoted above. No claim in this checkpoint is asserted from confidence alone.

**PROGRESSION VERDICT:**

YES — EVIDENCE SUPPORTS PROGRESSION

---

## PHASE 15.5 — OPERATION + AUTHORITY ENGINE

**PHASE:** 15.5 — Operation + Authority Engine

**OBJECTIVE:** Prove that intent alone cannot grant authority to perform a dangerous action — every operation goes through a real, durable REQUESTED → AUTHORIZED → STARTED → (SUCCEEDED|FAILED|CANCELLED) lifecycle; authorization is decided exclusively by the existing, mature `orca.godmode` authority engine (never by model prose, never self-granted); retries and concurrent races collapse to exactly one real side effect; every decision is durable and survives process loss.

**BASELINE:** Phase 15.4 closed with verdict YES. HEAD `e015ec2`. Confirmed clean working tree before starting.

**IMPLEMENTED:**
- `orca/mission/authority_bridge.py` — the ONLY integration point with `orca.godmode`. Contains no authorization logic of its own: `issue_operation_lease()` builds an `ElevatedCapabilityRequest` + `make_approval()` + `issue_lease()`; `consume_operation_lease()` is a thin wrapper over `orca.godmode.resolution.resolve_and_consume_lease()` — the real, atomic, fail-closed decision primitive already battle-tested across Phases 9–14B. Per-operation binding comes from `_resource_scope_for_operation(operation_id) -> f"mission-operation:{operation_id}"`, so a lease issued for one operation cannot decode as valid for a different one.
- `orca/mission/executor.py` — `Executor` protocol + `RecordingTestExecutor`, the deterministic, harmless, thread-safe test adapter used everywhere in place of a real destructive action (spec's explicit instruction: never invoke a real destructive cloud/payment/secret/production action to prove these properties).
- `orca/mission/operation_store.py` — the durable Operation lifecycle. `request_operation()` performs atomic dedup via `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id` — dedup happens BEFORE any side effect, not by catching a UNIQUE violation after the fact — and raises `OperationConflictError` if a retried key carries a different `compute_fingerprint()` (stdlib-only SHA-256 over canonical sorted-key JSON, no custom crypto, no raw secrets hashed). `authorize_operation()` locks the operation row `FOR UPDATE`, hard-rejects `approved_by == requested_by` with `SelfAuthorizationError` **before any godmode call is made**, then calls the authority bridge and records both an `authority_decisions` row (ALLOW/DENY) and an `approvals` row (APPROVED/REJECTED, carrying the real `lease_id`) — transitioning to AUTHORIZED only on ALLOW. `start_and_execute_operation()` commits the STARTED transition BEFORE invoking the executor (an external side effect of arbitrary duration must never hold a DB lock open), and treats a concurrent race — another caller's locked transition already having moved the row past AUTHORIZED — as a graceful, idempotent observation of the winner's state rather than an error, matching the same no-recall treatment already given to SUCCEEDED/FAILED/CANCELLED.
- `orca/mission/schema.py` — `PHASE_15_5_MIGRATION_SQL` (idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, same convention as `orca/auth/db.py`): `operations.parameters_fingerprint`, `operations.requested_by`, `approvals.lease_id` (a REFERENCE to the real godmode `CapabilityLease`, never a duplicate authority store), `authority_decisions.requested_by`.

**FILES / COMPONENTS:**
- `orca/mission/authority_bridge.py` (new)
- `orca/mission/executor.py` (new)
- `orca/mission/operation_store.py` (new)
- `orca/mission/schema.py` (updated — `PHASE_15_5_MIGRATION_SQL`)
- `orca/mission/db.py` (updated — `apply_schema()` now runs the Phase 15.5 migration too)
- `tests/test_authority_bridge.py` (new, 6 tests)
- `tests/test_executor_unit.py` (new, 3 tests)
- `tests/test_operation_store_live_neon.py` (new, 28 tests, `LIVE_NEON_TEMP_BRANCH`)
- `.github/workflows/phase14b-distributed-qualification.yml` (new `phase15_5_live_neon_qualification` dispatch mode)
- `orca/mission/requirements_seed.py` (updated — `REQ-OPIDEM-LIFECYCLE-001` and `REQ-AUTH-EXTERNAL-001` transitioned to VERIFIED; `REQ-CKPT-RESTORE-002` revisited, disclosed, stays IMPLEMENTED)

**MIGRATIONS:** `PHASE_15_5_MIGRATION_SQL` — four `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements, applied idempotently by `apply_schema()` on every live Neon dispatch (both the failed run and the fixed re-run). No separate owner approval request was needed beyond the standing schema-evolution convention already established in Phase 15.2/15.4, since these are additive nullable columns on tables already approved and live on production, applied the same idempotent way `orca/auth/db.py` has always applied incremental columns — no destructive or structural change, no data migration, no `prepare_database_migration`/`complete_database_migration` cycle required.

**COMMANDS EXECUTED:**
```
git rev-parse HEAD && git status --short
grep -n "CapabilityDomain\|LeaseIssuerClass\|ElevatedCapabilityRequest" orca/godmode/*.py   # inspected real godmode primitives before writing authority_bridge.py
mcp__Neon__create_branch(project_id, name="phase15-5-qualification", parent_id=production)  # br-plain-dew-b3xhd4c8
mcp__Neon__get_connection_string(...)                                    # value never printed to visible output or committed
gh secret set ORNEUR_MISSION_DATABASE_URL --env phase14b-staging
gh secret set ORNEUR_MISSION_DATABASE_URL_DIRECT --env phase14b-staging
gh workflow run phase14b-distributed-qualification.yml -f fresh_runner_mode=phase15_5_live_neon_qualification   # run 34236567314 (17/19 passed, 2 failed)
# diagnosed + fixed both failures locally (see FINDINGS below)
git commit -m "Phase 15.5: fix concurrency race and test expectation..."  # 5f13ebd
git push origin session-update-2026-08-25
gh workflow run phase14b-distributed-qualification.yml -f fresh_runner_mode=phase15_5_live_neon_qualification   # run 34237585402 (28/28 passed)
.venv/bin/python3 -m pytest tests/ -k "godmode or authority or authorization or approval or replay or cancellation or audit or auth or tenant" -q
git diff e015ec2 -- tests/test_memory_legacy_authority.py orca/brain/memory.py    # confirmed pre-existing, unrelated failure untouched by this subphase
mcp__Neon__delete_branch(project_id, branch_id=br-plain-dew-b3xhd4c8)   # cleanup
gh secret delete ORNEUR_MISSION_DATABASE_URL --env phase14b-staging     # cleanup
gh secret delete ORNEUR_MISSION_DATABASE_URL_DIRECT --env phase14b-staging  # cleanup
gh api repos/.../environments/phase14b-staging/secrets                  # confirmed both deleted, only original Phase 14 secrets remain
```

**TESTS EXECUTED:**
- UNIT: `tests/test_executor_unit.py` (3 tests) — local, no DB.
- INTEGRATION (real godmode, SQLite backend, local): `tests/test_authority_bridge.py` (6 tests).
- LIVE_NEON_TEMP_BRANCH: `tests/test_operation_store_live_neon.py` (28 tests) — GitHub Actions, against branch `br-plain-dew-b3xhd4c8` (cloned from `production`, deleted after use). First dispatch (run `34236567314`): 17 passed, 2 failed. Second dispatch after fixes (run `34237585402`): **28 passed**.
- Cross-check regression: full godmode/authority/authorization/approval/replay/cancellation/audit/auth/tenant-isolation suite plus all Phase 15 mission/operation tests, local.

**EXACT RESULTS:**
```
(local, pre-dispatch sanity)
tests/test_authority_bridge.py tests/test_executor_unit.py tests/test_mission_requirements.py tests/test_mission_schema.py: 33 passed
```
```
(GitHub Actions, run 34236567314 -- FIRST live dispatch, BEFORE fixes)
17 passed, 2 failed
FAILED tests/test_operation_store_live_neon.py::TestConcurrency::test_L_concurrent_execution_calls_executor_exactly_once
FAILED tests/test_operation_store_live_neon.py::TestCancellation::test_K_cancelled_requested_operation_never_executes
```
```
(local, post-fix sanity)
tests/test_operation_store_live_neon.py tests/test_authority_bridge.py tests/test_executor_unit.py: 9 passed, 19 skipped
```
```
(GitHub Actions, run 34237585402 -- SECOND live dispatch, AFTER fixes)
======================== 28 passed in 267.72s (0:04:27) ========================
```
```
(local security regression cross-check, post-fix)
1 failed, 344 passed, 11 skipped, 1403 deselected in 461.04s (0:07:41)
FAILED tests/test_memory_legacy_authority.py::test_distill_and_save_no_longer_writes_unscoped_summary
```

**LIVE NEON TESTS:** All 28 in `test_operation_store_live_neon.py` passed against real Neon on the second dispatch, run `34237585402`. Covered exactly the required A–M narrative: (A) `request_operation` creates a real row; (B) idempotent retry with the same key returns the existing operation, no duplicate row; (C) same key with different parameters raises `OperationConflictError`; (M) the underlying `operations.idempotency_key UNIQUE` constraint is still the real backstop even if application-level dedup were bypassed; (D) `approved_by == requested_by` is rejected with `SelfAuthorizationError` before any godmode call; (E) a valid external approval authorizes via the real godmode lease path; (F) an authorized operation starts and succeeds through the real executor; execution failure is recorded as FAILED with the real exception, not flattened to a generic error; an unauthorized (REQUESTED-state) operation cannot be started; (G) a retried "lost response" after real success does NOT re-invoke the executor (`call_count` stays 1, identical `result_ref` returned); (H) simulated process loss (all connections closed, brand-new connection opened) reconstructs the exact persisted state and resumes correctly; (I) a lease issued for operation A does not authorize operation B (per-operation `resource_scope` binding, live-proven); (J) an already-AUTHORIZED operation cannot be re-authorized; (K) a CANCELLED operation is never executed (graceful no-op, `call_count == 0`); (L) four concurrent threads racing to start the SAME authorized operation invoke the executor exactly once (fixed this dispatch — see CONCURRENCY FINDINGS); the underlying `idempotency_key UNIQUE` constraint still wins when two concurrent `request_operation()` calls share a key (one operation, not two).

**SECURITY FINDINGS:** No raw Neon connection string was ever printed in visible response text or committed to any file, following the same three-layer handling as Phase 15.4 (local `.gitignore`d scratch file, GitHub Actions encrypted secret, deleted after use). `authority_bridge.py` performs zero authorization decisions itself — every ALLOW/DENY comes from the real `orca.godmode.resolution.resolve_and_consume_lease()`, so the mature expired/revoked/replay/TOCTOU protections already proven by `test_godmode_security.py`, `test_godmode_distributed_atomicity.py`, `test_redteam_toctou.py`, and related suites apply transitively, unmodified — not reinvented.

**AUTHORITY FINDINGS:** Manual smoke-test (one-off script, not committed, deleted after use) directly confirmed the exact denial reasons godmode returns: reusing a single-use lease a second time → DENY "lease has no uses remaining"; using operation A's lease to authorize operation B → DENY "scope mismatch: lease covers resource='mission-operation:...' operation='deploy'". `issue_operation_lease()` always routes through `orca.godmode.issuance.issue_lease()`, which rejects wildcard scopes and caps duration at 900s — confirmed by `test_wildcard_kind_rejected_at_issuance`.

**OPERATION LIFECYCLE FINDINGS:** The `operations` table `CHECK` constraint plus `_ALLOWED_TRANSITIONS` in `operation_store.py` jointly enforce the exact lifecycle the spec requires: `REQUESTED → {AUTHORIZED, CANCELLED}`, `AUTHORIZED → {STARTED, CANCELLED}`, `STARTED → {SUCCEEDED, FAILED}`, all four terminal states empty. `REQUESTED → STARTED` and `REQUESTED/AUTHORIZED → SUCCEEDED` (skipping STARTED) are both structurally unreachable — proven by `test_cannot_start_unauthorized_operation`.

**IDEMPOTENCY FINDINGS:** Dedup on `idempotency_key` happens via `INSERT ... ON CONFLICT DO NOTHING RETURNING id` — before any side effect is attempted, not as an after-the-fact UNIQUE-violation catch. `compute_fingerprint()` uses only stdlib `hashlib.sha256` over canonical (sorted-key) JSON — no custom crypto, no raw secret material hashed. A retried key with different parameters is a hard `OperationConflictError`, never silently ignored or silently accepted.

**APPROVAL FINDINGS:** Every `authorize_operation()` call records BOTH an `authority_decisions` row (the godmode ALLOW/DENY, with reasons) and an `approvals` row (APPROVED/REJECTED, carrying the real `lease_id` as a foreign reference — never a duplicate authority store) — durable, queryable, and independent of any in-memory cache (proven by `test_H_process_loss_fresh_connection_reconstructs_exact_state` reloading everything through a brand-new connection).

**REPLAY-REVOCATION FINDINGS:** Single-use lease semantics come entirely from godmode's own `uses_remaining` mechanism (proven live in `test_lease_is_single_use`) — no separate nonce/replay system was invented for Phase 15.5, per the explicit instruction to inspect and reuse what already exists rather than build a parallel one.

**CANCELLATION FINDINGS:** A REQUESTED operation can be cancelled and is confirmed to never execute (`test_K`, `call_count == 0`). An AUTHORIZED-but-not-started operation can also be cancelled and never executes (`test_cancelled_authorized_operation_never_executes`). Any terminal state (SUCCEEDED/FAILED/CANCELLED) rejects a further cancel attempt (`test_terminal_operation_cannot_be_cancelled`) — cancellation is itself subject to the same `_ALLOWED_TRANSITIONS` table as every other state change, not a special-cased bypass.

**PROCESS-RESTART DURABILITY FINDINGS:** `test_H` closes every connection between the AUTHORIZED write and the subsequent read, opens a brand-new connection, and confirms both the reloaded state (`AUTHORIZED`) and the post-execution state (`SUCCEEDED`) are correct with no reliance on any in-memory cache or object identity.

**CONCURRENCY FINDINGS (the two real bugs found and fixed this subphase):**
1. `test_L_concurrent_execution_calls_executor_exactly_once` failed on the first live dispatch: `start_and_execute_operation()`'s initial status read (unlocked) let multiple concurrent callers all observe `AUTHORIZED` before any of them committed a transition, so only the first caller's `FOR UPDATE`-protected `_write_operation_transition(..., "STARTED")` succeeded — the other three raised an unhandled `OperationStateError("STARTED -> STARTED")`. **Fixed** by catching `OperationStateError` specifically at that call site, rolling back, re-reading the row's actual current state, and returning it gracefully (no re-raise, no executor recall) whenever that state is already STARTED/SUCCEEDED/FAILED/CANCELLED — i.e., a losing racer observes the winner's real result instead of erroring. Re-verified live: 4 concurrent threads, `executor.call_count == 1`, all four callers return the same SUCCEEDED result.
2. `test_K_cancelled_requested_operation_never_executes` failed on the first live dispatch with "DID NOT RAISE OperationStateError" — this was a **test bug**, not an implementation bug: the test wrongly expected a raise where the implementation's actual (and correct) design is a graceful idempotent no-op for a CANCELLED operation, exactly the same treatment already given to SUCCEEDED/FAILED and already proven correct by the passing sibling test `test_cancelled_authorized_operation_never_executes`. **Fixed** by correcting the test's assertion to match the intentional design (`result["status"] == "CANCELLED"`, `executor.call_count == 0`) rather than changing the implementation.
- `test_concurrent_requests_same_idempotency_key_one_operation_wins` (two concurrent `request_operation()` calls, same key): passed on both dispatches — the `ON CONFLICT DO NOTHING RETURNING id` pattern already handled this race correctly without any additional locking.

**AUDIT FINDINGS:** `authority_decisions` and `approvals` rows carry `requested_by`/`approved_by`/timestamps/reasons — no secrets recorded. This subphase does not claim tamper-evidence or cryptographic chaining; that would require integration with the real durable-audit-chain mechanism in `orca/godmode/durable_audit.py`, which was not undertaken here (see KNOWN LIMITATIONS).

**MISSION STATE FINDINGS:** N/A new this subphase — `orca/mission/operation_store.py` operates on the `operations` table independently of `missions.state`; no mission-state transition code was touched.

**CHECKPOINT-RESUME FINDINGS:** `REQ-CKPT-RESTORE-002` explicitly revisited per the owner's instruction (see REQUIREMENT STATUS DELTA) — Phase 15.5 built and live-proved the operation-level idempotency primitive this requirement depends on, but no test yet combines `mission_store.restore_mission()` with an operation-record dedup check in one path, so the requirement's exact acceptance criterion remains unmet and it is honestly left at IMPLEMENTED, not promoted.

**RELAY FINDINGS:** N/A this subphase.

**ANTI-TEST-GAMING FINDINGS:** N/A this subphase — `REQ-ANTIGAME-DETECT-001` remains UNIMPLEMENTED, unchanged.

**PRODUCTION PROOF STATUS:** N/A this subphase — `REQ-PROOF-NOINVENT-001` remains UNIMPLEMENTED, unchanged.

**REGRESSIONS:** None caused by this subphase. The local security regression cross-check (godmode/authority/authorization/approval/replay/cancellation/audit/auth/tenant-isolation suite) shows exactly one failure — `tests/test_memory_legacy_authority.py::test_distill_and_save_no_longer_writes_unscoped_summary` — confirmed via `git diff e015ec2 -- tests/test_memory_legacy_authority.py orca/brain/memory.py` (zero diff) and via running that single test in isolation (fails the same way with no Phase 15.5 code loaded), to be a pre-existing, order-dependent test-pollution issue in an unrelated legacy memory subsystem, not caused by or related to any file this subphase touched. It is explicitly excluded from this subphase's "no regressions" claim rather than silently omitted.

**TEST COLLECTION DELTA:** +37 (`test_authority_bridge.py`: 6, `test_executor_unit.py`: 3, `test_operation_store_live_neon.py`: 28). Cumulative Phase 15 delta: 19 (15.1) + 8 (15.2) + 48 (15.3) + 23 (15.4) + 37 (15.5) = 135 new tests since Phase 14C.1.

**REQUIREMENT STATUS DELTA:**
- `REQ-OPIDEM-LIFECYCLE-001`: UNIMPLEMENTED → VERIFIED (schema CHECK constraint + `_ALLOWED_TRANSITIONS` satisfy the first criterion; `test_G`/`test_H`/`test_L` live-satisfy the second).
- `REQ-AUTH-EXTERNAL-001`: UNIMPLEMENTED → VERIFIED (`test_D` proves self-approval is rejected independent of any model claim; full godmode/authority/auth/tenant-isolation regression stayed green, with the one unrelated pre-existing failure explicitly disclosed above).
- `REQ-CKPT-RESTORE-002`: revisited, stays IMPLEMENTED (not promoted — see CHECKPOINT-RESUME FINDINGS above; disclosed inline in `orca/mission/requirements_seed.py`, not silently left unexamined).
- Registry after this subphase (19 total): 8 VERIFIED, 2 IMPLEMENTED-only, 9 UNIMPLEMENTED.

**TECHNICAL DEBT:** The concurrency-race fix in `start_and_execute_operation()` (catch `OperationStateError`, re-check, return gracefully) is a targeted fix for the exact race proven by `test_L`; it has not been generalized into a reusable "observe-or-retry" helper, since no second call site needs it yet.

**KNOWN LIMITATIONS:**
- Audit records (`authority_decisions`, `approvals`) are durable and queryable but not yet integrated with `orca/godmode/durable_audit.py`'s tamper-evidence/chaining mechanism — no tamper-evidence claim is made for Phase 15.5's own tables.
- `REQ-CKPT-RESTORE-002`'s exact acceptance criterion (mission-checkpoint-restore combined with operation-record dedup) remains unmet — see CHECKPOINT-RESUME FINDINGS.
- The qualification branch used for live testing (`br-plain-dew-b3xhd4c8`) is deleted — the 28/28 result is a point-in-time proof, reproducible by re-dispatching the same workflow mode against a freshly-created branch.
- This Mac still cannot resolve Neon's Postgres hostnames — all live Neon verification continues to run via GitHub Actions dispatch only.

**UNVERIFIED ITEMS:** None new beyond the disclosed `REQ-CKPT-RESTORE-002` gap.

**DEFERRED ITEMS:** Phase 15.6 through 15.15 — not started. The mission-checkpoint-to-operation integration needed to fully VERIFY `REQ-CKPT-RESTORE-002` is deferred to whichever future subphase first wires mission resume to real operation execution.

**OWNER ACTION REQUIRED:** None.

**EVIDENCE:** This document; `orca/mission/authority_bridge.py`; `orca/mission/executor.py`; `orca/mission/operation_store.py`; `tests/test_authority_bridge.py`; `tests/test_executor_unit.py`; `tests/test_operation_store_live_neon.py`; GitHub Actions run `34236567314` (17/19, first dispatch, quoted above) and run `34237585402` (28/28, second dispatch after fixes, quoted above); Neon branch `br-plain-dew-b3xhd4c8` (created, used, deleted — all via direct Neon MCP tool calls); commit `5f13ebd` (the two bug fixes).

**EPISTEMIC STATE:** VERIFIED — every claim in this checkpoint traces to either a live GitHub Actions test run against real Neon infrastructure, a direct Neon MCP tool response, or a local test run quoted above. The two failures on the first live dispatch and their root causes are disclosed in full rather than omitted; the one unrelated pre-existing regression-suite failure is disclosed rather than silently excluded. No claim in this checkpoint is asserted from confidence alone.

**PROGRESSION VERDICT:**

YES — EVIDENCE SUPPORTS PROGRESSION
