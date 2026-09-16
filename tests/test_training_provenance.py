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

from orca.registry.checkpoint import CheckpointRecord
from orca.registry.dataset_manifest import DatasetManifest
from orca.registry.model_registry import ModelRegistry
from orca.registry.model_spec import LifecycleState
from orca.registry.provenance import (
    DatasetBindingInvalid,
    complete_training_run,
    deterministic_run_id,
    fail_training_run,
    hash_artifact_directory,
    resolve_pinned_revisions,
    start_training_run,
    verify_dataset_binding,
)
from orca.registry.training_run import TrainingRunManifest
from orca.train.config import TrainingConfig


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


def test_verify_dataset_binding_rejects_missing_manifest():
    cfg = TrainingConfig.preset("nano")
    with pytest.raises(DatasetBindingInvalid, match="No dataset manifest found"):
        verify_dataset_binding(cfg, dataset_manifest_ids=["does-not-exist-v99"])


def test_verify_dataset_binding_verifies_real_matching_files(cfg_with_real_dataset):
    digests = verify_dataset_binding(cfg_with_real_dataset, dataset_manifest_ids=["orneur-genesis-v2-v1"])
    assert "orneur-genesis-v2-v1" in digests


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
    assert "orneur-genesis-v2-v1" in manifest.dataset_content_digests
    assert manifest.base_model_revision == "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"
    assert manifest.tokenizer_revision == "7548fff1f997f57b2e9e8ab1ec7be96949b00ed0"


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
