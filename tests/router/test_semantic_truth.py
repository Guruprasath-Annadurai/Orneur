"""
Phase 20 semantic-truth micro-closure: narrow regression guards against
specific documentation/source-comment drift already found and fixed
once (a stale canonical-spec path, and a stale claim about receipt
structural-validation ordering). Deliberately narrow -- this is not a
general documentation linter.
"""
from __future__ import annotations

from pathlib import Path

ROUTER_SRC = Path(__file__).resolve().parent.parent.parent / "orneur" / "intelligence" / "router"
SPEC_DOC = Path(__file__).resolve().parent.parent.parent / "docs" / "orneur" / "phase-20" / "PHASE20_INTELLIGENCE_ROUTER_SPEC.md"

STALE_SPEC_PATH = "docs/PHASE20_INTELLIGENCE_ROUTER.md"
CANONICAL_SPEC_PATH = "docs/orneur/phase-20/PHASE20_INTELLIGENCE_ROUTER_SPEC.md"
STALE_RECEIPT_ORDER_SENTENCE = "Provenance-verified receipts are then structurally validated"


def test_evaluator_does_not_reference_the_stale_spec_path():
    text = (ROUTER_SRC / "evaluator.py").read_text(encoding="utf-8")
    assert STALE_SPEC_PATH not in text


def test_evaluator_references_the_canonical_spec_path():
    text = (ROUTER_SRC / "evaluator.py").read_text(encoding="utf-8")
    assert CANONICAL_SPEC_PATH in text


def test_no_router_source_file_references_the_stale_spec_path():
    for py_file in sorted(ROUTER_SRC.glob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        assert STALE_SPEC_PATH not in text, f"{py_file.name} still references the stale spec path"


def test_active_spec_does_not_contain_the_obsolete_receipt_order_sentence():
    text = SPEC_DOC.read_text(encoding="utf-8")
    assert STALE_RECEIPT_ORDER_SENTENCE not in text
