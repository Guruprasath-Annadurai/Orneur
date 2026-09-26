# Genesis Control Runtime Qualification Matrix — Phase 21B.4.20

**Runtime-compatibility evidence only. No frontier inference, no benchmark,
no private holdout, no generated-output execution, no Modal Sandbox.
CAPABILITY REMAINS UNPROVEN for every control.**

## Current authoritative state (one consistent state; everything below the "Historical record" heading is preserved history)

Canonical provider: **Modal, 1 x H100 80GB, BF16, no quantization, no substitution**, exact pinned revisions from a hash-verified
Modal Volume cache (CPU-only pre-cache manifests `GENESIS_CONTROL_*_MODAL_PRECACHE_MANIFEST_2026-09-24.json`).

| Control | Identity | Latest attempt | Locked smokes A / B / C | Technical serving | Financial acceptance | Runtime qualification | Capability |
|---|---|---|---|---|---|---|---|
| Qwen3-8B | ADMITTED | **attempt 5**, Modal H100, `qwen3_8b_non_thinking_v1`, 163.2 s, valid runtime attempt, `TECHNICAL_FAILURE` (model-runtime domain); attempts 1-4 preserved | PASS / **FAIL** / PASS | FAILED (locked Smoke B contract not met: `2 + 3 = 5`) | PASS (owner billed delta 0; promotional credit used 0.18768559 USD, settlement OBSERVED in-run) | **FAILED** | UNPROVEN |
| Mistral-Nemo-Instruct-2407 | ADMITTED | **attempt 2**, Modal H100 x1, 140 s, app `ap-euwY3zXbgcZfGoZiRNstFt`, valid runtime attempt: server ready; exact identity + BF16 + locked flags (`--tokenizer-mode hf --config-format hf --load-format safetensors`) proven by a CONTAINER_RETURNED proof; `UNATTRIBUTED_REQUEST_REJECTION`, failure domain `UNATTRIBUTED` (pre-generation vLLM chat-template resolution failure, not a model-response failure). Attempt 1 (also `UNATTRIBUTED_REQUEST_REJECTION`, originally recorded `TECHNICAL_FAILURE`) is preserved | HTTP 400 / HTTP 400 / HTTP 400 (bodies captured); model output NONE | **NOT_PROVEN** | PASS (owner billed delta 0; attempt-2 itemized run cost 0.15881105 USD; settlement OBSERVED by the 2026-09-26 read-only reconciliation) | **NOT_COMPLETED** | UNPROVEN |
| Phi-4 | ADMITTED | none | not run | NOT_TESTED | NOT_TESTED | NOT_TESTED | UNPROVEN |

**No control is RUNTIME_QUALIFIED.** Latest attempts: **Qwen3-8B = attempt 5** (`FAILED`, locked Smoke B contract not met); **Mistral-Nemo = attempt 2** (`UNATTRIBUTED_REQUEST_REJECTION`, technical NOT_PROVEN, runtime NOT_COMPLETED; the model is NOT called FAILED because no model output was ever produced); **Phi-4 = NOT_TESTED** (no attempts). **No further GPU run is currently authorized**: Qwen3-8B needs a separate owner authorization for any attempt 6, and Mistral-Nemo needs a separate owner authorization for any attempt 3. Mistral attempt 2's financial settlement is now OBSERVED (attempt-specific object-id cost 0.15881105 USD, owner billed delta 0), so it no longer blocks launch gating; the attempt-2 failure itself remains unresolved by any configuration change (the canonical configuration is still `--tokenizer-mode hf`; native `--tokenizer-mode mistral` is CPU-ready for prompt preprocessing only and is NOT authorized). Attempt-1 discussion below is preserved as history.
Runtime qualification is not capability qualification.

**Qwen3-8B attempt 5 (authorized, executed once).** Modal H100, approved configuration `qwen3_8b_non_thinking_v1`
(`chat_template_kwargs: {"enable_thinking": false}` sent with every locked smoke; proven from inside the container: configuration id, kwargs sent,
runtime-policy sha256 `50c0b455…c62e` equal to the record and the local pin, configuration sha `c88e0e14…bab1`, canonical protocol
`d462103b…25c1`, per-prompt hashes, exact model/revision, bfloat16, no quantization, parser `qwen3`). Results, canonical prompts, whitespace stripped:
A `READY` **PASS**; B `2 + 3 = 5` **FAIL** (not exactly `5`); C `{"status": "ready"}` **PASS** (parses to the exact object). Thinking was
disabled as designed (0 reasoning tokens each) and the response is still not the bare `5`, so the runtime configuration removed the
verbosity of attempt 4 for A and C but not for B. Infrastructure and identity facts hold: exact pinned identity PASS, BF16 PASS, serving PASS,
cleanup PASS (app stopped, 0 tasks, 0 containers, 0 live resources), owner billed delta 0, settlement OBSERVED in-run (0.18768559 USD promotional
credit, equal to the app's own itemized row and the exact per-category metered growth), generated output never executed. Outcome:
attempt 5 `TECHNICAL_FAILURE` (valid runtime attempt), technical `FAILED`, runtime `FAILED`. It is a smoke-contract (response-behaviour) failure,
not an identity, infrastructure or financial failure. The evidence record is written by the harness with its validator passing.
**Metadata correction (descriptive only).** The originally generated attempt-5 record carried a stale `reasoning_mode` ("ENABLED (Qwen3 hybrid-thinking template
default; ...)") copied from the model's default template capability. It is now derived from the effective approved configuration:
`NON_THINKING (enable_thinking=false ...); --reasoning-parser qwen3 is loaded but thinking is not enabled` (loading the parser does not mean thinking is on;
the persisted smokes show 0 reasoning tokens). The pre-correction record is preserved byte-identically as
`GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_ATTEMPT5_SNAPSHOT_2026-09-24.json` (sha256 `85d3fec9…13c5`); the correction changes only `reasoning_mode` and adds a
`metadata_correction` note, does **not** reclassify attempt 5, and leaves raw responses, raw log, financial/settlement evidence, container proof, smoke outputs and all
attempt outcomes untouched. Qwen3-8B remains FAILED.

**Mistral-Nemo-Instruct-2407 attempt 1 (authorized, executed once).** Modal H100, no per-control request configuration, locked flags `--tokenizer-mode hf --config-format hf
--load-format safetensors`, no reasoning parser, no `chat_template_kwargs`, canonical protocol `d462103b…25c1`. The server reached ready after 153 s with the exact pinned identity
(revision, weight bytes 24,495,607,104, served model id), bfloat16, no quantization. All three `POST /v1/chat/completions` (A streamed, B, C) returned **HTTP 400 Bad Request**
(proven by the immutable raw server log). The persisted smoke fields are unchanged: `http_status = null`, `raw_response = ""`, because `urllib` raised `HTTPError` before the status/body were
recorded, so the API error bodies were **not captured** (and are not reconstructed). The pinned tokenizer_config does define a chat template and rendering it locally for the three canonical prompts
succeeds, so a template-render error is not indicated; the cause is **unattributed**.
*Classification (conservative, after audit).* The harness first recorded `TECHNICAL_FAILURE` / `MODEL_RUNTIME` / technical `FAILED`. Without diagnostic evidence that cannot be attributed to the model
(vs a request-format/harness issue), so the attempt is now `UNATTRIBUTED_REQUEST_REJECTION` (new failure domain `UNATTRIBUTED`; the original classification is preserved in `original_classification`),
the model's technical status **NOT_PROVEN** and runtime **NOT_COMPLETED**. It is not a pass and not evidence that the model is incompatible; chat-completions qualification was not established. The
pre-correction record is preserved byte-for-byte as `GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_ATTEMPT1_SNAPSHOT_2026-09-24.json` (sha256 `5bcf5aa8…d5df`); the correction touches only
attempts (classification + settlement sync), technical/runtime status, `container_execution_proof`, `http_error_evidence_gap` and the `classification_correction` note.
*Container proof.* The harness now persists `container_execution_proof` for every control. Mistral's original container proof was verified at run time but not saved, so the persisted one is
`RECONSTRUCTED_FROM_PERSISTED_EVIDENCE` (model/served id, revision, bfloat16, no quantization, canonical protocol + per-prompt hashes, `chat_template_kwargs` null for A/B/C, no configuration id,
`--tokenizer-mode hf --config-format hf --load-format safetensors`, no reasoning parser; `runtime_policy_sha256` null because it is not reconstructable). New runs persist the container-returned proof.
*Runner.* The shared runner now captures HTTP error responses (status, safe headers, body as data, sha256, structured error, error class, smoke id) for streamed and non-streamed calls; an HTTP-level
rejection is classified `UNATTRIBUTED_REQUEST_REJECTION`, never `MODEL_RUNTIME`.
Owner cash 0; cleanup PASS (app stopped, 0 tasks, 0 containers). **Settlement: BILLING_SETTLEMENT_NOT_YET_OBSERVABLE** in every authoritative field (top-level, attempt entry, attempts file; the in-run OBSERVED
is preserved only as history: it matched itemized rows by the shared app description and included Qwen attempt 5's app; the harness now matches by object id and the validator enforces consistency).
Exact attribution: the run's own row is 0.20532158 USD; the account's metered totals moved non-monotonically so the excess cannot yet be attributed to this run. No waiver applies; only the read-only
`--mode reconcile` may be repeated later. No rerun.

**Mistral-Nemo HTTP 400: CPU-only root-cause analysis (decision B, not established).** `GENESIS_MISTRAL_NEMO_HTTP400_CPU_ROOT_CAUSE_ANALYSIS_2026-09-25.json`. The exact ORNEUR payloads for A (with its streaming
fields), B and C were run on CPU through the pinned HF tokenizer + chat template + tokenization with the run's own library versions (transformers 5.16.1, tokenizers 0.23.2): all three pass
(8 / 7 / 12 prompt tokens, `<s>[INST]…[/INST]`, one BOS, prompt + 64 <= 4096). Every payload field was traced against the vLLM v0.29.0 sources (immutable commit) and none is rejected on this path;
Qwen received HTTP 200 for the same fields. The immutable raw log has no traceback and no "error occurred in transformers while applying chat template" line (which vLLM logs and wraps as a 400 ValueError),
so a template-application error is unlikely, but pydantic request-validation rejections are logged only with `--log-error-stack` and other `create_error_response` paths are not logged, so they cannot be ruled out.
The exact 400 was **not reproduced** (vLLM cannot be run CPU-only and the model must not be loaded) and the API error bodies were never captured: **B. ROOT CAUSE NOT ESTABLISHED CPU-ONLY.** No fix is proposed; it
remains UNATTRIBUTED (harness/request configuration vs vLLM runtime vs tokenizer/template vs model runtime). A further attempt would need its own authorization (the runner now captures the error body).
*Settlement (fourth and final read-only reconciliation, 2026-09-25T12:06Z): OBSERVED* (details at the end of this paragraph). The third reconciliation (11:43Z) had returned `BILLING_SETTLEMENT_NOT_YET_OBSERVABLE`. The exact metered growth (0.20532159 USD) now equals the run's own itemized row (0.20532158, 1e-8 rounding) and owner billed
delta is 0 with 0 live resources, but the check failed only because the stopped app had aged out of Modal's listing; the harness was fixed to accept an unlisted app as not live only when run-time evidence recorded it stopped
and no live resources exist. The gate stayed closed then; no waiver applied.
*Fourth reconciliation (`…20260925T120607Z.json`):* with the aged-out-app rule (absent from the listing, run-time evidence proves the exact app stopped with 0 tasks, 0 live resources, 0 containers, object-id
attribution `ap-LEwLRsdDZiLhSvTgwIPn7g`) the verdict is **SETTLEMENT_OBSERVED**: itemized cost 0.20532158 USD, precise metered delta 0.20532159 (1e-8 rounding), owner billed delta 0. Finalization is
transactional: the record's top-level settlement, the embedded attempt and the attempts file all say OBSERVED (validated before either is written), the original contaminated in-run OBSERVED, the
`settlement_correction` and the earlier NOT_YET_OBSERVABLE reconciliation evidence are preserved, and the new artifact is referenced. **Only the financial settlement resolved: Mistral remains
`UNATTRIBUTED_REQUEST_REJECTION`, technical NOT_PROVEN, runtime NOT_COMPLETED, capability UNPROVEN.** No rerun, no waiver.

**Mistral-Nemo attempt 2 (EXECUTED 2026-09-25, Modal app `ap-euwY3zXbgcZfGoZiRNstFt`, H100 x1, 140 s): UNATTRIBUTED_REQUEST_REJECTION / failure_domain UNATTRIBUTED.** A fresh in-run preflight was ALLOWED (remaining promotional credit 9.0464, reserve 5.00, worst case 1.0828). Container-returned proof (provenance CONTAINER_RETURNED) confirmed the locked identity, revision, BF16, no quantization, tokenizer_mode/config_format/load_format hf/hf/safetensors, no reasoning parser, null runtime configuration and null chat_template_kwargs, protocol sha d462103b…25c1. Server became ready; smokes A, B, C each returned **HTTP 400** with identical captured body (216 bytes, sha256 `d0899ffb…c2309`): `As of transformers v4.44, default chat template is no longer allowed, so you must provide a chat template if the tokenizer does not define one.` (type BadRequestError). The message identifies the rejection reason, but the pinned revision's `tokenizer_config.json` (181,297 bytes, cached, size identical to upstream) DOES contain a `chat_template`, so why vLLM 0.29.0 / transformers 5.16.1 under `--tokenizer-mode hf` saw none is NOT established; the root cause therefore remains unattributed (no model output was produced, so nothing is attributable to the model). Technical serving NOT_PROVEN, runtime qualification NOT_COMPLETED, capability UNPROVEN. Owner billed delta 0; cleanup PASS (app stopped, 0 live resources); settlement BILLING_SETTLEMENT_NOT_YET_OBSERVABLE (metered unchanged at the 17:18Z reading). No retry; Phi-4 NOT_TESTED. Attempt-1 evidence preserved unchanged: the pre-correction snapshot (`…ATTEMPT1_SNAPSHOT…`, sha 5bcf5aa8…), the attempt-1 raw log, and a byte-identical archive of the finalized attempt-1 record taken before attempt 2 overwrote the live record (`GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_ATTEMPT1_FINALIZED_SNAPSHOT_2026-09-25.json`, sha bbde9921…9464; identical to the audited commit-22dfc78 record). The live record now describes attempt 2.

**Mistral attempt 2 follow-up (2026-09-26, CPU-only, no GPU) — item (1) below describes the FIRST reconciliation only; a later reconciliation OBSERVED settlement (see "Latest attempt-2 settlement observation"):** (1) One read-only settlement reconciliation (object-id attribution) found the attempt-2 app's own itemized cost 0.15881105 USD (owner billed delta 0, 0 live resources) but metered growth 0.31762209 exceeds it, so settlement stays **BILLING_SETTLEMENT_NOT_YET_OBSERVABLE** (`GENESIS_CONTROL_MISTRAL_NEMO_ATTEMPT2_SETTLEMENT_RECONCILIATION_20260925T191352Z.json`); no second reconciliation was run. (2) Chat-template root-cause V2 (`GENESIS_MISTRAL_NEMO_CHAT_TEMPLATE_ROOT_CAUSE_ANALYSIS_V2_2026-09-26.json`): the pinned `tokenizer_config.json` DOES contain a chat_template (3,945 bytes); under the container's exact transformers 5.16.1 / tokenizers 0.23.2 / huggingface_hub 1.30.0, AutoTokenizer on the pinned snapshot returns `MistralCommonBackend` (tekken.json is the discriminating file), which has no chat_template and no get_chat_template; the real vLLM 0.29.0 `resolve_chat_template` then returns None and `safe_apply_chat_template` raises the exact attempt-2 error (vLLM `ChatTemplateResolutionError` -> HTTP 400) before any generation. The log line 'Detected the chat template content format to be string' is emitted even when no template resolved (`"string" if jinja_text is None`), so it proves nothing. The container's own tokenizer class is NOT directly observed (not logged). This is a pre-generation template-resolution failure, not a model-response failure; classification is unchanged (UNATTRIBUTED_REQUEST_REJECTION / NOT_PROVEN / NOT_COMPLETED / capability UNPROVEN). No serving-configuration change is recommended or authorized. (3) The record's descriptive `chat_template_source` was corrected (pre-correction snapshot `…ATTEMPT2_SNAPSHOT_2026-09-24.json`, sha 7eabbd15…) so it no longer implies runtime resolution.

**Native tokenizer-mode readiness (2026-09-26, CPU-only, no GPU, no provider call):** `GENESIS_MISTRAL_NEMO_NATIVE_TOKENIZER_MODE_READINESS_2026-09-26.json` records vLLM v0.29.0 source evidence that `--tokenizer-mode mistral` selects `MistralTokenizer` + `MistralRenderer` (the explicit attempt-2 `hf` selected `CachedHfTokenizer` + `HfRenderer`), that the real `MistralTokenizer.from_pretrained` constructs on the pinned snapshot (Tekkenizer, mistral_common 1.12.0 locally; the container's version is unrecorded), and that the locked smokes A/B/C render to token ids through the real `safe_apply_chat_template` with no `ChatTemplateResolutionError` and no `get_chat_template`. Verdict `NATIVE_MISTRAL_MODE_CPU_READY` refers to the CPU-side preprocessing path only; it is NOT a GPU authorization, engine/weight loading under that mode is not covered, and the canonical configuration (`--tokenizer-mode hf`) is unchanged. The explicit `--chat-template` route through the HF renderer is not viable on `MistralCommonBackend` (real `resolve_chat_template` raises) and is not recommended. Any Mistral attempt 3 needs a separate explicit owner authorization and resolved attempt-2 settlement.

**Candidate runtime configuration `mistral_nemo_native_v1` (2026-09-26, CPU-only formalization; NOT promoted, NOT selected by default):** a separately versioned, separately fingerprinted candidate in `orca/eval/control_runtime_configuration.py` (sha256 `88a9cfec…459a`, pinned and verified on import): Mistral-Nemo-Instruct-2407 at revision 04d8a905…, `--tokenizer-mode mistral --config-format hf --load-format safetensors`, bfloat16, no quantization, no reasoning parser, no chat-template flag/override, null `chat_template_kwargs`, generation temperature 0 / top_p 1 / seed 0 / max_tokens 64, locked protocol `d462103b…25c1` unchanged. The runner selects it only via an explicit `serving_config(..., candidate=…)` (any other model or unknown id is refused; nothing falls back to hf), the container proof carries the candidate id/fingerprint and a `chat_template_flag` proof, and the validator accepts a record declaring `runtime_candidate_configuration_id` only if the container-returned proof matches the candidate exactly (any hf/config/load-format/id/fingerprint/kwargs/parser/flag drift fails closed). Evidence: `GENESIS_MISTRAL_NEMO_NATIVE_V1_IMPLEMENTATION_READINESS_2026-09-26.json` (the audited native-readiness artifact is hash-verified against an independent pin and its source/snapshot provenance re-verified fail-closed; the candidate mode maps through the real vLLM v0.29.0 `resolve_tokenizer_args` to `MistralTokenizer` + `MistralRenderer`; CPU A/B/C preprocessing consumed from the verified readiness artifact). **The canonical Mistral configuration is still `--tokenizer-mode hf`; this is not a GPU authorization and not a runtime qualification; promotion or any attempt 3 requires a separate owner authorization after audit.**

**Attempt-3 launch-path wiring for the candidate (2026-09-26, CPU-only; nothing launched):** `--mode run --control mistral_nemo` still runs the canonical hf configuration by default. A candidate attempt requires the explicit argument `--candidate mistral_nemo_native_v1` (accepted only with `--mode run`); the single GPU call site is `serve_and_smoke.remote(*remote_call_args(control, candidate))`, i.e. `serve_and_smoke.remote("mistral_nemo", "mistral_nemo_native_v1")` for a candidate launch and `(control,)` otherwise. Before ANY billing read or GPU call the candidate launch is refused unless: the candidate is known and used with its own control only, its fingerprint/invariants/protocol/model/revision match, the latest persisted Mistral attempt is exactly 2 with settlement OBSERVED and owner billed delta 0 (so it can only be attempt 3), the live record is byte-identical to the finalized attempt-2 archive `GENESIS_CONTROL_MISTRAL_NEMO_RUNTIME_QUALIFICATION_ATTEMPT2_FINALIZED_SNAPSHOT_2026-09-26.json` (sha256 `c43aeecd…a914`, distinct from the earlier pre-correction snapshot `…ATTEMPT2_SNAPSHOT…` sha 7eabbd15…; both are kept), and the native-v1 readiness artifact and that archive match their indexed hashes. A candidate record persists `runtime_candidate_configuration_id` (with `runtime_configuration` left null); any proof mismatch (hf substitution, id/fingerprint, chat-template flag, non-null kwargs, reasoning parser) is a HARNESS_FAILURE and is never reinterpreted as canonical. The financial gate is unchanged and still applies to attempt 3 (owner billed 0, prior settlements resolved, zero live resources, promotional credit >= 5.00 reserve + worst case, 900 s cap, <= 1.25 ceiling). Verified only with stubs on a temporary evidence copy; no Modal call, GPU, preflight or reconciliation occurred. **The canonical Mistral configuration is still `--tokenizer-mode hf`; attempt 3 is NOT authorized.**

**Latest attempt-2 settlement observation (2026-09-26T06:10:09Z, ONE read-only reconciliation):** `GENESIS_CONTROL_MISTRAL_NEMO_ATTEMPT2_SETTLEMENT_RECONCILIATION_20260926T061009Z.json` (object-id attribution of `ap-euwY3zXbgcZfGoZiRNstFt`; app absent from the listing with run-time stopped evidence, 0 tasks, 0 containers, 0 live resources): attempt-specific itemized cost **0.15881105 USD**, precise metered delta 0.15881104 (unattributed -1e-8, rounding), cent-rounded total delta 0.16, credits absorbed the growth, owner billed delta **0**, `free_storage` unchanged. Verdict **SETTLEMENT_OBSERVED**; the audited transactional finalizer synchronized the record's `billing_settlement`, the embedded attempt and the attempts file; the original in-run `metered_delta == 0` reading is preserved (`original_in_run_billing_settlement`) and the earlier NOT_YET_OBSERVABLE reconciliation `…20260925T191352Z.json` remains as history. Only settlement fields changed: attempt outcome, failure domain, technical/runtime/capability status and the HTTP evidence are untouched. The first reconciliation's statement that settlement 'stays NOT_YET_OBSERVABLE' is superseded.

### Historical (superseded) attempt-2 pre-execution states — kept for the record, NOT current

*The paragraphs below describe states that were true earlier and are contradicted by the executed attempt 2 above (attempt 2 has been executed; the authorization is used; whether storage charges were covered was later shown by the live `free_storage` adjustment).*

**HISTORICAL / SUPERSEDED —** **Mistral-Nemo attempt 2 (owner-authorized): NOT STARTED, the fresh live preflight was BLOCKED.** The existing gate refused: credits applied 20.70 do not cover metered 20.89627853 (owner billed still 0). A new metered
category `volumes` = 0.19627853 USD (the Modal Volume holding the three pre-cached model revisions) appeared; ephemeral-app metering is unchanged, so it is not GPU usage. No GPU, no Modal function, no volume change, no retry of the
gate. Whether the storage charge will be absorbed by credits/free storage or become owner-billed is not established. Evidence: `GENESIS_CONTROL_MISTRAL_NEMO_MODAL_H100_GPU_PREFLIGHT_2026-09-25T122704Z.json`,
`GENESIS_MODAL_VOLUME_METERING_DIAGNOSIS_2026-09-25.json`. The authorization for attempt 2 remains unused; Mistral stays NOT_PROVEN / NOT_COMPLETED.

**HISTORICAL / SUPERSEDED —** **Financial-gate correction (2026-09-25):** the 12:27 block was a false block (old assumption: all metered cost must be covered by `credits`; the provider's `free_storage` adjustment already offset the 0.19627853 volume metering). The gate now reconciles metered + all adjustments == billed == 0 for owner-payable coverage and keeps GPU runway promotional-credit-only. A corrected read-only preflight (`GENESIS_CONTROL_MISTRAL_NEMO_MODAL_H100_GPU_PREFLIGHT_2026-09-25T130507Z.json`) returned ALLOWED (remaining promotional credit 9.0464, reserve 5.00, worst case 1.0828, headroom 2.9636). **The GPU was NOT started; attempt 2 remains UNSTARTED pending independent audit.** See `GENESIS_MODAL_FINANCIAL_GATE_CORRECTION_2026-09-25.json`.

**HISTORICAL / SUPERSEDED —** **Credit-sign hardening (2026-09-25):** `provider_billing_reconciliation` now raises on a positive `adjustments.credits` (it can never increase promotional GPU runway) and on a negative derived `credits_applied`; no clamping. A fresh read-only preflight (`GENESIS_CONTROL_MISTRAL_NEMO_MODAL_H100_GPU_PREFLIGHT_2026-09-25T164921Z.json`) again returned ALLOWED (live credits adjustment negative). **The GPU was NOT started; attempt 2 remains UNSTARTED.**

*(End of the superseded attempt-2 pre-execution paragraphs; the remaining paragraphs of this section are Qwen history and standing conditions.)*

**Qwen3-8B attempt 4 (historical).** Preserved byte-identically as `GENESIS_CONTROL_QWEN3_8B_RUNTIME_QUALIFICATION_ATTEMPT4_SNAPSHOT_2026-09-24.json`.
Thinking default ON and the runner's earlier prompt wording; A PASS, B FAIL (verbose explanation), C PASS; owner billed delta 0; promotional credit
0.22772907 USD (settlement observed by the read-only `--mode reconcile`); reclassified `TECHNICAL_FAILURE`, technical `FAILED`, runtime `FAILED` after the
audit applied the locked smoke semantics (`original_classification`, `superseded_classification`, `original_in_run_billing_settlement` keep the history).

**Owner waiver.** Historical Modal attempt 1's unresolved settlement was lifted for launch gating only by the owner-created waiver
(strict `validate_owner_settlement_waiver`); it never marks that settlement resolved, its conservative exposure stays deducted, and
it applies to attempt 1 only, never to attempt 4.

**`qwen3_8b_non_thinking_v1` (implemented CPU-only, then executed once as attempt 5).** Source of truth `orca/eval/control_runtime_configuration.py`,
wired through the shared runner's single request builder, proven from inside the container and enforced by the validator for Qwen records whose
final attempt number is >= 5. The complete approved policy is pinned by a fail-closed fingerprint verified on import
(`PINNED_RUNTIME_POLICY_SHA256 = 50c0b455e710aa53d0ec4d5515c9f9835b51ebac14391242813ceef961b6c62e`); container proof, record and local pin must be
equal. Mistral-Nemo / Phi-4 receive no such setting. See `GENESIS_QWEN3_8B_NON_THINKING_V1_IMPLEMENTATION_READINESS_2026-09-25.json` (pre-run readiness).

**Resume conditions.** Any further Qwen3-8B attempt (attempt 6) would need a separate explicit owner authorization; any change to the qualified
runtime configuration, sampling or locked prompts is a configuration change and needs its own authorization. Every launch
still requires: owner billed delta 0, credit runway >= $5.00 reserve + worst-case run cost (H100 900 s cap ~= $1.083, under the
$1.25 maximum), zero live Modal resources, a verified model cache, and every earlier settlement observed or explicitly waived.

## Historical record (superseded state preserved; text below may describe earlier states)

### Historical: Qwen3-8B attempt 1 (Modal A100) and the gate that followed

**Attempt result is not model result.** Qwen3-8B attempt 1 was cancelled by a harness bug (Modal 1.5.5 raises the
*builtin* `TimeoutError` from `FunctionCall.get(timeout=)`; the harness did not catch it). The pinned model was never
served, so this attempt does **not** show runtime incompatibility. A model-runtime `FAILED` requires an actual valid
runtime attempt; a harness failure or financial-guard abort always leaves technical serving `NOT_PROVEN` and the
qualification `NOT_COMPLETED` (machine-enforced; see `FAILURE_DOMAIN_BY_OUTCOME`). The attempt itself is preserved
unchanged in the history: 34.6 s, billed delta 0 at observed time, cleanup PASS, 0 live tasks, 0 containers,
settlement `BILLING_SETTLEMENT_NOT_YET_OBSERVABLE`. Its true settled cost is unconfirmed and is not assumed to be zero.

*Historical (as of 2026-09-24T12:19Z, superseded):* the harness then refused any GPU start while attempt 1's settlement was
unresolved (`QWEN_ATTEMPT_1_SETTLEMENT_STILL_UNRESOLVED`; see `GENESIS_CONTROL_QWEN3_8B_ATTEMPT1_SETTLEMENT_RECONCILIATION_*.json`).
That gate was later lifted for launch purposes by the owner waiver described above; attempt 1's settlement itself is still unresolved.

### Historical: provider migration (Modal -> Lightning AI)

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

### Historical: Hugging Face ZeroGPU fallback (read-only eligibility check)

Modal and Lightning execution is stopped for this phase (audit decision). The next candidate, Hugging Face ZeroGPU, is a
**model runtime compatibility** test (exact BF16 checkpoint, Gradio/PyTorch), never a production-serving proof; production
serving qualification stays **UNCHANGED**. Official rules: free personal accounts in good standing (verified email, older
than 30 days) may host up to 2 ZeroGPU Spaces; the free daily GPU quota is 5 minutes; hardware `large` is 48 GB.

**Eligibility: NOT ESTABLISHED.** No authenticated Hugging Face session is available (no local token; Chrome shows the login
form), so eligibility can be neither confirmed nor refused; this is not `HF_ZEROGPU_NOT_ELIGIBLE`. No Space, repository or GPU
was created and no account action was taken. Estimated BF16 memory fits the 48 GB tier for all three controls (about 14.7 to
27.5 GB headroom, assuming a 4 GB overhead reserve; an estimate, not a measurement). Evidence:
`GENESIS_HF_ZEROGPU_ELIGIBILITY_AND_HEADROOM_2026-09-24.json`. Statuses below are unchanged.

#### Historical update: authenticated Hugging Face account verified -- HF_ZEROGPU_NOT_ELIGIBLE

The owner logged in to Hugging Face (personal account `Orneur`, email verified, not PRO, no payment method, credits $0.00,
ZeroGPU quota shown as 0/5 minutes). The account was created 2026-09-24T15:34:25Z, so it fails the documented
"older than 30 days" hosting rule: **HF_ZEROGPU_NOT_ELIGIBLE** for now (earliest 2026-10-24, not guaranteed). The
account-specific hardware selector cannot be seen without creating a Space, so `large`/48 GB remains documentation-only.
No Space, GPU quota, purchase or setting change was made. Evidence: `GENESIS_HF_ZEROGPU_ACCOUNT_VERIFICATION_2026-09-24.json`.
The email address is not persisted. Control statuses, production serving qualification and program state are unchanged.

### Historical: razorBridge (provider fallback 3)

Public facts verified (pricing page and docs) and account-side state read in the owner's logged-in web app: EUR 10 signup grant
as the only ledger entry, no payment-method or top-up control anywhere, owner payable 0, H100 80 GB selectable at EUR 4.29/hr,
durations 1/2/4/8 h. The zero-cash gate passed. Two structural constraints were recorded: blade disks are discarded at teardown
(every install and model download runs on the billed blade) and blades can be started and stopped only in the web app.

**Start refused by the provider:** two attempts about 5 minutes apart both returned "Self-serve GPU sessions are temporarily
paused for maintenance." No blade was created, the balance is still EUR 10 and nothing was charged. Qwen3-8B attempt 3 is
recorded as `BLOCKED_NO_GPU`. The razorBridge gate, validator and SSH operator script are implemented and unit-tested but have
never been run against a real blade. Evidence: `GENESIS_RAZORBRIDGE_ACCOUNT_GATE_QWEN3_8B_2026-09-24.json`,
`GENESIS_RAZORBRIDGE_PROVIDER_START_REFUSED_2026-09-24.json`. Control statuses are unchanged.

### Billing reconciliation (historical entries plus current baseline)

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
- **Current (Modal H100, 2026-09-24):** attempt 4 settlement OBSERVED by `GENESIS_CONTROL_QWEN3_8B_ATTEMPT4_SETTLEMENT_RECONCILIATION_20260924T211518Z.json`:
  metered growth 0.22772907 USD (exact breakdown) equals the app's itemized row, credits applied cover it, owner billed unchanged at 0. An earlier
  same-day artifact (`...T211440Z.json`) compared against the cent-rounded account total and returned NOT_OBSERVABLE; it is kept as evidence.
- Gates per run: owner-payable gate (billed must not exceed baseline) AND credit-coverage gate
  (derived remaining >= $5.00 reserve + $1.25 maximum authorized run cost).

### Historical: fresh account-specific financial preflight for Modal A100 attempt 1 (live, read-only)

Captured 2026-09-24 immediately before allocation via `modal billing summary --json` / `billing rates --json` /
`app|container|volume list`.

- Starting owner-payable (billed) cost: **$0.00**; metered $20.03 fully absorbed by $20.03 credits
- Known remaining credit: **~$9.97**, *derived* (owner pool $30.00 minus credits applied; Modal exposes no remaining-credit field)
- GPU: A100-80GB x 1 at $2.50/h; hard ceiling 20 min; worst case = rate x 20 min x 1.5 = **$1.25** per job
- Fixed reserve **$5.00**; gate requires remaining >= reserve + $1.25

The runway is thin and must be re-checked live before every launch. (Historical A100 figures; the current H100 gate uses rate x 900 s = ~$1.083 worst case, see the current state above.)

### Runtime topology (derived, not measured; originally planned on A100, executed on H100)

Common: vLLM `v0.29.0` official image, digest
`sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b`
(the digest proven for Mistral Small 4 in Phase 21B.4.12.3), 1× 80GB GPU (planned A100-80GB; the executed canonical runtime is Modal H100 80GB),
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

### Smoke prompts (not a benchmark) -- canonical LOCKED protocol

One source of truth: `orca/eval/locked_smoke_protocol.py` (stdlib only; verifies its pinned fingerprint on import). Persisted, with UTF-8
bytes and per-prompt hashes, in `GENESIS_LOCKED_SMOKE_PROTOCOL_2026-09-25.json`. **Protocol SHA256:
`d462103b607e9741786ef86afc0b1769d5857d6e7feef36de516dac87a2b25c1`.**

`temperature=0`, `top_p=1`, `seed=0`, small `max_tokens` (1024 for Qwen's thinking template, 64 otherwise). User-only messages:

- **A** — `Reply exactly:\nREADY` (streamed, for first-token latency); accepted iff stripped content == `READY`
- **B** — `2 + 3`; accepted iff stripped content == `5`
- **C** — `Return valid JSON:\n{"status":"ready"}`; accepted iff the stripped content parses as JSON equal to exactly `{"status":"ready"}`

**Wording drift (historical, now corrected).** Until 2026-09-25 the runner used a longer wording (`Reply with exactly:\nREADY`,
`Return the single integer result of:\n2 + 3`, `Return valid JSON with one field:\n{"status":"ready"}`). Qwen3-8B attempt 4 was run with it
(raw evidence unchanged; protocol fingerprint as run `303f55ca…4829`); the never-sent planned prompts of the Mistral-Nemo and Phi-4
NOT_TESTED records were canonicalized with the originals preserved. A record produced with any non-canonical wording cannot be
RUNTIME_QUALIFIED (machine-enforced). The corrected CPU-only Qwen rendering is
`GENESIS_QWEN3_8B_RUNTIME_CONFIGURATION_ANALYSIS_V2_CANONICAL_PROMPTS_2026-09-25.json`; the earlier analysis artifact is marked superseded and preserved.

Technical PASS = server ready, `/v1/models` identity matches the pinned repo id, clean shutdown, zero orphan processes,
**and every locked smoke matches exactly** (whitespace stripped only): A == `READY`; B == `5`; C parses as JSON and equals exactly
`{"status":"ready"}`. HTTP 200 + non-empty content is necessary but never sufficient, and a "contains 5" / "mentions ready"
match is not acceptance. (An earlier version of this document called exact-match non-blocking; that was wrong and is superseded.)
Generated text is data only.

### Acceptance rules (machine-enforced in `orca/eval/control_runtime_qualification.py`)

- `RUNTIME_QUALIFIED` only if technical `QUALIFIED` **and** financial `PASS` **and**
  cleanup `PASS` with zero live resources **and** verified identity **and** verified hashes **and** every locked smoke exactly
  satisfied **and** (Modal) the run's credit coverage observed in the account data (`PENDING_SETTLEMENT_OBSERVATION` until then).
- Financial `PASS` only if `owner_billed_delta_usd == 0` exactly. Technical success with any
  positive owner billing is `NOT_ACCEPTED` (the GLM-5.3-Flash mistake must not recur).
- No retry after positive billing, unclear cost state, or a failed cleanup; no automatic retry ever.
- Every attempt is recorded; a hidden or omitted attempt fails validation.

### Attempt accounting (Qwen3-8B; all attempts preserved)

| Attempt | Provider | Outcome / failure domain | Duration | Owner billed delta (observed) | Cleanup | Settlement |
|---|---|---|---|---|---|---|
| 1 | Modal (A100) | HARNESS_FAILURE / HARNESS (poll `TimeoutError` not caught) | 34.6 s | 0 | PASS | BILLING_SETTLEMENT_NOT_YET_OBSERVABLE (unresolved; owner waiver lifts launch gating only) |
| 2 | Lightning AI | BLOCKED_NO_GPU / NONE (payment-method requirement) | 7.2 s | 0 | PASS | n/a |
| 3 | razorBridge | BLOCKED_NO_GPU / NONE (maintenance pause) | 0 s | 0 | n/a | n/a |
| 4 | Modal (H100) | TECHNICAL_FAILURE / MODEL_RUNTIME (locked Smoke B contract; originally judged TECHNICAL_SUCCESS, reclassified by audit) | 196.5 s | 0 | PASS | OBSERVED by reconciliation (0.22772907 USD promotional credit) |
| 5 | Modal (H100), `qwen3_8b_non_thinking_v1` | TECHNICAL_FAILURE / MODEL_RUNTIME (locked Smoke B: `2 + 3 = 5`) | 163.2 s | 0 | PASS | OBSERVED in-run (0.18768559 USD promotional credit) |

### Environment-only behaviour (not exercised by CI)

CI has no Modal SDK, so the deterministic suite runs the harness against a recording stand-in for `modal`, plus static
AST checks, and does **not** test real Modal SDK behaviour. Validated in CI: module syntax, constants, pinned image
digest/GPU/ceiling passed to the decorator, CLI mode declarations, no `eval`/`exec`/shell/Sandbox/generated-output
execution, financial-gate and result-validator wiring, and that `reconcile` is read-only. Environment-only (needs a real
Modal workspace): `FunctionCall.get(timeout=)` exception types and `cancel(terminate_containers=True)` semantics,
image build/pull, GPU scheduling and container lifecycle, vLLM serving behaviour, and the billing CLI's real output and
settlement latency.

### Historical: A100-era resume instructions (obsolete)

The earlier instructions ("run `--mode run` for attempt 2 on the A100 harness once attempt 1 settles") are obsolete: the canonical
runtime is the Modal H100 harness `scripts/phase21b_4_20_modal_h100_control.py` (`preflight | precache | run | reconcile | reevaluate-smokes`).
See "Resume conditions" in the current state above; no run is authorized at present.

## Program state (unchanged)

- GENESIS FOUNDATION: NOT SELECTED
- GENESIS FRONTIER STATUS: UNPROVEN
- CONTROL CAPABILITY STATUS: UNPROVEN
- PHASE 21C: NOT AUTHORIZED
- FRONTIER EXECUTION AUTHORIZED: NO
