"""
Cognitive Kernel observability -- same pattern as orca/gateway/metrics.py
(in-memory, thread-locked, never raises). Deliberately low-cardinality:
labels are enum values (intent/complexity/risk/model-policy categories),
never raw prompts or free text (Phase 3 spec §33).
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque

_lock = threading.Lock()

_requests_total = 0
_intent_distribution: dict[str, int] = defaultdict(int)
_complexity_distribution: dict[str, int] = defaultdict(int)
_risk_distribution: dict[str, int] = defaultdict(int)
_model_policy_distribution: dict[str, int] = defaultdict(int)
_model_resolution: dict[str, int] = defaultdict(int)
_abstention_count = 0
_abstention_reasons: dict[str, int] = defaultdict(int)
_budget_exhaustion_count = 0
_plan_operation_counts: dict[str, int] = defaultdict(int)
_planning_latency_ms: deque = deque(maxlen=2000)
_total_latency_ms: deque = deque(maxlen=2000)
_shadow_agree_count = 0
_shadow_disagree_count = 0


def record_request() -> None:
    global _requests_total
    try:
        with _lock:
            _requests_total += 1
    except Exception:
        pass


def record_plan(intent: str, complexity: str, risk: str, model_policy: str, operations: list[str], planning_latency_ms: float) -> None:
    try:
        with _lock:
            _intent_distribution[intent] += 1
            _complexity_distribution[complexity] += 1
            _risk_distribution[risk] += 1
            _model_policy_distribution[model_policy] += 1
            for op in operations:
                _plan_operation_counts[op] += 1
            _planning_latency_ms.append(planning_latency_ms)
    except Exception:
        pass


def record_model_resolution(model: str) -> None:
    try:
        with _lock:
            _model_resolution[model] += 1
    except Exception:
        pass


def record_abstention(reason: str) -> None:
    global _abstention_count
    try:
        with _lock:
            _abstention_count += 1
            _abstention_reasons[reason] += 1
    except Exception:
        pass


def record_budget_exhaustion() -> None:
    global _budget_exhaustion_count
    try:
        with _lock:
            _budget_exhaustion_count += 1
    except Exception:
        pass


def record_shadow_comparison(kernel_tier: str, legacy_tier: str) -> None:
    """
    Phase 3 spec §35 (shadow equivalence): records whether the Kernel's
    suggested tier (from model_policy) agrees with the tier the legacy
    router actually used for this real request. Never raises, never
    changes the actual routing decision -- observability only.
    """
    global _shadow_agree_count, _shadow_disagree_count
    try:
        with _lock:
            if kernel_tier == legacy_tier:
                _shadow_agree_count += 1
            else:
                _shadow_disagree_count += 1
    except Exception:
        pass


def record_total_latency(latency_ms: float) -> None:
    try:
        with _lock:
            _total_latency_ms.append(latency_ms)
    except Exception:
        pass


def _avg(d: deque) -> float:
    return round(sum(d) / len(d), 2) if d else 0.0


def get_snapshot() -> dict:
    with _lock:
        return {
            "cognitive_requests_total": _requests_total,
            "intent_distribution": dict(_intent_distribution),
            "complexity_distribution": dict(_complexity_distribution),
            "risk_distribution": dict(_risk_distribution),
            "model_policy_distribution": dict(_model_policy_distribution),
            "model_resolution": dict(_model_resolution),
            "abstention_rate": round(_abstention_count / _requests_total, 4) if _requests_total else 0.0,
            "abstention_reasons": dict(_abstention_reasons),
            "budget_exhaustion": _budget_exhaustion_count,
            "plan_operations": dict(_plan_operation_counts),
            "avg_planning_latency_ms": _avg(_planning_latency_ms),
            "avg_total_latency_ms": _avg(_total_latency_ms),
            "shadow_agree": _shadow_agree_count,
            "shadow_disagree": _shadow_disagree_count,
        }


def reset() -> None:
    """Test-only."""
    global _requests_total, _abstention_count, _budget_exhaustion_count, _shadow_agree_count, _shadow_disagree_count
    with _lock:
        _requests_total = 0
        _abstention_count = 0
        _budget_exhaustion_count = 0
        _shadow_agree_count = 0
        _shadow_disagree_count = 0
        _intent_distribution.clear()
        _complexity_distribution.clear()
        _risk_distribution.clear()
        _model_policy_distribution.clear()
        _model_resolution.clear()
        _abstention_reasons.clear()
        _plan_operation_counts.clear()
        _planning_latency_ms.clear()
        _total_latency_ms.clear()
