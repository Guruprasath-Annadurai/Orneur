"""
ORNEUR Contract Compliance Engine -- MODEL GENERATES INTELLIGENCE; ORNEUR OWNS THE CONTRACT.

    Request -> Contract Detection -> Execution Strategy -> Model / Deterministic Tool -> Contract Validator -> Recovery / Fail-Closed Policy -> Final Output -> Evidence

Deterministic contracts (EXACT_TEXT, DETERMINISTIC_MATH, JSON_LITERAL) never call a model. Generated strict contracts (JSON_SCHEMA) validate BEFORE emission; a bounded,
explicit recovery (one validator-feedback retry, and an optional deterministic single-fence strip, both recorded in evidence) may be used, and if the output is still invalid
the engine FAILS CLOSED: no malformed text ever leaves. FREE_TEXT is normal conversation and is passed through untouched. The engine is model-independent: it never inspects a
model name and never trusts a model's own claim of compliance.

The orchestration is one generator (`_flow`) driven by a sync and an async driver, so the two paths cannot diverge.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Generator

from . import arith
from .detect import route
from .jsonutil import canonical_dumps, strict_loads
from .schema import check_schema
from .types import (STRICT_TYPES, ContractEvidence, ContractResult, ContractSpec, ContractStatus, ContractType, ValidationResult, sha256_text)
from .validators import validate

TOOL_PREFIX = "orneur.contracts"
FEEDBACK_TEMPLATE = "Your previous reply was rejected by the ORNEUR contract validator ({reason}). Reply again with ONLY the requested JSON value: no prose, no Markdown, no code fence."


@dataclass(frozen=True)
class ModelRequest:
    """What the engine asks a model backend for (only for contracts that genuinely need generation)."""
    text: str
    attempt: int = 0
    feedback: str | None = None
    contract_type: str = "FREE_TEXT"
    json_schema: str | None = None          # canonical schema text for backends that support constrained generation (optional; the engine never relies on it)


class ModelUnavailable(RuntimeError):
    pass


def _requested(spec: ContractSpec) -> dict:
    d: dict[str, Any] = {"type": spec.contract_type.value, "detection_basis": spec.detection_basis, "declared_by": spec.declared_by, "source_sha256": spec.source_sha256}
    for k in ("literal", "expression", "expected_json", "schema_json", "invalid_reason"):
        v = getattr(spec, k)
        if v is not None:
            d[k] = v
    return d


class ContractEngine:
    def __init__(self, *, max_recovery_attempts: int = 1, allow_fence_repair: bool = False):
        if not (0 <= max_recovery_attempts <= 1):
            raise ValueError("recovery is bounded: at most ONE validator-feedback retry")
        self.max_recovery_attempts = max_recovery_attempts
        self.allow_fence_repair = allow_fence_repair

    # ── detection ───────────────────────────────────────────────────────────────────────────────────────────────────
    def route(self, text: str, metadata: dict | None = None) -> ContractSpec:
        return route(text, metadata)

    # ── evidence / result construction ──────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _finish(spec: ContractSpec, status: ContractStatus, *, strategy: str, model_label: str | None, tool: str | None, raw: str | None, deterministic: str | None,
                vr: ValidationResult | None, repair_attempted: bool, repair_kind: str | None, transforms: tuple[str, ...], model_calls: int, final: str | None,
                reason: str = "", extra: dict | None = None) -> ContractResult:
        emitted = final if status is ContractStatus.SATISFIED else None
        ev = ContractEvidence(
            contract_type=spec.contract_type.value, contract_detection_basis=spec.detection_basis, requested_contract=_requested(spec), execution_strategy=strategy,
            model_used=model_label if model_calls else None, tool_used=tool, raw_model_output=raw, deterministic_result=deterministic,
            validator=vr.validator if vr else "NONE", validator_result=("PASS" if vr.ok else "FAIL") if vr else "NOT_RUN", validator_reason=vr.reason if vr else reason,
            repair_attempted=repair_attempted, repair_kind=repair_kind, transformations_by_orneur=transforms, model_calls=model_calls, final_output=emitted,
            final_output_sha256=sha256_text(emitted) if emitted is not None else None, contract_status=status.value, strict=spec.strict, extra=dict(extra or {}))
        return ContractResult(status=status, spec=spec, evidence=ev, final_output=emitted, reason=reason)

    # ── deterministic producers ─────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _produce(spec: ContractSpec) -> tuple[str, str, tuple[str, ...]]:
        if spec.contract_type is ContractType.EXACT_TEXT:
            return spec.literal or "", f"{TOOL_PREFIX}.exact_text_emitter", ("EMITTED_EXPLICIT_USER_LITERAL_WITHOUT_MODEL",)
        if spec.contract_type is ContractType.DETERMINISTIC_MATH:
            value, _ops = arith.evaluate(spec.expression or "")
            text, rounded = arith.format_result(value)
            t = ("EVALUATED_BY_ORNEUR_SAFE_ARITHMETIC",) + (("ROUNDED_NON_TERMINATING_RESULT_TO_12_FRACTIONAL_DIGITS",) if rounded else ())
            return text, f"{TOOL_PREFIX}.safe_arithmetic_evaluator", t
        if spec.contract_type is ContractType.JSON_LITERAL:
            return canonical_dumps(strict_loads(spec.expected_json or "null")), f"{TOOL_PREFIX}.json_canonical_serializer", ("SERIALIZED_BY_ORNEUR_CANONICAL_JSON",)
        raise ValueError("not a deterministic contract")

    # ── the one orchestration flow (driven by the sync and async drivers) ───────────────────────────────────────────
    def _flow(self, text: str, metadata: dict | None, model_label: str | None) -> Generator[ModelRequest, Any, ContractResult]:
        spec = route(text, metadata)
        fin = self._finish
        if spec.invalid_reason:
            return fin(spec, ContractStatus.INVALID_CONTRACT, strategy="NONE", model_label=model_label, tool=None, raw=None, deterministic=None, vr=None, repair_attempted=False,
                       repair_kind=None, transforms=(), model_calls=0, final=None, reason=spec.invalid_reason)
        if spec.contract_type in (ContractType.EXACT_TEXT, ContractType.DETERMINISTIC_MATH, ContractType.JSON_LITERAL):
            try:
                candidate, tool, transforms = self._produce(spec)
            except arith.ArithmeticDomainError as e:
                return fin(spec, ContractStatus.UNSATISFIABLE, strategy="DETERMINISTIC_EMISSION", model_label=None, tool=f"{TOOL_PREFIX}.safe_arithmetic_evaluator", raw=None, deterministic=None,
                           vr=None, repair_attempted=False, repair_kind=None, transforms=(), model_calls=0, final=None, reason=f"the expression has no value: {e}")
            except (arith.ArithmeticSyntaxError, ValueError) as e:
                return fin(spec, ContractStatus.INVALID_CONTRACT, strategy="DETERMINISTIC_EMISSION", model_label=None, tool=None, raw=None, deterministic=None, vr=None,
                           repair_attempted=False, repair_kind=None, transforms=(), model_calls=0, final=None, reason=f"the contract could not be executed: {e}")
            vr = validate(spec, candidate)                                                   # independent validation BEFORE emission
            status = ContractStatus.SATISFIED if vr.ok else ContractStatus.UNSATISFIABLE
            return fin(spec, status, strategy="DETERMINISTIC_EMISSION", model_label=None, tool=tool, raw=None, deterministic=candidate, vr=vr, repair_attempted=False, repair_kind=None,
                       transforms=transforms, model_calls=0, final=candidate, reason="" if vr.ok else vr.reason)
        # ── model-generated contracts: JSON_SCHEMA (strict) and FREE_TEXT (passthrough) ──
        calls, attempt, feedback, repair_kind, repaired = 0, 0, None, None, False
        while True:
            req = ModelRequest(text=text, attempt=attempt, feedback=feedback, contract_type=spec.contract_type.value, json_schema=spec.schema_json)
            try:
                raw = yield req
            except Exception as e:  # noqa: BLE001  (any backend failure is a typed EXECUTION_FAILED, never a partial answer)
                return fin(spec, ContractStatus.EXECUTION_FAILED, strategy="MODEL_GENERATION", model_label=model_label, tool=None, raw=None, deterministic=None, vr=None,
                           repair_attempted=repaired, repair_kind=repair_kind, transforms=(), model_calls=calls, final=None, reason=f"model execution failed: {type(e).__name__}")
            calls += 1
            if not isinstance(raw, str):
                return fin(spec, ContractStatus.EXECUTION_FAILED, strategy="MODEL_GENERATION", model_label=model_label, tool=None, raw=None, deterministic=None, vr=None,
                           repair_attempted=repaired, repair_kind=repair_kind, transforms=(), model_calls=calls, final=None, reason="model backend returned non-text output")
            strategy = "MODEL_GENERATION_WITH_RECOVERY" if repaired else "MODEL_GENERATION"
            vr = validate(spec, raw)
            if spec.contract_type is ContractType.FREE_TEXT or vr.ok:
                return fin(spec, ContractStatus.SATISFIED, strategy=strategy, model_label=model_label, tool=None, raw=raw, deterministic=None, vr=vr, repair_attempted=repaired,
                           repair_kind=repair_kind, transforms=(), model_calls=calls, final=raw)
            if self.allow_fence_repair:
                unfenced = _strip_single_fence(raw)
                if unfenced is not None:
                    vr2 = validate(spec, unfenced)
                    if vr2.ok:                                                              # explicit, recorded transformation -- never presented as raw-model compliance
                        return fin(spec, ContractStatus.SATISFIED, strategy=strategy, model_label=model_label, tool=f"{TOOL_PREFIX}.single_fence_stripper", raw=raw, deterministic=unfenced,
                                   vr=vr2, repair_attempted=True, repair_kind="STRIP_SINGLE_MARKDOWN_FENCE", transforms=("STRIPPED_SINGLE_MARKDOWN_FENCE_BY_ORNEUR",), model_calls=calls,
                                   final=unfenced)
            if attempt < self.max_recovery_attempts:
                attempt += 1
                repaired, repair_kind = True, "MODEL_RETRY_WITH_VALIDATOR_FEEDBACK"
                feedback = FEEDBACK_TEMPLATE.format(reason=vr.reason[:300] or "invalid")
                continue
            return fin(spec, ContractStatus.UNSATISFIABLE, strategy=strategy, model_label=model_label, tool=None, raw=raw, deterministic=None, vr=vr, repair_attempted=repaired,
                       repair_kind=repair_kind, transforms=(), model_calls=calls, final=None, reason=f"output failed the contract validator after bounded recovery: {vr.reason}")

    # ── drivers ─────────────────────────────────────────────────────────────────────────────────────────────────────
    def execute(self, text: str, model_call: Callable[[ModelRequest], str] | None = None, *, metadata: dict | None = None, model_label: str | None = None) -> ContractResult:
        gen = self._flow(text, metadata, model_label)
        try:
            req = gen.send(None)
            while True:
                try:
                    if model_call is None:
                        raise ModelUnavailable("no model backend is available for a contract that requires generation")
                    out = model_call(req)
                except Exception as e:  # noqa: BLE001
                    req = gen.throw(e)
                else:
                    req = gen.send(out)
        except StopIteration as done:
            return done.value

    async def aexecute(self, text: str, model_call: Callable[[ModelRequest], Any] | None = None, *, metadata: dict | None = None, model_label: str | None = None) -> ContractResult:
        gen = self._flow(text, metadata, model_label)
        try:
            req = gen.send(None)
            while True:
                try:
                    if model_call is None:
                        raise ModelUnavailable("no model backend is available for a contract that requires generation")
                    out = model_call(req)
                    if inspect.isawaitable(out):
                        out = await out
                except Exception as e:  # noqa: BLE001
                    req = gen.throw(e)
                else:
                    req = gen.send(out)
        except StopIteration as done:
            return done.value

    # ── future model-generated contracts: content + DECLARED metadata, never trusted ────────────────────────────────
    def execute_declared(self, request_text: str, content: str, declared: dict | None, *, request_metadata: dict | None = None, model_label: str | None = None) -> ContractResult:
        """A future ORNEUR model may return `content` plus declared contract metadata. The declaration is only a hint about WHICH validator to run; any claim of compliance inside it
        is ignored, and a strict contract that the REQUEST itself declares always wins over the model's declaration. The validator is the sole authority."""
        request_spec = route(request_text, request_metadata)
        ignored = bool(isinstance(declared, dict) and declared.get("compliant") is not None)
        note = {"declared": {k: v for k, v in (declared or {}).items() if k != "compliant"}, "declared_compliance_ignored": ignored}
        if request_spec.strict:
            vr = validate(request_spec, content) if request_spec.invalid_reason is None and request_spec.contract_type in (ContractType.JSON_SCHEMA,) else None
            if vr is None:
                # deterministic request contracts are produced by ORNEUR itself; model content is not the authority here
                return self.execute(request_text, None, metadata=request_metadata, model_label=model_label)
            return self._finish(request_spec, ContractStatus.SATISFIED if vr.ok else ContractStatus.UNSATISFIABLE, strategy="MODEL_GENERATION", model_label=model_label, tool=None,
                                raw=content, deterministic=None, vr=vr, repair_attempted=False, repair_kind=None, transforms=(), model_calls=1, final=content,
                                reason="" if vr.ok else vr.reason, extra=dict(note, request_contract_took_precedence=True))
        spec = _spec_from_declaration(request_text, declared)
        if spec is None:
            return self._finish(route(request_text, None), ContractStatus.INVALID_CONTRACT, strategy="NONE", model_label=model_label, tool=None, raw=content, deterministic=None, vr=None,
                                repair_attempted=False, repair_kind=None, transforms=(), model_calls=1, final=None, reason="the model-declared contract is missing, unsupported or invalid", extra=note)
        vr = validate(spec, content)
        return self._finish(spec, ContractStatus.SATISFIED if vr.ok else ContractStatus.UNSATISFIABLE, strategy="MODEL_GENERATION", model_label=model_label, tool=None, raw=content,
                            deterministic=None, vr=vr, repair_attempted=False, repair_kind=None, transforms=(), model_calls=1, final=content, reason="" if vr.ok else vr.reason, extra=note)


def _spec_from_declaration(request_text: str, declared: dict | None) -> ContractSpec | None:
    if not isinstance(declared, dict):
        return None
    kind, src = declared.get("contract_type"), sha256_text(request_text)
    try:
        if kind == "JSON_SCHEMA":
            schema = declared.get("schema")
            if check_schema(schema) is not None:
                return None
            return ContractSpec(ContractType.JSON_SCHEMA, "MODEL-DECLARED schema (validated independently; compliance claims ignored)", src, schema_json=canonical_dumps(schema), declared_by="MODEL_DECLARATION")
        if kind == "JSON_LITERAL":
            return ContractSpec(ContractType.JSON_LITERAL, "MODEL-DECLARED literal (validated independently; compliance claims ignored)", src, expected_json=canonical_dumps(declared.get("value")),
                                declared_by="MODEL_DECLARATION")
    except (TypeError, ValueError):
        return None
    return None


def _strip_single_fence(raw: str) -> str | None:
    """A raw output that is EXACTLY one multi-line Markdown code fence around the payload -> the payload; anything else (prose around it, several fences) -> None."""
    s = raw.strip()
    if not (s.startswith("```") and s.endswith("```")) or s.count("```") != 2:
        return None
    first, sep, rest = s[3:-3].partition("\n")
    if sep and first.strip().lower() in ("", "json"):
        return rest.strip()
    return None
