"""
Phase 21B.4.3 (spec section 8) -- ComputeResource: a capability contract
for wherever Genesis evaluation/inference actually runs, deliberately
decoupled from any specific vendor. Compute is replaceable
infrastructure; no cloud provider, GPU model, operating system, or
developer laptop may become part of Genesis's logical identity.

This module describes resource capability -- it does NOT provision,
create, or reserve any resource. Concrete provisioning clients (e.g. a
future RunPodResource, LambdaResource) can be added later without
touching this contract; this phase deliberately stops at the
descriptive layer per spec section 10 ("Do not provision anything").
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ComputeResource:
    """Describes what a compute resource CAN do, not who it is billed
    to. `provider` is metadata for humans/reporting only -- nothing in
    Genesis's evaluation/execution code should branch on it."""

    resource_id: str
    provider: str                      # human-readable label, e.g. "local", "runpod", "lambda-gpu-cloud", "modal" -- never used for branching logic
    accelerator_type: str | None       # e.g. "Apple M4 (MPS)", "NVIDIA RTX 4090", None if CPU-only
    accelerator_count: int
    accelerator_memory_gb: float | None  # VRAM (or unified memory, for MPS) per accelerator
    system_memory_gb: float
    storage_available_gb: float
    backend: str                       # "transformers" (matches orca.eval.runner.ModelAdapter implementations)
    device: str                        # "cpu" | "cuda" | "cuda:0" | "mps"
    cuda_version: str | None
    docker_available: bool
    supports_quantization: tuple[str, ...]  # subset of ("none", "8bit", "4bit")
    persistent: bool                   # False = ephemeral (state lost between sessions), True = persistent storage
    metadata: dict = field(default_factory=dict)

    def max_safe_model_vram_gb(self, safety_margin: float = 0.15) -> float | None:
        """Conservative VRAM budget after reserving a safety margin for
        CUDA allocator fragmentation, KV cache, and runtime overhead --
        mirrors the lesson learned in Phase 21B.4.2 where a naive
        'total capacity' budget did not survive contact with a real
        device-transfer allocation spike."""
        if self.accelerator_memory_gb is None:
            return None
        return self.accelerator_memory_gb * (1 - safety_margin)

    def qualifies_for(self, required_vram_gb: float, *, quantization: str, safety_margin: float = 0.15) -> bool:
        if quantization not in self.supports_quantization:
            return False
        budget = self.max_safe_model_vram_gb(safety_margin=safety_margin)
        if budget is None:
            return False
        return required_vram_gb <= budget


# Closed resource experiments / resource contracts recorded this phase.
# These are DESCRIPTIVE RECORDS of real findings or planning targets --
# not live provisioning, and not exhaustive of every possible resource.

LOCAL_M4_16GB = ComputeResource(
    resource_id="local-m4-16gb",
    provider="local",
    accelerator_type="Apple M4 (MPS)",
    accelerator_count=1,
    accelerator_memory_gb=16.0,  # unified memory, NOT dedicated VRAM -- shared with the host OS/other apps
    system_memory_gb=16.0,       # same physical pool as "accelerator_memory_gb" on Apple Silicon
    storage_available_gb=24.0,   # measured live, Phase 21B.4.2
    backend="transformers",
    device="mps",
    cuda_version=None,
    docker_available=True,
    supports_quantization=("none",),  # bitsandbytes 4-bit/8-bit is CUDA-only -- confirmed absent on MPS, Phase 21B.4.2
    persistent=True,
    metadata={
        "phase_closed": "21B.4.2",
        "verdict": "NOT_QUALIFIED",
        "reason": (
            "Empirically failed the model-load smoke test: system-wide free memory "
            "crashed 52%->25%->2% within ~20s during the .to('mps') device-transfer "
            "step for a 3.8B-class model at its only available precision (bfloat16, "
            "no working quantization path on MPS). A live watchdog killed the process "
            "before host instability. See docs/orneur/phase-21/"
            "PHASE21B4_2_RESOURCE_QUALIFICATION_CLOSURE.md. This resource is closed -- "
            "no further Genesis load attempts should be made against it per Phase "
            "21B.4.3 spec section 2."
        ),
    },
)

MINIMUM_VIABLE_CUDA_CONTRACT = ComputeResource(
    resource_id="cuda-minimum-viable-16gb",
    provider="unassigned",  # technical contract, not a provisioned resource -- see spec section 5
    accelerator_type="CUDA GPU, 16GB+ VRAM class (e.g. NVIDIA T4 16GB, RTX 4060 Ti 16GB)",
    accelerator_count=1,
    accelerator_memory_gb=16.0,
    system_memory_gb=32.0,
    storage_available_gb=150.0,
    backend="transformers",
    device="cuda",
    cuda_version="12.x",
    docker_available=True,
    supports_quantization=("none", "8bit", "4bit"),
    persistent=True,
    metadata={
        "quantization_mode": "4bit (NF4, bitsandbytes)",
        "qualified_for": ["Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"],
        "margin_note": (
            "Tightest of the three finalists (Phi-4, ~9.35GB estimated NF4 total) "
            "leaves ~6.6GB headroom on 16GB -- workable but tighter than the "
            "preferred class; recommended only if the preferred class is unavailable."
        ),
    },
)

PREFERRED_CUDA_CONTRACT = ComputeResource(
    resource_id="cuda-preferred-24gb",
    provider="unassigned",
    accelerator_type="CUDA GPU, 24GB VRAM class (e.g. NVIDIA RTX 4090, A10G, L4)",
    accelerator_count=1,
    accelerator_memory_gb=24.0,
    system_memory_gb=32.0,
    storage_available_gb=150.0,
    backend="transformers",
    device="cuda",
    cuda_version="12.x",
    docker_available=True,
    supports_quantization=("none", "8bit", "4bit"),
    persistent=True,
    metadata={
        "quantization_mode": "4bit (NF4, bitsandbytes) -- also comfortably supports uniform 8bit if higher fidelity is preferred",
        "qualified_for": ["Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"],
        "margin_note": (
            "Largest finalist (Phi-4, ~9.35GB estimated NF4 total) leaves ~14.6GB "
            "headroom (>60%) on 24GB -- comfortable margin for KV cache growth on "
            "longer genesis-eval-v1 tasks, CUDA allocator fragmentation, and reduced "
            "OOM risk versus the minimum-viable class."
        ),
    },
)
