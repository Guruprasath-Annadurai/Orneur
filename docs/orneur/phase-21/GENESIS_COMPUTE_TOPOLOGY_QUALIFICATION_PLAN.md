# Genesis Compute Topology Qualification Plan

**Phase 21B.4.10. NO GPU WAS STARTED this phase.** This document
reverifies current Modal GPU inventory/rates (read-only, supported CLI
only) and records, per deployable candidate, the THEORETICAL weight-
storage GPU count plus a proposed NEXT-PHASE practical topology to test
— never promoting the theoretical count to a qualified claim.

## Live-reverified Modal GPU inventory and rates (2026-09-19, `modal billing rates`)

| GPU | Rate/hr |
|---|---|
| T4 | $0.59 |
| L4 | $0.80 |
| A10G | $1.10 |
| L40S | $1.95 |
| A100 (40GB) | $2.10 |
| A100 (80GB) | $2.50 |
| RTX PRO 6000 | $3.03 |
| H100 | $3.95 |
| H200 | $4.54 |
| B200 | $6.25 |
| B300 | $7.10 |

**Unchanged from the Phase 21B.4.8/.9.2 rate card** — no rate has moved
since this project's last live check. CPU/Memory/Volume rates also
reverified unchanged (`$0.0473/core/hr` CPU, `$0.008/GiB/hr` memory,
`$0.09/GiB/month` volumes).

## Multi-GPU support (Modal documentation — not re-fetched from Modal's own docs this phase)

Modal's documented support for multi-GPU tensor-parallel
Functions/Classes (`gpu="H100:N"`-style allocation, with worked vLLM/
SGLang deployment examples) was live-confirmed in Phase 21B.4.8 and is
restated here **unchanged** — this phase did not re-fetch Modal's
documentation to re-confirm it, since the GPU rate card (which this
phase DID re-fetch) shows no infrastructure change that would suggest
this support was withdrawn. A future phase attempting an actual
multi-GPU smoke test should re-confirm the exact supported GPU-count
syntax and any per-GPU-type multi-GPU limits directly against Modal's
current documentation before relying on this restatement.

## Per-candidate topology plan

| Candidate | Theoretical weight-storage floor (80GB-class GPUs, from the registry) | Proposed next-phase practical topology to TEST | Current status |
|---|---|---|---|
| Qwen3.8-27B | BF16: 1×; FP8: 1×; INT4: 1× | Single L4 (24GB) at INT4, OR single A100-80GB at BF16/FP8 for more serving headroom | `UNQUALIFIED / TBD` |
| Qwen3.8-Flash-Next | BF16: 5×; FP8: 3×; INT4: 2× | 3×A100-80GB at FP8 (the corrected theoretical floor) as the first real multi-GPU tensor-parallel smoke candidate — but its `LICENSE_REVIEW_REQUIRED` status should resolve BEFORE spending any compute on it | `UNQUALIFIED / TBD` |
| Mistral Small 4 | BF16: 3×; FP8: 2×; INT4: 1× | 2×A100-80GB at its OFFICIAL FP8 checkpoint (no conversion needed — confirmed live this phase) | `UNQUALIFIED / TBD` |
| GLM-5.3-Flash | BF16: 9×; FP8: 5×; INT4: 2× | The 2×INT4 theoretical floor has essentially zero headroom (160.7GB weight floor against 160GB raw capacity) and is not recommended as the first test configuration; propose starting at 5×A100-80GB (FP8, its official checkpoint) instead, with INT4 attempted only after FP8 succeeds | `UNQUALIFIED / TBD` |
| Qwen3-8B (control) | 1× at any precision (80GB-class); also fits 1×L4 (24GB) at FP8/INT4 | Single L4 | `UNQUALIFIED / TBD` |
| Mistral-Nemo-Instruct-2407 (control) | 1× at any precision (80GB-class); BF16 borderline on L4 (24.5GB floor vs. 24GB capacity) | Single L4 at FP8/INT4 (BF16 not recommended on L4 given zero headroom) | `UNQUALIFIED / TBD` |
| Phi-4 (control) | 1× at FP8/INT4, 2× at BF16 (80GB-class); fits 1×L4 at FP8/INT4 | Single L4 at FP8/INT4 | `UNQUALIFIED / TBD` |

**No theoretical count above is promoted to "qualified practical
topology."** Every row remains `UNQUALIFIED / TBD` until a real
candidate-specific load succeeds on a live GPU in a future,
separately-authorized phase — exactly the same discipline
`GENESIS_FRONTIER_COST_PLAN.md` §3.1 already locked in Phase 21B.4.9.2.

## What changed this phase vs. what is carried forward

- **Re-verified live this phase**: current Modal billing state
  (`GENESIS_ZERO_CASH_EXECUTION_PLAN.md`), current GPU rate card (table
  above).
- **Carried forward unchanged**: multi-GPU documentation support claim,
  theoretical weight-storage math (already corrected in Phase
  21B.4.9.2 and unchanged by this phase's Stage-0 research, which
  confirmed rather than altered the underlying parameter counts).
- **Not attempted this phase**: any GPU start, any multi-GPU
  configuration test, any candidate load.
