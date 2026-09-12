from __future__ import annotations

import ast
from pathlib import Path

from orca.cognitive.contracts import CognitiveResult, CognitiveState, AbstentionReason
from orneur.intelligence.ocl.adapters import cognitive_result_to_ocl_draft
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import SourceClass


def test_legacy_cognitive_result_adapts_to_a_compilable_draft():
    result = CognitiveResult(request_id="req-1", trace_id="trace-1", status=CognitiveState.COMPLETED, output="the answer is 42")
    draft = cognitive_result_to_ocl_draft(result)
    compiled = compile_artifact(draft)
    assert compiled.request_id == "req-1"
    assert compiled.atoms[0].content == "the answer is 42"
    assert compiled.atoms[0].source_class == SourceClass.MODEL_ASSERTION


def test_abstained_result_carries_no_atom_but_still_compiles():
    result = CognitiveResult(
        request_id="req-2", trace_id="trace-2", status=CognitiveState.ABSTAINED,
        abstention_reason=AbstentionReason.INSUFFICIENT_EVIDENCE,
    )
    draft = cognitive_result_to_ocl_draft(result)
    compiled = compile_artifact(draft)
    assert compiled.atoms == ()
    assert compiled.metadata["legacy_abstention_reason"] == "INSUFFICIENT_EVIDENCE"


def test_adapter_module_does_not_import_orca_mission():
    """Mirrors tests/test_phase16_architecture_invariants.py's dependency-
    boundary discipline, extended to the new orneur.intelligence.ocl
    package: OCL's adapter to legacy contracts must never gain a path into
    Mission authority state."""
    import orneur.intelligence.ocl.adapters as adapters_mod

    tree = ast.parse(Path(adapters_mod.__file__).read_text())
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any(m == "orca.mission" or (m and m.startswith("orca.mission.")) for m in imported_modules)
