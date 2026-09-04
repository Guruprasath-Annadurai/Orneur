# Phase 14B §7-10 — Cloudflare Staging Edge

**Status: NOT_EXECUTED.** No Cloudflare account, zone, or Tunnel is
configured in this environment (confirmed: `cloudflared` not
installed, `~/.cloudflared` does not exist — see
`REAL_STAGING_TOPOLOGY.md`). This document records the design to
implement once the OWNER ACTION REQUIRED checkpoint is resolved and a
real VPS (Host A) exists to tunnel to.

## Design (once real infrastructure exists)

```
Internet → Cloudflare edge → Cloudflare Tunnel → ORNEUR staging ingress (Host A)
```

- **Cloudflare Tunnel preferred over exposing a public HTTP port** on
  Host A (spec §7) — `cloudflared` runs on Host A, makes an
  **outbound-only** connection to Cloudflare's edge, so Host A's
  firewall never needs an inbound rule for HTTP traffic at all. This
  directly satisfies spec §9's "direct origin isolation" requirement
  structurally, not just by convention.
- **Never tunnel/expose**: Postgres, Redis (if deployed), the security-
  root backend, or any model-worker admin endpoint. Only the ORNEUR API
  ingress port is tunneled.
- **Owner checkpoint** (spec §8): Tunnel authorization
  (`cloudflared tunnel login`) is an interactive browser-based flow —
  this session would run the command and report the browser URL for
  the owner to complete, never request a pasted credential. A scoped
  Cloudflare API token (not the Global API Key) would be used only if
  Cloudflare-side automation (DNS record creation, Tunnel route
  configuration) is needed beyond what `cloudflared`'s own CLI handles
  interactively.

## Direct-origin bypass test (spec §9) — design

Once configured: attempt a direct HTTP connection to Host A's public IP
on the ORNEUR service port. Required result: connection refused or
timed out (no inbound firewall rule permits it) — `DIRECT_ORIGIN_BYPASS`
audit counter would be `0` only once this is actually executed and
observed, not assumed from the Tunnel's outbound-only design alone.

## Trusted proxy header validation (spec §10) — design

Once Cloudflare is the reverse proxy, `CF-Connecting-IP`/
`X-Forwarded-For` headers must only be trusted when a request
genuinely arrived via Cloudflare's tunnel — spoofed headers sent
directly to Host A (bypassing Cloudflare) must not be trusted, since a
direct connection to Host A should already be refused per the bypass
test above; the header-trust boundary is a second layer of defense in
case that first layer is ever misconfigured. **No code in this
codebase currently validates Cloudflare-specific proxy headers**
(confirmed: no such validation exists in `orca/serve/api.py`) — this
was already noted as a concrete TODO in `CLOUDFLARE_ARCHITECTURE.md`
from the earlier local-foundation phase, unchanged this phase since
there is still no real Cloudflare deployment to validate against.

## Not executed

Everything in this document beyond the design itself: no Tunnel
exists, no zone is configured, no direct-origin test has been run, no
trusted-proxy-header test has been run.
