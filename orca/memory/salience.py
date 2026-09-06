"""
Memory salience and staleness (Phase 5 spec §27, §30-31). Deterministic,
no Gateway call -- these run on every recall, so they stay cheap
(spec §48).
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from orca.memory.contracts import EpistemicState, FailureMemoryRecord, MemoryLifecycleState, MemoryRecord, ProceduralMemoryRecord

_EPISTEMIC_WEIGHT = {
    EpistemicState.KNOWN: 1.0,
    EpistemicState.SUPPORTED: 0.9,
    EpistemicState.PROBABLE: 0.6,
    EpistemicState.CONTESTED: 0.4,
    EpistemicState.STALE: 0.3,
    EpistemicState.UNVERIFIED: 0.5,
    EpistemicState.UNKNOWN: 0.3,
    EpistemicState.DISPROVEN: 0.0,
}

# Facts matching these patterns should become stale FASTER than stable
# knowledge (spec §31's own example list) -- a shorter TTL, not a
# different mechanism.
_VOLATILE_FACT_RE = re.compile(
    r"\b(pric(e|ing)|version|available?|availability|personnel|deployment|deployed|on-call|staff(ed|ing)?)\b",
    re.IGNORECASE,
)

_STABLE_TTL_SECONDS = 90 * 24 * 3600     # 90 days -- e.g. "the project is named Atlas"
_VOLATILE_TTL_SECONDS = 3 * 24 * 3600    # 3 days -- e.g. pricing/version/availability facts

# Mathematical truths, verified historical events, and explicit long-term
# user decisions never decay (spec §30) -- approximated here by
# epistemic_state=KNOWN combined with an explicit "decision"/"always"
# marker in the claim text, since this codebase has no separate
# "this is a mathematical truth" flag. Documented as a heuristic, not a
# claim of perfect classification.
_NEVER_DECAY_RE = re.compile(r"\b(always|permanently|by definition|is defined as)\b", re.IGNORECASE)


def _parse_iso(ts: str) -> float:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def is_stale(record: MemoryRecord, claim_text: str = "") -> bool:
    """Never decays a record that's explicitly marked DISPROVEN (already
    the strongest possible state) or one matching the never-decay
    pattern. Otherwise compares the record's own last-verified timestamp
    (falls back to updated_at) against a class-specific TTL."""
    if record.epistemic_state == EpistemicState.STALE:
        return True
    if record.epistemic_state == EpistemicState.DISPROVEN:
        return False
    if _NEVER_DECAY_RE.search(claim_text):
        return False

    last_verified = getattr(record, "last_verified_at", None) or record.updated_at
    age_seconds = time.time() - _parse_iso(last_verified)
    ttl = _VOLATILE_TTL_SECONDS if _VOLATILE_FACT_RE.search(claim_text) else _STABLE_TTL_SECONDS
    return age_seconds > ttl


def compute_salience(record: MemoryRecord, relevance_score: float = 0.0, claim_text: str = "") -> float:
    """Combines relevance, recurrence-via-source-count, consequence
    (failure severity / high evidence quality), confidence/epistemic
    state, and recency -- explicitly NOT recency-dominated (spec §27): an
    old CRITICAL failure memory can outrank a merely recent one via the
    consequence term, since recency here contributes at most 0.15 of the
    total while consequence contributes up to 0.3."""
    epistemic_weight = _EPISTEMIC_WEIGHT.get(record.epistemic_state, 0.3)
    confidence = record.confidence if record.confidence is not None else epistemic_weight

    recurrence = min(1.0, len(record.source_refs) / 3.0)   # more corroborating episodes -> more salient, capped

    consequence = 0.0
    if isinstance(record, FailureMemoryRecord):
        consequence = 0.6 if "production" in claim_text.lower() or "security" in claim_text.lower() else 0.3
    elif isinstance(record, ProceduralMemoryRecord):
        total = record.successful_executions + record.failed_executions
        consequence = (record.successful_executions / total) if total else 0.0
    evidence_bonus = min(0.3, 0.1 * len(record.evidence_refs))

    age_seconds = max(0.0, time.time() - _parse_iso(record.updated_at))
    recency = max(0.0, 1.0 - min(1.0, age_seconds / _STABLE_TTL_SECONDS))

    lifecycle_penalty = 0.0 if record.lifecycle_state == MemoryLifecycleState.ACTIVE else 0.5

    score = (
        0.30 * relevance_score + 0.20 * confidence + 0.15 * recurrence
        + 0.20 * (consequence + evidence_bonus) + 0.15 * recency
    ) - lifecycle_penalty
    return max(0.0, min(1.0, score))
