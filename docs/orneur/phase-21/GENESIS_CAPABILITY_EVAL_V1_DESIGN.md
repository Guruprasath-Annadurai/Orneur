# Genesis Capability Eval V1 — Refreshed Design (2026-09-26)

Status: **design only. Nothing in this document is executed, and nothing here authorizes GPU use, provider inference, training, spending or Phase 21C.** It replaces the *planning* assumptions of the earlier minimum capability evaluation (420 items, three control models) for the refreshed candidate pool and the new ORNEUR identity. Earlier documents are historical and unchanged.

Companion documents: `GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.md` (candidate pool), `docs/orneur/intelligence/ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.md` (what the eval must serve), `GENESIS_BENCHMARK_INTEGRITY_CONTRACT.md` (contamination rules, unchanged and still binding).

## 1. What changed and why

- The old pool (Qwen3-8B, Mistral-Nemo, Phi-4) was a runtime-qualification **control** pool. The pool is now the gate-admitted set from the refresh.
- ORNEUR now includes Discovery Intelligence, hypothesis testing, outcome learning and information-gain reasoning; a base model is judged on the capabilities those need, not on chat quality alone.
- Strict output contracts are enforced by the ORNEUR Contract Engine, not by the model. The eval therefore reports raw-model contract behavior **as a cost signal** (how often the engine must recover or fail closed) and never as a substitute for `SYSTEM_CONTRACT_QUALIFICATION`.

## 2. Principles

1. **No single "smartness" score.** Results are per capability, reported with confidence intervals. There is no weighted composite that can hide a capability failure.
2. **Pre-registered rule.** The floors and the selection rule are frozen (content-hashed) *before* the first model is run. After the first run they cannot change for that eval version; a change means a new version.
3. **Frozen, contamination-controlled items** (per the benchmark integrity contract): private hold-out material is not published, not used in training data, and hashed.
4. **Same harness, same settings, same items** for every model; sampling configuration recorded; failures are reported as failures, never dropped.
5. **Raw model vs system.** Everything is scored on raw model output first. System-level scores (with the Contract Engine, verification, tools) are reported separately and labelled.
6. **No model is favoured by recency, size or popularity.**

## 3. Candidate pool and the staged funnel

The refreshed pool has 15 gate-admitted `GENESIS_EVAL_ADMITTED` models (see the refresh). *Admitted for evaluation* is deliberately not *proven trainable*: PEFT/QLoRA feasibility is `INFERRED_NOT_EXECUTED` until the Stage-0 CPU checks and the Stage-3 pilot produce evidence, and the three Phase 21B.4.20 controls are baseline-only and never admitted. Running the full eval on all 15 would consume a large fraction of the ~INR 10,000 planning budget, so the eval is staged; each stage has a **mechanical** entry rule that never uses capability results from a later stage or vendor benchmark claims.

| Stage | What | Who enters | Compute | Est. cost (formula, not measured) |
|---|---|---|---|---|
| 0 — CPU integrity (first evidence toward trainability) | tokenizer round-trip, chat-template rendering incl. tool and thinking modes, config/architecture load on CPU, license text archived, revision + file hashes verified | all 15 admitted models | CPU only | USD 0 GPU |
| 1 — Screening | reduced item set over all 21 categories (≈ 200 items) plus serving smoke | **LEAN:** per model *family*, the admitted model whose total parameters are nearest 9B (7 models). **FULL:** additionally the largest admitted model ≤ 32B per family (≤ 10 models); equal-size ties are broken by lexicographic model id, never by recency | 1×H100 | 0.4–1.0 GPU-h per model × USD 3.95/h |
| 2 — Full eval | full item set, 2 sampling configs, all categories | survivors of the pre-registered floors, at most 4 (drop Pareto-dominated first; ties → lower cost) | 1×H100 | 1–2 GPU-h per model |
| 3 — Trainability pilot | 5M-token QLoRA format/contract SFT on the training split, re-run of the format categories | at most 2 | 1×H100 | USD ≈ 1–7 per model + eval |

Estimated totals (planning only, formula = GPU-hours × the program's persisted H100 rate of USD 3.95/h, before a 1.5× contingency): **LEAN** Stage 1 ≈ USD 11–28; Stage 2 (≤ 4 models) ≈ USD 16–32; Stage 3 (≤ 2) ≈ USD 6–17. That can approach the whole USD 111–118 planning budget once contingency is included. Consequently the eval **requires an explicit owner funding decision** and the LEAN profile is the default recommendation. The budget cannot also fund a full training run of any model above the pilot scale until the eval concludes; this is a real constraint, not a formality.

## 4. Capability categories (all mandatory; per-category results only)

Item counts are minimums chosen so a 95% interval half-width is about ±0.07 for a category near 0.7 (n ≈ 165 for large categories; smaller categories are flagged **LOW_POWER** and may only *fail* a model, never rank it).

| # | Category | What is measured | Item sources (all frozen, hashed) | Scoring | Floor (PROPOSED, unfrozen) |
|---|---|---|---|---|---|
| 1 | `instruction_following` | verifiable constraints (length, format, inclusion/exclusion) | synthetic verifiable + private set | programmatic checker | ≥ 0.70 |
| 2 | `strict_contracts` | exact-text, math-literal, JSON-literal, schema contracts **raw**: fraction satisfied with no repair, with 1 retry, and fail-closed rate | generated from contract engine grammar (no hard-coded A/B/C ids) | independent validator = Contract Engine validators | report only; used for recovery-cost estimate |
| 3 | `structured_outputs` | valid JSON / schema conformance on realistic tasks | private schemas | schema validator | ≥ 0.85 valid without repair |
| 4 | `reasoning` | multi-step verifiable reasoning | private, short-answer | exact match | ≥ 0.50 |
| 5 | `coding` | hermetic, static and executable checks | private | unit tests in sandbox | ≥ 0.40 |
| 6 | `mathematics` | short verifiable maths | private | exact / numeric | ≥ 0.50 |
| 7 | `research` | answer from supplied documents, cite sources | private doc bundles | claim-support checking | ≥ 0.50 |
| 8 | `tool_use` | choose/call tools with valid arguments; refuse when no tool applies | private tool specs | argument validity + outcome | ≥ 0.60 |
| 9 | `long_context` | retrieval and reasoning at 8k / 16k / 40k (and higher where supported) | private | exact | ≥ 0.60 at 8k; report others |
| 10 | `multilingual` | instruction following and QA in a fixed language set incl. Indic languages relevant to the owner | private | programmatic + rubric-free checks where possible | ≥ 0.50 |
| 11 | `multimodal_where_applicable` | image/document understanding; **N/A** for text-only models (not a fail) | private | exact | report only |
| 12 | `verification` | detect a planted error in a given solution; judge claim vs evidence | private | exact | ≥ 0.60 |
| 13 | `evidence_use` | cite the right evidence, abstain when none supports | private | support/abstention checks | ≥ 0.60 |
| 14 | `counterfactual_reasoning` | consequences of changed assumptions on a supplied world state | private | exact against an oracle | ≥ 0.40 |
| 15 | `hypothesis_testing` | propose a falsification test that would actually refute a hypothesis; judge results | private | test-validity checklist checked by a deterministic rubric | ≥ 0.40 |
| 16 | `discovery_quality` | subset of `ORNEUR_DISCOVERY_EVAL` scaled to a base-model probe | private | see §6 | report only in V1 |
| 17 | `cross_domain_transfer` | see §8 | private | see §8 | report only; **capability not claimed** |
| 18 | `information_gain_reasoning` | given an underdetermined problem, ask the single question that most reduces uncertainty | private with known-optimal question set | match against oracle ranking; exactly-one-question check | ≥ 0.40 |
| 19 | `latency` | first-token latency and tokens/s under the harness | measured | measurement, with hardware recorded | report only |
| 20 | `cost` | USD per 1M tokens served and to train, on stated hardware | measured + formula | measurement | report only |
| 21 | `trainability` | Stage 3 pilot: format/contract gain per USD and regression on unrelated categories | private train/dev split | before/after delta | must show improvement without regression |

Floors are **proposals**, chosen to reject clearly unusable models, not to certify quality. They must be frozen and hashed before the first run; the owner may adjust them *before* freezing. "Report only" categories cannot select a model but are still published.

## 5. Selection rule (pre-registered)

Identical to the refresh's rule, restated: (1) a model must clear every frozen floor; (2) drop any model Pareto-dominated on every category at equal or lower cost; (3) rank remaining models lexicographically by `strict_contracts` recovery cost margin, then `verification`, then `evidence_use`, then `trainability`, then `cost`; (4) ties or irreconcilable trade-offs go to an explicit owner decision. Release date, parameter count and popularity are never inputs. The output is either `FOUNDATION_SELECTED` with the per-capability table, or `NO_MODEL_QUALIFIES` (a legitimate result).

## 6. `ORNEUR_DISCOVERY_EVAL` (future; designed, not executed)

**Question answered:** does the system find useful information that was *not explicitly requested*?

**Task format.** Each item is a bounded scenario: a set of documents/data (a small "world"), an objective, and a question that deliberately does not mention the planted finding. Planted items include: an inconsistency between two documents, a dependency that invalidates a stated plan, a weak early signal, a missing high-value fact, a transferable pattern from a second supplied domain, and distractors (true but irrelevant facts; near-miss false alarms). Ground truth is a private list of *valid* discoveries with evidence anchors, plus a list of decoys.

**What is scored** — each *candidate discovery* the system emits is scored on eight dimensions:

| Dimension | Scored by |
|---|---|
| novelty | not already stated in the prompt or trivially entailed by it (deterministic overlap check + private reference list) |
| relevance | bears on the stated objective (reference mapping) |
| evidence quality | fraction of claimed evidence that actually exists and supports the claim (mechanical anchor check) |
| counter-evidence awareness | whether known counter-evidence in the world was found or acknowledged |
| actionability | a concrete `potential_action` exists and is executable with supplied means |
| falsifiability | a falsification condition exists and would actually distinguish the claim (rubric checklist, deterministic where possible) |
| importance | matches the private importance grading of the planted item |
| non-obviousness | not in the "obvious" reference list |

Aggregate reporting is **per dimension**, plus *precision* (valid discoveries / emitted), *recall* (planted valid discoveries found), and a *decoy acceptance rate*. Emitting a decoy as a confident discovery is penalised; emitting nothing is never rewarded. No single composite is published.

**Human-judgment control.** Any dimension not checkable mechanically is scored by at least two independent judges (human owner and/or a model judge that is *not* the system under test and is disclosed), with agreement reported; disagreement is reported, not averaged away.

**Status.** Design only. No model is run. No claim about discovery capability is made.

## 7. `ORNEUR_SELF_IMPROVEMENT_EVAL` (future; designed, not executed)

**Question answered:** can the *learning system* (not the model) detect a capability gap, produce a candidate improvement, evaluate it honestly, reject regressions and promote only measured improvements?

**Harness.** A sandboxed, offline replica of the loop with **synthetic** failures and a frozen seed:

1. *Gap detection:* the harness supplies a stream of failures/outcomes containing a planted capability gap plus noise; score = did the Failure Genome contain an entry naming the gap (precision/recall over planted gaps; false-gap rate).
2. *Candidate generation:* the system proposes a candidate (data, adapter, strategy). Score = does it address the gap on the harness's held-out gap set.
3. *Honest evaluation:* the system must run frozen, adversarial and regression suites. Score = evaluation completeness; **integrity checks** detect eval tampering, test-set leakage into the candidate's data, and cherry-picking.
4. *Regression rejection:* some candidates are deliberately built to improve the gap while breaking something else. Score = fraction correctly rejected.
5. *Promotion discipline:* candidates that are neutral or worse must be rejected; a candidate produced by component X cannot be promoted by X. Score = zero tolerance: any self-promotion, any promotion without all four gate references, or any promotion with a regression **fails the eval**.
6. *No live mutation:* the harness checks that the serving system's weights/config are byte-identical before and after the loop except via a `PromotionDecision`.

**Reported metrics:** gap detection precision/recall, candidate efficacy, regression-catch rate, false-promotion count (must be 0), integrity violations (must be 0). **Status:** design only; no live self-modification exists or is authorized.

## 8. `CROSS_DOMAIN_TRANSFER` (future category)

**Question:** can a proven pattern from domain A solve a problem in domain B when the surface vocabulary differs?

**Format.** Pairs of items: a worked solution in domain A (e.g. a scheduling/queueing solution) and a problem in domain B (e.g. an unrelated logistics or biological one) whose structure matches; distractor domain-B problems with matching vocabulary but different structure. Scored on: identifying the mapping, the correctness of the transferred solution on B, and rejection of the vocabulary-matched decoys. **The capability is not claimed today**; the category is reserved so it cannot be silently omitted from the roadmap. Reported per model, never composited.

## 9. Integrity, contamination and reproducibility

- Item sets are content-hashed; hashes are recorded in the eval's pre-registration file before any run.
- Training data for any later stage must be checked against the hold-out hashes (n-gram and semantic overlap) per the benchmark integrity contract.
- The harness pins library versions (the current harness pins vLLM 0.29.0; per-model serving support at that pin is **unverified** for the newest architectures and is a Stage 0/1 exit criterion, not an assumption).
- Every run stores raw outputs, prompts, sampling settings, hardware, revision hashes and the harness commit.
- Historical control evidence and the Contract Engine qualification are read-only inputs; nothing here rewrites them.

## 10. Preconditions before anything is executed

1. Owner funding decision for a stated profile (LEAN or FULL) and a hard spend cap.
2. Pre-registration file (floors + item hashes + selection rule) frozen and hashed.
3. Fresh, exact-SHA-verified CPU-side integrity (Stage 0) complete.
4. An explicit authorization message for GPU use. **None exists now.**

## 11. Known uncertainties

- Floors are proposals and could reject every model or none.
- LEAN pool uses "nearest 9B per family" as a mechanical rule; it may miss a family's better size. FULL mitigates at higher cost.
- Some categories (discovery, information gain, hypothesis testing, counterfactual) require newly built private item sets; their construction cost is not included in GPU estimates.
- Judge disagreement in human-judged dimensions may make some rankings unresolvable; the rule then hands the decision to the owner.

## 12. Authorizations

`gpu_authorized=false`, `training_authorized=false`, `provider_inference_authorized=false`, `phase_21c_authorized=false`, `foundation_selected=false`.
