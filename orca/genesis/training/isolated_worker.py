"""
GENESIS Native Learning Engine -- Antigravity Audit #075 (independent
successor requalification) remediation, Mission A: a minimal, fail-
closed, single-host, process-isolated GENESIS training worker.

## Why this module exists

Every prior phase of this codebase has been explicit and honest that
`TrainingStepEngine`/`learning_governance.execute_authorized_training_step()`
are an IN-PROCESS cooperative-caller contract: nothing in pure Python
can stop a co-resident, equally-privileged caller in the SAME
interpreter from calling `TrainingStepEngine._issue_capability_for_
governance()` directly, or from writing an equivalent training loop
from scratch against the same public primitives. Audit #074 and #075
both recorded this as an open architectural requirement, not a
cosmetic gap to paper over with a tighter in-process check. This module
is that architecture.

## Threat model, stated explicitly

**In scope -- what this module defends against:**
- A client process that does NOT share this worker's address space
  attempting to call `step()`, read model weights, read the optimizer
  state, or obtain a capability token: structurally impossible, because
  the client never holds a Python reference to any of those objects --
  they exist only inside the worker's own process, constructed by the
  worker itself, never serialized across the IPC boundary.
- An unauthenticated or wrong-token IPC client: every message is
  HMAC-SHA256 signed with a shared secret established at worker spawn
  time (passed via `multiprocessing`'s own in-memory argument-passing,
  never written to disk, an environment variable, or process argv/
  command line -- so it is not visible via `ps` or `/proc/<pid>/environ`).
- A replayed IPC message (the exact same signed request sent again): a
  strictly-increasing sequence number plus a bounded nonce cache reject
  any message whose `seq` does not exceed the highest `seq` already
  accepted, or whose `nonce` has already been seen.
- A cross-workload/cross-run request (a message addressed to a
  DIFFERENT `workload_id` than the one this worker instance was bound
  to at spawn time): rejected before any training logic runs.
- Authorization becoming invalid (expiry, live revocation, or identity
  drift) WHILE the worker is running: `step` commands are dispatched
  through the EXACT SAME `learning_governance
  .execute_authorized_training_step()` this codebase already uses,
  which independently re-verifies the grant on every single call, with
  no caller-controllable cadence (see that module's own Audit #075
  fix). On the FIRST such failure, this worker does not merely refuse
  that one command -- it terminates its own process entirely, so no
  further command of any kind (including an innocuous `ping`) is ever
  served again. A fresh, re-authorized worker must be spawned to
  resume, by design.

## Isolation qualification, reported honestly -- not asserted

**A separate OS process alone (`multiprocessing`'s `spawn`) is NEVER
described anywhere in this module as a privilege/security boundary.**
Every `IsolatedTrainingWorker.start()` call sets
`self.isolation_qualification` to exactly one of three honest labels,
computed by the worker itself before it serves anything, and the
controller/any report built on this module MUST surface whichever one
actually applied:
- `ISOLATION_NOT_QUALIFIED` -- the default, conservative label. Reported
  whenever either (a) kernel peer-credential verification
  (`SO_PEERCRED`) is unavailable on this platform (true on macOS during
  this phase's own development -- there is no portable equivalent this
  module implements), or (b) the worker is running under the SAME uid
  as whatever spawned it (no `drop_to_uid`). In this state, this module
  makes NO privilege-isolation claim at all -- it is a separate process
  with its own address space and nothing more.
- `PEER_VERIFIED_SAME_UID` -- `SO_PEERCRED` IS available and every
  accepted connection's peer uid is independently, kernel-verified
  (never self-reported by the peer) against the uid that spawned this
  worker, but the worker still runs as that SAME uid. This stops a
  DIFFERENT uid's process from ever being accepted as a client; it does
  NOT stop a same-uid process (which, on Linux, can generally ptrace or
  read `/proc/<pid>/mem` of another same-uid process, subject to
  `ptrace_scope`).
- `PEER_VERIFIED_UID_SEPARATED` -- `SO_PEERCRED` available AND the
  worker successfully dropped (`drop_to_uid`, requires starting as
  root) to a distinct, lower-privileged uid before touching any model/
  grant state. This is the only label this module considers genuine
  OS-level privilege isolation; it still does not imply a container,
  seccomp profile, or any sandbox beyond uid/gid separation.

A caller that requires `PEER_VERIFIED_UID_SEPARATED` and gets anything
else must treat that run as `ISOLATION_NOT_QUALIFIED` for any claim
stronger than "ran in a separate process" -- this module itself never
upgrades its own report, and nothing here should be read as claiming
otherwise.

**Explicitly, honestly NOT in scope -- what this module does NOT achieve
by default:**
- **Same-uid co-resident isolation.** By default, this worker runs as
  the SAME OS user as its spawning process. On POSIX, a same-uid
  process can generally attach a debugger, read `/proc/<pid>/mem` (on
  Linux, subject to ptrace_scope), or otherwise inspect another
  same-uid process's memory -- this module does not, and cannot from
  pure Python, prevent that. `WorkerStartupConfig.drop_to_uid`/
  `drop_to_gid` let a deployment that already runs its spawning process
  as root drop the worker to a SEPARATE, dedicated, lower-privileged
  account before any model/optimizer state is ever constructed, which
  DOES close this gap against other same-uid-as-the-ORIGINAL-process
  attackers (the worker is no longer that uid at all) -- but this is
  opt-in, requires root, and is NOT the default, because most
  development and CI environments do not run as root. If a caller
  requests `drop_to_uid` and this process is not root, `start()` fails
  closed (`IsolationPropertiesUnavailableError`) rather than silently
  proceeding at the original, more privileged uid.
- **A container, seccomp profile, network namespace, or any other OS
  sandbox.** This module only establishes a separate OS PROCESS
  (`multiprocessing`'s `fork` start method -- a genuinely distinct
  address space from the moment of fork onward, not a thread) reachable
  solely through one authenticated Unix domain socket. It does not set
  up, and does not claim to set up, any stronger sandbox.
- **Multi-tenant concurrent serving.** This worker accepts and serves
  exactly one client connection at a time, sequentially. It is a
  single-workload training daemon, not a general RPC server.

This module's own fail-closed posture: if the Unix-socket directory's
ownership/permissions cannot be verified as private to this process's
own uid, or if `drop_to_uid` is requested but unsatisfiable, the worker
process exits BEFORE constructing the model, optimizer, run, or grant --
never falls back to a weaker, silent default.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import multiprocessing
import os
import secrets
import socket
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import torch

from orca.genesis.governance.authorization import NativePretrainingRequest, authorize_native_pretraining
from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.training.learning_governance import (
    TrainingNotAuthorizedForExecutionError,
    execute_authorized_training_step,
    verify_live_authorization_or_raise,
)
from orca.genesis.training.learning_step import TrainingStepConfig, TrainingStepEngine, set_deterministic_seed
from orca.genesis.training.orchestration import BoundDatasetRecords, GenesisTrainingRun
from orca.genesis.training.primitives import TrainingState
from orca.genesis.training.resumable_checkpoint import (
    DatasetIdentity,
    compute_config_fingerprint,
    restore_resumable_checkpoint,
    save_resumable_checkpoint,
)

_MAX_MESSAGE_BYTES = 16 * 1024 * 1024
_NONCE_CACHE_SIZE = 4096

# AUDIT-075 (CTO pre-handoff security directive): explicit isolation
# qualification labels. "spawn" alone -- a separate OS process -- is
# NOT asserted anywhere in this module as a privilege boundary; these
# are the only honest labels `IsolatedTrainingWorker.isolation_qualification`
# ever reports, and the controller/report MUST surface whichever one
# actually applied, never silently assume the strongest.
ISOLATION_NOT_QUALIFIED = "ISOLATION_NOT_QUALIFIED"  # same uid as spawner, and/or peer-credential checking unavailable on this platform
PEER_VERIFIED_SAME_UID = "PEER_VERIFIED_SAME_UID"  # SO_PEERCRED confirms the actual connecting peer, but worker and client still share one uid -- NOT a privilege boundary, only authenticates "this actually is a process holding that uid's credentials," not a different, lower-privileged account
PEER_VERIFIED_UID_SEPARATED = "PEER_VERIFIED_UID_SEPARATED"  # SO_PEERCRED confirms the peer AND the worker successfully dropped to a distinct, lower-privileged uid (drop_to_uid) -- the only label this module considers genuine OS-level privilege isolation


class WorkerPeerAuthenticationError(Exception):
    """Raised (and the offending connection closed, without processing
    any command on it) when `SO_PEERCRED`/`LOCAL_PEERCRED` is available
    on this platform and the actual connecting peer's uid does not
    match the expected one. NOT raised, and the connection is NOT
    rejected on this basis, on a platform where peer-credential lookup
    is unavailable -- that case is reported instead via
    `ISOLATION_NOT_QUALIFIED`, never silently treated as verified."""


def _get_peer_credentials(conn: socket.socket) -> tuple[int, int, int] | None:
    """Returns `(pid, uid, gid)` of the ACTUAL connected peer, verified
    by the kernel (not self-reported by the peer in any message payload
    -- a payload-asserted identity is trivially forgeable; `SO_PEERCRED`
    is not), or `None` if this platform does not expose peer credentials
    for `AF_UNIX` sockets at all (e.g. this module found no working
    mechanism on macOS during development -- Linux's `SO_PEERCRED` is
    the one this module actively relies on; see the module docstring's
    isolation-qualification section)."""
    if sys.platform.startswith("linux") and hasattr(socket, "SO_PEERCRED"):
        try:
            raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, gid = struct.unpack("3i", raw)
            return (pid, uid, gid)
        except OSError:
            return None
    return None


class IsolationPropertiesUnavailableError(Exception):
    """Raised (by the worker, before any model/optimizer/grant state is
    constructed) when the required isolation properties -- private
    socket directory ownership/permissions, or a requested uid drop --
    cannot be established. Fail-closed: the worker never proceeds under
    weaker isolation than what it could not verify."""


class WorkerStartupError(Exception):
    """Raised by `IsolatedTrainingWorker.start()` on the CONTROLLER side
    when the worker process failed to reach its ready state, wrapping
    whatever it reported before exiting."""


@dataclass(frozen=True)
class WorkerStartupConfig:
    """Everything the worker process needs to independently build its
    own run, grant, model, and engine -- entirely inside its own
    process. Nothing pre-built by the controller is ever handed across
    the process boundary and trusted: `NativePretrainingGrant` itself
    is deliberately process-bound (its MAC is keyed by a per-process
    random key generated at import time in `authorization.py`), so a
    grant minted in the controller's process would FAIL its own
    integrity check if simply pickled into the worker -- this config
    carries the raw, signed INPUTS (`record`, `registry`, the exact
    `NativePretrainingRequest`) so the worker mints its own grant,
    bound to its own process, independently."""
    workload_id: str
    auth_token: bytes
    sock_path: str
    model_cfg: GenesisModelConfig
    step_cfg: TrainingStepConfig
    run_id: str
    dataset_manifest_ids: tuple[str, ...]
    environment_class: str
    repo_root: str
    dataset_digest: str
    model_config_digest: str
    tokenizer_digest: str
    authorized_shard_digests: tuple[str, ...]
    shard_dir: str
    reviewed_commit_sha: str
    transformation_code_digest: str
    optimizer_config_digest: str
    record: dict
    registry: dict
    req: NativePretrainingRequest
    revoked_ids_path: str
    drop_to_uid: int | None = None
    drop_to_gid: int | None = None
    orca_home_override: str | None = None  # redirects where the anti-replay/rollback ledgers live; not a security weakening
    test_only_bypass_founder_ledger: bool = False  # see this field's own check in _worker_main -- pytest-gated, misuse-resistant, not a production bypass
    test_only_pinned_registry_sha256: str | None = None  # paired with the above, for synthetic test registries only
    checkpoint_workspace_dir: str | None = None  # AUDIT-076 Phase 3: the ONLY directory save_checkpoint/restore_checkpoint may ever resolve a path under; None means those commands are refused entirely (fail-closed default)
    dataset_records: tuple[str, ...] = ()


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, default=str).encode("utf-8")


def _sign(token: bytes, *, seq: int, nonce: str, command: str, workload_id: str, payload: dict) -> str:
    fields = {"seq": seq, "nonce": nonce, "command": command, "workload_id": workload_id, "payload": payload}
    return hmac.new(token, _canonical(fields), hashlib.sha256).hexdigest()


def _send_framed(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("connection closed before the expected number of bytes was received")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_framed(sock: socket.socket) -> bytes:
    (length,) = struct.unpack(">I", _recv_exact(sock, 4))
    if length > _MAX_MESSAGE_BYTES:
        raise ValueError(f"framed message of {length} bytes exceeds the {_MAX_MESSAGE_BYTES}-byte ceiling")
    return _recv_exact(sock, length)


class CheckpointWorkspaceViolationError(Exception):
    """AUDIT-076 Phase 3: raised by `_enforce_checkpoint_path_confinement()`
    when a save_checkpoint/restore_checkpoint request's `path` does not
    resolve strictly underneath this worker's own configured
    `checkpoint_workspace_dir`, or when no workspace was configured at
    all (the fail-closed default -- no workspace means no checkpoint
    capability, not an unrestricted one)."""


def _enforce_checkpoint_path_confinement(cfg: "WorkerStartupConfig", requested_path: str) -> Path:
    """AUDIT-077 Phase 1: previously computed and validated a `resolved`
    path but never RETURNED it -- every call site then went on to use
    the caller's ORIGINAL, unresolved `requested_path` string for the
    actual `save_resumable_checkpoint`/`restore_resumable_checkpoint`
    call instead. For a RELATIVE `requested_path`, those are two
    genuinely different filesystem targets: validation correctly
    checked `(workspace / requested_path).resolve()`, but
    `Path(requested_path)` alone resolves relative to the WORKER
    PROCESS's OWN CURRENT WORKING DIRECTORY when the underlying
    filesystem call opens it -- which is not, and has no reason to be,
    the configured workspace. Independently reproduced before this fix:
    a relative path like `"ckpt.pt"` passed this function's own
    validation (checked against `workspace / "ckpt.pt"`) while the
    checkpoint was actually written wherever the worker process
    happened to be running from. **Fixed**: this function now RETURNS
    the validated, resolved, absolute path, and every call site uses
    EXACTLY that return value for the actual filesystem operation --
    never the caller's original string again.

    Also now rejects (AUDIT-077 Phase 1, item 5) if the resolved target
    itself, or ANY directory between it and the workspace root, is
    already a symlink at validation time -- closing the straightforward
    "pre-planted symlink" attack. **Explicitly, honestly NOT claimed**:
    this is a validate-then-use check, not a directory-descriptor-
    relative (`openat`-style) operation -- a determined local attacker
    with write access to the workspace's parent directories could still
    swap a component to a symlink in the narrow window between this
    check and the LATER, separate `open()` calls
    `save_resumable_checkpoint()`/`restore_resumable_checkpoint()`
    perform.

    **Investigated and independently verified** (not merely assumed):
    for the SPECIFIC case of the final target NAME being swapped to a
    symlink in that window, `save_resumable_checkpoint()`'s own
    pre-existing atomic-write discipline (`tempfile.mkstemp()` +
    `os.replace()`) INCIDENTALLY defeats it -- POSIX `rename()`/
    `os.replace()` unlinks and replaces whatever directory entry
    currently sits at the destination name rather than following it to
    write through to its target, so a symlink planted there gets
    replaced, not followed.
    `tests/test_genesis_isolated_worker.py::
    test_audit077_destination_substitution_after_validation_is_incidentally_defeated_by_atomic_rename`
    demonstrates this directly. This is an emergent property of the
    pre-existing atomic-publish pattern, not a purpose-built defense
    this phase added, and it does NOT cover every possible substitution
    shape (e.g. a parent-directory component swapped instead of the
    final name, or a substitution landing during the temp file's own
    write rather than at the final rename) -- those remain honestly
    undemonstrated, not claimed closed. Eliminating the remaining
    window with certainty would require extending `resumable_checkpoint
    .py`'s own API to accept a directory file descriptor and a confined
    relative name, threading `os.open(..., dir_fd=...)` through every
    one of its internal atomic-write/read calls -- a genuine, recorded
    future improvement, deliberately out of scope for this phase's
    smallest-necessary-correction mandate. This function and its
    callers never describe themselves as race-proof."""
    if cfg.checkpoint_workspace_dir is None:
        raise CheckpointWorkspaceViolationError(
            "this worker was started with no checkpoint_workspace_dir configured -- "
            "save_checkpoint/restore_checkpoint are refused entirely, not merely unrestricted"
        )
    workspace = Path(cfg.checkpoint_workspace_dir).resolve()
    resolved = (workspace / requested_path).resolve() if not Path(requested_path).is_absolute() else Path(requested_path).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise CheckpointWorkspaceViolationError(
            f"requested checkpoint path {requested_path!r} resolves to {resolved}, which is outside this "
            f"worker's own authorized checkpoint workspace {workspace} -- refusing to read or write it"
        ) from None

    if resolved.is_symlink():
        raise CheckpointWorkspaceViolationError(f"refusing to use {resolved} -- it is a symlink, not a regular file")
    for parent in resolved.parents:
        if parent == workspace:
            break
        if parent.is_symlink():
            raise CheckpointWorkspaceViolationError(f"refusing to use {resolved} -- an intermediate directory {parent} is a symlink")

    return resolved


def _worker_config_fingerprint(cfg: "WorkerStartupConfig") -> str:
    """AUDIT-076 Phase 3: computed from THIS worker's own, already-
    verified startup config -- never accepted from the client payload.
    A client can no longer manufacture the expected value its own
    checkpoint is verified against."""
    return compute_config_fingerprint(cfg.model_cfg, cfg.step_cfg)


def _worker_dataset_identity(cfg: "WorkerStartupConfig") -> DatasetIdentity:
    """Same posture as `_worker_config_fingerprint()`, for dataset
    identity -- derived from the run's own validated identity fields,
    never from the client's payload."""
    return DatasetIdentity(
        dataset_manifest_id=cfg.dataset_manifest_ids[0],
        dataset_content_digest=cfg.dataset_digest,
        tokenizer_digest=cfg.tokenizer_digest,
    )


def _read_revoked_ids(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        # A revocation list this worker cannot read or parse is treated
        # as "everything is revoked" -- fail closed, never a silent
        # "assume nothing is revoked" on a read error.
        return ["__UNREADABLE_REVOCATION_LIST__"]


def _verify_socket_dir_isolation(sock_dir: Path) -> None:
    st = sock_dir.stat()
    if st.st_uid != os.getuid():
        raise IsolationPropertiesUnavailableError(
            f"socket directory {sock_dir} is not owned by this process's own uid ({os.getuid()}) -- refusing to bind"
        )
    if st.st_mode & 0o077:
        raise IsolationPropertiesUnavailableError(
            f"socket directory {sock_dir} is accessible to group or other (mode {oct(st.st_mode)}) -- refusing to bind"
        )


def _worker_main(cfg: WorkerStartupConfig, ready_evt, error_queue, status_queue) -> None:
    expected_peer_uid = os.getuid()  # captured BEFORE any uid drop -- this is who is allowed to drive this worker
    try:
        sock_path = Path(cfg.sock_path)
        _verify_socket_dir_isolation(sock_path.parent)

        if cfg.orca_home_override is not None:
            # Redirects where the anti-replay/rollback ledgers this
            # worker's own authorization and checkpoint calls use live --
            # NOT a security weakening (nothing is bypassed), just a
            # relocation. `orca.config`'s own ORCA_HOME-dependent paths
            # that matter here (the native-pretraining replay guard, the
            # checkpoint anti-rollback ledger) are deliberately looked up
            # LAZILY, at call time, inside this same process, for exactly
            # this purpose.
            import orca.config as _orca_config_mod
            _orca_config_mod.ORCA_HOME = Path(cfg.orca_home_override)

        if cfg.test_only_bypass_founder_ledger:
            # AUDIT-075: a named, misuse-resistant, test-only override --
            # the SAME honesty pattern as `ExecutionCapability.for_
            # unchecked_synthetic_test()` (see learning_step.py): requires
            # `pytest` to be importable in THIS process (a real production
            # deployment does not ship pytest), and is the only way this
            # worker will ever treat the founder-acceptance ledger as
            # satisfied without it actually being so. This does not
            # change what `execute_authorized_training_step()` itself
            # checks on every step -- only the one-time, today-always-
            # failing founder-ledger gate this codebase's own real
            # ledger is intentionally still empty for (see orchestration.py's
            # own module docstring).
            try:
                import pytest as _pytest_probe  # noqa: F401
            except ImportError as e:
                raise IsolationPropertiesUnavailableError(
                    "test_only_bypass_founder_ledger was requested but 'pytest' is not importable in this "
                    "process -- refusing to bypass the founder-acceptance ledger check outside a test context"
                ) from e
            import orca.genesis.governance.authorization as _gov_mod
            import orca.genesis.training.orchestration as _orch_mod
            _gov_mod.check_founder_acceptance_ledger = lambda repo_root, **_: []
            _orch_mod.check_founder_acceptance_ledger = lambda repo_root, **_: []
            if cfg.test_only_pinned_registry_sha256:
                _gov_mod.PINNED_REGISTRY_SHA256 = cfg.test_only_pinned_registry_sha256

        if cfg.drop_to_uid is not None:
            if os.getuid() != 0:
                raise IsolationPropertiesUnavailableError(
                    "drop_to_uid was requested but this process is not running as root -- refusing to start "
                    "under weaker isolation (the original uid) than what was requested"
                )
            if cfg.drop_to_gid is not None:
                os.setgid(cfg.drop_to_gid)
            os.setuid(cfg.drop_to_uid)

        run = GenesisTrainingRun(
            cfg.run_id, dataset_manifest_ids=cfg.dataset_manifest_ids, environment_class=cfg.environment_class,
            repo_root=cfg.repo_root, revocation_check=lambda auth_id: auth_id in set(_read_revoked_ids(cfg.revoked_ids_path)),
        )
        records = list(cfg.dataset_records)
        if not records or not cfg.dataset_manifest_ids:
            raise IsolationPropertiesUnavailableError(
                "dataset_records and dataset_manifest_ids are required to bind worker identity"
            )
        run.validate(
            dataset_manifest=BoundDatasetRecords(
                manifest_id=cfg.dataset_manifest_ids[0],
                source_content_digest=cfg.dataset_digest,
                expected_records=tuple(records),
            ),
            dataset_records=records,
            model_config_digest=cfg.model_config_digest,
            tokenizer_digest=cfg.tokenizer_digest, authorized_shard_digests=cfg.authorized_shard_digests,
            shard_dir=cfg.shard_dir, reviewed_commit_sha=cfg.reviewed_commit_sha,
            transformation_code_digest=cfg.transformation_code_digest, optimizer_config_digest=cfg.optimizer_config_digest,
        )
        run.request_authorization()
        grant = authorize_native_pretraining(
            repo_root=Path(cfg.repo_root), record=cfg.record, registry=cfg.registry, revoked_ids=_read_revoked_ids(cfg.revoked_ids_path),
            req=cfg.req, revocation_check=lambda auth_id: auth_id in set(_read_revoked_ids(cfg.revoked_ids_path)),
        )
        run.authorize(grant)
        run.start()

        # AUDIT-076 Phase 4: deterministic model initialization. Without
        # this, two separately-spawned worker processes constructed with
        # the SAME model_cfg/step_cfg would still get DIFFERENT random
        # initial weights (a fresh `spawn`ed interpreter has no fixed
        # torch RNG seed of its own) -- undermining the exact restart-
        # equivalence this phase's own test suite verifies. Seeded from
        # `cfg.step_cfg.seed`, the SAME value every other GENESIS
        # synthetic-learning test already uses for this purpose.
        set_deterministic_seed(cfg.step_cfg.seed)
        model = GenesisTransformer(cfg.model_cfg)
        engine = TrainingStepEngine(model, cfg.step_cfg)

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if sock_path.exists():
            sock_path.unlink()
        srv.bind(str(sock_path))
        os.chmod(sock_path, 0o600)
        srv.listen(1)
    except Exception as e:  # noqa: BLE001 -- report back to the controller, never hang it
        error_queue.put(f"{type(e).__name__}: {e}")
        return

    # AUDIT-075: compute and report the HONEST isolation qualification
    # BEFORE serving anything -- never the strongest label by default,
    # never asserted from "this is a separate process" alone.
    peer_check_supported = sys.platform.startswith("linux") and hasattr(socket, "SO_PEERCRED")
    uid_separated = cfg.drop_to_uid is not None and os.getuid() != expected_peer_uid
    if peer_check_supported and uid_separated:
        qualification = PEER_VERIFIED_UID_SEPARATED
    elif peer_check_supported:
        qualification = PEER_VERIFIED_SAME_UID
    else:
        qualification = ISOLATION_NOT_QUALIFIED
    status_queue.put(qualification)

    ready_evt.set()
    last_seq = 0
    seen_nonces: list[str] = []
    stopped = False

    try:
        while not stopped:
            conn, _ = srv.accept()
            try:
                if peer_check_supported:
                    creds = _get_peer_credentials(conn)
                    if creds is None or creds[1] != expected_peer_uid:
                        # A kernel-verified peer uid mismatch (or a
                        # lookup failure where one should have
                        # succeeded) -- reject this connection outright,
                        # before processing any command on it at all.
                        continue
                while True:
                    try:
                        raw = _recv_framed(conn)
                    except (ConnectionError, ValueError, struct.error):
                        break
                    try:
                        msg = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        _send_framed(conn, _canonical({"ok": False, "error": "MALFORMED_REQUEST", "result": None}))
                        continue

                    seq, nonce, command, workload_id, payload = (
                        msg.get("seq"), msg.get("nonce"), msg.get("command"), msg.get("workload_id"), msg.get("payload") or {},
                    )
                    expected_sig = msg.get("hmac")
                    actual_sig = _sign(cfg.auth_token, seq=seq, nonce=nonce, command=command, workload_id=workload_id, payload=payload) if None not in (seq, nonce, command, workload_id) else None
                    if actual_sig is None or not hmac.compare_digest(actual_sig, str(expected_sig)):
                        _send_framed(conn, _canonical({"ok": False, "error": "AUTHENTICATION_FAILED", "result": None}))
                        continue
                    if workload_id != cfg.workload_id:
                        _send_framed(conn, _canonical({"ok": False, "error": "CROSS_WORKLOAD_REQUEST", "result": None}))
                        continue
                    if not isinstance(seq, int) or seq <= last_seq or nonce in seen_nonces:
                        _send_framed(conn, _canonical({"ok": False, "error": "REPLAYED_MESSAGE", "result": None}))
                        continue
                    last_seq = seq
                    seen_nonces.append(nonce)
                    if len(seen_nonces) > _NONCE_CACHE_SIZE:
                        del seen_nonces[: len(seen_nonces) - _NONCE_CACHE_SIZE]

                    if command == "ping":
                        _send_framed(conn, _canonical({"ok": True, "error": None, "result": {"global_step": engine.global_step}}))
                    elif command == "shutdown":
                        _send_framed(conn, _canonical({"ok": True, "error": None, "result": {}}))
                        stopped = True
                        break
                    elif command == "step":
                        try:
                            input_ids = torch.tensor(payload["input_ids"], dtype=torch.long)
                            labels = torch.tensor(payload["labels"], dtype=torch.long)
                            result = execute_authorized_training_step(run, engine, input_ids, labels)
                            _send_framed(conn, _canonical({
                                "ok": True, "error": None,
                                "result": {
                                    "applied": result.applied, "global_step": result.global_step,
                                    "microbatch_loss": result.microbatch_loss, "lr": result.lr,
                                },
                            }))
                        except TrainingNotAuthorizedForExecutionError as e:
                            # AUDIT-075, Mission A: authorization became invalid
                            # WHILE running -- terminate this worker's own process
                            # entirely, not merely refuse this one command.
                            _send_framed(conn, _canonical({"ok": False, "error": f"AUTHORIZATION_DENIED: {e}", "result": None}))
                            stopped = True
                            break
                    elif command == "save_checkpoint":
                        # AUDIT-076 Phase 3: hardened following confirmed
                        # findings against the ORIGINAL version of this
                        # handler -- it trusted the client's OWN claimed
                        # path, dataset_identity, config_fingerprint, and
                        # ledger_run_id outright, and performed NO live
                        # authorization check at all. All four are fixed
                        # here, in the same handler (not a separate patch):
                        # the path must resolve under this worker's own
                        # configured checkpoint_workspace_dir; dataset
                        # identity, config fingerprint, and the ledger run
                        # id are now ALWAYS derived from this worker's own
                        # verified startup config, never taken from the
                        # client's payload (the fields are no longer even
                        # read from it); and a live authorization re-check
                        # (the SAME one `step` already performs) runs
                        # before anything is written to disk -- a revoked
                        # or expired grant now fails this exactly like it
                        # fails `step`, with the same fail-stop behavior.
                        try:
                            confined_path = _enforce_checkpoint_path_confinement(cfg, payload["path"])
                            verify_live_authorization_or_raise(run)
                            ts = TrainingState.capture(
                                step=engine.global_step, epoch=0, dataloader_position=payload["sampler_position"],
                                model=engine.model, optimizer=engine.optimizer,
                            )
                            save_resumable_checkpoint(
                                path=confined_path, training_state=ts, global_step=engine.global_step,
                                microbatch_in_cycle=engine.microbatch_in_cycle, sampler_position=payload["sampler_position"],
                                sampler_seed=payload["sampler_seed"], sampler_num_blocks=payload["sampler_num_blocks"],
                                config_fingerprint=_worker_config_fingerprint(cfg),
                                dataset_identity=_worker_dataset_identity(cfg),
                                integrity_key=bytes.fromhex(payload["integrity_key_hex"]), run_id=cfg.run_id,
                            )
                            _send_framed(conn, _canonical({"ok": True, "error": None, "result": {"global_step": engine.global_step}}))
                        except TrainingNotAuthorizedForExecutionError as e:
                            # Same fail-stop posture as `step`'s own authorization
                            # failure -- this worker's process terminates entirely.
                            _send_framed(conn, _canonical({"ok": False, "error": f"AUTHORIZATION_DENIED: {e}", "result": None}))
                            stopped = True
                            break
                        except Exception as e:  # noqa: BLE001 -- report the failure to the client, never crash the worker over it
                            _send_framed(conn, _canonical({"ok": False, "error": f"CHECKPOINT_SAVE_FAILED: {type(e).__name__}: {e}", "result": None}))
                    elif command == "restore_checkpoint":
                        try:
                            confined_path = _enforce_checkpoint_path_confinement(cfg, payload["path"])
                            verify_live_authorization_or_raise(run)
                            restored = restore_resumable_checkpoint(
                                path=confined_path, expected_config_fingerprint=_worker_config_fingerprint(cfg),
                                expected_dataset_identity=_worker_dataset_identity(cfg),
                                expected_sampler_seed=payload["sampler_seed"], expected_sampler_num_blocks=payload["sampler_num_blocks"],
                                integrity_key=bytes.fromhex(payload["integrity_key_hex"]), run_id=cfg.run_id,
                            )
                            restored.training_state.restore(model=engine.model, optimizer=engine.optimizer)
                            engine.global_step = restored.global_step
                            engine.microbatch_in_cycle = restored.microbatch_in_cycle
                            _send_framed(conn, _canonical({
                                "ok": True, "error": None,
                                "result": {"global_step": restored.global_step, "sampler_position": restored.sampler_position},
                            }))
                        except TrainingNotAuthorizedForExecutionError as e:
                            _send_framed(conn, _canonical({"ok": False, "error": f"AUTHORIZATION_DENIED: {e}", "result": None}))
                            stopped = True
                            break
                        except Exception as e:  # noqa: BLE001
                            _send_framed(conn, _canonical({"ok": False, "error": f"CHECKPOINT_RESTORE_FAILED: {type(e).__name__}: {e}", "result": None}))
                    else:
                        _send_framed(conn, _canonical({"ok": False, "error": "UNKNOWN_COMMAND", "result": None}))
            finally:
                conn.close()
    finally:
        srv.close()
        try:
            sock_path.unlink()
        except OSError:
            pass


class IsolatedWorkerClient:
    """What an orchestrating caller actually gets: a thin socket client
    with NO reference to the model, optimizer, engine, or any
    capability token -- those exist only inside the worker's own
    process. Every method sends one signed, sequenced, nonced request
    and waits for one framed response."""

    def __init__(self, sock_path: str, auth_token: bytes, workload_id: str):
        self._sock_path = sock_path
        self._token = auth_token
        self._workload_id = workload_id
        self._seq = 0
        self._sock: socket.socket | None = None

    def connect(self, timeout: float = 5.0) -> None:
        sock_path = Path(self._sock_path)
        st = sock_path.stat()
        if st.st_uid != os.getuid():
            raise IsolationPropertiesUnavailableError(f"refusing to connect to {sock_path} -- not owned by this process's own uid")
        if st.st_mode & 0o077:
            raise IsolationPropertiesUnavailableError(f"refusing to connect to {sock_path} -- accessible to group or other")
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        self._sock.connect(self._sock_path)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _request(self, command: str, payload: dict | None = None) -> dict:
        assert self._sock is not None, "connect() must be called first"
        self._seq += 1
        nonce = secrets.token_hex(16)
        payload = payload or {}
        sig = _sign(self._token, seq=self._seq, nonce=nonce, command=command, workload_id=self._workload_id, payload=payload)
        msg = {"seq": self._seq, "nonce": nonce, "command": command, "workload_id": self._workload_id, "payload": payload, "hmac": sig}
        _send_framed(self._sock, _canonical(msg))
        raw = _recv_framed(self._sock)
        return json.loads(raw.decode("utf-8"))

    def ping(self) -> dict:
        return self._request("ping")

    def step(self, input_ids: "list | torch.Tensor", labels: "list | torch.Tensor") -> dict:
        if isinstance(input_ids, torch.Tensor):
            input_ids = input_ids.tolist()
        if isinstance(labels, torch.Tensor):
            labels = labels.tolist()
        return self._request("step", {"input_ids": input_ids, "labels": labels})

    def shutdown(self) -> dict:
        return self._request("shutdown")

    def save_checkpoint(self, *, path: str, integrity_key: bytes, sampler_position: int, sampler_seed: int, sampler_num_blocks: int) -> dict:
        """AUDIT-076, Mission 4 / Phase 3: commands the worker to capture
        and save ITS OWN, never-exposed model/optimizer/engine state to
        `path`, using the real `save_resumable_checkpoint()`. No tensor
        crosses the wire -- only this plain request and an ok/error
        response. `path` must resolve under the worker's own configured
        checkpoint workspace. Deliberately NO `config_fingerprint`,
        `dataset_identity`, or `ledger_run_id` parameter here any more --
        AUDIT-076 Phase 3 found the worker was trusting a client-supplied
        value for all three, letting a client manufacture the very
        values its own checkpoint would later be verified against; the
        worker now always derives them itself from its own verified
        startup config, and no longer reads them from this request at all."""
        return self._request("save_checkpoint", {
            "path": path, "integrity_key_hex": integrity_key.hex(), "sampler_position": sampler_position,
            "sampler_seed": sampler_seed, "sampler_num_blocks": sampler_num_blocks,
        })

    def restore_checkpoint(self, *, path: str, integrity_key: bytes, sampler_seed: int, sampler_num_blocks: int) -> dict:
        """The restart-side counterpart: a FRESH worker (its own fresh
        model/optimizer, constructed the same way any worker start-up
        already builds them) restores exactly that saved state into
        itself before accepting any further `step` commands. Same
        AUDIT-076 Phase 3 posture as `save_checkpoint()` -- no identity-
        bearing parameter here is trusted from the client; see its own
        docstring."""
        return self._request("restore_checkpoint", {
            "path": path, "integrity_key_hex": integrity_key.hex(), "sampler_seed": sampler_seed,
            "sampler_num_blocks": sampler_num_blocks,
        })


class IsolatedTrainingWorker:
    """Controller-side handle: spawns the worker as a genuinely separate
    OS process (`multiprocessing`'s `spawn` start method -- a fresh
    interpreter, not a fork, see `start()`'s own comment for why), waits
    for it to report ready (or to fail closed before ever touching
    model/grant state), and hands back a `client()` with no access to
    anything inside that process."""

    def __init__(self, cfg: WorkerStartupConfig):
        self._cfg = cfg
        self._proc = None
        self._ready_evt: multiprocessing.synchronize.Event | None = None
        self._error_queue: multiprocessing.queues.Queue | None = None
        self._status_queue: multiprocessing.queues.Queue | None = None
        self.isolation_qualification: str = ISOLATION_NOT_QUALIFIED

    def start(self, timeout: float = 15.0) -> None:
        # AUDIT-075: deliberately "spawn", not "fork". A forked child
        # copies the parent's ENTIRE memory image, including however
        # many background threads PyTorch's own runtime (MKL/OpenMP/
        # whatever BLAS backend) has already started in the controller
        # process by the time this is called -- forking a multi-threaded
        # process is a well-known PyTorch hazard (the child can inherit
        # a torn thread-pool state and crash or deadlock on its first
        # real tensor op, independently reproduced while building this
        # module: it passed in isolation but crashed when spawned from a
        # test session that had already exercised torch heavily
        # beforehand). "spawn" starts a genuinely fresh interpreter that
        # re-imports everything from scratch -- slower, but it is both
        # the more robust choice AND, if anything, a STRONGER match for
        # this module's own isolation claim: the worker never inherits
        # ANY live state from the controller's process at all, copy-on-
        # write or otherwise.
        ctx = multiprocessing.get_context("spawn")
        self._ready_evt = ctx.Event()
        self._error_queue = ctx.Queue()
        self._status_queue = ctx.Queue()
        self._proc = ctx.Process(
            target=_worker_main, args=(self._cfg, self._ready_evt, self._error_queue, self._status_queue), daemon=True,
        )
        self._proc.start()
        became_ready = self._ready_evt.wait(timeout)
        if not became_ready:
            reason = self._error_queue.get_nowait() if not self._error_queue.empty() else "worker did not become ready in time (no error reported)"
            self.stop()
            raise WorkerStartupError(reason)
        try:
            self.isolation_qualification = self._status_queue.get(timeout=5.0)
        except Exception:  # noqa: BLE001 -- never crash start() over the status report itself; default stays the most conservative label
            self.isolation_qualification = ISOLATION_NOT_QUALIFIED

    def client(self) -> IsolatedWorkerClient:
        return IsolatedWorkerClient(self._cfg.sock_path, self._cfg.auth_token, self._cfg.workload_id)

    def stop(self, timeout: float = 5.0) -> None:
        if self._proc is not None and self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout)

    def join(self, timeout: float | None = None) -> None:
        if self._proc is not None:
            self._proc.join(timeout)

    @property
    def exitcode(self) -> int | None:
        return self._proc.exitcode if self._proc is not None else None

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()
