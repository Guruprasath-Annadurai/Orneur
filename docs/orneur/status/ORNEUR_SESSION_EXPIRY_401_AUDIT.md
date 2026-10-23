# Session-Expiry / HTTP 401 Audit (Mission 3)

**Branch:** `claude/b04-b09-implementation-2026-10-23`
**Scope:** audit session-expiry and HTTP 401 behavior honestly per the CTO's "Massive Frontend Engineering Execution" directive; implement basic recovery within scope; escalate any fundamental authentication design change rather than alter it unilaterally.

## What was audited, and how

Grepped every authenticated `fetch()` call site in `orca/serve/web/conversation.html` (`loadSessions()`, `openSession()`, `runConversationSearch()`, rename, export, delete, plus `tryRestoreSession()`'s boot-time `/api/auth/me` call) and cross-referenced each against the backend route it calls in `orca/serve/api.py` and the two auth dependencies in `orca/auth/middleware.py`.

## The real backend behavior, confirmed by reading the dependency code (not assumed)

```python
# orca/auth/middleware.py
async def get_current_user(creds=Depends(_bearer)) -> User:
    if not creds: raise HTTPException(401, "Not authenticated")
    ...
    payload = verify_token(token)
    if not payload: raise HTTPException(401, "Invalid or expired token")
    ...
    return user

async def get_current_user_optional(creds=Depends(_bearer)) -> Optional[User]:
    if not creds: return None
    try:
        return await get_current_user(creds)
    except HTTPException:
        return None   # <-- swallows the 401 and returns None instead
```

**`/api/auth/me`** (used only by `tryRestoreSession()` at boot) uses the strict `get_current_user` — confirmed live: `curl -H "Authorization: Bearer garbage.not.a.token" /api/auth/me` → **401**.

**Every other endpoint `conversation.html` calls while already signed in** — `/api/sessions`, `/api/session/{id}/messages`, `/api/sessions/search`, `/api/session/{id}/title` (PATCH), `/api/session/{id}/export`, `/api/session/{id}` (DELETE) — uses `get_current_user_optional`. Confirmed live: `curl -H "Authorization: Bearer garbage.not.a.token" /api/sessions?limit=20` → **200 OK**, body `{"sessions":[],"total":0,...}`. The invalid/expired/revoked token is silently treated as "no user" (anonymous-equivalent), not rejected.

## The real, disclosed consequence

If a signed-in user's token expires, is revoked, or otherwise becomes invalid while they are actively using the app, **none of the screens they're looking at will ever receive a 401** for it. The sidebar will silently show `"No conversations yet"` (indistinguishable from a genuinely-new account with zero conversations), search will silently show `"No matching conversations"`, and rename/export/delete will silently fail in whatever way the endpoint's not-found/not-authorized branch behaves for an anonymous caller — all while the UI's own `_authUser` state is untouched, so the sidebar still shows their name and avatar as if nothing happened. This is a real, user-facing truthfulness problem (a misleading "you have zero conversations" instead of an honest "your session expired"), not a hypothetical one.

## What was implemented (in scope: basic recovery, not an architecture change)

Added `_handleSessionExpired()` (reusing a new shared `_clearAuthStateAndShowSignIn(message)` that `doLogout()` now also uses) and wired `if (r.status === 401) { _handleSessionExpired(); return; }` into all six authenticated call sites, checked after each one's existing per-domain ownership guard (so a 401 on an already-abandoned/stale request — e.g. after the user already switched accounts — correctly does nothing, per the same ownership discipline as the rest of PR #85). On a real 401, the user is signed out, both view domains are invalidated (`_abandonAllViewsForAccountChange()`), and the sign-in overlay reopens with an honest, specific message: **"Your session has expired. Please sign in again."**

This is genuinely correct, tested code (9 new/updated unit tests in `tests/frontend/test_view_ownership_epoch.mjs`, including a structural check that every one of the six call sites has the guard) — and it is **not a fabricated fix for the problem above**, because the problem above happens on endpoints that currently never emit a 401 at all. What this change does cover, today: `tryRestoreSession()`'s boot-time restore (already correctly handled before this change, via the generic `!r.ok` path, since `/api/auth/me` is strict) and any future endpoint that adopts strict auth.

**Honest verdict on scope: this is infrastructure, not a solved problem.** The live reproduction below demonstrates the gap still exists exactly as described.

## Live reproduction (not asserted from reading code alone)

```js
_authToken = _authToken + 'CORRUPTED';   // simulate a real expired/invalid token, in a real logged-in session
await loadSessions();
// Result: recentsListAfter: "No conversations yet", authOverlayHidden: true (never opened), tokenAfter: still the corrupted token
```

The sidebar silently repainted to the empty-list state. The sign-in overlay never opened. The corrupted token was never cleared. This is the exact, disclosed, real behavior today — not improved by the frontend change above, because `loadSessions()`'s `r.status === 401` check is correct code that simply never gets a chance to run: the backend returned 200.

## Escalation (per the directive's own instruction, not altered unilaterally)

Whether `/api/sessions`, `/messages`, search, rename, export, and delete should:
- **(a)** switch to the strict `get_current_user` dependency, so an invalid/expired/revoked token on an already-authenticated screen produces a real 401 the frontend can react to honestly, or
- **(b)** keep the current anonymous-equivalent degradation deliberately (there may be a reason — e.g. some of these routes may be intended to also serve a genuinely-anonymous caller a public/empty response, which a strict dependency would break for that caller),

is a real authentication-architecture decision, not a bug I am positioned to silently fix from the frontend. **Escalated here rather than changed.** If the CTO/Cursor confirm (a) is correct, the frontend recovery code in this change is already written, tested, and ready — no further frontend work would be needed once the backend actually emits the 401.

## Tests and verification

```
node --test tests/frontend/*.mjs   # 71/71 passing (was 68)
```

New tests: `_handleSessionExpired()` clears auth state and shows the truthful message; is a no-op when already signed out; structural check that all six call sites have the 401 guard. Live-verified: `/api/auth/me` returns a real 401 for an invalid token (confirmed via `curl`); `/api/sessions` does not (confirmed via both `curl` and a live browser reproduction with a real logged-in session).

## Honest verdict

**Not fixed — correctly scoped and escalated.** The frontend now has correct, tested 401-recovery infrastructure wired into every authenticated call site, matching the directive's "implement necessary basic recovery within scope" instruction. The underlying architectural gap — that the endpoints most likely to encounter a stale token never emit a 401 at all — is a backend authentication design question, documented here with the exact code locations (`orca/auth/middleware.py:57-65`, every `Depends(get_current_user_optional)` call site in `orca/serve/api.py`) and escalated rather than patched around.
