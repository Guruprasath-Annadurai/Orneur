"""
ORNEUR final live-grounding truth micro-closure regression tests.

Verified current behavior (traced through the real code, not inferred):
- search_and_ground() marks sources with [S#].
- AgentLoop can call web_search via the same registry the live chat path
  uses (see tests/test_search_grounding_live_wiring.py for deep coverage).
- check_web_citations() (orca/docs/citation_check.py) is a marker-presence
  check: it flags compliant=False when web sources were available but the
  response used zero [S#] markers.
- orca/brain/agent.py's AgentLoop records that result as
  trace.citation_compliance on every turn but does not branch on it.
- orca/serve/api.py's /api/chat logs a citation_compliance_failed audit
  event and surfaces the report in the response stream, but does not
  block, retry, repair, or abstain the answer because compliance failed.

That is citation-marked grounding with citation-compliance checking, not
hard citation enforcement. This file guards against public docs drifting
back to the stronger "enforced citations" claim, and against the
differentiation doc re-acquiring a stale instruction to wire something
that is already wired.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_web_search_tool_remains_registered():
    from orca.tools import build_registry

    assert "web_search" in build_registry().all_names()


def test_live_agent_loop_path_uses_the_same_registry():
    """Source-inspection tripwire (kept alongside the deeper coverage in
    tests/test_search_grounding_live_wiring.py) that the real chat session
    class still wires build_registry() -- not a stub or disconnected
    registry -- into the AgentLoop that actually executes tool calls."""
    from orca.brain.agent import AgentLoop
    from orca.serve.api import _Session

    assert "build_registry(" in inspect.getsource(_Session._ensure_agent)
    assert "self.tools.call(" in inspect.getsource(AgentLoop.run) or \
           "self.tools.call(" in inspect.getsource(AgentLoop)


def test_check_web_citations_flags_missing_markers_as_not_compliant():
    from orca.docs.citation_check import check_web_citations

    tool_context = "[S1] Example source snippet about the topic.\n[S2] Another source."
    response_without_markers = "Here is an answer with no citation markers at all."

    result = check_web_citations(response_without_markers, tool_context)
    assert result["had_sources"] is True
    assert result["compliant"] is False
    assert result["citations_used"] == []


def test_check_web_citations_compliant_when_marker_present():
    from orca.docs.citation_check import check_web_citations

    tool_context = "[S1] Example source snippet about the topic."
    response_with_marker = "Per [S1], the answer is confirmed."

    result = check_web_citations(response_with_marker, tool_context)
    assert result["had_sources"] is True
    assert result["compliant"] is True
    assert "[S1]" in result["citations_used"]


def test_agent_loop_does_not_block_on_noncompliant_citations():
    """AgentLoop.run/stream compute trace.citation_compliance but must not
    gate, retry, or replace the returned answer on it -- that would be
    hard enforcement, which is explicitly not what this closure builds."""
    run_source = inspect.getsource(__import__("orca.brain.agent", fromlist=["AgentLoop"]).AgentLoop.run)
    # The compliance check runs, but nothing in run() branches control
    # flow on trace.citation_compliance (no if/raise/return keyed off it).
    compliance_line = next(
        (line for line in run_source.splitlines() if "citation_compliance = check_web_citations" in line),
        None,
    )
    assert compliance_line is not None, "expected trace.citation_compliance assignment in AgentLoop.run"
    after_assignment = run_source.split("citation_compliance = check_web_citations", 1)[1]
    assert "if trace.citation_compliance" not in after_assignment
    assert "raise" not in after_assignment.split("return")[0]


PUBLIC_DOCS = {
    "README.md": (REPO_ROOT / "README.md").read_text(encoding="utf-8"),
    "docs/PERPLEXITY_DIFFERENTIATION_PLAN.md": (REPO_ROOT / "docs/PERPLEXITY_DIFFERENTIATION_PLAN.md").read_text(encoding="utf-8"),
    "docs/MODEL_CARDS.md": (REPO_ROOT / "docs/MODEL_CARDS.md").read_text(encoding="utf-8"),
    "orca/serve/web/landing.html": (REPO_ROOT / "orca/serve/web/landing.html").read_text(encoding="utf-8"),
    "orca/serve/web/trust.html": (REPO_ROOT / "orca/serve/web/trust.html").read_text(encoding="utf-8"),
    "orca/serve/web/index.html": (REPO_ROOT / "orca/serve/web/index.html").read_text(encoding="utf-8"),
}

# "enforced persona-claim gate" and "append-only enforcement" are real,
# distinct, correctly-scoped claims about other subsystems -- only the
# specific citation/web-grounding overclaim is checked here.
_STALE_CITATION_ENFORCEMENT_PATTERNS = [
    re.compile(r"enforced\s+citations?\b", re.IGNORECASE),
    re.compile(r"citations?\s+enforcement\b", re.IGNORECASE),
    re.compile(r"\[S#?\]\s*citation\s+enforcement", re.IGNORECASE),
]


def test_no_active_public_doc_calls_current_behavior_enforced_citations():
    for doc_name, text in PUBLIC_DOCS.items():
        for pattern in _STALE_CITATION_ENFORCEMENT_PATTERNS:
            for match in pattern.finditer(text):
                window = text[max(0, match.start() - 200):match.end() + 200].lower()
                # Allow the phrase only inside an explicit historical/
                # corrected disclosure (quote-and-correct pattern already
                # used elsewhere in this closure), never as a bare claim.
                assert "original plan" in window or "corrected" in window or "not hard citation enforcement" in window or "not claim-level verification" in window, (
                    f"{doc_name} still asserts 'enforced citations' / 'citation "
                    f"enforcement' as current behavior without a correction "
                    f"nearby: {match.group()!r} in context {window!r}"
                )


def test_perplexity_doc_has_no_live_instruction_to_wire_already_wired_module():
    diff_doc = PUBLIC_DOCS["docs/PERPLEXITY_DIFFERENTIATION_PLAN.md"]

    # The doc may still discuss the historical instruction, but only while
    # explicitly flagging it as stale/corrected -- never as a live,
    # unqualified "go do this" instruction.
    for match in re.finditer(r"wire[^.\n]{0,40}search_grounding\.py[^.\n]{0,60}(into the real|chat path)", diff_doc, re.IGNORECASE):
        window = diff_doc[max(0, match.start() - 150):match.end() + 150].lower()
        assert "already wired" in window or "corrected" in window or "stale" in window, (
            "differentiation doc still instructs wiring search_grounding.py "
            "into the chat path as if it were not already wired"
        )

    assert "already wired into the real chat path" in diff_doc.lower()


def test_perplexity_doc_technical_gap_framed_as_historical_not_current():
    diff_doc = PUBLIC_DOCS["docs/PERPLEXITY_DIFFERENTIATION_PLAN.md"]
    for match in re.finditer(r"currently-missing technical piece is the search-grounding pipeline", diff_doc, re.IGNORECASE):
        window = diff_doc[max(0, match.start() - 200):match.end() + 100].lower()
        assert "at the time" in window or "since shipped" in window or "original plan" in window, (
            "the 'currently-missing technical piece' claim is not framed as "
            "historical even though the search-grounding pipeline has shipped"
        )
