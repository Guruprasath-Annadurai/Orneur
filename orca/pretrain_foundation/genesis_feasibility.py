"""Phase 3 GENESIS technical feasibility assessment (analytical only).

No external weight download. No invented performance measurements.
No free-cloud-GPU frontier-training assumption. No official foundation
selection (DEC-K remains founder-controlled).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from orca.genesis.model.config import GenesisModelConfig
from orca.genesis.model.family_registry import default_registry
from orca.genesis.model.scaling import (
    CORRECTED_SCALING_TIERS,
    estimate_training_compute,
    estimate_training_memory,
    resolve_corrected_tier,
    theoretical_flops_per_token,
)
from orca.pretrain_foundation.compute_scenarios import frontier_pretraining_available, scenario


@dataclass(frozen=True)
class GenesisFeasibilityReport:
    architecture_version: str
    candidate_tier: str
    parameter_count: int
    max_seq_len: int
    vocab_size: int
    memory_total_bytes: int
    approx_training_flops_for_planning_tokens: float
    flops_per_token_approx: float
    tokenizer_status: str
    checkpoint_structure: str
    distributed_training: str
    inference_implications: str
    training_data_requirements: str
    available_compute: str
    licensing_initialization: str
    official_foundation_selected: bool
    weights_downloaded: bool
    frontier_pretraining_available: bool
    family_statuses: dict[str, str]
    engineering_disposition: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def assess_genesis(*, tier_name: str = "10M-smoke", batch_size: int = 1, seq_len: int = 512) -> GenesisFeasibilityReport:
    """Build a reproducible analytical assessment for a synthetic GENESIS tier."""
    tier = next(t for t in CORRECTED_SCALING_TIERS if t.name == tier_name)
    cfg: GenesisModelConfig = resolve_corrected_tier(tier)
    mem = estimate_training_memory(cfg, batch_size=batch_size, seq_len=min(seq_len, cfg.max_seq_len))
    # Planning tokens only — not a claim that this many tokens were trained.
    planning_tokens = 100_000
    # peak_flops is a datasheet placeholder for analytical seconds; MFU omitted (None).
    compute = estimate_training_compute(
        cfg,
        total_tokens=planning_tokens,
        peak_flops_per_second=1.0e14,  # arbitrary analytical denominator; not measured hardware
        measured_mfu=None,
    )
    families = default_registry()
    cpu = scenario("synthetic_cpu")
    blockers = (
        "DEC-K foundation selection not accepted",
        "MODEL-1 / MODEL-2R no authorized training identity/revision",
        "G8 / DATA-3 protected corpus grant absent",
        "G10 training permission absent",
        "No GPU provisioned; frontier_pretraining_available() is False",
        "No external weights downloaded (authorization required)",
    )
    return GenesisFeasibilityReport(
        architecture_version=cfg.architecture_version,
        candidate_tier=tier.name,
        parameter_count=cfg.total_parameters(),
        max_seq_len=cfg.max_seq_len,
        vocab_size=cfg.vocab_size,
        memory_total_bytes=mem.total,
        approx_training_flops_for_planning_tokens=float(compute.total_flops),
        flops_per_token_approx=float(theoretical_flops_per_token(cfg)),
        tokenizer_status="framework+robustness synthetic tests present; official tokenizer digest not frozen",
        checkpoint_structure="resumable synthetic checkpoint integrity + refusal paths implemented",
        distributed_training="not required for synthetic CPU; distributed correctness BLOCKED pending compute grant",
        inference_implications="INTERFACE_ONLY serving contract; live generate/deployable denied",
        training_data_requirements="synthetic fixtures only until G8; no user-conversation ingestion",
        available_compute=f"{cpu['id']}: {cpu['hardware']} (frontier_pretraining={frontier_pretraining_available()})",
        licensing_initialization="legal/licensing dossier owned by Claude; engineering does not select foundation",
        official_foundation_selected=False,
        weights_downloaded=False,
        frontier_pretraining_available=frontier_pretraining_available(),
        family_statuses={name: rec.status for name, rec in families.items()},
        engineering_disposition="PARTIAL_ENGINEERING — CORRECTIONS_REQUIRED",
        blockers=blockers,
    )


def family_status_snapshot() -> dict[str, str]:
    return {name: rec.status for name, rec in default_registry().items()}
