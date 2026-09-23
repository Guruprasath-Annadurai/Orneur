# Genesis Frontier Reference Access Matrix — Phase 21B.4.17 (terms/access reconciled in 21B.4.17.1, private-holdout gate closed in 21B.4.17.2)

**PRIMARY-SOURCE RESEARCH + CPU/METADATA ONLY. No GPU, no frontier
inference, no paid API call, no benchmark. Metadata/docs/terms only.**

Source evidence: `docs/orneur/phase-21/evidence/GENESIS_FRONTIER_REFERENCE_PRIMARY_SOURCES_2026-09-23.json`
and the six per-reference `*_REFERENCE_ADMISSION_2026-09-23.json` files.

**Phase 21B.4.17.1 correction:** MiniMax M3's access preflight was
downgraded from `PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK` to
`UNQUALIFIED` — that status requires all NON-FINANCIAL access
requirements to already be satisfied with only a live billing/credit
check remaining. A compute-prohibitive self-host path with no
identified zero-owner-cash compute grant, combined with unverified
hosted-API terms, does not satisfy that bar; it was applied too
generously in Phase 21B.4.17.

**Phase 21B.4.17.2 correction:** `access_preflight_status` now means
readiness for the FULL Genesis frontier protocol (which ultimately
includes the sealed private holdout), not merely public/internal
evaluation. DeepSeek V4.1-Flash's `access_preflight_status` is
downgraded from `PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK` to
`UNQUALIFIED` for this reason — its private-holdout compatibility is
REVIEW_REQUIRED (DeepSeek's Privacy Policy states Personal Data
including User Input may be used to train DeepSeek's own models, with
only an unexercised opt-out right and no confirmed Open-Platform-
specific no-training carve-out found). DeepSeek remains **PUBLIC-EVAL
READY** — a separate, informational, non-quorum-determining status —
via `public_eval_access_preflight_status`.

## Access paths per reference

| Reference | Self-host | First-party API | Full-protocol access preflight | Public-eval access preflight |
|---|---|---|---|---|
| DeepSeek V4.1-Flash | COMPUTE_PROHIBITIVE (763B, 20x/10x/5x 80GB GPUs) | api.deepseek.com, OpenAI-compatible, documented pricing, concurrency 2500, automated-evaluation use CLEAR under ToS §4.2 (corrected 21B.4.17.1) | **UNQUALIFIED** (corrected 21B.4.17.2 — private-holdout REVIEW_REQUIRED) | **PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK** |
| GLM-5.3 (flagship) | COMPUTE_PROHIBITIVE (753B, 19x/10x/5x) | api.z.ai OpenAI-compatible, documented pricing, ToS on benchmarking/retention NOT found | UNQUALIFIED | UNQUALIFIED |
| Mistral Large 3 | COMPUTE_PROHIBITIVE (675B, 17x/9x/5x) | La Plateforme, model slug `mistral-large-3-25-12`; pricing UNCONFIRMED, ToS body text inaccessible (client-rendered site) | UNQUALIFIED | UNQUALIFIED |
| MiniMax M3 | COMPUTE_PROHIBITIVE (428B, 11x/6x/3x — least prohibitive of the six, but no identified zero-owner-cash compute grant) | platform.minimaxi.com redirects to a `.cn` domain, not fetched this phase; third-party-sourced pricing only, ToS unverified | UNQUALIFIED (corrected 21B.4.17.1) | UNQUALIFIED |
| Qwen3.8-Max | NOT_APPLICABLE (no open weights; MUTABLE_HOSTED_API) | Alibaba Cloud Model Studio, OpenAI-compatible + native DashScope; pricing found, rate limits/context window NOT confirmed | UNQUALIFIED | UNQUALIFIED |
| Kimi K3 | COMPUTE_PROHIBITIVE (2.8T, 70x/35x/18x — largest of the six) | api.moonshot.ai (→platform.kimi.ai), OpenAI-compatible, documented pricing; trains on content by default (ToS §4) unless enterprise opt-out | UNQUALIFIED | UNQUALIFIED |

All self-host figures cite `GENESIS_FRONTIER_COMPUTE_MATRIX.md`, not redesigned this phase (no material evidence change). Every self-host figure is a **THEORETICAL_WEIGHT_FIT**, never a **PRACTICAL_FRONTIER_EVALUATION_SERVING** claim.

## Access-preflight semantics (hardened 21B.4.17.1, holdout-scoped 21B.4.17.2)

`PREFLIGHT_READY_PENDING_FRESH_ZERO_CASH_CHECK`, for **full-protocol**
purposes, means all of the following are ALREADY satisfied for a
specific, identified access path, with only a live billing/credit
check remaining:
- provider/path identity is known;
- governing evaluation terms are clear for THAT path;
- evidence retention is acceptable for THAT path;
- automated evaluation is allowed (or clearly encompassed by the
  governing terms) for THAT path;
- **private-holdout compatibility is PERMITTED for THAT path** (new
  21B.4.17.2 requirement — the locked Genesis frontier protocol
  ultimately includes the sealed private holdout, so a reference whose
  only practical access path cannot yet safely receive confidential
  holdout material must not be counted as full-protocol-ready even if
  it is perfectly usable for public/internal evaluation);
- model identity is sufficiently attributable;
- no unresolved non-financial blocker remains.

A compute-prohibitive hypothetical self-host path with no identified
compute grant does NOT satisfy this state by itself, regardless of
whether the underlying open-weight repository technically exists. A
reference that satisfies every bullet EXCEPT private-holdout
compatibility is `PUBLIC_EVAL_READY` (see
`public_eval_access_preflight_status` / `compute_public_eval_ready_count()`)
but not full-protocol quorum-ready. **No reference currently satisfies
all of the above for full-protocol purposes this phase** — see the
QUORUM section of `GENESIS_FRONTIER_REFERENCE_PRIMARY_SOURCES_2026-09-23.json`.

## Third-party shared-endpoint discipline (§12)

The registry previously carried claims that a Modal pay-per-token Shared
Endpoint exists for GLM-5.3, Kimi K3, and (incorrectly, see the Qwen3.8-Max
special note below) an artifact conflated with Qwen3.8-Max — all discovered
in Phase 21B.4.8. **None of these claims were tested, verified, or called
this phase** (would require compute/cost, forbidden per §4). Each is marked
`ACCESS PATH: UNQUALIFIED` per §12's third-party-endpoint discipline: model-
identity-serving confirmation, non-substitution evidence, and reproducibility
evidence are all currently absent for these specific claims. This does not
reject the underlying reference — GLM-5.3's evaluation admission is blocked
by its own license gap regardless; Kimi K3 remains ADMITTED via its
self-host path even with this hosted claim unqualified.

## Qwen3.8-Max special note (§23 correction)

The registry's `zero_cash_access_status` field for Qwen3.8-Max previously
named `Qwen/Qwen3.8-2.4T-A95B`'s Modal Shared Endpoint as its access path.
This was an incorrect silent substitution — Qwen3.8-Max (the API product)
and Qwen/Qwen3.8-2.4T-A95B (the open-weight artifact) are
**DISTINCT_REFERENCE_IDENTITIES**; no official Alibaba documentation states
an equivalence (only a circumstantial `license_name='qwen3.8-max'` tag on
the open-weight repo's own metadata, flagged for future compliance review,
not acted on). This phase corrects the field to describe Qwen3.8-Max's own
actual access path (the Alibaba Cloud Model Studio API).

## Mutable hosted-API identity requirements (Qwen3.8-Max only)

No provider-exposed immutable version identifier exists for the base
`qwen3.8-max` model ID. Every future call must record: exact requested
model name (base vs. dated snapshot `qwen3.8-max-0902` vs. fast-mode
`qwen3.8-max-prime`), the provider-returned `model` field, full response
metadata (`id`, `created`/`created_at`, `usage`, `system_fingerprint` or
`request_id`), exact UTC call timestamp, endpoint/workspace region,
`enable_thinking` state, sampling parameters, and tool state. Two calls at
different times cannot be assumed to hit the same underlying model.

## Evaluation-adapter compatibility (preflight only, no execution)

All six references expose an OpenAI-compatible or OpenAI-compatible-adjacent
chat-completions request format. Reasoning-mode handling varies materially:
GLM-5.3 is always-on (no disable, only effort levels); Qwen3.8-Max is
enabled by default; Kimi K3 and MiniMax M3 expose explicit thinking-mode
toggles; DeepSeek V4.1-Flash and Mistral Large 3 support thinking mode per
their documented APIs. Any future harness must record the exact reasoning
configuration per call for every reference. No task execution occurred this
phase.
