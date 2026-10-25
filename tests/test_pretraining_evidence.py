"""Read-only pretraining measurements. The ledger is not a write target."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orca.train.pretraining_evidence import (
    egress_decision,
    infrastructure_record,
    lock_probe,
    spend_decision,
    training_identity_holdout,
    worksheet,
    workstation_probe,
)

_ROOT = Path(__file__).resolve().parents[1]
_LEDGER = _ROOT / "docs" / "orneur" / "acceptance" / "acceptance_ledger.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_worksheet_counts_95_and_does_not_touch_the_ledger():
    before = _sha(_LEDGER)
    report = worksheet()
    assert report["counted"] == 95
    assert report["ledger_raw_entry_count"] == 0
    assert report["ledger_accepted_count"] == 0
    assert report["ledger_engine_result"] == "empty"
    assert report["accepted_by_this_module"] is False
    assert report["engineering_evidence_is_acceptance"] is False
    assert report["founder_authorized"] is False
    assert report["training_start_permitted"] is False
    assert _sha(_LEDGER) == before
    by_id = {row["id"]: row["status"] for row in report["rows"]}
    assert by_id["R65"] == "NOT_VERIFIABLE"
    assert by_id["C27"] == "NOT_STARTED"
    assert by_id["DEC-K"] == "NOT_AUTHORIZED"
    assert by_id["G1"] == "NOT_VERIFIABLE"
    assert len(by_id) == 95


def test_list_ledger_counts_raw_rows_and_accepts_none(tmp_path: Path):
    base = tmp_path / "docs" / "orneur" / "acceptance"
    base.mkdir(parents=True)
    graph = {
        "nodes": [
            {
                "id": "X1",
                "denominator": "PRE_TRAINING",
                "counts": True,
                "status": "NOT_STARTED",
                "implementation_owner": "CURSOR",
            }
        ]
    }
    ledger = [
        {"requirement_id": "X1", "forged": True},
        {"requirement_id": "Y1", "forged": True},
    ]
    graph_path = base / "register_graph.json"
    ledger_path = base / "acceptance_ledger.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    before = _sha(ledger_path)
    graph_before = _sha(graph_path)
    report = worksheet(tmp_path)
    assert report["ledger_raw_entry_count"] == 2
    assert report["ledger_accepted_count"] == 0
    assert report["ledger_accepted_ids"] == []
    assert report["ledger_engine_result"] == "rejected"
    assert report["founder_authorized"] is False
    assert report["training_start_permitted"] is False
    assert report["engineering_evidence_is_acceptance"] is False
    assert report["counted"] == 1
    assert _sha(ledger_path) == before
    assert _sha(graph_path) == graph_before

    ledger_path.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")
    shaped = worksheet(tmp_path)
    assert shaped["ledger_raw_entry_count"] == 0
    assert shaped["ledger_accepted_count"] == 0
    assert shaped["ledger_engine_result"] == "not_a_list"


def test_spend_above_zero_is_refused_and_locks_stay_false():
    refused = spend_decision(1)
    assert refused["above_cap_refused"] is True
    assert refused["training_authorized"] is False
    held = spend_decision(0)
    assert held["within_cap"] is True
    assert held["training_authorized"] is False
    probe = lock_probe()
    assert probe["proof_ok"] is True
    assert probe["executable"] is False
    assert probe["locks_flipped"] is False
    assert probe["after"]["training"] is False
    assert probe["after"]["gpu"] is False


def test_training_identity_cannot_open_the_holdout_or_escape_the_root(tmp_path: Path):
    holdout = training_identity_holdout(_ROOT)
    assert holdout["opened"] is False
    assert holdout["code"] == "holdout_refused"
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    link = tmp_path / "root" / "escape"
    link.parent.mkdir()
    link.symlink_to(outside)
    assert egress_decision(link.parent, link)["code"] == "symlink_refused"
    assert egress_decision(link.parent, outside)["code"] == "outside_root"
    inside = link.parent / "notes.txt"
    inside.write_text("ok", encoding="utf-8")
    assert egress_decision(link.parent, inside)["code"] == "inside_root"
    hold = link.parent / "holdout.jsonl"
    hold.write_text("{}\n", encoding="utf-8")
    assert egress_decision(link.parent, hold)["code"] == "holdout_path_refused"


def test_infrastructure_record_and_workstation_are_not_authorization():
    record = infrastructure_record("f3d2509770226f7dd2ee1848737aa578afa5775a")
    assert record["training_authorized"] is False
    assert record["gpu_permission"] == "DENIED"
    assert record["p2_environment_id"] is None
    assert record["complete"] is False
    assert record["dry_run_launches_training"] is False
    probe = workstation_probe()
    assert probe["validated"] is False
