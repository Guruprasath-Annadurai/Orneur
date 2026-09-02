"""
CognitiveTrace never stores raw chain-of-thought (Phase 3 spec §25-26);
cognitive metrics stay low-cardinality (Phase 3 spec §33).
"""
from __future__ import annotations

import asyncio

import pytest

from orca.cognitive import metrics
from orca.cognitive.contracts import CognitiveRequest, CognitiveState
from orca.cognitive.kernel import CognitiveKernel
from orca.cognitive.trace import CognitiveTraceBuilder
from orca.gateway import wiring


@pytest.fixture(autouse=True)
def _reset():
    wiring.reset_for_tests()
    metrics.reset()
    yield
    wiring.reset_for_tests()
    metrics.reset()


def test_trace_builder_records_plan_without_raw_prompt_text():
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="How do I rm -rf the production database?")
    plan = kernel.plan(req)
    builder = CognitiveTraceBuilder(req.request_id, req.trace_id)
    builder.record_plan(plan)
    trace = builder.finalize(plan.budget)
    assert trace.intent_decision is not None
    assert req.objective not in str(trace.decision_explanations)
    for explanation in trace.decision_explanations:
        assert len(explanation) < 200  # short, structured -- never a prose dump


def test_trace_abstention_reason_recorded():
    builder = CognitiveTraceBuilder("req-1", "trace-1")
    from orca.cognitive.contracts import AbstentionReason
    builder.record_abstention(AbstentionReason.BUDGET_EXHAUSTED)
    trace = builder.finalize()
    assert trace.abstention_reason == AbstentionReason.BUDGET_EXHAUSTED


def test_metrics_snapshot_has_no_high_cardinality_labels():
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="What's the capital of France?")
    kernel.plan(req)
    snapshot = metrics.get_snapshot()
    assert snapshot["cognitive_requests_total"] == 0  # plan() alone doesn't record a request
    assert "FACTUAL" in snapshot["intent_distribution"] or sum(snapshot["intent_distribution"].values()) >= 1
    for key in snapshot["intent_distribution"]:
        assert len(key) < 40  # enum values, not raw text


@pytest.mark.asyncio
async def test_execute_records_request_and_abstention_metrics():
    """Since Phase 4, VERIFY is SUPPORTED_NOW via Truth Fabric, so this
    AUDIT_GRADE request abstains with INSUFFICIENT_EVIDENCE (no doc_store
    given -> no evidence found) rather than the old static
    INSUFFICIENT_CAPABILITY abstention."""
    kernel = CognitiveKernel()
    req = CognitiveRequest(objective="How do I rm -rf the production database?")
    await kernel.execute(req)
    snapshot = metrics.get_snapshot()
    assert snapshot["cognitive_requests_total"] == 1
    assert snapshot["abstention_reasons"].get("INSUFFICIENT_EVIDENCE") == 1
