# Phase 21B.4.2 — Resource Qualification + First Real Genesis Baseline: CLOSURE

## Outcome

**LOCAL M4 NOT SUFFICIENT FOR THIS CANDIDATE — CLOUD/DATACENTER RESOURCE
REQUIRES OWNER AUTHORIZATION.**

No real Genesis foundation baseline was recorded. `genesis-eval-v1`
remains unfrozen. No training, fine-tuning, or Phase 21C work occurred
(none was authorized or attempted).

## What happened, in order

1. **Preflight re-verification** (repo state, CI, router truth, suite
   state, sandbox, adapter, CLI, transaction) — all confirmed matching
   the Phase 21B.4.1 closure state. See
   `docs/orneur/phase-21/GENESIS_RESOURCE_QUALIFICATION_21B4_2.json`
   for the full machine-readable record.

2. **Resource qualification** — read live from the actual machine
   (`sysctl`, `memory_pressure`, `vm_stat`, `df`), never inferred from
   chip name:
   - Apple M4, 10 cores (4P+6E), **16GB total unified memory**
   - At measurement time: 47-52% system-wide free (`memory_pressure`),
     swap already 80-90% utilized from the host's own long-running
     processes (IDE, Claude Code, Docker Desktop, browsers)
   - Disk: only 24GB free on a 460GB/95%-full volume

3. **Live candidate re-verification** (HF API, not memory) for all 4
   finalists — exact revision SHAs, licenses, architectures, and
   **exact download sizes**:
   | Candidate | License | Download size | Disk verdict |
   |---|---|---|---|
   | Qwen3-8B | apache-2.0 | 16.4 GB | would leave <8GB free — NOT_QUALIFIED |
   | Mistral-Nemo-Instruct-2407 | apache-2.0 | 49.0 GB | exceeds free disk outright — NOT_QUALIFIED |
   | Phi-4 | mit | 29.3 GB | exceeds free disk outright — NOT_QUALIFIED |
   | Phi-4-mini-instruct | mit | 7.7 GB | leaves ~16GB free — QUALIFIED_WITH_LIMITS |

   Only Phi-4-mini-instruct passed even the disk gate. Per spec §5,
   selected as a **hardware-constrained first execution/infrastructure
   baseline** — explicitly NOT a foundation-shootout candidate
   substitution, and this closure does not declare it a winner of
   anything.

4. **Preflight dry run** for Phi-4-mini-instruct
   (`microsoft/Phi-4-mini-instruct` @
   `cfbefacb99257ffa30c83adab238a50856ac3083`, backend=transformers,
   device=mps) returned `READY FOR REAL BASELINE`, no blockers.

5. **Model download** — succeeded. 7.2GB, ~19 minutes, via
   `huggingface_hub.snapshot_download` pinned to the exact revision.
   Disk after download: 18GB free (96% used) — within the planned
   safety margin.

6. **Genuine technical finding, mid-preparation**: `bitsandbytes` (the
   quantization library the original resource budget assumed would
   shrink the memory footprint to ~2.2GB via 4-bit/nf4) is **not
   installed, and does not support Apple MPS** — its int4/int8 kernels
   are CUDA-only. This invalidated the original memory budget; the
   only available load path on this host is native `bfloat16`
   (matching the model's stored precision), i.e. the full ~7.6GB
   weight footprint, not the ~2.2GB originally estimated.

7. **Model-load smoke test** (Step 8; 3 non-eval prompts, never
   genesis-eval-v1 tasks) — run as a monitored, killable background
   process with a live memory-pressure watchdog polling every 5s,
   specifically because the corrected (larger) memory footprint made
   this a genuine safety question, not a formality.
   - Safetensors CPU-side weight loading completed fine (194/194
     tensors, <1s — mmap'd, no issue).
   - System-wide free memory then crashed **52% → 25% → 2% within
     ~15-20 seconds** during the `.to("mps")` device-transfer step
     (PyTorch's MPS backend allocates a distinct device-side buffer
     per tensor rather than reinterpreting the CPU-resident page, so
     this is a real, not illusory, near-doubling of resident memory
     during transfer).
   - The watchdog killed the process at the 2% reading, before
     macOS's own OOM killer could act on arbitrary processes (which
     could have included the user's other live applications).
   - Confirmed clean recovery afterward: memory returned to 63% free
     within seconds of the kill.
   - No generation was attempted; the process was killed before any
     prompt was sent to the model.

8. **Per spec §17**: this is a genuine, empirically-measured resource
   inadequacy, found during the mandated smoke-test safety gate before
   the real 90-task suite was ever touched. Per the explicit
   instruction to not "repeatedly crash/reload" the host or "lower
   scientific standards merely to finish," no further load attempts
   (e.g. CPU-only fallback) were made without separate owner
   authorization — MPS was the only device explicitly authorized this
   phase.

9. **Cleanup**: the downloaded 7.2GB model cache (created this session
   for this smoke test, no longer usable under the current plan) was
   removed to restore the host's disk headroom, which was already
   critically tight (95% full) before this phase began. Disk state
   confirmed restored to the pre-download baseline (24GB free).

## Resource requirement report (spec §17)

- **Model attempted**: microsoft/Phi-4-mini-instruct (the
  hardware-constrained infrastructure-baseline candidate, not an 8B/12B
  finalist)
- **Point of failure**: MPS device-transfer step of `model.to("mps")`,
  immediately after successful CPU-side safetensors load — not model
  incompatibility, not adapter code, not the sandbox, not the suite
- **Measured resource data**: 16GB total unified memory; ~47-52%
  free/reclaimable before load; swap already 80-90% utilized from the
  host's own pre-existing workload; free memory crashed to 2% within
  ~20s of starting the device transfer
- **Minimum realistic next resource**: a machine with either (a)
  meaningfully more *actually-free* system memory at the time of the
  run (not just more total RAM — this host's total 16GB was already
  mostly claimed by the user's own live workload), ideally with no
  competing live workload, or (b) a discrete GPU with its own VRAM
  pool separate from host system RAM (CUDA), so model weights don't
  contend with the OS/other applications for the same physical memory
- **Preferred GPU VRAM class**: 24GB+ (e.g. RTX 4090, A10G, L4) for
  Qwen3-8B at bf16 with comfortable KV-cache/activation headroom;
  48GB+ (e.g. A100-40GB/80GB) for Mistral-Nemo-Instruct-2407 (49GB) or
  Phi-4 (29.3GB) at full precision, or a CUDA-backed 4-bit/8-bit
  quantized load (bitsandbytes, which works on CUDA but not this
  host's MPS) to reduce that requirement substantially
- **Storage requirement**: candidate size + ~20-30% headroom —
  16.4GB (Qwen3-8B) / 49.0GB (Mistral-Nemo) / 29.3GB (Phi-4) / 7.7GB
  (Phi-4-mini) — this host's current 18-24GB free disk is itself
  marginal even setting memory aside
- **Recommended quantization**: CUDA-backed bitsandbytes 4-bit (nf4)
  or 8-bit — the single most consequential missing capability
  identified this phase; it is what the original resource budget
  assumed would be available and was not

**LOCAL M4 NOT SUFFICIENT FOR THIS CANDIDATE — CLOUD/DATACENTER
RESOURCE REQUIRES OWNER AUTHORIZATION.**

Paid compute remains unauthorized. No money was spent. No cloud
resource was created.

## Router / public truth

Unaffected by this phase — no code was modified, only documentation
added:
- Genesis lifecycle: no trained canonical (3B) checkpoint exists (all
  registered "genesis"-family entries are RETIRED legacy 7B artifacts)
- Genesis availability: no candidate is promoted/available
- Canonical base: `unsloth/Qwen2.5-3B-Instruct`, `qwen-research` /
  `RESTRICTED` — unchanged
- Trained checkpoint: none
- `genesis-eval-v1`: still unfrozen, 90 tasks, content/scoring digests
  unchanged from Phase 21B.4.1

## Phase 21C

Remains locked. Not authorized. Not started.
