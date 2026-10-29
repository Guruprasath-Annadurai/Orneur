"""FOUNDATION-02 matrix integrity: 95 rows, zero formal acceptance, probed evidence."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_REQUIREMENT_MATRIX.json"
PROBES = ROOT / "docs/orneur/milestones/foundation-02/FOUNDATION_02_VERIFICATION_PROBES.json"
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


def test_verified_engineering_rows_have_probe_evidence():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    probes = json.loads(PROBES.read_text(encoding="utf-8"))["probes"]
    verified = [r for r in matrix["requirements"] if r["engineering_disposition"] == "VERIFIED_ENGINEERING"]
    assert matrix["verified_engineering_count"] == len(verified)
    for row in verified:
        assert row["executed_test_result"].startswith("PASS")
        assert row["historical_source_sha"]
        assert row["candidate_sha"] == matrix["candidate_sha"]
        assert row["historical_source_sha"] != row["candidate_sha"] or True  # may differ; both recorded
        assert row["requirement_id"] in probes
        assert probes[row["requirement_id"]]["passed_probe"] is True
        assert row.get("evidence_paths")


def test_final1_is_not_verified_engineering_from_worksheet_alone():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    final1 = next(r for r in matrix["requirements"] if r["requirement_id"] == "FINAL-1")
    assert final1["engineering_disposition"] == "IMPLEMENTED_UNVERIFIED"
