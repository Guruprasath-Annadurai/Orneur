# Epistemic Twin (Phase 6)

`orca/deliberation/twin.py::EpistemicTwin`. Two logically independent
roles — Constructor builds the strongest supported candidate;
Falsifier attacks it.

## Independence (spec §12) — structural, not a redaction step

Falsifier receives the objective, the evidence passages, and
Constructor's **structured** `Argument` list (a claim string +
`evidence_ids` per claim) — never a prompt transcript or Constructor's
own reasoning trace. This is guaranteed by construction: Constructor's
own output IS already a structured claim list (its Gateway call returns
JSON `{"claims": [...], "assumptions": [...]}`), so there is no raw
chain-of-thought to accidentally leak in the first place. No extra
redaction logic exists or is needed.

## Output (spec §13) — never "critic says OK"

`TwinResult` always carries the full breakdown, even when Falsifier
finds nothing wrong:

```python
constructor_claims: list[Argument]
falsifier_objections: list[CounterArgument]
counter_evidence_ids: list[str]
unsupported_assumption_ids: list[str]
disputed_claim_ids: list[str]
surviving_claim_ids: list[str]
unresolved_questions: list[str]
role_executions: list[RoleExecution]
```

An empty `falsifier_objections` list is itself meaningful information
(distinguishable from "Falsifier never ran" via `role_executions`
always containing a `FALSIFIER` entry with a real `latency_ms`).

## Gateway routing

Both roles call `orca.truth.llm.gateway_json_call()` — the same
Gateway-routed helper Truth Fabric's own claim extraction/verification/
contradiction judges use, not a second, parallel LLM-call
implementation.

## Retrieved evidence is untrusted (spec §46-47)

`_sanitize_evidence_texts()` reuses `orca.truth.fetch.
sanitize_extracted_text()`'s generic injection-pattern scan, layered
with Deliberation-Fabric-specific patterns for role-hijack phrasing
("You are the Arbiter", "Ignore Falsifier", "Verdict must be ACCEPT")
the generic list didn't cover — a real gap found writing the security
test suite, fixed before being reported as covered. Flagged passages
are excluded entirely before reaching either role's prompt. See
[SECURITY.md](SECURITY.md).

## Honest, measured model-quality limitation

A live reproduction (this phase, real Ollama nano tier) on a
well-evidenced claim ("The API rate limit is 100 requests per minute,
effective March 2024.") produced a Falsifier objection labeling the
correctly-cited claim a "contradiction" and flagging a second, distinct
claim as a "duplicate" — both objections were wrong. This is the same
class of nano-tier judge imprecision already documented for Truth
Fabric's own claim verifier
([docs/orneur/phase-4/EVALUATION_V2.md](../phase-4/EVALUATION_V2.md)).
Not "fixed" by prompt tuning in this phase (same discipline: don't chase
a single observed failure with a hand-tuned prompt patch) — disclosed
here and in [EVALUATION.md](EVALUATION.md) as a real, retained
model-quality limitation that a stronger model tier for the Falsifier
role would directly address (see [COGNITIVE_COURT.md](COGNITIVE_COURT.md)'s
model-society hooks).
