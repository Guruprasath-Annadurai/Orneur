"""Training authorization gate (fail closed).

No real fine-tuning job may start -- locally, over SSH to a rented GPU, or through any lower-level function -- unless a signed authorization
record proves, for THIS exact request, that a registered training authority approved it. See
docs/orneur/authorization/TRAINING_AUTHORIZATION_DESIGN.md for the threat model.

What a grant is bound to (all must match the request EXACTLY, computed from facts the process cannot choose, never from the record):
  model family + base model + pinned revision, SHA-256 of the exact train/eval files, dataset manifest ids / bundle id, environment class
  (the entry path declares it), purpose, resource limits (runs, epochs, LoRA rank, sequence length, wall clock, spend), GPU permission, the
  reviewed commit (HEAD must be that commit or a descendant), a code-tree hash over orca/train + orca/registry, a clean working tree, and a
  short validity window.

What it deliberately does NOT consult: environment variables, CLI flags, config flags, branch names, commit messages, test markers, or a
"dry run" switch. Nothing in this module can sign: there is no private key handling here, so the training process cannot issue or approve its
own permission. Authority keys come from TRAINING_AUTHORITY_REGISTRY.json, whose canonical digest is PINNED in this source file, so adding a
key requires a reviewed source change as well as a registry change. The committed registry is empty and the committed record is
NOT_AUTHORIZED: nothing can be authorized until the founder provisions a key (a separate, founder-approved action).

Honest limits (documented, not hidden): code running in the same OS process with the privileges of the operator can import private helpers
or edit this file; an operator can run their own training script that never imports ORNEUR. This gate controls ORNEUR's own entry points and
makes any bypass require a source change that code review and the code-tree hash will see.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = "orneur-training-authorization/1"
REGISTRY_SCHEMA_VERSION = "orneur-training-authority-registry/1"
REVOCATIONS_SCHEMA_VERSION = "orneur-training-authorization-revocations/1"
RECORD_PATH = "docs/orneur/authorization/TRAINING_AUTHORIZATION.json"
REGISTRY_PATH = "docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json"
REVOCATIONS_PATH = "docs/orneur/authorization/TRAINING_AUTHORIZATION_REVOCATIONS.json"
SIGNING_DOMAIN = b"orneur-training-authorization/1\n"   # signatures made for any other purpose (e.g. model-eval) can never verify here

# Canonical SHA-256 of the committed (empty) registry. Provisioning a founder key means changing BOTH the registry file and this constant,
# in a reviewed change. A registry that does not hash to this value authorizes nothing.
PINNED_REGISTRY_SHA256 = "182f4069127ce1993393893d42d560231e028d23c42de69bb0c264fb5b992c84"

PURPOSES = ("EXPERIMENTAL_PILOT", "CANONICAL_RUN")
ENVIRONMENT_CLASSES = ("SELF_HOSTED_GPU", "SSH_RENTED_GPU")
AUTHORITY_ROLES = ("OWNER", "DELEGATED_OWNER")
GENERIC_FAMILY = "GENERIC"          # a config whose family is None (hardware-sizing preset, not a canonical family)
MAX_VALIDITY = timedelta(days=14)
CODE_PATHS = ("orca/train", "orca/registry")   # directories; every *.py file beneath, sorted

RECORD_KEYS = frozenset({
    "schema_version", "authorization_id", "status", "purpose", "reviewed_commit_sha", "authorized_code_tree_sha256", "model", "datasets",
    "environment_class", "limits", "permissions", "issued_at", "expires_at", "authorizing_authority", "signature",
})
MODEL_KEYS = frozenset({"family", "base_model", "base_model_revision"})
DATASET_KEYS = frozenset({"train_sha256", "eval_sha256", "dataset_manifest_ids", "dataset_bundle_id"})
LIMIT_KEYS = frozenset({"max_runs", "max_epochs", "max_lora_rank", "max_seq_length", "max_wall_clock_minutes", "max_spend_usd"})
PERMISSION_KEYS = frozenset({"gpu_allowed"})
REGISTRY_FIELDS = ("id", "role", "public_key_hex", "activation_timestamp", "expiry", "revoked", "permitted_purposes",
                   "permitted_environment_classes", "permitted_families", "gpu_permission", "spend_permission")

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^tauth-[0-9a-f]{16,64}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SEAL = object()      # only authorize_training() holds this; see TrainingGrant


class TrainingNotAuthorized(PermissionError):
    """Raised for every denial. `.reasons` is a list of stable reason codes; the message never contains record contents or secrets."""

    def __init__(self, reasons: list[str]):
        self.reasons = list(reasons)
        super().__init__("training is not authorized: " + ", ".join(self.reasons))


# ─── canonical forms ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def canonical_signing_bytes(record: dict) -> bytes:
    return SIGNING_DOMAIN + _canonical({k: v for k, v in record.items() if k != "signature"})


def registry_digest(doc) -> str:
    return hashlib.sha256(_canonical(doc)).hexdigest()


def default_record() -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "authorization_id": None, "status": "NOT_AUTHORIZED", "purpose": None, "reviewed_commit_sha": None,
        "authorized_code_tree_sha256": None, "model": {"family": None, "base_model": None, "base_model_revision": None},
        "datasets": {"train_sha256": None, "eval_sha256": None, "dataset_manifest_ids": [], "dataset_bundle_id": None},
        "environment_class": None,
        "limits": {"max_runs": 0, "max_epochs": 0, "max_lora_rank": 0, "max_seq_length": 0, "max_wall_clock_minutes": 0, "max_spend_usd": 0},
        "permissions": {"gpu_allowed": False}, "issued_at": None, "expires_at": None,
        "authorizing_authority": {"identity": None, "role": None, "key_id": None}, "signature": None,
    }


def empty_registry() -> dict:
    return {"schema_version": REGISTRY_SCHEMA_VERSION, "records": []}


def empty_revocations() -> dict:
    return {"schema_version": REVOCATIONS_SCHEMA_VERSION, "revoked_authorization_ids": []}


# ─── request (built from trusted runtime facts) ───────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Request:
    head_sha: str
    reviewed_commit_is_ancestor: bool
    working_tree_clean: bool
    current_code_tree_sha256: str
    family: str                       # canonical family name, or GENERIC_FAMILY
    base_model: str
    base_model_revision: str | None
    train_sha256: str
    eval_sha256: str | None
    dataset_manifest_ids: tuple
    dataset_bundle_id: str | None
    environment_class: str
    purpose: str
    epochs: int
    lora_rank: int
    max_seq_length: int
    requested_spend_usd: float
    gpu: bool = True


@dataclass
class Verdict:
    authorized: bool
    reasons: list = field(default_factory=list)


def _isint(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _parse_ts(s):
    if not isinstance(s, str) or not _TS.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ─── registry ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def validate_registry(doc) -> list:
    if not isinstance(doc, dict) or doc.get("schema_version") != REGISTRY_SCHEMA_VERSION or set(doc) != {"schema_version", "records"} \
            or not isinstance(doc.get("records"), list):
        return ["registry schema mismatch"]
    problems, seen = [], set()
    for r in doc["records"]:
        if not isinstance(r, dict) or set(r) != set(REGISTRY_FIELDS):
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
        for k, allowed in (("permitted_purposes", PURPOSES), ("permitted_environment_classes", ENVIRONMENT_CLASSES)):
            if not isinstance(r[k], list) or not r[k] or not set(r[k]) <= set(allowed):
                problems.append(f"{k} invalid")
        if not isinstance(r["permitted_families"], list) or not r["permitted_families"] or not all(isinstance(x, str) and x for x in r["permitted_families"]):
            problems.append("permitted_families invalid")
    return problems


def _key_active(r: dict, now: datetime) -> bool:
    if r.get("revoked") is not False:
        return False
    start, end = _parse_ts(r.get("activation_timestamp")), _parse_ts(r.get("expiry")) if r.get("expiry") else None
    return start is not None and start <= now and (end is None or now < end)


def verify_signature(record: dict, registry_doc: dict, now: datetime) -> tuple:
    """Returns (reason_or_None, registry_record_or_None)."""
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


# ─── verification (pure; no I/O) ──────────────────────────────────────────────────────────────────────────────────────────────────

def verify(record, req: Request, registry_doc, revoked_ids, now: datetime | None = None) -> Verdict:
    """Authorized only if `reasons` is empty."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(record, dict):
        return Verdict(False, ["RECORD_NOT_AN_OBJECT"])
    if set(record) != RECORD_KEYS:
        return Verdict(False, ["RECORD_SCHEMA_MISMATCH"])
    if record["schema_version"] != SCHEMA_VERSION:
        return Verdict(False, ["SCHEMA_VERSION_MISMATCH"])
    if record["status"] != "AUTHORIZED":
        return Verdict(False, ["NOT_AUTHORIZED" if record["status"] == "NOT_AUTHORIZED" else "STATUS_INVALID"])
    r: list = []
    model, ds, lim, perm = record["model"], record["datasets"], record["limits"], record["permissions"]
    if not (isinstance(model, dict) and set(model) == MODEL_KEYS and isinstance(ds, dict) and set(ds) == DATASET_KEYS
            and isinstance(lim, dict) and set(lim) == LIMIT_KEYS and isinstance(perm, dict) and set(perm) == PERMISSION_KEYS):
        return Verdict(False, ["RECORD_SCHEMA_MISMATCH"])
    if not (isinstance(record["authorization_id"], str) and _ID.match(record["authorization_id"])):
        r.append("AUTHORIZATION_ID_INVALID")
    elif record["authorization_id"] in set(revoked_ids or ()):
        r.append("AUTHORIZATION_REVOKED")
    if record["purpose"] not in PURPOSES or record["purpose"] != req.purpose:
        r.append("WRONG_PURPOSE")
    if record["environment_class"] not in ENVIRONMENT_CLASSES or record["environment_class"] != req.environment_class:
        r.append("WRONG_ENVIRONMENT_CLASS")
    # model
    if model["family"] != req.family or not req.family:
        r.append("WRONG_FAMILY")
    if model["base_model"] != req.base_model or not req.base_model:
        r.append("WRONG_BASE_MODEL")
    if model["base_model_revision"] != req.base_model_revision:
        r.append("WRONG_BASE_MODEL_REVISION")
    # datasets
    if not (isinstance(ds["train_sha256"], str) and _SHA64.match(ds["train_sha256"])) or ds["train_sha256"] != req.train_sha256:
        r.append("WRONG_TRAIN_DATASET")
    if ds["eval_sha256"] != req.eval_sha256 or (ds["eval_sha256"] is not None and not (isinstance(ds["eval_sha256"], str) and _SHA64.match(ds["eval_sha256"]))):
        r.append("WRONG_EVAL_DATASET")
    if not isinstance(ds["dataset_manifest_ids"], list) or tuple(sorted(ds["dataset_manifest_ids"])) != tuple(sorted(req.dataset_manifest_ids)):
        r.append("WRONG_DATASET_MANIFESTS")
    if ds["dataset_bundle_id"] != req.dataset_bundle_id:
        r.append("WRONG_DATASET_BUNDLE")
    # limits
    for k in ("max_runs", "max_epochs", "max_lora_rank", "max_seq_length", "max_wall_clock_minutes"):
        if not _isint(lim[k]) or lim[k] < 1:
            r.append("LIMITS_INVALID")
            break
    else:
        if req.epochs > lim["max_epochs"]:
            r.append("EPOCHS_NOT_AUTHORIZED")
        if req.lora_rank > lim["max_lora_rank"]:
            r.append("LORA_RANK_NOT_AUTHORIZED")
        if req.max_seq_length > lim["max_seq_length"]:
            r.append("SEQUENCE_LENGTH_NOT_AUTHORIZED")
    if not _isnum(lim["max_spend_usd"]) or lim["max_spend_usd"] < 0:
        r.append("LIMITS_INVALID")
    elif not _isnum(req.requested_spend_usd) or req.requested_spend_usd != req.requested_spend_usd or req.requested_spend_usd > lim["max_spend_usd"]:
        r.append("SPEND_NOT_AUTHORIZED")
    if not isinstance(perm["gpu_allowed"], bool) or (req.gpu and perm["gpu_allowed"] is not True):
        r.append("GPU_NOT_AUTHORIZED")
    # commit / code binding
    if not (isinstance(record["reviewed_commit_sha"], str) and _SHA40.match(record["reviewed_commit_sha"])):
        r.append("BAD_REVIEWED_COMMIT_SHA")
    elif not (isinstance(req.head_sha, str) and _SHA40.match(req.head_sha)):
        r.append("BAD_HEAD_SHA")
    elif req.reviewed_commit_is_ancestor is not True:
        r.append("REVIEWED_COMMIT_NOT_ANCESTOR_OF_HEAD")
    if req.working_tree_clean is not True:
        r.append("DIRTY_WORKING_TREE")
    if not (isinstance(record["authorized_code_tree_sha256"], str) and _SHA64.match(record["authorized_code_tree_sha256"])):
        r.append("BAD_AUTHORIZED_CODE_TREE_HASH")
    elif record["authorized_code_tree_sha256"] != req.current_code_tree_sha256:
        r.append("CODE_TREE_HASH_MISMATCH")
    # validity window
    issued, expires = _parse_ts(record["issued_at"]), _parse_ts(record["expires_at"])
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
    # authority
    auth = record["authorizing_authority"]
    if not (isinstance(auth, dict) and set(auth) == {"identity", "role", "key_id"} and auth["role"] in AUTHORITY_ROLES
            and isinstance(auth["identity"], str) and auth["identity"] and isinstance(auth["key_id"], str) and auth["key_id"]):
        r.append("AUTHORITY_INVALID")
    elif not registry_doc or not registry_doc.get("records"):
        r.append("NO_TRUSTED_TRAINING_AUTHORITY_REGISTERED")
    elif not r:
        reason, key = verify_signature(record, registry_doc, now)
        if reason:
            r.append(reason)
        elif key is not None:
            if req.purpose not in key["permitted_purposes"]:
                r.append("AUTHORITY_NOT_SCOPED_TO_PURPOSE")
            if req.environment_class not in key["permitted_environment_classes"]:
                r.append("AUTHORITY_NOT_SCOPED_TO_ENVIRONMENT")
            if req.family not in key["permitted_families"]:
                r.append("AUTHORITY_NOT_SCOPED_TO_FAMILY")
            if req.gpu and key["gpu_permission"] is not True:
                r.append("AUTHORITY_LACKS_GPU_PERMISSION")
            if lim["max_spend_usd"] > 0 and key["spend_permission"] is not True:
                r.append("AUTHORITY_LACKS_SPEND_PERMISSION")
    return Verdict(not r, r)


# ─── repository facts (git + files) ───────────────────────────────────────────────────────────────────────────────────────────────

def _default_root() -> Path:
    """Where the signed record, registry and revocations live: the repository this module was loaded from. Never taken from the environment
    or from a caller argument. Tests monkeypatch this function to point at a synthetic repository."""
    return Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> tuple:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30, check=False)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def code_tree_sha256(root: Path) -> str:
    h = hashlib.sha256()
    for rel in CODE_PATHS:
        for f in sorted((Path(root) / rel).rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            h.update(f.relative_to(root).as_posix().encode() + b"\0" + hashlib.sha256(f.read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return None


# ─── state (run slots + chained audit events); lives under the hardened ORNEUR home, never in the repo ─────────────────────────────

def _state_dir() -> Path:
    from orca.config import ORCA_HOME, _mkdir_owner_only
    return _mkdir_owner_only(ORCA_HOME / "training" / "authorization", parents=True)


def _append_event(state: Path, event: dict) -> dict:
    """Append-only, hash-chained event log. Best-effort for denials (a failure to log never turns a denial into a grant)."""
    path = state / "events.jsonl"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with open(path, "rb") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        prev = json.loads(lines[-1])["hash"] if lines else "0" * 64
        body = {**event, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "prev": prev}
        body["hash"] = hashlib.sha256(_canonical(body)).hexdigest()
        os.write(fd, _canonical(body) + b"\n")
        return body
    finally:
        os.close(fd)


def verify_event_chain(state: Path) -> bool:
    prev = "0" * 64
    p = Path(state) / "events.jsonl"
    if not p.exists():
        return True
    for ln in p.read_text().splitlines():
        if not ln.strip():
            continue
        e = json.loads(ln)
        h = e.pop("hash")
        if e.get("prev") != prev or hashlib.sha256(_canonical(e)).hexdigest() != h:
            return False
        prev = h
    return True


def _claim_run_slot(state: Path, authorization_id: str, max_runs: int) -> int | None:
    """Atomically claim one of the `max_runs` slots (O_CREAT|O_EXCL). Returns the slot index, or None if exhausted. A failed or cancelled run
    still consumes its slot. (A local operator who deletes this directory can re-run within the grant's other limits; that is a documented
    residual -- the grant's expiry, hash bindings and limits still apply.)"""
    from orca.config import _mkdir_owner_only
    d = _mkdir_owner_only(state / "runs" / authorization_id, parents=True)
    for i in range(max_runs):
        try:
            fd = os.open(d / f"slot-{i}", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        return i
    return None


# ─── the grant ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _cfg_fingerprint(cfg) -> str:
    return hashlib.sha256(_canonical({
        "family": cfg.family, "base_model": cfg.base_model, "epochs": cfg.num_epochs, "lora_r": cfg.lora.r, "lora_alpha": cfg.lora.lora_alpha,
        "max_seq_length": cfg.max_seq_length, "train_file": cfg.train_file, "eval_file": cfg.eval_file, "data_format": cfg.data_format,
    })).hexdigest()


@dataclass(frozen=True)
class TrainingGrant:
    """Proof that authorize_training() verified a request. It can only be constructed with the module-private seal, so a caller cannot mint
    one by hand through the public API; every training function re-checks it against the config and the exact data it is about to read."""
    authorization_id: str
    key_id: str
    record_sha256: str
    run_slot: int
    expires_at: str
    max_wall_clock_minutes: int
    cfg_fingerprint: str
    train_sha256: str
    eval_sha256: str | None
    environment_class: str
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._seal is not _SEAL:
            raise TrainingNotAuthorized(["GRANT_NOT_ISSUED_BY_GATE"])

    def assert_valid_for(self, cfg, *, environment_class: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        problems = []
        if self.cfg_fingerprint != _cfg_fingerprint(cfg):
            problems.append("CONFIG_CHANGED_AFTER_AUTHORIZATION")
        if self.environment_class != environment_class:
            problems.append("WRONG_ENVIRONMENT_CLASS")
        exp = _parse_ts(self.expires_at)
        if exp is None or now >= exp:
            problems.append("EXPIRED")
        if problems:
            raise TrainingNotAuthorized(problems)

    def assert_files(self, train_file, eval_file) -> None:
        """Re-hash the exact files about to be consumed. Call immediately before AND after loading."""
        problems = []
        if file_sha256(train_file) != self.train_sha256:
            problems.append("TRAIN_DATA_CHANGED_AFTER_AUTHORIZATION")
        if self.eval_sha256 is None:
            if eval_file is not None:
                problems.append("UNAUTHORIZED_EVAL_DATA")
        elif eval_file is None or file_sha256(eval_file) != self.eval_sha256:
            problems.append("EVAL_DATA_CHANGED_AFTER_AUTHORIZATION")
        if problems:
            raise TrainingNotAuthorized(problems)

    def wall_clock_callback(self, clock: Callable[[], float] = time.monotonic):
        return WallClockLimit(self.max_wall_clock_minutes * 60, clock)


class WallClockLimit:
    """Duck-typed HF TrainerCallback: stops training once the authorized wall-clock budget is spent."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self.deadline = clock() + seconds
        self.clock = clock
        self.tripped = False

    def _check(self, control):
        if self.clock() >= self.deadline:
            self.tripped = True
            control.should_training_stop = True
        return control

    def on_step_end(self, args, state, control, **kw):
        return self._check(control)

    def on_substep_end(self, args, state, control, **kw):
        return self._check(control)

    def __getattr__(self, name):          # every other TrainerCallback hook is a no-op
        if name.startswith("on_"):
            return lambda args, state, control, **kw: control
        raise AttributeError(name)


# ─── entry: build the request, verify, claim a slot, write evidence ──────────────────────────────────────────────────────────────

def _build_request(cfg, root: Path, *, environment_class, purpose, dataset_manifest_ids, dataset_bundle_id, requested_spend_usd, record) -> Request:
    from orca.registry.provenance import resolve_pinned_revisions
    from orca.train.config import resolve_training_data_inputs

    rc, head = _git(root, "rev-parse", "HEAD")
    reviewed = record.get("reviewed_commit_sha") if isinstance(record, dict) else None
    ancestor = bool(rc == 0 and isinstance(reviewed, str) and _SHA40.match(reviewed)
                    and _git(root, "merge-base", "--is-ancestor", reviewed, head)[0] == 0)
    rc2, porcelain = _git(root, "status", "--porcelain")
    resolved = resolve_training_data_inputs(cfg)
    if not Path(resolved.train_path).is_file():
        raise TrainingNotAuthorized(["TRAIN_DATA_MISSING"])
    try:
        base_rev, _ = resolve_pinned_revisions(cfg)
    except Exception:
        raise TrainingNotAuthorized(["BASE_MODEL_REVISION_UNRESOLVABLE"]) from None
    return Request(
        head_sha=head if rc == 0 else "", reviewed_commit_is_ancestor=ancestor, working_tree_clean=(rc2 == 0 and porcelain == ""),
        current_code_tree_sha256=code_tree_sha256(root), family=cfg.family or GENERIC_FAMILY, base_model=cfg.base_model,
        base_model_revision=base_rev, train_sha256=file_sha256(resolved.train_path),
        eval_sha256=file_sha256(resolved.eval_path) if resolved.eval_path is not None else None,
        dataset_manifest_ids=tuple(dataset_manifest_ids or ()), dataset_bundle_id=dataset_bundle_id, environment_class=environment_class,
        purpose=purpose, epochs=cfg.num_epochs, lora_rank=cfg.lora.r, max_seq_length=cfg.max_seq_length,
        requested_spend_usd=requested_spend_usd,
    )


def purpose_for(cfg) -> str:
    return "CANONICAL_RUN" if cfg.family is not None else "EXPERIMENTAL_PILOT"


def authorize_training(cfg, *, environment_class: str, dataset_manifest_ids=None, dataset_bundle_id=None,
                       requested_spend_usd: float = 0.0, now: datetime | None = None) -> TrainingGrant:
    """The single choke point. Raises TrainingNotAuthorized (with stable reason codes) for anything other than a fully verified, in-budget,
    unrevoked, unexpired grant bound to this exact request. There is intentionally no bypass parameter."""
    root = _default_root()
    now = now or datetime.now(timezone.utc)
    state = None
    try:
        state = _state_dir()
    except Exception:
        raise TrainingNotAuthorized(["STATE_DIRECTORY_UNTRUSTED"]) from None

    def deny(reasons, record=None):
        try:
            _append_event(state, {"event": "TRAINING_DENIED", "reasons": sorted(set(reasons)), "environment_class": environment_class,
                                  "authorization_id": (record or {}).get("authorization_id") if isinstance(record, dict) else None,
                                  "base_model": getattr(cfg, "base_model", None)})
        except Exception:
            pass
        raise TrainingNotAuthorized(sorted(set(reasons)))

    if environment_class not in ENVIRONMENT_CLASSES:
        deny(["UNKNOWN_ENVIRONMENT_CLASS"])
    registry = _load_json(root / REGISTRY_PATH)
    if registry is None or validate_registry(registry) or registry_digest(registry) != PINNED_REGISTRY_SHA256:
        deny(["AUTHORITY_REGISTRY_UNREADABLE_OR_NOT_PINNED"])
    revocations = _load_json(root / REVOCATIONS_PATH)
    if not (isinstance(revocations, dict) and revocations.get("schema_version") == REVOCATIONS_SCHEMA_VERSION
            and isinstance(revocations.get("revoked_authorization_ids"), list)):
        deny(["REVOCATION_LIST_UNREADABLE"])          # an unreadable revocation list is never treated as "nothing revoked"
    record = _load_json(root / RECORD_PATH)
    if record is None:
        deny(["RECORD_UNREADABLE"])
    if not isinstance(record, dict) or record.get("status") != "AUTHORIZED":
        deny(["NOT_AUTHORIZED" if isinstance(record, dict) and record.get("status") == "NOT_AUTHORIZED" else "RECORD_INVALID"], record)
    try:
        req = _build_request(cfg, root, environment_class=environment_class, purpose=purpose_for(cfg),
                             dataset_manifest_ids=dataset_manifest_ids, dataset_bundle_id=dataset_bundle_id,
                             requested_spend_usd=requested_spend_usd, record=record)
    except TrainingNotAuthorized as e:
        deny(e.reasons, record)
    verdict = verify(record, req, registry, revocations["revoked_authorization_ids"], now)
    if not verdict.authorized:
        deny(verdict.reasons, record)

    auth_id = record["authorization_id"]
    slot = _claim_run_slot(state, auth_id, record["limits"]["max_runs"])
    if slot is None:
        deny(["RUN_BUDGET_EXHAUSTED"], record)
    record_sha = hashlib.sha256(_canonical(record)).hexdigest()
    grant = TrainingGrant(
        authorization_id=auth_id, key_id=record["authorizing_authority"]["key_id"], record_sha256=record_sha, run_slot=slot,
        expires_at=record["expires_at"], max_wall_clock_minutes=record["limits"]["max_wall_clock_minutes"],
        cfg_fingerprint=_cfg_fingerprint(cfg), train_sha256=req.train_sha256, eval_sha256=req.eval_sha256,
        environment_class=environment_class, _seal=_SEAL,
    )
    evidence = {
        "event": "TRAINING_AUTHORIZED", "authorization_id": auth_id, "run_slot": slot, "key_id": grant.key_id, "record_sha256": record_sha,
        "head_sha": req.head_sha, "reviewed_commit_sha": record["reviewed_commit_sha"], "code_tree_sha256": req.current_code_tree_sha256,
        "family": req.family, "base_model": req.base_model, "base_model_revision": req.base_model_revision, "purpose": req.purpose,
        "environment_class": environment_class, "train_sha256": req.train_sha256, "eval_sha256": req.eval_sha256,
        "dataset_manifest_ids": sorted(req.dataset_manifest_ids), "dataset_bundle_id": req.dataset_bundle_id,
        "epochs": req.epochs, "lora_rank": req.lora_rank, "max_seq_length": req.max_seq_length, "requested_spend_usd": req.requested_spend_usd,
        "expires_at": record["expires_at"],
    }
    try:
        _append_event(state, evidence)
    except Exception:
        # Evidence is mandatory: a grant whose audit record could not be written is not honoured.
        raise TrainingNotAuthorized(["AUDIT_RECORD_UNWRITABLE"]) from None
    return grant


def require_grant(grant, cfg, *, environment_class: str) -> TrainingGrant:
    """Used by every lower-level training function: a missing, wrong-typed or stale grant is a denial, never a default."""
    if not isinstance(grant, TrainingGrant):
        raise TrainingNotAuthorized(["NO_TRAINING_GRANT"])
    grant.assert_valid_for(cfg, environment_class=environment_class)
    return grant
