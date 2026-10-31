#!/usr/bin/env bash
# Phase 15.15 CI truthfulness closure.
#
# The canonical deterministic-test CI step previously ran:
#
#   pytest -m "not live_ollama_smoke" -v 2>&1 | tee /tmp/pytest-log.txt
#
# as a plain `run:` block with no explicit `shell:` key. GitHub Actions'
# TRUE default shell in that case is `bash -e {0}` -- NOT `bash -eo
# pipefail {0}` (that stronger default only applies when `shell: bash`
# is given EXPLICITLY). Without `pipefail`, a pipeline's exit status is
# the LAST command's (`tee`, which always exits 0 as long as it can
# write its file) -- so a pytest COLLECTION failure (exit code 2) was
# silently swallowed and the step, and therefore the whole job, was
# reported SUCCESS. This is exactly what happened on run 34632529810:
# three real collection errors (missing openai/mcp/torch), yet a green
# check.
#
# This script is the single source of truth for how the deterministic
# suite is invoked in CI -- `set -euo pipefail` here means pytest's
# real exit code always propagates, through `tee` or not, regardless
# of what shell default the calling workflow step happens to use.
set -euo pipefail

# P0 remediation (2026-10-14): tests/test_trainprep_sentinel.py's
# test_the_pytest_process_has_no_trainer_packages_loaded_and_no_hook_active
# asserts that THIS pytest process has never imported a FORBIDDEN_TOP_LEVEL
# package (torch, transformers, tokenizers, ...) -- a real, load-bearing
# guarantee about the training dry-run sentinel's own hygiene, not a stray
# flake. Adding the `memory` extra to this job's install (same commit, to
# close the reopened G-025 privacy gap) transitively pulls in `tokenizers`
# via chromadb's default embedding function the first time ANY test
# constructs a real chromadb-backed LongTermMemory/DocStore -- and once
# imported, it stays in sys.modules for the rest of this one process,
# failing the hygiene check for every test file after whichever one
# imports chromadb first, regardless of execution order. This was found
# live on this exact commit's own CI run, not anticipated in advance.
#
# Fix, matching this file's own established precedent for the identical
# class of problem (test_train_losses.py's torch dependency runs in the
# separate torch-loss-tests job instead of polluting this shared process):
# run the sentinel file in genuine isolation, in its own process, BEFORE
# anything else has a chance to import a forbidden package -- then run
# everything else. Both invocations' exit codes are checked explicitly
# (not masked by `tee`, per this script's own original fix above).

# Antigravity Audit #71 CI closure (2026-10-17): tests/test_audit_genesis_hardening_adversarial.py
# is an EXACT, unmodified import of Antigravity's independent adversarial audit's own
# vulnerability-demonstration test file (preserved verbatim for provenance -- see
# docs/orneur/status/ORNEUR_AUDIT71_REMEDIATION_ENGINEERING_REPORT.md). It has two properties
# that make it unsuitable for this job's normal, pass/fail-gated, broad collection:
#   1. Its P0 tests now INTENTIONALLY fail post-remediation (each one asserted the VULNERABLE
#      behavior; the fix makes that assertion false by design -- a real test failure here would
#      mean the vulnerability came BACK, not that anything is wrong today).
#   2. It has no `pytest.importorskip("torch")` guard (unlike every test file this repository's
#      own test suite writes for torch-dependent code) -- it unconditionally imports
#      orca.genesis.training.orchestration, which imports torch transitively, and this job's
#      environment does not install torch. Without a guard, that is a hard COLLECTION ERROR
#      (not a skip), which aborts this job's entire test run -- not merely one file's results.
# The corrected, secure-behavior counterpart (tests/test_audit_genesis_hardening_remediation.py,
# written by this repository, WITH the standard importorskip guard) stays fully inside normal
# CI collection below and is what this job's green/red status actually reflects for Audit #71.
#
# Antigravity Audit #074 CI closure (2026-10-18): same exact situation,
# same exact reason -- tests/test_native_learning_engine_adversarial_audit.py
# (the imported, verbatim Native Learning Engine audit evidence) has no
# importorskip("torch") guard and its P0 tests now intentionally fail
# post-remediation. Excluded from this job for the identical reasons as
# the Audit #71 file above.
pytest tests/test_trainprep_sentinel.py -v 2>&1 | tee /tmp/pytest-sentinel-log.txt
# LANDMARK-03: the vector-service tests start real owner processes and real chromadb; with the rest of the suite they pushed this job past its 25-minute limit (run 41187453633 was
# cancelled at the limit). They run, unchanged, in the Journeys job (real servers, 45-minute limit) -- see .github/workflows/test.yml.
# MASTER-03: keep the adversarial-audit ignores that must not run in this job.
pytest -m "not live_ollama_smoke" \
  --ignore=tests/test_trainprep_sentinel.py \
  --ignore=tests/test_audit_genesis_hardening_adversarial.py \
  --ignore=tests/test_native_learning_engine_adversarial_audit.py \
  --ignore=tests/test_l03_vector_service.py \
  --ignore=tests/test_l03_lifecycle.py \
  --ignore=tests/test_l03_failure_lab.py \
  -v 2>&1 | tee /tmp/pytest-log.txt
