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

## 3. Candidate pool and the pre-registered funnel

The refreshed pool has 15 gate-admitted `GENESIS_EVAL_ADMITTED` models (see the refresh). *Admitted for evaluation* is deliberately not *proven trainable*: PEFT/QLoRA feasibility is `INFERRED_NOT_EXECUTED` until the Stage-0 CPU checks and the Stage-3 pilot produce evidence, and the three Phase 21B.4.20 controls are baseline-only and never admitted.

**Funnel principle.** No stage may use release date, parameter count, popularity, vendor benchmark claims or any size proxy as a *selection input*. Where money genuinely limits a stage, the limit is an explicit, published **cost/resource cap**, not a preference for some model size. The machine-readable form is `orca/eval/genesis_funnel.py` (`funnel_spec()`), embedded in the architecture JSON; tests prove the stated invariants.

| Stage | What | Who enters | Compute | Cap (planning constants, not authorization) |
|---|---|---|---|---|
| 0 — CPU integrity and compatibility | tokenizer round-trip, chat-template rendering incl. tool and thinking modes, config/architecture load on CPU under the pinned library stack, license text archived, revision + file hashes verified | **ALL** `GENESIS_EVAL_ADMITTED` models | CPU only | no GPU spend |
| 1 — Small common screening probe | one identical, small item set spanning every category plus a serving smoke test | **ALL** Stage-0-compatible models (no pre-selection of any kind) | 1×H100 | hard cap 0.25 GPU-hours per model including load, i.e. at most 15 × 0.25 h × USD 3.95/h = USD 14.81 for the current 15-model pool |
| 2 — Full capability eval | full item set, 2 sampling configurations, all 21 categories | Stage-1 survivors | 1×H100 | total USD 40 |
| 3 — Trainability pilot | 5M-token QLoRA format/contract SFT on the training split under one common protocol (`genesis-trainability-pilot-v1`), then re-run of the format categories and a regression check | up to 3 finalists chosen from **PRE-TRAINABILITY** information only (below) | 1×H100 | total USD 25 |

Planning total if every cap is fully used: USD 14.81 + 40 + 25 = USD 79.81, against a planning budget of USD 111–118 (about INR 10,000). This does **not** authorize spending and does not leave room for a full training run above pilot scale; the eval requires an explicit owner funding decision and a hard spend cap before anything runs. If the pool grows so the Stage-1 cap would exceed its budget, the funnel does **not** drop models automatically: the owner must raise the cap or remove models explicitly and record why.

**Stage 0 exit.** A model leaves the funnel at Stage 0 only for a *measured* failure of a pre-registered CPU check (for example, the tokenizer cannot round-trip or the architecture cannot load under the pinned stack). Nothing else is consulted.

**Stage 1 drop rule.** A model is dropped only if, on a gating category with sufficient power, the 95% **upper** confidence bound of its score is below that category's frozen floor (it is *confidently* below the floor). `LOW_POWER` and report-only categories can never drop a model. This makes the cheap probe safe: it removes only models that are clearly unusable.

**Stage 2 cost rule.** If the projected Stage-2 cost of all survivors fits the cap, all enter. Otherwise the transparent resource gate applies: first the cheapest survivor of each architecture family (diversity), then remaining survivors by ascending projected cost and then model id, until the cap is used. Projected cost comes from Stage-1 measured GPU time. This is an explicit cost gate and may disadvantage expensive-to-run models; that is reported, and the owner may raise the cap.

**Stage 3 entry (non-circular).** Finalists are chosen only from information that exists before any trainability result: Stage-2 capability results, projected cost and architecture family. Order: (a) the Pareto-non-dominated set on capability categories and cost; (b) one per architecture family, ascending cost; (c) ascending cost; (d) model id; capped at 3. A `trainability` value, if it were present, is ignored by construction (a test proves this). Models that do not enter Stage 3 are **not finalists and cannot be selected**.

**No foundation may be selected until all remaining finalists have completed the same trainability pilot.** Selection code returns `NO_SELECTION_YET` until every finalist has a `COMPLETE` pilot under the same protocol id. Only then does trainability join the ranking below, so it is never used to decide who is measured.

## 4. Capability categories (all mandatory; per-category results only)

Item counts are minimums chosen so a 95% interval half-width is about ±0.07 for a category near 0.7 (n ≈ 165 for large categories; smaller categories are flagged **LOW_POWER** and may only *fail* a model, never rank it).

| # | Category | What is measured | Item sources (all frozen, hashed) | Scoring | Floor (PROPOSED, unfrozen) |
|---|---|---|---|---|---|
| 1 | `instruction_following` | verifiable constraints (length, format, inclusion/exclusion) | synthetic verifiable + private set | programmatic checker | ≥ 0.70 |
| 2 | `strict_contracts` | exact-text, math-literal, JSON-literal, schema contracts **raw**: fraction satisfied with no repair, with 1 retry, and fail-closed rate | generated from contract engine grammar (no hard-coded A/B/C ids) | independent validator = Contract Engine validators | **report-only recovery-cost signal; never a floor and never a ranking input** |
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
| 21 | `trainability` | Stage 3 pilot: format/contract gain per USD and regression on unrelated categories | private train/dev split | before/after delta | Stage-3 finalists only (a measurement, not an entry floor): improvement without regression |

Floors are **proposals**, chosen to reject clearly unusable models, not to certify quality. They must be frozen and hashed before the first run; the owner may adjust them *before* freezing. "Report only" categories cannot select a model but are still published.

## 5. Selection rule (pre-registered)

Applied only after every finalist has completed the same trainability pilot: (1) a model must clear every frozen floor on the gating categories; (2) drop any model Pareto-dominated on every gating category at equal or lower cost; (3) rank the remainder lexicographically by `verification`, then `evidence_use`, then `trainability` (from the common pilot), then `cost`; (4) ties or irreconcilable trade-offs go to an explicit owner decision. Release date, parameter count and popularity are never inputs. `strict_contracts` is a **report-only recovery-cost signal**: raw-model contract behaviour tells us how often the Contract Engine would have to recover or fail closed, but `SYSTEM_CONTRACT_QUALIFICATION` belongs to ORNEUR itself and is neither a model floor nor a ranking input. The output is either `FOUNDATION_SELECTED` with the per-capability table, or `NO_MODEL_QUALIFIES` (a legitimate result).

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

1. Owner funding decision with a hard spend cap for the stated stage caps.
2. Pre-registration file (floors + item hashes + selection rule) frozen and hashed.
3. Fresh, exact-SHA-verified CPU-side integrity (Stage 0) complete.
4. An explicit authorization message for GPU use. **None exists now.**

## 11. Known uncertainties

- Floors are proposals and could reject every model or none.
- The Stage-2 cost rule can disadvantage expensive-to-run models when the cap binds; this is reported and the owner may raise the cap.
- Some categories (discovery, information gain, hypothesis testing, counterfactual) require newly built private item sets; their construction cost is not included in GPU estimates.
- Judge disagreement in human-judged dimensions may make some rankings unresolvable; the rule then hands the decision to the owner.

## 12. Authorizations

`gpu_authorized=false`, `training_authorized=false`, `provider_inference_authorized=false`, `phase_21c_authorized=false`, `foundation_selected=false`.

## 13. Freeze-readiness (computed; READY is not FROZEN)

Computed by `orca/intelligence/freeze.py` and recorded in the architecture JSON; a test asserts this section equals the computed value. Freezing additionally needs exact-SHA CI and an independent audit.

```
GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY = true
```
