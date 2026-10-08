#!/usr/bin/env bash
# REVIEW_REFERENCE_ONLY. Requires python3 with the 'cryptography' package. Writes ocr1_v2_independent_vectors.json here.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" check_rfc9180_a2.py
"$PY" gen_vectors.py
