# Genesis Evaluation Suite v1 — Specification and Build State

Phase 21B.1 wrote the original specification with only category 1 built
(30/~220 tasks, 14%). Phase 21B.3 builds out categories 2-17 against
that same specification, implemented in `orca/eval/genesis_suite.py`
with real, runnable scorers, plus a versioned suite manifest
(`orca.registry.evaluation_suite_manifest.EvaluationSuiteManifest`,
mirroring `DatasetManifest`'s freeze-on-first-baseline semantics).

## Suite identity

Version: `genesis-eval-v1`. **Not yet frozen** -- no real baseline or
candidate score has been recorded against it (Phase 21B.3 forbids any
training or evaluation execution). Freezing happens at the first real
baseline recording (Phase 21B.4 or later), not at authoring time. Once
frozen, no category's task set or scoring contract may change under the
`v1` name -- any future change requires `genesis-eval-v2`.

## Categories -- current build state (Phase 21B.3)

| # | Category | Task count (target) | Task count (built, 21B.3) | Scoring | Held-out verified |
|---|---|---|---|---|---|
| 1 | General instruction following / professional / everyday | 30 | **30** (pre-existing `genesis_eval.py`, unchanged) | Keyword coverage | YES (§ below) |
| 2 | Broad professional reasoning | 15+ | **5** | LLM-judge (rubric defined, versioned; NOT executed) | YES |
| 3 | Quantitative reasoning | 15+ | **6** | Exact numeric-string match | YES |
| 4 | Coding | 20+ | **5** | **Executable unit tests** (sandboxed) | YES |
| 5 | Debugging | 15+ | **4** | **Executable** (fixed-function unit tests) | YES |
| 6 | Software architecture | 10+ | **4** | LLM-judge (rubric defined, versioned; NOT executed) | YES |
| 7 | Multi-file reasoning | 10+ | **3** | Deterministic pattern match (required filenames present) | YES |
| 8 | Requirements interpretation | 10+ | **4** | LLM-judge (rubric defined, versioned; NOT executed) | YES |
| 9 | Product-building reasoning | 10+ | **3** | Structured fixture checklist (5-topic deterministic schema check) | YES |
| 10 | Verification / fabricated-completion resistance | 15+ | **4** | Deterministic pattern match (required + forbidden patterns) | YES |
| 11 | Tool planning | 10+ | **3** | Deterministic pattern match | YES |
| 12 | Uncertainty / epistemic behavior | 10+ | **3** | Deterministic pattern match | YES |
| 13 | Capability-expansion reflex (ASI protocol) | 10+ | **3** | LLM-judge (rubric defined, versioned; NOT executed) | YES |
| 14 | Human-sovereignty / authority boundaries | 15+ | **4** | Deterministic pattern match | YES |
| 15 | Security / adversarial behavior | 15+ | **3** | Deterministic pattern match | YES |
| 16 | Model-society interchange | 10+ | **3** | Deterministic pattern match (correct escalation named) | YES |
| 17 | Presence Mode / verified task-state behavior | 10+ | **3** | Deterministic pattern match (no fabricated state) | YES |

**Total built: 90/~220 target tasks (~41%).** All 17 categories now have
at least 3 real, runnable tasks each (up from 1/17 categories fully
built). This is a genuine 3x expansion of the previous 30-task state,
NOT a claim that the ~220 target, or any individual category's own
"15+"/"20+" target, has been met.

## Honest deficit explanation (per spec section 18)

Every category below its specified target ("15+", "20+", "10+") falls
short because each task in this build was individually authored with
real, checkable content (a genuine unit-test fixture, a genuine
numeric problem with a verified answer, a genuine pattern-match
contract) rather than templated -- the spec explicitly forbids "low-
quality variants merely to hit 220," and this closure's time budget did
not extend to authoring the full target count at the same quality bar.
Category 4 (Coding, target 20+, built 5) and categories 2/6/8/13
(LLM-judge categories, target 10-15+ each, built 3-5) are the largest
gaps in absolute task count; closing them is the most direct next step
for a future evaluation-build closure.

## Scoring philosophy

Executable/deterministic scoring is used for every category where the
task shape allows it (3, 4, 5, 7, 9, 10, 11, 12, 14, 15, 16, 17 -- 12 of
17 categories, all with real, tested scorer code in
`orca.eval.genesis_suite`). Category 1 retains its pre-existing keyword
scorer (explicitly the least rigorous method in this suite, kept for
compatibility). Categories 2, 6, 8, and 13 have a versioned, digested
rubric defined but are NOT scored by this closure -- no model has been
evaluated against this suite (Phase 21B.3 forbids training/evaluation
execution), so there is nothing to judge yet. Per spec section 22, the
final qualification decision must never depend solely on an LLM judge;
this suite structurally enforces that by having deterministic scoring
for the large majority (12/17) of categories.

## Held-out policy

Every one of the 90 tasks' prompts was screened against Genesis v1, v2,
and v3 (train AND validation splits) for exact and near-duplicate
overlap -- see `GENESIS_EVAL_CONTAMINATION_REPORT.md`. Result: zero
known direct leakage. This closes the prior document's "None of the 17
categories currently has a formally verified held-out split" gap for
every category that now has real tasks.

## Contamination policy

Direct leakage against this project's own training data: verified zero
(see contamination report). Base-model pretraining contamination:
explicitly UNKNOWN and unresolvable from outside the model provider --
stated as a limitation, not silently assumed away (see contamination
report's limitations section).

## Suite manifest / digest

`EvaluationSuiteManifest` (`orca/registry/evaluation_suite_manifest.py`)
records `task_ids`, `content_digest` (over task prompts/category/
difficulty), and `scoring_contract_digest` (over scoring type/expected
values/patterns/schema/rubric -- kept separate from content_digest so a
prose-only rubric edit and a scoring-contract change are independently
detectable) -- both computed deterministically via
`orca.eval.genesis_suite.compute_suite_digests()`. Verified in
`tests/test_genesis_eval_suite.py` that the manifest's recorded digests
match a fresh recomputation from the current task list, and that a
tampered task list is detected (fails `verify_against_tasks()`).

## Baseline-vs-candidate protocol

Unchanged from the original specification: the SAME suite version must
score both the untouched base model and any Genesis-trained candidate.
Per-category deltas, never a single aggregate score, determine
qualification. Not exercised this closure (no model evaluation was
run).

## Pass/fail interpretation

Not yet defined numerically for any category (see
`GENESIS_PRETRAINING_QUALIFICATION.md`'s regression-policy section for
why numeric thresholds are deliberately deferred until a real baseline
exists to calibrate against).

## Malformed-output / robustness

`orca.eval.genesis_suite.score_task()` is exercised in
`tests/test_genesis_eval_suite.py` against deliberately malformed model
outputs (no code block, code that raises an exception, code attempting
to `import os` to escape the sandbox) and confirmed to fail closed
(score as not-passed, never crash the scorer, never silently pass) in
every case -- see that test file's `# ── malformed output / sandbox
escape robustness ──` section.

## Limitations (honest, not glossed over)

- 41% built (task count: 90/~220), all 17 categories represented (up
  from 1/17 categories with any tasks at all).
- Category 4 (Coding) and the four LLM-judge categories (2, 6, 8, 13)
  are the largest remaining gaps in absolute task count relative to
  their own individual targets.
- LLM-judge categories have a rubric and digest but no executed
  scoring -- no LLM-judge harness/prompt-execution infrastructure was
  built this closure (out of scope: no model evaluation was permitted).
- The unit-test sandbox (`score_unit_test`) is best-effort restricted-
  builtins isolation, not a hardened security sandbox (no separate
  process, no resource limits) -- adequate for scoring fixture-shaped
  responses to known tasks, not a general-purpose untrusted-code
  execution guarantee.
- Base-model pretraining contamination remains fundamentally unresolved
  (see contamination report).
- No numeric pass/fail thresholds exist for any category.
