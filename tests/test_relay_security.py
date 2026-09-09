"""
Phase 15.12 / 15.12.1 -- UNIT tests for orca.mission.relay_security
(no mission Neon database required): capability-matrix intersection
semantics, session-security derivation, TTL/inactivity policy,
sensitive-file policy, security-profile construction, and REAL
(non-mocked) reauthentication + REAL server-side grant provenance
against the existing orca.auth primitives via the project's own
`isolated_home` fixture (isolated temp SQLite, never the developer's
real ~/.orca/auth.db).

15.12.1 correction: `check_capability()` no longer accepts a
`reauth_valid` boolean (removed entirely -- an owner audit found the
15.12 version let a caller manufacture ALLOW for a reauth-gated
capability just by passing `True`). `ReauthContext` (a publicly-
constructible, self-validating dataclass) is replaced by `ReauthGrant`
-- an opaque handle whose only trustable content is a `grant_id`
looked up in a server-side store; validation NEVER trusts fields
present on the object itself.

Live-Neon-dependent behavior (real TRUSTED enrollment against a real
device row, session creation/security validation against real
Postgres, `authorize_relay_capability()`'s full durable-state-loading
gate, Mobile Review state built from a real RelaySnapshot, authority
non-bypass, and the full secret battery across all 3 modes) is covered
in tests/test_relay_security_live_neon.py (LIVE_NEON_TEMP_BRANCH).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from orca.mission.relay_security import (
    MOBILE_REVIEW_INACTIVITY_SECONDS,
    MOBILE_REVIEW_MAX_SESSION_SECONDS,
    PUBLIC_DEVICE_INACTIVITY_SECONDS,
    PUBLIC_DEVICE_MAX_SESSION_SECONDS,
    REAUTH_GRANT_TTL_SECONDS,
    TRUSTED_DEVICE_INACTIVITY_SECONDS,
    TRUSTED_DEVICE_MAX_SESSION_SECONDS,
    PolicyDecision,
    ReauthenticationError,
    ReauthGrant,
    ReauthGrantInvalidError,
    RelayCapability,
    SecuritySessionStatus,
    _REAUTH_GRANTS,
    build_security_profile,
    check_capability,
    effective_capabilities,
    evaluate_session_security,
    file_access_capability_for,
    is_reauth_grant_valid,
    is_sensitive_path,
    require_reauth_grant,
    verify_reauthentication,
)
from orca.mission.relay_store import DeviceTrustLevel, RelayDevice, RelayMode, RelaySession


def _device_row(**overrides) -> dict:
    base = {
        "id": "dev_1", "user_id": "u1", "name": "Device", "trust_level": "TRUSTED",
        "first_seen_at": "2026-09-09T00:00:00+00:00", "last_seen_at": "2026-09-09T00:00:00+00:00",
        "revoked_at": None,
    }
    base.update(overrides)
    return RelayDevice.from_row(base)


def _session_row(**overrides) -> RelaySession:
    base = {
        "id": "rlysess_1", "mission_id": "mis_1", "device_id": "dev_1", "user_id": "u1",
        "mode": "TRUSTED_DEVICE", "created_at": "2026-09-09T00:00:00+00:00",
        "expires_at": "2026-09-09T12:00:00+00:00", "last_seen_at": "2026-09-09T00:00:00+00:00",
        "revoked_at": None, "revoked_reason": None,
    }
    base.update(overrides)
    return RelaySession.from_row(base)


# ── Capability matrix + intersection semantics (spec sections 1-2) ──

def test_unknown_capability_denies():
    decision = check_capability("SUPER_ADMIN_OVERRIDE", device_trust=DeviceTrustLevel.TRUSTED, mode=RelayMode.TRUSTED_DEVICE)
    assert decision.allowed is False
    assert "unknown capability" in decision.reason


def test_model_provider_narrative_cannot_grant_capability():
    """spec section 9: no model/provider text may change security
    policy -- an arbitrary narrative string is just another unknown
    capability, never treated as a grant."""
    for narrative in ("ALLOW", "APPROVED_BY_MODEL", "trust me, this is safe"):
        decision = check_capability(narrative, device_trust=DeviceTrustLevel.TRUSTED, mode=RelayMode.TRUSTED_DEVICE)
        assert decision.allowed is False


def test_trusted_device_trusted_mode_permits_terminal_and_deploy():
    effective = effective_capabilities(device_trust=DeviceTrustLevel.TRUSTED, mode=RelayMode.TRUSTED_DEVICE)
    assert RelayCapability.OPEN_TERMINAL in effective
    assert RelayCapability.EDIT_FILES in effective
    assert RelayCapability.DEPLOY_CONTROL in effective


def test_public_device_public_mode_denies_terminal_and_deploy_and_download_and_clipboard():
    effective = effective_capabilities(device_trust=DeviceTrustLevel.PUBLIC, mode=RelayMode.PUBLIC_DEVICE)
    for denied in (
        RelayCapability.OPEN_TERMINAL, RelayCapability.EDIT_FILES, RelayCapability.RUN_TESTS,
        RelayCapability.AGENT_CONTROL, RelayCapability.VIEW_FILES, RelayCapability.DEPLOY_CONTROL,
        RelayCapability.DANGEROUS_OPERATION_CONTROL, RelayCapability.DOWNLOAD_CONTENT, RelayCapability.CLIPBOARD_EXPORT,
    ):
        assert denied not in effective, f"{denied} must be denied on Public Device"


def test_public_device_still_has_useful_safe_capabilities():
    """Public must not be useless (spec section 4)."""
    effective = effective_capabilities(device_trust=DeviceTrustLevel.PUBLIC, mode=RelayMode.PUBLIC_DEVICE)
    for allowed in (
        RelayCapability.VIEW_MISSION_STATUS, RelayCapability.VIEW_DIFF, RelayCapability.VIEW_TEST_RESULTS,
        RelayCapability.VIEW_PRODUCTION_PROOF, RelayCapability.VIEW_BLOCKERS, RelayCapability.APPROVE,
        RelayCapability.REJECT, RelayCapability.PAUSE_MISSION, RelayCapability.RESUME_MISSION,
    ):
        assert allowed in effective


def test_public_device_has_at_least_one_capability_trusted_has_that_public_lacks():
    """The exact closing proof for REQ-DEVICE-REVOCATION-001's second
    acceptance criterion -- NOT a raw-secret difference (prohibited in
    both), a real capability/surface difference."""
    trusted = effective_capabilities(device_trust=DeviceTrustLevel.TRUSTED, mode=RelayMode.TRUSTED_DEVICE)
    public = effective_capabilities(device_trust=DeviceTrustLevel.PUBLIC, mode=RelayMode.PUBLIC_DEVICE)
    denied_to_public_permitted_to_trusted = trusted - public
    assert RelayCapability.OPEN_TERMINAL in denied_to_public_permitted_to_trusted
    assert RelayCapability.DEPLOY_CONTROL in denied_to_public_permitted_to_trusted


def test_mobile_review_denies_terminal_editor_and_direct_deploy():
    for device_trust in (DeviceTrustLevel.TRUSTED, DeviceTrustLevel.PUBLIC):
        effective = effective_capabilities(device_trust=device_trust, mode=RelayMode.MOBILE_REVIEW)
        for denied in (
            RelayCapability.OPEN_TERMINAL, RelayCapability.EDIT_FILES, RelayCapability.VIEW_FILES,
            RelayCapability.RUN_TESTS, RelayCapability.AGENT_CONTROL, RelayCapability.DEPLOY_CONTROL,
            RelayCapability.DANGEROUS_OPERATION_CONTROL,
        ):
            assert denied not in effective, f"{denied} must be denied in Mobile Review for {device_trust}"


def test_mobile_review_permits_its_canonical_review_surface():
    effective = effective_capabilities(device_trust=DeviceTrustLevel.TRUSTED, mode=RelayMode.MOBILE_REVIEW)
    for allowed in (
        RelayCapability.VIEW_MISSION_STATUS, RelayCapability.VIEW_DIFF, RelayCapability.VIEW_TEST_RESULTS,
        RelayCapability.VIEW_PRODUCTION_PROOF, RelayCapability.VIEW_BLOCKERS, RelayCapability.MESSAGE_AGENT,
        RelayCapability.APPROVE, RelayCapability.REJECT, RelayCapability.PAUSE_MISSION,
        RelayCapability.RESUME_MISSION, RelayCapability.REVOKE_SESSION,
    ):
        assert allowed in effective


def test_public_device_cannot_gain_privilege_by_choosing_trusted_device_mode():
    """spec section 2's canonical invariant: PUBLIC device + TRUSTED_DEVICE
    session mode request must still yield PUBLIC restrictions at the
    capability layer -- intersection, never union."""
    effective = effective_capabilities(device_trust=DeviceTrustLevel.PUBLIC, mode=RelayMode.TRUSTED_DEVICE)
    for denied in (RelayCapability.OPEN_TERMINAL, RelayCapability.EDIT_FILES, RelayCapability.DEPLOY_CONTROL):
        assert denied not in effective


def test_trusted_device_choosing_public_mode_gets_public_restrictions_not_trusted_capabilities():
    effective = effective_capabilities(device_trust=DeviceTrustLevel.TRUSTED, mode=RelayMode.PUBLIC_DEVICE)
    expected = effective_capabilities(device_trust=DeviceTrustLevel.PUBLIC, mode=RelayMode.PUBLIC_DEVICE)
    assert effective == expected
    assert RelayCapability.OPEN_TERMINAL not in effective


def test_privilege_cannot_increase_through_any_mode_swap_on_a_public_device():
    for mode in RelayMode:
        effective = effective_capabilities(device_trust=DeviceTrustLevel.PUBLIC, mode=mode)
        assert RelayCapability.OPEN_TERMINAL not in effective
        assert RelayCapability.DEPLOY_CONTROL not in effective
        assert RelayCapability.EDIT_FILES not in effective


# ── check_capability() is now a PURE STATIC query -- no reauth_valid (15.12.1 item 1) ──

def test_check_capability_has_no_reauth_valid_parameter():
    """15.12.1 item 1: the exact parameter that let a caller
    manufacture ALLOW for a reauth-gated capability is GONE."""
    import inspect
    sig = inspect.signature(check_capability)
    assert "reauth_valid" not in sig.parameters


def test_check_capability_marks_deploy_control_requires_reauth_and_authority():
    decision = check_capability(RelayCapability.DEPLOY_CONTROL, device_trust=DeviceTrustLevel.TRUSTED, mode=RelayMode.TRUSTED_DEVICE)
    assert decision.requires_reauthentication is True
    assert decision.requires_authority is True
    # Statically policy-eligible -- but this does NOT mean currently
    # authorized; only authorize_relay_capability() (live-Neon tests)
    # makes that determination, after validating a REAL grant.
    assert decision.allowed is True


def test_check_capability_harmless_read_never_requires_reauth():
    decision = check_capability(RelayCapability.VIEW_MISSION_STATUS, device_trust=DeviceTrustLevel.TRUSTED, mode=RelayMode.TRUSTED_DEVICE)
    assert decision.allowed is True
    assert decision.requires_reauthentication is False


def test_check_capability_public_device_deploy_control_requires_trusted_device_approval():
    decision = check_capability(RelayCapability.DEPLOY_CONTROL, device_trust=DeviceTrustLevel.PUBLIC, mode=RelayMode.PUBLIC_DEVICE)
    assert decision.allowed is False
    assert decision.requires_trusted_device_approval is True


def test_authorize_relay_capability_has_no_reauth_valid_parameter():
    """The authoritative gate also has no way to accept a boolean --
    only a real `reauth_grant` object, which is itself validated
    against the server-side store (see live-Neon tests for the full
    durable-state-loading behavior)."""
    import inspect
    from orca.mission.relay_security import authorize_relay_capability
    sig = inspect.signature(authorize_relay_capability)
    assert "reauth_valid" not in sig.parameters
    assert "device_trust" not in sig.parameters  # never accepted from the caller (15.12.1 item 2)
    assert "mode" not in sig.parameters  # never accepted from the caller (15.12.1 item 2)


# ── Session security validation (spec section 11) ────────────────────

def test_evaluate_session_security_active_before_inactivity_boundary():
    session = _session_row(mode="TRUSTED_DEVICE", last_seen_at="2026-09-09T00:00:00+00:00")
    device = _device_row(trust_level="TRUSTED")
    now = datetime(2026, 9, 9, 0, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=TRUSTED_DEVICE_INACTIVITY_SECONDS - 1)
    assert evaluate_session_security(session, device, now=now) is SecuritySessionStatus.ACTIVE


def test_evaluate_session_security_inactivity_expired_at_boundary():
    session = _session_row(mode="TRUSTED_DEVICE", last_seen_at="2026-09-09T00:00:00+00:00")
    device = _device_row(trust_level="TRUSTED")
    now = datetime(2026, 9, 9, 0, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=TRUSTED_DEVICE_INACTIVITY_SECONDS)
    assert evaluate_session_security(session, device, now=now) is SecuritySessionStatus.INACTIVITY_EXPIRED


def test_evaluate_session_security_public_inactivity_is_much_shorter():
    session = _session_row(mode="PUBLIC_DEVICE", last_seen_at="2026-09-09T00:00:00+00:00")
    device = _device_row(trust_level="PUBLIC")
    just_after_public_limit = datetime(2026, 9, 9, 0, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=PUBLIC_DEVICE_INACTIVITY_SECONDS + 1)
    assert evaluate_session_security(session, device, now=just_after_public_limit) is SecuritySessionStatus.INACTIVITY_EXPIRED
    assert PUBLIC_DEVICE_INACTIVITY_SECONDS < TRUSTED_DEVICE_INACTIVITY_SECONDS


def test_evaluate_session_security_revoked_takes_priority_over_inactivity():
    session = _session_row(mode="TRUSTED_DEVICE", last_seen_at="2026-09-09T00:00:00+00:00", revoked_at="2026-09-09T00:00:01+00:00")
    device = _device_row(trust_level="TRUSTED")
    now = datetime(2026, 9, 9, 0, 0, 2, tzinfo=timezone.utc)
    assert evaluate_session_security(session, device, now=now) is SecuritySessionStatus.REVOKED


def test_evaluate_session_security_device_revoked():
    session = _session_row(mode="TRUSTED_DEVICE")
    device = _device_row(trust_level="TRUSTED", revoked_at="2026-09-09T00:00:01+00:00")
    now = datetime(2026, 9, 9, 0, 0, 2, tzinfo=timezone.utc)
    assert evaluate_session_security(session, device, now=now) is SecuritySessionStatus.DEVICE_REVOKED


def test_evaluate_session_security_device_mode_mismatch():
    """A PUBLIC device somehow carrying a TRUSTED_DEVICE-mode session
    row (e.g. from data corruption, not the normal creation path,
    which is separately guarded) must be flagged, not silently ACTIVE."""
    session = _session_row(mode="TRUSTED_DEVICE")
    device = _device_row(trust_level="PUBLIC")
    now = datetime(2026, 9, 9, 0, 0, 1, tzinfo=timezone.utc)
    assert evaluate_session_security(session, device, now=now) is SecuritySessionStatus.DEVICE_MODE_MISMATCH


# ── TTL / inactivity policy constants (spec sections 9-10) ───────────

def test_public_device_max_lifetime_is_materially_shorter_than_trusted():
    assert PUBLIC_DEVICE_MAX_SESSION_SECONDS < TRUSTED_DEVICE_MAX_SESSION_SECONDS
    assert PUBLIC_DEVICE_MAX_SESSION_SECONDS <= TRUSTED_DEVICE_MAX_SESSION_SECONDS / 2


def test_all_ttl_and_inactivity_constants_are_positive_and_named():
    for value in (
        TRUSTED_DEVICE_MAX_SESSION_SECONDS, PUBLIC_DEVICE_MAX_SESSION_SECONDS, MOBILE_REVIEW_MAX_SESSION_SECONDS,
        TRUSTED_DEVICE_INACTIVITY_SECONDS, PUBLIC_DEVICE_INACTIVITY_SECONDS, MOBILE_REVIEW_INACTIVITY_SECONDS,
        REAUTH_GRANT_TTL_SECONDS,
    ):
        assert isinstance(value, int) and value > 0


def test_create_relay_session_has_no_caller_controlled_ttl_parameter():
    """spec section 9: no normal route may let a caller choose an
    arbitrary security-mode TTL."""
    import inspect
    from orca.mission.relay_security import create_relay_session
    sig = inspect.signature(create_relay_session)
    assert "ttl_seconds" not in sig.parameters
    assert "expires_in" not in sig.parameters


def test_verify_reauthentication_has_no_caller_controlled_ttl_parameter():
    """15.12.1 item 5: the public reauthentication API has no way to
    request an arbitrary grant lifetime."""
    import inspect
    sig = inspect.signature(verify_reauthentication)
    assert "ttl_seconds" not in sig.parameters
    assert "expires_in" not in sig.parameters


def test_verify_reauthentication_has_no_email_parameter():
    """15.12.1 item 4: the account is derived from `authenticated_user_id`,
    never selected independently via an `email` argument."""
    import inspect
    sig = inspect.signature(verify_reauthentication)
    assert "email" not in sig.parameters
    assert "authenticated_user_id" in sig.parameters


# ── Sensitive file policy (spec section 17) ──────────────────────────

@pytest.mark.parametrize("path", [
    ".env", ".env.production", "config/.env.local", "id_rsa", "id_rsa.pub",
    "certs/server.pem", "keys/signing.key", "creds/service-account.json",
    "kubeconfig", "secrets/credential_store.json",
])
def test_sensitive_paths_detected(path):
    assert is_sensitive_path(path) is True


@pytest.mark.parametrize("path", ["README.md", "src/main.py", "tests/test_foo.py", "package.json"])
def test_ordinary_paths_not_flagged_sensitive(path):
    assert is_sensitive_path(path) is False


def test_file_access_capability_denies_sensitive_path_on_public_device():
    assert file_access_capability_for(".env", device_trust=DeviceTrustLevel.PUBLIC) is None


def test_file_access_capability_permits_sensitive_path_lookup_on_trusted_device():
    """Trusted may inspect project files (spec section 17) -- the
    separate raw-secret-VALUE prohibition is enforced elsewhere
    (orca.mission.relay_store._sanitize()), not by denying the path
    reference itself."""
    assert file_access_capability_for(".env", device_trust=DeviceTrustLevel.TRUSTED) is RelayCapability.VIEW_FILES


def test_file_access_capability_ordinary_path_allowed_both_trust_levels():
    for trust in (DeviceTrustLevel.TRUSTED, DeviceTrustLevel.PUBLIC):
        assert file_access_capability_for("src/main.py", device_trust=trust) is RelayCapability.VIEW_FILES


# ── Security profile / Public Device indicator (spec sections 15-16) ──

def test_build_security_profile_public_device_indicator_true():
    session = _session_row(mode="PUBLIC_DEVICE")
    device = _device_row(trust_level="PUBLIC")
    profile = build_security_profile(session, device)
    assert profile.public_device is True
    assert profile.clipboard_export_allowed is False
    assert profile.download_allowed is False


def test_build_security_profile_trusted_device_indicator_false():
    session = _session_row(mode="TRUSTED_DEVICE")
    device = _device_row(trust_level="TRUSTED")
    profile = build_security_profile(session, device)
    assert profile.public_device is False


def test_build_security_profile_mobile_review_flag():
    session = _session_row(mode="MOBILE_REVIEW")
    device = _device_row(trust_level="TRUSTED")
    profile = build_security_profile(session, device)
    assert profile.mobile_review is True


def test_build_security_profile_mobile_on_public_device_still_shows_public_restriction():
    """If Mobile runs on a Public device, the payload must still show
    the underlying Public trust restriction (spec section 15)."""
    session = _session_row(mode="MOBILE_REVIEW")
    device = _device_row(trust_level="PUBLIC")
    profile = build_security_profile(session, device)
    assert profile.mobile_review is True
    assert profile.public_device is True
    assert profile.clipboard_export_allowed is False
    assert profile.download_allowed is False


def test_build_security_profile_restricted_capabilities_lists_denied_ones_for_public():
    session = _session_row(mode="PUBLIC_DEVICE")
    device = _device_row(trust_level="PUBLIC")
    profile = build_security_profile(session, device)
    assert "OPEN_TERMINAL" in profile.restricted_capabilities
    assert "DEPLOY_CONTROL" in profile.restricted_capabilities
    assert "VIEW_MISSION_STATUS" not in profile.restricted_capabilities


# ── Real (non-mocked) reauthentication with REAL server-side grant provenance ──
# (spec sections 7-8, 29; hardened 15.12.1 items 3-5)

def _make_user(store, password="Correct-Horse-Battery-9", totp_enabled=False):
    import uuid as _uuid
    email = f"reauth-{_uuid.uuid4().hex[:16]}@example.com"
    user = store.create_user(email, password)
    if totp_enabled:
        from orca.auth.totp import generate_totp_secret
        secret = generate_totp_secret()
        store.set_pending_totp_secret(user.id, secret)
        store.enable_totp(user.id)
        return user, secret
    return user, None


def test_correct_password_no_totp_yields_valid_grant(isolated_home):
    user, _ = _make_user(isolated_home, password="Correct-Horse-Battery-9")
    grant = verify_reauthentication(authenticated_user_id=user.id, password="Correct-Horse-Battery-9")
    assert isinstance(grant, ReauthGrant)
    assert is_reauth_grant_valid(grant, authenticated_user_id=user.id) is True


def test_wrong_password_denies(isolated_home):
    user, _ = _make_user(isolated_home, password="Correct-Horse-Battery-9")
    with pytest.raises(ReauthenticationError):
        verify_reauthentication(authenticated_user_id=user.id, password="totally-wrong-password")


def test_totp_enabled_correct_password_and_valid_totp_succeeds(isolated_home):
    from orca.auth.totp import totp_now
    user, secret = _make_user(isolated_home, password="Correct-Horse-Battery-9", totp_enabled=True)
    now = datetime.now(timezone.utc)
    code = totp_now(secret, at_time=now.timestamp())
    grant = verify_reauthentication(authenticated_user_id=user.id, password="Correct-Horse-Battery-9", totp_code=code, now_fn=lambda: now)
    assert is_reauth_grant_valid(grant, authenticated_user_id=user.id, now=now) is True


def test_totp_enabled_missing_code_denies(isolated_home):
    user, _ = _make_user(isolated_home, password="Correct-Horse-Battery-9", totp_enabled=True)
    with pytest.raises(ReauthenticationError):
        verify_reauthentication(authenticated_user_id=user.id, password="Correct-Horse-Battery-9")


def test_totp_enabled_wrong_code_denies(isolated_home):
    user, _ = _make_user(isolated_home, password="Correct-Horse-Battery-9", totp_enabled=True)
    with pytest.raises(ReauthenticationError):
        verify_reauthentication(authenticated_user_id=user.id, password="Correct-Horse-Battery-9", totp_code="000000")


def test_no_credential_values_stored_on_grant_record(isolated_home):
    user, _ = _make_user(isolated_home, password="Correct-Horse-Battery-9")
    grant = verify_reauthentication(authenticated_user_id=user.id, password="Correct-Horse-Battery-9")
    dumped = repr(grant)
    assert "Correct-Horse-Battery-9" not in dumped
    record = _REAUTH_GRANTS[grant.grant_id]
    assert "Correct-Horse-Battery-9" not in repr(record)


def test_no_alternate_account_selectable_through_authenticated_user_id_a(isolated_home):
    """15.12.1 item 4 adversarial case: user A's request cannot
    reauthenticate as user B merely by knowing B's password -- the
    account is looked up FROM `authenticated_user_id`, so calling with
    A's id and B's password fails as A's OWN wrong password, never
    succeeds as B."""
    user_a, _ = _make_user(isolated_home, password="Password-For-A-123")
    user_b, _ = _make_user(isolated_home, password="Password-For-B-456")
    with pytest.raises(ReauthenticationError):
        verify_reauthentication(authenticated_user_id=user_a.id, password="Password-For-B-456")
    # A's own real password still works.
    grant = verify_reauthentication(authenticated_user_id=user_a.id, password="Password-For-A-123")
    assert is_reauth_grant_valid(grant, authenticated_user_id=user_a.id) is True
    assert is_reauth_grant_valid(grant, authenticated_user_id=user_b.id) is False


# ── Forged/fabricated grant adversarial matrix (15.12.1 item 3) ──────

def test_fabricated_grant_with_random_id_is_rejected():
    fake = ReauthGrant(grant_id="totally-made-up-id-12345")
    assert is_reauth_grant_valid(fake, authenticated_user_id="u1") is False


def test_arbitrary_object_with_grant_id_attribute_is_rejected():
    fake = SimpleNamespace(grant_id="another-made-up-id")
    assert is_reauth_grant_valid(fake, authenticated_user_id="u1") is False


def test_object_missing_grant_id_entirely_is_rejected_not_crashed():
    fake = SimpleNamespace(user_id="u1")
    assert is_reauth_grant_valid(fake, authenticated_user_id="u1") is False


def test_none_grant_is_rejected():
    assert is_reauth_grant_valid(None, authenticated_user_id="u1") is False


def test_copied_grant_id_string_but_wrong_type_is_rejected():
    """A real, currently-valid grant_id string copied out and handed
    back as a bare string (not wrapped in a ReauthGrant) has no
    `.grant_id` attribute of its own and must be rejected, not
    accidentally treated as valid."""
    assert is_reauth_grant_valid("some-real-looking-grant-id-string", authenticated_user_id="u1") is False


def test_real_grant_for_user_a_cannot_authorize_user_b(isolated_home):
    user_a, _ = _make_user(isolated_home, password="Password-For-A-123")
    user_b, _ = _make_user(isolated_home, password="Password-For-B-456")
    grant = verify_reauthentication(authenticated_user_id=user_a.id, password="Password-For-A-123")
    assert is_reauth_grant_valid(grant, authenticated_user_id=user_b.id) is False


def test_real_grant_for_session_a_cannot_authorize_session_b(isolated_home):
    user, _ = _make_user(isolated_home, password="Correct-Horse-Battery-9")
    grant = verify_reauthentication(authenticated_user_id=user.id, password="Correct-Horse-Battery-9", relay_session_id="rlysess_A")
    assert is_reauth_grant_valid(grant, authenticated_user_id=user.id, relay_session_id="rlysess_B") is False
    assert is_reauth_grant_valid(grant, authenticated_user_id=user.id, relay_session_id="rlysess_A") is True


def test_real_grant_expires(isolated_home):
    base_now = datetime.now(timezone.utc)
    user, _ = _make_user(isolated_home, password="Correct-Horse-Battery-9")
    grant = verify_reauthentication(authenticated_user_id=user.id, password="Correct-Horse-Battery-9", now_fn=lambda: base_now)
    still_valid_time = base_now + timedelta(seconds=REAUTH_GRANT_TTL_SECONDS - 1)
    expired_time = base_now + timedelta(seconds=REAUTH_GRANT_TTL_SECONDS + 1)
    assert is_reauth_grant_valid(grant, authenticated_user_id=user.id, now=still_valid_time) is True
    assert is_reauth_grant_valid(grant, authenticated_user_id=user.id, now=expired_time) is False


def test_require_reauth_grant_raises_on_fabricated_grant():
    fake = ReauthGrant(grant_id="fabricated")
    with pytest.raises(ReauthGrantInvalidError):
        require_reauth_grant(fake, authenticated_user_id="u1")


def test_require_reauth_grant_raises_on_none():
    with pytest.raises(ReauthGrantInvalidError):
        require_reauth_grant(None, authenticated_user_id="u1")


def test_grant_store_reset_simulates_process_restart_fails_closed(isolated_home):
    """spec section 15 item 3: a process restart invalidates every
    outstanding grant -- fail closed, never fail open. Simulated here
    by directly clearing the in-process store (the exact effect a
    real restart would have, since it is an in-process dict)."""
    user, _ = _make_user(isolated_home, password="Correct-Horse-Battery-9")
    grant = verify_reauthentication(authenticated_user_id=user.id, password="Correct-Horse-Battery-9")
    assert is_reauth_grant_valid(grant, authenticated_user_id=user.id) is True

    saved = dict(_REAUTH_GRANTS)
    try:
        _REAUTH_GRANTS.clear()
        assert is_reauth_grant_valid(grant, authenticated_user_id=user.id) is False
    finally:
        _REAUTH_GRANTS.clear()
        _REAUTH_GRANTS.update(saved)
