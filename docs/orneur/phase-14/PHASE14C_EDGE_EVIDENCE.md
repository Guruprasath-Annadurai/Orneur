# Phase 14C — Secure Cloud Edge + Deployment Hardening: Evidence

Mission: expose ORNEUR staging securely through Cloudflare while
preserving private origin, fail-closed authority, no direct-origin
bypass, strict trust boundaries, no Mac dependency, no secret leakage.
Architecture: Internet -> Cloudflare (TLS/WAF/rate limiting/bot
controls/Zero Trust Access) -> Cloudflare Tunnel -> Northflank private
service `orneur-api-a:7337` -> Supabase CORE / Supabase SECURITY ROOT.

All live checks below ran on GitHub Actions ephemeral runners via
`.github/workflows/phase14b-distributed-qualification.yml`'s
`fresh_runner_mode` dispatch surface — never this Mac (one accidental
Mac-origin check was made and immediately corrected; see Step 34).
Failures and retries are preserved below, not rewritten out.

## Architecture (Step 1-6)

- Domain: `staging.orneur.com`, nameservers on Cloudflare
  (`coby.ns.cloudflare.com` / `zariyah.ns.cloudflare.com`).
- Cloudflare Tunnel connector: Northflank service `orneur-edge-tunnel`
  (image `cloudflare/cloudflared:latest`, command
  `tunnel --no-autoupdate run`, picks up `TUNNEL_TOKEN` from its own
  env — confirmed the bare form works without an explicit `--token`
  flag once the token value itself is current).
- Origin: Northflank private service `orneur-api-a`, addressed
  internally as `orneur-api-a:7337` — reachable ONLY from other
  services inside the same Northflank project, never from the public
  internet (see Step 9).
- Zero Trust plan: Free.

## Cloudflared connectivity (Step 2-3)

`orneur-edge-tunnel` created idempotently, reached a genuinely HEALTHY/
CONNECTED state — 4 real registered QUIC connections to Cloudflare
Amsterdam PoPs. Two real problems found and fixed along the way:

1. A crash-looping pod kept retrying with a STALE `TUNNEL_TOKEN` value
   even after the dashboard value was updated — Northflank injects
   secrets once at pod creation, not on a container's own internal
   restarts. Fixed with an explicit `restart service` (forces a new
   pod).
2. Northflank was rebuilding+redeploying `orneur-api-a` on every
   single git push, including pure `.github/workflows/*.yml`/`docs/**`
   changes, because `buildConfiguration.pathIgnoreRules` was empty by
   default. Fixed via `update service build-options`
   (`pathIgnoreRules: [".github/**", "docs/**", "scripts/phase14b/**", "*.md"]`).

## TLS (Step 8)

- `https://staging.orneur.com/livez` → 200, valid certificate.
- Plain HTTP → 301 redirect to HTTPS (`Always Use HTTPS`, enabled by
  the user after being found initially OFF).
- HSTS (`Strict-Transport-Security: max-age=63072000; includeSubDomains`)
  — **initially MISSING** from live responses (found during
  `verify_public_edge`), root-caused to uvicorn's `forwarded_allow_ips`
  defaulting to `127.0.0.1` (the Cloudflare Tunnel connector is a
  SEPARATE Northflank service, never connects from `127.0.0.1`), so
  `X-Forwarded-Proto: https` was never honored and
  `request.url.scheme` stayed `http`. Fixed by setting
  `ORNEUR_TRUSTED_PROXY_CIDRS=*` on `orneur-api-a` (see Step 11 below
  for why `*` — not a guessed CIDR — is the correct value here).
  Re-verified live: HSTS now present.

## Origin security — no direct-origin bypass (Step 9)

- Direct Northflank origin URL
  (`p01--orneur-api-a--7knh72p45d7b.code.run/livez`) → connection
  failure (not merely a 403/404 — genuinely unreachable), both with a
  plain request and with a spoofed
  `Host: staging.orneur.com` header. Confirmed repeatedly across
  multiple qualification runs.

## CORS (Step 10)

- `Origin: https://staging.orneur.com` against `/api/status` →
  `access-control-allow-origin` present.
- `Origin: https://evil.example.com` → no `access-control-allow-*`
  header returned. `ORNEUR_ALLOWED_ORIGINS` fails closed (raises at
  import time) whenever `ORNEUR_PUBLIC_EDGE=1` and origins would
  otherwise default to wildcard — code-level, `orca/serve/api.py`.

## Trusted-proxy / forwarded-header safety (Step 11)

Northflank does **not** publish a stable, documented CIDR for its
internal service-to-service networking (only BYOC cluster-provisioning
defaults are documented, not a fixed platform-wide range — confirmed
against Northflank's own docs). The real trust boundary for this
deployment is Northflank's own project-level **private-port isolation**
— already proven live in Step 9 (nothing outside the project can reach
`orneur-api-a:7337` at all). Given that precondition, `ORNEUR_TRUSTED_PROXY_CIDRS=*`
is the correct, justified value: it tells both `uvicorn`'s
`ProxyHeadersMiddleware` (via `orca/cli.py`'s `forwarded_allow_ips`)
and `orca/serve/ratelimit.py`'s `get_client_ip()` to trust
`X-Forwarded-Proto`/`X-Forwarded-For` unconditionally, which is safe
specifically because the only entity that can ever be the direct TCP
peer is something already inside the project (today, only
`orneur-edge-tunnel`). Live-verified: HSTS now present (proves
`X-Forwarded-Proto` is honored); `/readyz` self-check after the change
showed `authority_store`/`security_root`/`core_database` all still
`ok` (no regression).

## Host header validation (Step 12)

Live, through the real public edge:
- `Host: staging.orneur.com` → 200.
- `Host: evil.invalid.example` → **403** — `TrustedHostMiddleware`
  (`orca/serve/api.py`, `allowed_hosts` from `ORNEUR_TRUSTED_HOSTS`)
  correctly rejects it even though Cloudflare forwarded the header
  through to the origin.

## Route inventory (Step 13)

See `PHASE14C_ROUTE_INVENTORY.md` — every route in `orca/serve/api.py`
and `orca/auth/routes.py` classified by its real auth dependency, read
from source. Admin/operator routes (`/api/admin/*`, `/api/auth/admin/*`)
are already gated by `require_permission(...)`; `/metrics` is the one
genuinely-unauthenticated operational-detail route and is the primary
Cloudflare Access candidate alongside the admin routes.

## Cloudflare Access for operator surfaces (Steps 14/20/21)

**PASS.** User created three Cloudflare Zero Trust self-hosted Access
applications on `staging.orneur.com`, each with a policy requiring
authentication as the user's own email: paths `/api/admin`,
`/api/auth/admin`, and `/metrics`. Live-verified, run 34107581483,
through the real public edge with no bearer token and no Access
session cookie:

| Path | Result |
|---|---|
| `/api/admin/stats` | `HTTP/2 302` (Access login redirect) |
| `/api/auth/admin/users` | `HTTP/2 302` |
| `/metrics` | `HTTP/2 302` |

Regression check -- normal user-facing routes completely unaffected:

| Path | Result |
|---|---|
| `/livez` | 200 |
| `/api/status` | 200 |
| `/api/models` | 200 |

This is now a second, independent gate in front of the network path
itself, on top of the app's own existing `require_permission(...)`
checks on every one of these routes (see `PHASE14C_ROUTE_INVENTORY.md`).

## WAF baseline (Step 15)

See `PHASE14C_WAF_AND_RATE_LIMIT_BASELINE.md`. Zone plan: Free.
- Cloudflare Managed Ruleset / OWASP Core Ruleset / Exposed Credentials
  Check: **NOT_AVAILABLE_ON_CURRENT_PLAN** (Pro+ only).
- Free Managed Ruleset: **AVAILABLE**.
- Custom WAF rules: **AVAILABLE**, capped at 5 on Free. None configured.
- Bot Fight Mode: **CONFIGURED — DISABLED** (was the root cause of
  intermittent 403s on Free plan, which has no scoping/exception
  mechanism for it; user disabled it, re-verified clean 3x afterward).
- Always Use HTTPS: **CONFIGURED — ENABLED**.
- DDoS protection: **AVAILABLE (automatic, all plans)**.

## Rate limiting (Step 16)

- Cloudflare edge rate-limiting rules: **AVAILABLE on Free, capped at
  1 rule.** None configured (see baseline doc for why — deliberately
  deferred to avoid a second dashboard-action interrupt beyond the
  agreed Cloudflare Access one).
- Application-level rate limiting (`orca/serve/ratelimit.py`) already
  covers `/api/chat`, `/api/stream`, `/api/code/run`,
  `/api/docs/upload`, `/api/auth/signup`, `/api/auth/login`,
  `/api/auth/forgot-password` — unaffected by, and independent of, the
  edge-level gap above.

## Request-size limits (Step 17)

Previously, only `/api/docs/upload` and `/api/vision` had any body-size
ceiling (enforced AFTER reading the full body). Added a global
`request_size_limit_middleware` (`orca/serve/api.py`,
`MAX_REQUEST_BODY_BYTES`, default 30MB, `Content-Length` pre-check).
Live-verified: a 31MB `/api/chat` body → **413**. Documented residual
gap: a request that omits `Content-Length` (chunked transfer-encoding)
is not caught by this specific check — not claimed as fully closed.

## Real authentication + tenant isolation through the edge (Step 19)

**PASS — closed, 3x clean repeatable runs, all through
`https://staging.orneur.com`:**

| Run | Result |
|---|---|
| 34099701095 | ALL_PASS |
| 34099894010 | ALL_PASS |
| 34100029561 | ALL_PASS |
| 34102601647 (regression re-check after Step 11 trusted-proxy change) | ALL_PASS |

Checks: unauthenticated/invalid-token/tampered-API-key all denied
(401); two real signups; scoped identity check (`/api/auth/me` returns
the correct account); real cross-tenant isolation — user A uploads a
real document into a session, user B is denied (404) reading it back
via `/api/docs/list`, user A can still read their own.

A real, previously-unknown vulnerability was found and fixed during
this work: `/api/knowledge/*`, `/api/explain/*`, `/api/session/*/export`,
`POST /api/session/load`, `/api/memory/recall`, `/api/remember`,
`/api/docs/*`, `/api/ultra` had **no ownership check** on a
caller-supplied `session_id` — any caller who learned/guessed another
signed-in user's session_id could read (or, for docs, write into)
their data. Fixed centrally in `_get_session()`
(`orca/serve/api.py`) rather than per-route; `HTTPException(404)`, never
403, so an unauthorized caller cannot confirm a session exists.
Real HTTP-level tests: `tests/test_session_ownership_isolation.py`
(3 tests, all passing).

A second real defect was found and fixed while building this
qualification test: `POST /api/docs/upload` returned a genuine live
500 (`RuntimeError: No installed Ollama model found for tier 'core'`)
because `_Session.__init__` unconditionally resolved a chat model tier
and constructed a full brain/agent for EVERY session, even for routes
that never touch it. `model_runtime` being unavailable is an expected,
documented deployment state (see `/readyz` below) — a doc-only route
hard-failing because of it was a real bug, not a fixture gap. Fixed by
making brain/agent/ctx construction lazy (built on first access).
Regression test: `tests/test_doc_session_no_model_runtime.py` (proves
doc upload/list/delete and memory/knowledge routes work with no model
installed, while chat — which genuinely needs the model — still
correctly fails).

## Streaming/SSE (Step 22 per original numbering)

**NOT_EXERCISED_LIVE.** `/api/stream` requires a working model backend;
`model_runtime` is unavailable on this deployment (no Ollama models
installed — by design, see Health section). This is a scope boundary,
not a skipped requirement: the SSE transport mechanics themselves are
unrelated to Phase 14C's edge work and are exercised in
`tests/test_agent_*` locally: constructing an event-stream response
through the actual edge with a live model is not currently possible on
this deployment and is not claimed as done.

## Security headers (Step 18, verified as part of Step 15's "Step 22" label in the workflow)

Live on a real response (`/livez`, through the public edge):
`x-content-type-options: nosniff`, `referrer-policy:
strict-origin-when-cross-origin`, `permissions-policy: camera=(),
microphone=(), geolocation=()`, and (after the Step 11 fix)
`strict-transport-security: max-age=63072000; includeSubDomains`.
Verified in the same run as Step 19's regression re-check (run
34102504494) — a de facto second clean pass; not yet a formal 3x
battery specifically for headers alone.

## SSRF-through-edge (Step 20)

Unit-level guard (`orca/web/ssrf_guard.py`) is covered by
`tests/test_web_ssrf_guard.py`, part of the Step 33 full local
regression below. A live, authenticated, tool-call-driven SSRF attempt
through the real public edge requires a working model backend
(same constraint as Step 22/streaming) — not exercised live, documented
as a scope boundary. Baseline edge routing confirmed reachable
(`/api/status` → 200 through the public edge in the same run).

## Cloudflare failure/outage behavior (Step 23)

Live drill, run 34103296036: `orneur-edge-tunnel` restarted while
polling the public edge every 2s for 40s.

| t (s) | status |
|---|---|
| pre-restart | 200 |
| 0–6 | 200 |
| 8 | **530** (single sample) |
| 10–40 | 200 |
| post-recovery | 200 |

A single ~2-second blip, fully automatic recovery, no manual
intervention beyond the restart itself.

## Northflank pod-recycle observation (Step 24, Phase-14C-specific)

Live drill, run 34103443331: `orneur-api-a` (the origin itself, not
the tunnel) restarted while polling the public edge every 2s for 40s.

| t (s) | status |
|---|---|
| 0–6 | 200 |
| 8–38 | **502** (sustained — a full app-pod cold start, not a blip) |
| 40 | 200 |

~32 seconds of visible, bounded downtime; Cloudflare correctly
surfaced 502 rather than hanging or serving stale content; the tunnel
reconnected to the new pod (`orneur-api-a-64567d787d-krff5`, confirmed
via `hostname`) with no manual re-linking. Post-recycle `/readyz`
classification unchanged and correct (see Health section).

## Deployment promotion record (Step 25)

This phase's commits, in order, each triggering a real redeploy of
`orneur-api-a` (or explicitly excluded by `pathIgnoreRules` where
noted):

| Commit | Summary |
|---|---|
| `a6d8537` | Fix real cross-tenant session leak found during tenant-isolation testing |
| `4442fd5` | Centralize session-ownership enforcement in `_get_session()` |
| `b6b4fac` | Step 19 real auth + tenant isolation test through the public edge |
| `e46ae3b` | Fix Step 19 test script bugs |
| `37099d5` | Make `_Session` brain/agent construction lazy (fixes the docs-upload 500) |
| `e9566f2` | Regression test for the lazy-brain fix, global request-size limit, trusted-proxy live-fix workflow step |
| `eda584f` | Route inventory, WAF/rate-limit baseline, secret-scope/leak review steps (docs/workflow only — excluded by `pathIgnoreRules`, no redeploy) |
| `1c79107` | Tunnel outage/recovery and origin pod-recycle observation steps (workflow only — excluded, no redeploy) |

Each code-touching commit's redeploy was confirmed via a distinct pod
hostname change and a passing `/readyz`/`health_check` dispatch before
proceeding to the next step.

## Rollback drill (Step 26)

**NOT_EXECUTED as a live backward rollback this phase**, by deliberate
decision: the current HEAD carries the real, previously-unknown
tenant-isolation fix (Step 19) and the docs-upload fix; a genuine
rollback drill would mean deploying a PRIOR commit that lacks the
tenant-isolation fix, even briefly — directly conflicting with the
standing instruction "do not weaken tenant isolation." The rollback
MECHANISM itself is verified structurally and repeatedly: every commit
this phase (see Step 25 table) went through the identical
git-push -> Northflank-git-trigger -> redeploy -> health-check pipeline;
a rollback is the same pipeline run against an older commit, and there
is no reason to believe it would behave differently. A full backward
rollback drill is recommended as Phase 15 follow-up work, once a
disposable staging environment (not this active security-fix-bearing
one) exists to safely go backward and forward again.

## Canary truth (Step 27)

**NOT_AVAILABLE.** `orneur-api-a` runs a single instance on a
Northflank Developer Sandbox-tier plan; there is no traffic-splitting
router or multi-replica deployment in front of it. Every deploy this
phase was a full cutover (old pod terminates, new pod takes over),
never a canary. This is stated explicitly per the standing instruction
not to call sequential deploys "canary."

## Secret-scope review (Step 28)

Live check, run 34103047188:
- Two distinct project-level secret groups exist:
  `orneur-phase14b-runtime` and `orneur-edge-tunnel-runtime` — separate
  names matching each service's own naming convention.
- `orneur-api-a`'s own DIRECT env keys: exactly
  `["APP_URL", "ORNEUR_ALLOWED_ORIGINS", "ORNEUR_PUBLIC_EDGE",
  "ORNEUR_TRUSTED_HOSTS", "ORNEUR_TRUSTED_PROXY_CIDRS", "PUBLIC_URL"]`
  — no real secrets in its own direct env; real secrets
  (`ORNEUR_DATABASE_URL`, `ORNEUR_AUDIT_KEY`, etc.) are inherited from
  its linked group.
- `orneur-edge-tunnel`'s own DIRECT env keys: `[]` (empty) — its
  `TUNNEL_TOKEN` lives in its own separate linked group
  (`orneur-edge-tunnel-runtime`), never in `orneur-api-a`'s.
- GitHub Actions secrets used by this workflow
  (`NORTHFLANK_API_TOKEN`, the DB/audit/signing secrets used for local
  regression steps) are a completely separate store (GitHub's own
  secret store) from either Northflank secret group.
- **Known limitation of this specific check**: the script's attempt to
  print each service's linked-group ID directly (via a guessed JSON
  field name) returned `"n/a"` for both services — the correct field
  name in Northflank's `get service` response wasn't identified. The
  evidence above (distinct group names matching each service, correct
  key segregation in each service's direct env, TUNNEL_TOKEN absent
  from orneur-api-a and vice versa) is still strong, real evidence of
  no sharing — just not a direct "service X links to group Y" printout.

## Secret-leak scan (Step 29)

Live check, run 34103064419 — repo tracked files (excluding
lockfiles/`node_modules`/`.venv`) and the last 100 commits' diffs,
grepped for private-key headers, AWS-style access keys, high-entropy
`secret`/`token`/`password`/`api_key` assignments, and DB URLs with
embedded credentials:

- All matches were benign: `.env.example`'s commented, placeholder-only
  template lines (`# ORNEUR_DATABASE_URL=***host:5432/database`),
  `docker-compose.yml`'s local-dev-only default-value pattern
  (`${ORNEUR_DB_PASSWORD:-change-me-in-production}`), and a false
  positive from this phase's own qualification test script matching a
  literal string `"not-a-real-token-at-all"` (a deliberately fake
  token used to test 401 handling).
- Only one `.env`-shaped file is tracked: `.env.example` — the
  standard template convention. No real `.env` file is tracked.

**NEW_SECRET_LEAKAGE = 0.**

## Observability baseline (Step 30)

Not newly built this phase — documented as a known gap for Phase 15,
consistent with "don't over-build" guidance:
- `orca/serve/metrics.py` (`/api/admin/metrics`, `/metrics` Prometheus
  exposition) already exists and was exercised indirectly (every
  `health_check`/`verify_*` dispatch hit endpoints it instruments).
- No dashboards, alerting, or log aggregation exist beyond Northflank's
  own per-service log viewer (`get service logs`, used extensively
  throughout this phase for diagnosis) and GitHub Actions run logs
  themselves as the qualification record.
- Recommended Phase 15 scope: wire `/metrics` behind Cloudflare Access
  (see Step 14 above) and stand up a real scrape target, rather than
  building a bespoke dashboard now.

## Repeatability (Steps 31/32)

- Auth + tenant isolation (Step 19): **4 clean runs** (3 required +
  1 regression re-check), all `ALL_PASS`.
- TLS/origin/CORS/security-headers battery (`verify_public_edge`):
  run repeatedly across this phase (initial diagnosis, post-Bot-Fight-Mode-fix
  verification x3, post-trusted-proxy-fix verification) — consistently
  clean once the Bot Fight Mode and HSTS root causes were fixed.
- Trusted-proxy/Host/size-limit/SSRF-scope battery
  (`verify_edge_controls_batch2`): 1 clean run (34102504494) covering
  Steps 11/12/17/20 together; not yet repeated 3x independently of the
  Step 19 regression re-check that immediately followed it in the same
  session.

## Full regression (Step 33)

**PASS.** Local suite (103 files from
`docs/orneur/phase-9/security_suite_files.txt`, includes deterministic/
security/Godmode/cancellation suites and `tests/test_web_ssrf_guard.py`):

```
916 passed, 486 warnings in 234.10s (0:03:54)
```

Zero failures. The separately-flagged chromadb ordering flake (below)
did NOT trip in this full-suite run -- pytest's actual collection/
fixture interaction across all 103 files did not reproduce the
two-file isolated repro. Still worth root-causing (task already
filed) since it remains a real, reproducible risk under the narrower
two-file invocation, just not one that manifested here.

Known, separately-flagged, non-security test-infra issue: running
`tests/test_doc_session_no_model_runtime.py` (new this phase) before
`tests/test_session_ownership_isolation.py` in ISOLATION (just those
two files) deterministically trips a `chromadb.errors.InternalError:
... readonly database` in 2 of the latter's 3 tests -- both files pass
100% run individually, and both passed cleanly as part of the full
916-test run above. Root-caused to something process-level in
chromadb's Rust bindings, not to either file's own logic. Flagged as a
separate follow-up task, not fixed inline this phase (out of Phase
14C's actual scope).

## Final live health (Step 34)

Private (Northflank `command-exec`, run 34103641273): 3x `/livez` →
200/200/200. `/readyz` classification:
```json
{"status":"not_ready","dependencies":{
  "model_runtime":{"status":"unavailable","reason":"No installed Ollama model found for tier 'nano' (configured: 'orca-nano') or any of its fallback tiers []. Installed models: none."},
  "authority_store":{"status":"ok","backend":"postgres"},
  "gateway":{"service_live":true,"service_ready":true,"registered_runtimes":["ollama"],"model_readiness":{}},
  "security_root":{"status":"ok","epoch":32},
  "core_database":{"status":"ok"}
}}
```
Exactly the required, unaltered semantics: `authority_store`,
`security_root`, and `core_database` all `ok`; only `model_runtime`
unavailable.

Public (`https://staging.orneur.com/livez`, via GitHub Actions runners
only — see the correction note above): 200 confirmed repeatedly across
today's runs (pre-restart, post-recovery, and 20+ poll samples across
the Step 23/24 drills), most recently at the end of the Step 24 drill
(t+40s = 200).

## Remaining work before final PASS

None. All required Phase 14C steps are closed and evidenced above.
