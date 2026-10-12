"""Resilience #7 and the standing gate invariant: a grant is re-validated at the moment of use (revoked / withdrawn / expired / wrong subject),
and none of the new resilience tooling can start real training or relax the NOT_AUTHORIZED gate. Uses the gate suite's synthetic world with
in-test ephemeral keys; no real key, no network, nothing outside tmp_path."""
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
from orca.train.config import TrainingConfig
from tests.test_trainprep_authorization import NullGuard, _call, _denied, _world
from tests.test_training_authorization_gate import ENV
from tests.trainprep_support import BIND, ENVSHA, big_budget

REPO = Path(__file__).resolve().parent.parent


def _set_revoked(w, ids):
    w._write(A.REVOCATIONS_PATH, {"schema_version": A.REVOCATIONS_SCHEMA_VERSION, "revoked_authorization_ids": list(ids)})


def test_a_grant_revoked_after_issuance_is_refused_at_use(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 5, "max_runs": 3}})
    g = w.authorize()
    _set_revoked(w, [w.record["authorization_id"]])
    assert "AUTHORIZATION_REVOKED" in _denied(w, tmp_path, grant=g, authorize=False)


def test_an_unreadable_revocation_list_at_use_is_never_treated_as_nothing_revoked(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 5, "max_runs": 3}})
    g = w.authorize()
    (w.root / A.REVOCATIONS_PATH).write_text("{ not json")
    assert "REVOCATION_LIST_UNREADABLE" in _denied(w, tmp_path, grant=g, authorize=False)


def test_an_authorization_record_withdrawn_after_issuance_is_refused_at_use(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 5, "max_runs": 3}})
    g = w.authorize()
    w._write(A.RECORD_PATH, A.default_record())                          # back to NOT_AUTHORIZED
    assert "AUTHORIZATION_RECORD_WITHDRAWN" in _denied(w, tmp_path, grant=g, authorize=False)


def test_an_unrevoked_grant_still_runs(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch)
    out, _ = _call(w, tmp_path)
    assert out.status == "FINISHED"


def test_a_grant_that_expires_between_issue_and_use_is_refused(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 5, "max_runs": 3}})
    g = w.authorize()

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(timezone.utc) + timedelta(days=3650)
    monkeypatch.setattr(A, "datetime", Later)
    assert "EXPIRED" in _denied(w, tmp_path, grant=g, authorize=False)


def test_a_grant_for_one_environment_class_is_refused_for_another(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 5, "max_runs": 3}})
    g = w.authorize()
    other = "SSH_RENTED_GPU" if ENV != "SSH_RENTED_GPU" else "SELF_HOSTED_GPU"
    with pytest.raises(A.TrainingNotAuthorized) as e:
        H.rehearse_with_grant(w.cfg, g, environment_class=other, plan=H.Plan() if hasattr(H, "Plan") else None, root=tmp_path / "sbx" / "run",
                              consumed_dir=tmp_path / "sbx" / "c", guard=NullGuard(), run_id="x", budget=big_budget(max_spend_usd=1.0),
                              binding=BIND, env_manifest_sha256=ENVSHA)
    assert "WRONG_ENVIRONMENT_CLASS" in e.value.reasons and not (tmp_path / "sbx" / "run").exists()


def test_a_grant_presented_for_a_different_subject_config_is_refused(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 5, "max_runs": 3}})
    g = w.authorize()
    other = TrainingConfig()
    other.train_file, other.eval_file = w.cfg.train_file, w.cfg.eval_file
    other.base_model = "some/other-model"
    w.cfg = other
    assert "CONFIG_CHANGED_AFTER_AUTHORIZATION" in _denied(w, tmp_path, grant=g, authorize=False)


def test_a_refused_grant_is_not_consumed(tmp_path, monkeypatch):
    w = _world(tmp_path, monkeypatch, record_over={"limits": {"max_spend_usd": 5, "max_runs": 3}})
    g = w.authorize()
    _set_revoked(w, [w.record["authorization_id"]])
    _denied(w, tmp_path, grant=g, authorize=False)
    assert not (tmp_path / "sbx" / "consumed").exists() or not any((tmp_path / "sbx" / "consumed").iterdir())


# ── the standing invariant: nothing here can start training or authorize it ───────────────────────────────────────────────────

NEW_MODULES = ("lockverify.py", "evidence.py")


def test_new_tooling_cannot_reach_the_gate_a_trainer_or_the_environment():
    for name in NEW_MODULES:
        src = (REPO / "orca/train/dryrun" / name).read_text()
        tree = ast.parse(src)
        mods = {(a.name if isinstance(n, ast.Import) else (n.module or "")) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [n])}
        assert not any(m.startswith(("orca.train.authorization", "orca.train.dryrun.harness", "orca.train.dryrun.sentinel", "subprocess", "socket",
                                     "torch", "transformers", "trl", "peft", "unsloth", "requests", "urllib", "http")) for m in mods), (name, mods)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert not attrs & {"environ", "getenv", "authorize_training", "require_grant", "TrainingGrant"}, name


def test_no_dryrun_callable_gained_a_bypass_parameter():
    import importlib
    banned = {"dry_run", "dryrun", "force", "skip_auth", "no_auth", "bypass", "unsafe", "yes", "authorized", "allow", "override", "skip_verify"}
    for py in sorted((REPO / "orca/train/dryrun").glob("*.py")):
        mod = importlib.import_module(f"orca.train.dryrun.{py.stem}")
        for n, fn in inspect.getmembers(mod, inspect.isfunction):
            if fn.__module__ == mod.__name__:
                assert not banned & {p.lower() for p in inspect.signature(fn).parameters}, (py.name, n)


def test_the_real_repository_still_refuses_and_the_committed_record_is_not_authorized(tmp_path, monkeypatch):
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path / "h")
    cfg = TrainingConfig()
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n")
    cfg.train_file = str(t)
    for env in A.ENVIRONMENT_CLASSES:
        with pytest.raises(A.TrainingNotAuthorized) as e:
            A.authorize_training(cfg, environment_class=env)
        assert "NOT_AUTHORIZED" in e.value.reasons
    rec = json.loads((REPO / A.RECORD_PATH).read_text())
    assert rec["status"] == "NOT_AUTHORIZED" and rec == A.default_record()
    with pytest.raises(A.TrainingNotAuthorized):
        H.authorize_and_rehearse(cfg, environment_class=ENV, plan=None, root=tmp_path / "run", consumed_dir=tmp_path / "c", guard=NullGuard(),
                                 run_id="x", budget=big_budget(), binding=BIND, env_manifest_sha256=ENVSHA)
    assert not (tmp_path / "run").exists()
