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

## DOES EVIDENCE SUPPORT PROGRESSION TO PHASE 17?

**YES**
