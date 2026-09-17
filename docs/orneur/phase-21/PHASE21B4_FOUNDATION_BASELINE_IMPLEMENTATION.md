# Phase 21B.4 -- Foundation Baseline Implementation

Documents the REAL infrastructure built this closure: the baseline<->
freeze transaction, the evaluation runner, and the sandbox security
hardening. This is distinct from (and does not replace)
`PHASE21B4_FOUNDATION_BASELINE_SHOOTOUT.md`, which remains the
unexecuted runbook specifying candidates, configuration parity, and
compute-class estimates for the future execution this document's
infrastructure will eventually drive.

**No real model was executed to produce this document.** Every code
path described below has been exercised only against `DryRunAdapter`
(explicitly non-real, see below) and synthetic test fixtures.

## 1. The baseline<->freeze trust gap this closure closes

Independent-audit requirement: *"The first real baseline result must be
coupled transactionally/fail-closed to persistent freezing of
genesis-eval-v1. The evaluation suite must never be silently modified
after real model results have been recorded against it."*

Prior state (end of Phase 21B.3): `EvaluationSuiteManifest` existed with
freeze-on-disk protection (`save()` refuses to overwrite a frozen
manifest), but NOTHING coupled recording a real result to triggering
that freeze -- a caller could persist a result and simply never freeze
the suite, or freeze the suite without ever persisting a valid result,
leaving the two independently mutable.

### Architecture

Three new modules:

- `orca/registry/evaluation_result_manifest.py` -- `EvaluationResultManifest`,
  the RESULT side (one candidate's full run against one suite version).
  Distinct from `orca.registry.evaluation_registry.EvaluationReport`
  (pre-existing, keyed to a trained `CheckpointRecord` and the
  project's promotion-gate governance -- not used here, since no
  checkpoint exists) and from `EvaluationSuiteManifest` (the suite's own
  task-set definition, not a candidate's results against it).
- `orca/eval/baseline.py` -- `record_baseline_and_freeze_suite()`, the
  ONE fail-closed transactional entry point.
- `orca/eval/runner.py` -- `run_suite()`, the provider-neutral evaluation
  driver that produces an (unfinalized) `EvaluationResultManifest` for
  `record_baseline_and_freeze_suite()` to consume.

### Transaction lifecycle (implemented exactly as specified)

```
load persisted suite manifest (or register it fresh, unfrozen, if this
    is the very first call against this suite version)
  -> verify suite identity/version match
  -> verify content_digest match
  -> verify scoring_contract_digest match
  -> [caller already executed candidate evaluation via run_suite()]
  -> validate complete result (denominator integrity: every scored
     task_id has a per_task_results entry; every failed generation has
     a generation_failures entry; completed_at is set)
  -> if suite already frozen: persist result as finalized, done (no
     freeze attempted -- read-only path)
  -> if suite not yet frozen:
       -> stage result to disk with finalized=False
       -> freeze the suite manifest object
       -> persist (save) the frozen suite manifest
       -> re-read the suite manifest FROM DISK (never trust the
          in-memory object)
       -> verify frozen == True on the re-read copy
       -> verify digests on the re-read copy still match what was
          originally computed
       -> only now: flip result.finalized = True and re-save it
  -> any failure at any step after staging: delete the staged result
     (rollback), raise a typed error -- no falsely-valid state is ever
     left on disk
```

### Failure modes explicitly prevented (each with an executable test)

| Failure mode | Prevention |
|---|---|
| Result exists but suite remains mutable | `finalized` only ever flips to `True` after the freeze is re-read from disk and confirmed |
| Suite freezes before a failed/incomplete result | Completeness validated BEFORE the suite is touched at all |
| Result references digests differing from the persisted suite | Explicit digest comparison against the loaded manifest before any write |
| Partially-written baseline appears valid | Staged with `finalized=False`; only a verified freeze flips it |
| Later process overwrites v1 after the first baseline | `EvaluationSuiteManifest.save()`'s pre-existing frozen-on-disk guard (`EvaluationSuiteFrozenError`); this module never bypasses it, and the already-frozen path never calls `.save()` on the suite at all |

Tests: `tests/test_evaluation_baseline_freeze.py` -- 14 tests covering
all 16 required scenarios (two pairs of scenarios share one test each
where the same code path proves both). Includes simulated `save()` and
`load()` failures (monkeypatched to raise/return a torn state) to prove
the rollback path actually executes, not merely that it exists in code.

## 2. The evaluation runner

`orca/eval/runner.py::run_suite(adapter, candidate_config, ...)` drives
ANY `ModelAdapter` implementation (a `Protocol` with one method,
`generate(prompt, *, system_instruction, config) -> GenerationResult`)
against the full, persisted, digest-verified `genesis-eval-v1` suite.

- **Denominator integrity**: every task gets exactly one outcome --
  a `per_task_results` entry (deterministic or `UNSCORED_REQUIRES_JUDGE`
  for llm_judge categories) or a `generation_failures` entry. Never
  silently dropped.
- **Revision pinning enforced structurally**: `CandidateConfig.__post_init__`
  raises `ValueError` if `exact_revision` is missing, empty, or looks
  like a mutable ref (`"main"`, `"latest"`, `"head"`) -- a candidate
  cannot even be constructed, let alone evaluated, without a real pinned
  revision.
- **Raw responses persisted by content-addressed reference**
  (`RAW_RESPONSE_DIR/<run_id>/<task_id>-<digest16>.txt`), never inlined
  into the core result manifest.
- **Full provenance fields** captured per Step 11's schema: candidate,
  upstream_model, artifact_repo, exact_revision, tokenizer_revision,
  backend, quantization, inference_config, seed, context_window_used,
  system_instruction_digest, software_commit_sha, hardware,
  suite_content_digest, suite_scoring_contract_digest, per-task/
  per-category/deterministic summaries, unscored_categories,
  generation_failures, started_at/completed_at.

### `DryRunAdapter` -- explicitly not a real model

`orca.eval.runner.DryRunAdapter` returns a fixed, unmistakably-labeled
placeholder string (`"[DRY_RUN_PLACEHOLDER_RESPONSE -- NOT A REAL MODEL
OUTPUT]"`) for every prompt. It exists ONLY to validate the runner's own
plumbing (denominator integrity, digest wiring, failure capture) in
`tests/test_eval_runner.py`. Any result produced with it is a synthetic
harness-validation artifact, never presented as, or confusable with, a
real candidate baseline -- confirmed by the fact that its fixed response
predictably FAILS the majority of deterministic tasks
(`test_run_suite_deterministic_summary_reflects_actual_pass_rate`
asserts `passed < total`, not a suspiciously perfect or rigged score).

## 3. Executable scoring sandbox hardening

See `orca/eval/sandbox.py`'s module docstring for the full writeup. In
brief: the prior in-process `exec()` with restricted builtins (used for
category 4/coding and 5/debugging unit-test scoring) was LIVE
REPRODUCED as exploitable this closure:

```python
for cls in ().__class__.__bases__[0].__subclasses__():
    if cls.__name__ == "Popen":
        proc = cls(["echo", "PWNED"])   # actually ran -- printed PWNED to real stdout
```

This bypasses restricted builtins entirely (no `__import__` needed --
`Popen` was reachable via the live object graph of an already-loaded
process). A second reproduction found no timeout enforcement at all (a
`while True: pass` payload hung indefinitely).

**Fix**: `orca/eval/sandbox.py::run_sandboxed()` executes each
candidate function call in a **fresh child process** (`python -I -S`,
stripped environment, fresh temp cwd), with:

- A hard parent-side wall-clock timeout that kills the child.
- POSIX resource limits in a `preexec_fn` (CPU time, address space, no
  core dumps, `RLIMIT_NPROC=0`).
- A Python-level network-socket guard injected before the candidate
  code runs.
- Structured JSON-only communication back to the parent.

**Confirmed fixed, live, this closure** (see `tests/test_eval_sandbox.py`):
the subclass-walk attack now finds nothing (the fresh child never
imported `subprocess`); the infinite loop is killed at the configured
timeout; direct socket connections raise; and -- verified with a real
test, not assumed -- attempting `import subprocess` and spawning a
grandchild FROM WITHIN the sandboxed child fails with
`BlockingIOError: [Errno 35] Resource temporarily unavailable`
(`RLIMIT_NPROC=0` genuinely blocks forking on this platform).

**Confirmed NOT fixed, stated honestly**: the sandboxed child is not
filesystem-jailed. A live test in this closure confirmed generated code
CAN write files outside its own temp cwd (e.g. directly to `/tmp`), since
no portable, CI-safe (this project's CI runs on Linux; local development
here is macOS with no cgroups/seccomp) filesystem-namespace mechanism
was available. macOS's `sandbox-exec` could restrict this on macOS
specifically but is deprecated and fragile, and adopting it without an
equivalent Linux-CI mechanism would produce an inconsistent,
platform-conditional security boundary -- judged worse than a clearly
documented, uniform limitation. The recommended stronger option for a
fully-adversarial-hostile-input posture remains a real container
boundary (Docker/gVisor/nsjail).

## 4. LLM-judge categories -- Option B (not fabricated)

Per spec §4, categories 2 (broad professional reasoning), 6 (software
architecture), 8 (requirements interpretation), and 13 (capability-
expansion/ASI-protocol) have versioned, digested rubrics (built in
Phase 21B.3) but NO judge-execution harness was implemented this
closure. `orca.eval.runner.run_suite()` tags every task in these
categories with `passed=None` and `note="UNSCORED_REQUIRES_JUDGE"`, and
`orca.eval.baseline.record_baseline_and_freeze_suite()`'s completeness
check explicitly excludes them from the denominator it enforces (a
caller passes `scored_task_ids` covering only the deterministically-
scored tasks). These categories can never silently contaminate
`deterministic_summary`'s pass-rate calculation -- confirmed by
`per_category_summary` tracking `unscored` as a field distinct from
`scored`/`passed`.

## 5. Suite manifest registry schema

| Path | Class | Contents |
|---|---|---|
| `ORCA_HOME/registry/evaluation_suites/<suite_id>-<version>.json` | `EvaluationSuiteManifest` | task_ids, content_digest, scoring_contract_digest, frozen, frozen_at, category_task_counts |
| `ORCA_HOME/registry/evaluation_results/<run_id>.json` | `EvaluationResultManifest` | full per-candidate run record, per Step 11's schema, plus `is_first_baseline`/`finalized` |
| `ORCA_HOME/registry/evaluation_raw_responses/<run_id>/<task_id>-<digest16>.txt` | plain text | raw model generations, referenced by pointer from `per_task_results[].raw_response_ref` |

All three isolated in `tests/conftest.py`'s autouse fixture, following
this project's established discipline for every `ORCA_HOME`-derived
module constant.

## 6. Resource gate check (Step 8)

Checked explicitly before any inference-adjacent code was written for
real execution:

```
$ nvidia-smi          -> command not found
$ system_profiler SPDisplaysDataType -> Apple M4 (integrated, no CUDA)
$ env | grep -iE "modal|kaggle|colab|hf_token|cuda|gpu" -> (empty)
$ which modal kaggle   -> not found
```

This local development environment (macOS, Apple M4, Darwin) has no
CUDA-capable GPU and no configured credentials for any owner-approved
cloud compute provider (Kaggle, Colab, Modal, Race Engineering). Per
spec §8, this means: **BLOCKED ON OWNER-CONTROLLED COMPUTE RESOURCE --
NO MODEL BASELINE EXECUTED.** No model score of any kind has been
simulated, estimated, or fabricated anywhere in this closure.

## 7. Reproduction / future execution instructions

Once an owner-approved GPU/cloud resource is available and explicitly
authorized:

1. Implement a real `ModelAdapter` for the chosen backend (e.g. a
   `transformers`-based adapter loading a pinned HF revision, or a
   provider-API adapter) -- `orca/eval/runner.py::ModelAdapter` is the
   `Protocol` to implement; `DryRunAdapter` is the reference shape, NOT
   a starting point to weaken.
2. Re-verify each candidate's exact revision SHA/license live (do not
   trust the SHAs recorded in `GENESIS_FOUNDATION_SHORTLIST_2026.md` or
   `PHASE21B4_FOUNDATION_BASELINE_SHOOTOUT.md` -- upstream can publish
   new commits under the same tag).
3. Construct a `CandidateConfig` (raises if `exact_revision` isn't
   pinned).
4. `result, scored_task_ids = orca.eval.runner.run_suite(adapter, config)`.
5. `orca.eval.baseline.record_baseline_and_freeze_suite(tasks=orca.eval.genesis_suite.all_tasks(), result=result, scored_task_ids=scored_task_ids)`
   -- this call is what actually freezes `genesis-eval-v1` on the FIRST
   real candidate, and simply records subsequent candidates' results on
   later calls.
6. Update `GENESIS_BASELINE_RESULTS.md` with the real, factual per-
   category results -- never before step 5 has actually run.

Run the targeted + full test suites (see this closure's Final Stop
Report) before and after any real execution; do not proceed to real
inference with red tests.
