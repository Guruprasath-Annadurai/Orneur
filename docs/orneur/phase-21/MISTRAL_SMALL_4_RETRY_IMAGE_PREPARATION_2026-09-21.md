# Mistral Small 4 -- Retry Image Preparation (Phase 21B.4.12.1 §10)

**Status: PREPARED ONLY. NOT EXECUTED.** No image was built, no Modal
app was run, no GPU was launched to produce this document. This is a
planning artifact for a future retry phase, written under Phase
21B.4.12.1's explicit "NO GPU / NO MODEL DOWNLOAD / NO INFERENCE / NO
BENCHMARK" constraint.

## 1. Root cause being addressed

Phase 21B.4.12 attempt 2 loaded the full ~120.9GB FP8 weight set
successfully across both H200 GPUs, then failed during vLLM's post-load
profiling pass with:

```
RuntimeError: Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist
```

raised inside `flashinfer/jit/cpp_ext.py` while JIT-compiling a
FlashInfer kernel for the `--attention-backend FLASH_ATTN_MLA` backend
that Mistral3's MLA-style attention requires. The attempt's Modal image
was assembled ad hoc via `modal.Image.debian_slim(python_version="3.11")
.pip_install("vllm==0.29.0", "hf_transfer==0.1.9").pip_install("transformers==5.10.4")`
-- a pip-only image with no CUDA development toolkit installed at all.

Observed immediate root cause: missing CUDA development toolkit (nvcc)
during FlashInfer JIT compilation. No model defect or topology
insufficiency was demonstrated.

## 2. Primary-source verification of the fix (done this phase, no GPU)

Per Phase 21B.4.12.1 §10's explicit instruction to prefer "a current
official vLLM CUDA image or another reproducible image proven to
contain nvcc rather than assembling an ad-hoc runtime blindly," the
official vLLM `v0.29.0` release Dockerfile was fetched directly from
its primary source
(`https://raw.githubusercontent.com/vllm-project/vllm/v0.29.0/docker/Dockerfile`,
retrieved 2026-09-21) and inspected:

- `ARG CUDA_VERSION=13.0.3` -- matches our attempt 2 build's
  `torch==2.13.0+cu130` (CUDA 13.0 wheel tag).
- `ARG FINAL_BASE_IMAGE=nvidia/cuda:${CUDA_VERSION}-base-ubuntu${UBUNTU_VERSION}`
  -- the published image's runtime stage starts from an NVIDIA CUDA
  base image, annotated in the Dockerfile's own comment: "Using cuda
  base image with minimal dependencies necessary for JIT compilation
  (FlashInfer, DeepGEMM, EP kernels)".
- The Dockerfile then explicitly installs, with the comment "Install
  CUDA development tools for runtime JIT compilation (FlashInfer,
  DeepGEMM, EP kernels all require compilation at runtime)":
  ```
  cuda-nvcc-${CUDA_VERSION_DASH}
  cuda-cudart-${CUDA_VERSION_DASH}
  cuda-nvrtc-${CUDA_VERSION_DASH}
  cuda-cuobjdump-${CUDA_VERSION_DASH}
  libcurand-dev-${CUDA_VERSION_DASH}
  libcublas-dev-${CUDA_VERSION_DASH}
  ```
  This is precisely the missing capability (`nvcc`) that caused attempt
  2's `CUDA_KERNEL_FAILURE`.
- The Dockerfile also separately installs a prebuilt
  `flashinfer-jit-cache==${FLASHINFER_VERSION}` wheel from
  `https://flashinfer.ai/whl/cu<version>` (FlashInfer's own
  CUDA-version-specific index), which may pre-satisfy some kernels
  without JIT at all -- but `nvcc` remains present regardless as a
  documented, intentional runtime dependency, not an accidental
  omission.

This is a real, current, primary-source finding (the exact tagged
Dockerfile of the exact vLLM version already in use), not a guess or an
inference from an unrelated image.

## 3. Recommended retry image change

Replace the ad-hoc pip-only Modal image:

```python
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("vllm==0.29.0", "hf_transfer==0.1.9")
    .pip_install("transformers==5.10.4")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)
```

with one built from the official published vLLM image for the same
version, e.g.:

```python
image = (
    modal.Image.from_registry("vllm/vllm-openai:v0.29.0", add_python=None)
    .pip_install("transformers==5.10.4", "hf_transfer==0.1.9")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)
```

`vllm/vllm-openai:v0.29.0` on Docker Hub is vLLM's own published image
built from the exact Dockerfile inspected above -- a reproducible,
officially-maintained image already containing `nvcc` and the CUDA
devel packages, rather than an assembly this project would have to
independently prove correct.

## 4. What must still be independently re-verified at retry time (not assumed from this document)

- That the `vllm/vllm-openai:v0.29.0` tag still exists and its digest
  is stable at retry time (Docker Hub tags are not immutable by
  guarantee the way a Git commit SHA is).
- That the image's baked-in CUDA/driver version remains compatible with
  Modal's H200 host driver at retry time.
- That layering `transformers==5.10.4` on top of the official image's
  own pinned transformers version does not reintroduce a dependency
  conflict (the official image may already pin a compatible
  transformers version, making the extra pin unnecessary or requiring
  an `--upgrade`/constraint approach instead of a bare `pip_install`).
- That FlashInfer's JIT compilation of `FLASH_ATTN_MLA` specifically
  (not just FlashInfer in general) succeeds against this image -- the
  Dockerfile's own `flashinfer-jit-cache` wheel is a prebuilt kernel
  cache for common kernels and may not cover every attention backend
  variant; a live attempt is still required to know for certain.
- Current fresh Modal GPU availability/quota for 2xH200 at retry time.

None of the above was checked live this phase -- this section exists
so a future retry does not treat this document as a substitute for its
own pre-GPU verification.

## 5. Hard precondition before any retry GPU execution (Phase 21B.4.12.1 §11)

Before any retry GPU execution takes place, a **NEW fresh owner-provided
Modal dashboard screenshot showing Spend limit = $0** must be obtained
and independently confirmed -- the Phase 21B.4.12 billing gate is
scoped to that execution only (`scope: "THIS PHASE 21B.4.12 MISTRAL
SMALL 4 EXECUTION ONLY"` in the persisted billing-gate evidence
artifact) and does not carry forward to a future retry. No retry GPU
work may begin on the strength of this document, the Phase 21B.4.12
billing gate, or any other prior-phase evidence.

## 6. Explicit non-actions this phase

- No `modal.Image` was built.
- No `modal run` was invoked.
- No GPU was requested or allocated.
- No model weights were downloaded.
- No inference or generation was attempted.
- No benchmark or Genesis-eval content was touched.
