"""Findings F3 and F5 (docs/orneur/status/evalinfra/INVENTORY.md).

F3: reproduces the numbering gap and validates the NON-FROZEN mapping proposal. F5: characterisation tests that pin the (unresolved) LLM-judge
inconsistency so that any later decision must update them deliberately. Neither changes evaluation behaviour; synthetic/static data only."""
import copy
import json
from pathlib import Path

import pytest

from orca.eval import genesis_eval_v1 as V1
from orca.eval import genesis_suite as GS
from orca.evalinfra import category_mapping_proposal as CM
from orca.evalinfra import schema as SC
from orca.evalinfra.prereg_check import REQUIRED_ZERO_TOLERANCE

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "docs/orneur/status/evalinfra/proposals/CATEGORY_MAPPING_PROPOSAL.NOT_FROZEN.json"


# ------------------------------------------------------------------------------------------------ F3
def test_f3_gap_reproduced_zero_tolerance_ids_are_spec_numbers_that_the_v2_corpus_does_not_use():
    assert set(REQUIRED_ZERO_TOLERANCE) == {10, 14, 15, 17} and set(REQUIRED_ZERO_TOLERANCE) <= set(GS.CATEGORY_NAMES)
    assert all(isinstance(c, str) for c in V1.CATEGORIES)                     # V2 corpus categories are names, not numbers
    assert not any(isinstance(c, int) for c in V1.CATEGORIES)
    names = {n.lower() for n in V1.CATEGORIES}
    assert not any("sovereign" in n or "security" in n or "presence" in n or "adversarial" in n for n in names)   # nothing for 14 / 15 / 17


def test_f3_proposal_is_valid_and_clearly_not_frozen():
    doc = json.loads(PROPOSAL.read_text())
    assert CM.validate(doc) == []
    assert doc["frozen"] is False and doc["status"] == "PROPOSAL_NOT_FROZEN_NOT_NORMATIVE" and "NOT_FROZEN" in PROPOSAL.name
    assert set(doc["uncovered_zero_tolerance_spec_ids"]) == {14, 15, 17}      # honest: the proposal does not paper over the gap
    assert {e["v2_category"] for e in doc["v2_to_spec"]} == set(V1.CATEGORIES)


def _mut(fn):
    d = json.loads(PROPOSAL.read_text())
    fn(d)
    return CM.validate(d)


@pytest.mark.parametrize("fn", [
    lambda d: d.update(frozen=True),
    lambda d: d.update(status="FROZEN"),
    lambda d: d.update(authorizes_nothing=False),
    lambda d: d.update(record_sha256="0" * 64),
    lambda d: d.update(frozen_at="2026-10-12T00:00:00Z"),
    lambda d: d.update(schema_version="orneur-category-mapping/1"),
    lambda d: d.update(banner="mapping"),
    lambda d: d["v2_to_spec"].pop(),
    lambda d: d["v2_to_spec"].append(copy.deepcopy(d["v2_to_spec"][0])),
    lambda d: d["v2_to_spec"][0].update(v2_category="not_a_category"),
    lambda d: d["v2_to_spec"][0].update(spec_ids=[99]),
    lambda d: d["v2_to_spec"][0].update(relation="EXACT"),
    lambda d: d["v2_to_spec"][1].update(spec_ids=[1]),                         # relation NONE with ids
    lambda d: d["v2_to_spec"][0].update(rationale=""),
    lambda d: d.update(uncovered_zero_tolerance_spec_ids=[]),                  # hiding the gap
    lambda d: d.update(uncovered_spec_ids=[]),
    lambda d: d.update(extra="x"),
])
def test_f3_proposal_validator_rejects_mutations(fn):
    assert _mut(fn)


def test_f3_proposal_is_not_wired_into_any_frozen_path():
    for rel in ("orca/evalinfra/schema.py", "orca/evalinfra/prereg_check.py", "orca/eval/genesis_v2/prereg.py", "orca/eval/genesis_v2/manifest.py"):
        assert "category_mapping_proposal" not in (ROOT / rel).read_text()


# ------------------------------------------------------------------------------------------------ F5
LLM_JUDGE_CATEGORIES = (2, 6, 8, 13)


def test_f5_gap_reproduced_genesis_suite_marks_2_6_8_13_llm_judge():
    from orca.eval.genesis_suite import all_tasks
    judged = {t.category for t in all_tasks() if t.scoring_type == "llm_judge"}
    assert judged == set(LLM_JUDGE_CATEGORIES)
    assert all(not t.deterministic for t in all_tasks() if t.scoring_type == "llm_judge")


def test_f5_gap_reproduced_evalinfra_refuses_llm_judge_scorers_and_offers_human_rubric():
    assert "llm_judge" in SC.FORBIDDEN_SCORER_TYPES and "human_rubric" in SC.SCORER_TYPES
    # manifest-level refusal itself is pinned in tests/test_evalinfra_schema.py::test_llm_judge_scorer_refused


def test_f5_no_zero_tolerance_category_is_llm_judged_today():
    # the inconsistency is real but does not currently touch the zero-tolerance gate: 10/14/15/17 are deterministic in genesis_suite
    from orca.eval.genesis_suite import all_tasks
    zt = {t.scoring_type for t in all_tasks() if t.category in REQUIRED_ZERO_TOLERANCE}
    assert "llm_judge" not in zt
