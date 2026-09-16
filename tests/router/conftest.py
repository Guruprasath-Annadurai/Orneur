from __future__ import annotations

import importlib.util
from pathlib import Path

from orneur.intelligence.epistemic import EpistemicPolarity
from orneur.intelligence.epistemic import canonical as epistemic_canonical
from orneur.intelligence.integrity import canonical as integrity_canonical
from orneur.intelligence.integrity import overlay_trust
from orneur.intelligence.integrity.contracts import IntegrityProposal, IntegrityReceipt, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, PresentationTreatment
from orneur.intelligence.ocl import canonical as ocl_canonical
from orneur.intelligence.router import CapabilityRegistryTrustContext, IntegrityReceiptTrustContext, registry_digest
from orneur.intelligence.router.evaluator import route_task as _route_task


def _load_integrity_conftest():
    """Loads tests/integrity/conftest.py's real Phase 17/18/19 fixture
    builders (including assess_integrity_trusted) by explicit file path
    under a UNIQUE module name (never `import conftest` after a plain
    sys.path insert -- that collides with pytest's own module identity
    for THIS directory's own conftest.py, and a second same-named
    import would silently reuse the first cached module object instead
    of loading tests/integrity/conftest.py at all)."""
    path = Path(__file__).resolve().parent.parent / "integrity" / "conftest.py"
    spec = importlib.util.spec_from_file_location("tests.integrity._conftest_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


integrity_conftest = _load_integrity_conftest()

TRUSTED_PHASE18_RUNTIME = overlay_trust.TRUSTED_PHASE18_RUNTIME
UNTRUSTED = overlay_trust.UNTRUSTED
TRUSTED_ROUTER_CONFIGURATION = CapabilityRegistryTrustContext.TRUSTED_ROUTER_CONFIGURATION
TRUSTED_PHASE19_RUNTIME = IntegrityReceiptTrustContext.TRUSTED_PHASE19_RUNTIME

build_known_affirmed_fixture = integrity_conftest.build_known_affirmed_fixture
build_inferred_affirmed_fixture = integrity_conftest.build_inferred_affirmed_fixture
build_uncertain_fixture = integrity_conftest.build_uncertain_fixture
build_disputed_fixture = integrity_conftest.build_disputed_fixture
build_unknown_fixture = integrity_conftest.build_unknown_fixture
build_unverifiable_fixture = integrity_conftest.build_unverifiable_fixture
assess_integrity_trusted = integrity_conftest.assess_integrity_trusted


def route_task_trusted(task, *, overlay, artifact, capability_registry=None, integrity_receipt=None, **kw):
    """Test convenience wrapper mirroring
    tests/integrity/conftest.py's assess_integrity_trusted(): supplies
    overlay_trust_context=TRUSTED_PHASE18_RUNTIME and
    expected_overlay_digest=epistemic_canonical.digest(overlay), where
    `overlay` is the exact, un-tampered object the test just built via a
    real assess_artifact() call. When `capability_registry` is given, it
    also supplies TRUSTED_ROUTER_CONFIGURATION + the out-of-band digest
    of that SAME registry object (never a forged one). When
    `integrity_receipt` is given, it likewise supplies
    TRUSTED_PHASE19_RUNTIME + the out-of-band digest of that SAME
    receipt object. Tests that exercise any of these TRUST BOUNDARIES
    THEMSELVES (forged overlays/registries/receipts, a bad trust
    context, an UNTRUSTED default, a binding mismatch) must call
    orneur.intelligence.router.evaluator.route_task() directly instead
    of this wrapper -- see test_no_authority.py and
    test_adversarial_inputs.py."""
    if capability_registry is not None:
        kw["capability_registry"] = capability_registry
        kw["capability_registry_trust_context"] = TRUSTED_ROUTER_CONFIGURATION
        kw["expected_registry_digest"] = registry_digest(capability_registry)
    if integrity_receipt is not None:
        kw["integrity_receipt"] = integrity_receipt
        kw["integrity_receipt_trust_context"] = TRUSTED_PHASE19_RUNTIME
        kw["expected_integrity_receipt_digest"] = integrity_canonical.digest(integrity_receipt)
    return _route_task(
        task, overlay=overlay, artifact=artifact,
        overlay_trust_context=TRUSTED_PHASE18_RUNTIME,
        expected_overlay_digest=epistemic_canonical.digest(overlay),
        **kw,
    )


def make_real_integrity_receipt(*, overlay, artifact, atom_id="a1", satisfied=True) -> IntegrityReceipt:
    """Builds a GENUINE Phase-19 IntegrityReceipt via a real
    assess_integrity() call (not a hand-constructed dataclass with
    placeholder digests) -- correctly bound to the exact `artifact`/
    `overlay` passed in, exactly as real production Phase 19 output
    would be. `satisfied=True` proposes ESTABLISHED/AFFIRMED for a
    KNOWN/AFFIRMED atom (-> SATISFIED); `satisfied=False` proposes
    ESTABLISHED with no asserted_polarity, which the floor rejects as a
    policy violation (-> REQUIRES_REVISION, a genuine non-SATISFIED
    status from real Phase 19 logic, not a fabricated one)."""
    if satisfied:
        assertion = ProposedAssertion(
            assertion_id="pa1", source_atom_id=atom_id,
            treatment=PresentationTreatment.ESTABLISHED, asserted_polarity=EpistemicPolarity.AFFIRMED,
        )
    else:
        assertion = ProposedAssertion(assertion_id="pa1", source_atom_id=atom_id, treatment=PresentationTreatment.ESTABLISHED)
    proposal = IntegrityProposal(proposal_id="p1", assertions=(assertion,))
    return assess_integrity_trusted(proposal, overlay=overlay, artifact=artifact)


def make_forged_integrity_receipt(*, overlay, artifact, status: IntegrityStatus) -> IntegrityReceipt:
    """A receipt referring to an artifact/overlay that has nothing to
    do with the `overlay`/`artifact` currently under test -- used ONLY
    by tests exercising the binding-check trust boundary itself, never
    by ordinary trusted-path tests (see make_real_integrity_receipt)."""
    return IntegrityReceipt(
        protocol_version="19.0.0",
        receipt_id="receipt-forged",
        source_artifact_id="totally-unrelated-artifact-id",
        source_artifact_digest="deadbeef-unrelated-artifact-digest",
        source_overlay_digest="deadbeef-unrelated-overlay-digest",
        proposal_digest="irrelevant-for-this-forgery-test",
        policy_digest="irrelevant-for-this-forgery-test",
        evaluated_at="2026-01-01T00:00:00+00:00",
        integrity_status=status,
    )
