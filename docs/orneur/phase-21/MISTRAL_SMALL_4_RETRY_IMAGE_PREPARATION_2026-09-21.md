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
    modal.Image.from_registry(
        "vllm/vllm-openai:v0.29.0",
        add_python=None,
    )
    .entrypoint([])
    .pip_install(
        "transformers==5.10.4",
        "hf_transfer==0.1.9",
    )
)
```

`vllm/vllm-openai:v0.29.0` on Docker Hub is vLLM's own published image
built from the exact Dockerfile inspected above -- a reproducible,
officially-maintained image already containing `nvcc` and the CUDA
devel packages, rather than an assembly this project would have to
independently prove correct.

### 3.1 Why `.entrypoint([])` is required (Phase 21B.4.12.2)

The official `vllm/vllm-openai` image's own Dockerfile defines:

```
ENTRYPOINT ["vllm", "serve"]
```

That entrypoint is correct and intentional for normal Docker use --
`docker run vllm/vllm-openai <model>` is meant to immediately start an
OpenAI-compatible server. It is not a defect. But for ORNEUR's
controlled Modal Function execution, that inherited entrypoint must
never be allowed to launch automatically when the container starts,
because:

- ORNEUR's smoke harness -- not the base image -- must remain solely
  responsible for launching the exact pinned `vllm serve` command
  (with its own flags, revision pins, and timing instrumentation), so
  the executed command is always the one this project's evidence
  bundle actually describes.
- An uncontrolled auto-started server would race the harness's own
  process-management code (readiness polling, log capture, timeout
  handling), producing nondeterministic logging and timing evidence.
- Full lifecycle control (start, readiness detection, teardown,
  cleanup verification) depends on the harness owning the process it
  starts -- an entrypoint-launched server the harness did not spawn
  cannot be reliably attributed, monitored, or torn down through the
  same code path.
- Evidence capture (the raw execution log artifact) must correspond
  exactly to the command the manifest declares
  (`vllm_serve_command` in the runtime-environment evidence) -- an
  entrypoint-launched process launched before the harness's own code
  runs would not be captured by that same instrumentation.

`modal.Image.from_registry(..., add_python=None).entrypoint([])` clears
the inherited `ENTRYPOINT` on the constructed image (Modal Functions
otherwise execute the image's entrypoint before Modal's own function
code, per Modal's `from_registry` documentation), so the container
starts inert and the harness's own `subprocess.Popen([...])` call (as
already used in `mistral_small4_smoke.py`, see the Phase 21B.4.12
scratch script referenced by the execution-log evidence) remains the
only thing that ever launches vLLM.

## 4. What must still be independently re-verified at retry time (not assumed from this document)

- That the `vllm/vllm-openai:v0.29.0` tag still exists and its digest
  is stable at retry time (Docker Hub tags are not immutable by
  guarantee the way a Git commit SHA is) -- see §4.1 below.
- That the image's baked-in CUDA/driver version remains compatible with
  Modal's H200 host driver at retry time.
- That layering `transformers==5.10.4` on top of the official image's
  own pinned transformers version does not reintroduce a dependency
  conflict (the official image may already pin a compatible
  transformers version, making the extra pin unnecessary or requiring
  an `--upgrade`/constraint approach instead of a bare `pip_install`)
  -- see §6 below.
- That FlashInfer's JIT compilation of `FLASH_ATTN_MLA` specifically
  (not just FlashInfer in general) succeeds against this image -- the
  Dockerfile's own `flashinfer-jit-cache` wheel is a prebuilt kernel
  cache for common kernels and may not cover every attention backend
  variant; a live attempt is still required to know for certain.
- Current fresh Modal GPU availability/quota for 2xH200 at retry time.
- That `.entrypoint([])` (§3.1) does not remove anything else the base
  image relies on at container-start time (e.g. an `ENV`/`CMD`
  interaction) -- inspect the resolved image config at retry time
  rather than assuming this document's description of the Dockerfile
  is still current.

None of the above was checked live this phase -- this section exists
so a future retry does not treat this document as a substitute for its
own pre-GPU verification.

### 4.1 Image identity: a version tag is not immutability

`vllm/vllm-openai:v0.29.0` MUST NOT be treated as immutable merely
because it is version-tagged -- a Docker Hub tag can, in principle, be
repointed to a different underlying image after the fact, unlike a
Git commit SHA. Before any retry execution, Claude must resolve and
record the actual registry image digest for the tag in use, e.g.:

```
repository: vllm/vllm-openai
tag: v0.29.0
resolved image digest: sha256:<actual digest>
```

No digest is invented or recorded in this document -- it was not
pulled, built, or otherwise resolved this phase (doing so would
require pulling image manifests, which this phase's CPU-only,
no-image-build scope excludes). The digest must be resolved during the
authorized retry preflight, from a trusted registry source (e.g. `docker
buildx imagetools inspect vllm/vllm-openai:v0.29.0`, or the Docker Hub
API), and recorded in that retry's own evidence bundle before any GPU
launch.

### 4.2 Mandatory in-image preflight checks before any weight loading (Phase 21B.4.12.2 §4)

These are FUTURE execution requirements only -- none of them are run in
this phase (this phase is CPU-only documentation preparation; there is
no image and no container to run them against yet). A future live
retry must run all of the following inside the selected image before
starting any GPU weight load:

```
python3 --version
python3 -c "import torch; print(torch.__version__)"
python3 -c "import vllm; print(vllm.__version__)"
python3 -c "import transformers; print(transformers.__version__)"
which nvcc
nvcc --version
test -d /usr/local/cuda
```

The live retry must NOT begin weight loading unless, from these
checks:

- `nvcc` is present (both `which nvcc` resolves and `nvcc --version`
  succeeds);
- `CUDA_HOME`/the CUDA runtime path is valid (`/usr/local/cuda`
  exists);
- vLLM is the intended version (`0.29.0`, or whatever version the
  retry's own manifest declares);
- transformers is the intended, compatible version (`5.10.4`, or a
  version re-verified compatible per §6 below);
- GPU topology remains evidence-supported (re-derived from the model's
  own current published requirements, per Phase 21B.4.12's original
  topology-selection discipline, not merely copied from this
  document);
- fresh billing authorization exists (§5 below).

If any of these checks fails or is inconclusive, the retry must stop
before weight loading and classify the failure, exactly as Phase
21B.4.12's two-attempt discipline required -- these preflight checks
exist specifically so a future attempt does not repeat attempt 2's
"discover the CUDA gap only after a ~1076-second weight load" pattern.

## 5. Hard precondition before any retry GPU execution (Phase 21B.4.12.1 §11)

Before any retry GPU execution takes place, a **NEW fresh owner-provided
Modal dashboard screenshot showing Spend limit = $0** must be obtained
and independently confirmed -- the Phase 21B.4.12 billing gate is
scoped to that execution only (`scope: "THIS PHASE 21B.4.12 MISTRAL
SMALL 4 EXECUTION ONLY"` in the persisted billing-gate evidence
artifact) and does not carry forward to a future retry. No retry GPU
work may begin on the strength of this document, the Phase 21B.4.12
billing gate, or any other prior-phase evidence.

## 6. Transformers pin caution (Phase 21B.4.12.2 §6)

`transformers==5.10.4` remains the currently prepared corrective
version, because it is what resolved Phase 21B.4.12 attempt 1's
`PixtralRotaryEmbedding` import error (vLLM 0.29.0's own stated
minimum-tested floor). It stays the recommended pin in this document.

However, layering this pin on top of the official `vllm/vllm-openai`
image (rather than the ad-hoc pip-only image it was originally proven
against) is **not automatically safe** and must be independently
re-verified before any live retry:

- The official image already bakes in its own tested transformers
  version. Overriding it with `pip_install("transformers==5.10.4")`
  could either be a no-op (if the image already pins something
  compatible), a safe downgrade/upgrade, or a source of a *new*
  dependency conflict this document has not observed -- this has not
  been tested against the `vllm/vllm-openai:v0.29.0` image specifically,
  only reasoned about from the Dockerfile's text.
- Changing the official image's baked dependency set is not claimed to
  be automatically safe merely because it worked against a different,
  ad-hoc pip-only image in Phase 21B.4.12.

At retry time, before model loading begins, the final effective
versions actually present in the running container must be recorded
(this is the same information the §4.2 preflight checks surface, plus
FlashInfer and CUDA, which those checks do not directly print):

- `vllm`
- `transformers`
- `torch`
- `tokenizers`
- `flashinfer`
- `CUDA` (driver + toolkit, as resolved by `nvcc --version` and the
  runtime's own reported CUDA version)

These must be captured as genuinely observed values in that retry's
own runtime-environment evidence artifact -- not assumed to match this
document's or Phase 21B.4.12's prior values merely because the same
version strings were requested.

## 7. Explicit non-actions this phase

- No `modal.Image` was built.
- No `modal run` was invoked.
- No GPU was requested or allocated.
- No model weights were downloaded.
- No inference or generation was attempted.
- No benchmark or Genesis-eval content was touched.
- No image was pulled or inspected to resolve a digest.
- No preflight command (§4.2) was executed against any image.
