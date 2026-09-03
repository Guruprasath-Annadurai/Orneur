"""
Lease tamper-evidence (Phase 10 spec §11). Reuses the codebase's EXISTING
HMAC signing discipline (`orca.auth.tokens`, `orca.license.keys`,
`orca.license.stripe_hook`: `hmac.new(secret, data, sha256)` +
`hmac.compare_digest`) rather than inventing a second cryptographic
primitive. This is a REAL integrity check, not a fabricated guarantee --
it detects modification of any signed field; it is not a claim of
non-repudiation against a party who has the server-side secret.
"""
from __future__ import annotations

import hashlib
import hmac

from orca.config import orneur_env
from orca.godmode.contracts import CapabilityLease

_SECRET = orneur_env("GODMODE_LEASE_SECRET", "dev-secret-change-me")

# The exact, ordered set of fields covered by the signature (spec §11:
# "detect modification of capability, scope, expiry, principal, tenant,
# issuer" at minimum). Deliberately excludes uses_remaining/revocation_state
# (which legitimately change over the lease's life without invalidating
# its origin) and the signature field itself.
_SIGNED_FIELDS = (
    "lease_id", "principal_id", "tenant_id", "capability_domain", "capability",
    "resource_scope", "operation_scope", "issued_at", "expires_at", "issuer",
    "issuer_id", "approval_id", "max_uses", "delegable", "nonce",
    # Phase 10.1 (spec §7): the argument binding is part of the lease's
    # tamper-evident payload -- modifying arguments_hash OR binding_mode
    # after issuance must invalidate integrity, exactly like modifying
    # capability/resource/operation does.
    "arguments_hash", "binding_mode",
)


def _canonical_payload(lease: CapabilityLease) -> str:
    parts = []
    for name in _SIGNED_FIELDS:
        value = getattr(lease, name)
        domain_value = value.value if hasattr(value, "value") else value
        parts.append(f"{name}={domain_value}")
    return "\x1f".join(parts)


def sign_lease(lease: CapabilityLease) -> str:
    payload = _canonical_payload(lease)
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def apply_signature(lease: CapabilityLease) -> CapabilityLease:
    lease.signature = sign_lease(lease)
    return lease


def verify_lease_integrity(lease: CapabilityLease) -> bool:
    """True only if `lease.signature` matches a fresh signature computed
    over the lease's CURRENT signed fields -- any modification to
    capability/scope/expiry/principal/tenant/issuer/nonce/etc since
    issuance is detected here. Constant-time comparison (spec §11's
    "tamper-evident", same discipline as `orca.auth.tokens`)."""
    if not lease.signature:
        return False
    expected = sign_lease(lease)
    return hmac.compare_digest(lease.signature, expected)
