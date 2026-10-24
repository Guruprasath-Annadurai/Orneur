"""Versioned improvement contracts for every declared role.

Execution stays inactive unless a role is both implemented and independently
qualified. None of the current roles are qualified, so none of these
contracts run a worker or approve a promotion.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.pretrain_foundation.role_registry import load_roles

CONTRACT_VERSION = "improvement-contract-v1"


def improvement_contracts() -> tuple[dict, ...]:
    rows = []
    for role in load_roles():
        qualified = role.qualification_state == "QUALIFIED"
        rows.append({
            "role_id": role.agent_id,
            "contract_version": CONTRACT_VERSION,
            "group": role.group,
            "implemented": role.implemented,
            "qualification_state": role.qualification_state,
            "execution": "ACTIVE" if role.implemented and qualified else "INACTIVE",
            "failure_recording": "shared-genome",
            "procedure_proposal": "data-only",
            "candidate_generation": "requires-qualified-handler",
            "baseline_comparison": "required-before-promotion",
            "independent_verification": "required",
            "promotion": "forbidden-without-enrolled-reviewer",
            "self_approval": False,
        })
    return tuple(rows)


def record_failure(path: Path, *, role_id: str, detail: str) -> dict:
    """Append one failure. This does not change the role's authority."""
    known = {row["role_id"] for row in improvement_contracts()}
    if role_id not in known or not detail:
        raise ValueError("failure record requires a declared role and a detail")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"role_id": role_id, "detail": detail, "promoted": False}, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return {"recorded": True, "promoted": False, "execution": "INACTIVE"}
