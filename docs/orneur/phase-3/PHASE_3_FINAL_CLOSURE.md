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

Full suite: **725 passed, 1 failed, 106 warnings** (14m14s) on the definitive run. The single failure (`test_free_user_complex_request_is_downgraded_not_elevated`) is real-Ollama infrastructure flakiness under sustained load — confirmed passing in 3 separate isolated/small-combination reruns (including one immediately preceding the full run) with the identical assertion. Same category as the pre-existing flaky test disclosed in Phase 2.1's own closure (`test_live_gateway_brain_end_to_end_matches_orca_brain_interface`): a CPU-only local Ollama instance serving 700+ real generation requests back-to-back over 10+ minutes occasionally hits a transient `InferenceError` ("inference request failed", `orca/gateway/gateway.py:275`) on an otherwise-unchanged, pre-existing error path (`sess.agent.run`'s `except Exception` wrapping predates this phase). Not a Kernel/entitlement logic defect.

Security suite: **31 passed**.

New tests this phase: `tests/test_cognitive_entitlement.py` (12), 3 new real-Ollama tests in `tests/test_cognitive_kernel.py`, `tests/test_api_production_cutover.py` (15, real end-to-end, including explicit malformed-metadata and admin-role-string escalation-attempt tests). All real-Ollama tests auto-skip (not fail) when Ollama is unreachable, consistent with this project's standing testing discipline.

## Performance

Measured on this machine (Apple M4, 16GB, CPU-only Ollama — same environment as prior phase baselines):

| | |
|---|---|
| `kernel.plan()` latency (pure, no I/O, 20 runs) | avg 0.069ms, min 0.053ms, max 0.139ms |
| `derive_entitlement_policy()` latency (pure, no I/O, 20 runs) | avg 0.003ms, min 0.002ms, max 0.012ms |
| `/api/chat` total request latency (3 real runs, `plan=cognitive_direct`) | 2302.1ms / 1318.6ms / 1686.5ms |

Combined planning + entitlement-reconciliation overhead is well under 0.1ms — effectively free, deterministic, zero I/O. All measured end-to-end latency is the real Gateway/Ollama generation call, consistent with prior phases' own findings that Kernel orchestration adds no material overhead.

## Two test-isolation issues found and fixed during this phase's own verification

1. **Rate-limit bucket exhaustion**: `orca/serve/ratelimit.py`'s `_local_counters` is a process-wide dict keyed by client IP, and `TestClient` reports the same fake IP for every test file in the suite. Other files' real calls to `/api/chat`/`/api/stream` could exhaust this file's rate-limit budget depending on suite execution order — not a Kernel/entitlement defect. Fixed by clearing `ratelimit._local_counters` in this file's own `autouse` fixture (the pattern `tests/test_ratelimit.py` already uses).
2. **Auth DB schema loss from an unrelated fixture**: `tests/conftest.py`'s `isolated_home` fixture (used by `test_account_delete.py` and others) reloads `orca.auth.db` against a temp directory, then on teardown restores the `ORCA_HOME` env var **without reloading `orca.auth.db` again** — leaving its module-global `AUTH_DB` path pointing at the now-deleted temp directory for the rest of the process. The next real write there (e.g. this file's `check_quota()` calls through `/api/chat`) silently opens a fresh, schema-less SQLite file (`sqlite3.OperationalError: no such table: usage_daily`) rather than erroring loudly. Pre-existing test-infrastructure gap, not a Phase 3.1 code defect — fixed defensively in this file's fixture by re-running `orca.auth.db.init_db()` (idempotent, `CREATE TABLE IF NOT EXISTS`) before each test, rather than depending on suite run order to have left global auth-DB state in a good place.

## Known limitations (disclosed, not hidden)

1. Two architecturally separate entitlement mechanisms coexist (`orca/auth/store.py`'s per-user tier vs. `orca/license/`'s process-wide license, used by `/api/ultra`) — documented in `ENTITLEMENT_POLICY_AUDIT.md`, not resolved in this phase per its explicit "preserve that entitlement" instruction. A genuinely multi-tenant `/api/ultra` deployment should reconcile these in a future pass.
2. `VERIFY`/`SIMULATE`/general-purpose `DELEGATE_AGENT` remain `PLANNED`, unchanged from Phase 3 — an `AUDIT_GRADE`-evidence request still honestly abstains.
3. A real, deliberate behavior change: some requests that previously received an ordinary (if inadvisable) answer now abstain (HTTP 422 / SSE error) because the Kernel's own risk/evidence classification says they require unavailable verification. Disclosed in `PRODUCTION_CUTOVER.md`.

---

## Phase 3.2 addendum — inference test reliability closure

Phase 3.1's own closure reported "725 passed, 1 failed" and classified the failure as transient real-Ollama infrastructure flakiness. Phase 3.2 was scoped to determine root cause with evidence rather than accept that classification on faith. Full detail: `OLLAMA_TEST_RELIABILITY.md` (root cause, reproduction data) and `TEST_EXECUTION_POLICY.md` (live-runtime test classification going forward).

**Root cause, with evidence:** RESOURCE SATURATION on a genuinely shared, actively-used development machine (Apple M4, 16GB) — directly measured (load average 2.8–27+, ~94MB free memory at points, and — discovered mid-investigation — a second, entirely unrelated autonomous coding-agent session independently running its own test suite against the same shared local Ollama instance at the same time). Contributing, fixable factor: the specific flaky test requested an unbounded "comprehensive, in-depth" response with no verification need for one, reliably tripling its own real Ollama workload via `AgentLoop`'s reflection step. Isolated 10× reproduction of the original test: **2/10 failed** (both failures at ~200–220s, just above `ModelGateway`'s 180s `total_request_timeout_s`). Same test, fixed: **0/5 failed** across 5 verification runs (10 individual executions).

**Fixes applied:**
1. Bounded the two affected tests' real workload (append "Answer in one short sentence." — verified to preserve their `DEEP`/`AGENTIC` classification).
2. Found and fixed a real, separate contributing defect: fire-and-forget knowledge-graph extraction (`/api/stream`) contended for a deployment's bounded Gateway concurrency permits at the same `INTERACTIVE` priority as real foreground requests. `GatewayBrain.complete()`/`.stream()` gained an optional `priority` parameter (default unchanged); `KnowledgeGraph.extract_and_add()` now defaults to `BACKGROUND`, so Phase 2.1's own priority scheduler naturally yields to foreground work.
3. Centralized live-Ollama test support (`tests/ollama_test_support.py`): a `warm_model()` readiness helper and a narrow, classified, bounded `retry_transient()` (exactly `GenerationTimeoutError`/`QueueTimeoutError`, 2 attempts, logged, still fails past the bound) — applied where the exception boundary is clean enough to classify correctly, not blindly everywhere.
4. Registered `live_ollama_smoke`/`live_ollama_stress`/`performance` pytest markers so real-Ollama tests are explicitly classified going forward (`TEST_EXECUTION_POLICY.md`).

**No production timeout or security behavior was weakened.** `ModelGateway.TimeoutPolicy` defaults are untouched — evidence pointed at excess test workload, not an under-provisioned timeout budget.

**Full suite, definitive run this phase:** run in two parts due to a mid-session environmental event (see below) that made a single continuous run impractical to complete cleanly: `pytest -q -m "not live_ollama_smoke"` → **716 passed, 0 failed, 15 deselected** (250s), then the 15 deselected tests (`tests/test_api_production_cutover.py`, now marked `live_ollama_smoke`) run on their own once load had normalized → **15 passed, 0 failed** (485s). **Combined: 731 passed, 0 failed.**

**Security suite:** 31 passed, unchanged.

**Disclosed, not hidden:** during this phase's own verification, system load spiked to extraordinary levels (briefly 60+) due to a **second, independent autonomous coding-agent session** on this same shared machine running its own real-Ollama test suite concurrently, plus a Time Machine backup and OS disk-cache cleanup running at the same time. This is named explicitly rather than glossed over: it is real, external, verified evidence for the RESOURCE SATURATION classification, and it means a "clean full run" on this specific shared machine is a function of what else happens to be running on it at the time — not something any code change in this repository can fully guarantee. The fixes in this phase reduce this codebase's own resource footprint and make its real-infrastructure tests explicitly classified; they cannot make a shared laptop immune to a second concurrent heavy process.

## READY TO ADVANCE TO PHASE 4: YES

Cognitive Kernel is authoritative for `/api/chat`, `/api/stream`, and (for planning) `/api/ultra`. Commercial entitlement remains deterministic, unchanged in its underlying rules, and structurally incapable of being elevated by cognitive judgment. RAG, agent/tool-use, and model-lifecycle governance all survive the cutover, verified against real infrastructure. Inference test reliability root cause is identified with direct evidence, the fixable contributing defect (background-priority contention) is fixed and regression-tested, and the actual flaky test's excess workload is bounded and verified clean. Per the phase instruction, this phase **STOPS** here — no Truth Fabric (Phase 4) work has been started, and none will begin without explicit human approval.
