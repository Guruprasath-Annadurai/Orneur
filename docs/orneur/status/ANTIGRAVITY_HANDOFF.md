# Antigravity Qualification Handoff

Status: engineering package for **independent** review. Claude's own assessment is author self-assessment and is **not** independent. No audit signature in this repository is simulated, and none should be inferred from this document. Training remains **NOT_AUTHORIZED**.

## Branches (draft PRs, none merged, none targeting `main` for merge)

| Branch | Tip (at handoff writing) | Contents |
|---|---|---|
| `claude/integration-candidate-1` | `cd6af2a` | Baseline: PRs #22–#37 plus #32, #33 |
| `claude/a-integration-fixes` | see git (`047710d` at writing) | Workstream A: serving authorization, auth secret, production config validation, real PostgreSQL tests, bootstrap hardening, SafeDisk cache, SQLite backup/rollback |
| `claude/b-assistant-foundation` | `cad752e` | Workstream B on top of A: conversations, retention, idempotency, logout/revocation, usage, tools |
| `claude/ws-e-dataquality` | `669e665` | Dataset quality/provenance tooling (new files only) |
| `claude/ws-d-foundation-evidence` | `8f4a3ad` | Foundation evidence reassessment (docs/tools) |
| `claude/ws-g-training-prep` | `e312fe5` | Training preparation tooling, dry-run only |
| `claude/ws-f-evalinfra` | pending | Synthetic fail-closed evaluation infrastructure |

The **consolidated candidate SHA** is recorded in the final report, not here, because it is created after this document and a document cannot contain its own commit hash.

## Dependency graph
`cd6af2a` → A → B. E, D, G, F branch from `cd6af2a` and add disjoint files; merge order A, B, E, D, G, F; expected conflicts: none outside documentation indexes.

## Threat-model updates (what changed, to be attacked)
1. **Serving authorization.** One `_authorize_inference` path (quota, plan gate, moderation, DLP, usage) now fronts chat, stream, vision and ultra paths; an AST invariant test fails if a new route calls the engine without it. *Attack:* find a serving path that reaches a model without it.
2. **Auth secret.** Production-like profiles require a strong env secret; others persist a 0600 file; the process no longer regenerates per restart. *Attack:* restart/rotation, file permission races.
3. **Production config validation** at startup. *Attack:* a unsafe combination that passes.
4. **Owner bootstrap.** Singleton table, hashed single-use email-bound tokens, atomic redeem. *Attack:* squat, replay, race two redeemers on PostgreSQL.
5. **Token revocation** by `jti` (logout / logout-all). *Attack:* token reuse after logout, clock skew.
6. **SafeDisk cache.** Replaces unsafe pickle deserialization (PYSEC-2026-2447) with JSON plus a no-globals unpickler. *Attack:* crafted cache entry.
7. **Web tool authority.** Allow-listed registry for the web surface; server-authority tools denied; `/api/code/run` disabled (403). *Attack:* tool-name aliasing, prompt-injected tool calls.
8. **Row-level security.** RLS enabled but **not FORCE** — a deliberate choice discovered by real PostgreSQL tests (FORCE blocked non-superuser owner inserts). *Attack/review:* confirm the policy design against the table-owner role.

## Exploit/regression harnesses (all in `tests/`)
`test_a_serving_authorization.py`, `test_a_auth_secret.py`, `test_a_production_config.py`, `test_a_postgres_integration.py` (+ `_pg_scenarios.py`; real PostgreSQL 16 via `pgserver`, run with `pip install .[pgtest]`), `test_a_bootstrap_hardening.py`, `test_a_safe_cache.py`, `test_a_sqlite_migration.py` (verbatim pre-G-006 schemas in `tests/fixtures/`), `test_b_logout_revocation.py`, `test_b_conversations.py`, plus Sprint 2 suites (G-020/G-021 web authority, customer correctness).

## Before/after evidence
Real defects found by the new tests and fixed, each shown failing before / passing after: FORCE RLS blocking owner inserts; ambiguous `messages` column in the PostgreSQL usage upsert (every metered request failed); nested DDL "database is locked" in SQLite bootstrap. See commit messages on `claude/a-integration-fixes` and `cad752e`.

## Invariants to check
- Empty acceptance ledger accepts 0 rows (`python scripts/acceptance/validate_register_graph.py --check` → `pretraining=95 numerator=0`).
- Training authorization gate fails closed at every entry point.
- Scorecard has no aggregate percentage (`tests/test_scorecard.py`).

## Test matrix
Python 3.11. Local: `pytest -m "not live_ollama_smoke"`; PostgreSQL tests need `pgserver` and a non-root-traversable path (root sandboxes: copy the package, set `PYTHONPATH`). GitHub CI: 9 jobs, exact-SHA. **Known environment-only failures (5):** tests that assume non-root uid or DNS; they are not caused by the diff and must be re-run in the qualification environment.

## Container / database
Container non-root migration documented in `docs/orneur/status/CONTAINER_NON_ROOT_MIGRATION.md`. SQLite: automatic private pre-migration backup, tested rollback. PostgreSQL: migration idempotency and concurrency scenarios run in subprocesses against a real server.

## Training fail-closed evidence
Training authorization gate tests and the `NOT_TRAINED` guard (`tests/test_genesis_not_trained_guard.py`); Workstream G tooling is dry-run only and asserts it refuses without authorization.

## Serving-authorization tests
See harness list; plus `/metrics` token gating (`ORNEUR_METRICS_TOKEN`).

## Dataset / evaluation evidence
Synthetic data only. Dataset tooling (Workstream E) and evaluation infrastructure (Workstream F) have never touched a protected corpus or a hidden set; they cannot establish readiness.

## Hypotheses
`docs/orneur/research/ORNEUR_DIFFERENTIATION_RESEARCH_PROGRAMME.md`: C1, C2, C3 — pre-registration drafts, no results.

## Unresolved gates (not engineering-closable)
G1 independent architecture review; AUTH-1 and R65 founder acts; Audit #008/#009 text; DATA-1 teacher rights; MODEL-2C license block; V2 private evaluation freeze; trust-root hardware and custody (`HARDWARE_AND_CUSTODY_OPTIONS.md`); FINAL-2 / EXEC-1 founder authorizations.

## Environmental limitations
Sandbox ran as root with no DNS; no GPU; no live provider access; CI is GitHub-hosted; PostgreSQL tests used an embedded server, not the production topology; load and soak testing were not performed.

## Proposed reviewer assignments (for the founder to confirm — none has agreed)
Security review of A (serving authorization, bootstrap, secrets, RLS): Antigravity security reviewer. PostgreSQL/migration review: Antigravity data-platform reviewer. Cryptographic acceptance engine: reviewer who did not author it. G1: a person who did not author RSE-ARCH-1.2. Research design: a statistician external to the authors.

## Outstanding founder actions
Supply Audit #008/#009; decide H1–H7; approve/redirect the PR #29 design proposal; choose C3 workflows and languages; name reviewers; set a budget ceiling if any cloud tier is considered; give (or withhold) every authorization listed under restrictions.
