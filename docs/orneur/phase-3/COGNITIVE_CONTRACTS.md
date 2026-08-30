# Cognitive Contracts

All defined in `orca/cognitive/contracts.py` — pure dataclasses/enums, zero behavior, mirroring `orca/gateway/contracts.py`'s own pattern.

## Enums with documented semantics

| Enum | Values | Meaning |
|---|---|---|
| `IntentCategory` | FACTUAL, RESEARCH, REASONING, CODING, PLANNING, TOOL_USE, MEMORY_RECALL, DOCUMENT_ANALYSIS, CONVERSATIONAL, AGENTIC, UNKNOWN | Broad task-shape classification. Multi-label: a request can have one primary + N secondary. |
| `PrivacyClass` | STANDARD, SENSITIVE, RESTRICTED | Descriptive only — **not** an authorization grant. |
| `ExpectedOutputType` | TEXT, CODE, STRUCTURED_DATA, LIST, LONG_FORM | What shape of answer the request implies. |
| `FreshnessLevel` | STATIC, LONG_LIVED, RECENT, CURRENT, REAL_TIME | How time-sensitive correct grounding is. STATIC = math/established facts; REAL_TIME = stock price/breaking news. |
| `EvidenceLevel` | NONE, LIGHT, SUPPORTED, STRICT, AUDIT_GRADE | How strongly an answer must be grounded. NONE = casual/creative; AUDIT_GRADE = high-stakes enterprise report (requires `VERIFY`, which is `PLANNED` in Phase 3 — see `planner.py`). |
| `ComplexityLevel` | TRIVIAL, LOW, MEDIUM, HIGH, DEEP | Deterministic score-to-level mapping in `complexity.py` (documented thresholds, not implicit). |
| `RiskLevel` | LOW, MODERATE, HIGH, CRITICAL | Consequence awareness, not authorization. |
| `BudgetDimension` | TOKENS, LATENCY_MS, MODEL_CALLS, RETRIEVAL_CALLS, TOOL_CALLS, AGENT_CALLS, COST_USD, REASONING_ROUNDS | Independently tracked/capped budget axes. |
| `OperationType` | ANSWER_DIRECTLY, RETRIEVE, SEARCH, RECALL_MEMORY, REASON, USE_TOOL, DELEGATE_AGENT, VERIFY, SIMULATE, ABSTAIN | What the plan says is needed. |
| `OperationSupportState` | SUPPORTED_NOW, PLANNED, UNAVAILABLE, FORBIDDEN | Whether this repository can ACTUALLY perform that operation today — see `planner.py`'s `_SUPPORT_STATES` table for the honest mapping. |
| `ModelPolicyCharacteristic` | FAST, BALANCED, DEEP, CODE, REASONING, VERIFICATION | Desired cognitive characteristic — never a model/family name. |
| `CompletionCondition` | DIRECT_ANSWER_PRODUCED, EVIDENCE_OBTAINED, VERIFICATION_COMPLETE, OPERATION_UNAVAILABLE_ABSTAIN, BUDGET_EXHAUSTED, MAX_ROUNDS_REACHED | Explicit "done" conditions — never "continue until the model says done." |
| `AbstentionReason` | INSUFFICIENT_CAPABILITY, INSUFFICIENT_EVIDENCE, BUDGET_EXHAUSTED, MODEL_UNAVAILABLE, REQUIRED_OPERATION_UNAVAILABLE, POLICY_RESTRICTION, AMBIGUOUS_REQUEST | Why the Kernel declined to answer. |
| `CognitiveState` | RECEIVED, CLASSIFYING, PLANNED, EXECUTING, WAITING, VERIFYING, COMPLETED, ABSTAINED, FAILED, CANCELLED | Execution states — see `COGNITIVE_STATE_MACHINE.md`. |

## Core dataclasses

- **`CognitiveRequest`** — normalizes an objective. No infrastructure/runtime settings (model names, hosts, temperatures) — those are `ModelGateway`'s job, resolved later via `ModelPolicy`.
- **`IntentPlan`** — every field has explicit semantics (no unclear-interaction booleans): `requires_retrieval`, `requires_search`, `requires_memory`, `requires_tools`, `requires_reasoning`, `requires_agents`, `citation_requirement` are each independently set by `intent.py` from a distinct pattern-match category, not derived from each other implicitly.
- **`ComplexityAssessment`** / **`RiskAssessment`** / **`FreshnessRequirement`** / **`EvidenceRequirement`** — each pairs a level/score with a `factors`/`reasons` list of short, auditable strings (never free-form prose).
- **`CognitiveBudget`** — `max_*` (limits, `None` = uncapped) + `consumed_*` (ledger). See `COGNITIVE_BUDGET.md`.
- **`CognitiveContext`** — carries references (`memory_refs`, `evidence_refs`, `tool_observations`, `world_state_refs`), not fabricated content. Empty in Phase 3 for systems that don't exist yet (Truth Fabric, Memory Continuum) — explicitly allowed by the phase spec.
- **`CognitiveOperation`** — `(type, support_state, detail)`. `CognitivePlan.operations` is a list of these, never a bare list of `OperationType`.
- **`SubObjective`** — bounded decomposition unit; `depends_on` models sequential dependency, never recursive.
- **`CognitivePlan`** — the full structured plan: intent + complexity + risk + freshness + evidence + operations + model_policy + budget + completion_conditions + sub_objectives.
- **`CognitiveResult`** — `request_id`, `trace_id`, `status`, `output`, `resolved_model`, `plan_id`, `operations_executed`, `abstention_reason`, `usage`, `latency_ms`, `warnings`. No raw internal diagnostics (Phase 3 spec §31).
- **`CognitiveTrace`** — the Flight Recorder record. Every field is a label or short string list — see `COGNITIVE_STATE_MACHINE.md`'s note on no-raw-chain-of-thought.

## Naming deviations from the phase spec's suggested names

The spec's suggested names were followed almost exactly; the one deliberate addition is `FreshnessRequirement`/`EvidenceRequirement` as dataclasses (level + reasons) rather than bare enum values on `IntentPlan`, for consistency with `ComplexityAssessment`/`RiskAssessment`'s own (level + factors) shape — a canonical equivalent, not a renaming for its own sake.
