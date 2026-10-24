"""The readiness gate reports blockers and does not accept the production ledger."""
from __future__ import annotations

import json

from orca.pretrain_foundation.readiness_gate import (
    BLOCKER_CODES,
    LEDGER_PATH,
    Observation,
    blocker_codes,
    production_report,
    report,
)


def _clear(**overrides) -> Observation:
    observation = Observation(
        r65_status="MAPPED",
        r65_child_count=65,
        c27_status="ACCEPTED",
        trust_anchor_empty=False,
        protected_corpus_accepted=True,
        private_eval_frozen=True,
        foundation_selected=True,
        compute_qualified=True,
        independent_review_accepted=True,
        data_licensing_resolved=True,
        training_authorized=True,
        counted=2,
        numerator=0,
    )
    if overrides:
        observation = Observation(**{**observation.__dict__, **overrides})
    return observation


def test_production_report_is_blocked_and_does_not_edit_the_ledger():
    before = LEDGER_PATH.read_bytes()
    result = production_report()
    assert LEDGER_PATH.read_bytes() == before
    assert json.loads(LEDGER_PATH.read_text(encoding="utf-8")) == []
    assert result["counted"] == 95
    assert result["numerator"] == 0
    assert result["ledger_accepted_count"] == 0
    assert result["formally_accepted"] == []
    assert result["execution_allowed"] is False
    assert result["founder_authorized"] is False
    assert result["readiness_reportable"] is False
    assert result["gate"] == "BLOCKED"
    assert result["blockers"] == list(BLOCKER_CODES)


def test_a_clear_fixture_is_not_execution_permission():
    result = report(_clear(), {})
    assert blocker_codes(_clear()) == []
    assert result["gate"] == "BLOCKERS_CLEAR_NOT_ACCEPTED"
    assert result["execution_allowed"] is False
    assert result["founder_authorized"] is False
    assert result["readiness_reportable"] is False


def test_blockers_keep_a_supplied_execution_id_from_authorizing_training():
    result = report(_clear(c27_status="NOT_STARTED"), {"EXEC-1": "fixture"})
    assert "c27_unmet" in result["blockers"]
    assert result["execution_allowed"] is False
    assert result["founder_authorized"] is False


def test_each_named_blocker_fires_on_its_own_negative_fixture():
    cases = {
        "r65_unmapped": {"r65_status": "NOT_VERIFIABLE", "r65_child_count": 0},
        "c27_unmet": {"c27_status": "NOT_STARTED"},
        "trust_anchors_absent": {"trust_anchor_empty": True},
        "protected_corpus_evidence_absent": {"protected_corpus_accepted": False},
        "private_evaluation_unfrozen": {"private_eval_frozen": False},
        "foundation_not_selected": {"foundation_selected": False},
        "compute_unqualified": {"compute_qualified": False},
        "independent_reviews_missing": {"independent_review_accepted": False},
        "real_data_licensing_unresolved": {"data_licensing_resolved": False},
        "training_authorization_absent": {"training_authorized": False},
    }
    assert set(cases) == set(BLOCKER_CODES)
    for code, overrides in cases.items():
        assert blocker_codes(_clear(**overrides)) == [code]
