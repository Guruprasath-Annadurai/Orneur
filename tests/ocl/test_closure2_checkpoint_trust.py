"""
Phase 17 acceptance-boundary closure section 1: a checkpoint persists
COGNITIVE STATE, never compilation TRUST. Reproduced and confirmed real
against the unmodified prior code: `restore_checkpoint()` always compiled
with the hardcoded UNTRUSTED context, so a checkpoint created under a
legitimate TRUSTED_DETERMINISTIC_SYSTEM context containing a privileged
reference could never be restored at all -- not even by the same
independently-trusted system.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.checkpoint import create_checkpoint, restore_checkpoint
from orneur.intelligence.ocl.enums import AtomKind, EvidenceKind, ProducerKind, SourceClass
from orneur.intelligence.ocl.errors import EvidenceImpersonation
from orneur.intelligence.ocl.provenance import Provenance
from orneur.intelligence.ocl.trust import CompilationTrustContext
from tests.ocl.conftest import make_artifact, make_atom, make_evidence


def _trusted_draft():
    ev = make_evidence("e1")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE,
        evidence_refs=("e1",),
    )
    prov = Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="orca.mission.verification")
    return make_artifact(atoms=(atom,), evidence=(ev,), provenance=prov)


def test_trusted_create_and_same_trusted_restore_succeeds():
    checkpoint = create_checkpoint(_trusted_draft(), trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)
    restored = restore_checkpoint(checkpoint, trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)
    assert restored.atoms[0].source_class == SourceClass.MEASURED_EVIDENCE_REFERENCE


def test_trusted_create_default_untrusted_restore_fails_closed():
    """The exact reproduced gap: a checkpoint created under a legitimate
    trust context does NOT automatically restore with that trust -- the
    restoring runtime must re-establish it explicitly."""
    checkpoint = create_checkpoint(_trusted_draft(), trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)
    with pytest.raises(EvidenceImpersonation):
        restore_checkpoint(checkpoint)  # default trust_context=UNTRUSTED


def test_ordinary_untrusted_checkpoint_round_trips_normally():
    original = make_artifact(atoms=(make_atom("a1", content="ordinary content"),))
    checkpoint = create_checkpoint(original)
    restored = restore_checkpoint(checkpoint)
    assert restored.atoms[0].content == "ordinary content"


def test_self_declared_producer_kind_in_checkpoint_cannot_elevate_restore_trust():
    """Even if a checkpoint's own (now-untrusted-origin) JSON claims
    producer_kind=DETERMINISTIC_SYSTEM, restoring it with the default
    UNTRUSTED context must still fail -- the checkpoint content itself
    can never carry trust."""
    # Build a draft that self-declares DETERMINISTIC_SYSTEM but was never
    # actually compiled under a trusted context -- simulating an untrusted
    # checkpoint that merely claims trusted origin.
    checkpoint = create_checkpoint(make_artifact(
        atoms=(make_atom("a1", content="ordinary"),),
        provenance=Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="whoever"),
    ))
    restored = restore_checkpoint(checkpoint)  # fine, no privileged atom involved
    assert restored.provenance.producer_kind == ProducerKind.DETERMINISTIC_SYSTEM

    # Now the privileged case: even though the ARTIFACT claims a trusted
    # producer_kind, restoring with the default UNTRUSTED context must
    # still reject a privileged reference.
    checkpoint2 = create_checkpoint(_trusted_draft(), trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)
    with pytest.raises(EvidenceImpersonation):
        restore_checkpoint(checkpoint2)
