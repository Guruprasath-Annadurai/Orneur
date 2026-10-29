"""FOUNDATION-02 verification-probe honesty rules.

Engineering VERIFIED status requires actual passing tests. Exit code 0 alone
is insufficient. Zero-collected, skip-only, mixed pass/skip, and xfail-only
probes must not become PASS. Machine-specific interpreter / site-package
paths are refused. Acceptance-producing probes require complete, matching
candidate SHAs.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

# Absolute workstation paths that must never be baked into probe commands
# or PYTHONPATH by the evidence builder.
_FORBIDDEN_PATH_FRAGMENTS = (
    "/home/ubuntu/",
    "/Users/",
    "/workspace/.venv",  # absolute cloud-agent path; relative .venv is OK
)

_COUNT_TOKEN_RE = re.compile(
    r"(?P<n>\d+)\s+(?P<label>passed|failed|skipped|xfailed|xpassed|errors?)\b"
)
_COLLECTED_RE = re.compile(r"collected\s+(\d+)\s+items?")
_NO_TESTS_RAN_RE = re.compile(r"no tests ran", re.IGNORECASE)
# Complete git commit identity: full 40-char lowercase/uppercase hex SHA-1.
_COMPLETE_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class PytestCounts:
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    xfailed: int | None = None
    xpassed: int | None = None
    errors: int | None = None
    collected: int | None = None
    summary_line: str | None = None
    parseable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProbeVerdict:
    passed_probe: bool
    reason: str
    counts: PytestCounts
    refusal_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["refusal_codes"] = list(self.refusal_codes)
        d["counts"] = self.counts.to_dict()
        return d


def resolve_python(root: Path, *, environ: Mapping[str, str] | None = None) -> str:
    """Prefer a repo-local virtualenv relative to *root*; else ``sys.executable``.

    Never hard-codes ``/workspace/...`` or a specific user's home directory.
    """
    del environ  # reserved for future ORNEUR_PYTHON override policy
    candidates = (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return sys.executable


def build_probe_env(root: Path, *, base_environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Construct a portable probe environment.

    PYTHONPATH is set to the repository root only. Inherited PYTHONPATH and
    PYTEST_ADDOPTS are wiped so host site-packages or addopts cannot shadow
    the candidate under test.
    """
    env = dict(os.environ if base_environ is None else base_environ)
    env["PYTHONPATH"] = str(root.resolve())
    env.pop("PYTEST_ADDOPTS", None)
    return env


def assert_command_portable(command: list[str]) -> None:
    """Raise ``ValueError`` if a probe command embeds forbidden absolute paths."""
    joined = " ".join(command)
    for frag in _FORBIDDEN_PATH_FRAGMENTS:
        # Allow relative ".venv/bin/python" after resolve under root; forbid
        # the absolute cloud path fragment only when it appears literally.
        if frag in joined:
            raise ValueError(f"non-portable path fragment in probe command: {frag!r}")


def parse_pytest_summary(stdout: str, stderr: str = "") -> PytestCounts:
    """Parse pytest ``-q`` summary counts, including xfailed / xpassed."""
    combined = f"{stdout}\n{stderr}"
    collected_match = _COLLECTED_RE.search(combined)
    collected = int(collected_match.group(1)) if collected_match else None
    if _NO_TESTS_RAN_RE.search(combined) and collected is None:
        collected = 0

    summary_line: str | None = None
    for line in reversed(combined.splitlines()):
        if _COUNT_TOKEN_RE.search(line):
            summary_line = line.strip()
            break
    if summary_line is None:
        return PytestCounts(collected=collected, parseable=False)

    counts: dict[str, int] = {}
    for match in _COUNT_TOKEN_RE.finditer(summary_line):
        label = match.group("label")
        if label.startswith("error"):
            label = "errors"
        counts[label] = int(match.group("n"))

    return PytestCounts(
        passed=counts.get("passed"),
        failed=counts.get("failed"),
        skipped=counts.get("skipped"),
        xfailed=counts.get("xfailed"),
        xpassed=counts.get("xpassed"),
        errors=counts.get("errors"),
        collected=collected,
        summary_line=summary_line,
        parseable=bool(counts),
    )


def normalize_candidate_sha(value: str | None) -> str | None:
    """Return stripped SHA text, or ``None`` when absent/empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def is_complete_candidate_sha(value: str | None) -> bool:
    """True iff *value* is a complete 40-hex commit identity."""
    normalized = normalize_candidate_sha(value)
    if normalized is None:
        return False
    return bool(_COMPLETE_SHA_RE.fullmatch(normalized))


def classify_probe(
    *,
    exit_code: int,
    stdout: str,
    stderr: str = "",
    missing_implementation: list[str] | None = None,
    missing_tests: list[str] | None = None,
    expected_candidate_sha: str | None = None,
    recorded_candidate_sha: str | None = None,
) -> ProbeVerdict:
    """Decide whether a probe may become VERIFIED_ENGINEERING evidence.

    Acceptance-producing probes must supply valid, complete expected and
    recorded commit identities. Any skipped mandatory test refuses the probe,
    including mixed pass/skip suites.
    """
    counts = parse_pytest_summary(stdout, stderr)
    refusals: list[str] = []
    missing_implementation = missing_implementation or []
    missing_tests = missing_tests or []

    expected = normalize_candidate_sha(expected_candidate_sha)
    recorded = normalize_candidate_sha(recorded_candidate_sha)

    if expected is None or recorded is None:
        refusals.append("CANDIDATE_SHA_MISSING")
    else:
        if not is_complete_candidate_sha(expected) or not is_complete_candidate_sha(recorded):
            refusals.append("CANDIDATE_SHA_MALFORMED")
        elif expected.lower() != recorded.lower():
            refusals.append("CANDIDATE_SHA_MISMATCH")

    if missing_implementation:
        refusals.append("MISSING_IMPLEMENTATION")
    if missing_tests:
        refusals.append("MISSING_TESTS")
    if exit_code != 0:
        refusals.append("NONZERO_EXIT")
    if not counts.parseable:
        refusals.append("UNPARSEABLE_SUMMARY")
    if counts.collected == 0:
        refusals.append("ZERO_COLLECTED")
    if (counts.failed or 0) > 0:
        refusals.append("FAILURES_PRESENT")
    if (counts.errors or 0) > 0:
        refusals.append("ERRORS_PRESENT")
    if (counts.xpassed or 0) > 0:
        refusals.append("XPASSED_PRESENT")

    passed = counts.passed or 0
    skipped = counts.skipped or 0
    xfailed = counts.xfailed or 0

    # Any skip in a mandatory qualification suite refuses VERIFIED evidence.
    if counts.parseable and skipped > 0:
        if passed == 0 and (counts.failed or 0) == 0:
            refusals.append("SKIP_ONLY")
        refusals.append("SKIPS_PRESENT")

    if counts.parseable and passed == 0 and xfailed > 0 and skipped == 0 and (counts.failed or 0) == 0:
        refusals.append("XFAIL_ONLY")
    if counts.parseable and passed == 0 and skipped == 0 and xfailed == 0 and (counts.failed or 0) == 0:
        # e.g. "no tests ran" with parseable empty, or "0 passed"
        if counts.passed == 0 or counts.collected == 0:
            refusals.append("NO_PASSES")

    if passed < 1:
        if "NO_PASSES" not in refusals and "SKIP_ONLY" not in refusals and "XFAIL_ONLY" not in refusals:
            refusals.append("NO_PASSES")

    if refusals:
        return ProbeVerdict(
            passed_probe=False,
            reason=";".join(refusals),
            counts=counts,
            refusal_codes=tuple(refusals),
        )

    # Honest PASS: at least one real pass; zero skips; xfailed residuals may
    # coexist but are recorded separately and are never treated as passes.
    reason = f"PASS passed={passed}"
    if xfailed:
        reason += f" xfailed={xfailed} (expected failures distinguished, not counted as PASS)"
    return ProbeVerdict(
        passed_probe=True,
        reason=reason,
        counts=counts,
        refusal_codes=(),
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_digests(root: Path, relative_paths: list[str]) -> dict[str, str]:
    """Return sha256 digests for existing implementation paths (missing omitted)."""
    out: dict[str, str] = {}
    for rel in relative_paths:
        p = root / rel
        if p.is_file():
            out[rel] = file_sha256(p)
    return out


def lockfile_digest(root: Path) -> dict[str, str]:
    """Record reproducible-environment lock identity when present."""
    locks = {
        "uv.lock": root / "uv.lock",
        "pyproject.toml": root / "pyproject.toml",
    }
    result: dict[str, str] = {}
    for name, path in locks.items():
        if path.is_file():
            result[name] = file_sha256(path)
    return result
