"""Who may serve an unqualified ORNEUR model to the PUBLIC, and under what disclosure.

Before this module the only thing standing between an EXPERIMENTAL self-hosted model and public traffic was an environment variable
(``ORNEUR_ALLOW_EXPERIMENTAL_SERVING``) -- and the lifecycle label itself was derived from the *tier name* (anything mapped to ``nano`` was
treated as legacy production). A flag is not evidence, and a name is not an artifact.

Rules (all fail closed):

* Not a public edge -> unchanged: developers and private deployments run what they have; the lifecycle is still reported truthfully.
* Public edge -> an EXPERIMENTAL self-hosted model is served only under a **public-serving grant**: an Ed25519-signed, domain-separated record
  naming the exact model family, tier, Ollama tag AND the artifact digest Ollama reports for that tag, a validity window (at most
  ``MAX_GRANT_DAYS``), the users eligible, and the exact disclosure label. It must verify against a registry whose canonical digest is pinned in
  this file (so adding an authority needs a reviewed source change), must not be revoked, must still match the installed artifact, and the
  caller must be eligible. Anything else -> not served. The environment flag has **no authorizing effect**.
* The one pre-existing exemption (the legacy Genesis checkpoint, a documented founder decision in PR #25) is pinned to artifact *names* in
  ``LEGACY_GENESIS_ARTIFACTS``. Pointing the nano tier at some other model no longer inherits it.

A grant is NOT a promotion: it never changes a model's lifecycle to PRODUCTION, qualifies nothing, and carries the label it was signed with.
Nothing here signs anything; the registry ships empty, so nothing is authorized by this change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SIGNING_DOMAIN = b"orneur-public-serving-grant/1\n"
GRANT_SCHEMA = "orneur-public-serving-grant/1"
REGISTRY_SCHEMA = "orneur-public-serving-registry/1"
PURPOSE = "PUBLIC_EXPERIMENT"
MAX_GRANT_DAYS = 30
MIN_LABEL_CHARS = 40

# Registry canonical sha256 (empty registry). Changing the authorities requires editing this constant in a reviewed change.
PINNED_REGISTRY_SHA256 = "6a9c03369de28b83b28462757057a82d027479824b015568c0acd55a8e0eed27"

# Artifact names that may claim the documented LEGACY_PRODUCTION_SERVING exemption for the Genesis family. A different model configured for the
# nano tier is EXPERIMENTAL like any other.
LEGACY_GENESIS_FAMILY = "orneur-genesis"
LEGACY_GENESIS_ARTIFACTS = frozenset({"orca-nano-v7"})   # the documented legacy 7B checkpoint identity (docs/orneur/phase-7/DEPLOYMENT_HEALTH.md)

LIFECYCLE_EXPERIMENTAL = "EXPERIMENTAL"
LIFECYCLE_LEGACY = "LEGACY_PRODUCTION_SERVING"

_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

GRANT_FIELDS = {
    "schema", "grant_id", "purpose", "model_family", "tier", "ollama_tag", "ollama_digest", "not_before", "expires_at",
    "eligibility", "label", "authorizing_authority", "signature",
}


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def signing_bytes(grant: dict) -> bytes:
    return SIGNING_DOMAIN + _canonical({k: v for k, v in grant.items() if k != "signature"})


def registry_digest(doc) -> str:
    return hashlib.sha256(_canonical(doc)).hexdigest()


def empty_registry() -> dict:
    return {"schema_version": REGISTRY_SCHEMA, "records": []}


def _parse_ts(s):
    if not isinstance(s, str) or not _TS.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass(frozen=True)
class ServingDecision:
    allowed: bool
    lifecycle: str
    label: str
    reason: str                       # safe to log; never shown verbatim to end users
    grant_id: str | None = None
    problems: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class Viewer:
    """Who the request is for. Anonymous callers are never eligible for a public experiment."""
    user_id: str | None = None
    signup_seq: int | None = None


def _authority_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "orneur" / "authorization"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except Exception:
        return None  # unreadable / malformed -> callers treat None as "deny everything"


def load_trust_files() -> tuple:
    """(registry, grants, revoked_ids) -- any unreadable file yields None for it, which denies."""
    d = _authority_dir()
    registry = _load(d / "PUBLIC_SERVING_AUTHORITY_REGISTRY.json", empty_registry())
    grants = _load(d / "PUBLIC_SERVING_GRANTS.json", {"schema_version": GRANT_SCHEMA, "grants": []})
    revoked = _load(d / "PUBLIC_SERVING_REVOCATIONS.json", {"schema_version": GRANT_SCHEMA, "revoked_ids": []})
    return registry, grants, revoked


def validate_registry(doc) -> list:
    if not isinstance(doc, dict) or set(doc) != {"schema_version", "records"} or doc.get("schema_version") != REGISTRY_SCHEMA \
            or not isinstance(doc.get("records"), list):
        return ["registry schema mismatch"]
    problems, seen = [], set()
    for r in doc["records"]:
        keys = {"id", "public_key_hex", "activation_timestamp", "expiry", "revoked"}
        if not isinstance(r, dict) or set(r) != keys:
            problems.append("registry record schema mismatch")
            continue
        if not isinstance(r["id"], str) or not r["id"] or r["id"] in seen:
            problems.append("registry record id invalid or duplicate")
        seen.add(r["id"])
        if not isinstance(r["public_key_hex"], str) or not _HEX64.match(r["public_key_hex"]):
            problems.append("registry public key invalid")
        if _parse_ts(r["activation_timestamp"]) is None or (r["expiry"] is not None and _parse_ts(r["expiry"]) is None):
            problems.append("registry timestamps invalid")
        if not isinstance(r["revoked"], bool):
            problems.append("registry revoked flag invalid")
    return problems


def _verify_signature(grant: dict, registry: dict, now: datetime) -> str | None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        return "signature verifier unavailable"
    auth = grant.get("authorizing_authority")
    key = next((k for k in registry.get("records", []) if isinstance(auth, str) and k.get("id") == auth), None)
    if key is None:
        return "authority not registered"
    start, end = _parse_ts(key["activation_timestamp"]), _parse_ts(key["expiry"]) if key["expiry"] else None
    if key["revoked"] or start is None or now < start or (end is not None and now >= end):
        return "authority not active"
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"])).verify(bytes.fromhex(str(grant.get("signature") or "")), signing_bytes(grant))
    except (InvalidSignature, ValueError, TypeError):
        return "signature invalid"
    return None


def _grant_problems(grant: dict) -> list:
    if not isinstance(grant, dict) or set(grant) != GRANT_FIELDS:
        return ["grant schema mismatch"]
    out = []
    if grant["schema"] != GRANT_SCHEMA or grant["purpose"] != PURPOSE:
        out.append("grant schema/purpose mismatch")
    for k in ("grant_id", "model_family", "tier", "ollama_tag", "label", "authorizing_authority"):
        if not isinstance(grant[k], str) or not grant[k]:
            out.append(f"{k} invalid")
    if not isinstance(grant["ollama_digest"], str) or not _DIGEST.match(grant["ollama_digest"]):
        out.append("ollama_digest must be sha256:<64 hex>")
    nb, ex = _parse_ts(grant["not_before"]), _parse_ts(grant["expires_at"])
    if nb is None or ex is None or ex <= nb:
        out.append("validity window invalid")
    elif ex - nb > timedelta(days=MAX_GRANT_DAYS):
        out.append(f"validity window exceeds {MAX_GRANT_DAYS} days")
    elig = grant["eligibility"]
    if not isinstance(elig, dict) or set(elig) != {"user_ids", "signup_seq_max"}:
        out.append("eligibility schema mismatch")
    else:
        ids, cap = elig["user_ids"], elig["signup_seq_max"]
        if not isinstance(ids, list) or not all(isinstance(x, str) and x for x in ids):
            out.append("eligibility.user_ids invalid")
        if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 1):
            out.append("eligibility.signup_seq_max invalid")
        if not ids and cap is None:
            out.append("eligibility must name users or a signup cohort (no open-to-everyone grants)")
    label = grant["label"] if isinstance(grant["label"], str) else ""
    lowered = label.lower()
    if len(label) < MIN_LABEL_CHARS or "experimental" not in lowered or "not qualified" not in lowered:
        out.append("label must be truthful: >= 40 chars and state it is experimental and not qualified")
    return out


def _eligible(grant: dict, viewer: Viewer) -> bool:
    if viewer.user_id is None:
        return False
    elig = grant["eligibility"]
    if viewer.user_id in elig["user_ids"]:
        return True
    cap = elig["signup_seq_max"]
    return cap is not None and viewer.signup_seq is not None and viewer.signup_seq <= cap


def evaluate_grants(*, model_family: str, tier: str, ollama_tag: str, installed_digest: str | None, viewer: Viewer, now: datetime,
                    registry, grants_doc, revoked_doc) -> ServingDecision:
    """Pure: no I/O, no clock, no environment."""
    denied = lambda why, *probs: ServingDecision(False, LIFECYCLE_EXPERIMENTAL, "", why, None, tuple(probs))  # noqa: E731
    if registry is None or grants_doc is None or revoked_doc is None:
        return denied("trust files unreadable")
    if validate_registry(registry) or registry_digest(registry) != PINNED_REGISTRY_SHA256:
        return denied("registry invalid or does not match the source pin")
    if not isinstance(grants_doc, dict) or not isinstance(grants_doc.get("grants"), list):
        return denied("grants file malformed")
    revoked = revoked_doc.get("revoked_ids") if isinstance(revoked_doc, dict) else None
    if not isinstance(revoked, list):
        return denied("revocation list malformed")
    if installed_digest is None:
        return denied("installed artifact digest unavailable (artifact missing or runtime unreachable)")
    problems: list = []
    for g in grants_doc["grants"]:
        gid = g.get("grant_id") if isinstance(g, dict) else None
        bad = _grant_problems(g)
        if bad:
            problems.append(f"{gid}: {'; '.join(bad)}")
            continue
        if g["grant_id"] in revoked:
            problems.append(f"{gid}: revoked")
            continue
        if (g["model_family"], g["tier"], g["ollama_tag"]) != (model_family, tier, ollama_tag):
            continue  # a grant for something else is not a failure of this one
        if g["ollama_digest"] != installed_digest:
            problems.append(f"{gid}: installed artifact does not match the digest the grant was signed for")
            continue
        if not (_parse_ts(g["not_before"]) <= now < _parse_ts(g["expires_at"])):
            problems.append(f"{gid}: outside validity window")
            continue
        sig_problem = _verify_signature(g, registry, now)
        if sig_problem:
            problems.append(f"{gid}: {sig_problem}")
            continue
        if not _eligible(g, viewer):
            problems.append(f"{gid}: viewer not eligible")
            continue
        return ServingDecision(True, LIFECYCLE_EXPERIMENTAL, g["label"], "public experiment grant verified", g["grant_id"])
    return denied("no valid public-serving grant for this model, artifact and viewer", *problems)


def decide_self_hosted(*, model_family: str, tier: str, ollama_tag: str, public_edge: bool, viewer: Viewer | None = None,
                       installed_digest: str | None = None, now: datetime | None = None, trust_files: tuple | None = None) -> ServingDecision:
    viewer = viewer or Viewer()
    legacy = tier == "nano" and model_family == LEGACY_GENESIS_FAMILY and ollama_tag in LEGACY_GENESIS_ARTIFACTS
    if legacy:
        return ServingDecision(True, LIFECYCLE_LEGACY, "Legacy Genesis checkpoint -- not the canonical, qualified Genesis model.", "pinned legacy exemption")
    if not public_edge:
        return ServingDecision(True, LIFECYCLE_EXPERIMENTAL, "Experimental model -- not qualified.", "private deployment")
    registry, grants, revoked = trust_files if trust_files is not None else load_trust_files()
    return evaluate_grants(
        model_family=model_family, tier=tier, ollama_tag=ollama_tag, installed_digest=installed_digest, viewer=viewer,
        now=now or datetime.now(timezone.utc), registry=registry, grants_doc=grants, revoked_doc=revoked,
    )
