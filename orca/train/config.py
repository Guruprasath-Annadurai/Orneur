"""
Orca Training Configuration — QLoRA hyperparameters and model selection.

Generic hardware-sizing presets (VRAM/batch-size/LoRA-rank only -- NOT tied
to any canonical Orneur model identity; TrainingConfig.family stays None):
- "laptop"   : RTX 3060/4060 (8GB VRAM)
- "prosumer" : RTX 4090 (24GB VRAM)
- "cloud"    : A100 40GB
- "cloud_xl" : A100 80GB -- LEGACY_EXPERIMENTAL, historical 70B preset kept
               for backwards compatibility only; does NOT produce a
               canonical Orneur Aeternum artifact (see its own preset
               comment below and orca/registry/model_spec.py)

Canonical Orneur family presets (TrainingConfig.family set; base_model
resolved from orca/registry/model_spec.py's MODEL_SPECS, the single source
of truth):
- "nano"  : Genesis
- "core"  : Novus
- "ultra" : Aeternum -- base_model resolves to None (UNSELECTED); any
            actual training attempt fails closed (see orca/train/finetune.py
            and orca/train/cloud.py) rather than silently substituting a
            default or legacy base model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry.model_spec import MODEL_SPECS

MODELS_DIR = ORCA_HOME / "models"
MODELS_DIR.mkdir(exist_ok=True)


@dataclass
class LoRAConfig:
    r: int = 64                      # LoRA rank (higher = more capacity, more VRAM)
    lora_alpha: int = 128            # scaling factor (usually 2x rank)
    lora_dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",   # MLP layers
    ])
    bias: str = "none"
    task_type: str = "CAUSAL_LM"


@dataclass
class TrainingConfig:
    # Base model. None means UNSELECTED (see orca/registry/model_spec.py's
    # base_model_status) -- e.g. preset("ultra") currently resolves to None
    # because Aeternum has no selected base model, and this must fail loudly
    # at actual training time rather than silently train toward a stale target.
    base_model: str | None = "unsloth/Meta-Llama-3.1-8B-Instruct"
    model_name: str = "orca-8b"

    # Canonical ORNEUR family this config trains, or None for a generic
    # hardware-sizing preset (laptop/prosumer/cloud/cloud_xl) that is NOT
    # tied to any Genesis/Novus/Aeternum identity. A compute-sizing preset
    # (VRAM/batch-size/LoRA-rank) must never be conflated with model
    # identity -- see orca/registry/model_spec.py for the actual identity.
    family: str | None = None
    # True for a historical/experimental preset kept for backwards
    # compatibility that must NOT be presented as producing a canonical
    # Orneur model artifact (e.g. "cloud_xl" -- see its own preset comment).
    is_legacy_experimental: bool = False

    # LoRA
    lora: LoRAConfig = field(default_factory=LoRAConfig)

    # Quantization
    load_in_4bit: bool = True
    bnb_4bit_compute_dtype: str = "bfloat16"
    bnb_4bit_quant_type: str = "nf4"
    use_double_quant: bool = True

    # Training
    max_seq_length: int = 4096
    batch_size: int = 2
    gradient_accumulation_steps: int = 8   # effective batch = 16
    num_epochs: int = 3
    learning_rate: float = 2e-4
    warmup_ratio: float = 0.05
    lr_scheduler: str = "cosine"
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0
    fp16: bool = False
    bf16: bool = True

    # Data
    data_format: str = "llama3"
    train_file: str = ""
    eval_file: str = ""
    dataset_text_field: str = "text"

    # Output
    output_dir: str = str(MODELS_DIR / "orca-8b-qlora")
    save_steps: int = 100
    eval_steps: int = 100
    logging_steps: int = 10

    # Wandb (optional)
    use_wandb: bool = False
    wandb_project: str = "orca-finetune"

    @classmethod
    def preset(cls, name: str) -> "TrainingConfig":
        cfg = cls()
        if name == "laptop":
            cfg.lora.r = 8
            cfg.lora.lora_alpha = 16
            cfg.batch_size = 1
            cfg.gradient_accumulation_steps = 16
            cfg.max_seq_length = 2048
            cfg.base_model = "unsloth/Meta-Llama-3.1-8B-Instruct"
        elif name == "prosumer":
            cfg.lora.r = 64
            cfg.lora.lora_alpha = 128
            cfg.batch_size = 4
            cfg.gradient_accumulation_steps = 4
        elif name == "cloud":
            cfg.lora.r = 128
            cfg.lora.lora_alpha = 256
            cfg.batch_size = 8
            cfg.gradient_accumulation_steps = 2
            cfg.base_model = "unsloth/Meta-Llama-3.1-8B-Instruct"
        elif name == "cloud_xl":
            # LEGACY_EXPERIMENTAL: a generic A100-80GB hardware-sizing preset,
            # kept for backwards compatibility, predating orca/registry/
            # model_spec.py's canonical Aeternum identity. It is NOT resolved
            # from MODEL_SPECS and must never be presented as producing a
            # canonical Orneur Aeternum artifact -- Aeternum's own base model
            # remains UNSELECTED (see preset("ultra") below and
            # orca/registry/model_spec.py). model_name/output_dir are
            # deliberately NOT "orca-ultra" so this preset's output can never
            # be mistaken for a canonical Aeternum checkpoint.
            cfg.base_model = "unsloth/Meta-Llama-3.1-70B-Instruct"
            cfg.lora.r = 64
            cfg.lora.lora_alpha = 128
            cfg.batch_size = 4
            cfg.load_in_4bit = True
            cfg.model_name = "legacy-cloud-xl-70b-experimental"
            cfg.is_legacy_experimental = True
            cfg.output_dir = str(MODELS_DIR / "legacy-cloud-xl-70b-experimental-qlora")
        # ── Orneur named variants ──────────────────────────────────────────────
        elif name == "nano":
            # Resolved from the single source of truth (orca/registry/model_spec.py)
            # -- see docs/orneur/phase-0/GENESIS_MODEL_IDENTITY.md for why this
            # literal must not be duplicated independently again.
            cfg.base_model = MODEL_SPECS["genesis"].base_model
            cfg.family = "genesis"
            cfg.model_name = "orca-nano"
            cfg.lora.r = 32
            cfg.lora.lora_alpha = 64
            cfg.batch_size = 4
            cfg.gradient_accumulation_steps = 4
            cfg.max_seq_length = 4096
            cfg.output_dir = str(MODELS_DIR / "orca-nano-qlora")
        elif name == "core":
            cfg.base_model = MODEL_SPECS["novus"].base_model
            cfg.family = "novus"
            cfg.model_name = "orca-core"
            cfg.lora.r = 64
            cfg.lora.lora_alpha = 128
            cfg.batch_size = 2
            cfg.gradient_accumulation_steps = 8
            cfg.max_seq_length = 8192
            cfg.output_dir = str(MODELS_DIR / "orca-core-qlora")
        elif name == "ultra":
            cfg.base_model = MODEL_SPECS["aeternum"].base_model
            cfg.family = "aeternum"
            cfg.model_name = "orca-ultra"
            cfg.lora.r = 64
            cfg.lora.lora_alpha = 128
            cfg.batch_size = 4
            cfg.load_in_4bit = True
            cfg.max_seq_length = 8192
            cfg.output_dir = str(MODELS_DIR / "orca-ultra-qlora")
        return cfg


def validate_training_identity(cfg: "TrainingConfig", *, artifact_name: str | None = None) -> None:
    """
    THE single canonical training-identity validation boundary (Phase 16
    final closure). Call this at every real execution boundary (before any
    model load, dependency import, SSH connection, or GPU work) -- never
    add another ad-hoc `if base_model is None` check elsewhere.

    Two, and only two, valid shapes:

    1. A CANONICAL family config (cfg.family is not None): base_model MUST
       equal exactly what orca.registry.model_spec.require_base_model()
       returns for that family. A canonical family's base model comes only
       from its ModelSpec -- manually overriding it (e.g. the CLI's
       `--model` option, or direct attribute mutation) must be rejected,
       not silently honored. This is the direct fix for the bypass where
       `TrainingConfig.preset("ultra")` (family="aeternum") could have its
       base_model manually set to an arbitrary string while keeping the
       Aeternum family identity.

    2. A GENERIC/experimental config (cfg.family is None): base_model must
       be explicitly set (not None) -- this is an intentionally
       noncanonical experiment, not a family-identified training run.

    `artifact_name` lets a caller (e.g. CloudTrainer, whose own `model_name`
    constructor parameter is a SEPARATE Ollama-registration identity from
    cfg.model_name) check the name that will actually be used to register
    the trained artifact, rather than only cfg.model_name. Defaults to
    cfg.model_name when not given.
    """
    import orca.registry.model_spec as model_spec_mod

    if cfg.family is not None:
        expected = model_spec_mod.require_base_model(cfg.family)  # raises if UNSELECTED
        if cfg.base_model != expected:
            raise ValueError(
                f"TrainingConfig.family={cfg.family!r} requires base_model={expected!r} "
                f"(from orca.registry.model_spec, the single source of truth) -- refusing "
                f"to train with a manually overridden base_model={cfg.base_model!r}. A "
                "canonical family config cannot override its selected base. If you need "
                "an arbitrary experimental base model, use a generic config (family=None) "
                "instead of overriding a canonical family preset."
            )
    else:
        if cfg.base_model is None:
            raise ValueError(
                "TrainingConfig.base_model is None and no family is set -- refusing to "
                "train with no base model selected and no canonical family to resolve one "
                "from."
            )

    name_to_check = artifact_name if artifact_name is not None else cfg.model_name
    if cfg.family is None and name_to_check in model_spec_mod.RESERVED_NATIVE_MODEL_NAMES:
        raise ValueError(
            f"Artifact name {name_to_check!r} is reserved for a canonical native Orneur "
            "family (see orca.registry.model_spec.RESERVED_NATIVE_MODEL_NAMES) and cannot "
            "be used to register a generic/legacy/experimental (family=None) training "
            "artifact -- this would let a non-canonical artifact impersonate a canonical "
            "Orneur model by naming alone."
        )
