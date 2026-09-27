"""Model-execution authorization gate (fail closed).

No model may be invoked (evaluation, seeding, inference) unless an authorization record proves — for THIS exact request — that a trusted authority
authorized it. The committed record is NOT_AUTHORIZED. A record is accepted only if every field is exact and its Ed25519 signature verifies against a
public key registered in TRUSTED_AUTHORITY_KEYS.json; with no registered key nothing can ever be authorized (an agent cannot forge approval by editing
the record). Branch names, commit messages, labels and environment-variable existence are never consulted.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = "orneur-model-eval-authorization/1"
RECORD_PATH = "docs/orneur/authorization/MODEL_EVAL_AUTHORIZATION.json"
KEYS_PATH = "docs/orneur/authorization/TRUSTED_AUTHORITY_KEYS.json"  # deprecated; kept only as a legacy artifact, no longer read (see AUTHORITY_REGISTRY.json)
STAGES = ("STAGE_0", "STAGE_1", "STAGE_2", "STAGE_3")
RUNNER_CLASSES = ("GITHUB_HOSTED_CPU", "SELF_HOSTED_CPU", "SELF_HOSTED_GPU")
PURPOSES = ("QUALIFICATION", "SCREENING", "TRAINABILITY_PILOT", "DATA_SEEDING", "REGRESSION")
AUTHORITY_ROLES = ("OWNER", "DELEGATED_OWNER")
MAX_VALIDITY = timedelta(days=30)

RECORD_KEYS = frozenset({"schema_version", "authorization_id", "status", "commit_sha", "eval_version", "candidate", "permitted_stage",
                         "permitted_runner_class", "permitted_purpose", "max_runs", "max_spend_usd", "issued_at", "expires_at",
                         "authorizing_authority", "gpu_allowed", "network_provider_inference_allowed", "signature"})
_SHA = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^auth-[0-9a-f]{16,64}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True)
class Request:
    """What the workflow is about to do. Built from the workflow context, never from the authorization record."""
    commit_sha: str
    eval_version: str
    candidate_model_id: str
    candidate_revision: str
    stage: str
    runner_class: str
    purpose: str
    requested_runs: int = 1
    requested_spend_usd: float = 0.0
    gpu: bool = False
    provider_inference: bool = False
    event_name: str = ""


@dataclass
class Verdict:
    authorized: bool
    reasons: list = field(default_factory=list)


def default_record() -> dict:
    return {"schema_version": SCHEMA_VERSION, "authorization_id": None, "status": "NOT_AUTHORIZED", "commit_sha": None, "eval_version": None,
            "candidate": {"model_id": None, "revision": None}, "permitted_stage": None, "permitted_runner_class": None, "permitted_purpose": None,
            "max_runs": 0, "max_spend_usd": 0, "issued_at": None, "expires_at": None,
            "authorizing_authority": {"identity": None, "role": None, "key_id": None},
            "gpu_allowed": False, "network_provider_inference_allowed": False, "signature": None}


def canonical_signing_bytes(record: dict) -> bytes:
    body = {k: v for k, v in record.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _ts(s):
    if not isinstance(s, str) or not _TS.match(s):
        raise ValueError("bad timestamp")
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _isint(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def verify_signature(record: dict, keys: list) -> str | None:
    """Returns None if valid, else a reason."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        return "SIGNATURE_VERIFIER_UNAVAILABLE"
    auth = record.get("authorizing_authority") or {}
    key = next((k for k in keys if isinstance(k, dict) and k.get("key_id") == auth.get("key_id")), None)
    if key is None:
        return "AUTHORITY_KEY_NOT_REGISTERED"
    if key.get("role") != auth.get("role") or key.get("identity") != auth.get("identity"):
        return "AUTHORITY_IDENTITY_MISMATCH"
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"]))
        pub.verify(bytes.fromhex(str(record.get("signature") or "")), canonical_signing_bytes(record))
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return "SIGNATURE_INVALID"
    return None


def verify(record, req: Request, keys: list, now: datetime | None = None) -> Verdict:
    """Fail closed: authorized only if `reasons` is empty."""
    now = now or datetime.now(timezone.utc)
    r: list = []
    if req.event_name != "workflow_dispatch":
        r.append("EVENT_NOT_EXPLICIT_DISPATCH")           # push / pull_request / schedule can never run a model
    if not isinstance(record, dict):
        return Verdict(False, r + ["RECORD_NOT_AN_OBJECT"])
    if set(record) != RECORD_KEYS:
        return Verdict(False, r + ["RECORD_SCHEMA_MISMATCH"])
    if record["schema_version"] != SCHEMA_VERSION:
        r.append("SCHEMA_VERSION_MISMATCH")
    if record["status"] != "AUTHORIZED":
        r.append("NOT_AUTHORIZED" if record["status"] == "NOT_AUTHORIZED" else "STATUS_INVALID")
        return Verdict(False, r)
    if not (isinstance(record["authorization_id"], str) and _ID.match(record["authorization_id"])):
        r.append("AUTHORIZATION_ID_INVALID")
    if not (isinstance(record["commit_sha"], str) and _SHA.match(record["commit_sha"])) or record["commit_sha"] != req.commit_sha:
        r.append("WRONG_COMMIT_SHA")
    if record["eval_version"] != req.eval_version or not isinstance(record["eval_version"], str):
        r.append("WRONG_EVAL_VERSION")
    cand = record["candidate"]
    if not (isinstance(cand, dict) and set(cand) == {"model_id", "revision"} and cand["model_id"] == req.candidate_model_id
            and cand["revision"] == req.candidate_revision and req.candidate_model_id and req.candidate_revision):
        r.append("WRONG_CANDIDATE")
    if record["permitted_stage"] not in STAGES or record["permitted_stage"] != req.stage:
        r.append("WRONG_STAGE")
    if record["permitted_runner_class"] not in RUNNER_CLASSES or record["permitted_runner_class"] != req.runner_class:
        r.append("WRONG_RUNNER_CLASS")
    if record["permitted_purpose"] not in PURPOSES or record["permitted_purpose"] != req.purpose:
        r.append("WRONG_PURPOSE")
    if not _isint(record["max_runs"]) or record["max_runs"] < 1 or not _isint(req.requested_runs) or req.requested_runs < 1 or req.requested_runs > record["max_runs"]:
        r.append("RUN_COUNT_NOT_AUTHORIZED")
    if not _isnum(record["max_spend_usd"]) or record["max_spend_usd"] < 0 or req.requested_spend_usd > record["max_spend_usd"]:
        r.append("SPEND_NOT_AUTHORIZED")
    try:
        issued, expires = _ts(record["issued_at"]), _ts(record["expires_at"])
        if not (issued <= now < expires):
            r.append("AUTHORIZATION_EXPIRED_OR_NOT_YET_VALID")
        if expires - issued > MAX_VALIDITY:
            r.append("VALIDITY_WINDOW_TOO_LONG")
    except ValueError:
        r.append("TIMESTAMP_INVALID")
    auth = record["authorizing_authority"]
    if not (isinstance(auth, dict) and set(auth) == {"identity", "role", "key_id"} and auth["role"] in AUTHORITY_ROLES
            and isinstance(auth["identity"], str) and auth["identity"] and isinstance(auth["key_id"], str) and auth["key_id"]):
        r.append("AUTHORITY_INVALID")
    if not isinstance(record["gpu_allowed"], bool) or not isinstance(record["network_provider_inference_allowed"], bool):
        r.append("PERMISSION_FLAGS_INVALID")
    else:
        if req.gpu and not (record["gpu_allowed"] and record["permitted_runner_class"] == "SELF_HOSTED_GPU"):
            r.append("GPU_NOT_AUTHORIZED")
        if record["permitted_runner_class"] == "SELF_HOSTED_GPU" and not record["gpu_allowed"]:
            r.append("GPU_RUNNER_WITHOUT_GPU_PERMISSION")
        if req.provider_inference and not record["network_provider_inference_allowed"]:
            r.append("PROVIDER_INFERENCE_NOT_AUTHORIZED")
    if not keys:
        r.append("NO_TRUSTED_AUTHORITY_KEY_REGISTERED")
    elif not r:
        sig = verify_signature(record, keys)
        if sig:
            r.append(sig)
    return Verdict(not r, r)


def load_keys(root: Path) -> list:
    """Active authority public keys, derived from the canonical AUTHORITY_REGISTRY.json (see authority_registry.py). Any read/schema error, or an
    empty registry, means no key is trusted — nothing can be authorized."""
    from orca.eval.genesis_v2 import authority_registry as AR
    doc, problems = AR.load(Path(root) / AR.REGISTRY_PATH)
    if problems or doc is None:
        return []
    return AR.active_authority_keys(doc)          # unreadable registry => no trusted keys => nothing authorized


def load_record(root: Path):
    try:
        return json.loads((Path(root) / RECORD_PATH).read_text())
    except Exception:
        return "UNREADABLE"
