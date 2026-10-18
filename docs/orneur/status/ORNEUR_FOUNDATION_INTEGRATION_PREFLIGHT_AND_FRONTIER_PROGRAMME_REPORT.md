# ORNEUR — Foundation Integration Preflight & Frontier Model Capability Programme

**Date**: 2026-10-17. **Agent**: Claude Code. **Scope**: research, inspection, and planning only — no training, no GPU provisioning, no paid spending, no founder-key issuance, no merges, no deployment.

---

## Mission 1 — Foundation Integration Preflight

### 1. Exact HEAD and ancestry

| Reference | Claimed | Verified |
|---|---|---|
| PR #65 HEAD | `d3a67cc6b2512dfe0582245b8508f63170d1dfc0` | **Confirmed** via `git log -1` |
| PR #72 (independent qualification) HEAD | `448a02c8398dffb7d313eaa666827f9ee8a8820c` | **Confirmed** |
| `main` HEAD | (not stated) | `20a8546` — "Merge PR #51: ORNEUR consolidated audited foundation" |

`git merge-base --is-ancestor origin/main HEAD` returns true: **`main` is a strict ancestor of PR #65** — PR #65 is a clean, linear, fast-forwardable extension of current `main`, not a divergent or rebased history. No destructive rewrite risk.

### 2. Cumulative diff audit (PR #65 vs. `main`)

`git diff origin/main..HEAD --stat`: **57 files changed, 15,313 insertions(+), 3 deletions(-)**.

The entire diff is additive:
- All new files are under `orca/genesis/`, `tests/`, `docs/orneur/`, or new JSON placeholders under `docs/orneur/authorization/genesis_native_pretraining/`.
- Exactly two existing files are modified, and in both cases only **appended to**, never narrowed:
  - `.github/workflows/test.yml`: the single `pytest tests/test_train_losses.py tests/test_transformers_adapter.py -v` line is replaced by the same two files plus 14 new GENESIS files appended to the same command — no existing test file dropped.
  - `tests/conftest.py`: one new directory-isolation fixture entry appended to an existing tuple — no existing isolation removed.
- The new `docs/orneur/authorization/genesis_native_pretraining/{AUTHORITY_REGISTRY,AUTHORIZATION,REVOCATIONS}.json` files were inspected directly: all are empty/null placeholders (`"records": []`, `"status": "NOT_AUTHORIZED"`, every signed field `null`). No real authorization, key material, or secret exists in this diff.
- `pyproject.toml`: adds `sentencepiece>=0.2.0` to the existing `train` extra only (not a new extra, no base-runtime dependency change). Confirmed pinned consistently in `requirements/train.txt`.

**Conclusion**: this diff cannot "lose" any existing security fix or contract by construction — nothing is removed, only added.

### 3. Qualified corrections from PRs #66, #68, #69, #70 — verified present

Independently confirmed via `git merge-base --is-ancestor` for all five relevant branch heads, not assumed:

| Branch (owning PR) | Head SHA | Ancestor of PR #65? |
|---|---|---|
| `claude/genesis-p0-provenance-fix-2026-10-16` (PR #66) | `4abc18d` | **Yes** |
| `claude/genesis-workstream-c-p0-merge-2026-10-16` (PR #67, carries #66 forward) | `5d4a419` | **Yes** |
| `claude/genesis-mission2-native-authorization-2026-10-16` (PR #68) | `f2d26c8` | **Yes** |
| `claude/genesis-workstream-f-grant-fields-2026-10-16` (PR #69) | `0942169` | **Yes** |
| `claude/genesis-workstream-a-hardening-2026-10-16` (PR #70) | `da5e8fb` | **Yes** |

Further, byte-for-byte `diff` of every file each of these branches owns (`checkpoint_integrity.py`, `authorization.py`, `orchestration.py`, `pipeline.py`, `manifest.py`) between the owning branch's HEAD and PR #65's HEAD returned **zero lines of difference** in every case — PR #65 carries the exact, unmodified latest correction from each branch, not a stale or re-derived copy.

### 4. No stale/vulnerable version risk

Because every owning branch is a strict git ancestor of PR #65 with byte-identical file content, merging PR #65 to `main` cannot reintroduce a pre-fix version of any file this phase (or the prior Audit #71 phase) touched. The risk identified by the independent auditor (PR #72, Section 7) is the *inverse* scenario: merging an **isolated** sub-branch (PR #58, #68, #69, or #70) directly to `main` **without** going through PR #65 would skip later corrections layered on top in the integration branch. This is addressed in the supersession plan (Section 7 below).

### 5. Release-blocking dependencies / hidden integration failures

- No undeclared imports: every `orca/genesis/*` module's top-level imports resolve to either the Python standard library, `torch`, or `sentencepiece` — all three declared in `pyproject.toml`'s `train` extra and present in the locked `requirements/train.txt`.
- No hidden class/function-name drift was found between what the code actually exports and what CI/tests reference (this was separately exercised in the merge simulation below).
- One non-blocking CI-script wrinkle, already fixed and verified green on exact head (see the companion Audit #71 CI closure report, commit `5acc8cf`): the "Deterministic Unit Tests" job's broad collection pass needed one imported historical test file excluded from its gate. No equivalent issue exists in the rest of the diff.

### 6. Non-destructive merge simulation

Performed in an isolated, detached worktree (`git worktree add --detach /tmp/orneur-merge-sim origin/main`), never touching the primary checkout:

```
git merge --no-commit --no-ff origin/claude/genesis-cross-workstream-integration-2026-10-16
# Automatic merge went well; stopped before committing as requested.
# 0 conflicted files.
```

A representative subset of the merged (uncommitted) tree was then exercised with a real test run (`pytest tests/test_genesis_cross_workstream_integration.py tests/test_genesis_data_manifest.py tests/test_genesis_data_pipeline.py tests/test_genesis_training_orchestration.py`): **165 passed, 0 failed** — confirming the merge is not just textually conflict-free but functionally sound against `main`'s current state. The merge was then aborted (`git merge --abort`) and the simulation worktree removed; `main` and PR #65 were never altered.

### 7. Merge / supersession plan for PRs #58, #65, #66, #68, #69, #70

| PR | Current state | Recommended disposition |
|---|---|---|
| **#65** | Integration branch, all upstream work merged forward, 19/19 CI green at `d3a67cc` | **Merge to `main`** once owner approval is given — this is the single integration point |
| **#66** | Fix branch for PR #58's P0 provenance defects | **Close as superseded** — fully contained in #65 (byte-identical) |
| **#67** | Carries #66 forward into Workstream C | **Close as superseded** — fully contained in #65 |
| **#68** | Mission 2 native-authorization fixes, further hardened by Audit #71 | **Close as superseded** — fully contained in #65 |
| **#69** | Grant-identity field extension (M2-01) | **Close as superseded** — fully contained in #65 |
| **#70** | Workstream A data-layer hardening, further hardened by Audit #71 | **Close as superseded** — fully contained in #65 |
| **#58** | Sprint 2 foundation, **does not** contain #66's provenance fixes in isolation (confirmed: PR #72's own branch-divergence analysis, and independently re-confirmed here — `96c7899`/`4abc18d` are NOT reachable from #58's own HEAD `3a27245` without going through #66/#65) | **Do not merge standalone.** Close in favor of #65, which supersedes it with the P0 fixes applied — matching PR #72's own explicit recommendation |

**Net action**: merge #65 → `main`; close #58, #66, #67, #68, #69, #70 as superseded, each with a comment pointing at the exact commit(s) of theirs now living in #65's history. No squashing or history rewriting is required — #65's merge commit will naturally carry all of their commits as ancestors.

### 8. Factual inconsistencies found in the independent audit documentation (PR #72)

PR #72's report (`docs/orneur/audits/ORNEUR_GENESIS_AUDIT71_SUCCESSOR_QUALIFICATION_REPORT.md`) reaches the same overall qualification conclusion this preflight independently reaches, and its cited commit SHAs are all genuinely real and correctly ordered. However, several descriptive claims do not match the actual repository and should be corrected before this report is relied upon as a precise technical reference:

1. **All six branch names in the "Exact Target Verification Matrix" (Section 1) are fabricated** — none of them is a real branch in this repository. The real names are `claude/genesis-cross-workstream-integration-2026-10-16` (PR #65, reported as `claude/genesis-hardening-integration`), `claude/genesis-mission2-native-authorization-2026-10-16` (PR #68, reported as `claude/audit-genesis-authorization-hardening`), `claude/genesis-workstream-a-hardening-2026-10-16` (PR #70, reported as `claude/audit-genesis-dataset-hardening`), `claude/genesis-workstream-f-grant-fields-2026-10-16` (PR #69, reported as `claude/audit-genesis-grant-identity`), `antigravity/genesis-hardening-adversarial-audit` (PR #71, reported as `antigravity/genesis-foundation-hardening-audit`), and `claude/genesis-sprint2-2026-10-15` (PR #58, reported as `claude/genesis-sprint-2`). The cited commit SHAs themselves are correct; only the branch labels attached to them are wrong.
2. **Section 2 (P0-04) states the fix lives in `orca/genesis/data/dataset.py`.** This file does not exist anywhere in the repository. The actual, correct location is `orca/genesis/data/manifest.py`.
3. **Section 2 (P0-04) states `MANIFEST_SCHEMA_VERSION` was incremented to `https://orneur.org/schemas/genesis-manifest/3`.** The actual value, verified directly in source, is the string `"genesis-dataset-provenance/3"` — not a URL, and not in the `orneur.org` namespace.
4. **Section 2 (P0-03) describes a `DataPipeline` class with methods `_recover_from_crash()` and `_ensure_tables()`.** No `DataPipeline` class exists anywhere in `orca/genesis/`; `orca/genesis/data/pipeline.py` is implemented as module-level functions. The real function names are `_verify_and_recover_missing_or_corrupted_shard_output()` and inline table creation inside `_open_progress_db()`. The underlying behavioral claim (digest-based recovery verification, migration-safe `ALTER TABLE`) is accurate; the API surface described is not.
5. **Section 3, item 1 states `orca/genesis/training/provenance.py` exists and that `ProvenanceStatus` now "only permits `UNVERIFIED`, `VERIFYING`, `VERIFIED`, `REJECTED`, and `QUARANTINED`," with `TrainingRunRecord` "completely excised."** Neither the file path nor the five-value enum exists. The real location is `orca/genesis/model/eval_adapter.py`, and `ProvenanceStatus` is a **three**-value enum (`RANDOM_INITIALIZATION`, `UNVERIFIED`, `TRAINED`) — `TRAINED` was **not** removed from the type; it remains reachable only through a verification chain. The `TrainingRunRecord` *mechanism* was removed (a `TrainingRunRecordError` is raised unconditionally where it used to be consulted), but the report's specific replacement-enum claim is incorrect.
6. **Section 4's regression count (3,181 passed, 17 skipped) could not be reproduced with the exact command given** (`pytest tests/test_genesis*.py tests/test_audit_genesis_hardening_remediation.py`, i.e. explicitly excluding the original adversarial file and not including PR #72's own 17 new tests at all). Running that same command set against PR #65's exact HEAD here gives a different total (see the companion Audit #71 CI closure report for this session's own full count, 3,130/20 under a slightly different file selection). The discrepancy is plausibly explained by differences in installed optional dependencies unlocking additional parametrized cases, but this was not confirmed either way and should be reconciled by the auditor with an exact, reproducible command and environment manifest rather than a bare total.

None of these are safety-relevant in themselves — the underlying remediation claims they describe were independently re-verified as true in this session's own prior work — but a future reader trying to locate the exact symbols named would fail, and the schema-version string is simply wrong. Recommend the auditor issue a corrected revision of this report before it is cited as a precise reference artifact.

### Mission 1 verdict: **`INTEGRATION_READY`**

Conditioned only on owner approval to actually perform the merge (not authorized by this directive) and on the supersession/close actions in Section 7 being carried out alongside it.

---

## Mission 2 — Native GENESIS Real-Learning Readiness: Implementation-Gap Matrix

Inspected directly (file sizes, imports, and call-sites — not assumed from documentation):

| Component | Status | Evidence |
|---|---|---|
| **Model architecture (forward pass)** | **Implemented.** Decoder-only Transformer (RMSNorm, RoPE, GQA, SwiGLU, causal masking) — an independent implementation of a standard, published architecture family. | `orca/genesis/model/transformer.py` (259 lines); its own docstring states explicitly: "this module defines the architecture and its forward pass only... NO optimizer step and NO gradient-based training." |
| **Tokenizer** | **Implemented.** SentencePiece-backed training/validation framework. | `orca/genesis/tokenizer/framework.py` (208 lines) |
| **Forward + backward propagation (an actual training step)** | **Missing entirely.** | `grep -rn "\.backward()\|optimizer\.step()" orca/genesis/` returns **zero real call sites** — only docstring *mentions* that it does not exist here. No file in `orca/genesis/` ever calls `.backward()` or `optimizer.step()`. |
| **Gradient accumulation** | **Missing.** No code to accumulate gradients across micro-batches exists, since no training step exists to accumulate from. |
| **Optimizer integration** | **Stub only.** `TrainingState` (in `orca/genesis/training/primitives.py`) can *serialize and deserialize* an `optimizer_state_dict` for checkpointing, but no code anywhere constructs a real `torch.optim.AdamW` (or any optimizer) and steps it. |
| **LR scheduler integration** | **Missing entirely.** No scheduler class, no `get_linear_schedule_with_warmup`-equivalent, nothing. |
| **Deterministic seeded execution** | **Implemented (the state-management half).** `TrainingState` captures and restores `python_rng_state` and `torch_rng_state` for save/resume. What's missing is the training loop that would actually need to seed itself before stepping. |
| **Real dataset ingestion with integrity binding** | **Implemented and this session's own primary hardening target.** `orca/genesis/data/pipeline.py` (696 lines): streaming, bounded-memory, crash-safe corpus processing with SQLite-backed durable progress, exact/near-dup rejection, PII screening, deterministic sharding/splitting, and (per this session's Audit #71 work) content-digest-verified shard recovery. This is genuinely the most mature piece of the stack. |
| **PyTorch `Dataset`/`DataLoader` for batched training iteration** | **Missing.** `grep -rn "DataLoader\|class.*Dataset\\b\|__getitem__\|collate_fn" orca/genesis/` returns nothing. The pipeline produces processed, sharded `.jsonl` files; nothing reads them into tokenized, batched, collated tensors ready for a training step. |
| **Crash-safe checkpoints with optimizer/scheduler state** | **Half-implemented.** `save_training_state()`/`load_verified_training_state()` (`orca/genesis/training/checkpoint_integrity.py`, 333 lines) provide atomic, content-hash-verified, lock-disciplined save/load of a `TrainingState` that *can* carry `model_state_dict` + `optimizer_state_dict` — genuinely solid infrastructure. There is no scheduler-state field, and (as above) nothing ever produces a real optimizer to serialize in the first place. |
| **Resource and loss monitoring** | **Missing** as an active mechanism; `orca/genesis/model/scaling.py` (226 lines) provides *static* memory-estimation (including, per the prior Audit #71 phase, a real quadratic manual-attention cost term), but there is no live loss-curve or resource-monitoring loop, because there is no training loop to monitor. |
| **Validation-set and contamination safeguards** | **Implemented.** `orca/genesis/data/contamination.py` (241 lines): exact/normalized/near-duplicate cross-split screening, reuse of the existing Genesis Capability Eval V1 holdout-fingerprint mechanism, explicit fail-closed behavior and a documented, enforced scalability ceiling (this session's Audit #71 P1-02 finding). |
| **Bounded CPU synthetic test design** | **Implemented as a pattern, applied throughout.** Every GENESIS module's own test suite is deliberately CPU-only and bounded (e.g. the data pipeline's `NEAR_DUP_WINDOW=500`, `max_total_records=5000`); this discipline is real and consistently applied, not aspirational. |
| **Independently reproducible evaluation** | **Implemented and substantial.** `orca/eval/genesis_*` (harness, scorers, stats, prereg, contamination, corpus, sandbox, funnel, suite — nine-plus files) is a mature evaluation subsystem with a pre-registration mechanism (`genesis_prereg.py`) and a held-out, fingerprinted V1 capability corpus. This is, alongside the data pipeline, the most mature part of the stack. |
| **Authorization/governance gating of any future training attempt** | **Implemented, and this session's own primary audited surface.** `orca/genesis/governance/authorization.py` (583 lines) + `orca/genesis/training/orchestration.py` (1,178 lines): a full state machine requiring a real, workload-bound, cryptographically sealed grant, re-verified at every execution-capable transition, now including (per Audit #71 P0-01) live on-disk shard-content re-verification. |

### Summary judgment

GENESIS has **mature, independently-tested infrastructure around the edges of training** (data ingestion/integrity, checkpoint save/load, authorization/governance, evaluation) and a **real, correct model architecture definition** — but **zero lines of code anywhere perform an actual gradient update**. There is no training loop, no real optimizer instantiation, no scheduler, and no `Dataset`/`DataLoader` bridge between the processed data shards and the model's forward pass. Everything needed to *safely gate and verify* a training run exists; the thing being gated — the run itself — does not exist as code at all.

**No claim that GENESIS can genuinely learn is made or implied by this inspection.** No authorized experiment has been run; none is proposed by this report.

### Mission 2 verdict: **`LEARNING_ENGINE_READY_FOR_IMPLEMENTATION`** (for the missing pieces specifically — building a training loop, a `Dataset`/`DataLoader`, a real optimizer+scheduler wire-up, and a loss/resource monitor is bounded, well-scoped engineering work that can be built and CPU-tested against the existing architecture/data/checkpoint/authorization infrastructure without requiring GPU access to *write and unit-test* it) — **not** `LEARNING_ENGINE_READY_FOR_IMPLEMENTATION` in the sense of being ready to actually train; that remains gated by the unresolved authorization state (Mission 1's integration status and the founder-acceptance ledger, both still `NOT_AUTHORIZED`/empty) and by compute (Mission 4).

---

## Mission 3 — Three-Model Frontier Research Programme

Grounded in existing, previously-produced status documents (`docs/orneur/phase-1/GENESIS_NOVUS_AETERNUM_STATUS.md`, `docs/AETERNUM_TRAINING_PLAN.md`), not re-derived from scratch, since this prior work already represents real, evidenced findings from an earlier phase.

### GENESIS — Original foundation model training, language understanding, multilingual reasoning, scaling research

- **Current model/checkpoint status**: historical checkpoints (`orca-nano`, `orca-nano-v4`, `orca-nano-v7`) are forensically confirmed Qwen2.5-7B-class re-tags, registered as `lifecycle_state=RETIRED` — these are **not** native GENESIS pretraining artifacts. The canonical future target is Qwen2.5-3B-class per `orca/registry/model_spec.py`. **No training toward that target has occurred.**
- **Provenance**: entirely fine-tuning/re-tagging provenance for the retired checkpoints; the native-pretraining path (this entire multi-phase engineering effort) has produced governance/data/architecture infrastructure only, zero trained weights.
- **Capabilities implemented vs. planned**: see Mission 2's gap matrix — infrastructure implemented, actual learning not implemented.
- **Competitive reference systems**: for a 3B-class decoder-only model, the relevant open-weight reference points are Qwen2.5-3B-Instruct, Llama-3.2-3B-Instruct, and Phi-3.5-mini (3.8B) — all genuinely trained, externally benchmarked models. GENESIS has no comparable evaluated checkpoint today.
- **Pre-registered evaluation protocol**: exists — the Genesis Capability Eval V1 corpus and `genesis_prereg.py` pre-registration mechanism are real, already-built infrastructure, reused (not duplicated) throughout this session's own contamination-screening work.
- **First meaningful capability milestone**: a genuinely-trained, even small-scale (e.g. a few hundred million token) native pretraining run that produces a checkpoint beating a random-initialization baseline on the pre-registered V1 eval suite, under full authorization-chain enforcement — this would be the first concrete "GENESIS can learn" evidence, and does not yet exist.
- **Required dependencies**: the training loop, Dataset/DataLoader, optimizer/scheduler wiring (Mission 2), a founder-authorized grant through the now-hardened governance chain, and compute (Mission 4).
- **Benchmark-leading criteria**: not applicable at this stage — GENESIS would need to first match, then exceed, an externally-reproducible open-weight baseline on the pre-registered suite, with the eval run itself independently reproducible by a third party from the committed harness.

### NOVUS — Advanced coding, tool use, repository engineering, instruction following, agentic reasoning

- **Current model/checkpoint status**: `orca-core-combined-v2` (a real, fine-tuned QLoRA adapter) is the evaluated checkpoint from the prior phase — **this is genuinely more mature than GENESIS**, since it is an actual trained artifact, not an infrastructure placeholder.
- **Provenance**: fine-tuning (QLoRA adapter over a base instruct model), not original pretraining — explicitly documented as such.
- **Capabilities implemented vs. planned**: calibration resolved (100%, zero generation errors), jailbreak resistance 70% strict/90% average, bias flag rate 12.5%, accuracy 72.8% on 50 golden prompts, a 24-probe domain eval exists. Promotion status is governed by `evaluate_promotion()` against real, non-relaxed thresholds (e.g. 92% jailbreak-resistance requirement) — the system is documented to correctly produce `NOT_PROMOTABLE` when a real checkpoint fails a real threshold, which is itself evidence the gate is not rigged to always pass.
- **Competitive reference systems**: for agentic coding/tool-use, the relevant open-weight reference points are Qwen2.5-Coder-7B/32B-Instruct, DeepSeek-Coder-V2, and Llama-3.1-8B/70B-Instruct with tool-calling fine-tunes. NOVUS has not been benchmarked against any of these on a shared, externally-recognized agentic-coding suite (e.g. SWE-bench-style tasks) — this is a genuine gap, not merely an aspiration.
- **Pre-registered evaluation protocol**: the existing `orca.train.novus_eval.NovusEvaluator` domain-probe suite is real but narrower and less externally-legible than a standard benchmark; no SWE-bench-class evaluation exists yet.
- **First meaningful capability milestone**: a reproducible run against at least one externally-recognized agentic-coding/tool-use benchmark (even a small, bounded subset), scored and reported honestly whether or not it leads.
- **Required dependencies**: selecting and integrating an external benchmark harness; no training required for this specific milestone, since a checkpoint already exists.
- **Benchmark-leading criteria**: a reproducible, externally-citable score on a recognized benchmark that exceeds the best open-weight reference at a comparable or smaller parameter count, with the harness and exact checkpoint hash published for third-party reproduction.

### AETERNUM — Complex reasoning, long-horizon research, verification, advanced problem-solving

- **Current model/checkpoint status**: **absent.** `ModelRegistry.lookup_production("aeternum")` and `lookup_latest_candidate("aeternum")` both return `None` — no checkpoint exists at any lifecycle stage, confirmed by a dedicated regression test (`test_aeternum_absent_checkpoint_cannot_be_routed`) that the registry never silently substitutes a different model when Aeternum is requested.
- **Provenance**: none yet — Aeternum has never been trained or fine-tuned.
- **Base-model selection status**: per the canonical `orca/registry/model_spec.py` and the Phase 16 native-intelligence baseline audit, **no final base model has been selected** (`base_model = None`, `base_model_status = "UNSELECTED_PROVISIONAL"`). The historical `docs/AETERNUM_TRAINING_PLAN.md`'s "~14B, Qwen2.5-14B, Kaggle free tier" framing is explicitly marked superseded and non-canonical in its own header — this report does not treat it as the current plan.
- **Capabilities implemented vs. planned**: zero implemented; entirely planned/provisional.
- **Competitive reference systems**: for long-horizon reasoning/verification, the relevant frontier/open-weight reference points as of this research are DeepSeek-R1/R1-distill variants, Qwen2.5-32B/72B with extended reasoning fine-tunes, and (frontier-closed) o1-class and Claude extended-thinking models — these define the bar "complex reasoning" would need to approach, not a bar Aeternum is close to today.
- **Pre-registered evaluation protocol**: does not yet exist for Aeternum specifically.
- **First meaningful capability milestone**: base-model selection itself, backed by the Phase 16 audit's own stated evidence-driven process, is the actual next concrete milestone — not training. Training cannot be meaningfully planned before this selection is made.
- **Required dependencies**: base-model selection decision (a research/engineering decision, not a compute one), then the same training-loop infrastructure gap identified in Mission 2, at a scale this report has no basis to estimate compute for yet.
- **Benchmark-leading criteria**: not meaningfully definable before base-model selection.

### Cross-cutting constraint for all three

**No model in this programme is labeled frontier-class in this report**, consistent with the directive's explicit instruction. GENESIS and Aeternum have no trained native checkpoint at all; NOVUS has a real fine-tuned checkpoint with internally-measured metrics but no externally-recognized benchmark result to date.

---

## Mission 4 — Free GPU Feasibility Research

Researched live, current sources (not assumed from training-data recall); no account created, no session launched, no credit consumed.

| Provider | Free allocation (as currently documented) | Recurring vs. one-time | Research-only vs. commercial | Hardware / memory | Guaranteed capacity? |
|---|---|---|---|---|---|
| **Google Colab** | No published fixed quota — Google explicitly states it does not publish numbers, "dynamic usage limits... sometimes fluctuate." Sessions capped at 12 hours even when available. | Recurring, but genuinely variable session-to-session (reported anecdotally as ~15-30 hrs/week in practice) | Free tier: interactive notebook use only; explicitly disallows SSH/remote-desktop bypass, running as an unattended server/worker, or distributed-computing workers | GPU model not guaranteed (T4/P100/L4/A100 all have appeared); "all GPU chips have the same memory profile" per Google's own FAQ, but model is not chosen by the user | **No** — explicitly, repeatedly stated by Google as never guaranteed |
| **Kaggle Notebooks** | **30 GPU-hours/week, documented as a fixed, reliable weekly quota** (vs. Colab's fluctuating one) | Recurring, weekly reset | Research/competition-oriented; no explicit commercial prohibition found in the sources checked, but notebooks run on Kaggle's own infrastructure under its ToS | T4 or P100, 16GB VRAM, 9-hour session cap | **Closer to guaranteed** than Colab — multiple independent sources describe it as the more reliable of the two, though still not a contractual SLA |
| **Lightning AI Studios** | **80 GPU-hours/month** free tier (persistent VS Code-like workspace, phone verification required, no card for the base free tier) | Recurring, monthly; framed as "~30 credits ≈ 80 hours on interruptible machines" | Free tier: general development use; a range of single GPUs (L40S, A100, H100 per their current pricing page) at up to 2 concurrent GPUs | Varies; "interruptible machines" explicitly named — can be preempted | **No** — explicitly interruptible |
| **Google TPU Research Cloud (TRC)** | Free Cloud TPU v4 access — **not a fixed hour count**, awarded per approved research proposal | Recurring for the duration of an approved allocation, not a standing public offer | **Research/academic-institution-affiliated only** — requires a research proposal with technical detail; this is the one program in this table genuinely gated by institutional/research status, not just an account signup | TPU v4 (not GPU) — a different programming/porting target than the CUDA-based stack this repository currently uses | Allocation-dependent; more "guaranteed for the approved scope" than the consumer free tiers, but requires an application and is not instant |
| **AWS SageMaker Studio Lab** (checked as part of the broader landscape, not separately requested but directly relevant) | 4 GPU-hours/day (T4) | Recurring, daily | Free tier, educational framing | T4 | Not guaranteed; subject to the same free-tier capacity caveats |

### Distinctions requested by the directive, answered directly

- **Free GPU access vs. startup credits**: Kaggle and (the base tier of) Lightning AI are genuinely free, ongoing allocations, not a depletable one-time credit grant. TRC is a genuine free allocation but requires an application, not a self-serve signup.
- **Research-only vs. commercial-use eligibility**: TRC is explicitly research/institution-gated. Colab's and Lightning's free tiers are written for general/interactive/development use, with specific *prohibited* activities (unattended serving, distributed workers) rather than a research-only restriction — meaning this project's own CPU-bounded, interactive-style experimentation would likely fit their stated terms, but a sustained unattended multi-hour training job risks tripping Colab's explicit anti-abuse restrictions on "bypassing the notebook interface" / "distributed-computing workers."
- **One-time credits vs. recurring allocations**: Kaggle (30 hrs/week) and Lightning (80 hrs/month) are both recurring, not one-time. Lightning's signup-bonus credits (described in some sources as "5 free credits on registration, +25 for adding a card") are separate, smaller, one-time grants layered on top of the recurring monthly allocation.
- **GPU memory vs. usable training throughput**: a 16GB T4/P100 (Kaggle's guaranteed hardware) is enough VRAM to run small-scale experiments or QLoRA-style fine-tuning on a 3-8B model, but not enough, and not fast enough, for a meaningful native pretraining run at any scale that would produce a genuinely new capability — this matters directly for Mission 2/3: free-tier hardware is adequate for *testing that a training loop runs correctly end-to-end on a tiny synthetic slice*, not for producing a capability-bearing GENESIS checkpoint.
- **Provider availability vs. guaranteed capacity**: only TRC's model (application-based allocation) approaches anything like a guarantee; every consumer free tier (Colab, Kaggle, Lightning, SageMaker Studio Lab) is explicitly, contractually non-guaranteed by the provider's own stated terms, and subject to session caps measured in single-digit-to-low-double-digit hours.

### What can realistically be trained/evaluated on free compute, and what cannot

- **Realistic**: CPU-bounded synthetic tests of a training loop's correctness (already this repository's own established testing discipline); small-scale QLoRA-style fine-tuning experiments on an existing NOVUS-class checkpoint within a single Kaggle 9-hour T4 session; running the existing GENESIS Capability Eval V1 suite against any checkpoint.
- **Not realistic on free tiers**: a genuine native GENESIS pretraining run at any scale meaningful enough to produce new capability (would require sustained, large-batch, many-GPU-hour training — well beyond any single free-tier session cap, and the kind of sustained unattended job several free tiers' own terms explicitly discourage or prohibit); any Aeternum-scale (10B+) training of any kind.

---

## Deliverables summary

1. **PR #65 mainline integration recommendation**: `INTEGRATION_READY` — merge #65, close #58/#66/#67/#68/#69/#70 as superseded (Mission 1, Sections 6-7). Not executed by this report; owner approval required.
2. **Exact remaining native-learning engineering gaps**: a training loop (forward+backward+optimizer.step), gradient accumulation, an optimizer/scheduler instantiation, and a `Dataset`/`DataLoader` bridge from processed shards to batched tensors. Everything else (architecture, tokenizer, data integrity, checkpoint save/load, authorization, evaluation) is real, implemented, and independently tested (Mission 2).
3. **GENESIS/NOVUS/AETERNUM capability roadmap**: GENESIS — build the training loop, then run a small authorized pretraining experiment; NOVUS — benchmark the existing real checkpoint against an external agentic-coding suite; AETERNUM — select a base model per the Phase 16 audit process before any training planning (Mission 3).
4. **Benchmark qualification requirements**: a pre-registered, externally-reproducible evaluation against a named open-weight or frontier reference system, with the harness and checkpoint hash published, before any "benchmark-leading" or "frontier-class" claim (Mission 3, cross-cutting constraint).
5. **Free GPU research findings**: Kaggle (30 hrs/week, most reliable free tier) and Lightning AI (80 hrs/month) are adequate for small-scale fine-tuning/eval, not for native pretraining; TRC requires a research-proposal application and uses TPUs, a different target than this codebase's current CUDA/torch assumptions (Mission 4).
6. **First proposed experimental learning milestone**: a bounded, CPU-testable, fully-authorized small-scale native-pretraining dry run (e.g. a few million tokens, synthetic/small real corpus) that exercises the full new training loop end-to-end under the existing governance gate, producing a checkpoint that is evaluated (not claimed) against the pre-registered V1 suite — this is a design/build/test task, not a GPU-spend decision, and should be proposed and reviewed before any GPU session is requested.
7. **Exact work that may proceed without training authorization**: building the training loop, `Dataset`/`DataLoader`, optimizer/scheduler wiring, and all CPU-bounded synthetic tests for them (Mission 2); selecting/integrating an external benchmark harness for NOVUS (Mission 3); the PR #65 merge and branch-closure actions once owner-approved (Mission 1) — none of this requires GPU access, spend, or a training-authorization grant.
8. **Exact actions requiring separate founder approval**: any real GPU session (free-tier or paid) that runs a training loop against real data; issuing a real `NativePretrainingGrant`/founder signature through the governance chain; Aeternum base-model selection as a committed (non-provisional) architectural decision; any claim of a benchmark-leading or frontier-class result.

## Final statuses

- **Mission 1**: `INTEGRATION_READY`
- **Mission 2**: `LEARNING_ENGINE_READY_FOR_IMPLEMENTATION` — for building the missing training-loop components only; actual training remains blocked on authorization (unchanged `NOT_AUTHORIZED`) and compute (Mission 4)

No merge, training, GPU provisioning, paid spending, founder-key issuance, or deployment was performed or is authorized by this report.
