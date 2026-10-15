"""Reproducible environment manifest: a deterministic JSON document describing WHAT a (synthetic or future) training run would run on.

Deterministic = same inputs give byte-identical output: no timestamps, no hostnames, no paths beyond the repo-relative lock path, canonical
serialization, and a self-hash. Facts the process must not invent (code SHA, dataset bundle hash) are INJECTED by the caller. The container
image does not exist yet, so its digest is null and its status is the explicit string NOT_BUILT -- never a fabricated digest.
"""
from __future__ import annotations

import platform
import re
import sys
from pathlib import Path

from orca.train.dryrun.canon import canonical_bytes, hash_obj, sha256_hex
from orca.train.dryrun.lockcheck import check_lock_text

SCHEMA = "orneur-dryrun-env-manifest/1"
LOCK_REL_PATH = "requirements/train.txt"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_KEYS = {"schema", "synthetic", "python", "platform", "lock", "container", "code_sha", "dataset_bundle_sha256", "seeds", "manifest_sha256"}


class EnvManifestInvalid(ValueError):
    pass


def current_python() -> dict:
    return {"version": ".".join(str(x) for x in sys.version_info[:3]), "implementation": platform.python_implementation()}


def current_platform() -> dict:
    return {"system": platform.system(), "machine": platform.machine()}


def build_env_manifest(*, code_sha: str, dataset_bundle_sha256: str, seeds: dict, lock_path, python_info: dict | None = None,
                       platform_info: dict | None = None, lock_rel_path: str = LOCK_REL_PATH) -> dict:
    if not _SHA40.match(str(code_sha)):
        raise EnvManifestInvalid("code_sha must be an injected 40-hex git SHA")
    if not _SHA64.match(str(dataset_bundle_sha256)):
        raise EnvManifestInvalid("dataset_bundle_sha256 must be an injected 64-hex hash")
    if not isinstance(seeds, dict) or not seeds or not all(isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) for k, v in seeds.items()):
        raise EnvManifestInvalid("seeds must be a non-empty {name: int} mapping")
    text = Path(lock_path).read_text()
    rep = check_lock_text(text)
    body = {
        "schema": SCHEMA, "synthetic": True,
        "python": python_info or current_python(), "platform": platform_info or current_platform(),
        "lock": {"path": lock_rel_path, "sha256": sha256_hex(text.encode()), "structure_ok": rep.ok, "packages": rep.packages, "hashes": rep.hashes},
        "container": {"image_digest": None, "status": "NOT_BUILT"},
        "code_sha": code_sha, "dataset_bundle_sha256": dataset_bundle_sha256, "seeds": dict(sorted(seeds.items())),
    }
    return {**body, "manifest_sha256": hash_obj(body)}


def env_manifest_bytes(manifest: dict) -> bytes:
    return canonical_bytes(manifest) + b"\n"


def verify_env_manifest(manifest) -> list:
    """Problem codes (empty == internally consistent). Does not re-read the lock file; compare manifest['lock']['sha256'] to it separately."""
    if not isinstance(manifest, dict) or set(manifest) != _KEYS:
        return ["SCHEMA_MISMATCH"]
    problems = []
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if manifest["manifest_sha256"] != hash_obj(body):
        problems.append("SELF_HASH_MISMATCH")
    c = manifest["container"]
    if c != {"image_digest": None, "status": "NOT_BUILT"}:
        problems.append("CONTAINER_DIGEST_NOT_PLACEHOLDER")      # until an image is really built this must stay null/NOT_BUILT
    if manifest["synthetic"] is not True:
        problems.append("NOT_MARKED_SYNTHETIC")
    return problems
