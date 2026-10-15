#!/usr/bin/env python3
"""Validate docs/orneur/ci/RECONCILED_TEST_WORKFLOW_PREVIEW.yml.

Confirms the non-live reference preview actually is what the three
contributing branches (PR #12, PR #13, the cursor/claude chain ending in
PR #16) each independently inserted at the same anchor points in
.github/workflows/test.yml, without silently dropping one side the way a
careless manual conflict resolution could. See
docs/orneur/ci/CI_WORKFLOW_INTEGRATION_RECONCILIATION.md for the full
report this supports.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PREVIEW_PATH = ROOT / "docs" / "orneur" / "ci" / "RECONCILED_TEST_WORKFLOW_PREVIEW.yml"

EXPECTED_PUSH_BRANCHES = {
    "main",
    "session-update-2026-08-25",
    "phase14b-*",
    "cursor/**",
    "claude/**",
    "docker/**",
}
EXPECTED_PULL_REQUEST_BRANCHES = {"main", "session-update-2026-08-25"}
EXPECTED_JOBS = {
    "pytest",
    "torch-loss-tests",
    "container-build",
    "sse-diagnostics",
    "genesis-v2-security",
    "genesis-v2-sandbox",
    "security-audit",
    "rse-docker-lab",
    "rse-dependency-audit",
}


def validate(text):
    errors = []
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        return ["preview is not a YAML mapping"]
    on = doc.get(True, doc.get("on"))
    if on is None:
        return ["missing top-level 'on' key"]
    push_branches = set(on.get("push", {}).get("branches", []))
    if push_branches != EXPECTED_PUSH_BRANCHES:
        errors.append(
            f"push branches {sorted(push_branches)} != {sorted(EXPECTED_PUSH_BRANCHES)}"
        )
    pr_branches = set(on.get("pull_request", {}).get("branches", []))
    if pr_branches != EXPECTED_PULL_REQUEST_BRANCHES:
        errors.append(
            f"pull_request branches {sorted(pr_branches)} != {sorted(EXPECTED_PULL_REQUEST_BRANCHES)}"
        )
    jobs = set(doc.get("jobs", {}).keys())
    if jobs != EXPECTED_JOBS:
        errors.append(f"jobs {sorted(jobs)} != {sorted(EXPECTED_JOBS)}")
    for job_id in EXPECTED_JOBS & jobs:
        job = doc["jobs"][job_id]
        if not job.get("steps"):
            errors.append(f"{job_id} has no steps")
    return errors


def main():
    text = PREVIEW_PATH.read_text(encoding="utf-8")
    errors = validate(text)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"preview OK: {len(EXPECTED_JOBS)} jobs, {len(EXPECTED_PUSH_BRANCHES)} push branch globs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
