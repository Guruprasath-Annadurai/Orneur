"""Deterministic assessment scoring for synthetic learners.

A learner cannot score their own attempt. Nothing here is an accredited
qualification. Sharing a minor's record is refused.
"""
from __future__ import annotations

SCHEMA = "orneur-proof-assessment/1"


class ProofError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def score_attempt(*, assessment: dict, learner_id: str, scorer_id: str, responses: dict, mode: str, age_band: str) -> dict:
    if assessment.get("schema") != SCHEMA:
        raise ProofError("bad_assessment")
    if mode not in {"assisted", "unaided"}:
        raise ProofError("bad_mode")
    if not learner_id or not scorer_id:
        raise ProofError("missing_identity")
    if scorer_id == learner_id:
        raise ProofError("self_score_refused")
    if age_band == "child":
        shareable = False
    elif age_band == "adult":
        shareable = True
    else:
        raise ProofError("age_band_unknown")
    items = assessment.get("items") or []
    passed, failed, not_evaluated = [], [], []
    for item in items:
        item_id = item["id"]
        if item_id not in responses:
            not_evaluated.append(item_id)
            continue
        if responses[item_id] == item["answer"]:
            passed.append(item_id)
        else:
            failed.append(item_id)
    return {
        "schema": "orneur-proof-result/1",
        "assessment_id": assessment["assessment_id"],
        "assessment_version": assessment["version"],
        "learner_id": learner_id,
        "scorer_id": scorer_id,
        "mode": mode,
        "passed": passed,
        "failed": failed,
        "not_evaluated": not_evaluated,
        "accredited": False,
        "shareable": shareable,
        "synthetic_learner": True,
    }


def share_record(result: dict, *, public: bool) -> dict:
    if public and not result["shareable"]:
        raise ProofError("child_share_refused")
    if public:
        raise ProofError("public_share_not_issued")
    return {"shared": False, "code": "private", "learner_id": result["learner_id"]}
