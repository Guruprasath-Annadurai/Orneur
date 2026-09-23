# Qwen3.8-27B Production-Serving Qualification Specification — Phase 21B.4.15 (corrected Phase 21B.4.15.1)

**This spec is executable LATER. It does not execute now. No GPU, no
weight download, no inference, no benchmark occurs in producing this
document.**

**Phase 21B.4.15.1 correction notice:** the tool-call-parser flag in §B
below is no longer frozen at `qwen3_xml` — independent audit found the
official SGLang Cookbook for this exact model explicitly recommends
`qwen3_coder` with a checkpoint-specific rationale, creating a genuine
primary-source divergence with vLLM's own NVFP4-variant examples. See
§B's inline note for the full resolution requirement.

Governed by `GENESIS_ZERO_CASH_GPU_EXECUTION_CONTROL_SPEC_2026-09-23.md`
(monetary guardrail, mandatory precondition) and by the strict
qualification semantics in `orca/eval/runtime_qualification_manifest.py`
(`STRICT_RUNTIME_SMOKE_V2` protocol, `PRODUCTION_SERVING_RUNTIME_QUALIFIED`
type).

## A. Identity (required, verified at execution time, not assumed from this document)

- Exact repository: `Qwen/Qwen3.8-27B`
- Exact immutable revision: `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` (re-verify live against HF API immediately before execution — do not assume this phase's re-verification is still current by the time GPU work is authorized)
- Exact tokenizer revision: same
- Exact architecture: `Qwen3_5ForConditionalGeneration`
- Exact license state: Apache-2.0, `license_status: CLEAR` (re-confirm registry state at execution time)

## B. Serving runtime (required, exact — no floating tags)

- Exact engine: **vLLM** (per `GENESIS_QWEN3_8_27B_PRODUCTION_SERVING_ENGINE_DECISION_2026-09-23.md`; SGLang only if vLLM proves blocked)
- Exact engine version/commit: `v0.30.0-cu129` (re-resolve at execution time — a newer stable tag may exist by then; do not blindly reuse this exact tag without re-checking)
- Exact image digest: `vllm/vllm-openai@sha256:58fdb6bb123a81aa53f46fa4652ad8cc87e817bd1077c9832c6258ef12c1c688` (linux/amd64) — re-resolve at execution time per the same discipline used in Phase 21B.4.13 (never trust a mutable tag alone)
- Exact dependencies: transformers >=5.8.0 (confirm the resolved image's installed version at CPU-only preflight, before GPU allocation)
- Exact GPU topology: **1x NVIDIA H200, TP=1** (minimum qualification topology — see §Topology below)
- Exact precision: BF16 (the base checkpoint's native published format; do not substitute a quantized variant repository for the qualification run without separate authorization, since the registry's pinned identity is the BF16 repository)
- Exact launch args (constructed from documented building blocks per
  `QWEN3_8_27B_RUNTIME_SUPPORT_MATRIX_2026-09-23.json`, since no single
  official BF16+H200 example exists):
  ```
  vllm serve Qwen/Qwen3.8-27B \
    --revision 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0 \
    --tokenizer-revision 1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0 \
    --tensor-parallel-size 1 \
    --max-model-len 4096 \
    --max-num-seqs 8 \
    --gpu-memory-utilization 0.85 \
    --reasoning-parser qwen3 \
    --enable-auto-tool-choice --tool-call-parser <TOOL_CALL_PARSER> \
    --served-model-name Qwen/Qwen3.8-27B \
    --port 8000
  ```
  `--max-model-len 4096` deliberately bounds the smoke far below the
  262144 native default — per phase instruction, the future runtime
  smoke should minimize unnecessary compute while remaining
  representative of a real production-serving path; a full-context
  server is not needed to prove server-readiness/generation/cleanup.
  No `--kv-cache-dtype fp8` (no evidence this precision choice is
  required for a bounded BF16 TP1 smoke; add only if CPU-only preflight
  or the live GPU preflight demonstrates a concrete need). No
  speculative decoding, no long-context YaRN override.

  **`<TOOL_CALL_PARSER>` is deliberately NOT frozen (Phase 21B.4.15.1
  correction).** Current primary sources disagree: vLLM's own recipe
  uses `qwen3_xml` for its NVFP4-quantized-variant examples but
  `qwen3_coder` for its Ascend examples; the official SGLang Cookbook
  for this exact model uses `qwen3_coder` universally, with an explicit
  technical rationale tied to this checkpoint's own chat template (see
  `QWEN3_8_27B_CURRENT_SERVING_PRIMARY_SOURCES_2026-09-23.json`'s
  `tool_calling.primary_source_configuration_divergence`). A Phase
  21B.4.15.1 CPU-only preflight attempted to resolve this by inspecting
  vLLM's own tool-parser registry and was inconclusive (the expected
  `vllm.entrypoints.openai.tool_parsers` module path does not exist in
  the resolved vLLM v0.30.0+cu129 build). **The future qualification run
  must use whichever parser configuration (a) passes a corrected
  CPU-only registry preflight against the exact resolved image at
  execution time, or (b) failing that, is confirmed to actually parse
  tool calls correctly during the live GPU run itself** — never a value
  frozen prematurely by this document. Given the evidence currently
  available (SGLang's explicit, checkpoint-specific rationale, and that
  `qwen3_coder` is also what vLLM's own Ascend examples use), `qwen3_coder`
  is the better-evidenced starting hypothesis, but this is a hypothesis
  to verify at execution time, not a frozen decision.

## C. Server readiness (required)

- Process alive (confirmed via the harness's own process-exit check, not log-text pattern-matching — per the corrected-harness lesson from GLM's Phase 21B.4.13.2 quarantine: never terminate on a benign WARNING-level traceback substring)
- Readiness indicator: `GET /v1/models` returns HTTP 200 (positive signal, not a log-text scan)
- OpenAI-compatible chat endpoint: `POST /v1/chat/completions` returns HTTP 200

## D. Generation (required, trivial smoke only)

- ONE trivial non-benchmark smoke prompt. No coding benchmark. No
  reasoning benchmark. No capability benchmark. No untrusted generated
  code execution.
- Suggested prompt (mirroring the pattern used for Mistral Small 4 and
  GLM-5.3-Flash): a simple instruction-following request whose only
  purpose is proving server-ready + HTTP-accepted + non-empty decoded
  output (e.g. "Reply with exactly the single word READY.")
- Because thinking is ON by default for this model (§Reasoning below),
  the decoded response may legitimately include reasoning content ahead
  of/around the literal answer — record the FULL response honestly
  rather than requiring an exact one-word match, exactly as GLM's
  qualification handled its own always-on-thinking behavior.

## E. Response integrity (required)

- HTTP status (both endpoints)
- Non-empty decoded response
- Expected parser structure: with `--reasoning-parser qwen3`, the
  response must expose `reasoning_content` (or equivalent
  `delta.reasoning` in streaming) SEPARATELY from `content` — capture
  both fields distinctly, never conflate hidden reasoning with the
  user-visible final answer
- Token counts (input/output), via `stream_options: {"include_usage": true}`
- Generation latency, TTFT (time to first token of the visible answer,
  not the first reasoning token — mirror GLM's TTFT-of-first-content-token convention)
- Throughput (tokens/sec)
- No NaN/Inf/OOM observed (worker-level memory evidence from vLLM's own
  log, not parent-process `torch.cuda` — per the established Mistral/GLM
  evidence pattern)

## F. Tool-protocol smoke (conditional — protocol compatibility only)

- Only if it can be tested as PROTOCOL compatibility (does the server
  accept a `tools`-bearing request and return a well-formed
  OpenAI-compatible tool-call structure) without becoming a capability
  benchmark.
- No external side effect. No real tool action taken. A single
  synthetic tool schema (e.g. a trivial `get_weather`-style stub) used
  only to prove the server parses and returns tool-call-shaped output
  when `--enable-auto-tool-choice --tool-call-parser <TOOL_CALL_PARSER>`
  (the parser resolved per §B above, not frozen as `qwen3_xml`) is
  active — not to evaluate whether the model chooses correctly.

## G. Multimodal smoke (excluded unless separately authorized)

- NOT included in this qualification run's required evidence. Per
  phase instruction and the engine-decision evidence (the vLLM recipe
  itself states multimodal is unverified even by its own authors for
  this model), multimodal remains non-decisional for Genesis frontier
  selection and out of scope here.

## H. Financial (non-negotiable)

- `owner_billed_delta_usd == 0` for a zero-cash qualification —
  enforced structurally by the existing `validate_manifest()` invariant
  in `orca/eval/runtime_qualification_manifest.py` (unchanged, unweakened
  this phase; regression-tested — see tests).
- The execution must follow `GENESIS_ZERO_CASH_GPU_EXECUTION_CONTROL_SPEC_2026-09-23.md`
  in full, including the live monetary-runway guard this phase's
  incident review identified as missing from the GLM harness.

## I. Cleanup (required)

- GPU tasks stopped (process SIGTERM/SIGKILL confirmed, exit code
  recorded)
- Resources released (`nvidia-smi` / provider-equivalent confirms
  return to idle baseline)
- Temporary volumes/resources handled correctly (none should exist
  under the "no persistent storage" hard restriction already
  established across prior phases)
- No runaway serving process (explicit post-cleanup process/container
  listing showing zero phase-created active resources)

## Topology

- **Minimum qualification topology: 1x NVIDIA H200, TP=1.** The full
  BF16 weight set already fits comfortably on a single H200 (141 GiB
  raw VRAM; historical Phase 21B.4.11 evidence measured ~55 GB weight
  usage), and nothing in the current primary sources establishes TP4 (or
  any multi-GPU topology) as required merely to serve the base model —
  TP4 in the official recipe is used specifically to maximize KV-cache
  pool size on a GB300 tray at full 262K context, a throughput/capacity
  optimization, not a correctness requirement. A bounded TP1 smoke is
  the smallest topology likely able to prove a genuine production-serving
  path safely.
- **Long-context / high-throughput topology (not this qualification
  run):** if a future phase specifically needs to prove extended-context
  (up to the documented 1,000,000-token YaRN-extended maximum) or
  higher-throughput serving, a larger topology (TP2/TP4, matching the
  official recipe's own long-context/high-throughput examples) would be
  evaluated separately, with its own authorization and its own zero-cash
  guardrail check.
- **10,000-real-time-user serving topology: NOT ADDRESSED HERE.** Per
  phase instruction, this document does not attempt or claim to solve
  the 10K-user production feasibility gate — only the future
  measurements that gate would eventually require are noted as a
  placeholder for a later, separately-authorized phase: sustained
  concurrent-request throughput, tail latency under load, KV-cache
  pool exhaustion behavior, and horizontal-scaling topology (multiple
  replicas vs. larger TP) would all need real load-testing evidence
  this qualification run does not and cannot produce.

## J. Strict qualification semantics (fail-closed, per phase instruction)

`PRODUCTION_SERVING_RUNTIME_QUALIFIED` (and, correspondingly, this
candidate's future `production_serving_status: QUALIFIED` registry
field) must remain IMPOSSIBLE to obtain solely from any of:

- successful model import
- tokenizer load
- config parse
- Transformers generation (offline, no server) — this is exactly what
  the EXISTING `RUNTIME_LOAD_COMPATIBILITY_QUALIFIED` evidence already
  proved, and this phase's schema hardening (§6/§7 of the phase spec)
  makes structurally impossible to conflate with production serving
- local function call
- offline generation without a server
- an HTTP endpoint existing without a valid, non-empty generation
  actually passing through it
- a financial-gate violation (owner_billed_delta_usd != 0) — enforced
  by the existing, unweakened manifest validator
- incomplete cleanup evidence
- unverifiable (unhashed / unlinked) evidence

Formal production-serving qualification requires ALL of sections C
through I above, with byte-verified evidence artifacts, exactly
mirroring the STRICT_RUNTIME_SMOKE_V2 protocol already enforced for
Mistral Small 4's accepted manifest. Fail closed on any gap.
