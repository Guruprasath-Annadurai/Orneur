"""
Phase 3.2 diagnostic script -- reproduces the full suite's real access
pattern (alternating nano/core tier requests against a shared 16GB
machine) directly against the Gateway, capturing exact exception types,
timings, and Ollama's own /api/ps loaded-model state at each step.
"""
import asyncio
import time

import httpx

from orca.gateway import wiring
from orca.gateway.contracts import InferenceRequest
from orca.gateway.errors import InferenceError
from orca.serve.registry import resolve_tier_backend


def ollama_loaded_models():
    try:
        r = httpx.get("http://localhost:11434/api/ps", timeout=5)
        return [(m["name"], m.get("size_vram", m.get("size", 0)) // 1024 // 1024) for m in r.json().get("models", [])]
    except Exception as e:
        return f"ERROR: {e}"


async def one_call(tier: str, label: str):
    wiring.get_shared_gateway()  # ensure singleton exists
    resolution = resolve_tier_backend(tier)
    from orca.gateway.wiring import brain_for_tier_resolution
    brain = brain_for_tier_resolution(resolution)
    req = InferenceRequest(
        request_id=f"repro-{label}", model_id=brain.model_id, model_version=brain.model_version,
        messages=[{"role": "user", "content": "Say hello in exactly three words."}], max_tokens=64,
    )
    t0 = time.monotonic()
    print(f"[{label}] tier={tier} model={resolution.model} loaded_before={ollama_loaded_models()}")
    try:
        resp = await brain._gateway.generate(req, allow_experimental=brain.allow_experimental)
        dt = time.monotonic() - t0
        print(f"[{label}] OK in {dt:.2f}s ttft-not-tracked output_len={len(resp.output)} loaded_after={ollama_loaded_models()}")
    except InferenceError as e:
        dt = time.monotonic() - t0
        print(f"[{label}] FAILED after {dt:.2f}s code={e.code.value} detail={e.internal_detail!r} loaded_after={ollama_loaded_models()}")
    except Exception as e:
        dt = time.monotonic() - t0
        print(f"[{label}] UNCLASSIFIED FAILURE after {dt:.2f}s type={type(e).__name__} msg={e} loaded_after={ollama_loaded_models()}")


async def main():
    wiring.reset_for_tests()
    sequence = ["core", "nano", "core", "nano", "core", "nano", "nano", "core", "nano", "core"]
    for i, tier in enumerate(sequence):
        await one_call(tier, f"{i:02d}-{tier}")


if __name__ == "__main__":
    asyncio.run(main())
