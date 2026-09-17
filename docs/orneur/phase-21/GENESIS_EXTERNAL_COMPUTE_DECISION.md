# Genesis External Compute Decision (Phase 21B.4.3)

Research and technical-contract document only. **No resource has been
provisioned. No charge has been incurred. Paid compute authorization
remains NO.**

## 1. What is the minimum viable CUDA resource?

A single CUDA GPU with **16GB VRAM** (e.g. NVIDIA T4 16GB, RTX 4060 Ti
16GB), 32GB system RAM, 150GB free disk, CUDA 12.x, running all three
finalists (Qwen3-8B, Mistral-Nemo-Instruct-2407, Phi-4) under uniform
**4-bit NF4** quantization (bitsandbytes). Tightest fit is Phi-4 at an
estimated ~9.35GB total (weights + KV cache + overhead), leaving
~6.6GB headroom on 16GB — workable but tight. See
`orca.eval.compute_resource.MINIMUM_VIABLE_CUDA_CONTRACT`.

## 2. What is the preferred resource?

A single CUDA GPU with **24GB VRAM** (e.g. NVIDIA RTX 4090, A10G, L4),
32GB system RAM, 150GB free disk, CUDA 12.x. Same uniform 4-bit NF4
mode, but with ~14.6GB (>60%) headroom on the largest finalist —
comfortable margin for KV-cache growth on longer genesis-eval-v1
tasks, CUDA allocator fragmentation, and reduced OOM risk relative to
the minimum-viable class. This class also comfortably supports uniform
**8-bit** (largest finalist ~17.0GB of 24GB) if higher fidelity is
preferred over 4-bit — see Section 3. See
`orca.eval.compute_resource.PREFERRED_CUDA_CONTRACT`.

## 3. Can 24GB VRAM run all finalists under one uniform 4-bit configuration?

**YES**, with substantial margin. VRAM math (weights + KV cache @
2048 tokens, batch 1, fp16 cache + ~0.5GB runtime overhead; parameter
counts derived from actual bf16 safetensors shard sizes on the HF Hub,
not download-size totals, which for Mistral-Nemo include a redundant
duplicate `consolidated.safetensors` copy that `transformers` never
loads — see Section 3b):

| Candidate | Params (derived) | bf16 total | int8 total | **NF4 total** |
|---|---|---|---|---|
| Qwen3-8B | 8.19B | 17.18 GB | 9.81 GB | **5.51 GB** |
| Mistral-Nemo-Instruct-2407 | 12.26B | 25.43 GB | 14.40 GB | **7.97 GB** |
| Phi-4 | 14.65B | 30.23 GB | 17.04 GB | **9.35 GB** |

At bf16, only Qwen3-8B fits a 24GB card (17.18GB); Mistral-Nemo
(25.43GB) and Phi-4 (30.23GB) do not — uniform bf16 on 24GB is
**rejected**. At uniform int8, all three fit (max 17.04GB of 24GB,
~29% headroom) — technically viable but tight for the largest model.
At uniform **NF4, all three fit comfortably** (max 9.35GB of 24GB,
>60% headroom) — this is the recommended uniform mode for the
shootout, per spec section 4's preference for a resource-efficient
comparison methodology applied identically to every finalist.

### 3b. Model download size vs. GPU VRAM requirement — these are not the same thing

Phase 21B.4.2 recorded Mistral-Nemo-Instruct-2407's repo as "49.0GB,"
which was a **download-size** figure that (as re-verified live this
phase) double-counts the repo's `consolidated.safetensors` (a
redundant single-file copy of the same weights, 24.50GB) alongside the
HF-format sharded files `transformers` actually loads (5 shards,
24.51GB). The real download needed (and the real bf16 VRAM
requirement) is **~24.5GB**, not 49GB. This correction is recorded
here and in `orca/eval/compute_resource.py`; the 21B.4.2 disk-based
"NOT_QUALIFIED" verdict for Mistral-Nemo on the local M4 is unaffected
(24.5GB alone still exceeded that host's 24GB free disk), but the
figure should not be propagated uncorrected into future planning.

Download sizes needed (shard-only, excludes redundant copies):
Qwen3-8B 16.4GB, Mistral-Nemo-Instruct-2407 24.5GB, Phi-4 29.3GB —
total **70.2GB** for all three finalists.

## 4. How much host RAM is required?

**32GB recommended** (not a hard-computed minimum, but a
safety-conscious floor informed directly by the Phase 21B.4.2 finding
that a naive "total capacity" budget did not survive contact with a
real allocation spike). CPU-side staging during `from_pretrained`
with `low_cpu_mem_usage=True` and per-shard bitsandbytes quantization
is well below full model size, but headroom for the OS, Python,
tokenizer, the Docker evaluator's own containers, and ORNEUR itself
should not be assumed away as it was (incorrectly) in 21B.4.2's
original budget.

## 5. How much free disk is required?

**150GB floor recommended.** Calculation: 70.2GB (all three finalists'
real shard-only weights) + ~10GB (repo, Python venv, Docker images,
HF cache metadata) = ~80.2GB, +20% safety margin ≈ 96GB minimum;
rounded up to 150GB to retain all three candidates simultaneously
without repeatedly re-downloading tens of GB between shootout stages
(spec section 7's explicit preference).

## 6. Which provider options currently satisfy it?

Researched live this session (2026-09-18); GPU cloud pricing changes
frequently and should be re-verified against each provider's own
pricing page immediately before provisioning.

| Provider | GPU | VRAM | Docker/root access | Current price (per GPU-hr) | Suitable |
|---|---|---|---|---|---|
| RunPod (Secure Cloud) | RTX 4090 | 24GB | Full root, Docker supported | ~$0.69/hr | **YES** |
| RunPod (Community Cloud) | RTX 4090 | 24GB | Full root, Docker supported (variable host reliability) | ~$0.34/hr | YES, lower confidence |
| Lambda GPU Cloud | A10 | 24GB | Full root VM, Docker supported | ~$0.60/hr | **YES** |
| Vast.ai (marketplace) | RTX 4090 | 24GB | Varies by host; typically full container/VM access | median ~$0.42/hr (range ~$0.14-$0.59/hr) | YES, with host vetting required (spec section 9's own caveat: "only if security/reliability is acceptable") |
| Modal | A10G | 24GB | Serverless function containers -- **no raw `docker run` CLI inside the execution environment** | ~$1.10/hr (+ $30/mo free credit standard) | **NO** -- incompatible with our Phase 21B.4.1 Docker-CLI-based sandbox without re-architecting it, which is out of scope this phase |
| Google Colab (Pro/Pro+) | T4/L4/A100 (not guaranteed) | varies | Managed notebook kernel -- **no privileged Docker access** | $9.99-$49.99/mo (compute-unit budget, not a reserved GPU) | **NO** -- same Docker limitation, plus no exact-GPU guarantee |
| Kaggle | P100 16GB or 2xT4 (32GB) | 16-32GB | Managed notebook kernel -- **no privileged Docker access** | free, ~30 GPU-hr/week, 12hr session cap | **NO** -- same Docker limitation |

**Key finding**: three of the seven researched options (Modal, Colab,
Kaggle) are disqualified for this exact pipeline not on cost or GPU
grounds but because they do not provide the raw Docker daemon access
that Phase 21B.4.1's evaluator sandbox requires and fails closed
without. This is a genuine technical constraint, not a preference.

## 7. Which options are free?

Kaggle (free tier) and Colab's free T4 tier are cost-free, but both
are **NOT SUITABLE** per Section 6 (no Docker access). No genuinely
free option that also satisfies the full technical contract
(Docker-capable, 24GB-class VRAM, persistent enough storage) was
found this session. Modal's $30/month standing free credit would
cover a full shootout's estimated cost (Section 8) but is also
disqualified on the same Docker-access grounds.

## 8. Which options are paid?

RunPod, Lambda, and Vast.ai — see Section 6 for current per-hour
rates. All three are technically suitable (Docker-capable, 24GB VRAM
class, adequate storage add-ons available).

## 9. Estimated shootout cost (one full three-model, 90-task run)

**Assumptions** (explicitly flagged as planning estimates, not
measured): ~70.2GB one-time download across all three candidates
(~30-60 min on typical cloud-instance bandwidth); ~90 tasks per
candidate at a generous ~45s/task average (generation + sandbox
scoring for executable categories) ≈ ~1.1hr pure inference per
candidate; rounding up for setup/teardown/retries to **~2hr per
candidate**, **~8hr total wall-clock GPU time** for all three
candidates in one pass. These are rough planning numbers; actual
runtime should be measured, not assumed, once a resource is
authorized.

| Provider | Rate | ~8hr estimated cost |
|---|---|---|
| RunPod Community Cloud | ~$0.34/hr | **~$2.72** |
| Vast.ai (median) | ~$0.42/hr | **~$3.36** (range ~$0.90-$3.80 depending on host) |
| Lambda GPU Cloud | ~$0.60/hr | **~$4.80** |
| RunPod Secure Cloud | ~$0.69/hr | **~$5.52** |

All suitable paid options are inexpensive in absolute terms (under
$6 for a full pass at these assumptions) but **no charge will be
incurred without explicit separate owner authorization**, regardless
of how small.

## 10. Which environment gives the cleanest scientific comparison?

**RunPod Secure Cloud** is the recommended default: vetted
datacenter hosts (not an open marketplace of unknown third-party
hardware/reliability like Vast.ai), full root + Docker support,
per-second billing, predictable environment for reproducing the exact
sandbox contract and adapter configuration used elsewhere in this
project. Lambda GPU Cloud is a close, equally clean alternative.
Vast.ai remains viable but requires host vetting per-run (its own
marketplace nature makes exact reproducibility slightly less
guaranteed run-to-run unless the same specific host is pinned).

## 11. What exact owner authorization would be needed to start?

```
APPROVED — EXECUTE PHASE 21B.4 GENESIS FOUNDATION SHOOTOUT ON RUNPOD
SECURE CLOUD (RTX 4090, 24GB), UNIFORM 4-BIT NF4 QUANTIZATION,
MAXIMUM SPEND $10.
```

(Or the equivalent for whichever of the three suitable providers and
spend ceiling the owner actually authorizes — RunPod Secure Cloud is
this document's recommendation, not a decision made on the owner's
behalf.)
