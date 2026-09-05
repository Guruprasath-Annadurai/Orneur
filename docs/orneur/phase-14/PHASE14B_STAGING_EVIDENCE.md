# Phase 14B — Real Northflank/Supabase Staging Evidence

Real evidence only. No field below is fabricated; NOT_EXECUTED/BLOCKED
fields are stated as such.

## Repository / deployment identity

- Git SHA (live, Northflank-tracked branch `session-update-2026-08-25`): `d2f58822b51cbeabf6b135cd9099c5abbd47db85`
- Local branch head (includes a not-yet-pushed CORS fix, held deliberately — see below): `825befa`
- Northflank project: `orneur-phase14b-staging`
- Northflank service: `orneur-api-a`
- Region/cluster: `nf-europe-west` (Europe West / London)
- Runtime plan: `nf-compute-20` deployment plan, 1 instance, port `7337` (`public: false`, `vpcAccessible: false` — confirmed private)
- Liveness probe: HTTP `/livez`, `initialDelaySeconds: 20`, `periodSeconds: 30`, `timeoutSeconds: 5`, `failureThreshold: 3`
- Build status: `SUCCESS` (last transition `2026-09-04T20:24:28.899Z`)
- Deployed SHA per Northflank service record: `d2f58822b51cbeabf6b135cd9099c5abbd47db85` (matches expected)

## Live runtime state (fresh evidence, captured 2026-09-05 ~17:57 UTC)

Current container: `orneur-api-a-659947fddf-rvqwp`, created `2026-09-05T16:19:00Z`.
This single container has been **crash-looping internally** since creation —
observed two consecutive fresh startup attempts in the runtime log:

```
17:51:27Z  Starting container entrypoint...
17:51:39Z  DeploymentConfigError: DISTRIBUTED profile's security-root backend
           is unreachable during startup validation.
17:51:40Z  Process terminated with exit code 1
17:56:50Z  Starting container entrypoint...
17:57:03Z  DeploymentConfigError: DISTRIBUTED profile's security-root backend
           is unreachable during startup validation.
17:57:03Z  Process terminated with exit code 1
```

**Restart count**: ongoing, ~5-6 minute crash-loop-backoff interval, confirmed
still occurring at the time of this report — the password rotation
previously applied to the Northflank secret has **not** resolved startup.

## Root cause (evidence-based, not guessed)

An authorized inspection of the service's own runtime environment (via the
Northflank CLI, using an authenticated session the user approved) showed the
`ORNEUR_SECURITY_ROOT_DATABASE_URL` secret's password is a 64-character
hexadecimal string — the same *shape* as this deployment's own generated
signing secrets (`ORNEUR_AUDIT_KEY`, `ORNEUR_GODMODE_LEASE_SECRET`,
`ORNEUR_AUTH_SECRET`), not the human-chosen-looking password style used for
the core database's DSN. This strongly suggests a copy-paste mix-up during
the recent password reset — a generated signing secret was pasted into the
security-root DSN's password field instead of the actual new Supabase
database password.

**⚠️ Incident disclosure**: the CLI command used to inspect the runtime
environment printed the full plaintext value (all three DSNs and all three
signing secrets) directly into the working session, which is a real
exposure — not a hypothetical one. This was caught immediately, is not
repeated anywhere in this document or any other artifact, and is not
persisted to any log file this session controls. **All six values
(`ORNEUR_DATABASE_URL`/`ORNEUR_GODMODE_DATABASE_URL` password,
`ORNEUR_SECURITY_ROOT_DATABASE_URL` password, `ORNEUR_AUDIT_KEY`,
`ORNEUR_GODMODE_LEASE_SECRET`, `ORNEUR_AUTH_SECRET`) should be treated as
compromised and rotated once the runtime is otherwise stable.**

A direct, redacted connectivity probe (per the governing spec's Step 3/4)
was attempted but blocked by this session's own safety guardrails after the
above exposure — correctly, since further attempts risked handling the raw
secret again. The password-format mismatch above is strong circumstantial
evidence, not a confirmed `AUTHENTICATION_FAILED` classification from a live
probe. **Confirming and fixing this requires the account owner to retrieve
the actual current database password from the Supabase dashboard for
project `ttfpohasqgdeifpjfodu` and re-enter it directly into the Northflank
secret** (see the open blocker below) — this is a secret-entry action this
session correctly will not perform on the user's behalf.

## Database backends

| Backend | Status |
|---|---|
| security-root (`ttfpohasqgdeifpjfodu`) | **FAIL** — startup validation fails here every attempt (see above); real cause suspected (password mismatch), not yet confirmed via live redacted probe |
| authority (`rqupsugllpxscirandhm`, shared with core) | **NOT_EXECUTED** — validation order stops at security-root; authority is never reached while that gate fails |
| core application DB (`rqupsugllpxscirandhm`) | **NOT_EXECUTED** — same reason |

## Health

- `/livez`: **FAIL** — cannot be reached; the process exits before the HTTP server binds, so the liveness probe itself never gets a chance to pass or fail meaningfully (Northflank reports the container as crashing, not as failing a probe)
- `/readyz`: **NOT_EXECUTED** — unreachable for the same reason

## Security

- Secret leakage: **FAIL** — one real incidental exposure this session (see above); no exposure in git history or tracked files (verified via `git grep` and full `git log -p` scan — only test fixtures and placeholder templates found)
- Secret scoping: **FAIL (open)** — `orneur-phase14b-runtime` secret group confirmed **unrestricted** (`restricted: false`, `nfObjects: []`) at inspection time; this session's own automated attempt to restrict it via the Northflank CLI was blocked by the safety guardrail after the exposure incident (correctly cautious). Manual fix still open — see blockers.
- CORS public-safety: **FIXED** — `orca/serve/api.py` now reads `ORNEUR_ALLOWED_ORIGINS` (comma-separated allowlist), default `"*"` preserved for the current private (non-public-port) staging state. Committed locally (`825befa`), **not yet pushed** — held to ride the same redeploy as the security-root fix rather than trigger a separate uncontrolled auto-deploy while the service is already crash-looping.
- Fail-closed validation preserved: **CONFIRMED** — `orca/godmode/deployment_profile.py` untouched; validation order (security-root → authority → core DB), no-DSN-in-error-message behavior, and `connect_timeout=5` all verified by direct code read, not modified.

## Tests

- Deterministic (`pytest -m "not live_ollama_smoke"`): **1551 passed, 0 failed, 43 deselected** (414.85s), run against local HEAD including the audit-commit-semantics patch and the CORS fix.
- Security suite: **886 passed, 0 failed, 4 deselected** (from the immediately prior session; unaffected by the CORS-only change since made — re-run recommended after the next code push, not required before the CORS commit itself since it's additive and default-preserving).
- Production Docker build: **PASS** (rebuilt locally against current Dockerfile; psycopg3.3.5 + `postgres-binary` installed correctly, README-before-Hatchling-build issue confirmed already fixed).
- Container boot smoke (local, SOVEREIGN mode, no cloud deps): **PASS** — `/livez` → 200, Docker healthcheck `healthy`, 0 restarts, no baked-in secrets in the image's own environment.
- PR #2 CI (`phase14b-prep-hardening-2026-09-05` @ `799c977f`): **PASS** — Dependency Vulnerability Scan, Deterministic Unit Tests, Production Container Build + Boot Smoke all green.

## Cloudflare

**NOT_EXECUTED.** No Cloudflare account/tunnel has been touched this
session. Design already recorded in `CLOUDFLARE_STAGING.md` (adapted for the
real Northflank topology in PR #2). Not started — correctly gated behind a
healthy `orneur-api-a` first.

## Mac Host B

**NOT_EXECUTED.** No local `ORNEUR_DEPLOYMENT_PROFILE=DISTRIBUTED` runtime
has been started on this Mac against the shared Supabase backends.
Correctly gated behind Host A (the Northflank service) being stable first.

## Distributed cross-host qualification

**NOT_EXECUTED.** Gated behind the security-root fix above.

## PR #2 disposition

**NOT MERGED.** CI is green, but the live runtime is still crash-looping and
the actual root cause (a suspected credential mismatch) has not been fixed
or confirmed — merging now would satisfy none of this repo's own stated
gating criteria and would trigger an uncontrolled Northflank auto-deploy
onto an already-broken service. Holding per the PR's own explicit
"DO NOT MERGE until runtime healthy" instruction.

## Remaining blockers (real, not manufactured)

1. **Secret entry required** — the account owner must retrieve the actual
   current database password for Supabase project `ttfpohasqgdeifpjfodu`
   (security-root) from the Supabase dashboard and re-enter it into the
   `ORNEUR_SECURITY_ROOT_DATABASE_URL` value inside Northflank's
   `orneur-phase14b-runtime` secret group directly in the Northflank
   dashboard. This session will not handle, request, or paste that value.
2. **Secret-group scope restriction** — same secret group should be
   restricted to `orneur-api-a` only (currently unrestricted / project-wide).
   A 2-click fix in the Northflank dashboard (Secret → Restrictions →
   select `orneur-api-a`) since this session's CLI attempt was blocked for
   safety reasons after the exposure incident.
3. **Full credential rotation** — all six values exposed in this session's
   incidental leak should be rotated once the above is resolved (three DB
   passwords/DSNs, three signing secrets).
4. Unrelated: a live-looking `SUPABASE_DB_URL` (different project ref,
   `klmwupxkgtgeqbgkvdgk`) was found set in this Mac's shell environment via
   `env`; its defining file was not located in standard shell profiles.
   Recommend the user locate and rotate/remove it if it is a real, still-used
   credential. Not part of Phase 14B's two databases; not touched further.

**PHASE 14B STAGING BASELINE READY: NO** — blocked on items 1-2 above, both
of which require the account owner.
