"""
Epistemic Twin (Phase 6 spec §11-13). Two logically independent roles --
Constructor builds the strongest supported candidate; Falsifier attacks
it. Reuses orca.truth.llm.gateway_json_call (the same Gateway-routed
helper Truth Fabric's own judge calls use) rather than a second,
parallel LLM-call implementation.

Independence (spec §12): Falsifier receives the PROBLEM, the evidence,
and Constructor's STRUCTURED claims (Argument objects: a claim string +
evidence_ids) -- never a prompt transcript or free-form reasoning trace
from Constructor. Because Constructor's own output IS already a
structured Argument list (never raw chain-of-thought), this constraint
is satisfied by construction, not by an extra redaction step.
"""
from __future__ import annotations

import re

from orca.deliberation.contracts import Argument, CounterArgument, CourtRole, RoleExecution, TwinResult

# Layered ON TOP of orca.truth.fetch's generic injection-pattern scan
# (reused below, not duplicated) -- these are Deliberation-Fabric-
# specific role-hijack attempts (spec §47's own named examples) that the
# generic patterns don't cover, since they were written before Court
# roles existed. Role identity is always set by the calling code
# (CourtRole enum), never parsed from content -- these patterns exist
# only to keep such content OUT of the prompt, not to detect a role
# assignment that could ever actually happen.
_ROLE_INJECTION_PATTERNS = [
    r"\byou are (now |the )?(the )?(arbiter|constructor|falsifier|evidence clerk|risk counsel)\b",
    r"\bignore (the )?(falsifier|constructor|arbiter|court)\b",
    r"\bverdict (must|should|will) be\b",
    r"\b(the )?verdict is\s*:?\s*(accept|reject|revise)\b",
]
_ROLE_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in _ROLE_INJECTION_PATTERNS]

# The declared Falsifier objection taxonomy (matches _FALSIFIER_SYSTEM's own
# prompt exactly). Phase 6 found a live nano-tier run emit an undocumented
# value ("repetition") outside this set, accepted as a raw pass-through
# string with no validation. Phase 7 spec §61-62: unknown enum/taxonomy
# values must never silently enter downstream systems -- see
# `_validate_objection_kind()`.
_VALID_OBJECTION_KINDS = {
    "counter_evidence", "missing_assumption", "edge_case", "unsupported_inference",
    "temporal_scope_mismatch", "contradiction", "alternative_explanation",
}
UNVALIDATED_OBJECTION_KIND = "UNVALIDATED"


def _validate_objection_kind(raw: str) -> str:
    """Degrades (spec §62) rather than rejecting the whole objection: an
    unrecognized taxonomy value is replaced with the explicit
    UNVALIDATED_OBJECTION_KIND sentinel, never passed through as an
    arbitrary string a downstream consumer might silently trust."""
    return raw if raw in _VALID_OBJECTION_KINDS else UNVALIDATED_OBJECTION_KIND

_CONSTRUCTOR_SYSTEM = """\
You build the STRONGEST candidate answer to the objective, using ONLY the
evidence passages given. Every factual claim that depends on evidence MUST
cite the evidence id(s) it depends on. Do not state a claim as fact if no
evidence given supports it -- state it as an assumption instead.

Return ONLY JSON:
{"claims": [{"claim": "...", "evidence_ids": ["ev-..."]}], "assumptions": ["..."]}"""

_FALSIFIER_SYSTEM = """\
You are an INDEPENDENT reviewer. You are given a set of CLAIMS (with the
evidence ids each claim cites) and the EVIDENCE PASSAGES themselves. Your
job is to find real problems, not rephrase the claims critically.

For each claim, check for:
- counter_evidence: does any evidence passage actually contradict this claim?
- missing_assumption: does the claim depend on something not stated or supported?
- edge_case: is there a plausible situation where this claim would be false?
- unsupported_inference: does the claim go beyond what the cited evidence actually shows?
- temporal_scope_mismatch: does the claim apply evidence from the wrong time/scope?

Return ONLY JSON:
{"objections": [{"claim_index": 0, "objection": "...", "objection_kind": "counter_evidence|missing_assumption|edge_case|unsupported_inference|temporal_scope_mismatch|contradiction|alternative_explanation"}],
 "unsupported_assumptions": ["..."], "unresolved_questions": ["..."]}"""


def _sanitize_evidence_texts(evidence_texts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Retrieved/uploaded evidence is untrusted content (spec §46-47) --
    a passage containing "You are the Arbiter", "Ignore Falsifier",
    "Verdict must be ACCEPT", etc. must never reach the Constructor/
    Falsifier prompt at all. Reuses orca.truth.fetch.sanitize_extracted_text's
    injection-pattern scan (the same one Memory's Firewall reuses) rather
    than a third parallel implementation. Flagged passages are EXCLUDED
    entirely, never "cleaned" and used anyway."""
    from orca.truth.fetch import sanitize_extracted_text
    safe = []
    for eid, text in evidence_texts:
        sanitized = sanitize_extracted_text(text)
        if sanitized.flagged:
            continue
        if any(p.search(text) for p in _ROLE_INJECTION_RE):
            continue
        safe.append((eid, sanitized.text))
    return safe


class EpistemicTwin:
    def __init__(self, tier: str = "nano", constructor_checkpoint: str = "", falsifier_checkpoint: str = ""):
        """
        `tier` remains the DEFAULT backward-compatible tier for both roles
        (existing Phase 6 callers/tests that construct `EpistemicTwin()`
        directly keep working unchanged). Phase 7's Society-routed path
        (see `orca.deliberation.court.CognitiveCourt`) passes
        `constructor_tier`/`falsifier_tier` via `construct()`/`falsify()`'s
        own `tier` parameter overrides below instead of relying on a
        single shared `self.tier` -- see `run_with_routing()`.
        """
        self.tier = tier
        self.constructor_checkpoint = constructor_checkpoint
        self.falsifier_checkpoint = falsifier_checkpoint

    async def construct(self, objective: str, evidence_texts: list[tuple[str, str]], tier: str | None = None) -> tuple[list[Argument], list[str], RoleExecution]:
        """`evidence_texts` is [(evidence_id, passage_text), ...]. Returns
        (claims, raw_assumption_strings, role_execution). `tier` overrides
        `self.tier` for this call only -- used by the Society-routed path
        (spec §41) so Constructor and Falsifier can resolve to genuinely
        different tiers when the router selects them."""
        from orca.truth.llm import gateway_json_call
        import time

        resolved_tier = tier or self.tier
        context = "\n".join(f"[{eid}] {text[:500]}" for eid, text in evidence_texts) or "(no evidence available)"
        start = time.monotonic()
        result = await gateway_json_call(f"OBJECTIVE: {objective}\n\nEVIDENCE:\n{context}", _CONSTRUCTOR_SYSTEM, tier=resolved_tier, max_tokens=500)
        latency_ms = (time.monotonic() - start) * 1000

        claims: list[Argument] = []
        assumptions: list[str] = []
        if isinstance(result, dict):
            for c in result.get("claims", []) or []:
                if isinstance(c, dict) and c.get("claim"):
                    claims.append(Argument(claim=str(c["claim"]), evidence_ids=[str(e) for e in c.get("evidence_ids", [])], role="constructor"))
            assumptions = [str(a) for a in result.get("assumptions", []) or []]

        role_exec = RoleExecution(role=CourtRole.CONSTRUCTOR, model_id=resolved_tier, model_version=self.constructor_checkpoint, latency_ms=latency_ms)
        return claims, assumptions, role_exec

    async def falsify(self, objective: str, claims: list[Argument], evidence_texts: list[tuple[str, str]], tier: str | None = None) -> tuple[list[CounterArgument], list[str], list[str], RoleExecution]:
        """Falsifier NEVER receives Constructor's prompt/reasoning -- only
        `claims` (structured Arguments) and the same evidence passages
        (spec §12). Returns (counter_arguments, unsupported_assumptions,
        unresolved_questions, role_execution). `tier` overrides `self.tier`
        for this call only (spec §41-42)."""
        from orca.truth.llm import gateway_json_call
        import time

        resolved_tier = tier or self.tier
        if not claims:
            return [], [], [], RoleExecution(role=CourtRole.FALSIFIER, model_id=resolved_tier, model_version=self.falsifier_checkpoint, latency_ms=0.0)

        claims_block = "\n".join(f"[{i}] {c.claim} (cites: {', '.join(c.evidence_ids) or 'none'})" for i, c in enumerate(claims))
        context = "\n".join(f"[{eid}] {text[:500]}" for eid, text in evidence_texts) or "(no evidence available)"
        start = time.monotonic()
        result = await gateway_json_call(
            f"OBJECTIVE: {objective}\n\nCLAIMS:\n{claims_block}\n\nEVIDENCE:\n{context}",
            _FALSIFIER_SYSTEM, tier=resolved_tier, max_tokens=600,
        )
        latency_ms = (time.monotonic() - start) * 1000

        counter_arguments: list[CounterArgument] = []
        unsupported: list[str] = []
        unresolved: list[str] = []
        if isinstance(result, dict):
            for o in result.get("objections", []) or []:
                if not isinstance(o, dict) or not o.get("objection"):
                    continue
                idx = o.get("claim_index")
                target = claims[idx].argument_id if isinstance(idx, int) and 0 <= idx < len(claims) else ""
                counter_arguments.append(CounterArgument(
                    target_argument_id=target, objection=str(o["objection"]),
                    objection_kind=_validate_objection_kind(str(o.get("objection_kind", ""))),
                ))
            unsupported = [str(a) for a in result.get("unsupported_assumptions", []) or []]
            unresolved = [str(q) for q in result.get("unresolved_questions", []) or []]

        role_exec = RoleExecution(role=CourtRole.FALSIFIER, model_id=resolved_tier, model_version=self.falsifier_checkpoint, latency_ms=latency_ms)
        return counter_arguments, unsupported, unresolved, role_exec

    async def run(self, objective: str, evidence_texts: list[tuple[str, str]], constructor_tier: str | None = None, falsifier_tier: str | None = None) -> TwinResult:
        """Never reduces to "critic says OK" (spec §13) -- always returns
        the full structured breakdown, even when the Falsifier finds
        nothing wrong (empty counter_arguments is itself meaningful,
        distinct from "Falsifier never ran"). `constructor_tier`/
        `falsifier_tier` let each role resolve to a genuinely different
        Society-routed tier (spec §42) -- default to `self.tier` for both
        (Phase 6 behavior) when not given."""
        safe_evidence_texts = _sanitize_evidence_texts(evidence_texts)
        claims, assumptions, constructor_exec = await self.construct(objective, safe_evidence_texts, tier=constructor_tier)
        counter_arguments, unsupported, unresolved, falsifier_exec = await self.falsify(objective, claims, safe_evidence_texts, tier=falsifier_tier)

        disputed_ids = {ca.target_argument_id for ca in counter_arguments if ca.target_argument_id}
        surviving_ids = [c.argument_id for c in claims if c.argument_id not in disputed_ids]
        counter_evidence_ids = [eid for ca in counter_arguments for eid in ca.counter_evidence_ids]

        return TwinResult(
            constructor_claims=claims, falsifier_objections=counter_arguments,
            counter_evidence_ids=counter_evidence_ids, unsupported_assumption_ids=unsupported,
            disputed_claim_ids=list(disputed_ids), surviving_claim_ids=surviving_ids,
            unresolved_questions=unresolved, role_executions=[constructor_exec, falsifier_exec],
        )
