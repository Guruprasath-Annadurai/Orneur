# Production Cutover — /api/chat, /api/stream, /api/ultra

## Canonical authority chain, as actually implemented

```
Client
  -> ratelimit.enforce()                          [UNCHANGED]
  -> Lens generation-intent short-circuit          [UNCHANGED]
  -> check_quota() (daily message cap)             [UNCHANGED]
  -> model_access_allowed(user, req.model_variant) [UNCHANGED -- exact existing 402 gate]
  -> check_input() (moderation)                    [UNCHANGED]
  -> _run_cognitive_kernel()                       [NEW -- AUTHORITATIVE]
       -> derive_entitlement_policy(user, model_variant)
       -> narrow ceiling by user's own explicit tier selection
       -> kernel.execute(CognitiveRequest, entitlement=...)
            -> plan() [pure, no I/O]
            -> plan_abstention_reason() -- ABSTAIN if unsatisfiable
            -> reconcile_policy(model_policy, entitlement) -- never elevates
            -> if plan needs only ANSWER_DIRECTLY/REASON/RECALL_MEMORY:
                 answer directly via ModelGateway (entitlement-reconciled tier)
            -> else: CognitiveResult.output = None, resolved_tier carried through
  -> if ABSTAINED: return 422 (chat) / SSE error event (stream) -- NO generation happens
  -> _resolve_backend_for_chat() + cost-aware routing [UNCHANGED -- frontier-escalation decision, orthogonal to tier entitlement]
  -> if cognitive_result.output is not None: use it directly, skip AgentLoop entirely
  -> else: existing _Session/AgentLoop/RAG/memory/tools path [UNCHANGED]
  -> memory persistence, DLP scan, audit log          [UNCHANGED]
```

This is the real, verified authority chain (`tests/test_api_production_cutover.py`), not an aspiration -- every request to `/api/chat` and `/api/stream` now passes through `_run_cognitive_kernel()` BEFORE any generation happens, and its ABSTAIN/degrade decision is never bypassed or overridden by the legacy tier/routing logic that runs after it.

## What changed from Phase 3's shadow mode

| | Phase 3 (shadow) | Phase 3.1 (authoritative) |
|---|---|---|
| Kernel runs on every chat/stream request | Yes, `kernel.plan()` only | Yes, `kernel.execute()` (plan + reconcile + possibly answer) |
| Kernel's decision affects the real response | Never | Yes -- abstention blocks generation; direct-answer plans skip AgentLoop; degradation is disclosed |
| Entitlement reconciliation | Did not exist | `reconcile_policy()`, structurally incapable of elevating access (`POLICY_RECONCILIATION.md`) |
| A Kernel internal failure | Silently swallowed (`except Exception: pass`), legacy path ran anyway | Caught, mapped to a clean error, surfaced to the caller (never silently falls through) |
| `/api/cognitive/execute` | The only real end-to-end Kernel-authoritative path | Retained as-is (no session/entitlement) for isolated Kernel testing |

## The one deliberate, disclosed behavior change

**A request that would previously get a normal (if sometimes ill-advised) answer may now abstain.** A message matched as `CRITICAL` risk requiring `AUDIT_GRADE` evidence (e.g. destructive/security-sensitive phrasing) now returns HTTP 422 (`/api/chat`) or an SSE `error` event (`/api/stream`) with `abstained: true`, instead of reaching a model at all — because `VERIFY` (required for `AUDIT_GRADE` evidence) is honestly `PLANNED`, not implemented, in this repository. This is exactly what "Kernel authoritative... abstain as currently designed" (spec §12) means in practice, and is intentional, not a bug: the alternative would be answering a high-risk request without the verification its own risk classification says it needs.

## RAG and agent behavior explicitly preserved

**RAG**: `sess.doc_store.count() > 0` is still the trigger condition for the 7-stage Deep RAG pipeline, checked and enforced to run whenever docs are loaded REGARDLESS of what a single message's own cognitive plan says (`use_kernel_direct = cognitive_result.output is not None and sess.doc_store.count() == 0`) — a session with documents always uses the existing RAG/AgentLoop path. Verified end-to-end: `tests/test_api_production_cutover.py::test_rag_forces_deferral_to_existing_stack_when_docs_are_loaded`.

**Agents/tools**: any plan requiring `USE_TOOL`/`SEARCH`/`DELEGATE_AGENT` completes with `output=None` from the Kernel, which routes the request to the existing `sess.agent.run`/`sess.agent.stream` call exactly as before (AgentLoop's own internal tool-use planner, `PLANNER_SYSTEM`, is completely untouched). Verified: `test_tool_requiring_message_still_defers_to_agentloop`.

## `/api/ultra`

Ultra is a distinct, deliberately deep, paid product mode with its own entitlement gate (`has_feature("ultra")`) that predates and is architecturally separate from the tier-based `EntitlementPolicy` used for `/api/chat`/`/api/stream` (see `ENTITLEMENT_POLICY_AUDIT.md`'s "two entitlement mechanisms" finding — not resolved in this narrowly-scoped phase, per the phase spec's own "preserve that entitlement... do not remove product differentiation" instruction). Cognitive planning is no longer bypassed: `kernel.plan()` runs on every `/api/ultra` request (never `execute()` — Ultra's own fixed multi-agent pipeline remains authoritative for HOW the request is actually answered), wrapped in the same fail-safe `try/except` discipline as Phase 3's shadow mode, so a planning failure can never break the Ultra pipeline itself.

## Shadow comparison retained, now purely as verification

`_record_shadow_verification()` (formerly `_run_cognitive_shadow`) still records a comparison metric (`shadow_agree`/`shadow_disagree` in `orca/cognitive/metrics.py`) between the legacy requested tier and the Kernel's resolved tier — but it runs AFTER the Kernel's decision has already been made and used; it cannot influence the response in any way. This satisfies spec §11's "retain shadow comparison temporarily only as a verification mechanism."

## Entitlement bypass resistance

Verified directly (`test_metadata_cannot_manufacture_entitlement`): arbitrary extra JSON fields in the request body (`"tier": "enterprise"`, `"role": "admin"`) are silently ignored by Pydantic's `ChatRequest` model and have zero effect on entitlement — only the authenticated `User.tier` (from the database, via `get_current_user_optional`) and the existing `model_access_allowed()` gate determine access. The Kernel's own `ModelPolicyCharacteristic` has no code path capable of writing to or overriding `EntitlementPolicy` (`reconcile_policy()` only ever reads it) — verified structurally by the property test in `POLICY_RECONCILIATION.md` and directly by `test_entitlement_never_upgrades_kernel_choice`.
