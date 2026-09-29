"""Corpus-generation authorization gate (fail closed).

This is a DELIBERATELY SEPARATE gate from everything built in prior phases. Registering an owner authority key
(authority_registry.py) does not authorize corpus generation. A signed corpus-inventory attestation
(inventory.evaluate_pre_corpus_attestation) does not authorize corpus generation. owner_preflight returning
READY_FOR_PRIVATE_CORPUS_AUTHORIZATION does not authorize corpus generation — it only means the preparation
machinery is ready to be authorized, which is a human decision this module never makes for the owner.

Corpus generation (PILOT_TRAIN, DEV, SCREEN, QUALIFICATION_HOLDOUT) may proceed ONLY when a SEPARATE,
purpose-scoped, Ed25519-signed CORPUS_GENERATION_AUTHORIZATION record exists that:
  - has status == AUTHORIZED (the committed record is NOT_AUTHORIZED and stays that way until the owner signs one),
  - names purpose == "PRIVATE_V2_CORPUS_GENERATION" exactly (no generic "OWNER approved something" record can be reused here),
  - scopes exactly which artifact classes it authorizes (a subset of PILOT_TRAIN/DEV/SCREEN/QUALIFICATION_HOLDOUT),
  - binds authorized_artifact_digests to the exact evidence state (inventory digest, preregistration record hash) the
    owner reviewed when signing — if that evidence has since changed, the authorization no longer matches and fails,
  - has a short validity window (issued_at/expires_at, MAX_VALIDITY below) — an expired authorization fails,
  - has a real Ed25519 signature verified against a registered, active, non-revoked OWNER authority key.

## Commit binding (schema /2): code-tree hash + ancestry, not literal commit-SHA equality

Schema /1 bound `authorized_commit_sha` by exact equality against the executing commit. That is circular: the signed
record must itself be committed to the repository for a later execution to read it, and the commit that adds the
signed record is necessarily a DIFFERENT, not-yet-existing commit at signing time (the owner cannot know its hash in
advance — it depends on the record's own content, including the signature). Requiring literal equality would make
every real authorization unusable the moment it is actually committed and read.

Schema /2 instead binds:
  - `reviewed_commit_sha` — the commit that existed, and that the owner actually reviewed, at signing time. The
    execution commit must be that commit OR A DESCENDANT OF IT (`git merge-base --is-ancestor`), never an unrelated
    or rolled-back commit — this preserves forward-only replay protection without requiring literal equality.
  - `authorized_code_tree_sha256` — a SHA-256 over the exact generator code paths (`CODE_PATHS`) as they existed at
    `reviewed_commit_sha`. This is the REAL binding that survives the "evidence commit" problem: a later commit that
    only adds the signed authorization record (touching authorization/evidence JSON, not `CODE_PATHS`) does not
    change this hash, so the authorization still verifies; a commit that changes so much as one byte of the actual
    generator code the owner reviewed makes the hash mismatch and denies — code drift after review is caught even
    if it happens on the SAME commit lineage the ancestry check would otherwise accept.
  - the execution's working tree must be clean (`git status --porcelain` empty) — dirty or uncommitted code is never
    authorized, regardless of what HEAD says.

Any missing field, wrong purpose, out-of-scope artifact, non-ancestor commit, dirty working tree, mismatched code-tree
hash, mismatched evidence digest, expired window, unregistered key, revoked key, or invalid signature fails closed.
There is no code path in `verify()` that returns authorized=True without an explicit, valid, signed AUTHORIZED record
matching the exact request.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-corpus-generation-authorization/2"
RECORD_PATH = "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION.json"
PURPOSE = "PRIVATE_V2_CORPUS_GENERATION"          # the only purpose value this gate ever accepts
ARTIFACT_CLASSES = ("PILOT_TRAIN", "DEV", "SCREEN", "QUALIFICATION_HOLDOUT")
MAX_VALIDITY = timedelta(days=7)                  # an authorization older than this can never verify, regardless of expires_at
# The exact code whose content the code-tree hash binds to. Mirrors runner_registry.code_sha256_of's own pattern.
CODE_PATHS = ("orca/eval/genesis_v2",)            # directories; every *.py file within, sorted, is included

RECORD_KEYS = frozenset({"schema_version", "authorization_id", "status", "purpose", "authorized_scope", "reviewed_commit_sha",
                         "authorized_code_tree_sha256", "authorized_artifact_digests", "issued_at", "expires_at",
                         "authorizing_authority", "signature"})
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^cgauth-[0-9a-f]{16,64}$")


@dataclass(frozen=True)
class Request:
    """What is actually about to happen. Built from the real execution context, never trusted from the record."""
    commit_sha: str                                # the ACTUAL executing commit (informational/logged; ancestry-checked, not equality-checked)
    commit_is_descendant: bool                      # `git merge-base --is-ancestor reviewed_commit_sha commit_sha` — computed by the caller
    working_tree_clean: bool                        # `git status --porcelain` empty at execution time — computed by the caller
    current_code_tree_sha256: str                   # freshly recomputed hash of CODE_PATHS at execution time — never trusted from the record
    requested_scope: tuple                          # subset of ARTIFACT_CLASSES actually being generated right now
    current_inventory_digest: str
    current_prereg_record_sha256: str
    event_name: str = ""


@dataclass
class Verdict:
    authorized: bool
    reasons: list = field(default_factory=list)


def default_record() -> dict:
    return {"schema_version": SCHEMA_VERSION, "authorization_id": None, "status": "NOT_AUTHORIZED", "purpose": None,
            "authorized_scope": [], "reviewed_commit_sha": None, "authorized_code_tree_sha256": None, "authorized_artifact_digests": {},
            "issued_at": None, "expires_at": None, "authorizing_authority": {"identity": None, "role": None, "key_id": None}, "signature": None}


def code_tree_sha256(root: Path) -> str:
    """The live, independently-recomputable hash CODE_PATHS binds to — reuses runner_registry's own hashing helper
    so both registries agree on what "the generator code" means byte-for-byte."""
    from orca.eval.genesis_v2 import runner_registry as RN
    root = Path(root)
    files = []
    for rel in CODE_PATHS:
        files.extend(sorted((root / rel).glob("*.py")))
    return RN.code_sha256_of(files)


def _ts_ok(s) -> bool:
    return isinstance(s, str) and bool(_TS.match(s))


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def canonical_signing_bytes(record: dict) -> bytes:
    body = {k: v for k, v in record.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def verify_signature(record: dict, keys: list) -> str | None:
    """Returns None if valid, else a reason string. Never raises."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        return "SIGNATURE_VERIFIER_UNAVAILABLE"
    auth = record.get("authorizing_authority") or {}
    key = next((k for k in keys if isinstance(k, dict) and k.get("key_id") == auth.get("key_id")), None)
    if key is None:
        return "AUTHORITY_KEY_NOT_REGISTERED"
    if key.get("role") != "OWNER" or key.get("role") != auth.get("role") or key.get("identity") != auth.get("identity"):
        return "AUTHORITY_NOT_OWNER_OR_IDENTITY_MISMATCH"
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"]))
        pub.verify(bytes.fromhex(str(record.get("signature") or "")), canonical_signing_bytes(record))
    except InvalidSignature:
        return "INVALID_SIGNATURE"
    except Exception as e:
        return f"SIGNATURE_CHECK_ERROR:{type(e).__name__}"
    return None


def _safe_parse(s: str) -> datetime | None:
    """Like _parse(), but never raises: an impossible calendar date (e.g. month 13, day 32) matches the _TS regex's digit
    pattern but is not a real date, and strptime raises ValueError for it. Returns None on any parse failure instead of
    propagating an exception — the caller turns that into a deterministic denial."""
    try:
        return _parse(s)
    except (ValueError, TypeError):
        return None


def verify(record, req: Request, keys: list, now: datetime | None = None) -> Verdict:
    """Fail closed: authorized only if `reasons` is empty. Registering a key or having a signed inventory attestation is never
    sufficient here — `keys` only supplies the public key to check a signature THIS record must independently carry.

    Never raises: every branch that could throw on malformed input (bad timestamps, non-hex signatures, wrong types) is
    guarded and turned into a `Verdict(False, [...])` instead. A top-level guard below is defense in depth for anything
    not individually anticipated — an authorization gate that can crash into an unhandled exception is not fail-closed,
    it is merely fail-loud; the caller must always get back a definite yes/no."""
    try:
        return _verify_inner(record, req, keys, now)
    except Exception as e:
        return Verdict(False, [f"UNEXPECTED_VERIFY_ERROR:{type(e).__name__}"])


def _verify_inner(record, req: Request, keys: list, now: datetime | None = None) -> Verdict:
    now = now or datetime.now(timezone.utc)
    r: list = []
    if not isinstance(record, dict):
        return Verdict(False, ["RECORD_NOT_AN_OBJECT"])
    if set(record) != RECORD_KEYS:
        return Verdict(False, ["RECORD_SCHEMA_MISMATCH"])
    if record["schema_version"] != SCHEMA_VERSION:
        r.append("SCHEMA_VERSION_MISMATCH")
    if record["status"] != "AUTHORIZED":
        r.append("NOT_AUTHORIZED" if record["status"] == "NOT_AUTHORIZED" else "STATUS_INVALID")
        return Verdict(False, r)
    if not (isinstance(record["authorization_id"], str) and _ID.match(record["authorization_id"])):
        r.append("BAD_AUTHORIZATION_ID")
    if record["purpose"] != PURPOSE:
        r.append("WRONG_PURPOSE")
    scope = record.get("authorized_scope")
    if not isinstance(scope, list) or not scope or len(scope) != len(set(scope)) or not set(scope) <= set(ARTIFACT_CLASSES):
        r.append("BAD_AUTHORIZED_SCOPE")                       # covers empty, duplicate, and out-of-vocabulary entries
    requested = req.requested_scope
    if not isinstance(requested, (list, tuple)) or not requested:
        r.append("EMPTY_REQUESTED_SCOPE")
    elif len(requested) != len(set(requested)):
        r.append("DUPLICATE_REQUESTED_SCOPE")
    elif not set(requested) <= set(ARTIFACT_CLASSES):
        r.append("MALFORMED_REQUESTED_SCOPE_ITEM")
    elif isinstance(scope, list) and scope and not set(requested) <= set(scope):
        r.append("REQUESTED_SCOPE_EXCEEDS_AUTHORIZATION")
    if not (isinstance(record["reviewed_commit_sha"], str) and _SHA40.match(record["reviewed_commit_sha"])):
        r.append("BAD_REVIEWED_COMMIT_SHA")
    elif not (isinstance(req.commit_sha, str) and _SHA40.match(req.commit_sha)):
        r.append("BAD_REQUEST_COMMIT_SHA")
    elif not req.commit_is_descendant:
        r.append("REVIEWED_COMMIT_NOT_ANCESTOR_OF_EXECUTION")   # replay/rollback protection without requiring literal equality
    if req.working_tree_clean is not True:
        r.append("DIRTY_WORKING_TREE")                          # never authorize uncommitted/unreviewed code
    if not (isinstance(record["authorized_code_tree_sha256"], str) and _SHA64.match(record["authorized_code_tree_sha256"])):
        r.append("BAD_AUTHORIZED_CODE_TREE_HASH")
    elif not (isinstance(req.current_code_tree_sha256, str) and _SHA64.match(req.current_code_tree_sha256)):
        r.append("BAD_REQUEST_CODE_TREE_HASH")
    elif record["authorized_code_tree_sha256"] != req.current_code_tree_sha256:
        r.append("CODE_TREE_HASH_MISMATCH")                     # the real anti-drift binding: catches any code change since review
    digests = record.get("authorized_artifact_digests")
    if not isinstance(digests, dict) or set(digests) != {"corpus_inventory_digest", "preregistration_record_sha256"}:
        r.append("BAD_AUTHORIZED_ARTIFACT_DIGESTS")
    else:
        if digests["corpus_inventory_digest"] != req.current_inventory_digest:
            r.append("CORPUS_INVENTORY_DIGEST_MISMATCH")       # evidence changed since the owner reviewed/signed
        if digests["preregistration_record_sha256"] != req.current_prereg_record_sha256:
            r.append("PREREGISTRATION_DIGEST_MISMATCH")
    if not _ts_ok(record.get("issued_at")) or not _ts_ok(record.get("expires_at")):
        r.append("BAD_TIMESTAMPS")
    else:
        issued, expires = _safe_parse(record["issued_at"]), _safe_parse(record["expires_at"])
        if issued is None or expires is None:
            r.append("IMPOSSIBLE_TIMESTAMP")                   # regex-shaped but not a real calendar date/time
            return Verdict(False, r)
        if expires <= issued:
            r.append("EXPIRES_BEFORE_ISSUED")
        if expires - issued > MAX_VALIDITY:
            r.append("VALIDITY_WINDOW_TOO_LONG")
        if now < issued:
            r.append("NOT_YET_VALID")
        if now > expires:
            r.append("EXPIRED")
        if now - issued > MAX_VALIDITY:
            r.append("STALE_BEYOND_MAX_VALIDITY")              # even a long-lived-but-forgotten-about record ages out
    sig_problem = verify_signature(record, keys)
    if sig_problem:
        r.append(sig_problem)
    # An absent/empty event_name is exactly as unauthorized as any other non-dispatch event — never special-cased into a pass.
    if req.event_name != "workflow_dispatch":
        r.append("EVENT_NOT_EXPLICIT_DISPATCH")
    return Verdict(len(r) == 0, r)


def load_keys(root: Path) -> list:
    """Active OWNER authority keys, from the SAME registry authorization.py reads. Deliberately does NOT read
    CORPUS_GENERATION_AUTHORIZATION.json itself for keys — a signature is checked against a key that was registered
    through the ordinary authority-registry process, on its own separate track."""
    from orca.eval.genesis_v2 import authority_registry as AR
    doc, problems = AR.load(Path(root) / AR.REGISTRY_PATH)
    if problems or doc is None:
        return []
    return [k for k in AR.active_authority_keys(doc) if k.get("role") == "OWNER"]
