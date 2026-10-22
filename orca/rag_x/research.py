"""RAG-X research tracks X1–X8.

X2's threshold is declared in this module before `run_contradiction_first`
reads the frozen items. The runner does not change the threshold.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.rag_x.contracts import AnswerResult, RetrievalBudget, RetrievalRequest, RetrievalStatus
from orca.rag_x.corpus import Corpus
from orca.rag_x.kernel import execute, replay_evidence, verify_claim

# Pre-registered before the fixture result is interpreted.
X2_ID = "X2-contradiction-first-v1"
X2_PRIMARY_ENDPOINT = "confident_despite_conflict"
X2_NEGATIVE_IF = "contradiction-first count >= baseline count OR correct-answer loss > 0"


@dataclass(frozen=True)
class FrozenItem:
    item_id: str
    query: str
    expects_conflict: bool
    expects_answer: bool


# Frozen before execution. Do not add or drop items after seeing a result.
X2_ITEMS: tuple[FrozenItem, ...] = (
    FrozenItem("one-sided-a", "widget status", False, True),
    FrozenItem("one-sided-b", "bridge length", False, True),
    FrozenItem("conflict-a", "lamp state", True, False),
    FrozenItem("conflict-b", "door state", True, False),
    FrozenItem("missing", "unmentioned comet", False, False),
    FrozenItem("one-sided-c", "harbor depth", False, True),
)


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: str
    endpoint: str
    baseline: int
    treatment: int
    correct_loss: int
    hypothesis_supported: bool
    negative_result: bool
    detail: str


def confident_despite_conflict(result: AnswerResult) -> bool:
    return result.status == RetrievalStatus.SUCCESS and any(not item.temporal for item in result.contradictions)


def run_contradiction_first(corpus: Corpus, scope, *, software_revision: str) -> ExperimentResult:
    """Compare naive retrieval without a challenge pass to contradiction-first."""
    baseline = 0
    treatment = 0
    correct_loss = 0
    for item in X2_ITEMS:
        budget = RetrievalBudget(max_retrieval_calls=4, max_tokens=400)
        plain = execute(
            RetrievalRequest(item.query, scope, "naive", budget),
            corpus, software_revision=software_revision, challenge=False,
        )
        challenged = execute(
            RetrievalRequest(item.query, scope, "contradiction-first", budget),
            corpus, software_revision=software_revision, challenge=True,
        )
        if confident_despite_conflict(plain):
            baseline += 1
        if confident_despite_conflict(challenged):
            treatment += 1
        if item.expects_answer and challenged.status != RetrievalStatus.SUCCESS:
            correct_loss += 1
        if item.expects_conflict and plain.status == RetrievalStatus.SUCCESS and not plain.evidence:
            correct_loss += 0
    supported = treatment < baseline and correct_loss == 0
    return ExperimentResult(
        X2_ID, X2_PRIMARY_ENDPOINT, baseline, treatment, correct_loss, supported,
        not supported, X2_NEGATIVE_IF,
    )


def replay(result: AnswerResult, corpus: Corpus, scope) -> dict[str, object]:
    """Three replay modes. Generation replay does not promise byte-identical text."""
    return {
        "evidence_reconstruction": replay_evidence(result, corpus, scope),
        "verification_replay": [verify_claim(claim.claim, result.evidence).supported for claim in result.claims],
        "generation_replay": {
            "byte_identity": False,
            "reason": "the synthetic backend and any future model decode are not claimed to be byte-deterministic",
            "backend_id": result.manifest.backend_id,
        },
    }


def arbitrate(role_backends: dict[str, str]) -> dict[str, object]:
    """Count distinct backends. Repeated ids are not independent confirmations."""
    distinct = set(role_backends.values())
    native = [name for name in role_backends.values() if name.lower() in {"genesis", "novus", "aeternum"}]
    return {
        "roles": dict(role_backends),
        "independent_backends": len(distinct),
        "native_roles_trained": False,
        "native_roles_requested": native,
    }


def authorize_action(*, evidence_text: str, grant: str | None, principal: str, intent: str) -> dict[str, object]:
    """Evidence text is untrusted data. Only an explicit grant authorizes an action.

    This does not call the C02 mission backend.
    """
    required = ("principal", "intent", "grant")
    allowed = bool(grant) and grant != evidence_text and "grant" not in evidence_text.lower()
    # A grant token must be separate from the evidence body.
    if grant and grant in evidence_text:
        allowed = False
    return {
        "chain": required,
        "authorized": allowed,
        "principal": principal,
        "intent": intent,
        "evidence_conferred_permission": False,
        "c02_modified": False,
    }
