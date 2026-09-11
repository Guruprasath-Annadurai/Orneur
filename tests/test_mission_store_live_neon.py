"""
Phase 15.4 -- LIVE_NEON_TEMP_BRANCH integration tests for
orca.mission.mission_store.

These tests require ORNEUR_MISSION_DATABASE_URL and
ORNEUR_MISSION_DATABASE_URL_DIRECT to point at a real, disposable Neon
branch (never production -- spec section 1: "Do NOT use production as
the normal integration-test database"). They are skipped entirely
when those env vars are unset, so the rest of the suite (including CI
runs without Neon credentials) is unaffected.

This is deliberately NOT a mocked-Postgres test file -- every
assertion here is checked against a real, live Postgres database,
proving the actual CHECK/FK constraints, real transaction/rollback
behavior, and real row-lock concurrency semantics, not a simulation
of them. See docs/orneur/phase-15/PHASE15_EVIDENCE.md's Phase 15.4
checkpoint for the exact branch used and its disposal.
"""
from __future__ import annotations

import os
import uuid

import pytest

from orca.mission.db import apply_schema, get_conn
from orca.mission.mission_store import (
    Checkpoint,
    MissionNotFoundError,
    MissionStoreError,
    checkpoint_and_pause,
    create_checkpoint,
    create_mission,
    get_checkpoint,
    get_latest_checkpoint,
    get_mission,
    resume_mission,
    restore_mission,
    transition_mission,
)
from orca.mission.state_machine import MissionState, MissionStateError

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)


def _fresh_connection():
    """Returns a genuinely NEW psycopg connection -- used throughout
    this file every time a test wants to simulate 'a new process
    picked this mission back up', per spec section 6: 'The proof must
    construct NEW application/store objects after persistence... Do
    not qualify restart recovery by keeping the same Python object
    alive.'"""
    return get_conn(direct=False)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    """Applies the Phase 15.2 schema to the qualification branch once
    per test session -- idempotent (CREATE TABLE IF NOT EXISTS), safe
    to call even though the branch was already cloned from a schema-
    bearing parent."""
    conn = get_conn(direct=True)
    try:
        apply_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _mid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class TestMissionCRUD:
    def test_create_and_get_mission(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            created = create_mission(
                conn, id=mid, repository="github.com/example/repo", mode="BUILD",
                autonomy_level="L2", owner_user_id="user_test",
            )
            assert created["id"] == mid
            assert created["state"] == "DRAFT"

            fetched = get_mission(conn, mid)
            assert fetched == created
        finally:
            conn.close()

    def test_get_missing_mission_returns_none(self):
        conn = _fresh_connection()
        try:
            assert get_mission(conn, "mis_does_not_exist_xyz") is None
        finally:
            conn.close()


class TestTransitionPersistence:
    def test_legal_transition_persists(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            updated = transition_mission(conn, mid, MissionState.PLANNING)
            assert updated["state"] == "PLANNING"
            # re-read from a fresh connection to prove it's really durable, not cached
            conn2 = _fresh_connection()
            try:
                assert get_mission(conn2, mid)["state"] == "PLANNING"
            finally:
                conn2.close()
        finally:
            conn.close()

    def test_illegal_transition_rejected_and_state_unchanged(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            with pytest.raises(MissionStateError):
                transition_mission(conn, mid, MissionState.RUNNING)  # DRAFT -> RUNNING is illegal
            assert get_mission(conn, mid)["state"] == "DRAFT"  # unchanged
        finally:
            conn.close()

    def test_transition_on_missing_mission_raises(self):
        conn = _fresh_connection()
        try:
            with pytest.raises(MissionNotFoundError):
                transition_mission(conn, "mis_does_not_exist_xyz", MissionState.PLANNING)
        finally:
            conn.close()

    def test_completed_verified_without_evidence_rejected_live(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            transition_mission(conn, mid, MissionState.PLANNING)
            transition_mission(conn, mid, MissionState.READY)
            transition_mission(conn, mid, MissionState.RUNNING)
            transition_mission(conn, mid, MissionState.VERIFYING)
            with pytest.raises(MissionStateError):
                transition_mission(conn, mid, MissionState.COMPLETED_VERIFIED)  # no evidence_ref
            assert get_mission(conn, mid)["state"] == "VERIFYING"
        finally:
            conn.close()


class TestCheckpoints:
    def test_checkpoint_creation_and_field_population(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="github.com/example/repo", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            cid = _mid("ckpt")
            ckpt = create_checkpoint(
                conn,
                id=cid,
                mission_id=mid,
                mission_state=MissionState.DRAFT,
                repository="github.com/example/repo",
                current_step_id="step_2",
                completed_step_ids=("step_0", "step_1"),
                remaining_step_ids=("step_2", "step_3"),
                branch="main",
                base_revision="abc123",
                current_revision="def456",
                requirement_states={"REQ-X-001": "IMPLEMENTED"},
                evidence_refs=("workflow run 123",),
                pending_approvals=(),
                active_blocker=None,
                tool_outcomes=({"tool": "pytest", "status": "ok"},),
                environment_identity="github-actions-ubuntu-latest",
            )
            assert isinstance(ckpt, Checkpoint)
            assert ckpt.id == cid
            assert ckpt.mission_id == mid
            assert ckpt.completed_step_ids == ("step_0", "step_1")
            assert ckpt.remaining_step_ids == ("step_2", "step_3")
            assert ckpt.requirement_states == {"REQ-X-001": "IMPLEMENTED"}
            assert ckpt.active_blocker is None  # genuinely absent, not fabricated
            assert ckpt.tool_outcomes == ({"tool": "pytest", "status": "ok"},)
        finally:
            conn.close()

    def test_checkpoint_retrieval_by_id(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            cid = _mid("ckpt")
            create_checkpoint(conn, id=cid, mission_id=mid, mission_state=MissionState.DRAFT, repository="r")
            fetched = get_checkpoint(conn, cid)
            assert fetched is not None
            assert fetched.id == cid
        finally:
            conn.close()

    def test_missing_checkpoint_returns_none(self):
        conn = _fresh_connection()
        try:
            assert get_checkpoint(conn, "ckpt_does_not_exist_xyz") is None
        finally:
            conn.close()

    def test_latest_checkpoint_returns_most_recent(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            create_checkpoint(conn, id=_mid("ckpt"), mission_id=mid, mission_state=MissionState.DRAFT, repository="r")
            second_id = _mid("ckpt")
            create_checkpoint(conn, id=second_id, mission_id=mid, mission_state=MissionState.DRAFT, repository="r")
            latest = get_latest_checkpoint(conn, mid)
            assert latest.id == second_id
        finally:
            conn.close()


class TestFreshInstanceRestorationAndResume:
    """The core Phase 15.4 narrative (spec section 10, A-I): create,
    read from a fresh instance, transition, checkpoint atomically with
    a pause, discard everything, reconstruct fresh objects, restore,
    and resume through a legal transition -- with completed work
    preserved, not re-scheduled."""

    def test_full_pause_checkpoint_restore_resume_cycle(self):
        # A. CREATE
        conn_a = _fresh_connection()
        mid = _mid("mis")
        try:
            create_mission(conn_a, id=mid, repository="github.com/example/repo", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            transition_mission(conn_a, mid, MissionState.PLANNING)
            transition_mission(conn_a, mid, MissionState.READY)
            transition_mission(conn_a, mid, MissionState.RUNNING)
        finally:
            conn_a.close()

        # B. READ from a genuinely new store instance
        conn_b = _fresh_connection()
        try:
            reloaded = get_mission(conn_b, mid)
            assert reloaded["state"] == "RUNNING"
        finally:
            conn_b.close()

        # C+D. TRANSITION + CHECKPOINT, atomically, in one call
        conn_c = _fresh_connection()
        cid = _mid("ckpt")
        try:
            mission_after, checkpoint = checkpoint_and_pause(
                conn_c, mid,
                pause_state=MissionState.PAUSED_USER,
                checkpoint_id=cid,
                repository="github.com/example/repo",
                current_step_id="step_2",
                completed_step_ids=("step_0", "step_1"),
                remaining_step_ids=("step_2", "step_3"),
                branch="main",
            )
            assert mission_after["state"] == "PAUSED_USER"
            assert checkpoint.mission_state == "PAUSED_USER"
            assert checkpoint.completed_step_ids == ("step_0", "step_1")
            assert checkpoint.remaining_step_ids == ("step_2", "step_3")
        finally:
            conn_c.close()

        # E. PROCESS-STATE LOSS -- conn_a/conn_b/conn_c are already
        # closed and out of scope; nothing from them is referenced
        # below. No in-memory registry, no monkeypatched object.

        # F. RESTORE with fresh objects
        conn_d = _fresh_connection()
        try:
            restored_mission, restored_checkpoint = restore_mission(conn_d, mid)
            assert restored_mission["state"] == "PAUSED_USER"
            assert restored_checkpoint is not None
            assert restored_checkpoint.id == cid

            # H. COMPLETED-WORK PRESERVATION -- verify BEFORE resuming
            assert restored_checkpoint.completed_step_ids == ("step_0", "step_1")
            assert restored_checkpoint.remaining_step_ids == ("step_2", "step_3")
            assert "step_0" not in restored_checkpoint.remaining_step_ids
            assert "step_1" not in restored_checkpoint.remaining_step_ids

            # G. RESUME through the canonical state machine
            resumed = resume_mission(conn_d, mid)
            assert resumed["state"] == "RUNNING"
        finally:
            conn_d.close()

        # Confirm, from yet another fresh connection, that the resume
        # was truly durable.
        conn_e = _fresh_connection()
        try:
            final = get_mission(conn_e, mid)
            assert final["state"] == "RUNNING"
        finally:
            conn_e.close()

    def test_resume_from_paused_window_reached(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L3", owner_user_id="u")
            transition_mission(conn, mid, MissionState.PLANNING)
            transition_mission(conn, mid, MissionState.READY)
            transition_mission(conn, mid, MissionState.RUNNING)
            transition_mission(conn, mid, MissionState.PAUSED_WINDOW_REACHED)
            resumed = resume_mission(conn, mid)
            assert resumed["state"] == "RUNNING"
        finally:
            conn.close()

    def test_terminal_state_resume_rejected(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            transition_mission(conn, mid, MissionState.CANCELLED)
            with pytest.raises(MissionStoreError):
                resume_mission(conn, mid)
            assert get_mission(conn, mid)["state"] == "CANCELLED"  # unchanged by the rejected resume attempt
        finally:
            conn.close()

    def test_resume_missing_mission_raises(self):
        conn = _fresh_connection()
        try:
            with pytest.raises(MissionNotFoundError):
                resume_mission(conn, "mis_does_not_exist_xyz")
        finally:
            conn.close()

    def test_restore_missing_mission_raises(self):
        conn = _fresh_connection()
        try:
            with pytest.raises(MissionNotFoundError):
                restore_mission(conn, "mis_does_not_exist_xyz")
        finally:
            conn.close()

    def test_restore_mission_with_no_checkpoint_yet(self):
        """A freshly-created mission that was never paused/
        checkpointed is a legitimate state, not an error."""
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="ASSIST", autonomy_level="L1", owner_user_id="u")
            mission, checkpoint = restore_mission(conn, mid)
            assert mission["state"] == "DRAFT"
            assert checkpoint is None
        finally:
            conn.close()


class TestAtomicity:
    def test_checkpoint_and_pause_rolls_back_together_on_failure(self):
        """If the checkpoint write fails, the mission must NOT be left
        committed as paused with no checkpoint (spec section 5)."""
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            transition_mission(conn, mid, MissionState.PLANNING)
            transition_mission(conn, mid, MissionState.READY)
            transition_mission(conn, mid, MissionState.RUNNING)

            # Force the checkpoint write to fail: reuse an id that already
            # exists (PRIMARY KEY violation) to simulate a failure mid-transaction.
            existing_cid = _mid("ckpt")
            create_checkpoint(conn, id=existing_cid, mission_id=mid, mission_state=MissionState.RUNNING, repository="r")

            with pytest.raises(Exception):
                checkpoint_and_pause(
                    conn, mid,
                    pause_state=MissionState.PAUSED_USER,
                    checkpoint_id=existing_cid,  # duplicate -- will violate the PK constraint
                    repository="r",
                )

            # The mission's state transition must have been rolled back
            # together with the failed checkpoint write -- still RUNNING,
            # NOT PAUSED_USER.
            assert get_mission(conn, mid)["state"] == "RUNNING"
        finally:
            conn.close()

    def test_illegal_pause_state_rejected_before_any_write(self):
        conn = _fresh_connection()
        try:
            mid = _mid("mis")
            create_mission(conn, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            with pytest.raises(MissionStoreError):
                checkpoint_and_pause(
                    conn, mid,
                    pause_state=MissionState.RUNNING,  # not a pause state
                    checkpoint_id=_mid("ckpt"),
                    repository="r",
                )
            assert get_mission(conn, mid)["state"] == "DRAFT"
        finally:
            conn.close()


class TestConcurrency:
    def test_for_update_lock_serializes_concurrent_transitions(self):
        """Two connections attempt to transition the SAME mission at
        once. The FOR UPDATE lock must serialize them -- the second
        transaction blocks until the first commits, then operates on
        the ALREADY-UPDATED state, never on stale data (which is
        exactly what prevents a silent lost update)."""
        import threading

        conn_setup = _fresh_connection()
        mid = _mid("mis")
        try:
            create_mission(conn_setup, id=mid, repository="r", mode="BUILD", autonomy_level="L2", owner_user_id="u")
            transition_mission(conn_setup, mid, MissionState.PLANNING)
            transition_mission(conn_setup, mid, MissionState.READY)
            transition_mission(conn_setup, mid, MissionState.RUNNING)
        finally:
            conn_setup.close()

        results: dict[str, object] = {}

        def _try_pause():
            conn = _fresh_connection()
            try:
                results["pause"] = transition_mission(conn, mid, MissionState.PAUSED_USER)
            except Exception as e:  # noqa: BLE001
                results["pause_error"] = e
            finally:
                conn.close()

        def _try_block():
            conn = _fresh_connection()
            try:
                results["block"] = transition_mission(conn, mid, MissionState.BLOCKED)
            except Exception as e:  # noqa: BLE001
                results["block_error"] = e
            finally:
                conn.close()

        t1 = threading.Thread(target=_try_pause)
        t2 = threading.Thread(target=_try_block)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        # Exactly one of the two RUNNING -> {PAUSED_USER, BLOCKED}
        # transitions can have actually applied to RUNNING (both are
        # legal FROM RUNNING, but only one can win since the second
        # transaction's FOR UPDATE wait means it re-reads AFTER the
        # first committed -- landing on a state where its OWN target
        # transition may now be illegal, e.g. PAUSED_USER -> BLOCKED
        # is not a legal transition). At least one must have succeeded;
        # if both "succeeded" they cannot have produced two different
        # final states for the same row.
        conn_check = _fresh_connection()
        try:
            final_state = get_mission(conn_check, mid)["state"]
        finally:
            conn_check.close()
        assert final_state in ("PAUSED_USER", "BLOCKED"), f"unexpected final state: {final_state}"
        # No silent lost update: exactly one of the two threads
        # reached the final persisted state; the other either errored
        # (illegal transition once serialized after the winner) or
        # also reports that same final state (never a THIRD, wrong state).
        applied_states = {
            v["state"] for k, v in results.items() if k in ("pause", "block") and isinstance(v, dict)
        }
        assert applied_states.issubset({final_state}), (
            f"lost update detected -- multiple different states were reported as applied: {applied_states}"
        )


# ── REQ-AUTONOMY-LEVELS-001 (Phase 15.15): DURABLE-layer L5 rejection ──

def test_autonomy_level_l5_is_rejected_by_the_durable_check_constraint():
    """The app-level boundedness proof (schema SQL text, mission_window's
    L3/L4-only autonomous set) lives in tests/test_mission_state_
    machine.py -- this proves the SAME guarantee holds at the DURABLE
    layer: Postgres itself, not merely application code, refuses an
    'L5' autonomy_level."""
    conn = _fresh_connection()
    try:
        mid = _mid("mis_l5")
        with pytest.raises(Exception) as exc_info:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO missions
                        (id, repository, mode, autonomy_level, state, owner_user_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now()::text, now()::text)
                    """,
                    (mid, "org/l5-qual", "BUILD", "L5", "DRAFT", "user_l5_qual"),
                )
        conn.rollback()
        assert "check" in str(exc_info.value).lower() or "constraint" in str(exc_info.value).lower()

        # And a legal level (L4) DOES insert cleanly on a fresh transaction.
        legal_mid = _mid("mis_l4")
        create_mission(
            conn, id=legal_mid, repository="org/l5-qual", mode="BUILD",
            autonomy_level="L4", owner_user_id="user_l5_qual",
        )
        assert get_mission(conn, legal_mid)["autonomy_level"] == "L4"
    finally:
        conn.close()

