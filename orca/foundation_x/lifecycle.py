"""Evidence-linked lifecycle chain.

A string in `authorization_kind` is a caller claim. It is not a founder
grant. The only authorization evidence this function accepts is a
`NativePretrainingGrant` that passes `verify_integrity()` and whose
dataset, tokenizer, transformation, config, and run digests match the
chain. Even then the decision does not start training and does not call
`authorize_native_pretraining` or `GenesisTrainingRun.authorize`.

This module never mints a grant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from orca.genesis.governance.authorization import NativePretrainingGrant, NativePretrainingNotAuthorized


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
    tokenizer_digest: str | None = None
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


def _grant_binding_reasons(chain: LifecycleChain, grant) -> list[str]:
    """Compare grant fields to the chain. This is not an authorization decision."""
    reasons: list[str] = []
    checks = (
        (getattr(grant, "dataset_manifest_id", None), chain.dataset_id, "grant dataset id does not match the chain"),
        (getattr(grant, "dataset_content_digest", None), chain.dataset_digest, "grant dataset digest does not match the chain"),
        (getattr(grant, "transformation_code_digest", None), chain.transformation_digest, "grant transformation digest does not match the chain"),
        (getattr(grant, "model_config_digest", None), chain.config_digest, "grant config digest does not match the chain"),
        (getattr(grant, "tokenizer_digest", None), chain.tokenizer_digest, "grant tokenizer digest does not match the chain"),
        (getattr(grant, "run_id", None), chain.run_id, "grant run id does not match the chain"),
    )
    for actual, expected, reason in checks:
        if not expected or actual != expected:
            reasons.append(reason)
    if chain.checkpoint_dataset_digest != getattr(grant, "dataset_content_digest", None):
        reasons.append("checkpoint dataset digest does not match the grant")
    return reasons


def _authorization(chain: LifecycleChain, grant) -> tuple[list[str], list[str]]:
    ignored: list[str] = []
    if chain.authorization_kind:
        ignored.append(f"caller authorization claim ignored: {chain.authorization_kind}")
    if grant is None:
        return ["no NativePretrainingGrant was supplied"], ignored
    if not isinstance(grant, NativePretrainingGrant):
        return ["supplied authorization is not a NativePretrainingGrant"], ignored
    try:
        grant.verify_integrity()
    except NativePretrainingNotAuthorized as exc:
        return ["grant integrity failed: " + ",".join(exc.reasons)], ignored
    return _grant_binding_reasons(chain, grant), ignored


def assess_lifecycle(chain: LifecycleChain, grant=None) -> tuple[LifecycleDecision, list[str]]:
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
    auth_reasons, ignored = _authorization(chain, grant)
    reasons.extend(auth_reasons)
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
        return LifecycleDecision.FAIL_CLOSED, reasons + ignored
    return LifecycleDecision.CHAIN_COMPLETE_TRAINING_NOT_AUTHORIZED, [
        "NativePretrainingGrant integrity and digest binding passed",
        "this function does not start training and does not issue training authorization",
        *ignored,
    ]
