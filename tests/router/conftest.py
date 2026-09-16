from __future__ import annotations

import importlib.util
from pathlib import Path

from orneur.intelligence.epistemic import canonical as epistemic_canonical
from orneur.intelligence.integrity import overlay_trust
from orneur.intelligence.integrity.contracts import IntegrityReceipt
from orneur.intelligence.integrity.enums import IntegrityStatus
from orneur.intelligence.router.evaluator import route_task as _route_task


def _load_integrity_conftest():
    """Loads tests/integrity/conftest.py's real Phase 17/18 fixture
    builders by explicit file path (never via sys.path + `import
    conftest`, which would collide with pytest's own module identity
    for this directory's own conftest.py)."""
    path = Path(__file__).resolve().parent.parent / "integrity" / "conftest.py"
    spec = importlib.util.spec_from_file_location("tests.integrity._conftest_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


integrity_conftest = _load_integrity_conftest()

TRUSTED_PHASE18_RUNTIME = overlay_trust.TRUSTED_PHASE18_RUNTIME
UNTRUSTED = overlay_trust.UNTRUSTED

build_known_affirmed_fixture = integrity_conftest.build_known_affirmed_fixture
build_inferred_affirmed_fixture = integrity_conftest.build_inferred_affirmed_fixture
build_uncertain_fixture = integrity_conftest.build_uncertain_fixture
build_disputed_fixture = integrity_conftest.build_disputed_fixture
build_unknown_fixture = integrity_conftest.build_unknown_fixture
build_unverifiable_fixture = integrity_conftest.build_unverifiable_fixture


def route_task_trusted(task, *, overlay, artifact, **kw):
    """Test convenience wrapper mirroring
    tests/integrity/conftest.py's assess_integrity_trusted(): supplies
    overlay_trust_context=TRUSTED_PHASE18_RUNTIME and
    expected_overlay_digest=epistemic_canonical.digest(overlay), where
    `overlay` is the exact, un-tampered object the test just built via a
    real assess_artifact() call. Tests that exercise the overlay TRUST
    BOUNDARY ITSELF (forged overlays, a bad trust context, the
    UNTRUSTED default) must call
    orneur.intelligence.router.evaluator.route_task() directly instead
    of this wrapper -- see test_overlay_trust_reuse.py."""
    return _route_task(
        task, overlay=overlay, artifact=artifact,
        overlay_trust_context=TRUSTED_PHASE18_RUNTIME,
        expected_overlay_digest=epistemic_canonical.digest(overlay),
        **kw,
    )


def make_blocked_integrity_receipt(*, overlay, artifact, status=IntegrityStatus.BLOCKED) -> IntegrityReceipt:
    return IntegrityReceipt(
        protocol_version="19.0.0",
        receipt_id="receipt-blocked",
        source_artifact_id=artifact.artifact_id,
        source_artifact_digest="irrelevant-for-router-tests",
        source_overlay_digest=epistemic_canonical.digest(overlay),
        proposal_digest="irrelevant-for-router-tests",
        policy_digest="irrelevant-for-router-tests",
        evaluated_at="2026-01-01T00:00:00+00:00",
        integrity_status=status,
    )


def make_satisfied_integrity_receipt(*, overlay, artifact) -> IntegrityReceipt:
    return make_blocked_integrity_receipt(overlay=overlay, artifact=artifact, status=IntegrityStatus.SATISFIED)
