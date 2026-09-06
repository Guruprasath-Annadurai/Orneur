"""
Intent/complexity/risk/freshness/evidence classifiers -- all deterministic,
rules-first (Phase 3 spec §7-12). No model calls; same input always
produces the same output.
"""
from __future__ import annotations

from orca.cognitive.complexity import assess_complexity
from orca.cognitive.contracts import (
    ComplexityLevel,
    EvidenceLevel,
    FreshnessLevel,
    IntentCategory,
    RiskLevel,
)
from orca.cognitive.evidence import assess_evidence_requirement
from orca.cognitive.freshness import assess_freshness
from orca.cognitive.intent import compile_intent
from orca.cognitive.risk import assess_risk


# ── Intent ───────────────────────────────────────────────────────────────

def test_intent_is_deterministic():
    msg = "Can you write a function to sort a list in Python?"
    assert compile_intent(msg) == compile_intent(msg)


def test_intent_coding():
    plan = compile_intent("Write a function that reverses a string in Python.")
    assert plan.primary_intent == IntentCategory.CODING
    assert plan.expected_output_type.value == "CODE"


def test_intent_multi_label():
    plan = compile_intent("Research the topic and explain why it matters, step by step.")
    all_intents = {plan.primary_intent, *plan.secondary_intents}
    assert IntentCategory.RESEARCH in all_intents
    assert IntentCategory.REASONING in all_intents


def test_intent_memory_recall():
    plan = compile_intent("Remember when we talked about the project deadline?")
    assert plan.requires_memory


def test_intent_unknown_when_no_pattern_matches():
    plan = compile_intent("purple elephants dance quietly under moonlight fragments")
    assert plan.primary_intent == IntentCategory.UNKNOWN


def test_intent_document_analysis_requires_retrieval():
    plan = compile_intent("Please summarize this document for me.")
    assert plan.requires_retrieval


def test_intent_citation_requirement_for_research():
    plan = compile_intent("Research the origins of the internet and cite your sources.")
    assert plan.citation_requirement


# ── Complexity ───────────────────────────────────────────────────────────

def test_complexity_trivial_greeting():
    intent = compile_intent("hello")
    c = assess_complexity("hello", intent)
    assert c.level == ComplexityLevel.TRIVIAL


def test_complexity_long_but_simple_message_is_not_automatically_high():
    """Length alone must not equate to complexity (Phase 3 spec §9)."""
    long_simple = "hello " * 80  # long, but zero complexity signals
    intent = compile_intent(long_simple)
    c = assess_complexity(long_simple, intent)
    assert c.level in (ComplexityLevel.TRIVIAL, ComplexityLevel.LOW)
    assert c.score < 0.35


def test_complexity_multi_step_reasoning_scores_higher():
    msg = "Compare the trade-offs of X vs Y, analyze the pros and cons step by step, and delegate follow-up research to another agent."
    intent = compile_intent(msg)
    c = assess_complexity(msg, intent)
    assert c.level in (ComplexityLevel.HIGH, ComplexityLevel.DEEP)
    assert c.score > 0.5


def test_complexity_score_is_bounded_0_to_1():
    msg = "Compare, analyze, trade-offs, pros and cons, step-by-step, comprehensive, in depth. " * 5
    intent = compile_intent(msg)
    c = assess_complexity(msg, intent)
    assert 0.0 <= c.score <= 1.0


# ── Risk ─────────────────────────────────────────────────────────────────

def test_risk_low_by_default():
    intent = compile_intent("What's the capital of France?")
    r = assess_risk("What's the capital of France?", intent)
    assert r.level == RiskLevel.LOW


def test_risk_critical_for_destructive_action():
    msg = "How do I rm -rf the production database?"
    intent = compile_intent(msg)
    r = assess_risk(msg, intent)
    assert r.level == RiskLevel.CRITICAL


def test_risk_high_for_financial_consequence():
    msg = "Please execute trade to buy stock on my behalf."
    intent = compile_intent(msg)
    r = assess_risk(msg, intent)
    assert r.level == RiskLevel.HIGH


def test_risk_moderate_for_production_mention():
    msg = "What's the deployment status of the production environment?"
    intent = compile_intent(msg)
    r = assess_risk(msg, intent)
    assert r.level == RiskLevel.MODERATE


# ── Freshness ────────────────────────────────────────────────────────────

def test_freshness_static_for_math():
    f = assess_freshness("What is the proof of the Pythagorean theorem?")
    assert f.level == FreshnessLevel.STATIC


def test_freshness_real_time_for_stock_price():
    f = assess_freshness("What is the current stock price right now?")
    assert f.level == FreshnessLevel.REAL_TIME


def test_freshness_current_for_latest():
    f = assess_freshness("What's the latest version of the library?")
    assert f.level == FreshnessLevel.CURRENT


# ── Evidence ─────────────────────────────────────────────────────────────

def test_evidence_none_for_conversational():
    intent = compile_intent("hey, how's it going?")
    r = assess_risk("hey, how's it going?", intent)
    e = assess_evidence_requirement(intent, r)
    assert e.level == EvidenceLevel.NONE


def test_evidence_strict_for_research():
    msg = "Research the security implications and cite your sources."
    intent = compile_intent(msg)
    r = assess_risk(msg, intent)
    e = assess_evidence_requirement(intent, r)
    assert e.level == EvidenceLevel.STRICT


def test_evidence_audit_grade_for_critical_risk():
    msg = "How do I rm -rf the production database?"
    intent = compile_intent(msg)
    r = assess_risk(msg, intent)
    e = assess_evidence_requirement(intent, r)
    assert e.level == EvidenceLevel.AUDIT_GRADE


def test_evidence_supported_default():
    msg = "What's the boiling point of water at sea level?"
    intent = compile_intent(msg)
    r = assess_risk(msg, intent)
    e = assess_evidence_requirement(intent, r)
    assert e.level == EvidenceLevel.SUPPORTED
