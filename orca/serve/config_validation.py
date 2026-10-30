"""Production configuration validation (Workstream A).

`validate_production_config()` is run once at server import (`orca/serve/api.py`). In a production-like deployment (`ORNEUR_PUBLIC_EDGE` set, or the
DISTRIBUTED profile) any ERROR finding aborts startup, so a misconfigured public deployment fails to boot instead of failing at the first login, or
worse, serving with a forgeable secret. WARN findings are returned for the readiness endpoint and logs; they never contain secret values.

Fixes over the previous scattered checks: the auth secret is validated at STARTUP (it used to fail only when a token was first signed); a wildcard
trusted-host list, unsigned Stripe webhooks, exception-detail logging and a missing metrics token are now refused on a public edge.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.config import orneur_env


class ProductionConfigError(RuntimeError):
    """Startup aborted; the message lists finding codes only (no values)."""


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str          # "ERROR" | "WARN"
    message: str

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message}


def _truthy(name: str) -> bool:
    return orneur_env(name, "").strip().lower() in ("1", "true", "yes")


def collect_findings() -> list[Finding]:
    from orca.auth.secret import AuthSecretError, is_production_like, validate_auth_secret_config

    out: list[Finding] = []
    prod = is_production_like()
    public = _truthy("PUBLIC_EDGE")

    try:
        validate_auth_secret_config()
    except AuthSecretError as e:
        out.append(Finding("AUTH_SECRET", "ERROR" if prod else "WARN", str(e)))

    # L02-04: email verification and recovery depend on a delivery path. A request for verification with none is refused loudly (the gate stays OFF so nobody is locked
    # out); a local sink is not delivery and must not back a public edge.
    from orca.auth import email as _mail
    from orca.auth.account_security import verification_requested

    if verification_requested() and _mail.delivery_mode() == "none":
        out.append(Finding("EMAIL_VERIFICATION_NO_DELIVERY", "ERROR" if prod else "WARN",
                           "ORNEUR_REQUIRE_EMAIL_VERIFICATION is set but no email delivery is configured (SMTP_HOST/SMTP_USER/SMTP_PASS); verification is NOT enforced"))
    if public and _mail.delivery_mode() == "local_sink":
        out.append(Finding("EMAIL_LOCAL_SINK_ON_PUBLIC_EDGE", "ERROR", "ORNEUR_MAIL_SINK_DIR is a local file sink that delivers to nobody; it must not be used on a public edge"))

    if public:
        origins = orneur_env("ALLOWED_ORIGINS", "*").strip()
        if not origins or origins == "*":
            out.append(Finding("ALLOWED_ORIGINS", "ERROR", "ORNEUR_ALLOWED_ORIGINS must be an explicit list on a public edge"))
        hosts = orneur_env("TRUSTED_HOSTS", "").strip()
        if not hosts or hosts == "*":
            out.append(Finding("TRUSTED_HOSTS", "ERROR", "ORNEUR_TRUSTED_HOSTS must name the public hostnames on a public edge (Host-header abuse)"))
        if _truthy("ALLOW_UNSIGNED_WEBHOOKS"):
            out.append(Finding("UNSIGNED_WEBHOOKS", "ERROR", "unsigned payment webhooks must not be accepted on a public edge"))
        if orneur_env("LOG_EXCEPTION_DETAIL", "") == "1":
            out.append(Finding("EXCEPTION_DETAIL_LOGGING", "ERROR", "exception-detail logging is a local-debugging switch and must be off on a public edge"))
        token = orneur_env("METRICS_TOKEN", "")
        if len(token) < 32:
            out.append(Finding("METRICS_TOKEN", "WARN", "no ORNEUR_METRICS_TOKEN (>= 32 chars): /metrics is closed on a public edge until one is set"))
        if not orneur_env("REDIS_URL", ""):
            out.append(Finding("RATE_LIMIT_STORE", "WARN", "no shared rate-limit store: per-process counters are not enforced across workers/replicas"))
        if not orneur_env("DATABASE_URL", ""):
            out.append(Finding("DATABASE", "WARN", "SQLite auth database on a public edge: single-instance only; use a shared database for replicas"))
        try:
            from orca.auth.bootstrap import owner_exists

            if not owner_exists():
                out.append(Finding("OWNER_NOT_INITIALIZED", "WARN", "no owner exists: ordinary signup is closed until `python -m orca.auth.bootstrap issue` is redeemed"))
        except Exception:
            out.append(Finding("OWNER_STATE_UNKNOWN", "WARN", "owner bootstrap state could not be read"))
    return out


def validate_production_config() -> list[Finding]:
    """Raises ProductionConfigError on any ERROR finding when production-like; returns all findings otherwise."""
    from orca.auth.secret import is_production_like

    findings = collect_findings()
    errors = [f for f in findings if f.severity == "ERROR"]
    if errors and is_production_like():
        raise ProductionConfigError("production configuration refused: " + ", ".join(f.code for f in errors))
    return findings


def summary(findings: list[Finding]) -> dict:
    return {"errors": [f.code for f in findings if f.severity == "ERROR"], "warnings": [f.code for f in findings if f.severity == "WARN"]}
