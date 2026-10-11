"""Workstream G #15 (register TRAIN-2): `python -m orca.train.dryrun` prints one machine-readable SYNTHETIC result and proves the authorization
locks and TRAINING_AUTHORIZATION.json are untouched. The committed sample result is checked for consistency, not trusted."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import orca.train.authorization as A
from orca.train.dryrun import cli
from orca.train.dryrun.canon import file_sha256, hash_obj

REPO = Path(__file__).resolve().parent.parent
SAMPLE = REPO / "docs/orneur/status/trainprep/dryrun_result.json"


def _tree_clean() -> bool:
    return subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"], capture_output=True, text=True).stdout.strip() == ""


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "orca.train.dryrun", *args], cwd=REPO, capture_output=True, text=True, timeout=300)


def _auth_hashes():
    return {p.name: file_sha256(p) for p in sorted((REPO / "docs/orneur/authorization").glob("*.json"))}


def test_cli_is_fail_closed_on_a_dirty_tree_and_fully_green_on_a_clean_one():
    before = _auth_hashes()
    p = _cli()
    out = json.loads(p.stdout)
    assert out["synthetic"] is True and out["schema"] == cli.RESULT_SCHEMA
    assert _auth_hashes() == before                                                   # the CLI never touches an authorization file
    auth = out["authorization"]
    assert auth["authorization_files_byte_identical"] is True and auth["locks_still_false"] is True
    assert all(v is False for v in auth["locks_after"]["functions"].values()) and auth["locks_after"]["training_authorization_status"] == "NOT_AUTHORIZED"
    if _tree_clean():
        assert p.returncode == 0 and out["status"] == "OK"
        assert out["resume_equivalent"] is True and out["gate_probe"]["authorized"] is False and "NOT_AUTHORIZED" in out["gate_probe"]["reasons"]
        assert out["lock"]["structure_ok"] is True and out["env_manifest"]["container"] == {"image_digest": None, "status": "NOT_BUILT"}
        assert out["runs"]["zero_budget"]["status"] == "REFUSED" and out["runs"]["interrupted_first_segment"]["reason"] == "STEP_CAP"
        assert out["runs"]["uninterrupted"]["status"] == "FINISHED" and out["sentinel"]["forbidden_modules_loaded"] == []
        assert all(v["ledger_ok"] and v["manifests_ok"] and v["records"] >= 2 and v["manifests"] >= 1 for v in out["verification"].values())     # never vacuous
        assert out["verification"]["interrupted"]["manifests"] == 2 and out["verification"]["zero_budget"]["records"] == 2
        p2 = _cli()
        assert json.loads(p2.stdout)["result_sha256"] == out["result_sha256"]         # deterministic
    else:
        assert p.returncode == 3 and out["status"] == "REFUSED_BINDING"
        assert "DIRTY_WORKING_TREE" in out["reasons"]


def test_cli_with_a_zero_cap_runs_nothing_and_still_reports_cleanly():
    if not _tree_clean():
        pytest.skip("the CLI refuses to bind a dirty tree (covered above); zero-cap behaviour is covered at library level in test_trainprep_budget.py")
    p = _cli("--max-steps", "0")
    out = json.loads(p.stdout)
    assert p.returncode == 0 and out["status"] == "OK_BUDGET_LIMITED" and out["resume_equivalent"] is None
    assert out["runs"]["uninterrupted"]["status"] == "REFUSED" and out["runs"]["uninterrupted"]["steps"] == 0 and "interrupted_resumed" not in out["runs"]
    assert out["authorization"]["locks_still_false"] is True and out["verification"]["uninterrupted"]["records"] == 2


def test_cli_runs_in_a_scrubbed_child_environment():
    import orca.train.dryrun.__main__ as launcher
    src = Path(launcher.__file__).read_text()
    assert '"-E", "-s"' in src and "ORNEUR_HOME" in src and "env=env" in src


# ── lock snapshot / detection logic ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mini_auth(tmp_path):
    root = tmp_path / "r"
    (root / "docs/orneur/authorization").mkdir(parents=True)
    for p in (REPO / "docs/orneur/authorization").glob("*.json"):
        shutil.copy(p, root / "docs/orneur/authorization" / p.name)
    return root


def test_snapshot_of_the_committed_state_is_all_denied():
    snap = cli.lock_snapshot(REPO)
    assert cli.locks_all_denied(snap) and snap["training_authorization_sha256"] == file_sha256(REPO / A.RECORD_PATH)
    assert set(snap["functions"]) == {"corpus_generation_authorized", "qualification_authorized", "model_selection_authorized", "gpu_authorized",
                                      "provider_authorized", "spending_authorized", "training_authorized"}


def test_any_change_to_an_authorization_file_changes_the_snapshot_and_trips_the_check(mini_auth):
    before = cli.lock_snapshot(mini_auth)
    assert before == cli.lock_snapshot(mini_auth)
    p = mini_auth / A.RECORD_PATH
    rec = json.loads(p.read_text())
    rec["status"] = "AUTHORIZED"
    p.write_text(json.dumps(rec))
    after = cli.lock_snapshot(mini_auth)
    assert after != before and not cli.locks_all_denied(after)


def test_a_whitespace_only_edit_of_any_authorization_json_is_still_a_byte_change(mini_auth):
    before = cli.lock_snapshot(mini_auth)
    p = mini_auth / "docs/orneur/authorization/TRAINING_AUTHORITY_REGISTRY.json"
    p.write_text(p.read_text() + "\n")
    assert cli.lock_snapshot(mini_auth) != before


def test_gate_probe_denies_the_committed_record_with_the_gates_own_reason():
    probe = cli.gate_probe(REPO, "a" * 40, cli.Plan())
    assert probe == {"authorized": False, "reasons": ["NOT_AUTHORIZED"]}


def test_gate_probe_does_not_write_anything(tmp_path, monkeypatch):
    import orca.config as orca_config
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "home")
    cli.gate_probe(REPO, "a" * 40, cli.Plan())
    assert not (tmp_path / "home").exists()                                            # verify() is pure: no audit event, no state directory


# ── the committed sample ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_committed_sample_result_is_internally_consistent_and_synthetic():
    doc = json.loads(SAMPLE.read_text())
    assert doc["schema"] == cli.RESULT_SCHEMA and doc["synthetic"] is True and doc["status"] == "OK"
    assert doc["result_sha256"] == hash_obj({k: v for k, v in doc.items() if k != "result_sha256"})
    assert doc["resume_equivalent"] is True and doc["gate_probe"] == {"authorized": False, "reasons": ["NOT_AUTHORIZED"]}
    a = doc["authorization"]
    assert a["authorization_files_byte_identical"] is True and a["locks_still_false"] is True and a["locks_before"] == a["locks_after"]
    assert all(v is False for v in a["locks_after"]["functions"].values())
    assert doc["sentinel"]["forbidden_modules_loaded"] == [] and doc["env_manifest"]["container"]["status"] == "NOT_BUILT"
    assert len(doc["git_sha"]) == 40 and doc["runs"]["zero_budget"]["status"] == "REFUSED"
    assert all(v["ledger_ok"] and v["manifests_ok"] and v["records"] >= 2 for v in doc["verification"].values())


def test_committed_sample_matches_the_authorization_files_as_they_are_now():
    doc = json.loads(SAMPLE.read_text())
    assert doc["authorization"]["locks_after"]["training_authorization_sha256"] == file_sha256(REPO / A.RECORD_PATH)
    assert doc["authorization"]["locks_after"]["authorization_json_sha256"]["TRAINING_AUTHORITY_REGISTRY.json"] == file_sha256(REPO / A.REGISTRY_PATH)
