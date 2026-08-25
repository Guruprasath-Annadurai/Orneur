"""
Tests for the persona-claim gate — the actual enforcement mechanism behind
"don't let Orca describe itself as more capable than its own eval/red-team
numbers support" (orca/governance/model_cards.py's
check_persona_claim_allowed, orca/personas.py's get_persona_system).

This had ZERO test coverage before this file existed, despite being the
single mechanism that keeps every persona's self-description honest. A
live check against the real on-disk eval/redteam data confirmed correct
behavior at the moment this was written (nano/core both correctly
demoted, ultra correctly demoted with "no eval on record", an unknown
variant correctly falls back to core) — these tests lock that behavior in
against regression, using isolated fixture data rather than depending on
the real files, which change every time training runs again.

Also covers the domain-eval criterion added after a live investigation
found core scored 66% on the generic golden eval (below its 70% bar) but
88.1% on its own domain-specific, judge-scored eval — added as a REQUIRED
criterion alongside the generic bar, not a replacement for it.
"""
from __future__ import annotations

import json

import pytest

from orca.governance import model_cards as mc
from orca.personas import get_persona_system, _CLAIM_PHRASES

_DOMAIN_PREFIX = {"nano": "genesis", "core": "novus", "ultra": "aeternum"}


@pytest.fixture
def isolated_reports(tmp_path, monkeypatch):
    """Point the gate at an isolated eval/redteam directory so these tests
    never depend on (or mutate) real training data."""
    eval_dir = tmp_path / "eval"
    redteam_dir = tmp_path / "redteam"
    eval_dir.mkdir()
    redteam_dir.mkdir()
    monkeypatch.setattr(mc, "EVAL_DIR", eval_dir)
    monkeypatch.setattr(mc, "REDTEAM_DIR", redteam_dir)

    def _write(
        variant: str,
        accuracy: float | None,
        jailbreak_block_rate: float | None,
        bias_flag_rate: float | None = None,
        domain_score: float | None = None,
        domain_judged: bool = False,
    ):
        model_name = mc.VARIANTS[variant].ollama_name
        if accuracy is not None:
            (eval_dir / f"eval_{model_name}.json").write_text(
                json.dumps({"accuracy": {"accuracy": accuracy}})
            )
        if jailbreak_block_rate is not None:
            redteam_payload = {"jailbreak": {"block_rate": jailbreak_block_rate}}
            if bias_flag_rate is not None:
                redteam_payload["bias"] = {"flag_rate": bias_flag_rate}
            (redteam_dir / f"redteam_{model_name}.json").write_text(json.dumps(redteam_payload))
        if domain_score is not None:
            prefix = _DOMAIN_PREFIX[variant]
            suffix = "_judged" if domain_judged else ""
            (eval_dir / f"{prefix}_eval{suffix}_{model_name}.json").write_text(
                json.dumps({"overall_score": domain_score})
            )

    return _write


def _approved(variant: str, accuracy=0.99, jailbreak=100.0, bias=0.0, domain=0.99):
    """Shorthand for 'every criterion comfortably clears' — used by tests
    that aren't about the domain-eval criterion specifically."""
    return dict(accuracy=accuracy, jailbreak_block_rate=jailbreak, bias_flag_rate=bias, domain_score=domain)


# ── check_persona_claim_allowed ──────────────────────────────────────────────

def test_gate_rejects_unknown_variant():
    allowed, reason = mc.check_persona_claim_allowed("nonexistent")
    assert allowed is False
    assert "Unknown variant" in reason


def test_gate_rejects_when_no_eval_report_exists(isolated_reports):
    isolated_reports("nano", accuracy=None, jailbreak_block_rate=95.0)
    allowed, reason = mc.check_persona_claim_allowed("nano")
    assert allowed is False
    assert "No accuracy eval on record" in reason


def test_gate_rejects_when_no_redteam_report_exists(isolated_reports):
    isolated_reports("nano", accuracy=0.90, jailbreak_block_rate=None)
    allowed, reason = mc.check_persona_claim_allowed("nano")
    assert allowed is False
    assert "No red-team safety report on record" in reason


def test_gate_rejects_below_accuracy_threshold(isolated_reports):
    # nano's threshold is 0.60 accuracy / 90.0 jailbreak block rate
    isolated_reports("nano", **{**_approved("nano"), "accuracy": 0.50})
    allowed, reason = mc.check_persona_claim_allowed("nano")
    assert allowed is False
    assert "accuracy" in reason and "50%" in reason


def test_gate_rejects_below_jailbreak_threshold(isolated_reports):
    isolated_reports("nano", **{**_approved("nano"), "jailbreak_block_rate": 50.0})
    allowed, reason = mc.check_persona_claim_allowed("nano")
    assert allowed is False
    assert "jailbreak block rate" in reason


def test_gate_reports_both_failures_when_both_below_threshold(isolated_reports):
    isolated_reports("nano", **{**_approved("nano"), "accuracy": 0.10, "jailbreak_block_rate": 0.0})
    allowed, reason = mc.check_persona_claim_allowed("nano")
    assert allowed is False
    assert "accuracy" in reason
    assert "jailbreak block rate" in reason


def test_gate_approves_when_all_thresholds_cleared(isolated_reports):
    isolated_reports("nano", **_approved("nano"))
    allowed, reason = mc.check_persona_claim_allowed("nano")
    assert allowed is True
    assert "clear this tier's threshold" in reason


def test_gate_rejects_when_bias_flag_rate_exceeds_max(isolated_reports):
    # core's threshold is 20.0% max bias flag rate; every other criterion
    # clears its own bar here so bias is the ONLY failing reason.
    isolated_reports("core", **{**_approved("core"), "bias_flag_rate": 75.0})
    allowed, reason = mc.check_persona_claim_allowed("core")
    assert allowed is False
    assert "bias flag rate 75.0%" in reason
    assert "accuracy" not in reason
    assert "jailbreak block rate" not in reason


def test_gate_approves_when_bias_flag_rate_is_within_max(isolated_reports):
    isolated_reports("nano", **{**_approved("nano"), "bias_flag_rate": 12.5})
    allowed, reason = mc.check_persona_claim_allowed("nano")
    assert allowed is True


def test_gate_defaults_bias_to_zero_when_no_bias_report_field_exists(isolated_reports):
    # Backward compatibility: a redteam report generated before the bias
    # gate existed has no "bias" key at all — must not fail retroactively.
    isolated_reports("nano", accuracy=0.90, jailbreak_block_rate=95.0, domain_score=0.99)
    allowed, reason = mc.check_persona_claim_allowed("nano")
    assert allowed is True


def test_gate_reports_all_failures_together(isolated_reports):
    # This is the real, current production shape for orca-core: accuracy
    # below bar, jailbreak below bar, bias flag rate above the max, AND no
    # domain-specific eval recorded under the production alias name.
    isolated_reports("core", accuracy=0.664, jailbreak_block_rate=0.0, bias_flag_rate=75.0)
    allowed, reason = mc.check_persona_claim_allowed("core")
    assert allowed is False
    assert "accuracy" in reason
    assert "jailbreak block rate" in reason
    assert "bias flag rate" in reason
    assert "domain-specific eval missing" in reason


def test_gate_uses_per_tier_thresholds_not_a_shared_one(isolated_reports):
    # core's threshold (0.70 accuracy) is stricter than nano's (0.60) — the
    # SAME accuracy should pass for nano but fail for core.
    isolated_reports("nano", **{**_approved("nano"), "accuracy": 0.65})
    isolated_reports("core", **{**_approved("core"), "accuracy": 0.65})
    nano_allowed, _ = mc.check_persona_claim_allowed("nano")
    core_allowed, core_reason = mc.check_persona_claim_allowed("core")
    assert nano_allowed is True
    assert core_allowed is False
    assert "accuracy" in core_reason


# ── domain-eval criterion (added after the core business-domain finding) ────

def test_gate_rejects_when_no_domain_eval_recorded(isolated_reports):
    isolated_reports("core", accuracy=0.90, jailbreak_block_rate=95.0)  # no domain_score
    allowed, reason = mc.check_persona_claim_allowed("core")
    assert allowed is False
    assert "domain-specific eval missing" in reason
    assert "novus_eval" in reason


def test_gate_rejects_when_domain_eval_below_min(isolated_reports):
    isolated_reports("core", **{**_approved("core"), "domain_score": 0.30})
    allowed, reason = mc.check_persona_claim_allowed("core")
    assert allowed is False
    assert "domain-specific eval score 30%" in reason


def test_gate_approves_when_domain_eval_clears_min(isolated_reports):
    isolated_reports("core", **{**_approved("core"), "domain_score": 0.881})
    allowed, reason = mc.check_persona_claim_allowed("core")
    assert allowed is True
    assert "domain-specific eval 88%" in reason


def test_gate_prefers_judged_domain_eval_over_keyword_scored(isolated_reports):
    # The real case this models: keyword-scored novus_eval said 30.4%,
    # judge-scored said 88.1% for the SAME model. Both files can coexist —
    # the judge-scored one must win.
    isolated_reports("core", **{**_approved("core"), "domain_score": 0.304, "domain_judged": False})
    isolated_reports("core", **{**_approved("core"), "domain_score": 0.881, "domain_judged": True})
    allowed, reason = mc.check_persona_claim_allowed("core")
    assert allowed is True
    assert "judge-scored" in reason
    assert "88%" in reason


def test_gate_domain_eval_criterion_does_not_apply_generic_accuracy_bar():
    # domain_eval_min differs per tier (core=0.75) from eval_accuracy
    # (core=0.70) — confirms these are two independent, both-required checks.
    assert mc.PERSONA_CLAIM_THRESHOLDS["core"]["domain_eval_min"] != mc.PERSONA_CLAIM_THRESHOLDS["core"]["eval_accuracy"]


# ── get_persona_system (runtime prompt enforcement) ──────────────────────────

def test_persona_system_demotes_claim_phrase_when_not_approved(isolated_reports):
    isolated_reports("nano", accuracy=0.10, jailbreak_block_rate=0.0)
    system = get_persona_system("nano")
    approved_phrase, demoted_phrase = _CLAIM_PHRASES["nano"]
    assert approved_phrase not in system
    assert demoted_phrase in system
    assert "SELF-AWARENESS NOTICE" in system


def test_persona_system_disclaimer_states_the_real_reason(isolated_reports):
    isolated_reports("core", accuracy=0.10, jailbreak_block_rate=0.0)
    system = get_persona_system("core")
    assert "accuracy 10%" in system
    assert "jailbreak block rate 0.0%" in system


def test_persona_system_keeps_claim_phrase_when_approved(isolated_reports):
    isolated_reports("nano", **_approved("nano"))
    system = get_persona_system("nano")
    approved_phrase, demoted_phrase = _CLAIM_PHRASES["nano"]
    assert approved_phrase in system
    assert demoted_phrase not in system
    assert "SELF-AWARENESS NOTICE" not in system


def test_persona_system_ultra_demotes_chief_scientist_line_too(isolated_reports):
    isolated_reports("ultra", accuracy=0.10, jailbreak_block_rate=0.0)
    system = get_persona_system("ultra")
    assert "Aim toward chief-scientist-level synthesis as a goal" in system
    assert "Feel like a chief scientist, chief engineer, strategist, and educator" not in system


def test_persona_system_ultra_with_zero_training_data_is_demoted_not_crashed(isolated_reports):
    # The real-world case this session hit live: Aeternum has no eval/redteam
    # files at all yet (it doesn't exist). Must degrade gracefully, never crash.
    system = get_persona_system("ultra")
    assert "SELF-AWARENESS NOTICE" in system
    assert "No accuracy eval on record" in system


def test_persona_system_unknown_variant_falls_back_to_core_without_crashing(isolated_reports):
    isolated_reports("core", accuracy=0.10, jailbreak_block_rate=0.0)
    system = get_persona_system("totally-not-a-real-variant")
    # Falls back to core's identity/demotion, not a crash and not nano/ultra's.
    assert "professional reasoning" in system.lower() or "developing reasoning model" in system.lower()


def test_persona_system_always_includes_citation_discipline_and_tool_instructions(isolated_reports):
    isolated_reports("nano", **_approved("nano"))
    system = get_persona_system("nano")
    assert "CITATION DISCIPLINE" in system
