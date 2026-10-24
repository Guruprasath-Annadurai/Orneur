"""Deterministic team-size comparison on one synthetic equation task.

The handlers are not model inference. Repeated trials match because the
functions are pure. A larger team is better only when its extra handler
changes the verdict.
"""
from __future__ import annotations

from orca.pretrain_foundation.governed_handlers import HANDLERS


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


def _verdict(results: list[dict]) -> str:
    for result in results:
        if result.get("state") == "REFUTED":
            return "REFUTED"
    for result in results:
        if result.get("state") == "OBSERVED":
            return "OBSERVED"
    return "UNKNOWN"


def compare_equation_teams(*, trials: int = 5) -> dict:
    """Compare 1, 3, 5, and 10 handler calls on two fixed equations."""
    if trials < 2:
        raise ValueError("trials must be at least 2")
    plans = {
        1: ("claim.classify",),
        3: ("claim.classify", "claim.falsify", "claim.arbitrate"),
        5: ("claim.classify", "claim.falsify", "claim.arbitrate", "content.screen", "deadline.bound"),
        10: (
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
        ),
    }
    cases = {
        "supported": _equation("2+2=4", "2+2=4"),
        "unsupported": _equation("2+2=5", "2+2=4"),
    }
    overhead = {
        "content.screen": {"text": "2+2=4"},
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
    report = {"trials": trials, "deterministic": True, "model_inference": False, "cases": {}}
    for name, base in cases.items():
        sizes = {}
        for size, names in plans.items():
            trial_verdicts = []
            for _ in range(trials):
                results = []
                for handler_name in names:
                    payload = overhead.get(handler_name, base)
                    results.append(HANDLERS[handler_name](payload, {}))
                trial_verdicts.append(_verdict(results))
            sizes[str(size)] = {
                "handler_calls": size,
                "verdict": trial_verdicts[0],
                "trial_verdicts": trial_verdicts,
                "variance": 0 if len(set(trial_verdicts)) == 1 else len(set(trial_verdicts)) - 1,
            }
        single = sizes["1"]["verdict"]
        pair = sizes["3"]["verdict"]
        sizes_better_than_one = [
            int(size) for size, row in sizes.items() if int(size) > 1 and row["verdict"] != single and row["verdict"] == "REFUTED"
        ]
        report["cases"][name] = {
            "sizes": sizes,
            "larger_team_changes_verdict": bool(sizes_better_than_one),
            "ten_matches_three": sizes["10"]["verdict"] == pair,
            "ten_costs_more_calls": sizes["10"]["handler_calls"] > sizes["3"]["handler_calls"],
        }
    return report
