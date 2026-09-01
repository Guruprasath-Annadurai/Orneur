# Phase 3.1 Final Closure — Production Cognitive Cutover

## Scope reminder

Make the Cognitive Kernel authoritative for normal supported chat/generation requests while preserving existing subscription/entitlement rules, with an explicit, structural separation between cognitive quality policy and commercial entitlement policy. Not a Truth Fabric phase; no Evidence Graph/Deep Search/Memory Continuum expansion/Godmode work.

## Bypass audit — every user-serving generation endpoint

| Endpoint | Classification | Notes |
|---|---|---|
| `POST /api/chat` | **KERNEL_AUTHORITATIVE** | `_run_cognitive_kernel()` runs before any generation; ABSTAIN blocks generation entirely; direct-answer plans bypass AgentLoop; deferred plans use the reconciled tier. Frontier-passthrough branch is reached only after the Kernel already ran. |
| `POST /api/stream` | **KERNEL_AUTHORITATIVE** | Same authority chain as `/api/chat`, SSE-adapted. RAG-loaded sessions force deferral to the existing pipeline unconditionally (§13 compliance). |
| `POST /api/cognitive/execute` | **KERNEL_AUTHORITATIVE** | Retained from Phase 3 — internal/experimental, no session/entitlement, isolated Kernel testing surface. |
| `POST /api/ultra` | **KERNEL_AUTHORITATIVE (planning only)** | `kernel.plan()` runs on every request (never bypassed); execution remains Ultra's own distinct, deliberately deep, separately-entitled (`has_feature("ultra")`) multi-agent pipeline — preserving product differentiation per spec §10's explicit instruction not to remove it "merely for architectural purity." |
| `GET /api/status` | **NON_GENERATIVE** | Diagnostic only (`.is_available()`/`.name`), unchanged since the Phase 2.1 audit. |
| `orca chat` / `orca ultra` (CLI) | **INTERNAL_ADMIN** | Local, single-user, out of HTTP-serving/entitlement scope — unchanged classification from Phase 2.1's own audit. |
| Admin endpoints (`/api/admin/*`) | **INTERNAL_ADMIN** | Permission-gated (`require_permission`), not ordinary user generation. |

**`KERNEL_SHADOW_ONLY` count: 0.** Phase 3's shadow-only integration on `/api/chat`/`/api/stream` has been fully replaced by authoritative execution; the only thing "shadow" that remains is a post-decision comparison METRIC (`_record_shadow_verification`), which cannot influence any response — it does not constitute shadow-only Kernel authority.

**`UNEXPECTED_KERNEL_BYPASS` count: 0.** No user-serving generation endpoint was found that both (a) produces real generation output and (b) never reaches `_run_cognitive_kernel()` or an equivalent authoritative `kernel.plan()` call.

## Entitlement vs. cognitive policy — structural separation

- `CognitiveKernel.plan()` takes only a `CognitiveRequest`; it has no entitlement parameter and imports nothing from `orca.cognitive.entitlement`. Verified by inspection and by `POLICY_RECONCILIATION.md`'s property test.
- `reconcile_policy()` is a pure function of `(ModelPolicy, EntitlementPolicy)` with exactly three reachable branches (`GRANTED`/`DOWNGRADED`/`ENTITLEMENT_REQUIRED`; `ABSTAINED` defined but not reachable given `model_access_allowed`'s "nano always free" guarantee) — none of which can produce a resolved capability above the entitlement ceiling. Proven for every `(tier, ModelPolicyCharacteristic)` combination by `tests/test_cognitive_entitlement.py::test_reconciliation_never_grants_above_ceiling_property`.
- The user's own explicit tier selection additionally caps the Kernel's direct-answer path (never just the overall account ceiling) — `test_entitlement_never_upgrades_kernel_choice`.
- `EntitlementPolicy` is derived from, never a reimplementation of, the pre-existing `orca/auth/store.py::model_access_allowed`/`DAILY_LIMITS` billing rules — see `ENTITLEMENT_POLICY_AUDIT.md`.

## Model lifecycle governance — unchanged, re-verified through the authoritative path

- Aeternum: zero registered deployments; a `DEEP`-classified request through real `/api/chat` never claims an Aeternum identity in its response (`test_aeternum_still_unavailable_through_kernel_authoritative_chat`).
- Novus: deployments continue registering as `EXPERIMENTAL` lifecycle through the now-authoritative chat path (`test_novus_deployment_stays_experimental_through_authoritative_chat`).
- Genesis: legacy/canonical distinction re-verified at the Kernel-policy level (`test_genesis_legacy_and_canonical_stay_distinct_through_kernel_policy`, Phase 3, unaffected by this phase's changes since `characteristic_to_tier`/`brain_for_tier_resolution` were not touched).

## RAG and agent compatibility

Verified end-to-end against real Ollama: a session with loaded documents unconditionally uses the existing Deep RAG pipeline regardless of any single message's cognitive plan (`test_rag_forces_deferral_to_existing_stack_when_docs_are_loaded`); a message whose plan requires `USE_TOOL` is still executed by AgentLoop's own tool-use loop, untouched (`test_tool_requiring_message_still_defers_to_agentloop`).

## Cancellation and observability

- Client disconnect on the now-authoritative `/api/stream` path reaches the same proven cancellation chain built in Phase 2.1/3 (`sync_bridge.py`'s cancellable-task cancellation, `ModelGateway`'s permit release) — verified via `test_stream_cancellation_through_the_real_authoritative_path`.
- `trace_id` propagates from `CognitiveRequest` through `InferenceRequest.trace_id` into real Gateway metrics (`test_trace_id_propagates_from_request_into_gateway_metrics`).
- `CognitiveTrace` gained `entitlement_ceiling`/`effective_capability`/`reconciliation_outcome`/`resolved_tier` fields (labels only, no raw prompts/user IDs) for the new reconciliation step.

## Security

Re-run full security suite: 31 passed (unchanged from Phase 2.1/3). Specifically verified in this phase: entitlement escalation via user-supplied request metadata is impossible (`test_metadata_cannot_manufacture_entitlement` — extra JSON fields are silently dropped by Pydantic validation and have zero effect); the explicit 402 gate for an unentitled tier request is completely unchanged (`test_free_user_explicit_ultra_request_still_gets_the_existing_402`); risk classification never grants a capability (structural — `RiskAssessment` has no code path into `EntitlementPolicy` or `reconcile_policy`).

## Test suite state

Full suite: **[see final report]**. New tests this phase: `tests/test_cognitive_entitlement.py` (12), 3 new real-Ollama tests in `tests/test_cognitive_kernel.py`, `tests/test_api_production_cutover.py` (13, real end-to-end). All real-Ollama tests auto-skip (not fail) when Ollama is unreachable, consistent with this project's standing testing discipline.

## A test-isolation issue found and fixed during this phase's own verification

Running `tests/test_api_production_cutover.py` as part of the full suite (rather than in isolation) intermittently failed several of its own tests — traced to `orca/serve/ratelimit.py`'s `_local_counters` being a process-wide dict keyed by client IP, and `TestClient` reporting the same fake IP for every test file in the suite. Other test files' real calls to `/api/chat`/`/api/stream` (Phase 2.1's frontier-passthrough tests, gateway integration tests, Phase 3's cognitive-kernel-cutover tests) could exhaust this file's rate-limit budget by the time its own tests ran, depending on suite execution order and timing — not a defect in the Kernel/entitlement logic itself. Fixed by clearing `ratelimit._local_counters` in this file's own `autouse` fixture (the same pattern `tests/test_ratelimit.py` already uses for its own isolation).

## Known limitations (disclosed, not hidden)

1. Two architecturally separate entitlement mechanisms coexist (`orca/auth/store.py`'s per-user tier vs. `orca/license/`'s process-wide license, used by `/api/ultra`) — documented in `ENTITLEMENT_POLICY_AUDIT.md`, not resolved in this phase per its explicit "preserve that entitlement" instruction. A genuinely multi-tenant `/api/ultra` deployment should reconcile these in a future pass.
2. `VERIFY`/`SIMULATE`/general-purpose `DELEGATE_AGENT` remain `PLANNED`, unchanged from Phase 3 — an `AUDIT_GRADE`-evidence request still honestly abstains.
3. A real, deliberate behavior change: some requests that previously received an ordinary (if inadvisable) answer now abstain (HTTP 422 / SSE error) because the Kernel's own risk/evidence classification says they require unavailable verification. Disclosed in `PRODUCTION_CUTOVER.md`.

## READY TO ADVANCE TO PHASE 4: YES

Cognitive Kernel is authoritative for `/api/chat`, `/api/stream`, and (for planning) `/api/ultra`. Commercial entitlement remains deterministic, unchanged in its underlying rules, and structurally incapable of being elevated by cognitive judgment. RAG, agent/tool-use, and model-lifecycle governance all survive the cutover, verified against real infrastructure. Per the phase instruction, this phase **STOPS** here — no Truth Fabric (Phase 4) work has been started, and none will begin without explicit human approval.
