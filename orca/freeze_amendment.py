"""Fail-closed preparation for a three-file freeze amendment.

The historical baseline stays ``cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d``.
Exactly three already-committed denial documents may be named by a future
founder approval. This module does not activate that exception.

No founder public key is pinned here. A caller-supplied key, an empty
authority registry, and a signature made for training or native pretraining
are not founder authorization. ``activated`` is false on every verdict.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SCHEMA_APPROVAL = "orneur-freeze-amendment-approval/1"
SIGNING_DOMAIN = b"orneur-freeze-amendment-approval/1\n"
BASELINE = "cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d"
INTRODUCING_COMMIT = "6cd6127b608a0ea6670576ba6a506f8f3a6220b1"
DECISION = "adopt_files"
AWAITING = "AWAITING_FOUNDER_SIGNED_APPROVAL"
REJECTED = "REJECTED"
PROPOSAL_PATH = "docs/orneur/cursor/FREEZE_AMENDMENT_PROPOSAL.md"
# SHA-256 of PROPOSAL_PATH at the preparation that defined this verifier.
# The digest is not written inside the proposal, so the pin is not self-hashing.
PROPOSAL_SHA256 = "08daabb09d79c22b241691bc92c8a519f065519303a368cb44e5afb972f6996a"
APPROVAL_DIR = "docs/orneur/cursor/freeze_amendment_approvals"
# Digest of the existing native-pretraining denial module. This is not a
# founder key. The module is outside the frozen path list, so a byte change
# would otherwise be invisible to the historical diff.
TRUST_ROOT_CODE_PATH = "orca/genesis/governance/authorization.py"
TRUST_ROOT_CODE_SHA256 = "92ea00667999f7028dacdae88ab86175e4042e9f2ad561ccc409b7c5b3400e9f"

PERMITTED: tuple[tuple[str, str], ...] = (
    (
        "docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json",
        "13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84",
    ),
    (
        "docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json",
        "88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49",
    ),
    (
        "docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json",
        "2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3",
    ),
)
FROZEN = (
    "docs/orneur/acceptance",
    "docs/orneur/authorization",
    "docs/orneur/phase-21/rse",
    "orca/rse",
    "orca/train/authorization.py",
    "docs/orneur/acceptance/register_graph.json",
    "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json",
    "eval_private",
)
_UNCHANGED_REASON = {
    "docs/orneur/acceptance/acceptance_ledger.json": "acceptance_ledger_changed",
    "docs/orneur/acceptance/register_graph.json": "acceptance_graph_changed",
    "orca/train/authorization.py": "training_authorization_changed",
    "docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json": "trust_root_changed",
    "orca/gateway/serving_authority.py": "trust_root_changed",
}
UNCHANGED_PATHS = tuple(_UNCHANGED_REASON)
_DIFF_PRIORITY = (
    "historical_evidence_unreadable",
    "missing_historical_commit",
    "historical_bytes_mismatch",
    "acceptance_ledger_changed",
    "acceptance_graph_changed",
    "training_authorization_changed",
    "trust_root_changed",
    "frozen_deletion",
    "unauthorized_path",
    "permitted_path_missing",
    "permitted_bytes_modified",
)
_APPROVAL_PRIORITY = (
    "approval_store_refused",
    "malformed_approval",
    "decision_rejected",
    "proposal_not_bound",
    "baseline_not_bound",
    "path_set_mismatch",
    "digest_not_bound",
    "duplicate_approvals",
    "conflicting_approvals",
)
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_SIG128 = re.compile(r"^[0-9a-f]{128}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_IDENT = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_APPROVAL_KEYS = {
    "schema_version",
    "proposal_sha256",
    "baseline",
    "decision",
    "paths",
    "founder",
    "signature",
}
_PATH_KEYS = {"path", "sha256"}
_FOUNDER_KEYS = {"identity", "key_id"}


class FreezeAmendmentError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ApprovalLoad:
    documents: tuple[dict, ...]
    reason: str | None


@dataclass(frozen=True)
class FreezeAmendmentVerdict:
    status: str
    activated: bool
    reason: str
    reasons: tuple[str, ...]
    baseline: str
    proposal_sha256: str
    permitted: tuple[tuple[str, str], ...]
    observed_paths: tuple[str, ...]
    digest_ok: bool
    baseline_present: bool
    historical_commit_present: bool
    signature_checked: bool
    founder_authenticated: bool
    training_permission: bool
    gpu_permission: bool
    spending_permission: bool
    corpus_permission: bool
    model_selection_permission: bool


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def canonical_approval_bytes(document: dict) -> bytes:
    """Bytes a founder would sign. The signature field is not part of them."""
    body = {key: value for key, value in document.items() if key != "signature"}
    paths = body.get("paths")
    if isinstance(paths, list):
        body["paths"] = sorted(paths, key=lambda item: item.get("path", "") if isinstance(item, dict) else "")
    return SIGNING_DOMAIN + _canonical(body)


def proposal_digest(root: Path) -> str:
    return hashlib.sha256((root / PROPOSAL_PATH).read_bytes()).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_independent_trust() -> dict:
    """The independent founder trust source is not established in this process."""
    return {
        "established": False,
        "stale": False,
        "source": None,
        "reason": "missing_trust_material",
        "public_key": None,
        "key_id": None,
        "identity": None,
    }


def _expired(stamp: str) -> bool:
    if not _TS.match(stamp):
        return False
    return stamp < "2026-01-01T00:00:00Z"


def classify_presented_trust(material: object) -> str:
    """Refuse every trust object this process can be handed.

    An empty registry is not a founder key. A key dict, raw key bytes, and
    an expired record are refused. None of these results establish trust.
    """
    if material is None:
        return "missing_trust_material"
    if isinstance(material, (bytes, bytearray)):
        return "caller_supplied_trust_refused"
    if not isinstance(material, dict):
        return "caller_supplied_trust_refused"
    records = material.get("records") if "records" in material else None
    if records == []:
        return "empty_registry_not_authority"
    expiry = material.get("expiry")
    if isinstance(expiry, str) and _expired(expiry):
        return "stale_trust_material"
    return "caller_supplied_trust_refused"


def ed25519_signature_matches(public_key: bytes, signature: bytes, document: dict) -> bool:
    """Check one signature over the freeze-amendment domain.

    A true result is not founder authorization. ``evaluate`` does not call
    this with a key from the repository, and it does not activate when a
    caller passes a key in.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception as exc:
        raise FreezeAmendmentError("signature_verifier_unavailable") from exc
    if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != 32:
        return False
    if not isinstance(signature, (bytes, bytearray)) or len(signature) != 64:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes(public_key)).verify(
            bytes(signature), canonical_approval_bytes(document)
        )
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True)


def _commit_present(root: Path, sha: str) -> bool:
    return _git(root, ["cat-file", "-e", sha + "^{commit}"]).returncode == 0


def _blob_sha256(root: Path, spec: str) -> str | None:
    proc = _git(root, ["cat-file", "blob", spec])
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()


def _parse_name_status(text: str) -> list[tuple[str, str]] | None:
    if text == "":
        return []
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None
        rows.append((parts[0], parts[1]))
    return rows


def _ordered(reasons: set[str], priority: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(reason for reason in priority if reason in reasons)


def classify_diff(
    *,
    baseline_present: bool,
    introducing_present: bool,
    entries: list[tuple[str, str]] | None,
    digests: dict[str, str],
    historical_digests: dict[str, str],
    unchanged: dict[str, tuple[str | None, str | None]],
    trust_code_sha256: str,
) -> tuple[str, ...]:
    """Return diff reasons. An empty tuple means the frozen diff is only the three pins."""
    found: set[str] = set()
    if entries is None:
        found.add("historical_evidence_unreadable")
    if not baseline_present or not introducing_present:
        found.add("missing_historical_commit")
    if found & {"historical_evidence_unreadable", "missing_historical_commit"}:
        return _ordered(found, _DIFF_PRIORITY)

    permitted = dict(PERMITTED)
    seen: dict[str, str] = {}
    for status, path in entries or []:
        if path in seen:
            found.add("unauthorized_path")
        seen[path] = status
        specific = _UNCHANGED_REASON.get(path)
        if specific is not None:
            found.add(specific)
            continue
        if path not in permitted:
            if status.startswith("D"):
                found.add("frozen_deletion")
            else:
                found.add("unauthorized_path")
            continue
        if status != "A" or digests.get(path) != permitted[path]:
            found.add("permitted_bytes_modified")
    for path in permitted:
        if path not in seen:
            found.add("permitted_path_missing")
        elif historical_digests.get(path) != permitted[path]:
            found.add("historical_bytes_mismatch")
    for path, (baseline_sha, worktree_sha) in unchanged.items():
        if baseline_sha is None or worktree_sha is None or baseline_sha != worktree_sha:
            found.add(_UNCHANGED_REASON[path])
    if trust_code_sha256 != TRUST_ROOT_CODE_SHA256:
        found.add("trust_root_changed")
    return _ordered(found, _DIFF_PRIORITY)


def _problem(document: object) -> str | None:
    if not isinstance(document, dict) or set(document) != _APPROVAL_KEYS:
        return "malformed_approval"
    if document.get("schema_version") != SCHEMA_APPROVAL:
        return "malformed_approval"
    if document.get("decision") != DECISION:
        return "decision_rejected"
    if not isinstance(document.get("proposal_sha256"), str) or not _SHA64.match(document["proposal_sha256"]):
        return "malformed_approval"
    if document["proposal_sha256"] != PROPOSAL_SHA256:
        return "proposal_not_bound"
    if document.get("baseline") != BASELINE or not _SHA40.match(str(document.get("baseline"))):
        return "baseline_not_bound"
    founder = document.get("founder")
    if not isinstance(founder, dict) or set(founder) != _FOUNDER_KEYS:
        return "malformed_approval"
    if not _IDENT.match(str(founder.get("identity"))) or not _IDENT.match(str(founder.get("key_id"))):
        return "malformed_approval"
    signature = document.get("signature")
    if not isinstance(signature, str) or not _SIG128.match(signature):
        return "malformed_approval"
    paths = document.get("paths")
    if not isinstance(paths, list) or len(paths) != 3:
        return "path_set_mismatch"
    found: dict[str, str] = {}
    for item in paths:
        if not isinstance(item, dict) or set(item) != _PATH_KEYS:
            return "malformed_approval"
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str) or not _SHA64.match(digest):
            return "malformed_approval"
        if path in found:
            return "path_set_mismatch"
        found[path] = digest
    if set(found) != {path for path, _digest in PERMITTED}:
        return "path_set_mismatch"
    if any(found[path] != digest for path, digest in PERMITTED):
        return "digest_not_bound"
    return None


def assess_approvals(documents: list[object]) -> tuple[str, ...]:
    if not documents:
        return ()
    problems: set[str] = set()
    identities: list[bytes] = []
    for document in documents:
        reason = _problem(document)
        if reason is not None:
            problems.add(reason)
            continue
        assert isinstance(document, dict)
        identities.append(canonical_approval_bytes(document) + b"\n" + document["signature"].encode())
    if len(documents) >= 2 and not problems:
        if len(identities) == len(documents) and len(set(identities)) == 1:
            problems.add("duplicate_approvals")
        else:
            problems.add("conflicting_approvals")
    return _ordered(problems, _APPROVAL_PRIORITY)


def load_approval_documents(root: Path) -> ApprovalLoad:
    directory = root / APPROVAL_DIR
    if not directory.exists():
        return ApprovalLoad((), None)
    if directory.is_symlink() or not directory.is_dir():
        return ApprovalLoad((), "approval_store_refused")
    documents: list[dict] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file():
            return ApprovalLoad((), "approval_store_refused")
        if path.suffix != ".json":
            return ApprovalLoad((), "malformed_approval")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return ApprovalLoad((), "malformed_approval")
        if not isinstance(data, dict):
            return ApprovalLoad((), "malformed_approval")
        documents.append(data)
    return ApprovalLoad(tuple(documents), None)


def _observe(root: Path) -> dict:
    baseline_present = _commit_present(root, BASELINE)
    introducing_present = _commit_present(root, INTRODUCING_COMMIT)
    proc = _git(root, ["diff", "--name-status", BASELINE, "--", *FROZEN])
    entries = None if proc.returncode != 0 else _parse_name_status(proc.stdout.decode())
    digests: dict[str, str] = {}
    historical: dict[str, str] = {}
    for path, _pin in PERMITTED:
        file_path = root / path
        if file_path.is_file() and not file_path.is_symlink():
            digests[path] = file_digest(file_path)
        if introducing_present:
            blob = _blob_sha256(root, INTRODUCING_COMMIT + ":" + path)
            if blob is not None:
                historical[path] = blob
    unchanged: dict[str, tuple[str | None, str | None]] = {}
    if baseline_present:
        for path in _UNCHANGED_REASON:
            baseline_sha = _blob_sha256(root, BASELINE + ":" + path)
            file_path = root / path
            worktree_sha = file_digest(file_path) if file_path.is_file() and not file_path.is_symlink() else None
            unchanged[path] = (baseline_sha, worktree_sha)
    trust_path = root / TRUST_ROOT_CODE_PATH
    trust_sha = file_digest(trust_path) if trust_path.is_file() and not trust_path.is_symlink() else ""
    proposal_ok = (root / PROPOSAL_PATH).is_file() and proposal_digest(root) == PROPOSAL_SHA256
    return {
        "baseline_present": baseline_present,
        "introducing_present": introducing_present,
        "entries": entries,
        "digests": digests,
        "historical_digests": historical,
        "unchanged": unchanged,
        "trust_code_sha256": trust_sha,
        "proposal_ok": proposal_ok,
        "observed_paths": tuple(path for _status, path in entries) if entries is not None else (),
    }


def evaluate(root: Path | None = None, *, approvals: list[object] | None = None) -> FreezeAmendmentVerdict:
    """Judge the worktree. The returned ``activated`` field is false.

    ``approvals`` lets a test present documents. Presented documents are
    judged and still cannot activate the exception. When ``approvals`` is
    omitted, the inactive approval directory is read and is empty in this
    preparation.
    """
    base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    observed = _observe(base)
    diff_reasons = classify_diff(
        baseline_present=observed["baseline_present"],
        introducing_present=observed["introducing_present"],
        entries=observed["entries"],
        digests=observed["digests"],
        historical_digests=observed["historical_digests"],
        unchanged=observed["unchanged"],
        trust_code_sha256=observed["trust_code_sha256"],
    )
    if not observed["proposal_ok"]:
        diff_reasons = tuple(dict.fromkeys((*diff_reasons, "proposal_not_bound")))
    if approvals is None:
        loaded = load_approval_documents(base)
        approval_reasons = (loaded.reason,) if loaded.reason else assess_approvals(list(loaded.documents))
        presented = list(loaded.documents)
    else:
        approval_reasons = assess_approvals(approvals)
        presented = list(approvals)
    trust = load_independent_trust()
    hard = tuple(reason for reason in dict.fromkeys((*diff_reasons, *approval_reasons)) if reason)
    if hard:
        status = REJECTED
        reason = hard[0]
        reasons = hard
    elif trust["established"] is not False or trust["public_key"] is not None:
        # A substituted loader that claims a key is presented trust, not the
        # independent source this preparation established. There is none.
        status = REJECTED
        reason = "caller_supplied_trust_refused"
        reasons = (reason,)
    elif presented == []:
        status = AWAITING
        reason = "approval_absent"
        reasons = (reason,)
    else:
        status = AWAITING
        reason = "missing_trust_material"
        reasons = (reason,)
    permitted_ok = not any(
        item in diff_reasons
        for item in (
            "permitted_bytes_modified",
            "permitted_path_missing",
            "unauthorized_path",
            "historical_bytes_mismatch",
            "missing_historical_commit",
            "historical_evidence_unreadable",
        )
    )
    return FreezeAmendmentVerdict(
        status=status,
        activated=False,
        reason=reason,
        reasons=reasons,
        baseline=BASELINE,
        proposal_sha256=PROPOSAL_SHA256,
        permitted=PERMITTED,
        observed_paths=observed["observed_paths"],
        digest_ok=permitted_ok and observed["proposal_ok"],
        baseline_present=observed["baseline_present"],
        historical_commit_present=observed["introducing_present"],
        signature_checked=False,
        founder_authenticated=False,
        training_permission=False,
        gpu_permission=False,
        spending_permission=False,
        corpus_permission=False,
        model_selection_permission=False,
    )
