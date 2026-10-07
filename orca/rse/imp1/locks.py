"""Read-only proof that the frozen authorization locks are still denied.

This module cannot create a secret, select a model, or authorize corpus
generation, qualification, GPU, a provider, spending, or training.
"""

from __future__ import annotations

import json
from pathlib import Path

from orca.rse.imp1.verdict import CHECKS_PASSED, FAIL_CLOSED, POSTURE, Result, guard

_REPO = Path(__file__).resolve().parents[3]


def corpus_generation_authorized() -> bool:
    return False


def qualification_authorized() -> bool:
    return False


def model_selection_authorized() -> bool:
    return False


def gpu_authorized() -> bool:
    return False


def provider_authorized() -> bool:
    return False


def spending_authorized() -> bool:
    return False


def training_authorized() -> bool:
    return False


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("lock file")
    return data


@guard
def prove_authorization_locks(root: Path | None = None) -> Result:
    base = Path(root) if root is not None else _REPO
    corpus = _read_json(base / "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION.json")
    model = _read_json(base / "docs/orneur/authorization/MODEL_EVAL_AUTHORIZATION.json")
    runners = _read_json(base / "docs/orneur/authorization/QUALIFICATION_RUNNER_REGISTRY.json")
    if corpus.get("status") != "NOT_AUTHORIZED":
        return Result(FAIL_CLOSED, "CORPUS_LOCK")
    if model.get("status") != "NOT_AUTHORIZED":
        return Result(FAIL_CLOSED, "QUALIFICATION_LOCK")
    if model.get("gpu_allowed") is not False or model.get("network_provider_inference_allowed") is not False:
        return Result(FAIL_CLOSED, "PROVIDER_LOCK")
    if model.get("max_spend_usd") not in (0, None):
        return Result(FAIL_CLOSED, "SPEND_LOCK")
    records = runners.get("records")
    if not isinstance(records, list) or not records:
        return Result(FAIL_CLOSED, "RUNNER_LOCK")
    if any(row.get("state") != "REGISTERED_NOT_AUTHORIZED" for row in records):
        return Result(FAIL_CLOSED, "RUNNER_LOCK")
    if any(value not in (False, "NOT_AUTHORIZED") for _key, value in POSTURE):
        return Result(FAIL_CLOSED, "POSTURE")
    return Result(CHECKS_PASSED, "LOCKS_INTACT")
