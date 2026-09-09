"""
Phase 15.11 -- UNIT tests for orca.mission.relay_store (no database
required): session-status derivation with an injected clock, device/
session row parsing, and the recursive secret-redaction walk over a
full RelaySnapshot. Live database behavior (durable device/session
CRUD, IDOR, revocation, second-device continuity, fresh-connection
reload) is covered separately in
tests/test_relay_store_live_neon.py (LIVE_NEON_TEMP_BRANCH).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orca.mission.relay_store import (
    ApprovalSummary,
    AuthorityContextSummary,
    CheckpointSummary,
    DeviceTrustLevel,
    MissionSummary,
    ModelActivitySummary,
    OperationSummary,
    ProductionProofSummary,
    RelayDevice,
    RelayMode,
    RelaySession,
    RelaySessionStatus,
    RelaySnapshot,
    RequirementSummary,
    StepSummary,
    TestProgressSummary,
    ToolActivitySummary,
    VerificationSummary,
    _sanitize,
    session_status,
)


def _device_row(**overrides) -> dict:
    base = {
        "id": "dev_1", "user_id": "u1", "name": "Alice's Laptop", "trust_level": "TRUSTED",
        "first_seen_at": "2026-09-09T00:00:00+00:00", "last_seen_at": "2026-09-09T00:00:00+00:00",
        "revoked_at": None,
    }
    base.update(overrides)
    return base


def _session_row(**overrides) -> dict:
    base = {
        "id": "rlysess_1", "mission_id": "mis_1", "device_id": "dev_1", "user_id": "u1",
        "mode": "TRUSTED_DEVICE", "created_at": "2026-09-09T00:00:00+00:00",
        "expires_at": "2026-09-09T12:00:00+00:00", "last_seen_at": "2026-09-09T00:00:00+00:00",
        "revoked_at": None, "revoked_reason": None,
    }
    base.update(overrides)
    return base


def test_device_from_row_parses_trust_level_and_revocation():
    device = RelayDevice.from_row(_device_row())
    assert device.trust_level is DeviceTrustLevel.TRUSTED
    assert device.is_revoked is False

    revoked = RelayDevice.from_row(_device_row(revoked_at="2026-09-09T01:00:00+00:00"))
    assert revoked.is_revoked is True


def test_session_from_row_parses_mode():
    session = RelaySession.from_row(_session_row())
    assert session.mode is RelayMode.TRUSTED_DEVICE


# ── session_status() boundary semantics (spec section 5) ────────────

def test_session_active_before_expiry():
    session = RelaySession.from_row(_session_row(expires_at="2026-09-09T12:00:00+00:00"))
    now = datetime(2026, 9, 9, 11, 59, 59, tzinfo=timezone.utc)
    assert session_status(session, now=now) is RelaySessionStatus.ACTIVE


def test_session_expired_exactly_at_expiry_boundary():
    session = RelaySession.from_row(_session_row(expires_at="2026-09-09T12:00:00+00:00"))
    now = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
    assert session_status(session, now=now) is RelaySessionStatus.EXPIRED


def test_session_expired_after_expiry():
    session = RelaySession.from_row(_session_row(expires_at="2026-09-09T12:00:00+00:00"))
    now = datetime(2026, 9, 9, 12, 0, 1, tzinfo=timezone.utc)
    assert session_status(session, now=now) is RelaySessionStatus.EXPIRED


def test_revoked_session_is_revoked_even_if_not_yet_expired():
    session = RelaySession.from_row(_session_row(
        expires_at="2099-01-01T00:00:00+00:00", revoked_at="2026-09-09T00:30:00+00:00",
    ))
    now = datetime(2026, 9, 9, 0, 31, 0, tzinfo=timezone.utc)
    assert session_status(session, now=now) is RelaySessionStatus.REVOKED


def test_revoked_session_is_revoked_even_past_expiry():
    session = RelaySession.from_row(_session_row(
        expires_at="2020-01-01T00:00:00+00:00", revoked_at="2026-09-09T00:30:00+00:00",
    ))
    now = datetime(2026, 9, 9, 0, 31, 0, tzinfo=timezone.utc)
    assert session_status(session, now=now) is RelaySessionStatus.REVOKED


def test_session_status_defaults_to_wall_clock_when_now_omitted():
    far_future_expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    session = RelaySession.from_row(_session_row(expires_at=far_future_expiry))
    assert session_status(session) is RelaySessionStatus.ACTIVE


# ── Secret redaction over the full RelaySnapshot tree (spec section 19) ──

_SYNTHETIC_SECRETS = [
    "postgres://admin:sup3rs3cret@db.internal:5432/prod",
    "Authorization: Bearer abcdefghijklmnopqrstuvwx1234567890",
    "api_key: sk-abcdefghijklmnopqrstuvwxyz123456",
    "password=Tr0ub4dor&3-actually-long-enough-to-match",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIBogIBAAKCAQ==\n-----END RSA PRIVATE KEY-----",
    "AKIAABCDEFGHIJKLMNOP",
]


def _snapshot_with_secret_in(field_name: str, secret: str) -> RelaySnapshot:
    kwargs = dict(
        relay_session_id="rlysess_1", mission_id="mis_1", workspace_id="ws_1", device_id="dev_1", user_id="u1",
        repository="org/repo", branch="main", current_revision="rev1", mission_state="RUNNING",
        snapshot_generated_at="2026-09-09T00:00:00+00:00", mission_updated_at="2026-09-09T00:00:00+00:00",
        consistency_basis="single PostgreSQL REPEATABLE READ, READ ONLY transaction",
        mission=None, step=StepSummary(current_step_id=None, completed_step_ids=(), remaining_step_ids=(), failed_step_ids=()),
        requirements=(RequirementSummary(requirement_id="REQ-X-001", status="IMPLEMENTED", statement="ok", evidence_ref=None),),
        verifications=(VerificationSummary(requirement_id="REQ-X-001", category="UNIT_TEST", outcome="PASS", revision="rev1", verifier_id="V1", evidence_refs=(), stale=False),),
        test_progress=(TestProgressSummary(category="UNIT_TEST", verification_id="ver1", outcome="PASS", revision="rev1", verifier_id="V1", evidence_refs=()),),
        production_proof=ProductionProofSummary(proof_id="p1", revision="rev1", release_state="ENGINEERING_READY", proof_hash="h", generated_at="t", available=True, stale=None),
        pending_approvals=(ApprovalSummary(id="a1", operation_id="op1", decision="PENDING", requested_at="t", decided_by=None, reason="normal reason"),),
        pending_operations=(OperationSummary(id="op1", kind="deploy", status="REQUESTED", requested_by="u1", requested_at="t", result_ref=None),),
        checkpoint=CheckpointSummary(checkpoint_id="ckpt1", created_at="t", mission_state="RUNNING", current_step_id=None, current_revision="rev1", diff_ref=None, active_blocker=None, evidence_refs=()),
        model_activity=(ModelActivitySummary(id="m1", provider="anthropic", model="claude", purpose="plan", started_at="t", completed_at=None, outcome_summary="ok"),),
        tool_activity=(ToolActivitySummary(id="t1", tool_name="bash", status="SUCCEEDED", started_at="t", completed_at=None, outcome_summary="ok"),),
        authority_context=(AuthorityContextSummary(id="ad1", operation_id="op1", decision="ALLOW", decided_at="t", detail="normal detail"),),
    )
    kwargs["mission"] = MissionSummary(mission_id="mis_1", workspace_id="ws_1", repository="org/repo", branch="main", base_revision="base", current_revision="rev1", mission_state="RUNNING")

    # Inject the secret into ONE targeted text field via a fresh object built with it.
    if field_name == "model_outcome_summary":
        kwargs["model_activity"] = (ModelActivitySummary(id="m1", provider="anthropic", model="claude", purpose="plan", started_at="t", completed_at=None, outcome_summary=secret),)
    elif field_name == "tool_outcome_summary":
        kwargs["tool_activity"] = (ToolActivitySummary(id="t1", tool_name="bash", status="SUCCEEDED", started_at="t", completed_at=None, outcome_summary=secret),)
    elif field_name == "checkpoint_active_blocker":
        kwargs["checkpoint"] = CheckpointSummary(checkpoint_id="ckpt1", created_at="t", mission_state="RUNNING", current_step_id=None, current_revision="rev1", diff_ref=None, active_blocker=secret, evidence_refs=())
    elif field_name == "approval_reason":
        kwargs["pending_approvals"] = (ApprovalSummary(id="a1", operation_id="op1", decision="PENDING", requested_at="t", decided_by=None, reason=secret),)
    elif field_name == "authority_detail":
        kwargs["authority_context"] = (AuthorityContextSummary(id="ad1", operation_id="op1", decision="ALLOW", decided_at="t", detail=secret),)
    elif field_name == "repository":
        kwargs["repository"] = secret
    else:
        raise ValueError(field_name)

    return RelaySnapshot(**kwargs)


def test_sanitize_redacts_secret_in_model_activity_outcome():
    for secret in _SYNTHETIC_SECRETS:
        snap = _sanitize(_snapshot_with_secret_in("model_outcome_summary", secret))
        assert secret not in snap.model_activity[0].outcome_summary
        assert "[REDACTED]" in snap.model_activity[0].outcome_summary


def test_sanitize_redacts_secret_in_tool_activity_outcome():
    for secret in _SYNTHETIC_SECRETS:
        snap = _sanitize(_snapshot_with_secret_in("tool_outcome_summary", secret))
        assert secret not in snap.tool_activity[0].outcome_summary


def test_sanitize_redacts_secret_in_checkpoint_blocker():
    for secret in _SYNTHETIC_SECRETS:
        snap = _sanitize(_snapshot_with_secret_in("checkpoint_active_blocker", secret))
        assert secret not in snap.checkpoint.active_blocker


def test_sanitize_redacts_secret_in_approval_reason():
    for secret in _SYNTHETIC_SECRETS:
        snap = _sanitize(_snapshot_with_secret_in("approval_reason", secret))
        assert secret not in snap.pending_approvals[0].reason


def test_sanitize_redacts_secret_in_authority_detail():
    for secret in _SYNTHETIC_SECRETS:
        snap = _sanitize(_snapshot_with_secret_in("authority_detail", secret))
        assert secret not in snap.authority_context[0].detail


def test_sanitize_redacts_secret_in_repository_field():
    for secret in _SYNTHETIC_SECRETS:
        snap = _sanitize(_snapshot_with_secret_in("repository", secret))
        assert secret not in snap.repository


def test_sanitize_leaves_enum_members_untouched():
    from orca.mission.relay_store import DeviceTrustLevel as DTL
    assert _sanitize(DTL.TRUSTED) is DTL.TRUSTED


def test_sanitize_preserves_non_secret_text():
    snap = _sanitize(_snapshot_with_secret_in("model_outcome_summary", "all tests passed, 12 total"))
    assert snap.model_activity[0].outcome_summary == "all tests passed, 12 total"


# ── Production Proof freshness truthfulness (15.11.1 item 9) ────────

def test_build_relay_snapshot_sets_repeatable_read_before_any_read():
    """15.11.1 item 10 (static-shape proof): `build_relay_snapshot()`
    issues `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ
    ONLY` as its literal first statement, before any governed-state
    SELECT. The live mechanism itself (a concurrent write is invisible
    within that transaction) is proven against real Postgres in
    tests/test_relay_store_live_neon.py."""
    import inspect
    from orca.mission import relay_store
    source = inspect.getsource(relay_store.build_relay_snapshot)
    set_txn_pos = source.index("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    first_select_pos = source.index("SELECT * FROM relay_sessions")
    assert set_txn_pos < first_select_pos


def test_production_proof_summary_never_asserts_stale_false():
    """This module must never itself claim `stale=False` (CURRENT) --
    only `True` (definite mismatch) or `None` (unknown, revisions
    match but full decision context unavailable). `False` is reserved
    for a future caller that supplies the full stale-proof context."""
    import inspect
    from orca.mission import relay_store
    source = inspect.getsource(relay_store._build_production_proof_summary)
    assert "stale = False" not in source
    assert "stale=False" not in source

