"""Workstream G #13: the off-host training inventory is complete and CI-enforced. A NEW training notebook/script (or a changed or removed
inventoried one) that is not reflected in docs/orneur/status/trainprep/OFFHOST_NOTEBOOK_INVENTORY.json fails here. Read-only: nothing is run."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from orca.train.dryrun import inventory as inv

REPO = Path(__file__).resolve().parent.parent
INV = REPO / inv.INVENTORY_REL


@pytest.fixture(scope="module")
def committed():
    return json.loads(INV.read_text())


def test_committed_inventory_matches_the_repository(committed):
    assert inv.compare(REPO, committed) == []


def test_committed_inventory_is_exactly_what_the_generator_produces(committed):
    assert inv.inventory_bytes(inv.build_inventory(REPO)) == INV.read_bytes()


def test_every_entry_has_the_required_fields_and_a_valid_action(committed):
    assert committed["schema"] == inv.SCHEMA and committed["status"] == "INVENTORY_ONLY__NO_ACTION_TAKEN"
    need = {"id", "path", "kind", "sha256", "platform", "lineage", "what_it_trains", "trainer_constructs", "moves_model_weights", "base_models",
            "data_inputs", "outputs", "how_it_bypasses_the_gate", "proposed_action", "rationale"}
    ids = set()
    for e in committed["entries"]:
        assert need <= set(e), e["path"]
        assert e["proposed_action"] in ("retire", "freeze", "gate") and e["id"] not in ids and (REPO / e["path"]).is_file()
        assert len(e["sha256"]) == 64 and e["how_it_bypasses_the_gate"] and e["what_it_trains"] and e["rationale"]
        ids.add(e["id"])


def test_all_fourteen_known_training_notebooks_plus_the_merge_helpers_are_inventoried(committed):
    nbs = {e["path"].split("/")[-1][:-6] for e in committed["entries"] if e["kind"] == "NOTEBOOK"}
    from tests.test_training_authorization_assurance import FROZEN_TRAINING_NOTEBOOKS
    assert FROZEN_TRAINING_NOTEBOOKS <= nbs
    assert nbs - FROZEN_TRAINING_NOTEBOOKS == {"orca_core_dpo_merge_export_v1", "orca_nano_dpo_merge_fix_v2"}
    assert committed["summary"]["training_notebooks"] == 14
    assert {e["platform"] for e in committed["entries"] if e["kind"] == "NOTEBOOK"} == {"KAGGLE", "COLAB"}


def test_gated_in_repo_trainers_are_listed_as_gated(committed):
    gated = {e["path"] for e in committed["entries"] if e["kind"] == "GATED_IN_REPO"}
    assert gated == {"orca/train/finetune.py", "orca/train/cloud.py"}


def test_kaggle_launch_configs_are_inventoried_with_their_gpu_and_internet_settings(committed):
    metas = [e for e in committed["entries"] if e["kind"] == "KAGGLE_KERNEL_METADATA"]
    assert len(metas) == 2 and all(m["launch_config"]["enable_gpu"] is True and m["proposed_action"] == "freeze" for m in metas)


def test_offhost_gpu_inference_runners_are_tracked_but_marked_as_not_training(committed):
    wl = committed["offhost_gpu_runners_not_training"]
    assert wl and all(w["trains"] is False and w["note"] != "UNREVIEWED" for w in wl)


# ── the tripwire: simulate NEW artifacts in a copy of the relevant tree and prove the comparison fails ───────────────────────────

@pytest.fixture
def mini(tmp_path, committed):
    """A minimal repo containing the real notebooks + the real inventory, so we can add things to it."""
    root = tmp_path / "repo"
    shutil.copytree(REPO / "notebooks", root / "notebooks", ignore=shutil.ignore_patterns("data"))
    for rel in ("orca/train/finetune.py", "orca/train/cloud.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, root / rel)
    for e in committed["offhost_gpu_runners_not_training"]:
        (root / e["path"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / e["path"], root / e["path"])
    return root


def test_the_mini_repo_baseline_is_clean(mini, committed):
    assert inv.compare(mini, committed) == []


def test_a_new_training_notebook_fails_the_check(mini, committed):
    shutil.copy(mini / "notebooks/orca_nano_finetune_kaggle_v4_safety.ipynb", mini / "notebooks/orca_nano_finetune_kaggle_v5.ipynb")
    assert "NEW_UNINVENTORIED_TRAINING_ARTIFACT:notebooks/orca_nano_finetune_kaggle_v5.ipynb" in inv.compare(mini, committed)


def test_a_new_notebook_in_any_directory_fails_the_check(mini, committed):
    (mini / "somewhere/else").mkdir(parents=True)
    (mini / "somewhere/else/x.ipynb").write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["from trl import SFTTrainer\n"]}]}))
    assert any(p.startswith("NEW_UNINVENTORIED_TRAINING_ARTIFACT:somewhere/else/x.ipynb") for p in inv.compare(mini, committed))


def test_a_new_python_trainer_script_fails_the_check(mini, committed):
    (mini / "scripts").mkdir(exist_ok=True)
    (mini / "scripts/sneaky_train.py").write_text("from trl import SFTTrainer\nSFTTrainer(model=None).train()\n")
    assert "NEW_UNINVENTORIED_TRAINING_ARTIFACT:scripts/sneaky_train.py" in inv.compare(mini, committed)


def test_a_trainer_hidden_in_an_embedded_script_string_is_found(mini, committed):
    (mini / "scripts").mkdir(exist_ok=True)
    (mini / "scripts/remote.py").write_text('SCRIPT = """\\nfrom trl import SFTTrainer\\ntrainer = SFTTrainer(model)\\n"""\\n'.replace("\\n", "\n"))
    assert "NEW_UNINVENTORIED_TRAINING_ARTIFACT:scripts/remote.py" in inv.compare(mini, committed)


def test_a_new_launcher_command_in_ci_or_a_script_fails_the_check(mini, committed):
    (mini / "scripts").mkdir(exist_ok=True)
    (mini / "scripts/go.sh").write_text("#!/bin/sh\naccelerate launch train.py\n")
    (mini / ".github/workflows").mkdir(parents=True)
    (mini / ".github/workflows/t.yml").write_text("steps:\n  - run: torchrun --nproc 8 t.py\n")
    probs = inv.compare(mini, committed)
    assert "NEW_UNINVENTORIED_TRAINING_ARTIFACT:scripts/go.sh" in probs and "NEW_UNINVENTORIED_TRAINING_ARTIFACT:.github/workflows/t.yml" in probs


def test_a_new_kaggle_kernel_launch_config_fails_the_check(mini, committed):
    (mini / "notebooks/new-kernel-metadata.json").write_text(json.dumps({"id": "u/k", "enable_gpu": True}))
    assert "NEW_UNINVENTORIED_TRAINING_ARTIFACT:notebooks/new-kernel-metadata.json" in inv.compare(mini, committed)


def test_editing_a_frozen_notebook_fails_the_check(mini, committed):
    p = mini / "notebooks/orca_core_finetune_kaggle_v2.ipynb"
    p.write_text(p.read_text().replace("hardened", "hardened!", 1))
    assert "INVENTORIED_ARTIFACT_CHANGED:notebooks/orca_core_finetune_kaggle_v2.ipynb" in inv.compare(mini, committed)


def test_removing_an_inventoried_notebook_requires_an_inventory_update(mini, committed):
    (mini / "notebooks/orca_core_finetune_kaggle_v1.ipynb").unlink()
    assert any(p.startswith("INVENTORIED_ARTIFACT_MISSING") for p in inv.compare(mini, committed))


def test_a_new_offhost_gpu_runner_must_be_reviewed(mini, committed):
    (mini / "scripts/new_modal_job.py").write_text("import modal\napp = modal.App('x')\n")
    assert "NEW_OFFHOST_GPU_RUNNER:scripts/new_modal_job.py" in inv.compare(mini, committed)


def test_an_offhost_gpu_runner_that_starts_training_is_flagged(mini, committed):
    target = mini / "scripts/phase21b_4_20_modal_h100_control.py"
    target.write_text(target.read_text() + "\nfrom trl import SFTTrainer\n")
    probs = inv.compare(mini, committed)
    assert any(p.startswith("OFFHOST_GPU_RUNNER_CHANGED") or p.startswith("OFFHOST_GPU_RUNNER_NOW_CONSTRUCTS") for p in probs)
    assert "NEW_UNINVENTORIED_TRAINING_ARTIFACT:scripts/phase21b_4_20_modal_h100_control.py" in probs


def test_building_an_inventory_with_an_uncurated_artifact_refuses(mini):
    shutil.copy(mini / "notebooks/orca_nano_finetune_kaggle_v4_safety.ipynb", mini / "notebooks/brand_new.ipynb")
    with pytest.raises(KeyError):
        inv.build_inventory(mini)


def test_the_inventory_script_check_mode_runs_clean():
    import subprocess
    import sys
    p = subprocess.run([sys.executable, "scripts/trainprep/offhost_inventory.py", "--check"], cwd=REPO, capture_output=True, text=True)
    assert p.returncode == 0 and json.loads(p.stdout)["ok"] is True
