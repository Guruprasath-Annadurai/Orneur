"""Auth API routes — signup, login, me, logout."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from orca.auth.crypto import create_token
from orca.auth.crypto import verify_token
from orca.auth.middleware import _bearer, get_current_user
from orca.auth.store import (
    DAILY_LIMITS,
    User,
    authenticate,
    create_user,
    get_usage_today,
    get_user_by_email,
    get_user_by_id,
    set_user_tier,
    set_user_role,
    list_users,
    set_pending_totp_secret,
    enable_totp,
    disable_totp,
    get_totp_state,
)
from orca.auth.apikeys import create_key, list_keys, revoke_key
from orca.auth.rbac import require_permission
from orca.auth.tokens import (
    make_verification_token, make_reset_token, make_2fa_pending_token,
    verify_token as verify_auth_token,
)
from orca.auth.totp import generate_totp_secret, verify_totp, provisioning_uri, matching_step as verify_totp_step
from orca.auth.email import send_verification, send_password_reset, is_configured as email_configured
from orca.auth import account_security as acct
from orca.serve import ratelimit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


def _make_response(user: User) -> dict:
    token  = create_token({"sub": user.id, "type": "session", "jti": uuid.uuid4().hex, "email": user.email, "tier": user.tier, "role": user.role})
    limits = DAILY_LIMITS.get(user.tier, DAILY_LIMITS["free"])
    usage  = get_usage_today(user.id)
    return {
        "token": token,
        "user": {
            "id":    user.id,
            "email": user.email,
            "name":  user.name,
            "tier":  user.tier,
            "role":  user.role,
        },
        "limits": limits,
        "usage":  usage,
    }


def _dummy_password_work(password: str) -> None:
    """Spend the same CPU a real account creation / password check spends, so response time does not reveal whether an address is registered."""
    from orca.auth.crypto import hash_password

    hash_password(password)


def _send_verification_link(user) -> bool:
    ok, _ = acct.may_send(user.id, "verify")
    if not ok:
        return False
    jti = acct.issue(user.id, "verify", user.email, acct.VERIFY_TTL_S)
    return send_verification(user.email, make_verification_token(user.id, user.email, jti))


@router.post("/signup")
async def signup(req: SignupRequest, request: Request):
    ratelimit.enforce(request, ratelimit.AUTH_SIGNUP)
    from orca.auth.bootstrap import signup_blocked_until_bootstrap
    if signup_blocked_until_bootstrap():
        # G-021: a public deployment with no owner is not open for ordinary signups.
        raise HTTPException(503, detail={"error": "This deployment has not been initialized.", "code": "owner_not_initialized"})
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if "@" not in req.email or "." not in req.email.split("@")[-1]:
        raise HTTPException(400, "Invalid email address")
    existing = get_user_by_email(req.email)
    if acct.verification_required():
        # L02-04: enumeration-resistant signup. A new and an already-registered address get the SAME response (and similar work); the only difference is in the inbox
        # of whoever owns the address. No session is issued before the address is proven.
        from fastapi.responses import JSONResponse

        generic = {"status": "verification_required", "message": "If this address can be registered, we have sent a verification link to it. Open it to finish creating your account."}
        if existing:
            await _asyncio_to_thread(_dummy_password_work, req.password)
            ok, _ = acct.may_send(existing.id, "exists_notice")
            if ok:
                from orca.auth.email import send_email
                send_email(existing.email, "Someone tried to create an ORNEUR account with your address",
                           "<p>Someone used this address to sign up. If it was you, sign in instead (or reset your password). If not, ignore this message.</p>",
                           "Someone used this address to sign up for ORNEUR. If it was you, sign in instead or reset your password. If not, ignore this message.")
            return JSONResponse(generic, status_code=202)
        try:
            user = create_user(req.email, req.password, req.name)
        except Exception:
            raise HTTPException(500, detail={"error": "Could not create the account right now. Please try again.", "code": "internal_error"})
        try:
            from orca.auth.privacy import init_default_consents
            init_default_consents(user.id)
        except Exception:
            pass
        _send_verification_link(user)
        return JSONResponse(generic, status_code=202)
    # No verified delivery path is configured: the legacy behaviour (immediate session, duplicate reported) is kept and its limits are DISCLOSED by
    # GET /api/auth/email-status (verification_required=false, delivery!=smtp). Enumeration resistance needs verified delivery.
    if existing:
        raise HTTPException(409, "An account with this email already exists")
    try:
        user = create_user(req.email, req.password, req.name)
    except Exception:
        raise HTTPException(500, detail={"error": "Could not create the account right now. Please try again.", "code": "internal_error"})
    # Seeds the one consent record that isn't really optional (strictly
    # necessary cookies) — best-effort, a failure here shouldn't block
    # account creation, same reasoning as the verification email below.
    try:
        from orca.auth.privacy import init_default_consents
        init_default_consents(user.id)
    except Exception:
        pass
    # Send verification email (non-blocking best-effort)
    if email_configured():
        _send_verification_link(user)
    return _make_response(user)


async def _asyncio_to_thread(fn, *a):
    import asyncio

    return await asyncio.to_thread(fn, *a)


class BootstrapOwnerRequest(BaseModel):
    token: str
    email: str
    password: str
    name: str = ""


@router.get("/bootstrap-status")
async def bootstrap_status():
    """Public and deliberately minimal: whether an owner exists. Never names the owner."""
    from orca.auth.bootstrap import owner_exists
    return {"initialized": owner_exists()}


@router.post("/bootstrap-owner")
async def bootstrap_owner(req: BootstrapOwnerRequest, request: Request):
    """Redeem an operator-issued, single-use, email-bound token (`python -m orca.auth.bootstrap issue`). One-time; see orca/auth/bootstrap.py."""
    ratelimit.enforce(request, ratelimit.AUTH_LOGIN, extra_key="bootstrap_owner")
    from orca import audit
    from orca.auth.bootstrap import BootstrapError, redeem
    try:
        user = redeem(req.token, req.email, req.password, req.name)
    except BootstrapError as e:
        audit.log("owner_bootstrap_refused", detail={"code": e.code})
        status = 409 if e.code == "already_initialized" else 403
        raise HTTPException(status, detail={"error": "Owner bootstrap was refused.", "code": e.code})
    audit.log("owner_bootstrap_completed", user_id=user.id, detail={"method": "token"})
    return _make_response(user)


class RetentionRequest(BaseModel):
    retention_days: int


@router.get("/settings/retention")
async def get_retention(user: User = Depends(get_current_user)):
    from orca.auth.store import get_retention_days

    return {"retention_days": get_retention_days(user.id), "meaning": "0 keeps conversations until you delete them; N deletes conversations idle for N days"}


@router.put("/settings/retention")
async def put_retention(req: RetentionRequest, user: User = Depends(get_current_user)):
    from orca import audit
    from orca.auth.store import set_retention_days

    if not (req.retention_days == 0 or 1 <= req.retention_days <= 3650):
        raise HTTPException(422, detail={"error": "retention_days must be 0 or between 1 and 3650.", "code": "invalid_request"})
    set_retention_days(user.id, req.retention_days)
    audit.log("retention_changed", user_id=user.id, detail={"retention_days": req.retention_days})
    return {"retention_days": req.retention_days}


@router.post("/logout")
async def logout(user: User = Depends(get_current_user), creds=Depends(_bearer)):
    """Revokes THIS session token. A token without a `jti` (issued before this release) cannot be singled out, so it signs the user out everywhere."""
    from orca.auth.store import invalidate_all_sessions, revoke_token

    payload = verify_token(creds.credentials) if creds and not creds.credentials.startswith("athr_") else None
    if payload is None:
        raise HTTPException(400, detail={"error": "API keys are revoked with DELETE /api/auth/apikeys/{id}.", "code": "invalid_request"})
    jti = payload.get("jti")
    if jti:
        revoke_token(jti, user.id, float(payload.get("exp", 0)))
        scope = "this_session"
    else:
        invalidate_all_sessions(user.id)
        scope = "all_sessions"
    from orca import audit
    audit.log("logout", user_id=user.id, detail={"scope": scope})
    return {"revoked": scope}


@router.post("/logout-all")
async def logout_all(user: User = Depends(get_current_user)):
    from orca import audit
    from orca.auth.store import invalidate_all_sessions

    invalidate_all_sessions(user.id)
    audit.log("logout_all", user_id=user.id, detail={})
    return {"revoked": "all_sessions"}


@router.post("/login")
async def login(req: LoginRequest, request: Request):
    ratelimit.enforce(request, ratelimit.AUTH_LOGIN)
    from fastapi.responses import JSONResponse

    wait = acct.login_locked(req.email)
    if wait > 0:
        # L02-04: per-account lockout, identical for existing and non-existing addresses (so it reveals nothing about who is registered).
        return JSONResponse({"detail": "Too many failed attempts. Try again later.", "error": "Too many failed attempts. Try again later.", "code": "too_many_attempts"},
                            status_code=429, headers={"Retry-After": str(int(wait) + 1)})
    user = await _asyncio_to_thread(_authenticate_constant_time, req.email, req.password)
    if not user:
        acct.record_login_failure(req.email)
        raise HTTPException(401, "Invalid email or password")
    acct.clear_login_failures(req.email)

    if acct.verification_required() and not user.verified:
        raise HTTPException(403, detail={"error": "Verify your email address to sign in. Check your inbox for the verification link.", "code": "email_verification_required"})

    totp_state = get_totp_state(user.id)
    if totp_state["enabled"]:
        # Password checked out, but 2FA is on — don't hand out a real session
        # token yet. pending_token proves "already knows the password" without
        # granting access; the client exchanges it for a real token at
        # /api/auth/2fa/verify-login once it has the TOTP code.
        pending_token = make_2fa_pending_token(user.id, user.email)
        return {"requires_2fa": True, "pending_token": pending_token}

    return _make_response(user)


def _authenticate_constant_time(email: str, password: str):
    """``authenticate`` plus equal work for an unknown address (otherwise a missing account answers measurably faster than a wrong password)."""
    user = authenticate(email, password)
    if user is None and get_user_by_email(email) is None:
        _dummy_password_work(password)
    return user


class TwoFAVerifyLoginRequest(BaseModel):
    pending_token: str
    code: str


@router.post("/2fa/verify-login")
async def verify_login_2fa(req: TwoFAVerifyLoginRequest, request: Request):
    """Exchanges a pending_token (from /login, after password check) + a TOTP code for a real session token."""
    ratelimit.enforce(request, ratelimit.AUTH_LOGIN)
    payload = verify_auth_token(req.pending_token, "2fa_pending")
    if not payload:
        raise HTTPException(401, "2FA session expired or invalid — log in again.")

    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(404, "User not found")

    totp_state = get_totp_state(user.id)
    if not totp_state["enabled"] or not totp_state["secret"]:
        raise HTTPException(400, "2FA is not enabled on this account.")

    # P1-D: the second factor is bounded per ACCOUNT (not only per IP) and every code is single-use, exactly like the API-key step-up.
    wait = acct.stepup_locked(user.id)
    if wait > 0:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Too many failed attempts. Try again later.", "error": "Too many failed attempts. Try again later.", "code": "too_many_attempts"},
                            status_code=429, headers={"Retry-After": str(int(wait) + 1)})
    step = verify_totp_step(totp_state["secret"], req.code)
    if step is None or not acct.claim_totp_step(user.id, step):
        acct.record_stepup_failure(user.id)
        from orca import audit
        audit.log("mfa_login_failed", user_id=user.id, detail={"reason": "invalid" if step is None else "replayed"})
        raise HTTPException(401, "Invalid or expired code.")
    acct.clear_stepup_failures(user.id)

    return _make_response(user)


@router.post("/2fa/setup")
async def setup_2fa(user: User = Depends(get_current_user)):
    """
    Generates a new TOTP secret WITHOUT enabling 2FA yet — the user must
    scan/enter it into their authenticator app and prove a valid code via
    /2fa/enable before it takes effect. Overwrites any previous pending
    (not-yet-enabled) secret; does NOT touch an already-enabled 2FA setup —
    call /2fa/disable first if you want to redo an active setup.
    """
    existing = get_totp_state(user.id)
    if existing["enabled"]:
        raise HTTPException(400, "2FA is already enabled. Disable it first to set up a new device.")

    secret = generate_totp_secret()
    set_pending_totp_secret(user.id, secret)
    uri = provisioning_uri(secret, user.email)
    return {"secret": secret, "provisioning_uri": uri}


class TwoFAEnableRequest(BaseModel):
    code: str


@router.post("/2fa/enable")
async def enable_2fa(req: TwoFAEnableRequest, user: User = Depends(get_current_user)):
    """Finalizes 2FA — requires a valid code from the secret issued by /2fa/setup, proving the app is actually working."""
    state = get_totp_state(user.id)
    if not state["secret"]:
        raise HTTPException(400, "No pending 2FA setup found. Call /2fa/setup first.")
    if state["enabled"]:
        raise HTTPException(400, "2FA is already enabled.")

    if not verify_totp(state["secret"], req.code):
        raise HTTPException(401, "Invalid code — check your authenticator app and try again.")

    enable_totp(user.id)
    return {"enabled": True}


class TwoFADisableRequest(BaseModel):
    code: str


@router.post("/2fa/disable")
async def disable_2fa(req: TwoFADisableRequest, user: User = Depends(get_current_user)):
    """
    Requires a valid current TOTP code to disable — not just an active
    session. Without this, anyone who hijacks a logged-in session (XSS,
    stolen token, etc.) could silently turn off 2FA and lock out the real
    owner's recovery path.
    """
    state = get_totp_state(user.id)
    if not state["enabled"]:
        raise HTTPException(400, "2FA is not enabled on this account.")
    wait = acct.stepup_locked(user.id)
    if wait > 0:
        raise HTTPException(429, "Too many failed attempts. Try again later.", headers={"Retry-After": str(int(wait) + 1)})
    step = verify_totp_step(state["secret"], req.code)
    if step is None or not acct.claim_totp_step(user.id, step):
        acct.record_stepup_failure(user.id)
        raise HTTPException(401, "Invalid code.")
    acct.clear_stepup_failures(user.id)

    disable_totp(user.id)
    return {"enabled": False}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    limits = DAILY_LIMITS.get(user.tier, DAILY_LIMITS["free"])
    usage  = get_usage_today(user.id)
    totp_state = get_totp_state(user.id)
    return {
        "user":   {
            "id": user.id, "email": user.email, "name": user.name,
            "tier": user.tier, "role": user.role, "totp_enabled": totp_state["enabled"],
            "email_verified": bool(user.verified), "email_verification_required": acct.verification_required(),
        },
        "limits": limits,
        "usage":  usage,
    }


# ── Email / password routes ───────────────────────────────────────────────────

class ForgotRequest(BaseModel):
    email: str


class ResetRequest(BaseModel):
    token: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    totp_code: str | None = None      # required when the account has 2FA enabled


@router.get("/email-status")
async def email_status():
    """What email delivery this deployment actually has. ``real_delivery`` is true only for a configured SMTP provider; ``local_sink`` writes messages to a local directory
    and delivers to nobody (engineering / controlled staging)."""
    from orca.auth.email import delivery_mode, real_delivery

    return {"configured": email_configured(), "delivery": delivery_mode(), "real_delivery": real_delivery(), "verification_required": acct.verification_required()}


@router.post("/signup/resend-verification")
async def resend_verification(user: User = Depends(get_current_user)):
    if user.verified:
        raise HTTPException(400, "Account already verified")
    ok, retry_after = acct.may_send(user.id, "verify")
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "A verification email was sent recently. Please wait before requesting another.", "error": "A verification email was sent recently. Please wait before requesting another.",
                             "code": "rate_limited", "retry_after": int(retry_after) + 1}, status_code=429, headers={"Retry-After": str(int(retry_after) + 1)})
    jti = acct.issue(user.id, "verify", user.email, acct.VERIFY_TTL_S)
    sent = send_verification(user.email, make_verification_token(user.id, user.email, jti))
    return {"sent": sent, "email_configured": email_configured()}


class ResendByEmailRequest(BaseModel):
    email: str


@router.post("/verification/resend")
async def resend_verification_by_email(req: ResendByEmailRequest, request: Request):
    """Unauthenticated resend for someone who cannot sign in BECAUSE they are unverified (verification required). Always answers the same, whether or not the address is
    registered, already verified, or throttled; the per-account send ledger bounds how many messages any address can receive."""
    ratelimit.enforce(request, ratelimit.AUTH_FORGOT_PW, extra_key="verify_resend")
    user = get_user_by_email(req.email)
    if user is not None and not user.verified and acct.verification_required():
        _send_verification_link(user)
    else:
        await _asyncio_to_thread(_dummy_password_work, "timing-equalisation")
    return {"sent": True, "message": "If this address has an unverified account, a new verification link has been sent."}


_VERIFY_STYLE = ("<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                 "<style>body{background:#000;color:#e8e8e8;font-family:monospace;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}"
                 "div{text-align:center;padding:24px}button{background:#fff;color:#000;border:0;padding:12px 28px;font-weight:700;letter-spacing:.12em;font-family:monospace;cursor:pointer}</style></head><body><div>"
                 "<p style=\"letter-spacing:.35em;font-size:20px;color:#fff\">ORNEUR</p>")


def _verify_page(inner: str, status: int = 200):
    from fastapi.responses import HTMLResponse

    return HTMLResponse(_VERIFY_STYLE + inner + "</div></body></html>", status_code=status, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/verify")
async def verify_email(token: str):
    """Landing page for the emailed link. It does NOT verify anything: mail scanners and link previews fetch URLs, and that must not spend a single-use link. The person confirms
    with a button, which POSTs to /api/auth/verify."""
    import html as _html

    payload = verify_auth_token(token, "verify")
    user = get_user_by_id(payload["sub"]) if payload else None
    if not payload or user is None or not acct.peek(payload.get("jti"), user.id, "verify", user.email):
        return _verify_page("<h2>This verification link is invalid, expired or already used.</h2><p style=\"color:#888\">Request a new one from your account.</p>", 400)
    return _verify_page(f"<p style=\"color:#888;letter-spacing:.15em\">CONFIRM YOUR EMAIL</p><form method=\"post\" action=\"/api/auth/verify\">"
                        f"<input type=\"hidden\" name=\"token\" value=\"{_html.escape(token, quote=True)}\"><button type=\"submit\">CONFIRM EMAIL</button></form>")


@router.post("/verify")
async def verify_email_confirm(request: Request):
    from orca.auth.store import mark_verified

    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        token = str((await request.json()).get("token", ""))
    else:
        form = await request.form()
        token = str(form.get("token", ""))
    payload = verify_auth_token(token, "verify")
    user = get_user_by_id(payload["sub"]) if payload else None
    if not payload or user is None or not acct.consume(payload.get("jti"), user.id, "verify", user.email):
        return _verify_page("<h2>This verification link is invalid, expired or already used.</h2>", 400)
    mark_verified(user.id)
    from orca import audit
    audit.log("email_verified", user_id=user.id, detail={})
    return _verify_page("<p style=\"color:#888;letter-spacing:.15em;margin-top:8px\">EMAIL VERIFIED</p><p style=\"color:#555;margin-top:20px\">Your account is now active. <a href=\"/conversation\" style=\"color:#fff\">Return to ORNEUR →</a></p>")


@router.post("/forgot-password")
async def forgot_password(req: ForgotRequest, request: Request):
    ratelimit.enforce(request, ratelimit.AUTH_FORGOT_PW)
    user = get_user_by_email(req.email)
    if user:
        ok, _ = acct.may_send(user.id, "reset")        # per-account send ledger; a throttled request is indistinguishable to the caller
        if ok:
            jti = acct.issue(user.id, "reset", user.email, acct.RESET_TTL_S)
            send_password_reset(user.email, make_reset_token(user.id, user.email, jti))
    else:
        await _asyncio_to_thread(_dummy_password_work, "timing-equalisation")
    # Always return 200 — never reveal if email exists (or whether this request was throttled)
    return {"sent": True}


@router.post("/reset-password")
async def reset_password(req: ResetRequest):
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    payload = verify_auth_token(req.token, "reset")
    if not payload:
        raise HTTPException(400, "Reset link is invalid or expired")
    from orca.auth.store import update_password, get_user_by_id
    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(400, "Reset link is invalid or expired")       # same answer as an invalid link (no account-existence signal)
    # G-006 + L02-04: single use and bound to the account's CURRENT email. consume() is one atomic UPDATE; a replay, an expiry, a changed email or a
    # newer link all fail identically.
    if float(payload.get("iat", 0)) < user.tokens_valid_after or not acct.consume(payload.get("jti"), user.id, "reset", user.email):
        raise HTTPException(400, "Reset link is invalid or expired")
    update_password(user.id, req.password)                                # stamps tokens_valid_after: every session issued before now is dead
    # Recovery means the old credentials may be compromised: API keys minted with them are revoked too.
    try:
        from orca.auth.apikeys import list_keys as _list_keys, revoke_key as _revoke_key
        for k in _list_keys(user.id):
            _revoke_key(k["id"] if isinstance(k, dict) else k.id, user.id)
    except Exception:
        pass
    from orca import audit
    audit.log("password_reset", user_id=user.id, detail={"api_keys_revoked": True})
    user = get_user_by_id(user.id)
    # A reset proves control of the inbox, not possession of the second factor: an account with 2FA still has to pass it.
    if get_totp_state(user.id)["enabled"]:
        return {"requires_2fa": True, "pending_token": make_2fa_pending_token(user.id, user.email)}
    return _make_response(user)


async def _fresh_auth(user: User, password: str | None, totp_code: str | None, *, wrong_password_status: int = 401):
    """P1-D: fresh, server-verified authentication for a sensitive operation (same rules as API-key creation, L02-B3).

    Returns None when it succeeded, else the refusal response. The password is checked first; an account with 2FA must also present a single-use code. Failures are counted PER
    ACCOUNT (a stolen session token cannot guess at the IP rate limit); while locked even correct answers are refused.
    """
    wait = acct.stepup_locked(user.id)
    if wait > 0:
        return _reauth_refusal("too_many_attempts", 429, "Too many failed attempts. Try again later.", {"Retry-After": str(int(wait) + 1)})
    verified = await _asyncio_to_thread(authenticate, user.email, password or "")
    if verified is None or verified.id != user.id:
        acct.record_stepup_failure(user.id)
        return _reauth_refusal("reauth_failed", wrong_password_status, "Current password is incorrect." if wrong_password_status == 400 else "Incorrect password.")
    state = get_totp_state(user.id)
    if state["enabled"]:
        if not totp_code:
            return _reauth_refusal("reauth_required", 401, "Enter the code from your authenticator app to confirm.")
        step = verify_totp_step(state["secret"], totp_code)
        if step is None or not acct.claim_totp_step(user.id, step):
            acct.record_stepup_failure(user.id)
            return _reauth_refusal("reauth_failed", 401, "Invalid or expired code.")
    acct.clear_stepup_failures(user.id)
    return None


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, user: User = Depends(get_current_user)):
    from orca.auth.store import update_password
    if len(req.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    refusal = await _fresh_auth(user, req.current_password, req.totp_code, wrong_password_status=400)
    if refusal is not None:
        return refusal
    update_password(user.id, req.new_password)        # every session issued before now is dead, including the caller's
    from orca import audit
    audit.log("password_changed", user_id=user.id, detail={})
    # the caller changed their own password on purpose: continue THEIR session with a fresh token rather than silently signing them out
    return {"updated": True, **_make_response(get_user_by_id(user.id))}


# ── API Key routes ────────────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    name: str = ""
    # L02-B3: fresh verification, checked inside this request (never stored, never reusable). `totp_code` is required when the account has 2FA enabled.
    password: str | None = None
    totp_code: str | None = None


def _reauth_refusal(code: str, status: int, message: str, headers: dict | None = None):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": message, "error": message, "code": code}, status_code=status, headers=headers or {})


@router.post("/apikeys")
async def create_api_key(
    req: ApiKeyRequest,
    request: Request,
    user: User = Depends(require_permission("api_keys")),
    creds=Depends(_bearer),
):
    """Mint a long-lived credential. A session token alone is not enough: the caller must prove, now, that they know the account password and (when 2FA is on)
    hold the authenticator, so a stolen or hijacked session cannot create a key that outlives logout and password change."""
    from orca import audit

    if creds is not None and str(creds.credentials).startswith("athr_"):
        # an API key can never mint another API key: it would let one leaked key become permanent
        audit.log("api_key_reauth_failed", user_id=user.id, detail={"reason": "api_key_credential"})
        return _reauth_refusal("reauth_requires_session", 403, "Creating an API key requires a signed-in session.")
    ratelimit.enforce(request, ratelimit.AUTH_LOGIN, extra_key="apikey_create")
    wait = acct.stepup_locked(user.id)
    if wait > 0:
        audit.log("api_key_reauth_failed", user_id=user.id, detail={"reason": "locked"})
        return _reauth_refusal("too_many_attempts", 429, "Too many failed attempts. Try again later.", {"Retry-After": str(int(wait) + 1)})
    if not req.password or not req.password.strip():
        audit.log("api_key_reauth_failed", user_id=user.id, detail={"reason": "missing_password"})
        return _reauth_refusal("reauth_required", 401, "Confirm your password to create an API key.")

    def _fail(reason: str):
        acct.record_stepup_failure(user.id)
        audit.log("api_key_reauth_failed", user_id=user.id, detail={"reason": reason})
        return _reauth_refusal("reauth_failed", 401, "Verification failed.")

    verified = await _asyncio_to_thread(authenticate, user.email, req.password)
    if verified is None or verified.id != user.id:
        return _fail("password")
    totp_state = get_totp_state(user.id)
    if totp_state["enabled"]:
        step = verify_totp_step(totp_state["secret"], req.totp_code or "")
        if step is None:
            return _fail("totp_invalid")
        if not acct.claim_totp_step(user.id, step):
            return _fail("totp_replayed")
    acct.clear_stepup_failures(user.id)
    kid, raw = create_key(user.id, req.name)
    audit.log("api_key_created", user_id=user.id, detail={"key_id": kid, "mfa": bool(totp_state["enabled"])})
    return {"key_id": kid, "key": raw, "name": req.name}


@router.get("/apikeys")
async def get_api_keys(user: User = Depends(require_permission("api_keys"))):
    return {"keys": list_keys(user.id)}


@router.delete("/apikeys/{key_id}")
async def delete_api_key(key_id: str, user: User = Depends(require_permission("api_keys"))):
    ok = revoke_key(key_id, user.id)
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"revoked": True}


# ── Admin routes ──────────────────────────────────────────────────────────────

class TierUpdate(BaseModel):
    tier: str


class RoleUpdate(BaseModel):
    role: str


@router.get("/admin/users")
async def admin_list_users(
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(require_permission("manage_users")),
):
    return {"users": list_users(limit=limit, offset=offset)}


@router.patch("/admin/users/{user_id}/tier")
async def admin_set_tier(
    user_id: str,
    body: TierUpdate,
    admin: User = Depends(require_permission("manage_users")),
):
    if body.tier not in ("free", "pro", "enterprise"):
        raise HTTPException(400, "Invalid tier")
    set_user_tier(user_id, body.tier)
    return {"updated": True}


@router.patch("/admin/users/{user_id}/role")
async def admin_set_role(
    user_id: str,
    body: RoleUpdate,
    admin: User = Depends(require_permission("manage_users")),
):
    if body.role not in ("owner", "admin", "member", "viewer"):
        raise HTTPException(400, "Invalid role")
    from orca.auth.rbac import can_assign_role
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if not can_assign_role(admin.role, target.role, body.role):
        raise HTTPException(403, "You cannot assign a role at or above your own, or change a user ranked at or above you")
    set_user_role(user_id, body.role)
    return {"updated": True}


class DeleteAccountRequest(BaseModel):
    password: str
    totp_code: str | None = None      # required when the account has 2FA enabled


@router.post("/account/delete")
async def delete_account_endpoint(req: DeleteAccountRequest, user: User = Depends(get_current_user)):
    """
    Right-to-delete — requires the current password (not just an active
    session token) before deleting anything. Same reasoning as requiring a
    fresh TOTP code to disable 2FA: a hijacked session token alone (XSS,
    stolen JWT) shouldn't be enough to trigger an irreversible account
    deletion.
    """
    refusal = await _fresh_auth(user, req.password, req.totp_code)
    if refusal is not None:
        return refusal

    from orca.serve.account_delete import delete_account
    report = delete_account(user.id)

    from orca import audit
    audit.log("account_deleted", user_id=user.id, detail={
        "sessions_processed": report["sessions_processed"],
    })

    return report


# ── Enterprise / Team management ─────────────────────────────────────────────
# One org per owning account, lazily created on first invite — see
# orca/auth/org_store.py module docstring for the honest scope (seat limits
# tied to tier, not a separate Stripe seat-billing product).

class OrgInviteRequest(BaseModel):
    email: str
    role: str = "member"


class OrgMemberRoleUpdate(BaseModel):
    role: str


class OrgAcceptInviteRequest(BaseModel):
    token: str


@router.get("/org")
async def get_org(user: User = Depends(get_current_user)):
    from orca.auth.org_store import get_org_for_owner, list_members, SEAT_LIMITS
    org = get_org_for_owner(user.id)
    if not org:
        # No org created yet (no invites sent) — real limit for this
        # user's actual tier, not a hardcoded placeholder.
        limit = SEAT_LIMITS.get(user.tier, SEAT_LIMITS["free"])
        return {"org": None, "members": [], "seats": {"used": 1, "limit": limit}}
    from orca.auth.org_store import get_seat_usage
    return {
        "org": org,
        "members": list_members(org["id"]),
        "seats": get_seat_usage(org["id"], user.tier),
    }


@router.post("/org/invite")
async def invite_org_member(req: OrgInviteRequest, user: User = Depends(get_current_user)):
    from orca.auth.org_store import get_or_create_org, invite_member

    org_id = get_or_create_org(user.id, user.name)
    try:
        result = invite_member(org_id, user.tier, req.email, req.role)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Best-effort email delivery — same graceful-without-SMTP pattern as
    # email verification elsewhere. The invite link itself is always
    # returned so the inviter can share it manually if SMTP isn't configured.
    invite_link = f"/accept-invite?token={result['invite_token']}"
    email_sent = False
    if email_configured():
        try:
            from orca.license.mailer import send_org_invite_email
            from orca.auth.org_store import get_org_for_owner
            org_row = get_org_for_owner(user.id)  # already exists — invite_member() above created it
            org_name = org_row["name"] if org_row else "the team"
            email_sent = send_org_invite_email(req.email, invite_link, org_name, user.name)
        except Exception:
            email_sent = False

    from orca import audit
    audit.log("org_member_invited", user_id=user.id, detail={"email": req.email, "role": req.role})

    return {**result, "invite_link": invite_link, "email_sent": email_sent}


@router.post("/org/accept-invite")
async def accept_org_invite(req: OrgAcceptInviteRequest, user: User = Depends(get_current_user)):
    from orca.auth.org_store import accept_invite
    try:
        result = accept_invite(req.token, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    from orca import audit
    audit.log("org_invite_accepted", user_id=user.id, detail={"org_id": result["org_id"]})
    return result


@router.patch("/org/members/{member_id}/role")
async def update_org_member_role(member_id: str, req: OrgMemberRoleUpdate, user: User = Depends(get_current_user)):
    from orca.auth.org_store import get_org_for_owner, set_member_role
    org = get_org_for_owner(user.id)
    if not org:
        raise HTTPException(404, "You don't have a team organization yet.")
    try:
        set_member_role(org["id"], member_id, req.role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"updated": True}


@router.delete("/org/members/{member_id}")
async def remove_org_member(member_id: str, user: User = Depends(get_current_user)):
    from orca.auth.org_store import get_org_for_owner, remove_member
    org = get_org_for_owner(user.id)
    if not org:
        raise HTTPException(404, "You don't have a team organization yet.")
    remove_member(org["id"], member_id)
    from orca import audit
    audit.log("org_member_removed", user_id=user.id, detail={"member_id": member_id})
    return {"removed": True}
