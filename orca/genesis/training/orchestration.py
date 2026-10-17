"""
GENESIS Foundation Sprint 2, Workstream C: training-orchestration state
machine.

Models the full lifecycle a real GENESIS native-pretraining run would go
through -- PLANNED, VALIDATED, AWAITING_AUTHORIZATION, AUTHORIZED, RUNNING,
PAUSED, RECOVERING, COMPLETED, FAILED, REJECTED -- with fail-closed
transitions and real, independently-checkable evidence at every step. **No
training loop is executed by this module, and no gradient/optimizer step
ever runs here.** `record_step()` exists so a REAL training loop (which
does not exist yet anywhere in this codebase) could report genuine
progress; nothing in this module itself ever calls it.

## Independent-audit continuation (2026-10-16) -- C-01 through C-06

A founder-directed code review of the first version of this module
(commit `330f1b8`) independently reproduced six concerns before any fix was
applied here. Each is addressed below; this section records what was found
and how it was closed, so the fix is auditable against the original
finding, not just asserted.

- **C-01 (wrong-workload authorization)**: REPRODUCED. A legitimately
  issued `TrainingGrant` for an entirely unrelated, generic LoRA/QLoRA
  config transitioned a synthetic GENESIS run straight to `AUTHORIZED` --
  `authorize()` previously checked only that the grant was real
  (`isinstance` + `verify_integrity()`), never that it was bound to THIS
  workload. Fixed via `_expected_grant_scope()` +
  `TrainingGrant.assert_valid_for()` (see below) -- a `cfg_fingerprint`
  mismatch now raises `TrainingNotAuthorized` for any grant not computed
  from GENESIS's own declared scope. No conversion shortcut from LoRA
  authorization is invented: since no code anywhere produces a grant whose
  fingerprint matches a real GENESIS scope today, EVERY currently-issuable
  grant is now correctly rejected -- GENESIS authorization remains
  `BLOCKED`, exactly as instructed, not worked around.
- **C-02 (authorization checks during resume)**: REPRODUCED. `resume()`
  performed no grant re-check at all. Fixed: `resume()` now runs the same
  re-verification as `start()`/`recovered()` (HMAC integrity, expiry, and
  an optional live-revocation hook -- see `_reverify_grant_or_transition()`).
  Workload-scope binding (C-01's fingerprint check) is deliberately NOT
  re-run at every resume-capable transition -- it is a property of the
  one-time decision to authorize this run, checked exhaustively in
  `authorize()`, and cannot legitimately change afterward without this
  module itself replacing the grant, which never happens; re-deriving it
  on every transition would be redundant, not additional safety.
- **C-03 (execution-evidence authenticity)**: addressed by construction.
  `record_step()`'s output is now explicitly typed `ExecutionEvent` with a
  fixed `classification="REPORTED_EXECUTION_PROGRESS"` field -- never
  described, anywhere in this module's naming or docstrings, as
  independently verified proof that an optimizer step actually ran.
  `source_identity` and `run_id` are required and checked; a `sequence`
  counter enforces strict event ordering separately from the caller-chosen
  `step` number; `max_events` bounds the evidence list.
- **C-04 (evaluator-approval authenticity)**: `EvaluatorApprovalClaim`
  (renamed from `EvaluatorApproval`) carries a fixed
  `is_independently_authenticated=False` field -- this module has no
  evaluator-identity PKI, so `evaluator_identity` is a self-reported label,
  never a verified identity. What IS independently checked:
  `checkpoint_manifest_sha256` must equal this run's own
  `CompletionEvidence.checkpoint_manifest_sha256` exactly, so an approval
  claim cannot be silently misattributed to a different checkpoint.
- **C-05 (durable replay/recovery)**: `_consumed_authorization_ids` is
  explicitly documented, and now has a dedicated, documented
  `reset_in_process_replay_guard_for_new_process()` classmethod, as an
  IN-PROCESS-ONLY safety net. No second, conflicting on-disk ledger is
  created here -- the authoritative, cross-process defense against reusing
  one authorization across more real runs than it permits remains
  `orca.train.authorization`'s own on-disk run-slot ledger
  (`_claim_run_slot`/`_authorized_event_count`), which this module
  integrates with by relying on, not duplicating.
- **C-06 (state-transition consistency)**: REPRODUCED. `reject()`'s
  docstring/precondition claimed "any non-terminal state", but
  `_ALLOWED_TRANSITIONS` only permits `-> REJECTED` from `PLANNED`,
  `VALIDATED`, `AWAITING_AUTHORIZATION`, and `AUTHORIZED` -- calling
  `reject()` from `RUNNING`/`PAUSED`/`RECOVERING` raised
  `InvalidTransitionError` despite the method's own stated contract. Fixed
  by narrowing `reject()`'s precondition to match the actual transition
  graph (`_REJECTABLE_STATES`) -- the graph was correct; the method's
  stated contract was wrong, so the method was corrected, not the graph,
  and no test was loosened to paper over the mismatch.

## The authorization boundary (Native-Authorization-Convergence Mission 2)

GENESIS Foundation Sprint 2 Mission 1A built a `TrainingRunRecord`: a plain
JSON file with `run_id`/`checkpoint_sha256`/`authorized` fields
(`orca/genesis/model/eval_adapter.py`). An independent audit correctly
challenged whether a self-authored JSON boolean can ever qualify as real
founder authorization -- it cannot, and this module does not repeat that
design.

**Original design (C-01 through C-06, commits `330f1b8`/`ff9175f`)**:
this module required a real `orca.train.authorization.TrainingGrant`
(ORNEUR's existing LoRA/QLoRA fine-tune authorization gate) plus a
`cfg_fingerprint` check against a synthetic GENESIS-shaped
`TrainingConfig` scope, since no GENESIS-native authorization type existed
yet. That was a real mitigation against C-01 (wrong-workload
authorization), but still fundamentally asked a LoRA-shaped signing
domain to represent a different kind of request -- honestly documented
at the time as `BLOCKED`, not worked around.

**Mission 2 replaces that entirely.** Workstream F
(`orca.genesis.governance.authorization`) now provides a REAL,
GENESIS-native authorization type: `NativePretrainingGrant` -- a sealed,
HMAC-tamper-evident object, issued only by `authorize_native_pretraining()`
from an Ed25519-signed record under its OWN signing domain (so a LoRA
`TrainingGrant` can never verify as one of these, and vice versa -- this
is now a STRUCTURAL type distinction, not merely a fingerprint check),
carrying every field this module needs to bind exactly: `run_id`,
`model_config_digest`, `tokenizer_digest`, `dataset_manifest_id`,
`dataset_content_digest`, `authorized_shard_digests`, `environment_class`.

**`authorize()` below requires exactly a `NativePretrainingGrant` instance
that passes `verify_integrity()` and whose every one of those fields
EXACTLY matches this run's own declared identity** (set by `validate()`,
which now additionally requires `model_config_digest`, `tokenizer_digest`,
and `authorized_shard_digests`, not only `dataset_digest`) -- not a
boolean, not a string, not a dict, not a legacy `TrainingGrant`, and not a
`NativePretrainingGrant` issued for a different run, model, tokenizer,
dataset, shard set, or environment. Once authorized, this binding is
FROZEN (`_AuthorizedIdentitySnapshot`): every resume-capable transition
(`start()`/`resume()`/`recovered()`) re-derives the run's current identity
and raises `AuthorizedIdentityChangedError` if it no longer matches the
snapshot taken at `authorize()` time -- closing the "authorized identity
silently mutated after the fact" gap, which nothing in the original
design actually prevented (nothing mutates `self.identity` anywhere in
this module today, but nothing stopped external code from doing so
either).

**Durable, cross-process replay protection**: C-05's original
`_consumed_authorization_ids` was explicitly documented as an
IN-PROCESS-ONLY safety net. This module now ALSO atomically claims each
`authorization_id` on disk (`_claim_native_pretraining_authorization()`,
mirroring `orca.train.authorization._claim_run_slot()`'s own
`O_CREAT | O_EXCL` discipline, under `ORCA_HOME` -- never in the repo),
so a second OS process that never shared this process's memory CANNOT
reuse an authorization_id a prior process already consumed, closing the
exact gap `ReplayedAuthorizationError`'s prior docstring named as
unresolved.

**Execution-boundary acceptance gate**: `authorize_native_pretraining()`
itself requires the project-wide founder-acceptance ledger
(`scripts.acceptance.acceptance_engine`) to show R65/G1/AUTH-1/FINAL-1
accepted before issuing a grant at all. This module's `start()` ADDS a
SEPARATE, stricter gate at the moment of actual execution: it requires
FINAL-2 and EXEC-1 ALSO accepted (the authoritative
FINAL-1 -> FINAL-2 -> EXEC-1 dependency chain in
`docs/orneur/acceptance/register_graph.json`), via the SAME
`check_founder_acceptance_ledger()` Workstream F already built (reused,
not reimplemented). **The real, committed founder-acceptance ledger is
empty and the real authority registry is empty -- both checks deny every
real call today, by construction, and this module changes neither file.**

**Revocation is now MANDATORY, not optional**: `revocation_check` is a
REQUIRED constructor argument (previously optional) -- matching
`orca.genesis.governance.authorization.assert_execution_permitted()`'s
own mandatory-revocation contract, which this module now calls directly
at every resume-capable transition rather than re-implementing the
expiry/revocation logic locally. A truthy (not merely `True`) return is
treated as revoked, and a raising/unavailable check denies, never passes
silently.

**Dataset preflight integration (M2-03)**: `validate()` accepts an
optional `dataset_manifest` (any object satisfying
`orca.genesis.governance.authorization.DatasetManifestLike`'s
Protocol -- duck-typed, so this module imports nothing from Workstream A
and gains no hard dependency on it) together with the real
`dataset_records` to check it against, and calls
`dataset_manifest.verify_against_records()` itself before deriving
`dataset_digest` from the VERIFIED object -- not from a bare,
merely-well-formed caller-supplied digest string.

## M2-04: adversarial qualification and known, documented limitations

The following were independently qualified (not merely inspected) as
part of the Native-Authorization-Convergence Mission 2 source-review
response:

- **Durable replay under genuine concurrency**: proven atomic with a
  20-thread barrier-synchronized stress test
  (`test_concurrent_claims_of_the_same_authorization_id_have_exactly_one_winner`),
  not merely inferred from `O_CREAT | O_EXCL`'s documented semantics.
- **Crash consistency -- a REAL, acknowledged, UNRESOLVED residual**: if
  a process crashes after `_claim_native_pretraining_authorization()`
  succeeds but before `authorize()` finishes transitioning the run to
  `AUTHORIZED`, the authorization_id is durably, permanently claimed,
  yet no run ever actually reached `AUTHORIZED` with it -- there is no
  automatic recovery path. This mirrors
  `orca.train.authorization._claim_run_slot()`'s own documented
  trade-off exactly ("a failed or cancelled run still consumes its
  slot... a local operator who deletes this directory can re-run").
  Solving this in general would require a two-phase-commit-style
  transaction log this module does not have; building one is
  out-of-scope, separately-authorizable future work, not something this
  fix silently papers over.
- **Trusted revocation-service boundary**: an unavailable, erroring, or
  loosely-typed (truthy-but-not-`True`) revocation result is always
  treated as a denial -- qualified directly, not merely asserted.
- **P1-03: marker deletion and rollback** -- the same residual
  `_claim_run_slot()` already documents applies identically here, by
  construction (same `O_CREAT | O_EXCL` discipline): a local operator
  with filesystem access to `ORCA_HOME` who deletes a `.claimed` marker
  file CAN cause that `authorization_id` to be claimable again. This is
  not a defect introduced by this fix -- advisory, filesystem-based
  replay guards are inherently resettable by anyone with write access to
  the guard's own storage; the actual security boundary is WHO has
  write access to `ORCA_HOME`, not the guard mechanism itself. Marker
  files are created `0o600` (owner-only), consistent with every other
  sensitive artifact this codebase writes under `ORCA_HOME`.
- **P1-03: cross-host replay is explicitly NOT covered** -- the durable
  claim lives on ONE host's local filesystem; two processes on
  DIFFERENT hosts, each with their own `ORCA_HOME`, cannot detect each
  other's consumption of the same `authorization_id` at all. Closing
  this would require shared/networked durable storage (e.g. a database
  or object store both hosts can reach), which is infrastructure this
  module does not have and was not asked to build -- documented here as
  an explicit, out-of-scope limitation rather than an implied guarantee.
- **Advisory-lock boundary** (inherited from the Mission 1 checkpoint
  fix, restated here for completeness): `flock()`-based locking is
  advisory, not mandatory, and protects only against OTHER code that
  cooperates with the same lock discipline -- it is not, and cannot be,
  a defense against a caller with raw filesystem access who bypasses
  this module's own functions entirely.

## Antigravity Audit #71 remediation -- AUDIT-P0-01

Independently reproduced: this module's prior identity-drift check
compared only IN-MEMORY attributes (`self.identity.authorized_shard_digests`,
a caller-supplied, sorted multiset of digest strings recorded once at
`validate()` time). The actual shard FILES on disk were never re-read or
re-hashed at `start()`, `resume()`, or `recovered()` -- a shard file
modified, substituted, or swapped with another authorized shard's
content AFTER `authorize()` went completely undetected; `run.start()`
and `run.resume()` transitioned to `RUNNING` cleanly regardless.

Fixed by binding the run's identity to the REAL, on-disk shard files
from the moment `validate()` is called: `validate()` now requires a
`shard_dir`, independently computes each `shard-*.jsonl` file's actual
SHA-256 digest (`_compute_authorized_shard_file_digests()`, deliberately
re-implemented here rather than imported from
`orca.genesis.data.pipeline.compute_shard_digests` -- this module
retains no hard dependency on Workstream A, the same duck-typing
discipline `DatasetManifestLike` already established for dataset-
manifest preflight, M2-03), and REJECTS at validation time if the
caller's claimed `authorized_shard_digests` do not match those real,
independently-computed digests. This full `(filename, digest)` mapping
-- not merely a sorted multiset of digest strings -- is then part of
`_current_identity_snapshot()`, which `_reverify_grant_or_transition()`
already (C-02/Mission 2) re-derives FRESH from current state and
compares against the frozen `_AuthorizedIdentitySnapshot` at EVERY
resume-capable transition (`start()`, `resume()`, `recovered()`): since
the snapshot is recomputed by re-reading and re-hashing the actual files
on disk every time (never cached, never trusted from a prior call), any
post-authorization modification, substitution, deletion, or swap is
caught by the SAME, already-adversarially-tested
`AuthorizedIdentityChangedError` path identity-drift detection already
used for every other bound field -- no new, separately-tested check was
needed. Binding the full filename-to-digest mapping (not only the
digest multiset the signed grant itself carries, which remains a
Workstream F governance-contract concern this fix does not redesign)
additionally closes the "two authorized shard files swapped with each
other" case, which a multiset-only comparison cannot detect since the
set of digest VALUES is unchanged even though the filename-to-content
association is not.

**Verification-to-use race (TOCTOU), honestly scoped**: this check
re-verifies shard bytes at the instant of each state transition into
RUNNING, closing the specific window the audit named (authorize-then-
tamper-then-start/resume). It does NOT, and cannot, guarantee no
modification occurs in the interval between that check returning and
whatever process later actually reads the shard bytes to train --
closing that residual would require the eventual training-loop consumer
itself to read shard files only through this same verification path (or
an equivalent, e.g. re-opening by verified file descriptor rather than
by path), which is not yet buildable: no real GENESIS training loop
exists anywhere in this codebase (native pretraining remains
`NOT_AUTHORIZED`). This is documented here as an explicit, open
architectural requirement for whatever eventually consumes an
AUTHORIZED/RUNNING run's shard set, not an implied guarantee this module
does not provide.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

from orca.genesis.governance.authorization import (
    DatasetManifestLike,
    NativePretrainingGrant,
    NativePretrainingNotAuthorized,
    assert_execution_permitted,
    check_founder_acceptance_ledger,
)
from orca.genesis.model.config import ARCHITECTURE_VERSION
from orca.genesis.training.checkpoint_integrity import (
    CheckpointManifest,
    _manifest_path,
    load_verified_training_state,
)

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Mission 2: the execution-start gate is STRICTER than the grant-issuance
# gate. authorize_native_pretraining() itself already requires
# R65/G1/AUTH-1/FINAL-1; start() additionally requires FINAL-2 and EXEC-1,
# the authoritative dependency chain
# (FINAL-1 -> FINAL-2 -> EXEC-1) recorded in
# docs/orneur/acceptance/register_graph.json. All three are named
# explicitly here (not just "EXEC-1") so a reader can see the whole
# required sequence at the call site, even though acceptance_engine's own
# dependency resolution would also catch a missing prerequisite.
EXECUTION_START_REQUIRED_ACCEPTANCE_ROWS = ("FINAL-1", "FINAL-2", "EXEC-1")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str | None) -> datetime | None:
    """A small, local ISO-8601 parser -- deliberately NOT importing
    `orca.genesis.governance.authorization`'s private `_parse_ts()`. This
    module integrates with that module's PUBLIC authorization contract
    (`NativePretrainingGrant`, `verify_integrity()`,
    `assert_execution_permitted()`), not its private internals."""
    if not isinstance(s, str) or not _TS_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SHA40_HEX = re.compile(r"^[0-9a-f]{40}$")


def _git(root: Path, *args: str) -> tuple[int, str]:
    """Mirrors `orca.train.authorization._git()` exactly -- a timed-out
    or missing git binary fails closed (returncode 127), never silently
    treated as success."""
    import subprocess
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30, check=False)
        return p.returncode, p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def _is_live_ancestor_of_head(repo_root: Path, commit_sha: str) -> bool:
    """M2-01 fix: independently verifies, against the LIVE repository
    state (not a caller-supplied claim), that `commit_sha` is a real
    commit and is an ancestor of the current HEAD -- the same
    `merge-base --is-ancestor` discipline
    `orca.train.authorization._build_request()` already uses for its own
    `reviewed_commit_sha` binding. A caller-supplied SHA that merely
    LOOKS like a commit hash (40 hex characters) but was never actually
    reviewed, or belongs to an unrelated/future history, fails this
    check regardless of what any signed record claims about it."""
    rc, head = _git(repo_root, "rev-parse", "HEAD")
    if rc != 0 or not head:
        return False
    rc2, _ = _git(repo_root, "merge-base", "--is-ancestor", commit_sha, head)
    return rc2 == 0


def _compute_authorized_shard_file_digests(shard_dir: Path) -> tuple[tuple[str, str], ...]:
    """Antigravity Audit #71 (AUDIT-P0-01) fix: real, independently
    re-derivable SHA-256 digests of the ACTUAL `shard-*.jsonl` files
    present in `shard_dir` right now, keyed by filename and returned as a
    sorted tuple of `(filename, digest)` pairs -- never a bare multiset
    of digest values, so two shards swapped with each other (same set of
    digest VALUES, different filename-to-content association) are still
    detected as a change. Deliberately re-implemented here rather than
    imported from `orca.genesis.data.pipeline.compute_shard_digests`
    (functionally identical) -- this module gains no hard dependency on
    Workstream A, exactly the duck-typing discipline `DatasetManifestLike`
    already established for dataset-manifest preflight integration
    (M2-03, see module docstring). Called fresh every time this run's
    current identity snapshot is taken -- never cached -- so a file
    modified after the previous call is always caught."""
    digests: dict[str, str] = {}
    for path in sorted(Path(shard_dir).glob("shard-*.jsonl")):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        digests[path.name] = h.hexdigest()
    return tuple(sorted(digests.items()))


def _native_pretraining_replay_state_dir() -> Path:
    """Lives under the hardened ORNEUR home, never in the repo -- mirrors
    `orca.train.authorization._state_dir()`'s own placement and reasoning.
    Looked up lazily (not a module-level constant captured at import
    time) specifically so tests can isolate it the same way
    `tests/test_training_authorization_gate.py` isolates
    `orca.train.authorization`'s own state dir:
    `monkeypatch.setattr(orca.config, "ORCA_HOME", tmp_path)`."""
    from orca.config import ORCA_HOME, _mkdir_owner_only
    return _mkdir_owner_only(ORCA_HOME / "genesis" / "training" / "native_pretraining_authorizations", parents=True)


def _claim_native_pretraining_authorization(authorization_id: str) -> bool:
    """C-05 durable follow-up (Mission 2): atomically claims
    `authorization_id` as consumed, ON DISK, across process restarts --
    mirrors `orca.train.authorization._claim_run_slot()`'s own
    `O_CREAT | O_EXCL` atomicity (the filesystem, not this process's
    memory, is the source of truth). Returns `True` if THIS call is the
    first ever to claim it; `False` if it was already claimed, by this
    process or an earlier one. A failed or rejected run still consumes
    its claim -- the same documented trade-off `_claim_run_slot()` makes,
    for the same reason (a local operator who deletes this directory can
    manually reset it; that is a documented residual, not a silent
    bypass)."""
    state = _native_pretraining_replay_state_dir()
    try:
        fd = os.open(state / f"{authorization_id}.claimed", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    return True


class RunState(str, Enum):
    PLANNED = "PLANNED"
    VALIDATED = "VALIDATED"
    AWAITING_AUTHORIZATION = "AWAITING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


TERMINAL_STATES = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.REJECTED})

# The complete, fail-closed transition graph. Any (from, to) pair not listed
# here is forbidden -- including skipping states (PLANNED -> RUNNING),
# reversing a terminal state, or re-entering AWAITING_AUTHORIZATION/AUTHORIZED
# once a run has moved past them. C-06: this graph is the single source of
# truth; every method's precondition is reconciled against it, not the
# other way around.
_ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PLANNED: frozenset({RunState.VALIDATED, RunState.REJECTED}),
    RunState.VALIDATED: frozenset({RunState.AWAITING_AUTHORIZATION, RunState.REJECTED}),
    RunState.AWAITING_AUTHORIZATION: frozenset({RunState.AUTHORIZED, RunState.REJECTED}),
    RunState.AUTHORIZED: frozenset({RunState.RUNNING, RunState.REJECTED}),
    RunState.RUNNING: frozenset({RunState.PAUSED, RunState.COMPLETED, RunState.FAILED}),
    RunState.PAUSED: frozenset({RunState.RUNNING, RunState.RECOVERING, RunState.FAILED}),
    RunState.RECOVERING: frozenset({RunState.RUNNING, RunState.FAILED}),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.REJECTED: frozenset(),
}

# C-06 fix: reject() is valid only from states the graph actually permits
# a REJECTED transition from. Derived directly from _ALLOWED_TRANSITIONS
# (never hand-duplicated) so the two can never silently drift apart again.
_REJECTABLE_STATES = frozenset(s for s, targets in _ALLOWED_TRANSITIONS.items() if RunState.REJECTED in targets)


class InvalidTransitionError(Exception):
    """Raised for any transition not present in `_ALLOWED_TRANSITIONS`,
    including attempts to skip states, restart a terminal run, or re-enter
    an already-passed authorization step."""


class ReplayedAuthorizationError(Exception):
    """Raised when a `NativePretrainingGrant` whose `authorization_id` has
    already been consumed -- by a different run, in THIS process OR A
    PRIOR one -- is presented again. Mission 2: now backed by a DURABLE,
    on-disk claim (`_claim_native_pretraining_authorization()`), not only
    an in-process set -- see that function's own docstring."""


class StaleAuthorizationError(Exception):
    """Raised when a grant's own `expires_at` has passed, or its live
    revocation status has changed, at the moment `start()`, `resume()`,
    or `recovered()` is called -- re-checked at every one of these
    transitions via `assert_execution_permitted()`, never only trusted
    from whenever `authorize()` ran."""


class ForgedCompletionError(Exception):
    """Raised when `complete()` is given a checkpoint path that does not
    actually pass `load_verified_training_state()`'s full trust boundary,
    or whose verified step does not match this run's own recorded
    execution evidence -- a claimed completion is never accepted on the
    caller's word alone."""


class AuthorizedIdentityChangedError(Exception):
    """Mission 2: raised when the run's current identity (model config
    digest, tokenizer digest, dataset manifest/content digest, authorized
    shard digests, run id, or environment class) no longer matches the
    EXACT identity snapshot captured at the moment `authorize()` granted
    this run its authorization. An authorization is a decision about one
    specific, fully-identified workload -- it must never silently keep
    applying to a run whose identity has since changed, even though
    nothing in this module itself ever mutates `self.identity` after
    `validate()`."""


class ExecutionAcceptanceIncompleteError(Exception):
    """Raised by `start()` when the project-wide founder-acceptance
    ledger does not (yet) show FINAL-1, FINAL-2, AND EXEC-1 all accepted
    -- a stricter, execution-time-specific gate layered on top of
    `authorize_native_pretraining()`'s own grant-issuance-time
    requirement (R65/G1/AUTH-1/FINAL-1). The real ledger is empty; this
    always raises today."""


@dataclass
class RunIdentity:
    """The FULL workload identity a `NativePretrainingGrant` must bind to
    exactly -- every field Mission 2 requires: run id, model architecture
    + config, tokenizer, dataset manifest + content, the exact authorized
    shard set. Set in one place (`validate()`); immutable in spirit after
    `authorize()` via `_AuthorizedIdentitySnapshot` (this dataclass itself
    stays a plain, mutable dataclass -- nothing in this module needs to
    mutate it after `validate()`, but the snapshot, not this object's own
    mutability, is what `_reverify_grant_or_transition()` actually
    trusts)."""
    run_id: str
    model_architecture_version: str
    dataset_manifest_ids: tuple[str, ...]
    dataset_digest: str | None = None  # set by validate(); None beforehand
    model_config_digest: str | None = None  # set by validate(); None beforehand
    tokenizer_digest: str | None = None  # set by validate(); None beforehand
    authorized_shard_digests: tuple[str, ...] | None = None  # set by validate(); None beforehand
    shard_dir: Path | None = None  # Audit #71 P0-01: set by validate(); the real directory authorized_shard_digests was verified against
    # M2-01: the remaining signed-authorization fields a NativePretrainingGrant
    # now carries (PR #69) -- bound here too so authorize() can check ALL of
    # them, not only the original six.
    reviewed_commit_sha: str | None = None  # set by validate(); None beforehand
    transformation_code_digest: str | None = None  # set by validate(); None beforehand
    optimizer_config_digest: str | None = None  # set by validate(); None beforehand
    gpu_requested: bool = False
    requested_spend_usd: float = 0.0
    requested_wall_clock_minutes: int = 1


@dataclass(frozen=True)
class _AuthorizedIdentitySnapshot:
    """Mission 2: a frozen copy of every identity field bound at the
    moment `authorize()` succeeded. Compared against a freshly re-derived
    snapshot at every resume-capable transition
    (`_reverify_grant_or_transition()`) -- any field that no longer
    matches raises `AuthorizedIdentityChangedError`."""
    run_id: str
    model_architecture_version: str
    dataset_manifest_id: str
    dataset_digest: str
    model_config_digest: str
    tokenizer_digest: str
    authorized_shard_digests: tuple[str, ...]
    authorized_shard_file_digests: tuple[tuple[str, str], ...]  # Audit #71 P0-01: live (filename, digest) pairs, recomputed from disk every snapshot
    environment_class: str
    reviewed_commit_sha: str
    transformation_code_digest: str
    optimizer_config_digest: str
    gpu_requested: bool
    requested_spend_usd: float
    requested_wall_clock_minutes: int


@dataclass
class ExecutionEvent:
    """C-03: a single SELF-REPORTED progress event. `classification` is
    always `"REPORTED_EXECUTION_PROGRESS"` -- fixed, non-configurable --
    because this module has no mechanism to independently verify that an
    optimizer step actually ran. These are claims from whatever called
    `record_step()`, never proof. `source_identity` names the reporting
    process/caller (itself unauthenticated -- a real deployment would bind
    this to a signed or otherwise verifiable execution identity, which
    does not exist yet); `run_id` must match the run it is reported
    against; `sequence` is this module's own strictly-increasing event
    counter, kept separate from the caller-chosen `step` number so event
    ORDER is enforced independently of what the caller claims `step` to
    mean."""
    source_identity: str
    run_id: str
    step: int
    sequence: int
    reported_at: str
    classification: str = "REPORTED_EXECUTION_PROGRESS"


@dataclass
class ExecutionEvidence:
    """Actual execution evidence -- distinct from permission to execute
    (the `TrainingGrant`) and from completion evidence. `events` is
    append-only (nothing in this module ever removes or edits a past
    entry); `max_events` is an explicit evidence-volume limit (C-03), so
    an unbounded or malicious caller cannot grow this without limit."""
    events: list[ExecutionEvent] = field(default_factory=list)
    max_events: int = 100_000

    @property
    def steps_recorded(self) -> int:
        return self.events[-1].step if self.events else 0

    @property
    def last_recorded_at(self) -> str | None:
        return self.events[-1].reported_at if self.events else None


@dataclass(frozen=True)
class CompletionEvidence:
    """Completion evidence -- distinct from execution evidence (steps
    happened) and from checkpoint identity verification (the checkpoint is
    real and hash-verified); `complete()` is the only code path that
    constructs this, and only after independently re-verifying both."""
    checkpoint_path: str
    checkpoint_manifest_sha256: str
    final_step: int
    completed_at: str


@dataclass(frozen=True)
class EvaluatorApprovalClaim:
    """C-04: an explicitly UNAUTHENTICATED claim of evaluator approval.
    This module has no evaluator-identity PKI or signature-verification
    mechanism, so `evaluator_identity` is a self-reported label, never a
    cryptographically verified identity -- `is_independently_authenticated`
    is a fixed `False`, not a field a caller can set to claim otherwise.
    What IS independently checked here: `checkpoint_manifest_sha256` must
    equal this run's own completed checkpoint's manifest hash exactly, so
    an approval claim cannot be silently misattributed to a different
    checkpoint (see `record_evaluator_approval()`)."""
    evaluator_identity: str
    approved: bool
    evaluation_report_sha256: str
    checkpoint_manifest_sha256: str
    approved_at: str
    is_independently_authenticated: bool = False


class GenesisTrainingRun:
    """One run's state machine instance. Every transition method either
    succeeds and advances `state`, or raises without changing `state`
    beyond a single, intentional failure transition (e.g. to `REJECTED`)
    -- there is no partial-transition state."""

    def __init__(
        self, run_id: str, *, dataset_manifest_ids: tuple[str, ...], environment_class: str,
        repo_root: str | Path, revocation_check: Callable[[str], bool],
        architecture_version: str = ARCHITECTURE_VERSION,
    ):
        """Mission 2: `revocation_check` and `repo_root` are now REQUIRED,
        not optional -- `revocation_check` because
        `assert_execution_permitted()` (which this module now delegates
        all grant re-verification to) treats a missing revocation hook as
        a denial, never a silent "assume not revoked"; `repo_root` because
        `start()` must independently check the project-wide
        founder-acceptance ledger, which lives in THIS repository's own
        `docs/orneur/acceptance/` tree, not under `ORCA_HOME`."""
        self.state = RunState.PLANNED
        self.identity = RunIdentity(run_id=run_id, model_architecture_version=architecture_version, dataset_manifest_ids=tuple(dataset_manifest_ids))
        self.environment_class = environment_class
        self.repo_root = Path(repo_root)
        self.grant: NativePretrainingGrant | None = None
        self._authorized_identity: _AuthorizedIdentitySnapshot | None = None
        self.execution: ExecutionEvidence | None = None
        self.completion: CompletionEvidence | None = None
        self.evaluator_approval: EvaluatorApprovalClaim | None = None
        self.history: list[tuple[str, str, str]] = []  # (from_state, to_state, reason)
        self._revocation_check = revocation_check

    @classmethod
    def reset_in_process_replay_guard_for_new_process(cls) -> None:
        """Mission 2: kept as a no-op-compatible name for callers that
        still invoke it at process entrypoints, but the in-process set
        this classmethod used to reset is GONE -- replay protection is
        now exclusively the durable, on-disk
        `_claim_native_pretraining_authorization()` check (see its own
        docstring), which this call has no need to, and cannot, reset
        (resetting it would defeat its entire purpose)."""
        return None

    def _transition(self, to: RunState, *, reason: str) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if to not in allowed:
            raise InvalidTransitionError(f"{self.state.value} -> {to.value} is not an allowed transition (reason attempted: {reason!r})")
        self.history.append((self.state.value, to.value, reason))
        self.state = to

    def _current_identity_snapshot(self) -> _AuthorizedIdentitySnapshot:
        """The exact, full identity this run currently declares -- used
        both to check a candidate grant at `authorize()` time and to
        detect post-authorization drift at every resume-capable
        transition. Requires `validate()` to have already run (all the
        `| None` fields populated) -- `authorize()` itself enforces this
        via the state machine (`AWAITING_AUTHORIZATION` is unreachable
        without `validate()` having succeeded first)."""
        assert self.identity.dataset_manifest_ids, "validate() must set at least one dataset_manifest_id"
        return _AuthorizedIdentitySnapshot(
            run_id=self.identity.run_id,
            model_architecture_version=self.identity.model_architecture_version,
            dataset_manifest_id=self.identity.dataset_manifest_ids[0],
            dataset_digest=self.identity.dataset_digest or "",
            model_config_digest=self.identity.model_config_digest or "",
            tokenizer_digest=self.identity.tokenizer_digest or "",
            authorized_shard_digests=tuple(sorted(self.identity.authorized_shard_digests or ())),
            authorized_shard_file_digests=(
                _compute_authorized_shard_file_digests(self.identity.shard_dir)
                if self.identity.shard_dir is not None else ()
            ),
            environment_class=self.environment_class,
            reviewed_commit_sha=self.identity.reviewed_commit_sha or "",
            transformation_code_digest=self.identity.transformation_code_digest or "",
            optimizer_config_digest=self.identity.optimizer_config_digest or "",
            gpu_requested=self.identity.gpu_requested,
            requested_spend_usd=self.identity.requested_spend_usd,
            requested_wall_clock_minutes=self.identity.requested_wall_clock_minutes,
        )

    def _reverify_grant_or_transition(self, *, on_failure: RunState, context: str) -> None:
        """The single, shared re-verification routine `start()`,
        `resume()`, and `recovered()` all call (C-02, Mission 2 update).

        Two independent things are re-checked at every resume-capable
        transition, for two independent reasons:

        1. `assert_execution_permitted()` (delegated to
           `orca.genesis.governance.authorization`, not reimplemented
           here): HMAC integrity (forged/tampered since issuance),
           expiry, and MANDATORY live revocation. Passing HMAC integrity
           proves the grant object was genuinely issued and is
           untampered; it does NOT prove the underlying authorization
           hasn't since been revoked -- these are explicitly distinct
           checks, and `assert_execution_permitted()` itself treats a
           missing/erroring revocation check as a denial, never a silent
           pass.
        2. Identity-drift detection (Mission 2, new): the run's CURRENT
           identity must still exactly equal the snapshot frozen at
           `authorize()` time. An authorization is a decision about one
           specific workload; it must never keep applying if that
           workload's own declared identity has since changed.
        3. M2-02 fix: the project-wide founder-acceptance ledger's
           FINAL-1/FINAL-2/EXEC-1 rows are now re-checked HERE -- i.e. at
           EVERY resume-capable transition (`start()`, `resume()`,
           `recovered()`), not only at the original `start()` call.
           Independently reproduced as a real gap before this fix: a run
           that reached RUNNING while the ledger showed those rows
           accepted, then paused, would previously resume() successfully
           even if the ledger's acceptance had since been WITHDRAWN
           (e.g. a prior acceptance later found to be invalid and
           reverted) -- execution permission must be re-established at
           every resumption point, not assumed to persist from whenever
           `start()` last checked it."""
        assert self.grant is not None
        assert self._authorized_identity is not None
        try:
            assert_execution_permitted(self.grant, revocation_check=self._revocation_check)
        except NativePretrainingNotAuthorized as e:
            if "EXPIRED" in e.reasons:
                self._transition(on_failure, reason=f"authorization expired, detected at {context}")
                raise StaleAuthorizationError(f"grant {self.grant.authorization_id} expired at {self.grant.expires_at}") from e
            self._transition(on_failure, reason=f"grant failed re-verification at {context}: {e.reasons}")
            raise
        current = self._current_identity_snapshot()
        if current != self._authorized_identity:
            self._transition(on_failure, reason=f"authorized identity no longer matches current identity, detected at {context}")
            raise AuthorizedIdentityChangedError(
                f"this run's identity has changed since authorize() granted it authorization "
                f"(was {self._authorized_identity!r}, now {current!r}) -- re-authorization required"
            )
        missing_rows = check_founder_acceptance_ledger(self.repo_root, required_rows=EXECUTION_START_REQUIRED_ACCEPTANCE_ROWS)
        if missing_rows:
            self._transition(on_failure, reason=f"execution-permission acceptance incomplete at {context}: {missing_rows}")
            raise ExecutionAcceptanceIncompleteError(
                f"execution permission cannot be (re-)established at {context}: founder-acceptance ledger is missing "
                f"{missing_rows} (required: {EXECUTION_START_REQUIRED_ACCEPTANCE_ROWS})"
            )

    # ---- PLANNED -> VALIDATED --------------------------------------------------------------
    def validate(
        self, *, dataset_digest: str | None = None, model_config_digest: str, tokenizer_digest: str,
        authorized_shard_digests: tuple[str, ...], shard_dir: str | Path, reviewed_commit_sha: str,
        transformation_code_digest: str, optimizer_config_digest: str, gpu_requested: bool = False,
        requested_spend_usd: float = 0.0, requested_wall_clock_minutes: int = 1,
        dataset_manifest: DatasetManifestLike | None = None, dataset_records: list[str] | None = None,
    ) -> None:
        """Mission 2: binds the FULL workload identity a
        `NativePretrainingGrant` must match. Every one of these must be a
        real value the caller independently computed from the actual
        model config / tokenizer / dataset shards / code tree / optimizer
        config (this method does not compute any of them itself,
        deliberately, to avoid duplicating the responsibility of
        `orca.genesis.data.manifest`/`orca.genesis.tokenizer.framework`/
        `orca.registry.provenance`) -- with TWO exceptions, both M2-01/
        M2-03 fixes that verify against LIVE state rather than trusting a
        caller-supplied string alone:

        1. `reviewed_commit_sha` is independently re-checked against this
           repository's ACTUAL git history (`_is_live_ancestor_of_head()`)
           -- a caller cannot claim review of a commit that is not
           genuinely an ancestor of the current HEAD, regardless of what
           any signed record elsewhere claims.
        2. M2-03 (dataset preflight integration): pass `dataset_manifest`
           (any object satisfying Workstream F's own `DatasetManifestLike`
           Protocol -- e.g. a real `orca.genesis.data.manifest.GenesisDatasetManifest`,
           duck-typed, not imported, so this module gains no hard
           dependency on Workstream A) together with `dataset_records`
           (the actual normalized records to check it against), and this
           method calls `dataset_manifest.verify_against_records()`
           itself, deriving `dataset_digest`/the bound manifest id from
           the VERIFIED object -- not from a bare caller-supplied digest
           string that could be merely well-formed, never actually
           checked against real content. `dataset_digest` may be omitted
           when `dataset_manifest`+`dataset_records` are supplied (and
           vice versa); supplying neither, or a manifest whose id is not
           one of this run's declared `dataset_manifest_ids`, raises.

        `shard_dir` (Audit #71 P0-01 fix, required): the real directory
        containing this run's `shard-*.jsonl` files. `authorized_shard_digests`
        is independently re-verified against the REAL, freshly-computed
        digests of the files actually present there -- a caller cannot
        claim digests that do not correspond to real on-disk content.
        This directory (and its live content) is re-read and re-hashed
        at EVERY subsequent resume-capable transition
        (`start()`/`resume()`/`recovered()`, via
        `_reverify_grant_or_transition()`), so a shard file modified,
        substituted, or swapped after this call is detected and denies
        the transition -- see the module docstring's "AUDIT-P0-01"
        section."""
        if self.state != RunState.PLANNED:
            raise InvalidTransitionError(f"validate() requires PLANNED, got {self.state.value}")

        if dataset_manifest is not None:
            if dataset_records is None:
                self._transition(RunState.REJECTED, reason="dataset_manifest supplied without dataset_records at validation")
                raise ValueError("dataset_records is required when dataset_manifest is supplied -- a manifest must be re-verified against real records, not trusted on its own")
            if dataset_manifest.manifest_id not in self.identity.dataset_manifest_ids:
                self._transition(RunState.REJECTED, reason="dataset_manifest.manifest_id is not one of this run's declared dataset_manifest_ids")
                raise ValueError(f"dataset_manifest.manifest_id {dataset_manifest.manifest_id!r} is not in this run's declared dataset_manifest_ids {self.identity.dataset_manifest_ids!r}")
            ok, msg = dataset_manifest.verify_against_records(dataset_records)
            if not ok:
                self._transition(RunState.REJECTED, reason=f"dataset_manifest failed verify_against_records(): {msg}")
                raise ValueError(f"dataset_manifest failed independent re-verification against its own records: {msg}")
            dataset_digest = dataset_manifest.source_content_digest
        elif dataset_digest is None:
            self._transition(RunState.REJECTED, reason="neither dataset_digest nor dataset_manifest supplied at validation")
            raise ValueError("validate() requires either dataset_digest or (dataset_manifest, dataset_records)")

        if not isinstance(dataset_digest, str) or not _SHA256_HEX.match(dataset_digest):
            self._transition(RunState.REJECTED, reason="invalid dataset_digest at validation")
            raise ValueError(f"dataset_digest must be a 64-character lowercase hex SHA-256, got {dataset_digest!r}")
        if not isinstance(model_config_digest, str) or not _SHA256_HEX.match(model_config_digest):
            self._transition(RunState.REJECTED, reason="invalid model_config_digest at validation")
            raise ValueError(f"model_config_digest must be a 64-character lowercase hex SHA-256, got {model_config_digest!r}")
        if not isinstance(tokenizer_digest, str) or not _SHA256_HEX.match(tokenizer_digest):
            self._transition(RunState.REJECTED, reason="invalid tokenizer_digest at validation")
            raise ValueError(f"tokenizer_digest must be a 64-character lowercase hex SHA-256, got {tokenizer_digest!r}")
        shards = tuple(authorized_shard_digests)
        if not shards or not all(isinstance(s, str) and _SHA256_HEX.match(s) for s in shards):
            self._transition(RunState.REJECTED, reason="invalid authorized_shard_digests at validation")
            raise ValueError(f"authorized_shard_digests must be a non-empty tuple of 64-character lowercase hex SHA-256 values, got {authorized_shard_digests!r}")
        # Audit #71 P0-01 fix: never trust a caller-supplied digest string
        # alone -- independently recompute the REAL on-disk digests of the
        # files actually present in shard_dir and require them to match
        # exactly before this run's identity is ever bound to them. See
        # the module docstring's "AUDIT-P0-01" section.
        shard_dir_path = Path(shard_dir)
        on_disk_shard_digests = _compute_authorized_shard_file_digests(shard_dir_path)
        if not on_disk_shard_digests:
            self._transition(RunState.REJECTED, reason="shard_dir contains no real shard-*.jsonl files at validation")
            raise ValueError(
                f"shard_dir {shard_dir_path} contains no shard-*.jsonl files -- refusing to bind this run's "
                "authorization to a directory with nothing real to verify"
            )
        on_disk_digest_values = tuple(sorted(d for _, d in on_disk_shard_digests))
        if on_disk_digest_values != tuple(sorted(shards)):
            self._transition(RunState.REJECTED, reason="authorized_shard_digests does not match real on-disk shard file contents at validation")
            raise ValueError(
                f"authorized_shard_digests {sorted(shards)!r} does not match the real, independently computed "
                f"digests of the shard-*.jsonl files actually present in {shard_dir_path} "
                f"({on_disk_digest_values!r}) -- a caller-supplied digest string is never trusted without live "
                "verification against real file bytes"
            )
        if not isinstance(transformation_code_digest, str) or not _SHA256_HEX.match(transformation_code_digest):
            self._transition(RunState.REJECTED, reason="invalid transformation_code_digest at validation")
            raise ValueError(f"transformation_code_digest must be a 64-character lowercase hex SHA-256, got {transformation_code_digest!r}")
        if not isinstance(optimizer_config_digest, str) or not _SHA256_HEX.match(optimizer_config_digest):
            self._transition(RunState.REJECTED, reason="invalid optimizer_config_digest at validation")
            raise ValueError(f"optimizer_config_digest must be a 64-character lowercase hex SHA-256, got {optimizer_config_digest!r}")
        if not isinstance(reviewed_commit_sha, str) or not _SHA40_HEX.match(reviewed_commit_sha):
            self._transition(RunState.REJECTED, reason="invalid reviewed_commit_sha at validation")
            raise ValueError(f"reviewed_commit_sha must be a 40-character lowercase hex SHA-1, got {reviewed_commit_sha!r}")
        if not _is_live_ancestor_of_head(self.repo_root, reviewed_commit_sha):
            self._transition(RunState.REJECTED, reason="reviewed_commit_sha is not a real ancestor of this repository's current HEAD")
            raise ValueError(
                f"reviewed_commit_sha {reviewed_commit_sha!r} is not verifiably an ancestor of this repository's "
                f"current HEAD -- a caller-supplied commit SHA alone is never trusted without live verification"
            )
        # Mission 2 continuation fix (narrowly bounded, per directive):
        # independently reproduced before this fix -- `requested_spend_usd=
        # float("nan")` passed BOTH this check (`isinstance(..., (int, float))`
        # and `nan < 0` are each False, since every comparison against NaN is
        # False) AND authorize()'s later `current.requested_spend_usd >
        # grant.max_spend_usd` limit check (`nan > 0` is ALSO False) --
        # silently bypassing the spend-limit check entirely regardless of
        # what any real grant actually authorizes. `bool` is also a Python
        # `int`/`float` subtype, so a stray `True`/`False` would otherwise
        # slip through these `isinstance` checks as if it were a real
        # numeric value. Both are now explicitly rejected via
        # `math.isfinite()` (which is False for both NaN and +/-inf) and an
        # explicit `isinstance(..., bool)` exclusion.
        if isinstance(requested_wall_clock_minutes, bool) or not isinstance(requested_wall_clock_minutes, int) \
                or requested_wall_clock_minutes < 1:
            self._transition(RunState.REJECTED, reason="invalid requested_wall_clock_minutes at validation")
            raise ValueError(f"requested_wall_clock_minutes must be a positive integer, got {requested_wall_clock_minutes!r}")
        if isinstance(requested_spend_usd, bool) or not isinstance(requested_spend_usd, (int, float)) \
                or not math.isfinite(requested_spend_usd) or requested_spend_usd < 0:
            self._transition(RunState.REJECTED, reason="invalid requested_spend_usd at validation")
            raise ValueError(f"requested_spend_usd must be a finite, non-negative number, got {requested_spend_usd!r}")
        if not isinstance(gpu_requested, bool):
            self._transition(RunState.REJECTED, reason="invalid gpu_requested at validation")
            raise ValueError(f"gpu_requested must be a real bool, got {gpu_requested!r} ({type(gpu_requested).__name__}) -- a truthy string like 'False' is never silently coerced")

        self.identity.dataset_digest = dataset_digest
        self.identity.model_config_digest = model_config_digest
        self.identity.tokenizer_digest = tokenizer_digest
        self.identity.authorized_shard_digests = shards
        self.identity.shard_dir = shard_dir_path
        self.identity.reviewed_commit_sha = reviewed_commit_sha
        self.identity.transformation_code_digest = transformation_code_digest
        self.identity.optimizer_config_digest = optimizer_config_digest
        self.identity.gpu_requested = gpu_requested
        self.identity.requested_spend_usd = float(requested_spend_usd)
        self.identity.requested_wall_clock_minutes = requested_wall_clock_minutes
        self._transition(RunState.VALIDATED, reason="full workload identity recorded and well-formed")

    # ---- VALIDATED -> AWAITING_AUTHORIZATION -----------------------------------------------
    def request_authorization(self) -> None:
        if self.state != RunState.VALIDATED:
            raise InvalidTransitionError(f"request_authorization() requires VALIDATED, got {self.state.value}")
        self._transition(RunState.AWAITING_AUTHORIZATION, reason="awaiting founder-trusted authorization")

    # ---- AWAITING_AUTHORIZATION -> AUTHORIZED ----------------------------------------------
    def authorize(self, grant: NativePretrainingGrant) -> None:
        """The real authorization boundary -- see module docstring.
        Raises `NativePretrainingNotAuthorized` for anything that is not
        a genuinely sealed, untampered `NativePretrainingGrant` instance
        bound EXACTLY to this run's full declared identity (run id,
        model config digest, tokenizer digest, dataset manifest id,
        dataset content digest, authorized shard digests, environment
        class), and `ReplayedAuthorizationError` for an authorization_id
        already durably consumed -- by this process or any prior one."""
        if self.state != RunState.AWAITING_AUTHORIZATION:
            raise InvalidTransitionError(f"authorize() requires AWAITING_AUTHORIZATION, got {self.state.value}")
        if not isinstance(grant, NativePretrainingGrant):
            self._transition(RunState.REJECTED, reason="authorization rejected: not a real NativePretrainingGrant instance")
            raise NativePretrainingNotAuthorized(["NO_NATIVE_PRETRAINING_GRANT"])
        try:
            grant.verify_integrity()
        except NativePretrainingNotAuthorized:
            self._transition(RunState.REJECTED, reason="authorization rejected: grant failed integrity verification")
            raise
        expires = _parse_iso(grant.expires_at)
        if expires is None or datetime.now(timezone.utc) >= expires:
            self._transition(RunState.REJECTED, reason="authorization rejected: grant already expired")
            raise NativePretrainingNotAuthorized(["EXPIRED"])

        current = self._current_identity_snapshot()
        mismatches = []
        if grant.run_id != current.run_id:
            mismatches.append("WRONG_RUN_ID")
        if grant.model_config_digest != current.model_config_digest:
            mismatches.append("WRONG_MODEL_CONFIG_DIGEST")
        if grant.tokenizer_digest != current.tokenizer_digest:
            mismatches.append("WRONG_TOKENIZER_DIGEST")
        if grant.dataset_manifest_id != current.dataset_manifest_id:
            mismatches.append("WRONG_DATASET_MANIFEST_ID")
        if grant.dataset_content_digest != current.dataset_digest:
            mismatches.append("WRONG_DATASET_CONTENT_DIGEST")
        if tuple(sorted(grant.authorized_shard_digests)) != current.authorized_shard_digests:
            mismatches.append("WRONG_AUTHORIZED_SHARDS")
        if grant.environment_class != current.environment_class:
            mismatches.append("WRONG_ENVIRONMENT_CLASS")
        # M2-01: the remaining signed-authorization fields the grant now
        # carries (PR #69) -- architecture/code/optimizer identity bound
        # exactly, and GPU/spend/wall-clock treated as LIMITS the run's
        # own declared intent must fall within, not values to match
        # exactly (a grant permitting up to $50 legitimately covers a run
        # that only needs $10).
        if grant.architecture_version != current.model_architecture_version:
            mismatches.append("WRONG_ARCHITECTURE_VERSION")
        if grant.reviewed_commit_sha != current.reviewed_commit_sha:
            mismatches.append("WRONG_REVIEWED_COMMIT")
        if grant.transformation_code_digest != current.transformation_code_digest:
            mismatches.append("WRONG_TRANSFORMATION_CODE_DIGEST")
        if grant.optimizer_config_digest != current.optimizer_config_digest:
            mismatches.append("WRONG_OPTIMIZER_CONFIG_DIGEST")
        if current.gpu_requested and not grant.gpu_allowed:
            mismatches.append("GPU_NOT_AUTHORIZED")
        if current.requested_spend_usd > grant.max_spend_usd:
            mismatches.append("SPEND_NOT_AUTHORIZED")
        if current.requested_wall_clock_minutes > grant.max_wall_clock_minutes:
            mismatches.append("WALL_CLOCK_NOT_AUTHORIZED")
        if mismatches:
            self._transition(RunState.REJECTED, reason=f"authorization rejected: grant does not match this run's identity ({mismatches})")
            raise NativePretrainingNotAuthorized(mismatches)

        if not _claim_native_pretraining_authorization(grant.authorization_id):
            self._transition(RunState.REJECTED, reason="authorization rejected: replayed authorization_id")
            raise ReplayedAuthorizationError(
                f"authorization_id {grant.authorization_id!r} has already authorized a run (this process or a prior one)"
            )
        self.grant = grant
        self._authorized_identity = current
        self._transition(RunState.AUTHORIZED, reason=f"authorized via verified, workload-bound native-pretraining grant {grant.authorization_id}")

    # ---- AUTHORIZED -> RUNNING --------------------------------------------------------------
    def start(self) -> None:
        """Re-verifies the grant (integrity, expiry, mandatory live
        revocation, identity-drift, and -- M2-02 -- the project-wide
        founder-acceptance ledger's FINAL-1/FINAL-2/EXEC-1 rows) at the
        moment execution actually begins, not only at `authorize()`
        time. All of this is delegated to
        `_reverify_grant_or_transition()`, the SAME routine `resume()`
        and `recovered()` call, so execution permission is established
        (and re-established) identically at every point RUNNING is
        (re-)entered, not merely at the first `start()`."""
        if self.state != RunState.AUTHORIZED:
            raise InvalidTransitionError(f"start() requires AUTHORIZED, got {self.state.value}")
        if self.grant is None:
            raise InvalidTransitionError("start() called with no grant recorded -- internal invariant violated")
        self._reverify_grant_or_transition(on_failure=RunState.REJECTED, context="start()")
        self.execution = ExecutionEvidence()
        self._transition(RunState.RUNNING, reason="execution started under a freshly re-verified grant")

    # ---- RUNNING: execution evidence (never called by this module itself) -----------------
    def record_step(self, step: int, *, source_identity: str, loss: float | None = None) -> None:
        """C-03: records a SELF-REPORTED progress claim -- see
        `ExecutionEvent`'s docstring for why this is never described as
        verified proof of actual optimizer execution. A real training
        loop would call this once per optimizer step; nothing in this
        codebase does, because no GENESIS native training loop exists yet
        (native pretraining remains `NOT_AUTHORIZED`). `step` must
        strictly increase -- append-only progress, never a rewritable
        claim. `source_identity` is required and must identify the
        reporting process/caller (itself unauthenticated; see
        `ExecutionEvent`)."""
        if self.state != RunState.RUNNING:
            raise InvalidTransitionError(f"record_step() requires RUNNING, got {self.state.value}")
        if self.execution is None:
            raise InvalidTransitionError("record_step() called with no execution evidence initialized")
        if not isinstance(source_identity, str) or not source_identity:
            raise ValueError("source_identity is required and must be a non-empty string identifying the reporting process")
        if not isinstance(step, int) or step <= self.execution.steps_recorded:
            raise ValueError(f"step must be a strictly increasing integer; got {step}, last recorded {self.execution.steps_recorded}")
        if len(self.execution.events) >= self.execution.max_events:
            raise ValueError(f"execution evidence limit reached ({self.execution.max_events} events) -- refusing unbounded growth")
        self.execution.events.append(ExecutionEvent(
            source_identity=source_identity, run_id=self.identity.run_id, step=step,
            sequence=len(self.execution.events), reported_at=_now_iso(),
        ))

    # ---- RUNNING -> PAUSED -> RUNNING / RECOVERING -----------------------------------------
    def pause(self, *, reason: str = "paused") -> None:
        if self.state != RunState.RUNNING:
            raise InvalidTransitionError(f"pause() requires RUNNING, got {self.state.value}")
        self._transition(RunState.PAUSED, reason=reason)

    def resume(self) -> None:
        """C-02 fix: previously performed NO grant re-check at all --
        resuming computation is exactly the kind of transition the
        continuation order says must never assume a previously valid
        grant remains valid forever. Now runs the same full
        re-verification as `start()`/`recovered()`."""
        if self.state != RunState.PAUSED:
            raise InvalidTransitionError(f"resume() requires PAUSED, got {self.state.value}")
        if self.grant is None:
            raise InvalidTransitionError("resume() called with no grant recorded -- internal invariant violated")
        self._reverify_grant_or_transition(on_failure=RunState.FAILED, context="resume()")
        self._transition(RunState.RUNNING, reason="resumed under a freshly re-verified grant")

    def begin_recovery(self, *, reason: str) -> None:
        if self.state != RunState.PAUSED:
            raise InvalidTransitionError(f"begin_recovery() requires PAUSED, got {self.state.value}")
        self._transition(RunState.RECOVERING, reason=reason)

    def recovered(self) -> None:
        """RECOVERING -> RUNNING. Re-verifies the grant exactly like
        `start()`/`resume()` do -- an interrupted-and-recovered run must
        not resume on a since-expired, since-revoked, or
        since-tampered-with grant either."""
        if self.state != RunState.RECOVERING:
            raise InvalidTransitionError(f"recovered() requires RECOVERING, got {self.state.value}")
        if self.grant is None:
            raise InvalidTransitionError("recovered() called with no grant recorded -- internal invariant violated")
        self._reverify_grant_or_transition(on_failure=RunState.FAILED, context="recovered()")
        self._transition(RunState.RUNNING, reason="recovered and resumed under a freshly re-verified grant")

    # ---- RUNNING/PAUSED/RECOVERING -> FAILED -----------------------------------------------
    def fail(self, *, reason: str) -> None:
        if self.state not in (RunState.RUNNING, RunState.PAUSED, RunState.RECOVERING):
            raise InvalidTransitionError(f"fail() requires RUNNING, PAUSED, or RECOVERING, got {self.state.value}")
        self._transition(RunState.FAILED, reason=reason)

    # ---- REJECTED, only from states the transition graph actually permits (C-06) ----------
    def reject(self, *, reason: str) -> None:
        if self.state not in _REJECTABLE_STATES:
            raise InvalidTransitionError(
                f"reject() is only valid from {sorted(s.value for s in _REJECTABLE_STATES)}, got {self.state.value} "
                f"(a run already RUNNING/PAUSED/RECOVERING must use fail(), not reject())"
            )
        self._transition(RunState.REJECTED, reason=reason)

    # ---- RUNNING -> COMPLETED ---------------------------------------------------------------
    def complete(self, *, checkpoint_path: str | Path) -> None:
        """Completion evidence AND checkpoint identity, both independently
        re-verified here -- never accepted on the caller's word. Raises
        `ForgedCompletionError` if the checkpoint does not pass the full
        `load_verified_training_state()` trust boundary, or if its
        verified step does not match this run's own recorded execution
        evidence (closing the exact "forged completion" case the
        continuation order names: a caller claiming completion with a
        checkpoint that either isn't real, isn't verified, or doesn't
        correspond to what this run actually executed)."""
        if self.state != RunState.RUNNING:
            raise InvalidTransitionError(f"complete() requires RUNNING, got {self.state.value}")
        if self.execution is None or self.execution.steps_recorded == 0:
            raise ForgedCompletionError("cannot complete a run with no recorded execution evidence -- nothing was ever actually run")
        checkpoint_path = Path(checkpoint_path)
        try:
            state = load_verified_training_state(checkpoint_path)
        except Exception as e:
            raise ForgedCompletionError(f"checkpoint at {checkpoint_path} failed verification: {e!r}") from e
        if state.step != self.execution.steps_recorded:
            raise ForgedCompletionError(
                f"checkpoint's verified step ({state.step}) does not match this run's recorded execution "
                f"evidence ({self.execution.steps_recorded}) -- this checkpoint does not correspond to this run"
            )
        manifest = CheckpointManifest.from_dict(json.loads(_manifest_path(checkpoint_path).read_text()))
        self.completion = CompletionEvidence(
            checkpoint_path=str(checkpoint_path), checkpoint_manifest_sha256=manifest.sha256,
            final_step=state.step, completed_at=_now_iso(),
        )
        self._transition(RunState.COMPLETED, reason=f"completion verified against checkpoint step {state.step}")

    # ---- evaluator approval claim: COMPLETED only, separate from everything above ---------
    def record_evaluator_approval(
        self, *, evaluator_identity: str, approved: bool, evaluation_report_sha256: str, checkpoint_manifest_sha256: str,
    ) -> None:
        """C-04: records an explicitly UNAUTHENTICATED approval CLAIM --
        see `EvaluatorApprovalClaim`'s docstring. `checkpoint_manifest_sha256`
        is required and MUST equal this run's own completed checkpoint's
        manifest hash exactly, closing the "approval for the wrong
        checkpoint" case: an evaluator (real or impersonated) cannot
        record an approval that silently gets attributed to a checkpoint
        other than the one they actually name."""
        if self.state != RunState.COMPLETED:
            raise InvalidTransitionError(f"record_evaluator_approval() requires COMPLETED, got {self.state.value}")
        if self.completion is None:
            raise InvalidTransitionError("record_evaluator_approval() called with no completion evidence recorded")
        if not isinstance(evaluation_report_sha256, str) or not _SHA256_HEX.match(evaluation_report_sha256):
            raise ValueError(f"evaluation_report_sha256 must be a 64-character lowercase hex SHA-256, got {evaluation_report_sha256!r}")
        if checkpoint_manifest_sha256 != self.completion.checkpoint_manifest_sha256:
            raise ValueError(
                f"checkpoint_manifest_sha256 {checkpoint_manifest_sha256!r} does not match this run's completed "
                f"checkpoint's manifest hash {self.completion.checkpoint_manifest_sha256!r} -- refusing to record "
                "an approval claim for a different checkpoint"
            )
        self.evaluator_approval = EvaluatorApprovalClaim(
            evaluator_identity=evaluator_identity, approved=approved, evaluation_report_sha256=evaluation_report_sha256,
            checkpoint_manifest_sha256=checkpoint_manifest_sha256, approved_at=_now_iso(),
        )
