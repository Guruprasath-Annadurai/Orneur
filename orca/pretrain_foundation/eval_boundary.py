"""Phase 5 evaluation boundary controls (synthetic / non-secret).

Enforces training/evaluation identity separation and holdout access denial
for the training identity. Does not read protected evaluation corpora.
"""
from __future__ import annotations

from dataclasses import dataclass


class EvalBoundaryError(Exception):
    """Fail-closed evaluation boundary violation."""


TRAINING_IDENTITY = "training"
EVAL_IDENTITY = "evaluation"
HOLDOUT_IDENTITY = "holdout_custody"


@dataclass(frozen=True)
class AccessAttempt:
    actor_identity: str
    resource_class: str  # training_corpus | eval_public | eval_holdout | eval_private
    action: str  # read | score | publish


def authorize_access(attempt: AccessAttempt) -> None:
    """Refuse training identity reads of holdout / private eval resources."""
    if attempt.resource_class in {"eval_holdout", "eval_private"}:
        if attempt.actor_identity == TRAINING_IDENTITY:
            raise EvalBoundaryError(
                "training identity is denied holdout/private evaluation access "
                f"(resource={attempt.resource_class}, action={attempt.action})"
            )
        if attempt.actor_identity not in {EVAL_IDENTITY, HOLDOUT_IDENTITY}:
            raise EvalBoundaryError(
                f"identity {attempt.actor_identity!r} is not authorized for {attempt.resource_class}"
            )
    if attempt.resource_class == "training_corpus" and attempt.actor_identity == HOLDOUT_IDENTITY:
        raise EvalBoundaryError("holdout custody identity cannot read the training corpus")


def require_identity_separation(training_run_id: str, eval_id: str) -> None:
    if not training_run_id or not eval_id:
        raise EvalBoundaryError("training_run_id and eval_id are required")
    if training_run_id == eval_id:
        raise EvalBoundaryError("training run identity and evaluation identity must differ")


def fail_closed_on_scoring_error(*, scored_ok: bool, error_detail: str | None) -> None:
    if not scored_ok:
        raise EvalBoundaryError(
            f"evaluation scoring failed closed: {error_detail or 'unspecified error'}"
        )
