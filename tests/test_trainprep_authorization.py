"""Workstream G #10: independent-authorization enforcement. The synthetic harness is exercised against the REAL gate (orca.train.authorization)
using the gate suite's synthetic world: ephemeral Ed25519 keys generated in-test, throw-away git repo and ORCA_HOME in tmp_path, pin patched.
No real key exists or is created; nothing outside tmp_path is written. Every denial must also prove that NO synthetic run directory was created.
"""
from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import orca.config as orca_config
import orca.train.authorization as A
import orca.train.dryrun.harness as H
from orca.train.dryrun.budget import ResourceBudget
from orca.train.dryrun.ledger import RunLedger
from orca.train.dryrun.toy import Plan
from tests.test_training_authorization_assurance import _hand_built
from tests.test_training_authorization_gate import ENV, World, _git, _ts, reasons_of
from tests.trainprep_support import BIND, ENVSHA, big_budget

REPO = Path(__file__).resolve().parent.parent
NOW = datetime.now(timezone.utc)


class _Att:
    def assert_active(self):
        pass

    def assert_no_violations(self):
        pass


class NullGuard:
    """Test double for the sentinel (which has its own subprocess-based proof in test_trainprep_sentinel.py): isolates authorization logic."""

    def __init__(self):
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return _Att()

    def __exit__(self, *a):
        return False


def _call(world, tmp_path, *, grant=None, authorize=True, budget=None, **kw):
    guard = NullGuard()
    common = dict(plan=Plan(), root=tmp_path / "sbx" / "run", consumed_dir=tmp_path / "sbx" / "consumed", guard=guard, run_id="rehearsal",
                  budget=budget or big_budget(max_spend_usd=1.0), binding=BIND, env_manifest_sha256=ENVSHA, **kw)
    if authorize:
        return H.authorize_and_rehearse(world.cfg, environment_class=ENV, dataset_manifest_ids=["ds-1"], **common), guard
    return H.rehearse_with_grant(world.cfg, grant, environment_class=ENV, **common), guard


def _denied(world, tmp_path, **kw):
    reasons = reasons_of(lambda: _call(world, tmp_path, **kw))
    assert not (tmp_path / "sbx" / "run").exists(), "a denied request must not create any run state"
    return reasons


def _world(tmp_path, monkeypatch, **kw):
    kw.setdefault("record_over", {"limits": {"max_spend_usd": 5, "max_runs": 1}})
    return World(tmp_path, monkeypatch, **kw)


def _recommit(w, record):
    w._write(A.RECORD_PATH, record)
    _git(w.root, "add", "-A")
    _git(w.root, "commit", "-q", "-m", "edited record")


# ── no grant, wrong grant ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [None, "granted", {"authorization_id": "x"}, object()])
def test_refuses_without_a_valid_grant(tmp_path, monkeypatch, bad):
    w = _world(tmp_path, monkeypatch)
    assert _denied(w, tmp_path, grant=bad, authorize=False) == ["NO_TRAINING_GRANT"]


def test_real_repository_denies_a_perfectly_formed_request_and_runs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    from orca.train.config import TrainingConfig
    cfg = TrainingConfig()
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n")
    cfg.train_file = str(t)
    with pytest.raises(A.TrainingNotAuthorized) as e:
        H.authorize_and_rehearse(cfg, environment_class=ENV, plan=Plan(), root=tmp_path / "run", consumed_dir=tmp_path / "c", guard=NullGuard(),
                                 run_id="x", budget=big_budget(), binding=BIND, env_manifest_sha256=ENVSHA)
    assert "NOT_AUTHORIZED" in e.value.reasons and not (tmp_path / "run").exists()


def test_happy_path_synthetic_grant_runs_and_is_recorded_in_the_ledger(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    out, guard = _call(w, tmp_path)
    assert out.status == "FINISHED" and guard.entered == 1
    started = RunLedger(tmp_path / "sbx" / "run" / "ledger.jsonl").run_started_body()
    assert started["grant"]["authorization_id"] == w.record["authorization_id"] and started["grant"]["key_id"] == "synthetic-authority-1"
    assert [e["event"] for e in w.events()] == ["TRAINING_AUTHORIZED"]


# ── the required denial matrix ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_expired_authorization(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"issued_at": _ts(NOW - timedelta(days=3)), "expires_at": _ts(NOW - timedelta(days=1)),
                                                   "limits": {"max_spend_usd": 5}})
    assert "EXPIRED" in _denied(w, tmp_path)


def test_revoked_authorization(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, revoked=["tauth-" + "ab" * 8])
    assert "AUTHORIZATION_REVOKED" in _denied(w, tmp_path)


def test_replayed_authorization_beyond_max_runs(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    _call(w, tmp_path)                                                    # consumes the only slot (max_runs == 1)
    import shutil
    shutil.rmtree(tmp_path / "sbx")
    assert "RUN_BUDGET_EXHAUSTED" in _denied(w, tmp_path)


def test_replaying_the_same_grant_object_is_refused(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_runs": 3, "max_spend_usd": 5}})
    g = w.authorize()
    _call(w, tmp_path, grant=g, authorize=False)
    import shutil
    shutil.rmtree(tmp_path / "sbx" / "run")
    assert _denied(w, tmp_path, grant=g, authorize=False) == ["GRANT_ALREADY_CONSUMED"]


def test_replay_marker_survives_a_new_process_state_via_the_consumed_dir(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_runs": 3, "max_spend_usd": 5}})
    g = w.authorize()
    _call(w, tmp_path, grant=g, authorize=False)
    H._CONSUMED_IN_PROCESS.clear()                                        # simulate a fresh process
    import shutil
    shutil.rmtree(tmp_path / "sbx" / "run")
    assert _denied(w, tmp_path, grant=g, authorize=False) == ["GRANT_ALREADY_CONSUMED"]


def test_wrong_code_tree_hash(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    (w.root / "orca/train/dummy.py").write_text("X = 999  # changed after review\n")
    _git(w.root, "commit", "-qam", "post-review change")
    assert "CODE_TREE_HASH_MISMATCH" in _denied(w, tmp_path)


def test_dirty_tree(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    (w.root / "orca/train/dummy.py").write_text("X = 5\n")
    assert "DIRTY_WORKING_TREE" in _denied(w, tmp_path)


def test_wrong_dataset_hash(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    w.train.write_text('{"text": "tampered"}\n')
    assert "WRONG_TRAIN_DATASET" in _denied(w, tmp_path)


def test_dataset_changed_after_grant_is_refused_by_the_harness(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    g = w.authorize()
    w.train.write_text('{"text": "swapped after authorization"}\n')
    assert "TRAIN_DATA_CHANGED_AFTER_AUTHORIZATION" in _denied(w, tmp_path, grant=g, authorize=False)


def test_wrong_base_model_revision(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"model": {"base_model_revision": "a" * 40}, "limits": {"max_spend_usd": 5}})
    assert "WRONG_BASE_MODEL_REVISION" in _denied(w, tmp_path)


def test_tampered_signature(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    rec = dict(w.record)
    rec["signature"] = ("0" if rec["signature"][0] != "0" else "1") + rec["signature"][1:]
    _recommit(w, rec)
    assert "SIGNATURE_INVALID" in _denied(w, tmp_path)


def test_signed_field_edited_after_signing(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    rec = json.loads(json.dumps(w.record))
    rec["limits"]["max_spend_usd"] = 10 ** 6                              # widen the budget without re-signing
    _recommit(w, rec)
    assert "SIGNATURE_INVALID" in _denied(w, tmp_path)


def test_tampered_integrity_tag_on_the_grant(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    forged = _hand_built(w.authorize(), _mac="0" * 64)
    assert _denied(w, tmp_path, grant=forged, authorize=False) == ["GRANT_FORGED_OR_TAMPERED"]


def test_widened_grant_fields_are_refused(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    forged = _hand_built(w.authorize(), max_wall_clock_minutes=10 ** 6)
    assert _denied(w, tmp_path, grant=forged, authorize=False) == ["GRANT_FORGED_OR_TAMPERED"]


def test_audit_log_tamper_blocks_the_run(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_runs": 3, "max_spend_usd": 5}})
    w.authorize()
    p = w.state / "events.jsonl"
    p.write_text(p.read_text().replace('"TRAINING_AUTHORIZED"', '"TRAINING_AUTHORIZEX"', 1))
    assert "AUDIT_LOG_TAMPERED" in _denied(w, tmp_path)


def test_authorized_spend_budget_is_exceeded(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 0.5}})
    assert "SPEND_NOT_AUTHORIZED" in _denied(w, tmp_path, budget=big_budget(max_spend_usd=1.0))


def test_spend_cap_of_the_budget_cannot_exceed_zero_authorized_spend(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 0}})
    assert "SPEND_NOT_AUTHORIZED" in _denied(w, tmp_path, budget=big_budget(max_spend_usd=0.01))


def test_config_changed_after_authorization(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    g = w.authorize()
    w.cfg.num_epochs = 2
    assert "CONFIG_CHANGED_AFTER_AUTHORIZATION" in _denied(w, tmp_path, grant=g, authorize=False)


def test_the_grants_wall_clock_can_only_tighten_the_budget(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_wall_clock_minutes": 1, "max_spend_usd": 5}})

    class Clock:
        t = 0.0

        def __call__(self):
            return self.t
    clk = Clock()
    out, _ = _call(w, tmp_path, budget=big_budget(max_wall_clock_s=10 ** 6, max_spend_usd=1.0), clock=clk,
                   fault=H.Fault(on_micro=lambda s, m: setattr(clk, "t", 61.0)))
    assert (out.status, out.reason) == ("STOPPED", "WALL_CLOCK_CAP")        # 1 authorized minute beats the 10**6 s budget


# ── structural: no bypass exists ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_entry_point_has_a_bypass_parameter():
    banned = {"dry_run", "dryrun", "force", "skip_auth", "no_auth", "bypass", "unsafe", "yes", "authorized", "allow", "override"}
    for fn in (H.run_synthetic, H.rehearse_with_grant, H.authorize_and_rehearse, H.run_core):
        assert not banned & {n.lower() for n in inspect.signature(fn).parameters}, fn.__name__


def test_dryrun_modules_never_read_the_environment_or_hold_signing_keys():
    for py in sorted((REPO / "orca/train/dryrun").glob("*.py")):
        src = py.read_text()
        assert "Ed25519PrivateKey" not in src and "private_bytes" not in src and ".sign(" not in src, py.name
        if py.name in ("sentinel.py", "__main__.py"):                       # these two SET a scrubbed environment for the child / guard; they never read policy from it
            continue
        tree = ast.parse(src)
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not names & {"environ", "getenv", "putenv"}, f"{py.name} must not consult environment variables"


def test_dryrun_package_has_no_trainer_or_tensor_imports():
    forbidden = {"torch", "transformers", "unsloth", "trl", "peft", "bitsandbytes", "accelerate", "datasets", "numpy", "wandb", "safetensors"}
    for py in sorted((REPO / "orca/train/dryrun").glob("*.py")):
        for n in ast.walk(ast.parse(py.read_text())):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module or ""] if isinstance(n, ast.ImportFrom) else [])
            assert not {m.partition(".")[0] for m in mods} & forbidden, (py.name, mods)


def test_the_gate_still_has_no_dryrun_switch_and_the_committed_record_is_unchanged():
    assert list(inspect.signature(A.authorize_training).parameters) == [
        "cfg", "environment_class", "dataset_manifest_ids", "dataset_bundle_id", "requested_spend_usd", "now"]
    assert json.loads((REPO / A.RECORD_PATH).read_text()) == A.default_record()
    assert ResourceBudget().is_zero
