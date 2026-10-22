"""
Phase 15.4 -- durable Mission Repository / Checkpoint store.

Follows this project's own established Postgres pattern (see
orca/godmode/lease_store.py, orca/godmode/durable_audit.py):
`SELECT ... FOR UPDATE` inside an explicit transaction for read-
modify-write atomicity, `%s` psycopg placeholders, explicit
commit()/rollback(), no ORM.

Concurrency: a mission row is locked with `SELECT ... FOR UPDATE`
before any state transition is computed or applied. Since the lock is
held for the lifetime of the transaction, a second concurrent
transition on the SAME mission blocks until the first commits (or
rolls back), then re-reads the now-current state -- this makes lost
updates structurally impossible without needing an additive version/
revision column (spec section 3: "determine whether Phase 15.4
genuinely requires an additive optimistic-concurrency field or
whether row-level transactional locking is already sufficient for
this scope" -- it is). `_write_transition()` still asserts the
locked row's state matches what was just read, purely as a defensive
sanity check against a future refactor that accidentally reads
outside the lock -- not as the primary concurrency mechanism.

Every durable state change goes through
`orca.mission.state_machine.transition()` -- there is no code path in
this module that writes a `state` value to the `missions` table
without it having passed that validation first (spec section 2: "a DB
write must not provide an alternate route around transition()").
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from orca.mission.state_machine import MissionState, MissionStateError, transition

_RESUMABLE_STATES = frozenset({MissionState.PAUSED_USER, MissionState.PAUSED_WINDOW_REACHED})


class MissionStoreError(Exception):
    """Base class for mission-store errors."""


class MissionNotFoundError(MissionStoreError):
    pass


class CheckpointNotFoundError(MissionStoreError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Checkpoint:
    id: str
    mission_id: str
    created_at: str
    mission_state: str
    current_step_id: str | None
    completed_step_ids: tuple[str, ...]
    remaining_step_ids: tuple[str, ...]
    repository: str
    branch: str | None
    base_revision: str | None
    current_revision: str | None
    diff_ref: str | None
    requirement_states: dict
    test_states: dict
    verification_states: dict
    evidence_refs: tuple[str, ...]
    pending_approvals: tuple[str, ...]
    active_blocker: str | None
    resource_budget_state: dict | None
    tool_outcomes: tuple[dict, ...]
    environment_identity: str | None

    @classmethod
    def from_row(cls, row: dict) -> "Checkpoint":
        return cls(
            id=row["id"],
            mission_id=row["mission_id"],
            created_at=row["created_at"],
            mission_state=row["mission_state"],
            current_step_id=row["current_step_id"],
            completed_step_ids=tuple(json.loads(row["completed_step_ids"])),
            remaining_step_ids=tuple(json.loads(row["remaining_step_ids"])),
            repository=row["repository"],
            branch=row["branch"],
            base_revision=row["base_revision"],
            current_revision=row["current_revision"],
            diff_ref=row["diff_ref"],
            requirement_states=json.loads(row["requirement_states"]),
            test_states=json.loads(row["test_states"]),
            verification_states=json.loads(row["verification_states"]),
            evidence_refs=tuple(json.loads(row["evidence_refs"])),
            pending_approvals=tuple(json.loads(row["pending_approvals"])),
            active_blocker=row["active_blocker"],
            resource_budget_state=json.loads(row["resource_budget_state"]) if row["resource_budget_state"] else None,
            tool_outcomes=tuple(json.loads(row["tool_outcomes"])),
            environment_identity=row["environment_identity"],
        )


# ─────────────────────────────────────────────────────────────────
#  Mission CRUD
# ─────────────────────────────────────────────────────────────────

def create_mission(
    conn,
    *,
    id: str,
    repository: str,
    mode: str,
    autonomy_level: str,
    owner_user_id: str,
    state: MissionState = MissionState.DRAFT,
    workspace_id: str | None = None,
    branch: str | None = None,
    base_revision: str | None = None,
    current_revision: str | None = None,
    window_started_at: str | None = None,
    window_deadline_at: str | None = None,
) -> dict:
    """Inserts a new mission row. `state` defaults to DRAFT (the only
    state a mission may legitimately start in -- every other state is
    reached only via transition())."""
    now = _now_iso()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO missions
                (id, workspace_id, repository, branch, base_revision, current_revision,
                 mode, autonomy_level, state, owner_user_id, window_started_at,
                 window_deadline_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (id, workspace_id, repository, branch, base_revision, current_revision,
             mode, autonomy_level, state.value, owner_user_id, window_started_at,
             window_deadline_at, now, now),
        )
    conn.commit()
    return get_mission(conn, id)  # type: ignore[return-value]


def create_mission_steps(conn, mission_id: str, step_descriptions: list[str]) -> tuple[dict, ...]:
    """AUDIT-C02-P1-01 ("planning truth"): persists a real, validated
    plan -- one row per step in `mission_steps`, PENDING, in the given
    order -- rather than allowing a mission to reach READY with no
    plan content at all. Raises `ValueError` for an empty step list;
    callers (see `orca.serve.mission_api.plan_mission`) must not call
    this with no real content and must not transition to READY if it
    is never called."""
    if not step_descriptions:
        raise ValueError("step_descriptions must be non-empty -- a mission cannot be planned with zero steps")
    now = _now_iso()
    rows = []
    with conn.cursor() as cur:
        for index, description in enumerate(step_descriptions):
            step_id = f"step_{mission_id}_{index}"
            cur.execute(
                """
                INSERT INTO mission_steps (id, mission_id, step_index, description, status, created_at)
                VALUES (%s, %s, %s, %s, 'PENDING', %s)
                """,
                (step_id, mission_id, index, description, now),
            )
            rows.append({"id": step_id, "mission_id": mission_id, "step_index": index,
                         "description": description, "status": "PENDING", "created_at": now})
    conn.commit()
    return tuple(rows)


def list_mission_steps(conn, mission_id: str) -> tuple[dict, ...]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM mission_steps WHERE mission_id = %s ORDER BY step_index ASC",
            (mission_id,),
        )
        rows = cur.fetchall()
    conn.commit()
    return tuple(dict(r) for r in rows)


def get_mission(conn, mission_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM missions WHERE id = %s", (mission_id,))
        row = cur.fetchone()
    conn.commit()
    return dict(row) if row else None


def _write_transition(conn, mission_id: str, new_state: MissionState, *, evidence_ref: str | None) -> MissionState:
    """The one function in this module that ever writes `missions.state`.
    Locks the row, validates the transition against the canonical
    state machine, writes. Deliberately does NOT commit -- callers
    control the transaction boundary, so this can be composed with
    other writes (see checkpoint_and_pause()) inside a single atomic
    transaction, not just called standalone. Raises
    MissionNotFoundError or MissionStateError (from
    orca.mission.state_machine) without committing or rolling back --
    the caller is responsible for both (see transition_mission() and
    checkpoint_and_pause() below, matching the try/except pattern
    already used in orca/godmode/lease_store.py)."""
    with conn.cursor() as cur:
        cur.execute("SELECT state FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
        row = cur.fetchone()
        if row is None:
            raise MissionNotFoundError(f"No such mission: {mission_id}")

        current = MissionState(row["state"])
        validated_new = transition(current, new_state, evidence_ref=evidence_ref)  # raises MissionStateError if illegal

        now = _now_iso()
        cur.execute(
            "UPDATE missions SET state = %s, updated_at = %s WHERE id = %s AND state = %s",
            (validated_new.value, now, mission_id, current.value),
        )
        if cur.rowcount != 1:
            # Structurally should be unreachable while holding the FOR
            # UPDATE lock for the whole transaction -- a defensive
            # assertion, not the primary concurrency mechanism (see
            # module docstring).
            raise MissionStoreError(
                f"Mission {mission_id} state changed unexpectedly during transition "
                f"(expected {current.value}); this indicates the row lock was not held "
                f"for the full transaction."
            )
    return validated_new


def request_mission_cancellation(conn, mission_id: str) -> dict:
    """AUDIT-C02-P0-03 follow-up correction: entering
    CANCELLATION_REQUESTED mints a fresh, server-generated,
    unguessable `cancellation_episode_id` (never client-supplied) and
    captures the mission's own `current_revision` at this exact
    moment -- both in the SAME row-locked transaction as the state
    write, so there is no window where a stale or mismatched
    confirmation could apply. `resolve_mission_cancellation()` below
    is the only function that may consume this episode; a confirmation
    presenting an old episode id (from an earlier cancellation
    request on this same mission) is rejected as stale, not reused."""
    import secrets

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise MissionNotFoundError(f"No such mission: {mission_id}")

        current = MissionState(row["state"])
        validated_new = transition(current, MissionState.CANCELLATION_REQUESTED)  # raises MissionStateError if illegal

        episode_id = f"cancep_{secrets.token_hex(16)}"
        now = _now_iso()
        cur.execute(
            """
            UPDATE missions
            SET state = %s, cancellation_episode_id = %s, cancellation_episode_revision = %s, updated_at = %s
            WHERE id = %s AND state = %s
            """,
            (validated_new.value, episode_id, row["current_revision"], now, mission_id, current.value),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise MissionStoreError(
                f"Mission {mission_id} state changed unexpectedly during cancellation request "
                f"(expected {current.value})."
            )
    conn.commit()
    return get_mission(conn, mission_id)  # type: ignore[return-value]


class CancellationEvidenceError(MissionStoreError):
    """Raised by `resolve_mission_cancellation()` when the presented
    `cancellation_episode_id` does not match the mission's current,
    live episode -- a forged, stale (from an earlier episode), or
    wrong-mission confirmation attempt. Never silently accepted."""


def resolve_mission_cancellation(
    conn, mission_id: str, *, cancellation_episode_id: str,
    expected_cancellation_episode_revision: str | None, outcome: str,
) -> dict:
    """The ONLY function that may move a mission OUT of
    CANCELLATION_REQUESTED / CANCELLATION_UNRESOLVED. Requires the
    CURRENT, server-minted `cancellation_episode_id` for this exact
    mission -- a mismatch (forged, stale from an earlier episode, or
    copied from a different mission) raises `CancellationEvidenceError`
    and changes nothing.

    AUDIT-B79-B-P0-02: `cancellation_episode_revision` was captured by
    request_mission_cancellation() (the mission's `current_revision` at
    the moment the episode was minted) but never actually enforced here
    -- a confirmation only had to present the right episode id, never
    the right revision. `current_revision` is not writable by any
    existing code path while a mission sits in CANCELLATION_REQUESTED
    today, so this could not yet be exploited in practice, but a
    captured-and-never-checked field is exactly the kind of latent gap
    that becomes exploitable the moment a future code path DOES touch
    current_revision mid-episode. The caller must now present the
    EXACT revision this episode was opened against; a mismatch is
    treated identically to an episode-id mismatch -- rejected, nothing
    changed. `outcome` must be one of:

      'TERMINATED'    -> CANCELLED (worker independently confirmed stopped)
      'STILL_RUNNING' -> stays in CANCELLATION_REQUESTED, with a FRESH
                         episode id (the old one is retired, so a
                         stale confirmation describing the OLD attempt
                         can never be replayed against the new one)
      'UNRESOLVED'    -> CANCELLATION_UNRESOLVED (never silently
                         folded into FAILED or CANCELLED -- see
                         orca.mission.state_machine's own docstring)

    This function does not itself determine which outcome is true --
    that determination is the caller's (a real reconciliation
    process's) responsibility; see
    orca.serve.mission_api._require_reconciliation_principal() for who
    is actually allowed to call this."""
    import secrets

    if outcome not in ("TERMINATED", "STILL_RUNNING", "UNRESOLVED"):
        raise ValueError(f"unknown outcome: {outcome!r}")

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise MissionNotFoundError(f"No such mission: {mission_id}")

        current = MissionState(row["state"])
        if current not in (MissionState.CANCELLATION_REQUESTED, MissionState.CANCELLATION_UNRESOLVED):
            conn.rollback()
            raise MissionStateError(
                f"cannot resolve cancellation for mission {mission_id} in state {current.value} -- "
                f"only CANCELLATION_REQUESTED/CANCELLATION_UNRESOLVED missions have an active episode to resolve."
            )
        live_episode = row["cancellation_episode_id"]
        if not live_episode or cancellation_episode_id != live_episode:
            conn.rollback()
            raise CancellationEvidenceError(
                f"cancellation_episode_id does not match mission {mission_id}'s current, live cancellation "
                f"episode -- this is either a forged confirmation, a stale one from an earlier cancellation "
                f"attempt on this mission, or copied from a different mission. Refusing to change anything."
            )
        live_revision = row["cancellation_episode_revision"]
        if expected_cancellation_episode_revision != live_revision:
            conn.rollback()
            raise CancellationEvidenceError(
                f"cancellation_episode_revision does not match mission {mission_id}'s live cancellation "
                f"episode (expected {live_revision!r}, confirmation presented "
                f"{expected_cancellation_episode_revision!r}) -- refusing to change anything."
            )

        now = _now_iso()
        if outcome == "TERMINATED":
            target = MissionState.CANCELLED
            new_episode_id = None
            new_episode_revision = None
        elif outcome == "UNRESOLVED":
            target = MissionState.CANCELLATION_UNRESOLVED
            new_episode_id = live_episode  # same episode remains open until genuinely resolved
            new_episode_revision = live_revision  # unchanged -- same open episode
        else:  # STILL_RUNNING
            target = MissionState.CANCELLATION_REQUESTED
            new_episode_id = f"cancep_{secrets.token_hex(16)}"  # retire the old episode, mint a fresh one
            # AUDIT-B79-B-P0-02: re-snapshot current_revision for the
            # FRESH episode, exactly like request_mission_cancellation()
            # does for the first one -- a confirmation against this new
            # episode must present the revision pinned at the moment
            # THIS retry began, not the one from the episode just retired.
            new_episode_revision = row["current_revision"]

        validated_new = transition(current, target)  # raises MissionStateError if illegal
        cur.execute(
            """
            UPDATE missions
            SET state = %s, cancellation_episode_id = %s, cancellation_episode_revision = %s, updated_at = %s
            WHERE id = %s AND state = %s
            """,
            (validated_new.value, new_episode_id, new_episode_revision, now, mission_id, current.value),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise MissionStoreError(
                f"Mission {mission_id} state changed unexpectedly while resolving cancellation "
                f"(expected {current.value})."
            )
    conn.commit()
    return get_mission(conn, mission_id)  # type: ignore[return-value]


def transition_mission(conn, mission_id: str, new_state: MissionState, *, evidence_ref: str | None = None) -> dict:
    """Public entrypoint for a single, standalone legal state
    transition (its own complete transaction: commits on success,
    rolls back and re-raises on any error, leaving the mission's
    persisted state unchanged)."""
    try:
        _write_transition(conn, mission_id, new_state, evidence_ref=evidence_ref)
    except (MissionStoreError, MissionStateError):
        conn.rollback()
        raise
    conn.commit()
    return get_mission(conn, mission_id)  # type: ignore[return-value]


def resume_mission(conn, mission_id: str, *, evidence_ref: str | None = None) -> dict:
    """Resumes a paused mission (PAUSED_USER or PAUSED_WINDOW_REACHED)
    back to RUNNING via the canonical state machine -- never by
    directly mutating the persisted state string. Rejects resume from
    any other state, including terminal ones, with a clear error."""
    mission = get_mission(conn, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")

    current = MissionState(mission["state"])
    if current not in _RESUMABLE_STATES:
        raise MissionStoreError(
            f"Mission {mission_id} is in state {current.value}, which is not resumable "
            f"(only {sorted(s.value for s in _RESUMABLE_STATES)} are)."
        )
    return transition_mission(conn, mission_id, MissionState.RUNNING, evidence_ref=evidence_ref)


def _apply_mutation_with_precondition_locked(
    cur, mission_id: str, *,
    expected_state: MissionState | None,
    expected_revision: str | None,
    new_state: MissionState,
    evidence_ref: str | None = None,
    require_revision_if_present: bool = False,
) -> tuple[str, dict, str]:
    """Phase 15.13.2 -- the TRANSACTION-COMPOSABLE core: operates on an
    ALREADY-OPEN cursor inside the CALLER's transaction. Never commits
    or rolls back -- so a caller that ALSO needs to lock/validate other
    durable state first (e.g. a Relay session/device row -- see
    `orca.mission.relay_security.require_security_valid_session_locked()`)
    can compose this into ONE larger atomic transaction with a single
    final commit, rather than this function committing independently
    and leaving a window between an earlier validation and this write.

    Locks the mission row `FOR UPDATE`, evaluates the caller's
    `expected_state`/`expected_revision` against that SAME locked
    read, and -- only if eligible -- performs the `state_machine`-
    validated transition in the SAME transaction.

    Returns `(outcome, mission_row, detail)` where `outcome` is one of
    `"APPLIED"`, `"STALE_CONFLICT"`, `"DENIED"`:

      * Already at `new_state` (a racing, identical, later request):
        `"APPLIED"`, idempotent no-op, no redundant write -- `detail`
        explicitly says no precondition (state or revision) was
        validated, so this can never be misread as "the caller's
        revision was confirmed current."
      * `require_revision_if_present=True` and the durable row has a
        non-empty `current_revision` but the caller supplied none (or
        an empty string): `"STALE_CONFLICT"` -- optimistic concurrency
        cannot be bypassed by omitting the revision. Skipped entirely
        when the durable revision is genuinely absent (nothing to
        compare against, never fabricated).
      * `expected_state`/`expected_revision` (when supplied) do not
        match the LOCKED, actual, current row: `"STALE_CONFLICT"`.
      * A `new_state` of RUNNING is only reachable from the same
        `_RESUMABLE_STATES` set `resume_mission()` itself enforces
        (PAUSED_USER, PAUSED_WINDOW_REACHED) -- preserved here so this
        atomic primitive does not silently widen what "resume" means
        relative to the pre-existing behavior; anything else is
        `"DENIED"`.
      * Any other illegal transition per the canonical state machine:
        `"DENIED"`.

    Raises `MissionNotFoundError` if the mission does not exist, or
    `MissionStoreError` if the row changed unexpectedly under the
    lock -- the caller is responsible for rollback (see
    `apply_mutation_with_precondition()` below for the standalone,
    committing wrapper's defensive `except Exception` handling)."""
    cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
    row = cur.fetchone()
    if row is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")
    mission_row = dict(row)
    actual_state = MissionState(mission_row["state"])
    actual_revision = mission_row.get("current_revision")

    if actual_state is new_state:
        return "APPLIED", mission_row, (
            "IDEMPOTENT_NO_OP: mission already durably at the requested target state -- "
            "no write was performed, and no precondition (state or revision) was validated "
            "against this specific request"
        )

    if require_revision_if_present and actual_revision and not expected_revision:
        return "STALE_CONFLICT", mission_row, (
            f"durable mission has current_revision={actual_revision!r} but the caller supplied "
            f"no expected_revision -- optimistic concurrency cannot be bypassed by omitting it"
        )

    if expected_state is not None and actual_state is not expected_state:
        return "STALE_CONFLICT", mission_row, (
            f"caller expected state {expected_state.value!r}, mission is actually {actual_state.value!r}"
        )
    if expected_revision is not None and actual_revision != expected_revision:
        return "STALE_CONFLICT", mission_row, (
            f"caller expected revision {expected_revision!r}, mission is actually at {actual_revision!r}"
        )

    if new_state is MissionState.RUNNING and actual_state not in _RESUMABLE_STATES:
        return "DENIED", mission_row, (
            f"RUNNING is only reachable from {sorted(s.value for s in _RESUMABLE_STATES)} "
            f"via this primitive; mission is actually {actual_state.value!r}"
        )

    try:
        validated_new = transition(actual_state, new_state, evidence_ref=evidence_ref)
    except MissionStateError as e:
        return "DENIED", mission_row, str(e)

    now = _now_iso()
    cur.execute(
        "UPDATE missions SET state = %s, updated_at = %s WHERE id = %s AND state = %s",
        (validated_new.value, now, mission_id, actual_state.value),
    )
    if cur.rowcount != 1:
        raise MissionStoreError(
            f"Mission {mission_id} state changed unexpectedly during atomic mutation "
            f"(expected {actual_state.value}); the row lock was not held for the full transaction."
        )
    mission_row = dict(mission_row)
    mission_row["state"] = validated_new.value
    mission_row["updated_at"] = now
    return "APPLIED", mission_row, "mutation applied atomically under a single locked row read"


def apply_mutation_with_precondition(
    conn, mission_id: str, *,
    expected_state: MissionState | None,
    expected_revision: str | None,
    new_state: MissionState,
    evidence_ref: str | None = None,
    require_revision_if_present: bool = False,
) -> tuple[str, dict, str]:
    """Phase 15.13.1/15.13.2 -- the standalone, committing entrypoint:
    opens its own single transaction around `_apply_mutation_with_
    precondition_locked()` above and commits once. Any exception --
    expected (`MissionNotFoundError`, `MissionStoreError`) or
    genuinely unexpected (a raw database error, etc.) -- rolls back
    before propagating (Phase 15.13.2 item 5: every exit path must
    release the row lock; no exception type is swallowed)."""
    try:
        with conn.cursor() as cur:
            outcome, mission_row, detail = _apply_mutation_with_precondition_locked(
                cur, mission_id,
                expected_state=expected_state, expected_revision=expected_revision,
                new_state=new_state, evidence_ref=evidence_ref,
                require_revision_if_present=require_revision_if_present,
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return outcome, mission_row, detail


# ─────────────────────────────────────────────────────────────────
#  Checkpoints
# ─────────────────────────────────────────────────────────────────

def create_checkpoint(
    conn,
    *,
    id: str,
    mission_id: str,
    mission_state: MissionState,
    repository: str,
    current_step_id: str | None = None,
    completed_step_ids: tuple[str, ...] = (),
    remaining_step_ids: tuple[str, ...] = (),
    branch: str | None = None,
    base_revision: str | None = None,
    current_revision: str | None = None,
    diff_ref: str | None = None,
    requirement_states: dict | None = None,
    test_states: dict | None = None,
    verification_states: dict | None = None,
    evidence_refs: tuple[str, ...] = (),
    pending_approvals: tuple[str, ...] = (),
    active_blocker: str | None = None,
    resource_budget_state: dict | None = None,
    tool_outcomes: tuple[dict, ...] = (),
    environment_identity: str | None = None,
) -> Checkpoint:
    """Writes a checkpoint row from REAL caller-supplied data only --
    every field defaults to the schema's own empty representation
    ('[]', '{}', or NULL) when genuinely absent, never a fabricated
    placeholder value (spec section 4: 'do not insert fake values
    merely to populate every nullable field')."""
    now = _now_iso()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO checkpoints
                (id, mission_id, created_at, mission_state, current_step_id,
                 completed_step_ids, remaining_step_ids, repository, branch,
                 base_revision, current_revision, diff_ref, requirement_states,
                 test_states, verification_states, evidence_refs, pending_approvals,
                 active_blocker, resource_budget_state, tool_outcomes, environment_identity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                id, mission_id, now, mission_state.value, current_step_id,
                json.dumps(list(completed_step_ids)), json.dumps(list(remaining_step_ids)),
                repository, branch, base_revision, current_revision, diff_ref,
                json.dumps(requirement_states or {}), json.dumps(test_states or {}),
                json.dumps(verification_states or {}), json.dumps(list(evidence_refs)),
                json.dumps(list(pending_approvals)), active_blocker,
                json.dumps(resource_budget_state) if resource_budget_state is not None else None,
                json.dumps(list(tool_outcomes)), environment_identity,
            ),
        )
    conn.commit()
    return get_checkpoint(conn, id)  # type: ignore[return-value]


def get_checkpoint(conn, checkpoint_id: str) -> Checkpoint | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM checkpoints WHERE id = %s", (checkpoint_id,))
        row = cur.fetchone()
    conn.commit()
    return Checkpoint.from_row(dict(row)) if row else None


def get_latest_checkpoint(conn, mission_id: str) -> Checkpoint | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM checkpoints WHERE mission_id = %s ORDER BY created_at DESC LIMIT 1",
            (mission_id,),
        )
        row = cur.fetchone()
    conn.commit()
    return Checkpoint.from_row(dict(row)) if row else None


def checkpoint_and_pause(
    conn,
    mission_id: str,
    *,
    pause_state: MissionState,
    checkpoint_id: str,
    **checkpoint_kwargs,
) -> tuple[dict, Checkpoint]:
    """Atomically transitions a mission to a paused state AND writes
    its checkpoint in the SAME database transaction (spec section 5:
    a paused mission must never be committed without the checkpoint
    that makes it resumable, or vice versa). Either both writes
    succeed, or neither does -- proven by a rollback test, see
    tests/test_mission_store.py."""
    if pause_state not in (MissionState.PAUSED_USER, MissionState.PAUSED_WINDOW_REACHED):
        raise MissionStoreError(f"checkpoint_and_pause requires a pause state, got {pause_state.value}")

    try:
        validated_state = _write_transition(conn, mission_id, pause_state, evidence_ref=None)
        # _write_transition() does NOT commit (unlike transition_mission()) --
        # both writes below share this one open transaction, committed
        # exactly once at the end. This is what actually makes the
        # pause + checkpoint atomic (see the dedicated rollback test).
        now = _now_iso()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO checkpoints
                    (id, mission_id, created_at, mission_state, current_step_id,
                     completed_step_ids, remaining_step_ids, repository, branch,
                     base_revision, current_revision, diff_ref, requirement_states,
                     test_states, verification_states, evidence_refs, pending_approvals,
                     active_blocker, resource_budget_state, tool_outcomes, environment_identity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    checkpoint_id, mission_id, now, pause_state.value,
                    checkpoint_kwargs.get("current_step_id"),
                    json.dumps(list(checkpoint_kwargs.get("completed_step_ids", ()))),
                    json.dumps(list(checkpoint_kwargs.get("remaining_step_ids", ()))),
                    checkpoint_kwargs["repository"],
                    checkpoint_kwargs.get("branch"),
                    checkpoint_kwargs.get("base_revision"),
                    checkpoint_kwargs.get("current_revision"),
                    checkpoint_kwargs.get("diff_ref"),
                    json.dumps(checkpoint_kwargs.get("requirement_states") or {}),
                    json.dumps(checkpoint_kwargs.get("test_states") or {}),
                    json.dumps(checkpoint_kwargs.get("verification_states") or {}),
                    json.dumps(list(checkpoint_kwargs.get("evidence_refs", ()))),
                    json.dumps(list(checkpoint_kwargs.get("pending_approvals", ()))),
                    checkpoint_kwargs.get("active_blocker"),
                    json.dumps(checkpoint_kwargs["resource_budget_state"]) if checkpoint_kwargs.get("resource_budget_state") is not None else None,
                    json.dumps(list(checkpoint_kwargs.get("tool_outcomes", ()))),
                    checkpoint_kwargs.get("environment_identity"),
                ),
            )
    except Exception:
        conn.rollback()
        raise

    conn.commit()
    mission = get_mission(conn, mission_id)
    checkpoint = get_checkpoint(conn, checkpoint_id)
    assert mission is not None and checkpoint is not None
    assert mission["state"] == validated_state.value
    return mission, checkpoint


def restore_mission(conn, mission_id: str) -> tuple[dict, Checkpoint | None]:
    """The Phase 15.4 'restore' entrypoint (spec section 6): loads a
    mission and its latest checkpoint (if any) fresh from durable
    storage. Callers use this after constructing a brand-new
    connection/process (simulating real process-state loss) -- it
    never reads from any in-memory cache. Raises MissionNotFoundError
    if the mission itself doesn't exist; a mission with no checkpoint
    yet returns (mission, None), which is a legitimate state (e.g. a
    freshly-created DRAFT mission that was never paused/checkpointed),
    not an error."""
    mission = get_mission(conn, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")
    checkpoint = get_latest_checkpoint(conn, mission_id)
    return mission, checkpoint
