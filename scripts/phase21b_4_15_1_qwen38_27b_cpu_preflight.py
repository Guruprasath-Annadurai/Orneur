"""
HISTORICAL / PREFLIGHT TOOLING (Phase 21B.4.15.1 containment note):
this script contains no `gpu=` parameter anywhere and cannot allocate
GPU compute -- confirmed structurally by AST inspection in the paired
test suite. It performs a CPU-only, metadata/config/CLI-parse-only
check against the resolved vLLM v0.30.0-cu129 image: no model weight
download, no CUDA initialization, no engine start.

Goals (Phase 21B.4.15.1 section 8):
  - confirm Qwen3_5ForConditionalGeneration is registered
  - confirm qwen3 reasoning parser is registered
  - confirm qwen3_xml and qwen3_coder tool-call parsers are registered
  - record exact installed vLLM / transformers / torch / CUDA-build metadata
"""

import modal

IMAGE_REF = "vllm/vllm-openai@sha256:58fdb6bb123a81aa53f46fa4652ad8cc87e817bd1077c9832c6258ef12c1c688"

image = (
    modal.Image.from_registry(
        IMAGE_REF,
        add_python=None,
        setup_dockerfile_commands=[
            "RUN which python || ln -s $(which python3) /usr/local/bin/python"
        ],
    )
    .entrypoint([])
)

app = modal.App("orca-phase21b-4-15-1-qwen38-27b-cpu-preflight")


@app.function(image=image, timeout=300)
def cpu_preflight():
    import importlib.metadata as im

    result = {}

    def safe_version(dist_name):
        try:
            return im.version(dist_name)
        except Exception as e:
            return f"UNRESOLVED ({e})"

    result["vllm_version"] = safe_version("vllm")
    result["transformers_version"] = safe_version("transformers")
    result["torch_version"] = safe_version("torch")

    try:
        import torch
        result["torch_version_cuda_build"] = torch.version.cuda
    except Exception as e:
        result["torch_import_error"] = str(e)

    # Architecture registry check -- no weights touched
    try:
        from vllm.model_executor.models.registry import ModelRegistry
        supported = ModelRegistry.get_supported_archs()
        result["qwen3_5_architecture_recognized"] = "Qwen3_5ForConditionalGeneration" in supported
    except Exception as e:
        result["qwen3_5_architecture_recognized"] = None
        result["architecture_registry_error"] = str(e)

    # Reasoning parser registry check
    try:
        from vllm.reasoning import ReasoningParserManager
        reasoning_parsers = list(ReasoningParserManager.reasoning_parsers.keys())
        result["reasoning_parsers_registered"] = reasoning_parsers
        result["qwen3_reasoning_parser_registered"] = "qwen3" in reasoning_parsers
    except Exception as e:
        result["reasoning_parsers_registered"] = None
        result["reasoning_parser_registry_error"] = str(e)

    # Tool-call parser registry check
    try:
        from vllm.entrypoints.openai.tool_parsers import ToolParserManager
        tool_parsers = list(ToolParserManager.tool_parsers.keys())
        result["tool_parsers_registered"] = tool_parsers
        result["qwen3_xml_tool_parser_registered"] = "qwen3_xml" in tool_parsers
        result["qwen3_coder_tool_parser_registered"] = "qwen3_coder" in tool_parsers
    except Exception as e:
        result["tool_parsers_registered"] = None
        result["tool_parser_registry_error"] = str(e)

    return result


@app.local_entrypoint()
def main():
    import json
    print(json.dumps(cpu_preflight.remote(), indent=2, default=str))
