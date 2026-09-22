"""
Phase 21B.4.13 GLM-5.3-Flash -- CPU-ONLY image/config preflight.

NO GPU. NO model weight download (306 GiB checkpoint). NO inference.

Verifies, inside the exact resolved nightly image digest, that:
  - the inherited vLLM entrypoint is cleared
  - Python / torch / vLLM / transformers / tokenizers / FlashInfer versions
  - nvcc / /usr/local/cuda presence (image-baked CUDA toolchain, no GPU needed to inspect it)
  - Glm5NextForConditionalGeneration is a recognized vLLM model architecture
  - the pinned model revision resolves via metadata-only Hugging Face API call
    (no weight files downloaded)
  - the intended H200 server launch command line parses via vLLM's own arg parser
    without actually starting the engine or touching weights
"""

import modal

IMAGE_DIGEST = (
    "vllm/vllm-openai@sha256:"
    "4cc4c4532e7d935777a62ba49027fbb38d6b866dafd4ac56608f1853d933551e"
)

image = (
    modal.Image.from_registry(
        IMAGE_DIGEST,
        add_python=None,
        setup_dockerfile_commands=[
            "RUN which python || ln -s $(which python3) /usr/local/bin/python"
        ],
    )
    .entrypoint([])
    .pip_install("huggingface_hub")
)

app = modal.App("orca-phase21b-4-13-glm-cpu-preflight")


@app.function(image=image, timeout=600)
def cpu_preflight():
    import importlib.metadata as im
    import json
    import subprocess
    import sys

    result = {}

    # --- entrypoint cleared check (best-effort: confirm python is directly invocable,
    # i.e. this function body is executing at all under a non-`vllm serve`-hijacked entrypoint) ---
    result["entrypoint_cleared"] = True  # if this function runs to completion, entrypoint did not hijack it

    result["python_version"] = sys.version

    def safe_version(mod_name, dist_name=None):
        try:
            return im.version(dist_name or mod_name)
        except Exception as e:
            return f"UNRESOLVED ({e})"

    result["torch_version"] = safe_version("torch")
    result["vllm_version"] = safe_version("vllm")
    result["transformers_version"] = safe_version("transformers")
    result["tokenizers_version"] = safe_version("tokenizers")

    flashinfer_version = None
    for name in ["flashinfer-python", "flashinfer"]:
        try:
            flashinfer_version = im.version(name)
            result["flashinfer_package_name"] = name
            break
        except Exception:
            continue
    result["flashinfer_version"] = flashinfer_version or "NOT_INSTALLED"

    # torch build metadata (no GPU required to read these)
    try:
        import torch

        result["torch_version_cuda_build"] = torch.version.cuda
        result["torch_cuda_is_available_in_this_cpu_container"] = torch.cuda.is_available()
    except Exception as e:
        result["torch_import_error"] = str(e)

    # nvcc / cuda toolkit presence baked into the image
    try:
        nvcc_which = subprocess.run(["which", "nvcc"], capture_output=True, text=True)
        result["nvcc_which"] = nvcc_which.stdout.strip() or nvcc_which.stderr.strip()
        if nvcc_which.returncode == 0:
            nvcc_ver = subprocess.run(["nvcc", "--version"], capture_output=True, text=True)
            result["nvcc_version"] = nvcc_ver.stdout.strip()
        else:
            result["nvcc_version"] = "NOT_FOUND"
    except Exception as e:
        result["nvcc_check_error"] = str(e)

    import os

    result["cuda_path_exists"] = os.path.isdir("/usr/local/cuda")

    # vLLM architecture recognition -- does NOT touch weights, only the model registry
    try:
        from vllm.model_executor.models.registry import ModelRegistry

        supported = ModelRegistry.get_supported_archs()
        result["glm5_next_architecture_recognized"] = "Glm5NextForConditionalGeneration" in supported
        result["vllm_registry_lookup_error"] = None
    except Exception as e:
        result["glm5_next_architecture_recognized"] = None
        result["vllm_registry_lookup_error"] = str(e)

    # transformers model_type recognition (glm5_next) -- metadata only, no weights
    try:
        from transformers import CONFIG_MAPPING

        result["transformers_recognizes_glm5_next_model_type"] = "glm5_next" in CONFIG_MAPPING
    except Exception as e:
        result["transformers_config_mapping_error"] = str(e)

    # Pinned revision metadata-only resolution (no weight files fetched)
    try:
        from huggingface_hub import HfApi

        api = HfApi()
        info = api.model_info(
            "zai-org/GLM-5.3-Flash",
            revision="eb9eb208eb0d988989d07a6a12d0fdeb5f52574a",
        )
        result["hf_revision_resolved_sha"] = info.sha
        result["hf_revision_matches_pinned"] = (
            info.sha == "eb9eb208eb0d988989d07a6a12d0fdeb5f52574a"
        )
        result["hf_siblings_count"] = len(info.siblings) if info.siblings else 0
    except Exception as e:
        result["hf_metadata_resolution_error"] = str(e)

    # Config-only load via transformers AutoConfig (still no weights) to confirm
    # the architecture class instantiates cleanly from the pinned revision's config.json
    try:
        from transformers import AutoConfig

        cfg = AutoConfig.from_pretrained(
            "zai-org/GLM-5.3-Flash",
            revision="eb9eb208eb0d988989d07a6a12d0fdeb5f52574a",
        )
        result["config_architectures"] = getattr(cfg, "architectures", None)
        result["config_model_type"] = getattr(cfg, "model_type", None)
        result["config_load_error"] = None
    except Exception as e:
        result["config_architectures"] = None
        result["config_load_error"] = str(e)

    # Proposed H200 launch flags -- parse-only via vLLM's own CLI arg parser,
    # never actually constructing the LLM engine or touching weights.
    proposed_flags = [
        "vllm",
        "serve",
        "zai-org/GLM-5.3-Flash",
        "--revision",
        "eb9eb208eb0d988989d07a6a12d0fdeb5f52574a",
        "--tokenizer-revision",
        "eb9eb208eb0d988989d07a6a12d0fdeb5f52574a",
        "--tensor-parallel-size",
        "4",
        "--max-model-len",
        "4096",
        "--max-num-seqs",
        "8",
        "--max-num-batched-tokens",
        "4096",
        "--gpu-memory-utilization",
        "0.85",
        "--port",
        "8000",
        "--served-model-name",
        "zai-org/GLM-5.3-Flash",
    ]
    result["proposed_h200_launch_flags"] = proposed_flags
    try:
        from vllm.entrypoints.openai.cli_args import make_arg_parser
        import argparse

        parser = make_arg_parser(argparse.ArgumentParser())
        parsed = parser.parse_args(proposed_flags[2:])
        result["launch_flags_parse_result"] = "PARSED_OK"
        result["parsed_tensor_parallel_size"] = parsed.tensor_parallel_size
        result["parsed_kv_cache_dtype"] = getattr(parsed, "kv_cache_dtype", None)
    except Exception as e:
        result["launch_flags_parse_result"] = f"PARSE_FAILED: {e}"

    return result


@app.local_entrypoint()
def main():
    import json

    res = cpu_preflight.remote()
    print(json.dumps(res, indent=2, default=str))
