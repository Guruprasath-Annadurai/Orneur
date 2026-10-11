"""Workstream G #11: code-revision + dataset-hash + config binding. A run binds (clean git SHA, dataset manifest hashes, config hash); start and
every resume recompute the live facts and any mismatch is a refusal. Uses throw-away git repos in tmp_path and in-memory registry dataclasses."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orca.registry.dataset_bundle import DatasetBundleManifest, SourceManifestLineage
from orca.registry.dataset_manifest import DatasetManifest
from orca.train.dryrun.binding import Binding, BindingRefused, collect_binding, git_state, manifest_hash, synthetic_dataset_manifest, verify_binding
from orca.train.dryrun.budget import ResourceBudget
from orca.train.dryrun.harness import RunRefused, run_core
from orca.train.dryrun.toy import Plan
from tests.trainprep_support import ENVSHA, big_budget


def _g(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _g(r, "init", "-q", "-b", "main")
    (r / "a.py").write_text("x = 1\n")
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "one")
    return r


def _dm(**over) -> DatasetManifest:
    kw = dict(dataset_id="synthetic-ds", version="v1", purpose="test", source_paths=["synthetic"], record_count=2, schema="{}", train_checksum="1" * 64,
              eval_checksum="2" * 64, creation_code_sha="3" * 40, filters_applied="none", deduplication_result="none")
    kw.update(over)
    return DatasetManifest(**kw)


PLAN = Plan()
CFG = PLAN.as_dict()


def test_collects_the_real_head_sha_and_requires_a_clean_tree(repo):
    b = collect_binding(repo, config=CFG, dataset_manifests=[_dm()])
    assert b.git_sha == _g(repo, "rev-parse", "HEAD") and b.tree_clean and len(b.dataset_manifest_sha256s) == 1


@pytest.mark.parametrize("dirty", ["modify", "untracked", "staged"])
def test_dirty_tree_is_refused(repo, dirty):
    if dirty == "modify":
        (repo / "a.py").write_text("x = 2\n")
    elif dirty == "untracked":
        (repo / "new.py").write_text("y = 1\n")
    else:
        (repo / "a.py").write_text("x = 3\n")
        _g(repo, "add", "a.py")
    with pytest.raises(BindingRefused) as e:
        collect_binding(repo, config=CFG, dataset_manifests=[_dm()])
    assert "DIRTY_WORKING_TREE" in e.value.reasons


def test_not_a_repository_and_no_dataset_are_refused(tmp_path, repo):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_state(plain) == (None, False)
    with pytest.raises(BindingRefused) as e:
        collect_binding(plain, config=CFG, dataset_manifests=[_dm()])
    assert "GIT_SHA_UNAVAILABLE" in e.value.reasons
    with pytest.raises(BindingRefused) as e2:
        collect_binding(repo, config=CFG, dataset_manifests=[])
    assert "NO_DATASET_MANIFEST_BOUND" in e2.value.reasons


def test_manifest_hash_binds_checksums_but_ignores_creation_time():
    a, b = _dm(), _dm()
    b.created_at = "1999-01-01T00:00:00Z"
    assert manifest_hash(a) == manifest_hash(b)
    assert manifest_hash(_dm(train_checksum="9" * 64)) != manifest_hash(a)
    assert manifest_hash(_dm(eval_checksum="9" * 64)) != manifest_hash(a)
    bundle = DatasetBundleManifest(bundle_id="b", version="v1", source_manifests=[SourceManifestLineage("synthetic-ds-v1", "1" * 64, "2" * 64)],
                                   train_checksum="5" * 64, eval_checksum="6" * 64)
    assert manifest_hash(bundle) != manifest_hash(a) and len(manifest_hash(bundle)) == 64


def test_multiple_manifest_hashes_are_order_insensitive(repo):
    x, y = _dm(dataset_id="a-ds"), _dm(dataset_id="b-ds")
    assert collect_binding(repo, config=CFG, dataset_manifests=[x, y]) == collect_binding(repo, config=CFG, dataset_manifests=[y, x])


def test_verify_binding_flags_every_kind_of_drift(repo):
    live = collect_binding(repo, config=CFG, dataset_manifests=[_dm()])
    rec = live.as_dict()
    verify_binding(rec, live)                                                     # identical -> fine
    cases = {
        "GIT_SHA_MISMATCH": {**rec, "git_sha": "f" * 40},
        "CONFIG_HASH_MISMATCH": {**rec, "config_sha256": "e" * 64},
        "DATASET_MANIFEST_HASH_MISMATCH": {**rec, "dataset_manifest_sha256s": ["d" * 64]},
        "DATASET_BUNDLE_HASH_MISMATCH": {**rec, "dataset_bundle_sha256": "c" * 64},
    }
    for code, expected in cases.items():
        with pytest.raises(BindingRefused) as e:
            verify_binding(expected, live)
        assert code in e.value.reasons
    with pytest.raises(BindingRefused) as e:
        verify_binding({"git_sha": "x"}, live)
    assert e.value.reasons == ["EXPECTED_BINDING_MALFORMED"]
    with pytest.raises(BindingRefused) as e:
        verify_binding(rec, Binding(live.git_sha, False, live.config_sha256, live.dataset_manifest_sha256s, None))
    assert "DIRTY_WORKING_TREE" in e.value.reasons


# ── end to end: the run ledger carries the binding and resume re-verifies it ─────────────────────────────────────────────────────

def _bind(repo, ds=None):
    return collect_binding(repo, config=PLAN.as_dict(), dataset_manifests=[ds or synthetic_dataset_manifest(PLAN)])


def _start(repo, root, **kw):
    return run_core(PLAN, root, run_id="bound", budget=big_budget(max_steps=4), binding=_bind(repo), env_manifest_sha256=ENVSHA, **kw)


def test_resume_with_the_same_binding_works(repo, tmp_path):
    _start(repo, tmp_path / "r")
    out = run_core(PLAN, tmp_path / "r", run_id="bound", budget=big_budget(), binding=_bind(repo), env_manifest_sha256=ENVSHA, resume=True)
    assert out.status == "FINISHED"


def test_resume_after_the_code_changed_is_refused(repo, tmp_path):
    _start(repo, tmp_path / "r")
    (repo / "a.py").write_text("x = 'changed after the run began'\n")
    _g(repo, "commit", "-qam", "two")
    with pytest.raises(BindingRefused) as e:
        run_core(PLAN, tmp_path / "r", run_id="bound", budget=big_budget(), binding=_bind(repo), env_manifest_sha256=ENVSHA, resume=True)
    assert "GIT_SHA_MISMATCH" in e.value.reasons


def test_resume_with_a_dirty_tree_is_refused_at_binding_time(repo, tmp_path):
    _start(repo, tmp_path / "r")
    (repo / "a.py").write_text("x = 'uncommitted'\n")
    with pytest.raises(BindingRefused) as e:
        _bind(repo)
    assert "DIRTY_WORKING_TREE" in e.value.reasons


def test_resume_with_a_different_dataset_is_refused(repo, tmp_path):
    _start(repo, tmp_path / "r")
    other = {**synthetic_dataset_manifest(PLAN), "data_seed": 12345}
    with pytest.raises(BindingRefused) as e:
        run_core(PLAN, tmp_path / "r", run_id="bound", budget=big_budget(), binding=_bind(repo, other), env_manifest_sha256=ENVSHA, resume=True)
    assert "DATASET_MANIFEST_HASH_MISMATCH" in e.value.reasons


def test_resume_with_a_different_config_is_refused(repo, tmp_path):
    _start(repo, tmp_path / "r")
    changed = Plan(lr=0.5)
    with pytest.raises(RunRefused) as e:                                           # plan hash is checked first ...
        run_core(changed, tmp_path / "r", run_id="bound", budget=big_budget(), binding=_bind(repo), env_manifest_sha256=ENVSHA, resume=True)
    assert "PLAN_HASH_MISMATCH" in e.value.reasons
    same_plan_other_cfg_hash = collect_binding(repo, config={**PLAN.as_dict(), "lr": 0.5}, dataset_manifests=[synthetic_dataset_manifest(PLAN)])
    with pytest.raises(BindingRefused) as e2:                                      # ... and the config hash independently
        run_core(PLAN, tmp_path / "r", run_id="bound", budget=big_budget(), binding=same_plan_other_cfg_hash, env_manifest_sha256=ENVSHA, resume=True)
    assert "CONFIG_HASH_MISMATCH" in e2.value.reasons


def test_the_ledger_records_the_binding_at_start(repo, tmp_path):
    from orca.train.dryrun.ledger import RunLedger
    _start(repo, tmp_path / "r")
    rec = RunLedger(tmp_path / "r" / "ledger.jsonl").run_started_body()["binding"]
    assert rec["git_sha"] == _g(repo, "rev-parse", "HEAD") and rec["tree_clean"] is True and rec["config_sha256"] and rec["dataset_manifest_sha256s"]


def test_zero_budget_import_sanity():
    assert ResourceBudget().is_zero
