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
# separate torch-loss-tests job instead of polluting this shared process;
# test_independent_adversarial_dlp.py's external candidate dependency runs in
# the dedicated dual-worktree qualification runner scripts/qualification/run_b01_qualification.py):
# run the sentinel file in genuine isolation, in its own process, BEFORE
# anything else has a chance to import a forbidden package -- then run
# everything else. Both invocations' exit codes are checked explicitly
# (not masked by `tee`, per this script's own original fix above).

pytest tests/test_trainprep_sentinel.py -v 2>&1 | tee /tmp/pytest-sentinel-log.txt
pytest -m "not live_ollama_smoke" --ignore=tests/test_trainprep_sentinel.py --ignore=tests/qualification/test_independent_adversarial_dlp.py -v 2>&1 | tee /tmp/pytest-log.txt
