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

Every endpoint `conversation.html` calls on an already-signed-in screen uses this dependency: `GET /api/sessions`, `GET /api/session/{id}/messages`, `GET /api/sessions/search`, `PATCH /api/session/{id}/title`, `GET /api/session/{id}/export`, `DELETE /api/session/{id}`. An invalid, expired, or revoked Bearer token on any of these produces **200 OK** with an empty/anonymous-equivalent result, never a 401. Only `GET /api/auth/me` (strict `get_current_user`) returns a real 401 for a bad token — confirmed live via `curl`.

## Proposed contract (for Cursor to accept, modify, or reject)

**Request:** for the six endpoints listed above, when a Bearer token is present in the `Authorization` header but fails verification (expired, revoked, malformed, unknown `sub`, or fails the password-change/`tokens_valid_after` check already in `get_current_user`), return **`401 { "detail": "Invalid or expired token" }`** — i.e., use the already-existing strict `get_current_user` dependency (or an equivalent that still treats a genuinely *absent* `Authorization` header as "anonymous, proceed" per each endpoint's own existing public/anonymous semantics, if any of them intentionally serve anonymous callers something other than an empty list).

**Open question for Cursor, not assumed by this document:** do any of these six endpoints deliberately serve a *genuinely anonymous* caller (no `Authorization` header at all) something meaningful today, where switching to strict auth would need to preserve that? From reading `orca/serve/api.py`, all six appear to be conversation-ownership-scoped (a session list/search/message/export/delete/rename tied to a specific signed-in user) with no documented anonymous use case — but Cursor owns this code and should confirm before the switch, since an incorrect assumption here could break a legitimate anonymous flow this document isn't aware of.

## What the frontend already does, ready for this contract today

`orca/serve/web/conversation.html` already has `_handleSessionExpired()` wired into all six call sites via `if (r.status === 401) { _handleSessionExpired(); return; }`, tested (`tests/frontend/test_view_ownership_epoch.mjs`, 401-recovery tests) and shipped on this branch. **No further frontend work is needed once the backend emits the 401** — this is purely a backend-side change request.

## What NOT to do (per the CTO directive's own restriction)

This document does not change `orca/auth/middleware.py`, does not change any `Depends(...)` declaration in `orca/serve/api.py`, and does not attempt to guess at or silently patch around Cursor's authentication design. The fix, if accepted, belongs entirely to Cursor's own branch/PR.

## Reference

Full audit, reproduction evidence, and live `curl`/browser verification: [`ORNEUR_SESSION_EXPIRY_401_AUDIT.md`](ORNEUR_SESSION_EXPIRY_401_AUDIT.md).
