"""Task C -- adversarial assurance for the training authorization gate (PR #24).

Reuses the gate suite's synthetic world (throw-away git repo, synthetic Ed25519 key, patched pin): no real key, GPU, model or training. Every test
asserts the SAFE behaviour; ``xfail(strict=True)`` marks a documented residual so it cannot silently change.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import pickle
import re
import threading
from pathlib import Path

import pytest

import orca.train.authorization as A
from tests.test_training_authorization_gate import ENV, World, reasons_of, world  # noqa: F401  (fixture re-export)

REPO = Path(__file__).resolve().parent.parent


# ── grant integrity: a valid grant must not be widened, copied, pickled or hand-built ───────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("max_wall_clock_minutes", 10**6), ("expires_at", "2099-01-01T00:00:00Z"), ("train_sha256", "b" * 64), ("eval_sha256", "c" * 64),
    ("run_slot", 99), ("environment_class", "SSH_RENTED_GPU"), ("cfg_fingerprint", "f" * 64), ("authorization_id", "tauth-forged"),
])
def test_a_grant_cannot_be_widened_with_dataclasses_replace(world, field, value):
    g = world.authorize()
    with pytest.raises(A.TrainingNotAuthorized):
        dataclasses.replace(g, **{field: value})


def test_a_grant_cannot_be_copied_or_pickled(world):
    g = world.authorize()
    for attempt in (lambda: pickle.dumps(g), lambda: copy.copy(g), lambda: copy.deepcopy(g)):
        with pytest.raises(TypeError):
            attempt()


def _hand_built(g, **over):
    forged = object.__new__(A.TrainingGrant)
    for f in dataclasses.fields(A.TrainingGrant):
        object.__setattr__(forged, f.name, over.get(f.name, getattr(g, f.name)))
    return forged


@pytest.mark.parametrize("over", [
    {"_seal": object()},                                   # wrong seal
    {"_mac": "0" * 64},                                    # right seal, wrong integrity tag
    {"max_wall_clock_minutes": 10**6},                     # right seal + right (old) tag, widened field
    {"expires_at": "2099-01-01T00:00:00Z"},
])
def test_every_consumer_refuses_a_hand_built_or_edited_grant(world, over):
    forged = _hand_built(world.authorize(), **over)
    with pytest.raises(A.TrainingNotAuthorized):
        A.require_grant(forged, world.cfg, environment_class=ENV)
    with pytest.raises(A.TrainingNotAuthorized):
        forged.assert_valid_for(world.cfg, environment_class=ENV)
    with pytest.raises(A.TrainingNotAuthorized):
        forged.assert_files(world.train, world.eval)
    with pytest.raises(A.TrainingNotAuthorized):
        forged.wall_clock_callback()


def test_a_genuine_grant_still_verifies_everywhere(world):
    g = world.authorize()
    assert A.require_grant(g, world.cfg, environment_class=ENV) is g
    g.assert_files(world.train, world.eval)
    assert g.wall_clock_callback() is not None


# ── ledger and audit-log manipulation ───────────────────────────────────────────────────────────────────────────────────────────────

def test_deleting_the_run_slot_files_does_not_reset_the_run_budget(world):
    world.authorize()                                       # max_runs == 1
    import shutil
    shutil.rmtree(world.state / "runs")
    assert "RUN_BUDGET_EXHAUSTED" in reasons_of(world.authorize)


def test_an_edited_audit_log_blocks_new_authorizations(world):
    A._state_dir()                                          # create the hardened state directory the way the gate does
    A._append_event(world.state, {"event": "SEED"})
    p = world.state / "events.jsonl"
    p.write_text(p.read_text().replace("SEED", "SEEX", 1))
    assert not A.verify_event_chain(world.state)
    assert "AUDIT_LOG_TAMPERED" in reasons_of(world.authorize)


def test_a_malformed_audit_log_blocks_new_authorizations(world):
    A._state_dir()
    A._append_event(world.state, {"event": "SEED"})
    with open(world.state / "events.jsonl", "a") as f:
        f.write("{not json\n")
    assert "AUDIT_LOG_TAMPERED" in reasons_of(world.authorize)


@pytest.mark.xfail(strict=True, reason="RESIDUAL (documented): truncating the TAIL of a hash chain leaves a valid chain; detecting it needs an anchor outside "
                                        "the operator's write access (e.g. a remote append-only log)")
def test_truncating_the_audit_log_tail_is_detected(world):
    world.authorize()
    A._append_event(world.state, {"event": "LATER"})
    p = world.state / "events.jsonl"
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:1]) + "\n")
    assert not A.verify_event_chain(world.state)


def test_concurrent_starts_never_exceed_the_run_budget(world):
    results, barrier = [], threading.Barrier(6)

    def go():
        barrier.wait()
        try:
            world.authorize()
            results.append("ok")
        except A.TrainingNotAuthorized as e:
            results.append(tuple(e.reasons))

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1


# ── forged environment / state directory ────────────────────────────────────────────────────────────────────────────────────────

def test_hand_crafted_state_and_environment_cannot_authorize_the_real_repository(tmp_path, monkeypatch):
    """Everything an attacker controls without editing the reviewed repo files: environment variables and the state directory."""
    import orca.config as orca_config
    from orca.train.config import TrainingConfig

    home = tmp_path / "h"
    state = home / "training" / "authorization"
    state.mkdir(parents=True, mode=0o700)
    (state / "AUTHORIZED").write_text("yes")
    (state / "TRAINING_AUTHORIZATION.json").write_text(json.dumps({"status": "AUTHORIZED", "authorization_id": "tauth-attacker"}))
    for k in ("ORNEUR_TRAINING_AUTHORIZED", "ORNEUR_ALLOW_TRAINING", "ORCA_ALLOW_TRAINING", "ORNEUR_TRAINING_GRANT", "CI", "ORNEUR_DRY_RUN", "FORCE"):
        monkeypatch.setenv(k, "1")
    monkeypatch.setattr(orca_config, "ORCA_HOME", home)
    cfg = TrainingConfig()
    t = tmp_path / "t.jsonl"
    t.write_text("{}\n")
    cfg.train_file = str(t)
    with pytest.raises(A.TrainingNotAuthorized) as exc:
        A.authorize_training(cfg, environment_class=ENV)
    assert "NOT_AUTHORIZED" in exc.value.reasons


# ── alternate trainer surfaces the Python AST guard cannot see ──────────────────────────────────────────────────────────────

def _py_files(*roots):
    for r in roots:
        yield from (p for p in (REPO / r).rglob("*.py") if "__pycache__" not in p.parts)


def test_remote_gpu_helpers_are_not_used_outside_the_gated_cloud_trainer():
    """`_ssh_run` / `_rsync_*` can start remote work with no gate; only CloudTrainer.run() (which authorizes first) may use them."""
    allowed = {"orca/train/cloud.py", "scripts/security/training_gate_repro.py"}      # the repro only PATCHES them to prove the gate stops the call
    offenders = [p.relative_to(REPO).as_posix() for p in _py_files("orca", "scripts")
                 if p.relative_to(REPO).as_posix() not in allowed and re.search(r"\b_ssh_run\b|\b_rsync_up\b|\b_rsync_down\b|\bREMOTE_WORKDIR\b", p.read_text())]
    assert offenders == [], offenders


_LAUNCHERS = re.compile(r"\b(?:orneur|orca)\s+train\s+(?:run|nano|core|ultra|cloud)\b|python3?\s+-m\s+orca\.train\b|\btorchrun\b|\baccelerate\s+launch\b|\bdeepspeed\b")


def _non_python_surfaces():
    for pattern in (".github/workflows/*.yml", ".github/workflows/*.yaml", "Dockerfile*", "docker-compose*.yml", "docker/*", "k8s/*.yaml", "scripts/**/*.sh",
                    "Makefile", "fly*.toml", "*.sh"):
        yield from (p for p in REPO.glob(pattern) if p.is_file())


def test_no_ci_container_or_script_surface_launches_training():
    offenders = [f"{p.relative_to(REPO)}:{m.group(0)}" for p in _non_python_surfaces() for m in [_LAUNCHERS.search(p.read_text(errors="replace"))] if m]
    assert offenders == [], offenders


def test_nothing_executes_notebooks():
    runners = re.compile(r"papermill|nbconvert|nbclient|ExecutePreprocessor|jupyter\s+(?:nbconvert|execute)")
    files = list(_py_files("orca", "scripts")) + list((REPO / ".github/workflows").glob("*.yml"))
    assert [p.name for p in files if runners.search(p.read_text(errors="replace"))] == []


FROZEN_TRAINING_NOTEBOOKS = {
    "orca_core_calibration_sft_kaggle_v1", "orca_core_combined_sft_kaggle_v1", "orca_core_dpo_kaggle_v1",
    "orca_core_finetune_kaggle_v1", "orca_core_finetune_kaggle_v2", "orca_nano_dpo_kaggle_v1",
    "orca_nano_finetune_colab", "orca_nano_finetune_colab_v2", "orca_nano_finetune_colab_v3", "orca_nano_finetune_colab_v4",
    "orca_nano_finetune_kaggle", "orca_nano_finetune_kaggle_v2", "orca_nano_finetune_kaggle_v3", "orca_nano_finetune_kaggle_v4_safety",
}


def test_training_notebooks_are_a_closed_reviewed_set():
    """These 14 train on third-party hosts (the merge/export notebooks contain no trainer) and are OUTSIDE the gate by nature (the gate controls ORNEUR's own entry points). A new one must be a
    visible, reviewed change to this list."""
    trainers = re.compile(r"SFTTrainer|DPOTrainer|GRPOTrainer|transformers\.Trainer|trainer\.train\(")
    found = {p.stem for p in (REPO / "notebooks").glob("*.ipynb") if trainers.search(p.read_text(errors="replace"))}
    assert found == FROZEN_TRAINING_NOTEBOOKS, sorted(found ^ FROZEN_TRAINING_NOTEBOOKS)
