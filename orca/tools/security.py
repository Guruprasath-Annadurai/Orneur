"""
Orca Security Scan Tool — real static analysis, sandboxed to the workspace.

Two real checks, not a marketing claim:
1. Python files: runs `bandit` (the standard Python SAST tool) and parses
   its JSON output into a structured summary.
2. All text files (any language, including mobile — Swift, Kotlin, Dart,
   JS/TS): a portable regex scan for hardcoded secrets (API keys, private
   key headers, AWS credentials, generic high-entropy assignment patterns).
   This is deliberately NOT a claim of comprehensive multi-language SAST —
   bandit only understands Python. Non-Python findings here are limited to
   secret-pattern matches, not full vulnerability classes (SQLi, XSS, etc.)
   — that honest scope boundary matters more than a bigger-sounding claim.

Sandboxed identically to read_file/write_file (orca/tools/__init__.py's
_resolve_in_workspace) — a caller cannot point this at an arbitrary
filesystem path outside WORKSPACE_DIR.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_BANDIT_TIMEOUT = 30

# Portable secret patterns — deliberately conservative (few false positives)
# over exhaustive. Each tuple is (label, compiled regex).
_SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Private key header", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("Generic API key assignment", re.compile(
        r"""(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*["'][A-Za-z0-9_\-]{20,}["']"""
    )),
    ("Slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
]

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


@dataclass
class SecurityFinding:
    file: str
    line: int
    severity: str
    label: str
    detail: str


@dataclass
class ScanResult:
    files_scanned: int
    findings: list[SecurityFinding] = field(default_factory=list)
    bandit_ran: bool = False
    bandit_error: str | None = None

    def format(self) -> str:
        if not self.findings:
            base = f"Scanned {self.files_scanned} file(s) — no findings."
        else:
            by_sev: dict[str, list[SecurityFinding]] = {}
            for f in self.findings:
                by_sev.setdefault(f.severity, []).append(f)
            lines = [f"Scanned {self.files_scanned} file(s) — {len(self.findings)} finding(s):"]
            for sev in sorted(by_sev, key=lambda s: _SEVERITY_ORDER.get(s, 99)):
                lines.append(f"\n{sev}:")
                for f in by_sev[sev]:
                    lines.append(f"  {f.file}:{f.line} — {f.label}: {f.detail}")
            base = "\n".join(lines)
        if self.bandit_error:
            base += f"\n\n[bandit unavailable: {self.bandit_error} — Python AST checks skipped, secret-pattern scan still ran]"
        return base


def _iter_text_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files = []
    for p in root.rglob("*"):
        if p.is_file() and p.stat().st_size < 2_000_000:  # skip anything >2MB, not source code
            files.append(p)
    return files


def _scan_secrets(files: list[Path]) -> list[SecurityFinding]:
    findings = []
    for f in files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(SecurityFinding(
                        file=f.name, line=lineno, severity="HIGH",
                        label=label, detail="hardcoded secret pattern matched",
                    ))
    return findings


def _bandit_executable() -> str:
    """
    `bandit` is a declared, required project dependency (pyproject.toml),
    not optional -- so "not found on PATH" almost always means the
    invoking shell simply hasn't activated this project's venv, not that
    bandit is genuinely absent. Resolving relative to sys.executable's own
    directory (the same venv the running Python process came from) makes
    this tool work correctly regardless of the CALLER's PATH/activation
    state -- the actual gap found in Phase 4.1's environment audit
    (bandit was pip-installed in .venv but .venv/bin wasn't on PATH in the
    shell that ran the test suite).
    """
    found = shutil.which("bandit")
    if found:
        return found
    venv_candidate = Path(sys.executable).parent / "bandit"
    return str(venv_candidate) if venv_candidate.exists() else "bandit"


def _run_bandit(target: Path) -> tuple[list[SecurityFinding], str | None]:
    try:
        proc = subprocess.run(
            [_bandit_executable(), "-r", "-f", "json", str(target)],
            capture_output=True, text=True, timeout=_BANDIT_TIMEOUT,
        )
    except FileNotFoundError:
        return [], "bandit is not installed"
    except subprocess.TimeoutExpired:
        return [], f"bandit timed out after {_BANDIT_TIMEOUT}s"

    # bandit exits non-zero when it finds issues — that's expected, not an error.
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return [], "bandit produced unparseable output"

    findings = []
    for result in data.get("results", []):
        findings.append(SecurityFinding(
            file=Path(result.get("filename", "?")).name,
            line=result.get("line_number", 0),
            severity=result.get("issue_severity", "LOW"),
            label=result.get("test_name", "bandit finding"),
            detail=result.get("issue_text", ""),
        ))
    return findings, None


def run_security_scan(path: str) -> ScanResult | str:
    """Scan a file or directory within the sandboxed workspace.

    Runs bandit against any Python files found, plus a portable
    secret-pattern scan across every text file regardless of language —
    see module docstring for the honest scope of each.
    """
    from orca.tools import _resolve_in_workspace  # avoid import cycle at module load

    resolved = _resolve_in_workspace(path)
    if resolved is None:
        from orca.tools import WORKSPACE_DIR
        return f"Access denied: '{path}' is outside the sandboxed workspace directory ({WORKSPACE_DIR})."
    if not resolved.exists():
        return f"Path not found: {path}"

    files = _iter_text_files(resolved)
    has_python = any(f.suffix == ".py" for f in files)

    findings: list[SecurityFinding] = []
    bandit_ran = False
    bandit_error = None
    if has_python:
        bandit_findings, bandit_error = _run_bandit(resolved)
        findings.extend(bandit_findings)
        bandit_ran = bandit_error is None

    findings.extend(_scan_secrets(files))

    return ScanResult(
        files_scanned=len(files), findings=findings,
        bandit_ran=bandit_ran, bandit_error=bandit_error,
    )
