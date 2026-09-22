"""
Phase 21B.4.13 GLM-5.3-Flash -- LIVE GPU Attempt 1 (4x H200, TP=4).

Hard ceiling: 55 minutes total Modal function wall time (owner-authorized).
Internal soft deadline (readiness wait) is set below that ceiling to
reserve time for clean shutdown, log capture, and a graceful return even
if the model is still loading/downloading when the ceiling approaches.

NO persistent storage. NO speculative decoding / MTP. NO tool calling.
NO --kv-cache-dtype fp8 (Hopper cannot use FP8 KV cache for this model).
Exactly one trivial synthetic generation if the server becomes ready.
"""

import modal

IMAGE_DIGEST = (
    "vllm/vllm-openai@sha256:"
    "4cc4c4532e7d935777a62ba49027fbb38d6b866dafd4ac56608f1853d933551e"
)

MODEL_REPO = "zai-org/GLM-5.3-Flash"
PINNED_REVISION = "eb9eb208eb0d988989d07a6a12d0fdeb5f52574a"

HARD_CEILING_SECONDS = 55 * 60          # 3300s -- owner-authorized absolute max
SOFT_READY_DEADLINE_SECONDS = 49 * 60   # 2940s -- give up waiting for readiness here
SHUTDOWN_BUDGET_SECONDS = 60            # reserve time to SIGTERM/SIGKILL + gather logs

image = (
    modal.Image.from_registry(
        IMAGE_DIGEST,
        add_python=None,
        setup_dockerfile_commands=[
            "RUN which python || ln -s $(which python3) /usr/local/bin/python"
        ],
    )
    .entrypoint([])
    .pip_install("huggingface_hub", "requests")
)

app = modal.App("orca-phase21b-4-13-glm-gpu-attempt1")


@app.function(
    image=image,
    gpu="H200:4",
    timeout=HARD_CEILING_SECONDS,
)
def gpu_attempt():
    import hashlib
    import json
    import os
    import re
    import signal
    import subprocess
    import time

    t_start = time.time()
    result = {"attempt": 1}

    # ---------------------------------------------------------------
    # GPU preflight -- must pass before any weight loading is attempted
    # ---------------------------------------------------------------
    nvidia_smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total", "--format=csv"],
        capture_output=True, text=True,
    )
    result["nvidia_smi_returncode"] = nvidia_smi.returncode
    result["nvidia_smi_output"] = nvidia_smi.stdout.strip()
    gpu_lines = [l for l in nvidia_smi.stdout.strip().splitlines()[1:] if l.strip()]
    result["gpu_count_detected"] = len(gpu_lines)
    result["gpu_names"] = gpu_lines

    h200_count = sum(1 for l in gpu_lines if "H200" in l)
    result["h200_count_confirmed"] = h200_count

    nvcc_ver = subprocess.run(["nvcc", "--version"], capture_output=True, text=True)
    result["nvcc_version"] = nvcc_ver.stdout.strip()
    result["cuda_path_exists"] = os.path.isdir("/usr/local/cuda")

    try:
        import torch
        result["torch_cuda_available"] = torch.cuda.is_available()
        result["torch_cuda_device_count"] = torch.cuda.device_count()
        result["torch_version_cuda_build"] = torch.version.cuda
    except Exception as e:
        result["torch_gpu_check_error"] = str(e)

    gpu_preflight_passed = (
        nvidia_smi.returncode == 0
        and h200_count == 4
        and result.get("torch_cuda_device_count") == 4
        and result["cuda_path_exists"]
    )
    result["gpu_preflight_passed"] = gpu_preflight_passed

    if not gpu_preflight_passed:
        result["result_state"] = "RUNTIME_QUALIFICATION_FAILED"
        result["failure_class"] = "GPU_PREFLIGHT_FAILED"
        result["server_ready"] = False
        return result

    idle_mem = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"],
        capture_output=True, text=True,
    )
    result["idle_baseline_memory_per_gpu"] = idle_mem.stdout.strip()

    # ---------------------------------------------------------------
    # Launch vLLM OpenAI-compatible server as a subprocess
    # ---------------------------------------------------------------
    launch_flags = [
        "vllm", "serve", MODEL_REPO,
        "--revision", PINNED_REVISION,
        "--tokenizer-revision", PINNED_REVISION,
        "--tensor-parallel-size", "4",
        "--max-model-len", "4096",
        "--max-num-seqs", "8",
        "--max-num-batched-tokens", "4096",
        "--gpu-memory-utilization", "0.85",
        "--no-enable-flashinfer-autotune",
        "--served-model-name", MODEL_REPO,
        "--port", "8000",
    ]
    result["launch_flags"] = launch_flags

    log_path = "/tmp/vllm_server.log"
    log_file = open(log_path, "w")

    env = dict(os.environ)
    proc = subprocess.Popen(
        launch_flags,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
    )
    result["server_pid"] = proc.pid
    t_launch = time.time()

    import requests

    ready = False
    concrete_failure = None
    ready_wait_deadline = t_start + SOFT_READY_DEADLINE_SECONDS

    while time.time() < ready_wait_deadline:
        if proc.poll() is not None:
            # process exited before becoming ready -- concrete failure
            concrete_failure = f"server process exited early with code {proc.returncode}"
            break
        try:
            with open(log_path, "r", errors="replace") as f:
                log_so_far = f.read()
        except Exception:
            log_so_far = ""

        if "Application startup complete" in log_so_far:
            ready = True
            break

        # scan for concrete error signatures while waiting
        for pattern in ("Traceback (most recent call last)", "CUDA out of memory", "CUDA error", "RuntimeError:"):
            if pattern in log_so_far:
                concrete_failure = f"detected error pattern in log: {pattern!r}"
                break
        if concrete_failure:
            break

        time.sleep(5)

    t_ready_check_done = time.time()
    result["server_ready"] = ready
    result["seconds_to_ready_or_giveup"] = t_ready_check_done - t_launch
    result["concrete_failure_detected"] = concrete_failure

    generation_result = None
    models_status = None
    chat_status = None

    if ready:
        try:
            models_resp = requests.get("http://localhost:8000/v1/models", timeout=30)
            models_status = models_resp.status_code
            result["models_response_body"] = models_resp.text[:2000]
        except Exception as e:
            models_status = None
            result["models_endpoint_error"] = str(e)

        prompt_text = "Reply with exactly the single word READY."
        chat_payload = {
            "model": MODEL_REPO,
            "messages": [{"role": "user", "content": prompt_text}],
            "max_tokens": 64,
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        try:
            t_req_start = time.time()
            ttft = None
            decoded_chunks = []
            usage = None
            with requests.post(
                "http://localhost:8000/v1/chat/completions",
                json=chat_payload,
                stream=True,
                timeout=180,
            ) as resp:
                chat_status = resp.status_code
                for raw_line in resp.iter_lines(decode_unicode=True):
                    if not raw_line or not raw_line.startswith("data:"):
                        continue
                    data_str = raw_line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if ttft is None and chunk.get("choices"):
                        delta = chunk["choices"][0].get("delta", {})
                        if delta.get("content"):
                            ttft = time.time() - t_req_start
                    if chunk.get("choices"):
                        delta = chunk["choices"][0].get("delta", {})
                        if delta.get("content"):
                            decoded_chunks.append(delta["content"])
                    if chunk.get("usage"):
                        usage = chunk["usage"]
            t_req_end = time.time()

            decoded_response = "".join(decoded_chunks)
            generation_succeeded = bool(decoded_response.strip()) and chat_status == 200

            generation_result = {
                "evidence_type": "LIVE_HARNESS_GENERATION_RESULT",
                "source": "ORIGINAL_PHASE_21B_4_13_ATTEMPT1_HARNESS_OUTPUT",
                "evidence_strength": "OBSERVED_LIVE",
                "original_harness_result": {
                    "server_ready": True,
                    "models_endpoint_status": models_status,
                    "chat_endpoint_status": chat_status,
                    "generation_succeeded": generation_succeeded,
                    "synthetic_prompt": prompt_text,
                    "synthetic_prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
                    "decoded_response": decoded_response,
                    "decoded_response_sha256": hashlib.sha256(decoded_response.encode()).hexdigest(),
                    "input_tokens": usage.get("prompt_tokens") if usage else None,
                    "output_tokens": usage.get("completion_tokens") if usage else None,
                    "generation_latency_seconds": t_req_end - t_req_start,
                    "ttft_seconds": ttft,
                    "tokens_per_second": (
                        (usage.get("completion_tokens") / (t_req_end - t_req_start))
                        if usage and usage.get("completion_tokens") else None
                    ),
                },
            }
        except Exception as e:
            result["generation_request_error"] = str(e)

    result["models_status"] = models_status
    result["chat_status"] = chat_status
    result["generation_result"] = generation_result

    # ---------------------------------------------------------------
    # Worker-level memory evidence (parse from vLLM's own log, not
    # parent-process torch.cuda which does not hold the model)
    # ---------------------------------------------------------------
    try:
        with open(log_path, "r", errors="replace") as f:
            full_log = f.read()
    except Exception:
        full_log = ""

    mem_lines = [l for l in full_log.splitlines() if "consumed memory" in l or "Free memory on device" in l]
    result["worker_memory_log_lines"] = mem_lines[:8]

    load_time_lines = [l for l in full_log.splitlines() if "Loading weights took" in l or "Time spent downloading weights" in l]
    result["weight_load_log_lines"] = load_time_lines[:8]

    weight_file_lines = [l for l in full_log.splitlines() if "safetensors" in l.lower() and ("shard" in l.lower() or "checkpoint" in l.lower())]
    result["weight_file_log_lines"] = weight_file_lines[:8]

    # ---------------------------------------------------------------
    # Cleanup: terminate the server cleanly within the shutdown budget
    # ---------------------------------------------------------------
    cleanup_ok = True
    if proc.poll() is None:
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=SHUTDOWN_BUDGET_SECONDS)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=15)
            except Exception as e:
                cleanup_ok = False
                result["cleanup_error"] = str(e)
    result["cleanup_confirmed"] = cleanup_ok
    result["server_final_returncode"] = proc.returncode

    post_mem = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"],
        capture_output=True, text=True,
    )
    result["post_cleanup_gpu_memory"] = post_mem.stdout.strip()

    t_end = time.time()
    result["total_wall_seconds"] = t_end - t_start

    # ---------------------------------------------------------------
    # Result classification
    # ---------------------------------------------------------------
    if ready and generation_result and generation_result["original_harness_result"]["generation_succeeded"]:
        result["result_state"] = "PRODUCTION_SERVING_RUNTIME_QUALIFIED"
    elif concrete_failure:
        result["result_state"] = "RUNTIME_QUALIFICATION_FAILED"
        result["failure_class"] = concrete_failure
    else:
        result["result_state"] = "DEFERRED_FOR_COMPUTE"
        result["deferred_reason"] = (
            "soft readiness deadline reached with no concrete technical failure detected; "
            "server had not signaled 'Application startup complete' within the owner-authorized "
            f"{SOFT_READY_DEADLINE_SECONDS}s budget (weights are a 306 GiB checkpoint)"
        )

    # full log returned directly (no persistent storage per hard restriction)
    result["full_execution_log"] = full_log

    return result


@app.local_entrypoint()
def main():
    import json
    res = gpu_attempt.remote()
    # write full result (incl. full log) to local scratch file; print a trimmed summary
    with open("/tmp/glm_gpu_attempt1_result.json", "w") as f:
        json.dump(res, f, indent=2, default=str)
    summary = {k: v for k, v in res.items() if k != "full_execution_log"}
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nFull log length: {len(res.get('full_execution_log', ''))} chars, saved to /tmp/glm_gpu_attempt1_result.json")
