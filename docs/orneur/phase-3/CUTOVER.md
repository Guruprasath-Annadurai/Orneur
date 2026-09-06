# Kernel Cutover — What's Real, What's Shadow, and Why

## The existing router is not deleted

`orca/serve/routing.py`'s cost-aware escalation mechanism (4-gate opt-in: operator flag, sovereignty lock, credentials present, per-query heuristic; daily cap) is unchanged, untouched, and still the sole authority for the frontier-escalation decision. Its `classify_query()` heuristic is *reused* by `orca/cognitive/complexity.py` (see `CURRENT_COGNITIVE_ORCHESTRATION.md`) rather than duplicated. Nothing here moved or superseded it — it continues to run exactly where it already ran, on every `/api/chat`/`/api/stream` request, before and independent of anything the Cognitive Kernel decides.

`orca/serve/registry.py`'s tier resolution (`resolve_tier_backend`/`resolve_tier_model`, the `ultra→core→nano` step-down chain, the data-sovereignty lock) is likewise completely unchanged. The Kernel's `ModelPolicyCharacteristic → tier` mapping (`policy.py`) feeds INTO this router; it does not replace or duplicate it.

## What is real, end-to-end Kernel authority in Phase 3

**`POST /api/cognitive/execute`** — a new, clearly-marked internal/experimental endpoint. The Kernel is genuinely authoritative here: it plans (`kernel.plan()`) AND executes (`kernel.execute()`) with no fallback to `AgentLoop`/`DocStore`/`MemoryEngine`. A plan needing only a direct model call (`ANSWER_DIRECTLY`/`REASON`/`RECALL_MEMORY`) is genuinely answered via `ModelGateway`, exactly per the phase spec's canonical path (`API → Cognitive Kernel → model policy → ModelGateway → deployment/runtime`). A plan needing tools/retrieval/agents completes honestly with an explicit warning naming what was deferred, never a fabricated answer. This is proven end-to-end against real local Ollama in `tests/test_api_cognitive_kernel_cutover.py`.

## What is shadow-only in Phase 3, and why

**`POST /api/chat` and `POST /api/stream`** — the production, paid-tier, session-continuity chat surface. The Kernel runs (`_run_cognitive_shadow()` in `orca/serve/api.py`) on every real request here, computing a full plan and recording a shadow-comparison metric (`orca/cognitive/metrics.py::record_shadow_comparison`, suggested tier vs. actual tier used) — but the ACTUAL response continues to come from the existing `_Session`/`AgentLoop` path, completely unchanged. `_run_cognitive_shadow()` is wrapped in a broad `try/except` that can never break the real request (tested explicitly in `test_shadow_planning_failure_never_breaks_the_real_chat_path`).

This was a deliberate scope decision, not an oversight, for one concrete, disclosed reason:

**Tier selection on these endpoints is not purely a cognitive decision — it's entangled with paid-tier entitlement.** `model_access_allowed()` (`orca/auth/store.py`) gates which tier a user is even allowed to request based on their plan (free/pro/enterprise). `orca/serve/registry.py`'s own docstring is explicit: *"a user asking for nano should never be silently upgraded to a paid tier's model (that would be a plan-gating leak, not a convenience)."* If the Kernel's `ModelPolicyCharacteristic` (a purely cognitive judgment — "this looks DEEP") were allowed to override or blend with the user's requested/entitled tier on these production endpoints, a free-tier user asking a complex question could get silently routed to a paid tier's model — exactly the plan-gating leak the existing router was built to prevent. The phase spec is explicit that model policy and risk are NOT authorization (§37) — conflating them here would violate that principle in practice, not just in theory.

Resolving this properly (e.g., using the Kernel's model policy only as a *tie-breaker within* a user's already-entitled tier, or making entitlement itself Kernel-aware) is a real, legitimate next step — but it's a product/policy decision, not a mechanical wiring task, and making it silently inside a "Phase 3 cutover" commit would be exactly the kind of undisclosed scope creep this whole multi-phase process has been structured to avoid. It is named here explicitly as a **remaining Phase 3 blocker for full production cutover**, not hidden.

## Also real: conversation continuity

Bypassing `AgentLoop` for the "simple" case on `/api/chat`/`/api/stream` would also mean losing `AgentLoop._history`'s multi-turn continuity (and Redis-backed cross-instance session restore) for exactly the requests most likely to be simple greetings in an ongoing conversation — a second, independent reason full production cutover of these two endpoints was not attempted this phase.

## Summary table

| Endpoint | Kernel role | Real execution authority |
|---|---|---|
| `/api/cognitive/execute` (new, internal) | Plans AND executes | **Yes** — genuine end-to-end Kernel authority |
| `/api/chat` | Plans (shadow only) | No — existing `_Session`/`AgentLoop` path, unchanged |
| `/api/stream` | Plans (shadow only) | No — existing `_Session`/`AgentLoop` path, unchanged |
| `/api/ultra` | Not integrated this phase | No — `OrcaUltra`'s own fixed multi-agent pipeline (Phase 2.1 Gateway-routed, unrelated to Phase 3) |

## `UNEXPECTED_COGNITIVE_KERNEL_BYPASS` — scope of the claim

The Phase 3 spec's closure gate asks for zero unexpected bypass "for supported ordinary chat/generation paths." Given the table above, the honest claim is: **zero bypass among paths this phase actually claims Kernel authority over** (`/api/cognitive/execute` — verified). `/api/chat` and `/api/stream` are not claimed as Kernel-authoritative for execution in Phase 3 at all (shadow only, disclosed above), so they are not counted as "bypasses" of a claim that was never made for them.
