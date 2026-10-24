"""Structured business-report journey.

The caller supplies records and an objective kind. This module does not
infer a goal from natural language. Figures are non-boolean integer cents.
Completion stores a binding and does not treat a later file edit as success.
The flock is single-host.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.core_runtime.journal import Journal, MissionError, _sha
from orca.core_runtime.router import route

_STEPS = ["select_tool", "read_records", "calculate", "write_artifact", "verify"]
_MAX_ROWS = 1000
_MAX_MAGNITUDE = 1_000_000_000_000


class JourneyInterrupted(Exception):
    pass


class JourneyRefused(Exception):
    def __init__(self, code: str, report: dict):
        self.code = code
        self.report = report
        super().__init__(code)


def canonical_records(records: list) -> bytes:
    return json.dumps(records, sort_keys=True, separators=(",", ":")).encode()


def recompute(records: list) -> int:
    if not isinstance(records, list) or not records:
        raise MissionError("missing_data")
    if len(records) > _MAX_ROWS:
        raise MissionError("input_too_large")
    total = 0
    for row in records:
        if not isinstance(row, dict) or "units" not in row or "unit_price_cents" not in row:
            raise MissionError("missing_data")
        units = row["units"]
        price = row["unit_price_cents"]
        if type(units) is not int or type(price) is not int or units < 0 or price < 0:
            raise MissionError("invalid_record")
        if units > _MAX_MAGNITUDE or price > _MAX_MAGNITUDE:
            raise MissionError("input_too_large")
        total += units * price
        if total > _MAX_MAGNITUDE:
            raise MissionError("input_too_large")
    return total


def _artifact_rel(mission_id: str) -> Path:
    return Path("artifacts") / mission_id / "report.json"


def _write_once(journal: Journal, mission_id: str, owner: str, effect_key: str, payload: bytes, crash_after: str | None) -> dict:
    effect = journal.begin_effect(mission_id, owner, effect_key, payload)
    relative = _artifact_rel(mission_id)
    if effect["status"] == "committed":
        return effect
    if effect["status"] == "bytes_written":
        try:
            current = journal.read_bytes(relative)
        except FileNotFoundError:
            current = b""
        if current == payload:
            return journal.commit_effect(mission_id, owner, effect_key)
    if crash_after == f"cancel_after_admit:{effect_key}":
        journal.request_cancel(mission_id, owner)
    elif crash_after == f"revoke_after_admit:{effect_key}":
        journal.revoke(mission_id, owner)
    fresh = journal.get(mission_id, owner)
    if fresh.get("cancel_requested") or fresh.get("access_revoked") or fresh.get("state") == "revoked":
        return journal.commit_effect(mission_id, owner, effect_key)
    if crash_after == f"before:{effect_key}":
        journal.transition(mission_id, owner, "interrupted")
        raise JourneyInterrupted()
    try:
        current = journal.read_bytes(relative)
    except FileNotFoundError:
        current = None
    except MissionError:
        raise
    if current is not None and current != payload:
        raise MissionError("artifact_conflict")
    if current is None:
        journal.write_bytes(relative, payload)
        if crash_after == f"cancel_after_bytes:{effect_key}":
            journal.request_cancel(mission_id, owner)
        elif crash_after == f"revoke_after_bytes:{effect_key}":
            journal.revoke(mission_id, owner)
        journal.note_write(mission_id, owner, effect_key)
    elif effect["status"] == "started":
        journal.note_write(mission_id, owner, effect_key)
    if crash_after == f"after_bytes:{effect_key}":
        journal.transition(mission_id, owner, "interrupted")
        raise JourneyInterrupted()
    return journal.commit_effect(mission_id, owner, effect_key)


def _integrity(journal: Journal, mission: dict, records: list) -> tuple[str, bool, int | None]:
    verification = mission.get("verification") or None
    if not verification:
        return "missing_evidence", False, None
    try:
        artifact = journal.read_bytes(_artifact_rel(mission["mission_id"]))
    except FileNotFoundError:
        return "missing_artifact", False, verification.get("total_cents")
    except MissionError:
        return "artifact_unreadable", False, verification.get("total_cents")
    if _sha(artifact) != verification.get("artifact_sha256"):
        return "artifact_digest_mismatch", False, verification.get("total_cents")
    if _sha(canonical_records(records)) != verification.get("input_sha256"):
        return "input_revision_mismatch", False, verification.get("total_cents")
    try:
        parsed = json.loads(artifact)
        total = recompute(records)
    except (MissionError, json.JSONDecodeError):
        return "postcondition_mismatch", False, verification.get("total_cents")
    if parsed.get("total_cents") != verification.get("total_cents") or total != verification.get("total_cents"):
        return "postcondition_mismatch", False, verification.get("total_cents")
    return "intact", True, total


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
    mission_path = journal.root / "missions" / f"{mission_id}.json"
    if mission_path.is_symlink():
        raise MissionError("symlink_refused")
    if mission_path.exists():
        mission = journal.get(mission_id, owner_user_id)
    else:
        mission = journal.create(
            mission_id=mission_id,
            owner_user_id=owner_user_id,
            objective={"kind": "structured_report", "title": "synthetic-business-report"},
            steps=_STEPS,
        )
        if crash_after == "after:draft":
            raise JourneyInterrupted()
    if mission["access_revoked"] or mission["state"] == "revoked":
        raise JourneyRefused("revoked", _report(mission_id, owner_user_id, journal, state=mission["state"], total=None, verified=False, code="revoked", integrity="revoked"))
    if mission["state"] == "completed_verified":
        integrity, verified, total = _integrity(journal, mission, records)
        code = "ok" if verified else integrity
        return _report(
            mission_id, owner_user_id, journal,
            state="completed_verified", total=total, verified=verified, code=code,
            writes=(journal.effect(mission_id, owner_user_id, "write_report") or {}).get("writes", 0),
            integrity=integrity,
        )
    if mission["state"] in {"failed", "cancelled", "partial"}:
        return _report(mission_id, owner_user_id, journal, state=mission["state"], total=None, verified=False, code=mission["state"], integrity="historical")
    if mission["state"] == "draft":
        journal.transition(mission_id, owner_user_id, "running")
    elif mission["state"] == "interrupted":
        journal.transition(mission_id, owner_user_id, "running")
    mission = journal.get(mission_id, owner_user_id)
    if mission["cancel_requested"] and mission["state"] != "verifying":
        journal.transition(mission_id, owner_user_id, "cancelled")
        return _report(mission_id, owner_user_id, journal, state="cancelled", total=None, verified=False, code="cancelled", integrity="cancelled")
    if mission["state"] != "verifying" and crash_after == "timeout":
        journal.transition(mission_id, owner_user_id, "failed")
        raise JourneyRefused("timed_out", _report(mission_id, owner_user_id, journal, state="failed", total=None, verified=False, code="timed_out", integrity="timed_out"))

    if mission["state"] != "verifying":
        try:
            journal.bind_input(mission_id, owner_user_id, canonical_records(records))
        except MissionError as exc:
            if exc.code == "input_revision_mismatch":
                current = journal.get(mission_id, owner_user_id)
                return _report(
                    mission_id, owner_user_id, journal,
                    state=current["state"], total=None, verified=False,
                    code="input_revision_mismatch", integrity="input_revision_mismatch",
                )
            raise
        select_pending = any(step["id"] == "select_tool" and step["status"] == "pending" for step in mission["steps"])
        decision = route(task_type="structured_arithmetic", requested_family=requested_family, budget_usd=budget_usd, capability_cost_usd=0)
        if decision["decision"] != "selected":
            journal.transition(mission_id, owner_user_id, "failed")
            raise JourneyRefused(decision["code"], _report(mission_id, owner_user_id, journal, state="failed", total=None, verified=False, code=decision["code"], route=decision, integrity="refused"))
        journal.mark_step(mission_id, owner_user_id, "select_tool", "completed")
        if crash_after == "after:running" and select_pending:
            raise JourneyInterrupted()
        try:
            total = recompute(records)
        except MissionError as exc:
            journal.transition(mission_id, owner_user_id, "failed")
            raise JourneyRefused(exc.code, _report(mission_id, owner_user_id, journal, state="failed", total=None, verified=False, code=exc.code, integrity=exc.code)) from exc
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
            "effect_key": "write_report",
        }
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        try:
            effect = _write_once(journal, mission_id, owner_user_id, "write_report", payload, crash_after)
        except MissionError as exc:
            if exc.code in {"cancelled_after_admission", "revoked_after_admission"}:
                current = journal.get(mission_id, owner_user_id)
                if current["state"] == "running":
                    journal.transition(mission_id, owner_user_id, "revoked" if exc.code.startswith("revoked") else "cancelled")
                return _report(mission_id, owner_user_id, journal, state=journal.get(mission_id, owner_user_id)["state"], total=None, verified=False, code=exc.code, integrity=exc.code)
            raise
        journal.mark_step(mission_id, owner_user_id, "write_artifact", "completed")
    else:
        decision = None
        effect = journal.effect(mission_id, owner_user_id, "write_report") or {"writes": 0}
        payload = journal.read_bytes(_artifact_rel(mission_id))
        total = json.loads(payload)["total_cents"]

    if corrupt_artifact:
        observed = journal.read_bytes(_artifact_rel(mission_id))
        (journal.root / "artifacts" / mission_id / "report.json").write_bytes(observed + b" ")
    if journal.get(mission_id, owner_user_id)["state"] != "verifying":
        journal.transition(mission_id, owner_user_id, "verifying")
        if crash_after == "after:verifying":
            raise JourneyInterrupted()
    observed = journal.read_bytes(_artifact_rel(mission_id))
    try:
        recomputed = recompute(records)
    except MissionError as exc:
        journal.transition(mission_id, owner_user_id, "failed")
        raise JourneyRefused(exc.code, _report(mission_id, owner_user_id, journal, state="failed", total=None, verified=False, code=exc.code, integrity=exc.code)) from exc
    intact = observed == payload and recomputed == total
    fresh = journal.get(mission_id, owner_user_id)
    if fresh["cancel_requested"] or fresh["access_revoked"]:
        if fresh["state"] == "verifying":
            journal.transition(mission_id, owner_user_id, "cancelled" if fresh["cancel_requested"] else "revoked")
        return _report(mission_id, owner_user_id, journal, state=journal.get(mission_id, owner_user_id)["state"], total=recomputed, verified=False, code="cancelled" if fresh["cancel_requested"] else "revoked", integrity="cancelled_during_verification")
    if fresh.get("input_sha256") != _sha(canonical_records(records)):
        return _report(
            mission_id, owner_user_id, journal,
            state=fresh["state"], total=None, verified=False, code="input_revision_mismatch",
            writes=effect.get("writes", 0), route=decision, integrity="input_revision_mismatch",
        )
    if not intact:
        journal.transition(mission_id, owner_user_id, "failed")
        return _report(mission_id, owner_user_id, journal, state="failed", total=recomputed, verified=False, code="verifier_rejected", writes=effect.get("writes", 0), route=decision, integrity="verifier_rejected")
    journal.mark_step(mission_id, owner_user_id, "verify", "completed")
    journal.seal_verified(mission_id, owner_user_id)
    return _report(
        mission_id, owner_user_id, journal,
        state="completed_verified", total=recomputed, verified=True, code="ok",
        writes=effect.get("writes", 0), route=decision, integrity="intact",
    )


def _report(mission_id, owner, journal: Journal, *, state, total, verified, code, writes=0, route=None, integrity="unknown") -> dict:
    mission = journal.get(mission_id, owner)
    return {
        "schema": "orneur-mission-report/1",
        "mission_id": mission_id,
        "state": state,
        "journal_state": mission["state"],
        "historical_verification": mission.get("verification"),
        "current_integrity": integrity,
        "code": code,
        "total_cents": total,
        "independently_verified": verified,
        "artifact_writes": writes,
        "route": route,
        "native_model_loaded": False,
        "language_understanding": "not_performed",
        "actor_authenticated": False,
        "durability": "single_host_flock",
        "production_runtime": False,
    }
