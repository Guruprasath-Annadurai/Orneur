"""Structured business-report journey.

The caller supplies records and an objective kind. This module does not
infer a goal from natural language. Figures are integer cents. The saved
artifact is recomputed before a verified completion is recorded.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.core_runtime.journal import Journal, MissionError
from orca.core_runtime.router import route

_STEPS = ["select_tool", "read_records", "calculate", "write_artifact", "verify"]


class JourneyInterrupted(Exception):
    pass


class JourneyRefused(Exception):
    def __init__(self, code: str, report: dict):
        self.code = code
        self.report = report
        super().__init__(code)


def recompute(records: list[dict]) -> int:
    if not records:
        raise MissionError("missing_data")
    total = 0
    for row in records:
        if "units" not in row or "unit_price_cents" not in row:
            raise MissionError("missing_data")
        units = row["units"]
        price = row["unit_price_cents"]
        if not isinstance(units, int) or not isinstance(price, int) or units < 0 or price < 0:
            raise MissionError("invalid_record")
        total += units * price
    return total


def _artifact_path(root: Path, mission_id: str) -> Path:
    return root / "artifacts" / mission_id / "report.json"


def _write_once(journal: Journal, mission_id: str, owner: str, effect_key: str, payload: bytes, path: Path, crash_after: str | None) -> dict:
    effect = journal.begin_effect(mission_id, owner, effect_key, payload)
    if effect["status"] == "committed":
        return effect
    if effect["status"] == "bytes_written" and path.is_file() and path.read_bytes() == payload:
        return journal.commit_effect(mission_id, owner, effect_key)
    if crash_after == f"before:{effect_key}":
        journal.transition(mission_id, owner, "interrupted")
        raise JourneyInterrupted()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != payload:
        raise MissionError("artifact_conflict")
    if not path.exists():
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        journal.note_write(mission_id, owner, effect_key)
    if crash_after == f"after_bytes:{effect_key}":
        journal.transition(mission_id, owner, "interrupted")
        raise JourneyInterrupted()
    return journal.commit_effect(mission_id, owner, effect_key)


def run_business_report(
    journal: Journal,
    *,
    mission_id: str,
    owner_user_id: str,
    records: list[dict],
    budget_usd: float = 0,
    requested_family: str | None = None,
    crash_after: str | None = None,
    corrupt_artifact: bool = False,
) -> dict:
    root = journal.root
    path = _artifact_path(root, mission_id)
    if (journal.root / "missions" / f"{mission_id}.json").exists():
        mission = journal.get(mission_id, owner_user_id)
    else:
        mission = journal.create(
            mission_id=mission_id,
            owner_user_id=owner_user_id,
            objective={"kind": "structured_report", "title": "synthetic-business-report"},
            steps=_STEPS,
        )
    if mission["access_revoked"] or mission["state"] == "revoked":
        raise JourneyRefused("revoked", _report(mission_id, owner_user_id, journal, state=mission["state"], total=None, verified=False, code="revoked"))
    if mission["state"] == "completed_verified":
        saved = json.loads(path.read_bytes())
        effect = journal.effect(mission_id, owner_user_id, "write_report") or {"writes": 0}
        return _report(
            mission_id, owner_user_id, journal,
            state="completed_verified", total=saved["total_cents"], verified=True, code="ok",
            writes=effect.get("writes", 0),
        )
    if mission["state"] == "draft":
        journal.transition(mission_id, owner_user_id, "running")
    elif mission["state"] == "interrupted":
        journal.transition(mission_id, owner_user_id, "running")
    mission = journal.get(mission_id, owner_user_id)
    if mission["cancel_requested"]:
        journal.transition(mission_id, owner_user_id, "cancelled")
        return _report(mission_id, owner_user_id, journal, state="cancelled", total=None, verified=False, code="cancelled")
    if crash_after == "timeout":
        journal.transition(mission_id, owner_user_id, "failed")
        raise JourneyRefused("timed_out", _report(mission_id, owner_user_id, journal, state="failed", total=None, verified=False, code="timed_out"))

    decision = route(
        task_type="structured_arithmetic",
        requested_family=requested_family,
        budget_usd=budget_usd,
        capability_cost_usd=0,
    )
    if decision["decision"] != "selected":
        journal.transition(mission_id, owner_user_id, "failed")
        raise JourneyRefused(decision["code"], _report(mission_id, owner_user_id, journal, state="failed", total=None, verified=False, code=decision["code"], route=decision))
    journal.mark_step(mission_id, owner_user_id, "select_tool", "completed")

    try:
        total = recompute(records)
    except MissionError as exc:
        journal.transition(mission_id, owner_user_id, "failed")
        raise JourneyRefused(exc.code, _report(mission_id, owner_user_id, journal, state="failed", total=None, verified=False, code=exc.code)) from exc
    journal.mark_step(mission_id, owner_user_id, "read_records", "completed")
    journal.mark_step(mission_id, owner_user_id, "calculate", "completed")

    body = {
        "schema": "orneur-business-report/1",
        "mission_id": mission_id,
        "owner_user_id": owner_user_id,
        "total_cents": total,
        "line_count": len(records),
        "calculator": decision["tool"],
        "native_model_used": None,
        "verified": False,
    }
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    path = _artifact_path(root, mission_id)
    effect = _write_once(journal, mission_id, owner_user_id, "write_report", payload, path, crash_after)
    journal.mark_step(mission_id, owner_user_id, "write_artifact", "completed")

    observed = path.read_bytes()
    if corrupt_artifact:
        path.write_bytes(observed + b" ")
        observed = path.read_bytes()
    journal.transition(mission_id, owner_user_id, "verifying")
    recomputed = recompute(records)
    intact = observed == payload
    figures_match = recomputed == total and intact
    if not figures_match:
        journal.transition(mission_id, owner_user_id, "failed")
        return _report(
            mission_id, owner_user_id, journal,
            state="failed", total=recomputed, verified=False, code="verifier_rejected",
            writes=effect["writes"], route=decision,
        )
    reopened = json.loads(path.read_bytes())
    if reopened["total_cents"] != recomputed:
        journal.transition(mission_id, owner_user_id, "failed")
        return _report(
            mission_id, owner_user_id, journal,
            state="failed", total=recomputed, verified=False, code="verifier_rejected",
            writes=effect["writes"], route=decision,
        )
    journal.mark_step(mission_id, owner_user_id, "verify", "completed")
    journal.transition(mission_id, owner_user_id, "completed_verified")
    return _report(
        mission_id, owner_user_id, journal,
        state="completed_verified", total=total, verified=True, code="ok",
        writes=effect["writes"], route=decision,
    )


def _report(mission_id, owner, journal: Journal, *, state, total, verified, code, writes=0, route=None) -> dict:
    mission = journal.get(mission_id, owner)
    return {
        "schema": "orneur-mission-report/1",
        "mission_id": mission_id,
        "state": mission["state"] if mission["state"] == state else state,
        "journal_state": mission["state"],
        "code": code,
        "total_cents": total,
        "independently_verified": verified,
        "artifact_writes": writes,
        "route": route,
        "native_model_loaded": False,
        "language_understanding": "not_performed",
    }
