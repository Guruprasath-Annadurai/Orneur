"""The readiness gate reports blockers and does not accept the production ledger."""
from __future__ import annotations

import json

from orca.pretrain_foundation.readiness_gate import (
    BLOCKER_CODES,
    GRAPH_PATH,
    LEDGER_PATH,
    ROOT,
    Observation,
    _claims_for_engine_map,
    _known_requirement_ids,
    blocker_codes,
    production_report,
    report,
    report_evaluated,
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


def test_forged_identifiers_cannot_authorize_a_cleared_synthetic_observation():
    """Reproduced on the previous gate: this call returned execution_allowed true."""
    forged = {"EXEC-1": "forged", "FINAL-2": "forged"}
    result = report(_clear(counted=2, numerator=2), forged)
    assert result["interface"] == "SYNTHETIC_OBSERVATION"
    assert result["authorization_source"] == "none"
    assert result["execution_allowed"] is False
    assert result["founder_authorized"] is False
    assert result["readiness_reportable"] is False
    assert result["formally_accepted"] == []
    assert result["supplied_identifiers_ignored"] == ["EXEC-1", "FINAL-2"]
    duplicated = report(_clear(), ["EXEC-1", "EXEC-1", "NOT-A-ROW"])
    assert duplicated["execution_allowed"] is False
    assert duplicated["supplied_identifiers_ignored"] == ["EXEC-1", "EXEC-1", "NOT-A-ROW"]


def _evaluated_kwargs():
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    empty = {
        "trust_snapshot": json.loads((ROOT / "docs/orneur/acceptance/reviewer_trust.json").read_text(encoding="utf-8")),
        "root_state": json.loads((ROOT / "docs/orneur/acceptance/founder_root_keys.json").read_text(encoding="utf-8")),
        "bootstrap_root_key_hex": "",
        "trust_checkpoint": json.loads((ROOT / "docs/orneur/acceptance/TRUST_CHECKPOINT.json").read_text(encoding="utf-8")),
        "pinned_checkpoint_hash": "",
    }
    return {
        "subject_sha": "a" * 40,
        "observation": _clear(),
        "nodes": graph["nodes"],
        "pretraining_ids": graph["denominator_pretraining_ids"],
        "known_ids": _known_requirement_ids(graph),
        **empty,
    }


def test_unverified_ledger_shapes_stay_unauthorized():
    before = LEDGER_PATH.read_bytes()
    kwargs = _evaluated_kwargs()
    stale = report_evaluated(
        [{"requirement_id": "G1", "git_sha": "b" * 40}],
        **kwargs,
    )
    duplicate = report_evaluated(
        [
            {"requirement_id": "G1", "git_sha": "a" * 40},
            {"requirement_id": "G1", "git_sha": "a" * 40},
        ],
        **kwargs,
    )
    unknown = report_evaluated(
        [{"requirement_id": "NOT-A-ROW", "git_sha": "a" * 40}],
        **kwargs,
    )
    missing = report_evaluated(
        [{"requirement_id": "G1", "git_sha": "a" * 40}],
        **kwargs,
    )
    incomplete = report_evaluated([], **kwargs)
    for result in (stale, duplicate, unknown, missing, incomplete):
        assert result["execution_allowed"] is False
        assert result["founder_authorized"] is False
        assert result["readiness_reportable"] is False
        assert result["interface"] == "ACCEPTANCE_ENGINE"
    assert "stale_evidence" in stale["refusal_reasons"]
    assert "duplicate_identifier" in duplicate["refusal_reasons"]
    assert "wrong_denominator_id" in unknown["refusal_reasons"]
    assert "missing_authority" in missing["refusal_reasons"]
    assert missing["engine_error"] == "WRONG_ROOT_STATE_SHA"
    assert incomplete["formally_accepted"] == []
    assert LEDGER_PATH.read_bytes() == before


def test_engine_map_predicate_is_not_reachable_through_the_synthetic_report():
    ids = [f"row-{index}" for index in range(95)]
    accepted = {item: "ab" * 32 for item in ids}
    accepted["EXEC-1"] = "cd" * 32
    accepted["FINAL-2"] = "ef" * 32
    known = set(accepted)
    observation = _clear(counted=95, numerator=95)
    claims = _claims_for_engine_map(
        observation, accepted, pretraining_ids=ids, known_ids=known,
    )
    assert claims["execution_allowed"] is True
    assert claims["founder_authorized"] is True
    wrong = dict(accepted)
    wrong["NOT-A-ROW"] = "00" * 32
    assert _claims_for_engine_map(
        observation, wrong, pretraining_ids=ids, known_ids=known,
    )["execution_allowed"] is False
    partial = dict(accepted)
    partial.pop(ids[0])
    assert _claims_for_engine_map(
        observation, partial, pretraining_ids=ids, known_ids=known,
    )["execution_allowed"] is False
    blocked = _claims_for_engine_map(
        _clear(counted=95, c27_status="NOT_STARTED"),
        accepted,
        pretraining_ids=ids,
        known_ids=known,
    )
    assert blocked["execution_allowed"] is False
    public = report(observation, accepted)
    assert public["execution_allowed"] is False
    assert public["formally_accepted"] == []


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
