"""
Phase 17 final closure: trust MUST come from the invocation/runtime
boundary outside the artifact, never be derived from data inside it.
Reproduces the exact bypass an independent owner audit found against
commit feed714 -- confirmed real before this closure's fix (see
PHASE17_EVIDENCE.md's final closure section for the exact pre-fix
reproduction transcript).
"""
from __future__ import annotations

import json

import pytest

from orneur.intelligence.ocl.canonical import compile_ocl_json
from orneur.intelligence.ocl.errors import EvidenceImpersonation
from orneur.intelligence.ocl.trust import UNTRUSTED, CompilationTrustContext


def _attack_payload(evidence_kind: str, source_class: str = "MEASURED_EVIDENCE_REFERENCE") -> str:
    return json.dumps({
        "artifact_id": "art-attack",
        "schema_version": "1.0.0",
        "request_id": "req-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "provenance": {"producer_kind": "DETERMINISTIC_SYSTEM", "producer_id": "attacker-controlled"},
        "atoms": [
            {"atom_id": "a1", "kind": "OBSERVATION_REFERENCE", "source_class": source_class,
             "content": "production is healthy", "evidence_refs": ["e1"]},
        ],
        "evidence": [
            {"evidence_id": "e1", "evidence_kind": evidence_kind, "issuer": "fake-system", "reference": "fake-id-123"},
        ],
    })


@pytest.mark.parametrize("evidence_kind", [
    "VERIFICATION_RECORD", "PRODUCTION_PROOF", "COURT_DECISION", "DETERMINISTIC_POLICY_FACT",
])
def test_self_declared_producer_kind_cannot_unlock_privileged_evidence_via_safe_public_entry_point(evidence_kind):
    """The exact bypass: compile_ocl_json (the SAFE public untrusted-wire
    entry point) must reject a payload that self-labels its own
    producer_kind as DETERMINISTIC_SYSTEM and then cites a fabricated
    privileged EvidenceAnchor -- regardless of what the payload claims
    about itself."""
    with pytest.raises(EvidenceImpersonation):
        compile_ocl_json(_attack_payload(evidence_kind))


def test_self_declared_deterministic_policy_reference_also_rejected():
    with pytest.raises(EvidenceImpersonation):
        compile_ocl_json(_attack_payload("DETERMINISTIC_POLICY_FACT", source_class="DETERMINISTIC_POLICY_REFERENCE"))


def test_compile_ocl_json_always_uses_untrusted_context_no_matter_the_payload():
    """There is no field anywhere in the wire payload that can elevate
    trust -- compile_ocl_json hardcodes UNTRUSTED_MODEL_OR_WIRE."""
    import inspect

    from orneur.intelligence.ocl import canonical as canonical_mod

    src = inspect.getsource(canonical_mod.compile_ocl_json)
    assert "UNTRUSTED" in src
    assert "trust_context" in src


def test_trusted_context_from_a_genuinely_trusted_caller_is_still_honored():
    """Non-regression: this closure does not remove the ability for a
    genuinely trusted internal caller to compile privileged evidence --
    only removes the ability for an untrusted wire payload to grant
    itself that trust."""
    from orneur.intelligence.ocl.artifact import CognitiveArtifact
    from orneur.intelligence.ocl.compiler import compile_artifact
    from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, SourceClass
    from orneur.intelligence.ocl.provenance import Provenance
    from orneur.intelligence.ocl.version import CURRENT_SCHEMA_VERSION
    from tests.ocl.conftest import FIXED_TIME, make_atom, make_evidence

    draft = CognitiveArtifact(
        artifact_id="art-trusted", schema_version=CURRENT_SCHEMA_VERSION, request_id="req-1",
        provenance=Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="orca.mission.verification"),
        created_at=FIXED_TIME,
        atoms=(make_atom("a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE, evidence_refs=("e1",)),),
        evidence=(make_evidence("e1"),),
    )
    compile_artifact(draft, trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)
