"""
Phase 14A.3 -- closes a real, disclosed cloud-blocking configuration
hazard: in DISTRIBUTED mode, if `ORNEUR_SECURITY_ROOT_DATABASE_URL` was
absent, `orca.godmode.security_root._backend()` silently fell back to
per-host file storage. On a genuine multi-host deployment this creates
MULTIPLE INDEPENDENT kill-switch/security-root authorities -- exactly
the class of bug the security root itself exists to prevent, just one
layer up. Phase 14A.2's own closure disclosed this as a known
limitation ("In DISTRIBUTED mode, if ORNEUR_SECURITY_ROOT_DATABASE_URL
is left unset, the security root silently falls back to the SOVEREIGN
file-based mechanism per host").

This module is the single, centralized place that decides ORNEUR's
deployment profile and enforces what each profile requires, so "no
silent fallback" is impossible BY CONSTRUCTION rather than by every
caller remembering to check. `orca.godmode.security_root._backend()`
and `orca.godmode.lease_store._backend()` both call into
`require_distributed_security_root_url()` /
`require_distributed_authority_url()` respectively when
`is_distributed()` is true -- meaning even a caller who never heard of
this module cannot silently get file-based fallback in DISTRIBUTED
mode; the backend-selection function itself raises.

No connection string is ever included in a raised error message or log
line (spec §6's explicit "do not echo connection strings containing
credentials") -- messages name which backend is missing/invalid/
unreachable, never the URL's contents.
"""
from __future__ import annotations

from orca.config import orneur_env

VALID_PROFILES = ("SOVEREIGN", "DISTRIBUTED")


class DeploymentConfigError(Exception):
    """Raised for any DISTRIBUTED-profile configuration defect: missing,
    empty, malformed, or (during explicit startup validation) unreachable
    critical configuration. Never carries a connection string in its
    message."""


def get_profile() -> str:
    """`ORNEUR_DEPLOYMENT_PROFILE`, defaulting to SOVEREIGN (this
    codebase's zero-config, single-host default -- unchanged for every
    existing developer/self-hosted/offline use case, per spec §4).
    Case-insensitive, whitespace-tolerant; an unrecognized value fails
    immediately rather than silently defaulting (spec §5's "Unknown
    profile: fail startup")."""
    raw = orneur_env("DEPLOYMENT_PROFILE", "SOVEREIGN").strip().upper()
    if raw not in VALID_PROFILES:
        raise DeploymentConfigError(
            f"Unknown ORNEUR_DEPLOYMENT_PROFILE={raw!r} -- must be one of {VALID_PROFILES}."
        )
    return raw


def is_distributed() -> bool:
    return get_profile() == "DISTRIBUTED"


def _looks_like_postgres_dsn(url: str) -> bool:
    """Deliberately conservative: only a recognized scheme counts as a
    "supported backend" (spec §2's "resolves to an unsupported
    backend" failure case). Does not, and cannot, verify the DSN
    actually points at a database this deployment owns (spec §10:
    "Do not claim ability to detect a semantically wrong-but-valid
    database... unless there is an existing deployment/cluster
    identity mechanism" -- none exists in this codebase, so this
    module does not pretend to check for one)."""
    return url.startswith("postgresql://") or url.startswith("postgres://")


def require_distributed_security_root_url() -> str:
    """Raises DeploymentConfigError (no connection string in the
    message) unless a well-formed shared security-root URL is
    configured. This is the actual enforcement point
    `security_root._backend()` calls -- not merely an optional
    advisory check a caller might forget to run."""
    url = orneur_env("SECURITY_ROOT_DATABASE_URL")
    if not url or not url.strip():
        raise DeploymentConfigError(
            "DISTRIBUTED profile requires an explicitly configured shared security-root backend "
            "(set ORNEUR_SECURITY_ROOT_DATABASE_URL) -- local per-host security-root storage is not "
            "valid in DISTRIBUTED mode."
        )
    if not _looks_like_postgres_dsn(url):
        raise DeploymentConfigError(
            "DISTRIBUTED profile's security-root backend URL does not resolve to a supported backend "
            "(expected a postgresql:// DSN)."
        )
    return url


def require_distributed_authority_url() -> str:
    """Same enforcement, for the Godmode authority (lease) backend
    (spec §6's "shared authority backend where architecture requires
    it" -- Phase 14A already established Postgres is required for
    DISTRIBUTED lease correctness; this makes that requirement
    fail-fast rather than merely documented)."""
    url = orneur_env("GODMODE_DATABASE_URL")
    if not url or not url.strip():
        raise DeploymentConfigError(
            "DISTRIBUTED profile requires an explicitly configured shared Godmode authority backend "
            "(set ORNEUR_GODMODE_DATABASE_URL) -- local per-host authority storage is not valid in "
            "DISTRIBUTED mode."
        )
    if not _looks_like_postgres_dsn(url):
        raise DeploymentConfigError(
            "DISTRIBUTED profile's Godmode authority backend URL does not resolve to a supported "
            "backend (expected a postgresql:// DSN)."
        )
    return url


def validate_deployment_config(*, check_connectivity: bool = True) -> dict:
    """Mandatory startup validation (spec §2, §6). Intended to be called
    once, early, by the actual server process (see
    `orca/serve/api.py`) so a misconfigured DISTRIBUTED deployment
    fails to start rather than silently serving with a broken/absent
    security root. Raises `DeploymentConfigError` on any defect,
    including (when `check_connectivity=True`) a real connection
    attempt to each required backend -- an unreachable backend at
    startup is treated exactly like a missing one, per spec §2's
    "unreachable during mandatory startup validation" failure case.

    Returns a small, secret-free summary dict suitable for a startup
    log line.
    """
    profile = get_profile()
    if profile == "SOVEREIGN":
        return {"profile": "SOVEREIGN", "security_root_backend": "sqlite", "authority_backend": "sqlite"}

    security_root_url = require_distributed_security_root_url()
    authority_url = require_distributed_authority_url()

    if check_connectivity:
        import psycopg

        for label, url in (("security-root", security_root_url), ("authority", authority_url)):
            try:
                conn = psycopg.connect(url, connect_timeout=5)
                conn.close()
            except Exception:
                # Deliberately re-raised as a NEW exception (not
                # `raise ... from e`) -- psycopg's own exception message
                # can include the DSN/host/credentials; re-raising fresh
                # guarantees nothing from the original exception (which
                # may be logged elsewhere with less care) propagates
                # into this message.
                raise DeploymentConfigError(
                    f"DISTRIBUTED profile's {label} backend is unreachable during startup validation."
                ) from None

    return {"profile": "DISTRIBUTED", "security_root_backend": "postgres", "authority_backend": "postgres"}
