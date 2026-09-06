"""
Filesystem elevation (Phase 10 spec §22; Phase 10.1 spec §12's honesty
requirement). An elevated FILE_WRITE lease grants write access to
exactly one additional, explicit directory ROOT (e.g.
`/workspace/project-a/config/`) -- NEVER the whole filesystem, and never
merely because authority is high. Reuses
`orca.tools._resolve_in_workspace`'s realpath-resolution discipline
(symlinks are followed and checked against the final resolved path, not
the literal string) rather than inventing a second path-safety
implementation, and adds a hard-coded denylist of sensitive absolute
paths that no lease scope can ever override (spec §22: "does not
authorize /etc, ~/.ssh, other projects").

EXACT BINDING DIMENSIONS, disclosed explicitly (spec §12: "do not claim
stronger binding than actually implemented"): a FILE_WRITE lease binds
`resource_scope` (the root directory) and `operation_scope` exactly --
it does NOT bind the specific file path within that root, and does NOT
bind file content. This is a deliberate design choice, not an oversight:
spec §7's own "good lease" example is itself a DIRECTORY-scoped grant
(`write /workspace/project-a/config/`), and a fix-a-bug elevated session
legitimately needs to write more than one file, with content that
cannot be known at approval time. `resolve_and_consume_lease()` is
therefore called with `arguments={}` -- the canonical "empty payload"
that a default (`arguments=None`) approval's `arguments_hash` binds to
-- rather than the path or content, so this module's `EXACT_ARGUMENTS`
check passes trivially and the REAL narrowing is the directory-root
scope check (`_resolve_within_root()`) plus the hard denylist, both of
which are independent of and unaffected by this phase's argument-hash
work.
"""
from __future__ import annotations

from pathlib import Path

from orca.godmode.cancellation import CancellationSignal, check_and_record_pre_side_effect_cancellation
from orca.godmode.contracts import CapabilityDomain
from orca.godmode.lease_store import get as get_lease
from orca.godmode.resolution import resolve_and_consume_lease

# Absolute, resolved paths (and their descendants) that NO file-elevation
# lease may ever grant access to, regardless of what its resource_scope
# names -- defense in depth on top of (never instead of) exact lease
# scope matching.
_HARD_DENYLIST = [
    Path("/etc").resolve(),
    Path("/root").resolve(),
    Path.home().joinpath(".ssh").resolve(),
    Path.home().joinpath(".aws").resolve(),
    Path.home().joinpath(".gnupg").resolve(),
    Path.home().joinpath(".orca", "auth.db").resolve(),
    Path.home().joinpath(".orca", "godmode").resolve(),
]


def _is_denied(resolved: Path) -> bool:
    for denied in _HARD_DENYLIST:
        try:
            resolved.relative_to(denied)
            return True
        except ValueError:
            continue
    return False


def _resolve_within_root(path: str, root: Path) -> Path | None:
    """Resolves `path` (relative or absolute) and returns it only if the
    FULLY RESOLVED path (symlinks followed) is inside `root` -- mirrors
    `orca.tools._resolve_in_workspace`'s exact discipline, generalized to
    an arbitrary lease-granted root instead of the fixed WORKSPACE_DIR."""
    raw = Path(path).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if _is_denied(candidate):
        return None
    return candidate


def elevated_write_file(
    *, lease_id: str, tenant_id: str, path: str, content: str,
    cancellation: "CancellationSignal | None" = None,
) -> tuple[bool, str]:
    """
    Returns `(success, message)`. Fails closed on ANY of: lease not
    FILE-domain, lease not FILE_WRITE, scope/tenant mismatch, resolved
    path escaping the lease's granted root (traversal or symlink),
    resolved path hitting the hard denylist, or the lease having no uses
    remaining (consumed atomically here, exactly once per successful
    write -- never before the path safety checks pass, so a
    path-rejected attempt never burns a use).

    `cancellation` (Phase 14B.2): forwarded to
    `resolve_and_consume_lease()` for its own in-flight checkpoints, AND
    checked AGAIN via `check_and_record_pre_side_effect_cancellation()`
    immediately before the actual file write below -- this function is
    a self-contained example of Step 5's caller-side final gate: a
    cancellation arriving in the (normally instantaneous, but real)
    window between `resolve_and_consume_lease()` returning ALLOW and
    `resolved.write_text()` actually running must still block the
    write, even though the lease's use has already been durably
    committed by that point. `None` (the default) preserves existing
    behavior exactly -- this module's only current callers
    (`orca/godmode/eval_harness.py`, simulations) are synchronous.
    """
    lease = get_lease(lease_id)
    if lease is None or lease.capability_domain != CapabilityDomain.FILE or lease.capability != "FILE_WRITE":
        return False, "no matching FILE_WRITE lease"

    root = Path(lease.resource_scope).expanduser().resolve()
    resolved = _resolve_within_root(path, root)
    if resolved is None:
        return False, f"path '{path}' is outside the lease's granted root or denylisted -- denied"

    decision = resolve_and_consume_lease(
        lease_id, tenant_id=tenant_id, capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE",
        resource_scope=lease.resource_scope, operation_scope=lease.operation_scope, arguments={},
        cancellation=cancellation,
    )
    if decision.state.value != "ALLOW":
        return False, "; ".join(decision.reasons)

    # Caller-side final gate (spec Step 5): the lease is now durably
    # COMMITTED -- that fact is never undone below -- but the side
    # effect (the actual write) has not happened yet.
    if not check_and_record_pre_side_effect_cancellation(
        cancellation=cancellation, tenant_id=tenant_id, lease_id=lease_id,
        capability="FILE_WRITE", resource_scope=lease.resource_scope, operation_scope=lease.operation_scope,
    ):
        return False, "cancelled after authorization was committed, before the file write executed -- write not performed"

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content)
    return True, str(resolved)
