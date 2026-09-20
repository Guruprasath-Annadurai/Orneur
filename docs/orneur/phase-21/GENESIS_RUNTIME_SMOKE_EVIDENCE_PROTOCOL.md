# Genesis Runtime Smoke Evidence Protocol

Established Phase 21B.4.11.2. Applies to every deployable-candidate
runtime smoke executed **after** Qwen3.8-27B (Phase 21B.4.11, the one
`LEGACY_RECONCILED_V1`-grandfathered exception -- see
`GENESIS_RUNTIME_QUALIFICATION_MANIFEST_QWEN3_8_27B.json`).

Every future candidate smoke must use
`evidence_protocol_generation: "STRICT_RUNTIME_SMOKE_V2"`
(`orca/eval/runtime_qualification_manifest.py`), which structurally
enforces this evidence lifecycle. **No candidate may be marked
`QUALIFIED` before every step below has completed.**

## Locked execution order

1. Billing hard-limit owner evidence obtained (fresh, independently
   checkable -- never inferred, never reused from a prior phase).
2. Billing-before snapshot persisted (metered/billed cost, GPU
   rate/inventory) via supported Modal tooling only.
3. Model identity artifact persisted (repository, exact pinned
   revision, architecture, license, tokenizer identity/revision, weight
   index/shard metadata) -- metadata-only, no weight download yet.
4. Runtime environment artifact persisted (exact Python/PyTorch/CUDA/
   Transformers/vLLM-or-SGLang/safetensors/tokenizers/accelerate
   versions).
5. GPU/model load executed.
6. Synthetic (non-benchmark) inference executed.
7. Sanitized execution log persisted **before teardown** -- stdout/
   stderr or a structured event log with secrets/tokens/credentials
   stripped, saved to a durable file (not left only in a transient tool
   transcript).
8. Runtime qualification manifest constructed from the persisted
   artifacts above (not from memory/recollection).
9. Manifest validated against the schema
   (`orca.eval.runtime_qualification_manifest.validate_manifest`) --
   under `STRICT_RUNTIME_SMOKE_V2` this requires a real
   `raw_execution_log_artifact` and a valid `raw_execution_log_sha256`,
   or validation fails closed.
10. Artifact hashes persisted (prompt hash, response hash, execution
    log hash, manifest canonical-JSON digest).
11. GPU teardown executed.
12. Cleanup evidence persisted (zero active apps/containers, zero
    persistent Volumes, confirmed via supported tooling).
13. Billing-after evidence persisted (metered/billed cost delta; owner
    billed must remain exactly $0.00).
14. Manifest finalized and re-sealed (digest recomputed over the final
    content).
15. Registry updated **only after** the manifest has independently
    validated and its digest matches what the registry will record --
    `orca.eval.candidate_registry.verify_qualified_manifest_linkage` is
    the generic (non-candidate-specific) enforcement of this.
16. Deterministic tests + CI run and green before the phase closes.

## Non-negotiable invariants (enforced in code, not just process)

- `owner_billed_delta_usd == 0`, `billed_before_usd == 0`,
  `billed_after_usd == 0` for every accepted manifest.
- `benchmark_prompt_exposed`, `genesis_eval_executed`,
  `generated_output_executed` must all be `false`.
- `persistent_volume_used` must be `false`.
- A `QUALIFIED` manifest requires at least one `SUCCEEDED` attempt,
  `cleanup_status == "CONFIRMED_ZERO_ACTIVE_RESOURCES"`, and
  `active_resources_after` indicating `NONE`.
- `evidence_strength` must cover exactly the locked
  `EVIDENCE_BEARING_FIELDS` set -- partial provenance coverage fails
  validation.
- Under `STRICT_RUNTIME_SMOKE_V2`: a durable `raw_execution_log_artifact`
  and 64-hex `raw_execution_log_sha256` are mandatory, and `created_at`/
  `execution_time` must be real timezone-aware timestamps, not
  `NOT_CAPTURED`.

## Qualification-type semantics (never conflated)

- `RUNTIME_LOAD_COMPATIBILITY_QUALIFIED` -- a native-runtime
  (e.g. Transformers) load + generation succeeded. Not a production
  serving claim.
- `PRODUCTION_SERVING_RUNTIME_QUALIFIED` -- a production serving
  runtime (e.g. vLLM, SGLang) was actually exercised as a server.
- `RUNTIME_QUALIFICATION_FAILED` / `DEFERRED_FOR_COMPUTE` -- the
  candidate is not eliminated; its Genesis candidate-pool standing is
  unaffected.

None of these ever imply `FRONTIER_CLASS`, `BENCHMARK_QUALIFIED`, or
`GENESIS_SELECTED` -- those remain separate, unrelated judgments this
protocol makes no claim about.
