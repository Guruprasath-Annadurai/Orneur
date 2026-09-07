# Phase 14C Step 13 — Route Inventory

Every route registered on `orca/serve/api.py`'s `app` and `orca/auth/routes.py`'s
`router` (mounted under `/api/auth`), classified by real auth dependency —
read directly from source, not inferred. "Depends" names are the actual
FastAPI dependency each route uses.

Classes:
- **PUBLIC** — no auth dependency, safe to be world-reachable through the edge.
- **OPTIONAL_AUTH** — works anonymously; behavior/scoping changes if a valid
  token is present (`get_current_user_optional`). Session-ownership
  enforcement (`_get_session()`, see `PHASE14C_EDGE_EVIDENCE.md`) applies to
  every one of these that takes a `session_id`.
- **AUTH_REQUIRED** — 401s without a valid token (`get_current_user`).
- **ADMIN_PERMISSION** — requires a specific permission via
  `require_permission(...)`, not just any authenticated user. These are the
  routes Steps 14/20/21 route through Cloudflare Access.
- **WEBHOOK_SIGNED** — no bearer-token auth, but verifies a cryptographic
  signature on the payload itself (Stripe).
- **INTERNAL_HEALTH** — liveness/readiness probes. Must stay reachable by
  the platform's own health checks; never gate these behind Access.

## `orca/serve/api.py`

| Method | Path | Class | Notes |
|---|---|---|---|
| GET | `/` | PUBLIC | landing page |
| GET | `/app` | PUBLIC | web UI shell |
| GET | `/trust` | PUBLIC | trust/transparency page |
| GET | `/livez` | INTERNAL_HEALTH | |
| GET | `/readyz` | INTERNAL_HEALTH | |
| GET | `/healthz` | INTERNAL_HEALTH | |
| GET | `/api/status` | PUBLIC | |
| POST | `/api/cognitive/execute` | OPTIONAL_AUTH | |
| POST | `/api/chat` | OPTIONAL_AUTH | rate-limited (`ratelimit.CHAT`) |
| POST | `/api/stream` | OPTIONAL_AUTH | rate-limited |
| POST | `/api/memory/recall` | OPTIONAL_AUTH | session-owned |
| POST | `/api/remember` | OPTIONAL_AUTH | session-owned |
| GET | `/api/sessions` | PUBLIC | lists only the caller's own in-memory `_sessions` process state, not another tenant's data |
| POST | `/api/session/load` | OPTIONAL_AUTH | session-owned (both source and target) |
| PATCH | `/api/session/{session_id}/title` | PUBLIC | title rename by session_id; no ownership check — pre-existing scope, unaffected by Phase 14C's session-ownership fix (titles carry no sensitive content) |
| GET | `/api/explain/{session_id}/{message_id}` | OPTIONAL_AUTH | session-owned |
| GET | `/api/knowledge/{session_id}` | OPTIONAL_AUTH | session-owned |
| GET | `/api/knowledge/{session_id}/{entity_name}` | OPTIONAL_AUTH | session-owned |
| GET | `/api/session/{session_id}/export` | OPTIONAL_AUTH | session-owned |
| POST | `/api/session/save` | PUBLIC | |
| GET | `/api/models` | PUBLIC | model tier listing, no secrets |
| GET | `/legal/privacy` | PUBLIC | |
| GET | `/legal/terms` | PUBLIC | |
| GET | `/legal/ai-policy` | PUBLIC | |
| GET | `/docs` | PUBLIC | product docs index, distinct from FastAPI's own `/docs` (Swagger UI is disabled — see SECURITY.md) |
| GET | `/docs/{slug}` | PUBLIC | |
| GET | `/api/license` | PUBLIC | |
| POST | `/api/billing/checkout` | AUTH_REQUIRED | |
| POST | `/webhook/stripe` | WEBHOOK_SIGNED | verifies `stripe-signature` header |
| POST | `/api/ultra` | OPTIONAL_AUTH | session-owned |
| POST | `/api/docs/upload` | OPTIONAL_AUTH | session-owned; rate-limited; per-file size cap (`MAX_FILE_SIZE`) |
| GET | `/api/docs/list` | OPTIONAL_AUTH | session-owned |
| DELETE | `/api/docs/{doc_id}` | OPTIONAL_AUTH | session-owned |
| POST | `/api/code/run` | OPTIONAL_AUTH | rate-limited; sandboxed subprocess |
| POST | `/api/vision` | OPTIONAL_AUTH | session-owned; per-image size cap |
| GET | `/api/admin/metrics` | ADMIN_PERMISSION | `audit_read` |
| GET | `/metrics` | PUBLIC (by design) | Prometheus scrape endpoint — own docstring already warns this reveals operational detail and should be firewalled if exposed; **recommend Cloudflare Access** (Step 14) rather than leaving it open through the public edge |
| GET | `/api/admin/audit` | ADMIN_PERMISSION | `audit_read` |
| GET | `/api/admin/audit/verify` | ADMIN_PERMISSION | `audit_read` |
| GET | `/api/admin/audit/export` | ADMIN_PERMISSION | `audit_read` |
| GET | `/api/admin/governance/cards` | ADMIN_PERMISSION | `audit_read` |
| GET | `/api/admin/governance/cards/{variant}` | ADMIN_PERMISSION | `audit_read` |
| POST | `/api/admin/governance/cards/{variant}/generate` | ADMIN_PERMISSION | `manage_users` |
| GET | `/api/admin/stats` | ADMIN_PERMISSION | `manage_users` |

## `orca/auth/routes.py` (mounted at `/api/auth`)

| Method | Path | Class | Notes |
|---|---|---|---|
| POST | `/api/auth/signup` | PUBLIC | rate-limited |
| POST | `/api/auth/login` | PUBLIC | rate-limited |
| POST | `/api/auth/2fa/verify-login` | PUBLIC | short-lived pre-auth token, not a session token |
| POST | `/api/auth/2fa/setup` | AUTH_REQUIRED | |
| POST | `/api/auth/2fa/enable` | AUTH_REQUIRED | |
| POST | `/api/auth/2fa/disable` | AUTH_REQUIRED | |
| GET | `/api/auth/me` | AUTH_REQUIRED | |
| GET | `/api/auth/email-status` | PUBLIC | |
| POST | `/api/auth/signup/resend-verification` | AUTH_REQUIRED | |
| GET | `/api/auth/verify` | PUBLIC | email-verification link target, token-in-URL is the credential |
| POST | `/api/auth/forgot-password` | PUBLIC | rate-limited |
| POST | `/api/auth/reset-password` | PUBLIC | token-in-body is the credential |
| POST | `/api/auth/change-password` | AUTH_REQUIRED | |
| POST | `/api/auth/apikeys` | ADMIN_PERMISSION | `api_keys` (any authenticated user with that permission, not admin-only) |
| GET | `/api/auth/apikeys` | ADMIN_PERMISSION | `api_keys` |
| DELETE | `/api/auth/apikeys/{key_id}` | ADMIN_PERMISSION | `api_keys`; ownership double-checked in the handler (`revoke_key(key_id, user.id)`) |
| GET | `/api/auth/admin/users` | ADMIN_PERMISSION | `manage_users` |
| PATCH | `/api/auth/admin/users/{user_id}/tier` | ADMIN_PERMISSION | `manage_users` |
| PATCH | `/api/auth/admin/users/{user_id}/role` | ADMIN_PERMISSION | `manage_users` |
| POST | `/api/auth/account/delete` | AUTH_REQUIRED | |
| GET | `/api/auth/org` | AUTH_REQUIRED | |
| POST | `/api/auth/org/invite` | AUTH_REQUIRED | |
| POST | `/api/auth/org/accept-invite` | AUTH_REQUIRED | |
| PATCH | `/api/auth/org/members/{member_id}/role` | AUTH_REQUIRED | |
| DELETE | `/api/auth/org/members/{member_id}` | AUTH_REQUIRED | |

## Cloudflare Access candidates (Steps 14/20/21)

Every `ADMIN_PERMISSION` route above is already defense-in-depth (a stolen
non-admin token cannot use them regardless of network path). Cloudflare
Access adds a SECOND, independent gate in front of the network path itself
— recommended for:

- `/api/admin/*` (all of `orca/serve/api.py`'s admin routes)
- `/api/auth/admin/*` (user/tier/role management)
- `/metrics` (the one genuinely-unauthenticated operational-detail route)

Everything else is intentionally reachable from the public edge (chat,
docs, auth signup/login, health checks) and must NOT be placed behind
Access — doing so would break the product for real users.
