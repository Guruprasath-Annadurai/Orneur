"""Code-revision + dataset-hash + config binding for a run. A run is bound to (clean git SHA, dataset manifest hashes, config hash); on
start AND on every resume the live facts are recomputed and compared with what the ledger recorded. Any mismatch is a refusal.

Same trusted-facts rule as orca.train.authorization: the SHA and the cleanliness come from `git` run against the repo root, never from an
argument, an environment variable or a config flag.
"""
from __future__ import annotations

import dataclasses
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from orca.train.dryrun.canon import hash_obj

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_VOLATILE_KEYS = frozenset({"created_at"})


class BindingRefused(RuntimeError):
    def __init__(self, reasons):
        self.reasons = sorted(set(reasons))
        super().__init__("run binding refused: " + ", ".join(self.reasons))


@dataclass(frozen=True)
class Binding:
    git_sha: str
    tree_clean: bool
    config_sha256: str
    dataset_manifest_sha256s: tuple
    dataset_bundle_sha256: str | None = None

    def as_dict(self) -> dict:
        return {"git_sha": self.git_sha, "tree_clean": self.tree_clean, "config_sha256": self.config_sha256,
                "dataset_manifest_sha256s": list(self.dataset_manifest_sha256s), "dataset_bundle_sha256": self.dataset_bundle_sha256}


def _git(root: Path, *args: str) -> tuple:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30, check=False)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def git_state(repo_root) -> tuple:
    """(head_sha | None, tree_clean). Unknown == not clean."""
    rc, head = _git(Path(repo_root), "rev-parse", "HEAD")
    rc2, porcelain = _git(Path(repo_root), "status", "--porcelain")
    return (head if rc == 0 and _SHA40.match(head) else None), (rc2 == 0 and porcelain == "")


def manifest_hash(obj) -> str:
    """Stable hash of a dataset/bundle manifest (a registry dataclass or a dict), ignoring volatile fields like created_at."""
    d = dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) and not isinstance(obj, type) else dict(obj)
    return hash_obj({k: v for k, v in sorted(d.items()) if k not in _VOLATILE_KEYS})


def synthetic_dataset_manifest(plan) -> dict:
    return {"kind": "synthetic-regression", "generator": "orca.train.dryrun.toy.make_dataset/1", "data_seed": plan.data_seed,
            "n_examples": plan.n_examples, "n_features": plan.n_features}


def collect_binding(repo_root, *, config: dict, dataset_manifests, bundle=None, require_clean: bool = True) -> Binding:
    reasons = []
    head, clean = git_state(repo_root)
    if head is None:
        reasons.append("GIT_SHA_UNAVAILABLE")
    if require_clean and not clean:
        reasons.append("DIRTY_WORKING_TREE")
    manifests = tuple(sorted(manifest_hash(m) for m in (dataset_manifests or ())))
    if not manifests:
        reasons.append("NO_DATASET_MANIFEST_BOUND")
    if reasons:
        raise BindingRefused(reasons)
    return Binding(git_sha=head, tree_clean=clean, config_sha256=hash_obj(config), dataset_manifest_sha256s=manifests,
                   dataset_bundle_sha256=manifest_hash(bundle) if bundle is not None else None)


def verify_binding(expected: dict, actual: Binding, *, require_clean: bool = True) -> None:
    """`expected` is the binding dict recorded in the ledger at run start. Raises BindingRefused on ANY difference."""
    reasons = []
    if not isinstance(expected, dict) or set(expected) != {"git_sha", "tree_clean", "config_sha256", "dataset_manifest_sha256s", "dataset_bundle_sha256"}:
        raise BindingRefused(["EXPECTED_BINDING_MALFORMED"])
    if not _SHA40.match(str(expected["git_sha"])) or not all(_SHA64.match(str(h)) for h in expected["dataset_manifest_sha256s"]):
        reasons.append("EXPECTED_BINDING_MALFORMED")
    if expected["git_sha"] != actual.git_sha:
        reasons.append("GIT_SHA_MISMATCH")
    if expected["config_sha256"] != actual.config_sha256:
        reasons.append("CONFIG_HASH_MISMATCH")
    if list(expected["dataset_manifest_sha256s"]) != list(actual.dataset_manifest_sha256s):
        reasons.append("DATASET_MANIFEST_HASH_MISMATCH")
    if expected["dataset_bundle_sha256"] != actual.dataset_bundle_sha256:
        reasons.append("DATASET_BUNDLE_HASH_MISMATCH")
    if require_clean and not actual.tree_clean:
        reasons.append("DIRTY_WORKING_TREE")
    if reasons:
        raise BindingRefused(reasons)
