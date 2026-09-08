"""
Phase 15.2 -- durable schema for the Mission Engine + Relay (spec
section 9's minimum durable domains, plus section 9's explicitly-
permitted Phase-16-reserved storage domains).

Postgres-only by design (spec section 9: "Postgres only is currently
intentional"), targeting the Neon project `orneur-core`
(little-boat-61470844) -- a database entirely separate from the
existing Supabase-backed Phase 14 authority/tenant databases (see
docs/orneur/phase-15/PHASE15_IMPLEMENTATION_PLAN.md). No cross-
database foreign keys are declared to orca.auth's users/organizations
tables (a different Postgres instance) -- user_id/org_id columns here
are plain TEXT references, validated at the application layer.

Follows the existing project's own established table convention
(see orca/auth/db.py): TEXT primary keys (app-generated IDs, not
SERIAL/UUID column types), TEXT timestamps (ISO 8601 strings, so the
exact same string round-trips through Python's `datetime.isoformat()`
without a driver-specific timestamp type), and JSON-shaped columns
stored as TEXT (parsed/serialized in Python) rather than native JSONB
-- kept consistent with how the rest of this codebase already does
it, not a new convention introduced for Phase 15 alone.

CHECK constraints on status/enum columns ARE added here (a real,
inexpensive extra safety net Postgres provides for free) even though
orca/auth/db.py doesn't use them -- enum validity is enforced in
Python (orca.mission.requirements.RequirementStatus and friends) as
the primary guard; the CHECK constraint is defense-in-depth against a
future direct-SQL write that bypasses the Python layer, not a
replacement for it.
"""
from __future__ import annotations

SCHEMA_SQL = """
-- ─────────────────────────────────────────────────────────────────
--  Mission Engine (spec section 6, 9)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS missions (
    id                 TEXT PRIMARY KEY,
    workspace_id       TEXT,
    repository         TEXT NOT NULL,
    branch             TEXT,
    base_revision      TEXT,
    current_revision   TEXT,
    mode               TEXT NOT NULL CHECK (mode IN ('ASSIST', 'PROTOTYPE', 'BUILD', 'LAUNCH')),
    autonomy_level     TEXT NOT NULL CHECK (autonomy_level IN ('L0', 'L1', 'L2', 'L3', 'L4')),
    state              TEXT NOT NULL CHECK (state IN (
                           'DRAFT', 'PLANNING', 'READY', 'RUNNING', 'WAITING_TOOL',
                           'WAITING_EXTERNAL_EVENT', 'WAITING_APPROVAL', 'VERIFYING',
                           'COURT_REVIEW', 'PAUSED_USER', 'PAUSED_WINDOW_REACHED',
                           'BLOCKED', 'FAILED', 'COMPLETED_UNVERIFIED',
                           'COMPLETED_VERIFIED', 'CANCELLED'
                       )),
    owner_user_id      TEXT NOT NULL,
    window_started_at  TEXT,
    window_deadline_at TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_missions_owner ON missions(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_missions_state ON missions(state);

CREATE TABLE IF NOT EXISTS mission_steps (
    id           TEXT PRIMARY KEY,
    mission_id   TEXT NOT NULL REFERENCES missions(id),
    step_index   INTEGER NOT NULL,
    description  TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'SKIPPED')),
    started_at   TEXT,
    completed_at TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mission_steps_mission ON mission_steps(mission_id);

-- ─────────────────────────────────────────────────────────────────
--  Checkpoint System (spec section 10)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS checkpoints (
    id                     TEXT PRIMARY KEY,
    mission_id             TEXT NOT NULL REFERENCES missions(id),
    created_at             TEXT NOT NULL,
    mission_state          TEXT NOT NULL,
    current_step_id        TEXT,
    completed_step_ids     TEXT NOT NULL DEFAULT '[]',   -- JSON array
    remaining_step_ids     TEXT NOT NULL DEFAULT '[]',   -- JSON array
    repository             TEXT NOT NULL,
    branch                 TEXT,
    base_revision          TEXT,
    current_revision       TEXT,
    diff_ref               TEXT,
    requirement_states     TEXT NOT NULL DEFAULT '{}',   -- JSON object: req_id -> status
    test_states            TEXT NOT NULL DEFAULT '{}',   -- JSON object
    verification_states    TEXT NOT NULL DEFAULT '{}',   -- JSON object
    evidence_refs          TEXT NOT NULL DEFAULT '[]',   -- JSON array
    pending_approvals      TEXT NOT NULL DEFAULT '[]',   -- JSON array
    active_blocker         TEXT,
    resource_budget_state  TEXT,                          -- JSON object, nullable
    tool_outcomes          TEXT NOT NULL DEFAULT '[]',   -- JSON array
    environment_identity   TEXT
);
CREATE INDEX IF NOT EXISTS ix_checkpoints_mission ON checkpoints(mission_id, created_at);

-- ─────────────────────────────────────────────────────────────────
--  Requirement Compiler (spec section 5, 9) -- durable mirror of
--  orca.mission.requirements' in-memory registry (Phase 15.1).
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS requirements (
    id              TEXT PRIMARY KEY,   -- the REQ-<AREA>-<NAME>-<NNN> string itself
    mission_id      TEXT REFERENCES missions(id),   -- nullable: some requirements are project-level, not mission-scoped
    source_section  TEXT NOT NULL,
    statement       TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('UNIMPLEMENTED', 'IMPLEMENTED', 'VERIFIED')),
    evidence_ref    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_requirements_mission ON requirements(mission_id);

CREATE TABLE IF NOT EXISTS requirement_acceptance_criteria (
    id             TEXT PRIMARY KEY,
    requirement_id TEXT NOT NULL REFERENCES requirements(id),
    criterion      TEXT NOT NULL,
    satisfied      INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_req_acceptance_criteria_req ON requirement_acceptance_criteria(requirement_id);

-- ─────────────────────────────────────────────────────────────────
--  Assumptions (spec section 4) -- VERIFIED/UNVERIFIED/UNKNOWN/
--  CONTESTED, the explicit Phase-15-scale stand-in for the future
--  Epistemic State Machine (Phase 16) -- not claimed to be that
--  system, just an honest assumption-tracking primitive.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS assumptions (
    id         TEXT PRIMARY KEY,
    mission_id TEXT REFERENCES missions(id),
    statement  TEXT NOT NULL,
    state      TEXT NOT NULL CHECK (state IN ('VERIFIED', 'UNVERIFIED', 'UNKNOWN', 'CONTESTED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_assumptions_mission ON assumptions(mission_id);

-- ─────────────────────────────────────────────────────────────────
--  Evidence (spec section 9, 18) -- REFERENCES only, never raw
--  secret values (enforced at the application layer that writes
--  rows here, spec section 13/34).
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS evidence (
    id             TEXT PRIMARY KEY,
    mission_id     TEXT REFERENCES missions(id),
    requirement_id TEXT REFERENCES requirements(id),
    kind           TEXT NOT NULL,   -- e.g. test_result, command_output, doc_ref, workflow_run
    reference      TEXT NOT NULL,   -- a path/URL/pointer, never a secret value
    summary        TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evidence_mission ON evidence(mission_id);
CREATE INDEX IF NOT EXISTS ix_evidence_requirement ON evidence(requirement_id);

-- ─────────────────────────────────────────────────────────────────
--  Operation Idempotency (spec section 11)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS operations (
    id              TEXT PRIMARY KEY,
    mission_id      TEXT REFERENCES missions(id),
    idempotency_key TEXT NOT NULL UNIQUE,   -- the stable operation ID a client uses to dedupe on reconnect
    kind            TEXT NOT NULL,          -- deploy | migration | delete | publish | ...
    status          TEXT NOT NULL CHECK (status IN ('REQUESTED', 'AUTHORIZED', 'STARTED', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    requested_at    TEXT NOT NULL,
    authorized_at   TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    result_ref      TEXT
);
CREATE INDEX IF NOT EXISTS ix_operations_mission ON operations(mission_id);

-- ─────────────────────────────────────────────────────────────────
--  Approvals + Authority Decisions (spec section 14)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS approvals (
    id           TEXT PRIMARY KEY,
    mission_id   TEXT REFERENCES missions(id),
    operation_id TEXT REFERENCES operations(id),
    requested_at TEXT NOT NULL,
    decided_at   TEXT,
    decision     TEXT NOT NULL CHECK (decision IN ('PENDING', 'APPROVED', 'REJECTED')),
    decided_by   TEXT,   -- user id or device id -- never a model
    reason       TEXT
);
CREATE INDEX IF NOT EXISTS ix_approvals_mission ON approvals(mission_id);

CREATE TABLE IF NOT EXISTS authority_decisions (
    id           TEXT PRIMARY KEY,
    mission_id   TEXT REFERENCES missions(id),
    operation_id TEXT REFERENCES operations(id),
    decision     TEXT NOT NULL CHECK (decision IN ('ALLOW', 'DENY')),
    policy_ref   TEXT,
    decided_at   TEXT NOT NULL,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS ix_authority_decisions_mission ON authority_decisions(mission_id);

-- ─────────────────────────────────────────────────────────────────
--  Model / Tool Invocation Records (spec section 9)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS model_invocations (
    id              TEXT PRIMARY KEY,
    mission_id      TEXT REFERENCES missions(id),
    step_id         TEXT REFERENCES mission_steps(id),
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    purpose         TEXT,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    token_usage     TEXT,   -- JSON, nullable
    outcome_summary TEXT
);
CREATE INDEX IF NOT EXISTS ix_model_invocations_mission ON model_invocations(mission_id);

CREATE TABLE IF NOT EXISTS tool_invocations (
    id              TEXT PRIMARY KEY,
    mission_id      TEXT REFERENCES missions(id),
    step_id         TEXT REFERENCES mission_steps(id),
    tool_name       TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    status          TEXT,
    outcome_summary TEXT
);
CREATE INDEX IF NOT EXISTS ix_tool_invocations_mission ON tool_invocations(mission_id);

-- ─────────────────────────────────────────────────────────────────
--  ORNEUR Relay -- devices, relay sessions (spec section 22-27)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS devices (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    name          TEXT,
    trust_level   TEXT NOT NULL CHECK (trust_level IN ('TRUSTED', 'PUBLIC')),
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    revoked_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_devices_user ON devices(user_id);

CREATE TABLE IF NOT EXISTS relay_sessions (
    id              TEXT PRIMARY KEY,
    mission_id      TEXT REFERENCES missions(id),
    device_id       TEXT NOT NULL REFERENCES devices(id),
    user_id         TEXT NOT NULL,
    mode            TEXT NOT NULL CHECK (mode IN ('TRUSTED_DEVICE', 'PUBLIC_DEVICE', 'MOBILE_REVIEW')),
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    revoked_at      TEXT,
    revoked_reason  TEXT
);
CREATE INDEX IF NOT EXISTS ix_relay_sessions_mission ON relay_sessions(mission_id);
CREATE INDEX IF NOT EXISTS ix_relay_sessions_device ON relay_sessions(device_id);
CREATE INDEX IF NOT EXISTS ix_relay_sessions_user ON relay_sessions(user_id);

-- ─────────────────────────────────────────────────────────────────
--  Production Proof (spec section 18)
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS production_proofs (
    id              TEXT PRIMARY KEY,
    mission_id      TEXT NOT NULL REFERENCES missions(id),
    revision        TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    categories      TEXT NOT NULL,   -- JSON object: category -> {status: PASS|UNVERIFIED|FAIL, detail}
    overall_status  TEXT NOT NULL CHECK (overall_status IN (
                        'ENGINEERING_READY', 'SUBMISSION_READY', 'RELEASE_CANDIDATE', 'PUBLISHED'
                    ))
);
CREATE INDEX IF NOT EXISTS ix_production_proofs_mission ON production_proofs(mission_id);

-- ─────────────────────────────────────────────────────────────────
--  Audit Events (spec section 9) -- append-only by convention
--  (enforced at the application layer, matching orca.auth.db's
--  consent_audit_log pattern rather than introducing a new
--  append-only trigger mechanism here).
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_events (
    id          TEXT PRIMARY KEY,
    mission_id  TEXT REFERENCES missions(id),
    occurred_at TEXT NOT NULL,
    actor       TEXT NOT NULL,   -- user id, device id, or 'system'
    event_type  TEXT NOT NULL,
    detail      TEXT             -- JSON
);
CREATE INDEX IF NOT EXISTS ix_audit_events_mission ON audit_events(mission_id, occurred_at);

-- ─────────────────────────────────────────────────────────────────
--  Phase-16-reserved storage (spec section 9: "may also be reserved
--  ... but do not claim the Phase 16 intelligence semantics are
--  implemented merely because storage tables exist"). These tables
--  intentionally hold only an opaque JSON payload -- no Phase 15
--  code reads or writes semantic meaning into them. They exist so a
--  future Phase 16 migration can ALTER TABLE rather than create from
--  nothing, and so this schema file documents the reservation
--  explicitly rather than leaving it implicit.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS epistemic_transitions_reserved (
    id          TEXT PRIMARY KEY,
    mission_id  TEXT REFERENCES missions(id),
    created_at  TEXT NOT NULL,
    payload     TEXT   -- JSON, opaque -- Phase 16 defines the shape
);

CREATE TABLE IF NOT EXISTS escalations_reserved (
    id          TEXT PRIMARY KEY,
    mission_id  TEXT REFERENCES missions(id),
    created_at  TEXT NOT NULL,
    payload     TEXT
);

CREATE TABLE IF NOT EXISTS failure_genome_reserved (
    id          TEXT PRIMARY KEY,
    mission_id  TEXT REFERENCES missions(id),
    created_at  TEXT NOT NULL,
    payload     TEXT
);

CREATE TABLE IF NOT EXISTS outcome_memory_reserved (
    id          TEXT PRIMARY KEY,
    mission_id  TEXT REFERENCES missions(id),
    created_at  TEXT NOT NULL,
    payload     TEXT
);

CREATE TABLE IF NOT EXISTS capability_delta_reserved (
    id          TEXT PRIMARY KEY,
    mission_id  TEXT REFERENCES missions(id),
    created_at  TEXT NOT NULL,
    payload     TEXT
);
"""

# Every table this schema creates, in creation order -- used by tests
# and by the migration-verification step to confirm nothing was
# silently skipped.
ALL_TABLES: tuple[str, ...] = (
    "missions",
    "mission_steps",
    "checkpoints",
    "requirements",
    "requirement_acceptance_criteria",
    "assumptions",
    "evidence",
    "operations",
    "approvals",
    "authority_decisions",
    "model_invocations",
    "tool_invocations",
    "devices",
    "relay_sessions",
    "production_proofs",
    "audit_events",
    "epistemic_transitions_reserved",
    "escalations_reserved",
    "failure_genome_reserved",
    "outcome_memory_reserved",
    "capability_delta_reserved",
)


# ─────────────────────────────────────────────────────────────────
#  Phase 15.5 schema evolution -- ALTER TABLE ADD COLUMN IF NOT
#  EXISTS, the same idempotent-migration convention already used by
#  orca/auth/db.py (see its init_db()). Applied every time
#  apply_schema() runs, safe on a database that already has these
#  columns.
#
#  operations.parameters_fingerprint: a canonical hash of the
#  operation's material execution intent (spec section 3) -- lets a
#  retry with the SAME idempotency_key but DIFFERENT parameters be
#  detected and rejected as a conflict, instead of silently reusing
#  (or silently ignoring) the original operation.
#  operations.requested_by: the requesting principal -- needed to
#  test the hard invariant "the requester cannot also be the
#  approver" (spec section 21).
#
#  approvals.lease_id: NOT a duplicate authority store. This is a
#  REFERENCE to the real orca.godmode.contracts.CapabilityLease that
#  actually backs this approval -- the lease's own expiry/single-use
#  consumption is enforced for real by
#  orca.godmode.resolution.resolve_and_consume_lease() (the existing,
#  battle-tested, race-safe primitive from Phases 9-14B), not
#  reimplemented here. This column exists so the Neon-side mission/
#  operation domain has a durable, queryable record of WHICH real
#  authority decision authorized a given operation, without competing
#  with godmode as a second source of truth.
#
#  authority_decisions.requested_by: same principal-tracking need as
#  operations.requested_by, recorded on the decision record itself so
#  a decision remains fully self-describing even if the operations
#  row it references is later queried separately.
# ─────────────────────────────────────────────────────────────────

PHASE_15_5_MIGRATION_SQL = """
ALTER TABLE operations ADD COLUMN IF NOT EXISTS parameters_fingerprint TEXT;
ALTER TABLE operations ADD COLUMN IF NOT EXISTS requested_by TEXT;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS lease_id TEXT;
ALTER TABLE authority_decisions ADD COLUMN IF NOT EXISTS requested_by TEXT;
"""
