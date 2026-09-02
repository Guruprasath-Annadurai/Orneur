"""
Episodic Ledger (Phase 5 spec §8) -- append-only, distinct from
orca/brain/memory.py's EpisodicMemory (which overwrites its one JSON
file in full on every save(), the opposite of a ledger). A correction
creates a NEW linked episode; nothing here rewrites a prior episode's
own record in place.

Storage: one JSONL file per (scope, scope_id) pair under
ORCA_HOME/memory/episodic/ -- append-only by construction (opening in
"a" mode, one JSON object per line). No database dependency, matching
the project's existing "disk-backed JSON/JSONL" convention (DocStore's
keyword fallback, orca/brain/knowledge_graph.py) rather than introducing
a new storage backend for this alone (spec §49).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from orca.config import ORCA_HOME
from orca.memory.contracts import (
    EpistemicState,
    MemoryEpisode,
    MemoryLifecycleState,
    MemoryScope,
    PrivacyClass,
    content_hash,
)

EPISODIC_DIR = ORCA_HOME / "memory" / "episodic"
EPISODIC_DIR.mkdir(parents=True, exist_ok=True)


def _ledger_path(scope: MemoryScope, scope_id: str) -> Path:
    """Hash the scope_id into the filename rather than using it directly
    -- scope_id is caller-supplied (a session_id, user_id, etc.) and must
    never be interpreted as a filesystem path (same discipline as
    orca/docs/store.py's collection-name derivation)."""
    safe = hashlib.sha256(f"{scope.value}:{scope_id}".encode()).hexdigest()[:24]
    return EPISODIC_DIR / f"{safe}.jsonl"


def append_episode(episode: MemoryEpisode) -> MemoryEpisode:
    """Idempotent by content_hash (spec §51): re-appending an episode
    whose content_hash already exists in this scope's ledger is a no-op
    that returns the existing record's memory_id rather than creating a
    duplicate -- processing the same event twice (e.g. a retried request)
    must not create two equivalent episodes."""
    if not episode.content_hash:
        episode.content_hash = content_hash(
            f"{episode.event}|{episode.context}|{episode.outcome}|{'|'.join(episode.actions)}"
        )
    path = _ledger_path(episode.scope, episode.scope_id)
    for existing in _read_all(path):
        if existing.content_hash == episode.content_hash:
            return existing
    with open(path, "a") as f:
        f.write(json.dumps(asdict(episode)) + "\n")
    return episode


def _evidence_from_dict(d: dict) -> "MemoryEvidence":
    from orca.memory.contracts import MemoryEvidence
    return MemoryEvidence(**d)


def _read_all(path: Path) -> list[MemoryEpisode]:
    if not path.exists():
        return []
    episodes = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            data.pop("memory_type", None)
            data["scope"] = MemoryScope(data["scope"])
            data["epistemic_state"] = EpistemicState(data["epistemic_state"])
            data["lifecycle_state"] = MemoryLifecycleState(data["lifecycle_state"])
            data["privacy"] = PrivacyClass(data["privacy"])
            data["evidence_refs"] = [_evidence_from_dict(e) for e in data.get("evidence_refs", [])]
            episodes.append(MemoryEpisode(**data))
    return episodes


def list_episodes(scope: MemoryScope, scope_id: str) -> list[MemoryEpisode]:
    return _read_all(_ledger_path(scope, scope_id))


def get_episode(scope: MemoryScope, scope_id: str, memory_id: str) -> MemoryEpisode | None:
    for ep in list_episodes(scope, scope_id):
        if ep.memory_id == memory_id:
            return ep
    return None


def delete_episode(scope: MemoryScope, scope_id: str, memory_id: str) -> bool:
    """Privacy-safe tombstone (spec §29, §38), not a silent full removal:
    the episode's content fields are redacted and lifecycle_state is set
    to PURGED, but the ledger LINE remains (memory_id, timestamps,
    scope) -- callers holding a source_ref to this episode_id can still
    tell "this existed and was deleted" apart from "this id never
    existed", which orca/memory/consolidation.py's derived-memory
    re-evaluation (spec §39) depends on."""
    path = _ledger_path(scope, scope_id)
    episodes = _read_all(path)
    found = False
    rewritten = []
    for ep in episodes:
        if ep.memory_id == memory_id:
            found = True
            ep.actors, ep.event, ep.context = [], "", ""
            ep.actions, ep.observations, ep.outcome = [], [], ""
            from orca.memory.contracts import MemoryLifecycleState
            ep.lifecycle_state = MemoryLifecycleState.PURGED
        rewritten.append(ep)
    if not found:
        return False
    with open(path, "w") as f:
        for ep in rewritten:
            f.write(json.dumps(asdict(ep)) + "\n")
    return True


def delete_ledger(scope: MemoryScope, scope_id: str) -> bool:
    """Full ledger removal for a scope -- used by account deletion (spec
    §38). Returns whether a ledger actually existed to delete."""
    path = _ledger_path(scope, scope_id)
    if path.exists():
        path.unlink()
        return True
    return False
