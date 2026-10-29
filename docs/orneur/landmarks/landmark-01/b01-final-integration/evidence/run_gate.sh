#!/usr/bin/env bash
# Runs the repository's own deterministic gate from a clean worktree (see scripts/ci/run_deterministic_tests.sh).
set -uo pipefail
export PATH="/home/pc/projects/Orneur/.venv/bin:/home/pc/projects/.journey-tools/node-v22.11.0-linux-x64/bin:$PATH"
unset PYTHONDONTWRITEBYTECODE
cd /home/pc/projects/Orneur-b01-gate
git rev-parse HEAD
bash scripts/ci/run_deterministic_tests.sh
echo "GATE_EXIT=$?"
