"""Dependency-lock verification beyond lockcheck's structural pass (resilience #1). Pure text; nothing is downloaded, installed or imported.

Adds, on top of lockcheck.check_lock_text:
  * hash consistency: a duplicate hash inside one package, or one hash claimed by two packages, is refused (a copy/paste or forged lock);
  * per-spec coverage: every DECLARED dependency (e.g. pyproject's `train` extra) must be present in the lock AND its pinned version must satisfy
    the declared specifier; an absent or unpinned/mismatching dependency is refused;
  * lock drift: the lock file must still hash to the sha256 bound into the environment manifest, and that manifest must be self-consistent.
Every failure is a problem code; `require_verified_lock` raises LockRefused (fail closed). Unparseable input is a refusal, never a pass.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from orca.train.dryrun.canon import sha256_hex
from orca.train.dryrun.envmanifest import verify_env_manifest
from orca.train.dryrun.lockcheck import check_lock_text, normalize

_HEAD = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==(?P<ver>[A-Za-z0-9][A-Za-z0-9._+!-]*)")


class LockRefused(RuntimeError):
    def __init__(self, problems):
        self.problems = sorted(set(problems))
        super().__init__("dependency lock refused: " + ", ".join(self.problems))


@dataclass
class LockVerdict:
    ok: bool
    sha256: str
    problems: list = field(default_factory=list)


def _statements(text: str) -> list:
    """[(name, version, [hash,...])] in file order; malformed statements are skipped (check_lock_text reports them)."""
    out, cur = [], []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        cont = s.endswith("\\")
        cur.append(s[:-1].strip() if cont else s)
        if not cont:
            m = _HEAD.match(cur[0])
            if m:
                out.append((normalize(m.group("name")), m.group("ver"), [p for p in cur[1:] if p.startswith("--hash=sha256:")]))
            cur = []
    return out


def check_lock_consistency(text: str) -> list:
    problems, owner = [], {}
    for name, _ver, hashes in _statements(text):
        if len(set(hashes)) != len(hashes):
            problems.append(f"DUPLICATE_HASH_IN_{name}")
        for h in set(hashes):
            if h in owner and owner[h] != name:
                problems.append(f"HASH_SHARED_BY_{owner[h]}_AND_{name}")
            owner.setdefault(h, name)
    return sorted(set(problems))


def declared_train_specs(pyproject_path) -> list:
    """The `train` extra's requirement strings that apply on the locked interpreter (marker-gated entries skipped, like lockcheck)."""
    doc = tomllib.loads(Path(pyproject_path).read_text())
    return [r for r in doc["project"]["optional-dependencies"]["train"] if ";" not in r]


def verify_lock(text: str, *, declared=(), bound_sha256: str | None = None) -> LockVerdict:
    rep = check_lock_text(text)
    problems = list(rep.problems) + check_lock_consistency(text)
    if bound_sha256 is not None and bound_sha256 != rep.sha256:
        problems.append("LOCK_SHA_MISMATCH")
    if declared:
        try:
            from packaging.requirements import InvalidRequirement, Requirement
            from packaging.version import InvalidVersion, Version
        except ImportError:                                                     # cannot check -> cannot pass
            problems.append("SPEC_CHECKER_UNAVAILABLE")
            declared = ()
    locked = {n: v for n, v, _h in _statements(text)}
    for spec in declared:
        try:
            req = Requirement(spec)
        except (InvalidRequirement, TypeError):
            problems.append(f"UNPARSEABLE_DECLARED_SPEC_{spec!r}")
            continue
        n = normalize(req.name)
        if n not in locked:
            problems.append(f"UNLOCKED_DEPENDENCY_{n}")
            continue
        try:
            ok = req.specifier.contains(Version(locked[n]), prereleases=True)
        except InvalidVersion:
            ok = False
        if not ok:
            problems.append(f"LOCKED_VERSION_VIOLATES_{n}")
    problems = sorted(set(problems))
    return LockVerdict(not problems, rep.sha256, problems)


def require_verified_lock(lock_path, env_manifest: dict, *, declared=()) -> LockVerdict:
    """The lock file on disk must be valid AND be exactly the lock the (self-consistent) env manifest was built from."""
    problems = list(verify_env_manifest(env_manifest))
    text = Path(lock_path).read_text()
    bound = (env_manifest.get("lock") or {}).get("sha256") if isinstance(env_manifest, dict) else None
    v = verify_lock(text, declared=declared)
    problems += v.problems
    if bound != sha256_hex(text.encode()):
        problems.append("LOCK_DRIFT")
    if problems:
        raise LockRefused(problems)
    return v


__all__ = ["LockRefused", "LockVerdict", "check_lock_consistency", "declared_train_specs", "require_verified_lock", "verify_lock"]
