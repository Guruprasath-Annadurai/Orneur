"""Workstream I: scorecard must never fabricate acceptance or a single number."""
import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gen_scorecard", ROOT / "scripts/scorecard/generate_scorecard.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


def test_empty_ledger_accepts_nothing_and_no_percentage():
    card = sc.build()
    assert sc.validate(card) == []
    assert card["acceptance"]["pretraining_accepted"] == 0
    assert card["acceptance"]["pretraining_denominator"] == 95
    assert card["single_readiness_percentage"] is None
    assert card["training_status"] == "NOT_AUTHORIZED"
    assert all(r["class"] != "VERIFIED_ACCEPTED" for r in card["requirements"])


def test_status_mapping_never_yields_accepted():
    for status in sc._STATUS_CLASS.values():
        assert status != "VERIFIED_ACCEPTED"
    assert sc.classify({"status": "SOMETHING_NEW"}) == "MISSING"


def test_validator_rejects_tampering():
    card = sc.build()
    bad = copy.deepcopy(card)
    bad["single_readiness_percentage"] = 80
    assert sc.validate(bad)
    bad = copy.deepcopy(card)
    bad["training_status"] = "AUTHORIZED"
    assert sc.validate(bad)
    bad = copy.deepcopy(card)
    bad["dimensions"][8]["state"] = "AUTHORIZED"
    assert sc.validate(bad)
    bad = copy.deepcopy(card)
    bad["dimensions"] = bad["dimensions"][:-1]
    assert sc.validate(bad)


def test_committed_scorecard_matches_generator():
    import json
    out = ROOT / "docs/orneur/status/SCORECARD.json"
    assert out.exists()
    assert json.loads(out.read_text()) == sc.build()
