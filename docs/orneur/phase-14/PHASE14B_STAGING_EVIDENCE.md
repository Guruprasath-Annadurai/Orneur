# Phase 14B — Real Northflank/Supabase Staging Evidence

Real evidence only. No field below is fabricated; NOT_EXECUTED/BLOCKED
fields are stated as such.

## Repository / deployment identity

- Git SHA (live, deployed): `a3f3106159b39ac2b6fd31d7238c19fbd6a8285e` (PR #2 merge commit)
- Northflank project: `orneur-phase14b-staging`
- Northflank service: `orneur-api-a`
- Region/cluster: `nf-europe-west` (Europe West / London)
- Runtime plan: `nf-compute-20` deployment plan, 1 instance, port `7337` (`public: false`, `vpcAccessible: false` — confirmed private)
- Liveness probe: HTTP `/livez`, `initialDelaySeconds: 20`, `periodSeconds: 30`, `timeoutSeconds: 5`, `failureThreshold: 3`
- Latest build: `SUCCESS`, `deployedSHA` confirmed `a3f3106159b39ac2b6fd31d7238c19fbd6a8285e`
- Current pod: `orneur-api-a-7f8b899f46-zwdnb`

## Final closure (post-rotation, post-merge)

After the READY=YES report above, the two exposed database passwords
(security-root project `ttfpohasqgdeifpjfodu`, core project
`rqupsugllpxscirandhm`) were rotated by the account owner directly in
Supabase, and the corresponding Northflank secret values were updated
(`ORNEUR_SECURITY_ROOT_DATABASE_URL`, `ORNEUR_DATABASE_URL` +
`ORNEUR_GODMODE_DATABASE_URL`) — no value was ever pasted into or
printed by this session.

A controlled `northflank restart service` produced a fresh pod
(`orneur-api-a-87954597c-wfzwb`) that started clean on the newly
rotated credentials: no `DeploymentConfigError`, all three backends
(security-root/authority/core) passed, `/livez` returned `200` on 3
checks spaced ~40s apart (19:08:16 / 19:09:08 / 19:09:53 UTC),
`/readyz` returned `503` with `authority_store: ok`, `security_root:
ok`, `core_database: ok`, and only `model_runtime: unavailable` —
classified `EXPECTED_NOT_READY`, exactly as this codebase's readiness
semantics require.

A final leak audit (tracked files, full git history, all local
diagnostic scripts/logs) found nothing beyond the pre-existing test
fixture placeholder (`hunter2@example.com`) — `NEW_SECRET_LEAKAGE = NO`.

PR #2 (`phase14b-prep-hardening-2026-09-05`) was reviewed once more
(CI green, 0 merge conflicts, no secret material) and merged — merge
commit `a3f3106159b39ac2b6fd31d7238c19fbd6a8285e`. This triggered a
real Northflank rebuild+redeploy, verified independently rather than
trusted from GitHub CI alone: new pod `orneur-api-a-7f8b899f46-zwdnb`,
`deployedSHA` confirmed matching the merge commit, clean startup,
`/livez` → `200`/`200`/`200` (19:13:35 / 19:14:27 / 19:15:14 UTC),
`/readyz` → `503` `EXPECTED_NOT_READY` with the same all-dependencies-ok
breakdown, 0 restarts throughout.

**PHASE 14B STAGING BASELINE: FULLY CLOSED (staging-runtime scope).**
Distributed multi-host qualification remains separately NOT_EXECUTED.
Per the architecture correction accepted mid-session, the future Host
B is an ephemeral GitHub Actions runner, not this Mac — the Mac holds
no staging/production runtime, models, authority, or security-root
state.

## Timeline (what actually happened, in order)

1. **First diagnosis** (~17:57 UTC): pod `orneur-api-a-659947fddf-rvqwp` crash-looping on `DeploymentConfigError: security-root backend unreachable`, every ~5-6 min.
2. **Secret-group scope restriction applied** (`orneur-phase14b-runtime` → restricted to `orneur-api-a` only) — this write itself triggered an automatic fresh redeploy (new pod `sdnzx`), which **incidentally fixed the security-root gate**: the fresh pod's startup log showed validation advancing past security-root to `DeploymentConfigError: authority backend unreachable` instead. (Correction accepted: the 64-hex-char password shape was not evidence of a copy-paste mistake, per the user's correction — the real explanation was a stale secret revision on the old pod, not a wrong value.)
3. User reset the core DB password in Supabase and updated the Northflank secret. Pod did **not** pick it up automatically (plain secret-value edits don't force a redeploy the way a restrictions change did) — same pod, same error, for ~19 minutes after the update.
4. **Redacted verification, safely**: piped Northflank's `get service runtime-environment` output directly into a local Python script (`psycopg.connect`) that only ever printed a classification, never the DSN. Result: **all three DSNs (`ORNEUR_SECURITY_ROOT_DATABASE_URL`, `ORNEUR_GODMODE_DATABASE_URL`, `ORNEUR_DATABASE_URL`) → `CONNECTED`**. Credentials were correct; only the running pod's cached environment was stale.
5. **Forced an explicit `northflank restart service`** — new pod (`6d8657dfc6-mkhvm`) came up clean: no `DeploymentConfigError`, "Orca Server" banner printed, sustained `TASK_RUNNING` for 4+ continuous minutes.
6. **Signing-secret rotation** (`ORNEUR_AUDIT_KEY`, `ORNEUR_GODMODE_LEASE_SECRET`, `ORNEUR_AUTH_SECRET`) performed to remediate the earlier incidental exposure — generated locally (`secrets.token_hex(32)`), applied via a script that fetched the current secret payload, merged in the three new values, patched, and deleted its own temp file; **no value was ever printed**. Restarted again — new pod (`747d45fcfd-lqsb7`) came up clean, sustained stable for 160s+.
7. **Held commits pushed** (CORS allowlist fix `825befa` + this evidence doc `796768d`) — triggered a full Northflank rebuild+redeploy (not just a restart). New pod (`698f54759f-nsq2t`), `deployedSHA` confirmed as `796768d9a2...`, build `SUCCESS`, "Orca Server" banner, stable.

## Database backends

| Backend | Status |
|---|---|
| security-root (`ttfpohasqgdeifpjfodu`) | **PASS** — confirmed by startup validation advancing past it (step 2), and again on every subsequent clean boot |
| authority (`rqupsugllpxscirandhm`, shared with core) | **PASS** — confirmed `CONNECTED` via redacted probe (step 4) and by clean startup thereafter |
| core application DB (`rqupsugllpxscirandhm`) | **PASS** — same DSN as authority, confirmed `CONNECTED` via redacted probe |

## Health

- `/livez`: **PASS** (inferred from strong operational evidence — sustained `TASK_RUNNING` across three consecutive deploys, each well past the liveness probe's `failureThreshold: 3 × periodSeconds: 30 = 90s` window, with the app's own startup banner confirming the HTTP server bound successfully). A direct external curl was attempted via `northflank forward` port-tunneling but the tunnel itself failed at the WebSocket layer (Northflank-side tunnel issue, unrelated to app health) — not pursued further as unnecessary given the above.
- `/readyz`: **NOT_EXECUTED** — not directly curled (same tunnel limitation); expected to report `model_runtime: not ready` per this codebase's existing readiness semantics (model runtime is intentionally required and none is connected in this staging topology yet). Not a defect.

## Security

- Secret leakage: **ADDRESSED, not undone** — the incidental exposure (all three DSNs + all three signing secrets, printed in full during diagnosis) happened and cannot be un-happened. Remediation completed for what could be remediated without further owner action: the three signing secrets were rotated (see timeline step 6). The two DB passwords were **not** rotated again in this session — already rotated once by the user during diagnosis, and rotating again immediately after finally achieving a stable, verified connection was judged higher-risk than beneficial for a staging environment with no real traffic yet. **Recommendation, not yet executed: rotate both DB passwords once more at the user's convenience**, since the current ones were exposed in this transcript.
- Secret scoping: **FIXED** — `orneur-phase14b-runtime` confirmed `restricted: true`, `nfObjects: [{id: orneur-api-a, type: service}]`. A future `cloudflared` service will not inherit these secrets unless explicitly added.
- CORS public-safety: **FIXED and deployed** — `ORNEUR_ALLOWED_ORIGINS` env-driven allowlist, default `"*"` preserved (private staging, port not public). Live in the current deployed SHA.
- Fail-closed validation preserved: **CONFIRMED, untouched** — `orca/godmode/deployment_profile.py` was never modified. Every fix this session was infrastructure/secret-side, not a weakening of the validation code.

## Tests

- Deterministic (`pytest -m "not live_ollama_smoke"`): **1551 passed, 0 failed, 43 deselected** (414.85s).
- Security suite: **886 passed, 0 failed, 4 deselected** (71.74s), re-run after the CORS change — confirmed unaffected.
- Production Docker build: **PASS** (local rebuild + Northflank's own real rebuild on push, both green).
- Container boot smoke: **PASS** — local (SOVEREIGN, no cloud deps) and real (DISTRIBUTED, real Supabase, on Northflank) both confirmed clean.
- PR #2 CI (`phase14b-prep-hardening-2026-09-05` @ `799c977f`): **PASS**.

## Cloudflare

**NOT_EXECUTED.** Now correctly unblocked (Host A is stable) but not started this session — design already recorded in `CLOUDFLARE_STAGING.md` / PR #2.

## Mac Host B

**NOT_EXECUTED.** Now correctly unblocked. Not started this session.

## Distributed cross-host qualification

**NOT_EXECUTED.** Gated behind Cloudflare/Host B above.

## PR #2 disposition

**Still NOT MERGED, but now genuinely reviewable.** CI green, and the live runtime gate this PR's own description required ("DO NOT MERGE until orneur-api-a runtime startup, real Supabase connectivity, and liveness are confirmed") is now **satisfied**. Recommend merging in the next session/step, since it primarily adds `.dockerignore`, updated docs, and CI coverage — no conflict with the CORS fix or evidence doc already pushed directly to the tracked branch.

## Remaining items (none blocking further real progress)

1. **Recommended, not required**: rotate the two Supabase DB passwords one more time, since they were exposed in this transcript during diagnosis (the signing secrets already were rotated).
2. Unrelated: a live-looking `SUPABASE_DB_URL` (different project ref, `klmwupxkgtgeqbgkvdgk`) found set in this Mac's shell environment; not part of Phase 14B's two databases; recommend the user locate and rotate/remove it.
3. PR #2 merge — recommended, not yet executed (see above).
4. Cloudflare setup and Mac Host B — not started, both now correctly unblocked.

**PHASE 14B STAGING BASELINE READY: YES**
(Distributed multi-host qualification remains separately NOT_EXECUTED — do not read this as Phase 14B being fully closed.)
