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

from orca.registry.checkpoint import CheckpointRecord, CheckpointStructureInvalid
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
