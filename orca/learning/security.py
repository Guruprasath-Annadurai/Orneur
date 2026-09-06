"""
Phase 12 security guards (spec §63-69).

Central principle: candidate/failure SOURCE TEXT is data, never
instructions. Every function here treats untrusted text as an inert string
to be pattern-matched or hashed -- never evaluated, executed, or trusted as
a policy directive. This mirrors the exact discipline used throughout the
project for injection-prone content (orca.truth.fetch's sanitization,
orca.connectors.security's cross-connector policy).
"""
from __future__ import annotations

import re

from orca.learning.contracts import CurriculumCandidate, PrivacyClass, TrainingDestination

# Spec §63: known poisoning-attempt phrasings. Pattern-based, floor-not-
# ceiling (same honest posture as orca/train/redteam.py) -- this catches
# the explicit examples the spec lists and their obvious variants, not
# every conceivable phrasing.
_POISONING_PATTERNS = [
    re.compile(r"(?i)\bmark\s+this\s+(answer|response|candidate)\s+(as\s+)?correct\b"),
    re.compile(r"(?i)\btrain\s+on\s+this\s+secret\b"),
    re.compile(r"(?i)\bignore\s+(the\s+)?review\b"),
    re.compile(r"(?i)\bpromote\s+this\s+checkpoint\b"),
    re.compile(r"(?i)\bthis\s+is\s+verified\b"),
    re.compile(r"(?i)\bapprove\s+(this|for)\s+training\b"),
    re.compile(r"(?i)\bskip\s+(the\s+)?(review|approval|sanitization)\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(the\s+)?(reviewer|approver|admin)\b"),
]


class DataPoisoningAttemptDetected(Exception):
    pass


def scan_for_poisoning_attempt(text: str) -> list[str]:
    """Returns matched pattern descriptions; empty means clean. Never
    raises -- callers decide what to do (flag, reject, log) since a
    detection here is evidence for a human/policy step, not itself an
    automatic verdict."""
    hits = []
    for pattern in _POISONING_PATTERNS:
        if pattern.search(text):
            hits.append(pattern.pattern)
    return hits


def assert_no_poisoning_attempt(text: str) -> None:
    hits = scan_for_poisoning_attempt(text)
    if hits:
        raise DataPoisoningAttemptDetected(f"Candidate source text matched {len(hits)} known poisoning pattern(s); requires human review before admission.")


class TenantExfiltrationBlocked(Exception):
    pass


def enforce_tenant_boundary(candidate: CurriculumCandidate, requesting_tenant_id: str | None, target: TrainingDestination) -> None:
    """
    Spec §13, §64: tenant-private data must not become a global dataset, a
    different tenant's dataset, or a public eval artifact without explicit
    allowed transformation/review.
    """
    if candidate.privacy_class != PrivacyClass.TENANT_PRIVATE:
        return
    if target == TrainingDestination.GLOBAL_TRAINING_ELIGIBLE:
        raise TenantExfiltrationBlocked(
            f"Candidate {candidate.candidate_id} is TENANT_PRIVATE and cannot become "
            f"GLOBAL_TRAINING_ELIGIBLE without an explicit, reviewed sanitization/approval step."
        )
    if target == TrainingDestination.TENANT_LOCAL_TRAINING:
        source_tenant = None
        for ref in candidate.source_lineage:
            if ref.startswith("tenant:"):
                source_tenant = ref.split(":", 1)[1]
                break
        if source_tenant and requesting_tenant_id and source_tenant != requesting_tenant_id:
            raise TenantExfiltrationBlocked(
                f"Candidate {candidate.candidate_id} belongs to tenant '{source_tenant}', "
                f"not '{requesting_tenant_id}' -- cross-tenant training access denied."
            )


class TrainingPromptInjectionBlocked(Exception):
    pass


# The bounded set of fields a candidate's OWN source text is never allowed
# to change via its content -- these are set exclusively by code/policy
# elsewhere in the pipeline (triage.py, dataset_manifest.approve(), the
# review queue), never derived from parsing the candidate's own text.
_PROTECTED_FIELDS = frozenset({
    "review_state", "training_destination", "target_model_family", "dedupe_fingerprint",
})


def assert_source_text_is_inert(candidate: CurriculumCandidate, attempted_field_changes: dict) -> None:
    """
    Spec §65: candidate source text is data. It cannot change compiler
    policy, grant approval, change target model, alter dataset split, or
    trigger training. Call this whenever a transformation step claims a
    change was "derived from the candidate's own input/evidence text" --
    if that change touches a protected field, it is rejected outright.
    """
    touched = _PROTECTED_FIELDS & attempted_field_changes.keys()
    if touched:
        raise TrainingPromptInjectionBlocked(
            f"Attempted to change protected field(s) {sorted(touched)} on candidate "
            f"{candidate.candidate_id} based on its own source text -- rejected (spec §65)."
        )


class CheckpointSupplyChainRejected(Exception):
    pass


def verify_checkpoint_supply_chain(checkpoint, expected_base_model: str, expected_dataset_ids: set[str]) -> None:
    """
    Spec §66: reject unknown model artifact, checksum mismatch, wrong base
    checkpoint, or unregistered dataset before training/evaluation/
    promotion. `checkpoint` is an orca.registry.checkpoint.CheckpointRecord.
    """
    from orca.registry.checkpoint import CorruptCheckpointError

    if checkpoint.base_model != expected_base_model:
        raise CheckpointSupplyChainRejected(
            f"Checkpoint '{checkpoint.checkpoint_id}' base_model={checkpoint.base_model!r} "
            f"does not match expected {expected_base_model!r}."
        )
    unregistered = set(checkpoint.dataset_manifest_ids) - expected_dataset_ids
    if not checkpoint.dataset_manifest_ids:
        raise CheckpointSupplyChainRejected(f"Checkpoint '{checkpoint.checkpoint_id}' has no registered dataset manifest ids.")
    if unregistered:
        raise CheckpointSupplyChainRejected(
            f"Checkpoint '{checkpoint.checkpoint_id}' references unregistered dataset(s): {sorted(unregistered)}"
        )
    try:
        checkpoint.verify_integrity()
    except CorruptCheckpointError as e:
        raise CheckpointSupplyChainRejected(str(e)) from e


class HoldoutExposureBlocked(Exception):
    pass


def assert_training_manifest_excludes_holdout(training_dataset_ids: set[str], holdout_dataset_id: str) -> None:
    """Spec §67: training pipeline must not gain access to protected
    holdout labels -- the holdout's dataset_id must never appear among the
    ids a training run's manifest references."""
    if holdout_dataset_id in training_dataset_ids:
        raise HoldoutExposureBlocked(f"Holdout dataset '{holdout_dataset_id}' must not appear in a training run's dataset references.")
