"""
Output-side DLP scan — real gap this closes: orca/docs/pii_redact.py only
scans DOCUMENT UPLOADS before they enter the RAG vector store. Nothing
scanned what the MODEL actually outputs in a response — if a third
party's PII somehow entered context (a RAG chunk, a memory recall) or a
real secret leaked into a prompt/environment, nothing would catch it
before it reached the user.

Two categories, two different postures, deliberately asymmetric:
  - PII (SSN/email/phone/credit card): reuses pii_redact.py's proven,
    Luhn-validated patterns. FLAGGED for audit visibility, not silently
    redacted — a user's own conversational data (their own email, their
    own phone) legitimately appearing in a response is not a leak, and
    pii_redact.py's own module docstring already makes this exact
    argument for why chat input isn't blanket-redacted. The same logic
    applies to output: flagging preserves governance visibility without
    breaking a legitimate response.
  - SECRETS (API keys, private key blocks, bearer tokens): there is no
    legitimate reason a model response should ever contain a real
    credential. These ARE actively redacted, not just flagged.

HONEST SCOPE: pattern-based, not a trained classifier — same floor-not-
ceiling posture as every other heuristic check in this codebase
(orca/train/redteam.py, orca/serve/moderation.py). Secret patterns can
false-positive on documentation/example code showing a fake key format,
and can miss a real secret in an unrecognized shape.
"""
from __future__ import annotations

import re

from orca.docs.pii_redact import redact_pii

_SECRET_PATTERNS = {
    "openai_api_key": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "anthropic_api_key": re.compile(r"\bsk-ant-[A-Za-z0-9\-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "generic_bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
}


def _redact_secrets(text: str) -> tuple[str, dict]:
    report = {}
    for name, pattern in _SECRET_PATTERNS.items():
        text, count = pattern.subn(f"[REDACTED-{name.upper()}]", text)
        if count:
            report[name] = count
    return text, report


def scan_output(text: str) -> dict:
    """
    Scans an outgoing model response for PII and secret-shaped patterns.

    Returns:
      {
        "safe_text": str,          # text with SECRETS redacted (PII is NOT redacted here — see module docstring)
        "pii_flagged": dict,       # category -> count, PII is flagged not redacted
        "secrets_redacted": dict,  # category -> count, secrets ARE redacted
        "has_findings": bool,
      }

    Callers that want PII actually stripped from what's shown to the user
    (as opposed to just logged for governance visibility) should redact
    using orca.docs.pii_redact.redact_pii directly and make that an
    explicit, deliberate product decision — this function's default
    matches pii_redact.py's own stated reasoning: don't silently mangle a
    user's own data.
    """
    _, pii_report = redact_pii(text)
    pii_report.pop("total", None)
    pii_flagged = {k: v for k, v in pii_report.items() if v > 0}

    safe_text, secrets_report = _redact_secrets(text)

    return {
        "safe_text": safe_text,
        "pii_flagged": pii_flagged,
        "secrets_redacted": secrets_report,
        "has_findings": bool(pii_flagged or secrets_report),
    }
