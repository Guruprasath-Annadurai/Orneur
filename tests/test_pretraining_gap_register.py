"""The gap register covers the counted rows and accepts none of them."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _register():
    path = ROOT / "scripts" / "cursor" / "pretraining_gap_register.py"
    spec = importlib.util.spec_from_file_location("pretraining_gap_register", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gap_register_matches_the_graph_and_leaves_the_ledger_empty():
    module = _register()
    before = {
        path: path.read_bytes()
        for path in (
            module.LEDGER_PATH,
            module.GRAPH_PATH,
            module.POLICY_PATH,
            module.TRUST_PATH,
            module.ROOT_PATH,
            module.BOOTSTRAP_PATH,
            module.CHECKPOINT_PATH,
            module.PIN_PATH,
        )
    }
    text = module.build_markdown()
    assert module.OUT_PATH.read_text(encoding="utf-8") == text
    after = {path: path.read_bytes() for path in before}
    assert after == before
    ledger = json.loads(module.LEDGER_PATH.read_text(encoding="utf-8"))
    graph = json.loads(module.GRAPH_PATH.read_text(encoding="utf-8"))
    assert ledger == []
    assert graph["numerator_pretraining"] == 0
    assert len(graph["denominator_pretraining_ids"]) == 95
    assert text.count("### ") == 95
    assert "acceptance_eligibility | NOT_ELIGIBLE" in text
    assert "returned `0` accepted ids" in text
    assert "does not assert that any of them occurred" in text
    assert "This pass did not find a founder-approved source file and did not construct an expansion proposal." in text
    assert module.INSPECTED_PR99_HEAD in text
    for node_id in graph["denominator_pretraining_ids"]:
        assert f"### {node_id}\n" in text
    assert not any(str(node["id"]).startswith("R65-") for node in graph["nodes"])


def test_class_k_stays_outside_the_semantic_classes():
    from orca.rse.imp1.profiles import DEFERRED_CLASSES, SEMANTIC_CLASSES

    assert ord("K") in DEFERRED_CLASSES
    assert ord("K") not in SEMANTIC_CLASSES
