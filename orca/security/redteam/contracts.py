"""
Phase 13 typed contracts (spec §7-8): SecurityFinding for genuinely
discovered vulnerabilities, and the closed campaign-category enum.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _new_id() -> str:
    return f"finding-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CampaignCategory(str, Enum):
    PROMPT_INJECTION = "PROMPT_INJECTION"
    AUTHORITY_ESCALATION = "AUTHORITY_ESCALATION"
    TENANT_ESCAPE = "TENANT_ESCAPE"
    RAG_POISONING = "RAG_POISONING"
    MEMORY_POISONING = "MEMORY_POISONING"
    TOOL_INJECTION = "TOOL_INJECTION"
    CONNECTOR_ATTACK = "CONNECTOR_ATTACK"
    GODMODE_ATTACK = "GODMODE_ATTACK"
    SIMULATION_ATTACK = "SIMULATION_ATTACK"
    LEARNING_POISONING = "LEARNING_POISONING"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    RACE_CONDITION = "RACE_CONDITION"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    SECRETS_EXFILTRATION = "SECRETS_EXFILTRATION"
    PROTOCOL_CONFUSION = "PROTOCOL_CONFUSION"
    STATE_CORRUPTION = "STATE_CORRUPTION"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Reproducibility(str, Enum):
    REPRODUCIBLE = "REPRODUCIBLE"
    INTERMITTENT = "INTERMITTENT"
    NOT_REPRODUCIBLE = "NOT_REPRODUCIBLE"


class FixStatus(str, Enum):
    OPEN = "OPEN"
    FIXED = "FIXED"
    DISPROVED = "DISPROVED"          # investigated, confirmed NOT a real vulnerability
    ACCEPTED_RISK = "ACCEPTED_RISK"  # real but deliberately not fixed this phase, disclosed


@dataclass
class SecurityFinding:
    finding_id: str = field(default_factory=_new_id)
    category: CampaignCategory = CampaignCategory.PROTOCOL_CONFUSION
    severity: Severity = Severity.LOW
    affected_subsystem: str = ""
    attack_preconditions: str = ""
    attack_input_reference: str = ""
    observed_behavior: str = ""
    expected_behavior: str = ""
    reproducibility: Reproducibility = Reproducibility.REPRODUCIBLE
    exploitability: str = ""
    impact: str = ""
    root_cause: str = ""
    fix_status: FixStatus = FixStatus.OPEN
    regression_test: str = ""        # e.g. "tests/test_x.py::test_y"
    cwe_like: str | None = None      # only when genuinely applicable -- never fabricated
    trace_reference: str = ""
    created_at: str = field(default_factory=_now_iso)


@dataclass
class CampaignRecord:
    """Links a category to the real evidence for it -- existing test
    files (already-passing, pre-Phase-13 coverage) and/or new ones added
    this phase. `attacks_executed` is the count of distinct adversarial
    assertions covered (not a fabricated score)."""
    category: CampaignCategory
    existing_test_files: list[str] = field(default_factory=list)
    new_test_files: list[str] = field(default_factory=list)
    attacks_executed: int = 0
    expected_blocks: int = 0
    findings: list[SecurityFinding] = field(default_factory=list)
    notes: str = ""
