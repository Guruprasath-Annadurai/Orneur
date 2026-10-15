# GENESIS Native Model Foundation — Sprint 1

Status date: 2026-10-15. Base: `main` at `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`.
Implementation sprint: real, tested, non-training code. No gradient-based
training, no GPU, no spend, no acceptance-count advancement.

## Phase 1 — Audit #015 scientific-assumption corrections

Directly checked: no document named "Audit #015", and no committed GENESIS
model configuration, existed in `main` at the time this section was
first drafted (grepped directly — zero matches for "30M"/"Audit #015"
tied to a model config on `main`). **Correction to that initial finding**:
the actual Audit #015 document exists as a concurrent, not-yet-merged
PR — [#54, "Audit 015: Independent Native-Model Reality Audit"](https://github.com/Guruprasath-Annadurai/Orneur/pull/54),
authored by the founder/independent-auditor account, created around the
same time as this sprint's own work. Fetched and checked directly once
found, rather than left as "does not exist":

1. **Embeddings alone exceeding a stated 30M-parameter budget — the real
   instance, verified with exact numbers.** PR #54's Stage 1 config is
   stated as: `vocab_size=64,000, d_model=512, n_layers=12, n_heads=8,
   n_kv_heads=4, max_seq_len=2,048`, "~30M parameters." Computed directly
   with this sprint's own `GenesisModelConfig` (standard SwiGLU
   `d_ff = 8/3 * d_model` rounded to 256, tied embeddings): **the
   embedding table alone is 32,768,000 parameters — already exceeding the
   stated ~30M total before a single transformer layer is counted.** The
   real total for this exact config is **65,810,944** — roughly **2.2×**
   the stated figure, with the embedding table alone accounting for
   49.8% of the real total. Confirmed this is a `vocab_size`/`d_model`
   mismatch, not a one-off arithmetic slip: solving for the `d_model`
   that genuinely produces ~30M total at `vocab_size=64,000` gives
   `d_model≈296`, not 512 — at `d_model=512`, no choice of layer count
   at this vocab size can reach a genuine 30M total, because the
   embedding table alone already exceeds it. PR #54 should correct
   either the stated parameter count (to ~66M) or the architecture
   (shrink `d_model` to ~300, or `vocab_size` substantially below
   64,000) — this sprint does not pick one on the founder/auditor's
   behalf, only reports the precise, reproducible discrepancy.
   `GenesisModelConfig.total_parameters()` and `.breakdown()`
   (`orca/genesis/model/config.py`) compute every component — including
   the embedding table — from real dimensions, never a hand-entered
   total, which is how this specific discrepancy was caught mechanically
   rather than by manual arithmetic. `from_param_budget()` *solves* for
   dimensions that fit a requested budget and explicitly **raises** if
   the embedding table alone would exceed it, rather than silently
   accepting an inconsistent config. Reproducible:
   `tests/test_genesis_model_architecture.py::test_from_param_budget_rejects_embedding_alone_exceeding_budget`
   (the general case) and the inline computation above (the specific
   Audit #015 instance, using this module directly against PR #54's own
   stated numbers).
2. **Inconsistent model dimensions and total parameter budgets.**
   Same root cause as item 1, same fix — `total_parameters()` is
   derived, never asserted independently of `breakdown()`'s own
   components (test: `test_parameter_count_breakdown_matches_total`),
   and cross-checked against a REAL constructed model's actual parameter
   count, not just internal arithmetic (test:
   `test_parameter_count_matches_actual_constructed_model`). PR #54's
   Stage 3 config (`~300M`, `L=24, d=1024, h=16, kv=8, vocab=64,000,
   ctx=4,096`) was also checked directly: computed total (assuming the
   same standard `d_ff = 8/3 * d_model` convention, since PR #54 does
   not state its own `d_ff` explicitly) is **348,701,696** — about 16%
   over the stated ~300M, with the embedding table a reasonable 18.8% of
   the total. This is a materially smaller, more ambiguous discrepancy
   than Stage 1's (plausibly just a different `d_ff` convention than the
   one assumed here, not clearly the same embedding-dominates-the-budget
   error), reported as "approximately consistent, pending PR #54 stating
   its actual `d_ff`" rather than flagged with Stage 1's confidence.
3. **Unsupported small-model H100 utilization assumptions.** Not
   addressed by code in this sprint — this is a hardware/throughput
   claim, not an architecture question, and no benchmark was run on real
   hardware (none was provisioned, per the sprint's own restrictions).
   Flagged as unresolved: any future compute-planning document should
   cite a measured, reproduced throughput number for the actual model
   size in question, not a general "H100 utilization" assumption.
4. **Tokenizer vocabulary size vs. Indian-language measurement.**
   `orca/genesis/tokenizer/framework.py`'s `recommend_vocab_size()`
   trains throwaway tokenizers at several candidate sizes and reports
   measured per-language fertility — no size is hardcoded as
   universally correct (explicit per Phase 3's own instruction). A real
   example of the underlying trade-off was found directly, not assumed:
   this sprint's own tiny 4-script (Latin + Devanagari + Tamil + Telugu)
   test fixture required 375 unique characters, exceeding an initially
   chosen 300-token vocabulary before any BPE merging could even begin —
   SentencePiece itself rejected the too-small config with a precise
   error, corrected to 500 for the test fixture.
5. **Dataset-size and token-storage assumptions.** Not addressed with
   new code this sprint — no dataset has been assembled (Wave 1 already
   found dataset/legal prerequisites `IMPLEMENTED_UNQUALIFIED` at the
   tooling level, not satisfied at pretraining scale). Any future sizing
   claim should be computed from an actual assembled, provenance-cleared
   corpus, not estimated in advance.
6. **Do Stage 0 optimizer steps constitute prohibited training?**
   Answered structurally, not by argument: `orca/genesis/training/primitives.py`
   contains loss functions, optimizer/scheduler *configuration* objects,
   gradient-clipping math, and checkpoint serialization — **no function
   in this module calls `.backward()` followed by `optimizer.step()`
   against real or synthetic training data in a loop.** The one place a
   real `.backward()` call occurs in this sprint's own test suite
   (`test_clip_grad_norm_reduces_gradient_norm_below_threshold`) exists
   solely to produce a gradient tensor to measure gradient-clipping math
   against, is never followed by an optimizer step, and is not part of
   any loop. There is no "Stage 0" training loop implemented anywhere in
   this sprint. Constructing a model, running a forward pass to check
   shapes, or computing a loss value for a unit test is categorically
   different from training, and this sprint's code performs only the
   former.
7. **The R65/R65-child acceptance-engine contradiction.** See the Phase 6
   package below — this is the substantive item.
8. **Licensing and source-provenance requirements.** Not newly addressed
   — this sprint uses only original, hand-written test fixtures (see
   `tests/test_genesis_tokenizer.py`'s own docstring) and reuses the
   existing, already-tested provenance infrastructure
   (`orca/registry/provenance.py`, `orca/dataquality/`) rather than
   duplicating it. No new corpus was acquired.

## Phase 2 — Native Transformer implementation

`orca/genesis/model/` — architecture version `genesis-arch-v1`. A
standard decoder-only Transformer: causal self-attention with grouped-
query attention (Ainslie et al. 2023), rotary positional embeddings (Su
et al. 2021), RMSNorm (Zhang & Sennrich 2019), SwiGLU (Shazeer 2020),
pre-norm residual placement (Xiong et al. 2020). Every technique is
cited to its published source in the relevant class's docstring and is
an **independent implementation**, not a claimed invention. Includes:
configurable dimensions/parameter counts (`config.py`), correct causal
masking, two selectable attention backends (`"manual"` for direct
reasoning about masking, `"sdpa"` for PyTorch's fused kernel — cross-
checked against each other), a generation-compatible `generate_step()`
interface (explicitly `@torch.no_grad()`), deterministic initialization
(verified bit-for-bit reproducible given a fixed seed), and the
architecture-version string recorded on every config.

## Phase 3 — Tokenizer engineering

`orca/genesis/tokenizer/framework.py` — a SentencePiece BPE training and
validation framework (Kudo & Richardson 2018). Explicit NFC normalization
policy, with SentencePiece's own internal normalization pass disabled
(`normalization_rule_name="identity"`) — a real conflict found and fixed
during this sprint, not assumed away: SentencePiece's hidden default
normalization silently mapped styled Unicode (Mathematical Alphanumeric
Symbols) to plain ASCII and altered round-trip behavior for a zero-width
non-joiner, independent of this framework's own stated NFC policy. Byte
fallback guarantees any input is representable. Special-token integrity
is validated at construction (fails closed if the four reserved tokens
aren't at their reserved ids). Per-language and code-switching fertility
reporting, and `recommend_vocab_size()`'s measured trade-off curve, are
real, tested functions — not hardcoded recommendations.

## Phase 4 — Pretraining engine primitives

`orca/genesis/training/primitives.py`: causal LM loss with correct
shift/ignore-index handling (verified against torch's own
`F.cross_entropy` reference), AdamW with the standard decay/no-decay
parameter grouping, cosine-with-warmup LR schedule, gradient-clipping
math, NaN/Inf fail-closed checks, and full `TrainingState`
capture/restore — model weights, optimizer state, and RNG state
(Python/torch/CUDA) — verified by actually resuming a run and checking
that the NEXT random draw matches what it would have been had training
never stopped (`test_rng_state_restoration_reproduces_subsequent_randomness`),
not merely that deserialization doesn't crash. Reuses
`orca/registry/provenance.py`'s existing custody infrastructure rather
than duplicating it; this module does not implement its own signing or
trust logic.

## Phase 5 — Non-training verification evidence

**63 new tests, all passing**:
- `tests/test_genesis_model_architecture.py` — 23 tests: shapes, parameter
  counts (including the Phase-1 budget-rejection case), RoPE norm
  preservation and position-dependence, GQA's `repeat_kv` checked against
  a direct manual reference calculation, the two attention backends
  cross-checked against each other, **causal masking verified via a
  genuine information-leakage adversarial test** (changing only the last
  token of a sequence must leave every earlier position's logits
  bit-for-bit unchanged), deterministic initialization, invalid-config
  rejection.
- `tests/test_genesis_training_primitives.py` — 18 tests: loss math
  against two independent references, optimizer parameter grouping,
  scheduler value checks at specific steps, grad-clipping verified
  against the gradient norm it actually produces, NaN/Inf detection, and
  checkpoint/RNG round-trip through real disk I/O into a fresh model.
- `tests/test_genesis_tokenizer.py` — 22 tests: NFC normalization, special-
  token integrity, round-trip encode/decode across English + 3 Indian
  languages (Hindi, Tamil, Telugu) + 2 code-switched samples, byte-
  fallback on genuinely unseen Unicode, per-language and code-switching
  fertility measurement.

**A real CI integration gap was found and fixed during this sprint, not
left for later discovery**: these 3 new files import `torch`/
`sentencepiece`, neither of which the main "Deterministic Unit Tests" CI
job installs (confirmed directly by reading `.github/workflows/test.yml`
— `test_train_losses.py` is deliberately excluded from that job for the
identical reason). Fixed the same way the existing `test_train_losses.py`
is: `pytest.importorskip` in each new test file (a legitimate skip, not a
collection error, where the dependency is absent) and added all 3 files
plus a `sentencepiece` install line to the existing, already-required
`torch-loss-tests` CI job, rather than creating a new job or silently
leaving them untested in CI.

Untrusted-checkpoint handling and permission/authorization enforcement
(Phase 5's remaining items): `load_training_state()`'s own docstring
states explicitly that provenance verification is the caller's
responsibility via the existing `orca.registry.provenance` module, which
this sprint reuses rather than re-implements; no new bypass of
`orca.train.authorization`'s existing fail-closed gate is introduced
anywhere in this sprint (verified: `orca/genesis/` imports nothing from
`orca.train.authorization` and contains no training-authorization logic
of its own — it has no reason to, since it performs no training).

## Phase 6 — R65/G1/AUTH-1 founder-decision package

Re-verified directly (not from memory): `docs/orneur/acceptance/acceptance_ledger.json`
is an empty list; `ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md`
states `R65` is `NOT_VERIFIABLE` with **no rule source**, and that *"the
child rules are absent on purpose"* until a founder-approved source
exists. `G1` and `AUTH-1` are likewise `NOT_VERIFIABLE`.

- **Does an authentic source for the 65 founder rules exist?** Not found
  anywhere in this repository. The register's own text confirms this is
  known and intentional, not an oversight: *"No pre-training percentage
  is published... Until then the child rules are absent on purpose."*
- **Implications if no authoritative source exists:** per the register's
  own fail-closed design, `FINAL-1` (94 pre-training ids, excluding
  itself) stays `NOT_STARTED`; `FINAL-2` requires `FINAL-1`; `EXEC-1`
  requires `FINAL-2`. The entire formal training-authorization chain is
  blocked at its root by this one unresolved input. This is not an
  engineering defect — the register is doing exactly what it was
  designed to do (fail closed on an unmapped mandatory requirement)
  — but it does mean no further engineering effort can advance this
  specific chain without the founder-approved source.
- **Formally permitted governance correction process:** the register's
  own text names the needed step precisely: *"When a founder-approved
  source of the 65 rules exists, R65 is replaced by one child row per
  rule and the denominator changes."* No other path is described or
  implied. This sprint does not invent or propose an alternative process.
- **Why R65-child rejection is hardcoded:** the acceptance engine
  (`scripts/acceptance/acceptance_engine.py`) rejects a non-empty
  committed ledger/trust store and fails closed on a missing, forged,
  stale, or improperly-scoped signature — by design, so that an
  unresolved mandatory requirement cannot be quietly routed around by
  editing a status cell or the graph JSON directly (the register's own
  text: *"Editing a status cell, the Markdown, or the graph JSON does
  not accept a row."*). This sprint does not alter, weaken, or propose
  weakening this mechanism.
- **Separating research planning from training authorization:** this
  entire sprint (architecture, tokenizer, training primitives) is
  research/engineering preparation, explicitly NOT a claim that training
  is authorized — the acceptance ledger's 0-entry state and R65's
  unresolved status are unchanged by anything implemented here, and
  nothing in this sprint advances any acceptance count.

**No automatic waiver or register rewrite was made or proposed.** This
section reports the state and the one named path forward (a
founder-approved rule source); it does not act on the founder's behalf.

## Mandatory assessment

| Area | Readiness |
|---|---|
| Platform foundation | STRONG_ENGINEERING_BETA_CANDIDATE-equivalent (unchanged from Wave 1) |
| Native model architecture | **IMPLEMENTED_UNQUALIFIED** — real, tested code now exists (this sprint); never run at a real scale, never trained |
| Tokenizer | **IMPLEMENTED_UNQUALIFIED** — real, tested framework now exists; validated only on a small, hand-written multilingual fixture, not a real corpus |
| Training engine (pretraining primitives) | **IMPLEMENTED_UNQUALIFIED** — real, tested math/serialization primitives exist; no training loop connects them to a real model/data yet |
| Dataset readiness | **NOT_VERIFIED** (unchanged from Wave 1) |
| Evaluation integrity | **NOT_VERIFIED** for a native model (unchanged — Genesis eval harness still has no candidate model to score) |
| Compute readiness | **NOT_VERIFIED** (unchanged — no hardware provisioned) |
| Formal training authorization | **NOT_VERIFIED / blocked** on R65 (unchanged — explicit founder-input dependency, named in Phase 6) |

No category is scored 9.5/10 or `GOD_MODE_VERIFIED`-eligible. This sprint
moved three categories from `ABSENT`/`NOT_VERIFIED` (Wave 1) to
`IMPLEMENTED_UNQUALIFIED` — real, tested code exists now — and changed
nothing about dataset/compute/authorization readiness, which remain
exactly where Wave 1 found them.

## Final verdict

**`GENESIS_FOUNDATION_READY_FOR_INDEPENDENT_AUDIT`**

No training, GPU provisioning, paid infrastructure, corpus acquisition,
production deployment, frozen-governance modification, or merge into
`main` occurred. No trained native model, qualified checkpoint, or
frontier capability is claimed — architecture code compiling and 63
tests passing is reported as exactly that: real, tested, non-training
engineering, nothing more.
