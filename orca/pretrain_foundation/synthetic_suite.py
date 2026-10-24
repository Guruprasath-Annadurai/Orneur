"""Versioned synthetic tasks for the twelve handlers.

The handlers are deterministic functions. A result here is not a model
score and does not qualify an agent. Team size is the smallest plan that
meets the task predicate. A larger plan is not selected when it only adds
calls.
"""
from __future__ import annotations

import time

from orca.pretrain_foundation.governed_handlers import HANDLERS

SUITE_VERSION = "synthetic-agent-eval-v1"

_FULL = (
    "claim.classify",
    "claim.falsify",
    "claim.arbitrate",
    "content.screen",
    "deadline.bound",
    "cost.account",
    "training.watch",
    "memory.isolate",
    "promotion.deny",
    "authority.decide",
)
_SIZES = (1, 2, 3, 5, 10)


def _ordered(first: tuple[str, ...]) -> tuple[str, ...]:
    return first + tuple(name for name in _FULL if name not in first)

_OVERHEAD = {
    "content.screen": {"text": "local fixture"},
    "deadline.bound": {"used_ticks": 1, "budget_ticks": 5, "done": True},
    "cost.account": {"prices": {"handler": 1}, "currency": "fixture"},
    "training.watch": {"training": False, "gpu": False, "spend": False},
    "memory.isolate": {"actor_tenant": "t", "record_tenant": "t", "record_id": "r"},
    "promotion.deny": {"candidate_id": "cand", "produced_by": "lab", "decided_by": "reviewer"},
    "authority.decide": {
        "action": "read",
        "tenant_id": "t",
        "grant": {"tenant_id": "t", "capabilities": ["read"], "expired": False, "revoked": False},
    },
}


def _equation(text: str, span: str) -> dict:
    return {
        "claim_id": "eq",
        "text": text,
        "span": span,
        "source_id": "fixture",
        "authorized": True,
        "producer_id": "producer",
        "falsifier_id": "falsifier",
        "claims": [
            {"text": text, "state": "OBSERVED"},
            {"text": span, "state": "OBSERVED"},
        ],
    }


def _tasks() -> tuple[dict, ...]:
    return (
        {
            "id": "reasoning-unsupported",
            "category": "reasoning",
            "payload": _equation("2+2=5", "2+2=4"),
            "predicate": "refuted",
            "order": _ordered(("claim.classify", "claim.falsify")),
        },
        {
            "id": "reasoning-supported",
            "category": "reasoning",
            "payload": _equation("2+2=4", "2+2=4"),
            "predicate": "observed_unverified",
            "order": _ordered(("claim.classify",)),
        },
        {
            "id": "coding-return-value",
            "category": "coding",
            "payload": {"text": "def add(left, right):\n    return left + right\n", "producer_id": "producer"},
            "predicate": "tests_passed",
            "order": _ordered(("claim.classify",)),
        },
        {
            "id": "retrieval-span",
            "category": "retrieval",
            "payload": {"text": "What is the fixture span?", "producer_id": "producer"},
            "predicate": "retrieved_span",
            "order": _ordered(("claim.classify",)),
        },
        {
            "id": "contradiction",
            "category": "contradiction",
            "order": _ordered(("claim.classify", "claim.arbitrate")),
            "payload": {
                "text": "left",
                "producer_id": "producer",
                "claims": [
                    {"text": "left", "state": "OBSERVED"},
                    {"text": "right", "state": "OBSERVED"},
                ],
            },
            "predicate": "disputed",
        },
        {
            "id": "abstention",
            "category": "abstention",
            "payload": {"text": "2+2=4", "producer_id": "producer"},
            "predicate": "unknown",
            "order": _ordered(("claim.classify",)),
        },
        {
            "id": "authority-refusal",
            "category": "authority",
            "payload": _OVERHEAD["authority.decide"],
            "predicate": "denied",
            "order": _ordered(("authority.decide",)),
        },
        {
            "id": "workflow-incomplete",
            "category": "workflow",
            "payload": {"used_ticks": 5, "budget_ticks": 5, "done": False},
            "predicate": "incomplete",
            "order": _ordered(("deadline.bound",)),
        },
    )


def _payload_for(task: dict, handler_name: str) -> dict:
    if handler_name in {"claim.classify", "claim.falsify", "claim.arbitrate"}:
        return task["payload"]
    if handler_name == "authority.decide" and task["id"] == "authority-refusal":
        return task["payload"]
    if handler_name == "deadline.bound" and task["id"] == "workflow-incomplete":
        return task["payload"]
    return _OVERHEAD[handler_name]


def _invoke(handler_name: str, payload: dict) -> dict:
    """Run one handler. An exception stays inside the trial."""
    try:
        result = HANDLERS[handler_name](payload, {})
    except Exception as exc:
        return {
            "contained": True,
            "handler_error": type(exc).__name__,
            "handler": handler_name,
        }
    if not isinstance(result, dict):
        return {"contained": True, "handler_error": "non_dict_result", "handler": handler_name}
    return result


def _succeeded(predicate: str, results: list[dict]) -> bool:
    if predicate == "refuted":
        return any(row.get("state") == "REFUTED" for row in results)
    if predicate == "observed_unverified":
        return any(row.get("state") == "OBSERVED" and row.get("verified") is False for row in results) and not any(
            row.get("state") == "REFUTED" for row in results
        )
    if predicate == "tests_passed":
        return any(row.get("tests_passed") is True for row in results)
    if predicate == "retrieved_span":
        return any(row.get("retrieved") is True for row in results)
    if predicate == "disputed":
        return any(row.get("resolution") == "DISPUTED" for row in results)
    if predicate == "unknown":
        return any(row.get("state") == "UNKNOWN" for row in results) and not any(
            row.get("state") == "VERIFIED" for row in results
        )
    if predicate == "denied":
        return any(row.get("decision") == "DENIED" and row.get("executed") is False for row in results)
    if predicate == "incomplete":
        return any(row.get("status") == "INCOMPLETE" and row.get("fabricated_completion") is False for row in results)
    raise ValueError(f"unknown predicate {predicate}")


def _false_verification(results: list[dict]) -> int:
    return sum(1 for row in results if row.get("verified") is True or row.get("production_authorization") is True)


def _unsupported(predicate: str, results: list[dict], success: bool) -> int:
    if success:
        return 0
    if predicate == "refuted" and any(row.get("state") == "OBSERVED" for row in results):
        return 1
    return 0


def run_synthetic_suite(*, trials: int = 5) -> dict:
    if trials < 2:
        raise ValueError("trials must be at least 2")
    task_reports = []
    for task in _tasks():
        sizes = {}
        for size in _SIZES:
            names = task["order"][:size]
            started = time.perf_counter()
            trial_rows = []
            for _ in range(trials):
                results = [_invoke(name, _payload_for(task, name)) for name in names]
                success = _succeeded(task["predicate"], results)
                contained = sum(1 for row in results if row.get("contained") is True)
                trial_rows.append({
                    "success": success,
                    "false_verification": _false_verification(results),
                    "unsupported_claims": _unsupported(task["predicate"], results, success),
                    "contained_handler_errors": contained,
                    # A later handler can still meet the predicate after an
                    # earlier handler raises. That is containment, not a retry.
                    "failure_recovery": 1 if contained and success else 0,
                })
            elapsed = time.perf_counter() - started
            successes = [row["success"] for row in trial_rows]
            sizes[str(size)] = {
                "handler_calls": size,
                "success": successes[0],
                "trial_successes": successes,
                "variance": 0 if len(set(successes)) == 1 else len(set(successes)) - 1,
                "false_verification": trial_rows[0]["false_verification"],
                "unsupported_claims": trial_rows[0]["unsupported_claims"],
                "contained_handler_errors": trial_rows[0]["contained_handler_errors"],
                "failure_recovery": trial_rows[0]["failure_recovery"],
                "latency_seconds": elapsed / trials,
                "resource_handler_calls": size * trials,
            }
        selected = None
        for size in _SIZES:
            row = sizes[str(size)]
            if row["success"] and row["false_verification"] == 0:
                selected = size
                break
        task_reports.append({
            "id": task["id"],
            "category": task["category"],
            "predicate": task["predicate"],
            "sizes": sizes,
            "selected_team_size": selected,
            "larger_team_justified": bool(selected is not None and selected > 1),
            "model_inference": False,
        })
    return {
        "version": SUITE_VERSION,
        "model_inference": False,
        "independently_qualified": False,
        "production_authorized": False,
        "trials": trials,
        "latency_unit": "process_perf_counter_seconds",
        "tasks": task_reports,
    }


def shadow_tournament(report: dict) -> dict:
    """Compare plans already measured. The winner is not promoted."""
    if report.get("version") != SUITE_VERSION:
        raise ValueError("tournament requires synthetic-agent-eval-v1")
    tasks = {}
    for task in report["tasks"]:
        tasks[task["id"]] = {
            "selected_team_size": task["selected_team_size"],
            "qualified": False,
            "production_authorized": False,
        }
    return {
        "version": report["version"],
        "qualified": False,
        "production_authorized": False,
        "tasks": tasks,
    }
