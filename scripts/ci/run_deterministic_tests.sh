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

pytest -m "not live_ollama_smoke" -v 2>&1 | tee /tmp/pytest-log.txt
