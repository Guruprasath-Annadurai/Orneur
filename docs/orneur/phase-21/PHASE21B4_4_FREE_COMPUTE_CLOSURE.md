# Phase 21B.4.4 — Free-Credit Genesis Compute Acquisition: CLOSURE

## Outcome

No compute provisioned. No charge incurred. Three research/planning
artifacts produced (`GENESIS_FREE_GPU_CREDIT_MATRIX.md`,
`GENESIS_ZERO_COST_COMPUTE_PLAN.md`,
`GENESIS_FREE_COMPUTE_EXECUTION_GATE.md`). One real architectural
addition: `orca/eval/sandbox_backend.py`, a `SandboxBackend` protocol
decoupling Genesis's evaluator from the literal Docker CLI, per spec
section 6, without weakening or changing the isolation guarantees
Phase 21B.4.1 empirically verified.

## Foundation target preserved

Qwen3-8B, Mistral-Nemo-Instruct-2407, and Phi-4 remain the three
finalists. No smaller model was substituted to fit easier-to-obtain
free hardware. Phi-4-mini-instruct remains infrastructure-reference
only, unchanged from prior phases.

## Free-credit research summary

11 programs researched live (2026-09-18): 1 classified
IMMEDIATELY USABLE pending live verification (Lightning AI free
plan, T4/16GB), 4 classified APPLICATION REQUIRED (AWS Activate
Founders Tier, NVIDIA Inception, Vast.ai Startup Program, HF
Community GPU Grants), 6 classified NOT SUITABLE for stated reasons
(GCP $300 trial structurally requires a paid-account upgrade before
any GPU access; RunPod's new-account bonus requires a $10 cash
deposit first, directly violating the ₹0 constraint; Oracle Always
Free has no GPU at all; Paperspace's free GPUs are architecturally
too old/weak; Azure's free credit window is short with uncertain GPU
quota; GitHub Student Pack's one relevant GPU credit was discontinued
2026-08-01). Full detail: `GENESIS_FREE_GPU_CREDIT_MATRIX.md`.

## Docker constraint re-examined (spec section 6)

Re-examined from first principles: the real requirement is an
independently-enforced isolation boundary, not literally the `docker`
binary. Hugging Face Spaces (ZeroGPU/Community GPU Grants), Colab,
and Kaggle were all re-checked under this framing and remain
unsuitable for the same underlying reason as Phase 21B.4.3 -- none
expose a nested container-execution boundary this project's evaluator
can call into and independently verify. No new alternative backend was
found or verified this phase.

What DID change: `orca.eval.genesis_suite.score_unit_test()` now
depends on the `SandboxBackend` protocol (`orca/eval/sandbox_backend.py`)
rather than importing `orca.eval.sandbox_docker` directly, with
`DockerSandboxBackend` as the only implementation and the unchanged
default. This is architecture-only -- no behavior, no security
posture, and no test outcome changed (45/45 targeted tests pass,
including the full pre-existing Docker sandbox suite). It exists so
that if a future platform's isolation is independently verified the
same way Docker's was in Phase 21B.4.1 (live reproduction of the
filesystem/network/ctypes escape classes, not assumed from marketing
copy), it can be plugged in without touching `genesis_suite.py` again.

## Zero-spend safety

No resource was provisioned, so no live safeguard was needed this
phase. `GENESIS_ZERO_COST_COMPUTE_PLAN.md` specifies the required
safeguards for each pending path (Lightning AI: stay within the
monthly free-tier allocation, no paid-GPU-tier selection; AWS
Activate: mandatory hard AWS Budgets cap + billing alarm configured
before any instance launch, explicit shutdown after each session) --
these are commitments for when a resource is authorized, not
retroactive claims about anything already running.

## Router / public truth

Unchanged. Genesis remains without a trained canonical checkpoint,
unavailable, canonical base unchanged. `genesis-eval-v1` remains
unfrozen; not executed, not inspected, not modified this phase (spec
section 11 honored -- no smoke test against real candidates occurred
this phase either, since no qualified resource exists yet).

## Phase 21C

Remains locked. Not authorized. Not started.
