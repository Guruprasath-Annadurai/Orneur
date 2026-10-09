"""Fail-closed acceptance for the ORNEUR register.

The published graph status is not an acceptance bit. A row advances only
when this module verifies a detached signature over that row's own
artifact. This module does not write the register, the ledger, or any
authorization file, and it does not authorize training.
"""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SIGNED_FIELDS = (
    "requirement_id",
    "evidence_key",
    "artifact_class",
    "artifact_sha256",
    "git_sha",
    "scope",
    "reviewer_role",
)


class AcceptanceRejected(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def payload_bytes(record):
    try:
        lines = [record[field] for field in SIGNED_FIELDS]
    except KeyError as exc:
        missing = exc.args[0]
        code = "MISSING_REVIEWER" if missing == "reviewer_role" else "MISSING_FIELD"
        raise AcceptanceRejected(code, missing) from exc
    return ("\n".join(lines) + "\n").encode("utf-8")


def assert_published_baseline(nodes, markdown, ledger, trust):
    errors = []
    if any(node.get("status") == "ACCEPTED" for node in nodes):
        errors.append("published status ACCEPTED")
    if ledger != []:
        errors.append("committed ledger is not empty")
    if trust != {"keys": []}:
        errors.append("committed trust store is not empty")
    for line in markdown.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 6 or cells[0] in {"ID", "---"}:
            continue
        if cells[5] == "ACCEPTED":
            errors.append(f"markdown status ACCEPTED on {cells[0]}")
    return errors


def evaluate(nodes, records, *, trust_keys, subject_sha, ancestor_shas=()):
    """Return the ids this ledger accepts. Raise on any bad record.

    `nodes` is not modified. An empty ledger accepts nothing.
    """
    by_id = {node["id"]: node for node in nodes}
    if not isinstance(records, list):
        raise AcceptanceRejected("MISSING_FIELD", "ledger")
    if not records:
        return {}

    seen_ids = []
    seen_artifacts = {}
    for record in records:
        if not isinstance(record, dict):
            raise AcceptanceRejected("MISSING_FIELD", "record")
        requirement_id = record.get("requirement_id")
        if not requirement_id:
            raise AcceptanceRejected("MISSING_FIELD", "requirement_id")
        if requirement_id in seen_ids:
            raise AcceptanceRejected("DUPLICATE", requirement_id)
        seen_ids.append(requirement_id)
        digest = record.get("artifact_sha256")
        if not _hex_length(digest, 64):
            raise AcceptanceRejected("MISSING_FIELD", "artifact_sha256")
        if digest in seen_artifacts:
            raise AcceptanceRejected(
                "DUPLICATE_ARTIFACT",
                f"{seen_artifacts[digest]} and {requirement_id}",
            )
        seen_artifacts[digest] = requirement_id

    order = _order(by_id)
    pending = {record["requirement_id"]: record for record in records}
    accepted = {}
    for requirement_id in order:
        if requirement_id not in pending:
            continue
        _accept_one(
            by_id[requirement_id],
            pending[requirement_id],
            nodes=nodes,
            by_id=by_id,
            accepted=accepted,
            trust_keys=trust_keys,
            subject_sha=subject_sha,
            ancestor_shas=set(ancestor_shas),
        )
        accepted[requirement_id] = pending[requirement_id]["artifact_sha256"]
    unknown = set(pending) - set(order)
    if unknown:
        raise AcceptanceRejected("UNKNOWN_REQUIREMENT", sorted(unknown)[0])
    return dict(accepted)


def _accept_one(node, record, *, nodes, by_id, accepted, trust_keys, subject_sha, ancestor_shas):
    if node["id"] == "R65" or node["id"].startswith("R65-"):
        raise AcceptanceRejected("NOT_VERIFIABLE", node["id"])
    if not node["counts"]:
        raise AcceptanceRejected("NOT_COUNTABLE", node["id"])
    _require_match(record, "evidence_key", node["evidence_key"], "MISMATCH")
    _require_match(record, "artifact_class", node["artifact_class"], "MISMATCH")
    _require_match(record, "scope", node["denominator"], "SCOPE_MISMATCH")
    git_sha = record.get("git_sha", "")
    if not _hex_length(git_sha, 40):
        raise AcceptanceRejected("WRONG_SHA", git_sha or "missing")
    if git_sha != subject_sha:
        code = "STALE" if git_sha in ancestor_shas else "WRONG_SHA"
        raise AcceptanceRejected(code, git_sha)
    reviewer = record.get("reviewer_role", "")
    if not reviewer or reviewer == "UNRESOLVED_EXTERNAL":
        raise AcceptanceRejected("MISSING_REVIEWER", node["id"])
    if node["independent_reviewer"] in {"", "UNRESOLVED_EXTERNAL"}:
        raise AcceptanceRejected("MISSING_REVIEWER", node["id"])
    if reviewer == node["implementation_owner"]:
        raise AcceptanceRejected("SELF_REVIEW", node["id"])
    if reviewer != node["independent_reviewer"]:
        raise AcceptanceRejected("REVIEWER_MISMATCH", reviewer)
    key_id = record.get("reviewer_key_id")
    if not key_id:
        raise AcceptanceRejected("MISSING_REVIEWER", "reviewer_key_id")
    key = _key_by_id(trust_keys, key_id)
    if key is None:
        raise AcceptanceRejected("FORGED", key_id)
    if key.get("role") != reviewer:
        raise AcceptanceRejected("REVIEWER_MISMATCH", key_id)
    _verify_signature(record, key)
    for dep in node["depends_on"]:
        predecessor = by_id.get(dep)
        if predecessor is None:
            raise AcceptanceRejected("DEPENDENCY_UNACCEPTED", dep)
        if predecessor["counts"] and dep not in accepted:
            raise AcceptanceRejected("DEPENDENCY_UNACCEPTED", f"{node['id']} missing {dep}")
    if node["id"] == "FINAL-1":
        open_rows = [
            other["id"]
            for other in nodes
            if other["denominator"] == "PRE_TRAINING"
            and other["counts"]
            and other["id"] != "FINAL-1"
            and other["id"] not in accepted
        ]
        if open_rows:
            raise AcceptanceRejected("FINAL_READINESS_BLOCKED", open_rows[0])
    if node["id"] == "FINAL-2" and "FINAL-1" not in accepted:
        raise AcceptanceRejected("DEPENDENCY_UNACCEPTED", "FINAL-2 missing FINAL-1")
    if node["id"] == "EXEC-1" and "FINAL-2" not in accepted:
        raise AcceptanceRejected("DEPENDENCY_UNACCEPTED", "EXEC-1 missing FINAL-2")


def _require_match(record, field, expected, code):
    actual = record.get(field)
    if actual is None:
        raise AcceptanceRejected("MISSING_FIELD", field)
    if actual != expected:
        raise AcceptanceRejected(code, field)


def _verify_signature(record, key):
    signature = record.get("signature_hex", "")
    public_hex = key.get("public_key_hex", "")
    if not _hex_length(signature, 128) or not _hex_length(public_hex, 64):
        raise AcceptanceRejected("FORGED", record.get("requirement_id", ""))
    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
        public.verify(bytes.fromhex(signature), payload_bytes(record))
    except (InvalidSignature, ValueError) as exc:
        raise AcceptanceRejected("FORGED", record.get("requirement_id", "")) from exc


def _key_by_id(trust_keys, key_id):
    for key in trust_keys:
        if key.get("key_id") == key_id:
            return key
    return None


def _hex_length(value, size):
    return isinstance(value, str) and len(value) == size and all(
        char in "0123456789abcdef" for char in value
    )


def _order(by_id):
    sorter = TopologicalSorter()
    for node in by_id.values():
        sorter.add(node["id"], *[dep for dep in node["depends_on"] if dep in by_id])
    try:
        return list(sorter.static_order())
    except CycleError as exc:
        raise AcceptanceRejected("CYCLE", "graph") from exc
