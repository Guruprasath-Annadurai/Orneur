# ORNEUR Self-Evolving Expert Mesh

Status: design and contracts. No expert is implemented or qualified by this document.

## 1. Idea

ORNEUR does not ship "a model". It ships a **mesh of qualified capabilities** behind one stable interface. Any capability may be replaced, split, merged or retired without changing the callers, because callers depend on the interface and on evaluation evidence, never on how the expert is built.

## 2. Expert kinds (open vocabulary)

Examples known today: reasoning, coding, mathematics, science, research, tool-use, verification, discovery, counterfactual, multimodal. `ExpertCapability.kind` is an open name, so **experts not known today are legal**: `FUTURE:<name>` is valid, and the validator constrains only the shape of the name, not its membership in a list.

## 3. Representation is not part of the contract

`ExpertCapability.realization` is likewise open. An expert may be realized as:

- a LoRA / adapter on some base
- a specialized checkpoint
- an MoE expert inside a larger model
- an external temporary teacher (e.g. a licensed provider model used only to produce data or a reference answer)
- a symbolic engine (solver, prover, database, calculator)
- a retriever
- a simulator
- a future neural architecture

No code path may branch on `realization` to decide *whether to trust* an expert. Trust comes only from qualification evidence and independent verification.

## 4. Interfaces

```
ExpertCapability { expert_id, kind, realization, capability_tags, state, qualification_eval_refs, interface_version }
ExpertRequest    { request_id, expert_id, tenant_id, task_ref, budget: ComputeBudget }
ExpertResult     { request_id, expert_id, status OK|FAILED|REFUSED, output_ref, evidence_refs,
                   self_reported_confidence, claims_trusted=False }
```

- `state` ∈ `CANDIDATE | SHADOW | QUALIFIED | RETIRED`. A `QUALIFIED` expert must cite `qualification_eval_refs`.
- `ExpertResult.claims_trusted` must be `False`. An expert's confidence and self-declared compliance are **never trusted**; the Verification Engine and the Contract Engine decide.
- Budgets are expressed as `ComputeBudget` (latency target, cost ceiling, reasoning steps, expert count, verification depth) — never as a model size.

## 5. Routing

A router selects experts per request from capability tags, qualification state and budget. Routing is itself a versioned, evaluated behavior: `router_behavior` is a migration asset class (see `ORNEUR_ARCHITECTURE_MIGRATION_PROTOCOL.md`) so that a new architecture inherits, or is measured against, the existing router's decisions.

Routing principles (Instant Response Fabric): never invoke more intelligence than the request needs; a deterministic or tool path beats a model path when it satisfies the contract; independent experts run in parallel; the cheapest qualified expert that clears the verification bar wins; a verification expert is never the same instance as the producer.

## 6. Lifecycle — how the mesh evolves without self-promotion

```
Failure Genome / outcome → capability gap → candidate expert (state CANDIDATE)
→ frozen eval → adversarial eval → regression eval → shadow deployment (state SHADOW)
→ PromotionDecision → QUALIFIED → periodic distillation into next generation → RETIRED when superseded
```

- Candidates are produced by a learning pipeline; **the producer cannot promote its own candidate** (`PromotionDecision` refuses `decided_by == candidate_produced_by` and `== candidate_id`).
- Promotion requires frozen, adversarial and regression eval references, a shadow deployment reference, a measured positive improvement and zero regressions, decided by a human owner or a qualified gate service.
- **No uncontrolled live weight mutation**: candidate creation happens offline; the serving mesh only ever swaps in a promoted, versioned expert.
- **Retirement is a normal event.** The Self-Obsolescence Rule applies: an expert superseded by a proven better replacement is retired; keeping it "because we built it" is not a reason.

## 7. Temporary external teachers

A teacher may generate training data or reference answers, subject to its license and to tenant/privacy rules. A teacher is an `ExpertCapability` with `realization = external_teacher` and is **never** in the serving path unless separately qualified for it; distilled knowledge is judged by the same frozen evals as anything else. Teacher-output licensing must be reviewed per teacher before use (not done in this phase).

## 8. Multi-architecture by design

Because the mesh is representation-agnostic, ORNEUR can run experts from different architecture families side by side, dual-run an old and a new expert during migration, and compare them with the same eval suites. That is the mechanism that lets a Transformer-based expert and a future non-Transformer expert coexist.

## 9. What is deliberately not specified

The number of experts, their sizes, their training recipes, the router's algorithm and any foundation model. These are implementation decisions to be made by measurement.
