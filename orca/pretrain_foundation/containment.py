"""Fail-closed helpers for untrusted agent and tool text.

None of these helpers grants authority or writes a training corpus.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.pretrain_foundation.artifact_guard import ArtifactBoundaryError, atomic_write_regular, read_regular_nofollow
from orca.pretrain_foundation.governed_handlers import screen_untrusted


class EffectLedgerError(Exception):
    """The durable effect record cannot be trusted."""


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
    """Record one irreversible effect per key.

    A pathless ledger exists only in this process. Pass a path to keep the
    keys across a new instance. The file is not a signature. A symlink or
    an unreadable file refuses the ledger instead of starting empty.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._seen: dict[str, str] = {}
        if self.path is not None:
            self._load()

    @property
    def durable(self) -> bool:
        return self.path is not None

    def _load(self) -> None:
        assert self.path is not None
        if not self.path.exists():
            return
        try:
            raw = read_regular_nofollow(self.path)
        except ArtifactBoundaryError as exc:
            raise EffectLedgerError("durable effect ledger is not a regular file") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise EffectLedgerError("durable effect ledger is unreadable") from exc
        if not isinstance(data, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in data.items()):
            raise EffectLedgerError("durable effect ledger is unreadable")
        self._seen = dict(data)

    def _store(self) -> None:
        assert self.path is not None
        payload = json.dumps(self._seen, sort_keys=True, separators=(",", ":")).encode("utf-8")
        atomic_write_regular(self.path, payload)

    def apply(self, key: str, effect: str) -> dict:
        if not key:
            return {"applied": False, "duplicate": False, "durable": self.durable, "reason": "missing effect key"}
        prior = self._seen.get(key)
        if prior is not None:
            return {"applied": False, "duplicate": True, "durable": self.durable, "effect": prior}
        self._seen[key] = effect
        if self.path is not None:
            self._store()
        return {"applied": True, "duplicate": False, "durable": self.durable, "effect": effect}
