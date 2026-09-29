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
  - binds authorized_commit_sha to the EXACT commit the request is running at (no replay against a different commit),
  - binds authorized_artifact_digests to the exact evidence state (inventory digest, preregistration record hash) the
    owner reviewed when signing — if that evidence has since changed, the authorization no longer matches and fails,
  - has a short validity window (issued_at/expires_at, MAX_VALIDITY below) — an expired authorization fails,
  - has a real Ed25519 signature verified against a registered, active, non-revoked OWNER authority key.

Any missing field, wrong purpose, out-of-scope artifact, wrong commit, mismatched digest, expired window, unregistered
key, revoked key, or invalid signature fails closed. There is no code path in `verify()` that returns authorized=True
without an explicit, valid, signed AUTHORIZED record matching the exact request.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = "genesis-v2-corpus-generation-authorization/1"
RECORD_PATH = "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION.json"
PURPOSE = "PRIVATE_V2_CORPUS_GENERATION"          # the only purpose value this gate ever accepts
ARTIFACT_CLASSES = ("PILOT_TRAIN", "DEV", "SCREEN", "QUALIFICATION_HOLDOUT")
MAX_VALIDITY = timedelta(days=7)                  # an authorization older than this can never verify, regardless of expires_at

RECORD_KEYS = frozenset({"schema_version", "authorization_id", "status", "purpose", "authorized_scope", "authorized_commit_sha",
                         "authorized_artifact_digests", "issued_at", "expires_at", "authorizing_authority", "signature"})
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^cgauth-[0-9a-f]{16,64}$")


@dataclass(frozen=True)
class Request:
    """What is actually about to happen. Built from the real execution context, never trusted from the record."""
    commit_sha: str
    requested_scope: tuple                        # subset of ARTIFACT_CLASSES actually being generated right now
    current_inventory_digest: str
    current_prereg_record_sha256: str
    event_name: str = ""


@dataclass
class Verdict:
    authorized: bool
    reasons: list = field(default_factory=list)


def default_record() -> dict:
    return {"schema_version": SCHEMA_VERSION, "authorization_id": None, "status": "NOT_AUTHORIZED", "purpose": None,
            "authorized_scope": [], "authorized_commit_sha": None, "authorized_artifact_digests": {}, "issued_at": None,
            "expires_at": None, "authorizing_authority": {"identity": None, "role": None, "key_id": None}, "signature": None}


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
    if not (isinstance(record["authorized_commit_sha"], str) and _SHA40.match(record["authorized_commit_sha"])):
        r.append("BAD_AUTHORIZED_COMMIT_SHA")
    elif not (isinstance(req.commit_sha, str) and _SHA40.match(req.commit_sha)):
        r.append("BAD_REQUEST_COMMIT_SHA")
    elif record["authorized_commit_sha"] != req.commit_sha:
        r.append("COMMIT_SHA_MISMATCH")                       # the classic replay case: reusing an old authorization at a new commit
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
