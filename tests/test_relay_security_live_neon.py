"""
Phase 15.12 -- LIVE_NEON_TEMP_BRANCH: Relay security-mode qualification
against real Postgres -- TRUSTED enrollment through real
reauthentication, device/mode compatibility at session-creation time,
security-valid-session inactivity/revocation, Mobile Review state
built from a real RelaySnapshot, the raw-secret battery across all
three modes, and Authority Engine non-bypass against the real Phase
15.5 operation lifecycle.

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file. Real auth reauthentication
uses the isolated SQLite auth backend (`isolated_home`), a completely
separate database from the mission Neon Postgres used here -- exactly
as the two systems are architecturally separate in production.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from orca.mission.db import apply_schema, get_conn
from orca.mission.mission_store import create_mission
from orca.mission.operation_store import (
    OperationStateError,
    request_operation,
    start_and_execute_operation,
)
from orca.mission.relay_security import (
    MobileReviewState,
    RelayCapability,
    ReauthContextInvalidError,
    SecuritySessionStatus,
    TrustedEnrollmentDeniedError,
    build_mobile_review_state,
    build_security_profile,
    check_capability,
    create_relay_session,
    enroll_public_device,
    enroll_trusted_device,
    evaluate_session_security,
    require_security_valid_session,
    verify_reauthentication,
)
from orca.mission.relay_store import (
    DeviceRevokedError,
    RelayAccessDeniedError,
    RelayMode,
    get_device,
    get_session,
    revoke_device,
    revoke_other_session,
    revoke_session,
    session_status,
)

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    conn = get_conn(direct=True)
    try:
        apply_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _fresh_connection():
    return get_conn(direct=False)


def _mid() -> str:
    return f"mis_{uuid.uuid4().hex[:12]}"


_TEST_USER_CREDENTIALS: dict[str, tuple[str, str]] = {}


def _real_user(store) -> str:
    email = f"relaysec-{uuid.uuid4().hex[:10]}@example.com"
    password = f"Pw{uuid.uuid4().hex[:16]}!"
    user = store.create_user(email, password)
    _TEST_USER_CREDENTIALS[user.id] = (email, password)
    return user.id


def _reauth_for(owner: str, *, now_fn=None):
    email, password = _TEST_USER_CREDENTIALS[owner]
    kwargs = {"email": email, "password": password}
    if now_fn is not None:
        kwargs["now_fn"] = now_fn
    return verify_reauthentication(**kwargs)


@pytest.fixture(autouse=True)
def _isolated_auth(isolated_home):
    yield isolated_home


def _seed_mission(conn, owner_user_id: str) -> str:
    mission_id = _mid()
    create_mission(
        conn, id=mission_id, repository="org/relay-sec-qual", branch="main", mode="BUILD",
        autonomy_level="L1", owner_user_id=owner_user_id, current_revision="rev1", workspace_id="ws_relay_sec",
    )
    return mission_id


# ── Trusted enrollment through real reauthentication (spec section 6) ──

def test_enroll_trusted_device_succeeds_with_valid_reauth(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        ctx = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_context=ctx, name="Owner's Laptop")
        assert device.trust_level.value == "TRUSTED"
        assert device.user_id == owner
    finally:
        conn.close()


def test_enroll_trusted_device_reauth_for_user_a_cannot_enroll_for_user_b(isolated_home):
    user_a = _real_user(isolated_home)
    user_b = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        ctx_for_a = _reauth_for(user_a)
        with pytest.raises(TrustedEnrollmentDeniedError):
            enroll_trusted_device(conn, authenticated_user_id=user_b, reauth_context=ctx_for_a, name="stolen enrollment attempt")
    finally:
        conn.close()


def test_enroll_trusted_device_expired_reauth_denied(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        base_now = datetime.now(timezone.utc)
        ctx = _reauth_for(owner, now_fn=lambda: base_now)
        far_future = lambda: base_now + timedelta(hours=1)  # noqa: E731
        with pytest.raises(TrustedEnrollmentDeniedError):
            enroll_trusted_device(conn, authenticated_user_id=owner, reauth_context=ctx, now_fn=far_future)
    finally:
        conn.close()


def test_enroll_public_device_requires_no_reauth(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        device = enroll_public_device(conn, authenticated_user_id=owner, name="Shared Kiosk")
        assert device.trust_level.value == "PUBLIC"
    finally:
        conn.close()


# ── Device/mode compatibility at session-creation time (spec section 2) ──

def test_create_relay_session_public_device_cannot_get_trusted_device_mode(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        with pytest.raises(RelayAccessDeniedError):
            create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE)
    finally:
        conn.close()


def test_create_relay_session_trusted_device_choosing_public_mode_succeeds_with_public_restrictions(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        ctx = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_context=ctx)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        assert session.mode is RelayMode.PUBLIC_DEVICE
        decision = check_capability(RelayCapability.OPEN_TERMINAL, device_trust=device.trust_level, mode=session.mode)
        assert decision.allowed is False
    finally:
        conn.close()


def test_create_relay_session_ttl_is_server_policy_not_caller_input(isolated_home):
    import inspect
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        assert "ttl_seconds" not in inspect.signature(create_relay_session).parameters
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        from orca.mission.relay_security import PUBLIC_DEVICE_MAX_SESSION_SECONDS
        created = datetime.fromisoformat(session.created_at)
        expires = datetime.fromisoformat(session.expires_at)
        assert abs((expires - created).total_seconds() - PUBLIC_DEVICE_MAX_SESSION_SECONDS) < 2
    finally:
        conn.close()


# ── Security-valid-session (spec section 11) against real Postgres ──

def test_require_security_valid_session_inactivity_expired_via_injected_clock(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        from orca.mission.relay_security import PUBLIC_DEVICE_INACTIVITY_SECONDS
        future = lambda: datetime.now(timezone.utc) + timedelta(seconds=PUBLIC_DEVICE_INACTIVITY_SECONDS + 5)  # noqa: E731
        from orca.mission.relay_security import SessionSecurityInvalidError
        with pytest.raises(SessionSecurityInvalidError) as exc_info:
            require_security_valid_session(conn, session.id, authenticated_user_id=owner, now_fn=future)
        assert exc_info.value.status is SecuritySessionStatus.INACTIVITY_EXPIRED
    finally:
        conn.close()


def test_inactivity_expired_session_cannot_be_revived_by_touch(isolated_home):
    """Uses a FIXED base timestamp (never a lambda that recomputes
    `datetime.now()` on every call) so touching the session at T1 and
    then checking security validity at T2 = T1 + inactivity_timeout
    produces a REAL idle gap, not two nearly-identical wall-clock
    reads that cancel each other out."""
    from orca.mission.relay_store import touch_session
    from orca.mission.relay_security import (
        PUBLIC_DEVICE_INACTIVITY_SECONDS,
        SessionSecurityInvalidError,
        require_security_valid_session,
    )
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        base_now = datetime.now(timezone.utc)
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.PUBLIC_DEVICE, now_fn=lambda: base_now,
        )
        still_within_inactivity = lambda: base_now + timedelta(seconds=60)  # noqa: E731
        # Absolute-expiry-based touch_session() still considers this
        # session ACTIVE (2h max lifetime not yet reached) -- it is
        # ONLY the security-layer's inactivity policy that must reject
        # it later, proving the two checks are genuinely additive, not
        # redundant duplicates of each other.
        touched = touch_session(conn, session.id, authenticated_user_id=owner, now_fn=still_within_inactivity)
        assert touched is not None

        past_inactivity_deadline = lambda: base_now + timedelta(seconds=60 + PUBLIC_DEVICE_INACTIVITY_SECONDS + 5)  # noqa: E731
        with pytest.raises(SessionSecurityInvalidError):
            require_security_valid_session(conn, session.id, authenticated_user_id=owner, now_fn=past_inactivity_deadline)
    finally:
        conn.close()


def test_require_security_valid_session_device_revoked(isolated_home):
    from orca.mission.relay_security import SessionSecurityInvalidError
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        revoke_device(conn, device.id, authenticated_user_id=owner)
        with pytest.raises(SessionSecurityInvalidError) as exc_info:
            require_security_valid_session(conn, session.id, authenticated_user_id=owner)
        assert exc_info.value.status is SecuritySessionStatus.DEVICE_REVOKED
    finally:
        conn.close()


# ── Mobile Review state built from the real RelaySnapshot (spec sections 5, 23) ──

def test_mobile_review_state_reflects_real_snapshot_identity(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        ctx = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_context=ctx)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.MOBILE_REVIEW)
        state = build_mobile_review_state(conn, session_id=session.id, authenticated_user_id=owner)
        assert isinstance(state, MobileReviewState)
        assert state.mission_id == mission_id
        assert state.current_revision == "rev1"
        assert state.security_profile.mobile_review is True
        assert state.snapshot.mission_id == mission_id
    finally:
        conn.close()


def test_mobile_review_state_on_public_device_shows_public_restriction(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.MOBILE_REVIEW)
        state = build_mobile_review_state(conn, session_id=session.id, authenticated_user_id=owner)
        assert state.security_profile.public_device is True
        assert state.security_profile.mobile_review is True
        assert state.security_profile.clipboard_export_allowed is False
        assert state.security_profile.download_allowed is False
    finally:
        conn.close()


# ── Raw-secret battery across all three modes (spec section 19) ─────

def test_no_raw_secrets_in_relay_snapshot_or_mobile_state_across_all_modes(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        now = datetime.now(timezone.utc).isoformat()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO model_invocations (id, mission_id, provider, model, purpose, started_at, outcome_summary) "
                "VALUES (%s, %s, 'anthropic', 'claude', 'plan', %s, %s)",
                (f"minv_{uuid.uuid4().hex[:8]}", mission_id, now, "leaked: postgres://admin:sup3rs3cret@db.internal:5432/prod"),
            )
            cur.execute(
                "INSERT INTO checkpoints (id, mission_id, created_at, mission_state, repository, current_revision, active_blocker) "
                "VALUES (%s, %s, %s, 'RUNNING', %s, 'rev1', %s)",
                (f"ckpt_{uuid.uuid4().hex[:8]}", mission_id, now, "org/relay-sec-qual", "api_key: sk-abcdefghijklmnopqrstuvwxyz123456"),
            )
        conn.commit()

        ctx = _reauth_for(owner)
        trusted_device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_context=ctx)
        public_device = enroll_public_device(conn, authenticated_user_id=owner)

        results = []
        for device, mode in (
            (trusted_device, RelayMode.TRUSTED_DEVICE),
            (public_device, RelayMode.PUBLIC_DEVICE),
            (trusted_device, RelayMode.MOBILE_REVIEW),
        ):
            session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=mode)
            state = build_mobile_review_state(conn, session_id=session.id, authenticated_user_id=owner)
            results.append(state)

        for state in results:
            blob = json.dumps({
                "model": [m.outcome_summary for m in state.snapshot.model_activity],
                "checkpoint_blocker": state.snapshot.checkpoint.active_blocker,
            })
            assert "sup3rs3cret" not in blob
            assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in blob
            assert "[REDACTED]" in blob
    finally:
        conn.close()


# ── Authority Engine non-bypass (spec section 14) ────────────────────

def test_relay_policy_allow_does_not_manufacture_authority(isolated_home):
    """Trusted Device + fresh valid reauth + DEPLOY_CONTROL permitted
    by Relay policy + NO real authority approval => the underlying
    operation still cannot execute."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        ctx = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_context=ctx)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE)

        decision = check_capability(RelayCapability.DEPLOY_CONTROL, device_trust=device.trust_level, mode=session.mode, reauth_valid=True)
        assert decision.allowed is True  # Relay POLICY says yes

        op, created = request_operation(
            conn, id=f"op_{uuid.uuid4().hex[:8]}", idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
            kind="deploy", requested_by=owner, mission_id=mission_id,
        )
        assert op["status"] == "REQUESTED"

        class _NeverCalledExecutor:
            def execute(self, **kwargs):
                raise AssertionError("executor must never be invoked -- operation was never AUTHORIZED")

        with pytest.raises(OperationStateError):
            start_and_execute_operation(conn, op["id"], _NeverCalledExecutor())

        with conn.cursor() as cur:
            cur.execute("SELECT status FROM operations WHERE id = %s", (op["id"],))
            final_status = cur.fetchone()["status"]
        conn.commit()
        assert final_status == "REQUESTED"  # still not authorized -- Relay policy ALLOW changed nothing here
    finally:
        conn.close()


def test_public_device_dangerous_action_requires_trusted_approval_not_direct_execution(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        decision = check_capability(RelayCapability.DEPLOY_CONTROL, device_trust=device.trust_level, mode=session.mode, reauth_valid=True)
        assert decision.allowed is False
        assert decision.requires_trusted_device_approval is True
    finally:
        conn.close()


# ── Session revocation under security modes (spec section 20) ───────

def test_trusted_device_session_revokes_public_device_session(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        ctx = _reauth_for(owner)
        trusted_device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_context=ctx)
        public_device = enroll_public_device(conn, authenticated_user_id=owner)
        trusted_session = create_relay_session(conn, device_id=trusted_device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE)
        public_session = create_relay_session(conn, device_id=public_device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)

        revoke_other_session(conn, current_session_id=trusted_session.id, target_session_id=public_session.id, authenticated_user_id=owner)
        assert session_status(get_session(conn, public_session.id)).value == "REVOKED"
        assert session_status(get_session(conn, trusted_session.id)).value == "ACTIVE"
    finally:
        conn.close()


def test_public_device_session_can_revoke_itself(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        revoke_session(conn, session.id, authenticated_user_id=owner, reason="user logged out on shared computer")
        assert session_status(get_session(conn, session.id)).value == "REVOKED"
    finally:
        conn.close()


def test_public_device_cannot_perform_cross_session_control_it_does_not_own(isolated_home):
    owner = _real_user(isolated_home)
    other = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id_owner = _seed_mission(conn, owner)
        mission_id_other = _seed_mission(conn, other)
        public_device = enroll_public_device(conn, authenticated_user_id=owner)
        public_session = create_relay_session(conn, device_id=public_device.id, mission_id=mission_id_owner, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)

        other_device = enroll_public_device(conn, authenticated_user_id=other)
        other_session = create_relay_session(conn, device_id=other_device.id, mission_id=mission_id_other, authenticated_user_id=other, mode=RelayMode.PUBLIC_DEVICE)

        with pytest.raises(RelayAccessDeniedError):
            revoke_other_session(conn, current_session_id=public_session.id, target_session_id=other_session.id, authenticated_user_id=owner)
    finally:
        conn.close()


# ── Device trust immutability (spec section 21) ──────────────────────

def test_device_trust_level_has_no_update_entrypoint(isolated_home):
    """Safer V1 behavior: enroll a NEW Trusted Device identity after
    reauth, rather than silently upgrading a Public row in place --
    there is no function anywhere in relay_store/relay_security that
    mutates an existing device's trust_level."""
    import inspect
    from orca.mission import relay_store, relay_security

    for module in (relay_store, relay_security):
        for name, fn in vars(module).items():
            if not callable(fn) or name.startswith("__"):
                continue
            try:
                source = inspect.getsource(fn)
            except (OSError, TypeError):
                continue
            assert "UPDATE devices SET trust_level" not in source, f"{module.__name__}.{name} must not mutate trust_level in place"


def test_trust_escalation_via_new_enrollment_is_the_only_path(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        public_device = enroll_public_device(conn, authenticated_user_id=owner)
        assert public_device.trust_level.value == "PUBLIC"
        ctx = _reauth_for(owner)
        trusted_device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_context=ctx)
        assert trusted_device.trust_level.value == "TRUSTED"
        # The original PUBLIC row is untouched -- a genuinely NEW row.
        assert trusted_device.id != public_device.id
        assert get_device(conn, public_device.id).trust_level.value == "PUBLIC"
    finally:
        conn.close()


# ── Threat-model battery items requiring live state (spec section 22) ──

def test_stolen_active_session_used_by_a_different_authenticated_identity_denied(isolated_home):
    owner = _real_user(isolated_home)
    attacker = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        with pytest.raises(RelayAccessDeniedError):
            require_security_valid_session(conn, session.id, authenticated_user_id=attacker)
    finally:
        conn.close()


def test_cross_session_reauth_replay_denied(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device_a = enroll_public_device(conn, authenticated_user_id=owner)
        device_b = enroll_public_device(conn, authenticated_user_id=owner)
        session_a = create_relay_session(conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        session_b = create_relay_session(conn, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)

        ctx = _reauth_for(owner, now_fn=None)
        # Bind the reauth to session_a's own id explicitly and confirm it cannot be reused for session_b.
        from orca.mission.relay_security import ReauthContext, is_reauth_context_valid
        bound_ctx = ReauthContext(
            user_id=ctx.user_id, relay_session_id=session_a.id, issued_at=ctx.issued_at,
            expires_at=ctx.expires_at, factors_verified=ctx.factors_verified,
        )
        assert is_reauth_context_valid(bound_ctx, authenticated_user_id=owner, relay_session_id=session_a.id) is True
        assert is_reauth_context_valid(bound_ctx, authenticated_user_id=owner, relay_session_id=session_b.id) is False
    finally:
        conn.close()
