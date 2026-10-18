"""
GENESIS Foundation Sprint 2, Workstream F: native-pretraining training
authorization contract.

## Mission F1 investigation findings (recorded here, not just asserted)

This repository already has TWO separate, real, cryptographically-sound
trust systems -- neither of which represents GENESIS native pretraining
correctly today, and neither of which this module duplicates:

1. **`orca.train.authorization`**: a per-run operational gate for the
   LoRA/QLoRA fine-tune path. Ed25519-signed records, a pinned (empty)
   authority-key registry, an append-only hash-chained audit log, a
   durable on-disk run-slot ledger. Its `Request`/`TrainingGrant` shape is
   built around `TrainingConfig` (LoRA rank, file-based datasets) -- it has
   no field for a dataset MANIFEST identity, no model-architecture-version
   concept, and (per PR #61's own Workstream C findings, C-01) its records
   carry nothing that distinguishes "this grant is for a LoRA fine-tune"
   from "this grant is for GENESIS native pretraining" except a
   `cfg_fingerprint` hash a caller could coincidentally satisfy. Workstream
   C's `GenesisTrainingRun.authorize()` works around this by requiring a
   real `TrainingGrant` and checking its fingerprint against a GENESIS-shaped
   scope -- a real mitigation, but still fundamentally a LoRA-shaped
   signing domain being asked to represent a different kind of request.
2. **`scripts/acceptance/acceptance_engine.py`**: the project-wide
   requirement-acceptance ledger (R65/G1/AUTH-1/FINAL-1/FINAL-2/EXEC-1 and
   91 further rows). This governs whether GENESIS native pretraining has
   been independently reviewed and founder-accepted AT ALL as a readiness
   milestone -- a BROADER, slower-moving gate than "is this one specific
   run authorized." `docs/orneur/acceptance/acceptance_ledger.json` is `[]`
   (empty) and `PINNED_BOOTSTRAP_ROOT_KEYS` is an empty `frozenset()` --
   nothing can be accepted through this engine today, full stop.

**This module's actual job, correctly scoped**: provide a REAL signing
domain specifically for GENESIS native-pretraining requests (a different
`SIGNING_DOMAIN` from `orca.train.authorization`'s, so a LoRA grant can
NEVER verify as one of these records and vice versa -- closing the
cross-workload-confusion gap structurally, not merely via a fingerprint
check), binding every field Mission F2 requires, AND requiring the
project-wide acceptance ledger to actually show GENESIS pretraining's
gating rows accepted before issuing anything -- reusing
`scripts.acceptance.acceptance_engine.evaluate()` directly (not
re-implementing ledger verification) for that second check.

**The committed registry below is empty, its own digest is pinned, and the
acceptance ledger this module checks is empty too. Nothing in this
repository can cause `authorize_native_pretraining()` to return anything
other than a denial today.** Provisioning either requires a separate,
explicit, founder-approved action this module cannot take on its own.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sys
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

SCHEMA_VERSION = "orneur-genesis-native-pretraining-authorization/1"
REGISTRY_SCHEMA_VERSION = "orneur-genesis-native-pretraining-authority-registry/1"
REVOCATIONS_SCHEMA_VERSION = "orneur-genesis-native-pretraining-revocations/1"
RECORD_PATH = "docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json"
REGISTRY_PATH = "docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json"
REVOCATIONS_PATH = "docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json"
# A DIFFERENT signing domain from orca.train.authorization.SIGNING_DOMAIN --
# a record signed for one can never verify under the other, by construction
# (Ed25519 signatures are over this exact domain-prefixed byte string).
SIGNING_DOMAIN = b"orneur-genesis-native-pretraining-authorization/1\n"

AUTHORITY_ROLES = ("OWNER", "DELEGATED_OWNER")
ENVIRONMENT_CLASSES = ("SELF_HOSTED_GPU", "SSH_RENTED_GPU")
MAX_VALIDITY = timedelta(days=14)
REQUIRED_ACCEPTANCE_ROWS = ("R65", "G1", "AUTH-1", "FINAL-1")

_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^gnpauth-[0-9a-f]{16,64}$")
_NONCE = re.compile(r"^[0-9a-f]{32,64}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_SEAL = object()
_PROCESS_KEY = secrets.token_bytes(32)
_GRANT_MAC_FIELDS = (
    "authorization_id", "key_id", "record_sha256", "run_id", "expires_at", "max_wall_clock_minutes",
    "model_config_digest", "tokenizer_digest", "dataset_manifest_id", "dataset_content_digest",
    "authorized_shard_digests", "environment_class",
    # Mission 2 M2-01 fix: previously the issued grant object discarded
    # these fields entirely after `verify()` checked them against the
    # signed record -- so a CONSUMER of the grant (GenesisTrainingRun)
    # had no way to independently bind its own declared architecture
    # version, reviewed commit, transformation code, optimizer config,
    # or GPU/spend intent against what was actually authorized. Now
    # carried into the grant (and HMAC-protected, like every other
    # field) so consumers can check them directly against the grant
    # object itself, not just trust that `verify()` checked them once
    # at issuance against a record the consumer never sees again.
    "architecture_version", "reviewed_commit_sha", "transformation_code_digest", "optimizer_config_digest",
    "gpu_allowed", "max_spend_usd",
)


class NativePretrainingNotAuthorized(PermissionError):
    """Raised for every denial. `.reasons` is a list of stable reason
    codes; the message never contains record contents or secrets."""

    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("GENESIS native pretraining is not authorized: " + ", ".join(self.reasons))


# ---- canonical forms (mirrors orca.train.authorization's own, a different domain, same discipline) ----

def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def canonical_signing_bytes(record: dict) -> bytes:
    return SIGNING_DOMAIN + _canonical({k: v for k, v in record.items() if k != "signature"})


def registry_digest(doc) -> str:
    return hashlib.sha256(_canonical(doc)).hexdigest()


def empty_registry() -> dict:
    return {"schema_version": REGISTRY_SCHEMA_VERSION, "records": []}


def empty_revocations() -> dict:
    return {"schema_version": REVOCATIONS_SCHEMA_VERSION, "revoked_authorization_ids": []}


# Committed (empty) registry's own digest, HARDCODED (not computed from
# empty_registry() at import time -- that would make this "pin" trivially
# self-satisfying regardless of what is actually written to
# REGISTRY_PATH on disk, defeating the entire point of a pin). Computed
# once via `registry_digest(empty_registry())` and copied here literally.
# Provisioning a founder key means changing BOTH the registry file and
# this constant, in a reviewed change -- a registry that does not hash to
# this exact value authorizes nothing.
PINNED_REGISTRY_SHA256 = "696a236bc257f878df9565ac2c4cfa6d3642adaead1dd6ce69032299f0a46deb"


def default_record() -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "authorization_id": None, "status": "NOT_AUTHORIZED",
        "run_id": None, "nonce": None,
        "model": {"family": None, "architecture_version": None, "model_config_digest": None},
        "tokenizer": {"tokenizer_digest": None},
        "dataset": {"dataset_manifest_id": None, "dataset_content_digest": None, "authorized_shard_digests": []},
        "code": {"reviewed_commit_sha": None, "transformation_code_digest": None},
        "training": {"optimizer_config_digest": None},
        "environment_class": None,
        "limits": {"max_wall_clock_minutes": 0, "max_spend_usd": 0, "gpu_allowed": False},
        "issued_at": None, "expires_at": None,
        "authorizing_authority": {"identity": None, "role": None, "key_id": None}, "signature": None,
    }


def _parse_ts(s):
    if not isinstance(s, str) or not _TS.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---- registry validation (mirrors orca.train.authorization's own shape/discipline) ----

def validate_registry(doc) -> list[str]:
    if not isinstance(doc, dict) or doc.get("schema_version") != REGISTRY_SCHEMA_VERSION or set(doc) != {"schema_version", "records"} \
            or not isinstance(doc.get("records"), list):
        return ["registry schema mismatch"]
    problems, seen = [], set()
    for r in doc["records"]:
        if not isinstance(r, dict) or set(r) != {
            "id", "role", "public_key_hex", "activation_timestamp", "expiry", "revoked", "gpu_permission", "spend_permission",
        }:
            problems.append("registry record schema mismatch")
            continue
        if not isinstance(r["id"], str) or not r["id"] or r["id"] in seen:
            problems.append("registry record id invalid or duplicate")
        seen.add(r["id"])
        if r["role"] not in AUTHORITY_ROLES:
            problems.append("registry role invalid")
        if not isinstance(r["public_key_hex"], str) or not _SHA64.match(r["public_key_hex"]):
            problems.append("registry public key must be 64 lowercase hex characters")
        if _parse_ts(r["activation_timestamp"]) is None or (r["expiry"] is not None and _parse_ts(r["expiry"]) is None):
            problems.append("registry timestamps invalid")
        if not isinstance(r["revoked"], bool) or not isinstance(r["gpu_permission"], bool) or not isinstance(r["spend_permission"], bool):
            problems.append("registry booleans invalid")
    return problems


def _key_active(r: dict, now: datetime) -> bool:
    if r.get("revoked") is not False:
        return False
    start, end = _parse_ts(r.get("activation_timestamp")), _parse_ts(r.get("expiry")) if r.get("expiry") else None
    return start is not None and start <= now and (end is None or now < end)


def verify_signature(record: dict, registry_doc: dict, now: datetime) -> tuple[str | None, dict | None]:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        return "SIGNATURE_VERIFIER_UNAVAILABLE", None
    auth = record.get("authorizing_authority") or {}
    key = next((k for k in registry_doc.get("records", []) if k.get("id") == auth.get("key_id")), None)
    if key is None:
        return "AUTHORITY_KEY_NOT_REGISTERED", None
    if not _key_active(key, now):
        return "AUTHORITY_KEY_NOT_ACTIVE_OR_REVOKED", key
    if key["role"] != auth.get("role") or key["id"] != auth.get("identity"):
        return "AUTHORITY_IDENTITY_MISMATCH", key
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"])).verify(
            bytes.fromhex(str(record.get("signature") or "")), canonical_signing_bytes(record))
    except (InvalidSignature, ValueError, TypeError):
        return "SIGNATURE_INVALID", key
    return None, key


# ---- the request (built from real, independently-derived facts) ----

@dataclass(frozen=True)
class NativePretrainingRequest:
    run_id: str
    nonce: str
    model_family: str
    architecture_version: str
    model_config_digest: str
    tokenizer_digest: str
    dataset_manifest_id: str
    dataset_content_digest: str
    authorized_shard_digests: tuple[str, ...]
    reviewed_commit_sha: str
    transformation_code_digest: str
    optimizer_config_digest: str
    environment_class: str
    gpu_requested: bool
    max_wall_clock_minutes: int
    requested_spend_usd: float


@dataclass
class Verdict:
    authorized: bool
    reasons: list = field(default_factory=list)


def _content_digest(obj) -> str:
    """A real content digest of a dataclass (or plain dict) -- used for
    `model_config_digest`/`optimizer_config_digest` so these are derived
    from the actual object's real field values, never a caller-supplied
    label."""
    payload = asdict(obj) if is_dataclass(obj) and not isinstance(obj, type) else obj
    return hashlib.sha256(_canonical(payload)).hexdigest()


class DatasetManifestLike(Protocol):
    """Structural contract a real `orca.genesis.data.manifest.GenesisDatasetManifest`
    already satisfies -- this module does not import that class directly
    (Mission F6: isolated governance contracts against the lowest valid
    dependency), so any object with this shape can be used."""
    manifest_id: str
    source_content_digest: str

    def verify_against_records(self, normalized_records: list[str]) -> tuple[bool, str]: ...


def verify(record, req: NativePretrainingRequest, registry_doc, revoked_ids, now: datetime | None = None) -> Verdict:
    """Authorized only if `reasons` is empty. Exhaustively checks every
    binding field Mission F2 requires."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(record, dict):
        return Verdict(False, ["RECORD_NOT_AN_OBJECT"])
    if record.get("schema_version") != SCHEMA_VERSION:
        return Verdict(False, ["SCHEMA_VERSION_MISMATCH"])
    if record.get("status") != "AUTHORIZED":
        return Verdict(False, ["NOT_AUTHORIZED" if record.get("status") == "NOT_AUTHORIZED" else "STATUS_INVALID"])

    r: list[str] = []
    model, tok, ds, code, training, limits = (
        record.get("model") or {}, record.get("tokenizer") or {}, record.get("dataset") or {},
        record.get("code") or {}, record.get("training") or {}, record.get("limits") or {},
    )

    if not (isinstance(record.get("authorization_id"), str) and _ID.match(record["authorization_id"])):
        r.append("AUTHORIZATION_ID_INVALID")
    elif record["authorization_id"] in set(revoked_ids or ()):
        r.append("AUTHORIZATION_REVOKED")

    # unique run ID + replay-resistant nonce
    if record.get("run_id") != req.run_id or not req.run_id:
        r.append("WRONG_RUN_ID")
    if not (isinstance(record.get("nonce"), str) and _NONCE.match(record.get("nonce") or "")) or record.get("nonce") != req.nonce:
        r.append("WRONG_OR_MALFORMED_NONCE")

    # model family + architecture version + config digest
    if model.get("family") != req.model_family or not req.model_family:
        r.append("WRONG_MODEL_FAMILY")
    if model.get("architecture_version") != req.architecture_version or not req.architecture_version:
        r.append("WRONG_ARCHITECTURE_VERSION")
    if not (isinstance(model.get("model_config_digest"), str) and _SHA64.match(model["model_config_digest"])) \
            or model["model_config_digest"] != req.model_config_digest:
        r.append("WRONG_MODEL_CONFIG_DIGEST")

    # tokenizer digest
    if not (isinstance(tok.get("tokenizer_digest"), str) and _SHA64.match(tok["tokenizer_digest"])) \
            or tok["tokenizer_digest"] != req.tokenizer_digest:
        r.append("WRONG_TOKENIZER_DIGEST")

    # dataset manifest identity + exact authorized shard digests
    if ds.get("dataset_manifest_id") != req.dataset_manifest_id or not req.dataset_manifest_id:
        r.append("WRONG_DATASET_MANIFEST_ID")
    if not (isinstance(ds.get("dataset_content_digest"), str) and _SHA64.match(ds["dataset_content_digest"])) \
            or ds["dataset_content_digest"] != req.dataset_content_digest:
        r.append("WRONG_DATASET_CONTENT_DIGEST")
    authorized_shards = ds.get("authorized_shard_digests")
    if not isinstance(authorized_shards, list) or tuple(sorted(authorized_shards)) != tuple(sorted(req.authorized_shard_digests)):
        r.append("WRONG_AUTHORIZED_SHARDS")
    elif not all(isinstance(s, str) and _SHA64.match(s) for s in authorized_shards):
        r.append("MALFORMED_SHARD_DIGEST")

    # transformation/code identity
    if not (isinstance(code.get("reviewed_commit_sha"), str) and _SHA40.match(code["reviewed_commit_sha"])) \
            or code["reviewed_commit_sha"] != req.reviewed_commit_sha:
        r.append("WRONG_REVIEWED_COMMIT")
    if not (isinstance(code.get("transformation_code_digest"), str) and _SHA64.match(code["transformation_code_digest"])) \
            or code["transformation_code_digest"] != req.transformation_code_digest:
        r.append("WRONG_TRANSFORMATION_CODE_DIGEST")

    # optimizer/hyperparameter configuration
    if not (isinstance(training.get("optimizer_config_digest"), str) and _SHA64.match(training["optimizer_config_digest"])) \
            or training["optimizer_config_digest"] != req.optimizer_config_digest:
        r.append("WRONG_OPTIMIZER_CONFIG_DIGEST")

    # hardware environment + GPU/runtime limits + spend (MUST be zero while NO-GO)
    if record.get("environment_class") not in ENVIRONMENT_CLASSES or record.get("environment_class") != req.environment_class:
        r.append("WRONG_ENVIRONMENT_CLASS")
    if not isinstance(limits.get("max_wall_clock_minutes"), int) or limits["max_wall_clock_minutes"] < 1:
        r.append("LIMITS_INVALID")
    elif req.max_wall_clock_minutes > limits["max_wall_clock_minutes"]:
        r.append("WALL_CLOCK_NOT_AUTHORIZED")
    if limits.get("max_spend_usd") != 0:
        r.append("SPEND_MUST_BE_ZERO_WHILE_NOGO")
    elif req.requested_spend_usd != 0:
        r.append("SPEND_REQUESTED_WHILE_NOGO")
    if not isinstance(limits.get("gpu_allowed"), bool) or (req.gpu_requested and limits["gpu_allowed"] is not True):
        r.append("GPU_NOT_AUTHORIZED")

    # validity window
    issued, expires = _parse_ts(record.get("issued_at")), _parse_ts(record.get("expires_at"))
    if issued is None or expires is None:
        r.append("BAD_TIMESTAMPS")
    else:
        if expires <= issued:
            r.append("EXPIRES_BEFORE_ISSUED")
        if expires - issued > MAX_VALIDITY:
            r.append("VALIDITY_WINDOW_TOO_LONG")
        if now < issued:
            r.append("NOT_YET_VALID")
        if now >= expires:
            r.append("EXPIRED")

    # founder authority identity + cryptographic verification + revocation status
    auth = record.get("authorizing_authority") or {}
    if not (isinstance(auth, dict) and set(auth) == {"identity", "role", "key_id"} and auth.get("role") in AUTHORITY_ROLES
            and isinstance(auth.get("identity"), str) and auth["identity"] and isinstance(auth.get("key_id"), str) and auth["key_id"]):
        r.append("AUTHORITY_INVALID")
    elif not registry_doc or not registry_doc.get("records"):
        r.append("NO_TRUSTED_AUTHORITY_REGISTERED")
    elif not r:
        reason, _key = verify_signature(record, registry_doc, now)
        if reason:
            r.append(reason)

    return Verdict(not r, r)


# ---- the sealed grant (mirrors orca.train.authorization.TrainingGrant's unforgeability pattern) ----

@dataclass(frozen=True)
class NativePretrainingGrant:
    """Proof that `authorize_native_pretraining()` verified a request. Can
    only be constructed with the module-private seal; every consumer
    re-checks it against the request and the exact data it is about to
    read."""
    authorization_id: str
    key_id: str
    record_sha256: str
    run_id: str
    expires_at: str
    max_wall_clock_minutes: int
    model_config_digest: str
    tokenizer_digest: str
    dataset_manifest_id: str
    dataset_content_digest: str
    authorized_shard_digests: tuple[str, ...]
    environment_class: str
    architecture_version: str
    reviewed_commit_sha: str
    transformation_code_digest: str
    optimizer_config_digest: str
    gpu_allowed: bool
    max_spend_usd: float
    _seal: object = field(default=None, repr=False, compare=False)
    _mac: str = field(default="", repr=False, compare=False)

    def _compute_mac(self) -> str:
        return hmac.new(_PROCESS_KEY, _canonical({f: getattr(self, f) for f in _GRANT_MAC_FIELDS}), hashlib.sha256).hexdigest()

    def __post_init__(self):
        if self._seal is not _SEAL:
            raise NativePretrainingNotAuthorized(["GRANT_NOT_ISSUED_BY_GATE"])
        expected = self._compute_mac()
        if self._mac and not hmac.compare_digest(self._mac, expected):
            raise NativePretrainingNotAuthorized(["GRANT_TAMPERED"])
        object.__setattr__(self, "_mac", expected)

    def verify_integrity(self) -> None:
        try:
            ok = self._seal is _SEAL and isinstance(self._mac, str) and hmac.compare_digest(self._mac, self._compute_mac())
        except (AttributeError, TypeError):
            ok = False
        if not ok:
            raise NativePretrainingNotAuthorized(["GRANT_FORGED_OR_TAMPERED"])

    def __reduce__(self):
        raise TypeError("a NativePretrainingGrant cannot be copied or serialized")


# ---- founder project-wide acceptance gate (reused, not reimplemented) ----

def check_founder_acceptance_ledger(repo_root: Path, *, required_rows: tuple[str, ...] = REQUIRED_ACCEPTANCE_ROWS) -> list[str]:
    """Reuses `scripts.acceptance.acceptance_engine.evaluate()` DIRECTLY --
    the real, already-built, cryptographic requirement-acceptance ledger
    -- rather than re-implementing ledger verification here. Returns the
    list of `required_rows` NOT currently accepted (empty list means all
    required rows are accepted). An empty ledger (the committed, real
    state today) accepts nothing, per that engine's own docstring, and
    needs no real trust material to determine that."""
    repo_root = Path(repo_root)
    engine_dir = str(repo_root / "scripts" / "acceptance")
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    import acceptance_engine as engine  # noqa: PLC0415 -- see module docstring for why this import pattern

    graph = json.loads((repo_root / "docs/orneur/acceptance/register_graph.json").read_text())
    ledger = json.loads((repo_root / "docs/orneur/acceptance/acceptance_ledger.json").read_text())
    rc_result = _git_rev_parse_head(repo_root)
    accepted = engine.evaluate(
        nodes=graph["nodes"], records=ledger, trust_snapshot=None, root_state=None,
        bootstrap_root_key_hex="", subject_sha=rc_result,
    )
    return [row for row in required_rows if row not in accepted]


def _git_rev_parse_head(repo_root: Path) -> str:
    import subprocess
    try:
        p = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


class NonceReplayedError(Exception):
    """Raised when a `(run_id, nonce)` pair has already been consumed by a
    prior call in THIS PROCESS. Mission F4 item 8 ("process restart and
    replay"): like `orca.genesis.training.orchestration`'s own
    in-process-only replay guard, this is explicitly NOT a durable,
    cross-process ledger -- a genuinely new process has no memory of a
    prior process's consumed nonces. A real deployment's durable defense
    against replay across process restarts would need to persist
    consumed `(run_id, nonce)` pairs to disk (or reuse
    `orca.train.authorization`'s own on-disk run-slot ledger pattern,
    scoped separately) -- not attempted here; `reset_in_process_nonce_guard_for_new_process()`
    exists for the same documented reason
    `GenesisTrainingRun.reset_in_process_replay_guard_for_new_process()`
    does."""


_consumed_nonces: set[tuple[str, str]] = set()


def reset_in_process_nonce_guard_for_new_process() -> None:
    """Call only at a genuinely new OS process's entrypoint -- see
    `NonceReplayedError`'s docstring."""
    global _consumed_nonces
    _consumed_nonces = set()


# ---- entry point ----

def authorize_native_pretraining(
    *, repo_root: Path, record: dict, registry: dict, revoked_ids: list[str], req: NativePretrainingRequest,
    revocation_check: Callable[[str], bool], now: datetime | None = None,
) -> NativePretrainingGrant:
    """The single choke point. `revocation_check` is MANDATORY -- Mission
    F3's explicit requirement: 'a missing, failing or unavailable
    revocation service must not silently authorize progress.' A caller
    that cannot provide one (or whose check raises) is denied, not
    defaulted to 'not revoked.'

    ALSO requires the real, project-wide founder-acceptance ledger
    (`scripts.acceptance.acceptance_engine`) to show GENESIS pretraining's
    gating rows (R65, G1, AUTH-1, FINAL-1) accepted -- this ledger is
    empty today, so this check alone denies every call until the founder
    completes that separate, frozen acceptance process."""
    now = now or datetime.now(timezone.utc)

    if revocation_check is None:
        raise NativePretrainingNotAuthorized(["REVOCATION_CHECK_REQUIRED"])

    missing_rows = check_founder_acceptance_ledger(repo_root)
    if missing_rows:
        raise NativePretrainingNotAuthorized([f"FOUNDER_ACCEPTANCE_INCOMPLETE:{row}" for row in missing_rows])

    if registry is None or validate_registry(registry) or registry_digest(registry) != PINNED_REGISTRY_SHA256:
        raise NativePretrainingNotAuthorized(["AUTHORITY_REGISTRY_UNREADABLE_OR_NOT_PINNED"])
    if not isinstance(record, dict) or record.get("status") != "AUTHORIZED":
        raise NativePretrainingNotAuthorized(["NOT_AUTHORIZED" if isinstance(record, dict) else "RECORD_INVALID"])

    verdict = verify(record, req, registry, revoked_ids, now)
    if not verdict.authorized:
        raise NativePretrainingNotAuthorized(verdict.reasons)

    nonce_key = (req.run_id, req.nonce)
    if nonce_key in _consumed_nonces:
        raise NonceReplayedError(f"(run_id={req.run_id!r}, nonce={req.nonce!r}) has already been consumed in this process")

    try:
        if revocation_check(record["authorization_id"]):
            raise NativePretrainingNotAuthorized(["AUTHORIZATION_REVOKED_LIVE"])
    except NativePretrainingNotAuthorized:
        raise
    except Exception as e:  # noqa: BLE001 -- an unavailable/erroring revocation service is a denial, never a silent pass
        raise NativePretrainingNotAuthorized([f"REVOCATION_CHECK_UNAVAILABLE:{e!r}"]) from e

    _consumed_nonces.add(nonce_key)
    record_sha = hashlib.sha256(_canonical(record)).hexdigest()
    return NativePretrainingGrant(
        authorization_id=record["authorization_id"], key_id=record["authorizing_authority"]["key_id"],
        record_sha256=record_sha, run_id=req.run_id, expires_at=record["expires_at"],
        max_wall_clock_minutes=record["limits"]["max_wall_clock_minutes"], model_config_digest=req.model_config_digest,
        tokenizer_digest=req.tokenizer_digest, dataset_manifest_id=req.dataset_manifest_id,
        dataset_content_digest=req.dataset_content_digest, authorized_shard_digests=req.authorized_shard_digests,
        environment_class=req.environment_class, architecture_version=req.architecture_version,
        reviewed_commit_sha=req.reviewed_commit_sha, transformation_code_digest=req.transformation_code_digest,
        optimizer_config_digest=req.optimizer_config_digest, gpu_allowed=record["limits"]["gpu_allowed"],
        max_spend_usd=record["limits"]["max_spend_usd"], _seal=_SEAL,
    )


def assert_execution_permitted(grant: NativePretrainingGrant, *, revocation_check: Callable[[str], bool], now: datetime | None = None) -> None:
    """MANDATORY re-check at the actual execution boundary (Mission F3).
    Never assume a grant issued earlier is still valid: re-verifies HMAC
    integrity, expiry, AND live revocation -- the same mandatory,
    non-optional revocation check `authorize_native_pretraining()` itself
    requires. An unavailable or erroring revocation service denies
    execution; it never silently permits it."""
    grant.verify_integrity()
    now = now or datetime.now(timezone.utc)
    expires = _parse_ts(grant.expires_at)
    if expires is None or now >= expires:
        raise NativePretrainingNotAuthorized(["EXPIRED"])
    if revocation_check is None:
        raise NativePretrainingNotAuthorized(["REVOCATION_CHECK_REQUIRED"])
    try:
        if revocation_check(grant.authorization_id):
            raise NativePretrainingNotAuthorized(["AUTHORIZATION_REVOKED_LIVE"])
    except NativePretrainingNotAuthorized:
        raise
    except Exception as e:  # noqa: BLE001
        raise NativePretrainingNotAuthorized([f"REVOCATION_CHECK_UNAVAILABLE:{e!r}"]) from e
