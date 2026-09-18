# Genesis Judge Protocol Specification

**Contract definition only, per spec section 12. No judge runs this
phase. No judge is implemented this phase.**

## Why not a single-model judge

`genesis-eval-v1` categories 2, 6, 8, and 13 require subjective
judgment (rubric-scored, not deterministically verifiable). The
tempting shortcut -- have one LLM score another LLM's output against a
rubric -- is explicitly rejected as the final qualification mechanism:
a single judge model has its own biases, blind spots, and potential
correlation with the very failure modes it's meant to catch (a judge
that shares training lineage or stylistic preferences with a candidate
can systematically over- or under-rate it). Frontier qualification
must not rest on one model's opinion of another.

## Proposed versioned protocol structure

Three layers, applied in order, with escalation only where needed:

### Layer 1: Deterministic scoring (unchanged, already implemented)

Categories with executable/exact-match/pattern-match/schema-match
scoring types continue to be scored exactly as
`orca.eval.genesis_suite.score_task()` already does -- no judge
involvement, no change from the existing mechanism.

### Layer 2: Blind rubric-based multi-judge evaluation

For `llm_judge` categories:
- Multiple distinct judge models (not one), each scoring the SAME
  candidate response against the SAME published rubric, blind to which
  candidate produced the response and blind to the other judges' scores
- Judges should be drawn from models with meaningfully different
  training lineage from each other and, ideally, from the candidate
  being evaluated, to reduce correlated bias
- Disagreement threshold: if the judges' scores diverge beyond a
  defined tolerance (exact threshold TBD when this layer is actually
  implemented, not this phase), the item is escalated to Layer 3
  rather than resolved by averaging or majority vote alone
- Every judge call's raw output, model identity (including exact
  revision/provider-version metadata per
  `GENESIS_FRONTIER_HOLDOUT_SPEC.md`'s mutable-API-model policy), and
  rubric version must be persisted -- judge decisions are themselves
  auditable evidence, not ephemeral scores

### Layer 3: Human adjudication for finalist disagreements / critical items

Reserved for:
- Items where Layer 2's judges materially disagree (per the threshold
  above)
- Any item flagged under the "critical failures" category from prior
  phase specs (self-authorization, fake completion, fake deployment,
  fabricated evidence, capability-as-permission conflation, bypassing
  human authority) -- these are never resolved by automated judgment
  alone, regardless of judge agreement, because the cost of a false
  negative here is categorically different from an ordinary capability
  miss
- Final-round disagreements among the actual frontier finalists (once
  candidates reach that stage), where the selection decision itself
  carries enough weight to warrant a human check even absent explicit
  judge disagreement

## Versioning

This protocol, once actually implemented, must carry an explicit
version identifier (e.g. `genesis-judge-protocol-v1`) bound into any
result manifest that used it -- mirroring the suite/scoring-contract
digest pattern already established elsewhere in this project, so a
future protocol revision cannot silently be applied retroactively to
past results or conflated with a different version's scoring behavior.

## What this phase explicitly does not do

- No judge model is selected
- No rubric is finalized
- No disagreement threshold is set
- No judge is run, tested, or wired into any evaluation path
- Categories 2, 6, 8, 13 remain `UNSCORED_REQUIRES_JUDGE` exactly as
  before

This document exists so that when judge-based scoring IS built, it is
built against a considered multi-layer contract decided in advance,
not improvised at the moment a real candidate's judge-required
categories need a number.
