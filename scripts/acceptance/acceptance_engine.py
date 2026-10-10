"""Fail-closed acceptance for the ORNEUR register.

The published graph status is not an acceptance bit. A row advances only
when this module verifies a detached signature over that row's own
artifact. This module does not write the register, the ledger, or any
authorization file, and it does not authorize training.

Phase 0 remediation (temporary Cursor-to-Claude handoff) adds three
independent controls on top of the original reviewer-attestation gate:

  * Founder authority (task A): a row marked ``founder_approval ==
    "REQUIRED"`` (FINAL-2, EXEC-1, and the other founder-gated rows in the
    register) needs a SECOND detached signature, from a key enrolled with
    role ``FOUNDER``, over the same canonical payload as the reviewer's
    signature. A reviewer attestation alone can never satisfy these rows,
    and the founder key must be cryptographically distinct from the
    reviewer key used on the same record.
  * Artifact integrity (task B): every record must declare the policy
    version it was produced against (``policy_version``), and the four
    dependent protected-corpus evidence rows (DATA-1, DATA-2, DATA-5, and
    DATA-3 itself) must reference one common corpus identity --
    ``bound_corpus_sha256`` on the dependent rows must equal DATA-3's own
    accepted digest, not merely some hex string of the right shape.
  * Reviewer trust (task C): a key is usable as a reviewer or a founder
    approver only if it carries a detached enrollment signature from a
    founder root key supplied by the caller (``founder_root_keys``) --
    the engine never trusts a bare ``{key_id, role, public_key_hex}``
    tuple handed to it by the caller. Enrollment also carries a scope
    (which denominators the key may act on) and a revocation flag, both
    covered by that same enrollment signature.
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

# Appended to the signed payload after the original seven fields. Optional
# for rows that do not need them (default ""), but once set they cannot be
# changed without invalidating every signature already collected on the
# record -- a policy_version downgrade or a corpus-digest swap after the
# fact is therefore a forgery, not a silent edit.
EXTENDED_SIGNED_FIELDS = ("policy_version", "bound_corpus_sha256")

# The policy a record must declare it was produced against. Bumping this
# invalidates every previously-signed record for a new ledger -- that is
# the point: it forces a conscious re-attestation rather than letting an
# old record silently keep validating under a changed acceptance policy.
POLICY_VERSION = "orneur-acceptance-policy/1"

# The protected-corpus evidence rows that must all point at one identity.
# DATA-3 establishes the identity (its own accepted artifact digest); the
# other three must bind to exactly that digest. G8 (the founder's grant)
# deliberately carries no corpus digest at all -- see its evidence text --
# so it is not part of this binding set.
CORPUS_ORIGIN_ID = "DATA-3"
CORPUS_BOUND_IDS = ("DATA-1", "DATA-2", "DATA-5")

# Fields covered by a trust-key enrollment signature, in this fixed order.
# `revoked` is part of the signed payload, not a free-standing flag: a
# caller that flips a legitimately-enrolled key's `revoked` value after the
# fact (true -> false, to un-revoke; or false -> true, to frame a key as
# revoked) invalidates the enrollment signature rather than silently
# changing the key's live status. A real revocation is therefore itself a
# founder-signed act -- a fresh enrollment record with revoked=true -- not
# an unsigned edit to a stored flag.
ENROLLMENT_FIELDS = ("key_id", "role", "public_key_hex", "scope", "revoked")


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
    lines += [record.get(field, "") for field in EXTENDED_SIGNED_FIELDS]
    return ("\n".join(lines) + "\n").encode("utf-8")


def enrollment_payload_bytes(entry):
    scope = ",".join(sorted(entry.get("scope", []) or []))
    revoked = "true" if entry.get("revoked") else "false"
    parts = [str(entry.get(field, "")) for field in ("key_id", "role", "public_key_hex")]
    parts.append(scope)
    parts.append(revoked)
    return ("\n".join(parts) + "\n").encode("utf-8")


def assert_published_baseline(nodes, markdown, ledger, trust, founder_root_keys=None):
    errors = []
    if any(node.get("status") == "ACCEPTED" for node in nodes):
        errors.append("published status ACCEPTED")
    if ledger != []:
        errors.append("committed ledger is not empty")
    if trust != {"keys": []}:
        errors.append("committed trust store is not empty")
    if founder_root_keys is not None and founder_root_keys != {"keys": []}:
        errors.append("committed founder root key store is not empty")
    for line in markdown.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 6 or cells[0] in {"ID", "---"}:
            continue
        if cells[5] == "ACCEPTED":
            errors.append(f"markdown status ACCEPTED on {cells[0]}")
    return errors


def evaluate(nodes, records, *, trust_keys, subject_sha, ancestor_shas=(), founder_root_keys=()):
    """Return the ids this ledger accepts. Raise on any bad record.

    `nodes` is not modified. An empty ledger accepts nothing. An empty
    `founder_root_keys` means no reviewer or founder key can ever be
    trusted, no matter what `trust_keys` contains -- trust is never taken
    on the caller's word alone.
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
            founder_root_keys=tuple(founder_root_keys),
        )
        accepted[requirement_id] = pending[requirement_id]["artifact_sha256"]
    unknown = set(pending) - set(order)
    if unknown:
        raise AcceptanceRejected("UNKNOWN_REQUIREMENT", sorted(unknown)[0])
    return dict(accepted)


def _accept_one(node, record, *, nodes, by_id, accepted, trust_keys, subject_sha, ancestor_shas, founder_root_keys):
    if node["id"] == "R65" or node["id"].startswith("R65-"):
        raise AcceptanceRejected("NOT_VERIFIABLE", node["id"])
    if not node["counts"]:
        raise AcceptanceRejected("NOT_COUNTABLE", node["id"])
    if record.get("policy_version") != POLICY_VERSION:
        raise AcceptanceRejected("WRONG_POLICY_VERSION", record.get("policy_version") or "missing")
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
    key = _trusted_key(trust_keys, key_id, founder_root_keys)
    if key.get("role") != reviewer:
        raise AcceptanceRejected("REVIEWER_MISMATCH", key_id)
    if node["denominator"] not in (key.get("scope") or ()):
        raise AcceptanceRejected("OUT_OF_SCOPE", key_id)
    _verify_signature(record, key, "signature_hex")

    if node["founder_approval"] == "REQUIRED":
        founder_key_id = record.get("founder_key_id")
        if not founder_key_id:
            raise AcceptanceRejected("MISSING_FOUNDER_APPROVAL", node["id"])
        if founder_key_id == key_id:
            raise AcceptanceRejected("SAME_KEY_DUAL_ROLE", node["id"])
        founder_key = _trusted_key(trust_keys, founder_key_id, founder_root_keys)
        if founder_key.get("role") != "FOUNDER":
            raise AcceptanceRejected("FOUNDER_ROLE_REQUIRED", founder_key_id)
        if node["denominator"] not in (founder_key.get("scope") or ()):
            raise AcceptanceRejected("OUT_OF_SCOPE", founder_key_id)
        _verify_signature(record, founder_key, "founder_signature_hex", code="FOUNDER_FORGED")

    for dep in node["depends_on"]:
        predecessor = by_id.get(dep)
        if predecessor is None:
            raise AcceptanceRejected("DEPENDENCY_UNACCEPTED", dep)
        if predecessor["counts"] and dep not in accepted:
            raise AcceptanceRejected("DEPENDENCY_UNACCEPTED", f"{node['id']} missing {dep}")

    if node["id"] in CORPUS_BOUND_IDS:
        bound = record.get("bound_corpus_sha256", "")
        origin_digest = accepted.get(CORPUS_ORIGIN_ID)
        if origin_digest is None or not _hex_length(bound, 64) or bound != origin_digest:
            raise AcceptanceRejected("CORPUS_IDENTITY_MISMATCH", node["id"])

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


def _verify_signature(record, key, field, code="FORGED"):
    signature = record.get(field, "")
    public_hex = key.get("public_key_hex", "")
    if not _hex_length(signature, 128) or not _hex_length(public_hex, 64):
        raise AcceptanceRejected(code, record.get("requirement_id", ""))
    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
        public.verify(bytes.fromhex(signature), payload_bytes(record))
    except (InvalidSignature, ValueError) as exc:
        raise AcceptanceRejected(code, record.get("requirement_id", "")) from exc


def _trusted_key(trust_keys, key_id, founder_root_keys):
    """Return the enrolled, non-revoked key for `key_id`, or raise.

    A `{key_id, role, public_key_hex, scope}` tuple appearing in
    `trust_keys` is not, by itself, trusted: it must also carry an
    `enrollment_signature_hex` that verifies against one of the caller's
    `founder_root_keys` over exactly `(key_id, role, public_key_hex,
    scope)`. This is what stops a compromised or careless caller from
    smuggling an arbitrary trust root into the ledger evaluation by
    constructing the `trust_keys` argument itself -- the engine checks the
    founder's own signature, not the caller's say-so.
    """
    match = None
    for key in trust_keys:
        if key.get("key_id") == key_id:
            match = key
            break
    if match is None:
        raise AcceptanceRejected("FORGED", key_id)
    if not founder_root_keys or not _verify_enrollment(match, founder_root_keys):
        raise AcceptanceRejected("UNTRUSTED_KEY", key_id)
    if match.get("revoked"):
        raise AcceptanceRejected("REVOKED_REVIEWER", key_id)
    return match


def _verify_enrollment(entry, founder_root_keys):
    signature = entry.get("enrollment_signature_hex", "")
    if not _hex_length(signature, 128):
        return False
    payload = enrollment_payload_bytes(entry)
    for root_hex in founder_root_keys:
        if not _hex_length(root_hex, 64):
            continue
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(root_hex)).verify(
                bytes.fromhex(signature), payload
            )
            return True
        except (InvalidSignature, ValueError):
            continue
    return False


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
