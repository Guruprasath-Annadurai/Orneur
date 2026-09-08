"""
Phase 15.1 initial requirement compilation -- the first batch of
stable requirement IDs derived directly from
docs/orneur/phase-15/ORNEUR_CODE_RELAY_MASTER_SPEC_V1.md.

This is a MATERIAL requirement set, not an exhaustive sentence-by-
sentence transcription of the spec (the spec itself does not demand
that -- section 5 says "every MATERIAL requirement", section 30 seeds
each subphase's own concerns). Later subphases add their own
requirements here as they're defined (Phase 15.2 adds REQ-STATE-*
schema requirements, Phase 15.11 adds REQ-RELAY-* session
requirements, etc.) -- this file grows across the whole Phase 15
program rather than being finalized in one pass.

Call seed_registry() once at process/test start to populate
orca.mission.requirements' module-level registry.
"""
from __future__ import annotations

from orca.mission.requirements import Requirement, RequirementStatus, register, transition

_SEEDED = False


def seed_registry() -> None:
    global _SEEDED
    if _SEEDED:
        return
    _SEEDED = True

    # -- Mission Engine (spec section 6) --
    register(Requirement(
        id="REQ-MISSION-STATES-001",
        source_section="spec section 6",
        statement="A Mission is a durable unit of ORNEUR Code work with 15 canonical states, "
                   "not merely chat history.",
        acceptance_criteria=(
            "All 15 canonical states are represented: DRAFT, PLANNING, READY, RUNNING, "
            "WAITING_TOOL, WAITING_EXTERNAL_EVENT, WAITING_APPROVAL, VERIFYING, COURT_REVIEW, "
            "PAUSED_USER, PAUSED_WINDOW_REACHED, BLOCKED, FAILED, COMPLETED_UNVERIFIED, "
            "COMPLETED_VERIFIED, CANCELLED.",
            "A mission's state is queryable independent of any chat transcript.",
        ),
    ))
    register(Requirement(
        id="REQ-MISSION-TRANSITIONS-002",
        source_section="spec section 6",
        statement="Mission state transitions must be explicit and validated; invalid "
                   "transitions must be rejected.",
        acceptance_criteria=(
            "An attempted transition not in the mission state machine's allowed-transition "
            "table raises an error and does not change the mission's persisted state.",
            "Every valid transition is covered by a passing test; every tested invalid "
            "transition is confirmed rejected.",
        ),
    ))
    # Phase 15.3 implemented orca/mission/state_machine.py -- the 15
    # states and their validated transitions are real, tested code
    # (tests/test_mission_state_machine.py, 48/48 passing).
    transition(
        "REQ-MISSION-STATES-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/state_machine.py",),
    )
    transition(
        "REQ-MISSION-STATES-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_state_machine.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-153--mission-state-machine",
    )
    transition(
        "REQ-MISSION-TRANSITIONS-002",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/state_machine.py",),
    )
    transition(
        "REQ-MISSION-TRANSITIONS-002",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_state_machine.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-153--mission-state-machine",
    )
    register(Requirement(
        id="REQ-MISSION-DURABILITY-003",
        source_section="spec section 6",
        statement="Mission state must survive browser refresh, browser close, Relay "
                   "disconnect, process restart, worker restart, temporary model failure, "
                   "network interruption, six-hour mission-window expiration, and normal "
                   "service restart.",
        acceptance_criteria=(
            "Mission state is persisted to durable storage (Neon Postgres), not held only "
            "in process memory or a client-side transcript.",
            "A test restarts the process (or simulates equivalent state loss) and confirms "
            "the mission's state, current step, and progress are recoverable unchanged.",
        ),
    ))

    # -- Six-Hour Autonomous Mission Window (spec section 7) --
    register(Requirement(
        id="REQ-WINDOW-DEFAULT-001",
        source_section="spec section 7",
        statement="The standard ORNEUR Code autonomous mission window is 6 hours wall "
                   "clock, configurable, with an injected clock for testing (never a real "
                   "6-hour test wait).",
        acceptance_criteria=(
            "The mission-window duration is a configurable value, defaulting to 6 hours.",
            "Tests exercise the boundary via a clock abstraction that can be advanced "
            "programmatically, not via real elapsed time.",
        ),
    ))
    register(Requirement(
        id="REQ-WINDOW-EXPIRY-002",
        source_section="spec section 7",
        statement="At the six-hour limit, the mission stops starting new discretionary "
                   "work, safely completes/aborts active atomic work, persists full state "
                   "(revision, diff, requirement progress, test state, evidence, failures, "
                   "remaining plan), and transitions to PAUSED_WINDOW_REACHED with no state "
                   "loss.",
        acceptance_criteria=(
            "A test drives the injected clock past the window boundary and confirms the "
            "mission transitions to PAUSED_WINDOW_REACHED.",
            "All required state fields are present and non-lossy after the transition, "
            "verified by resuming the mission and confirming it continues from the exact "
            "recorded point.",
        ),
    ))

    # -- Autonomy Levels (spec section 8) --
    register(Requirement(
        id="REQ-AUTONOMY-LEVELS-001",
        source_section="spec section 8",
        statement="Exactly four bounded autonomy levels exist (L0 ADVISE, L1 EDIT, L2 "
                   "EXECUTE, L3 AUTONOMOUS MISSION, L4 GOVERNED ENTERPRISE AUTONOMY) with "
                   "no uncontrolled L5 root autonomy.",
        acceptance_criteria=(
            "The autonomy-level enumeration has exactly the five named levels (L0-L4) and "
            "no level grants unrestricted host/system authority.",
            "A test confirms no code path can escalate a mission beyond L4 without an "
            "explicit, externally-authorized policy change.",
        ),
    ))

    # -- Durable Mission State (spec section 9) --
    register(Requirement(
        id="REQ-STATE-DOMAINS-001",
        source_section="spec section 9",
        statement="Durable typed state is persisted for the minimum required domains "
                   "(missions, mission_steps, checkpoints, requirements, "
                   "requirement_acceptance_criteria, assumptions, evidence, "
                   "model_invocations, tool_invocations, approvals, authority_decisions, "
                   "relay_sessions, devices, operation_records, production_proofs, "
                   "audit_events), not one giant conversation transcript.",
        acceptance_criteria=(
            "Each listed domain has a corresponding durable table/schema definition.",
            "No domain's state is representable only as an opaque chat-transcript blob.",
        ),
    ))
    # Phase 15.2 built orca/mission/schema.py with a table for every
    # listed domain, live-verified against real Neon (temp branch +
    # production) -- see PHASE15_EVIDENCE.md's Phase 15.2 checkpoint.
    # Corrected retroactively here (should have transitioned during
    # 15.2 itself).
    transition(
        "REQ-STATE-DOMAINS-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/schema.py",),
    )
    transition(
        "REQ-STATE-DOMAINS-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_schema.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-152--durable-data-model",
    )
    register(Requirement(
        id="REQ-STATE-NEON-002",
        source_section="spec section 9",
        statement="The canonical durable database is Neon/Lakebase Postgres, project "
                   "orneur-core (little-boat-61470844), production branch, Singapore "
                   "region; application traffic uses the pooled connection, schema "
                   "migrations/admin operations use the direct/unpooled connection; no "
                   "Neon Auth/Functions/Object Storage/AI Gateway activated merely because "
                   "they exist.",
        acceptance_criteria=(
            "The project and branch identity match exactly: little-boat-61470844, "
            "production branch, aws-ap-southeast-1 -- confirmed live, not assumed.",
            "Schema-modifying code paths are demonstrably distinct from the pooled "
            "application connection path.",
            "No Neon Auth/Functions/Object Storage/AI Gateway capability is enabled unless "
            "a specific, evidenced Phase 15 requirement calls for it.",
        ),
    ))
    # Project/branch identity was confirmed live in Phase 15.0 (Neon MCP
    # describe_project/list_branches, see PHASE15_EVIDENCE.md) -- the
    # narrow "does this project/branch exist and match" half of this
    # requirement is genuinely verified; the connection-routing and
    # capability-restraint halves are not yet implemented in code, so
    # the requirement as a whole stays at IMPLEMENTED, not VERIFIED,
    # until Phase 15.2 actually wires the pooled/direct connection split.
    transition(
        "REQ-STATE-NEON-002",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-150--baseline",),
    )

    # -- Checkpoint System (spec section 10) --
    register(Requirement(
        id="REQ-CKPT-FIELDS-001",
        source_section="spec section 10",
        statement="Every material checkpoint records enough information to resume "
                   "deterministically: checkpoint ID, mission ID, timestamp, mission "
                   "state, current/completed/remaining steps, repository identity, "
                   "branch, base/current revision, working diff reference, requirement/"
                   "test/verification states, evidence references, pending approvals, "
                   "active blocker, tool outcomes, environment identity.",
        acceptance_criteria=(
            "The checkpoint schema includes every listed field.",
            "A test creates a checkpoint and confirms every required field is populated "
            "(non-null where the mission has a value for it).",
        ),
    ))
    # Phase 15.2's checkpoints table has every listed field (schema-
    # level, live-verified via pg_constraint on production) -- only
    # the FIRST acceptance criterion. The second (a test that actually
    # CREATES a checkpoint row and confirms population) isn't done
    # yet -- that's Phase 15.4's job. IMPLEMENTED, not VERIFIED.
    transition(
        "REQ-CKPT-FIELDS-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/schema.py",),
    )
    register(Requirement(
        id="REQ-CKPT-RESTORE-002",
        source_section="spec section 10",
        statement="Checkpoint restoration is tested and must not silently duplicate "
                   "already-completed dangerous operations.",
        acceptance_criteria=(
            "A test restores a mission from a checkpoint taken mid-mission and confirms "
            "execution resumes without re-running any operation whose operation record "
            "already shows SUCCEEDED.",
        ),
    ))

    # -- Operation Idempotency (spec section 11) --
    register(Requirement(
        id="REQ-OPIDEM-LIFECYCLE-001",
        source_section="spec section 11",
        statement="Every significant external/dangerous operation has a stable operation "
                   "ID and a lifecycle of REQUESTED -> AUTHORIZED -> STARTED -> "
                   "(SUCCEEDED | FAILED | CANCELLED); reconnect/retry logic determines "
                   "whether an operation already ran before re-attempting it.",
        acceptance_criteria=(
            "The operation record schema enforces the five-state lifecycle.",
            "A test simulates a lost response after an operation actually SUCCEEDED "
            "server-side and confirms a retry looks up the existing record instead of "
            "re-executing the dangerous action.",
        ),
    ))

    # -- Execution Sandbox (spec section 12) --
    register(Requirement(
        id="REQ-SANDBOX-BOUNDARY-001",
        source_section="spec section 12",
        statement="Generated/untrusted code runs inside a real, enforceable execution "
                   "boundary (not merely a model instruction) with controls over "
                   "filesystem, network, environment variables, secrets, CPU/RAM, "
                   "runtime duration, process count, privileges, child processes, and "
                   "working directory, across DEVELOPMENT/TEST/STAGING/PRODUCTION "
                   "boundaries.",
        acceptance_criteria=(
            "A test attempts a boundary-violating action (e.g. unrestricted network "
            "access, exceeding the runtime limit) and confirms it is actually blocked or "
            "terminated, not merely discouraged.",
        ),
    ))

    # -- Authority Engine (spec section 14) --
    register(Requirement(
        id="REQ-AUTH-EXTERNAL-001",
        source_section="spec section 14",
        statement="Models are not organizational authorities; policy is enforced outside "
                   "model prose; dangerous operations are classified and require approval "
                   "per policy; a model cannot approve its own authority escalation.",
        acceptance_criteria=(
            "A test attempts to have a model-originated action self-approve a classified "
            "dangerous operation and confirms the authority engine rejects it "
            "independent of what the model claims.",
            "Existing orca.godmode authority/security invariants remain green (non-"
            "regression, spec section 32).",
        ),
    ))

    # -- Anti-Test-Gaming (spec section 15) --
    register(Requirement(
        id="REQ-ANTIGAME-DETECT-001",
        source_section="spec section 15",
        statement="ORNEUR Code detects/blocks attempts to make a task 'pass' by deleting, "
                   "disabling, or weakening tests/assertions/security controls without a "
                   "real, approved requirement-change justification.",
        acceptance_criteria=(
            "A test simulates a diff that deletes or weakens a security-relevant "
            "assertion with no linked requirement change and confirms the anti-gaming "
            "check flags/blocks it.",
            "A test simulates a legitimate test edit backed by an approved requirement "
            "change and confirms it is NOT blocked.",
        ),
    ))

    # -- No Fake Completion (spec section 17) --
    register(Requirement(
        id="REQ-NOFAKE-DISTINCTION-001",
        source_section="spec section 17",
        statement="COMPLETED_UNVERIFIED and COMPLETED_VERIFIED remain distinct mission "
                   "states; a missing test produces UNVERIFIED, never a fabricated PASS.",
        acceptance_criteria=(
            "The mission state machine has both states as distinct, non-interchangeable "
            "terminal states.",
            "A test confirms a mission with an unresolved/missing verification cannot "
            "reach COMPLETED_VERIFIED.",
        ),
    ))
    transition(
        "REQ-NOFAKE-DISTINCTION-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/state_machine.py",),
    )
    transition(
        "REQ-NOFAKE-DISTINCTION-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_state_machine.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-153--mission-state-machine",
    )

    # -- Production Proof (spec section 18) --
    register(Requirement(
        id="REQ-PROOF-NOINVENT-001",
        source_section="spec section 18",
        statement="Production Proof is a first-class evidence artifact that never "
                   "invents evidence; a missing check produces UNVERIFIED, not PASS.",
        acceptance_criteria=(
            "The Production Proof schema has an explicit UNVERIFIED state per category.",
            "A test generates a Production Proof for a mission with an incomplete check "
            "category and confirms that category reads UNVERIFIED, not PASS.",
        ),
    ))

    # -- Relay core (spec section 22) --
    register(Requirement(
        id="REQ-RELAY-STATE-001",
        source_section="spec section 22",
        statement="Relay synchronizes governed engineering state (workspace, repository, "
                   "branch, revision, mission/step state, requirement/test/verification "
                   "progress, Production Proof status, pending approvals/dangerous "
                   "actions, checkpoints, agent/tool activity summaries, authority "
                   "context), not just files, and never relays raw secrets.",
        acceptance_criteria=(
            "A test reconnects a second device to an existing mission and confirms every "
            "listed state category is present in the synchronized payload.",
            "A test confirms no raw secret value ever appears in a Relay payload -- only "
            "secret references.",
        ),
    ))

    # -- Device Trust + Session Revocation (spec section 25) --
    register(Requirement(
        id="REQ-DEVICE-REVOCATION-001",
        source_section="spec section 25",
        statement="Relay session/device state supports creation, expiry, device "
                   "association, last-seen tracking, and revoke-current/revoke-other/"
                   "revoke-all-others; Public Device Mode is visibly and technically "
                   "distinct from Trusted Device mode.",
        acceptance_criteria=(
            "A test revokes a specific other-device session and confirms that session's "
            "subsequent requests are rejected while the revoking session remains valid.",
            "A test confirms a Public Device session cannot access raw secrets that a "
            "Trusted Device session of the same user can.",
        ),
    ))

    # -- Reconnect Truthfulness (spec section 26) --
    register(Requirement(
        id="REQ-RECONNECT-TRUTH-001",
        source_section="spec section 26",
        statement="A lost response never becomes a fake success; reconnect reconciles "
                   "server-side durable operation state (e.g. a deployment that succeeded "
                   "server-side after the client disconnected is discovered as SUCCEEDED "
                   "on reconnect, never re-issued).",
        acceptance_criteria=(
            "A test drops the connection after a dangerous operation is REQUESTED but "
            "before the client sees the response, confirms the operation completes "
            "server-side, then reconnects and confirms the client observes SUCCEEDED "
            "without re-issuing the operation.",
        ),
    ))


__all__ = ["seed_registry"]
