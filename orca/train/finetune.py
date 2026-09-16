"""
Orca Fine-Tuner — QLoRA training with Unsloth (2x faster, 60% less VRAM).

Pipeline:
1. Load base model with 4-bit quantization
2. Attach LoRA adapters to attention + MLP layers
3. Train on curated Orca conversations
4. Save merged model ready for GGUF export

Run:
    orca train run --preset prosumer
    orca train run --preset cloud --epochs 5
"""
from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Callable

from orca.train.config import TrainingConfig, MODELS_DIR, resolve_training_data_inputs
from orca.registry.provenance import complete_training_run, fail_training_run, start_training_run, verify_run_snapshot


def _check_deps():
    missing = []
    for pkg in ["unsloth", "trl", "transformers", "datasets", "peft", "bitsandbytes"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        raise ImportError(
            f"Missing training dependencies: {', '.join(missing)}\n"
            f"Run: pip install unsloth trl transformers datasets peft bitsandbytes accelerate"
        )


def train(
    cfg: TrainingConfig,
    on_log: Callable[[str], None] | None = None,
    dataset_manifest_ids: list[str] | None = None,
    dataset_bundle_id: str | None = None,
) -> dict:
    """
    Full QLoRA fine-tuning pipeline.
    Returns paths to saved model artifacts.

    Phase 21B reproducibility closure: a TrainingRunManifest is created
    and persisted BEFORE any model/dependency loading begins (so even a
    dependency-import failure is recorded, not silently lost), and is
    marked complete (with a real CheckpointRecord registered at
    EXPERIMENTAL lifecycle -- never auto-PROMOTABLE/PRODUCTION) or failed
    at every exit path. See orca/registry/provenance.py.

    Phase 21B.2.1: `dataset_bundle_id` is forwarded straight through to
    start_training_run() -- this is the ONLY path for a multi-manifest
    canonical run to actually use a DatasetBundleManifest through the
    real training entrypoint (start_training_run() already accepted this
    parameter, but this function previously had no way to pass it,
    making the bundle-provenance path unreachable from real training --
    see tests/test_training_provenance.py::
    test_finetune_train_wrapper_forwards_dataset_bundle_id_through_real_entrypoint).
    """
    log = on_log or print

    # validate_training_identity() is called by start_training_run() --
    # this is the mandatory first step, before ANY model/dependency work,
    # so a bad config never even gets far enough to create a manifest for
    # a run that could never have been legitimate. verify_dataset_binding()
    # (also inside start_training_run()) similarly runs -- and can raise
    # DatasetBindingInvalid -- before _check_deps() below is ever reached,
    # so a multi-manifest run missing its required dataset_bundle_id fails
    # closed before any dependency/model loading, not merely before training.
    manifest = start_training_run(
        cfg,
        dataset_manifest_ids=dataset_manifest_ids or [],
        hardware_info=f"{platform.system()} {platform.machine()}",
        dataset_bundle_id=dataset_bundle_id,
    )

    try:
        result = _train_impl(cfg, log, manifest)
    except Exception as exc:
        fail_training_run(manifest, f"{type(exc).__name__}: {exc}")
        raise
    return result


def _load_base_model_and_tokenizer(cfg: TrainingConfig, base_model_revision: str | None):
    """Isolated so the exact kwargs passed to Unsloth's real loader can
    be inspected/mocked in a CPU-safe test without importing unsloth --
    see tests/test_training_provenance.py::
    test_load_base_model_and_tokenizer_passes_pinned_revision_to_loader.
    Phase 21B.1 fix: `revision` is now always passed through (verified
    live against Unsloth's own from_pretrained() signature, which
    accepts `revision=None` and resolves it via HF's own revision
    mechanism) -- never silently resolves the repo's default branch for
    canonical (family-set) training, since resolve_pinned_revisions()
    already raised before this function is ever called if a canonical
    config had no pinned revision."""
    from unsloth import FastLanguageModel

    return FastLanguageModel.from_pretrained(
        model_name=cfg.base_model,
        max_seq_length=cfg.max_seq_length,
        dtype=None,
        load_in_4bit=cfg.load_in_4bit,
        revision=base_model_revision,
    )


def _train_impl(cfg: TrainingConfig, log: Callable[[str], None], manifest) -> dict:
    _check_deps()

    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments
    from datasets import load_dataset

    log(f"[Train] Loading base model: {cfg.base_model} @ revision={manifest.base_model_revision or 'UNPINNED (generic config)'}")
    log(f"[Train] LoRA rank: {cfg.lora.r} | 4-bit: {cfg.load_in_4bit} | seq_len: {cfg.max_seq_length}")

    # ── Step 1: Load model + tokenizer, at the exact pinned revision ──────────
    model, tokenizer = _load_base_model_and_tokenizer(cfg, manifest.base_model_revision)

    # ── Step 2: Attach LoRA adapters ──────────────────────────────────────────
    log("[Train] Attaching LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=cfg.lora.r,
        target_modules=cfg.lora.target_modules,
        lora_alpha=cfg.lora.lora_alpha,
        lora_dropout=cfg.lora.lora_dropout,
        bias=cfg.lora.bias,
        use_gradient_checkpointing="unsloth",  # saves VRAM
        random_state=42,
    )

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    log(f"[Train] Trainable: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")

    # ── Step 3: Load dataset ───────────────────────────────────────────────────
    # Phase 21B.2: the trainer consumes ONLY the run-scoped snapshot
    # created by start_training_run() -- never the original (still-
    # mutable) source path -- and re-verifies the snapshot's digest
    # immediately before load_dataset(), closing the TOCTOU window
    # between provenance verification and actual training consumption.
    if manifest.dataset_snapshot_paths:
        verify_run_snapshot({
            "train": {"path": manifest.dataset_snapshot_paths["train"], "sha256": manifest.dataset_split_digests["train"]},
            "eval": (
                {"path": manifest.dataset_snapshot_paths["validation"], "sha256": manifest.dataset_split_digests["validation"]}
                if "validation" in manifest.dataset_snapshot_paths else None
            ),
        })
        train_file = manifest.dataset_snapshot_paths["train"]
        eval_file = manifest.dataset_snapshot_paths.get("validation")
    else:
        # Generic (family=None) experimental config -- no canonical
        # dataset binding/snapshot requirement; resolve the same way
        # verify_dataset_binding() would have, for consistency.
        resolved = resolve_training_data_inputs(cfg)
        train_file = str(resolved.train_path)
        eval_file = str(resolved.eval_path) if resolved.eval_path is not None else None

    if not Path(train_file).exists():
        raise FileNotFoundError(
            f"Training data not found: {train_file}\n"
            f"Run first: orca data curate && orca data format"
        )

    log(f"[Train] Loading dataset: {train_file}")
    data_files = {"train": train_file}
    if eval_file is not None and Path(eval_file).exists():
        data_files["validation"] = eval_file

    dataset = load_dataset("json", data_files=data_files)
    log(f"[Train] Train examples: {len(dataset['train'])}")

    # ── Step 4: Training arguments ─────────────────────────────────────────────
    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=cfg.num_epochs,
        per_device_train_batch_size=cfg.batch_size,
        gradient_accumulation_steps=cfg.gradient_accumulation_steps,
        learning_rate=cfg.learning_rate,
        warmup_ratio=cfg.warmup_ratio,
        lr_scheduler_type=cfg.lr_scheduler,
        weight_decay=cfg.weight_decay,
        max_grad_norm=cfg.max_grad_norm,
        fp16=cfg.fp16,
        bf16=cfg.bf16,
        logging_steps=cfg.logging_steps,
        save_steps=cfg.save_steps,
        eval_steps=cfg.eval_steps if "validation" in dataset else None,
        evaluation_strategy="steps" if "validation" in dataset else "no",
        save_total_limit=3,
        load_best_model_at_end=True if "validation" in dataset else False,
        report_to="wandb" if cfg.use_wandb else "none",
        run_name=cfg.model_name if cfg.use_wandb else None,
        dataloader_num_workers=2,
        group_by_length=True,   # pack similar-length sequences → faster
        seed=42,
    )

    # ── Step 5: Train ─────────────────────────────────────────────────────────
    log(f"[Train] Starting training for {cfg.num_epochs} epoch(s)...")
    start = time.time()

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset.get("validation"),
        dataset_text_field=cfg.dataset_text_field,
        max_seq_length=cfg.max_seq_length,
        args=training_args,
        packing=True,  # pack multiple short examples → higher GPU utilization
    )

    trainer_stats = trainer.train()
    elapsed = time.time() - start
    log(f"[Train] Done in {elapsed/60:.1f} min | loss: {trainer_stats.training_loss:.4f}")

    # ── Step 6: Save LoRA adapters ────────────────────────────────────────────
    adapter_path = output_dir / "lora_adapters"
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    log(f"[Train] LoRA adapters saved: {adapter_path}")

    # ── Step 7: Merge and save full model ─────────────────────────────────────
    log("[Train] Merging LoRA into base model (this takes a few minutes)...")
    merged_path = output_dir / "merged"
    model.save_pretrained_merged(
        str(merged_path),
        tokenizer,
        save_method="merged_16bit",
    )
    log(f"[Train] Merged model saved: {merged_path}")

    # Save training metadata
    meta = {
        "model_name": cfg.model_name,
        "base_model": cfg.base_model,
        "lora_rank": cfg.lora.r,
        "epochs": cfg.num_epochs,
        "train_loss": trainer_stats.training_loss,
        "duration_min": elapsed / 60,
        "adapter_path": str(adapter_path),
        "merged_path": str(merged_path),
    }
    with open(output_dir / "training_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Phase 21B.1: register a real CheckpointRecord for this run
    # (EXPERIMENTAL lifecycle only -- never auto-promoted) and mark the
    # manifest complete. checkpoint_id reuses cfg.model_name, matching
    # the existing convention of keeping the legacy/Ollama name as the
    # checkpoint identity. artifact_checksum is now a deterministic,
    # multi-file artifact-manifest digest over the ENTIRE merged_path
    # directory (config, tokenizer, every weight shard) -- computed
    # inside complete_training_run() via hash_artifact_directory(),
    # replacing the prior "hash the first file only" identity.
    complete_training_run(
        manifest,
        checkpoint_id=cfg.model_name,
        artifact_path=str(merged_path),
        step_or_epoch=f"epoch={cfg.num_epochs}",
        training_config_summary=f"QLoRA r={cfg.lora.r} alpha={cfg.lora.lora_alpha} seq_len={cfg.max_seq_length}",
        tokenizer_identity=cfg.base_model,
    )

    return meta
