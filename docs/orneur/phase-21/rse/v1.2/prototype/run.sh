#!/usr/bin/env bash
# PROTOTYPE_ONLY test command. Needs python3 and node. Writes only to a temp dir.
set -euo pipefail
d="$(cd "$(dirname "$0")" && pwd)"
t="$(mktemp -d)"
trap 'rm -rf "$t"' EXIT
python3 "$d/ocr1_ref.py" "$t/cases.json" | tee "$t/py.out"
node "$d/ocr1_ref.js" "$t/cases.json" | tee "$t/js.out"
pa="$(grep verdict_digest "$t/py.out" | awk '{print $3}')"
ja="$(grep verdict_digest "$t/js.out" | awk '{print $3}')"
if [ "$pa" = "$ja" ]; then echo "disagreements 0"; else echo "disagreements DIGEST_MISMATCH"; exit 1; fi
python3 "$d/json_contrast.py"
node "$d/json_contrast.js"
