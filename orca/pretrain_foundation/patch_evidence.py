"""Bind a candidate patch to the test that actually ran.

A passing command for a different file, a test edited after the failing
baseline, or a success whose tree does not contain the recorded patch is
rejected. The seal is a digest of this record, not a signature.
"""
from __future__ import annotations

import hashlib
import json
import re

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
    return {"accepted": True, "reasons": [], "seal": seal, "signature": False, "evidence": body}


def verify_seal(evidence: dict) -> bool:
    if not isinstance(evidence, dict) or not evidence.get("seal"):
        return False
    seal = evidence["seal"]
    body = {key: value for key, value in evidence.items() if key != "seal"}
    actual = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return actual == seal
