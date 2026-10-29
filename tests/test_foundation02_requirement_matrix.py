"""FOUNDATION-02 matrix integrity: 95 rows, zero formal acceptance, honest probes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orca.pretrain_foundation.probe_honesty import classify_probe, parse_pytest_summary

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
    assert matrix.get("training_authorization") == "NO-GO"


def test_acceptance_ledger_remains_empty():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert ledger == []


def test_verified_engineering_rows_have_honest_probe_evidence():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    probes_doc = json.loads(PROBES.read_text(encoding="utf-8"))
    probes = probes_doc["probes"]
    verified = [r for r in matrix["requirements"] if r["engineering_disposition"] == "VERIFIED_ENGINEERING"]
    assert matrix["verified_engineering_count"] == len(verified)
    for row in verified:
        assert row["executed_test_result"].startswith("PASS")
        assert row["historical_source_sha"]
        assert row["candidate_sha"] == matrix["candidate_sha"]
        assert row["requirement_id"] in probes
        probe = probes[row["requirement_id"]]
        assert probe["passed_probe"] is True
        assert probe["candidate_sha"] == matrix["candidate_sha"]
        assert row.get("evidence_paths")
        counts = probe.get("counts") or {}
        # Prefer structured counts; fall back to summary parse for transitional probes.
        if counts.get("passed") is None and probe.get("summary_line"):
            counts = parse_pytest_summary(probe["summary_line"]).to_dict()
        assert (counts.get("passed") or 0) >= 1
        # Portable command recording (no machine-specific argv).
        cmd = " ".join(probe.get("pytest_command") or [])
        assert "/home/ubuntu/" not in cmd
        assert "/Users/" not in cmd
        # Probe must survive honesty reclassification.
        verdict = classify_probe(
            exit_code=probe.get("exit_code", 1),
            stdout=probe.get("summary_line") or "",
            missing_implementation=probe.get("missing_implementation") or [],
            missing_tests=probe.get("missing_tests") or [],
            expected_candidate_sha=matrix["candidate_sha"],
            recorded_candidate_sha=probe.get("candidate_sha"),
        )
        assert verdict.passed_probe is True, verdict.reason


def test_probes_document_rejects_machine_specific_pythonpath():
    probes_doc = json.loads(PROBES.read_text(encoding="utf-8"))
    for probe in probes_doc.get("probes", {}).values():
        pp = probe.get("pythonpath") or ""
        assert "/home/ubuntu/" not in pp
        cmd = " ".join(probe.get("pytest_command") or [])
        assert "/home/ubuntu/" not in cmd
        assert "/workspace/.venv" not in cmd


def test_final1_is_not_verified_engineering_from_worksheet_alone():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    final1 = next(r for r in matrix["requirements"] if r["requirement_id"] == "FINAL-1")
    assert final1["engineering_disposition"] == "IMPLEMENTED_UNVERIFIED"


def test_matrix_schema_is_honesty_v3():
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert matrix["schema"] == "orneur-foundation-02-requirement-matrix/3"
    assert matrix.get("prior_qualified_code_sha") == "4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4"
