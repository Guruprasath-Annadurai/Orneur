"""
Real, honest performance baseline for the current single-host Ollama
inference path, measured through the new OllamaRuntime adapter itself
(dogfooding the Phase 2 code, not a separate ad-hoc script). Numbers are
whatever this specific machine/model produce right now -- not presented as
representative hardware, since this project's own machine is a 16GB
Apple M4 laptop with competing processes, not a dedicated inference host.
"""
from __future__ import annotations

import asyncio
import json
import platform
import subprocess
import time

from orca.gateway.contracts import InferenceRequest
from orca.gateway.ollama_runtime import OllamaRuntime


def _hardware_info() -> dict:
    try:
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    except Exception:
        cpu = "unknown"
    try:
        mem_bytes = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip())
        mem_gb = round(mem_bytes / (1024 ** 3), 1)
    except Exception:
        mem_gb = "unknown"
    return {
        "cpu": cpu,
        "memory_gb": mem_gb,
        "arch": platform.machine(),
        "os": platform.platform(),
        "note": "shared laptop, not a dedicated inference host -- other processes competing for CPU/memory during this measurement",
    }


async def _measure_generate(rt: OllamaRuntime, model: str, prompt: str, max_tokens: int) -> dict:
    request = InferenceRequest(
        request_id=f"baseline-{model}-{max_tokens}", model_id=model, model_version=model,
        messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens,
    )
    t0 = time.monotonic()
    response = await rt.generate(request)
    total_s = time.monotonic() - t0
    tokens_per_sec = response.completion_tokens / total_s if total_s > 0 and response.completion_tokens else 0
    return {
        "model": model, "max_tokens": max_tokens,
        "total_latency_ms": round(total_s * 1000, 1),
        "completion_tokens": response.completion_tokens,
        "prompt_tokens": response.prompt_tokens,
        "tokens_per_sec": round(tokens_per_sec, 2),
    }


async def _measure_ttft(rt: OllamaRuntime, model: str, prompt: str, max_tokens: int) -> dict:
    request = InferenceRequest(
        request_id=f"baseline-ttft-{model}", model_id=model, model_version=model,
        messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens,
    )
    t0 = time.monotonic()
    ttft_ms = None
    chunk_count = 0
    async for chunk in rt.stream(request):
        if ttft_ms is None and chunk.delta:
            ttft_ms = (time.monotonic() - t0) * 1000
        chunk_count += 1
    total_ms = (time.monotonic() - t0) * 1000
    return {"model": model, "ttft_ms": round(ttft_ms, 1) if ttft_ms else None, "total_ms": round(total_ms, 1), "chunk_count": chunk_count}


async def _measure_concurrency(rt: OllamaRuntime, model: str, n: int) -> dict:
    async def _one(i):
        request = InferenceRequest(
            request_id=f"baseline-concurrent-{i}", model_id=model, model_version=model,
            messages=[{"role": "user", "content": "Say a single word."}], max_tokens=5,
        )
        t0 = time.monotonic()
        try:
            await rt.generate(request)
            return time.monotonic() - t0
        except Exception as e:
            return f"error: {e}"

    t0 = time.monotonic()
    results = await asyncio.gather(*[_one(i) for i in range(n)])
    wall_s = time.monotonic() - t0
    successes = [r for r in results if isinstance(r, float)]
    return {
        "concurrent_requests": n, "successes": len(successes), "failures": n - len(successes),
        "wall_time_s": round(wall_s, 2),
        "individual_latencies_s": [round(r, 2) if isinstance(r, float) else r for r in results],
    }


async def main():
    rt = OllamaRuntime(host="http://localhost:11434", timeout_s=120.0)
    model = "orca-nano-v7"  # fastest available checkpoint on this machine per this session's own prior measurements

    print(f"[baseline] hardware: {json.dumps(_hardware_info())}")
    print(f"[baseline] model: {model}\n")

    print("[baseline] measuring generate() latency at increasing max_tokens...")
    generate_results = []
    for max_tokens in (5, 20, 50):
        r = await _measure_generate(rt, model, "Explain what a hash map is in one sentence.", max_tokens)
        generate_results.append(r)
        print(f"  {r}")

    print("\n[baseline] measuring time-to-first-token (streaming)...")
    ttft_result = await _measure_ttft(rt, model, "Count from 1 to 10.", 30)
    print(f"  {ttft_result}")

    print("\n[baseline] measuring concurrent request behavior (2 simultaneous)...")
    concurrency_result = await _measure_concurrency(rt, model, 2)
    print(f"  {concurrency_result}")

    report = {
        "hardware": _hardware_info(),
        "model": model,
        "generate_latency": generate_results,
        "ttft": ttft_result,
        "concurrency": concurrency_result,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out_path = "docs/orneur/phase-2/inference_baseline_raw.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n[baseline] wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
