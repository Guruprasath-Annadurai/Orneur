"""
Training-run provenance wiring -- the mandatory lifecycle path connecting
TrainingConfig -> TrainingRunManifest -> (training happens) -> CheckpointRecord
-> ModelRegistry.register(). Phase 21B closes the gap identified in the
Phase 21A audit: TrainingRunManifest and CheckpointRecord both already
existed in code, but no real training entry point ever called them, so
`~/.orca/registry/training_runs/` was empty despite real historical
training having occurred (informally, via notebook filenames only).

Deliberately CPU-safe and import-light (no unsloth/torch/transformers) so
the full manifest/checkpoint/registry lifecycle -- including the failure
path -- can be unit-tested without a GPU or the heavy training dependency
stack. See tests/test_training_provenance.py and
orca/train/finetune.py::train() for the real (GPU-only) integration point.
"""
from __future__ import annotations

import hashlib
import time

from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord
from orca.registry.model_registry import ModelRegistry
from orca.registry.model_spec import MODEL_SPECS, get_spec
from orca.registry.training_run import TrainingRunManifest
from orca.train.config import TrainingConfig, validate_training_identity


def deterministic_run_id(cfg: TrainingConfig, *, nonce: str) -> str:
    """Deterministic given (cfg identity fields, nonce) -- never uuid4()
    or a bare wall-clock read alone. `nonce` is caller-supplied (e.g. a
    fresh timestamp or an explicit experiment label) so this function
    itself stays pure and testable; the real training path supplies a
    fresh nonce per invocation."""
    payload = f"{cfg.family}:{cfg.base_model}:{cfg.model_name}:{nonce}"
    return f"run-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def start_training_run(
    cfg: TrainingConfig,
    *,
    dataset_manifest_ids: list[str],
    hardware_info: str,
    run_id: str | None = None,
) -> TrainingRunManifest:
    """Creates and PERSISTS a TrainingRunManifest BEFORE any expensive
    training work begins -- the mandatory first step of the real training
    path. Fails closed via TrainingConfig's own validate_training_identity()
    (never silently trains a canonical family toward a manually-overridden
    base model, and never trains with base_model=None)."""
    validate_training_identity(cfg)

    resolved_run_id = run_id or deterministic_run_id(cfg, nonce=str(time.time_ns()))
    model_id = get_spec(cfg.family).model_id if cfg.family else cfg.model_name
    manifest = TrainingRunManifest(
        run_id=resolved_run_id,
        model_id=model_id,
        base_model=cfg.base_model,
        dataset_manifest_ids=list(dataset_manifest_ids),
        training_config={
            "preset_family": cfg.family,
            "is_legacy_experimental": cfg.is_legacy_experimental,
            "data_format": cfg.data_format,
        },
        hyperparameters={
            "lora_r": cfg.lora.r,
            "lora_alpha": cfg.lora.lora_alpha,
            "lora_dropout": cfg.lora.lora_dropout,
            "target_modules": list(cfg.lora.target_modules),
            "max_seq_length": cfg.max_seq_length,
            "batch_size": cfg.batch_size,
            "gradient_accumulation_steps": cfg.gradient_accumulation_steps,
            "num_epochs": cfg.num_epochs,
            "learning_rate": cfg.learning_rate,
            "lr_scheduler": cfg.lr_scheduler,
            "warmup_ratio": cfg.warmup_ratio,
            "weight_decay": cfg.weight_decay,
            "max_grad_norm": cfg.max_grad_norm,
        },
        seed=42,  # matches finetune.py's hardcoded TrainingArguments/get_peft_model seed
        precision="bf16" if cfg.bf16 else ("fp16" if cfg.fp16 else "fp32"),
        hardware_info=hardware_info,
    )
    manifest.save()
    return manifest


def complete_training_run(
    manifest: TrainingRunManifest,
    *,
    checkpoint_id: str,
    artifact_path: str,
    artifact_checksum: str,
    step_or_epoch: str,
    training_config_summary: str,
    tokenizer_identity: str,
) -> CheckpointRecord:
    """Records a CheckpointRecord for a successfully completed run and
    marks the manifest complete. Registers the checkpoint at EXPERIMENTAL
    lifecycle only (ModelRegistry.register()'s own default) -- training
    completion NEVER implies PROMOTABLE/PRODUCTION/AVAILABLE; those remain
    later, separately evidence-gated transitions via
    ModelRegistry.promote(), which itself refuses without a passing
    evaluation report."""
    record = CheckpointRecord(
        checkpoint_id=checkpoint_id,
        model_id=manifest.model_id,
        run_id=manifest.run_id,
        step_or_epoch=step_or_epoch,
        base_model=manifest.base_model,
        dataset_manifest_ids=manifest.dataset_manifest_ids,
        training_config_summary=training_config_summary,
        optimizer_state_available=False,
        scheduler_state_available=False,
        tokenizer_identity=tokenizer_identity,
        artifact_path=artifact_path,
        artifact_checksum=artifact_checksum,
        availability=ArtifactAvailability.LOCAL.value,
        availability_note="Registered immediately after training completion by orca.registry.provenance.",
    )
    record.save()

    family = _family_from_model_id(manifest.model_id)
    if family is not None:
        ModelRegistry().register(record, family=family)

    manifest.mark_complete(checkpoint_id)
    return record


def fail_training_run(manifest: TrainingRunManifest, reason: str) -> None:
    """Records a failed run. Never creates a CheckpointRecord on this
    path -- a failure must never leave the registry looking as if a
    checkpoint succeeded when the output is incomplete or absent."""
    manifest.mark_failed(reason)


def _family_from_model_id(model_id: str) -> str | None:
    prefix = "orneur-"
    if not model_id.startswith(prefix):
        return None
    candidate = model_id[len(prefix):]
    return candidate if candidate in MODEL_SPECS else None
