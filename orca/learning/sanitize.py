"""
PII/secret sanitization before candidate admission (spec §14), reusing
existing redaction infrastructure rather than a second implementation:
orca.serve.dlp.scan_output (PII flagging + secret redaction, output-side
DLP) and orca.connectors.security.redact_secrets (Phase 9's connector
credential-pattern list, a slightly different pattern set worth running
too since it catches Slack/GitHub-shaped tokens dlp.py's own list does
not).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.connectors.security import redact_secrets as _connector_redact_secrets
from orca.serve.dlp import scan_output


@dataclass
class SanitizationResult:
    clean_text: str
    rejected: bool
    pii_flagged: dict = field(default_factory=dict)
    secrets_redacted: dict = field(default_factory=dict)
    reject_reasons: list[str] = field(default_factory=list)


# A curriculum candidate must never carry a live, unredacted credential --
# unlike scan_output's chat-output posture (flag PII, redact secrets), a
# training/eval candidate that would still contain a secret pattern after
# BOTH redaction passes is rejected outright rather than admitted with best-
# effort redaction, since it will be durably persisted and versioned.
def sanitize_for_candidate(text: str) -> SanitizationResult:
    scan = scan_output(text)
    clean = _connector_redact_secrets(scan["safe_text"])

    reject_reasons: list[str] = []
    if "[REDACTED]" in clean or any(v for v in scan["secrets_redacted"].values()):
        # Both passes ran; if a redaction fired at all, do not admit the
        # ORIGINAL secret-bearing text as a candidate even after redaction --
        # secret-shaped content in source material means the event needs
        # human review before this can become a durable, versioned artifact.
        reject_reasons.append("secret pattern detected and redacted -- candidate rejected pending human review, not silently admitted")

    return SanitizationResult(
        clean_text=clean,
        rejected=bool(reject_reasons),
        pii_flagged=scan["pii_flagged"],
        secrets_redacted=scan["secrets_redacted"],
        reject_reasons=reject_reasons,
    )
