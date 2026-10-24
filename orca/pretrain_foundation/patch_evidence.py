"""Bind a candidate patch to the test that actually ran.

A passing command for a different file, a test edited after the failing
baseline, or a success whose tree does not contain the recorded patch is
rejected. The seal is a digest of this record, not a signature.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

_HEX = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class PatchEvidenceError(Exception):
    """The evidence record is not usable."""


def seal_patch_evidence(
    *,
    known_bad_commit: str,
    test_identity: str,
    test_digest: str,
    failing_exit: int,
    failing_test_digest: str,
    failing_command: list[str],
    patch_digest: str,
    patched_commit: str,
    build_id: str,
    passing_exit: int,
    passing_test_digest: str,
    passing_command: list[str],
    applied_patch_digest: str,
) -> dict:
    reasons: list[str] = []
    if not _COMMIT.fullmatch(known_bad_commit or "") or not _COMMIT.fullmatch(patched_commit or ""):
        reasons.append("commit identity is not a 40-character digest")
    elif known_bad_commit == patched_commit:
        reasons.append("patched commit is the known-bad commit")
    if not test_identity or not isinstance(failing_command, list) or failing_command != passing_command:
        reasons.append("passing command is not the reproducing command")
    if not _HEX.fullmatch(test_digest or "") or failing_test_digest != test_digest or passing_test_digest != test_digest:
        reasons.append("the test changed between the failing baseline and the candidate")
    if failing_exit == 0:
        reasons.append("the baseline did not fail")
    if passing_exit != 0:
        reasons.append("the candidate command did not pass")
    if not _HEX.fullmatch(patch_digest or "") or applied_patch_digest != patch_digest:
        reasons.append("the recorded patch was not applied")
    if not build_id:
        reasons.append("build identity is missing")
    if reasons:
        return {"accepted": False, "reasons": reasons, "seal": None, "signature": False}
    body = {
        "known_bad_commit": known_bad_commit,
        "test_identity": test_identity,
        "test_digest": test_digest,
        "failing_exit": failing_exit,
        "failing_command": list(failing_command),
        "patch_digest": patch_digest,
        "patched_commit": patched_commit,
        "build_id": build_id,
        "passing_exit": passing_exit,
        "passing_command": list(passing_command),
        "applied_patch_digest": applied_patch_digest,
        "signature": False,
    }
    seal = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    body["seal"] = seal
    return {
        "accepted": True,
        "reasons": [],
        "seal": seal,
        "signature": False,
        "repair_proof": False,
        "evidence": body,
    }


def observed_head(repo: Path) -> str:
    """The commit git reports. A caller-supplied hash is not consulted."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    head = (proc.stdout or "").strip()
    if proc.returncode != 0 or not _COMMIT.fullmatch(head):
        raise PatchEvidenceError("git head was not observed")
    kind = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", head],
        capture_output=True,
        text=True,
        check=False,
    )
    if kind.returncode != 0 or kind.stdout.strip() != "commit":
        raise PatchEvidenceError("git head is not a commit object")
    return head


_OBSERVED: set[tuple] = set()


def _relative_file(repo: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise PatchEvidenceError("evidence path escapes the checkout")
    path = Path(repo) / relative
    if path.is_symlink():
        raise PatchEvidenceError("evidence path is a symlink")
    if not path.is_file():
        raise PatchEvidenceError("evidence path is not a regular file")
    root = Path(repo).resolve()
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise PatchEvidenceError("evidence path escapes the checkout")
    return path


def _observation_key(row: dict) -> tuple:
    command = row.get("command") or []
    return (
        row.get("head"),
        row.get("relative_test"),
        row.get("source_path"),
        row.get("test_digest"),
        row.get("source_digest"),
        row.get("exit_code"),
        tuple(command),
        row.get("containment"),
    )


def _blob_sha256(repo: Path, commit: str, relative: str) -> str | None:
    if not _COMMIT.fullmatch(commit or ""):
        return None
    if not isinstance(relative, str) or not relative or relative.startswith("/") or ".." in Path(relative).parts:
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{relative}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()


def observe_execution(repo: Path, relative_test: str, source_path: str) -> dict:
    """Run the restricted pytest and bind the result to this checkout.

    The returned record is registered in this process. A later comparison
    rejects a dict that was not produced here. This is an execution record.
    It is not evidence that an agent wrote a patch.
    """
    from orca.pretrain_foundation.restricted_runner import run_authorized_pytest

    root = Path(repo)
    head = observed_head(root)
    test_file = _relative_file(root, relative_test)
    source = _relative_file(root, source_path)
    result = run_authorized_pytest(root, relative_test)
    test_digest = hashlib.sha256(test_file.read_bytes()).hexdigest()
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if result.get("test_digest") != test_digest:
        raise PatchEvidenceError("runner digest does not match the test file")
    if result.get("containment") != "user-namespace-chroot" or not result.get("executed"):
        raise PatchEvidenceError("the test was not executed in the restricted runner")
    if _blob_sha256(root, head, source_path) != source_digest or _blob_sha256(root, head, relative_test) != test_digest:
        raise PatchEvidenceError("the working tree does not match the observed git commit")
    record = {
        "head": head,
        "relative_test": relative_test,
        "source_path": source_path,
        "test_digest": test_digest,
        "source_digest": source_digest,
        "exit_code": result["exit_code"],
        "command": list(result["command"]),
        "containment": result["containment"],
        "repair_proof": False,
        "patch_generation": "NOT DEMONSTRATED",
    }
    _OBSERVED.add(_observation_key(record))
    return record


def compare_observed_executions(repo: Path, before: dict, after: dict) -> dict:
    """Accept a failing-then-passing pair only when this process ran both.

    The test blob must be unchanged, the source blob and git head must differ,
    and both digests must match `git show`. The result is not repair proof.
    """
    reasons: list[str] = []
    root = Path(repo)
    if before.get("repair_proof") or after.get("repair_proof"):
        reasons.append("a caller marked an execution as repair proof")
    if _observation_key(before) not in _OBSERVED or _observation_key(after) not in _OBSERVED:
        reasons.append("an execution was not observed in this process")
    if before.get("relative_test") != after.get("relative_test") or before.get("command") != after.get("command"):
        reasons.append("the passing command is not the failing command")
    if before.get("test_digest") != after.get("test_digest"):
        reasons.append("the test file changed")
    if before.get("exit_code") == 0:
        reasons.append("the baseline did not fail")
    if after.get("exit_code") != 0:
        reasons.append("the later command did not pass")
    if not before.get("head") or before.get("head") == after.get("head"):
        reasons.append("git head did not change")
    if not before.get("source_digest") or before.get("source_digest") == after.get("source_digest"):
        reasons.append("the observed source bytes did not change")
    if before.get("containment") != "user-namespace-chroot" or after.get("containment") != "user-namespace-chroot":
        reasons.append("an execution was not observed in the restricted runner")
    try:
        head = observed_head(root)
    except PatchEvidenceError as exc:
        reasons.append(str(exc))
        head = None
    if head != after.get("head"):
        reasons.append("the passing head is not the observed checkout")
    if _blob_sha256(root, str(before.get("head") or ""), str(before.get("source_path") or "")) != before.get("source_digest"):
        reasons.append("the failing source digest does not match the git object")
    if _blob_sha256(root, str(after.get("head") or ""), str(after.get("source_path") or "")) != after.get("source_digest"):
        reasons.append("the passing source digest does not match the git object")
    if _blob_sha256(root, str(before.get("head") or ""), str(before.get("relative_test") or "")) != before.get("test_digest"):
        reasons.append("the failing test digest does not match the git object")
    if _blob_sha256(root, str(after.get("head") or ""), str(after.get("relative_test") or "")) != after.get("test_digest"):
        reasons.append("the passing test digest does not match the git object")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "repair_proof": False,
        "patch_generation": "NOT DEMONSTRATED",
        "signature": False,
    }


def verify_seal(evidence: dict) -> bool:
    if not isinstance(evidence, dict) or not evidence.get("seal"):
        return False
    seal = evidence["seal"]
    body = {key: value for key, value in evidence.items() if key != "seal"}
    actual = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return actual == seal
