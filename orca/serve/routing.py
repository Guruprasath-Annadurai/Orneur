"""
Cost-aware query routing — the mechanism that actually makes Orca's cost
differentiation claim true (see docs/PERPLEXITY_DIFFERENTIATION_PLAN.md).

Without this module, a tier configured with a frontier backend is exactly
as expensive per-query as any competitor that always calls a frontier API
— "cheaper" would be marketing copy, not a fact. This module is what makes
it a fact for the specific, narrow case it handles: a tier statically
configured for "ollama" (self-hosted, near-zero marginal cost) stays on
that path by default for every query. It is escalated to a frontier
backend for ONE query at a time only when ALL of the following hold:

  1. The operator explicitly opted in
     (CONFIG.backends.cost_aware_escalation_enabled). Escalating a
     self-hosted-configured tier to a paid frontier API without explicit
     opt-in would silently break the exact "self-hosted = $0 marginal
     cost, predictable spend, data stays here" promise the product is
     built on. This is NOT a default-on feature.
  2. The data-sovereignty lock is not set — checked directly here as an
     independent second gate. Never trust a single check for something
     this consequential; orca/serve/registry.py enforces the same lock
     for the static per-tier config, this module must never bypass it.
  3. A frontier backend is actually configured with real credentials.
  4. The query itself is classified as plausibly needing it (time-sensitive
     or long-and-complex) — a heuristic based on surface language, not a
     certainty, and documented as such below.

Without step 4, "cost-aware" is meaningless — every query would always
escalate, which is exactly as expensive as a frontier-API-per-query
competitor. Without steps 1-3, escalation could violate a deployment's
sovereignty guarantee or spend money the operator never authorized.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from orca.config import CONFIG
from orca.serve.registry import TierResolution, _configured_frontier_model, _frontier_backend_available

# Safety valve on top of the opt-in gate: escalation being enabled at all
# should not mean an unbounded bill. If the operator sets
# escalation_daily_cap=0 ("not set"), fall back to this conservative default
# rather than treating 0 as unlimited — an operator who flips the opt-in
# flag but never thinks about a cap should still get a bounded blast radius,
# not a surprise invoice.
_DEFAULT_DAILY_CAP = 100
_escalations_by_day: dict[str, int] = {}


def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _escalation_count_today() -> int:
    return _escalations_by_day.get(_today_key(), 0)


def _record_escalation() -> None:
    key = _today_key()
    _escalations_by_day[key] = _escalations_by_day.get(key, 0) + 1
    # Defensive cleanup — this dict should never hold more than a couple of
    # days of entries; drop anything older than today+yesterday.
    for k in list(_escalations_by_day):
        if k != key and k != time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400)):
            del _escalations_by_day[k]


def reset_daily_cap_counter() -> None:
    """Test-only — clears the in-memory escalation-count tracker."""
    _escalations_by_day.clear()

_TIME_SENSITIVE_PATTERNS = [
    r"\btoday\b", r"\byesterday\b", r"\bthis (week|month|year)\b",
    r"\blatest\b", r"\bcurrent(ly)?\b", r"\bright now\b", r"\bbreaking\b",
    r"\brecent(ly)?\b", r"\bnews\b", r"\bstock price\b", r"\bweather\b",
]

_COMPLEX_REASONING_PATTERNS = [
    r"\bcompare\b", r"\banalyz(e|is)\b", r"\bstep[- ]by[- ]step\b",
    r"\btrade-?offs?\b", r"\bpros and cons\b", r"\bmulti[- ]step\b",
    r"\bin depth\b", r"\bcomprehensive\b",
]

_TIME_RE = [re.compile(p, re.IGNORECASE) for p in _TIME_SENSITIVE_PATTERNS]
_COMPLEX_RE = [re.compile(p, re.IGNORECASE) for p in _COMPLEX_REASONING_PATTERNS]

_LONG_QUERY_WORD_THRESHOLD = 25


@dataclass
class QueryComplexity:
    is_time_sensitive: bool
    is_complex: bool
    word_count: int
    reasons: list[str] = field(default_factory=list)

    @property
    def suggests_escalation(self) -> bool:
        """
        A heuristic, not a certainty: explicitly time-sensitive language, OR
        a long query that also reads as asking for multi-step/comparative
        reasoning. Documented as a heuristic because it is one — no trained
        classifier backs this, it's surface pattern matching, same honesty
        standard applied to every other heuristic signal in this codebase
        (e.g. orca/serve/moderation.py's pattern-based checks).
        """
        return self.is_time_sensitive or (self.is_complex and self.word_count > _LONG_QUERY_WORD_THRESHOLD)


def classify_query(message: str) -> QueryComplexity:
    time_hits = [p.pattern for p in _TIME_RE if p.search(message)]
    complex_hits = [p.pattern for p in _COMPLEX_RE if p.search(message)]
    word_count = len(message.split())

    reasons = []
    if time_hits:
        reasons.append(f"time-sensitive language matched ({len(time_hits)} pattern(s))")
    if complex_hits:
        reasons.append(f"complex-reasoning language matched ({len(complex_hits)} pattern(s))")
    if word_count > _LONG_QUERY_WORD_THRESHOLD:
        reasons.append(f"long query ({word_count} words)")
    if not reasons:
        reasons.append("no time-sensitive or complex-reasoning signals found")

    return QueryComplexity(
        is_time_sensitive=bool(time_hits),
        is_complex=bool(complex_hits),
        word_count=word_count,
        reasons=reasons,
    )


@dataclass
class RoutingDecision:
    escalated: bool
    reason: str
    complexity: QueryComplexity


def escalation_available() -> tuple[bool, str]:
    """
    Whether cost-aware escalation is possible at all in this deployment
    right now. All three gates checked independently and explicitly —
    this function is the single place that answers "is escalation even
    on the table," so every caller gets the same answer.
    """
    if not CONFIG.backends.cost_aware_escalation_enabled:
        return False, "cost-aware escalation is not enabled for this deployment"
    if CONFIG.backends.data_sovereignty_lock:
        return False, "data sovereignty lock is set — escalation is disabled regardless of other config"

    backend = CONFIG.backends.escalation_backend
    if backend not in ("openai", "anthropic"):
        return False, "no valid escalation_backend configured (must be 'openai' or 'anthropic')"
    if not _frontier_backend_available(backend):
        return False, f"escalation_backend '{backend}' has no API key configured"

    return True, f"escalation available via '{backend}'"


def decide_route(base_resolution: TierResolution, message: str) -> tuple[TierResolution, RoutingDecision]:
    """
    Given a tier's statically-configured resolution (from
    orca.serve.registry.resolve_tier_backend), decide whether THIS specific
    query should escalate to a frontier backend. Returns
    (resolution_to_actually_use, decision_record) — the decision record
    carries the reasoning for metrics/audit visibility, never just a bool.

    Never escalates a resolution that's already on a non-Ollama backend —
    there's nothing to escalate to, the operator already chose a frontier
    backend for that tier statically.
    """
    complexity = classify_query(message)

    if base_resolution.backend != "ollama":
        return base_resolution, RoutingDecision(
            escalated=False,
            reason="tier is already configured for a non-self-hosted backend — nothing to escalate",
            complexity=complexity,
        )

    available, availability_reason = escalation_available()
    if not available:
        return base_resolution, RoutingDecision(escalated=False, reason=availability_reason, complexity=complexity)

    if not complexity.suggests_escalation:
        return base_resolution, RoutingDecision(
            escalated=False,
            reason="query shows no time-sensitive or complex-reasoning signals — self-hosted model is appropriate",
            complexity=complexity,
        )

    cap = CONFIG.backends.escalation_daily_cap or _DEFAULT_DAILY_CAP
    if _escalation_count_today() >= cap:
        return base_resolution, RoutingDecision(
            escalated=False,
            reason=f"escalation daily cap reached ({cap}/day) — staying on self-hosted model for the rest of today",
            complexity=complexity,
        )

    backend = CONFIG.backends.escalation_backend
    model = _configured_frontier_model(base_resolution.tier, backend)
    escalated_resolution = TierResolution(
        tier=base_resolution.tier, backend=backend, model=model,
        data_left_infrastructure=True, sovereignty_overridden=False,
    )
    _record_escalation()
    return escalated_resolution, RoutingDecision(
        escalated=True,
        reason="; ".join(complexity.reasons),
        complexity=complexity,
    )
