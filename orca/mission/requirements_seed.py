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
    # Phase 15.4's live Neon test (test_full_pause_checkpoint_restore_resume_cycle)
    # persists real mission state, discards every in-memory object,
    # constructs fresh connections, and confirms exact recovery.
    transition(
        "REQ-MISSION-DURABILITY-003",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/mission_store.py",),
    )
    transition(
        "REQ-MISSION-DURABILITY-003",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_store_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-154--checkpoint--resume",
    )

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
    # Phase 15.14 implements both requirements in
    # orca/mission/mission_window.py, layered entirely on the
    # already-proven Phase 15.4 checkpoint_and_pause()/resume_mission()
    # primitives (no competing checkpoint system, no schema migration).
    transition(
        "REQ-WINDOW-DEFAULT-001", RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/mission_window.py",),
    )
    # test_default_window_is_six_hours (unit) proves the constant;
    # test_default_window_start_is_exactly_six_hours (live Neon) proves
    # a REAL start_autonomous_window() call against real Postgres
    # produces exactly a 6-hour deadline. Every window test in both
    # files uses an injected now_fn -- no test waits six real hours.
    transition(
        "REQ-WINDOW-DEFAULT-001", RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_window.py", "tests/test_mission_window_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1514--six-hour-mission-governance",
    )
    # Phase 15.14.1 -- APPEND-ONLY: VERIFIED is terminal, so no
    # backward transition is attempted. The owner audit flagged that
    # "configurable" duration was exposed as a raw caller-supplied
    # `window_seconds` integer on the authoritative entrypoint, not
    # structurally server-controlled. Closed via `MissionWindowPolicy`
    # / `get_mission_window_policy()` -- see
    # docs/orneur/phase-15/PHASE15_EVIDENCE.md's Phase 15.14.1 section
    # ("SERVER WINDOW POLICY"). Phase 15.14.2 (further audit) found the
    # Phase 15.14.1 closure itself insufficient -- the `_policy`
    # parameter was still caller-injectable despite its underscore
    # prefix. Now REMOVED outright from both `start_autonomous_
    # window()` and `resume_after_window()`; duration is sourced
    # exclusively from `get_mission_window_policy()`, which validates
    # every policy value eagerly at construction. See PHASE15_EVIDENCE
    # .md's Phase 15.14.2 section ("POLICY PARAMETER REMOVAL") for the
    # re-proof.
    # ("SERVER WINDOW POLICY") for the re-proof that no production
    # call site can supply an arbitrary duration.
    transition(
        "REQ-WINDOW-EXPIRY-002", RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/mission_window.py",),
    )
    # test_enforce_window_expiry_atomic_pause_and_checkpoint proves the
    # injected-clock-driven boundary transition to PAUSED_WINDOW_REACHED;
    # test_window_checkpoint_preserves_full_mission_state proves every
    # required field is present and non-lossy;
    # test_resume_after_window_creates_a_new_server_controlled_window
    # and test_req_ckpt_restore_002_exact_acceptance_proof prove the
    # mission continues from the exact recorded point after resume.
    transition(
        "REQ-WINDOW-EXPIRY-002", RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_window_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1514--six-hour-mission-governance",
    )
    # Phase 15.14.1 (owner audit) -- APPEND-ONLY RECONCILIATION, no
    # backward transition attempted: VERIFIED is terminal in this
    # registry's state machine (no outgoing transitions), so the
    # above VERIFIED call is left exactly as it was written. The
    # owner-side audit found the Phase 15.14 qualification that earned
    # it insufficient for the full autonomous-governance boundary this
    # requirement's statement actually implies: a direct
    # start_autonomous_window() could silently renew an EXPIRED
    # window (bypassing the PAUSED_WINDOW_REACHED -> explicit-resume
    # boundary); NOT_STARTED L3/L4 missions could admit new
    # discretionary work with no window ever begun; PAUSED_USER and
    # BLOCKED could be reported eligible while a deadline remained in
    # range; an AUTHORIZED-but-not-yet-STARTED operation could still
    # begin STARTED after expiry; window/state eligibility and new-
    # operation admission were not atomic (a real TOCTOU window
    # existed between the two); and an idempotency-key retry bypass
    # was not mission-bound. Every one of these gaps is now closed in
    # orca/mission/mission_window.py (see module docstring's Phase
    # 15.14.1 section) and re-proven live against real Postgres --
    # see docs/orneur/phase-15/PHASE15_EVIDENCE.md's
    # "PHASE 15.14.1 -- AUTONOMOUS-WINDOW GOVERNANCE CLOSURE" section
    # for the full evidence. This requirement's VERIFIED status is
    # retroactively understood to be backed by THAT evidence going
    # forward, not the narrower Phase 15.14 qualification alone.
    #
    # Phase 15.14.2 (further owner audit) -- APPEND-ONLY, no backward
    # transition: four remaining integrity gaps were found and closed:
    # (1) the Phase 15.14.1 `_policy` seam on `start_autonomous_
    # window()`/`resume_after_window()` was a caller-injectable
    # parameter in fact, regardless of its underscore prefix -- REMOVED
    # outright, both entrypoints now derive duration ONLY from
    # `get_mission_window_policy()`, which itself now validates every
    # policy value eagerly at construction (positive integer, L3 and L4
    # both present); (2) `request_operation_within_window()`'s same-
    # mission retry-bypass fast path returned the existing operation
    # WITHOUT re-checking its material fingerprint, weakening the
    # Phase 15.5 same-key-different-parameters conflict guarantee --
    # closed, fingerprint mismatch now conflicts regardless of window
    # state; (3) `_admit_new_operation_locked()`'s post-ON-CONFLICT
    # lookup did not verify the winning row belonged to the requesting
    # mission, so a lost insert race to a DIFFERENT mission's
    # concurrent request for the same key could return that foreign
    # mission's operation -- closed, cross-mission ownership is now
    # checked before any row is returned; (4) `resume_after_window()`
    # validated that its checkpoint was the mission's LATEST but never
    # that it was CURRENT against the mission's own durable revision --
    # closed, reusing the existing `orca.mission.relay_reconnect.
    # _classify_checkpoint_currency()` rule under the same resume lock.
    # See docs/orneur/phase-15/PHASE15_EVIDENCE.md's
    # "PHASE 15.14.2 -- FINAL WINDOW-INTEGRITY CLOSURE" section for the
    # full evidence.

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
    # Phase 15.4's test_checkpoint_creation_and_field_population creates
    # a real checkpoint with real values for every field (and confirms
    # active_blocker stays genuinely None, not fabricated) -- the
    # second acceptance criterion is now satisfied too.
    transition(
        "REQ-CKPT-FIELDS-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_store_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-154--checkpoint--resume",
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
    # Phase 15.4 proved the ADJACENT, narrower guarantee -- restored
    # checkpoints preserve completed vs. remaining STEPS correctly
    # (test_full_pause_checkpoint_restore_resume_cycle's step H), so
    # restoration itself is real and tested. But this requirement's
    # specific acceptance criterion is about the OPERATIONS table's
    # idempotency-key dedup (SUCCEEDED operation records not re-run),
    # which the spec explicitly reserves for Phase 15.5/15.13 (section
    # 8: "do not overclaim full dangerous-operation idempotency here").
    # IMPLEMENTED only -- VERIFIED requires the operations-table
    # integration this checkpoint layer doesn't yet have.
    #
    # REVISITED in Phase 15.5 per explicit instruction. Phase 15.5 DID
    # build and live-prove the operations-table idempotency primitive
    # this requirement depends on (REQ-OPIDEM-LIFECYCLE-001, now
    # VERIFIED: test_G/test_H prove a retried/reconnected operation
    # does not re-run a SUCCEEDED side effect). But the EXACT acceptance
    # criterion here is narrower and still unmet: no test restores a
    # MISSION from a mission_store checkpoint (mid-mission, via
    # restore_mission()) and then confirms a subsequent operation
    # request against an already-SUCCEEDED operation record is not
    # re-executed as part of that mission-level resume path -- every
    # Phase 15.5 test drives operation_store directly, with no
    # mission_store/checkpoint object in the loop. Per the explicit
    # instruction not to promote "because an operations table exists,"
    # this stays IMPLEMENTED. Deferred to whichever future subphase
    # first wires mission resume to real operation execution (spec
    # section 8/13 territory).
    transition(
        "REQ-CKPT-RESTORE-002",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/mission_store.py", "orca/mission/operation_store.py"),
    )
    # PHASE 15.14 closes the exact gap the comment above identifies:
    # test_req_ckpt_restore_002_exact_acceptance_proof
    # (tests/test_mission_window_live_neon.py) drives the full
    # mission-level path this requirement's acceptance criterion
    # actually names -- a real mission checkpointed mid-mission (via
    # the Phase 15.14 window-expiry boundary, itself built on
    # `checkpoint_and_pause()`), process-state discarded, restored via
    # a fresh connection, explicitly resumed via
    # `resume_after_window()`, and the SAME logical operation
    # (idempotency key K, already SUCCEEDED before the checkpoint) is
    # re-requested/reconciled through that restored mission -- the
    # existing SUCCEEDED record is returned, a fresh executor object
    # is never invoked (`call_count == 0` on retry), and remaining
    # mission work continues under the newly-started window. VERIFIED
    # here, genuinely earned against the requirement's own literal
    # acceptance criterion -- not promoted merely because Phase 15.5's
    # operation-table idempotency already existed independently.
    transition(
        "REQ-CKPT-RESTORE-002",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_mission_window_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1514--six-hour-mission-governance",
    )

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
    # Phase 15.5's operations table CHECK constraint enforces the five
    # states and the exact allowed transitions (orca/mission/schema.py,
    # orca/mission/operation_store.py's _ALLOWED_TRANSITIONS). The
    # second criterion is proven live on real Neon by
    # test_G_retry_after_success_no_duplicate_side_effect: an operation
    # already SUCCEEDED is retried via start_and_execute_operation() and
    # the executor is NOT invoked again (call_count stays 1, same
    # result_ref returned) -- see also test_H (fresh-connection replay
    # after simulated process loss) and test_L (concurrent execution
    # collapses to exactly one real side effect).
    transition(
        "REQ-OPIDEM-LIFECYCLE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/schema.py", "orca/mission/operation_store.py"),
    )
    transition(
        "REQ-OPIDEM-LIFECYCLE-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_operation_store_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-155--operation--authority-engine",
    )

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
    # Phase 15.6 (orca/mission/sandbox_executor.py) implements and
    # adversarially tests a REAL subset of this boundary: workspace
    # cwd containment (traversal/absolute/symlink/sibling-prefix all
    # rejected), path-controlled write/delete tool actions, argv-only
    # execution (no shell injection), a real wall-clock timeout that
    # terminates a runaway process (test_enforced_long_running_
    # process_times_out -- exactly the spec's own "exceeding the
    # runtime limit" example), bounded/truncation-flagged output, an
    # explicit env allowlist (no blind inheritance), and POSIX
    # process-group cleanup (no orphan survives timeout). BUT the
    # statement's own listed dimension "network" is explicitly,
    # adversarially proven NOT enforced at this V1 subprocess layer
    # (test_network_policy_denied_is_not_kernel_enforced_on_this_v1_
    # path), an arbitrary command's absolute-path filesystem access is
    # not namespace-jailed
    # (test_limitation_arbitrary_command_can_write_outside_workspace_
    # via_absolute_path), and RLIMIT_AS/process-count limits are
    # disclosed as unreliable-or-unset on this host. Per the standing
    # rule ("do not promote because a mechanism partially exists"),
    # this stays IMPLEMENTED, not VERIFIED -- the full multi-dimension
    # statement is not yet fully satisfied, even though a real,
    # tested, adversarially-proven boundary now exists for a genuine
    # subset of it.
    transition(
        "REQ-SANDBOX-BOUNDARY-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/sandbox_executor.py", "orca/mission/execution_plan.py"),
    )
    # Phase 15.6.1 (SANDBOX CLOSURE) closes the specific gap that kept
    # this requirement at IMPLEMENTED: orca/mission/container_executor.py
    # is now the QUALIFIED V1 path for RUN_ARBITRARY_COMMANDS (never
    # orca/mission/sandbox_executor.py's LOCAL_SUBPROCESS path, which
    # stays explicitly DEVELOPMENT_ONLY / PARTIAL_ISOLATION /
    # NOT_VERIFIED_SANDBOX -- see ExecutionPath in sandbox_executor.py).
    # Every dimension the statement lists is now adversarially proven
    # on the qualified path, against a REAL Linux Docker daemon (this
    # repo's own CI, GitHub Actions run 34262207489, 27/27 passed --
    # not merely on this dev Mac, where the isolation mechanism is
    # weaker/looser): filesystem (host home/repo-parent/sibling/
    # symlink-escape/traversal all proven absent or denied --
    # test_host_home_directory_not_visible et al.), network (a raw-IP
    # connect attempt under --network none fails with "Network is
    # unreachable", a real kernel denial, not a DNS-only failure --
    # test_outbound_connection_is_kernel_denied_not_dns_failure),
    # environment variables + secrets (explicit allowlist, synthetic
    # secret markers proven absent when not allowlisted --
    # test_synthetic_secret_not_visible_without_allowlist), CPU/RAM
    # (--cpus/--memory, a genuine cgroup OOM-kill observed, exit 137
    # -- test_memory_limit_enforced_via_cgroup_oom), runtime duration
    # (real timeout, truthful TIMED_OUT -- test_timeout_kills_
    # container_truthfully), process count (--pids-limit, a real
    # cgroup-enforced fork failure that leaves the HOST's own process
    # table untouched, unlike the RLIMIT_NPROC bug Phase 15.6
    # disclosed -- test_pids_limit_enforced_by_cgroup_not_host_ulimit),
    # privileges (non-root, dynamically matched to the workspace's
    # real owner after a genuine permission bug was found and fixed
    # via this exact live dispatch -- test_absolute_host_path_read_
    # denied_or_absent), child processes (a grandchild spawned inside
    # the container does not survive a timeout-triggered kill, because
    # the container's whole PID namespace is torn down --
    # test_child_process_inside_container_is_cleaned_up_on_timeout),
    # and working directory (the bind-mounted workspace_root is the
    # ONLY host path visible at all).
    #
    # NOT claimed: the statement's "across DEVELOPMENT/TEST/STAGING/
    # PRODUCTION boundaries" clause is a separate deployment-profile
    # concern (orca.godmode.deployment_profile) this module does not
    # integrate with -- disclosed, not silently assumed satisfied.
    # NetworkPolicy.RESTRICTED remains unimplemented (only DENIED and
    # unrestricted ALLOWED exist) and stays out of scope for this
    # promotion. LOCAL_SUBPROCESS (orca/mission/sandbox_executor.py)
    # remains explicitly NOT the verified path for this requirement --
    # its own partial-enforcement disclosure above is unchanged.
    transition(
        "REQ-SANDBOX-BOUNDARY-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_container_adversarial.py", "tests/test_container_execution_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1561--sandbox-closure",
    )

    # -- Phase 15.6: Code Mode Contract (spec sections 1-2) --
    register(Requirement(
        id="REQ-CODEMODE-CONTRACT-001",
        source_section="spec section 1-2",
        statement="ORNEUR Code implements four canonical modes (ASSIST, PROTOTYPE, BUILD, "
                   "LAUNCH), each with an enforceable capability-action policy, not a "
                   "display label; a mode narrows what may be attempted and never expands "
                   "authority beyond what the real authority engine grants.",
        acceptance_criteria=(
            "A test confirms each mode's policy differs and that ASSIST cannot attempt "
            "WRITE_FILES/DEPLOY/PUBLISH while LAUNCH can attempt them.",
            "A test confirms an action requiring real authority (e.g. DEPLOY) still "
            "requires Phase 15.5 authorization even when the mode permits attempting it.",
        ),
    ))
    transition(
        "REQ-CODEMODE-CONTRACT-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/code_mode.py",),
    )
    transition(
        "REQ-CODEMODE-CONTRACT-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_code_mode.py", "tests/test_code_execution_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-156--code-execution-foundation",
    )

    register(Requirement(
        id="REQ-CODEMODE-AUTHORITY-002",
        source_section="spec section 13, 20",
        statement="Privileged Code-mode execution routes through the existing Phase 15.5 "
                   "operation/authority engine (no parallel authority system); model "
                   "output can never self-authorize execution.",
        acceptance_criteria=(
            "A live test authorizes and executes a Code-mode operation via the real "
            "orca.mission.operation_store + orca.godmode path and confirms it succeeds.",
            "A live test confirms a requester cannot also approve their own Code-mode "
            "operation (SelfAuthorizationError), and that an unauthorized operation "
            "cannot start.",
        ),
    ))
    transition(
        "REQ-CODEMODE-AUTHORITY-002",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/sandbox_executor.py", "orca/mission/operation_store.py"),
    )
    transition(
        "REQ-CODEMODE-AUTHORITY-002",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_code_execution_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-156--code-execution-foundation",
    )

    register(Requirement(
        id="REQ-PROTOTYPE-DEBT-001",
        source_section="spec section 15-16",
        statement="Prototype shortcuts are captured as structured, queryable "
                   "PrototypeDebt; debt blocking LAUNCH must surface (not silently "
                   "disappear) before a mission can claim LAUNCH readiness.",
        acceptance_criteria=(
            "A test records debt, confirms it is queryable by mission, and confirms "
            "blocking debt is surfaced for a PROTOTYPE -> LAUNCH transition until "
            "explicitly resolved.",
            "A test confirms resolved debt is never deleted -- only its status changes.",
        ),
    ))
    transition(
        "REQ-PROTOTYPE-DEBT-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/code_mode.py",),
    )
    transition(
        "REQ-PROTOTYPE-DEBT-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_code_mode.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-156--code-execution-foundation",
    )

    register(Requirement(
        id="REQ-PROVIDER-NEUTRAL-001",
        source_section="spec section 3",
        statement="A provider-neutral model interface exists that does not bind the "
                   "mission engine to any one checkpoint/provider, does not claim any "
                   "ORNEUR-native model (Genesis/Novus/Aeternum) exists, and does not "
                   "expose provider secrets through model-visible state.",
        acceptance_criteria=(
            "Core tests pass using only a deterministic mock provider, no paid provider "
            "required.",
            "A structural test confirms ProviderRequest carries no secret-shaped field.",
        ),
    ))
    transition(
        "REQ-PROVIDER-NEUTRAL-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/providers.py",),
    )
    transition(
        "REQ-PROVIDER-NEUTRAL-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_providers.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-156--code-execution-foundation",
    )

    register(Requirement(
        id="REQ-NOFAKE-EXEC-001",
        source_section="spec section 18",
        statement="A successful command exit is not conflated with verified mission "
                   "completion; a failing, timed-out, or unauthorized Code-mode execution "
                   "can never produce a SUCCEEDED operation or a COMPLETED_VERIFIED "
                   "mission state.",
        acceptance_criteria=(
            "A live test proves a failing command yields a FAILED operation, never "
            "SUCCEEDED.",
            "A live test proves a timed-out command yields a FAILED operation with a "
            "TIMED_OUT-tagged result, never SUCCEEDED.",
            "A live test proves an unauthorized execution attempt cannot start at all.",
        ),
    ))
    transition(
        "REQ-NOFAKE-EXEC-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/sandbox_executor.py", "orca/mission/operation_store.py"),
    )
    transition(
        "REQ-NOFAKE-EXEC-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_code_execution_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-156--code-execution-foundation",
    )

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
    # Phase 15.5's authority_bridge.py contains zero authorization logic
    # of its own -- it is a thin, direct pass-through to the real,
    # mature orca.godmode.resolution.resolve_and_consume_lease(), the
    # same function exercised by godmode's own expired/revoked/replay
    # test suites (test_godmode_security.py,
    # test_godmode_distributed_atomicity.py, test_redteam_toctou.py,
    # etc.) -- those protections apply transitively, unmodified.
    # operation_store.authorize_operation() hard-rejects
    # approved_by == requested_by (SelfAuthorizationError) BEFORE ever
    # calling godmode, proven live by
    # test_D_requester_cannot_approve_own_operation. Cross-operation and
    # cross-tenant binding are proven by
    # test_lease_for_operation_a_does_not_authorize_operation_b and
    # test_wrong_tenant_denied (both live, real godmode SQLite backend).
    # The full existing godmode/authority/auth/tenant-isolation
    # regression suite (344 passed) plus every Phase 15 mission/
    # operation test ran clean after Phase 15.5's changes -- see
    # REGRESSIONS in the evidence checkpoint for the one unrelated,
    # pre-existing failure excluded from this claim.
    transition(
        "REQ-AUTH-EXTERNAL-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/authority_bridge.py", "orca/mission/operation_store.py"),
    )
    transition(
        "REQ-AUTH-EXTERNAL-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_authority_bridge.py", "tests/test_operation_store_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-155--operation--authority-engine",
    )

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
    # Phase 15.11.1 closure: both acceptance criteria above are genuinely
    # satisfied -- tests/test_relay_store_live_neon.py::
    # test_second_device_continuity_asserts_every_governed_domain_individually
    # asserts every REQ-RELAY-STATE-001 domain (workspace, repository,
    # branch, revision, mission/step state, requirement/test/verification
    # progress, Production Proof status, pending approvals/operations,
    # checkpoints, model/tool activity, authority context) individually
    # across two independently-created devices/sessions on the SAME
    # mission; tests/test_relay_store.py and
    # tests/test_relay_store_live_neon.py::test_snapshot_contains_no_raw_secrets_from_seeded_adversarial_fields
    # prove no raw secret value survives in a Relay payload. This is why
    # the canonical registry (not merely an isolated test copy) advances
    # REQ-RELAY-STATE-001 all the way to VERIFIED here.
    transition(
        "REQ-RELAY-STATE-001", RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/relay_store.py",),
    )
    transition(
        "REQ-RELAY-STATE-001", RequirementStatus.VERIFIED,
        test_files=("tests/test_relay_store_live_neon.py", "tests/test_relay_store.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-15111-relay-state-session-authority-integrity-closure",
    )

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
            "A test confirms Public Device Mode cannot access one or more security-sensitive "
            "Relay capabilities/surfaces permitted to a Trusted Device under policy, while raw "
            "secret values remain absent from Relay payloads in BOTH modes.",
        ),
    ))
    # Phase 15.11.2 wording correction: the second acceptance criterion
    # above previously read "a Public Device session cannot access raw
    # secrets that a Trusted Device session of the same user can" --
    # internally contradicting Relay's own canonical invariant that RAW
    # SECRET VALUES ARE NEVER RELAYED, in ANY mode (spec section 19;
    # orca.mission.relay_store's own _sanitize()/redact_secrets() pass
    # applies unconditionally, regardless of RelayMode). That original
    # wording could be misread as implying Trusted Device mode is
    # PERMITTED to relay raw secrets -- it is not, and Phase 15.12 must
    # not implement that. Corrected to describe the REAL intended
    # distinction: Public vs. Trusted differ in which CAPABILITIES/
    # SURFACES are reachable (a policy question Phase 15.12 owns), not
    # in whether raw secrets are ever exposed (they never are, in
    # either mode). This is a correction of internally-contradictory
    # acceptance wording, not a completed security feature -- the
    # requirement's status remains IMPLEMENTED, not VERIFIED, below.
    #
    # Phase 15.11.1: creation/expiry/device-association/last-seen/
    # revoke-current/revoke-other/revoke-all-others are all genuinely
    # implemented and tested (tests/test_relay_store_live_neon.py).
    #
    # Phase 15.12: the SECOND acceptance criterion is now also
    # genuinely satisfied -- `orca.mission.relay_security`'s capability
    # matrix gives Public Device a real, tested, materially narrower
    # capability surface than Trusted Device (OPEN_TERMINAL,
    # EDIT_FILES, RUN_TESTS, AGENT_CONTROL, VIEW_FILES, DEPLOY_CONTROL,
    # DANGEROUS_OPERATION_CONTROL, DOWNLOAD_CONTENT, and CLIPBOARD_EXPORT
    # are all denied to Public but permitted to Trusted --
    # tests/test_relay_security.py::test_public_device_has_at_least_one_capability_trusted_has_that_public_lacks),
    # while raw secret values remain absent from every Relay payload in
    # BOTH modes (proven end-to-end against real live Neon in
    # tests/test_relay_security_live_neon.py::test_no_raw_secrets_in_relay_snapshot_or_mobile_state_across_all_modes).
    # Both acceptance criteria are now genuinely proven -- this
    # requirement advances to VERIFIED.
    transition(
        "REQ-DEVICE-REVOCATION-001", RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/relay_store.py", "orca/mission/relay_security.py"),
    )
    transition(
        "REQ-DEVICE-REVOCATION-001", RequirementStatus.VERIFIED,
        test_files=("tests/test_relay_store_live_neon.py", "tests/test_relay_security.py", "tests/test_relay_security_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-15121-reauth-provenance-session-security-enforcement-closure",
    )

    # -- Relay Reauthentication Boundary (spec sections 7-8, 13) --
    register(Requirement(
        id="REQ-RELAY-REAUTH-001",
        source_section="spec sections 7-8, 13",
        statement="Security-sensitive Relay actions (e.g. Trusted-device enrollment, "
                   "DEPLOY_CONTROL, DANGEROUS_OPERATION_CONTROL) require a genuinely fresh "
                   "reauthentication -- derived from a real orca.auth password/TOTP "
                   "verification, never a caller-supplied boolean -- bound to the "
                   "authenticated user (and, where applicable, the Relay session), and "
                   "expiring on its own; reauthentication permission is never confused with "
                   "operation authorization.",
        acceptance_criteria=(
            "A test performs a REAL password (and, when TOTP is enabled, TOTP) "
            "verification through orca.auth.store/orca.auth.totp and confirms a valid "
            "fresh reauthentication context is produced only on success, never from a "
            "boolean flag.",
            "A test confirms a reauthentication context bound to one user/session cannot "
            "be used to authorize an action for a different user or a different Relay "
            "session, and that an expired context is rejected.",
        ),
    ))
    # Phase 15.12.1 RECONCILIATION (append-only, per the owner's own
    # instruction -- history is not silently rewritten): an independent
    # owner audit of the Phase 15.12 checkpoint found the VERIFIED claim
    # below was OVER-PROMOTED. At that time, `check_capability(...,
    # reauth_valid=True)` let a caller manufacture ALLOW for a reauth-
    # gated capability from a plain boolean, and `ReauthContext` was a
    # publicly-constructible, self-validating dataclass -- a caller
    # could fabricate one with a fake future `expires_at` and matching
    # `factors_verified=("password","totp")` WITHOUT ever presenting a
    # real password or TOTP code, and `is_reauth_context_valid()` would
    # accept it (it validated only the object's OWN fields). Neither
    # defect was caught by the 15.12 test suite, because that suite's
    # own tests used the SAME forgeable pattern. This closure (15.12.1)
    # removed `reauth_valid` entirely, replaced `ReauthContext` with an
    # opaque `ReauthGrant` whose only trustable content is a
    # `secrets.token_urlsafe()` ID looked up in a server-side store
    # (`_REAUTH_GRANTS`), and added `authorize_relay_capability()` as
    # the actual authoritative gate (loads real session/device state,
    # validates a real grant). REQ-RELAY-REAUTH-001 RE-EARNS its
    # VERIFIED status here, now genuinely satisfied: no boolean reauth
    # authorization remains, fabricated grants fail
    # (tests/test_relay_security.py's forged-grant matrix +
    # tests/test_relay_security_live_neon.py's enrollment-forgery
    # matrix), real password/TOTP issuance succeeds, user/session
    # binding succeeds, expiry succeeds, and no caller TTL override
    # remains.
    transition(
        "REQ-RELAY-REAUTH-001", RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/relay_security.py",),
    )
    transition(
        "REQ-RELAY-REAUTH-001", RequirementStatus.VERIFIED,
        test_files=("tests/test_relay_security.py", "tests/test_relay_security_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-15121-reauth-provenance-session-security-enforcement-closure",
    )

    # -- Mobile Review Reduced Surface (spec sections 5, 18, 23) --
    register(Requirement(
        id="REQ-RELAY-MOBILEREVIEW-001",
        source_section="spec sections 5, 18, 23",
        statement="Mobile Review exposes a deliberately reduced review/control surface "
                   "(mission status, diff review, tests, Production Proof, blockers, "
                   "message/approve/reject/pause/resume/revoke) derived from the same "
                   "canonical, already-consistent, already-secret-sanitized RelaySnapshot -- "
                   "never a second independently-queried mission representation -- and "
                   "denies by default a terminal, full editor, arbitrary file browsing, "
                   "and direct deployment/command execution.",
        acceptance_criteria=(
            "A test confirms Mobile Review's effective capability set excludes "
            "OPEN_TERMINAL, EDIT_FILES, VIEW_FILES, RUN_TESTS, AGENT_CONTROL, "
            "DEPLOY_CONTROL, and DANGEROUS_OPERATION_CONTROL for both Trusted and Public "
            "underlying device trust.",
            "A test confirms MobileReviewState is built exclusively from the canonical "
            "RelaySnapshot (same mission identity, revision, and consistency basis), "
            "against real live Neon.",
        ),
    ))
    transition(
        "REQ-RELAY-MOBILEREVIEW-001", RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/relay_security.py",),
    )
    transition(
        "REQ-RELAY-MOBILEREVIEW-001", RequirementStatus.VERIFIED,
        test_files=("tests/test_relay_security.py", "tests/test_relay_security_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-15121-reauth-provenance-session-security-enforcement-closure",
    )

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
    # Phase 15.13 implements orca/mission/relay_reconnect.py: a typed
    # RelayOperationTruth model (never confusing connection loss with
    # operation failure/success) plus reconnect_to_mission()/
    # reconcile_operation(), layered on the already-proven Phase 15.5
    # operation_store.py lifecycle unmodified. VERIFIED here against a
    # REAL live-Neon proof of the exact acceptance criterion above: a
    # deploy-shaped operation is REQUESTED -> AUTHORIZED -> STARTED ->
    # executed exactly once (RecordingTestExecutor.call_count == 1) ->
    # SUCCEEDED, the client's response is simulated lost (never read),
    # a FRESH connection reconnects and observes RelayOperationTruth.
    # CONFIRMED, and a deliberate retry of start_and_execute_operation()
    # still returns SUCCEEDED with executor.call_count still 1 (see
    # tests/test_relay_reconnect_live_neon.py::
    # test_lost_successful_response_reconnect_reports_confirmed_executor_count_still_one,
    # 219/219 passed against a disposable Neon branch, run
    # 34459590675). The companion FAILED- and STARTED/unknown-outcome
    # scenarios are proven by the two adjacent tests in the same file.
    transition(
        "REQ-RECONNECT-TRUTH-001", RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/relay_reconnect.py",),
    )
    transition(
        "REQ-RECONNECT-TRUTH-001", RequirementStatus.VERIFIED,
        test_files=("tests/test_relay_reconnect.py", "tests/test_relay_reconnect_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1513--reconnect--idempotency",
    )

    # -- Multi-Device Stale-Write Conflict (spec sections 15-19, 27) --
    # No existing requirement captures "a stale device's mission-state
    # mutation attempt is reported truthfully (STALE_CONFLICT/DENIED),
    # never silently last-write-wins" -- REQ-RELAY-STATE-001 covers
    # snapshot/session integrity, not mutation-conflict semantics.
    register(Requirement(
        id="REQ-RELAY-STALEMUTATION-001",
        source_section="spec sections 15-19, 27",
        statement="A Relay mission-state mutation (pause/resume) requires a real, "
                   "security-valid Relay session bound to the target mission -- a mission "
                   "ID alone is never proof of authority. The precondition check and the "
                   "mutation write observe the SAME locked durable row (atomic, not a "
                   "two-step read-then-write race). A device whose view of mission state "
                   "or revision is stale is never silently last-write-wins: it is reported "
                   "as a typed STALE_CONFLICT, distinct from a DENIED illegal transition "
                   "and from a successful idempotent no-op when a racing identical request "
                   "already reached the same target state. A durably CANCELLED mission "
                   "cannot be mutated by a stale device under any precondition.",
        acceptance_criteria=(
            "A test moves a mission to RUNNING, then attempts a PAUSE precondition whose "
            "expected_state no longer matches (READY) and confirms STALE_CONFLICT is "
            "reported without mutating the mission's actual durable state.",
            "A test issues the same PAUSE precondition twice in a row (simulating a race) "
            "and confirms the second call reports APPLIED as an idempotent no-op rather "
            "than an error, against real live Neon.",
            "A test attempts an illegal transition (resume a DRAFT mission) with an "
            "accurate expected_state and confirms DENIED, distinct from STALE_CONFLICT.",
            "A test proves the mutation entrypoint requires a real, security-valid Relay "
            "session bound to the target mission -- cross-mission, cross-user, and "
            "revoked-session attempts are all denied, against real live Neon.",
            "A test with TWO REAL Relay sessions/devices for the same mission, forced to "
            "genuine simultaneity via a threading barrier across two independent DB "
            "connections, proves the precondition check and the mutation write observe "
            "the SAME locked row: exactly one wins (APPLIED), the other observes the "
            "ALREADY-CHANGED state and reports STALE_CONFLICT.",
            "A test proves a stale expected_revision (even with an accurate expected_state) "
            "produces STALE_CONFLICT, against real live Neon.",
            "A test proves a durably CANCELLED mission cannot be paused or resumed by a "
            "stale device under any precondition, against real live Neon.",
        ),
    ))
    # PHASE 15.13.1 RECONCILIATION (append-only, per the owner's own
    # instruction -- the original 15.13 VERIFIED claim below is
    # retained, not edited out): an independent owner-side audit found
    # the 15.13 version of this requirement insufficient. The verified
    # implementation at that time (`apply_mission_mutation_precondition()`)
    # had NO `session_id`/`authenticated_user_id` parameters -- it was
    # not actually a Relay-authorized control boundary, and a caller
    # could nominate an arbitrary mission_id without proving
    # authenticated ownership or Relay session validity. Separately,
    # its precondition READ (`get_mission()`, its own committed
    # transaction) and its mutation WRITE (`transition_mission()`,
    # a LATER, separate transaction) left a real race window in which
    # a concurrent writer could change the row between the two -- the
    # existing row lock protected only the WRITE, not the precondition
    # COMPARISON. Neither gap was caught by the 15.13 test suite,
    # which never tested cross-mission/cross-user/revoked-session
    # denial for this entrypoint, and only ever exercised it
    # sequentially, never with two real concurrent connections. This
    # closure (15.13.1) fixes both: `apply_relay_mission_mutation()`
    # is the new, actual Relay-authorized entrypoint (requires
    # `require_security_valid_session()` plus a
    # `session.mission_id == precondition.mission_id` proof before any
    # mutation is attempted), and `mission_store.apply_mutation_with_
    # precondition()` performs the precondition read and the state
    # write under ONE held `SELECT ... FOR UPDATE` lock, proven by a
    # real two-connection concurrent race test. `expected_revision` was
    # also added to `RelayMutationPrecondition` (absent from the 15.13
    # version entirely). REQ-RELAY-STALEMUTATION-001 is RE-EARNED as
    # VERIFIED here, now genuinely satisfied against the strengthened
    # acceptance criteria above -- not merely re-asserted.
    transition(
        "REQ-RELAY-STALEMUTATION-001", RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/relay_reconnect.py", "orca/mission/mission_store.py"),
    )
    # PHASE 15.13.2 RECONCILIATION (append-only): a further owner audit
    # found the 15.13.1 VERIFIED claim (immediately below) still
    # incomplete on two points -- (1) `apply_relay_mission_mutation()`
    # called `require_security_valid_session()`, whose own reads
    # COMMIT internally, and only LATER, in a SEPARATE transaction,
    # locked and mutated the mission row: a real TOCTOU window in
    # which a concurrent session/device revocation could commit in
    # between, and the mutation would still proceed using the earlier,
    # now-stale security read; (2) `RelayMutationPrecondition.
    # expected_revision` could simply be omitted (left `None`) even
    # when the durable mission had a real `current_revision`, silently
    # opting the caller out of optimistic-concurrency protection.
    # Neither gap was caught by the 15.13.1 test suite, which never
    # forced a real session/device-revocation-vs-mutation race with
    # two separate connections, and never tested omitting
    # `expected_revision` against a mission that durably has one.
    # This closure (15.13.2) fixes both: `require_security_valid_
    # session_locked()` (new, in `relay_security.py`) locks the Relay
    # session row, then the bound device row, `FOR UPDATE`, inside the
    # SAME transaction the mission-row lock and mutation now also
    # share (deterministic lock order: session -> device -> mission,
    # one final commit); `_apply_mutation_with_precondition_locked()`
    # gained `require_revision_if_present`, which
    # `apply_relay_mission_mutation()` always passes as `True` -- a
    # durable non-empty `current_revision` with an omitted/empty
    # `expected_revision` is now `STALE_CONFLICT`, never silently
    # eligible. The requirement registry has no "re-verify" transition
    # (VERIFIED is terminal, forward-only) -- re-earning is reflected
    # here by pointing THIS SAME, single VERIFIED transition's
    # `evidence_ref`/`test_files` at the 15.13.2 evidence section,
    # append-only, rather than by a second transition call (which the
    # registry's own state machine would reject).
    transition(
        "REQ-RELAY-STALEMUTATION-001", RequirementStatus.VERIFIED,
        test_files=("tests/test_relay_reconnect_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-15132--atomic-relay-security--revision-enforcement-closure",
    )

    # -- Phase 15.7: Product Contract + Requirement Compiler --
    register(Requirement(
        id="REQ-PRODUCT-CONTRACT-001",
        source_section="Phase 15.7 spec sections 1-2",
        statement="A typed Product Contract exists where a missing fact remains explicitly "
                   "missing/unknown rather than auto-filled with a plausible guess, and "
                   "structural validation (duplicate actors, undefined actor references, "
                   "out-of-scope/acceptance-target overlap) is enforced at construction time.",
        acceptance_criteria=(
            "A test constructs a minimal valid contract and confirms unaddressed fields "
            "are None/empty, never invented.",
            "A test confirms duplicate actor IDs, a journey referencing an undefined actor, "
            "and out-of-scope/acceptance-target overlap are all rejected at construction.",
        ),
    ))
    transition(
        "REQ-PRODUCT-CONTRACT-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/product_contract.py",),
    )
    transition(
        "REQ-PRODUCT-CONTRACT-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_product_contract.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-157--product--requirement-compilers",
    )

    register(Requirement(
        id="REQ-ASSUMPTION-INTEGRITY-001",
        source_section="Phase 15.7 spec sections 3, 11",
        statement="Assumptions/unknowns use exactly the four states the durable assumptions "
                   "table already defines (VERIFIED/UNVERIFIED/UNKNOWN/CONTESTED); VERIFIED "
                   "requires real evidence supplied by the caller, never by the fact's own "
                   "provenance; an inferred or provider-proposed assumption can never "
                   "self-promote to VERIFIED; CONTESTED preserves competing statements "
                   "rather than silently picking one.",
        acceptance_criteria=(
            "A test constructs a Fact directly as VERIFIED and confirms it is rejected -- "
            "verify() with real evidence is the only path to VERIFIED.",
            "A test compiles 'Build me a food-delivery app' with no explicit facts and "
            "confirms payment/country/tax/etc. all become UNKNOWN facts, never VERIFIED.",
            "A test confirms a provider-proposed candidate fact is recorded UNVERIFIED/"
            "INFERRED_ASSUMPTION, never VERIFIED.",
        ),
    ))
    transition(
        "REQ-ASSUMPTION-INTEGRITY-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/assumption_model.py", "orca/mission/idea_compiler.py"),
    )
    transition(
        "REQ-ASSUMPTION-INTEGRITY-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_assumption_model.py", "tests/test_idea_compiler.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-157--product--requirement-compilers",
    )

    register(Requirement(
        id="REQ-REQUIREMENT-COMPILER-001",
        source_section="Phase 15.7 spec sections 5, 8-9, 16",
        statement="Requirement IDs are stable under irrelevant source reordering/formatting "
                   "(derived from content, not list position); a materially changed "
                   "requirement receives a new stable ID rather than silently inheriting the "
                   "old one's evidence; dependency cycles are rejected; structurally obvious "
                   "conflicting requirements are detected and represented, never silently "
                   "resolved; an idea targeting ORNEUR's own platform cannot compile a "
                   "requirement that weakens a real Phase 15.5 authority invariant.",
        acceptance_criteria=(
            "A test computes the same requirement ID for the same statement under different "
            "case/whitespace, and a different ID for materially different statement text.",
            "A test creates a DEPENDS_ON cycle attempt (direct and indirect) and confirms "
            "both are rejected.",
            "A test detects a structurally obvious 'data must remain local' vs 'upload to "
            "third-party' conflict and confirms neither requirement's statement is mutated.",
            "A test attempts to compile an ORNEUR-platform-targeted idea containing an "
            "authority-bypass phrase and confirms IdeaCompilerError is raised.",
        ),
    ))
    transition(
        "REQ-REQUIREMENT-COMPILER-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/idea_compiler.py", "orca/mission/requirement_dependencies.py"),
    )
    transition(
        "REQ-REQUIREMENT-COMPILER-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_idea_compiler.py", "tests/test_requirement_dependencies.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-157--product--requirement-compilers",
    )

    register(Requirement(
        id="REQ-ACCEPTANCE-TRACE-001",
        source_section="Phase 15.7 spec sections 7, 13",
        statement="Every acceptance criterion is typed (verification method, status, "
                   "evidence) and rejects vague/unmeasurable descriptions; missing evidence "
                   "never counts as PASS; implementation existing is not the same as "
                   "verified; a traceability report from Product Contract through "
                   "requirement, acceptance criterion, implementation, test, and evidence "
                   "shows missing links explicitly rather than omitting them.",
        acceptance_criteria=(
            "A test registers an orphan criterion (unregistered requirement_id) and "
            "confirms it is rejected.",
            "A test confirms a vague description ('works well') is rejected at construction.",
            "A test confirms a criterion moved to IMPLEMENTED (not VERIFIED) does not count "
            "as verified, and that a requirement with zero criteria is never vacuously "
            "considered fully verified.",
            "A test traces a freshly compiled requirement and confirms has_missing_links "
            "is True until implementation/test/evidence are actually supplied.",
        ),
    ))
    transition(
        "REQ-ACCEPTANCE-TRACE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/acceptance_criteria.py", "orca/mission/traceability.py"),
    )
    transition(
        "REQ-ACCEPTANCE-TRACE-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_acceptance_criteria.py", "tests/test_traceability.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-157--product--requirement-compilers",
    )

    # -- Phase 15.8: Verification Engine --
    register(Requirement(
        id="REQ-VERIFY-ENGINE-001",
        source_section="Phase 15.8 spec sections 2-6, 27",
        statement="A typed VerificationOutcome vocabulary (PASS/FAIL/UNVERIFIED/"
                   "NOT_APPLICABLE/ERROR/CANCELLED/TIMED_OUT) is enforced structurally: "
                   "missing evidence, a verifier crash, a timeout, or a cancellation can "
                   "never produce PASS; NOT_APPLICABLE requires an explicit reason; real "
                   "command-based verifiers (build, unit test) observe actual execution "
                   "through the governed Phase 15.6/15.6.1 execution paths; a model cannot "
                   "self-declare a deterministic PASS.",
        acceptance_criteria=(
            "A test constructs a VerificationRecord with NOT_APPLICABLE and no reason, "
            "or ERROR with no detail, and confirms both are rejected at construction.",
            "A test runs a real failing/timed-out/cancelled/missing command through "
            "BuildVerifier/UnitTestVerifier and confirms none of them produce PASS.",
            "A test confirms an interface-only verifier (StaticAnalysis/Performance/"
            "Accessibility/ManualReview/ExternalConfirmation) defaults to UNVERIFIED and "
            "only reaches PASS given a real, caller-supplied observation.",
        ),
    ))
    transition(
        "REQ-VERIFY-ENGINE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/verification.py", "orca/mission/verifiers.py"),
    )
    transition(
        "REQ-VERIFY-ENGINE-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_verification.py", "tests/test_verifiers.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-158--verification-engine",
    )

    register(Requirement(
        id="REQ-VERIFY-AGGREGATION-001",
        source_section="Phase 15.8 spec sections 16-18",
        statement="Requirement/criterion aggregation is non-vacuous (an empty or "
                   "all-NOT_APPLICABLE set is UNVERIFIED, never a vacuous PASS); a "
                   "criterion reaches VERIFIED through the integrated engine path only by "
                   "referencing a real VerificationRecord whose outcome is PASS and whose "
                   "requirement_id/criterion_id genuinely match; mission COMPLETED_VERIFIED "
                   "cannot be reached while any required requirement is not PASS for the "
                   "current revision.",
        acceptance_criteria=(
            "A test confirms aggregate_outcomes(()) and an all-NOT_APPLICABLE set both "
            "yield UNVERIFIED, never PASS.",
            "A test confirms a FAIL or wrongly-scoped VerificationRecord cannot verify a "
            "criterion through verify_criterion_via_verification_record().",
            "A test confirms can_complete_verified() returns False when any required "
            "requirement is UNVERIFIED, FAIL, or has only stale-revision evidence.",
        ),
    ))
    transition(
        "REQ-VERIFY-AGGREGATION-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=(
            "orca/mission/verification_aggregation.py", "orca/mission/verification_integration.py",
            "orca/mission/mission_verification_gate.py",
        ),
    )
    transition(
        "REQ-VERIFY-AGGREGATION-001",
        RequirementStatus.VERIFIED,
        test_files=(
            "tests/test_verification_aggregation.py", "tests/test_verification_integration.py",
            "tests/test_mission_verification_gate.py",
        ),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-158--verification-engine",
    )

    register(Requirement(
        id="REQ-VERIFY-STALE-001",
        source_section="Phase 15.8 spec section 21",
        statement="Evidence is bound to the revision it verified; when code changes to a "
                   "new revision, old evidence never silently counts as proof for the new "
                   "revision, even though it remains visible in full history.",
        acceptance_criteria=(
            "An end-to-end test verifies a correct implementation (revision A, PASS), "
            "breaks it (revision B), and confirms revision A's PASS evidence is excluded "
            "from revision B's aggregation -- revision B correctly aggregates to FAIL/"
            "UNVERIFIED, not PASS.",
            "A live test confirms the same exclusion against real, durably-stored "
            "verification history.",
        ),
    ))
    transition(
        "REQ-VERIFY-STALE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/verification_aggregation.py",),
    )
    transition(
        "REQ-VERIFY-STALE-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_verification_e2e.py", "tests/test_verification_store_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-158--verification-engine",
    )

    register(Requirement(
        id="REQ-VERIFY-DURABILITY-001",
        source_section="Phase 15.8 spec sections 25-26, 30",
        statement="Material VerificationRecord state is durable: a record written, then "
                   "reloaded through a fresh connection after all prior connections close, "
                   "shows the exact same outcome/revision/requirement linkage/evidence; a "
                   "FAIL record is never deleted or overwritten by a later PASS -- both "
                   "remain in queryable history.",
        acceptance_criteria=(
            "A live test writes a VerificationRecord, closes the connection, opens a "
            "fresh one, and confirms the reloaded record matches exactly.",
            "A live test writes a FAIL then a PASS record for the same requirement and "
            "confirms both remain independently queryable afterward.",
        ),
    ))
    transition(
        "REQ-VERIFY-DURABILITY-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/verification_store.py", "orca/mission/verification_schema.py"),
    )
    # Live Neon dispatch (GitHub Actions run 34268049123) actually ran
    # and passed: tests/test_verification_store_live_neon.py's fresh-
    # connection reload and FAIL-remains-in-history-after-later-PASS
    # scenarios both passed against the real verification_records
    # table on a disposable branch. Promoted with real test_files +
    # evidence_ref, not inflated ahead of that evidence.
    transition(
        "REQ-VERIFY-DURABILITY-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_verification_store_live_neon.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-158--verification-engine",
    )

    # -- Phase 15.9: Anti-Test-Gaming + Cognitive Court --
    register(Requirement(
        id="REQ-ANTIGAMING-DETECT-001",
        source_section="Phase 15.9 spec sections 1, 3-13, 31-32",
        statement="Baseline-bound (real git revision) analysis detects structurally obvious "
                   "test-suite weakening: deleted tests (distinguished from git-proven renames), "
                   "newly added skip/xfail markers, assertion weakening (fewer asserts, "
                   "broadened equality-to-membership comparisons, pytest.raises() widened to "
                   "bare Exception), new broad exception suppression, and a real integration "
                   "call replaced by a mock while the import that provided it disappears.",
        acceptance_criteria=(
            "A test simulates a diff that deletes or weakens a security-relevant assertion "
            "with no linked requirement change and confirms the anti-gaming check flags/"
            "blocks it.",
            "A test simulates a legitimate test edit (a genuinely NEW, stronger test added) "
            "backed by real coverage and confirms it is NOT flagged.",
            "Real git-repository adversarial fixtures cover all ten spec section 32 scenarios "
            "(deleted test, auth-weakened test, skip-to-avoid-failure, mock-replaces-real, "
            "weakened-but-green assertions, requirement-driven change surfaced not silently "
            "dropped, pure rename not misclassified, new test not flagged, provider narrative "
            "cannot override a CRITICAL finding, provider failure never yields a fake ACCEPT).",
        ),
    ))
    transition(
        "REQ-ANTIGAMING-DETECT-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=(
            "orca/mission/anti_gaming.py", "orca/mission/git_diff_analysis.py",
            "orca/mission/gaming_detectors.py", "orca/mission/test_collection_diff.py",
        ),
    )
    transition(
        "REQ-ANTIGAMING-DETECT-001",
        RequirementStatus.VERIFIED,
        test_files=(
            "tests/test_anti_gaming.py", "tests/test_git_diff_analysis.py",
            "tests/test_gaming_detectors.py", "tests/test_test_collection_diff.py",
        ),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-159--anti-test-gaming--cognitive-court",
    )

    register(Requirement(
        id="REQ-ANTIGAMING-BLOCK-001",
        source_section="Phase 15.9 spec sections 2, 14, 27",
        statement="A CRITICAL blocking anti-gaming finding structurally prevents "
                   "COMPLETED_VERIFIED and prevents a Court ACCEPT verdict, with no code path "
                   "for a critic or provider to vote it away; the same deterministic function "
                   "is consulted by both the mission gate and the Arbiter.",
        acceptance_criteria=(
            "A test constructs a CRITICAL-severity finding with blocking=False and confirms "
            "construction is rejected -- CRITICAL implies blocking structurally.",
            "A test proves arbiter_decide() returns REJECT when a blocking finding exists, "
            "even when every supplied critic output is SUPPORTS_ACCEPT.",
        ),
    ))
    transition(
        "REQ-ANTIGAMING-BLOCK-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/anti_gaming.py", "orca/mission/cognitive_court.py"),
    )
    transition(
        "REQ-ANTIGAMING-BLOCK-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_anti_gaming.py", "tests/test_cognitive_court.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-159--anti-test-gaming--cognitive-court",
    )

    register(Requirement(
        id="REQ-COURT-ROLES-001",
        source_section="Phase 15.9 spec sections 15-22, 24-26",
        statement="Cognitive Court implements typed, risk-aware Constructor/Falsifier/"
                   "Security/Regression/Test/Performance critic roles as software "
                   "interfaces -- never bound to a specific model family, never named "
                   "'Aeternum'. A ModelProvider may contribute advisory narrative kept "
                   "structurally separate from each critic's deterministic conclusion; "
                   "provider absence or failure never yields a fake ACCEPT.",
        acceptance_criteria=(
            "A test confirms Constructor's conclusion is always NOT_REQUIRED (it does not "
            "approve its own work).",
            "A test confirms a MockProvider's narrative claiming ACCEPT does not change a "
            "critic's deterministic SUPPORTS_REJECT conclusion when real findings exist.",
            "A test confirms a failing/unavailable provider still produces a correct "
            "deterministic conclusion from real findings, never a default ACCEPT.",
        ),
    ))
    transition(
        "REQ-COURT-ROLES-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/cognitive_court.py",),
    )
    transition(
        "REQ-COURT-ROLES-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_cognitive_court.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-159--anti-test-gaming--cognitive-court",
    )

    register(Requirement(
        id="REQ-COURT-ARBITRATION-001",
        source_section="Phase 15.9 spec sections 16, 23, 27-28",
        statement="The Arbiter produces exactly one of ACCEPT/REJECT/NEED_MORE_EVIDENCE/"
                   "ESCALATE/HUMAN_APPROVAL_REQUIRED from deterministic inputs only "
                   "(findings, verification outcomes, critic conclusions); conflicting "
                   "critic conclusions at HIGH/CRITICAL risk escalate rather than average; "
                   "Court review is never authority -- an ACCEPT verdict grants no "
                   "deployment/migration/secret-access permission, and a real Phase 15.5 "
                   "authority approval does not force a Court ACCEPT.",
        acceptance_criteria=(
            "A test confirms disagreeing critics at HIGH risk produce ESCALATE, not an "
            "averaged verdict.",
            "A test confirms can_proceed_to_completed_verified() requires BOTH a Court "
            "ACCEPT verdict AND the Phase 15.8 verification gate to independently pass -- "
            "neither alone is sufficient.",
        ),
    ))
    transition(
        "REQ-COURT-ARBITRATION-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/cognitive_court.py", "orca/mission/court_mission_gate.py"),
    )
    transition(
        "REQ-COURT-ARBITRATION-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_cognitive_court.py", "tests/test_court_mission_gate.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-159--anti-test-gaming--cognitive-court",
    )

    register(Requirement(
        id="REQ-COURT-RISK-001",
        source_section="Phase 15.9 spec section 24",
        statement="A deterministic risk classifier (TRIVIAL/STANDARD/ELEVATED/HIGH/CRITICAL) "
                   "decides which Court roles are actually invoked, avoiding a full-Court "
                   "run for every trivial edit while guaranteeing full-Court invocation for "
                   "security-relevant or CRITICAL-finding candidates.",
        acceptance_criteria=(
            "A test confirms a docs-only change classifies as TRIVIAL and does not invoke "
            "the Security Critic.",
            "A test confirms a candidate with a CRITICAL anti-gaming finding classifies as "
            "CRITICAL risk and invokes the full role set including Security Critic and "
            "Falsifier.",
        ),
    ))
    transition(
        "REQ-COURT-RISK-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/cognitive_court.py",),
    )
    transition(
        "REQ-COURT-RISK-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_cognitive_court.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-159--anti-test-gaming--cognitive-court",
    )

    # -- Phase 15.10: Production Proof (spec sections 17-20) --
    # REQ-PROOF-NOINVENT-001 was already registered above (spec section
    # 18) but left UNIMPLEMENTED -- no generator existed yet. It is now
    # implemented and verified by the actual Production Proof engine.
    transition(
        "REQ-PROOF-NOINVENT-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/production_proof.py",),
    )
    transition(
        "REQ-PROOF-NOINVENT-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_production_proof.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1510--production-proof",
    )

    register(Requirement(
        id="REQ-PROOF-AUTHORITATIVE-001",
        source_section="Phase 15.10 spec sections 3, 5",
        statement="Production Proof requirement results are derived exclusively via the "
                   "Phase 15.9.4 authoritative mission-critical aggregator "
                   "(evaluate_requirement_completion_for_mission()) with an explicit, "
                   "non-empty RequiredVerificationScope per required requirement -- unknown "
                   "expected scope fails closed (a configuration error), never silently "
                   "inferred from the in-process AcceptanceCriterion registry or from "
                   "whichever records happen to exist.",
        acceptance_criteria=(
            "A test proves a required requirement with no explicit scope raises "
            "ProductionProofError rather than producing any proof.",
            "A test proves a stale-revision, cross-mission, or wrong-requirement "
            "VerificationRecord does not satisfy a requirement in the generated proof.",
            "A test proves a missing required criterion/category leaves the requirement "
            "unresolved, never PASS.",
        ),
    ))
    transition(
        "REQ-PROOF-AUTHORITATIVE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/production_proof.py",),
    )
    transition(
        "REQ-PROOF-AUTHORITATIVE-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_production_proof.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1510--production-proof",
    )

    register(Requirement(
        id="REQ-PROOF-DURABILITY-001",
        source_section="Phase 15.10 spec sections 27, 30-31",
        statement="Production Proof persists durably against the existing Phase 15.2 "
                   "production_proofs table, surviving a fresh connection/process "
                   "boundary with its hash, mission/revision binding, and evidence refs "
                   "unchanged; proof history is append-only (a later proof never "
                   "overwrites an earlier one), and a proof is revision-bound (stale-proof "
                   "detection rejects reuse for a different revision or changed scope).",
        acceptance_criteria=(
            "A live-Neon qualification writes a proof, closes the connection, opens a "
            "fresh connection, reloads the proof, and confirms the recomputed hash "
            "matches the hash stored at write time.",
            "A live-Neon qualification writes three proofs for the same mission across "
            "three revisions (blocked, ready, regressed) and confirms all three remain "
            "visible in chronological order with unmodified outcomes.",
            "A test proves is_proof_stale() returns True for a different revision or a "
            "changed RequiredVerificationScope, and False when both are unchanged.",
        ),
    ))
    transition(
        "REQ-PROOF-DURABILITY-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/production_proof_store.py",),
    )
    transition(
        "REQ-PROOF-DURABILITY-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_production_proof_store.py", "tests/test_production_proof_live_neon.py"),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1510--production-proof",
    )

    register(Requirement(
        id="REQ-PROOF-HASH-001",
        source_section="Phase 15.10 spec section 24",
        statement="Every Production Proof has a deterministic SHA-256 hash computed over "
                   "its canonical serialization; the identical canonical payload always "
                   "yields the identical hash, and any material mutation of the proof "
                   "changes the hash. The hash proves byte-identity/integrity of the "
                   "payload -- it does not itself prove the claims inside the proof are "
                   "true, and this distinction is stated wherever the hash is rendered.",
        acceptance_criteria=(
            "A test confirms two proofs built from the identical inputs produce the "
            "identical hash.",
            "A test confirms changing one real evidence input changes the hash.",
            "The human-readable renderer's hash line is accompanied by an explicit "
            "disclaimer that the hash does not prove the claims are true.",
        ),
    ))
    transition(
        "REQ-PROOF-HASH-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/production_proof.py",),
    )
    transition(
        "REQ-PROOF-HASH-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_production_proof.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1510--production-proof",
    )

    register(Requirement(
        id="REQ-PROOF-RELEASESTATE-001",
        source_section="Phase 15.10 spec section 22",
        statement="Production Proof derives release_state (ENGINEERING_READY / "
                   "SUBMISSION_READY / RELEASE_CANDIDATE / PUBLISHED) from a deterministic "
                   "policy over its own assembled category outcomes -- never from a "
                   "caller-supplied boolean -- and PUBLISHED requires explicit external "
                   "confirmation. A proof with unmet criteria still generates "
                   "successfully; it simply does not reach a higher release_state.",
        acceptance_criteria=(
            "A test proves a Court REJECT/ESCALATE/NEED_MORE_EVIDENCE verdict, a blocking "
            "anti-gaming finding, or a non-PASS build/unit_tests/security category each "
            "independently keep release_state at NOT_ENGINEERING_READY.",
            "A test proves release_state cannot skip a stage (e.g. RELEASE_CANDIDATE "
            "without SUBMISSION_READY first being satisfied).",
            "A test proves PUBLISHED is unreachable without published_externally_confirmed "
            "explicitly set.",
        ),
    ))
    transition(
        "REQ-PROOF-RELEASESTATE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/production_proof.py",),
    )
    transition(
        "REQ-PROOF-RELEASESTATE-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_production_proof.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1510--production-proof",
    )

    register(Requirement(
        id="REQ-SUPPLY-EVIDENCE-001",
        source_section="Phase 15.10 spec section 19",
        statement="Supply-chain and licensing evidence uses only tools genuinely available "
                   "in this environment (no paid scans, no external service dependency); "
                   "an unavailable check (vulnerability scanning, SBOM/provenance) is "
                   "UNVERIFIED, never PASS, and known debt (the mutable "
                   "CONTAINER_SANDBOX image tag) is surfaced explicitly rather than "
                   "omitted. Licensing evidence never asserts \"legally safe\" or "
                   "\"commercially cleared.\"",
        acceptance_criteria=(
            "A test confirms the supply-chain category never reports PASS given the "
            "absence of a vulnerability scanner.",
            "A test confirms the mutable python:3.11-slim image tag is named explicitly "
            "in the supply-chain evidence summary.",
            "A test confirms the licensing category's summary never contains the phrases "
            "'legally safe' or 'commercially cleared'.",
        ),
    ))
    transition(
        "REQ-SUPPLY-EVIDENCE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/supply_chain_evidence.py",),
    )
    transition(
        "REQ-SUPPLY-EVIDENCE-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_supply_chain_evidence.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1510--production-proof",
    )

    register(Requirement(
        id="REQ-DEPLOY-EVIDENCE-001",
        source_section="Phase 15.10 spec sections 19-21",
        statement="Deployment evidence is revision-bound (NOT_DEPLOYED by default, never "
                   "assumed) and rollback evidence distinguishes a documented strategy from "
                   "a tested procedure from proof the rollback actually works for the "
                   "CURRENT deployment -- a documented plan alone never counts as a tested "
                   "rollback, preserving Phase 14C.1's honest distinction that this "
                   "platform's proven rollback mechanism is git revert/redeploy-to-known-"
                   "good-commit, never labeled \"native rollback.\"",
        acceptance_criteria=(
            "A test confirms the default DeploymentResult is NOT_DEPLOYED.",
            "A test confirms a RollbackResult with strategy_documented=True and "
            "procedure_tested=False still reports proven_for_current_deployment=False.",
        ),
    ))
    transition(
        "REQ-DEPLOY-EVIDENCE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/production_proof.py",),
    )
    transition(
        "REQ-DEPLOY-EVIDENCE-001",
        RequirementStatus.VERIFIED,
        test_files=("tests/test_production_proof.py",),
        evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1510--production-proof",
    )


__all__ = ["seed_registry"]
