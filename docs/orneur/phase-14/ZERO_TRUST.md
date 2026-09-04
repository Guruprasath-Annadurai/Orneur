# Phase 14 §7, §25 — Zero Trust (DESIGN ONLY — NOT PROVISIONED)

**Status: NOT_EXECUTED.** No Cloudflare Access / Zero Trust instance
exists. This is the design to implement once `CLOUDFLARE_ARCHITECTURE.md`'s
OWNER ACTION REQUIRED checkpoint is resolved.

## Principle (spec §7, §25)

Administrative surfaces (admin API, deployment/observability
dashboards, operator endpoints, debug endpoints, registry
administration) must not be reachable merely because a request carries
a valid login — they require an *additional*, edge-enforced identity
check before the request even reaches ORNEUR's own auth layer. The
public consumer API is explicitly excluded from this — it keeps
ORNEUR's own existing JWT/session auth (`orca/auth/*`) unchanged, and
Cloudflare Access identity is never a substitute for ORNEUR's own
tenant/capability checks (spec §25's "Edge Authentication vs
Application Auth").

## Surfaces that would be gated

Identified by reading the existing route table in `orca/serve/api.py`
(`grep -n "@app\."`): no endpoint in this codebase is currently labeled
"admin-only" at the routing layer in a way this document can point to a
line number for — this codebase does not yet have a distinct set of
admin-prefixed routes (e.g. `/admin/*`) separated from consumer routes.
**This itself is a real, disclosed finding**: implementing Zero Trust
gating well requires first establishing a clear admin-route boundary in
the application itself (e.g. an `/internal/` or `/admin/` route prefix
with its own dependency), which does not exist today. Recommended as a
prerequisite before Zero Trust policy can be meaningfully applied,
rather than gating arbitrary existing routes by guesswork.

## OWNER ACTION REQUIRED

Same checkpoint as `CLOUDFLARE_ARCHITECTURE.md` — Zero Trust is a
Cloudflare Access feature, gated on the same account/domain
provisioning. No separate checkpoint needed beyond that one.
