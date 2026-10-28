"""FastAPI auth dependency — extracts and validates the current user."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from orca.auth.crypto import verify_token
from orca.auth.store import User, get_user_by_id
from orca.auth.apikeys import verify_api_key

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> User:
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = creds.credentials
    # API key path (athr_ prefix)
    if token.startswith("athr_"):
        uid = verify_api_key(token)
        if not uid:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")
        user = get_user_by_id(uid)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    # JWT path
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    # G-006: reset, email-verification and 2FA-pending tokens are signed with
    # the same AUTH_SECRET and carry a "sub" too, so without this check any of
    # them (a pre-2FA pending token, an emailed link) was accepted as a full
    # session. Tokens issued before "type" existed have no type and are
    # session tokens by construction.
    if payload.get("type", "session") != "session":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    jti = payload.get("jti")
    if jti:
        from orca.auth.store import is_token_revoked

        if is_token_revoked(jti):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = get_user_by_id(payload.get("sub", ""))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # G-006: a password change/reset invalidates every token issued before it.
    if float(payload.get("iat", 0)) < user.tokens_valid_after:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


async def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[User]:
    """Optional auth for routes that allow missing credentials.

    Missing Authorization → None (anonymous, subject to the route policy).
    Present but invalid / expired / revoked / wrong-type credentials → 401.
    Never downgrade a failed credential presentation to anonymous.
    """
    if not creds:
        return None
    # Intentionally do not swallow HTTPException: invalid credentials must fail.
    return await get_current_user(creds)
