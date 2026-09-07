# Phase 14C Steps 15/16 — WAF and Edge Rate-Limiting Capability Baseline

Zone plan: **Cloudflare Free**. No Cloudflare API token is available to this
workflow or this session (every Cloudflare-side action this phase has been
performed by the user directly in the dashboard) — so this document is a
**capability baseline**, not a configuration record. It states honestly
what the current plan allows and what is/is not currently enabled; it does
NOT claim any Pro/Business/Enterprise-only feature is available.

## WAF

| Capability | Status | Detail |
|---|---|---|
| Cloudflare Managed Ruleset | **NOT_AVAILABLE_ON_CURRENT_PLAN** | Pro plan and above only |
| Cloudflare OWASP Core Ruleset | **NOT_AVAILABLE_ON_CURRENT_PLAN** | Pro plan and above only |
| Cloudflare Exposed Credentials Check | **NOT_AVAILABLE_ON_CURRENT_PLAN** | Pro plan and above only |
| Free Managed Ruleset | **AVAILABLE** | smaller free-tier managed ruleset, distinct from the above; not confirmed enabled/disabled for this zone as of this writing |
| Custom (user-defined) WAF rules | **AVAILABLE** | Free plan cap: **5 rules** total in the `http_request_firewall_custom` phase. None currently configured for this zone. |
| Bot Fight Mode | **CONFIGURED — DISABLED** | Was enabled by default; the user disabled it after it was found to be the cause of intermittent 403s during Step 8/9 qualification (Free plan has no scoping/exception mechanism for it, so disabling was the only option) |
| DDoS protection | **AVAILABLE (automatic)** | applies to all Cloudflare plans including Free, no configuration needed |
| Always Use HTTPS | **CONFIGURED — ENABLED** | user-enabled during Step 8; confirmed via live redirect test (`http status=301`) |

Source: https://developers.cloudflare.com/waf/managed-rules/,
https://developers.cloudflare.com/waf/custom-rules/

## Rate Limiting (edge-level, Cloudflare)

| Capability | Status | Detail |
|---|---|---|
| Cloudflare-edge rate limiting rules | **AVAILABLE** | Free plan cap: **1 rule**. None currently configured for this zone. |

Source: https://developers.cloudflare.com/waf/rate-limiting-rules/

Application-level rate limiting (`orca/serve/ratelimit.py`) is already
implemented and audited independently (Phase 14C Step 1 truth audit) —
covers `/api/chat`, `/api/stream`, `/api/code/run`, `/api/docs/upload`,
`/api/auth/signup`, `/api/auth/login`, `/api/auth/forgot-password`. The
edge-level rule above would be an ADDITIONAL layer in front of that, not
a replacement for it.

## Deliberately not configured this phase

Both the one available rate-limiting rule and the five available custom
WAF rule slots are real, available hardening this zone has not yet used —
but configuring either requires a Cloudflare dashboard action, and this
phase's standing instruction was to interrupt the user for only the
Cloudflare Access dashboard step (Steps 14/20/21), not for every optional
Free-plan capability. This is recorded as a known, available-but-unused
capability for the user to enable at their discretion, not a blocking gap:
the actual security boundary for this deployment is the private Northflank
origin + Cloudflare Tunnel (no direct route to the origin exists at all,
proven in Step 9), with the application's own auth/rate-limit/CORS/
trusted-host/session-ownership controls as the next layer — Cloudflare's
edge WAF/rate-limiting would be defense-in-depth on top of that, not the
primary control.
