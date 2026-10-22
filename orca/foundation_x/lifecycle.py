"""Evidence-linked lifecycle chain.

Serving eligibility for GENESIS, NOVUS, or AETERNUM stays false unless a
non-synthetic founder grant is present. This module never creates that grant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LifecycleDecision(str, Enum):
    FAIL_CLOSED = "fail_closed"
    CHAIN_COMPLETE_TRAINING_NOT_AUTHORIZED = "chain_complete_training_not_authorized"


REQUIRED_LINKS = (
    "dataset",
    "transformations",
    "tokenizer",
    "config",
    "authorization",
    "run_identity",
    "training_state",
    "checkpoint",
    "evaluation",
    "qualification",
    "serving",
)


@dataclass(frozen=True)
class LifecycleChain:
    dataset_id: str | None = None
    dataset_digest: str | None = None
    transformation_digest: str | None = None
    tokenizer_id: str | None = None
    expected_tokenizer_id: str | None = None
    config_digest: str | None = None
    authorization_kind: str | None = None
    authorization_synthetic: bool = True
    run_id: str | None = None
    training_state_digest: str | None = None
    checkpoint_digest: str | None = None
    checkpoint_dataset_digest: str | None = None
    evaluation_id: str | None = None
    evaluation_approved: bool = False
    model_family: str | None = None
    model_family_trained: bool = False
    witness_required: bool = False
    witness_present: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


def assess_lifecycle(chain: LifecycleChain) -> tuple[LifecycleDecision, list[str]]:
    """Return the decision and every failed link. Training is not authorized here."""
    reasons: list[str] = []
    if not chain.dataset_id or not chain.dataset_digest:
        reasons.append("missing dataset manifest")
    if not chain.transformation_digest:
        reasons.append("missing transformation digest")
    if not chain.tokenizer_id or chain.tokenizer_id != chain.expected_tokenizer_id:
        reasons.append("tokenizer does not match the expected identity")
    if not chain.config_digest:
        reasons.append("missing config digest")
    if chain.authorization_kind != "FOUNDER_GRANT" or chain.authorization_synthetic:
        reasons.append("authorization is missing or synthetic")
    if not chain.run_id:
        reasons.append("missing run identity")
    if not chain.training_state_digest:
        reasons.append("missing training state")
    if not chain.checkpoint_digest:
        reasons.append("missing checkpoint")
    if chain.checkpoint_dataset_digest != chain.dataset_digest:
        reasons.append("checkpoint dataset digest does not match")
    if not chain.evaluation_id or not chain.evaluation_approved:
        reasons.append("evaluation is missing or unapproved")
    if chain.model_family in {"genesis", "novus", "aeternum"} and not chain.model_family_trained:
        reasons.append("model family is not trained")
    if chain.witness_required and not chain.witness_present:
        reasons.append("required external witness is missing")
    if reasons:
        return LifecycleDecision.FAIL_CLOSED, reasons
    return LifecycleDecision.CHAIN_COMPLETE_TRAINING_NOT_AUTHORIZED, ["founder grant matched the chain; this function still does not start training"]
