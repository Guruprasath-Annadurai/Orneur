"""FOUNDATION-02 matrix integrity: 95 rows, zero formal acceptance."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json"
LEDGER = ROOT / "docs/orneur/acceptance/acceptance_ledger.json"
GRAPH = ROOT / "docs/orneur/acceptance/register_graph.json"


def test_matrix_covers_exactly_the_95_pretraining_ids():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    ids = graph["denominator_pretraining_ids"]
    assert len(ids) == 95
    assert matrix["formal_accepted_count"] == 0
    assert matrix["formal_denominator"] == 95
    assert len(matrix["requirements"]) == 95
    assert [r["requirement_id"] for r in matrix["requirements"]] == ids
    assert all(r["formal_acceptance"] is False for r in matrix["requirements"])
    assert "FORMALLY_ACCEPTED" not in matrix["disposition_histogram"]


def test_acceptance_ledger_remains_empty():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert ledger == []
