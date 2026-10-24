"""Incident lifecycle, durability, and refusal of self-approval."""
from __future__ import annotations

from pathlib import Path

import pytest

from orca.pretrain_foundation.incident_engine import STATES, IncidentEngine, IncidentError, IncidentJournalError
from orca.pretrain_foundation.model_monitor import PROBES, ModelMonitorError, diagnose, monitoring_contracts, request_rollback


def _engine(tmp_path, **clock):
    now = clock.get("now", lambda: 1_700_000_000)
    return IncidentEngine(tmp_path / "incident", now=now)


def _detect(engine, **overrides):
    fields = {
        "incident_id": "INC-1",
        "source_commit": "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a",
        "signal": "deleted attachment text is still retrievable",
        "fingerprint": "doc-delete-fallback",
        "owner_id": "repair-agent",
        "deadline_unix": 1_700_000_500,
        "budget_units": 16,
        "retry_limit": 2,
    }
    fields.update(overrides)
    return engine.detect(**fields)


def _reach_proposed(engine, workspace):
    _detect(engine)
    engine.transition(
        "INC-1",
        "REPRODUCED",
        actor_id="repair-agent",
        evidence={"repro_command": "python3 check.py", "observed_output": "secret still present"},
    )
    engine.transition(
        "INC-1",
        "DIAGNOSED",
        actor_id="repair-agent",
        evidence={"cause": "collection delete returned before the fallback file was purged"},
    )
    return engine.transition(
        "INC-1",
        "PATCH_PROPOSED",
        actor_id="repair-agent",
        evidence={
            "patch_text": "purge fallback after the collection delete\n",
            "changed_files": ["orca/docs/store.py"],
            "verified": True,
            "digest": "f" * 64,
        },
    )


def _pytest_case(workspace: Path, source: str) -> str:
    (workspace / "tests").mkdir(parents=True, exist_ok=True)
    (workspace / "tests" / "test_check.py").write_text(source)
    return "tests/test_check.py"


def test_lifecycle_requires_an_observed_command_and_refuses_self_approval(tmp_path):
    workspace = tmp_path / "iso"
    workspace.mkdir()
    (workspace / "app.py").write_text("VALUE = 0\n")
    relative = _pytest_case(workspace, "import app\n\ndef test_value():\n    assert app.VALUE == 1, 'secret still present'\n")
    engine = _engine(tmp_path)
    proposed = _reach_proposed(engine, workspace)
    assert proposed["state"] == "PATCH_PROPOSED"
    assert proposed["production_authorization"] == "DENIED"
    with pytest.raises(IncidentError, match="observed command"):
        engine.transition(
            "INC-1",
            "TESTED",
            actor_id="repair-agent",
            evidence={"exit_code": 0, "output": "ok", "verified": True, "recovered": True},
        )
    failed = engine.run_authorized_test("INC-1", workspace, relative)
    assert failed["exit_code"] != 0
    assert failed["containment"] == "user-namespace-chroot"
    held = engine.transition("INC-1", "TESTED", actor_id="repair-agent", evidence={"observation_id": failed["observation_id"]})
    assert held["advanced"] is False
    assert held["state"] == "PATCH_PROPOSED"
    assert held["test_failures"] == 1
    (workspace / "app.py").write_text("VALUE = 1\n")
    passed = engine.run_authorized_test("INC-1", workspace, relative)
    assert passed["exit_code"] == 0
    assert passed["test_digest"] == failed["test_digest"]
    tested = engine.transition("INC-1", "TESTED", actor_id="repair-agent", evidence={"observation_id": passed["observation_id"]})
    assert tested["state"] == "TESTED"
    with pytest.raises(IncidentError, match="author cannot verify"):
        engine.transition(
            "INC-1",
            "INDEPENDENTLY_VERIFIED",
            actor_id="repair-agent",
            evidence={"tested_observation_id": passed["observation_id"], "approved": True},
        )
    with pytest.raises(IncidentError, match="does not match"):
        engine.transition(
            "INC-1",
            "INDEPENDENTLY_VERIFIED",
            actor_id="reviewer-2",
            evidence={"tested_observation_id": "forged", "verified": True},
        )
    verified = engine.transition(
        "INC-1",
        "INDEPENDENTLY_VERIFIED",
        actor_id="reviewer-2",
        evidence={"tested_observation_id": passed["observation_id"]},
    )
    assert verified["state"] == "INDEPENDENTLY_VERIFIED"
    waiting = engine.transition(
        "INC-1",
        "AWAITING_AUTHORIZATION",
        actor_id="repair-agent",
        evidence={"request": "isolated rerun only", "approved": True, "production_authorization": "GRANTED"},
    )
    assert waiting["production_authorization"] == "DENIED"
    rerun = engine.run_authorized_test("INC-1", workspace, relative)
    with pytest.raises(IncidentError, match="isolated-test"):
        engine.transition(
            "INC-1",
            "SIMULATED_RECOVERY_VERIFIED",
            actor_id="repair-agent",
            evidence={"observation_id": rerun["observation_id"], "recovered": True},
        )
    simulated = engine.transition(
        "INC-1",
        "SIMULATED_RECOVERY_VERIFIED",
        actor_id="repair-agent",
        evidence={"observation_id": rerun["observation_id"], "environment": "isolated-test"},
    )
    assert simulated["state"] == "SIMULATED_RECOVERY_VERIFIED"
    engine.transition("INC-1", "REPORTED", actor_id="repair-agent", evidence={})
    report = engine.build_report("INC-1")
    assert report["recovery_result"] == "PATCH DEVELOPED AND TESTED"
    assert report["authorization_decision"] == "DENIED"
    assert "RECOVERY VERIFIED" not in report["recovery_result"]
    assert "PRODUCTION FIXED" not in report.values()
    assert report["independent_verification"]["reviewer_enrolled"] is False
    assert report["model_contracts"]["GENESIS"]["model_loaded"] is False
    assert report["patch_generator"] == "not an enrolled model backend"
    assert report["timestamps"]["zone"] == "Asia/Kolkata"
    assert list(STATES)[-1] == "REPORTED"


def test_presence_deadline_budget_cancel_and_duplicate_stay_fail_closed(tmp_path):
    clock = {"now": 1_700_000_000}
    engine = _engine(tmp_path, now=lambda: clock["now"])
    opened = _detect(engine, budget_units=2, retry_limit=1)
    assert opened["duplicate"] is False
    again = _detect(engine, incident_id="INC-2")
    assert again["duplicate"] is True
    assert again["incident_id"] == "INC-1"
    engine.set_presence(founder_online=False, developer_online=False)
    noted = engine.note("INC-1", actor_id="repair-agent", text="founder and developer are offline; diagnosis continues")
    assert noted["state"] == "DETECTED"
    assert engine.authorization("INC-1")["decision"] == "DENIED"
    engine.transition(
        "INC-1",
        "REPRODUCED",
        actor_id="repair-agent",
        evidence={"repro_command": "pytest", "observed_output": "still present"},
    )
    with pytest.raises(IncidentError, match="budget"):
        engine.transition("INC-1", "DIAGNOSED", actor_id="repair-agent", evidence={"cause": "late"})
    assert engine.note("INC-1", actor_id="repair-agent", text="budget blocks the repair; the note remains")["state"] == "REPRODUCED"
    clock["now"] = 1_700_000_500
    broad = IncidentEngine(tmp_path / "other", now=lambda: clock["now"])
    _detect(broad, deadline_unix=1_700_000_400)
    with pytest.raises(IncidentError, match="deadline"):
        broad.transition("INC-1", "REPRODUCED", actor_id="repair-agent", evidence={"repro_command": "pytest", "observed_output": "x"})
    assert broad.note("INC-1", actor_id="repair-agent", text="deadline blocks repair only")["state"] == "DETECTED"
    broad.cancel("INC-1", actor_id="repair-agent", reason="operator stop")
    with pytest.raises(IncidentError, match="cancelled"):
        broad.transition("INC-1", "REPRODUCED", actor_id="repair-agent", evidence={"repro_command": "pytest", "observed_output": "x"})
    assert broad.note("INC-1", actor_id="repair-agent", text="cancelled work can still be described")["cancelled"] is True


def test_restart_mutation_competing_patches_and_notification(tmp_path):
    engine = _engine(tmp_path)
    _reach_proposed(engine, tmp_path)
    engine.transition(
        "INC-1",
        "PATCH_PROPOSED",
        actor_id="repair-agent",
        evidence={"patch_text": "a different and contradictory edit\n", "changed_files": ["orca/docs/store.py"]},
    )
    workspace = tmp_path / "iso"
    workspace.mkdir()
    relative = _pytest_case(workspace, "def test_ok():\n    assert True\n")
    passed = engine.run_authorized_test("INC-1", workspace, relative)
    engine.transition("INC-1", "TESTED", actor_id="repair-agent", evidence={"observation_id": passed["observation_id"]})
    with pytest.raises(IncidentError, match="contradict"):
        engine.transition(
            "INC-1",
            "INDEPENDENTLY_VERIFIED",
            actor_id="reviewer-2",
            evidence={"tested_observation_id": passed["observation_id"]},
        )
    reloaded = IncidentEngine(tmp_path / "incident", now=lambda: 1_700_000_000)
    assert reloaded.build_report("INC-1")["lifecycle_state"] == "TESTED"
    assert reloaded.build_report("INC-1")["notification_delivery"] == "NOT_ATTEMPTED"
    failed = reloaded.notify("INC-1", lambda _report: (_ for _ in ()).throw(ConnectionError("network down")))
    assert failed["delivered"] is False
    assert failed["state"] == "TESTED"
    sent = reloaded.notify("INC-1", lambda _report: None)
    assert sent["delivered"] is True
    replay = reloaded.notify("INC-1", lambda _report: (_ for _ in ()).throw(AssertionError("sender must not be called again")))
    assert replay["duplicate"] is True
    journal = (tmp_path / "incident" / "journal.jsonl").read_bytes()
    (tmp_path / "incident" / "journal.jsonl").write_bytes(journal[:-2])
    with pytest.raises(IncidentJournalError, match="torn"):
        IncidentEngine(tmp_path / "incident", now=lambda: 1_700_000_000)
    (tmp_path / "incident" / "journal.jsonl").write_bytes(journal)
    flipped = bytearray(journal)
    flipped[20] = flipped[20] ^ 1
    (tmp_path / "incident" / "journal.jsonl").write_bytes(flipped)
    with pytest.raises(IncidentJournalError):
        IncidentEngine(tmp_path / "incident", now=lambda: 1_700_000_000)


def test_notification_interruption_does_not_send_twice(tmp_path):
    engine = _engine(tmp_path)
    _detect(engine)
    engine.journal.append({
        "kind": "notification",
        "incident_id": "INC-1",
        "phase": "started",
        "unix": 1_700_000_000,
    })
    engine._reload()
    calls = {"n": 0}

    def sender(_report):
        calls["n"] += 1

    result = engine.notify("INC-1", sender)
    assert result["delivered"] is False
    assert calls["n"] == 0
    assert "unknown" in result["reason"]


def test_model_contracts_do_not_claim_a_loaded_model():
    contracts = monitoring_contracts()
    assert set(contracts) == {"GENESIS", "NOVUS", "AETERNUM"}
    assert contracts["GENESIS"]["registry_status"] == "INTERFACE_ONLY"
    assert contracts["NOVUS"]["registry_status"] == "NOT_AVAILABLE"
    assert contracts["AETERNUM"]["registry_status"] == "NOT_AVAILABLE"
    for record in contracts.values():
        assert record["model_loaded"] is False
        assert record["repaired"] is False
        assert record["native_test_executed"] is False
        assert record["checkpoint_digest"] is None
        assert set(record["probes"]) == set(PROBES)
        assert set(record["probes"].values()) == {"NOT_OBSERVED"}
    for family in contracts:
        diagnosis = diagnose(family)
        assert diagnosis["model_loaded"] is False
        assert diagnosis["trained"] is False
        assert diagnosis["rollback"] == "REFUSED"
        with pytest.raises(ModelMonitorError, match="rollback refused"):
            request_rollback(family, "abc")
