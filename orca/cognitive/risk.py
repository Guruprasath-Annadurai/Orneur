"""
Risk Assessment -- cognitive consequence awareness, NOT Godmode
authorization (Phase 3 spec §10, §37). This module only classifies; it
never grants or denies a capability. The result later informs completion
conditions / evidence requirements (e.g. higher risk implies stricter
evidence, see planner.py), not permission.
"""
from __future__ import annotations

import re

from orca.cognitive.contracts import IntentPlan, PrivacyClass, RiskAssessment, RiskLevel

_DESTRUCTIVE_RE = re.compile(
    r"\b(delete|drop table|rm -rf|force[- ]push|wipe|destroy|shut ?down production|"
    r"terminate (all|the) instances?)\b", re.IGNORECASE,
)
_FINANCIAL_RE = re.compile(
    r"\b(wire transfer|send money|buy stock|sell stock|execute trade|place (an? )?order|"
    r"crypto (swap|transfer))\b", re.IGNORECASE,
)
_SECURITY_RE = re.compile(
    r"\b(exploit|vulnerability|bypass auth|credentials?|api key|password|privilege escalation|"
    r"malware|ransomware)\b", re.IGNORECASE,
)
_PRODUCTION_RE = re.compile(r"\b(production|prod environment|live (system|database))\b", re.IGNORECASE)
_LEGAL_RE = re.compile(r"\b(legal advice|contract terms|compliance|regulat(ion|ory)|lawsuit)\b", re.IGNORECASE)


def assess_risk(message: str, intent: IntentPlan) -> RiskAssessment:
    """
    Deterministic, additive: each matched factor raises the level by at
    most one step per category, capped at CRITICAL. A message with no
    matched signal is LOW, not MODERATE-by-default -- absence of risk
    language is itself meaningful, not an unknown state to round up from.
    """
    factors: list[str] = []
    level = RiskLevel.LOW

    def _raise_to(new_level: RiskLevel) -> None:
        nonlocal level
        order = [RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL]
        if order.index(new_level) > order.index(level):
            level = new_level

    if _DESTRUCTIVE_RE.search(message):
        factors.append("destructive-action language matched")
        _raise_to(RiskLevel.CRITICAL)
    if _FINANCIAL_RE.search(message):
        factors.append("financial-consequence language matched")
        _raise_to(RiskLevel.HIGH)
    if _SECURITY_RE.search(message):
        factors.append("security-sensitive language matched")
        _raise_to(RiskLevel.HIGH)
    if _PRODUCTION_RE.search(message):
        factors.append("production-impact language matched")
        _raise_to(RiskLevel.MODERATE)
    if _LEGAL_RE.search(message):
        factors.append("legal/compliance-sensitive language matched")
        _raise_to(RiskLevel.MODERATE)
    if intent.privacy_class in (PrivacyClass.SENSITIVE, PrivacyClass.RESTRICTED):
        factors.append(f"privacy_class={intent.privacy_class.value}")
        _raise_to(RiskLevel.MODERATE)

    if not factors:
        factors.append("no risk signals found")

    return RiskAssessment(level=level, factors=factors)
