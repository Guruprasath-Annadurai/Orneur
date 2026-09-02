"""
MemoryArbiter (Phase 5 spec §17-18). Memory governance ONLY -- promotion,
duplicate resolution, conflict assessment, temporal reconciliation,
epistemic-state transitions, supersession. Never authorizes external
actions (spec §18) -- every method here returns a decision/record, it
never calls a tool, sends a request, or mutates anything outside the
memory store itself.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from orca.memory.contracts import (
    ContradictionResolution,
    DuplicateClassification,
    EpistemicState,
    MemoryCandidate,
    MemoryDecision,
    MemoryScope,
    PromotionDecision,
    SemanticMemoryRecord,
    _now_iso,
)
from orca.memory import store as memory_store

_IDENTICAL_THRESHOLD = 0.95
_NEAR_DUPLICATE_THRESHOLD = 0.6
_SAME_FACT_TOKEN_OVERLAP_THRESHOLD = 0.5

# Maps a Truth Fabric ContradictionRelationship (when the candidate's
# evidence already carries one -- spec §12: "do not rerun an unrelated
# second verifier") directly onto Memory's own resolution vocabulary,
# preserving lineage instead of re-deriving a verdict Truth Fabric
# already computed.
_TRUTH_RELATIONSHIP_MAP = {
    "DIRECT_CONTRADICTION": ContradictionResolution.CONTESTED,
    "TEMPORALLY_RECONCILABLE": ContradictionResolution.TEMPORAL_CHANGE,
    "SCOPE_DIFFERENCE": ContradictionResolution.SCOPE_DIFFERENCE,
    "LIKELY_CONFLICT": ContradictionResolution.CONTESTED,
}


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"\w+", text) if len(w) > 2}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def _shared_entity(a_entities: list[str], b_entities: list[str]) -> bool:
    return bool({e.lower() for e in a_entities} & {e.lower() for e in b_entities})


class MemoryArbiter:
    def find_duplicate(
        self, candidate: MemoryCandidate, existing: list[SemanticMemoryRecord],
    ) -> tuple[SemanticMemoryRecord | None, DuplicateClassification]:
        """Bounded -- compares against at most the given `existing` list
        (callers pass an already scope/entity-filtered candidate set, not
        every semantic memory ever stored, avoiding a quadratic scan over
        unrestricted history -- spec §26)."""
        best: tuple[SemanticMemoryRecord | None, float] = (None, 0.0)
        for record in existing:
            ratio = SequenceMatcher(None, candidate.extracted_claim.lower(), record.claim.lower()).ratio()
            if ratio > best[1]:
                best = (record, ratio)

        record, ratio = best
        if record is None:
            return None, DuplicateClassification.DISTINCT

        # A differing specific number is checked BEFORE the lexical-
        # similarity thresholds below: two claims that differ only in one
        # digit substring ("100 requests per minute" vs "500 requests per
        # minute") score a very high SequenceMatcher ratio despite
        # asserting genuinely different facts -- treating that as
        # IDENTICAL/NEAR_DUPLICATE would silently drop a real
        # contradiction instead of flagging it (spec §17: contradictory
        # memories must coexist, never be silently merged away).
        cand_numbers, rec_numbers = _numbers(candidate.extracted_claim), _numbers(record.claim)
        shares_entity = _shared_entity(candidate.entities, record.entities)
        if cand_numbers and rec_numbers and cand_numbers != rec_numbers and (shares_entity or ratio >= _NEAR_DUPLICATE_THRESHOLD):
            return record, DuplicateClassification.POTENTIAL_CONFLICT

        if ratio >= _IDENTICAL_THRESHOLD:
            return record, DuplicateClassification.IDENTICAL
        if ratio >= _NEAR_DUPLICATE_THRESHOLD:
            return record, DuplicateClassification.NEAR_DUPLICATE

        cand_tokens, rec_tokens = _tokens(candidate.extracted_claim), _tokens(record.claim)
        token_overlap = len(cand_tokens & rec_tokens) / max(1, min(len(cand_tokens), len(rec_tokens)))
        if token_overlap >= _SAME_FACT_TOKEN_OVERLAP_THRESHOLD:
            return record, DuplicateClassification.SAME_FACT_DIFFERENT_WORDING
        return None, DuplicateClassification.DISTINCT

    def resolve_contradiction(
        self, candidate: MemoryCandidate, conflicting: SemanticMemoryRecord,
    ) -> ContradictionResolution:
        """Never "pick the newest string" (spec §17). Checks, in order:
        an already-computed Truth Fabric relationship on the candidate's
        own evidence (highest-fidelity signal, preserved not re-derived);
        scope difference; then temporal ordering (a newer record with an
        open-ended validity window for the same entity/claim shape is a
        real update, not a standing conflict) -- both are DETERMINISTIC,
        never a coin-flip or authority-only decision. Anything left over
        is CONTESTED or UNRESOLVED, both of which mean the memories
        coexist (spec §17: "allow conflicting memories to coexist")."""
        # A Truth Fabric contradiction relationship, when present, is
        # carried on evidence_refs[i].note as "truth_relationship:<VALUE>"
        # by whatever caller already ran detect_evidence_contradictions --
        # see docs/orneur/phase-5/MEMORY_EVIDENCE_LEDGER.md for the exact
        # convention. Checked before any of memory's own heuristics.
        for evidence in candidate.evidence_refs:
            if evidence.note.startswith("truth_relationship:"):
                truth_rel = evidence.note.split(":", 1)[1]
                if truth_rel in _TRUTH_RELATIONSHIP_MAP:
                    return _TRUTH_RELATIONSHIP_MAP[truth_rel]

        if candidate.scope != conflicting.scope or candidate.scope_id != conflicting.scope_id:
            return ContradictionResolution.SCOPE_DIFFERENCE

        if conflicting.valid_to is None and candidate.valid_from and candidate.valid_from > conflicting.created_at:
            return ContradictionResolution.TEMPORAL_CHANGE

        return ContradictionResolution.UNRESOLVED

    def decide_promotion(
        self, candidate: MemoryCandidate, existing: list[SemanticMemoryRecord],
    ) -> tuple[PromotionDecision, list[str]]:
        """The explicit "not automatically trusted" gate (spec §10, §14):
        a candidate with NO evidence_refs at all (no source episode, no
        Truth Fabric lineage) is deferred, never silently promoted to
        KNOWN/SUPPORTED -- it can still be stored as a low-trust
        UNVERIFIED memory by the caller if that's the desired policy, but
        this method never claims strong epistemic status for an
        unsupported candidate."""
        reasons: list[str] = []
        if not candidate.extracted_claim.strip():
            return PromotionDecision.REJECTED, ["empty extracted claim"]

        duplicate, classification = self.find_duplicate(candidate, existing)
        if classification == DuplicateClassification.IDENTICAL:
            return PromotionDecision.REJECTED, [f"identical to existing memory {duplicate.memory_id}"]

        if classification == DuplicateClassification.POTENTIAL_CONFLICT and duplicate is not None:
            resolution = self.resolve_contradiction(candidate, duplicate)
            reasons.append(f"conflicts with {duplicate.memory_id}: {resolution.value}")
            if resolution == ContradictionResolution.DISPROVEN:
                return PromotionDecision.REJECTED, reasons
            # TEMPORAL_CHANGE/SCOPE_DIFFERENCE/CONTESTED/UNRESOLVED all
            # promote -- coexistence is the point (spec §17), never
            # silently overwriting the older record.
            return PromotionDecision.PROMOTED, reasons

        if not candidate.evidence_refs:
            reasons.append("no evidence_refs -- promoted at UNVERIFIED epistemic state, not KNOWN/SUPPORTED")
        return PromotionDecision.PROMOTED, reasons

    def promote(self, candidate: MemoryCandidate, conflicting: SemanticMemoryRecord | None = None) -> SemanticMemoryRecord:
        """Actually persists the promoted candidate. Epistemic state is
        derived honestly from what's actually known about the
        candidate -- evidence presence, not the model's own confidence in
        having said it (spec §14: "Do not promote unsupported generated
        model text into KNOWN")."""
        epistemic_state = EpistemicState.SUPPORTED if candidate.evidence_refs else EpistemicState.UNVERIFIED
        record = SemanticMemoryRecord(
            claim=candidate.extracted_claim, entities=list(candidate.entities),
            scope=candidate.scope, scope_id=candidate.scope_id, privacy=candidate.privacy,
            source_refs=[candidate.source_episode_id] if candidate.source_episode_id else [],
            evidence_refs=list(candidate.evidence_refs), epistemic_state=epistemic_state,
            valid_from=candidate.valid_from, last_verified_at=_now_iso() if candidate.evidence_refs else None,
        )
        if conflicting is not None:
            record.contradicts = [conflicting.memory_id]
            if record.memory_id not in conflicting.contradicts:
                conflicting.contradicts = list(set(conflicting.contradicts) | {record.memory_id})
                memory_store.save(conflicting)
        memory_store.save(record)
        return record

    def supersede(self, old: SemanticMemoryRecord, new: SemanticMemoryRecord) -> None:
        """Spec §16: never deletes the superseded record -- both remain
        retrievable, linked by SUPERSEDES/SUPERSEDED_BY, with valid_to set
        on the old record rather than the old record vanishing."""
        old.superseded_by = new.memory_id
        old.valid_to = new.valid_from or _now_iso()
        new.supersedes = old.memory_id
        memory_store.save(old)
        memory_store.save(new)


def record_decision(decision_type: str, memory_id: str, reason: str, made_by: str = "arbiter") -> MemoryDecision:
    return MemoryDecision(decision_type=decision_type, memory_id=memory_id, reason=reason, made_by=made_by)
