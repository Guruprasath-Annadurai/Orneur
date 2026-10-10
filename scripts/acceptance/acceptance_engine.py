"""Fail-closed acceptance for the ORNEUR register.

The published graph status is not an acceptance bit. A row advances only
when this module verifies a detached signature over that row's own
artifact. This module does not write the register, the ledger, or any
authorization file, and it does not authorize training.

History: Phase 0 remediation (temporary Cursor-to-Claude handoff) added
founder authority, corpus-identity binding, and founder-enrolled reviewer
trust on top of the original reviewer-attestation gate. A trust-boundary
hardening pass then closed a real, reproduced revocation-replay bug with
per-entry epochs. This third pass replaces the epoch scheme entirely with
something structurally stronger, after further review found the epoch
scheme still let a caller omit a newer record and succeed with a stale one
("REVOCATION OMISSION"), and raised three further gaps (founder-root
authority, evidence integrity, policy/corpus identity). What follows is the
final design, not an incremental patch on the epoch scheme:

  * Trust is no longer "a caller-supplied list of individually-signed
    entries, pick the newest". It is now two whole, atomically-signed
    documents -- a ``root_state`` (which founder roots are currently
    valid) and a ``trust_snapshot`` (which reviewer/founder keys are
    currently valid) -- each bound to the EXACT commit SHA under
    evaluation via the same staleness check already used for evidence
    rows (``WRONG_ROOT_STATE_SHA``/``STALE_ROOT_STATE``,
    ``WRONG_TRUST_SNAPSHOT_SHA``/``STALE_TRUST_SNAPSHOT``). A caller
    cannot "choose" to present an old, still-validly-signed snapshot
    instead of a newer one, because the old one's signature covers an
    ancestor SHA, not the current one -- the real trust state at commit
    X is the one document the founder actually signed for commit X, the
    same way an evidence record's `git_sha` already pins it to one
    commit. Within one snapshot/root-state, a duplicate `key_id` /
    `root_id` is rejected outright (`DUPLICATE_ENROLLMENT`,
    `DUPLICATE_ROOT`) -- there is no notion of "two entries, which one
    wins" any more.
  * `root_state` is itself anchored to a single, permanent
    `bootstrap_root_key_hex` supplied by the caller from a committed,
    normally-empty file (`BOOTSTRAP_ROOT_KEY.json`) -- a caller cannot
    make its own generated root authoritative merely by passing it in;
    only a root_state signed by the bootstrap key is ever trusted, and a
    root_state's own `roots` list is what `trust_snapshot` must be signed
    against (by any one non-revoked root in it).
  * Evidence integrity now requires either (a) the caller to present
    actual artifact bytes (`artifact_bytes`) that hash to the record's
    declared digest, for ordinary rows, or (b) for the four protected
    corpus-evidence classes (where real content must never be
    generated or accessed), a non-disclosing custody-possession
    signature over a challenge derived from the digest and commit, from
    the row's own reviewer key -- a correctly SHAPED digest with a valid
    reviewer signature is no longer enough on its own.
  * The corpus-identity record DATA-3 declares (`corpus_identity_sha256`)
    is now a distinct, separately-signed field from DATA-3's own
    `artifact_sha256` (the digest of DATA-3's creation *record*, not of
    "the corpus"). DATA-1/DATA-2/DATA-5 bind to that distinct identity
    field (`bound_corpus_identity_sha256`), not to DATA-3's record
    digest. DATA-5's custody independence is now checked against the
    actual resolved `public_key_hex`, not the caller-chosen `key_id`
    label two different identities could otherwise share.
  * `POLICY_VERSION` is now the sha256 of the policy document, this
    engine's own source, and the published register graph JSON
    concatenated -- "policy identity" now commits to the actual
    enforcement code and graph, not only a prose document.

Audit #003 then found that binding `trust_snapshot`/`root_state` to the
exact commit SHA closes rollback ACROSS commits, but not a same-commit
rollback: nothing stopped the founder's own root from validly signing TWO
different trust_snapshot generations for the SAME `subject_sha` (e.g. one
before and one after a revocation decided without a code change), and a
caller presenting the earlier one would verify just as cleanly as the
later one -- git_sha equality alone cannot order two documents for the one
commit it names. The audit note is explicit: do not "fix" this by
embedding a commit's own SHA inside a file committed as part of that same
commit -- that is a self-referential hash dependency (the tree you are
hashing to get the commit's SHA would need to already contain a file that
names that same SHA). This module does not do that. Three separate things
now exist, matching what the audit asked for:

  1. The immutable code/policy commit being evaluated (`subject_sha`) --
     unchanged, external to this module.
  2. The signed trust-state snapshot (`trust_snapshot`/`root_state`) --
     bound to `subject_sha`, as before, but that alone is not "current".
  3. A separate, also-signed `trust_checkpoint` that commits to the exact
     hash of #2 (both `trust_snapshot` and `root_state` together) for
     `subject_sha`, whose own hash must equal a `pinned_checkpoint_hash`
     supplied by the caller from a channel independent of both #1 and #2.

A same-SHA rollback (two validly-signed snapshots at different
generations, same commit) is closed by exact pinning, not generation
comparison: a hash pin matches at most one document, full stop, regardless
of how many other validly-signed-but-different documents also exist for
that commit. This module cannot determine *which* checkpoint is "current"
by itself -- that is an operational, out-of-band fact (independently
published, witnessed, or mirrored, the way a certificate-transparency
checkpoint is), and `pinned_checkpoint_hash` is exactly the seam where that
external fact enters. This module only verifies that what it was given is
consistent and matches that external pin; it does not invent one, and the
committed baseline has none, so no trust_checkpoint can ever verify until
a real one is actually pinned by that external process.

Audit #003 also asked that the bootstrap root itself not become
authoritative merely because a caller passed it in. `bootstrap_root_key_hex`
is now checked against `PINNED_BOOTSTRAP_ROOT_KEYS`, a frozenset literal in
this module's own source (not read from any file a caller or this repo's
own commit history could alone control) -- committed empty, exactly like
every other trust material in this program, so no bootstrap identity is
authoritative yet. Pinning it here, in the engine's source, is the
"pinned release identity" the audit asked for: changing it changes
`POLICY_VERSION` too (the engine's own source is part of that hash),
so a silently swapped pin is not silent.
"""

from __future__ import annotations

import hashlib
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_ACCEPTANCE_DIR = Path(__file__).resolve().parents[2] / "docs" / "orneur" / "acceptance"
_POLICY_DOC = _ACCEPTANCE_DIR / "ACCEPTANCE_POLICY.md"
_ENGINE_SOURCE = Path(__file__).resolve()
_GRAPH_DOC = _ACCEPTANCE_DIR / "register_graph.json"

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
# changed without invalidating the signature -- a policy_version downgrade
# or a corpus-identity swap after the fact is a forgery, not a silent edit.
EXTENDED_SIGNED_FIELDS = (
    "policy_version",
    "corpus_identity_sha256",
    "bound_corpus_identity_sha256",
)


def _policy_version():
    data = _POLICY_DOC.read_bytes() + _ENGINE_SOURCE.read_bytes()
    if _GRAPH_DOC.exists():
        data += _GRAPH_DOC.read_bytes()
    return "orneur-acceptance-policy/" + hashlib.sha256(data).hexdigest()


# "Policy identity" bound to real content: the policy document's prose,
# this engine's own source code, and the published register graph JSON,
# concatenated and hashed together. Changing any of the three -- the
# written policy, the enforcement code itself, or the graph it enforces --
# changes this value and invalidates every previously-signed record for a
# new ledger. A free-floating version label could be typed correctly by
# anyone; this cannot be satisfied without the underlying content matching.
POLICY_VERSION = _policy_version()

# The protected-corpus evidence rows. DATA-3 declares the corpus identity;
# the other three must bind to exactly that identity (not to DATA-3's own
# record digest -- see corpus_identity_sha256 below). G8 (the founder's
# grant) deliberately carries no corpus digest or identity at all -- see
# its evidence text -- so it is not part of this binding set.
CORPUS_ORIGIN_ID = "DATA-3"
CORPUS_BOUND_IDS = ("DATA-1", "DATA-2", "DATA-5")

# Real content must never be generated or accessed for these artifact
# classes (see CORPUS_ARTIFACTS in validate_register_graph.py) -- evidence
# integrity for them is a non-disclosing custody-possession signature,
# never a byte-for-byte hash check.
PROTECTED_EVIDENCE_CLASSES = {
    "protected-corpus-creation",
    "corpus-provenance-manifest",
    "corpus-custody-integrity",
    "contamination-holdout-separation",
}

# DATA-5 (corpus custody and integrity) must be an INDEPENDENT custodian,
# not merely a same-named-role rubber stamp: its own register evidence text
# says "a custodian who is not the creator". Checked against the resolved
# entry's actual public_key_hex, not the caller-chosen key_id label --
# two different key_ids could otherwise be enrolled with the same
# underlying keypair and look independent when they are not.
CUSTODY_INDEPENDENT_FROM = {"DATA-5": "DATA-3"}

# Pinned release identity for the bootstrap root (audit #003, task 3): a
# caller-supplied bootstrap key is never authoritative merely by being
# passed in, even if it matches a root_state signature -- it must ALSO
# appear here, in this module's own source, not in any file this repo's
# own commit history alone could edit. Committed empty: no real bootstrap
# identity exists yet, so no root_state can ever verify for real use.
# Tests populate this via monkeypatch to exercise the positive path with a
# synthetic key; they never add a real one.
PINNED_BOOTSTRAP_ROOT_KEYS = frozenset()


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


def custody_challenge_bytes(record):
    """A non-disclosing possession challenge: binds a custody signature to
    this exact requirement, digest, and commit, without needing (and
    without this module ever touching) the underlying protected content."""
    parts = [
        record.get("requirement_id", ""),
        record.get("artifact_sha256", ""),
        record.get("git_sha", ""),
        "POSSESSION_ATTESTATION_V1",
    ]
    return ("\n".join(parts) + "\n").encode("utf-8")


def root_state_payload_bytes(root_state):
    roots = root_state.get("roots", []) or []
    canon = ",".join(sorted(
        f"{r.get('root_id', '')}:{r.get('public_key_hex', '')}:{'1' if r.get('revoked') else '0'}"
        for r in roots
    ))
    parts = [str(root_state.get("git_sha", "")), str(root_state.get("generation", "")), canon]
    return ("\n".join(parts) + "\n").encode("utf-8")


def trust_snapshot_payload_bytes(snapshot):
    entries = snapshot.get("entries", []) or []
    canon = ",".join(sorted(
        f"{e.get('key_id', '')}:{e.get('role', '')}:{e.get('public_key_hex', '')}:"
        f"{','.join(sorted(e.get('scope', []) or []))}:{'1' if e.get('revoked') else '0'}"
        for e in entries
    ))
    parts = [str(snapshot.get("git_sha", "")), str(snapshot.get("generation", "")), canon]
    return ("\n".join(parts) + "\n").encode("utf-8")


def checkpoint_payload_bytes(checkpoint):
    parts = [
        str(checkpoint.get("subject_sha", "")),
        str(checkpoint.get("generation", "")),
        str(checkpoint.get("trust_snapshot_hash", "")),
        str(checkpoint.get("root_state_hash", "")),
        str(checkpoint.get("previous_checkpoint_hash", "")),
    ]
    return ("\n".join(parts) + "\n").encode("utf-8")


def assert_published_baseline(
    nodes, markdown, ledger, trust_snapshot, root_state=None, bootstrap=None, trust_checkpoint=None,
):
    errors = []
    empty_snapshot = {"git_sha": "", "generation": 0, "entries": [], "signature_hex": ""}
    empty_root_state = {"git_sha": "", "generation": 0, "roots": [], "signature_hex": ""}
    empty_bootstrap = {"public_key_hex": ""}
    empty_checkpoint = {
        "subject_sha": "", "generation": 0, "trust_snapshot_hash": "",
        "root_state_hash": "", "previous_checkpoint_hash": "", "signature_hex": "",
    }
    if any(node.get("status") == "ACCEPTED" for node in nodes):
        errors.append("published status ACCEPTED")
    if ledger != []:
        errors.append("committed ledger is not empty")
    if trust_snapshot != empty_snapshot:
        errors.append("committed trust snapshot is not empty")
    if root_state is not None and root_state != empty_root_state:
        errors.append("committed root state is not empty")
    if bootstrap is not None and bootstrap != empty_bootstrap:
        errors.append("committed bootstrap root key is not empty")
    if trust_checkpoint is not None and trust_checkpoint != empty_checkpoint:
        errors.append("committed trust checkpoint is not empty")
    for line in markdown.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 6 or cells[0] in {"ID", "---"}:
            continue
        if cells[5] == "ACCEPTED":
            errors.append(f"markdown status ACCEPTED on {cells[0]}")
    return errors


def evaluate(
    nodes,
    records,
    *,
    trust_snapshot,
    root_state,
    bootstrap_root_key_hex,
    subject_sha,
    ancestor_shas=(),
    artifact_bytes=None,
    trust_checkpoint=None,
    pinned_checkpoint_hash=None,
):
    """Return the ids this ledger accepts. Raise on any bad record.

    `nodes` is not modified. An empty ledger accepts nothing and is
    checked before `trust_snapshot`/`root_state`/`trust_checkpoint` are
    even inspected, so an empty ledger needs no real trust material at
    all. Once there is at least one record:

      - `root_state` must verify against a bootstrap key that is BOTH
        `bootstrap_root_key_hex` AND a member of the hardcoded
        `PINNED_BOOTSTRAP_ROOT_KEYS` -- a caller cannot make its own
        generated bootstrap authoritative merely by passing it in.
      - `trust_snapshot` must verify against a non-revoked root in
        `root_state`.
      - Both must be bound to the exact `subject_sha` (stale/wrong-SHA
        rejected the same way a stale evidence record is).
      - `trust_checkpoint` must verify against a non-revoked root too,
        must commit to the exact hash of both `trust_snapshot` and
        `root_state` for this `subject_sha`, and its own hash must equal
        the caller-supplied `pinned_checkpoint_hash` -- a value this
        module never derives on its own, only compares against. This is
        what stops a same-commit rollback: two different, both validly
        signed, trust_snapshot generations can exist for one `subject_sha`
        (nothing about commit identity alone orders them), but only the
        one named by the externally pinned checkpoint hash will ever
        match -- exact equality, not "latest generation wins".
    """
    by_id = {node["id"]: node for node in nodes}
    if not isinstance(records, list):
        raise AcceptanceRejected("MISSING_FIELD", "ledger")
    if not records:
        return {}

    ancestor_shas = set(ancestor_shas)
    roots = _verify_root_state(root_state, bootstrap_root_key_hex, subject_sha, ancestor_shas)
    by_key_id = _verify_trust_snapshot(trust_snapshot, roots, subject_sha, ancestor_shas)
    _verify_checkpoint(trust_checkpoint, trust_snapshot, root_state, roots, subject_sha, pinned_checkpoint_hash)
    artifact_bytes = artifact_bytes or {}

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
    accepted_public_keys = {}
    accepted_corpus_identities = {}
    for requirement_id in order:
        if requirement_id not in pending:
            continue
        key = _accept_one(
            by_id[requirement_id],
            pending[requirement_id],
            nodes=nodes,
            by_id=by_id,
            accepted=accepted,
            accepted_public_keys=accepted_public_keys,
            accepted_corpus_identities=accepted_corpus_identities,
            by_key_id=by_key_id,
            subject_sha=subject_sha,
            ancestor_shas=ancestor_shas,
            artifact_bytes=artifact_bytes,
        )
        accepted[requirement_id] = pending[requirement_id]["artifact_sha256"]
        accepted_public_keys[requirement_id] = key.get("public_key_hex")
        accepted_corpus_identities[requirement_id] = pending[requirement_id].get("corpus_identity_sha256", "")
    unknown = set(pending) - set(order)
    if unknown:
        raise AcceptanceRejected("UNKNOWN_REQUIREMENT", sorted(unknown)[0])
    return dict(accepted)


def _accept_one(
    node,
    record,
    *,
    nodes,
    by_id,
    accepted,
    accepted_public_keys,
    accepted_corpus_identities,
    by_key_id,
    subject_sha,
    ancestor_shas,
    artifact_bytes,
):
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
    key = _resolve_key(by_key_id, key_id)
    if key.get("role") != reviewer:
        raise AcceptanceRejected("REVIEWER_MISMATCH", key_id)
    if node["denominator"] not in (key.get("scope") or ()):
        raise AcceptanceRejected("OUT_OF_SCOPE", key_id)
    _verify_signature(record, key, "signature_hex")

    artifact_class = node["artifact_class"]
    digest = record["artifact_sha256"]
    if artifact_class in PROTECTED_EVIDENCE_CLASSES:
        custody_signature = record.get("custody_signature_hex", "")
        if not _verify_whole_signature(
            custody_challenge_bytes(record), custody_signature, key.get("public_key_hex", "")
        ):
            raise AcceptanceRejected("CUSTODY_NOT_AUTHENTICATED", node["id"])
    else:
        content = artifact_bytes.get(digest)
        if content is None or hashlib.sha256(content).hexdigest() != digest:
            raise AcceptanceRejected("EVIDENCE_NOT_RESOLVED", node["id"])

    if node["founder_approval"] == "REQUIRED":
        founder_key_id = record.get("founder_key_id")
        if not founder_key_id:
            raise AcceptanceRejected("MISSING_FOUNDER_APPROVAL", node["id"])
        if founder_key_id == key_id:
            raise AcceptanceRejected("SAME_KEY_DUAL_ROLE", node["id"])
        founder_key = _resolve_key(by_key_id, founder_key_id)
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

    if node["id"] == CORPUS_ORIGIN_ID:
        identity = record.get("corpus_identity_sha256", "")
        if not _hex_length(identity, 64):
            raise AcceptanceRejected("MISSING_CORPUS_IDENTITY", node["id"])
    if node["id"] in CORPUS_BOUND_IDS:
        bound = record.get("bound_corpus_identity_sha256", "")
        origin_identity = accepted_corpus_identities.get(CORPUS_ORIGIN_ID)
        if not origin_identity or not _hex_length(bound, 64) or bound != origin_identity:
            raise AcceptanceRejected("CORPUS_IDENTITY_MISMATCH", node["id"])

    creator_id = CUSTODY_INDEPENDENT_FROM.get(node["id"])
    if creator_id is not None:
        creator_pubkey = accepted_public_keys.get(creator_id)
        if creator_pubkey is None or key.get("public_key_hex") == creator_pubkey:
            raise AcceptanceRejected("CUSTODY_NOT_INDEPENDENT", node["id"])

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

    return key


def _require_match(record, field, expected, code):
    actual = record.get(field)
    if actual is None:
        raise AcceptanceRejected("MISSING_FIELD", field)
    if actual != expected:
        raise AcceptanceRejected(code, field)


def _verify_whole_signature(payload, signature_hex, public_key_hex):
    if not _hex_length(signature_hex, 128) or not _hex_length(public_key_hex, 64):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(
            bytes.fromhex(signature_hex), payload
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def _verify_signature(record, key, field, code="FORGED"):
    if not _verify_whole_signature(payload_bytes(record), record.get(field, ""), key.get("public_key_hex", "")):
        raise AcceptanceRejected(code, record.get("requirement_id", ""))


def _non_negative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _verify_root_state(root_state, bootstrap_root_key_hex, subject_sha, ancestor_shas):
    """Verify the whole root_state document and return its `roots` list.

    `root_state` names which founder roots are currently valid. It is
    trusted only if it verifies against `bootstrap_root_key_hex` -- a
    caller cannot make its own generated root authoritative merely by
    passing it into this function. It must also be for the exact commit
    under evaluation: an older, still-validly-bootstrap-signed root_state
    (e.g. one that had not yet revoked a since-compromised root) is
    rejected the same way a stale evidence record is, not treated as an
    acceptable substitute for the current one.
    """
    if not isinstance(root_state, dict):
        raise AcceptanceRejected("MALFORMED_ROOT_STATE", "root_state")
    if not _non_negative_int(root_state.get("generation")):
        raise AcceptanceRejected("MALFORMED_GENERATION", "root_state")
    git_sha = root_state.get("git_sha", "")
    if not _hex_length(git_sha, 40):
        raise AcceptanceRejected("WRONG_ROOT_STATE_SHA", git_sha or "missing")
    if git_sha != subject_sha:
        code = "STALE_ROOT_STATE" if git_sha in ancestor_shas else "WRONG_ROOT_STATE_SHA"
        raise AcceptanceRejected(code, git_sha)
    if not _hex_length(bootstrap_root_key_hex, 64):
        raise AcceptanceRejected("NO_BOOTSTRAP_ANCHOR", "bootstrap_root_key_hex")
    if bootstrap_root_key_hex not in PINNED_BOOTSTRAP_ROOT_KEYS:
        raise AcceptanceRejected("UNPINNED_BOOTSTRAP", bootstrap_root_key_hex)
    if not _verify_whole_signature(
        root_state_payload_bytes(root_state), root_state.get("signature_hex", ""), bootstrap_root_key_hex
    ):
        raise AcceptanceRejected("UNTRUSTED_ROOT_STATE", "root_state")
    roots = root_state.get("roots", [])
    if not isinstance(roots, list):
        raise AcceptanceRejected("MALFORMED_ROOT_STATE", "roots")
    seen = set()
    for root in roots:
        root_id = root.get("root_id") if isinstance(root, dict) else None
        if root_id is None or root_id in seen:
            raise AcceptanceRejected("DUPLICATE_ROOT", root_id)
        seen.add(root_id)
    return roots


def _verify_trust_snapshot(trust_snapshot, roots, subject_sha, ancestor_shas):
    """Verify the whole trust_snapshot document and return its entries,
    keyed by key_id. Signed by any one currently non-revoked root from
    `roots`; bound to the exact commit the same way root_state is."""
    if not isinstance(trust_snapshot, dict):
        raise AcceptanceRejected("MALFORMED_TRUST_SNAPSHOT", "trust_snapshot")
    if not _non_negative_int(trust_snapshot.get("generation")):
        raise AcceptanceRejected("MALFORMED_GENERATION", "trust_snapshot")
    git_sha = trust_snapshot.get("git_sha", "")
    if not _hex_length(git_sha, 40):
        raise AcceptanceRejected("WRONG_TRUST_SNAPSHOT_SHA", git_sha or "missing")
    if git_sha != subject_sha:
        code = "STALE_TRUST_SNAPSHOT" if git_sha in ancestor_shas else "WRONG_TRUST_SNAPSHOT_SHA"
        raise AcceptanceRejected(code, git_sha)
    payload = trust_snapshot_payload_bytes(trust_snapshot)
    signature = trust_snapshot.get("signature_hex", "")
    active_roots = [r for r in roots if isinstance(r, dict) and not r.get("revoked")]
    if not any(_verify_whole_signature(payload, signature, r.get("public_key_hex", "")) for r in active_roots):
        raise AcceptanceRejected("UNTRUSTED_TRUST_SNAPSHOT", "trust_snapshot")
    entries = trust_snapshot.get("entries", [])
    if not isinstance(entries, list):
        raise AcceptanceRejected("MALFORMED_TRUST_SNAPSHOT", "entries")
    by_key_id = {}
    for entry in entries:
        key_id = entry.get("key_id") if isinstance(entry, dict) else None
        if key_id is None or key_id in by_key_id:
            raise AcceptanceRejected("DUPLICATE_ENROLLMENT", key_id)
        by_key_id[key_id] = entry
    return by_key_id


def _verify_checkpoint(trust_checkpoint, trust_snapshot, root_state, roots, subject_sha, pinned_checkpoint_hash):
    """Verify the independently-pinned checkpoint that names which exact
    trust_snapshot/root_state pair is current for `subject_sha`.

    This is the third, separate document audit #003 asked for: distinct
    from the code commit (`subject_sha`) and from the trust-state
    documents themselves. It closes a same-commit rollback that binding to
    `subject_sha` alone cannot: two different trust_snapshot generations
    can both validly carry the same `subject_sha` (nothing about the
    commit orders them), so freshness here comes from an exact match
    against `pinned_checkpoint_hash` -- a value from a channel independent
    of this call, never computed by this module. No committed checkpoint
    exists yet (this document is entirely unused while the ledger is
    empty), so this only ever runs once a real ledger, trust_snapshot,
    root_state, trust_checkpoint, and pin all exist together.
    """
    if not isinstance(trust_checkpoint, dict):
        raise AcceptanceRejected("MALFORMED_CHECKPOINT", "trust_checkpoint")
    if not _non_negative_int(trust_checkpoint.get("generation")):
        raise AcceptanceRejected("MALFORMED_GENERATION", "trust_checkpoint")
    if trust_checkpoint.get("subject_sha") != subject_sha:
        raise AcceptanceRejected("WRONG_CHECKPOINT_SHA", trust_checkpoint.get("subject_sha") or "missing")
    expected_snapshot_hash = hashlib.sha256(trust_snapshot_payload_bytes(trust_snapshot)).hexdigest()
    expected_root_hash = hashlib.sha256(root_state_payload_bytes(root_state)).hexdigest()
    if trust_checkpoint.get("trust_snapshot_hash") != expected_snapshot_hash:
        raise AcceptanceRejected("CHECKPOINT_SNAPSHOT_MISMATCH", "trust_snapshot_hash")
    if trust_checkpoint.get("root_state_hash") != expected_root_hash:
        raise AcceptanceRejected("CHECKPOINT_SNAPSHOT_MISMATCH", "root_state_hash")
    payload = checkpoint_payload_bytes(trust_checkpoint)
    signature = trust_checkpoint.get("signature_hex", "")
    active_roots = [r for r in roots if isinstance(r, dict) and not r.get("revoked")]
    if not any(_verify_whole_signature(payload, signature, r.get("public_key_hex", "")) for r in active_roots):
        raise AcceptanceRejected("UNTRUSTED_CHECKPOINT", "trust_checkpoint")
    actual_hash = hashlib.sha256(payload).hexdigest()
    if not pinned_checkpoint_hash or actual_hash != pinned_checkpoint_hash:
        raise AcceptanceRejected("UNPINNED_CHECKPOINT", actual_hash)


def _resolve_key(by_key_id, key_id):
    entry = by_key_id.get(key_id)
    if entry is None:
        raise AcceptanceRejected("FORGED", key_id)
    if entry.get("revoked"):
        raise AcceptanceRejected("REVOKED_REVIEWER", key_id)
    return entry


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
