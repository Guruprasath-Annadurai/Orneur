"""
Adapter boundary to the existing, Phase-16-frozen `orca/cognitive/
contracts.py` types (spec section 26). Phase 16 recommended a thin
`orneur.intelligence` adapter over legacy `orca.*` modules rather than a
destructive rewrite -- this module is the first real consumer of that
recommendation. It does NOT import `orca.mission` (see
tests/ocl/test_ocl_adapter.py's own INV-NATIVE-001-style regression
check) and does not replace `orca/cognitive/contracts.py`; both remain
valid, and this module only translates between them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from orca.cognitive.contracts import CognitiveResult, CognitiveState
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, SourceClass
from orneur.intelligence.ocl.graph import CognitiveAtom
from orneur.intelligence.ocl.provenance import Provenance
from orneur.intelligence.ocl.version import CURRENT_SCHEMA_VERSION


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def cognitive_result_to_ocl_draft(result: CognitiveResult, *, producer_id: str = "orca.cognitive.kernel") -> CognitiveArtifact:
    """Wraps a legacy `CognitiveResult`'s SAFE fields into a minimal draft
    OCL artifact -- `result.output` becomes a single MODEL_ASSERTION atom
    (it is model-produced text, never upgraded to measured evidence by
    this adapter), and `abstention_reason`/`status` become metadata. This
    is a one-way, read-only translation for observability/interop; it does
    not attempt to reconstruct the kernel's internal reasoning graph."""
    atoms: tuple[CognitiveAtom, ...] = ()
    if result.output:
        atoms = (
            CognitiveAtom(
                atom_id=_new_id("atom"),
                kind=AtomKind.ASSERTION,
                source_class=SourceClass.MODEL_ASSERTION,
                content=result.output,
            ),
        )

    return CognitiveArtifact(
        artifact_id=_new_id("artifact"),
        schema_version=CURRENT_SCHEMA_VERSION,
        request_id=result.request_id,
        provenance=Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id=producer_id),
        created_at=datetime.now(timezone.utc).isoformat(),
        atoms=atoms,
        metadata={
            "legacy_status": result.status.value,
            "legacy_abstention_reason": result.abstention_reason.value if result.abstention_reason else None,
            "legacy_trace_id": result.trace_id,
        },
    )
