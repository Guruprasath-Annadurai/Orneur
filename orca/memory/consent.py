"""Explicit memory consent. Existing stores do not call this unless asked."""

from __future__ import annotations


class MemoryConsentError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require_consent(*, user_id: str, granted: bool, purpose: str) -> dict:
    if not user_id:
        raise MemoryConsentError("unauthenticated")
    if not granted:
        raise MemoryConsentError("consent_required")
    if purpose not in {"long_term", "short_term", "search"}:
        raise MemoryConsentError("purpose_refused")
    return {"user_id": user_id, "granted": True, "purpose": purpose}
