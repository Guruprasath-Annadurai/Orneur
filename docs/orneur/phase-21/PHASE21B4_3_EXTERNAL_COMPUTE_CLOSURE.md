# Phase 21B.4.3 — External CUDA Resource Qualification: CLOSURE

## Outcome

Technical resource contract established; current provider landscape
researched; **no resource provisioned, no charge incurred.** Full
decision document: `docs/orneur/phase-21/GENESIS_EXTERNAL_COMPUTE_DECISION.md`.

## M4 status (closed experiment)

`local-m4-16gb: NOT_QUALIFIED` — recorded as a closed resource
experiment in `orca.eval.compute_resource.LOCAL_M4_16GB`. No further
attempts were made against it this phase (no re-download, no MPS
retry, no CPU-inference retry, no model substitution to fit the
laptop) per spec section 2.

## ComputeResource abstraction

No prior `ComputeResource` abstraction existed in the codebase. Added
the minimum clean contract at `orca/eval/compute_resource.py` (spec
section 8): a frozen dataclass describing capability (accelerator
type/count/memory, system memory, storage, backend, device, CUDA
version, Docker availability, supported quantization modes,
ephemeral/persistent) with no vendor branching logic anywhere in
Genesis's evaluation/execution code. Three descriptive records were
populated: `LOCAL_M4_16GB` (closed, NOT_QUALIFIED), and the two
technical resource classes from Section 5 below
(`MINIMUM_VIABLE_CUDA_CONTRACT`, `PREFERRED_CUDA_CONTRACT`). This
module provisions nothing — it is a pure capability/planning record,
matching spec section 10's "do not provision anything."

## Resource classes (spec section 5)

See `GENESIS_EXTERNAL_COMPUTE_DECISION.md` Sections 1-2 for the full
VRAM math and reasoning. Summary:
- **Minimum viable**: 16GB VRAM CUDA GPU, 32GB system RAM, 150GB disk,
  uniform 4-bit NF4 — tight margin (~6.6GB headroom on the largest
  finalist).
- **Preferred**: 24GB VRAM CUDA GPU, 32GB system RAM, 150GB disk,
  uniform 4-bit NF4 — comfortable margin (>60% headroom on the largest
  finalist); also supports uniform 8-bit if higher fidelity is wanted.

## The 24GB question (spec section 6)

**Answered: YES**, with large margin, under uniform 4-bit NF4 — see
`GENESIS_EXTERNAL_COMPUTE_DECISION.md` Section 3 for the full
candidate-by-candidate VRAM table and the bf16/int8/NF4 comparison
that proves (not assumes) this.

## Scientific parity (spec section 4)

Recommended uniform mode: **4-bit NF4 (bitsandbytes) for all three
finalists**, identically configured. This is deliberately NOT the
same quantization used (or attempted) on the local M4 — that attempt
used no quantization at all (bfloat16, the only path bitsandbytes-less
MPS offered), so there is no continuity to preserve or bias to correct
for. No deviation from uniform treatment is currently anticipated;
if actual execution reveals one candidate requires a different mode
for a genuine technical reason, that deviation must be recorded
explicitly per spec, not silently absorbed into an average.

## Canonical shootout execution configuration (prepared, not executed)

To be used identically for all three finalists at actual execution
time, per spec section 13:

```json
{
  "quantization": "4bit",
  "bitsandbytes_config": {"load_in_4bit": true, "bnb_4bit_quant_type": "nf4"},
  "compute_dtype": "bfloat16",
  "device_map": "cuda:0",
  "max_context_tokens": 2048,
  "max_new_tokens": 512,
  "temperature": 0.0,
  "top_p": 1.0,
  "seed": 42,
  "suite_id": "genesis-eval-v1",
  "suite_version": "v1",
  "suite_content_digest": "c9745c132d0204149479d6abc68bf8822f1120088a4884051b5fdb794aaa36d1",
  "suite_scoring_contract_digest": "8bc3a331c2492886890a8da8acc632ec870720d1547f60aeaeca5215db9e2e4d",
  "sandbox_contract_id": "docker-v1-<resolved live at execution time -- image digest may differ on the execution host>",
  "software_sha": "2b9d7c9b0ae2112985a4c5c54431fe8f52b504fe"
}
```

Per spec section 12, model/tokenizer revision SHAs are deliberately
**not** pinned into this canonical config ahead of time — they must be
freshly re-resolved from the upstream HF API at actual execution time
(never reused from this phase's or Phase 21B.4.2's planning-time
lookups), and the result manifest must record whichever revision was
actually executed.

## Execution order (prepared, not started)

1. First real baseline (whichever finalist runs first under this
   config)
2. Transactional freeze of `genesis-eval-v1` (permanent — the first
   successfully recorded baseline result freezes the suite for every
   subsequent candidate)
3. Qwen3-8B
4. Mistral-Nemo-Instruct-2407
5. Phi-4
6. Optional: Phi-4-mini-instruct as an infrastructure reference only
   (not a foundation-shootout finalist)

No step in this order has been executed. Real inference requires a
separate, explicit owner resource authorization per Section 11 of
`GENESIS_EXTERNAL_COMPUTE_DECISION.md`.

## Router / public truth

Unchanged — no code affecting Genesis's public/router state was
modified. Genesis remains without a trained canonical checkpoint,
unavailable, canonical base unchanged
(`unsloth/Qwen2.5-3B-Instruct`, `qwen-research`/`RESTRICTED`).
`genesis-eval-v1` remains unfrozen; content/scoring digests re-verified
unchanged this phase.

## Phase 21C

Remains locked. Not authorized. Not started.
