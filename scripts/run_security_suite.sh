#!/usr/bin/env bash
# Authoritative platform security regression (Phase 9.1 spec §3).
# Runs every file listed in docs/orneur/phase-9/security_suite_files.txt --
# the curated, reviewed security-relevant test inventory (62 files as of
# Phase 9.1), not a filename-pattern guess or a nonexistent pytest marker.
set -euo pipefail
cd "$(dirname "$0")/.."
FILE_LIST="docs/orneur/phase-9/security_suite_files.txt"
LIVE_FLAG="${1:-}"

MARKER_EXPR="not live_ollama_smoke"
if [ "$LIVE_FLAG" = "--live" ]; then
    MARKER_EXPR="live_ollama_smoke"
fi

.venv/bin/python -m pytest -m "$MARKER_EXPR" -p no:cacheprovider -q $(paste -sd' ' "$FILE_LIST")
