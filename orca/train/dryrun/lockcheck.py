"""Structural verifier for a hash-locked requirements file (`uv pip compile --generate-hashes` output).

It checks STRUCTURE only: every requirement is pinned with `==`, carries at least one sha256 `--hash`, and nothing can redirect resolution
(no URL / VCS / editable / index override / nested include). It does not download anything and does not prove the hashes match PyPI; that is
what `pip install --require-hashes` / `uv pip install --require-hashes` does at install time. No trainer package is installed or imported.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from orca.train.dryrun.canon import sha256_hex

_REQ = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<extras>\[[A-Za-z0-9._,\s-]+\])?==(?P<ver>[A-Za-z0-9][A-Za-z0-9._+!-]*)(?:\s*;\s*(?P<marker>.+?))?$")
_HASH = re.compile(r"^--hash=sha256:[0-9a-f]{64}$")
_FORBIDDEN_PREFIXES = ("-e", "--editable", "-r", "--requirement", "-c", "--constraint", "-i", "--index-url", "--extra-index-url", "-f", "--find-links",
                       "--trusted-host", "--no-index", "--pre", "--no-binary", "--only-binary", "--prefer-binary")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class LockReport:
    ok: bool
    sha256: str
    packages: int = 0
    hashes: int = 0
    names: list = field(default_factory=list)
    header: str = ""
    problems: list = field(default_factory=list)


def check_lock_text(text: str, *, required_names=()) -> LockReport:
    rep = LockReport(ok=False, sha256=sha256_hex(text.encode()))
    problems = rep.problems
    lines = text.splitlines()
    comments = [ln for ln in lines if ln.startswith("#")]
    rep.header = " ".join(c.lstrip("# ").strip() for c in comments[:3])
    if "--generate-hashes" not in rep.header:
        problems.append("HEADER_MISSING_GENERATE_HASHES_COMMAND")
    statements, cur, cur_start = [], [], 0
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if not cur and (not s or s.startswith("#")):
            continue
        if s.startswith("#") or not s:
            continue                     # comment inside a continued statement (uv emits `# via` lines after the last hash)
        if not cur:
            cur_start = i
        cont = s.endswith("\\")
        cur.append(s[:-1].strip() if cont else s)
        if not cont:
            statements.append((cur_start, cur))
            cur = []
    if cur:
        problems.append(f"UNTERMINATED_CONTINUATION_AT_{cur_start}")
    seen: dict = {}
    for start, parts in statements:
        head, hashes = parts[0], parts[1:]
        if head.startswith("-"):
            problems.append(f"FORBIDDEN_OPTION_AT_{start}")
            continue
        if "@" in head.split(";")[0] or "://" in head or re.match(r"^(?:vcs|hg|svn|bzr)\+", head) or head.startswith("file:") or head.startswith("git+"):
            problems.append(f"URL_OR_VCS_REQUIREMENT_AT_{start}")
            continue
        m = _REQ.match(head)
        if not m:
            problems.append(f"NOT_PINNED_WITH_DOUBLE_EQUALS_AT_{start}")
            continue
        n = normalize(m.group("name"))
        if n in seen:
            problems.append(f"DUPLICATE_{n}")
        seen[n] = m.group("ver")
        if not hashes:
            problems.append(f"NO_HASH_FOR_{n}")
        for h in hashes:
            if h.startswith(_FORBIDDEN_PREFIXES) and not h.startswith("--hash="):
                problems.append(f"FORBIDDEN_OPTION_AT_{start}")
            elif not _HASH.match(h):
                problems.append(f"BAD_HASH_FOR_{n}")
            else:
                rep.hashes += 1
    rep.packages = len(seen)
    rep.names = sorted(seen)
    if not seen:
        problems.append("EMPTY_LOCK")
    for req in required_names:
        if normalize(req) not in seen:
            problems.append(f"REQUIRED_PACKAGE_NOT_LOCKED_{normalize(req)}")
    rep.problems = sorted(set(problems))
    rep.ok = not rep.problems
    return rep


def check_lock_file(path, *, required_names=()) -> LockReport:
    return check_lock_text(Path(path).read_text(), required_names=required_names)


def train_extra_requirements(pyproject_path) -> list:
    """Normalized names of the `train` extra that apply on the locked interpreter (entries gated by a marker are skipped, e.g. the
    python>=3.12-only setuptools floor: the lock is for 3.11)."""
    doc = tomllib.loads(Path(pyproject_path).read_text())
    out = []
    for req in doc["project"]["optional-dependencies"]["train"]:
        if ";" in req:
            continue
        out.append(normalize(re.split(r"[<>=!~\[\s]", req, maxsplit=1)[0]))
    return sorted(out)
