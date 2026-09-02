"""
Orca Memory Engine — four-layer memory architecture.

Short-term  : in-context message history (sliding window)
Long-term   : disk-backed ChromaDB vector store
Episodic    : structured session logs with metadata
Semantic    : distilled facts/concepts across sessions
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import diskcache

from orca.config import MEMORY_DIR, CACHE_DIR


@dataclass
class Message:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass
class Episode:
    session_id: str
    messages: list[Message]
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class ShortTermMemory:
    """Sliding-window in-context history."""

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self._messages: list[Message] = []

    def add(self, role: str, content: str, **meta) -> None:
        self._messages.append(Message(role=role, content=content, metadata=meta))
        if len(self._messages) > self.max_turns * 2:
            # Keep last max_turns exchanges
            self._messages = self._messages[-(self.max_turns * 2):]

    def to_api_messages(self) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in self._messages]

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)


class LongTermMemory:
    """ChromaDB vector store for semantic retrieval across sessions.
    Falls back to simple JSON search if chromadb is not installed."""

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._fallback_file = MEMORY_DIR / "vectors" / f"{session_id[:8]}.jsonl"
        try:
            import chromadb
            Path(str(MEMORY_DIR / "vectors")).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(MEMORY_DIR / "vectors"))
            self._collection = self._client.get_or_create_collection(
                name=f"orca_{session_id[:8]}",
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
        except ImportError:
            self._available = False
            self._fallback_file.parent.mkdir(parents=True, exist_ok=True)

    def store(self, text: str, metadata: dict | None = None) -> str:
        if self._available:
            doc_id = str(uuid.uuid4())
            # A real production bug, found via load testing: newer chromadb
            # versions reject an EMPTY metadata dict outright ("Expected
            # metadata to be a non-empty dict") — every commit_to_long_term()
            # call with no explicit metadata (the normal case) crashed the
            # whole request. Always include at least a timestamp so the
            # dict is never empty, regardless of what the caller passed.
            stored_metadata = dict(metadata) if metadata else {}
            stored_metadata.setdefault("stored_at", time.time())
            self._collection.add(
                documents=[text],
                ids=[doc_id],
                metadatas=[stored_metadata],
            )
            return doc_id
        # Fallback: append to JSONL
        with open(self._fallback_file, "a") as f:
            f.write(json.dumps({"text": text, "metadata": metadata or {}}) + "\n")
        return ""

    def recall(self, query: str, n: int = 5) -> list[dict]:
        if self._available:
            results = self._collection.query(query_texts=[query], n_results=n)
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            return [{"text": d, "metadata": m} for d, m in zip(docs, metas)]
        # Fallback: keyword search over JSONL
        if not self._fallback_file.exists():
            return []
        hits = []
        query_words = set(query.lower().split())
        with open(self._fallback_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    text = entry.get("text", "")
                    score = sum(1 for w in query_words if w in text.lower())
                    if score > 0:
                        hits.append((score, entry))
                except json.JSONDecodeError:
                    continue
        hits.sort(key=lambda x: x[0], reverse=True)
        return [h[1] for h in hits[:n]]

    def delete(self) -> bool:
        """Phase 5.1 (docs/orneur/phase-5/LEGACY_MEMORY_AUTHORITY_AUDIT.md):
        a real, confirmed gap -- this class had NO deletion method at
        all, and orca/serve/account_delete.py never touched it, meaning
        every raw Q:/A: turn ever written via commit_to_long_term()
        (which runs unconditionally on every chat/stream/ultra turn)
        persisted in this session's ChromaDB collection FOREVER, even
        after a full account deletion. Removes the collection (or the
        JSONL fallback file). Returns whether anything was actually
        found and removed."""
        if self._available:
            try:
                self._client.delete_collection(name=f"orca_{self._session_id[:8]}")
                return True
            except Exception:
                return False
        if self._fallback_file.exists():
            self._fallback_file.unlink()
            return True
        return False


class EpisodicMemory:
    """Structured session logs stored as JSON files."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.path = MEMORY_DIR / "episodes" / f"{session_id}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, episode: Episode) -> None:
        with open(self.path, "w") as f:
            json.dump(
                {
                    "session_id": episode.session_id,
                    "messages": [asdict(m) for m in episode.messages],
                    "summary": episode.summary,
                    "tags": episode.tags,
                    "created_at": episode.created_at,
                },
                f,
                indent=2,
            )

    def load(self) -> Episode | None:
        if not self.path.exists():
            return None
        with open(self.path) as f:
            data = json.load(f)
        msgs = [Message(**m) for m in data["messages"]]
        return Episode(
            session_id=data["session_id"],
            messages=msgs,
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            created_at=data.get("created_at", 0),
        )

    @classmethod
    def list_sessions(cls) -> list[str]:
        ep_dir = MEMORY_DIR / "episodes"
        if not ep_dir.exists():
            return []
        return [p.stem for p in sorted(ep_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)]


class SemanticMemory:
    """Distilled facts/concepts persisted across all sessions via disk cache."""

    def __init__(self):
        self._cache = diskcache.Cache(str(CACHE_DIR / "semantic"))

    def store_fact(self, key: str, value: Any) -> None:
        self._cache[f"fact:{key}"] = value

    def recall_fact(self, key: str) -> Any | None:
        return self._cache.get(f"fact:{key}")

    def store_concept(self, concept: str, description: str) -> None:
        existing = self._cache.get("concepts", {})
        existing[concept] = description
        self._cache["concepts"] = existing

    def all_concepts(self) -> dict[str, str]:
        return self._cache.get("concepts", {})

    def delete_session_facts(self, session_id: str) -> bool:
        """Phase 5 (docs/orneur/phase-5/CURRENT_MEMORY_ARCHITECTURE.md's
        Finding: this store was entirely missing from
        orca/serve/account_delete.py's deletion cascade before this fix).

        Removes this session's own `fact:session_{id[:8]}` key, AND strips
        this session's block out of the shared `all_sessions_summary`
        string -- distill_and_save() merges every session's distilled
        summary into ONE global string tagged with "[Session {id[:8]}]"
        markers, so a plain per-session key deletion alone would leave
        this session's content sitting inside that merged blob forever.
        Returns whether anything was actually found and removed.
        """
        removed = False
        session_key = f"fact:session_{session_id[:8]}"
        if session_key in self._cache:
            del self._cache[session_key]
            removed = True

        merged = self._cache.get("fact:all_sessions_summary", "")
        marker = f"[Session {session_id[:8]}]"
        if marker in merged:
            import re
            # Split on each "[Session <id>]" header, keeping the header
            # attached to its own block, regardless of whether it's the
            # first block in the string or not.
            parts = re.split(r"(?=\[Session )", merged)
            kept = [p for p in parts if p.strip() and not p.startswith(marker)]
            self._cache["fact:all_sessions_summary"] = "\n\n".join(p.strip() for p in kept).strip()
            removed = True
        return removed


class MemoryEngine:
    """Unified interface over all four memory layers."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.short = ShortTermMemory()
        self.long = LongTermMemory(self.session_id)
        self.episodic = EpisodicMemory(self.session_id)
        self.semantic = SemanticMemory()

    def add_turn(self, role: str, content: str) -> None:
        self.short.add(role, content)

    def recall_context(self, query: str, n: int = 3) -> str:
        hits = self.long.recall(query, n=n)
        if not hits:
            return ""
        lines = [f"[Memory] {h['text']}" for h in hits]
        return "\n".join(lines)

    def commit_to_long_term(self, text: str, meta: dict | None = None) -> None:
        self.long.store(text, meta)

    def save_session(self, summary: str = "", tags: list[str] | None = None) -> None:
        ep = Episode(
            session_id=self.session_id,
            messages=self.short._messages,
            summary=summary,
            tags=tags or [],
        )
        self.episodic.save(ep)

    def load_session(self, session_id: str) -> bool:
        ep_mem = EpisodicMemory(session_id)
        ep = ep_mem.load()
        if not ep:
            return False
        self.session_id = session_id
        for m in ep.messages:
            self.short._messages.append(m)
        return True

    def messages(self) -> list[dict]:
        return self.short.to_api_messages()

    def distill_and_save(self, brain) -> str:
        """Summarize session into semantic facts. Call at session end.

        Phase 5.1 (docs/orneur/phase-5/LEGACY_MEMORY_AUTHORITY_AUDIT.md):
        this used to ALSO merge every session's distilled summary into one
        shared, unscoped `all_sessions_summary` string -- readable by ANY
        session via load_prior_context(), including through the
        `memory_recall` agent tool on the multi-tenant web serving path
        (orca/tools/__init__.py::_recall_memory_engine). That was a real,
        confirmed cross-session (and, in a multi-user deployment,
        cross-user) read path with zero scope check. Retired outright
        (spec §9/§16 option "retire the path") -- no code still needs it,
        and it never went through MemoryArbiter/evidence-lineage/firewall
        governance in the first place.

        The distilled summary is now ALSO routed through Memory
        Continuum's real candidate/promotion pipeline, scoped to this
        session and carrying NO evidence_refs (a raw self-summary of the
        conversation is not verified against anything) -- MemoryArbiter
        promotes it at UNVERIFIED, never KNOWN/SUPPORTED, per spec §9's
        "no silently labeling generated summaries as SUPPORTED or KNOWN".
        The legacy per-session `fact:session_{id[:8]}` key is still
        written too (an explicit, documented dual-write -- see
        docs/orneur/phase-5/MEMORY_MIGRATION.md) since
        orca/variants/core.py's own `/recall` command still reads it
        directly; it is itself session-scoped and was never part of the
        cross-session leak.
        """
        msgs = self.short.to_api_messages()
        if len(msgs) < 2:
            return ""
        history = "\n".join(f"[{m['role'].upper()}]: {m['content'][:300]}" for m in msgs[-20:])
        try:
            summary = brain.complete(
                [{"role": "user", "content": (
                    "Extract the key facts, decisions, goals, and context from this conversation "
                    "that should be remembered for future sessions. Be concise and specific. "
                    "Focus on: user goals, business context, technical decisions, personal preferences.\n\n"
                    f"{history}"
                )}],
                system="You are a memory distiller. Output only a bulleted list of key facts. No preamble.",
                temperature=0.1,
                max_tokens=400,
            )
        except Exception:
            return ""
        self.semantic.store_fact(f"session_{self.session_id[:8]}", summary)
        self.save_session(summary=summary)

        try:
            from orca.memory.arbiter import MemoryArbiter
            from orca.memory.contracts import MemoryCandidate, MemoryScope, MemoryType
            from orca.memory import store as memory_store

            arbiter = MemoryArbiter()
            candidate = MemoryCandidate(
                extracted_claim=summary[:2000], scope=MemoryScope.SESSION, scope_id=self.session_id,
            )
            existing = memory_store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, self.session_id)
            decision, _reasons = arbiter.decide_promotion(candidate, existing)
            if decision.value == "PROMOTED":
                arbiter.promote(candidate)
        except Exception:
            pass  # Memory Continuum promotion is additive -- never blocks the legacy summary from being returned/saved

        return summary

    def load_prior_context(self) -> str:
        """Return this session's own distilled facts -- NEVER another
        session's (see distill_and_save()'s docstring: the old
        cross-session `all_sessions_summary` fallback was a real,
        confirmed unscoped read leak, retired in Phase 5.1)."""
        return self.semantic.recall_fact(f"session_{self.session_id[:8]}") or ""
