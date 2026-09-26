# ORNEUR Contract Compliance Engine

**MODEL GENERATES INTELLIGENCE. ORNEUR OWNS THE CONTRACT.**

Package: `orca/contracts/` · Boundary adapter: `orca/contracts/gateway.py` · System qualification: `orca/eval/system_contract_qualification.py` ·
Evidence: `docs/orneur/phase-21/evidence/ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json`

```
Request → Contract Detection → Execution Strategy → Model / Deterministic Tool → Contract Validator → Recovery / Fail-Closed Policy → Final Output → Evidence
```

## 1. Why raw model generation cannot be the final contract authority

A language model samples text. Even at temperature 0 its answer to `Reply exactly: READY` depends on the checkpoint, the chat template, the tokenizer path and the serving stack; the
locked control program showed that three well-known instruct models answered such terse exact-output prompts with ordinary chat-style prose (`Understood. I'm ready.`, `2 + 3 equals 5.`,
fenced JSON with commentary). That is normal instruct-model behavior, not a bug to be argued away — and it means a product promise like "when you ask for exactly READY you get exactly
READY" cannot rest on the model. It has to rest on a component that can **prove** the promise. The engine is that component: if ORNEUR declares a strict contract satisfied, the runtime — not the
model — has independently checked the exact text that leaves.

## 2. Contract taxonomy

| Type | Meaning | Produced by | Validator |
|---|---|---|---|
| `EXACT_TEXT` | the request supplies the literal to return (`Reply exactly:` + literal) | ORNEUR emits the literal (no model) | `final == literal` (byte equality) |
| `DETERMINISTIC_MATH` | the message is a safe pure arithmetic expression | ORNEUR's exact-rational evaluator (no model) | recompute + canonical form |
| `JSON_LITERAL` | the request supplies the JSON value to return (`Return valid JSON:` + value) | ORNEUR canonical serialization (no model) | strict parse + strict value equality, no prefix/suffix/fence |
| `JSON_SCHEMA` | the response must satisfy a declared schema | a model (constrained decoding when a backend offers it) | strict parse + schema validation |
| `FREE_TEXT` | ordinary conversation | a model | none — normal runtime semantics, output untouched |

Reserved for later (not implemented): `TOOL_RESULT`, `CODE`, `SQL`, `XML`, `ENUM`, `REGEX`, `FUNCTION_ARGUMENTS`.

Result states: `SATISFIED`, `UNSATISFIABLE` (well formed but no valid output exists or the validator failed), `INVALID_CONTRACT` (the declared contract is itself malformed/unsupported),
`EXECUTION_FAILED` (execution could not run). Detection, execution, validation and emission are separate steps; a failed validator is never converted into `SATISFIED`.

## 3. Routing (deterministic, conservative, explicit priority)

0. a machine-declared `response_contract` in request metadata → `JSON_SCHEMA`
1. explicit exact literal → `EXACT_TEXT`
2. safe pure arithmetic expression → `DETERMINISTIC_MATH`
3. explicit requested JSON value → `JSON_LITERAL`
4. explicit schema requirement → `JSON_SCHEMA`
5. otherwise → `FREE_TEXT`

The whole message must *be* the directive. A directive buried in conversation (`I told him to reply exactly: no…`), vague wording (`reply exactly how you feel`), quote-wrapped or Markdown-fenced
literals (ambiguous whether the quotes/fence belong to the answer) and bare tight forms like `5-3`, `12/25`, `555-1234` or `2026-09-26` (ranges, dates, phone numbers) are **not** routed
deterministically. When a strict contract is unmistakably declared but cannot be honoured (empty or oversize literal, malformed JSON object, oversize arithmetic, unsupported schema
keyword) the result is `INVALID_CONTRACT` — the request is *not* handed to a model to guess. Nothing in detection depends on a model name, a prompt id or a benchmark string.

Framing rule for `EXACT_TEXT`: after the colon exactly one leading separator (one newline or one space/tab) and at most one trailing newline are framing; everything else — interior and
edge whitespace, multiple lines, Unicode — is the literal, emitted byte for byte. Literal limit: 2,000 characters; control characters are refused.

## 4. Validation

Every contract has an independent validator that sees only the spec and the exact text about to be emitted. Strict contracts are validated **before** any user-visible emission. JSON is
parsed strictly: the entire text is one value; trailing data, NaN/Infinity, duplicate keys, oversize (4,096 chars) and over-deep (20) documents are rejected; equality is strict
(`true ≠ 1`, `1 ≠ 1.0`). Arithmetic results are canonical: `5` (never `5.0`, `2 + 3 = 5` or prose), terminating decimals exactly (`0.1 + 0.2 → 0.3`), non-terminating quotients rounded
half-even to 12 fractional digits and explicitly flagged in evidence. The JSON-Schema support is a small dependency-free subset; any unsupported keyword makes the schema invalid.

## 4a. Fail-closed emission

The emission gate is fail-closed by construction. `ContractResult.final_output` exists only when the status is `SATISFIED`; the constructor refuses anything else. `ContractResult.emit()` raises the typed
`ContractViolationError` (client-safe payload `CONTRACT_<STATUS>`) instead of releasing malformed text. For generated strict contracts (`JSON_SCHEMA`) a failure may be followed by **one**
bounded recovery — a single retry that quotes the validator's reason — and, only if explicitly enabled, a deterministic strip of one exact Markdown fence. Both are recorded in the
evidence (`repair_attempted`, `repair_kind`, `transformations_by_orneur`, `raw_model_output` retained). If the output is still invalid the engine fails closed. `Here's the JSON: ```json…`
is never silently turned into a compliance claim.

## 5. Evidence

One record per execution: `contract_type`, `contract_detection_basis`, `requested_contract`, `execution_strategy`, `model_used`, `tool_used`, `raw_model_output`, `deterministic_result`,
`validator`, `validator_result`, `repair_attempted`, `repair_kind`, `transformations_by_orneur`, `model_calls`, `final_output`, `final_output_sha256`, `contract_status`. Two flags are
constant: `raw_model_compliance_claimed = false` (a system contract never claims the raw model complied) and `declared_compliance_trusted = false`. Any ORNEUR-side transformation
(serialization, evaluation, rounding, fence strip) is listed explicitly. Generated output is data and is never executed.

## 6. Integration boundary

`ContractEnforcedGateway(inner)` wraps any object with `async generate(request)` (and optionally `stream`): after request interpretation (the last user message defines the contract),
**before** expensive model execution when deterministic execution is possible (the inner gateway is not called), and before final emission when validation is required (strict generated
contracts are buffered and validated; nothing is streamed before validation). `FREE_TEXT` requests pass straight through untouched. The adapter never inspects a model or deployment
name and is opt-in: the default Model Gateway is unchanged.

Future ORNEUR models may return `content` plus **declared** contract metadata (`ContractEngine.execute_declared`). The declaration only selects which validator to run; a claim of compliance
inside it is ignored (declared compliance is never trusted), a strict contract declared by the request always wins, and the validator remains the sole authority.

## 7. Security considerations

* No Python evaluation of any kind: arithmetic uses a hand-written tokenizer + recursive-descent parser over exact rationals; names, calls, attributes, strings, exponent operators, unicode
  operators and scientific notation are syntax errors. Hard bounds on length (200), tokens (100), nesting (24), literal digits (30) and result size prevent resource exhaustion.
* JSON is parsed by the standard library with strict hooks; size/depth bounded; no schema keyword that could trigger catastrophic regex work is supported (`pattern` is unsupported).
* Model output is data and is never executed, imported or interpreted as code.
* Failures are typed and carry client-safe messages; internal reasons stay in evidence.
* Recovery is bounded to one retry, so a hostile or broken backend cannot loop the engine.

## 8. RAW_MODEL_RUNTIME_QUALIFICATION vs SYSTEM_CONTRACT_QUALIFICATION

| | `RAW_MODEL_RUNTIME_QUALIFICATION` | `SYSTEM_CONTRACT_QUALIFICATION` |
|---|---|---|
| Subject | a specific model checkpoint on a specific runtime | ORNEUR's contract engine |
| Question | does the model's own raw response satisfy the locked contract? | does ORNEUR guarantee the contract regardless of the model? |
| Evidence | Modal H100 runs of Qwen3-8B, Mistral-Nemo, Phi-4 (immutable history) | `ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json` (no model, GPU or provider) |
| Result today | **all three `RUNTIME_QUALIFIED = false`** (unchanged, never reinterpreted) | `SYSTEM_CONTRACT_QUALIFIED` for the three canonical cases |

The categories must never be conflated: the engine's qualification says nothing about whether any model is smart or compliant, and the raw failures say nothing about the engine.

## 9. What ORNEUR does and does not guarantee

ORNEUR does NOT guarantee that every AI request can be completed. ORNEUR guarantees that for **supported strict deterministic contracts**, invalid output is not silently emitted as
compliant output: it either satisfies the validator or a typed failure is returned and no malformed text is released.
