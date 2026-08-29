"""
Canonical model identity — the single source of truth this project has
lacked until now. Before this module existed, Genesis's base model was
declared independently in TWO places (orca/train/variants.py and
orca/train/config.py) and they silently disagreed: variants.py's own
docstring said Qwen2.5-3B while its actual code value was Qwen2.5-7B, and
config.py's preset independently said 3B. Forensic inspection of the
installed Ollama checkpoints (`ollama show orca-nano` / `orca-nano-v7`)
settled which one was real: 7.6B parameters, embedding length 3584 —
Qwen2.5-7B-class. See docs/orneur/phase-0/GENESIS_MODEL_IDENTITY.md.

This module is that single source of truth. orca/train/variants.py and
orca/train/config.py both resolve their base_model from MODEL_SPECS instead
of duplicating the literal, so this class of silent divergence can't
recur — see tests/test_registry_model_spec.py's
test_variants_and_config_agree_with_model_spec for the guard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LifecycleState(str, Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    TRAINED = "TRAINED"
    EVALUATING = "EVALUATING"
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    PRODUCTION = "PRODUCTION"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class ModelSpec:
    """
    A model FAMILY's canonical identity — not a specific trained checkpoint.
    A family can exist (this spec) with no trained checkpoint at all
    (Aeternum today) — see orca/registry/model_registry.py for the
    checkpoint layer that sits on top of this.
    """
    model_id: str            # e.g. "orneur-genesis" -- canonical machine identifier
    display_name: str        # e.g. "Orneur Genesis"
    family: str              # "genesis" | "novus" | "aeternum"
    role: str                # human-readable cognitive role
    base_model: str          # HuggingFace model ID used for fine-tuning
    parameter_class: str     # e.g. "3B", "8B", "70B" -- a class, not a measured count
    tokenizer: str           # tokenizer identity (same as base_model unless overridden)
    context_length: int
    architecture: str        # e.g. "qwen2", "llama"
    legacy_ollama_names: list[str] = field(default_factory=list)  # ORCA-era Ollama tags, for compatibility mapping only
    legacy_note: str = ""    # honest caveat about legacy artifacts under this family, if any


MODEL_SPECS: dict[str, ModelSpec] = {
    "genesis": ModelSpec(
        model_id="orneur-genesis",
        display_name="Orneur Genesis",
        family="genesis",
        role="fast cognition — routing, classification, extraction, retrieval planning, "
             "query rewriting, memory relevance, context compression, claim extraction, "
             "fast verification, lightweight reasoning",
        base_model="unsloth/Qwen2.5-3B-Instruct",
        parameter_class="3B",
        tokenizer="unsloth/Qwen2.5-3B-Instruct",
        context_length=4096,
        architecture="qwen2",
        legacy_ollama_names=["orca-nano", "orca-nano-v4", "orca-nano-v7"],
        legacy_note=(
            "All legacy orca-nano* Ollama checkpoints are forensically confirmed "
            "Qwen2.5-7B-class (7.6B params, embedding length 3584 -- see "
            "docs/orneur/phase-0/GENESIS_MODEL_IDENTITY.md), NOT this family's "
            "canonical 3B target. They are preserved as legacy artifacts, not "
            "relabeled, and must not be presented as the future Genesis architecture."
        ),
    ),
    "novus": ModelSpec(
        model_id="orneur-novus",
        display_name="Orneur Novus",
        family="novus",
        role="operational cognition — complex reasoning, coding, planning, tools, agents, "
             "multi-hop retrieval, evidence reconciliation, workflow execution",
        base_model="unsloth/Meta-Llama-3.1-8B-Instruct",
        parameter_class="8B",
        tokenizer="unsloth/Meta-Llama-3.1-8B-Instruct",
        context_length=8192,
        architecture="llama",
        legacy_ollama_names=["orca-core", "orca-core-dpo", "orca-core-combined"],
        legacy_note="Base model is unambiguous (Llama-3.1-8B) across all historical config sources.",
    ),
    "aeternum": ModelSpec(
        model_id="orneur-aeternum",
        display_name="Orneur Aeternum",
        family="aeternum",
        role="deep cognition — difficult ambiguity, deep synthesis, complex arbitration, "
             "cross-domain reasoning, difficult counterfactuals, advanced planning, "
             "advanced multi-agent coordination",
        base_model="unsloth/Meta-Llama-3.1-70B-Instruct",
        parameter_class="70B",
        tokenizer="unsloth/Meta-Llama-3.1-70B-Instruct",
        context_length=8192,
        architecture="llama",
        legacy_ollama_names=["orca-ultra"],
        legacy_note=(
            "No trained checkpoint exists for this family under any name, legacy "
            "or canonical -- 'orca-ultra' has never been fine-tuned. Base model "
            "above is the planned training target, not evidence of an existing run."
        ),
    ),
}


def get_spec(family: str) -> ModelSpec:
    key = family.removeprefix("orneur-").removeprefix("orca-")
    aliases = {"nano": "genesis", "core": "novus", "ultra": "aeternum"}
    key = aliases.get(key, key)
    if key not in MODEL_SPECS:
        raise ValueError(f"Unknown model family '{family}'. Available: {list(MODEL_SPECS)}")
    return MODEL_SPECS[key]
