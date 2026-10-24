"""Fail-closed helpers for untrusted agent and tool text.

None of these helpers grants authority or writes a training corpus.
"""
from __future__ import annotations

from orca.pretrain_foundation.governed_handlers import screen_untrusted


def deliver_agent_message(text: str) -> dict:
    """An agent message is data. It does not become a system instruction."""
    screened = screen_untrusted({"text": text})
    admitted = bool(screened.get("admitted"))
    return {
        "as_instruction": False,
        "authority_changed": False,
        "admitted": admitted,
        "text": screened.get("text") if admitted else None,
    }


def hidden_eval_leak(text: str, hidden: list[str] | tuple[str, ...]) -> bool:
    """True when hidden evaluation text appears inside a candidate."""
    folded = text.casefold()
    return any(item and item.casefold() in folded for item in hidden)


class EffectLedger:
    """Record one irreversible effect per key. A replay does not apply it again."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def apply(self, key: str, effect: str) -> dict:
        if not key:
            return {"applied": False, "duplicate": False, "reason": "missing effect key"}
        prior = self._seen.get(key)
        if prior is not None:
            return {"applied": False, "duplicate": True, "effect": prior}
        self._seen[key] = effect
        return {"applied": True, "duplicate": False, "effect": effect}
