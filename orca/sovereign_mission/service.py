"""Authenticated mission execution. A response is not an external effect."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from orca.auth.crypto import create_token, verify_token
import orca.auth.db as auth_db
from orca.auth.store import User, get_user_by_id, is_token_revoked
from orca.sovereign_mission import states
from orca.sovereign_mission.store import StoreError, Unit, canonical, connect, digest, ensure_schema, now_iso

_TOOLS = frozenset({"browser", "local_marker"})
_BROWSER_ACTIONS = frozenset({"navigate", "read", "click", "fill", "scroll", "screenshot"})
_LIVE: dict[str, object] = {}
_STOP: dict[str, str] = {}
_LIVE_LOCK = threading.Lock()


class MissionError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SovereignMission:
    def __init__(self, *, fail_outcome_write: bool = False):
        ensure_schema()
        self.fail_outcome_write = fail_outcome_write
        # A restarted process must not leave an in-flight effect looking executable.
        self.recover()

    def session_user(self, token: str) -> User:
        payload = verify_token(token) if isinstance(token, str) else None
        if not payload or payload.get("type", "session") != "session":
            raise MissionError("unauthenticated")
        jti = payload.get("jti")
        if jti and is_token_revoked(jti):
            raise MissionError("unauthenticated")
        user = get_user_by_id(payload.get("sub", ""))
        if user is None or float(payload.get("iat", 0)) < user.tokens_valid_after:
            raise MissionError("unauthenticated")
        return user

    def login(self, email: str, password: str) -> str:
        from orca.auth.store import authenticate

        user = authenticate(email, password)
        if user is None:
            raise MissionError("unauthenticated")
        return self.issue_session(user)

    def issue_session(self, user: User) -> str:
        return create_token(
            {
                "sub": user.id,
                "type": "session",
                "jti": uuid.uuid4().hex,
                "email": user.email,
                "tier": user.tier,
                "role": user.role,
            }
        )

    def create(self, user: User, objective: str) -> dict:
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 500:
            raise MissionError("objective_refused")
        mission_id = uuid.uuid4().hex
        stamp = now_iso()
        unit = Unit()
        try:
            unit.conn.execute(
                """
                INSERT INTO sovereign_missions
                    (id, owner_user_id, tenant_id, objective, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (mission_id, user.id, user.id, objective.strip(), states.CREATED, stamp, stamp),
            )
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        return self.get(user, mission_id)

    def save_plan(self, user: User, mission_id: str, steps: list[dict]) -> dict:
        classified = [_classify(step, index) for index, step in enumerate(steps)]
        if not classified:
            raise MissionError("plan_refused")
        unit = Unit()
        try:
            mission = self._owned(unit, user, mission_id)
            states.transition(mission["state"], states.PLANNED)
            unit.conn.execute("DELETE FROM sovereign_steps WHERE mission_id=?", (mission_id,))
            for step in classified:
                unit.conn.execute(
                    """
                    INSERT INTO sovereign_steps
                        (id, mission_id, position, tool, risk, arguments_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (step["id"], mission_id, step["position"], step["tool"], step["risk"], canonical(step["arguments"])),
                )
            self._set_state(unit, mission, states.PLANNED)
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        return self.get(user, mission_id)

    def request_approval(self, user: User, mission_id: str) -> dict:
        unit = Unit()
        try:
            mission = self._owned(unit, user, mission_id)
            states.transition(mission["state"], states.AWAITING_APPROVAL)
            self._set_state(unit, mission, states.AWAITING_APPROVAL)
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        return self.get(user, mission_id)

    def approve(self, user: User, mission_id: str, step_id: str, *, ttl_seconds: int, now: datetime | None = None) -> dict:
        if ttl_seconds < 1 or ttl_seconds > 120:
            raise MissionError("approval_ttl_refused")
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None:
            raise MissionError("naive_clock")
        expires = clock + timedelta(seconds=ttl_seconds)
        approval_id = uuid.uuid4().hex
        unit = Unit()
        try:
            mission = self._owned(unit, user, mission_id)
            if mission["state"] not in {states.AWAITING_APPROVAL, states.AUTHORIZED}:
                raise MissionError("approval_refused")
            step = self._step(unit, mission_id, step_id)
            if step["approval_id"]:
                raise MissionError("approval_replay_refused")
            destination = _destination(step)
            unit.conn.execute(
                """
                INSERT INTO sovereign_approvals
                    (id, mission_id, step_id, user_id, tool, destination, expires_at, nonce)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (approval_id, mission_id, step_id, user.id, step["tool"], destination, now_iso(expires), uuid.uuid4().hex),
            )
            unit.conn.execute("UPDATE sovereign_steps SET approval_id=? WHERE id=?", (approval_id, step_id))
            if mission["state"] == states.AWAITING_APPROVAL:
                self._set_state(unit, mission, states.AUTHORIZED)
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        return {"approval_id": approval_id, "expires_at": now_iso(expires), "mission": self.get(user, mission_id)}

    def dispatch(self, user: User, mission_id: str, step_id: str, *, now: datetime | None = None) -> dict:
        clock = now or datetime.now(timezone.utc)
        prepared = self._prepare(user, mission_id, step_id, clock)
        if prepared.get("receipt"):
            return prepared["receipt"]
        try:
            outcome = self._execute(user, prepared["mission"], prepared["step"], clock)
        except MissionError as exc:
            if exc.code != "outcome_write_failed":
                self._settle(mission_id, step_id, exc.code)
            raise
        except Exception as exc:
            self._settle(mission_id, step_id, "execution_interrupted")
            raise MissionError("execution_interrupted") from exc
        self._finish(user, mission_id, step_id, outcome)
        return self.reported(user, mission_id)

    def request_cancel(self, user: User, mission_id: str) -> dict:
        unit = Unit()
        confirmed = False
        try:
            mission = self._require_owner(unit, user, mission_id, cancel_requested=1)
            started = self._step_effects(unit, mission_id)
            uncertain = any(row["effect_started"] and row["outcome_json"] is None for row in started)
            external = any(row["effect_started"] for row in started)
            if uncertain and mission["state"] == states.EXECUTING:
                self._set_state(unit, mission, states.OUTCOME_UNKNOWN)
            elif (
                not external
                and mission["state"] in {
                    states.CREATED,
                    states.PLANNED,
                    states.AWAITING_APPROVAL,
                    states.AUTHORIZED,
                    states.EXECUTING,
                }
            ):
                self._set_state(unit, mission, states.CANCELLED)
                confirmed = True
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        self._arm_stop(mission_id, "cancelled")
        body = self.get(user, mission_id)
        body["cancel_confirmed"] = confirmed and body["state"] == states.CANCELLED
        return body

    def revoke(self, user: User, mission_id: str) -> dict:
        unit = Unit()
        try:
            mission = self._require_owner(unit, user, mission_id, revoked=1)
            unit.conn.execute(
                """
                UPDATE sovereign_approvals SET consumed_at=?
                WHERE mission_id=? AND user_id=? AND consumed_at IS NULL
                """,
                (now_iso(), mission_id, user.id),
            )
            started = self._step_effects(unit, mission_id)
            uncertain = any(row["effect_started"] and row["outcome_json"] is None for row in started)
            external = any(row["effect_started"] for row in started)
            if uncertain and mission["state"] == states.EXECUTING:
                self._set_state(unit, mission, states.OUTCOME_UNKNOWN)
            elif not external and mission["state"] == states.EXECUTING:
                self._set_state(unit, mission, states.REVOKED)
            elif mission["state"] in {states.AUTHORIZED, states.AWAITING_APPROVAL, states.PLANNED, states.CREATED}:
                target = states.REVOKED if mission["state"] == states.AUTHORIZED else states.CANCELLED
                self._set_state(unit, mission, target)
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        self._arm_stop(mission_id, "revoked")
        return self.get(user, mission_id)

    def recover(self) -> list[str]:
        """Reconcile missions left executing by a dead process. Does not claim success."""
        changed: list[str] = []
        unit = Unit()
        try:
            rows = unit.conn.execute(
                "SELECT id, state FROM sovereign_missions WHERE state=?",
                (states.EXECUTING,),
            ).fetchall()
            for row in rows:
                steps = unit.conn.execute(
                    "SELECT intent_json, effect_started, outcome_json FROM sovereign_steps WHERE mission_id=?",
                    (row["id"],),
                ).fetchall()
                if any(step["outcome_json"] is None and step["effect_started"] for step in steps):
                    new = states.OUTCOME_UNKNOWN
                elif any(step["outcome_json"] is None and step["intent_json"] for step in steps):
                    new = states.INTERRUPTED_UNKNOWN
                else:
                    continue
                states.transition(row["state"], new)
                unit.conn.execute(
                    "UPDATE sovereign_missions SET state=?, updated_at=? WHERE id=?",
                    (new, now_iso(), row["id"]),
                )
                changed.append(row["id"])
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        return changed

    def get(self, user: User, mission_id: str) -> dict:
        unit = Unit()
        try:
            mission = self._owned(unit, user, mission_id)
            steps = unit.conn.execute(
                "SELECT id, position, tool, risk, approval_id, effect_started, outcome_json FROM sovereign_steps WHERE mission_id=? ORDER BY position",
                (mission_id,),
            ).fetchall()
            claim = self._claim(unit, mission)
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        return {
            "id": mission["id"],
            "state": mission["state"],
            "objective": mission["objective"],
            "owner_user_id": mission["owner_user_id"],
            "cancel_requested": bool(mission["cancel_requested"]),
            "revoked": bool(mission["revoked"]),
            "claim": claim,
            "steps": [
                {
                    "id": step["id"],
                    "position": step["position"],
                    "tool": step["tool"],
                    "risk": step["risk"],
                    "approved": bool(step["approval_id"]),
                    "effect_started": bool(step["effect_started"]),
                    "has_outcome": step["outcome_json"] is not None,
                }
                for step in steps
            ],
        }

    def evidence(self, user: User, mission_id: str) -> dict:
        unit = Unit()
        try:
            mission = self._owned(unit, user, mission_id)
            intact = self._intact(unit, mission)
            rows = []
            if intact:
                rows = unit.conn.execute(
                    "SELECT id, step_id, record_json, record_sha256 FROM sovereign_evidence WHERE mission_id=? ORDER BY created_at",
                    (mission_id,),
                ).fetchall()
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        return {
            "integrity": "intact" if intact else "tampered",
            "records": [json.loads(row["record_json"]) for row in rows],
        }

    def reported(self, user: User, mission_id: str) -> dict:
        body = self.get(user, mission_id)
        return {"mission_id": body["id"], "state": body["state"], "claim": body["claim"]}

    def _prepare(self, user: User, mission_id: str, step_id: str, now: datetime) -> dict:
        unit = Unit()
        try:
            mission = self._owned(unit, user, mission_id)
            if mission["revoked"]:
                raise MissionError("revoked")
            if mission["state"] in {states.OUTCOME_UNKNOWN, states.INTERRUPTED_UNKNOWN}:
                raise MissionError("duplicate_effect_refused")
            if mission["cancel_requested"] and mission["state"] != states.EXECUTING:
                raise MissionError("cancelled")
            step = self._step(unit, mission_id, step_id)
            if step["outcome_json"]:
                receipt = self._claim(unit, mission)
                unit.commit()
                return {"receipt": {"mission_id": mission_id, "state": mission["state"], "claim": receipt, "replayed": True}}
            if step["intent_json"]:
                raise MissionError("duplicate_effect_refused")
            if mission["state"] != states.AUTHORIZED:
                raise MissionError("not_authorized")
            approval = unit.conn.execute("SELECT * FROM sovereign_approvals WHERE id=?", (step["approval_id"],)).fetchone()
            if approval is None or approval["user_id"] != user.id or approval["mission_id"] != mission_id or approval["step_id"] != step_id:
                raise MissionError("approval_refused")
            if approval["consumed_at"] is not None:
                raise MissionError("approval_replay_refused")
            if approval["expires_at"] <= now_iso(now):
                raise MissionError("approval_expired")
            if approval["tool"] != step["tool"] or approval["destination"] != _destination(step):
                raise MissionError("approval_refused")
            intent = {"tool": step["tool"], "destination_sha256": digest({"destination": approval["destination"]}), "at": now_iso(now)}
            unit.conn.execute(
                "UPDATE sovereign_approvals SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
                (now_iso(now), approval["id"]),
            )
            if unit.conn.execute("SELECT changes() AS n").fetchone()["n"] != 1:
                raise MissionError("approval_replay_refused")
            unit.conn.execute("UPDATE sovereign_steps SET intent_json=? WHERE id=?", (canonical(intent), step_id))
            self._set_state(unit, mission, states.EXECUTING)
            unit.commit()
            return {"mission": dict(mission), "step": dict(step)}
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()

    def _mark_started(self, mission_id: str, step_id: str) -> None:
        unit = Unit()
        try:
            mission = unit.conn.execute("SELECT * FROM sovereign_missions WHERE id=?", (mission_id,)).fetchone()
            if mission["cancel_requested"] or mission["revoked"]:
                if not mission["revoked"]:
                    self._set_state(unit, mission, states.CANCELLED)
                else:
                    self._set_state(unit, mission, states.REVOKED)
                unit.commit()
                raise MissionError("revoked" if mission["revoked"] else "cancelled")
            unit.conn.execute("UPDATE sovereign_steps SET effect_started=1 WHERE id=?", (step_id,))
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()

    def _execute(self, user: User, mission: dict, step: sqlite_step, now: datetime) -> dict:
        arguments = json.loads(step["arguments_json"])
        if step["tool"] == "local_marker":
            self._begin_external(mission["id"], step["id"])
            _refuse_if_stopped(mission["id"])
            return _run_marker(user.id, mission["id"], arguments)
        if step["tool"] == "browser":
            return _run_browser(
                self,
                user.id,
                mission["id"],
                step["id"],
                arguments,
                now,
            )
        raise MissionError("capability_unavailable")

    def _finish(self, user: User, mission_id: str, step_id: str, outcome: dict) -> None:
        if self.fail_outcome_write:
            raise MissionError("outcome_write_failed")
        record = {
            "mission_id": mission_id,
            "step_id": step_id,
            "tool": outcome["tool"],
            "completion": outcome["completion"],
            "matched": bool(outcome["matched"]),
            "detail": outcome.get("detail", ""),
            "witness": outcome.get("witness", ""),
            "authority": outcome.get("authority", ""),
            "actions": outcome.get("actions", []),
            "content_sha256": outcome.get("content_sha256"),
        }
        record_hash = digest(record)
        unit = Unit()
        try:
            mission = self._owned(unit, user, mission_id)
            unit.conn.execute(
                """
                INSERT INTO sovereign_evidence
                    (id, mission_id, step_id, owner_user_id, record_json, record_sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, mission_id, step_id, user.id, canonical(record), record_hash, now_iso()),
            )
            unit.conn.execute(
                "UPDATE sovereign_steps SET outcome_json=? WHERE id=? AND outcome_json IS NULL",
                (canonical(outcome), step_id),
            )
            aggregate = digest({"evidence": [record_hash]})
            stopped = mission["cancel_requested"] or mission["revoked"] or mission["state"] != states.EXECUTING
            if stopped:
                if mission["state"] == states.EXECUTING:
                    self._set_state(unit, mission, states.OUTCOME_UNKNOWN)
                unit.conn.execute(
                    "UPDATE sovereign_missions SET evidence_sha256=?, updated_at=? WHERE id=? AND evidence_sha256 IS NULL",
                    (aggregate, now_iso(), mission_id),
                )
                unit.commit()
                return
            if outcome["matched"] and outcome["completion"] == "verified" and outcome.get("witness") == "application_observed":
                self._set_state(unit, mission, states.VERIFYING)
                mission = self._owned(unit, user, mission_id)
                try:
                    states.transition(mission["state"], states.COMPLETED_VERIFIED, evidence_intact=True)
                except states.StateError as exc:
                    raise MissionError(exc.code) from exc
                unit.conn.execute(
                    "UPDATE sovereign_missions SET state=?, evidence_sha256=?, updated_at=? WHERE id=?",
                    (states.COMPLETED_VERIFIED, aggregate, now_iso(), mission_id),
                )
            else:
                self._set_state(unit, mission, states.VERIFYING)
                mission = self._owned(unit, user, mission_id)
                self._set_state(unit, mission, states.FAILED)
                unit.conn.execute(
                    "UPDATE sovereign_missions SET evidence_sha256=?, updated_at=? WHERE id=?",
                    (aggregate, now_iso(), mission_id),
                )
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()

    def _begin_external(self, mission_id: str, step_id: str) -> None:
        """Mark the external attempt, then refuse if stop won the race.

        The flag is committed before the call. A crash after this point stays
        unknown. A stop that lands before the call does not become success.
        """
        unit = Unit()
        refusal = None
        try:
            mission = unit.conn.execute("SELECT * FROM sovereign_missions WHERE id=?", (mission_id,)).fetchone()
            if mission is None:
                raise MissionError("mission_not_found")
            if mission["revoked"] or mission["state"] == states.REVOKED:
                if mission["state"] == states.EXECUTING:
                    self._set_state(unit, mission, states.REVOKED)
                refusal = "revoked"
            elif mission["cancel_requested"] or mission["state"] != states.EXECUTING:
                if mission["state"] == states.EXECUTING:
                    self._set_state(unit, mission, states.CANCELLED)
                refusal = "cancelled"
            else:
                unit.conn.execute(
                    """
                    UPDATE sovereign_steps SET effect_started=1
                    WHERE id=? AND effect_started=0 AND outcome_json IS NULL
                      AND EXISTS (
                        SELECT 1 FROM sovereign_missions
                        WHERE id=? AND state=? AND cancel_requested=0 AND revoked=0
                      )
                    """,
                    (step_id, mission_id, states.EXECUTING),
                )
                if unit.conn.execute("SELECT changes() AS n").fetchone()["n"] != 1:
                    raise MissionError("duplicate_effect_refused")
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()
        if refusal:
            raise MissionError(refusal)
        code = _durable_stop(mission_id)
        if code:
            raise MissionError(code)

    def _settle(self, mission_id: str, step_id: str, code: str) -> None:
        unit = Unit()
        try:
            mission = unit.conn.execute("SELECT * FROM sovereign_missions WHERE id=?", (mission_id,)).fetchone()
            if mission is None or mission["state"] != states.EXECUTING:
                unit.commit()
                return
            step = unit.conn.execute(
                "SELECT effect_started FROM sovereign_steps WHERE id=?",
                (step_id,),
            ).fetchone()
            started = bool(step["effect_started"]) if step is not None else False
            if mission["revoked"] or mission["state"] == states.REVOKED:
                new = states.OUTCOME_UNKNOWN if started else states.REVOKED
            elif mission["cancel_requested"] or mission["state"] == states.CANCELLED:
                new = states.OUTCOME_UNKNOWN if started else states.CANCELLED
            elif code in {"cancelled", "revoked"}:
                unit.commit()
                return
            elif code in {"browser_dead", "browser_closed", "execution_interrupted"}:
                new = states.INTERRUPTED_UNKNOWN
            else:
                new = states.FAILED
            completion = "unknown" if new in {states.OUTCOME_UNKNOWN, states.INTERRUPTED_UNKNOWN} else "failed"
            outcome = {"tool": "unknown", "completion": completion, "matched": False, "detail": code, "witness": "none"}
            unit.conn.execute(
                "UPDATE sovereign_steps SET outcome_json=? WHERE id=? AND outcome_json IS NULL",
                (canonical(outcome), step_id),
            )
            self._set_state(unit, mission, new)
            unit.commit()
        except Exception:
            unit.rollback()
            raise
        finally:
            unit.close()

    def _owned(self, unit: Unit, user: User, mission_id: str):
        row = unit.conn.execute("SELECT * FROM sovereign_missions WHERE id=?", (mission_id,)).fetchone()
        if row is None:
            raise MissionError("mission_not_found")
        if row["owner_user_id"] != user.id or row["tenant_id"] != user.id:
            raise MissionError("access_denied")
        return row

    def _require_owner(
        self,
        unit: Unit,
        user: User,
        mission_id: str,
        *,
        cancel_requested: int | None = None,
        revoked: int | None = None,
    ):
        """Record this user's authority on the owned row before the caller commits."""
        mission = self._owned(unit, user, mission_id)
        if (cancel_requested is None) == (revoked is None):
            raise MissionError("access_denied")
        if cancel_requested is not None:
            unit.conn.execute(
                """
                UPDATE sovereign_missions
                SET cancel_requested=?, updated_at=?
                WHERE id=? AND owner_user_id=? AND tenant_id=?
                """,
                (cancel_requested, now_iso(), mission_id, user.id, user.id),
            )
        else:
            unit.conn.execute(
                """
                UPDATE sovereign_missions
                SET revoked=?, updated_at=?
                WHERE id=? AND owner_user_id=? AND tenant_id=?
                """,
                (revoked, now_iso(), mission_id, user.id, user.id),
            )
        if unit.conn.execute("SELECT changes() AS n").fetchone()["n"] != 1:
            raise MissionError("access_denied")
        return mission

    def _step_effects(self, unit: Unit, mission_id: str):
        return unit.conn.execute(
            "SELECT effect_started, outcome_json FROM sovereign_steps WHERE mission_id=?",
            (mission_id,),
        ).fetchall()

    def _arm_stop(self, mission_id: str, code: str) -> None:
        _signal_stop(mission_id, code)
        _cancel_live(mission_id)

    def _step(self, unit: Unit, mission_id: str, step_id: str):
        row = unit.conn.execute(
            "SELECT * FROM sovereign_steps WHERE id=? AND mission_id=?",
            (step_id, mission_id),
        ).fetchone()
        if row is None:
            raise MissionError("step_not_found")
        return row

    def _set_state(self, unit: Unit, mission, new: str) -> None:
        try:
            states.transition(mission["state"], new)
        except states.StateError as exc:
            raise MissionError(exc.code) from exc
        unit.conn.execute(
            "UPDATE sovereign_missions SET state=?, updated_at=? WHERE id=?",
            (new, now_iso(), mission["id"]),
        )

    def _intact(self, unit: Unit, mission) -> bool:
        rows = unit.conn.execute(
            "SELECT record_json, record_sha256 FROM sovereign_evidence WHERE mission_id=? ORDER BY created_at",
            (mission["id"],),
        ).fetchall()
        hashes = []
        for row in rows:
            if digest(json.loads(row["record_json"])) != row["record_sha256"]:
                return False
            hashes.append(row["record_sha256"])
        if mission["evidence_sha256"] is None:
            return not hashes
        return mission["evidence_sha256"] == digest({"evidence": hashes})

    def _claim(self, unit: Unit, mission) -> str:
        if not self._intact(unit, mission):
            return "withheld"
        state = mission["state"]
        if state == states.COMPLETED_VERIFIED:
            return "verified"
        if state in {states.INTERRUPTED_UNKNOWN, states.OUTCOME_UNKNOWN}:
            return "unknown"
        if state == states.FAILED:
            return "failed"
        if state in {states.CANCELLED, states.REVOKED}:
            return "refused"
        if state == states.EXECUTING:
            return "authorized_not_performed" if not mission["cancel_requested"] else "unknown"
        return "authorized_not_performed"


def _classify(step: dict, index: int) -> dict:
    if not isinstance(step, dict):
        raise MissionError("plan_refused")
    tool = step.get("tool")
    if tool not in _TOOLS:
        raise MissionError("capability_unavailable")
    arguments = step.get("arguments")
    if not isinstance(arguments, dict):
        raise MissionError("plan_refused")
    if tool == "browser":
        _destination_of_browser(arguments)
        actions = arguments.get("actions")
        if not isinstance(actions, list) or not actions or not set(actions) <= _BROWSER_ACTIONS:
            raise MissionError("action_unqualified")
        if "click" in actions or "fill" in actions:
            selector = arguments.get("selector")
            if not isinstance(selector, str) or not selector.startswith("#"):
                raise MissionError("plan_refused")
        expect = arguments.get("expect")
        if not isinstance(expect, str) or not expect or len(expect) > 64 or "\n" in expect:
            raise MissionError("plan_refused")
        risk = "local_fixture"
    else:
        name = arguments.get("name", "marker.txt")
        if not isinstance(name, str) or name != Path(name).name or name in {".", ".."}:
            raise MissionError("destination_refused")
        risk = "local_fixture"
    if step.get("risk") not in {None, risk}:
        raise MissionError("risk_mismatch")
    return {"id": uuid.uuid4().hex, "position": index, "tool": tool, "risk": risk, "arguments": arguments}


def _destination(step) -> str:
    arguments = json.loads(step["arguments_json"])
    if step["tool"] == "browser":
        return _destination_of_browser(arguments)
    return arguments.get("name", "marker.txt")


def _destination_of_browser(arguments: dict) -> str:
    url = arguments.get("url")
    if not isinstance(url, str) or len(url) > 2048:
        raise MissionError("destination_refused")
    parts = urlsplit(url)
    if parts.username or parts.password or parts.scheme != "http":
        raise MissionError("public_browser_unqualified")
    host = (parts.hostname or "").casefold()
    if host not in {"127.0.0.1", "::1"} or parts.port is None:
        raise MissionError("public_browser_unqualified")
    return f"{host}:{parts.port}"


def _workspace(user_id: str, mission_id: str) -> Path:
    path = auth_db.AUTH_DB.parent / "sovereign" / user_id / mission_id
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    return path


def _run_marker(user_id: str, mission_id: str, arguments: dict) -> dict:
    name = arguments.get("name", "marker.txt")
    text = arguments.get("text", "marked")
    if not isinstance(text, str) or len(text) > 64 or "\n" in text:
        raise MissionError("arguments_refused")
    target = _workspace(user_id, mission_id) / name
    if target.exists() or target.is_symlink():
        raise MissionError("duplicate_effect")
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)
    return {
        "tool": "local_marker",
        "completion": "verified",
        "matched": True,
        "detail": "",
        "witness": "application_observed",
        "content_sha256": digest({"text": text}),
    }


def _run_browser(service: SovereignMission, user_id: str, mission_id: str, step_id: str, arguments: dict, now: datetime) -> dict:
    from orca.browser_engine.engine import BrowserEngine, BrowserError, issue_grant

    endpoint = _destination_of_browser(arguments)
    actions = tuple(arguments["actions"])
    grant_actions = tuple(dict.fromkeys((*actions, "navigate", "read")))
    try:
        grant = issue_grant(
            user_id=user_id,
            mission_id=mission_id,
            allow_loopback=(endpoint,),
            actions=grant_actions,
            ttl_seconds=60,
            now=now,
        )
    except Exception as exc:
        raise MissionError(getattr(exc, "code", "grant_refused")) from exc
    engine = BrowserEngine(_workspace(user_id, mission_id) / "browser", grant)
    with _LIVE_LOCK:
        _LIVE[mission_id] = engine
    try:
        _refuse_if_stopped(mission_id)
        engine.start(now=now)
        _refuse_if_stopped(mission_id)
        service._begin_external(mission_id, step_id)
        _refuse_if_stopped(mission_id)
        engine.navigate(arguments["url"], now=now)
        if "click" in actions:
            _refuse_if_stopped(mission_id)
            engine.click(arguments["selector"], now=now)
        if "fill" in actions:
            _refuse_if_stopped(mission_id)
            engine.fill(arguments["selector"], arguments.get("text", ""), now=now)
        if "scroll" in actions:
            _refuse_if_stopped(mission_id)
            engine.scroll(int(arguments.get("delta_y", 200)), now=now)
        _refuse_if_stopped(mission_id)
        observed = engine.read_text(now=now)
        deadline = time.monotonic() + 2
        while arguments["expect"] not in observed["text"] and time.monotonic() < deadline:
            if _durable_stop(mission_id):
                break
            time.sleep(0.05)
            observed = engine.read_text(now=now)
        if "screenshot" in actions:
            _refuse_if_stopped(mission_id)
            engine.screenshot(now=now)
        if observed.get("authority") != "page_content_not_authority":
            raise MissionError("page_authority_refused")
        matched = arguments["expect"] in observed["text"] and _durable_stop(mission_id) is None
        content_hash = digest({"text": observed["text"]})
        for record in engine.evidence:
            encoded = json.dumps(record)
            if arguments["expect"] in encoded or "grant yourself" in encoded:
                raise MissionError("evidence_leak")
        return {
            "tool": "browser",
            "completion": "verified" if matched else "failed",
            "matched": matched,
            "detail": "" if matched else "expectation_unmet",
            "witness": "application_observed",
            "authority": "page_content_not_authority",
            "actions": list(actions),
            "content_sha256": content_hash,
        }
    except BrowserError as exc:
        raise MissionError(exc.code) from exc
    finally:
        with _LIVE_LOCK:
            _LIVE.pop(mission_id, None)
        engine.close()


def _signal_stop(mission_id: str, code: str) -> None:
    with _LIVE_LOCK:
        _STOP[mission_id] = code


def _durable_stop(mission_id: str) -> str | None:
    """Return a stop code only when the committed mission row authorizes it.

    A process-local ``_STOP`` entry is not authority. Cancel and revoke write
    that entry only after the owner update commits.
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT state, cancel_requested, revoked FROM sovereign_missions WHERE id=?",
            (mission_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["state"] in {states.COMPLETED_VERIFIED, states.FAILED}:
        return None
    if row["revoked"] or row["state"] == states.REVOKED:
        return "revoked"
    if row["cancel_requested"] or row["state"] in {
        states.CANCELLED,
        states.OUTCOME_UNKNOWN,
        states.INTERRUPTED_UNKNOWN,
    }:
        return "cancelled"
    return None


def _refuse_if_stopped(mission_id: str) -> None:
    code = _durable_stop(mission_id)
    if code:
        raise MissionError(code)


def _cancel_live(mission_id: str) -> None:
    with _LIVE_LOCK:
        engine = _LIVE.get(mission_id)
    if engine is not None:
        engine.cancel()


# sqlite3.Row is the step type at runtime. The alias keeps the signature readable.
sqlite_step = object
