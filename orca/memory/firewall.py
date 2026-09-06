"""
Memory Firewall (Phase 5 spec §36, §40). No recalled memory reaches
CognitiveContext without passing through here first. Checks, in order:
scope, permission/privacy, sensitivity, epistemic state, staleness, then
prompt-injection/safety sanitization of the content itself.

Reuses orca.truth.fetch.sanitize_extracted_text's injection-pattern scan
(spec §12's "do not rerun an unrelated second verifier" applies to
security scanning logic too -- one proven pattern list, not a second,
parallel one for memory).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.cognitive.contracts import PrivacyClass
from orca.memory.contracts import EpistemicState, MemoryRecord, MemoryScope
from orca.memory.salience import is_stale
from orca.truth.fetch import sanitize_extracted_text


@dataclass
class FirewallVerdict:
    allowed: bool
    memory_id: str
    reasons: list[str] = field(default_factory=list)
    sanitized_text: str | None = None
    is_stale: bool = False


def _claim_text(record: MemoryRecord) -> str:
    return getattr(record, "claim", None) or getattr(record, "task_context", None) or getattr(record, "name", None) or getattr(record, "event", "")


def check(
    record: MemoryRecord, requesting_scope: MemoryScope, requesting_scope_id: str,
    requester_privacy_clearance: PrivacyClass = PrivacyClass.STANDARD,
) -> FirewallVerdict:
    reasons: list[str] = []

    # 1. Scope check -- memory from one tenant/user/project must not
    # bleed into another (spec §6's critical rule). GLOBAL-scoped memory
    # is the one deliberate exception (platform-wide facts).
    if record.scope != MemoryScope.GLOBAL and (record.scope != requesting_scope or record.scope_id != requesting_scope_id):
        return FirewallVerdict(allowed=False, memory_id=record.memory_id, reasons=["scope_mismatch"])

    # 2. Privacy / permission check.
    _PRIVACY_RANK = {PrivacyClass.STANDARD: 0, PrivacyClass.SENSITIVE: 1, PrivacyClass.RESTRICTED: 2}
    if _PRIVACY_RANK[record.privacy] > _PRIVACY_RANK[requester_privacy_clearance]:
        return FirewallVerdict(allowed=False, memory_id=record.memory_id, reasons=["privacy_clearance_insufficient"])

    # 3. Epistemic state check -- a DISPROVEN memory is never injected as
    # if it were true, no matter how relevant it scored.
    if record.epistemic_state == EpistemicState.DISPROVEN:
        return FirewallVerdict(allowed=False, memory_id=record.memory_id, reasons=["disproven"])

    claim_text = _claim_text(record)

    # 4. Staleness check -- allowed through, but flagged (spec §32: a
    # stale memory should trigger a Truth Fabric refresh upstream, not be
    # silently blocked outright; blocking would make refresh impossible
    # to ever trigger from a recalled-but-stale memory).
    stale = is_stale(record, claim_text)
    if stale:
        reasons.append("stale -- caller should consider a Truth Fabric refresh before treating this as current")

    # 5. Prompt-injection / safety scan -- memory content is not system
    # authority (spec §40). Flagged content is EXCLUDED, never
    # "cleaned" and used anyway (same posture as orca/truth/fetch.py).
    sanitized = sanitize_extracted_text(claim_text)
    if sanitized.flagged:
        return FirewallVerdict(allowed=False, memory_id=record.memory_id, reasons=["prompt_injection_pattern_matched"])

    return FirewallVerdict(allowed=True, memory_id=record.memory_id, reasons=reasons, sanitized_text=sanitized.text, is_stale=stale)


def filter_recall(
    records: list[MemoryRecord], requesting_scope: MemoryScope, requesting_scope_id: str,
    requester_privacy_clearance: PrivacyClass = PrivacyClass.STANDARD,
) -> tuple[list[MemoryRecord], list[FirewallVerdict]]:
    """Applies check() to a whole recall batch. Returns (allowed_records,
    all_verdicts) -- the verdicts list is kept even for rejected records
    so a caller can log/trace WHY something was filtered (spec §45),
    without ever including the rejected record's own content in that
    trace."""
    allowed: list[MemoryRecord] = []
    verdicts: list[FirewallVerdict] = []
    for record in records:
        verdict = check(record, requesting_scope, requesting_scope_id, requester_privacy_clearance)
        verdicts.append(verdict)
        if verdict.allowed:
            allowed.append(record)
    return allowed, verdicts
