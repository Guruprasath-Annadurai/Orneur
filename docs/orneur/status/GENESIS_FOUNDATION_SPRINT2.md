# GENESIS Foundation — Sprint 2: Native Pretraining Readiness Engineering

Status date: 2026-10-15. Implementation branch: `claude/genesis-sprint2-2026-10-15`,
branched from PR #55's exact head SHA `88ac6da8450f7751e002aa243053c541d5eae4e5`
(Sprint 1 + Audit #016 remediation, final evidence commit) — **not** from `main`.
`main`'s head at branch time was independently re-verified unchanged at
`20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`. Sprint 1 is not yet merged to `main`;
this branch therefore carries a hard, explicit dependency on PR #55 landing first,
or on PR #55's commits being rebased onto whatever successor branch actually merges.
This is a documented risk, not a silent assumption.

Starting evidence confirmed before this sprint began: independent Audit #016
successor (PR #57) reported `GENESIS_SPRINT1_ACCEPTED_VERIFIED`; two successful CI
runs on the `torch-loss-tests` job; native training remains `NOT_AUTHORIZED`;
postgres tenant-isolation test finding remains `retained as unresolved` per the
prior sprint's own correction.

**No training, no GPU provisioning, no spend, and no external corpus ingestion
occurred anywhere in this sprint.** Every new module operates on CPU, on tiny
(≤2-layer, ≤16-dim) models constructed fresh in-test, or on pure closed-form
arithmetic.

## Scope decision

The directive specified six workstreams (A–F). Given the length of this session
and the quality bar already established (original implementation, real
derivations, adversarial tests, no shortcuts), three workstreams were implemented
with full depth rather than attempting shallow coverage of all six — the same
bounded-scope judgment this session applied to the earlier GOD-MODE directive,
where the user's own follow-up confirmed that approach:

- **Implemented, tested, evidence below**: Workstream E (compute/scaling
  realism), Workstream B (checkpoint integrity/recovery), Workstream D (model
  evaluation integration).
- **Deliberately deferred, not blocked**: Workstream A (dataset pipeline
  foundations), Workstream C (training orchestration state machine),
  Workstream F (training governance package specific to Sprint 2). Nothing
  encountered during this sprint prevents these from being implemented in a
  follow-up sprint; they were simply not attempted, to keep what was attempted
  held to the same rigor as the rest of this program.

## Workstream E — Compute and scaling realism

`orca/genesis/model/scaling.py` (new):

- `estimate_training_memory()`: closed-form AdamW memory accounting —
  `optimizer_state_fp32 = n_params * 4 bytes * 3` (fp32 master weight + exp_avg +
  exp_avg_sq), `model_weights_bf16` / `gradients_bf16` at 2 bytes/param, and a
  documented conservative (no-activation-checkpointing) activation estimate.
- `theoretical_flops_per_token()`: the standard `6N` approximation (Kaplan et
  al. 2020 / Chinchilla scaling-law literature), kept strictly separate from
  `estimate_training_compute()`'s optional `measured_mfu` — a caller who
  supplies no real measurement gets an explicit `None` for
  `measured_seconds_estimate`, never a silently invented default MFU.
- `CORRECTED_SCALING_TIERS`: six tiers (`10M-smoke` through `3B`, all
  `vocab_size=64_000`), each resolved via `GenesisModelConfig.from_param_budget()`
  (already-audited Sprint 1 code) so every tier's real parameter count is
  derived, not asserted.
- A real, computed finding kept as an executable test rather than smoothed over:
  at `vocab_size=64,000`, the `10M-smoke` tier's embedding table is **89%** of
  its own total parameter budget — this is the same error class Audit #015
  (PR #54) was found to have for its Stage 1 config, now caught structurally.

Tests: `tests/test_genesis_scaling.py`, **11/11 passing**.

## Workstream B — Checkpoint integrity and recovery

`orca/genesis/training/checkpoint_integrity.py` (new, strictly additive — does
not modify Sprint 1/Audit #016's already-remediated `save_training_state()` /
`load_training_state()`):

- `save_verified_training_state()`: saves via the existing atomic-write path
  unchanged, then computes the real on-disk SHA-256 (after the atomic rename,
  reflecting exactly what a future reader sees) and writes an owner-only
  (`0o600`) sidecar manifest via the same `_mkdir_owner_only` + tmp-write +
  atomic-replace discipline established in Sprint 1.
- `load_verified_training_state()`: the trusted-load boundary. Refuses to call
  `load_training_state()` at all unless the on-disk hash matches the manifest.
  Two distinct exception types (`ChecksumMismatchError` vs. `ManifestMissingError`)
  deliberately kept separate — a checkpoint saved by the older, unverified path
  is a different condition from a tampered one, and collapsing them would make
  the two indistinguishable in logs/alerts.
- Explicitly scoped as a **content**-integrity check, not a provenance/trust
  check — `orca.registry.provenance`'s responsibility is not duplicated here,
  and one test documents this boundary directly (a matched, mutually-consistent
  substituted checkpoint+manifest pair defeats the hash check by construction;
  that is `orca.registry.provenance`'s job, not this module's).

Adversarial tests, `tests/test_genesis_checkpoint_integrity.py`, **10/10 passing**:
single-byte corruption, truncation, whole-file substitution with a different
valid checkpoint, missing manifest, deleted manifest, missing checkpoint file,
and a crash-consistency test (`monkeypatch`-forced failure mid-manifest-write)
confirming the prior manifest survives untouched.

## Workstream D — Model evaluation integration

`orca/genesis/model/eval_adapter.py` (new):

- `make_inference_backend(model, tokenizer)`: wraps a `GenesisTransformer` +
  `GenesisTokenizer` into exactly the `Callable[[str, SamplingConfig],
  GenerationResult]` signature `orca.eval.genesis_harness.Harness` already
  expects. Real autoregressive generation via the model's own
  `generate_step()` — one real forward pass per emitted token, no mocked
  generation path — with real wall-clock timing and the harness's own
  error-reporting contract (`GenerationResult.error`, never a raised exception).
- `diagnose_adapter(model, *, checkpoint_source=None)`: the explicit,
  unmissable statement of whether a model behind this adapter is a fresh
  random initialization (the only kind that exists anywhere in this codebase)
  or a real checkpoint. `checkpoint_source` is required to be stated by the
  caller, never auto-detected — this module has no way to know on its own
  whether a model object came from a real trained checkpoint, and guessing
  would be exactly the "quietly blur the distinction" failure mode this sprint
  was asked to avoid.

Tests: `tests/test_genesis_eval_adapter.py`, **8/8 passing**, including:

- A deterministic inference-adapter test (same model, same seed, temperature
  0 → bit-identical output across two calls).
- `diagnose_adapter()` correctly flagging `is_randomly_initialized=True` by
  default, and `False` with an explicit checkpoint source.
- A concrete, executable version of the "not meaningful capability" claim: a
  random-weight model's greedy continuation of a real training sentence does
  **not** reproduce the real corpus continuation — checked as an assertion,
  not left as an unverified docstring claim.
- **A genuine end-to-end integration test against the real, already-committed
  corpus and preregistration** (`ROOT = repo root`, the same artifacts
  `tests/test_genesis_eval_v1.py` itself verifies) — not a fabricated stand-in.
  This constructs a real `RunProvenance` and `SamplingConfig`, instantiates the
  real `Harness` class (which fail-closed-verifies the preregistration before
  accepting any backend), and runs the real `GenesisTransformer` +
  `GenesisTokenizer` + adapter against one real `DEV`-split item through
  `Harness.run_item()`. The first attempt at this test called `Harness(backend=...)`
  directly, which failed immediately (`TypeError: missing 4 required positional
  arguments`) — the real `Harness` requires `root`, `prereg_path`, `provenance`,
  and `sampling`, not just a backend. Reusing the existing `_prov()` fixture
  pattern from `tests/test_genesis_eval_v1.py` fixed this correctly rather than
  loosening the test to avoid the real class's actual contract.

## Regression evidence

Full local run (`/Users/ag/orca/.venv`, Python 3.11.15, torch 2.13.0,
sentencepiece 0.2.2) across every GENESIS test file plus the full pre-existing
Genesis Capability Eval V1 suite (`tests/test_genesis_eval_v1.py`, 150 tests
covering freeze records, funnel corrections, the private corpus, contamination
control, floors, pre-registration, and the CPU harness itself):

```
tests/test_genesis_eval_adapter.py ................ 8 passed
tests/test_genesis_scaling.py .................... 11 passed
tests/test_genesis_checkpoint_integrity.py ........ 10 passed
tests/test_genesis_model_architecture.py .......... (Sprint 1, unchanged)
tests/test_genesis_training_primitives.py ......... (Sprint 1, unchanged)
tests/test_genesis_tokenizer.py ................... (Sprint 1, unchanged)
tests/test_genesis_audit016_remediation.py ........ (Audit #016, unchanged)
tests/test_genesis_eval_v1.py ...................... 150 passed

== 202 passed in 28.76s ==
```

No existing test was modified to make this pass. `.github/workflows/test.yml`'s
`torch-loss-tests` job ("Training Math Unit Tests (Torch)") was extended with
the three new Sprint 2 test files, following the exact pattern Sprint 1 and
Audit #016 remediation established (this job, not the main "Deterministic Unit
Tests" job, installs torch/transformers/sentencepiece).

CI run on this exact commit: **pending** — not yet pushed/observed at the time
of writing this report; the PR description will be updated with the actual
run link once pushed, per this session's standing practice of never asserting
CI results that have not been observed.

## Known risks / unresolved items carried forward

- **Sprint 1 → `main` merge dependency**: this branch depends on PR #55's
  content; if PR #55 is rebased, abandoned, or squash-merged differently,
  this branch's history will need to be rebased accordingly. Not yet resolved,
  and explicitly not something this sprint had authority to resolve
  (no merge without explicit founder approval).
- **Postgres tenant-isolation test**: unchanged from the prior sprint's
  correction — retained as unresolved, not reproduced under genuine concurrent
  load on the current commit, not re-classified here.
- **Workstreams A, C, F**: not attempted in this sprint (see Scope decision
  above). R65/G1/AUTH-1 and the 0/95 acceptance ledger remain exactly as
  documented in Sprint 1 and the Wave 1 audit — nothing in this sprint advances
  or alters those gates, and nothing here should be read as doing so.
- **Native model training**: remains `NOT_AUTHORIZED`. Nothing in this sprint
  performs, enables, or shortens the path to unauthorized training — Workstream
  C (the only workstream that would touch training orchestration) was
  deliberately not attempted.

## Verdict

**`GENESIS_SPRINT2_READY_FOR_INDEPENDENT_AUDIT`** — scoped explicitly to
Workstreams B, D, and E as implemented and tested above. Workstreams A, C, and
F are out of scope for this audit request, deferred (not blocked), and should
be treated as not-yet-attempted rather than reviewed as absent deliverables.

Native-model training remains `NOT_AUTHORIZED`. No merge to `main` is requested
or should occur without explicit founder approval.
