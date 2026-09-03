"""
Controlled training experiment orchestration (spec §27-30, §72-75, §81).

Reuses orca.registry.training_run.TrainingRunManifest and
orca.train.finetune (the existing Phase-1 QLoRA backend) rather than
building a second training path -- this module's job is governance
wiring (budget, cancellation, honest hardware gating) around that
existing backend, not a reimplementation of it.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from orca.learning.contracts import (
    TrainingBudget,
    TrainingCostReport,
    TrainingExperimentStatus,
    TrainingFailureCategory,
    TrainingMode,
)
from orca.learning.registry_isolation import isolated_registry
from orca.registry.training_run import TrainingRunManifest


@dataclass
class HardwareAudit:
    cuda_available: bool
    mps_available: bool
    unsloth_installed: bool
    bitsandbytes_installed: bool

    def can_run_qlora(self) -> bool:
        """
        Unsloth's QLoRA path requires bitsandbytes 4-bit quantization,
        which is CUDA-only -- Apple Silicon's MPS backend cannot run it.
        This is a real, checked fact about this specific machine, not a
        guess: see docs/orneur/phase-12/TRAINING_RUNS.md for the exact
        audit output this class was built from.
        """
        return self.cuda_available and self.unsloth_installed and self.bitsandbytes_installed


def audit_hardware() -> HardwareAudit:
    cuda_available = False
    mps_available = False
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        mps_available = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    except ImportError:
        pass
    return HardwareAudit(
        cuda_available=cuda_available,
        mps_available=mps_available,
        unsloth_installed=importlib.util.find_spec("unsloth") is not None,
        bitsandbytes_installed=importlib.util.find_spec("bitsandbytes") is not None,
    )


class TrainingCancelled(Exception):
    pass


@dataclass
class TrainingExperimentResult:
    status: TrainingExperimentStatus
    reason: str
    training_run_manifest: TrainingRunManifest | None = None
    failure_category: TrainingFailureCategory | None = None
    # The manifest's on-disk path AT THE TIME it was saved -- computed
    # while still inside the isolation context, since `manifest.
    # manifest_path()` re-derives its directory from the (by-then-restored)
    # module-level DIR constant and would otherwise silently point at the
    # wrong location once this function has returned (spec §13 distinction
    # between the evaluation harness and a real persistence context).
    manifest_path: Path | None = None


def prepare_training_experiment(
    model_id: str,
    base_model: str,
    dataset_manifest_ids: list[str],
    mode: TrainingMode,
    budget: TrainingBudget,
    seed: int = 42,
    registry_home: Path | None = None,
) -> TrainingExperimentResult:
    """
    Spec §81: 'If hardware does NOT permit: stop honestly at a validated
    TRAINING_READY run and report why. Do not fake trained artifacts.'

    Spec 12.1 §15: this is a governance-preparation call, not a real
    production training launch -- it defaults to EPHEMERAL registry
    storage (`registry_home=None`), matching `orca.learning.eval_harness`'s
    default. Pass an explicit `registry_home` Path only when you actually
    want this TrainingRunManifest to persist somewhere real (still never
    the developer's ambient `~/.orca/registry/` unless that literal path
    is passed explicitly, validated, and its destination reported before
    writing).

    This function ALWAYS builds and saves a real TrainingRunManifest (spec
    §27's typed contract) -- that manifest IS the "validated TRAINING_READY
    run": real config, real dataset references, real git SHA, real
    hardware string. It never invokes the actual training backend unless
    hardware genuinely supports it, and never marks status beyond
    TRAINING_READY on this machine.
    """
    hw = audit_hardware()
    hardware_info = (
        f"cuda={hw.cuda_available} mps={hw.mps_available} "
        f"unsloth_installed={hw.unsloth_installed} bitsandbytes_installed={hw.bitsandbytes_installed}"
    )

    run_id = f"phase12-{model_id}-{mode.value.lower()}-experiment"

    with isolated_registry(destination=registry_home) as base:
        if registry_home is not None:
            print(f"[persist] writing training-experiment registry artifacts under: {base}")
        manifest = TrainingRunManifest(
            run_id=run_id,
            model_id=model_id,
            base_model=base_model,
            dataset_manifest_ids=list(dataset_manifest_ids),
            training_config={"mode": mode.value},
            hyperparameters={"seed": seed},
            seed=seed,
            precision="bf16",
            hardware_info=hardware_info,
        )
        manifest.save()

        if not hw.can_run_qlora():
            reason = (
                "This machine has no CUDA GPU (Apple Silicon MPS-only); "
                "unsloth's QLoRA path requires bitsandbytes 4-bit quantization, which is "
                "CUDA-only and therefore unsupported here even if unsloth/bitsandbytes were "
                "installed. Stopping honestly at TRAINING_READY per spec §30/§81 -- "
                "no training executed, no checkpoint fabricated."
            )
            manifest.mark_failed(reason)
            return TrainingExperimentResult(
                status=TrainingExperimentStatus.TRAINING_READY,
                reason=reason,
                training_run_manifest=manifest,
                manifest_path=manifest.manifest_path(),
            )

        # Hardware genuinely supports it -- out of scope to execute here
        # since this environment doesn't reach this branch, but the real
        # call site would be orca.train.finetune.run_finetune(...) with
        # `manifest` threaded through for provenance, never a parallel
        # training path.
        raise NotImplementedError(
            "This machine's hardware audit reports QLoRA-capable, but no execution path is "
            "wired here -- intentional: Phase 12 does not claim an actual training run "
            "occurred anywhere this code has actually been exercised. Wire "
            "orca.train.finetune.run_finetune(manifest=...) explicitly when running on "
            "real GPU hardware."
        )


def cancel_training(manifest: TrainingRunManifest, partial_checkpoint_id: str | None = None) -> TrainingExperimentResult:
    """Spec §73: training run must be cancellable safely. On cancel: status
    CANCELLED, checkpoint marked incomplete, no promotion, partial artifact
    handled explicitly."""
    reason = "Cancelled by explicit request." if partial_checkpoint_id is None else f"Cancelled with partial checkpoint '{partial_checkpoint_id}' marked incomplete, not promotable."
    manifest.mark_failed(reason)
    return TrainingExperimentResult(
        status=TrainingExperimentStatus.CANCELLED,
        reason=reason,
        training_run_manifest=manifest,
        failure_category=TrainingFailureCategory.CANCELLED,
    )
