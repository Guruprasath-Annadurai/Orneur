# ORNEUR Eternal Intelligence Architecture

- Architecture version: `orneur.eternal-architecture/1.1.0`
- Core protocol version: `orneur.core-protocol/1.1.0` (`orca/intelligence/protocol.py`)
- Machine-readable companion: `ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.json` (generated from `orca/intelligence/spec.py`; a test asserts they match)
- Status: **a roadmap and a set of contracts, not a claim of current capability.**

## 0. What this document is and is not

ORNEUR is being designed as persistent intelligence that keeps objectives, models the world it works in, proves its conclusions, acts only under authority, learns from what actually happened, looks for what the user did not know to ask, and updates itself when the world changes.

This document freezes the architecture *before* expensive implementation. It defines the permanent parts, the replaceable parts, and the typed interfaces between them. It does not implement the subsystems, does not select a foundation model, and does not authorize training, GPU use, provider inference or Phase 21C.

It does **not** claim general intelligence, self-awareness, consciousness, autonomous self-evolution, perfect reasoning, a guarantee that the architecture survives 20 years, superiority over any named commercial model, frontier capability, any measured latency, or that cross-domain transfer works today. Each of those would need a specific, measured, evidence-backed statement that does not exist yet.

## 1. Doctrine

> Models are replaceable organs. ORNEUR itself is permanent.

No neural architecture is permanent. Transformers, mixture-of-experts, retrieval-augmented generation, any tokenizer, any checkpoint family and any parameter-count target are **implementation choices**. The 15–20 year plan is only credible if every one of them can be retired without losing what ORNEUR has learned, proven or promised. That is why the durable asset is the protocol, the state, the evaluations and the migration machinery, and why the migration machinery is a first-class contract (`ArchitectureMigrationManifest`).

The Phase 21B controls and the Contract Compliance Engine established the pattern this architecture generalizes: **the model generates; ORNEUR owns the contract.** A component may propose, but only an independent, evidence-backed ORNEUR mechanism may release, act or promote.

## 2. The canonical loop

```
User
→ Persistent Objective Graph
→ Reality Compiler
→ Living World Model
→ World Delta Engine
→ Discovery Intelligence
→ Hypothesis Laboratory
→ Self-Evolving Expert Mesh
→ Adaptive Compute Engine
→ Fast / Reason / Frontier / future modes
→ Verification Engine
→ Evidence Graph
→ Confidence Calibration
→ Authority Runtime
→ Contract Compliance
→ Action
→ Outcome Capture
→ Failure Genome
→ Learning Pipeline
→ Qualification / Promotion
→ Architecture Migration Engine
→ (loop back into improved ORNEUR)
```

The **Instant Response Fabric** is not a stage. It spans the whole loop (section 12).

| # | Stage | Job | Interface (protocol object) |
|---|---|---|---|
| 1 | User | states or implies intent | `CognitiveRequest` |
| 2 | Persistent Objective Graph | keeps long-lived goals, constraints and success metrics across sessions | `Objective` |
| 3 | Reality Compiler | turns heterogeneous inputs into a canonical, model-independent representation | canonical IR (section 5) |
| 4 | Living World Model | versioned model of entities, state, causality, assumptions, decisions, uncertainty and time | `WorldState` |
| 5 | World Delta Engine | applies evidence as explicit `V(n) → V(n+1)` changes | `WorldDelta` |
| 6 | Discovery Intelligence | finds what nobody asked for | `Discovery` |
| 7 | Hypothesis Laboratory | tries to disprove ideas with tests | `Hypothesis` |
| 8 | Self-Evolving Expert Mesh | routes work to qualified experts of any representation | `ExpertCapability`, `ExpertRequest`, `ExpertResult` |
| 9 | Adaptive Compute Engine | chooses the least compute that is reliable | `ComputeBudget` |
| 10 | Compute modes | FAST / REASON / FRONTIER / future | `CognitiveRequest.mode` |
| 11 | Verification Engine | independent checking, beside generation when safe | `VerificationResult` |
| 12 | Evidence Graph | provenance for everything asserted | `EvidenceReference` |
| 13 | Confidence Calibration | turns verification into calibrated confidence | `CognitiveResult.confidence` |
| 14 | Authority Runtime | decides whether ORNEUR may act (existing ORNEUR runtime) | authority decision |
| 15 | Contract Compliance | strict output contracts, validated before release | `orca.contracts` (qualified, unchanged) |
| 16 | Action | releases an answer or takes an authorized action | `CognitiveResult` |
| 17 | Outcome Capture | records what actually happened | `Outcome` |
| 18 | Failure Genome | records structured failures and capability gaps | `FailureGenomeEntry` |
| 19 | Learning Pipeline | produces candidate data / experts / strategies | (candidates only) |
| 20 | Qualification / Promotion | evidence-gated promotion | `PromotionDecision` |
| 21 | Architecture Migration Engine | moves everything to the next architecture | `ArchitectureMigrationManifest` |

## 3. Permanent versus replaceable

**Permanent ORNEUR assets** (these persist across any architecture change):

- ORNEUR Core Intelligence Protocol
- persistent objectives
- Reality Compiler
- Living World Model
- World Delta
- Discovery Intelligence
- hypothesis / falsification system
- Outcome Learning
- Failure Genome
- Self-Evolving Expert Mesh (the mesh, not any one expert)
- evaluation suites
- qualified cognitive strategies
- Verification + Evidence
- Authority Runtime
- Contract Compliance
- memory / knowledge state
- architecture migration machinery

**Replaceable components** (may be retired when a better one is *proven*):

- any neural architecture, including Transformers, MoE, state-space, hybrid and future designs
- retrieval mechanisms, including RAG
- tokenizers and chat templates
- checkpoint families
- parameter-count targets
- individual experts and adapters
- serving stacks, quantization formats and training recipes

"Permanent" means *the contract and the accumulated state are permanent*. It does not mean a particular implementation of them is immune from replacement; the Self-Obsolescence Rule (section 11) applies to the permanent list too.

## 4. FAST / REASON / FRONTIER

These are **compute and capability expressions**, not sizes. No mode is defined by a parameter count, and `CognitiveRequest` / `ComputeBudget` contain no parameter-count field. Each generation of ORNEUR binds each mode to whichever qualified implementation is best at that time; in this document the binding is intentionally empty (`current_implementation_binding: null`).

**ORNEUR FAST** — the minimum compute necessary for a reliable response.
- extremely low first-token latency (design target only)
- deterministic / tool path wherever one exists (the Contract Engine already answers strict contracts with no model call)
- lightweight expert activation
- everyday multimodal intelligence
- normal conversational use

**ORNEUR REASON** — adaptive deeper compute.
- multiple experts when useful
- coding, mathematics, science, research, planning, tool orchestration
- stronger verification
- an adjustable reasoning budget (`ComputeBudget.reasoning_steps`, `verification_depth`)

**ORNEUR FRONTIER** — the maximum available ORNEUR intelligence configuration at that generation.
- dynamic expert ensemble
- discovery loops and hypothesis generation
- adversarial verification
- search, simulation and tools
- the highest compute budget
- **not tied to 14B, 70B, 500B or any other size**

Modes are extensible: a request may carry `FUTURE:<name>`; the protocol validator accepts it so that new modes need no protocol break.

## 5. Reality Compiler

**Purpose.** Convert heterogeneous evidence into one canonical intermediate representation (IR) that no model owns. A model may *assist* compilation (for example, extraction), but the IR, its provenance rules and its validators belong to ORNEUR. The compiler is model-independent by construction.

**Inputs (eventually):** text, documents, email, calendar, spreadsheets, databases, web, images, video, audio, code, tools, sensors, agent results.

**Not built now.** No connector is implemented in this phase. What is frozen is the protocol.

**Canonical objects:**

| Object | Meaning |
|---|---|
| entity | a thing the world contains (person, asset, system, document) |
| relationship | a typed link between entities, with validity interval |
| event | something that happened at a time |
| claim | a statement attributed to a source |
| evidence | the source material a claim rests on (`EvidenceReference`) |
| contradiction | two claims or observations that cannot both hold |
| timeline | ordered events and validity intervals |
| objective | a goal (`Objective`) |
| constraint | a limit on action |
| obligation | something owed by or to someone |
| decision | a choice made, with its reasons and dependencies |
| risk | a possible bad outcome with likelihood and impact |
| assumption | something taken as true without proof; always explicit |
| unknown | a named gap; the raw material for information-gain reasoning |

**Rules.** (1) Every object carries `tenant_id` and at least one `EvidenceReference` (content-addressed by sha256). (2) Claims are never promoted to facts by the compiler; belief is a property of the World Model plus verification. (3) Contradictions are kept as objects, never silently resolved. (4) Unknowns are first-class. (5) The IR is versioned; a new architecture may change extraction, never the IR semantics without a migration manifest.

## 6. Living World Model and World Delta

`WorldState` is one immutable **WorldModelVersion** (`world_id`, `tenant_id`, `version`, `parent_version`, `content_digest`). The state itself tracks entities, state, causal relationships, objectives, assumptions, decisions, dependencies, observations, uncertainty, time and changes.

`WorldDelta` is the explicit transition `V(n) + evidence → V(n+1)`: `base_version`, `result_version = base_version + 1`, and a list of changes (`ADD | UPDATE | REMOVE | RETRACT`), **each of which must cite evidence**. Because the transition is explicit and content-addressed, `V(n+1)` is computed from `V(n)` and the delta; nothing is recomputed from scratch, and any version can be replayed or audited.

### 6.1 World Delta propagation

```
World Delta
→ dependency graph
→ impacted assumptions
→ impacted conclusions
→ impacted objectives
→ selective re-verification
```

The dependency graph records which assumption rests on which observation, which conclusion rests on which assumption, and which objective rests on which conclusion. `propagate_delta()` in the protocol module is the reference algorithm: given the changed nodes it returns the transitive dependents grouped into assumptions, conclusions and objectives. Only those are re-verified. When a previously supported conclusion loses a dependency, ORNEUR can say: *"Your previous conclusion is no longer supported because one of its dependencies changed,"* naming the dependency, and can show which objective is affected. This is a design target; nothing here claims the behavior exists in a product.

## 7. Discovery Intelligence

Discovery is a first-class ORNEUR identity, specified in `ORNEUR_DISCOVERY_INTELLIGENCE.md`. In summary: ORNEUR must be able to find opportunities, risks, contradictions, weak signals, unexpected connections, novel hypotheses, high-value missing information, changes that invalidate earlier conclusions, and cross-domain transferable solutions. The `Discovery` object requires evidence, a counter-evidence status, a falsification condition and immutable provenance.

## 8. Hypothesis Laboratory

Scientific reasoning is an **evidence-driven, testable contract**, not a self-reflection prompt. A `Hypothesis` carries a statement, supporting and counter-evidence, assumptions, a prediction, a **falsification test**, an experiment or simulation reference, result references and a verdict (`UNTESTED | SUPPORTED | FALSIFIED | INCONCLUSIVE`). The validator refuses `SUPPORTED` or `FALSIFIED` without an executed test's result. The laboratory's distinguishing behavior is that it actively tries to *disprove* ORNEUR's own idea: an adversarial expert (which must be independent of the producer; see `VerificationResult`) proposes the cheapest test whose failure would refute the hypothesis, and the test is run by a tool, simulator or human, not asserted by a model.

## 9. Self-Evolving Expert Mesh

Specified in `ORNEUR_SELF_EVOLVING_EXPERT_MESH.md`. Experts are capabilities behind a stable interface; their representation (adapter, specialised checkpoint, MoE expert, external temporary teacher, symbolic engine, retriever, simulator, future neural architecture) is open vocabulary. Experts are qualified by evals, can be retired, and their self-reports are never trusted.

## 10. Controlled self-improvement

Self-improvement never means uncontrolled live weight mutation. The canonical loop:

```
real failure / successful outcome
→ Failure Genome
→ capability gap
→ candidate training data
→ candidate expert / adapter / strategy
→ frozen eval
→ adversarial eval
→ regression eval
→ shadow deployment
→ promotion decision
→ qualified capability
→ periodic distillation into next ORNEUR generation
```

Hard rules, enforced by `PromotionDecision`: (1) every promotion requires frozen, adversarial and regression eval references and a shadow deployment reference; (2) it requires a measured positive improvement and zero regressions; (3) **no self-generated component may promote itself** — the decider must differ from the producer and from the candidate, and must be either a separately identified `HUMAN_OWNER` or a `QUALIFIED_GATE_SERVICE` that cites a `decider_qualification_ref` (evidence that the service is itself qualified; an unqualified service, a producer or the candidate cannot promote, and a candidate cannot vouch for its own promoter); (4) the loop mutates *candidates*, never the serving system in place; (5) `ORNEUR_SELF_IMPROVEMENT_EVAL` (designed in `GENESIS_CAPABILITY_EVAL_V1_DESIGN.md`) tests the loop itself.

### 10.1 Outcome Learning

Outcome Learning is separate from preference learning. `PreferenceFeedback` records what the user *liked*. `Outcome` records **whether a decision or action actually worked**: objective, decision, action, expected outcome, observed outcome, time horizon, success metric, difference, root cause, lesson and a reusable strategy candidate. `Outcome` cannot have `USER_PREFERENCE` as its source; an `OBSERVED` outcome requires an observed outcome and observation evidence. Tenant boundaries hold: outcomes, Failure Genome entries and discoveries are `TENANT_PRIVATE` unless an anonymization evidence reference exists.

### 10.2 Cognitive primitives

A `CognitivePrimitive` stores a **structured strategy**: problem class, strategy steps, conditions where it worked, conditions where it failed, evidence, version and qualification state. It is versioned, evaluated and qualified before use. Free-form chain-of-thought is **not** a permanent asset: `raw_reasoning_trace_stored` must be `False`, and hidden raw reasoning traces are not persisted.

### 10.3 Information-gain reasoning

When evidence is insufficient ORNEUR should not hallucinate; it should ask *one* high-value question. The contract is `InformationGainQuery`: the single question, the uncertainty it targets, the expected uncertainty reduction and the alternatives considered. A `CognitiveResult` with status `NEEDS_INFORMATION` must carry exactly one such query. Selection uses expected-information-gain over the World Model's named unknowns. The contract is defined here; an implementation is **not** required in this phase.

### 10.4 Cross-domain discovery

ORNEUR should eventually ask: *can a proven pattern from domain A solve a problem in domain B?* The `Discovery` type `CROSS_DOMAIN_TRANSFER` and a future eval category `CROSS_DOMAIN_TRANSFER` exist for this. **The capability is not claimed today.**

## 11. Architecture migration and the Self-Obsolescence Rule

Specified in `ORNEUR_ARCHITECTURE_MIGRATION_PROTOCOL.md`. Datasets, eval suites, experts, memory schemas, world models, discovery history, outcome history, the Failure Genome, cognitive primitives, router behavior and authority/evidence contracts must all be migratable from architecture A to B by distillation, continued training, representation conversion, adapter conversion, re-indexing, replay, shadow comparison, dual-running and eval-preserving cutover. `ArchitectureMigrationManifest` refuses a manifest that leaves any asset class uncovered and refuses to approve a cutover without a shadow comparison, a rollback plan and an obsolescence review.

**Self-Obsolescence Rule (canonical).** Every major ORNEUR generation must evaluate: *"What part of the current architecture is now unnecessary or inferior?"* If a better replacement is proven, the old mechanism must be allowed to retire. Nothing is sacred merely because ORNEUR previously built it.

## 12. Instant Response Fabric

The fabric spans the whole loop. Its four doctrines:

1. **Never serialize independent work.**
2. **Never invoke more intelligence than the request requires.**
3. **Verification runs beside generation when safe.**
4. **Trustworthiness must increase without making ORNEUR feel visibly slower.**

**Parallel lanes.** For a request the router starts, concurrently and as dependencies allow: model generation, memory retrieval, search, tool preparation, evidence construction, verification and confidence calculation. Lanes that need another lane's output wait on it; nothing else waits. The Adaptive Compute Engine cancels lanes whose result can no longer change the outcome.

**Two release regimes.**
- *Strict contracts:* **validate before release.** Nothing is emitted until the independent validator passes (the qualified `orca.contracts` behavior; deterministic contracts need no model call at all).
- *Free text:* **progressively verified streaming.** Text is released in classes, and no emitted byte is ever silently treated as verified:
  1. *Non-claim text* (connectives, formatting, verbatim quotation of supplied source text) may stream immediately.
  2. *Claim-bearing spans* are either **held** until sufficiently verified under the authority policy, or **labelled provisional before emission** (a visible marker travels with the span). One of the two is mandatory; a claim-bearing span is never streamed unmarked and unverified.
  3. If a span that was already emitted (held-and-released or provisional) is later found unsupported or contradicted, ORNEUR issues a **visible correction event** that names the span and the reason. Transport-level retraction is **not** claimed: bytes that have reached the user cannot be recalled, so the recourse is an explicit, user-visible correction, never a silent edit and never an implication that the span was withdrawn.
  4. Provisional labels are upgraded to verified only by an explicit verification event tied to the span's evidence, never by elapsed time or by the absence of an objection.
  The user sees non-claim text quickly; claim text arrives verified, or visibly provisional, or visibly corrected.

**Latency targets (DESIGN TARGETS ONLY — no SLO is measured or claimed):**

| Path | Design target |
|---|---|
| strict deterministic contract | server-side overhead ≤ ~50 ms |
| FAST model path | first token ≤ ~300 ms |
| REASON | first visible progress signal ≤ ~1000 ms |
| FRONTIER | acknowledgement plus progressively verified updates ≤ ~1500 ms |

These numbers exist so that designs can be judged against something; they must be replaced by measurements before any external statement is made. They are not derived from any model benchmark.

## 12a. Output semantics: epistemic vs non-epistemic (final pre-freeze hardening)

Contract Compliance and factual Verification are distinct concepts, and not every output makes a factual claim. `OutputKind` is assigned by the ORNEUR router from trusted runtime state (section 12c), never by a model, and it decides what a result must prove before it may be represented as complete:

| `OutputKind` | Examples | What must be proven before COMPLETED | Presented to the user as |
|---|---|---|---|
| `DETERMINISTIC_EXACT_TEXT` / `DETERMINISTIC_MATH` / `DETERMINISTIC_JSON_LITERAL` | "Reply exactly: READY", `2 + 3`, an explicit JSON literal | a `SATISFIED` contract whose evidence digest equals the output digest, trusted `DETERMINISTIC_AUTHORITY` provenance, and `model_calls == 0`. No separate factual Verification: the deterministic mechanism establishes correctness completely | deterministic output |
| `GENERATED_EPISTEMIC` | "The capital of X is Y" | a passing, trusted, digest-bound Verification of the exact output, **or** trusted claim-level coverage of every factual claim (section 12d) | verified claims |
| `GENERATED_STRUCTURED_EPISTEMIC` | schema-valid JSON that asserts facts | the epistemic requirement above **and** a `SATISFIED` `JSON_SCHEMA` contract. Schema compliance alone is never sufficient | verified claims |
| `GENERATED_TRANSFORMATIVE` | rewrite professionally, translate, format, summarise supplied material with attribution | **no** factual Verification for the content it merely reshapes; it must carry the digests of the supplied sources and trusted epistemic-screening provenance. Any *new* factual claim it introduces is enumerated as a `ClaimBinding` and is epistemic **for that claim** (rule C) | transformation of supplied material |
| `GENERATED_CREATIVE` | a fictional short story, brainstorming presented as ideas | **no** factual Verification for invented content; trusted epistemic screening; embedded factual claims are bound and verified individually. It can never be presented as verified fact (rule D) | fiction or ideation |

Rules, all machine-checked in `CognitiveResult`:

- **A.** Any factual or inferential claim ORNEUR makes needs appropriate Verification/Evidence before it can be represented as verified.
- **B.** A non-epistemic transformation is not forced through fake factual verification, so the verification latency is only paid where a truth claim exists.
- **C.** A transformation that introduces new factual claims is epistemic for those claims.
- **D.** Creative or brainstorming content is never silently represented as factual: `presented_as` must equal the kind's presentation, and a creative or transformative result cannot claim `VERIFIED_CLAIMS`.
- **E.** Contract compliance stays separate from truth: a satisfied contract is necessary for structured output and sufficient for nothing epistemic.
- **F.** Strict-contract fail-closed behaviour is unchanged: the Contract Engine is untouched, and a deterministic bypass needs the contract to be `SATISFIED` with evidence bound to the same output digest.

Examples. "Rewrite this paragraph professionally" completes as `GENERATED_TRANSFORMATIVE` without factual verification if no new claims are introduced. "Write a fictional short story" completes as `GENERATED_CREATIVE`. "The capital of X is Y" is `GENERATED_EPISTEMIC`. Valid JSON containing factual claims is `GENERATED_STRUCTURED_EPISTEMIC`. Misclassifying an epistemic answer as creative is not something a model can do: the classification must carry router provenance that a trusted ledger verifies.

## 12b. Content binding of verification to the exact output (time-of-check/time-of-use protection)

`CognitiveResult.output_digest` and `VerificationResult.subject_digest` are lowercase SHA-256 over the **exact canonical bytes released**: the UTF-8 encoding of the text exactly as emitted, with no normalisation (for canonical JSON, the canonical serialisation is the released text). A Verification qualifies only if `subject_ref == output_ref` **and** `subject_digest == output_digest`, **and** trusted `VERIFIER` provenance shows the verifier's `input_digest` was that digest. For deterministic outputs, `contract_output_digest` (the contract evidence's own output digest) must equal `output_digest`, and the deterministic-authority provenance is bound to the same digest.

References are opaque names and can be re-pointed; the digest is the identity. Consequences, all regression-tested: changing the output changes its digest and invalidates any earlier Verification; a Verification of an older version cannot qualify a newer output; a matching ref with a different digest fails; a matching digest under the wrong subject ref fails. Release-time protection: the emission path must call `CognitiveResult.release_matches(bytes)` (or an equivalent re-hash) immediately before sending, so a check-then-swap between verification and release is detected rather than trusted.

## 12c. Trusted runtime provenance (no self-asserted authority)

An ordinary string is not authority. Privileged statements (the router's `output_kind` assignment, a deterministic authority, claim extraction, epistemic screening, and a verifier's involvement) are made through `RuntimeProvenance`: `provenance_id`, `component_id`, `component_kind` (`ROUTER`, `DETERMINISTIC_AUTHORITY`, `CLAIM_EXTRACTOR`, `EPISTEMIC_SCREENER`, `VERIFIER`), `execution_ref`, `authority_evidence_ref`, `input_digest`, `output_digest`, `seal`. The `seal` is an HMAC minted only by a `ProvenanceLedger`, the in-process trust anchor held by trusted runtime code. The protocol does not attempt PKI; a later generation can replace the seal with signatures without changing the fields.

Invariants: (1) a user- or model-supplied payload cannot make itself authoritative by writing "ORNEUR_ROUTER" or by naming a deterministic tool, because without a ledger-issued seal the provenance does not verify; (2) `COMPLETED` results are validated only against a trusted ledger and fail closed without one; (3) provenance must be bound to the content it vouches for (classification digest, output digest, verified digest); (4) **future deserialisation of any untrusted or model-generated content must strip or reject privileged fields** (`strip_privileged` lists them: provenance, `output_kind`, `presented_as`, contract status and evidence, `model_calls`, `verifications`, `claims_trusted`, `seal`), and the runtime must re-derive them from its own state.

## 12d. Claim-level verification (future contract; no engine implemented)

Progressive verification will operate on individual claim-bearing spans. The protocol therefore defines `ClaimBinding` (`claim_id`, `output_ref`, `output_digest`, `claim_digest`, optional `span_start`/`span_end`, optional `canonical_claim`) and lets a `VerificationResult` bind either to the whole output or to one claim (`claim_id` + `claim_digest`, still inside the output identified by `subject_digest`). A result may complete on claim-level coverage when trusted `CLAIM_EXTRACTOR` provenance vouches for the enumeration and every bound claim has a passing, trusted, digest-bound claim verification. Non-claim prose therefore streams without a fake whole-output verification while coverage of factual claims is still proven. Only canonical claim representations or span digests are stored; hidden chain-of-thought is never stored. `ClaimBinding.matches_output(text)` checks that released text and span still hash to the bound digests.

## 13. Authority and contracts

The Authority Runtime and the Contract Compliance Engine are unchanged by this phase. The Contract Engine remains `SYSTEM_CONTRACT_QUALIFIED`; its qualification artifact and the historical raw-model control evidence (Qwen3-8B, Mistral-Nemo, Phi-4 all `RUNTIME_QUALIFIED=false`) are not modified. Every stage that emits to a user or acts on the world passes through these two mechanisms, and no expert's self-reported confidence or compliance is trusted.

## 14. Stable Core Intelligence Protocol

The protocol module defines the following typed, versioned, model-independent interfaces, each with a validator that returns every violated rule:

`CognitiveRequest`, `CognitiveResult`, `Objective`, `WorldState`, `WorldDelta`, `Discovery`, `Hypothesis`, `EvidenceReference`, `VerificationResult`, `ExpertCapability`, `ExpertRequest`, `ExpertResult`, `Outcome`, `FailureGenomeEntry`, `CognitivePrimitive`, `ArchitectureMigrationManifest`, `PromotionDecision`

(plus supporting `ComputeBudget`, `InformationGainQuery`, `PreferenceFeedback`, `ArchitectureDescriptor`, `AssetMigration`). No field names a model family or a parameter count. Objects are frozen; updates produce new revisions chained by digest. The module is deliberately small: it freezes interfaces so later phases cannot quietly couple ORNEUR to one architecture.

## 15. Foundation models in this architecture

A foundation model is one replaceable organ that may realize FAST, REASON or an expert. The Genesis selection is a separate, evidence-gated process (`GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.md`, `GENESIS_CAPABILITY_EVAL_V1_DESIGN.md`). **No foundation is selected**, and this architecture is written so that none needs to be.

## 16. What must be true before this becomes real

- Genesis capability eval executed on admitted candidates under the pre-registered rule (needs an explicit owner funding decision).
- Subsystems built and qualified one at a time, each with its own frozen evals.
- Latency targets converted into measured budgets.
- Every "not claimed" item above either measured or left unclaimed.

## 16a. Freeze-readiness (computed; READY is not FROZEN)

The three flags below are computed by `orca/intelligence/freeze.py` from behavioural self-tests and structural checks on this tree and are recorded in the JSON companion (`freeze_status`). A test asserts this section equals the computed values, so no flag can say `true` unless the checks justify it. Freezing additionally requires exact-SHA CI and an independent audit, so `frozen` remains `false` in this artifact.

```
ETERNAL_ARCHITECTURE_V1_FREEZE_READY = true
CORE_INTELLIGENCE_PROTOCOL_V1_FREEZE_READY = true
GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY = true
frozen = false
```

Version note: the semantic protocol change (new `OutputKind` members, digest binding, provenance, claim binding) is a breaking change relative to `orneur.core-protocol/1.0.0`, so the protocol is now `1.1.0` and the architecture `1.1.0`. Both are made before any freeze, so no frozen version is altered.

## 17. Authorizations

`training=false`, `gpu=false`, `provider_inference=false`, `phase_21c=false`, `foundation_selected=false`.
