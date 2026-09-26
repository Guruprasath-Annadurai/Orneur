# ORNEUR Discovery Intelligence

Status: design and contracts. Nothing here claims ORNEUR can do discovery today.

## 1. Why discovery is first-class

An assistant that only answers the question asked is bounded by the user's awareness. ORNEUR's identity includes finding what the user **did not know to ask**. Discovery Intelligence therefore sits inside the core loop (after the World Delta Engine, before the Hypothesis Laboratory), not beside it as a feature.

ORNEUR must be able to find:

- **opportunities** (an action available that improves an objective)
- **risks** (a plausible failure not on anyone's list)
- **contradictions** (two things believed that cannot both hold)
- **weak signals** (small, early indicators of a larger change)
- **unexpected connections** (links across documents, people, systems)
- **novel hypotheses** (candidate explanations worth testing)
- **missing information with high information value** (see `InformationGainQuery`)
- **changes that invalidate previous conclusions** (via World Delta propagation)
- **cross-domain transferable solutions** (a proven pattern from domain A applied to domain B)

`discovery_type` values in the protocol: `OPPORTUNITY`, `RISK`, `CONTRADICTION`, `WEAK_SIGNAL`, `UNEXPECTED_CONNECTION`, `NOVEL_HYPOTHESIS`, `MISSING_INFORMATION`, `INVALIDATED_CONCLUSION`, `CROSS_DOMAIN_TRANSFER`.

## 2. The `Discovery` object

A first-class, immutable, provenance-carrying record (`orca.intelligence.protocol.Discovery`).

| Field | Meaning / rule |
|---|---|
| `discovery_id` | stable identifier |
| `objective_id` | the objective it bears on |
| `tenant_id` | tenant boundary; discoveries never cross tenants without anonymization evidence |
| `discovery_type` | one of the types above |
| `statement` | the discovery, stated so it can be wrong |
| `why_non_obvious` | required: why it is not something the user or a trivial search would already have |
| `evidence_refs` | **required, non-empty**: content-addressed `EvidenceReference` ids |
| `counter_evidence_refs` | evidence against; required non-empty when counter-evidence was found |
| `counter_evidence_status` | `SEARCHED_FOUND`, `SEARCHED_NONE_FOUND` or `NOT_SEARCHED` — makes "no counter-evidence" an explicit, auditable statement rather than an omission |
| `assumptions` | what must hold for the discovery to be true |
| `confidence` | 0–1; **capped at 0.5 while `NOT_SEARCHED`** |
| `estimated_importance` | 0–1 |
| `falsification_condition` | required: what observation would refute it |
| `suggested_experiment` | the cheapest test that could refute or confirm it |
| `potential_action` | what the user could do if it holds |
| `affected_prior_decisions` | earlier decisions it would change (links into the decision graph) |
| `outcome_status` | `PROPOSED`, `UNDER_TEST`, `CONFIRMED`, `FALSIFIED`, `ACTED_ON`, `EXPIRED`; `CONFIRMED`/`ACTED_ON` are refused while `NOT_SEARCHED` |
| `created_at`, `updated_at` | timestamps |
| `revision`, `parent_digest` | immutability chain (below) |

### Provenance and immutability

`Discovery` is a frozen dataclass. A change is a **new revision** via `Discovery.revise(...)`: `revision` increments and `parent_digest` is the sha256 of the previous revision's canonical form. `parent_digest` must be `None` exactly for revision 0, and for every revision above 0 it must be a valid lowercase sha256 hex digest (the validator rejects anything else). History is therefore append-only and tamper-evident. Evidence is referenced by content digest, so a discovery cannot silently point at changed material.

## 3. How a discovery is produced (design)

1. **Trigger.** A `WorldDelta`, a new document, a scheduled scan of open unknowns, a contradiction detected by the Reality Compiler, or a low-confidence region of the World Model.
2. **Candidate generation.** One or more experts (a `discovery expert`, `counterfactual expert`, retrievers, statistical tools) propose candidates. Producers are untrusted.
3. **Evidence binding.** Each candidate must bind to evidence refs; a candidate with none is discarded, not softened.
4. **Counter-evidence search.** An independent expert searches for counter-evidence and records the status honestly.
5. **Falsification design.** A falsification condition and cheapest experiment are attached (handoff to the Hypothesis Laboratory).
6. **Scoring and surfacing.** Importance × confidence × actionability, with a budget on interruptions so ORNEUR does not spam the user. Low-importance findings are kept, not pushed.
7. **Follow-up.** The discovery's `outcome_status` is updated as it is tested or acted on; outcomes feed Outcome Learning, so the system learns which kinds of discovery actually mattered.

## 4. Guardrails

- A discovery is a **hypothesis with provenance**, never a fact. It is not allowed to trigger an action by itself; actions go through the Authority Runtime.
- Producers cannot verify their own discoveries (`VerificationResult` requires `verifier_id != producer_id`).
- Surfacing volume is budgeted per objective; an over-eager discoverer that produces noise is penalised by the evaluation below.
- Tenant privacy: a discovery derived from one tenant's data never informs another tenant except through anonymized, evidence-referenced primitives.

## 5. Evaluation: `ORNEUR_DISCOVERY_EVAL`

Designed in `GENESIS_CAPABILITY_EVAL_V1_DESIGN.md` §6. It measures whether a system finds useful information **not explicitly requested**, scoring each candidate on novelty, relevance, evidence quality, counter-evidence awareness, actionability, falsifiability, importance and non-obviousness. It is designed here and **not executed** in this phase.

## 6. Non-claims

No claim that ORNEUR currently discovers anything, that discoveries are correct, or that any model can do this reliably. This document defines the contract and the evaluation that would let such a claim be tested.
