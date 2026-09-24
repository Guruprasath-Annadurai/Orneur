# Genesis Control Runtime Qualification Matrix — Phase 21B.4.20

**Runtime-compatibility evidence only. No frontier inference, no benchmark,
no private holdout, no generated-output execution, no Modal Sandbox.
CAPABILITY REMAINS UNPROVEN for every control.**

## Status (true state after this session)

| Control | Identity | Preflight | Attempt result | Technical serving | Financial acceptance | Runtime qualification | Capability |
|---|---|---|---|---|---|---|---|
| Qwen3-8B | ADMITTED | PASSED | attempt 1 = HARNESS_FAILURE (failure domain HARNESS, 34.6 s) | NOT_PROVEN | PASS (billed delta 0 at observed time) | NOT_COMPLETED | UNPROVEN |
| Mistral-Nemo-Instruct-2407 | ADMITTED | PASSED | none | NOT_TESTED | NOT_TESTED | NOT_TESTED | UNPROVEN |
| Phi-4 | ADMITTED | PASSED | none | NOT_TESTED | NOT_TESTED | NOT_TESTED | UNPROVEN |

**Attempt result is not model result.** Qwen3-8B attempt 1 was cancelled by a harness bug (Modal 1.5.5 raises the
*builtin* `TimeoutError` from `FunctionCall.get(timeout=)`; the harness did not catch it). The pinned model was never
served, so this attempt does **not** show runtime incompatibility. A model-runtime `FAILED` requires an actual valid
runtime attempt; a harness failure or financial-guard abort always leaves technical serving `NOT_PROVEN` and the
qualification `NOT_COMPLETED` (machine-enforced; see `FAILURE_DOMAIN_BY_OUTCOME`). The attempt itself is preserved
unchanged in the history: 34.6 s, billed delta 0 at observed time, cleanup PASS, 0 live tasks, 0 containers,
settlement `BILLING_SETTLEMENT_NOT_YET_OBSERVABLE`. Its true settled cost is unconfirmed and is not assumed to be zero.

**No control is RUNTIME_QUALIFIED. No GPU may start** until attempt 1's settlement is observable
(`QWEN_ATTEMPT_1_SETTLEMENT_STILL_UNRESOLVED` as of the last reconciliation, 2026-09-24T12:19Z; see
`GENESIS_CONTROL_QWEN3_8B_ATTEMPT1_SETTLEMENT_RECONCILIATION_*.json`). This is not a zero-cash-runway block:
every preflight passed. Resume conditions: previous settlement observable AND owner payable delta 0 AND
remaining credit >= $5.00 reserve + $1.25 maximum run cost AND zero live resources. Then exactly one Qwen3-8B
retry (attempt 2), then Mistral-Nemo, then Phi-4, each gated on the previous settlement.

## Provider migration (Modal -> Lightning AI)

Owner decision: no new Phase 21B.4.20 execution on Modal; Modal evidence and the unresolved Qwen attempt are preserved as
historical provider-specific evidence (`GENESIS_CONTROL_PROVIDER_MIGRATION_MODAL_TO_LIGHTNING_2026-09-24.json`).

**Lightning account (verified via the official SDK as `annaduraiguruprasath5`):** Free plan, 4.98 complimentary credits,
balance limit 0, no payment method, no GPU running. No single A100-80GB exists on this account; the only A100 is
8 x 40GB at 30.9 credits/h and all A100/H100/H200/B200 machines are tier-restricted. The chosen GPU was a single L40S 48GB
(3.54 credits/h; fits all three controls in BF16, unquantized) with a 900 s cap (0.885 credits) plus a Studio-side watchdog.

**CPU staging (free, done):** vLLM 0.29.0 / torch 2.13.0 / transformers 5.17.0 in a Studio venv; all three controls' exact
pinned revisions downloaded and verified (summed weight bytes equal the recorded exact bytes and every file's sha256 equals
its Hugging Face LFS sha256).

**GPU start (blocked by the provider):** the Studio switch to the L40S was refused with HTTP 400 PermissionDenied:
*"Free-tier users must have a verified payment method before starting GPU compute."* Every zero-cash gate had passed
(the plan-feature flag `requires_credit_card_verification` did not predict this). No GPU was allocated, credits are
unchanged (4.9823576) and cleanup is verified. The owner's rule forbids adding or requiring a card, so Lightning GPU
execution cannot proceed under it. The gate now refuses automatically while this rejection stands
(`GENESIS_LIGHTNING_PROVIDER_GPU_REJECTION_2026-09-24.json`). No control has run on any provider; statuses are unchanged.

## Hugging Face ZeroGPU fallback (read-only eligibility check)

Modal and Lightning execution is stopped for this phase (audit decision). The next candidate, Hugging Face ZeroGPU, is a
**model runtime compatibility** test (exact BF16 checkpoint, Gradio/PyTorch), never a production-serving proof; production
serving qualification stays **UNCHANGED**. Official rules: free personal accounts in good standing (verified email, older
than 30 days) may host up to 2 ZeroGPU Spaces; the free daily GPU quota is 5 minutes; hardware `large` is 48 GB.

**Eligibility: NOT ESTABLISHED.** No authenticated Hugging Face session is available (no local token; Chrome shows the login
form), so eligibility can be neither confirmed nor refused; this is not `HF_ZEROGPU_NOT_ELIGIBLE`. No Space, repository or GPU
was created and no account action was taken. Estimated BF16 memory fits the 48 GB tier for all three controls (about 14.7 to
27.5 GB headroom, assuming a 4 GB overhead reserve; an estimate, not a measurement). Evidence:
`GENESIS_HF_ZEROGPU_ELIGIBILITY_AND_HEADROOM_2026-09-24.json`. Statuses below are unchanged.

### Update: authenticated Hugging Face account verified -- HF_ZEROGPU_NOT_ELIGIBLE

The owner logged in to Hugging Face (personal account `Orneur`, email verified, not PRO, no payment method, credits $0.00,
ZeroGPU quota shown as 0/5 minutes). The account was created 2026-09-24T15:34:25Z, so it fails the documented
"older than 30 days" hosting rule: **HF_ZEROGPU_NOT_ELIGIBLE** for now (earliest 2026-10-24, not guaranteed). The
account-specific hardware selector cannot be seen without creating a Space, so `large`/48 GB remains documentation-only.
No Space, GPU quota, purchase or setting change was made. Evidence: `GENESIS_HF_ZEROGPU_ACCOUNT_VERIFICATION_2026-09-24.json`.
The email address is not persisted. Control statuses, production serving qualification and program state are unchanged.

## razorBridge (provider fallback 3)

Public facts verified (pricing page and docs) and account-side state read in the owner's logged-in web app: EUR 10 signup grant
as the only ledger entry, no payment-method or top-up control anywhere, owner payable 0, H100 80 GB selectable at EUR 4.29/hr,
durations 1/2/4/8 h. The zero-cash gate passed. Two structural constraints were recorded: blade disks are discarded at teardown
(every install and model download runs on the billed blade) and blades can be started and stopped only in the web app.

**Start refused by the provider:** two attempts about 5 minutes apart both returned "Self-serve GPU sessions are temporarily
paused for maintenance." No blade was created, the balance is still EUR 10 and nothing was charged. Qwen3-8B attempt 3 is
recorded as `BLOCKED_NO_GPU`. The razorBridge gate, validator and SSH operator script are implemented and unit-tested but have
never been run against a real blade. Evidence: `GENESIS_RAZORBRIDGE_ACCOUNT_GATE_QWEN3_8B_2026-09-24.json`,
`GENESIS_RAZORBRIDGE_PROVIDER_START_REFUSED_2026-09-24.json`. Control statuses are unchanged.

## Billing reconciliation

- **Historical GLM record (preserved, not rewritten):** before invocation 2 metered $8.68 / billed $0 / credits -$8.68;
  after, metered $33.52 / billed $3.52 / credits -$30.00, owner delta $3.52, zero-cash gate VIOLATED.
- **Current live baseline (2026-09-24):** metered $20.03 / billed $0 / credits -$20.03.
- **Discrepancy:** unresolved billing-observability discrepancy, persisted in
  `GENESIS_BILLING_DISCREPANCY_OBSERVATION_2026-09-24.json`; the historical incident is not treated as disproven.
- **Qwen3-8B attempt 1:** metered delta 0 (not visible), billed delta 0, derived remaining credit $9.97 before and $9.97 after
  (unchanged only because usage was not visible). Settlement ambiguity: **YES**.
- **Re-reconciliation 2026-09-24T12:15-12:19Z (read-only, ~1 h after the attempt):** metered $20.03 (ephemeral apps $20.03366467, unchanged to 8 decimals),
  credits -$20.03, billed $0; hourly itemized rows for 2026-09-23..25 contain nothing for the Qwen app (latest row anywhere: the 2026-09-23T08:00 CPU preflight);
  0 containers, 0 volumes, both deployed apps idle. Verdict `QWEN_ATTEMPT_1_SETTLEMENT_STILL_UNRESOLVED`; no GPU started.
- **Execution attribution (read-only, 2026-09-24T13:05-13:09Z):** classification **C. EXECUTION_ATTRIBUTION_UNRESOLVED** (see
  `GENESIS_CONTROL_QWEN3_8B_ATTEMPT1_EXECUTION_ATTRIBUTION_2026-09-24.json`). App lifetime 33.8 s, no function/container logs, empty task/stats and no itemized
  11:00Z row are consistent with cancellation before allocation but do not prove it; FunctionCallList is unavailable and terminated tasks are not retained.
  Gate stays closed; retry eligible: NO.
- Gates per run: owner-payable gate (billed must not exceed baseline) AND credit-coverage gate
  (derived remaining >= $5.00 reserve + $1.25 maximum authorized run cost).

## Fresh account-specific financial preflight (live, read-only)

Captured 2026-09-24 immediately before allocation via `modal billing summary --json` / `billing rates --json` /
`app|container|volume list`.

- Starting owner-payable (billed) cost: **$0.00**; metered $20.03 fully absorbed by $20.03 credits
- Known remaining credit: **~$9.97**, *derived* (owner pool $30.00 minus credits applied; Modal exposes no remaining-credit field)
- GPU: A100-80GB x 1 at $2.50/h; hard ceiling 20 min; worst case = rate x 20 min x 1.5 = **$1.25** per job
- Fixed reserve **$5.00**; gate requires remaining >= reserve + $1.25

The runway is thin (three worst-case jobs $3.75 vs $4.97 usable) and must be re-checked live before every launch.

## Planned runtime topology (derived, not measured)

Common: vLLM `v0.29.0` official image, digest
`sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b`
(the digest proven for Mistral Small 4 in Phase 21B.4.12.3), 1× A100-80GB,
tensor-parallel 1, BF16, `--max-model-len 4096`, `--gpu-memory-utilization 0.90`
(≈72 GB budget), OpenAI-compatible server started for the **exact pinned
revision** from a local snapshot pre-downloaded with `revision=<pinned commit>`
(consolidated duplicates excluded).

| Control | Pinned revision | Raw BF16 weights | vs 24 GB | Runtime flags | Template / stop path |
|---|---|---|---|---|---|
| Qwen3-8B | `b968826d9c46dd6066d109eabc6255188de91218` | 16,381,516,776 B (5 shards) | fits raw weights, but runtime overhead must not be assumed to fit | `--reasoning-parser qwen3` (canonical control spec; thinking template default ON) | tokenizer_config chat_template, eos `<\|im_end\|>` |
| Mistral-Nemo-Instruct-2407 | `04d8a90549d23fc6bd7f642064003592df51e9b3` | 24,495,607,104 B (HF 5-shard) | does **not** fit safely | `--tokenizer-mode hf --config-format hf --load-format safetensors` (pins the HF path; mistral-common path not used) | tokenizer_config chat_template, eos `</s>` |
| Phi-4 | `2db69c1c3e91a05d2c64a3185acfbaf36f744e25` | 29,319,042,992 B (6 shards) | does **not** fit safely | default (Phi3ForCausalLM) | ChatML-like `<\|im_sep\|>`, eos `<\|im_end\|>` |

An 80 GB-class GPU is chosen for fidelity, not minimal cost: weights plus
runtime overhead plus a 4,096-token KV cache (roughly 0.6–0.85 GB per
sequence, derived from architecture parameters and **not verified this
phase**) sit far inside the 72 GB budget, avoiding OOM risk and any reliance
on unconfirmed multi-GPU tensor-parallel support.

## Smoke prompts (not a benchmark)

`temperature=0`, `top_p=1`, `seed=0`, small `max_tokens` (1024 for Qwen's
thinking template, 64 otherwise). User-only messages:

- **A** — `Reply with exactly:` / `READY` (streamed, for first-token latency)
- **B** — `Return the single integer result of:` / `2 + 3`
- **C** — `Return valid JSON with one field:` / `{"status":"ready"}`

Technical PASS = server ready, `/v1/models` identity matches the pinned repo id,
all three requests HTTP 200 with non-empty content, clean shutdown, zero orphan
processes. Exact-match against the expected strings is recorded but non-blocking;
any difference is documented, never hidden. Generated text is data only.

## Acceptance rules (machine-enforced in `orca/eval/control_runtime_qualification.py`)

- `RUNTIME_QUALIFIED` only if technical `QUALIFIED` **and** financial `PASS` **and**
  cleanup `PASS` with zero live resources **and** verified identity **and** verified hashes.
- Financial `PASS` only if `owner_billed_delta_usd == 0` exactly. Technical success with any
  positive owner billing is `NOT_ACCEPTED` (the GLM-5.3-Flash mistake must not recur).
- No retry after positive billing, unclear cost state, or a failed cleanup; no automatic retry ever.
- Every attempt is recorded; a hidden or omitted attempt fails validation.

## Attempt accounting

| Control | Attempt | Outcome / failure domain | Duration | Owner billed delta (observed) | Cleanup | Settlement |
|---|---|---|---|---|---|---|
| Qwen3-8B | 1 | HARNESS_FAILURE / HARNESS (poll `TimeoutError` not caught) | 34.6 s | 0 | PASS | BILLING_SETTLEMENT_NOT_YET_OBSERVABLE |

## Environment-only behaviour (not exercised by CI)

CI has no Modal SDK, so the deterministic suite runs the harness against a recording stand-in for `modal`, plus static
AST checks, and does **not** test real Modal SDK behaviour. Validated in CI: module syntax, constants, pinned image
digest/GPU/ceiling passed to the decorator, CLI mode declarations, no `eval`/`exec`/shell/Sandbox/generated-output
execution, financial-gate and result-validator wiring, and that `reconcile` is read-only. Environment-only (needs a real
Modal workspace): `FunctionCall.get(timeout=)` exception types and `cancel(terminate_containers=True)` semantics,
image build/pull, GPU scheduling and container lifecycle, vLLM serving behaviour, and the billing CLI's real output and
settlement latency.

## To resume (each launch needs the previous settlement observable and a fresh gate)

```bash
.venv/bin/python scripts/phase21b_4_20_control_runtime_qualification.py --control qwen3_8b --mode reconcile --attempt 1   # read-only
.venv/bin/python scripts/phase21b_4_20_control_runtime_qualification.py --control qwen3_8b --mode run                       # attempt 2
```

The harness refuses to start while any earlier attempt's billing settlement is unresolved.

## Program state (unchanged)

- GENESIS FOUNDATION: NOT SELECTED
- GENESIS FRONTIER STATUS: UNPROVEN
- CONTROL CAPABILITY STATUS: UNPROVEN
- PHASE 21C: NOT AUTHORIZED
- FRONTIER EXECUTION AUTHORIZED: NO
