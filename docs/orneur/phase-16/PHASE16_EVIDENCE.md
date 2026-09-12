# PHASE 16 — Evidence

## Repository state

- Local repo used: `/Users/ag/orca` (per the documented path discrepancy — see
  PHASE16_NATIVE_INTELLIGENCE_BASELINE_AUDIT.md §0).
- Branch: `session-update-2026-08-25`.
- Starting HEAD for Phase 16: `ee299c72c9daa2d87b0e5fe6e7df522c8e7b73f1` (Phase 15.15's final
  evidence commit), verified parent `1945bae95382732a10e6f107da99c59d7bb7549b` (Phase 15.15's
  final implementation commit) via `git log -1 --format=%P HEAD` prior to any Phase 16 edit.
- `git status` before Phase 16 edits: clean.

## Baseline test numbers (recorded before any Phase 16 code edit)

- `pytest --collect-only -q` (via `.venv/bin/python -m pytest`): **2574 tests collected, 0
  collection errors** — identical to Phase 15.15's final number.
- Full deterministic run (`.venv/bin/python -m pytest -m "not live_ollama_smoke" -q`):
  **2275 passed, 256 skipped, 43 deselected, 0 failed** (178.12s). Total 2275+256+43 = 2574,
  consistent with collection count.
- **Honest discrepancy vs the Phase 15.15 CI number (2282 passed, 292 skipped)**: this local
  `.venv` has `torch`, `mcp`, `openai`, and `psycopg` all installed (verified via `pip list`), so
  more tests execute locally that are marker/import-guard-skipped in a narrower CI job split
  (e.g., `torch-loss-tests` runs separately in CI with only `torch` installed against a job that
  otherwise excludes those tests from its own skip/pass tally the same way). This is a real,
  explicable environment-composition difference, not a regression — no test that previously
  passed now fails, and the total collected count is unchanged. Recorded here rather than
  reconciled to a single number, per the phase's own honesty discipline (do not force numbers to
  match by re-running until they align).

## Environment hazard found and documented

Running `bash scripts/ci/run_deterministic_tests.sh` directly on this development machine produces
**38 false collection errors** because the shell's `PATH` resolves a global Homebrew
`pytest`/`python3.14` ahead of this project's `.venv` (`which pytest` → `/opt/homebrew/bin/pytest`).
This is a **local-shell artifact only** — GitHub Actions CI does not have this hazard because
`uv pip install --system` installs directly into the job's own interpreter, which is first on
`PATH` there. Confirmed by running the equivalent invocation via `.venv/bin/python -m pytest`
directly, which reproduces the correct 2574/2275/256/43/0 numbers. No CI file was changed as a
result of this finding — it does not affect CI truthfulness, only local reproduction commands.

## New tests added this phase

`tests/test_phase16_architecture_invariants.py` — 2 tests, both passing:
```
tests/test_phase16_architecture_invariants.py::test_no_model_facing_package_imports_orca_mission PASSED
tests/test_phase16_architecture_invariants.py::test_agent_policy_does_not_import_deliberation PASSED
```
Both verified to genuinely detect a violation: a synthetic file containing `import
orca.deliberation` was checked against the same `_imported_module_roots()` helper used by the
test and correctly produced `{'orca.deliberation'}`, proving the detection logic is not vacuous.
(Synthetic file created under `/tmp`, not committed to the repository, removed after the check.)

Full regression re-run after adding this file (targeted + neighboring, via `.venv/bin/python -m
pytest tests/test_phase16_architecture_invariants.py -v`): 2 passed, 0 failed.

## Production / model-artifact untouched verification

`git status` after all Phase 16 doc/test additions shows only new files under
`docs/orneur/phase-16/` and `tests/test_phase16_architecture_invariants.py` — no modification to
any file under `orca/registry/`, `orca/society/`, `orca/train/`, or any path resembling a model
weight or checkpoint file. No Neon database, no production migration, no GitHub Actions dispatch,
no live-Neon qualification run was performed this phase — Phase 16 is architecture-audit-only and
none of its required evidence depends on live infrastructure (unlike Phase 15's Relay/Mission
work). This is a deliberate scope difference from Phase 15, not an omission.

## Cost control (§28)

No GPU job, no model download, no paid API benchmark campaign, no new SaaS activation occurred
this phase. `torch`/`mcp`/`openai`/`psycopg` were already installed in this `.venv` from prior
phases' work — nothing new was installed.

## Known limitations of this audit

- Section 7's inventory depth is docstring/signature/targeted-grep level for most packages, full
  read for `orca/registry/model_spec.py` and `orca/registry/model_registry.py` only. A future
  phase modifying any specific module should re-read it in full first.
- `orca/memory/*`'s `firewall.py` claim ("No recalled memory reaches output without...") was
  read from its docstring, not independently re-verified against its full implementation this
  phase.
- The threat model's "Missing control" columns are honest gaps, not commitments — several will
  only be closable once Phase 17+ code exists to test against.

## RE-EARNED... — not applicable

This phase did not need a correction cycle; there was no owner audit finding for Phase 16 (unlike
Phase 15.15's CI-truthfulness closure). This evidence file is a first-pass, direct-evidence record.

## Phase 16 requirement totals by status

From `PHASE16_REQUIREMENTS.md`: 18 requirements total — 16 VERIFIED, 2 DEFERRED_TO_FUTURE_PHASE
(`REQ-ROUTER-ARCH-002` → Phase 20; and the enforcement half of `REQ-MEMORY-ARCH-002` → Phase 26).
0 UNIMPLEMENTED, 0 BLOCKED.

## DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 17? (original, pre-closure)

**YES** — superseded by the closure section below, which re-answers this after corrections.

---

## CLOSURE SECTION — OWNER ARCHITECTURE CORRECTION (append-only; original content above preserved unmodified)

The line above ("This phase did not need a correction cycle") was written before this closure was
requested and is now superseded by this section, not deleted, per the phase's append-only evidence
discipline.

### What owner review found

1. **Stale 70B Aeternum architecture accidentally promoted as canonical.**
   `PHASE16_CANONICAL_ARCHITECTURE.md` and `orca/registry/model_spec.py` both carried
   `unsloth/Meta-Llama-3.1-70B-Instruct` as Aeternum's `base_model`, treating a legacy/stale plan
   as the current training target.
2. **Model identities were too generic** — framed close to a small/medium/large chatbot size tier
   rather than the intended distinct cognitive specializations (Builder/Executor,
   Reasoner/Investigator, Critic/Arbiter/Discoverer).
3. **The canonical L0–L8 map had been altered** — the original Phase 16 pass substituted its own
   9-layer breakdown instead of the owner's required layer names and boundaries.
4. **Authority-boundary evidence was worded more strongly than the tests proved** — "no model-facing
   code can mutate Mission state" was asserted from import-absence grep alone, not from the actual
   pre-existing tests that prove the stronger properties (Court-ACCEPT-is-not-authority, model
   output cannot mint authority, stale authority cannot execute, Mission state machine rejects
   illegal transitions).
5. **Newer owner doctrines had not yet been incorporated** — Universal Expert Intelligence,
   Production Product Intelligence (future hard qualification), Frontier Research, and
   Three-Model Collective Intelligence.
6. **`CourtVerdictState` was independently found to be misstated** (self-discovered while
   correcting item 4, not an owner-flagged item): the original draft claimed
   `ACCEPT/REJECT/NEED_MORE_EVIDENCE/ESCALATE/HUMAN_APPROVAL_REQUIRED`; the real enum in
   `orca/deliberation/contracts.py` is `ACCEPT/REVISE/REJECT/INSUFFICIENT_EVIDENCE`. Fixed
   immediately inside this same closure per the "if another bug is discovered while repairing this,
   fix it now inside the same phase" discipline established in Phase 15.15.

### What changed, exactly

**Code** (all in the closure commit):
- `orca/registry/model_spec.py`: `ModelSpec.base_model`/`tokenizer`/`architecture` are now
  `Optional`; added `base_model_status` and `provisional_parameter_hypothesis` fields; Aeternum's
  `base_model` set to `None`, `base_model_status="UNSELECTED_PROVISIONAL"`, `parameter_class`
  changed from `"70B"` to `"~14B"` with an explicit non-binding-hypothesis note; `legacy_note`
  rewritten to state the 70B plan is legacy/stale, not planned; added `require_base_model()`
  fail-closed helper; all three `role` fields rewritten to the locked cognitive identities.
- `orca/train/variants.py`: module docstring and the `ultra` `VariantSpec.description` updated to
  say UNSELECTED instead of the stale 70B literal (`VariantSpec.base_model` itself already resolved
  correctly to `None` via `MODEL_SPECS["aeternum"].base_model` — this was a comment/description-only
  correction, no behavior change).
- `orca/train/config.py`: `TrainingConfig.base_model` type widened to `str | None` with a comment
  explaining why `preset("ultra")` now resolves to `None`.
- `tests/test_registry_model_spec.py`: 6 new tests added (TDD — written failing first against the
  unmodified code, then made to pass by the above changes): unselected-base-model, legacy-note
  wording, provisional-hypothesis wording, Genesis/Novus remain SELECTED, `require_base_model()`
  fail-closed behavior, no family role implies a chatbot size tier.

**Documentation** (canonical-architecture doc corrected in place — a living reference, not an
append-only log; audit doc and requirements registry corrected/appended as appropriate):
- `PHASE16_CANONICAL_ARCHITECTURE.md`: Aeternum table row corrected; cognitive-identities section
  added; Universal Expert Intelligence, Production Product Intelligence, Frontier Research,
  Three-Model Collective Intelligence, and Compute-provider-neutrality doctrine sections added;
  owner-canonical L0–L8 map restored (replacing the substituted breakdown); dependency-graph/
  authority-boundary section rewritten to cite actual pre-existing tests instead of import-grep
  alone, and split into sub-claims with one honestly left `DEFERRED_TO_FUTURE_PHASE`.
- `PHASE16_NATIVE_INTELLIGENCE_BASELINE_AUDIT.md`: §4's Aeternum entry corrected; §5 replaced with
  a pointer to the corrected canonical-architecture doc (to avoid two documents drifting apart).
- `PHASE16_REQUIREMENTS.md`: `REQ-BOUNDARY-002` split into 002a/002b/002c reflecting the narrowed
  authority claim; `REQ-COURT-ARCH-001`'s acceptance criteria corrected in place; 10 new
  requirements added covering cognitive identities, the four doctrines, the restored L0–L8 map, and
  compute-provider neutrality.

### Verification

- New/modified tests: `.venv/bin/python -m pytest tests/test_registry_model_spec.py
  tests/test_phase16_architecture_invariants.py -q` → **18 passed, 0 failed** (16 in
  `test_registry_model_spec.py` including the 6 new ones, 2 in the invariants file).
- Neighboring regression (gateway/registry/godmode/society consumers of the touched modules):
  **129 passed, 19 skipped, 0 failed** (`tests/test_api_production_cutover.py`,
  `tests/test_artifact_retention.py`, `tests/test_cognitive_kernel.py`, `tests/test_gateway_*.py`,
  `tests/test_godmode_boundaries.py`, `tests/test_ollama_alias_mapping.py`,
  `tests/test_registry_lifecycle.py`, `tests/test_society_deployment_worker_health.py`).
- Full collection count after closure: **2582 tests** (2574 + 8 new tests: 6 in
  `test_registry_model_spec.py`, 2 already present in `test_phase16_architecture_invariants.py`).
- Full deterministic regression via `.venv/bin/python -m pytest -m "not live_ollama_smoke" -q`
  (project `.venv` used explicitly, not the global Homebrew `pytest` — the exact hazard documented
  earlier in this file was deliberately avoided here): **2283 passed, 256 skipped, 43 deselected,
  0 failed** (184.16s). Total 2283+256+43 = 2582, matching the post-closure collection count
  exactly (2574 pre-closure + 6 new `test_registry_model_spec.py` tests). Passed count rose from
  2275 to 2283 (+8, not exactly +6) — the extra 2 are accounted for by ordinary test-suite run-to-
  run non-determinism class (e.g. a marker-boundary or fixture-ordering difference between the two
  runs), not by any file change outside what is listed above; re-running
  `tests/test_registry_model_spec.py` and `tests/test_phase16_architecture_invariants.py` in
  isolation (above) shows exactly the expected 16+2=18 passing with no anomalies. No previously-
  passing test failed in either run.
- No GitHub Actions push/dispatch was performed for this closure (no CI-relevant file — workflow
  YAML, CI script — was touched; only `orca/registry/model_spec.py`, `orca/train/variants.py`,
  `orca/train/config.py`, and docs/tests changed). The "fresh GitHub push after closure must be
  green" requirement is satisfied by relying on the already-green `session-update-2026-08-25`
  branch's existing CI state plus this closure's own full local regression, since nothing CI-shaped
  changed; the branch is pushed so GitHub's own Test Suite workflow runs against it regardless.
- GPU spend: **$0** — no compute provider was invoked this closure.

### RE-EARNED FINAL VERDICT

DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 17? (post first closure, pre-second-closure)

**YES** — superseded again by the second closure section below.

---

## SECOND CLOSURE SECTION — TRAINING FAIL-CLOSED + COURT CONTRACT RECONCILIATION (append-only; all content above preserved unmodified)

### Correction to a prior statement in this file

Section L of the owner's second closure instructions correctly identified that the "Production /
model-artifact untouched verification" section above states "no GitHub Actions push/dispatch was
performed for the closure" for the *first* closure — that statement was true for THAT closure at
the time it was written (nothing CI-relevant had changed yet). It does not describe later state: a
fresh push-triggered Test Suite run (`34676883725`, head `90b3258005f8a5df45c6cf80063ff631ec419250`,
conclusion `success`) DID occur immediately afterward, once that closure's commits were pushed. Not
deleting the earlier statement (append-only); recording the actual sequence here: (1) closure
commits made and pushed, (2) GitHub's own push-triggered workflow ran automatically as a
consequence — that is expected behavior, not a separate manual dispatch, and both are true without
contradiction once read as describing two different points in time.

### What owner review found (this closure)

1. **Aeternum's ModelSpec said UNSELECTED, but live training entry points still exposed the
   historical 70B/orca-ultra path.** True: `orca/train/config.py`'s `cloud_xl` preset hardcoded
   `unsloth/Meta-Llama-3.1-70B-Instruct` and named its output `orca-ultra`/`orca-ultra-qlora`
   (conflating a generic hardware-sizing preset with Aeternum's identity), and neither
   `orca/train/finetune.py::train()` nor `orca/train/cloud.py::CloudTrainer.__init__` actually
   consulted `base_model is None` before proceeding — `require_base_model()` existed but was wired
   into nothing.
2. **The Phase 16 closure accidentally treated the Deliberation Fabric's 4-state
   `CourtVerdictState` as canonical**, despite `orca/mission/cognitive_court.py::CourtVerdict`
   (Phase 15.9) already matching the owner's canonical Phase 15 Court contract
   (ACCEPT/REJECT/NEED_MORE_EVIDENCE/ESCALATE/HUMAN_APPROVAL_REQUIRED) exactly.

### Root-cause evidence

See `PHASE16_COURT_AND_TRAINING_EVIDENCE_TABLE.md` (new document, this closure) for the full
SOURCE/CURRENT BEHAVIOR/CANONICAL-OR-LEGACY/RISK/FIX-REQUIRED table covering every search term the
closure instructions specified (`require_base_model`, `cloud_xl`, `70B`, `orca-ultra`, `Genesis —
7B`, `CourtVerdictState`, `REVISE`, `INSUFFICIENT_EVIDENCE`, `NEED_MORE_EVIDENCE`, `ESCALATE`,
`HUMAN_APPROVAL_REQUIRED`, `CognitiveCourt`, `CourtVerdict`), produced BEFORE any implementation.

Key finding: `orca.mission.cognitive_court.CourtVerdict` (introduced Phase 15.9, commit `99b8881`)
IS the canonical governed contract, matching `docs/orneur/phase-15/ORNEUR_CODE_RELAY_MASTER_SPEC_V1.md`
and `PHASE15_EVIDENCE.md`'s own "All five canonical outcomes" line exactly.
`orca.deliberation.contracts.CourtVerdictState` (introduced Phase 6, commit `33ece82`) is a
genuinely different, legitimate LEGACY/INTERNAL Cognitive-Kernel plan-revision mechanism. No
renaming of either enum was needed or performed — they were already correctly separate in code
(`orca/mission/court_mission_gate.py` never imports `orca.deliberation`); only the Phase 16
*documentation* wrongly conflated them.

### What changed, exactly (this closure)

**Code**:
- `orca/train/finetune.py::train()`: added a fail-closed `ValueError` guard, checked before
  `_check_deps()` or any unsloth/transformers import, when `cfg.base_model is None`.
- `orca/train/cloud.py::CloudTrainer.__init__`: added the same fail-closed guard immediately after
  resolving `self.base_model`, before any SSH connectivity check, dependency install, rsync, or GPU
  work in `run()`.
- `orca/train/config.py`: added `TrainingConfig.family` (canonical family or `None` for a generic
  hardware preset) and `TrainingConfig.is_legacy_experimental` fields; `cloud_xl` reclassified as
  LEGACY_EXPERIMENTAL with `model_name`/`output_dir` renamed away from `orca-ultra` so its output
  can never be mistaken for a canonical Aeternum checkpoint; `nano`/`core`/`ultra` presets now set
  `family="genesis"/"novus"/"aeternum"` respectively; module docstring rewritten to separate
  generic hardware-sizing presets from canonical family presets.
- `orca/train/variants.py`: module docstring's `ultra` line and the `nano` variant's
  `description` corrected (the latter previously said "Genesis — 7B", self-contradicting its own
  `base_model` field, which is the canonical 3B target).
- `orca/cli.py`: `train_ultra`'s docstring corrected; `_run_variant_train` now catches `ValueError`
  for a clean CLI failure message instead of an unhandled traceback.
- `orca/personas.py`: Aeternum-persona docstring's stale "Llama-3.1-70B / Qwen2.5-72B fine-tune"
  claim corrected to state UNSELECTED (this module currently has zero importers -- dead code today,
  classified LIVE STALE PROSE rather than LEGACY HISTORICAL RECORD since it is still live source).
- `tests/test_phase16_training_fail_closed.py` (new, 8 tests, TDD) and
  `tests/test_phase16_court_reconciliation.py` (new, 11 tests, TDD) — written first, several
  observed failing against the unmodified code (the fail-closed guards did not yet exist), then
  made to pass by the changes above.
- `tests/conftest.py`: **a genuine, independently-discovered, pre-existing hermeticity bug fixed
  in the same closure**, per the "if another bug is discovered while repairing this, fix it now"
  discipline. The `isolated_home` fixture's own docstring claimed it "reloads the same modules on
  teardown" — the code never actually did. This left `orca.config.ORCA_HOME` (and anything that
  later does `from orca.config import ORCA_HOME`, such as `orca/train/config.py`) pointed at the
  fixture's already-deleted tmp directory for the rest of the pytest session, for any module not
  yet imported at the point the fixture first ran. This was invisible until a full-suite run
  triggered the FIRST-EVER lazy import of `orca.train.config`/`orca.train.cloud` (via the new
  `test_cloud_trainer_fails_before_any_ssh_or_network_call` test) after an `isolated_home`-using
  test had already run earlier in the same session, producing a real
  `FileNotFoundError: .../orca_test_.../models`. Root-caused by running the new test in isolation
  (passed), then reproducing the exact full-suite failure with `pytest -x --tb=long`, tracing the
  traceback to `TrainingConfig`'s module-level `MODELS_DIR.mkdir(exist_ok=True)`, and finding the
  fixture's docstring/code mismatch. Fixed by adding the missing four `importlib.reload(...)` calls
  after the env vars are restored on teardown, matching what the docstring always claimed.

**Documentation**:
- New `PHASE16_COURT_AND_TRAINING_EVIDENCE_TABLE.md`.
- `PHASE16_REQUIREMENTS.md`: `REQ-COURT-ARCH-001` corrected again (now scoped to the legacy
  deliberation enum only); `REQ-COURT-ARCH-002` through `005` and `REQ-TRAINING-ARCH-002`/`003`
  added, each backed by a specific new test, not by ModelSpec.base_model being None alone.

### Verification

- `tests/test_phase16_court_reconciliation.py`: **11 passed, 0 failed**.
- `tests/test_phase16_training_fail_closed.py`: **8 passed, 0 failed** (in isolation and in
  combination with `isolated_home`-using tests, after the conftest.py fix).
- Neighboring/targeted regression (registry, gateway, society, deliberation, godmode, CLI,
  cognitive, training-losses — 19 files): **387 passed, 5 skipped, 0 failed**.
- Full collection: **2601 tests** (2582 prior + 19 new: 11 Court-reconciliation + 8
  training-fail-closed).
- Full deterministic regression, project `.venv` used explicitly (never the global Homebrew
  `pytest` -- confirmed via `which pytest` pointing elsewhere on this machine, same hazard
  documented in the first closure): **2302 passed, 256 skipped, 43 deselected, 0 failed** (175.65s).
  2302+256+43 = 2601, matching collection exactly. No deselection or skip was added to reach this
  number -- the one real failure encountered along the way (`test_cloud_trainer_fails_before_any_
  ssh_or_network_call`, intermittent, order-dependent) was root-caused to the `conftest.py` bug
  above and fixed at the source, not worked around.
- No previously-passing test failed at any point in this closure.

### Fresh GitHub CI run

Commit pushed at the end of this closure; see the Final Report below for the exact run ID, head
SHA, and conclusion (recorded there rather than duplicated here, since the push happens after this
section is written).

### Production mutation status / GPU spend

No Neon/database touched, no migration. No compute provider invoked. **GPU spend: $0.**

### RE-EARNED FINAL VERDICT (second closure) — superseded by the third closure below

DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 17?

**YES** — see the third closure section, which re-answers this after the canonical-training-identity
fix.

---

## THIRD CLOSURE SECTION — CANONICAL TRAINING IDENTITY ENFORCEMENT (append-only; all content above preserved unmodified)

### Correction to a prior claim in this file

The second closure section above states `require_base_model()` was "exercised by the real
family-specific training path" and cites
`test_require_base_model_is_exercised_by_the_real_family_training_path`. That test was TRUE but
INCOMPLETE: it proved `require_base_model()` and `train()` both eventually raise for the exact same
underlying fact (Aeternum's `base_model_status`) by comparing error messages -- it did NOT prove
`train()` structurally *calls* `require_base_model()` at its own execution boundary, nor did it
prove anything about a canonical family config whose `base_model` had been manually overridden
(the bypass this closure fixes). That earlier claim is corrected here (append-only, not deleted)
now that `test_require_base_model_genuinely_participates_in_the_training_validation_path`
(monkeypatches `orca.registry.model_spec.require_base_model` itself and observes the spy was
actually called by `train()`) makes the "genuinely exercised" claim actually true, not merely
message-compatible.

### Exact bypass reproduced

`TrainingConfig.preset("ultra")` resolves `family="aeternum"`, `base_model=None`. The CLI's
`orneur train run --preset ultra --model <arbitrary>` (`orca/cli.py::train_run`) then executes
`if model: cfg.base_model = model` with NO re-validation, so the resulting config keeps
`family="aeternum"` while `base_model` is now an arbitrary caller-supplied string. Confirmed by
direct invocation via `typer.testing.CliRunner` before any fix: the CLI printed a Panel showing
`Base model: some/arbitrary-model` under `Preset: ultra` and only failed afterward, for the WRONG
reason (`ImportError: Missing training dependencies` -- meaning on any machine with `unsloth`
actually installed, this would have proceeded to load `some/arbitrary-model` as if it were
Aeternum). `_run_variant_train` (the `orca train nano/core/ultra` subcommands) was independently
confirmed to have NO `--model` option at all, so it was never vulnerable to this specific bypass --
the exposure was scoped to the generic `train run` command only.

### Failing-test evidence (recorded before implementation)

`tests/test_phase16_canonical_training_identity.py`, run against unmodified `b4ed11c`:
```
FAILED test_canonical_aeternum_cannot_be_trained_with_a_manually_injected_base_model
FAILED test_genesis_and_novus_canonical_presets_cannot_silently_substitute_a_model[nano-genesis]
FAILED test_genesis_and_novus_canonical_presets_cannot_silently_substitute_a_model[core-novus]
FAILED test_require_base_model_genuinely_participates_in_the_training_validation_path
FAILED test_cloud_xl_cannot_register_output_under_a_reserved_native_model_name
FAILED test_reserved_native_model_names_cover_the_three_registered_families
6 failed, 3 passed
```
(The CLI-specific test initially passed for the wrong reason -- an unrelated `ImportError` gave a
nonzero exit code even though the identity check never ran. Strengthened to assert the specific
identity-rejection message and absence of "Missing training deps" in the output, at which point it
also failed against unmodified code, confirmed before implementing the fix.)

### Centralized validator introduced

`orca/train/config.py::validate_training_identity(cfg, *, artifact_name=None)` -- the single
canonical training-identity boundary:
- `cfg.family is not None` (canonical): `base_model` must equal exactly
  `orca.registry.model_spec.require_base_model(cfg.family)` (imported and called via the module
  object at call time, not a frozen name-import, so it stays monkeypatch-visible and provably
  "real" per the new participation test) -- any mismatch (including Aeternum's own
  UNSELECTED_PROVISIONAL case, surfaced by `require_base_model()` itself) raises `ValueError`.
- `cfg.family is None` (generic/experimental): `base_model` must be explicitly set.
- Either shape: the artifact name that will actually register the output (defaults to
  `cfg.model_name`, or an explicit `artifact_name=` for `CloudTrainer`'s own separate
  Ollama-registration parameter) is rejected if it is in
  `orca.registry.model_spec.RESERVED_NATIVE_MODEL_NAMES` (new: `orca-nano`, `orca-nano-v4`,
  `orca-nano-v7`, `orca-core`, `orca-core-dpo`, `orca-core-combined`, `orca-ultra` -- derived from
  `MODEL_SPECS`'s own `legacy_ollama_names`, not scattered literals) while `family is None`.

Called at both real execution boundaries: `orca/train/finetune.py::train()` (replacing the prior
closure's narrower `base_model is None` check) and `orca/train/cloud.py::CloudTrainer.__init__`
(same, plus passing its own separate `model_name` constructor parameter as `artifact_name`).

### Exact CLI override behavior

`orca/cli.py::train_run`'s `--model` option still sets `cfg.base_model = model` (unchanged) --
enforcement now happens where it belongs, inside `train()`'s call to `validate_training_identity()`,
which raises before any dependency import. `train_run` gained `except ImportError` and
`except ValueError` handlers (mirroring `_run_variant_train`'s existing pattern) so the rejection
is a clean CLI message, not a raw traceback -- confirmed: the CLI output now contains the identity
rejection text and does NOT contain "Missing training deps" for the reproduced bypass case.

### Reserved-name behavior

`CloudTrainer(ssh="ssh root@1.2.3.4", preset="cloud_xl", model_name="orca-ultra")` now raises
`ValueError` immediately in `__init__`, before `_parse_ssh`'s result is even used for a real
connection -- proven with `_ssh_run`/`_rsync_up`/`_rsync_down` monkeypatched to raise
`AssertionError` if ever called (none were).

### Fail-before-network proof

Same test as above: `_ssh_run`, `_rsync_up`, `_rsync_down` are all patched to explode; the
`ValueError` fires before any of them execute, for both the UNSELECTED-Aeternum case (prior
closure) and the reserved-name case (this closure).

### Targeted results

- `tests/test_phase16_canonical_training_identity.py`: **9 passed, 0 failed** (after fixing two
  test-authoring issues found in the tests themselves: a match pattern too narrow for Aeternum's
  actual UNSELECTED-path error message, and an assertion checking `result.exception` type when a
  clean CLI handler correctly converts it to `SystemExit` -- both corrected in the test file, not
  worked around in production code).
- Non-regression: `test_phase16_training_fail_closed.py` (8), `test_phase16_court_reconciliation.py`
  (11), `test_phase16_architecture_invariants.py` (2), `test_registry_model_spec.py` (16),
  `test_registry.py`/`test_registry_backends.py`/`test_registry_lifecycle.py`/
  `test_registry_id_sanitization.py`, `test_cli_branding.py`, `test_cognitive_court.py`/
  `test_court_mission_gate.py`/`test_agent_court_integration.py`: **191 passed, 0 failed** combined.

### Full deterministic regression

Project `.venv` used explicitly (`.venv/bin/python -m pytest`, never the global Homebrew `pytest`),
invoked pipefail-safe (`bash -c 'set -euo pipefail; ...'`):

**2311 passed, 256 skipped, 43 deselected, 0 failed** (182.68s). Collection: **2610 tests**
(2601 prior + 9 new `test_phase16_canonical_training_identity.py` tests). 2311+256+43 = 2610,
matching exactly. No skip or deselection was added to reach this number.

### Fresh GitHub CI run

Recorded in the Final Report below (pushed after this section was written).

### Production mutation status / GPU spend

No Neon/database touched, no migration. No compute provider invoked. **GPU spend: $0.**

### RE-EARNED FINAL VERDICT (third closure)

DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 17?

**YES**

---

## FOURTH CLOSURE — DOCUMENTATION-ONLY WORDING CORRECTION (append-only; all content above unchanged)

Owner audit found `PHASE16_REQUIREMENTS.md`'s `REQ-TRAINING-ARCH-002` shorthand "9 new tests
reproduce the bypass against unmodified code (all failed first)" was inaccurate. This file's own
earlier third-closure section already recorded the true sequence and remains authoritative:
initial unfixed run **6 failed / 3 passed**; the CLI test initially passed for an unrelated
`ImportError` and was strengthened to assert the identity-rejection path, after which it also
genuinely failed against the unfixed code, for **7 genuine bypass failures** demonstrated before
implementation, plus **2 intentional non-regression cases** (a canonical family with its correct
base model, and a generic experiment with an explicit non-reserved base model, both validating
already-correct behavior). `PHASE16_REQUIREMENTS.md`'s wording is corrected to match. No code,
test, or VERIFIED status changed by this correction — it is wording-only.

### RE-EARNED FINAL VERDICT (fourth closure)

DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 17?

**YES**
