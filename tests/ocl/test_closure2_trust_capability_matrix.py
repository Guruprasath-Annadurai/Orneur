"""
Phase 17 acceptance-boundary closure sections 5-7: trust_context must be
runtime-typed (not accept a plain string that matches an enum value), and
not every trusted caller is equally capable -- a per-SourceClass and
per-EvidenceKind capability matrix replaces the old flat "trusted or not"
gate. EXTERNAL_EVIDENCE_REFERENCE is reclassified as an unverified
reference expressible even by untrusted/model cognition.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, EvidenceKind, PRIVILEGED_REFERENCE_SOURCE_CLASSES, SourceClass
from orneur.intelligence.ocl.errors import EvidenceImpersonation, InvalidTrustContext
from orneur.intelligence.ocl.trust import CompilationTrustContext
from tests.ocl.conftest import make_artifact, make_atom, make_evidence


# ── Runtime-typed trust context (section 5) ──────────────────────────────

def test_raw_string_trust_context_is_rejected():
    draft = make_artifact(atoms=(make_atom("a1"),))
    with pytest.raises(InvalidTrustContext):
        compile_artifact(draft, trust_context="TRUSTED_DETERMINISTIC_SYSTEM")


def test_raw_string_matching_untrusted_value_is_also_rejected():
    """Even the "safe-looking" string must be rejected -- only the actual
    enum member is ever valid, no exceptions."""
    draft = make_artifact(atoms=(make_atom("a1"),))
    with pytest.raises(InvalidTrustContext):
        compile_artifact(draft, trust_context="UNTRUSTED_MODEL_OR_WIRE")


def test_actual_enum_member_is_accepted():
    draft = make_artifact(atoms=(make_atom("a1"),))
    compile_artifact(draft, trust_context=CompilationTrustContext.UNTRUSTED_MODEL_OR_WIRE)


# ── Capability matrix (sections 6-7) ──────────────────────────────────────

def _privileged_atom_and_evidence(source_class, evidence_kind):
    ev = make_evidence("e1", kind=evidence_kind)
    atom = make_atom("a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=source_class, evidence_refs=("e1",))
    return atom, ev


def test_untrusted_context_cannot_unlock_any_privileged_source_class():
    atom, ev = _privileged_atom_and_evidence(SourceClass.MEASURED_EVIDENCE_REFERENCE, EvidenceKind.MEASURED_SYSTEM_DATA)
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)))


def test_trusted_tool_adapter_can_unlock_measured_evidence_reference():
    atom, ev = _privileged_atom_and_evidence(SourceClass.MEASURED_EVIDENCE_REFERENCE, EvidenceKind.MEASURED_SYSTEM_DATA)
    compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)), trust_context=CompilationTrustContext.TRUSTED_TOOL_ADAPTER)


def test_trusted_tool_adapter_cannot_unlock_deterministic_policy_reference():
    """A tool adapter is not equivalent to a Court/Policy system."""
    atom, ev = _privileged_atom_and_evidence(SourceClass.DETERMINISTIC_POLICY_REFERENCE, EvidenceKind.DETERMINISTIC_POLICY_FACT)
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)), trust_context=CompilationTrustContext.TRUSTED_TOOL_ADAPTER)


def test_trusted_deterministic_system_can_unlock_deterministic_policy_reference():
    atom, ev = _privileged_atom_and_evidence(SourceClass.DETERMINISTIC_POLICY_REFERENCE, EvidenceKind.DETERMINISTIC_POLICY_FACT)
    compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)), trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)


def test_trusted_human_input_cannot_unlock_any_privileged_source_class():
    """TRUSTED_HUMAN_INPUT proves only that the runtime authenticated a
    human source -- it must not itself unlock deterministic-policy/Court/
    Production-Proof semantics (human identity != sovereign approval)."""
    atom, ev = _privileged_atom_and_evidence(SourceClass.MEASURED_EVIDENCE_REFERENCE, EvidenceKind.MEASURED_SYSTEM_DATA)
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)), trust_context=CompilationTrustContext.TRUSTED_HUMAN_INPUT)


def test_trusted_tool_adapter_cannot_certify_court_decision_evidence_kind():
    """Even for a SourceClass the tool adapter CAN unlock, it must not be
    able to certify a COURT_DECISION-kind evidence anchor -- the
    EvidenceKind capability gate is independent of the SourceClass one."""
    atom, ev = _privileged_atom_and_evidence(SourceClass.MEASURED_EVIDENCE_REFERENCE, EvidenceKind.COURT_DECISION)
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)), trust_context=CompilationTrustContext.TRUSTED_TOOL_ADAPTER)


def test_trusted_deterministic_system_can_certify_court_decision_and_production_proof():
    for kind in (EvidenceKind.COURT_DECISION, EvidenceKind.PRODUCTION_PROOF, EvidenceKind.VERIFICATION_RECORD):
        atom, ev = _privileged_atom_and_evidence(SourceClass.MEASURED_EVIDENCE_REFERENCE, kind)
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)), trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)


# ── EXTERNAL_EVIDENCE_REFERENCE reclassification ─────────────────────────

def test_external_evidence_reference_not_in_privileged_set():
    assert SourceClass.EXTERNAL_EVIDENCE_REFERENCE not in PRIVILEGED_REFERENCE_SOURCE_CLASSES


def test_untrusted_model_can_cite_external_evidence_reference_as_unverified():
    """The core Phase 17 doctrine this closure restores: a model MUST be
    able to cite external evidence without self-authenticating it -- an
    EXTERNAL_EVIDENCE_REFERENCE atom compiles even under the default
    UNTRUSTED context, on ANY atom kind, with no evidence_refs required."""
    atom = make_atom("a1", kind=AtomKind.ASSERTION, source_class=SourceClass.EXTERNAL_EVIDENCE_REFERENCE, content="according to source X, ...")
    compile_artifact(make_artifact(atoms=(atom,)))  # default UNTRUSTED context, still compiles


def test_external_evidence_reference_does_not_require_observation_reference_kind():
    atom = make_atom("a1", kind=AtomKind.HYPOTHESIS, source_class=SourceClass.EXTERNAL_EVIDENCE_REFERENCE)
    compile_artifact(make_artifact(atoms=(atom,)))
