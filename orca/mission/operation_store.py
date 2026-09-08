"""
Phase 15.5 -- durable Operation lifecycle + authority integration.

The canonical lifecycle (spec section 1):

    REQUESTED -> AUTHORIZED -> STARTED -> SUCCEEDED | FAILED
    REQUESTED -> CANCELLED
    AUTHORIZED -> CANCELLED

No code path in this module writes `operations.status` outside
`_write_operation_transition()`, which validates every move against
`_ALLOWED_TRANSITIONS` -- there is no way to reach STARTED without
having passed through AUTHORIZED first, and no way to reach
SUCCEEDED/FAILED without STARTED.

Authority is never decided here. `authorize_operation()` is a thin
orchestration layer around `orca.mission.authority_bridge`, which
itself delegates the actual ALLOW/DENY decision to
`orca.godmode.resolution.resolve_and_consume_lease()` -- the real,
existing, race-safe authority primitive. This module's only authority-
adjacent responsibility is the hard structural guard that a requester
can never also be the approver (spec section 21) -- checked BEFORE any
call into godmode, so a self-authorization attempt never even reaches
the lease system.

Idempotency (spec section 2): `request_operation()` deduplicates
BEFORE any side effect, using `INSERT ... ON CONFLICT (idempotency_key)
DO NOTHING RETURNING *` -- an atomic, database-level check, not a
catch-the-UNIQUE-violation-after-the-fact pattern. A retry with the
SAME idempotency_key and the SAME material parameters returns the
existing operation; a retry with the SAME key and DIFFERENT parameters
raises OperationConflictError before any row is touched.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from orca.godmode.contracts import ElevatedPolicyDecisionState, LeaseIssuanceError
from orca.mission.authority_bridge import consume_operation_lease, issue_operation_lease

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "REQUESTED": frozenset({"AUTHORIZED", "CANCELLED"}),
    "AUTHORIZED": frozenset({"STARTED", "CANCELLED"}),
    "STARTED": frozenset({"SUCCEEDED", "FAILED"}),
    "SUCCEEDED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}

_NO_EXECUTOR_RECALL_STATES = frozenset({"STARTED", "SUCCEEDED", "FAILED", "CANCELLED"})


class OperationStoreError(Exception):
    """Base class for operation-store errors."""


class OperationNotFoundError(OperationStoreError):
    pass


class OperationStateError(OperationStoreError):
    """An illegal lifecycle transition was attempted."""


class OperationConflictError(OperationStoreError):
    """The same idempotency_key was reused with materially different
    operation parameters."""


class SelfAuthorizationError(OperationStoreError):
    """A requester attempted to also be the approver of their own
    operation -- rejected before any call into the authority engine."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_fingerprint(*, kind: str, target: str, parameters: dict | None) -> str:
    """A canonical hash of the material execution intent (spec section
    3) -- deliberately uses only the stdlib (hashlib + json, sorted
    keys for a stable ordering), no custom cryptography. `parameters`
    must never contain a raw secret value (the caller's
    responsibility -- this function does not know which fields are
    sensitive)."""
    canonical = json.dumps(
        {"kind": kind, "target": target, "parameters": parameters or {}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def request_operation(
    conn,
    *,
    id: str,
    idempotency_key: str,
    kind: str,
    requested_by: str,
    mission_id: str | None = None,
    target: str = "",
    parameters: dict | None = None,
) -> tuple[dict, bool]:
    """Returns (operation_row, was_newly_created). Deduplicates on
    idempotency_key BEFORE any row is inserted -- see module
    docstring. Raises OperationConflictError if the same key was
    already used with a different fingerprint."""
    fingerprint = compute_fingerprint(kind=kind, target=target, parameters=parameters)
    now = _now_iso()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO operations
                (id, mission_id, idempotency_key, kind, status, requested_at,
                 parameters_fingerprint, requested_by)
            VALUES (%s, %s, %s, %s, 'REQUESTED', %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            (id, mission_id, idempotency_key, kind, now, fingerprint, requested_by),
        )
        inserted = cur.fetchone()
    conn.commit()

    if inserted is not None:
        return get_operation(conn, id), True  # type: ignore[return-value]

    existing = get_operation_by_idempotency_key(conn, idempotency_key)
    assert existing is not None  # ON CONFLICT fired, so a row with this key must exist
    if existing["parameters_fingerprint"] != fingerprint:
        raise OperationConflictError(
            f"idempotency_key {idempotency_key!r} was already used with different operation "
            f"parameters (existing fingerprint {existing['parameters_fingerprint']!r}, "
            f"this request's fingerprint {fingerprint!r})."
        )
    return existing, False


def get_operation(conn, operation_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM operations WHERE id = %s", (operation_id,))
        row = cur.fetchone()
    conn.commit()
    return dict(row) if row else None


def get_operation_by_idempotency_key(conn, idempotency_key: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM operations WHERE idempotency_key = %s", (idempotency_key,))
        row = cur.fetchone()
    conn.commit()
    return dict(row) if row else None


def _write_operation_transition(conn, operation_id: str, new_status: str, *, result_ref: str | None = None) -> str:
    """Locks the operation row, validates the transition, writes.
    Does NOT commit -- callers control the transaction boundary."""
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM operations WHERE id = %s FOR UPDATE", (operation_id,))
        row = cur.fetchone()
        if row is None:
            raise OperationNotFoundError(f"No such operation: {operation_id}")
        current = row["status"]
        if new_status not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            allowed = sorted(_ALLOWED_TRANSITIONS.get(current, frozenset()))
            raise OperationStateError(
                f"Cannot transition operation {operation_id} {current} -> {new_status}. "
                f"Allowed from {current}: {allowed or 'none (terminal)'}."
            )

        now = _now_iso()
        if new_status == "AUTHORIZED":
            cur.execute("UPDATE operations SET status=%s, authorized_at=%s WHERE id=%s", (new_status, now, operation_id))
        elif new_status == "STARTED":
            cur.execute("UPDATE operations SET status=%s, started_at=%s WHERE id=%s", (new_status, now, operation_id))
        elif new_status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            cur.execute(
                "UPDATE operations SET status=%s, completed_at=%s, result_ref=%s WHERE id=%s",
                (new_status, now, result_ref, operation_id),
            )
        else:  # pragma: no cover -- guarded by _ALLOWED_TRANSITIONS above
            raise OperationStateError(f"unhandled target status: {new_status}")
    return current


def cancel_operation(conn, operation_id: str) -> dict:
    """Cancels a REQUESTED or AUTHORIZED operation. Rejects (raises
    OperationStateError) for anything already STARTED or terminal --
    a cancelled operation can never later execute, and a
    started/finished operation can never be 'uncancelled' by this
    call."""
    try:
        _write_operation_transition(conn, operation_id, "CANCELLED")
    except OperationStoreError:
        conn.rollback()
        raise
    conn.commit()
    return get_operation(conn, operation_id)  # type: ignore[return-value]


def authorize_operation(
    conn,
    operation_id: str,
    *,
    tenant_id: str,
    approved_by: str,
    reason: str,
    arguments: dict | None = None,
) -> tuple[dict, bool]:
    """Attempts to authorize a REQUESTED operation. Returns
    (operation_row, was_authorized). The hard self-authorization guard
    (approved_by == requested_by) is checked BEFORE any call into
    orca.mission.authority_bridge / orca.godmode -- a self-approval
    attempt never reaches the real authority engine at all. A real
    DENY from godmode (or a structural lease-issuance failure) is
    durably recorded as an authority_decisions row and leaves the
    operation in REQUESTED (never AUTHORIZED, never silently treated
    as approved)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM operations WHERE id = %s FOR UPDATE", (operation_id,))
        row = cur.fetchone()

    if row is None:
        conn.rollback()
        raise OperationNotFoundError(f"No such operation: {operation_id}")
    if row["status"] != "REQUESTED":
        conn.rollback()
        raise OperationStateError(f"cannot authorize operation {operation_id} in status {row['status']}")

    requested_by = row["requested_by"]
    if approved_by == requested_by:
        conn.rollback()
        raise SelfAuthorizationError(
            f"requester {requested_by!r} cannot also approve operation {operation_id} -- "
            f"spec section 21: requesting an action does not grant authority to perform it."
        )

    lease_id: str | None = None
    decision_reasons: list[str] = []
    allowed = False
    try:
        lease = issue_operation_lease(
            operation_id=operation_id,
            operation_kind=row["kind"],
            tenant_id=tenant_id,
            requested_by=requested_by,
            approved_by=approved_by,
            reason=reason,
            arguments=arguments,
        )
        lease_id = lease.lease_id
        decision = consume_operation_lease(
            lease_id=lease_id,
            operation_id=operation_id,
            operation_kind=row["kind"],
            tenant_id=tenant_id,
            requested_by=requested_by,
            arguments=arguments,
        )
        allowed = decision.state == ElevatedPolicyDecisionState.ALLOW
        decision_reasons = decision.reasons
    except LeaseIssuanceError as e:
        decision_reasons = [f"lease issuance failed: {e}"]

    now = _now_iso()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO authority_decisions (id, mission_id, operation_id, decision, policy_ref, decided_at, detail, requested_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"authdec_{operation_id}_{now}", row["mission_id"], operation_id,
                "ALLOW" if allowed else "DENY", lease_id, now,
                "; ".join(decision_reasons) if decision_reasons else None, requested_by,
            ),
        )
        cur.execute(
            """
            INSERT INTO approvals (id, mission_id, operation_id, requested_at, decided_at, decision, decided_by, reason, lease_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"appr_{operation_id}_{now}", row["mission_id"], operation_id, row["requested_at"],
                now, "APPROVED" if allowed else "REJECTED", approved_by, reason, lease_id,
            ),
        )
        if allowed:
            cur.execute(
                "UPDATE operations SET status='AUTHORIZED', authorized_at=%s WHERE id=%s AND status='REQUESTED'",
                (now, operation_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise OperationStoreError(f"operation {operation_id} status changed unexpectedly during authorization")

    conn.commit()
    return get_operation(conn, operation_id), allowed  # type: ignore[return-value]


def start_and_execute_operation(conn, operation_id: str, executor) -> dict:
    """Starts and executes an AUTHORIZED operation exactly once. If the
    operation is already STARTED, SUCCEEDED, FAILED, or CANCELLED, the
    current row is returned WITHOUT calling the executor again -- this
    is the mechanism that makes 'retry after lost response performs no
    duplicate side effect' true (spec sections 10, 16.G)."""
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM operations WHERE id = %s", (operation_id,))
        row = cur.fetchone()
    if row is None:
        raise OperationNotFoundError(f"No such operation: {operation_id}")
    if row["status"] in _NO_EXECUTOR_RECALL_STATES:
        return get_operation(conn, operation_id)  # type: ignore[return-value]
    if row["status"] != "AUTHORIZED":
        raise OperationStateError(f"cannot start operation {operation_id} in status {row['status']}")

    # Transition to STARTED and commit BEFORE calling the executor --
    # an external side effect of arbitrary duration should never hold
    # a database transaction/lock open.
    try:
        _write_operation_transition(conn, operation_id, "STARTED")
    except OperationStateError:
        # Concurrency race: another caller's FOR UPDATE-protected
        # transition won between our unlocked read above and this
        # attempt. That is NOT an error for this caller -- it is
        # exactly spec section 15's required behavior ("the other
        # worker reconciles/observes existing state rather than
        # performing the side effect again"). Re-check the row's
        # ACTUAL current state: if a concurrent winner already moved
        # it past AUTHORIZED, return gracefully without recalling the
        # executor; any other illegal-transition cause is a real
        # error and still propagates.
        conn.rollback()
        current = get_operation(conn, operation_id)
        if current is not None and current["status"] in _NO_EXECUTOR_RECALL_STATES:
            return current
        raise
    except OperationStoreError:
        conn.rollback()
        raise
    conn.commit()

    operation = get_operation(conn, operation_id)
    assert operation is not None
    from orca.mission.executor import ExecutionFailed  # local import -- avoids a hard dependency for callers who never execute

    try:
        result_ref = executor.execute(operation_id=operation_id, kind=operation["kind"], mission_id=operation["mission_id"])
    except ExecutionFailed as e:
        try:
            _write_operation_transition(conn, operation_id, "FAILED", result_ref=str(e))
        except OperationStoreError:
            conn.rollback()
            raise
        conn.commit()
        return get_operation(conn, operation_id)  # type: ignore[return-value]

    try:
        _write_operation_transition(conn, operation_id, "SUCCEEDED", result_ref=result_ref)
    except OperationStoreError:
        conn.rollback()
        raise
    conn.commit()
    return get_operation(conn, operation_id)  # type: ignore[return-value]
