"""Restricted tests, patch evidence, durability, and inactive improvement contracts."""
from __future__ import annotations

import hashlib
import multiprocessing
import os
import subprocess
from pathlib import Path

import pytest

from orca.pretrain_foundation.containment import EffectLedger
from orca.pretrain_foundation.improvement import CONTRACT_VERSION, improvement_contracts, record_failure
from orca.pretrain_foundation.incident_engine import IncidentEngine, IncidentError, IncidentJournalError
from orca.pretrain_foundation.patch_evidence import (
    compare_observed_executions,
    observe_execution,
    seal_patch_evidence,
    verify_seal,
)
from orca.pretrain_foundation.restricted_runner import ContainmentError, containment_status, run_authorized_pytest
from orca.pretrain_foundation.role_registry import load_roles
from orca.pretrain_foundation.unattended import PATCH_GENERATION, UnattendedRepair


def _passing_workspace(root: Path) -> str:
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    return "tests/test_ok.py"


def test_containment_is_available_and_drops_host_access(tmp_path):
    status = containment_status()
    if not status["available"]:
        assert status["executed"] is False
        assert status["gap"]
        with pytest.raises(ContainmentError):
            run_authorized_pytest(tmp_path, _passing_workspace(tmp_path))
        return
    assert status["available"] is True
    relative = _passing_workspace(tmp_path)
    (tmp_path / "tests" / "test_ok.py").write_text(
        "import os, urllib.request\n"
        "def test_closed():\n"
        "    assert 'ORNEUR_SECRET' not in os.environ\n"
        "    try:\n"
        "        urllib.request.urlopen('http://127.0.0.1:9', timeout=1)\n"
        "        raise AssertionError('network opened')\n"
        "    except Exception as exc:\n"
        "        assert type(exc).__name__ != 'AssertionError'\n"
        "    missing = False\n"
        "    try:\n"
        "        open('/workspace/README.md').read(1)\n"
        "    except FileNotFoundError:\n"
        "        missing = True\n"
        "    assert missing\n"
    )
    os.environ["ORNEUR_SECRET"] = "should-not-leak"
    try:
        result = run_authorized_pytest(tmp_path, relative, wall_seconds=20)
    finally:
        os.environ.pop("ORNEUR_SECRET", None)
    assert result["exit_code"] == 0
    assert result["containment"] == "user-namespace-chroot"


def test_unavailable_containment_starts_no_pytest(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "orca.pretrain_foundation.restricted_runner.containment_status",
        lambda: {"available": False, "gap": "user namespace refused", "executed": False},
    )
    with pytest.raises(ContainmentError, match="user namespace refused"):
        run_authorized_pytest(tmp_path, _passing_workspace(tmp_path))


def test_command_substitution_symlink_and_timeout_do_not_escape(tmp_path):
    marker = tmp_path / "escaped"
    with pytest.raises(ContainmentError):
        run_authorized_pytest(tmp_path, "python3 -c 'open(\"/tmp/x\",\"w\")'")
    assert not marker.exists()
    workspace = tmp_path / "tree"
    workspace.mkdir()
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_link.py").symlink_to("/etc/passwd")
    with pytest.raises(ContainmentError, match="symlink"):
        run_authorized_pytest(workspace, "tests/test_link.py")
    sleep_root = tmp_path / "sleep"
    relative = _passing_workspace(sleep_root)
    (sleep_root / "tests" / "test_ok.py").write_text("import time\ndef test_sleep():\n    time.sleep(30)\n")
    if not containment_status()["available"]:
        with pytest.raises(ContainmentError):
            run_authorized_pytest(sleep_root, relative, wall_seconds=2, cpu_seconds=1)
        return
    result = run_authorized_pytest(sleep_root, relative, wall_seconds=2, cpu_seconds=1)
    assert result["exit_code"] != 0


def test_patch_evidence_rejects_a_rewritten_test_and_an_unapplied_patch():
    command = ["python3", "-m", "pytest", "-q", "tests/test_check.py"]
    bad = "a" * 40
    patched = "b" * 40
    test_digest = "c" * 64
    patch_digest = "d" * 64
    accepted = seal_patch_evidence(
        known_bad_commit=bad,
        test_identity="tests/test_check.py",
        test_digest=test_digest,
        failing_exit=1,
        failing_test_digest=test_digest,
        failing_command=command,
        patch_digest=patch_digest,
        patched_commit=patched,
        build_id="jail-1",
        passing_exit=0,
        passing_test_digest=test_digest,
        passing_command=command,
        applied_patch_digest=patch_digest,
    )
    assert accepted["accepted"] is True
    assert accepted["signature"] is False
    assert accepted["repair_proof"] is False
    assert verify_seal(accepted["evidence"]) is True
    changed = dict(accepted["evidence"])
    changed["passing_exit"] = 1
    assert verify_seal(changed) is False
    rewritten = seal_patch_evidence(
        known_bad_commit=bad,
        test_identity="tests/test_check.py",
        test_digest=test_digest,
        failing_exit=1,
        failing_test_digest=test_digest,
        failing_command=command,
        patch_digest=patch_digest,
        patched_commit=patched,
        build_id="jail-1",
        passing_exit=0,
        passing_test_digest="e" * 64,
        passing_command=command,
        applied_patch_digest=patch_digest,
    )
    assert rewritten["accepted"] is False
    unrelated = seal_patch_evidence(
        known_bad_commit=bad,
        test_identity="tests/test_check.py",
        test_digest=test_digest,
        failing_exit=1,
        failing_test_digest=test_digest,
        failing_command=command,
        patch_digest=patch_digest,
        patched_commit=patched,
        build_id="jail-1",
        passing_exit=0,
        passing_test_digest=test_digest,
        passing_command=["python3", "-m", "pytest", "-q", "tests/other.py"],
        applied_patch_digest=patch_digest,
    )
    assert unrelated["accepted"] is False
    missing = seal_patch_evidence(
        known_bad_commit=bad,
        test_identity="tests/test_check.py",
        test_digest=test_digest,
        failing_exit=1,
        failing_test_digest=test_digest,
        failing_command=command,
        patch_digest=patch_digest,
        patched_commit=patched,
        build_id="jail-1",
        passing_exit=0,
        passing_test_digest=test_digest,
        passing_command=command,
        applied_patch_digest="f" * 64,
    )
    assert any("not applied" in reason for reason in missing["reasons"])


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=repair-test@example.com", "-c", "user.name=repair-test", *args],
        check=True,
        capture_output=True,
    )


def test_self_supplied_execution_is_not_repair_proof(tmp_path):
    refused = compare_observed_executions(
        tmp_path,
        {"exit_code": 1, "repair_proof": True, "test_digest": "a" * 64, "source_digest": "b" * 64},
        {"exit_code": 0, "repair_proof": True, "test_digest": "a" * 64, "source_digest": "c" * 64},
    )
    assert refused["accepted"] is False
    assert refused["repair_proof"] is False
    assert refused["patch_generation"] == "NOT DEMONSTRATED"


def test_observed_execution_matches_git_and_is_not_repair_proof(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init")
    (repo / "app.py").write_text("VALUE = 0\n")
    test_body = "from pathlib import Path\n\ndef test_value():\n    assert 'VALUE = 1' in Path('/work/app.py').read_text()\n"
    (repo / "tests" / "test_value.py").write_text(test_body)
    _git(repo, "add", "app.py", "tests/test_value.py")
    _git(repo, "commit", "-m", "known bad")
    if not containment_status()["available"]:
        with pytest.raises(ContainmentError):
            observe_execution(repo, "tests/test_value.py", "app.py")
        return
    before = observe_execution(repo, "tests/test_value.py", "app.py")
    assert before["exit_code"] != 0
    assert before["repair_proof"] is False
    assert before["patch_generation"] == "NOT DEMONSTRATED"
    (repo / "app.py").write_text("VALUE = 1\n")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "source bytes changed")
    after = observe_execution(repo, "tests/test_value.py", "app.py")
    assert after["exit_code"] == 0
    assert after["head"] != before["head"]
    assert after["test_digest"] == before["test_digest"]
    assert after["source_digest"] != before["source_digest"]
    compared = compare_observed_executions(repo, before, after)
    assert compared["accepted"] is True
    assert compared["repair_proof"] is False
    assert compared["patch_generation"] == "NOT DEMONSTRATED"
    assert compared["signature"] is False
    marked = dict(after)
    marked["repair_proof"] = True
    assert compare_observed_executions(repo, before, marked)["accepted"] is False
    invented = dict(before)
    invented["source_digest"] = "d" * 64
    assert compare_observed_executions(repo, invented, after)["accepted"] is False
    (repo / "tests" / "test_other.py").write_text("def test_ok():\n    assert True\n")
    _git(repo, "add", "tests/test_other.py")
    _git(repo, "commit", "-m", "unrelated test")
    other = observe_execution(repo, "tests/test_other.py", "app.py")
    assert other["exit_code"] == 0
    unrelated = compare_observed_executions(repo, before, other)
    assert unrelated["accepted"] is False
    assert unrelated["repair_proof"] is False


def _detect_same(root: str, incident_id: str, queue) -> None:
    engine = IncidentEngine(Path(root), now=lambda: 1_700_000_000)
    row = engine.detect(
        incident_id=incident_id,
        source_commit="a" * 40,
        signal="same fault",
        fingerprint="same-fingerprint",
        owner_id="repair-agent",
        deadline_unix=1_700_003_600,
        budget_units=4,
        retry_limit=2,
    )
    queue.put((row["incident_id"], row["duplicate"]))


def _apply_effect(path: str, key: str, queue) -> None:
    EffectLedger(Path(path)).apply(key, "recorded")
    queue.put(key)


def test_two_processes_deduplicate_and_keep_both_effects(tmp_path):
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    root = tmp_path / "incident"
    first = ctx.Process(target=_detect_same, args=(str(root), "INC-1", queue))
    second = ctx.Process(target=_detect_same, args=(str(root), "INC-2", queue))
    first.start()
    second.start()
    first.join(10)
    second.join(10)
    assert first.exitcode == 0 and second.exitcode == 0
    rows = [queue.get(timeout=5), queue.get(timeout=5)]
    assert {item[0] for item in rows} == {"INC-1"} or {item[0] for item in rows} == {"INC-2"}
    assert sorted(item[1] for item in rows) == [False, True]
    reloaded = IncidentEngine(root, now=lambda: 1_700_000_000)
    assert len(reloaded._by_id) == 1
    effect = tmp_path / "effects.json"
    effect_queue = ctx.Queue()
    left = ctx.Process(target=_apply_effect, args=(str(effect), "left", effect_queue))
    right = ctx.Process(target=_apply_effect, args=(str(effect), "right", effect_queue))
    left.start()
    right.start()
    left.join(10)
    right.join(10)
    assert left.exitcode == 0 and right.exitcode == 0
    ledger = EffectLedger(effect)
    assert set(ledger._seen) == {"left", "right"}
    assert ledger.apply("left", "recorded")["exactly_once_across_hosts"] is False


def test_torn_tail_stays_closed_until_explicit_recovery(tmp_path):
    engine = IncidentEngine(tmp_path / "incident", now=lambda: 1_700_000_000)
    engine.detect(
        incident_id="INC-1",
        source_commit="a" * 40,
        signal="fault",
        fingerprint="one",
        owner_id="repair-agent",
        deadline_unix=1_700_003_600,
        budget_units=4,
        retry_limit=2,
    )
    engine.note("INC-1", actor_id="repair-agent", text="still diagnosing")
    journal = tmp_path / "incident" / "journal.jsonl"
    raw = journal.read_bytes()
    journal.write_bytes(raw[:-5])
    with pytest.raises(IncidentJournalError, match="torn"):
        IncidentEngine(tmp_path / "incident", now=lambda: 1_700_000_000)
    assert engine.journal.recover_torn_tail() == 1
    restored = IncidentEngine(tmp_path / "incident", now=lambda: 1_700_000_000)
    assert restored.build_report("INC-1")["lifecycle_state"] == "DETECTED"


def test_arbitrary_command_is_not_started(tmp_path):
    engine = IncidentEngine(tmp_path / "incident", now=lambda: 1_700_000_000)
    engine.detect(
        incident_id="INC-1",
        source_commit="a" * 40,
        signal="fault",
        fingerprint="one",
        owner_id="repair-agent",
        deadline_unix=1_700_003_600,
        budget_units=4,
        retry_limit=2,
    )
    marker = tmp_path / "marker"
    with pytest.raises(IncidentError, match="disabled"):
        engine.observe_command("INC-1", ["python3", "-c", f"open({str(marker)!r},'w').write('x')"], tmp_path)
    assert not marker.exists()


def test_unattended_poll_does_not_invent_a_patch(tmp_path):
    def detector():
        return {"fingerprint": "fallback-remains", "signal": "keyword fallback still answers", "source_commit": "c" * 40}

    repair = UnattendedRepair(tmp_path / "incident", detector, now=lambda: 1_700_000_000)
    first = repair.poll()
    second = repair.poll()
    assert first is not None and second is not None
    assert first["incident_id"] == second["incident_id"]
    assert second["duplicate"] is True
    assert first["patch_generation"] == PATCH_GENERATION
    investigated = repair.investigate(first["incident_id"], "def delete_doc():\n    return True\n")
    assert investigated["patch_text"] is None
    assert investigated["patch_generation"] == "NOT DEMONSTRATED"
    restarted = UnattendedRepair(tmp_path / "incident", detector, now=lambda: 1_700_000_000)
    again = restarted.poll()
    assert again["duplicate"] is True
    report = restarted.report(first["incident_id"])
    assert report["autonomous_patch"] is False
    assert report["production_authorization"] == "DENIED"
    assert report["patch_generation"] == "NOT DEMONSTRATED"


def test_every_role_has_an_inactive_improvement_contract(tmp_path):
    roles = load_roles()
    contracts = improvement_contracts()
    assert len(roles) == 100
    assert len(contracts) == 100
    assert len({row["role_id"] for row in contracts}) == 100
    assert {row["contract_version"] for row in contracts} == {CONTRACT_VERSION}
    assert {row["execution"] for row in contracts} == {"INACTIVE"}
    assert all(row["self_approval"] is False for row in contracts)
    recorded = record_failure(tmp_path / "genome.jsonl", role_id=contracts[0]["role_id"], detail="fixture mismatch")
    assert recorded["promoted"] is False
    assert recorded["execution"] == "INACTIVE"
    digest = hashlib.sha256((tmp_path / "genome.jsonl").read_bytes()).hexdigest()
    assert len(digest) == 64
