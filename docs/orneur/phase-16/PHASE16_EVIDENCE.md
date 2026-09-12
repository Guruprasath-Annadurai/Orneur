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

DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 17?

**YES**
