#!/usr/bin/env python3
"""G-020 before/after: run the agent-tool-authority tests and print one line per test.

    python scripts/security/g020_repro.py                                  # fixed tree
    git stash push -- orca && python scripts/security/g020_repro.py; git stash pop   # original source, same tests
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = "tests/test_g020_agent_tool_authority.py"


def main() -> int:
    proc = subprocess.run([sys.executable, "-m", "pytest", TESTS, "-q", "-p", "no:cacheprovider", "--tb=no", "-rA"], cwd=ROOT, capture_output=True, text=True)
    rows = []
    for line in proc.stdout.splitlines():
        m = re.match(r"^(PASSED|FAILED|XFAIL|XPASS|ERROR) tests/\S+::(\S+)", line)
        if m:
            rows.append((m.group(1), m.group(2)))
    verdict = {"PASSED": "secure", "FAILED": "EXPLOITABLE/UNSUPPORTED", "XFAIL": "KNOWN-UNFIXED", "XPASS": "FIXED-REMOVE-XFAIL", "ERROR": "HARNESS-ERROR"}
    for status, name in sorted(rows, key=lambda r: r[1]):
        print(f"{verdict[status]:<24} {name}")
    counts: dict[str, int] = {}
    for status, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    print("\n" + ", ".join(f"{verdict[k]}={v}" for k, v in sorted(counts.items())))
    return 0 if not any(s in ("FAILED", "ERROR") for s, _ in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
