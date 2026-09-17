"""Phase 21B.4.3 ComputeResource contract tests."""
from __future__ import annotations

from orca.eval.compute_resource import (
    LOCAL_M4_16GB,
    MINIMUM_VIABLE_CUDA_CONTRACT,
    PREFERRED_CUDA_CONTRACT,
    ComputeResource,
)


def test_local_m4_is_recorded_as_not_qualified():
    assert LOCAL_M4_16GB.metadata["verdict"] == "NOT_QUALIFIED"
    assert LOCAL_M4_16GB.supports_quantization == ("none",)


def test_local_m4_does_not_qualify_for_any_quantized_model():
    assert LOCAL_M4_16GB.qualifies_for(4.0, quantization="4bit") is False
    assert LOCAL_M4_16GB.qualifies_for(4.0, quantization="8bit") is False


def test_max_safe_model_vram_reserves_safety_margin():
    resource = ComputeResource(
        resource_id="test", provider="test", accelerator_type="test-gpu",
        accelerator_count=1, accelerator_memory_gb=24.0, system_memory_gb=32.0,
        storage_available_gb=100.0, backend="transformers", device="cuda",
        cuda_version="12.x", docker_available=True, supports_quantization=("4bit",),
        persistent=True,
    )
    assert resource.max_safe_model_vram_gb(safety_margin=0.15) == 24.0 * 0.85


def test_max_safe_model_vram_none_when_no_accelerator():
    resource = ComputeResource(
        resource_id="cpu-only", provider="test", accelerator_type=None,
        accelerator_count=0, accelerator_memory_gb=None, system_memory_gb=32.0,
        storage_available_gb=100.0, backend="transformers", device="cpu",
        cuda_version=None, docker_available=True, supports_quantization=("none",),
        persistent=True,
    )
    assert resource.max_safe_model_vram_gb() is None
    assert resource.qualifies_for(1.0, quantization="none") is False


def test_preferred_cuda_contract_qualifies_all_three_finalists_at_4bit():
    # Estimated NF4 totals (weights + KV cache + overhead) from Phase 21B.4.3
    # VRAM math: Qwen3-8B ~5.51GB, Mistral-Nemo ~7.97GB, Phi-4 ~9.35GB.
    for required_gb in (5.51, 7.97, 9.35):
        assert PREFERRED_CUDA_CONTRACT.qualifies_for(required_gb, quantization="4bit") is True


def test_minimum_viable_cuda_contract_qualifies_all_three_finalists_at_4bit_with_tighter_margin():
    for required_gb in (5.51, 7.97, 9.35):
        assert MINIMUM_VIABLE_CUDA_CONTRACT.qualifies_for(required_gb, quantization="4bit") is True


def test_minimum_viable_contract_does_not_qualify_any_finalist_at_bf16():
    # bf16 totals: Qwen3-8B ~17.18GB, Mistral-Nemo ~25.43GB, Phi-4 ~30.23GB --
    # none fit safely on a 16GB card even before considering the 24GB one.
    for required_gb in (17.18, 25.43, 30.23):
        assert MINIMUM_VIABLE_CUDA_CONTRACT.qualifies_for(required_gb, quantization="none") is False


def test_qualifies_for_rejects_unsupported_quantization_mode():
    resource = ComputeResource(
        resource_id="test", provider="test", accelerator_type="test-gpu",
        accelerator_count=1, accelerator_memory_gb=80.0, system_memory_gb=64.0,
        storage_available_gb=500.0, backend="transformers", device="cuda",
        cuda_version="12.x", docker_available=True, supports_quantization=("none",),
        persistent=True,
    )
    assert resource.qualifies_for(1.0, quantization="4bit") is False
