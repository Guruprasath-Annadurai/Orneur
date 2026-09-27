#!/usr/bin/env bash
# Mandatory sandbox CI job for Genesis Capability Eval V2: containment tests MUST run against a real Docker daemon (zero skips). No model code is executed;
# the hostile programs are fixtures written by the test suite.
set -euo pipefail
export ORNEUR_REQUIRE_DOCKER=1
docker version --format 'docker server {{.Server.Version}}'
docker image inspect python:3.11-slim >/dev/null 2>&1 || docker pull python:3.11-slim
out=$(mktemp)
pytest -q -rs -p no:cacheprovider tests/test_genesis_v2_sandbox_policy.py tests/test_genesis_v2_sandbox_containment.py 2>&1 | tee "$out"
if grep -Eq "[0-9]+ (skipped|xfailed|deselected)" "$out"; then
  echo "::error::sandbox suite had skipped tests; containment tests must execute"
  exit 1
fi
