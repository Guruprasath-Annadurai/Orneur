# Entitlement Policy Audit — Pre-Phase-3.1

Read before any Phase 3.1 code was written. Maps exactly how `/api/chat`, `/api/stream`, and `/api/ultra` currently enforce plan/tier/subscription/model-access, and every point where commercial entitlement, model capability tier, legacy Orca tier name, and Cognitive `ModelPolicy` are conflated.

## Two separate, unrelated entitlement mechanisms coexist today

This is the single most important finding: **`/api/chat`/`/api/stream` and `/api/ultra` are gated by two entirely different systems that were never reconciled with each other.**

### Mechanism 1 — per-request authenticated user tier (`orca/auth/store.py`)

`model_access_allowed(user, model_variant)` — used by `/api/chat` (line 613) and `/api/stream` (line 774). Gates by the **authenticated HTTP user's** `user.tier` (`"free"`/`"pro"`/`"enterprise"`, read from the users database per request) against a **legacy Orca tier string** (`"nano"`/`"core"`/`"ultra"`, the `model_variant` request field):

```
nano  (Genesis)  -> always free, no restriction, anonymous included
core  (Novus)    -> free if user.tier in {pro, enterprise}, OR user.signup_seq <= 100
ultra (Aeternum) -> paid only (pro/enterprise), no free path ever
```

`check_quota(user.id, user.tier, "message")` (also per-request, per-user, DB-backed) separately caps daily message count by the same `user.tier`.

### Mechanism 2 — process-wide activated license (`orca/license/`)

`has_feature("ultra")` — used by `/api/ultra` (line 1353). Calls `current_tier()` (`orca/license/store.py`), which reads **this server process's own globally-activated license** (the CLI-style `orca activate <key>` flow) — **not** the authenticated HTTP user's database row at all. `TIER_FEATURES` (`orca/license/keys.py`) maps `free`/`pro`/`enterprise` (the *license's* tier, not the user's) to a feature set including `"ultra"`.

**Consequence, stated plainly:** on a real multi-tenant deployment, `/api/ultra`'s entitlement check has no relationship to which user is making the request — it reflects whichever license the server process itself was activated with, at the process level, shared by every user hitting that process. `/api/chat`/`/api/stream`'s entitlement check is correctly per-user. These are architecturally incompatible entitlement models running side-by-side in the same server. This is a **pre-existing** issue, not introduced by Phase 3/3.1 — but it directly affects how "commercial entitlement" can be represented as one coherent `EntitlementPolicy` type (see `POLICY_RECONCILIATION.md`): Phase 3.1's `EntitlementPolicy` is derived from `user.tier` (Mechanism 1, the correct per-request model) for `/api/chat`/`/api/stream`, and `/api/ultra`'s cutover reconciles against the SAME `user.tier`-derived policy rather than perpetuating Mechanism 2 into the new abstraction — this is disclosed as a genuine behavior consideration in `PRODUCTION_CUTOVER.md`, not silently papered over.

## Every conflation point, named explicitly

| Location | What's conflated | Detail |
|---|---|---|
| `orca/auth/store.py::model_access_allowed` | Legacy Orca tier name (`nano`/`core`/`ultra`) **is** the commercial entitlement unit | The function signature takes `model_variant` (a *model capability* selector) and returns a *commercial* allow/deny — there's no intermediate "what capability class does this user get" concept, just a direct string-keyed lookup. |
| `orca/serve/api.py` `_resolve_backend_for_chat`/`resolve_tier_backend` | Legacy tier name **is** the deployment-resolution unit | Tier strings (`nano`/`core`/`ultra`) simultaneously mean: (a) which model family (Genesis/Novus/Aeternum) is desired, (b) which commercial plan is required, and (c) what the pre-existing step-down chain falls back through. Three concerns, one string. |
| `orca/license/keys.py::TIER_FEATURES` | License tier **is** feature entitlement, independent of per-user tier | `"ultra"` feature membership is a property of the *license*, not the *user* — see Mechanism 2 above. |
| `_run_cognitive_shadow` (Phase 3, `orca/serve/api.py`) | Cognitive `ModelPolicyCharacteristic` compared directly against legacy tier string | Phase 3's shadow comparison (`record_shadow_comparison(kernel_tier, legacy_tier)`) compares `characteristic_to_tier()`'s output (`nano`/`core`/`ultra`) against `backend_resolution.tier` — this conflation was fine for *observability only* (Phase 3's explicit, disclosed scope decision in `CUTOVER.md`), but is exactly what Phase 3.1 must NOT do for real authoritative routing: never let a cognitive characteristic silently stand in for a commercial entitlement decision. |
| `orca/serve/api.py::DAILY_LIMITS` (`orca/auth/store.py`) | Quota (`messages`, `ultra` count) keyed by `user.tier` string, independent of model/capability class | Orthogonal to model-access gating — a separate deterministic cap, not itself a source of tier conflation, but must be preserved as a distinct concern in the new `EntitlementPolicy` (a rate/quota ceiling, not a capability-class gate). |

## What must NOT change (preserved product semantics)

- `nano` (Genesis) stays free/unrestricted for everyone, including anonymous users.
- `core` (Novus) stays free only for pro/enterprise tier OR the first-100-signup cohort (`NOVUS_FREE_SIGNUP_CUTOFF`).
- `ultra` (Aeternum) stays paid-only, no free path, ever.
- Daily message/ultra quotas by `user.tier` (`DAILY_LIMITS`) stay exactly as they are.
- A free-tier user must never be silently upgraded to a paid tier's model, regardless of what the Cognitive Kernel's `ModelPolicyCharacteristic` recommends (this is the exact plan-gating leak `orca/serve/registry.py`'s own docstring already warns against, and the reason Phase 3 kept `/api/chat`/`/api/stream` shadow-only — see `docs/orneur/phase-3/CUTOVER.md`).

## What Phase 3.1 changes

Introduces a typed `EntitlementPolicy` (see `POLICY_RECONCILIATION.md`) derived from `user.tier` via the EXISTING `model_access_allowed`/`DAILY_LIMITS` logic (not replacing it, wrapping it into a stable, capability-class-based shape), and an explicit reconciliation step between the Kernel's `ModelPolicy` and this `EntitlementPolicy` — so `/api/chat`/`/api/stream` can become Kernel-authoritative for PLANNING while the actual tier/model selection remains provably bound by the same commercial rules as today, never by cognitive judgment alone.
