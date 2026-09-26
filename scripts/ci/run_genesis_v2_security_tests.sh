#!/usr/bin/env bash
# Mandatory exact-SHA security job for Genesis Capability Eval V2: the private-corpus encryption/ledger/privacy tests must EXECUTE (zero skips).
set -euo pipefail
export ORNEUR_REQUIRE_CRYPTOGRAPHY=1
python -c "import cryptography.hazmat.primitives.ciphers.aead as a; a.AESGCM(bytes(32)); print('cryptography OK')"
out=$(mktemp)
pytest -q -rs -p no:cacheprovider tests/test_genesis_v2_privacy.py tests/test_genesis_v2_storage.py tests/test_genesis_v2_ledger.py \
  tests/test_genesis_v2_contamination.py tests/test_genesis_v2_integrity.py 2>&1 | tee "$out"
if grep -Eq "[0-9]+ (skipped|xfailed|deselected)" "$out"; then
  echo "::error::security suite had skipped/xfailed/deselected tests; encryption and privacy tests must execute"
  exit 1
fi
