# Genesis Frontier Compute Matrix

Weight-storage VRAM math for every candidate in
`GENESIS_FRONTIER_MODEL_LANDSCAPE_2026_09.md`, computed from TOTAL
parameter counts (never active-parameter counts — see the explicit
warning in spec section 11 and the worked explanation below), against
80GB-class accelerators (Modal's largest single-GPU offering:
A100-80GB / H100 / H200 / B200 / B300 all cluster around this class or
above).

## Why total parameters, not active parameters, determine VRAM

A sparse MoE model activates only a subset of its experts per token,
but which subset activates changes token-to-token and request-to-
request — over the lifetime of a serving deployment, effectively all
experts get used. Every expert's weights must therefore reside in
accessible accelerator memory (or be paged in with severe latency
cost) regardless of how few are active for any single token. **DeepSeek
V4.1-Flash's 8B/16B active-parameter figure does NOT mean it fits on
an 8-16B-parameter-class GPU budget — its ~763B TOTAL parameters must
be stored somewhere the accelerators can reach.**

## Weight-storage VRAM by precision (GPU count = ceil(weight_GB / 80))

| Candidate | Total params | BF16 (2B/param) | FP8 (1B/param) | INT4 (0.5B/param) |
|---|---|---|---|---|
| DeepSeek V4.1-Flash | 763B | 1,526GB → **20× 80GB GPUs** | 763GB → **10×** | 382GB → **5×** |
| GLM-5.2 | 753B | 1,506GB → **19×** | 753GB → **10×** | 376GB → **5×** |
| GLM-5.3 | 743B | 1,486GB → **19×** | 743GB → **10×** | 372GB → **5×** |
| GLM-5.3-Flash | 320B | 640GB → **8×** | 320GB → **4×** | 160GB → **2×** |
| Mistral Large 3 | 675B | 1,350GB → **17×** | 675GB → **9×** | 338GB → **5×** |
| MiniMax M3 | 428B | 856GB → **11×** | 428GB → **6×** | 214GB → **3×** |
| Qwen3.8-Max | 2,400B | 4,800GB → **60×** | 2,400GB → **30×** | 1,200GB → **15×** |
| **Qwen3.8-27B (dense)** | **27B** | **54GB → 1×** | **27GB → 1×** | **14GB → 1×** |
| Kimi K3 | 2,800B | 5,600GB → **70×** | 2,800GB → **35×** | 1,400GB → **18×** |

KV cache, runtime/allocator overhead, and tensor/expert-parallel
communication buffers add further headroom on top of these figures
(typically 10-30% depending on context length and batch size) — not
included above, since weight storage alone already determines the
minimum viable GPU count for every candidate except Qwen3.8-27B.

## Modal GPU inventory and live rates (2026-09-18/19, authenticated `modal billing rates`)

| GPU | VRAM | Rate/hr |
|---|---|---|
| T4 | 16GB | $0.59 |
| L4 | 24GB | $0.80 |
| A10G | 24GB | $1.10 |
| L40S | 48GB | $1.95 |
| A100-40GB | 40GB | $2.10 |
| A100-80GB | 80GB | $2.50 |
| RTX PRO 6000 | 96GB | $3.03 |
| H100 | 80GB | $3.95 |
| H200 | 141GB | $4.54 |
| B200 | ~192GB (class) | $6.25 |
| B300 | ~192GB (class) | $7.10 |

Modal also hosts several frontier models directly as pay-per-token
Shared Endpoints (discovered live via the rate card, not assumed):
`moonshotai/Kimi-K3`, `nvidia/GLM-5.2-NVFP4`, `Qwen/Qwen3.8-2.4T-A95B`,
`zai-org/GLM-5.3`, `zai-org/GLM-5.3-Flash`, `thinkingmachines/Inkling-NVFP4`
— see Section "Practical implication" below.

## Multi-GPU support (reverified live)

Modal documents multi-GPU tensor-parallel Functions (`gpu="H100:N"`-
style allocation), with worked examples deploying vLLM and SGLang
(including an existing Modal doc example serving a Qwen model via
SGLang). This is a real, supported, documented pattern — not something
ORNEUR would need to build from scratch.

## Credit reality check (owner's $30 included compute, $0 spend limit)

At the CHEAPEST viable precision (INT4) for the cheapest "true
frontier" candidate (MiniMax M3, 3× 80GB GPUs), a bare weight-loading
smoke test — download + load only, no meaningful inference — would
plausibly consume 3 × $2.50-3.95/hr × however long loading + minimal
verification takes. Even a fast ~10-minute load-and-verify would cost
roughly 3 GPUs × ~$3/hr × (10/60)hr ≈ **$1.50**, already exceeding this
phase's own $1 GPU-qualification ceiling, and this is before any real
inference. **Loading any of the 100B+ total-parameter candidates even
once would likely consume a meaningful fraction to all of the
workspace's entire $30 included allowance.** Per spec section 14, this
fact is reported here rather than acted on — none of these models were
downloaded or loaded this phase.

## Practical implication

Given the credit reality above, the most realistic near-term path to
touching genuine frontier-model *outputs* (not weights) within the
owner's ₹0/included-credit constraint is Modal's own pay-per-token
Shared Endpoints for the models it already hosts (Kimi K3, GLM-5.2/5.3,
Qwen3.8-Max) — this avoids provisioning any GPU/weight-storage
infrastructure at all for teacher/reference use, at the cost of paying
per-token (still drawing from the same $30 included balance, still
subject to the $0 spend limit hard-stopping any overage) rather than
per-GPU-hour. This is noted as a real, evidence-based option for the
Frontier Teacher Pool (see `GENESIS_TEACHER_STUDENT_STRATEGY.md`), not
a decision made this phase.

## Modal GPU trusted-inference qualification (live-verified this phase)

Per spec section 16, a tiny synthetic (non-Genesis) workload was run
against a real Modal GPU Function (never a Sandbox — this is trusted
inference infrastructure, a separate trust domain from the
NOT_QUALIFIED SandboxBackend) to qualify Modal as a candidate inference
provider:

- GPU: NVIDIA L4 (24GB class), compute capability 8.9
- CUDA available: yes (`torch.cuda.is_available() == True`)
- PyTorch: 2.5.1+cu124
- BF16: confirmed working (a real 2048×2048 bf16 matmul executed on-GPU, `torch.bfloat16` dtype confirmed on the result)
- FP8: `torch.float8_e4m3fn` dtype available and constructible on this GPU/torch combination
- `nvidia-smi`: "NVIDIA L4, 580.95.05, 23034 MiB" — confirms real hardware, not a mock
- No Genesis/frontier model weights were downloaded for this test
- Credit consumed: ~$0.0045 (ephemeral Modal Function usage) on top of a ~$0.001 pre-existing session baseline — total metered cost this phase ~$0.0055, billed cost $0.00 (fully covered by included credits), comfortably under the phase's $1 ceiling

This confirms Modal is a technically viable trusted-inference provider
for at least single-GPU workloads. Multi-GPU tensor-parallel Functions
were not live-tested this phase (not needed to establish basic
GPU/CUDA/BF16/FP8 viability, and would cost meaningfully more) — their
support is confirmed only via Modal's own documentation (see above),
not by a live ORNEUR test, and should be qualified separately before
any real multi-GPU frontier-candidate work.

## Race Engineering (secondary compute source, research only)

Per spec section 15, this phase researched Race's current live GPU
inventory/rates only — no balance was checked against actual spend
requirements in enough detail to declare it sufficient, and no
spend/top-up occurred. Treated as a secondary, not-yet-quantified
compute source pending further owner-directed research.

## 10K-user serving implications (capacity architecture, not provisioning)

For any candidate that clears foundation-model selection, serving
10,000 real-time users requires (regardless of which candidate is
chosen): continuous batching, multiple replicas behind a router,
autoscaling tied to concurrent-request/queue-depth signals, streaming
token delivery, KV-cache-aware request routing (sticky sessions or
prefix caching), and failover across replicas/regions. For the
100B+-total-parameter candidates, EACH replica alone requires the
multi-GPU weight-storage footprint in the table above — meaning 10K-
user serving of a true frontier-scale model implies many multi-GPU
replicas running concurrently, a substantially larger and more
expensive deployment than the smaller Qwen3.8-27B-class candidates
would require per replica. This is capacity architecture to plan
around, not a requirement to provision anything now.
