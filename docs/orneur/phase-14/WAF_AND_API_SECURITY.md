# Phase 14 §8-11 — WAF and API Security (DESIGN ONLY, PARTIAL LOCAL EVIDENCE)

**Cloudflare WAF: NOT_EXECUTED** — no Cloudflare account exists (see
`CLOUDFLARE_ARCHITECTURE.md`).

## What already exists at the application layer (confirmed, not new this phase)

- Every request body in `orca/serve/api.py` is validated via Pydantic
  models — malformed JSON, wrong types, and missing required fields are
  already rejected by FastAPI's own validation layer before any
  handler code runs. This is real, pre-existing schema validation
  (spec §9's "use API schema validation internally even if Cloudflare
  provides additional schema controls" is already true).
- `orca/serve/ratelimit.py` already implements per-tenant/per-user rate
  limiting, dual-backend (in-process or Redis) — confirmed in the Phase
  14 state audit, unchanged this phase.
- `orca/auth/*` already implements JWT-based authentication with
  quota/tier checks (`check_quota`, `increment_usage` in
  `orca/serve/api.py`'s imports).

## Not verified or built this phase

- **Oversized request body limits** — no explicit `Content-Length`
  cap was found or added in `orca/serve/api.py` beyond whatever
  Starlette's/uvicorn's defaults are. A large-body DoS test was not
  executed.
- **Method confusion / unusual HTTP protocol abuse** — not
  specifically tested this phase (would need a raw-socket test client,
  not `httpx`, to send genuinely malformed HTTP; not built).
- **Credential stuffing / rapid enumeration defenses** beyond the
  existing rate limiter — no dedicated brute-force test was run.
- **Cloudflare-layer WAF rules** — entirely NOT_EXECUTED (see above).

## Real staging attacks (spec §51) — NOT_EXECUTED

Spec §51 explicitly frames these as attacks "against our own staging
domain," which requires a deployed staging environment behind
Cloudflare — neither exists. Not attempted against the local dev server
as a substitute, since doing so would not exercise the actual claim
(Cloudflare-edge denial) the spec is asking to prove.
