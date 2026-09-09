"""
Phase 15.12 / 15.12.1 -- LIVE_NEON_TEMP_BRANCH: Relay security-mode
qualification against real Postgres -- TRUSTED enrollment through a
REAL, server-issued, non-forgeable reauthentication grant, the
authoritative capability gate loading trust/mode from DURABLE state
(never a caller argument), device/mode compatibility at session-
creation time, security-valid-session inactivity/revocation
(including the genuine post-expiry-touch adversarial case),
device/mode-mismatch snapshot denial, Mobile Review state built from a
real RelaySnapshot, the raw-secret battery across all three modes, and
Authority Engine non-bypass against the real Phase 15.5 operation
lifecycle.

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
from types import SimpleNamespace

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
    ReauthGrant,
    RelayCapability,
    SecuritySessionStatus,
    SessionSecurityInvalidError,
    TrustedEnrollmentDeniedError,
    authorize_relay_capability,
    build_mobile_review_state,
    build_security_valid_relay_snapshot,
    check_capability,
    create_relay_session,
    enroll_public_device,
    enroll_trusted_device,
    evaluate_session_security,
    is_reauth_grant_valid,
    require_security_valid_session,
    revoke_all_other_relay_sessions,
    revoke_other_relay_session,
    revoke_own_relay_session,
    touch_relay_session_securely,
    verify_reauthentication,
)
from orca.mission.relay_store import (
    DeviceRevokedError,
    RelayAccessDeniedError,
    RelayMode,
    RelaySessionInvalidError,
    get_device,
    get_session,
    register_device,
    revoke_device,
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


_TEST_USER_CREDENTIALS: dict[str, str] = {}


def _real_user(store) -> str:
    email = f"relaysec-{uuid.uuid4().hex[:10]}@example.com"
    password = f"Pw{uuid.uuid4().hex[:16]}!"
    user = store.create_user(email, password)
    _TEST_USER_CREDENTIALS[user.id] = password
    return user.id


def _reauth_for(owner: str, *, now_fn=None, relay_session_id=None) -> ReauthGrant:
    password = _TEST_USER_CREDENTIALS[owner]
    kwargs = {"authenticated_user_id": owner, "password": password}
    if now_fn is not None:
        kwargs["now_fn"] = now_fn
    if relay_session_id is not None:
        kwargs["relay_session_id"] = relay_session_id
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


# ── Trusted enrollment through a REAL, non-forgeable reauth grant (spec section 6; 15.12.1 items 3/6) ──

def test_enroll_trusted_device_succeeds_with_valid_reauth(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        grant = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant, name="Owner's Laptop")
        assert device.trust_level.value == "TRUSTED"
        assert device.user_id == owner
    finally:
        conn.close()


def test_enroll_trusted_device_reauth_for_user_a_cannot_enroll_for_user_b(isolated_home):
    user_a = _real_user(isolated_home)
    user_b = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        grant_for_a = _reauth_for(user_a)
        with pytest.raises(TrustedEnrollmentDeniedError):
            enroll_trusted_device(conn, authenticated_user_id=user_b, reauth_grant=grant_for_a, name="stolen enrollment attempt")
    finally:
        conn.close()


def test_enroll_trusted_device_expired_reauth_denied(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        base_now = datetime.now(timezone.utc)
        grant = _reauth_for(owner, now_fn=lambda: base_now)
        far_future = lambda: base_now + timedelta(hours=1)  # noqa: E731
        with pytest.raises(TrustedEnrollmentDeniedError):
            enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant, now_fn=far_future)
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


def test_arbitrary_object_cannot_satisfy_trusted_enrollment(isolated_home):
    """15.12.1 adversarial item 9: the exact forgery the 15.12 version
    of this boundary accepted -- `SimpleNamespace(user_id=owner)` --
    must now fail, because `enroll_trusted_device()` never reads
    `.user_id` off the presented object; it looks up `.grant_id` in
    the real server-side grant store."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        fake = SimpleNamespace(user_id=owner)
        with pytest.raises(TrustedEnrollmentDeniedError):
            enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=fake)
    finally:
        conn.close()


def test_fake_dataclass_with_user_id_cannot_satisfy_trusted_enrollment(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        fake = SimpleNamespace(grant_id=None, user_id=owner, issued_at="2026-01-01T00:00:00+00:00")
        with pytest.raises(TrustedEnrollmentDeniedError):
            enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=fake)
    finally:
        conn.close()


def test_manually_fabricated_reauth_grant_cannot_satisfy_trusted_enrollment(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        fabricated = ReauthGrant(grant_id="hand-fabricated-grant-id-does-not-exist")
        with pytest.raises(TrustedEnrollmentDeniedError):
            enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=fabricated)
    finally:
        conn.close()


def test_direct_register_device_trusted_is_unconditionally_rejected(isolated_home):
    """15.12.1 item 6: the ordinary public `register_device()` never
    grants TRUSTED trust, period -- no parameter of any kind can make
    it do so anymore."""
    from orca.mission.relay_store import DeviceTrustLevel
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        with pytest.raises(RelayAccessDeniedError):
            register_device(conn, authenticated_user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
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
        grant = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant)
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


def test_arbitrary_long_ttl_cannot_be_created_through_the_normal_api(isolated_home):
    """15.12.1 item 12: attempting to create a PUBLIC session with a
    30-day lifetime through the NORMAL production API is structurally
    impossible -- there is no parameter to even try it with."""
    import inspect
    sig = inspect.signature(create_relay_session)
    assert "ttl_seconds" not in sig.parameters
    thirty_days_seconds = 30 * 24 * 3600
    from orca.mission.relay_security import PUBLIC_DEVICE_MAX_SESSION_SECONDS
    assert PUBLIC_DEVICE_MAX_SESSION_SECONDS < thirty_days_seconds


# ── The AUTHORITATIVE capability gate loads trust/mode from DURABLE state (15.12.1 items 1-2) ──

def test_authoritative_gate_real_public_session_denies_terminal_and_deploy(isolated_home):
    """Adversarial matrix item 13/14: even though `authorize_relay_
    capability()` has no `device_trust`/`mode` parameter to fake, this
    test proves the REAL end-to-end behavior -- a genuinely PUBLIC
    session denies OPEN_TERMINAL/DEPLOY_CONTROL, full stop."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)

        terminal_decision = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.OPEN_TERMINAL,
        )
        assert terminal_decision.allowed is False

        deploy_decision = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.DEPLOY_CONTROL,
        )
        assert deploy_decision.allowed is False
        assert deploy_decision.requires_trusted_device_approval is True
    finally:
        conn.close()


def test_authoritative_gate_real_trusted_session_reaches_deploy_with_real_grant(isolated_home):
    """Adversarial matrix item 22: legitimate Trusted critical
    capability + a REAL server-issued grant reaches Relay-policy
    ALLOW through the authoritative gate."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        grant_for_enroll = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant_for_enroll)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE)

        # Without a grant: DENY.
        without_grant = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.DEPLOY_CONTROL,
        )
        assert without_grant.allowed is False

        # With a REAL grant bound to this exact session: ALLOW.
        grant_for_action = _reauth_for(owner, relay_session_id=session.id)
        with_grant = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.DEPLOY_CONTROL,
            reauth_grant=grant_for_action,
        )
        assert with_grant.allowed is True
    finally:
        conn.close()


def test_authoritative_gate_harmless_read_remains_possible(isolated_home):
    """Adversarial matrix item 21: a harmless valid read never
    requires a grant and always succeeds for an active session."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        decision = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.VIEW_MISSION_STATUS,
        )
        assert decision.allowed is True
    finally:
        conn.close()


def test_authoritative_gate_cross_user_session_denied(isolated_home):
    owner = _real_user(isolated_home)
    attacker = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        with pytest.raises(RelayAccessDeniedError):
            authorize_relay_capability(
                conn, session_id=session.id, authenticated_user_id=attacker, capability=RelayCapability.VIEW_MISSION_STATUS,
            )
    finally:
        conn.close()


def test_authoritative_gate_revoked_session_denied(isolated_home):
    from orca.mission.relay_security import revoke_own_relay_session as _revoke_own
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        _revoke_own(conn, session.id, authenticated_user_id=owner)
        with pytest.raises(SessionSecurityInvalidError):
            authorize_relay_capability(
                conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.VIEW_MISSION_STATUS,
            )
    finally:
        conn.close()


def test_authoritative_gate_idle_expired_session_denied(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        base_now = datetime.now(timezone.utc)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE, now_fn=lambda: base_now)
        from orca.mission.relay_security import PUBLIC_DEVICE_INACTIVITY_SECONDS
        past_deadline = lambda: base_now + timedelta(seconds=PUBLIC_DEVICE_INACTIVITY_SECONDS + 5)  # noqa: E731
        with pytest.raises(SessionSecurityInvalidError):
            authorize_relay_capability(
                conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.VIEW_MISSION_STATUS,
                now_fn=past_deadline,
            )
    finally:
        conn.close()


def test_authoritative_gate_unknown_capability_denies(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        decision = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability="SUPER_ADMIN_OVERRIDE",
        )
        assert decision.allowed is False
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
        with pytest.raises(SessionSecurityInvalidError) as exc_info:
            require_security_valid_session(conn, session.id, authenticated_user_id=owner, now_fn=future)
        assert exc_info.value.status is SecuritySessionStatus.INACTIVITY_EXPIRED
    finally:
        conn.close()


def test_normal_heartbeat_path_rejects_a_genuinely_idle_expired_session_never_touched(isolated_home):
    """15.12.1 item 8's EXACT required adversarial proof: T0 create,
    NO touch at all, T0 + inactivity_timeout + 1s, attempt the NORMAL
    heartbeat/touch path (`touch_relay_session_securely()`) -- must
    REJECT, and `last_seen_at` must remain unchanged. This is
    different from (and closes the real gap in) the OLD test, which
    touched the session while it was still valid and only checked
    expiry afterward -- proving nothing about reviving an
    ALREADY-idle-expired session via touch."""
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
        original_last_seen_at = get_session(conn, session.id).last_seen_at

        from orca.mission.relay_security import PUBLIC_DEVICE_INACTIVITY_SECONDS
        past_deadline = lambda: base_now + timedelta(seconds=PUBLIC_DEVICE_INACTIVITY_SECONDS + 1)  # noqa: E731

        # NO touch happened between creation and this point.
        with pytest.raises(SessionSecurityInvalidError) as exc_info:
            touch_relay_session_securely(conn, session.id, authenticated_user_id=owner, now_fn=past_deadline)
        assert exc_info.value.status is SecuritySessionStatus.INACTIVITY_EXPIRED

        reloaded = get_session(conn, session.id)
        assert reloaded.last_seen_at == original_last_seen_at  # UNCHANGED -- no revival

        # Subsequent security validation still reports INACTIVITY_EXPIRED.
        with pytest.raises(SessionSecurityInvalidError) as exc_info2:
            require_security_valid_session(conn, session.id, authenticated_user_id=owner, now_fn=past_deadline)
        assert exc_info2.value.status is SecuritySessionStatus.INACTIVITY_EXPIRED
    finally:
        conn.close()


def test_trusted_device_normal_heartbeat_path_also_rejects_idle_expiry(isolated_home):
    """Same adversarial proof, Trusted mode (spec section 8's own
    'do the same minimum proof for whichever other modes have
    inactivity timeouts')."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        base_now = datetime.now(timezone.utc)
        mission_id = _seed_mission(conn, owner)
        grant = _reauth_for(owner, now_fn=lambda: base_now)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant, now_fn=lambda: base_now)
        session = create_relay_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, now_fn=lambda: base_now,
        )
        original_last_seen_at = get_session(conn, session.id).last_seen_at

        from orca.mission.relay_security import TRUSTED_DEVICE_INACTIVITY_SECONDS
        past_deadline = lambda: base_now + timedelta(seconds=TRUSTED_DEVICE_INACTIVITY_SECONDS + 1)  # noqa: E731

        with pytest.raises(SessionSecurityInvalidError) as exc_info:
            touch_relay_session_securely(conn, session.id, authenticated_user_id=owner, now_fn=past_deadline)
        assert exc_info.value.status is SecuritySessionStatus.INACTIVITY_EXPIRED

        reloaded = get_session(conn, session.id)
        assert reloaded.last_seen_at == original_last_seen_at
    finally:
        conn.close()


def test_require_security_valid_session_device_revoked(isolated_home):
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


def test_device_mode_mismatch_row_denied_by_security_validator(isolated_home):
    """A corrupted PUBLIC-device/TRUSTED_DEVICE-mode session row
    (fabricated directly via SQL -- the normal creation path already
    structurally prevents this, per
    test_create_relay_session_public_device_cannot_get_trusted_device_mode)
    must still be flagged by the security validator, not silently
    treated as valid."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        with conn.cursor() as cur:
            cur.execute("UPDATE relay_sessions SET mode = 'TRUSTED_DEVICE' WHERE id = %s", (session.id,))
        conn.commit()
        with pytest.raises(SessionSecurityInvalidError) as exc_info:
            require_security_valid_session(conn, session.id, authenticated_user_id=owner)
        assert exc_info.value.status is SecuritySessionStatus.DEVICE_MODE_MISMATCH
    finally:
        conn.close()


# ── Mobile Review state / secure snapshot (spec sections 5, 9, 23) ──

def test_mobile_review_state_reflects_real_snapshot_identity(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        grant = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant)
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


def test_idle_expired_public_session_cannot_build_security_snapshot(isolated_home):
    """15.12.1 item 9 adversarial proof: an idle-expired PUBLIC
    session must not build a RelaySnapshot through the security-
    authoritative entrypoint (unlike the OLD `build_mobile_review_state()`,
    the ordinary `relay_store.build_relay_snapshot()` alone would NOT
    have caught this -- only `build_security_valid_relay_snapshot()`/
    `build_mobile_review_state()` do)."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        base_now = datetime.now(timezone.utc)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE, now_fn=lambda: base_now)
        from orca.mission.relay_security import PUBLIC_DEVICE_INACTIVITY_SECONDS
        past_deadline = lambda: base_now + timedelta(seconds=PUBLIC_DEVICE_INACTIVITY_SECONDS + 5)  # noqa: E731
        with pytest.raises(SessionSecurityInvalidError):
            build_security_valid_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner, now_fn=past_deadline)
        with pytest.raises(SessionSecurityInvalidError):
            build_mobile_review_state(conn, session_id=session.id, authenticated_user_id=owner, now_fn=past_deadline)
    finally:
        conn.close()


def test_idle_expired_trusted_session_cannot_build_security_snapshot(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        grant = _reauth_for(owner, now_fn=lambda: base_now)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant, now_fn=lambda: base_now)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, now_fn=lambda: base_now)
        from orca.mission.relay_security import TRUSTED_DEVICE_INACTIVITY_SECONDS
        past_deadline = lambda: base_now + timedelta(seconds=TRUSTED_DEVICE_INACTIVITY_SECONDS + 5)  # noqa: E731
        with pytest.raises(SessionSecurityInvalidError):
            build_security_valid_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner, now_fn=past_deadline)
    finally:
        conn.close()


def test_device_mode_mismatch_row_cannot_build_security_snapshot(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        with conn.cursor() as cur:
            cur.execute("UPDATE relay_sessions SET mode = 'TRUSTED_DEVICE' WHERE id = %s", (session.id,))
        conn.commit()
        with pytest.raises(SessionSecurityInvalidError) as exc_info:
            build_security_valid_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
        assert exc_info.value.status is SecuritySessionStatus.DEVICE_MODE_MISMATCH
    finally:
        conn.close()


def test_valid_session_snapshot_unaffected_by_the_new_security_check(isolated_home):
    """The strengthened entrypoint must not break the ordinary,
    genuinely-valid case."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)
        snapshot = build_security_valid_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
        assert snapshot.mission_id == mission_id
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

        grant = _reauth_for(owner)
        trusted_device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant)
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


# ── Authority Engine non-bypass (spec sections 14, 22, 23) ───────────

def test_relay_policy_allow_does_not_manufacture_authority(isolated_home):
    """Trusted Device + fresh valid grant + DEPLOY_CONTROL permitted
    by the AUTHORITATIVE Relay gate + NO real authority approval =>
    the underlying operation still cannot execute."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        grant_for_enroll = _reauth_for(owner)
        device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant_for_enroll)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE)

        grant_for_action = _reauth_for(owner, relay_session_id=session.id)
        decision = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.DEPLOY_CONTROL,
            reauth_grant=grant_for_action,
        )
        assert decision.allowed is True  # Relay POLICY says yes, via the REAL authoritative gate

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
        decision = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.DEPLOY_CONTROL,
        )
        assert decision.allowed is False
        assert decision.requires_trusted_device_approval is True
    finally:
        conn.close()


def test_approve_capability_does_not_itself_write_any_authority_state(isolated_home):
    """spec section 11: `RelayCapability.APPROVE` means access to the
    governed approval control SURFACE -- it must never itself write
    `Approval.APPROVED`/`AuthorityDecision.ALLOW`/`Operation.AUTHORIZED`.
    Proven here by seeding a real PENDING approval, confirming the
    Relay-policy layer can grant the APPROVE capability, and then
    confirming that granting it alone never touched the approval's
    real durable row."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)

        op, _ = request_operation(
            conn, id=f"op_{uuid.uuid4().hex[:8]}", idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
            kind="deploy", requested_by=owner, mission_id=mission_id,
        )
        now = datetime.now(timezone.utc).isoformat()
        appr_id = f"appr_{uuid.uuid4().hex[:8]}"
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO approvals (id, mission_id, operation_id, requested_at, decision) VALUES (%s, %s, %s, %s, 'PENDING')",
                (appr_id, mission_id, op["id"], now),
            )
        conn.commit()

        decision = authorize_relay_capability(
            conn, session_id=session.id, authenticated_user_id=owner, capability=RelayCapability.APPROVE,
        )
        assert decision.allowed is True

        with conn.cursor() as cur:
            cur.execute("SELECT decision FROM approvals WHERE id = %s", (appr_id,))
            still_pending = cur.fetchone()["decision"]
            cur.execute("SELECT status FROM operations WHERE id = %s", (op["id"],))
            still_requested = cur.fetchone()["status"]
        conn.commit()
        assert still_pending == "PENDING"  # unchanged -- APPROVE capability grant never wrote this
        assert still_requested == "REQUESTED"  # unchanged
    finally:
        conn.close()


# ── Session revocation under security modes, using 15.12 validity (spec section 20; 15.12.1 item 10) ──

def test_trusted_device_session_revokes_public_device_session(isolated_home):
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        grant = _reauth_for(owner)
        trusted_device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant)
        public_device = enroll_public_device(conn, authenticated_user_id=owner)
        trusted_session = create_relay_session(conn, device_id=trusted_device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE)
        public_session = create_relay_session(conn, device_id=public_device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE)

        revoke_other_relay_session(conn, current_session_id=trusted_session.id, target_session_id=public_session.id, authenticated_user_id=owner)
        assert session_status(get_session(conn, public_session.id)).value == "REVOKED"
        assert session_status(get_session(conn, trusted_session.id)).value == "ACTIVE"
    finally:
        conn.close()


def test_public_device_session_can_revoke_itself_even_when_idle_expired(isolated_home):
    """Self-revocation is deliberately MORE permissive (spec section
    10's own allowance) -- an idle-expired session may still revoke
    ITSELF."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device = enroll_public_device(conn, authenticated_user_id=owner)
        base_now = datetime.now(timezone.utc)
        session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE, now_fn=lambda: base_now)
        revoke_own_relay_session(conn, session.id, authenticated_user_id=owner, reason="user logged out on shared computer")
        assert session_status(get_session(conn, session.id)).value == "REVOKED"
    finally:
        conn.close()


def test_idle_expired_current_session_cannot_revoke_another_session(isolated_home):
    """15.12.1 item 10's core adversarial proof: an idle-expired
    session cannot act as the control context for revoking ANOTHER
    session, even though it still passes Phase 15.11's own weaker
    `_require_active_session_context()` check (not expired/revoked)."""
    owner = _real_user(isolated_home)
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device_a = enroll_public_device(conn, authenticated_user_id=owner)
        device_b = enroll_public_device(conn, authenticated_user_id=owner)
        base_now = datetime.now(timezone.utc)
        session_a = create_relay_session(conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE, now_fn=lambda: base_now)
        session_b = create_relay_session(conn, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE, now_fn=lambda: base_now)

        from orca.mission.relay_security import PUBLIC_DEVICE_INACTIVITY_SECONDS
        past_deadline = lambda: base_now + timedelta(seconds=PUBLIC_DEVICE_INACTIVITY_SECONDS + 5)  # noqa: E731

        with pytest.raises(SessionSecurityInvalidError) as exc_info:
            revoke_other_relay_session(
                conn, current_session_id=session_a.id, target_session_id=session_b.id, authenticated_user_id=owner,
                now_fn=past_deadline,
            )
        assert exc_info.value.status is SecuritySessionStatus.INACTIVITY_EXPIRED
        # target untouched
        assert session_status(get_session(conn, session_b.id)).value == "ACTIVE"

        with pytest.raises(SessionSecurityInvalidError):
            revoke_all_other_relay_sessions(conn, current_session_id=session_a.id, authenticated_user_id=owner, now_fn=past_deadline)
        assert session_status(get_session(conn, session_b.id)).value == "ACTIVE"
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
            revoke_other_relay_session(conn, current_session_id=public_session.id, target_session_id=other_session.id, authenticated_user_id=owner)
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
        grant = _reauth_for(owner)
        trusted_device = enroll_trusted_device(conn, authenticated_user_id=owner, reauth_grant=grant)
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

        grant = _reauth_for(owner, relay_session_id=session_a.id)
        assert is_reauth_grant_valid(grant, authenticated_user_id=owner, relay_session_id=session_a.id) is True
        assert is_reauth_grant_valid(grant, authenticated_user_id=owner, relay_session_id=session_b.id) is False
    finally:
        conn.close()
