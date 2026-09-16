"""
Phase 21B / 21B.1 reproducibility closure: orca.registry.provenance
wires TrainingConfig -> TrainingRunManifest -> CheckpointRecord ->
ModelRegistry without ever needing a GPU or the unsloth/torch/
transformers stack -- these tests exercise the full lifecycle,
including the failure path and every new Phase 21B.1 trust seam
(revision pinning, dataset binding, multi-file checkpoint identity),
entirely on CPU.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from orca.registry.checkpoint import CheckpointRecord, CheckpointStructureInvalid, CorruptCheckpointError
from orca.registry.dataset_bundle import DatasetBundleManifest, SourceManifestLineage
from orca.registry.dataset_manifest import DatasetManifest, sha256_of_file
from orca.registry.model_registry import ModelRegistry
from orca.registry.model_spec import LifecycleState
from orca.registry.provenance import (
    DatasetBindingInvalid,
    SnapshotIntegrityError,
    complete_training_run,
    create_run_snapshot,
    deterministic_run_id,
    fail_training_run,
    hash_artifact_directory,
    resolve_pinned_revisions,
    start_training_run,
    verify_dataset_binding,
    verify_run_snapshot,
)
from orca.registry.training_run import TrainingRunManifest
from orca.train.config import TrainingConfig, resolve_training_data_inputs


def _register_genesis_v2_manifest(*, train_path: Path, eval_path: Path) -> DatasetManifest:
    """Real DatasetManifest, checksummed against the actual (isolated
    temp) files it describes -- mirroring the real
    scripts/build_genesis_v2_dataset.py + DatasetManifest.save() flow."""
    from orca.registry.dataset_manifest import sha256_of_file

    manifest = DatasetManifest(
        dataset_id="orneur-genesis-v2",
        version="v1",
        purpose="test fixture",
        source_paths=["test"],
        record_count=2,
        schema='{"text": str}',
        train_checksum=sha256_of_file(train_path),
        eval_checksum=sha256_of_file(eval_path),
        creation_code_sha="test-sha",
        filters_applied="none",
        deduplication_result="0 duplicates",
    )
    manifest.save()
    return manifest


@pytest.fixture()
def cfg_with_real_dataset(tmp_path):
    """A canonical nano config wired to real train/eval files, with a
    matching DatasetManifest registered -- the normal, fully-bound
    successful path."""
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    train_path.write_text('{"text": "hello"}\n')
    eval_path.write_text('{"text": "world"}\n')
    _register_genesis_v2_manifest(train_path=train_path, eval_path=eval_path)

    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(train_path)
    cfg.eval_file = str(eval_path)
    return cfg


def test_deterministic_run_id_is_pure_and_reproducible():
    cfg = TrainingConfig.preset("nano")
    a = deterministic_run_id(cfg, nonce="fixed-nonce")
    b = deterministic_run_id(cfg, nonce="fixed-nonce")
    assert a == b
    assert a.startswith("run-")


def test_deterministic_run_id_changes_with_nonce():
    cfg = TrainingConfig.preset("nano")
    a = deterministic_run_id(cfg, nonce="n1")
    b = deterministic_run_id(cfg, nonce="n2")
    assert a != b


def test_start_training_run_fails_closed_for_manually_overridden_base_model():
    """The exact Phase 16 bypass class -- a canonical family config with
    its base_model manually overridden must never reach manifest
    creation (or even revision/dataset resolution) at all."""
    cfg = TrainingConfig.preset("nano")
    cfg.base_model = "some/arbitrary-model"
    with pytest.raises(ValueError, match="canonical|family|override"):
        start_training_run(cfg, dataset_manifest_ids=[], hardware_info="test-cpu")


def test_start_training_run_fails_closed_for_unselected_aeternum():
    cfg = TrainingConfig.preset("ultra")
    with pytest.raises(ValueError, match="UNSELECTED_PROVISIONAL|no selected|None"):
        start_training_run(cfg, dataset_manifest_ids=[], hardware_info="test-cpu")


# ── (B) revision pinning ────────────────────────────────────────────────


def test_resolve_pinned_revisions_returns_the_canonical_pin_for_genesis():
    cfg = TrainingConfig.preset("nano")
    base_rev, tok_rev = resolve_pinned_revisions(cfg)
    assert base_rev == "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"
    assert tok_rev == "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"


def test_resolve_pinned_revisions_fails_closed_for_unpinned_family():
    """Novus has a selected base but no pinned revision yet (Phase
    21B.1 only qualified Genesis) -- must raise, never silently
    resolve an unpinned 'latest'."""
    cfg = TrainingConfig.preset("core")
    with pytest.raises(ValueError, match="no pinned base_model_revision"):
        resolve_pinned_revisions(cfg)


def test_resolve_pinned_revisions_returns_none_for_generic_config():
    cfg = TrainingConfig.preset("prosumer")  # family=None, no ModelSpec to pin against
    assert resolve_pinned_revisions(cfg) == (None, None)


def test_load_base_model_and_tokenizer_passes_pinned_revision_to_loader(monkeypatch):
    """Mocks the real unsloth.FastLanguageModel.from_pretrained() call
    (never imported for real in this CPU-only environment) and proves
    the exact pinned revision is passed through -- closing the audit
    finding that 'recording a revision is not equivalent to loading
    that revision'."""
    received_kwargs = {}

    def fake_from_pretrained(**kwargs):
        received_kwargs.update(kwargs)
        return ("FAKE_MODEL", "FAKE_TOKENIZER")

    fake_unsloth = types.ModuleType("unsloth")
    fake_unsloth.FastLanguageModel = types.SimpleNamespace(from_pretrained=fake_from_pretrained)
    monkeypatch.setitem(sys.modules, "unsloth", fake_unsloth)

    from orca.train.finetune import _load_base_model_and_tokenizer

    cfg = TrainingConfig.preset("nano")
    model, tokenizer = _load_base_model_and_tokenizer(cfg, "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0")

    assert model == "FAKE_MODEL"
    assert tokenizer == "FAKE_TOKENIZER"
    assert received_kwargs["revision"] == "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"
    assert received_kwargs["model_name"] == cfg.base_model


def test_load_base_model_and_tokenizer_passes_none_revision_explicitly(monkeypatch):
    """A generic/unpinned config still explicitly passes revision=None
    (Unsloth's own documented default) -- never omits the kwarg in a
    way that could silently vary by call site."""
    received_kwargs = {}

    def fake_from_pretrained(**kwargs):
        received_kwargs.update(kwargs)
        return ("M", "T")

    fake_unsloth = types.ModuleType("unsloth")
    fake_unsloth.FastLanguageModel = types.SimpleNamespace(from_pretrained=fake_from_pretrained)
    monkeypatch.setitem(sys.modules, "unsloth", fake_unsloth)

    from orca.train.finetune import _load_base_model_and_tokenizer

    cfg = TrainingConfig.preset("prosumer")
    _load_base_model_and_tokenizer(cfg, None)
    assert received_kwargs["revision"] is None


# ── (C) dataset binding ─────────────────────────────────────────────────


def test_verify_dataset_binding_rejects_empty_list_for_canonical_family():
    cfg = TrainingConfig.preset("nano")
    with pytest.raises(DatasetBindingInvalid, match="at least one dataset_manifest_id"):
        verify_dataset_binding(cfg, dataset_manifest_ids=[])


def test_verify_dataset_binding_allows_empty_list_for_generic_config():
    cfg = TrainingConfig.preset("prosumer")
    assert verify_dataset_binding(cfg, dataset_manifest_ids=[]) == {}


def test_verify_dataset_binding_rejects_missing_manifest(cfg_with_real_dataset):
    with pytest.raises(DatasetBindingInvalid, match="No dataset manifest found"):
        verify_dataset_binding(cfg_with_real_dataset, dataset_manifest_ids=["does-not-exist-v99"])


def test_verify_dataset_binding_verifies_real_matching_files(cfg_with_real_dataset):
    digests = verify_dataset_binding(cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"])
    assert digests["train"] and digests["validation"]


def test_verify_dataset_binding_rejects_tampered_train_file(cfg_with_real_dataset):
    """The exact scenario the audit named: dataset_manifest_ids naming
    one dataset while the JSONL on disk has been altered/is different
    content -- must be rejected before any model loading."""
    Path(cfg_with_real_dataset.train_file).write_text('{"text": "TAMPERED CONTENT"}\n')
    with pytest.raises(DatasetBindingInvalid, match="failed binding verification"):
        verify_dataset_binding(cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"])


def test_verify_dataset_binding_rejects_missing_declared_file(cfg_with_real_dataset):
    Path(cfg_with_real_dataset.train_file).unlink()
    with pytest.raises(DatasetBindingInvalid, match="does not exist"):
        verify_dataset_binding(cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"])


def test_start_training_run_binds_and_records_verified_dataset_digest(cfg_with_real_dataset):
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-bound-1",
    )
    assert manifest.dataset_content_digests["train"]
    assert manifest.dataset_content_digests["validation"]
    assert manifest.base_model_revision == "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"
    assert manifest.tokenizer_revision == "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"
    # Phase 21B.2: a run-scoped snapshot was created and its digest
    # (not the original source file's digest at some earlier moment)
    # is what dataset_split_digests actually records.
    assert manifest.dataset_split_digests["train"]
    assert manifest.dataset_split_digests["validation"]
    assert Path(manifest.dataset_snapshot_paths["train"]).exists()
    assert Path(manifest.dataset_snapshot_paths["train"]) != Path(cfg_with_real_dataset.train_file)


def test_start_training_run_fails_closed_for_empty_dataset_manifest_ids(cfg_with_real_dataset):
    with pytest.raises(DatasetBindingInvalid):
        start_training_run(cfg_with_real_dataset, dataset_manifest_ids=[], hardware_info="test-cpu")


# ── (D) checkpoint artifact-manifest identity ───────────────────────────


def test_hash_artifact_directory_is_deterministic(tmp_path):
    d = tmp_path / "checkpoint"
    d.mkdir()
    (d / "config.json").write_text('{"a": 1}')
    (d / "model-00001-of-00002.safetensors").write_bytes(b"fake-shard-1")
    (d / "model-00002-of-00002.safetensors").write_bytes(b"fake-shard-2")

    result_a = hash_artifact_directory(d)
    result_b = hash_artifact_directory(d)
    assert result_a["manifest_digest"] == result_b["manifest_digest"]
    assert len(result_a["files"]) == 3


def test_hash_artifact_directory_changes_when_any_shard_changes(tmp_path):
    d = tmp_path / "checkpoint"
    d.mkdir()
    (d / "config.json").write_text('{"a": 1}')
    (d / "model-00001-of-00002.safetensors").write_bytes(b"fake-shard-1")
    (d / "model-00002-of-00002.safetensors").write_bytes(b"fake-shard-2")
    before = hash_artifact_directory(d)["manifest_digest"]

    (d / "model-00002-of-00002.safetensors").write_bytes(b"MUTATED-shard-2")
    after = hash_artifact_directory(d)["manifest_digest"]
    assert before != after


def test_hash_artifact_directory_changes_when_config_changes(tmp_path):
    d = tmp_path / "checkpoint"
    d.mkdir()
    (d / "config.json").write_text('{"a": 1}')
    (d / "model.safetensors").write_bytes(b"weights")
    before = hash_artifact_directory(d)["manifest_digest"]

    (d / "config.json").write_text('{"a": 2}')
    after = hash_artifact_directory(d)["manifest_digest"]
    assert before != after


def test_hash_artifact_directory_changes_when_a_file_is_missing(tmp_path):
    d = tmp_path / "checkpoint"
    d.mkdir()
    (d / "config.json").write_text('{"a": 1}')
    (d / "tokenizer.json").write_text("{}")
    before = hash_artifact_directory(d)["manifest_digest"]

    (d / "tokenizer.json").unlink()
    after = hash_artifact_directory(d)["manifest_digest"]
    assert before != after


def test_hash_artifact_directory_does_not_depend_on_filesystem_order(tmp_path):
    """Two directories with the same files but created in a different
    order must produce the same digest -- proves sorted-by-path
    canonicalization, not traversal order."""
    d1 = tmp_path / "d1"
    d1.mkdir()
    (d1 / "b.txt").write_text("B")
    (d1 / "a.txt").write_text("A")

    d2 = tmp_path / "d2"
    d2.mkdir()
    (d2 / "a.txt").write_text("A")
    (d2 / "b.txt").write_text("B")

    assert hash_artifact_directory(d1)["manifest_digest"] == hash_artifact_directory(d2)["manifest_digest"]


def test_hash_artifact_directory_missing_directory_raises():
    with pytest.raises(FileNotFoundError):
        hash_artifact_directory(Path("/does/not/exist/at/all"))


# ── full lifecycle (updated for Phase 21B.1's fail-closed dataset binding) ──


def test_complete_training_run_registers_checkpoint_at_experimental_only(tmp_path, cfg_with_real_dataset):
    """Training completion must never imply PROMOTABLE/PRODUCTION/
    AVAILABLE -- only ModelRegistry.promote() (gated on a passing
    evaluation report) can do that."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-complete-1",
    )

    artifact_dir = tmp_path / "merged"
    artifact_dir.mkdir()
    (artifact_dir / "config.json").write_text("{}")
    (artifact_dir / "tokenizer.json").write_text("{}")
    (artifact_dir / "model.safetensors").write_bytes(b"fake-weights")

    record = complete_training_run(
        manifest,
        checkpoint_id="genesis-test-checkpoint",
        artifact_path=str(artifact_dir),
        step_or_epoch="epoch=3",
        training_config_summary="QLoRA r=32",
        tokenizer_identity=cfg_with_real_dataset.base_model,
    )
    assert isinstance(record, CheckpointRecord)
    assert record.run_id == "run-complete-1"
    assert record.model_id == "orneur-genesis"
    assert record.base_model == cfg_with_real_dataset.base_model
    assert len(record.artifact_checksum) == 64  # sha256 hex digest of the artifact manifest

    registry = ModelRegistry()
    entry = registry.lookup("genesis-test-checkpoint")
    assert entry is not None
    assert entry.lifecycle_state == LifecycleState.EXPERIMENTAL.value
    assert registry.lookup_production("genesis") is None

    reloaded = TrainingRunManifest.load("run-complete-1")
    assert reloaded.end_time is not None
    assert reloaded.failure_state is None
    assert reloaded.checkpoint_outputs == ["genesis-test-checkpoint"]


def test_finetune_train_wrapper_marks_manifest_failed_on_missing_dependencies(cfg_with_real_dataset):
    """CPU-safe, real (not mocked) end-to-end proof of the orchestration
    path: this test environment genuinely has no unsloth/trl/datasets/
    peft/bitsandbytes installed, so orca.train.finetune.train()'s real
    _check_deps() call genuinely raises ImportError -- proving the
    manifest-created-before-any-model-work / marked-failed-on-any-
    exception wiring end to end, without mocking anything and without
    ever touching a GPU. This is orchestration verification, not model
    training -- no CheckpointRecord is ever created on this path."""
    from orca.registry.training_run import list_runs
    from orca.train.finetune import train

    with pytest.raises(ImportError, match="Missing training dependencies"):
        train(cfg_with_real_dataset, on_log=lambda _msg: None, dataset_manifest_ids=["orneur-genesis-v2-v1"])

    runs = list_runs("orneur-genesis")
    assert len(runs) == 1
    assert runs[0].failure_state is not None
    assert "ImportError" in runs[0].failure_state
    assert runs[0].end_time is not None
    assert runs[0].checkpoint_outputs == []
    # Even on failure, the manifest already recorded the revision it
    # WOULD have used -- created before dependency loading.
    assert runs[0].base_model_revision == "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"


# ── (§2-3) real train() entrypoint bundle wiring ────────────────────────


def _cfg_and_valid_bundle_for_two_sources(tmp_path):
    """Builds two real source DatasetManifests, a combined train/eval
    file pair, and a DatasetBundleManifest whose lineage checksums
    exactly match the current source manifests -- the normal, fully-
    bound multi-manifest success path, returned as
    (cfg, dataset_manifest_ids, dataset_bundle_id)."""
    manifest_a, manifest_b = _register_two_source_manifests(tmp_path)
    combined_train = tmp_path / "combined_train.jsonl"
    combined_eval = tmp_path / "combined_eval.jsonl"
    combined_train.write_text('{"text": "a-train"}\n{"text": "b-train"}\n')
    combined_eval.write_text('{"text": "a-eval"}\n{"text": "b-eval"}\n')

    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                train_checksum=manifest_b.train_checksum, eval_checksum=manifest_b.eval_checksum,
            ),
        ],
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="test-sha", creation_procedure="concatenation, seed=42", seed=42,
    )
    bundle.save()

    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(combined_train)
    cfg.eval_file = str(combined_eval)
    dataset_manifest_ids = ["orneur-genesis-combined-safety-calibration-v1", "orneur-genesis-v2-v1"]
    return cfg, dataset_manifest_ids, "orneur-genesis-bundle-v1"


def test_finetune_train_wrapper_forwards_dataset_bundle_id_through_real_entrypoint(tmp_path):
    """Defect A closure: start_training_run() has always accepted
    dataset_bundle_id, but orca.train.finetune.train() -- the real
    public training path -- had no parameter to forward one, so
    multi-manifest canonical training could never actually reach the
    DatasetBundleManifest path except via a direct (test-only) call to
    start_training_run(). This proves the REAL train() entrypoint: a
    canonical Genesis config + two source manifests + a valid
    DatasetBundleManifest + dataset_bundle_id reaches provenance
    creation successfully and fails only at the expected missing heavy
    training dependency boundary (this CPU test environment genuinely
    lacks unsloth/trl/datasets/peft/bitsandbytes)."""
    from orca.registry.training_run import list_runs
    from orca.train.finetune import train

    cfg, dataset_manifest_ids, dataset_bundle_id = _cfg_and_valid_bundle_for_two_sources(tmp_path)

    with pytest.raises(ImportError, match="Missing training dependencies"):
        train(
            cfg, on_log=lambda _msg: None,
            dataset_manifest_ids=dataset_manifest_ids,
            dataset_bundle_id=dataset_bundle_id,
        )

    runs = list_runs("orneur-genesis")
    assert len(runs) == 1
    run = runs[0]
    assert run.dataset_bundle_id == dataset_bundle_id
    assert set(run.dataset_manifest_ids) == set(dataset_manifest_ids)
    assert "train" in run.dataset_split_digests
    assert "validation" in run.dataset_split_digests
    assert "train" in run.dataset_snapshot_paths
    assert "validation" in run.dataset_snapshot_paths
    # The recorded digests are the run-scoped SNAPSHOT's digests (Phase
    # 21B.2 TOCTOU closure), not merely the bundle's own combined digest
    # -- verify the snapshot files actually exist and match.
    assert Path(run.dataset_snapshot_paths["train"]).exists()
    assert sha256_of_file(Path(run.dataset_snapshot_paths["train"])) == run.dataset_split_digests["train"]
    # Even on failure, the manifest already recorded what it would have used.
    assert run.failure_state is not None
    assert "ImportError" in run.failure_state


def test_finetune_train_wrapper_without_bundle_id_fails_before_dependency_loading(tmp_path):
    """Defect A closure, second half: the SAME multi-manifest call
    WITHOUT dataset_bundle_id must fail closed inside
    start_training_run()'s verify_dataset_binding() call -- BEFORE
    _train_impl()'s _check_deps() is ever reached, i.e. a
    DatasetBindingInvalid, never an ImportError. No TrainingRunManifest
    may be persisted for a run that was never even valid enough to
    start."""
    from orca.registry.training_run import list_runs
    from orca.train.finetune import train

    cfg, dataset_manifest_ids, _dataset_bundle_id = _cfg_and_valid_bundle_for_two_sources(tmp_path)

    with pytest.raises(DatasetBindingInvalid, match="dataset_bundle_id"):
        train(cfg, on_log=lambda _msg: None, dataset_manifest_ids=dataset_manifest_ids)

    assert list_runs("orneur-genesis") == []


def test_fail_training_run_never_creates_a_checkpoint(cfg_with_real_dataset):
    """A failure must never leave the registry looking as if a
    checkpoint succeeded -- no CheckpointRecord exists after a failure."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-fail-1",
    )

    fail_training_run(manifest, "simulated CUDA OOM")

    reloaded = TrainingRunManifest.load("run-fail-1")
    assert reloaded.end_time is not None
    assert reloaded.failure_state == "simulated CUDA OOM"
    assert reloaded.checkpoint_outputs == []

    with pytest.raises(FileNotFoundError):
        CheckpointRecord.load("run-fail-1")

    registry = ModelRegistry()
    assert registry.lookup_production("genesis") is None


# ── hostile-self-review finding: canonical model_id impersonation ──────


def test_generic_config_cannot_impersonate_genesis_via_canonical_model_id():
    """Found during this closure's own hostile self-review (spec §23's
    'can a generic experimental run impersonate Genesis?'): the reserved-
    name guard previously covered only legacy Ollama aliases (e.g.
    "orca-nano"), not each family's own canonical model_id
    ("orneur-genesis"). A generic (family=None) config could set
    model_name="orneur-genesis" directly and pass
    validate_training_identity() unrejected."""
    from orca.train.config import validate_training_identity

    cfg = TrainingConfig.preset("prosumer")  # family=None
    cfg.model_name = "orneur-genesis"
    cfg.base_model = "some/arbitrary-experimental-model"
    with pytest.raises(ValueError, match="reserved"):
        validate_training_identity(cfg)


def test_generic_config_cannot_impersonate_novus_or_aeternum_either():
    from orca.train.config import validate_training_identity

    for canonical_id in ("orneur-novus", "orneur-aeternum"):
        cfg = TrainingConfig.preset("prosumer")
        cfg.model_name = canonical_id
        cfg.base_model = "some/arbitrary-experimental-model"
        with pytest.raises(ValueError, match="reserved"):
            validate_training_identity(cfg)


# ── (§13) default-path bypass regression -- the primary Phase 21B.2 finding ──


def test_default_path_resolution_is_never_bypassed_by_canonical_training(monkeypatch, tmp_path):
    """The exact independent-audit bug: a canonical config with
    train_file="" / eval_file="" (the dataclass defaults) declaring a
    real dataset manifest ID must never produce a manifest with
    dataset_content_digests == {} -- either the default-resolved files
    are genuinely hashed, or the run fails closed. Reproduces the bug
    first (pre-fix behavior would have returned {}), then proves the
    fix."""
    import orca.train.config as train_config_mod

    formatted_dir = tmp_path / "formatted"
    formatted_dir.mkdir()
    monkeypatch.setattr(train_config_mod, "FORMATTED_DIR", formatted_dir)

    train_path = formatted_dir / "orca_llama3_train.jsonl"
    eval_path = formatted_dir / "orca_llama3_eval.jsonl"
    train_path.write_text('{"text": "default-path hello"}\n')
    eval_path.write_text('{"text": "default-path world"}\n')

    manifest = DatasetManifest(
        dataset_id="orneur-genesis-v2", version="v1", purpose="test fixture", source_paths=["test"],
        record_count=2, schema='{"text": str}', train_checksum=sha256_of_file(train_path),
        eval_checksum=sha256_of_file(eval_path), creation_code_sha="test-sha", filters_applied="none",
        deduplication_result="0 duplicates",
    )
    manifest.save()

    cfg = TrainingConfig.preset("nano")
    assert cfg.train_file == "" and cfg.eval_file == ""  # the exact default-path scenario

    result = start_training_run(cfg, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu")

    assert result.dataset_content_digests != {}
    assert result.dataset_content_digests["train"] and result.dataset_content_digests["validation"]
    assert result.dataset_split_digests["train"] and result.dataset_split_digests["validation"]


def test_default_path_with_no_dataset_at_all_still_fails_closed():
    """Even with no data files anywhere, canonical training with an
    empty dataset_manifest_ids list must fail closed -- never silently
    accepted as a runnable manifest."""
    cfg = TrainingConfig.preset("nano")
    with pytest.raises(DatasetBindingInvalid):
        start_training_run(cfg, dataset_manifest_ids=[], hardware_info="test-cpu")


# ── (§14) TOCTOU snapshot tests ──────────────────────────────────────────


def test_create_run_snapshot_copies_and_hashes_files(tmp_path):
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    train_path.write_text('{"text": "a"}\n')
    eval_path.write_text('{"text": "b"}\n')

    info = create_run_snapshot("run-snap-1", train_path=train_path, eval_path=eval_path)
    assert Path(info["train"]["path"]).exists()
    assert Path(info["train"]["path"]) != train_path
    assert info["train"]["sha256"] == sha256_of_file(train_path)
    assert info["eval"]["sha256"] == sha256_of_file(eval_path)


def test_toctou_a_snapshot_is_unaffected_by_mutating_the_original_source(tmp_path):
    """(A) verify source -> create run snapshot -> mutate original
    source -> snapshot remains the bytes selected for the run."""
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    train_path.write_text('{"text": "original"}\n')
    eval_path.write_text('{"text": "original-eval"}\n')

    info = create_run_snapshot("run-snap-2", train_path=train_path, eval_path=eval_path)
    original_snapshot_hash = info["train"]["sha256"]

    train_path.write_text('{"text": "MUTATED AFTER SNAPSHOT"}\n')

    snapshot_content = Path(info["train"]["path"]).read_text()
    assert "MUTATED" not in snapshot_content
    assert sha256_of_file(Path(info["train"]["path"])) == original_snapshot_hash


def test_toctou_b_mutating_the_snapshot_itself_fails_preload_verification(tmp_path):
    """(B) verify snapshot -> mutate the snapshot itself before trainer
    load -> pre-load verification fails."""
    train_path = tmp_path / "train.jsonl"
    train_path.write_text('{"text": "original"}\n')

    info = create_run_snapshot("run-snap-3", train_path=train_path, eval_path=None)
    verify_run_snapshot(info)  # passes before mutation

    Path(info["train"]["path"]).write_text('{"text": "TAMPERED SNAPSHOT"}\n')

    with pytest.raises(SnapshotIntegrityError, match="modified after verification"):
        verify_run_snapshot(info)


def test_toctou_c_snapshot_failure_persists_and_creates_no_checkpoint(cfg_with_real_dataset):
    """(C) failure is persisted; no CheckpointRecord is created."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-snap-toctou-c",
    )
    # Tamper with the run-scoped snapshot itself (simulating a compromised
    # or buggy intermediate step) and verify the preload check catches it.
    Path(manifest.dataset_snapshot_paths["train"]).write_text('{"text": "TAMPERED"}\n')

    try:
        verify_run_snapshot({
            "train": {"path": manifest.dataset_snapshot_paths["train"], "sha256": manifest.dataset_split_digests["train"]},
            "eval": None,
        })
        raised = False
    except SnapshotIntegrityError as exc:
        raised = True
        fail_training_run(manifest, f"SnapshotIntegrityError: {exc}")

    assert raised
    reloaded = TrainingRunManifest.load("run-snap-toctou-c")
    assert reloaded.failure_state is not None
    assert reloaded.checkpoint_outputs == []
    with pytest.raises(FileNotFoundError):
        CheckpointRecord.load("run-snap-toctou-c")


def test_missing_snapshot_file_fails_preload_verification(tmp_path):
    train_path = tmp_path / "train.jsonl"
    train_path.write_text('{"text": "x"}\n')
    info = create_run_snapshot("run-snap-missing", train_path=train_path, eval_path=None)
    Path(info["train"]["path"]).unlink()
    with pytest.raises(SnapshotIntegrityError, match="missing"):
        verify_run_snapshot(info)


# ── (§2-8) Phase 21B.2.2: verified-source -> snapshot race closure ──────


def test_race_source_mutated_between_verification_and_snapshot_copy_is_detected(tmp_path):
    """(§8) The exact reproduced gap: verify_dataset_binding() computes a
    verified digest for the source file; the source is THEN mutated;
    create_run_snapshot() is called with that (now-stale) verified
    digest as its expectation. The snapshot copy would capture the
    MUTATED bytes -- must be detected and rejected, not silently
    recorded as if it were the verified content."""
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    train_path.write_text('{"text": "original-train"}\n')
    eval_path.write_text('{"text": "original-eval"}\n')
    _register_genesis_v2_manifest(train_path=train_path, eval_path=eval_path)

    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(train_path)
    cfg.eval_file = str(eval_path)

    # Step 1-3: real binding verification, obtaining the verified digest.
    verified_digests = verify_dataset_binding(cfg, dataset_manifest_ids=["orneur-genesis-v2-v1"])
    assert verified_digests["train"] == sha256_of_file(train_path)

    # Step 4: mutate the source BEFORE the snapshot copy happens.
    train_path.write_text('{"text": "MUTATED AFTER VERIFICATION, BEFORE SNAPSHOT"}\n')

    # Step 5: attempt snapshot creation with the (now-stale) verified digest
    # as the expectation the snapshot must satisfy.
    with pytest.raises(SnapshotIntegrityError, match="does not match the previously verified source digest"):
        create_run_snapshot(
            "run-race-1", train_path=train_path, eval_path=eval_path,
            expected_split_digests=verified_digests,
        )

    # The partial/untrustworthy snapshot directory must not be left behind.
    assert not (RUN_SNAPSHOT_DIR_FOR_TEST() / "run-race-1").exists()


def RUN_SNAPSHOT_DIR_FOR_TEST():
    from orca.registry.provenance import RUN_SNAPSHOT_DIR
    return RUN_SNAPSHOT_DIR


def test_race_through_real_start_training_run_creates_no_manifest(tmp_path, monkeypatch):
    """Same race, but exercised through the real start_training_run()
    path (not a direct create_run_snapshot() call) -- proving no
    runnable TrainingRunManifest is ever persisted, no CheckpointRecord
    exists, and no dependency/model loading is reachable, because the
    exception propagates out of start_training_run() before the
    manifest object is even constructed."""
    from orca.train.config import FORMATTED_DIR

    cfg_probe = TrainingConfig.preset("nano")
    train_path = FORMATTED_DIR / f"orca_{cfg_probe.data_format}_train.jsonl"
    eval_path = FORMATTED_DIR / f"orca_{cfg_probe.data_format}_eval.jsonl"
    train_path.write_text('{"text": "original-train"}\n')
    eval_path.write_text('{"text": "original-eval"}\n')
    _register_genesis_v2_manifest(train_path=train_path, eval_path=eval_path)

    cfg = TrainingConfig.preset("nano")  # default paths -- resolves to FORMATTED_DIR

    # Monkeypatch create_run_snapshot to mutate the source file the instant
    # it is called, simulating a real race between verification (already
    # completed by verify_dataset_binding() inside start_training_run())
    # and the snapshot copy.
    import orca.registry.provenance as provenance_mod
    real_create_run_snapshot = provenance_mod.create_run_snapshot

    def _racing_create_run_snapshot(run_id, *, train_path, eval_path, expected_split_digests=None):
        Path(train_path).write_text('{"text": "MUTATED DURING THE RACE WINDOW"}\n')
        return real_create_run_snapshot(
            run_id, train_path=train_path, eval_path=eval_path,
            expected_split_digests=expected_split_digests,
        )

    monkeypatch.setattr(provenance_mod, "create_run_snapshot", _racing_create_run_snapshot)

    from orca.registry.training_run import list_runs

    with pytest.raises(SnapshotIntegrityError):
        start_training_run(
            cfg, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
            run_id="run-race-2",
        )

    assert list_runs("orneur-genesis") == []
    with pytest.raises(FileNotFoundError):
        TrainingRunManifest.load("run-race-2")
    with pytest.raises(FileNotFoundError):
        CheckpointRecord.load("run-race-2")


# ── (§9) canonical-snapshot requirement tests ────────────────────────────


def test_canonical_create_snapshot_false_fails_closed(cfg_with_real_dataset):
    """(§9.A) A canonical (family-set) config explicitly passing
    create_snapshot=False must be rejected outright -- it can no longer
    obtain a "canonical" manifest with verified digests but no
    protected run-scoped snapshot."""
    with pytest.raises(SnapshotIntegrityError, match="create_snapshot=False is not permitted"):
        start_training_run(
            cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
            run_id="run-no-snapshot-canonical", create_snapshot=False,
        )


def _install_fake_training_deps(monkeypatch):
    """Installs minimal fake modules for the heavy training dependency
    stack (unsloth/trl/transformers/datasets/peft/bitsandbytes -- never
    really installed in this CPU-only environment) so a full
    _train_impl() call can execute past its _check_deps()/import lines.
    FastLanguageModel.from_pretrained() and datasets.load_dataset()
    both raise AssertionError if actually called, so a test using this
    helper positively proves those expensive steps were never reached
    when it expects an earlier failure."""
    for name in ("unsloth", "trl", "transformers", "datasets", "peft", "bitsandbytes"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    def _unreachable_model_load(**kwargs):
        raise AssertionError("FastLanguageModel.from_pretrained() was reached unexpectedly")

    def _unreachable_dataset_load(*args, **kwargs):
        raise AssertionError("datasets.load_dataset() was reached unexpectedly")

    sys.modules["unsloth"].FastLanguageModel = types.SimpleNamespace(
        from_pretrained=_unreachable_model_load, get_peft_model=lambda *a, **k: None,
    )
    sys.modules["trl"].SFTTrainer = object
    sys.modules["transformers"].TrainingArguments = object
    sys.modules["datasets"].load_dataset = _unreachable_dataset_load


def test_canonical_manifest_with_empty_snapshot_paths_fails_before_model_load(cfg_with_real_dataset, monkeypatch):
    """(§9.B) Even if a canonical manifest somehow has empty
    dataset_snapshot_paths (e.g. constructed directly, bypassing
    start_training_run()'s own guard), orca.train.finetune._train_impl()
    must independently refuse to fall back to mutable source files --
    defense in depth, not merely trusting the constructor-time guard.
    _install_fake_training_deps() proves this happens BEFORE any model
    load: FastLanguageModel.from_pretrained() would raise AssertionError
    if it were ever reached, but SnapshotIntegrityError is raised first."""
    _install_fake_training_deps(monkeypatch)
    from orca.train.finetune import _train_impl

    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-empty-snapshot-paths",
    )
    # Simulate a canonical manifest that somehow lost its snapshot paths
    # (e.g. a future code path that forgets to populate them).
    manifest.dataset_snapshot_paths = {}

    with pytest.raises(SnapshotIntegrityError, match="requires a verified run snapshot"):
        _train_impl(cfg_with_real_dataset, lambda _msg: None, manifest)


def test_dataset_resolution_and_snapshot_verification_precede_base_model_load(cfg_with_real_dataset, monkeypatch):
    """(§7) Positive ordering proof, not just the fail-closed case above:
    for a VALID canonical snapshot, _train_impl() must resolve/verify
    and load the dataset BEFORE calling
    FastLanguageModel.from_pretrained() on the success path too."""
    call_order: list[str] = []

    for name in ("unsloth", "trl", "transformers", "datasets", "peft", "bitsandbytes"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    def fake_from_pretrained(**kwargs):
        call_order.append("model_load")
        raise RuntimeError("stop here -- ordering proof only, not full training")

    def fake_load_dataset(*args, **kwargs):
        call_order.append("dataset_load")
        return {"train": [1, 2], "validation": [1]}

    sys.modules["unsloth"].FastLanguageModel = types.SimpleNamespace(
        from_pretrained=fake_from_pretrained, get_peft_model=lambda *a, **k: None,
    )
    sys.modules["trl"].SFTTrainer = object
    sys.modules["transformers"].TrainingArguments = object
    sys.modules["datasets"].load_dataset = fake_load_dataset

    from orca.train.finetune import _train_impl

    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-ordering-proof",
    )

    with pytest.raises(RuntimeError, match="stop here"):
        _train_impl(cfg_with_real_dataset, lambda _msg: None, manifest)

    assert call_order == ["dataset_load", "model_load"]


def test_canonical_snapshot_with_digest_equal_to_manifest_is_accepted(cfg_with_real_dataset):
    """(§9.C) The normal, fully-verified canonical path: snapshot digest
    equals the manifest's own dataset_content_digests -- accepted."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-snapshot-matches-manifest",
    )
    assert manifest.dataset_split_digests["train"] == manifest.dataset_content_digests["train"]
    assert manifest.dataset_split_digests["validation"] == manifest.dataset_content_digests["validation"]
    # verify_run_snapshot() (the pre-load check _train_impl() performs)
    # must accept this snapshot without raising.
    verify_run_snapshot({
        "train": {"path": manifest.dataset_snapshot_paths["train"], "sha256": manifest.dataset_split_digests["train"]},
        "eval": {"path": manifest.dataset_snapshot_paths["validation"], "sha256": manifest.dataset_split_digests["validation"]},
    })


def test_bundle_digest_equals_source_digest_equals_snapshot_digest(tmp_path):
    """(§9.D) For a multi-manifest bundle run: bundle digest == verified
    source digest == snapshot digest, for every consumed split -- the
    full semantic chain the manifest is supposed to preserve."""
    manifest_a, manifest_b = _register_two_source_manifests(tmp_path)
    combined_train = tmp_path / "combined_train.jsonl"
    combined_eval = tmp_path / "combined_eval.jsonl"
    combined_train.write_text('{"text": "a-train"}\n{"text": "b-train"}\n')
    combined_eval.write_text('{"text": "a-eval"}\n{"text": "b-eval"}\n')

    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                train_checksum=manifest_b.train_checksum, eval_checksum=manifest_b.eval_checksum,
            ),
        ],
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="test-sha", creation_procedure="concat", seed=42,
    )
    bundle.save()

    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(combined_train)
    cfg.eval_file = str(combined_eval)

    manifest = start_training_run(
        cfg, dataset_manifest_ids=["orneur-genesis-combined-safety-calibration-v1", "orneur-genesis-v2-v1"],
        hardware_info="test-cpu", run_id="run-bundle-chain", dataset_bundle_id="orneur-genesis-bundle-v1",
    )

    assert manifest.dataset_content_digests["train"] == bundle.train_checksum
    assert manifest.dataset_content_digests["validation"] == bundle.eval_checksum
    assert manifest.dataset_split_digests["train"] == bundle.train_checksum
    assert manifest.dataset_split_digests["validation"] == bundle.eval_checksum


def test_snapshot_train_split_off_by_one_byte_from_verified_source_is_rejected(tmp_path):
    """(§9.E) The snapshot's train digest differs from the verified
    source digest by even a single byte of drift -- must be rejected,
    not merely "close enough"."""
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    train_path.write_text('{"text": "content"}\n')
    eval_path.write_text('{"text": "eval-content"}\n')

    real_train_digest = sha256_of_file(train_path)
    real_eval_digest = sha256_of_file(eval_path)
    # A single-character-different (but still well-formed) fake "verified"
    # train digest -- simulates the snapshot's actual bytes not matching
    # what was verified, without needing a real race window.
    tampered_expected = ("f" if real_train_digest[0] != "f" else "0") + real_train_digest[1:]

    with pytest.raises(SnapshotIntegrityError, match="train snapshot digest"):
        create_run_snapshot(
            "run-off-by-one-train", train_path=train_path, eval_path=eval_path,
            expected_split_digests={"train": tampered_expected, "validation": real_eval_digest},
        )


def test_snapshot_validation_split_off_by_one_byte_from_verified_source_is_rejected(tmp_path):
    """(§9.F) Same as above, but the validation split's digest is the
    one that drifts from the verified expectation."""
    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "eval.jsonl"
    train_path.write_text('{"text": "content"}\n')
    eval_path.write_text('{"text": "eval-content"}\n')

    real_train_digest = sha256_of_file(train_path)
    real_eval_digest = sha256_of_file(eval_path)
    tampered_expected = ("f" if real_eval_digest[0] != "f" else "0") + real_eval_digest[1:]

    with pytest.raises(SnapshotIntegrityError, match="validation snapshot digest"):
        create_run_snapshot(
            "run-off-by-one-eval", train_path=train_path, eval_path=eval_path,
            expected_split_digests={"train": real_train_digest, "validation": tampered_expected},
        )


def test_generic_config_remains_explicitly_noncanonical_and_cannot_register_as_native_family(tmp_path):
    """(§9.G) A generic (family=None) config may still disable the
    snapshot (create_snapshot=False) -- explicitly noncanonical, never
    silently promoted to look like Genesis/Novus/Aeternum. Combined with
    the pre-existing RESERVED_NATIVE_MODEL_NAMES guard (Phase 21B.2),
    such a config still cannot register its output under a canonical
    native model_id."""
    cfg = TrainingConfig.preset("prosumer")  # family=None
    assert cfg.family is None

    # A generic config may still disable the snapshot without being
    # rejected -- this is explicitly permitted (unlike canonical family
    # configs, which are rejected by test_canonical_create_snapshot_false_fails_closed).
    manifest = start_training_run(
        cfg, dataset_manifest_ids=[], hardware_info="test-cpu",
        run_id="run-generic-no-snapshot", create_snapshot=False,
    )
    assert manifest.dataset_snapshot_paths == {}
    assert manifest.model_id == cfg.model_name  # not a canonical orneur-* model_id

    # And it still cannot impersonate a canonical family by name (Phase
    # 21B.2 regression, re-verified here in the same no-snapshot context).
    from orca.train.config import validate_training_identity

    cfg.model_name = "orneur-genesis"
    with pytest.raises(ValueError, match="reserved"):
        validate_training_identity(cfg)


# ── (§15) multi-manifest / dataset bundle tests ─────────────────────────


def _register_two_source_manifests(tmp_path):
    a_train, a_eval = tmp_path / "a_train.jsonl", tmp_path / "a_eval.jsonl"
    b_train, b_eval = tmp_path / "b_train.jsonl", tmp_path / "b_eval.jsonl"
    for p, content in [(a_train, "a-train"), (a_eval, "a-eval"), (b_train, "b-train"), (b_eval, "b-eval")]:
        p.write_text(f'{{"text": "{content}"}}\n')

    manifest_a = DatasetManifest(
        dataset_id="orneur-genesis-combined-safety-calibration", version="v1", purpose="t", source_paths=["t"],
        record_count=1, schema='{"text": str}', train_checksum=sha256_of_file(a_train),
        eval_checksum=sha256_of_file(a_eval), creation_code_sha="t", filters_applied="t", deduplication_result="t",
    )
    manifest_a.save()
    manifest_b = DatasetManifest(
        dataset_id="orneur-genesis-v2", version="v1", purpose="t", source_paths=["t"],
        record_count=1, schema='{"text": str}', train_checksum=sha256_of_file(b_train),
        eval_checksum=sha256_of_file(b_eval), creation_code_sha="t", filters_applied="t", deduplication_result="t",
    )
    manifest_b.save()
    return manifest_a, manifest_b


def test_multi_manifest_without_bundle_fails_closed_even_though_sources_exist(tmp_path):
    """Both source manifests genuinely exist, and some combined JSONL is
    supplied -- but WITHOUT a valid DatasetBundleManifest, canonical
    training must fail closed (existence-only is no longer accepted)."""
    manifest_a, manifest_b = _register_two_source_manifests(tmp_path)
    combined_train = tmp_path / "combined_train.jsonl"
    combined_eval = tmp_path / "combined_eval.jsonl"
    combined_train.write_text('{"text": "a-train"}\n{"text": "b-train"}\n')
    combined_eval.write_text('{"text": "a-eval"}\n{"text": "b-eval"}\n')

    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(combined_train)
    cfg.eval_file = str(combined_eval)

    with pytest.raises(DatasetBindingInvalid, match="dataset_bundle_id"):
        verify_dataset_binding(
            cfg,
            dataset_manifest_ids=["orneur-genesis-combined-safety-calibration-v1", "orneur-genesis-v2-v1"],
        )


def test_multi_manifest_with_valid_bundle_passes(tmp_path):
    manifest_a, manifest_b = _register_two_source_manifests(tmp_path)
    combined_train = tmp_path / "combined_train.jsonl"
    combined_eval = tmp_path / "combined_eval.jsonl"
    combined_train.write_text('{"text": "a-train"}\n{"text": "b-train"}\n')
    combined_eval.write_text('{"text": "a-eval"}\n{"text": "b-eval"}\n')

    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                train_checksum=manifest_b.train_checksum, eval_checksum=manifest_b.eval_checksum,
            ),
        ],
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="test-sha", creation_procedure="concatenation, seed=42", seed=42,
    )
    bundle.save()

    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(combined_train)
    cfg.eval_file = str(combined_eval)

    digests = verify_dataset_binding(
        cfg,
        dataset_manifest_ids=["orneur-genesis-combined-safety-calibration-v1", "orneur-genesis-v2-v1"],
        dataset_bundle_id="orneur-genesis-bundle-v1",
    )
    assert digests["train"] == bundle.train_checksum
    assert digests["validation"] == bundle.eval_checksum


def test_multi_manifest_bundle_rejects_mutated_combined_file(tmp_path):
    manifest_a, manifest_b = _register_two_source_manifests(tmp_path)
    combined_train = tmp_path / "combined_train.jsonl"
    combined_eval = tmp_path / "combined_eval.jsonl"
    combined_train.write_text('{"text": "a-train"}\n{"text": "b-train"}\n')
    combined_eval.write_text('{"text": "a-eval"}\n{"text": "b-eval"}\n')

    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                train_checksum=manifest_b.train_checksum, eval_checksum=manifest_b.eval_checksum,
            ),
        ],
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="test-sha", creation_procedure="concatenation", seed=42,
    )
    bundle.save()

    combined_train.write_text('{"text": "a-train"}\n{"text": "TAMPERED"}\n')

    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(combined_train)
    cfg.eval_file = str(combined_eval)

    with pytest.raises(DatasetBindingInvalid, match="failed binding verification"):
        verify_dataset_binding(
            cfg,
            dataset_manifest_ids=["orneur-genesis-combined-safety-calibration-v1", "orneur-genesis-v2-v1"],
            dataset_bundle_id="orneur-genesis-bundle-v1",
        )


def test_bundle_lineage_mismatch_is_rejected(tmp_path):
    """A bundle whose recorded source lineage doesn't match the
    dataset_manifest_ids actually declared for this run must be
    rejected -- prevents a bundle built for different sources from
    being silently reused."""
    manifest_a, manifest_b = _register_two_source_manifests(tmp_path)
    combined_train = tmp_path / "combined_train.jsonl"
    combined_eval = tmp_path / "combined_eval.jsonl"
    combined_train.write_text("x\n")
    combined_eval.write_text("y\n")

    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                train_checksum=manifest_b.train_checksum, eval_checksum=manifest_b.eval_checksum,
            ),
        ],  # only ONE source, but the run below declares two
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=1, creation_code_sha="t", creation_procedure="t",
    )
    bundle.save()

    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(combined_train)
    cfg.eval_file = str(combined_eval)

    with pytest.raises(DatasetBindingInvalid, match="lineage"):
        verify_dataset_binding(
            cfg,
            dataset_manifest_ids=["orneur-genesis-combined-safety-calibration-v1", "orneur-genesis-v2-v1"],
            dataset_bundle_id="orneur-genesis-bundle-v1",
        )


# ── (§4-6) bundle source-manifest lineage checksum enforcement ──────────
# Distinct from test_bundle_lineage_mismatch_is_rejected above (which
# covers the SOURCE-ID-SET mismatch case): these tests cover the case
# where the source ID set matches exactly, but the per-source content
# CHECKSUMS the bundle recorded no longer match (or never matched) that
# source manifest's actual current checksums.


def _valid_two_source_bundle(tmp_path):
    """Two real source manifests + a combined file pair + a
    DatasetBundleManifest whose lineage checksums are, at this point,
    exactly correct -- the baseline every test below perturbs."""
    manifest_a, manifest_b = _register_two_source_manifests(tmp_path)
    combined_train = tmp_path / "combined_train.jsonl"
    combined_eval = tmp_path / "combined_eval.jsonl"
    combined_train.write_text('{"text": "a-train"}\n{"text": "b-train"}\n')
    combined_eval.write_text('{"text": "a-eval"}\n{"text": "b-eval"}\n')

    dataset_manifest_ids = ["orneur-genesis-combined-safety-calibration-v1", "orneur-genesis-v2-v1"]
    cfg = TrainingConfig.preset("nano")
    cfg.train_file = str(combined_train)
    cfg.eval_file = str(combined_eval)
    return manifest_a, manifest_b, cfg, dataset_manifest_ids, combined_train, combined_eval


def test_bundle_lineage_rejects_source_manifest_mutated_after_bundle_built_train_checksum(tmp_path):
    """(§6.B) Same source ID, but the on-disk source DatasetManifest's
    train_checksum was replaced/mutated AFTER the bundle recorded its
    lineage -- must FAIL, proving a source manifest cannot be silently
    swapped under the same id without invalidating the bundle's lineage
    claim."""
    manifest_a, manifest_b, cfg, dataset_manifest_ids, combined_train, combined_eval = (
        _valid_two_source_bundle(tmp_path)
    )
    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                train_checksum=manifest_b.train_checksum, eval_checksum=manifest_b.eval_checksum,
            ),
        ],
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="t", creation_procedure="t", seed=42,
    )
    bundle.save()

    # Mutate source manifest A's train_checksum on disk AFTER the bundle
    # was built -- same dataset_id/version, different recorded checksum
    # (simulates the source manifest being silently replaced/regenerated).
    manifest_a.train_checksum = "f" * 64
    manifest_a.save()

    with pytest.raises(DatasetBindingInvalid, match="train_checksum"):
        verify_dataset_binding(cfg, dataset_manifest_ids=dataset_manifest_ids, dataset_bundle_id="orneur-genesis-bundle-v1")


def test_bundle_lineage_rejects_source_manifest_mutated_after_bundle_built_eval_checksum(tmp_path):
    """(§6.C) Same as above, but the eval_checksum was mutated."""
    manifest_a, manifest_b, cfg, dataset_manifest_ids, combined_train, combined_eval = (
        _valid_two_source_bundle(tmp_path)
    )
    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                train_checksum=manifest_b.train_checksum, eval_checksum=manifest_b.eval_checksum,
            ),
        ],
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="t", creation_procedure="t", seed=42,
    )
    bundle.save()

    manifest_b.eval_checksum = "e" * 64
    manifest_b.save()

    with pytest.raises(DatasetBindingInvalid, match="eval_checksum"):
        verify_dataset_binding(cfg, dataset_manifest_ids=dataset_manifest_ids, dataset_bundle_id="orneur-genesis-bundle-v1")


def test_bundle_lineage_rejects_duplicate_source_entry(tmp_path):
    """(§6.D) The same dataset_manifest_id appears twice in the bundle's
    own source_manifests lineage list -- must FAIL regardless of whether
    the declared dataset_manifest_ids set happens to match."""
    manifest_a, manifest_b, cfg, dataset_manifest_ids, combined_train, combined_eval = (
        _valid_two_source_bundle(tmp_path)
    )
    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
        ],  # duplicate entry; "orneur-genesis-v2-v1" never named at all
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="t", creation_procedure="t", seed=42,
    )
    bundle.save()

    with pytest.raises(DatasetBindingInvalid, match="duplicate"):
        verify_dataset_binding(cfg, dataset_manifest_ids=dataset_manifest_ids, dataset_bundle_id="orneur-genesis-bundle-v1")


def test_bundle_lineage_rejects_malformed_digest(tmp_path):
    """(§6.E) A lineage entry's checksum is not a real sha256 hex
    digest -- must FAIL rather than attempt a (meaningless) comparison."""
    manifest_a, manifest_b, cfg, dataset_manifest_ids, combined_train, combined_eval = (
        _valid_two_source_bundle(tmp_path)
    )
    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum="not-a-real-sha256-digest", eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                train_checksum=manifest_b.train_checksum, eval_checksum=manifest_b.eval_checksum,
            ),
        ],
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="t", creation_procedure="t", seed=42,
    )
    bundle.save()

    with pytest.raises(DatasetBindingInvalid, match="malformed"):
        verify_dataset_binding(cfg, dataset_manifest_ids=dataset_manifest_ids, dataset_bundle_id="orneur-genesis-bundle-v1")


def test_bundle_lineage_rejects_wrong_digest_even_when_source_id_set_matches(tmp_path):
    """(§6.F) The bundle's source-ID SET matches the declared
    dataset_manifest_ids exactly (so the set-equality check alone would
    pass), but the recorded lineage digest for one source was simply
    wrong from the start (not a later mutation) -- must still FAIL."""
    manifest_a, manifest_b, cfg, dataset_manifest_ids, combined_train, combined_eval = (
        _valid_two_source_bundle(tmp_path)
    )
    bundle = DatasetBundleManifest(
        bundle_id="orneur-genesis-bundle", version="v1",
        source_manifests=[
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-combined-safety-calibration-v1",
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
            SourceManifestLineage(
                dataset_manifest_id="orneur-genesis-v2-v1",
                # Correct ID, but checksums swapped with manifest A's --
                # same set of IDs, wrong digest lineage.
                train_checksum=manifest_a.train_checksum, eval_checksum=manifest_a.eval_checksum,
            ),
        ],
        train_checksum=sha256_of_file(combined_train), eval_checksum=sha256_of_file(combined_eval),
        record_count=2, creation_code_sha="t", creation_procedure="t", seed=42,
    )
    bundle.save()

    assert {s.dataset_manifest_id for s in bundle.source_manifests} == set(dataset_manifest_ids)

    with pytest.raises(DatasetBindingInvalid, match="does not match"):
        verify_dataset_binding(cfg, dataset_manifest_ids=dataset_manifest_ids, dataset_bundle_id="orneur-genesis-bundle-v1")


# ── (§16) checkpoint structural completeness tests ──────────────────────


def _minimal_unsharded_checkpoint(d: Path) -> None:
    (d / "config.json").write_text("{}")
    (d / "tokenizer.json").write_text("{}")
    (d / "model.safetensors").write_bytes(b"weights")


def _minimal_sharded_checkpoint(d: Path) -> None:
    import json as _json

    (d / "config.json").write_text("{}")
    (d / "tokenizer.json").write_text("{}")
    (d / "model-00001-of-00002.safetensors").write_bytes(b"shard1")
    (d / "model-00002-of-00002.safetensors").write_bytes(b"shard2")
    (d / "model.safetensors.index.json").write_text(_json.dumps({
        "weight_map": {"layer1": "model-00001-of-00002.safetensors", "layer2": "model-00002-of-00002.safetensors"}
    }))


def test_complete_unsharded_checkpoint_is_accepted(tmp_path):
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_unsharded_checkpoint(d)
    result = validate_checkpoint_artifact(d)
    assert result.valid


def test_complete_sharded_checkpoint_is_accepted(tmp_path):
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_sharded_checkpoint(d)
    result = validate_checkpoint_artifact(d)
    assert result.valid
    assert "model-00001-of-00002.safetensors" in result.files_validated
    assert "model-00002-of-00002.safetensors" in result.files_validated


def test_checkpoint_missing_config_is_rejected(tmp_path):
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_unsharded_checkpoint(d)
    (d / "config.json").unlink()
    with pytest.raises(CheckpointStructureInvalid, match="config.json"):
        validate_checkpoint_artifact(d)


def test_checkpoint_missing_tokenizer_is_rejected(tmp_path):
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_unsharded_checkpoint(d)
    (d / "tokenizer.json").unlink()
    with pytest.raises(CheckpointStructureInvalid, match="tokenizer"):
        validate_checkpoint_artifact(d)


def test_checkpoint_missing_weight_file_is_rejected(tmp_path):
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_unsharded_checkpoint(d)
    (d / "model.safetensors").unlink()
    with pytest.raises(CheckpointStructureInvalid, match="weight"):
        validate_checkpoint_artifact(d)


def test_checkpoint_one_referenced_shard_missing_is_rejected(tmp_path):
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_sharded_checkpoint(d)
    (d / "model-00002-of-00002.safetensors").unlink()
    with pytest.raises(CheckpointStructureInvalid, match="missing shard"):
        validate_checkpoint_artifact(d)


def test_checkpoint_malformed_index_is_rejected(tmp_path):
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_sharded_checkpoint(d)
    (d / "model.safetensors.index.json").write_text("NOT VALID JSON")
    with pytest.raises(CheckpointStructureInvalid, match="does not parse"):
        validate_checkpoint_artifact(d)


def test_checkpoint_index_with_empty_weight_map_is_rejected(tmp_path):
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_sharded_checkpoint(d)
    (d / "model.safetensors.index.json").write_text('{"weight_map": {}}')
    with pytest.raises(CheckpointStructureInvalid, match="weight_map"):
        validate_checkpoint_artifact(d)


def test_checkpoint_path_traversal_in_index_is_rejected(tmp_path):
    import json as _json
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_unsharded_checkpoint(d)
    (d / "model.safetensors.index.json").write_text(_json.dumps({"weight_map": {"layer1": "../../../etc/passwd"}}))
    with pytest.raises(CheckpointStructureInvalid, match="unsafe shard path"):
        validate_checkpoint_artifact(d)


def test_checkpoint_absolute_path_escape_in_index_is_rejected(tmp_path):
    import json as _json
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_unsharded_checkpoint(d)
    (d / "model.safetensors.index.json").write_text(_json.dumps({"weight_map": {"layer1": "/etc/passwd"}}))
    with pytest.raises(CheckpointStructureInvalid, match="unsafe shard path"):
        validate_checkpoint_artifact(d)


def test_checkpoint_identity_changes_when_shard_changes_but_validity_is_a_separate_concern(tmp_path):
    """Identity (hash_artifact_directory) and validity
    (validate_checkpoint_artifact) are deliberately separate -- both
    must independently agree a checkpoint is trustworthy."""
    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_sharded_checkpoint(d)
    from orca.registry.checkpoint import validate_checkpoint_artifact

    validate_checkpoint_artifact(d)  # structurally valid
    before = hash_artifact_directory(d)["manifest_digest"]

    (d / "model-00002-of-00002.safetensors").write_bytes(b"MUTATED")
    validate_checkpoint_artifact(d)  # still structurally valid (same files present)
    after = hash_artifact_directory(d)["manifest_digest"]
    assert before != after  # but identity changed


def test_complete_training_run_refuses_structurally_incomplete_checkpoint(tmp_path, cfg_with_real_dataset):
    """The core Phase 21B.2 checkpoint-registration guard: an artifact
    directory missing its tokenizer must never be registered, even
    though it would hash cleanly."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-incomplete-ckpt",
    )
    artifact_dir = tmp_path / "incomplete"
    artifact_dir.mkdir()
    (artifact_dir / "config.json").write_text("{}")
    (artifact_dir / "model.safetensors").write_bytes(b"weights")
    # tokenizer.json deliberately absent

    with pytest.raises(CheckpointStructureInvalid):
        complete_training_run(
            manifest, checkpoint_id="incomplete-checkpoint", artifact_path=str(artifact_dir),
            step_or_epoch="epoch=1", training_config_summary="t", tokenizer_identity="t",
        )

    registry = ModelRegistry()
    assert registry.lookup("incomplete-checkpoint") is None


def test_extra_harmless_file_is_accepted_and_documented(tmp_path):
    """An extra, non-required file (e.g. a README dropped into the
    checkpoint directory) does not fail structural validation -- only
    required files are checked; extras are harmlessly included in the
    identity digest but never required or forbidden."""
    from orca.registry.checkpoint import validate_checkpoint_artifact

    d = tmp_path / "ckpt"
    d.mkdir()
    _minimal_unsharded_checkpoint(d)
    (d / "README.md").write_text("notes")
    result = validate_checkpoint_artifact(d)
    assert result.valid
    # The extra file is not in files_validated (not required), but does
    # not block validation and would still appear in hash_artifact_directory().
    manifest = hash_artifact_directory(d)
    assert any(f["path"] == "README.md" for f in manifest["files"])


# ── (§7-13) checkpoint post-registration integrity closure ──────────────
# Phase 21B.2.1: CheckpointRecord.verify_integrity() previously called
# sha256_of_file() unconditionally, which disagreed with the directory
# manifest digest complete_training_run() actually registered for every
# merged (directory-backed) checkpoint. These tests exercise the real
# registration -> reload -> verify_integrity() lifecycle end to end, plus
# the fail-closed symlink-escape policy for every required checkpoint
# member (config, tokenizer, unsharded weight, shard).


def _register_complete_checkpoint(tmp_path, cfg_with_real_dataset, run_id: str):
    """Registers a real, structurally-complete directory checkpoint via
    the actual complete_training_run() path and returns
    (CheckpointRecord, artifact_dir)."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id=run_id,
    )
    artifact_dir = tmp_path / f"{run_id}-artifact"
    artifact_dir.mkdir()
    (artifact_dir / "config.json").write_text("{}")
    (artifact_dir / "tokenizer.json").write_text("{}")
    (artifact_dir / "model.safetensors").write_bytes(b"real-weights")

    record = complete_training_run(
        manifest, checkpoint_id=f"{run_id}-checkpoint", artifact_path=str(artifact_dir),
        step_or_epoch="epoch=1", training_config_summary="t", tokenizer_identity="t",
    )
    return record, artifact_dir


def test_registered_directory_checkpoint_reverifies_as_valid(tmp_path, cfg_with_real_dataset):
    """(§12.A) Register a complete directory checkpoint, reload the
    CheckpointRecord from disk (a fresh object, not the in-memory one
    complete_training_run() returned), and verify_integrity() must use
    the SAME canonical directory-manifest algorithm registration used --
    proving registration and reverification no longer disagree."""
    record, artifact_dir = _register_complete_checkpoint(tmp_path, cfg_with_real_dataset, "run-integrity-a")

    reloaded = CheckpointRecord.load(f"{record.checkpoint_id}")
    assert reloaded.verify_integrity(artifact_dir) is True
    assert reloaded.validation_state == "VALID"
    assert reloaded.availability == "LOCAL"


def test_registered_directory_checkpoint_detects_mutated_weight_byte(tmp_path, cfg_with_real_dataset):
    """(§12.B) A single mutated byte in the weight file after
    registration must be detected as CORRUPT, not silently pass or
    error out on "can't hash a directory"."""
    record, artifact_dir = _register_complete_checkpoint(tmp_path, cfg_with_real_dataset, "run-integrity-b")
    (artifact_dir / "model.safetensors").write_bytes(b"MUTATED-weights")

    reloaded = CheckpointRecord.load(record.checkpoint_id)
    with pytest.raises(CorruptCheckpointError):
        reloaded.verify_integrity(artifact_dir)
    assert reloaded.validation_state == "CORRUPT"


def test_registered_directory_checkpoint_detects_mutated_config(tmp_path, cfg_with_real_dataset):
    """(§12.C) A mutated config.json after registration must also be
    detected as CORRUPT."""
    record, artifact_dir = _register_complete_checkpoint(tmp_path, cfg_with_real_dataset, "run-integrity-c")
    (artifact_dir / "config.json").write_text('{"mutated": true}')

    reloaded = CheckpointRecord.load(record.checkpoint_id)
    with pytest.raises(CorruptCheckpointError):
        reloaded.verify_integrity(artifact_dir)
    assert reloaded.validation_state == "CORRUPT"


def test_registered_directory_checkpoint_detects_unexpected_added_file(tmp_path, cfg_with_real_dataset):
    """(§12.D) A file added to the artifact directory after registration
    changes the manifest digest -- must be detected as CORRUPT."""
    record, artifact_dir = _register_complete_checkpoint(tmp_path, cfg_with_real_dataset, "run-integrity-d")
    (artifact_dir / "unexpected-extra-file.bin").write_bytes(b"not part of the registered checkpoint")

    reloaded = CheckpointRecord.load(record.checkpoint_id)
    with pytest.raises(CorruptCheckpointError):
        reloaded.verify_integrity(artifact_dir)
    assert reloaded.validation_state == "CORRUPT"


def test_registered_directory_checkpoint_never_stays_valid_after_tokenizer_removed(tmp_path, cfg_with_real_dataset):
    """(§12.E) Removing the tokenizer after registration must never
    leave the checkpoint looking VALID -- the digest no longer matches
    (a required file is gone), so integrity verification fails closed."""
    record, artifact_dir = _register_complete_checkpoint(tmp_path, cfg_with_real_dataset, "run-integrity-e")
    (artifact_dir / "tokenizer.json").unlink()

    reloaded = CheckpointRecord.load(record.checkpoint_id)
    with pytest.raises(CorruptCheckpointError):
        reloaded.verify_integrity(artifact_dir)
    assert reloaded.validation_state != "VALID"


def test_registered_directory_checkpoint_survives_filesystem_creation_order(tmp_path, cfg_with_real_dataset):
    """(§12.K) Deterministic digest invariance under filesystem creation
    order, exercised through the real registration/reverification path
    (not just hash_artifact_directory() in isolation, as
    test_hash_artifact_directory_does_not_depend_on_filesystem_order
    already covers) -- registering the same file set in a different
    creation order must still verify as VALID against the same record."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-integrity-k",
    )
    artifact_dir = tmp_path / "order-artifact"
    artifact_dir.mkdir()
    # Deliberately reversed creation order vs _register_complete_checkpoint.
    (artifact_dir / "model.safetensors").write_bytes(b"real-weights")
    (artifact_dir / "tokenizer.json").write_text("{}")
    (artifact_dir / "config.json").write_text("{}")

    record = complete_training_run(
        manifest, checkpoint_id="run-integrity-k-checkpoint", artifact_path=str(artifact_dir),
        step_or_epoch="epoch=1", training_config_summary="t", tokenizer_identity="t",
    )
    reloaded = CheckpointRecord.load(record.checkpoint_id)
    assert reloaded.verify_integrity(artifact_dir) is True
    assert reloaded.validation_state == "VALID"


def _artifact_dir_with_symlink(tmp_path, run_label: str, *, symlink_name: str, other_required: dict[str, bytes]):
    """Builds an otherwise-complete checkpoint artifact directory where
    ONE required file (`symlink_name`) is a symlink pointing OUTSIDE the
    artifact root, and every other file in `other_required` is a normal
    regular file. Returns the artifact directory path."""
    outside_dir = tmp_path / f"{run_label}-outside"
    outside_dir.mkdir()
    outside_target = outside_dir / f"escaped-{symlink_name}"
    outside_target.write_bytes(b"content living outside the artifact root")

    artifact_dir = tmp_path / f"{run_label}-artifact"
    artifact_dir.mkdir()
    for name, content in other_required.items():
        (artifact_dir / name).write_bytes(content)
    (artifact_dir / symlink_name).symlink_to(outside_target)
    return artifact_dir


def test_config_symlink_outside_artifact_root_is_rejected(tmp_path, cfg_with_real_dataset):
    """(§12.F) config.json as a symlink escaping the artifact root must
    be rejected at registration -- never silently trusted."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-symlink-config",
    )
    artifact_dir = _artifact_dir_with_symlink(
        tmp_path, "symlink-config", symlink_name="config.json",
        other_required={"tokenizer.json": b"{}", "model.safetensors": b"weights"},
    )
    with pytest.raises(CheckpointStructureInvalid, match="symlink"):
        complete_training_run(
            manifest, checkpoint_id="symlink-config-checkpoint", artifact_path=str(artifact_dir),
            step_or_epoch="epoch=1", training_config_summary="t", tokenizer_identity="t",
        )
    assert ModelRegistry().lookup("symlink-config-checkpoint") is None


def test_tokenizer_symlink_outside_artifact_root_is_rejected(tmp_path, cfg_with_real_dataset):
    """(§12.G) tokenizer.json as an out-of-root symlink must be rejected."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-symlink-tokenizer",
    )
    artifact_dir = _artifact_dir_with_symlink(
        tmp_path, "symlink-tokenizer", symlink_name="tokenizer.json",
        other_required={"config.json": b"{}", "model.safetensors": b"weights"},
    )
    with pytest.raises(CheckpointStructureInvalid, match="symlink"):
        complete_training_run(
            manifest, checkpoint_id="symlink-tokenizer-checkpoint", artifact_path=str(artifact_dir),
            step_or_epoch="epoch=1", training_config_summary="t", tokenizer_identity="t",
        )
    assert ModelRegistry().lookup("symlink-tokenizer-checkpoint") is None


def test_unsharded_weight_symlink_outside_artifact_root_is_rejected(tmp_path, cfg_with_real_dataset):
    """(§12.H) An unsharded model.safetensors as an out-of-root symlink
    must be rejected."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-symlink-weight",
    )
    artifact_dir = _artifact_dir_with_symlink(
        tmp_path, "symlink-weight", symlink_name="model.safetensors",
        other_required={"config.json": b"{}", "tokenizer.json": b"{}"},
    )
    with pytest.raises(CheckpointStructureInvalid, match="symlink"):
        complete_training_run(
            manifest, checkpoint_id="symlink-weight-checkpoint", artifact_path=str(artifact_dir),
            step_or_epoch="epoch=1", training_config_summary="t", tokenizer_identity="t",
        )
    assert ModelRegistry().lookup("symlink-weight-checkpoint") is None


def test_shard_symlink_outside_artifact_root_is_rejected(tmp_path, cfg_with_real_dataset):
    """(§12.I) A shard file referenced by a shard index, itself a
    symlink escaping the artifact root, must be rejected -- both by the
    existing resolve()-based shard-escape check AND the blanket
    fail-closed symlink policy."""
    manifest = start_training_run(
        cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"], hardware_info="test-cpu",
        run_id="run-symlink-shard",
    )
    outside_dir = tmp_path / "symlink-shard-outside"
    outside_dir.mkdir()
    outside_shard = outside_dir / "escaped-shard.safetensors"
    outside_shard.write_bytes(b"shard content living outside the artifact root")

    artifact_dir = tmp_path / "symlink-shard-artifact"
    artifact_dir.mkdir()
    (artifact_dir / "config.json").write_text("{}")
    (artifact_dir / "tokenizer.json").write_text("{}")
    (artifact_dir / "model-00001-of-00001.safetensors").symlink_to(outside_shard)
    (artifact_dir / "model.safetensors.index.json").write_text(json.dumps({
        "weight_map": {"layer1": "model-00001-of-00001.safetensors"}
    }))

    with pytest.raises(CheckpointStructureInvalid, match="symlink"):
        complete_training_run(
            manifest, checkpoint_id="symlink-shard-checkpoint", artifact_path=str(artifact_dir),
            step_or_epoch="epoch=1", training_config_summary="t", tokenizer_identity="t",
        )
    assert ModelRegistry().lookup("symlink-shard-checkpoint") is None


def test_valid_ordinary_in_root_files_are_still_accepted_after_symlink_policy(tmp_path, cfg_with_real_dataset):
    """(§12.J) The new fail-closed symlink policy must not reject a
    perfectly ordinary checkpoint that contains no symlinks at all --
    exercised through the real registration path, complementing
    test_complete_training_run_registers_checkpoint_at_experimental_only."""
    record, artifact_dir = _register_complete_checkpoint(tmp_path, cfg_with_real_dataset, "run-ordinary-files")
    assert ModelRegistry().lookup(record.checkpoint_id) is not None
    reloaded = CheckpointRecord.load(record.checkpoint_id)
    assert reloaded.verify_integrity(artifact_dir) is True


def test_hash_artifact_directory_rejects_symlinks_directly_too(tmp_path):
    """hash_artifact_directory() applies the same fail-closed symlink
    policy independently of validate_checkpoint_artifact() -- so the
    hasher and the validator can never disagree, even if hash_artifact_directory()
    is ever called on a directory that skipped structural validation."""
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside content")
    d = tmp_path / "ckpt"
    d.mkdir()
    (d / "config.json").write_text("{}")
    (d / "tokenizer.json").write_text("{}")
    (d / "model.safetensors").symlink_to(outside)

    with pytest.raises(CheckpointStructureInvalid, match="symlink"):
        hash_artifact_directory(d)
