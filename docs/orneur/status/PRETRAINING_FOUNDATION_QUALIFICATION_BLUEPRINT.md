# ORNEUR Pre-Training Foundation Qualification Blueprint

Date: 2026-10-11 · Repository HEAD of this document: branch `claude/s2-customer-correctness` (stack #22→…→#36; nothing merged; `main` = `464b602f3f25`)
Author role: Claude (engineering). Requested by: the founder (Pre-Training Directive).

> **TRAINING IS NO-GO.** This document does not initiate, resume, schedule or authorize training, GPU use, spend, corpus generation, provider inference,
> foundation selection or any protected operation. It is NON_NORMATIVE: it is not in Manifest V3 and does not amend RSE-ARCH-1.2, R65, C27, G1 or any
> founder-controlled gate. It is a planning and evidence document; an author's claim in it is not independent acceptance.
> Training stays NO-GO until every mandatory gate below is satisfied **and** the founder gives explicit authorization (FINAL-2, then EXEC-1).

## 0. How to read this

**Status vocabulary.** *VERIFIED-HERE* means I read the artifact (or ran its test) in this pass and the claim holds as stated; it is **not** independent acceptance.
*PARTIAL* means implemented or evidenced in part. *MISSING* means nothing exists. *BLOCKED* means it cannot move without a founder act, an external party or a
license. The authoritative acceptance count is the register's, not mine: `python3 scripts/acceptance/validate_register_graph.py --check` →
`pretraining=95 numerator=0 application=3 execution=2 post=1` (re-run in this pass). **0 of 95 pre-training requirements are accepted.** Nothing in this
blueprint changes that number; only the acceptance engine with detached, independent signatures can.

**Evidence convention.** Paths are repository paths. `PR #n` are draft PRs, all unmerged. "Register" is `docs/orneur/ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md`
(+ `docs/orneur/acceptance/register_graph.json`). Facts about external models are quoted **as recorded in the repository** (`docs/orneur/phase-21/…`); I did not
re-verify them against the internet in this pass and they must be re-verified at freeze time (decision package criterion K).

## 1. Executive verdict

| Question | Answer |
|---|---|
| Is ORNEUR ready to train Genesis or Novus? | **No.** 0/95 mandatory pre-training rows accepted; no founder authorization exists (`TRAINING_AUTHORIZATION.json` = `NOT_AUTHORIZED`). |
| Is there a differentiated, verifiable model today? | **No.** Novus (`orca-core-combined-v2`) is `EXPERIMENTAL`, `NOT_PROMOTABLE` (2 of 4 measured gates fail). Genesis has no canonical checkpoint (legacy `orca-nano*` are 7.6B Qwen2.5-class artifacts, not the 3B target). Aeternum was never trained. No model is recorded as beating its own zero-shot base. |
| Is a foundation chosen? | **No.** `foundation_selected: null`. The canonical Genesis base (Qwen2.5-3B-Instruct) carries the `qwen-research` license: research only, commercial release **BLOCKED_LICENSE** (MODEL-2C). Three finalists exist; none is runtime-qualified; capability is unproven for all. |
| Is the independent evaluation ready? | **No.** V1 holdout was exposed publicly and is permanently invalid. V2 has real infrastructure (ledger, vault, sandbox, authorization gate, preregistration draft) but the V2 corpus is not generated, private storage is `NOT_CONFIGURED`, the repository is PUBLIC, the reviewer registry has zero keys, and no independent audit approval exists. |
| Is dataset provenance acceptable? | **No.** 140 hand-built records (~22.7k proxy tokens) across v1–v3; a signed corpus *inventory attestation* exists, but DATA-1/2/3/5 are not started, teacher-model output licensing is unreviewed, and base-model pretraining contamination is unknowable from outside. |
| Is the security authorization chain ready? | **Partially built, unreviewed.** Fail-closed training authorization gate (PR #24) and its adversarial assurance pass (PR #32), signed public-serving authority (PR #31), tenant isolation (PR #30), web tool authority and owner bootstrap (PR #35): implemented and CI-green, **none independently reviewed**, none merged. |
| Is the training infrastructure reproducible? | **Not yet.** No hash-locked train extra, no dry-run log, no two independent build digests (TRAIN-1/2, SUP-1, C39 not started); hardware chain (G4–G7, HW-01…27, C22–C38) entirely NOT_STARTED / NOT_AUTHORIZED pending a founder purchase decision. |
| Can ORNEUR beat its base models? | **Unproven; plausible at the system level, not yet at the raw-model level.** §6 defines the falsifiable research programme. The honest prior: fine-tuning on ~10²–10⁴ curated examples can change format, calibration and refusal behavior; it will not add broad capability. The defensible advantage is the *system* (verification, grounding, authority boundaries, routing, cost), and a trained model is justified only if it beats **base + the same system** with statistical confidence. |

**Verdict: NO-GO, with a defined path.** Critical path length is dominated by items only the founder or an external independent party can supply (§11, §12).

## 2. Reconciliation of completed work (nothing restarted)

| Layer | What exists | Evidence | Standing |
|---|---|---|---|
| Phases 0–15 (assistant platform, gateway, kernel, truth, memory, deliberation, society, agent runtime, relay) | Implemented and tested; closures recorded | `docs/orneur/phase-N/*CLOSURE*.md` | IMPLEMENTED_TESTED; each phase self-reported, not independently accepted |
| Phase 16–20 (native-intelligence audit, epistemic state/integrity, router) | Specs, threat models, evidence docs | `docs/orneur/phase-16…20/` | Same |
| Phase 21 Genesis programme (eval v1/v2, foundation study, control runtimes, decision package, V2 infrastructure) | Large evidence base; **foundation undecided; training not authorized** | `docs/orneur/phase-21/` (≈100 files) | §4–§8 |
| RSE-ARCH-1.2 / Manifest V3 security programme | Frozen architecture; software blocks IMP-2/3/4 (PR #8) and follow-ups (#9–#18) | `docs/orneur/phase-21/rse/v1.2/`; Register | **Unchanged by this blueprint and by Sprints 1–2.** Verified: `git diff dfa9188 HEAD` over `orca/rse`, `docs/orneur/phase-21/rse`, `docs/orneur/acceptance` is empty; the only changes under `docs/orneur/authorization/` since then are the two `NOT_AUTHORIZED` training templates added by PR #24 |
| Audit #007 remediation | Canonical verified cache paths (PR #23) | PR #23 `bd3072c` | Awaiting Antigravity Audit #008 (not received; PR #23 has 0 reviews) |
| Sprint 1 | Training gate (#24), serving policy (#25), register (#26), non-root container (#27/#28/#33), UI spec (#29), tenant isolation (#30), public-serving authority (#31), training assurance (#32), flow evidence (#34) | `docs/orneur/status/ORNEUR_DEVELOPMENT_REGISTER.md` | All 9/9 CI at their exact SHAs; **0 independent reviews** |
| Sprint 2 | G-020 web tool authority + G-021 owner bootstrap (#35); G-015/023/024/026/027 correctness (#36) | same | 9/9 CI; 0 independent reviews |

Accepted phases are preserved as-is. This blueprint adds a *qualification layer on top*; it does not re-open or edit any frozen artifact.

## 3. Requirement matrix by workstream

Row format: **requirement → status → exact evidence → blocker / next evidence needed**. Register ids are given where a counted row exists.

### WS-A Architecture maturity

| # | Requirement | Status | Evidence | Blocker / needed |
|---|---|---|---|---|
| A1 | RSE-ARCH-1.2 frozen, Manifest V3 intact | VERIFIED-HERE (unchanged) | Register G2 `PRESENT_ON_MAIN`; diff check above | none; keep untouched |
| A2 | Independent architecture review of RSE-ARCH-1.2 (G1) | **MISSING** | Register G1 `NOT_VERIFIABLE`: "No such review file was found" | A reviewer who did not author RSE-ARCH-1.2 must be named by the founder; review stored in-repo |
| A3 | RSE software IMP-2/3/4 independently code-reviewed and merged (G3, C01–C21, C45) | PARTIAL | PR #8 `da567d9…`, push run `37884389862` success; reviews = 0 | Independent review of the merged SHA + that SHA's main push CI (G3) |
| A4 | R65 (65-rule set) | **BLOCKED** | Register R65 `NOT_VERIFIABLE`; source text absent, no children | Founder supplies the approved source text; then one child row per rule (changes the denominator) |
| A5 | C27 class-K recovery | **BLOCKED by design** | Register C27 `NOT_STARTED`, DEC-K `NOT_AUTHORIZED` | Founder decision DEC-K keeps class K deferred and C27 unmet until a later architecture-change authorization. C27 stays mandatory; this blueprint does not implement it |
| A6 | Model-serving stack (gateway, runtime, router, cognitive kernel) is real and tested | VERIFIED-HERE for the test-double path | `docs/orneur/status/SPRINT2_CUSTOMER_CORRECTNESS.md`; `tests/test_product_flows_fake_ollama.py` (E2E vs `FakeOllama`) | A test double proves the request path, not model quality. Real-model end-to-end is untested |
| A7 | Application/web security boundary (tenant isolation, tool authority, owner bootstrap) | PARTIAL | PRs #30, #35; `tests/test_g006_tenant_isolation.py` (41), `tests/test_g020_agent_tool_authority.py` (59), `tests/test_g021_owner_bootstrap.py` (33) | Independent review (APP-1/APP-2 are `OPEN_PR_UNREVIEWED`); Postgres SQL unexecuted |
| A8 | Training code does not depend on the web app | VERIFIED-HERE | Register note: `orca/train` does not import `orca.serve` (APP rows are outside the pre-training denominator for that reason) | none |

### WS-B Trust root and hardware chain (counted in the 95)

| # | Requirement | Status | Evidence | Blocker |
|---|---|---|---|---|
| B1 | Hardware purchase and named selection (G4) | **BLOCKED (founder)** | Register G4 `NOT_AUTHORIZED`; freeze: `NO_HARDWARE_PURCHASE_AUTHORIZED` | Founder purchase authorization |
| B2 | Provisioning + key ceremony without secrets (G5) | **BLOCKED (founder)** | G5 `NOT_AUTHORIZED` | After G4 |
| B3 | Real-hardware controls C22–C38, HW-01…27, HW-FORGE (TPM policy, rollback counter, Secure Boot keys, IOMMU, USB deny, radios off, no netdev, ME check, LUKS2, storage scan) | **MISSING** | All `NOT_STARTED` in the graph | Hardware must exist; each needs its own real-device artifact. A simulator is only the partial credit the freeze allows (C26) |
| B4 | Two physical tokens (C08, C44) | **BLOCKED (founder)** | `NOT_AUTHORIZED` | Purchase |
| B5 | Crown isolated machine(s), custody (G7, G9, C38, C41, C40, C42) | **MISSING** | `NOT_STARTED` / `DESIGNED_ONLY` | After B1–B3 |
| B6 | Software-only designed rows (C06, C07, C40, C42, C48) | PARTIAL (DESIGNED_ONLY) | Graph | Implementation + review |
| B7 | Chamber design review, qualification runner authorization (G10, QUAL-1) | **BLOCKED** | `NOT_AUTHORIZED`; `QUALIFICATION_RUNNER_REGISTRY.json` = `REGISTERED_NOT_AUTHORIZED` | Founder authorization; independent chamber-design review naming SHA and tests run |
| B8 | P2 environment: attestation, egress test, spend-cap refusal, bit-budget counters (P2-1/2/4, C46, C47) | **MISSING** | `NOT_STARTED` | Needs G10 first |

### WS-C Model differentiation (evidence that ORNEUR models are better than their bases)

| # | Requirement | Status | Evidence | Blocker / needed |
|---|---|---|---|---|
| C1 | A trained Genesis checkpoint exists | **MISSING** | `docs/orneur/phase-1/GENESIS_NOVUS_AETERNUM_STATUS.md`; `MODEL_SPECS["genesis"]`: no canonical checkpoint; legacy nano = 7.6B Qwen2.5-class (`docs/orneur/phase-0/GENESIS_MODEL_IDENTITY.md`) | Foundation + data + gates (this blueprint) |
| C2 | Novus candidate measured against governance thresholds | VERIFIED-HERE | `docs/orneur/phase-1/NOVUS_PROMOTION_DECISION.md`: accuracy 72.8% (≥70 PASS), jailbreak block 70.0% strict (≥92 **FAIL**), bias 12.5% (≤20 PASS), domain eval 37.5% (≥75 **FAIL**) → `NOT_PROMOTABLE` | Not a training trigger. Failure analysis first (§6.4) |
| C3 | Any model beats its own zero-shot/base baseline with confidence | **MISSING** | `docs/PERPLEXITY_DIFFERENTIATION_PLAN.md` (citing the Phase 16 audit): "neither has beaten its own zero-shot baseline in a way that would support a raw-superiority claim" | A frozen paired comparison (§6.3) |
| C4 | Comparison vs competitors / frontier references | **MISSING** | `GENESIS_FRONTIER_*` docs design the method; provider access matrix shows blockers; no run | Owner-funded, terms-compliant reference runs (§6.5) |
| C5 | Aeternum (70B) | **MISSING / out of scope** | `MODEL_SPECS["aeternum"]` "never trained" | Not part of the first run; keep out of the denominator |
| C6 | Product claims honest | VERIFIED-HERE | `orca/serve/model_identity.py` (PR #36) reports requested vs served model, lifecycle, `EXPERIMENTAL` disclosure; public serving requires a signed grant (PR #31) | none |

### WS-D Candidate foundation comparison

| # | Requirement | Status | Evidence | Blocker / needed |
|---|---|---|---|---|
| D1 | Pre-registered criteria A–Q (gates A,B,K; weighted F–Q) | VERIFIED-HERE (defined) | `GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.md` §2 | freeze with the preregistration |
| D2 | Finalists identified with pinned revisions + licenses | PARTIAL | Same package; `GENESIS_FOUNDATION_SHORTLIST_2026.md`; `GENESIS_STAGE0_LICENSE_MATRIX.md` (LICENSE text retrieved at pinned revision where it exists; Mistral Small 4 repo has none, metadata-tag evidence only) | Re-verify at freeze time |
| D3 | Runtime qualification of controls | **FAILED / unproven** | Package §1: Qwen3-8B attempt 5 `PASS/FAIL/PASS`, Mistral-Nemo attempt 3 `FAIL/FAIL/FAIL`, Phi-4 attempt 1 `PASS/FAIL/FAIL`; **no control RUNTIME_QUALIFIED**; "no further control retry is authorized" | The failures were exact-output format failures of instruct models; the package states they are not capability evidence |
| D4 | Capability eval on a frozen private set | **BLOCKED** | Package verdict `FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL`; 420 items × 2 sampling configs planned, est. USD 6.15–9.28 (≈USD 9.2–13.9 with contingency) | Needs V2 freeze (WS-F), an owner funding decision (promotional headroom is insufficient), and separate sandbox authorization |
| D5 | Commercial rights for the chosen base (MODEL-2C) | **BLOCKED_LICENSE** for the current canonical base | `MODEL_SPECS["genesis"].license_commercial_use = "RESTRICTED"` (qwen-research); register MODEL-2C | Either a commercial grant, a base whose license permits commercial use (finalists are recorded as Apache-2.0 / MIT), or a founder record that no commercial release is made from this base |
| D6 | Founder selection record (MODEL-1) naming repo + exact revision | **BLOCKED (founder)** | `NOT_AUTHORIZED`; the code pin (MODEL-0) "is not a selection" | After D4 |
| D7 | Foundation provenance in the registry (C49 / MODEL-3) | **MISSING** | `NOT_STARTED` | After D6 |

### WS-E Dataset provenance

| # | Requirement | Status | Evidence | Blocker / needed |
|---|---|---|---|---|
| E1 | Corpus inventory + signed attestation | PARTIAL | `GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json` (83 KB) `ATTESTED`, `attested_complete: false`; status JSON: `contamination_check_status = PENDING_V2_CORPUS` on every entry | Attestation completeness; contamination pending the private corpus |
| E2 | Existing datasets documented and versioned | VERIFIED-HERE (small) | v1 37 records, v2 19, v3 84 (`GENESIS_DATASET_V3.md`); Novus combined 72 (65 train / 7 eval, `PUBLIC_SFT_DATASET_CLASSIFICATION.json`); manifests via `orca/registry/dataset_manifest.py` | Scale and diversity: 29% of Genesis v1 pairs exceed 0.85 similarity (`phase-0/GENESIS_DATASET_BASELINE.md`) |
| E3 | Provenance of synthetic/teacher data | **PARTIAL / RISK** | Inventory lists `distillation_data` from `llama3.1:8b` and `nvidia-nemotron-3-ultra-550b-a55b` teacher logs | **Output-use terms of each teacher are not reviewed.** No teacher output may enter a training corpus until a per-source license/terms record exists (DATA-1) |
| E4 | DATA-3 protected corpus creation, DATA-1 provenance manifest, DATA-5 independent custody, DATA-2 contamination/holdout separation | **MISSING** | `NOT_STARTED`/`NOT_ACCEPTED`; G8 corpus-generation grant `NOT_AUTHORIZED` (`CORPUS_GENERATION_AUTHORIZATION.json`) | Founder grant (G8), a generator identity separate from the runner, an independent custodian |
| E5 | Contamination controls | PARTIAL | `orca/eval/genesis_contamination.py` (framework `IMPLEMENTED_TESTED`); v1 scan: 0 exact / 0 near-duplicate overlaps across 90 tasks × 140 records (`GENESIS_EVAL_CONTAMINATION_REPORT.md`) | Lexical only. **Base-model pretraining contamination is unknowable** and must be handled by design (§5.3), not by claim |
| E6 | Data card (DATA-4) | **MISSING** | `NOT_STARTED` | After E4 |

### WS-F Independent evaluation

| # | Requirement | Status | Evidence | Blocker / needed |
|---|---|---|---|---|
| F1 | V1 private holdout | **INVALID (permanent)** | `GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json`: `PRIVATE_HOLDOUT_VALID=false`, 71 exposed files hashed; "V1 HOLDOUT is a public benchmark" | Never reuse any V1 prompt/answer/seed |
| F2 | V2 infrastructure | PARTIAL (strong) | `GENESIS_CAPABILITY_EVAL_V2_STATUS.json` component_states: access ledger, split-isolation, privacy scanner, sandbox, authorization gates `IMPLEMENTED_TESTED`; ledger deployed (sqlite); owner preflight `READY_FOR_PRIVATE_CORPUS_AUTHORIZATION` | none of this is "QUALIFIED/FROZEN" by its own terminology rule |
| F3 | V2 private storage | **BLOCKED** | `private_storage_state: NOT_CONFIGURED`; vault `ACTIVATED_VERIFIED_TEST_ONLY` (ephemeral test key); `repository_visibility: PUBLIC`; `PRIVATE_GITHUB_REPO` / `PRIVATE_OBJECT_STORE` are descriptor-only | Founder-held vault procedure (`GENESIS_CAPABILITY_EVAL_V2_OWNER_VAULT_PROCEDURE.md`), real secret, private store |
| F4 | V2 corpus generated, preregistration frozen | **MISSING** | `v2_corpus: NOT_GENERATED`, `v2_freeze: NOT_FROZEN`; preregistration 22 of 23 bindings filled, the remaining one (`private_corpus_aggregate_commitment`) deferred | Needs G8 grant and F3 |
| F5 | Freeze prerequisites | **ALL FALSE** | status `freeze_prerequisites`: contamination controls, exact-SHA CI, preregistration frozen, independent audit approval, new secret corpus, privacy audit, private storage, sandbox ready, SCREEN/HOLDOUT separation: every one `false` | Each is a work item in §11 |
| F6 | Independent reviewer path | **MISSING** | `REVIEWER_REGISTRY.json`: zero keys; `semantic_path_substitutes`; `REVIEWER_PATH_STATUS.md` | Founder enrolls an independent reviewer key (not the implementer, not the author) |
| F7 | Coding sandbox for model-generated code | PARTIAL | `sandbox_qualification_candidate` digest `sha256:4678e0aa…` recorded; containment suite runs against the pinned image; `model_generated_code_executed: false` | Separate authorization to execute model code; independent qualification |
| F8 | Judge protocol, frontier scoring contract, benchmark integrity | DESIGNED | `GENESIS_JUDGE_PROTOCOL_SPEC.md`, `GENESIS_FRONTIER_SCORING_CONTRACT.md`, `GENESIS_BENCHMARK_INTEGRITY_CONTRACT.md` | Implementation + review |
| F9 | Thresholds fixed before results (QUAL-3) | **MISSING** | `NOT_STARTED`; `GENESIS_PRETRAINING_QUALIFICATION.md` defers material-regression numbers to baseline calibration | §6.6 proposes the procedure; numbers must be frozen before any candidate result |

### WS-G Security authorization

| # | Requirement | Status | Evidence | Blocker / needed |
|---|---|---|---|---|
| G-1 | Fail-closed training authorization on every entry point | PARTIAL (implemented, unreviewed) | PR #24 `orca/train/authorization.py`; 145 gate/registry/acceptance tests pass in this pass; `TRAINING_AUTHORIZATION.json` = `NOT_AUTHORIZED`; `training_authorized()` returns false | Merge only after independent review |
| G-2 | Grant integrity, audit-chain verification, cross-ledger run budget; 16 bypass attacks fixed | PARTIAL (implemented, unreviewed) | PR #32 `orca/train/authorization.py`, `docs/orneur/status/taskc/`; entry-point inventory `TRAINING_AUTHORIZATION_ASSURANCE.md` lists **14 off-host training notebooks** that cannot be gated from this repository | Off-host notebooks must be retired or frozen before any run; one strict-xfail remains (audit-tail truncation) |
| G-3 | Founder-held authority keys; no automated key generation | PARTIAL | `AUTHORITY_REGISTRY.json` has one registered owner key id (`orneur-owner-authority-1`); `OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md` | Key custody evidence is the founder's; `AUTH-1` budget record missing |
| G-4 | Budget record (AUTH-1) with number, currency, signature | **MISSING** | `NOT_VERIFIABLE` | Founder |
| G-5 | Research-only scope (MODEL-2R) | **BLOCKED (founder)** | `NOT_AUTHORIZED` | Founder scope record |
| G-6 | Public-serving authority separate from training authority | VERIFIED-HERE | PR #31 `orca/gateway/serving_authority.py`; a grant is not a promotion | none |
| G-7 | Three-event chain FINAL-1 → FINAL-2 → EXEC-1 | VERIFIED-HERE (structure) | Register "Events"; validator rejects any readiness edge into FINAL-2/EXEC-1 | FINAL-1 needs all 95 counted rows |
| G-8 | Acceptance engine rejects reuse, wrong SHA, self-review, missing predecessor | VERIFIED-HERE | `scripts/acceptance/acceptance_engine.py`; `tests/test_acceptance_engine*.py` (in the 145 passed); ledger and trust store committed empty | none |

### WS-H Reproducible training infrastructure

| # | Requirement | Status | Evidence | Blocker / needed |
|---|---|---|---|---|
| H1 | Hash-locked train extra + pinned dry-run (TRAIN-1) | **MISSING** | `NOT_STARTED` | Build and review |
| H2 | Synthetic dry-run showing all locks still false afterwards (TRAIN-2) | **MISSING** | `NOT_STARTED` | After H1 |
| H3 | Two independent build digests of the training image (SUP-1, C39) | **MISSING** | `NOT_STARTED` | Compared on Crown |
| H4 | Hash-locked RSE extra with fail-closed audit (SUP-3) | PARTIAL | `UNMERGED_NOT_ACCEPTED` | Merge + review |
| H5 | Pinned base revision + tokenizer + chat template | PARTIAL | `MODEL_SPECS` revision pin `7548fff1…` (Qwen2.5-3B only) | Pin the chosen foundation; template stability criterion D |
| H6 | Reproducibility manifest (code SHA, data hashes, library versions, seeds, container digest) | **MISSING** | Package gate G9 `NOT_MET`; `orca/registry/training_run.py` captures git SHA, seed, precision, hardware, resume lineage | Wire it to the frozen datasets and image |
| H7 | Checkpoint/rollback (adapter checkpoints, byte-identical restore) | PARTIAL | `orca/registry/checkpoint.py` `verify_integrity()` | Restore test |
| H8 | Cost containment | PARTIAL (lessons recorded) | `GLM_5_3_FLASH_COMPUTE_COST_INCIDENT_2026-09-23.md`, `…FUTURE_ZERO_CASH_GPU_GUARDRAIL…`, program owner-billed delta 0 across control runs; spend cap refusal test P2-4 `NOT_STARTED` | Hard cap enforced in the environment, not in policy text |
| H9 | Hardware plan frozen (GPU class, provider, region, max hours, kill switch) | **MISSING** | Package gate G7 `NOT_MET` | Founder-approved plan |

### WS-I Evidence-based acceptance criteria

Defined in §8. Status: **DEFINED, NOT FROZEN.** Freezing requires QUAL-3 and an independent audit.

## 4. Architecture maturity assessment

**What is genuinely strong.** (1) A governance spine that is unusually explicit: three distinct events (FINAL-1/FINAL-2/EXEC-1), an acceptance engine that ignores published
status cells, empty committed ledgers so editing a file cannot "accept" anything. (2) Fail-closed authorization at every code entry point (PRs #24/#32). (3) A pre-registered, ledger-audited
evaluation design with an explicit "QUALIFIED is never used for something merely unit-tested" rule. (4) Honest negative results kept on record (Novus NOT_PROMOTABLE; V1 holdout invalidated;
control runtimes not qualified).

**What limits maturity.** (1) Zero independent reviews anywhere in the chain; the author/implementer/reviewer separation is designed but the reviewer roles are `UNRESOLVED_EXTERNAL`.
(2) The model layer is far behind the system layer: no checkpoint beats a baseline. (3) The pre-training denominator (95 rows) is dominated by hardware and trust-root items that
cannot start without a purchase decision, so the *calendar* critical path is not training-code work. (4) Scale: the whole Genesis/Novus corpus is ~10² records.

**Maturity rating (qualitative, author's).** System software: *beta, unaudited*. Evaluation infrastructure: *alpha-to-beta, unfrozen*. Model capability: *pre-alpha, unproven*. Trust root / hardware:
*design only*. Nothing here is a claim of independent assessment.

## 5. Foundation comparison and selection

### 5.1 Candidates as recorded in the repository

| Candidate | License (recorded) | Role | Control-runtime result | Capability | Notes |
|---|---|---|---|---|---|
| Qwen2.5-3B-Instruct (`unsloth/…`, rev `7548fff…`) | `qwen-research` (non-commercial) | current canonical Genesis base | not a control | unproven | **Research-only**; commercial release blocked (MODEL-2C). Also ambiguity history with the legacy 7.6B artifacts |
| Qwen3-8B (rev `b968826d…`) | Apache-2.0 | finalist 1 | attempt 5: PASS/FAIL/PASS | unproven | Smallest/cheapest; hybrid thinking template needs a deliberate SFT template decision; greedy decoding discouraged in thinking mode |
| Mistral-Nemo-Instruct-2407 (rev `04d8a905…`) | Apache-2.0 | finalist 2 | attempt 3: FAIL/FAIL/FAIL | unproven | 128k context; Tekken tokenizer friction under pinned vLLM |
| Phi-4 (rev `2db69c1c…`) | MIT | finalist 3 | attempt 1: PASS/FAIL/FAIL | unproven | Highest cost; 16K context; reasoning-oriented synthetic pretraining |
| Larger references (e.g. 27B-class, frontier-scale MoE) | mixed; several revenue/MAU-gated or unresolved | teachers / references, not first-run bases | not run | not run | Terms unresolved; teacher use of outputs needs per-source terms review (E3) |

### 5.2 Selection procedure (no selection is made here)

1. Gates first (pre-registered): **A** architecture supportable by mainstream PEFT/vLLM; **B** QLoRA-trainable and servable within the frozen hardware plan; **K** license permits fine-tuning, redistribution of derived weights and the intended use.
2. Then the weighted criteria F–Q from the decision package, scored **only** on the frozen private V2 set plus a 5M-token QLoRA format-adherence pilot per candidate (to separate "cannot do it" from "was not trained to emit this format", the actual cause of the smoke failures).
3. Report every dimension separately with paired-bootstrap CIs. No single "smartness" number; no selection by counting smoke passes.
4. A **base-swap-ability requirement**: data, eval and adapters are owned assets independent of the base, so a later base swap re-runs the pipeline (decision package §6). This is the mitigation for choosing the wrong first base.

### 5.3 Pretraining-contamination handling (cannot be proven away)

Because no candidate's pretraining corpus is inspectable, every capability claim is made on **items created after the candidates' data cutoffs, privately, with canary strings and
never exposed**, plus a *familiarity probe* (compare accuracy on verbatim-published vs freshly-authored isomorphic items; a large gap is evidence of memorization). The score that matters is the
**delta between base and tuned model on the same private items**, which is far less sensitive to base contamination than an absolute score.

## 6. Research strategy: how ORNEUR can achieve measurable advantages

### 6.1 Honest framing

Competing on raw capability with frontier labs and with the base models themselves is not credible with ~10²–10⁴ curated examples and a USD ≈10 evidence budget. ORNEUR's defensible hypotheses live
where its architecture is different: **verified grounding, calibrated abstention, authority/consequence discipline, tool-plan reliability, cost, and sovereignty (self-hosted)**. The research
programme tests each as a *falsifiable* hypothesis against explicit controls and keeps the negative results.

### 6.2 Arms (every comparison is paired, same items, same seeds)

| Arm | Definition | Purpose |
|---|---|---|
| **B0** | Base model, vendor system prompt, no ORNEUR scaffolding | raw baseline |
| **B1** | Base + engineered prompt (ORNEUR persona/format) | the *cheap alternative* a skeptic will propose |
| **B2** | Base + full ORNEUR system (kernel, Truth Fabric, memory, tools, verification) | measures the system's contribution |
| **T1** | Tuned adapter (LoRA/QLoRA) alone | measures what training adds |
| **T2** | Tuned adapter + full system | the product |
| **R** | External reference(s) (frontier API models, answer engines) | context only; terms-compliant, owner-funded |

**Training is justified only if T2 > B2 (and T1 > B1) on a pre-registered primary metric with the CI excluding zero.** If B2 already matches T2, the correct decision is *do not train*; ship the system.

### 6.3 Hypotheses (each with metric, baseline, kill criterion)

| ID | Hypothesis | Primary metric | Comparison | Kill / stop criterion |
|---|---|---|---|---|
| H1 | The system (B2) reduces unsupported claims vs the base (B0) | unsupported-claim rate via Truth Fabric claim verification + human audit of a sample | B2 vs B0, B1 | No reduction ≥ pre-registered MDE → the Truth Fabric is not a differentiator on this task class |
| H2 | Tuning improves **calibrated abstention**: abstains when evidence is insufficient, answers when sufficient | AUROC of confidence vs correctness; abstention precision/recall; expected calibration error | T1 vs B1, T2 vs B2 | No gain → drop calibration data as a training objective |
| H3 | Tuning improves **format/structure adherence** (JSON schema, citation markers `[D#]`, tool-call grammar) | exact-validity rate | T1 vs B1 | Expected to succeed (the smoke failures were format failures); if not, the base/template is wrong |
| H4 | Tuning improves **authority-boundary behavior** (propose-not-execute, ask-before-destructive) with **zero** tolerated regressions | zero-tolerance counts in categories 14/15; refusal over/under-rate | T2 vs B2 | Any zero-tolerance violation blocks promotion |
| H5 | Tuning improves **tool-plan reliability** (correct tool, correct args, no fabricated completion) | plan-validity, fabricated-completion rate (category 10) | T2 vs B2 | Same |
| H6 | Cost: a small tuned model + system reaches a quality bar at lower cost per answer than the reference | cost per correct answer at fixed quality | T2 vs R | Not cheaper → drop the cost claim |
| H7 | Safety: jailbreak block rate reaches the tier threshold without raising over-refusal | strict block rate (≥92 for core tier) and over-refusal on benign twins | T1 vs B1 | Novus today: 70%; do not retrain without a failure analysis (§6.4) |
| H8 | Domain competence (business/engineering/legal) improves | `domain_eval` (≥75 for core tier) | T1 vs B1 | Novus today: 37.5% across all three domains evenly, which suggests a capacity/data-quantity issue, not a narrow bug |

Non-claims: no hypothesis asserts "smarter than", ASI, or universal competence (Doctrine Lock; Mariana eval is design-only and explicitly not part of foundation selection).

### 6.4 What the Novus result already tells us (use before spending anything)

Domain accuracy of 36–39% across three domains with only 65 training examples is the expected outcome of a tiny SFT mix; it is not evidence that the *architecture* cannot reach 75%. Before any retraining:
(a) per-probe error taxonomy (knowledge gap vs reasoning vs format vs refusal), (b) run B0/B1/B2 on the same 24 probes to learn how much of the 37.5% is the base, the prompt, or the tuning, (c) only then
decide whether data scale, base choice, or the *system* is the lever. The `NOVUS_PROMOTION_DECISION.md` explicitly records "no retraining until the owner decides".

### 6.5 Competitor and reference comparison (design)

Reference runs are **context, not selection inputs**, and are bound by `GENESIS_FRONTIER_*` documents: terms-checked access, no ToS-violating benchmarking, owner-funded, holdout never sent to a third-party provider that retains prompts
(a provider that logs prompts would compromise the private set; the access matrix records which do). Where a reference cannot be run lawfully, it is marked `NOT_EVALUATED`, never estimated.

### 6.6 Statistical design (computed in this pass)

Paired binary outcomes, two-sided α = 0.05, power 0.80, discordant-pair rate p_d (fraction of items where exactly one arm is correct):

| Target effect d | n needed (p_d=0.10) | (p_d=0.20) | (p_d=0.30) |
|---|---|---|---|
| 3 pts | 870 | 1,742 | 2,614 |
| 5 pts | 312 | 626 | 940 |
| 8 pts | 120 | 243 | 366 |
| 10 pts | 76 | 155 | 233 |

Minimum detectable effect for a fixed n (p_d=0.20): n=40 → 19.2 pts; n=80 → 13.8; n=100 → 12.4; n=120 → 11.3; **n=420 → 6.1**; n=1000 → 4.0. With 8 primary comparisons and Bonferroni (α=0.00625) a 5-point effect needs ≈1,020 items.

Consequences for the plan: (1) the existing 420-item workload (strict format 120, JSON 80, reasoning 100, coding 80, long-context 40) can detect only ≈6 pts overall and **≈11–19 pts per category**, so it is adequate for a *go/no-go screen* between very different candidates but **not** for claiming small advantages; (2) the qualification-grade private set should target **≥1,000 items** for the headline categories, or the claim must be restricted to effects ≥10 pts; (3) pre-register a **small set of primary endpoints (≤4)** and report the rest as exploratory; (4) use paired bootstrap (≥10,000 resamples) and report effect sizes with CIs; (5) set material-regression thresholds from observed baseline run-to-run variance (`GENESIS_PRETRAINING_QUALIFICATION.md` procedure) **before** any candidate result.

### 6.7 Data strategy that can plausibly move the metrics

* Quality over scale first: executable-verified and schema-verified targets, rejected-sample (negative) pairs for DPO, premise-correction and evidence-insufficiency items, authority-boundary traces. Target a **pilot of ~5M tokens** (decision package) then scale only if the pilot shows a held-out gain.
* Diversity gates: cap near-duplicate rate (≤5% pairs at Jaccard ≥0.85; today 29% in Genesis v1) and template concentration.
* Teacher use: only teachers whose output terms permit training a competing model, each with a per-source terms record (DATA-1); prefer *programmatic/verifiable* generation (sandbox-checked code, schema-checked JSON, claim-checked answers) over opaque distillation.
* Replay: keep a safety/authority replay slice in every mixture (the Novus sequential-training regression: jailbreak block fell 20%→0% when the safety slice was dropped).
* Continued pretraining is **out of scope** for the first run.

### 6.8 Ablations and controls to pre-register

No-RAG vs RAG; with/without Truth Fabric verification; adapter rank sweep (small, fixed grid); data-slice ablations (calibration only / format only / safety only); decoding settings fixed per arm; seed repeats (≥3) to measure variance; a *shuffled-label* control and a *no-op adapter* control to bound the evaluation's false-positive rate.

## 7. Dataset provenance blueprint

1. **Inventory completeness**: every training/adaptation source declared in the signed inventory (done in part: `attested_complete: false`).
2. **Per-record lineage**: source id, license/terms id, generator (human / model id+revision / program), creation code SHA, digest. (`orca/registry/dataset_manifest.py` supplies the schema; DATA-1 binds it to the creation digest.)
3. **Separation of duties**: generator identity ≠ runner identity ≠ custodian (`CORPUS_GENERATOR_REGISTRY.json` currently *empty*; `operational_authorization_boundary` implemented).
4. **Contamination**: lexical + local semantic engine against all public SFT files (`PUBLIC_SFT_DATASET_CLASSIFICATION.json` marks them `may_be_qualification_evidence: false`), canary strings, holdout fingerprints, no item-level leakage (DATA-2).
5. **Custody**: independent re-hash by a custodian who is not the creator (DATA-5).
6. **Data card** (DATA-4) published only after DATA-1/2/5 are accepted; `QUAL-4` keeps holdout out of marketing.

## 8. Evidence-based acceptance criteria (proposed; frozen only via QUAL-3 + independent audit)

**Gate set for "pre-training foundation qualified" (necessary, not sufficient for training):**

| Gate | Criterion | Evidence artifact | Independent party |
|---|---|---|---|
| Q-ARCH | G1 review filed; G3 merged-SHA review + main push CI | review file; run id | architecture reviewer ≠ RSE-ARCH-1.2 author |
| Q-SEC | #24/#32 (+#30/#31/#35) reviewed; acceptance ledger records signed per-row evidence | ledger entries | security reviewer ≠ implementer |
| Q-DATA | DATA-1,2,3,5 accepted; provenance manifest covers 100% of records; 0 unlicensed sources; near-dup rate ≤ 5%; 0 exact/near overlaps with V2 | manifests, scan reports | custodian ≠ creator |
| Q-EVAL | V2 frozen: preregistration signed, corpus generated and custody-verified, vault in a real private store, all `freeze_prerequisites` true | status JSON + signatures | independent audit approval |
| Q-FOUND | MODEL-1 selected by the **pre-registered rule** from the frozen eval; license gate K satisfied; MODEL-2R scope recorded; MODEL-2C resolved or declared "no commercial release" | selection record | founder + reviewer |
| Q-INFRA | TRAIN-1/2, SUP-1 (two matching builds), C39, G12 accepted; spend-cap refusal test passes; kill switch tested | logs, digests | second builder |
| Q-AUTH | AUTH-1 budget record; FINAL-1 worksheet recomputed independently | worksheet | independent recomputation |

**Gate set for "a trained checkpoint is an advantage" (post-run, never before):**
* Primary endpoint(s) pre-registered (≤4); **T2 − B2 ≥ MDE with 95% paired-bootstrap CI excluding 0** on the frozen private set; all other categories within the pre-set non-regression margin;
* zero tolerated events in categories 10, 14, 15, 17 (fabricated completion; self-authorized or fabricated approvals; instruction override; presence-mode authority);
* tier thresholds met on the existing governance bars (`PERSONA_CLAIM_THRESHOLDS`) before any lifecycle promotion; promotion only via `ModelRegistry.promote()` (`PROMOTABLE`), public serving only with a signed grant (PR #31);
* result replicated on ≥3 seeds and reproduced by a second party from the reproducibility manifest.

## 9. Prioritized work plan

**Rule: nothing below starts a protected operation. Items marked ✅ can proceed now with zero spend, no GPU, no keys, no corpus generation. Items marked 🔒 need the named founder act or external party.**

| Pri | Work item | Rows addressed | Owner role | Needs |
|---|---|---|---|---|
| **P0-1** | Obtain independent reviews of the security chain: #23 (Audit #008), #24, #32, #30, #31, #35 | G3, APP-1/2, G-1…G-3 | Antigravity / independent reviewer | 🔒 reviewer named by founder |
| **P0-2** | Name G1 reviewer; supply R65 source text; decide DEC-K | G1, R65, DEC-K | Founder | 🔒 |
| **P0-3** | Retire or freeze the 14 off-host training notebooks so no ungated training path exists | G-2 | Claude ✅ (repo side) + founder (off-host) | ✅/🔒 |
| **P1-1** | Novus failure analysis on existing artifacts only (error taxonomy, B0/B1/B2 on the 24 domain probes via local CPU Ollama if available) | C2, §6.4 | Claude ✅ | no GPU, no spend |
| **P1-2** | Build the V2-compatible **item-authoring pipeline** (public-safe templates only; private items are generated later under G8) and the power-analysis tool (§6.6) as tested code | F4, F9 | Claude ✅ | none |
| **P1-3** | TRAIN-1/TRAIN-2: hash-locked train extra and a *synthetic* dry-run harness that proves every lock stays false (no real model, no GPU) | H1, H2 | Claude ✅ | review |
| **P1-4** | Teacher-terms register: one record per teacher/source, blocking ingestion without it | E3, DATA-1 | Claude ✅ + counsel 🔒 | legal reading |
| **P1-5** | Diversity/near-dup gates in the dataset builder with failing-before tests | E2 | Claude ✅ | none |
| **P2-1** | Founder decisions D1–D8 (§12) | many | Founder | 🔒 |
| **P2-2** | Private vault: real private store, real secret, owner vault procedure executed | F3 | Founder 🔒 | purchase/provisioning |
| **P2-3** | G8 corpus-generation grant → V2 corpus generation → custody → freeze | F4, E4, DATA-1/2/3/5 | Founder → generator ≠ runner → custodian | 🔒 sequential |
| **P2-4** | Hardware purchase decision and chain (G4→G5→C22…C38) | WS-B | Founder 🔒 | the long pole |
| **P3-1** | Capability screen of the three finalists (420-item, ≈USD 6–9; 1.5× contingency) and 5M-token format pilots | D4 | Claude/runner | 🔒 funding + V2 freeze + sandbox authorization |
| **P3-2** | Foundation selection by the pre-registered rule | D6, MODEL-1 | Founder 🔒 | P3-1 |
| **P3-3** | Qualification-grade private set (≥1,000 headline items), thresholds frozen (QUAL-3) | F9 | Claude drafts, auditor reviews | after P1-2 |
| **P4** | FINAL-1 recomputation → FINAL-2 → EXEC-1 | G-7 | independent recomputer, founder | all above |

**Calendar reality.** The Claude Cloud resource expires on **2026-11-05**. Everything marked ✅ fits inside that window; the 🔒 items (reviewers, vault, hardware, corpus grant) are decided by the founder's schedule, not by engineering effort, and the pre-training denominator cannot reach FINAL-1 before the hardware chain exists. Plan for a **hand-off package** (this blueprint, the register, runbooks, tests) that lets another engineer continue after the expiry.

## 10. Exact blockers (by owner)

**Founder (explicit acts only the founder can perform):** G1 reviewer naming; R65 source text; DEC-K; G4 purchase; G5 provisioning/key ceremony; G8 corpus-generation grant; QUAL-1 runner authorization; AUTH-1 budget record; MODEL-2R scope; MODEL-1 selection; MODEL-2C commercial decision; evidence-budget funding for the capability screen (headroom above reserve ≈ USD 3.46 vs. estimated USD 6.15–9.28); real vault/private store; reviewer key enrolment; FINAL-2; EXEC-1.
**External independent parties:** architecture reviewer (G1); code reviewer for RSE software (G3) and for the application/security PRs (APP-1/2, #23–#36); chamber-design reviewer (G10); custodian (DATA-5); independent recomputer (FINAL-1); second builder (SUP-1/C39); legal reader of license and teacher terms.
**Technical, no founder act needed:** TRAIN-1/2; near-dup and diversity gates; off-host notebook retirement (repo side); item-authoring and power tooling; Postgres execution of the new auth SQL.
**Licensing:** the current canonical base is non-commercial; a commercial release from it is impossible without a grant.
**Known unfixed engineering risks relevant to training:** audit-tail truncation (strict xfail in PR #32); Postgres migration SQL unexecuted; G-022 8-char storage keys.

## 11. Independent audit requirements

Each audit must be performed by a party who did not author or implement the artifact, must name the exact SHA, must list the tests/commands the auditor ran, and must be recorded through the acceptance engine with a detached signature (not by editing a status cell).

| Audit | Scope | Artifacts to provide | Pass condition |
|---|---|---|---|
| **AU-1 Architecture** | RSE-ARCH-1.2 vs Manifest V3 (G1) | freeze docs, attack report `RSE_03_ATTACK_REPORT.md` | filed review, no author overlap |
| **AU-2 RSE software** | PR #8 (and #9–#18) | head SHAs, CI run ids | G3 + row-level C01…C21 verdicts |
| **AU-3 Training authorization** | `orca/train/authorization.py` (+#32), every entry point in `TRAINING_AUTHORIZATION_ASSURANCE.md` | assurance doc, 24 adversarial tests, before/after logs | no bypass; off-host notebooks addressed |
| **AU-4 Application security** | #23, #30, #31, #35 | `G006_TENANT_ISOLATION_REPORT.md`, repro scripts, residual-risk lists | Audit #008 + findings closed |
| **AU-5 Evaluation integrity** | V2 design, ledger, vault, sandbox, scanner, preregistration | `GENESIS_CAPABILITY_EVAL_V2_DESIGN.md`, status JSON, ledger deployment record | all `freeze_prerequisites` true; holdout never exposed (F1 lesson) |
| **AU-6 Data provenance** | corpus, manifests, teacher terms | inventory, DATA-1 manifest | 100% records licensed and traceable; custodian re-hash matches |
| **AU-7 Reproducibility** | training image and lock | two independent build reports | digests match (C39) |
| **AU-8 Recomputation** | FINAL-1 worksheet | all rows + evidence keys | independent recompute equals the claimed set |
| **AU-9 Statistics** | preregistration and analysis plan | §6.6 tooling, preregistered endpoints | endpoints ≤4, power adequate, thresholds frozen pre-result |

## 12. Founder decisions required (none is assumed)

1. Name the independent reviewers (architecture, code, custody, recomputation) — or state that the review path stays closed.
2. Supply the R65 source text; confirm DEC-K (class K stays deferred, C27 stays unmet).
3. Decide the hardware purchase path (G4) or confirm training waits for it.
4. Decide the commercial posture: research-only first run (MODEL-2R) and either a commercial-grant route, an Apache/MIT-licensed base, or "no commercial release from this base" (MODEL-2C).
5. Fund (or decline) the ≈USD 6–9 capability screen and set the cap that the environment must enforce.
6. Approve the vault/private-store activation and the G8 corpus-generation grant (separately).
7. Approve the training-vs-system policy in §6.2: *no training unless T2 beats B2 on the frozen metric.*
8. Decide the fate of the 14 off-host training notebooks and of teacher-output sources whose terms are unreviewed.

## 13. What this blueprint does not establish

It does not establish that any model is better than any other, that any listed external fact is current, that any gate is met, or that ORNEUR will outperform any competitor. It does not authorize any
protected operation. Every "VERIFIED-HERE" is an author's reading and a test run, subject to the independent audits above.

## Appendix A — Evidence index

* Register and graph: `docs/orneur/ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md`, `docs/orneur/acceptance/register_graph.json`, `scripts/acceptance/validate_register_graph.py`, `scripts/acceptance/acceptance_engine.py`.
* Authorization state: `docs/orneur/authorization/{TRAINING_AUTHORIZATION,CORPUS_GENERATION_AUTHORIZATION,MODEL_EVAL_AUTHORIZATION}.json` (all `NOT_AUTHORIZED`), `QUALIFICATION_RUNNER_REGISTRY.json` (`REGISTERED_NOT_AUTHORIZED`), `AUTHORITY_REGISTRY.json`, `REVIEWER_REGISTRY.json` (0 keys).
* Models: `orca/registry/model_spec.py`, `docs/orneur/phase-0/{MODEL_TRAINING_STATUS,GENESIS_MODEL_IDENTITY,GENESIS_DATASET_BASELINE,NOVUS_FRESH_EVALUATION}.md`, `docs/orneur/phase-1/{MODEL_LIFECYCLE,NOVUS_PROMOTION_DECISION,GENESIS_NOVUS_AETERNUM_STATUS}.md`.
* Foundation: `docs/orneur/phase-21/GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.{md,json}`, `…SHORTLIST_2026.md`, `…STAGE0_LICENSE_MATRIX.md`, `…TEACHER_STUDENT_STRATEGY.md`, `…PRETRAINING_QUALIFICATION.md`, `…BASELINE_RESULTS.md`, control-runtime manifests.
* Evaluation: `docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json`, `…V2_STATUS.json`, `…V2_DESIGN.md`, `…V2_PREREGISTRATION_DRAFT.json`, `…V2_PRE_CORPUS_CLOSURE_MANIFEST.json`, `…EVAL_CONTAMINATION_REPORT.md`, `…JUDGE_PROTOCOL_SPEC.md`.
* Data: `…TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json`, `…PUBLIC_SFT_DATASET_CLASSIFICATION.json`, `…DATASET_V3.md`.
* Training gates: `orca/train/authorization.py`, `docs/orneur/authorization/TRAINING_AUTHORIZATION_DESIGN.md`; PR #32 `TRAINING_AUTHORIZATION_ASSURANCE.md`.
* Product/system: `docs/orneur/status/ORNEUR_DEVELOPMENT_REGISTER.md`, `…/SPRINT2_CUSTOMER_CORRECTNESS.md`, `…/G006_TENANT_ISOLATION_REPORT.md`.
* Doctrine: `docs/orneur/phase-21/ORNEUR_DOCTRINE_LOCK.md`, `docs/orneur/intelligence/*`.

## Appendix B — Commands run in this pass (read-only / local)

```
python3 scripts/acceptance/validate_register_graph.py --check
  -> pretraining=95 numerator=0 application=3 execution=2 post=1
pytest tests/test_registry_model_spec.py tests/test_training_authorization*.py tests/test_acceptance_engine*.py
  -> 145 passed
git diff --stat dfa9188 HEAD -- orca/rse docs/orneur/phase-21/rse docs/orneur/acceptance   (empty)
power analysis: closed-form paired-binary sample size / MDE (tables in §6.6)
```
No model was loaded, no GPU or network inference used, no key touched, no corpus or protected holdout read, no training or evaluation run.
