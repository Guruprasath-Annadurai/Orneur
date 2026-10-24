# API Contract for Cursor — Session-Expiry 401 on Conversation Endpoints

**Requested by:** ORNEUR CTO directive (Mission 2, finding #8) — "Coordinate the backend issue where expired tokens are silently treated as anonymous. Give Cursor an exact API contract; do not independently rewrite Cursor-owned authentication code."
**This document does not modify `orca/auth/` or `orca/serve/api.py`.** It specifies the contract Cursor's team should implement, with the frontend's own commitment to what it will do once that contract exists.

## The problem, exactly

`orca/auth/middleware.py:57-65`:

```python
async def get_current_user_optional(creds=Depends(_bearer)) -> Optional[User]:
    if not creds: return None
    try:
        return await get_current_user(creds)
    except HTTPException:
        return None
```

Every endpoint `conversation.html` calls on an already-signed-in screen uses this dependency: `GET /api/sessions`, `GET /api/session/{id}/messages`, `GET /api/sessions/search`, `PATCH /api/session/{id}/title`, `GET /api/session/{id}/export`, `DELETE /api/session/{id}`, and — found during the B12 Error & Recovery pass, not in the original audit — `POST /api/stream`. An invalid, expired, or revoked Bearer token on any of these produces **200 OK** with an empty/anonymous-equivalent result, never a 401. Only `GET /api/auth/me` (strict `get_current_user`) returns a real 401 for a bad token — confirmed live via `curl`.

## Proposed contract (for Cursor to accept, modify, or reject)

**Request:** when a Bearer token is present in the `Authorization` header but fails verification (expired, revoked, malformed, unknown `sub`, or fails the password-change/`tokens_valid_after` check already in `get_current_user`), return **`401 { "detail": "Invalid or expired token" }`** — i.e., use the already-existing strict `get_current_user` dependency (or an equivalent that still treats a genuinely *absent* `Authorization` header as "anonymous, proceed" per each endpoint's own existing public/anonymous semantics, if any of them intentionally serve anonymous callers something other than an empty list).

**Open question for Cursor, not assumed by this document:** do the six conversation-management endpoints (`sessions`, `messages`, `search`, `title`, `export`, delete) deliberately serve a *genuinely anonymous* caller (no `Authorization` header at all) something meaningful today, where switching to strict auth would need to preserve that? From reading `orca/serve/api.py`, all six appear to be conversation-ownership-scoped (tied to a specific signed-in user) with no documented anonymous use case. **`/api/stream` is different and needs its own care**: its own code (`if user: check_quota(...)`) shows it is explicitly designed to also serve genuinely anonymous callers a real response, just without quota tracking — so the fix there cannot simply be "require a valid token." It needs to distinguish three cases, not two: (a) no `Authorization` header at all → anonymous, proceed, unchanged; (b) a header present and valid → authenticated, proceed as today; (c) a header present but invalid/expired/revoked → this is the genuinely new case, and should 401 rather than silently falling back to anonymous, since silently downgrading a user who believes they are still signed in is the exact truthfulness problem this document exists to fix.

## What the frontend already does, ready for this contract today

`orca/serve/web/conversation.html` already has `_handleSessionExpired()` wired into all six call sites via `if (r.status === 401) { _handleSessionExpired(); return; }`, tested (`tests/frontend/test_view_ownership_epoch.mjs`, 401-recovery tests) and shipped on this branch. **No further frontend work is needed once the backend emits the 401** — this is purely a backend-side change request.

## What NOT to do (per the CTO directive's own restriction)

This document does not change `orca/auth/middleware.py`, does not change any `Depends(...)` declaration in `orca/serve/api.py`, and does not attempt to guess at or silently patch around Cursor's authentication design. The fix, if accepted, belongs entirely to Cursor's own branch/PR.

## Reference

Full audit, reproduction evidence, and live `curl`/browser verification: [`ORNEUR_SESSION_EXPIRY_401_AUDIT.md`](ORNEUR_SESSION_EXPIRY_401_AUDIT.md).
