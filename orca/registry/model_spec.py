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
    role: str                # human-readable cognitive specialization -- NOT a size tier
    base_model: str | None   # HuggingFace model ID used for fine-tuning, or None if UNSELECTED_PROVISIONAL
    parameter_class: str     # a PROVISIONAL research starting-point class (e.g. "3B", "8B", "~14B"),
                              # never a permanent ceiling -- scaling beyond it is permitted if empirical
                              # capability evaluation demonstrates the smaller candidate is insufficient
    tokenizer: str | None    # tokenizer identity (same as base_model unless overridden); None if unselected
    context_length: int
    architecture: str | None  # e.g. "qwen2", "llama"; None if unselected
    base_model_status: str = "SELECTED"  # "SELECTED" | "UNSELECTED_PROVISIONAL"
    provisional_parameter_hypothesis: str = ""  # only set when base_model_status is UNSELECTED_PROVISIONAL
    legacy_ollama_names: list[str] = field(default_factory=list)  # ORCA-era Ollama tags, for compatibility mapping only
    legacy_note: str = ""    # honest caveat about legacy artifacts under this family, if any


MODEL_SPECS: dict[str, ModelSpec] = {
    "genesis": ModelSpec(
        model_id="orneur-genesis",
        display_name="Orneur Genesis",
        family="genesis",
        role="Builder / Executor -- Executable Intelligence. Research question: how much "
             "reliable, verified agency and expert execution can be compressed into a fast "
             "intelligence? Fast execution, tool use, product building, coding, execution "
             "planning, repair, verification, consequence awareness, plus routing, "
             "classification, extraction, retrieval planning, query rewriting, memory "
             "relevance, context compression, claim extraction -- all on top of broad, "
             "cross-domain expert knowledge, not instead of it.",
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
        role="Reasoner / Investigator -- Epistemic-Causal Intelligence. Research question: "
             "can intelligence understand the boundary between what it knows, infers, "
             "doubts, disputes, and does not know -- and determine what evidence would "
             "resolve uncertainty? Deep reasoning, diagnosis, architecture, causal "
             "analysis, competing hypotheses, counterfactual reasoning, evidence seeking, "
             "uncertainty analysis, difficult debugging -- on top of broad, cross-domain "
             "expert knowledge, not confined to coding.",
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
        role="Critic / Arbiter / Discoverer -- Adversarial Discovery Intelligence. "
             "Research question: can intelligence systematically discover what other "
             "intelligent systems failed to notice? Falsification, adversarial reasoning, "
             "assumption attack, counterexample generation, arbitration, security review, "
             "scientific criticism, hypothesis generation, discovery, novel solution "
             "search -- on top of broad, cross-domain expert knowledge, not merely "
             "'Novus with more parameters'.",
        base_model=None,
        parameter_class="~14B",
        tokenizer=None,
        context_length=8192,
        architecture=None,
        base_model_status="UNSELECTED_PROVISIONAL",
        provisional_parameter_hypothesis=(
            "~14B is a provisional research starting-point hypothesis only, not a "
            "final or permanent size lock. Scaling beyond ~14B (or landing smaller) is "
            "explicitly permitted if empirical capability evaluation demonstrates the "
            "candidate is insufficient or sufficient respectively. No final base model "
            "has been selected for this family."
        ),
        legacy_ollama_names=["orca-ultra"],
        legacy_note=(
            "No trained checkpoint exists for this family under any name, legacy "
            "or canonical -- 'orca-ultra' has never been fine-tuned. The historical "
            "Llama-3.1-70B plan is LEGACY/STALE architecture, not the current owner "
            "architecture, and must not be treated as the canonical Aeternum training "
            "target. No final base model has been selected; see "
            "provisional_parameter_hypothesis for the current (non-binding) sizing "
            "hypothesis."
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


def require_base_model(family: str) -> str:
    """
    Fail-closed accessor for any future code path that actually needs a
    concrete base model to train or load (e.g. Phase 18+ training code).
    Raises rather than silently falling back to a stale/legacy literal --
    this is the direct fix for the Phase 16 closure finding that Aeternum's
    old Llama-3.1-70B plan could otherwise be silently treated as canonical.
    """
    spec = get_spec(family)
    if spec.base_model is None:
        raise ValueError(
            f"Model family '{spec.family}' has no selected base model "
            f"(status={spec.base_model_status}). Refusing to silently substitute "
            "a legacy or default model -- a base model must be explicitly chosen "
            "before this family can be trained."
        )
    return spec.base_model
