# Phase 14 §3, §18-22 — Cloudflare Architecture (DESIGN ONLY — NOT PROVISIONED)

**Status: NOT_EXECUTED.** No Cloudflare account, zone, or domain exists
for ORNEUR in this environment. `cloudflared`/`wrangler` are not
installed on this machine. Per the governing spec's §0 rule ("when real
cloud infrastructure is required: STOP, return OWNER ACTION REQUIRED"),
this document is the design that would be implemented once an owner
provisions a Cloudflare account and domain — see the checkpoint at the
end. Nothing below has been configured, tested, or verified against a
real Cloudflare edge.

## Conceptual path (per spec §3)

```
PUBLIC INTERNET
  -> CLOUDFLARE EDGE (DDoS, WAF, bot/abuse controls, rate limiting, API security)
  -> Zero Trust / Access policy (for admin/operator surfaces only)
  -> Cloudflare Tunnel (private origin connection, no public inbound port on ORNEUR's origin)
  -> ORNEUR ingress (load balancer / ingress controller)
  -> ORNEUR API / Kernel / Gateway
  -> GCP / Azure / AWS internal services
```

## Design decisions (to implement once provisioned)

- **Origin hiding via Cloudflare Tunnel** (spec §4, §6): the ORNEUR
  origin should never have a public inbound port. A `cloudflared`
  connector, running with least privilege, makes an outbound-only
  connection to Cloudflare's edge — this removes the origin IP from any
  attacker's reach entirely (not merely "the URL is secret," which spec
  §4 explicitly rejects as insufficient).
- **Direct-origin bypass must deny** (spec §5): once a real environment
  exists, the FIRST security test to run is attempting a direct
  connection to the cloud origin, bypassing Cloudflare. Required:
  DENY/unreachable. Audit counter `DIRECT_ORIGIN_BYPASS` must be 0 —
  **cannot be measured until a real origin exists**, so it is reported
  as NOT_EXECUTED, not fabricated as 0.
- **Zero Trust for admin surfaces only** (spec §7): the public
  consumer API keeps ORNEUR's own auth (JWT, existing `orca/auth/*`);
  Cloudflare Access policy would gate only admin/deployment/
  observability/registry-administration/debug endpoints — Cloudflare
  identity never substitutes for ORNEUR's own tenant/capability
  checks (spec §25).
- **WAF as defense-in-depth, not the authority** (spec §8): common
  exploit patterns, path traversal, malformed methods, scanner
  behavior — caught at the edge where possible, but ORNEUR's own input
  validation (already exists — Pydantic models throughout
  `orca/serve/api.py`) remains the actual authority. A WAF rule set
  reduces load reaching the origin; it is not a substitute for
  application-level validation.
- **Layered rate limiting** (spec §10): Cloudflare edge rate limits
  (by IP) are independent of ORNEUR's own application-level rate limits
  (`orca/serve/ratelimit.py`, already dual-backend — in-process or
  Redis, per-tenant/per-user). The two must never be conflated into one
  budget; a Cloudflare-level block and an ORNEUR-level 429 are
  different signals for different purposes.
- **Trusted proxy header handling** (spec §24): once Cloudflare is the
  reverse proxy, `CF-Connecting-IP`/`X-Forwarded-For` must only be
  trusted when the request genuinely arrived via the verified Cloudflare
  IP ranges (Cloudflare publishes these; the origin should reject any
  request not from them once Tunnel/firewall rules are in place) —
  otherwise an attacker who reaches the origin directly could spoof
  those headers. **No code in this codebase currently validates this**
  (confirmed: no Cloudflare-specific header validation exists in
  `orca/serve/api.py` — there is no Cloudflare deployment yet to
  validate against). This is a concrete TODO for Phase 14B once GCP/
  Cloudflare exist together.
- **Failover** (spec §18): if Cloudflare/Tunnel is unavailable, the
  service must become unavailable/degraded, never fall back to exposing
  the raw origin automatically. This is a network/DNS-level design
  decision (no automatic "expose origin" fallback should ever be
  configured) rather than application code.
- **Credential model** (spec §19-22): any Cloudflare automation must use
  a scoped API **token** (never the Global API Key), limited to the
  specific zone/tunnel/rule set needed, ideally against a staging zone
  first. No token has been requested or created — see the checkpoint
  below.

## OWNER ACTION REQUIRED — CLOUDFLARE

```
Provider: Cloudflare
Purpose: Public security perimeter (DDoS/WAF/rate-limit/Zero Trust/Tunnel)
         for a real ORNEUR DISTRIBUTED staging deployment
Resource: A Cloudflare account + a domain/zone for ORNEUR, a scoped API
          token (DNS + Tunnel + WAF rule permissions on that zone only),
          and (recommended) a `cloudflared` Tunnel connector credential
Authentication method preferred: scoped API token, or an interactive
          `cloudflared tunnel login` device-flow authentication
Secret/API key required in chat: NO
Owner action: create the Cloudflare account/zone if not already held;
          create a scoped API token in the Cloudflare dashboard
          (My Profile -> API Tokens -> Create Token, scoped to the
          specific zone and only DNS Edit + Cloudflare Tunnel: Edit
          permissions); provide the token via a secret-manager
          reference or local environment variable this session can
          read without the token ever being pasted into chat
Verification command: `cloudflared tunnel login` (interactive) or
          `curl -H "Authorization: Bearer $TOKEN" https://api.cloudflare.com/client/v4/user/tokens/verify`
Expected cost category: Cloudflare's free/pro tier covers WAF, basic
          DDoS, and Tunnel at no cost; Zero Trust seat pricing applies
          only if admin-surface gating needs more than the free seat
          allowance
Can continue without this action: YES — all local-foundation work
          (Phase 14A) proceeds independently of this
```

Until this action is taken, `DIRECT_ORIGIN_BYPASS`, WAF/rate-limit
staging attacks, trusted-proxy spoof tests, and the deception loop
(`DECEPTION_DEFENSE.md`) all remain **NOT_EXECUTED** — not fabricated
as passing.
