"""
Independent per-contract validators. A validator sees ONLY the spec and the exact text about to be emitted; it is the authority (never the model, never the producer).
Strict contracts are validated BEFORE any user-visible emission.
"""
from __future__ import annotations

from . import arith
from .jsonutil import StrictJSONError, strict_equal, strict_loads
from .schema import validate as validate_schema
from .types import ContractSpec, ContractType, ValidationResult


def validate_exact_text(spec: ContractSpec, final: str) -> ValidationResult:
    ok = isinstance(final, str) and spec.literal is not None and final == spec.literal
    return ValidationResult(ok, "EXACT_TEXT:byte_equality", "" if ok else "final text is not byte-for-byte equal to the requested literal")


def validate_math(spec: ContractSpec, final: str) -> ValidationResult:
    try:
        expected, _ = arith.evaluate(spec.expression or "")
    except (arith.ArithmeticSyntaxError, arith.ArithmeticDomainError) as e:
        return ValidationResult(False, "DETERMINISTIC_MATH:recompute", f"expression has no evaluable value: {e}")
    text, _rounded = arith.format_result(expected)
    ok = isinstance(final, str) and final == text
    return ValidationResult(ok, "DETERMINISTIC_MATH:recompute_and_canonical_form", "" if ok else "final text is not the canonical representation of the recomputed value")


def validate_json_literal(spec: ContractSpec, final: str) -> ValidationResult:
    name = "JSON_LITERAL:strict_parse_and_strict_equality"
    if not isinstance(final, str) or final != final.strip():
        return ValidationResult(False, name, "surrounding whitespace / prefix / suffix is not allowed")
    if final.startswith("```") or final.endswith("```"):
        return ValidationResult(False, name, "Markdown fences are not allowed")
    try:
        got = strict_loads(final)
        want = strict_loads(spec.expected_json or "null")
    except StrictJSONError as e:
        return ValidationResult(False, name, str(e))
    ok = strict_equal(got, want)
    return ValidationResult(ok, name, "" if ok else "parsed JSON value differs from the requested value")


def validate_json_schema(spec: ContractSpec, final: str) -> ValidationResult:
    import json as _json
    name = "JSON_SCHEMA:strict_parse_and_schema_validation"
    if not isinstance(final, str) or final != final.strip():
        return ValidationResult(False, name, "surrounding whitespace / prefix / suffix is not allowed")
    if final.startswith("```") or final.endswith("```"):
        return ValidationResult(False, name, "Markdown fences are not allowed")
    try:
        instance = strict_loads(final)
        schema = _json.loads(spec.schema_json or "true")
    except (StrictJSONError, ValueError) as e:
        return ValidationResult(False, name, str(e))
    errs = validate_schema(instance, schema)
    return ValidationResult(not errs, name, "; ".join(errs[:5]))


def validate_free_text(spec: ContractSpec, final: str) -> ValidationResult:
    return ValidationResult(isinstance(final, str), "FREE_TEXT:none (normal runtime semantics)", "" if isinstance(final, str) else "output is not text")


VALIDATORS = {ContractType.EXACT_TEXT: validate_exact_text, ContractType.DETERMINISTIC_MATH: validate_math, ContractType.JSON_LITERAL: validate_json_literal,
              ContractType.JSON_SCHEMA: validate_json_schema, ContractType.FREE_TEXT: validate_free_text}


def validate(spec: ContractSpec, final: str) -> ValidationResult:
    return VALIDATORS[spec.contract_type](spec, final)
