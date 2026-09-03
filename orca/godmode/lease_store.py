"""
Capability lease persistence (Phase 10 spec §57-58). File-backed under
`ORCA_HOME/godmode/` -- the same real persistence convention as
`orca.gateway.deployment`'s `ModelDeployment` records -- so active/revoked
leases survive a process restart (spec §58: no accidental "all sessions
become valid" behavior after a restart; an expired/revoked lease read
back from disk is still expired/revoked).

Atomic use-count consumption (spec §35-36): a per-lease-id `threading.Lock`
serializes `consume_use()` so two concurrent callers racing a one-use
lease can never both succeed (verified directly in
`tests/test_godmode_lease_store.py` with real concurrent threads).
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

from orca.config import ORCA_HOME
from orca.godmode.contracts import (
    ArgumentBindingMode,
    CapabilityDomain,
    CapabilityLease,
    LeaseIssuerClass,
    LeaseRevocationState,
    now_iso,
    parse_iso,
)
from orca.godmode.integrity import verify_lease_integrity

LEASE_DIR = ORCA_HOME / "godmode" / "leases"

_locks_guard = threading.Lock()
_lease_locks: dict[str, threading.Lock] = {}


def _lock_for(lease_id: str) -> threading.Lock:
    with _locks_guard:
        return _lease_locks.setdefault(lease_id, threading.Lock())


def _path_for(lease_id: str) -> Path:
    return LEASE_DIR / f"{lease_id}.json"


def _to_dict(lease: CapabilityLease) -> dict:
    d = asdict(lease)
    d["capability_domain"] = lease.capability_domain.value
    d["issuer"] = lease.issuer.value
    d["revocation_state"] = lease.revocation_state.value
    d["binding_mode"] = lease.binding_mode.value
    return d


def _from_dict(d: dict) -> CapabilityLease:
    return CapabilityLease(
        lease_id=d["lease_id"], principal_id=d["principal_id"], tenant_id=d["tenant_id"],
        capability_domain=CapabilityDomain(d["capability_domain"]), capability=d["capability"],
        resource_scope=d["resource_scope"], operation_scope=d["operation_scope"],
        issued_at=d["issued_at"], expires_at=d["expires_at"],
        issuer=LeaseIssuerClass(d["issuer"]), issuer_id=d["issuer_id"], reason=d["reason"],
        approval_id=d.get("approval_id"), max_uses=d.get("max_uses"), uses_remaining=d.get("uses_remaining"),
        delegable=d.get("delegable", False), nonce=d["nonce"],
        revocation_state=LeaseRevocationState(d["revocation_state"]), signature=d.get("signature", ""),
        arguments_hash=d.get("arguments_hash"),
        binding_mode=ArgumentBindingMode(d.get("binding_mode", ArgumentBindingMode.EXACT_ARGUMENTS.value)),
    )


def save(lease: CapabilityLease) -> None:
    LEASE_DIR.mkdir(parents=True, exist_ok=True)
    _path_for(lease.lease_id).write_text(json.dumps(_to_dict(lease), indent=2))


def get(lease_id: str) -> CapabilityLease | None:
    path = _path_for(lease_id)
    if not path.exists():
        return None
    try:
        return _from_dict(json.loads(path.read_text()))
    except Exception:
        return None


def revoke(lease_id: str) -> bool:
    """Immediate revocation (spec §14) -- the lease becomes unusable for
    new actions the instant this returns, regardless of remaining TTL or
    uses_remaining."""
    with _lock_for(lease_id):
        lease = get(lease_id)
        if lease is None:
            return False
        lease.revocation_state = LeaseRevocationState.REVOKED
        save(lease)
        return True


def is_revoked(lease_id: str) -> bool:
    lease = get(lease_id)
    return lease is None or lease.revocation_state == LeaseRevocationState.REVOKED


def is_expired(lease: CapabilityLease, *, at: str | None = None) -> bool:
    reference = parse_iso(at) if at else parse_iso(now_iso())
    try:
        return reference >= parse_iso(lease.expires_at)
    except Exception:
        return True  # fail closed on an unparseable expiry


def consume_use(lease_id: str) -> bool:
    """
    Atomic single-use (or N-use) consumption (spec §35-36). Returns True
    if a use was successfully consumed, False if the lease has no uses
    remaining, is revoked, is expired, fails integrity verification, or
    does not exist -- all fail-closed, never an exception the caller must
    remember to catch.

    A per-lease-id lock makes this atomic across concurrent callers
    within this process: only one of two threads racing the same
    one-use lease can ever observe `uses_remaining == 1 -> 0` and
    proceed; the other sees it already consumed.
    """
    with _lock_for(lease_id):
        lease = get(lease_id)
        if lease is None:
            return False
        if lease.revocation_state == LeaseRevocationState.REVOKED:
            return False
        if is_expired(lease):
            return False
        if not verify_lease_integrity(lease):
            return False
        if lease.max_uses is None:
            return True  # explicitly unmetered lease -- reviewed at issuance
        if lease.uses_remaining is None or lease.uses_remaining <= 0:
            return False
        lease.uses_remaining -= 1
        save(lease)
        return True


def list_active_for_tenant(tenant_id: str) -> list[CapabilityLease]:
    if not LEASE_DIR.exists():
        return []
    leases = []
    for path in LEASE_DIR.glob("*.json"):
        try:
            lease = _from_dict(json.loads(path.read_text()))
        except Exception:
            continue
        if lease.tenant_id != tenant_id:
            continue
        if lease.revocation_state == LeaseRevocationState.REVOKED or is_expired(lease):
            continue
        leases.append(lease)
    return leases
