"""Synthetic handlers for twelve declared roles.

Each handler is a deterministic function. None of them calls a model,
spends money, or changes a training lock. The existing Orchestrator
remains the scheduler; this module only registers handlers on it.
"""
from __future__ import annotations

import hashlib
from typing import Any

from orca.pretrain_foundation.evidence_contract import (
    Claim,
    DenialReceipt,
    EvidenceContractError,
    PromotionProposal,
    evidence_span,
    transition,
)
from orca.pretrain_foundation.role_registry import implemented_roles, role_for_task

_DIRECTIVES = ("ignore previous", "grant admin", "you are now", "system:")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_claim(payload: dict, _ctx: dict | None = None) -> dict:
    """The producer may record OBSERVED or UNKNOWN. It cannot record VERIFIED."""
    text = str(payload.get("text") or "")
    producer = str(payload.get("producer_id") or "")
    span_text = payload.get("span")
    if not text or not producer:
        return {"state": "UNKNOWN", "verified": False, "reason": "missing claim"}
    if not isinstance(span_text, str) or not payload.get("source_id"):
        claim = Claim(claim_id=str(payload.get("claim_id") or "claim"), text=text, state="UNKNOWN", producer_id=producer)
        return {"state": claim.state, "verified": False, "producer_id": producer}
    span = evidence_span(str(payload["source_id"]), span_text, authorized=False)
    if not span.matches():
        return {"state": "UNKNOWN", "verified": False, "evidence_authorized": False, "reason": "evidence digest mismatch"}
    claim = Claim(
        claim_id=str(payload.get("claim_id") or "claim"),
        text=text,
        state="OBSERVED",
        producer_id=producer,
        evidence=(span,),
    )
    if payload.get("request_verified") is True:
        try:
            transition(claim, "VERIFIED", actor_id=producer, outcome="passed")
        except EvidenceContractError as exc:
            return {
                "state": "OBSERVED",
                "verified": False,
                "evidence_authorized": False,
                "production_authorization": False,
                "reason": str(exc),
            }
    return {
        "state": claim.state,
        "verified": False,
        "evidence_authorized": False,
        "production_authorization": False,
        "caller_authorized_ignored": "authorized" in payload,
        "producer_id": producer,
        "evidence_digest": span.digest,
    }


def falsify_claim(payload: dict, _ctx: dict | None = None) -> dict:
    """An independent actor compares the claim text with the evidence span."""
    producer = str(payload.get("producer_id") or "")
    falsifier = str(payload.get("falsifier_id") or "")
    if not falsifier or falsifier == producer:
        raise EvidenceContractError("falsifier must be a different actor")
    span_text = str(payload.get("span") or "")
    text = str(payload.get("text") or "")
    if not span_text or not payload.get("source_id"):
        return {"state": "UNKNOWN", "outcome": "unsupported", "falsifier_id": falsifier}
    span = evidence_span(str(payload["source_id"]), span_text, authorized=False)
    if not span.matches():
        return {
            "state": "DISPUTED",
            "outcome": "evidence-mismatch",
            "falsifier_id": falsifier,
            "evidence_authorized": False,
            "production_authorization": False,
        }
    if "=" in text and "=" in span_text and text.strip() != span_text.strip():
        return {
            "state": "REFUTED",
            "outcome": "contradicts-evidence",
            "falsifier_id": falsifier,
            "evidence_digest": span.digest,
            "evidence_authorized": False,
            "production_authorization": False,
        }
    return {
        "state": "OBSERVED",
        "outcome": "not-refuted",
        "falsifier_id": falsifier,
        "evidence_digest": span.digest,
        "evidence_authorized": False,
        "production_authorization": False,
    }


def arbitrate_claims(payload: dict, _ctx: dict | None = None) -> dict:
    """Disagreement is not resolved by counting votes."""
    claims = payload.get("claims")
    if not isinstance(claims, list) or len(claims) < 2:
        return {"resolution": "INSUFFICIENT", "method": "not_majority_vote"}
    states = {str(item.get("state")) for item in claims if isinstance(item, dict)}
    texts = {str(item.get("text")) for item in claims if isinstance(item, dict)}
    if "VERIFIED" in states and "REFUTED" in states:
        return {"resolution": "UNRESOLVED_REQUIRES_REPRODUCIBLE_CHECK", "method": "not_majority_vote"}
    if len(texts) > 1:
        return {"resolution": "DISPUTED", "method": "not_majority_vote", "votes_ignored": len(claims)}
    return {"resolution": "NO_DISAGREEMENT", "method": "not_majority_vote"}


def decide_authority(payload: dict, _ctx: dict | None = None) -> dict:
    """Caller grant dictionaries are not enrolled authority. This path denies them."""
    grant = payload.get("grant") if isinstance(payload.get("grant"), dict) else {}
    action = str(payload.get("action") or "")
    tenant = str(payload.get("tenant_id") or "")
    if not grant:
        reason = "grant missing"
    elif grant.get("expired") is True or grant.get("revoked") is True:
        reason = "grant not active"
    elif grant.get("tenant_id") != tenant:
        reason = "tenant mismatch"
    else:
        reason = "caller-supplied grant is not enrolled authority"
    receipt = DenialReceipt(
        requested_action=action or "(none)",
        decision="DENIED",
        reason=reason,
        enforcement_point="governed_handlers.decide_authority",
        evidence_digest=_digest(reason),
        tenant_id=tenant,
    )
    return {
        "decision": receipt.decision,
        "executed": False,
        "reason": receipt.reason,
        "enforcement_point": receipt.enforcement_point,
        "evidence_digest": receipt.evidence_digest,
        "requested_action": receipt.requested_action,
    }


def record_denial(payload: dict, _ctx: dict | None = None) -> dict:
    decision = decide_authority(payload, _ctx)
    if decision["decision"] != "DENIED":
        return {"recorded": False, "reason": "the guarded path did not deny"}
    return {"recorded": True, "receipt": decision, "scope": "guarded-path-only"}


def screen_untrusted(payload: dict, _ctx: dict | None = None) -> dict:
    text = str(payload.get("text") or "")
    lowered = text.casefold()
    if any(marker in lowered for marker in _DIRECTIVES):
        return {"admitted": False, "as_instruction": False, "authority_changed": False, "reason": "untrusted_directive"}
    return {"admitted": True, "as_instruction": False, "authority_changed": False, "text": text}


def deny_self_promotion(payload: dict, _ctx: dict | None = None) -> dict:
    try:
        proposal = PromotionProposal(
            candidate_id=str(payload.get("candidate_id") or ""),
            produced_by=str(payload.get("produced_by") or ""),
            decided_by=str(payload.get("decided_by") or ""),
            applied=False,
        )
    except EvidenceContractError as exc:
        return {"promoted": False, "applied": False, "reason": str(exc)}
    return {
        "promoted": False,
        "applied": proposal.applied,
        "candidate_id": proposal.candidate_id,
        "reason": "proposal recorded; promotion requires a separate authorized decision",
    }


def isolate_memory(payload: dict, _ctx: dict | None = None) -> dict:
    actor = str(payload.get("actor_tenant") or "")
    record = str(payload.get("record_tenant") or "")
    if not actor or actor != record:
        return {"allowed": False, "enrolled": False, "reason": "cross-tenant memory read"}
    return {
        "allowed": False,
        "enrolled": False,
        "reason": "tenant strings are not an enrolled identity",
        "record_id": payload.get("record_id"),
    }


def select_team(payload: dict, _ctx: dict | None = None) -> dict:
    requested = payload.get("tasks")
    if not isinstance(requested, list) or not requested:
        return {"selected": [], "reason": "no tasks"}
    selected = []
    blocked = []
    for task in requested:
        role = role_for_task(str(task))
        if role is None:
            blocked.append(str(task))
            continue
        selected.append(role.agent_id)
    return {
        "selected": selected,
        "blocked_unqualified": blocked,
        "catalog_size": 100,
        "selected_count": len(selected),
    }


def bound_deadline(payload: dict, _ctx: dict | None = None) -> dict:
    used = int(payload.get("used_ticks") or 0)
    budget = int(payload.get("budget_ticks") or 0)
    done = bool(payload.get("done"))
    if used >= budget and not done:
        return {"status": "INCOMPLETE", "fabricated_completion": False, "used_ticks": used, "budget_ticks": budget}
    if done:
        return {"status": "COMPLETE", "fabricated_completion": False, "used_ticks": used, "budget_ticks": budget}
    return {"status": "IN_PROGRESS", "fabricated_completion": False, "used_ticks": used, "budget_ticks": budget}


def account_cost(payload: dict, _ctx: dict | None = None) -> dict:
    prices = payload.get("prices")
    if not isinstance(prices, dict) or not prices:
        return {"total": "UNKNOWN", "reason": "no price list"}
    total = 0
    for value in prices.values():
        if isinstance(value, bool) or not isinstance(value, int):
            return {"total": "UNKNOWN", "known_partial": total}
        total += value
    return {"total": total, "currency": payload.get("currency") or "UNKNOWN"}


def watch_training_locks(payload: dict, _ctx: dict | None = None) -> dict:
    requested = {
        "training": bool(payload.get("training")),
        "gpu": bool(payload.get("gpu")),
        "spend": bool(payload.get("spend")),
    }
    if any(requested.values()):
        return {"decision": "DENIED", "locks_changed": False, "requested": requested, "executed": False}
    return {
        "decision": "NOT_REQUESTED",
        "locks_changed": False,
        "training_lock": False,
        "gpu_lock": False,
        "spend_lock": False,
        "executed": False,
    }


HANDLERS: dict[str, Any] = {
    "claim.classify": classify_claim,
    "claim.falsify": falsify_claim,
    "claim.arbitrate": arbitrate_claims,
    "authority.decide": decide_authority,
    "authority.deny": record_denial,
    "content.screen": screen_untrusted,
    "promotion.deny": deny_self_promotion,
    "memory.isolate": isolate_memory,
    "team.select": select_team,
    "deadline.bound": bound_deadline,
    "cost.account": account_cost,
    "training.watch": watch_training_locks,
}


def bind_handlers(orchestrator) -> None:
    """Register the twelve handlers on an existing Orchestrator."""
    expected = {role.supported_tasks[0] for role in implemented_roles()}
    if set(HANDLERS) != expected:
        raise RuntimeError("handler map does not match implemented roles")
    for name, fn in HANDLERS.items():
        orchestrator.register_handler(name, fn, "governed")
