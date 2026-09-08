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
