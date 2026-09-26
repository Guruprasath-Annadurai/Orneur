"""ORNEUR Contract Compliance Engine: unit, adversarial, property/fuzz (seeded stdlib random) and system-qualification tests. No model, GPU or provider is ever used."""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import string
from fractions import Fraction
from pathlib import Path

import pytest

from orca.contracts import (ContractEngine, ContractStatus, ContractType, ContractViolationError, ModelRequest)
from orca.contracts import arith
from orca.contracts.detect import MAX_EXACT_LITERAL_CHARS, route
from orca.contracts.gateway import ContractEnforcedGateway
from orca.contracts.jsonutil import StrictJSONError, canonical_dumps, strict_equal, strict_loads
from orca.contracts.schema import check_schema, validate as schema_validate
from orca.contracts.types import ContractEvidence, ContractResult, ContractSpec
from orca.contracts.validators import validate
from orca.eval import system_contract_qualification as sysq
from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = REPO_ROOT / "orca" / "contracts"
EVIDENCE = REPO_ROOT / "docs" / "orneur" / "phase-21" / "evidence"
QUALIFICATION = EVIDENCE / "ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json"
CONTROL_EVIDENCE_AGGREGATE_SHA256 = "125db85c9abbbe2af9671c688a4335169162d8483c3f35bf763bf87688c2d358"      # sha256 over every GENESIS_CONTROL_{QWEN3_8B,MISTRAL_NEMO,PHI4}_* evidence file at the audited base


def boom(_req):
    raise AssertionError("model must not be called")


class Counting:
    def __init__(self, answer="a free answer"):
        self.calls, self.answer = 0, answer

    def __call__(self, req):
        self.calls += 1
        return self.answer


E = ContractEngine()


def run(text, model=None, engine=E, **kw):
    return engine.execute(text, model if model is not None else boom, **kw)


# ══ the three canonical cases are deterministic system contracts (no model) ═══════════════════════════════════════════════
@pytest.mark.parametrize("text,ctype,out", [("Reply exactly:\nREADY", ContractType.EXACT_TEXT, "READY"), ("2 + 3", ContractType.DETERMINISTIC_MATH, "5"),
                                            ('Return valid JSON:\n{"status":"ready"}', ContractType.JSON_LITERAL, '{"status":"ready"}')])
def test_canonical_cases_are_satisfied_without_any_model(text, ctype, out):
    r = run(text)
    assert r.status is ContractStatus.SATISFIED and r.spec.contract_type is ctype and r.final_output == out and r.emit() == out
    assert r.final_output.encode() == out.encode() and r.evidence.model_calls == 0 and r.evidence.validator_result == "PASS" and r.evidence.model_used is None
    assert r.evidence.raw_model_compliance_claimed is False and r.evidence.declared_compliance_trusted is False and r.evidence.transformations_by_orneur


# ══ EXACT_TEXT ═════════════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("prompt,literal", [("Reply exactly:\nREADY", "READY"), ("Reply exactly: READY", "READY"), ("please reply with exactly: ok", "ok"), ("REPLY EXACTLY:\nyes", "yes"),
                                            ("Respond exactly the following text:\nA B  C", "A B  C"), ("Say verbatim: héllo wörld ✓", "héllo wörld ✓"),
                                            ("Reply exactly:\nline one\nline two\n\nline four", "line one\nline two\n\nline four"), ("Reply exactly:\n  READY  ", "  READY  "),
                                            ("Reply exactly:\nREADY\n", "READY"), ("Reply exactly:\n\tTabbed", "\tTabbed"), ("Reply exactly:\n日本語のテキスト", "日本語のテキスト")])
def test_exact_text_literals_are_emitted_byte_for_byte(prompt, literal):
    r = run(prompt)
    assert r.spec.contract_type is ContractType.EXACT_TEXT and r.status is ContractStatus.SATISFIED and r.final_output == literal and r.evidence.model_calls == 0


@pytest.mark.parametrize("prompt", ["Reply exactly:", "Reply exactly:\n", "Reply exactly:\n   \n", "Reply exactly: \t"])
def test_empty_or_blank_literals_are_refused_as_invalid_contracts(prompt):
    r = run(prompt)
    assert r.status is ContractStatus.INVALID_CONTRACT and r.final_output is None and r.evidence.model_calls == 0
    with pytest.raises(ContractViolationError):
        r.emit()


def test_excessive_literal_length_and_control_characters_are_refused():
    assert run("Reply exactly:\n" + "x" * MAX_EXACT_LITERAL_CHARS).status is ContractStatus.SATISFIED
    assert run("Reply exactly:\n" + "x" * (MAX_EXACT_LITERAL_CHARS + 1)).status is ContractStatus.INVALID_CONTRACT
    assert run("Reply exactly:\nab\x00cd").status is ContractStatus.INVALID_CONTRACT


@pytest.mark.parametrize("prompt", ["Reply exactly how you feel", "Reply exactly as the docs say", "Can you reply exactly: yes or no?",
                                    "I told him to reply exactly: no, but he wrote a novel. What now?", "Please explain what it means to reply exactly", "reply exactly",
                                    'Reply exactly: "READY"', "Reply exactly: 'yes'", "Reply exactly: `code`", "Reply exactly: “quoted”"])
def test_vague_buried_or_quote_ambiguous_wording_is_never_deterministic(prompt):
    r = run(prompt, Counting("model answer"))
    assert r.spec.contract_type is ContractType.FREE_TEXT and r.final_output == "model answer"


# ══ DETERMINISTIC_MATH ═════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("expr,out", [("2 + 3", "5"), ("5 - 3", "2"), ("((2 + 3) * (4 - 1)) / 5", "3"), ("0.1 + 0.2", "0.3"), ("-(2 + 3)", "-5"), ("--3 + 1", "4"), ("7 / 2", "3.5"),
                                      ("10 / 4", "2.5"), ("2.5 + 2.5", "5"), ("3 * 0.5", "1.5"), ("2*3", "6"), ("1 - 5", "-4"), ("100 / 8", "12.5"), ("0.5 * 2", "1"),
                                      ("1 / 3", "0.333333333333"), ("2 / 3", "0.666666666667"), ("-1 / 3", "-0.333333333333"), ("1 - 1", "0"), ("0 * -5", "0"), ("(((((1 + 1)))))", None)])
def test_arithmetic_results_are_canonical_never_float_or_prose(expr, out):
    r = run(expr)
    if out is None:                                    # no binary operator worth routing? "(((((1 + 1)))))" has one: value 2
        assert r.final_output == "2"
        return
    assert r.spec.contract_type is ContractType.DETERMINISTIC_MATH and r.final_output == out and r.evidence.model_calls == 0
    assert "." not in out or not out.endswith("0")


@pytest.mark.parametrize("prompt,out", [("What is 2 + 3?", "5"), ("what's 6 * 7", "42"), ("Calculate 2+3", "5"), ("compute 5-3", "2"), ("Evaluate (1 + 2) * 3 =", "9"), ("2 + 3 =", "5"), ("Please calculate 10 / 4", "2.5")])
def test_explicit_calculate_lead_ins_are_supported(prompt, out):
    r = run(prompt)
    assert r.spec.contract_type is ContractType.DETERMINISTIC_MATH and r.final_output == out


@pytest.mark.parametrize("prompt", ["1 / 0", "calculate 1/0", "5 / (2 - 2)", "3 / 0.0"])
def test_division_by_zero_fails_closed_without_output_or_model(prompt):
    r = run(prompt)
    assert r.spec.contract_type is ContractType.DETERMINISTIC_MATH and r.status is ContractStatus.UNSATISFIABLE and r.final_output is None and r.evidence.model_calls == 0
    with pytest.raises(ContractViolationError):
        r.emit()


@pytest.mark.parametrize("prompt", ["__import__('os').system('echo pwned')", "2 + 3; import os", "2 + abs(3)", "(1).real + 2", "open('/etc/passwd')", "x + 1", "2 ** 3", "9 ** 9 ** 9", "1e3 + 1",
                                    "2 + 3 // 1", "lambda: 1", "2 + '3'", "print(2 + 3)", "[1] + [2]", "2 % 3", "２ + ３", "2 × 3", "−2 + 3", "2 + 3 and 4",
                                    "2 +", "(2 + 3", "2 + + ", "* 3", "()", "5", "3.14", "2 3", "call me at 555-1234", "2026-09-26", "12/25", "1-2", "3.4.5 + 1"])
def test_non_arithmetic_or_hostile_text_is_never_evaluated_or_routed_as_math(prompt):
    r = run(prompt, Counting("model answer"))
    assert r.spec.contract_type is ContractType.FREE_TEXT and r.final_output == "model answer"


@pytest.mark.parametrize("prompt", ["9" * 40 + " + 1", "(" * 30 + "1 + 1" + ")" * 30, " + ".join(["1"] * 120), "1 + " * 60 + "1" + " " * 200, "1" * 250 + " + 1"])
def test_oversized_or_resource_exhausting_arithmetic_is_rejected_not_evaluated(prompt):
    r = run(prompt)
    assert r.status is ContractStatus.INVALID_CONTRACT and r.final_output is None and r.evidence.model_calls == 0


def test_arith_module_has_no_code_evaluation_primitives():
    src = (CONTRACT_DIR / "arith.py").read_text()
    for banned in ("eval(", "exec(", "__import__", "ast.", "import ast", "literal_eval", "subprocess", "os.system"):
        assert banned not in src, banned
    assert not re.search(r"(?<![\w.])compile\(", src)                                                                 # only re.compile of the fixed token pattern is allowed


# ══ JSON_LITERAL ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("prompt,out", [('Return valid JSON:\n{"status":"ready"}', '{"status":"ready"}'), ('Return valid JSON: { "a" : [1, 2 , 3] }', '{"a":[1,2,3]}'),
                                        ("Return valid JSON: []", "[]"), ("Return valid JSON: [1, 2.5, \"x\", true, false, null]", '[1,2.5,"x",true,false,null]'),
                                        ('Return valid JSON: "hello"', '"hello"'), ("Return valid JSON: true", "true"), ("Return valid JSON: null", "null"), ("Return JSON: 42", "42"),
                                        ('Return valid JSON: {"k":"é","n":{"z":[{"y":1.0}]}}', '{"k":"é","n":{"z":[{"y":1.0}]}}'), ('Return valid JSON:\n{\n  "b": 1,\n  "a": 2\n}\n', '{"b":1,"a":2}'),
                                        ('Respond with the following JSON: {"ok": false}', '{"ok":false}'), ('please output only this valid json:{"x":null}', '{"x":null}')])
def test_json_literals_are_serialized_canonically_and_strictly(prompt, out):
    r = run(prompt)
    assert r.spec.contract_type is ContractType.JSON_LITERAL and r.status is ContractStatus.SATISFIED and r.final_output == out and r.evidence.model_calls == 0
    assert json.loads(r.final_output) == json.loads(out) and "SERIALIZED_BY_ORNEUR_CANONICAL_JSON" in r.evidence.transformations_by_orneur


@pytest.mark.parametrize("prompt", ['Return valid JSON: {"a":', 'Return valid JSON: {"a":1} and thanks!', 'Return valid JSON: {"a":1,"a":2}', 'Return valid JSON: {"a": NaN}',
                                    'Return valid JSON: {"a":1}\nReturn valid JSON: {"b":2}', "Return valid JSON: [1, 2,]", "Return valid JSON: {'a': 1}", 'Return valid JSON: {"a": Infinity}',
                                    "Return valid JSON: " + "[" * 30 + "]" * 30, "Return valid JSON: [" + ",".join(["1"] * 3000) + "]"])
def test_malformed_or_ambiguous_json_literals_fail_closed(prompt):
    r = run(prompt)
    assert r.spec.contract_type is ContractType.JSON_LITERAL and r.status is ContractStatus.INVALID_CONTRACT and r.final_output is None and r.evidence.model_calls == 0


@pytest.mark.parametrize("prompt", ['Return valid JSON:\n```json\n{"a":1}\n```', "Return valid JSON describing a user with a name and an age", "Return valid JSON: give me a user object",
                                    "Return valid JSON", "Can you return valid JSON: {\"a\":1} for me?", "Explain why we return JSON: it is portable"])
def test_fenced_conversational_or_unframed_json_requests_are_not_deterministic(prompt):
    r = run(prompt, Counting("model answer"))
    assert r.spec.contract_type is ContractType.FREE_TEXT and r.final_output == "model answer"


@pytest.mark.parametrize("final", ['{"status":"ready"}'])
def test_json_literal_validator_accepts_exactly_the_value(final):
    spec = route('Return valid JSON: {"status":"ready"}')
    assert validate(spec, final).ok and validate(spec, '{"status": "ready"}').ok                       # any strict-valid rendering of the same value with no surrounding text


@pytest.mark.parametrize("final", ['Here is the JSON:\n{"status":"ready"}', '```json\n{"status":"ready"}\n```', '{"status":"ready"}\nThanks!', ' {"status":"ready"}', '{"status":"ready"} ',
                                   '{"status":"READY"}', '{"status":"ready","x":1}', '{"status":true}', "", "{}", '{"status":"ready"', '{"status":"ready","status":"ready"}'])
def test_json_literal_validator_rejects_prefixes_suffixes_fences_and_value_drift(final):
    assert not validate(route('Return valid JSON: {"status":"ready"}'), final).ok


def test_strict_equality_distinguishes_bool_int_and_float():
    assert not strict_equal(True, 1) and not strict_equal(1, 1.0) and not strict_equal([1], [True]) and strict_equal({"a": [1, {"b": None}]}, {"a": [1, {"b": None}]})
    assert not strict_equal({"a": 1}, {"a": 1, "b": 2}) and not strict_equal([1, 2], [2, 1])
    with pytest.raises(StrictJSONError):
        strict_loads('{"a":1} trailing')


# ══ ROUTING priority, FREE_TEXT, leakage ═════════════════════════════════════════════════════════════════════════════════════
def test_routing_priority_is_explicit():
    assert route("Reply exactly:\n2 + 3").contract_type is ContractType.EXACT_TEXT                       # exact literal wins over arithmetic
    assert route('Reply exactly:\n{"a":1}').contract_type is ContractType.EXACT_TEXT and route('Reply exactly:\n{"a":1}').literal == '{"a":1}'
    assert route("2 + 3").contract_type is ContractType.DETERMINISTIC_MATH
    assert route('Return valid JSON: {"a":1}').contract_type is ContractType.JSON_LITERAL
    assert route('Return valid JSON matching this schema: {"type":"object"}').contract_type is ContractType.JSON_SCHEMA
    assert route("Tell me a story").contract_type is ContractType.FREE_TEXT
    meta = {"response_contract": {"type": "json_schema", "schema": {"type": "object"}}}
    assert route("2 + 3", meta).contract_type is ContractType.JSON_SCHEMA and route("2 + 3", meta).declared_by == "REQUEST_METADATA"   # a machine-declared contract is the highest priority
    assert route("2 + 3", {"response_contract": "nonsense"}).contract_type is ContractType.DETERMINISTIC_MATH
    assert route(12345).contract_type is ContractType.FREE_TEXT


CONVERSATION = ["Hello!", "How are you today?", "Explain quantum entanglement simply.", "Write a haiku about autumn.", "What is the capital of France?", "Summarize this article for me.",
                "I think 2 + 3 is a weird thing to ask a model, but what do you think about arithmetic education?", "Give me 5 ideas for a birthday party", "Tell me about JSON and why it is popular",
                "My phone number is 555-1234, please remember it", "The meeting is on 2026-09-26 at 3pm", "How do I reply exactly to a customer complaint politely?", "Translate 'exactly' into French",
                "What's 5 apples plus 3 apples?", "Return to the previous topic", "Reply to this email politely", "Answer briefly: what is DNS?", "print hello world in python", "say hi",
                "Output the results of the analysis in a table", "Please write a short poem", "Is 2+3 equal to 5? Explain.", "calculate my taxes for me", "what is love?"]


@pytest.mark.parametrize("prompt", CONVERSATION)
def test_ordinary_conversation_is_never_routed_to_a_deterministic_contract(prompt):
    c = Counting("free reply")
    r = run(prompt, c)
    assert r.spec.contract_type is ContractType.FREE_TEXT and r.final_output == "free reply" and c.calls == 1 and r.status is ContractStatus.SATISFIED and r.spec.strict is False


def test_free_text_passes_model_output_through_untouched_even_if_odd():
    odd = "  Sure!\n```json\n{\"x\": 1}\n``` \n"
    r = run("Tell me something", lambda q: odd)
    assert r.final_output == odd and r.evidence.transformations_by_orneur == () and r.evidence.validator_result == "PASS"


def test_contracts_package_is_model_independent_and_has_no_benchmark_strings():
    for p in CONTRACT_DIR.glob("*.py"):
        text = p.read_text()
        assert not re.search(r"\b(qwen|mistral|phi-?4?|llama|gemma)\b", text, re.IGNORECASE), p.name              # no model names anywhere
        assert "READY" not in text and "smoke" not in text.lower() and "d462103b" not in text, p.name                   # no memorized canonical prompts / protocol ids
        assert not re.search(r"['\"]status['\"]\s*:\s*['\"]ready", text), p.name


# ══ JSON_SCHEMA + recovery + fail-closed ═══════════════════════════════════════════════════════════════════════════════════
SCHEMA_PROMPT = 'Return valid JSON matching this schema: {"type":"object","properties":{"name":{"type":"string"},"age":{"type":"integer","minimum":0}},"required":["name","age"],"additionalProperties":false}'


def test_schema_contract_validates_before_emission():
    r = E.execute(SCHEMA_PROMPT, lambda q: '{"name":"Ada","age":36}')
    assert r.spec.contract_type is ContractType.JSON_SCHEMA and r.status is ContractStatus.SATISFIED and r.final_output == '{"name":"Ada","age":36}' and r.evidence.model_calls == 1
    assert r.evidence.transformations_by_orneur == () and r.evidence.raw_model_output == r.final_output and r.evidence.repair_attempted is False


@pytest.mark.parametrize("bad", ['{"name":"Ada"}', '{"name":"Ada","age":"36"}', '{"name":"Ada","age":-1}', '{"name":"Ada","age":36,"x":1}', '{"name":"Ada","age":true}', 'Here you go: {"name":"Ada","age":36}',
                                 '```json\n{"name":"Ada","age":36}\n```', "", "not json", '{"name":"Ada","age":36} thanks', '[1]'])
def test_invalid_structured_output_is_never_released(bad):
    engine = ContractEngine(max_recovery_attempts=0)
    r = engine.execute(SCHEMA_PROMPT, lambda q: bad)
    assert r.status is ContractStatus.UNSATISFIABLE and r.final_output is None and r.evidence.validator_result == "FAIL" and r.evidence.raw_model_output == bad
    with pytest.raises(ContractViolationError) as ei:
        r.emit()
    assert ei.value.to_client_payload()["error_code"] == "CONTRACT_UNSATISFIABLE" and "no output was released" in ei.value.to_client_payload()["message"]


def test_one_bounded_recovery_is_explicit_and_recorded():
    answers = iter(['Sure! {"name":"Ada","age":36}', '{"name":"Ada","age":36}'])
    seen = []

    def model(req: ModelRequest):
        seen.append((req.attempt, req.feedback))
        return next(answers)

    r = E.execute(SCHEMA_PROMPT, model)
    assert r.status is ContractStatus.SATISFIED and r.evidence.repair_attempted and r.evidence.repair_kind == "MODEL_RETRY_WITH_VALIDATOR_FEEDBACK" and r.evidence.model_calls == 2
    assert seen[0] == (0, None) and seen[1][0] == 1 and "rejected by the ORNEUR contract validator" in seen[1][1] and r.evidence.execution_strategy == "MODEL_GENERATION_WITH_RECOVERY"
    still_bad = E.execute(SCHEMA_PROMPT, lambda q: "never valid")
    assert still_bad.status is ContractStatus.UNSATISFIABLE and still_bad.evidence.model_calls == 2 and still_bad.final_output is None            # exactly ONE retry, then fail closed
    with pytest.raises(ValueError):
        ContractEngine(max_recovery_attempts=2)


def test_markdown_fence_repair_is_off_by_default_and_fully_disclosed_when_on():
    fenced = '```json\n{"name":"Ada","age":36}\n```'
    assert ContractEngine(max_recovery_attempts=0).execute(SCHEMA_PROMPT, lambda q: fenced).status is ContractStatus.UNSATISFIABLE
    r = ContractEngine(max_recovery_attempts=0, allow_fence_repair=True).execute(SCHEMA_PROMPT, lambda q: fenced)
    assert r.status is ContractStatus.SATISFIED and r.final_output == '{"name":"Ada","age":36}' and r.evidence.raw_model_output == fenced
    assert r.evidence.repair_kind == "STRIP_SINGLE_MARKDOWN_FENCE" and "STRIPPED_SINGLE_MARKDOWN_FENCE_BY_ORNEUR" in r.evidence.transformations_by_orneur and r.evidence.raw_model_compliance_claimed is False
    prose = ContractEngine(max_recovery_attempts=0, allow_fence_repair=True).execute(SCHEMA_PROMPT, lambda q: 'Here:\n' + fenced)
    assert prose.status is ContractStatus.UNSATISFIABLE                                                              # only an EXACT single fence is ever repaired


def test_execution_failures_and_invalid_contracts_are_typed():
    def exploding(q):
        raise ConnectionError("backend down")
    r = E.execute(SCHEMA_PROMPT, exploding)
    assert r.status is ContractStatus.EXECUTION_FAILED and r.final_output is None and "ConnectionError" in r.reason
    assert E.execute(SCHEMA_PROMPT, None).status is ContractStatus.EXECUTION_FAILED
    assert E.execute(SCHEMA_PROMPT, lambda q: 123).status is ContractStatus.EXECUTION_FAILED
    bad_schema = E.execute('Return valid JSON matching this schema: {"type":"object","patternProperties":{}}', boom)
    assert bad_schema.status is ContractStatus.INVALID_CONTRACT and bad_schema.evidence.model_calls == 0 and "patternProperties" in bad_schema.reason
    assert E.execute("Return valid JSON matching this schema: not json", boom).status is ContractStatus.INVALID_CONTRACT
    meta = {"response_contract": {"type": "json_schema", "schema": {"type": "array", "items": {"type": "integer"}}}}
    r2 = E.execute("give me numbers", lambda q: "[1,2,3]", metadata=meta)
    assert r2.status is ContractStatus.SATISFIED and r2.spec.declared_by == "REQUEST_METADATA" and r2.final_output == "[1,2,3]"
    assert E.execute("give me numbers", lambda q: "[1,2,\"3\"]", metadata=meta, ).status is ContractStatus.UNSATISFIABLE


def test_schema_subset_semantics_and_fail_closed_keywords():
    s = {"type": "object", "properties": {"t": {"enum": ["a", "b"]}, "n": {"type": "number", "maximum": 10}, "l": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 2},
                                          "c": {"const": 1}, "s": {"type": "string", "minLength": 2, "maxLength": 3}}, "required": ["t"]}
    assert check_schema(s) is None
    ok = {"t": "a", "n": 3.5, "l": ["x"], "c": 1, "s": "ab"}
    assert schema_validate(ok, s) == []
    for bad in ({"t": "z"}, {"t": "a", "n": 11}, {"t": "a", "l": []}, {"t": "a", "l": ["a", "b", "c"]}, {"t": "a", "l": [1]}, {"t": "a", "c": True}, {"t": "a", "s": "a"}, {"t": "a", "s": "abcd"}, {}, {"t": "a", "n": True}):
        assert schema_validate(bad, s), bad
    for unsupported in ({"$ref": "#/x"}, {"pattern": "a+"}, {"oneOf": []}, {"type": "quantum"}, {"required": "x"}, {"minLength": -1}, {"properties": []}, 5, None):
        assert check_schema(unsupported) is not None, unsupported
    assert schema_validate(True, {"type": "integer"}) and schema_validate(1.0, {"type": "integer"}) == []


# ══ ContractResult invariants, evidence, declared contracts ═════════════════════════════════════════════════════════════════
def test_a_failed_result_can_never_hold_output_and_a_satisfied_one_must():
    spec = route("2 + 3")
    ev = run("2 + 3").evidence
    with pytest.raises(ValueError):
        ContractResult(ContractStatus.UNSATISFIABLE, spec, ev, final_output="5")
    with pytest.raises(ValueError):
        ContractResult(ContractStatus.SATISFIED, spec, ev, final_output=None)
    with pytest.raises(Exception):
        run("2 + 3").status = ContractStatus.UNSATISFIABLE                                                       # frozen


def test_evidence_records_every_required_field_and_is_json_serializable():
    for text in ("Reply exactly:\nREADY", "2 + 3", 'Return valid JSON: {"a":1}'):
        d = run(text).evidence.to_dict()
        for k in ("contract_type", "contract_detection_basis", "requested_contract", "execution_strategy", "model_used", "tool_used", "raw_model_output", "deterministic_result", "validator",
                  "validator_result", "repair_attempted", "repair_kind", "final_output", "final_output_sha256", "contract_status", "transformations_by_orneur", "model_calls"):
            assert k in d, k
        assert d["tool_used"].startswith("orneur.contracts.") and d["final_output_sha256"] == hashlib.sha256(d["final_output"].encode()).hexdigest() and d["deterministic_result"] == d["final_output"]
        assert d["raw_model_output"] is None and d["model_used"] is None
        json.dumps(d)
    failed = run("1 / 0").evidence
    assert failed.final_output is None and failed.final_output_sha256 is None and failed.contract_status == "UNSATISFIABLE"
    assert run("1 / 3").evidence.transformations_by_orneur == ("EVALUATED_BY_ORNEUR_SAFE_ARITHMETIC", "ROUNDED_NON_TERMINATING_RESULT_TO_12_FRACTIONAL_DIGITS")


def test_model_declared_compliance_is_never_trusted():
    decl = {"contract_type": "JSON_SCHEMA", "schema": {"type": "object", "required": ["a"]}, "compliant": True}
    bad = E.execute_declared("Make me an object", '{"b": 1}', decl)
    assert bad.status is ContractStatus.UNSATISFIABLE and bad.final_output is None and bad.evidence.extra["declared_compliance_ignored"] is True and bad.evidence.declared_compliance_trusted is False
    good = E.execute_declared("Make me an object", '{"a": 1}', decl)
    assert good.status is ContractStatus.SATISFIED and good.evidence.requested_contract["declared_by"] == "MODEL_DECLARATION"
    lit = E.execute_declared("x", '{"k": 1}', {"contract_type": "JSON_LITERAL", "value": {"k": 1}, "compliant": True})
    assert lit.status is ContractStatus.SATISFIED
    assert E.execute_declared("x", "anything", {"contract_type": "CODE", "compliant": True}).status is ContractStatus.INVALID_CONTRACT
    assert E.execute_declared("x", "anything", None).status is ContractStatus.INVALID_CONTRACT
    # a strict contract declared by the REQUEST always wins over the model's declaration
    won = E.execute_declared(SCHEMA_PROMPT, '{"name":"A"}', {"contract_type": "JSON_SCHEMA", "schema": {"type": "object"}, "compliant": True})
    assert won.status is ContractStatus.UNSATISFIABLE and won.evidence.extra["request_contract_took_precedence"] is True
    det = E.execute_declared("2 + 3", "9", {"contract_type": "JSON_LITERAL", "value": 9, "compliant": True})
    assert det.final_output == "5" and det.evidence.model_calls == 0                                                # a deterministic request contract is produced by ORNEUR, not by the model


# ══ gateway boundary ═══════════════════════════════════════════════════════════════════════════════════════════════════════
class FakeInner:
    def __init__(self, outputs):
        self.outputs, self.calls, self.requests = list(outputs), 0, []

    async def generate(self, request, allow_experimental=False):
        self.calls += 1
        self.requests.append(request)
        out = self.outputs[min(self.calls - 1, len(self.outputs) - 1)]
        return InferenceResponse(request_id=request.request_id, model_id=request.model_id, resolved_version="v", runtime="fake", deployment_id="d", output=out, finish_reason="stop", prompt_tokens=3,
                                 completion_tokens=4, latency_ms=1.0, queue_latency_ms=0.0, model_latency_ms=1.0)

    async def stream(self, request, allow_experimental=False):
        self.calls += 1
        yield InferenceChunk(request_id=request.request_id, sequence=0, delta="hello", finish_reason="stop")


def req(text, **kw):
    return InferenceRequest(request_id="r1", model_id="any-model-id", messages=[{"role": "user", "content": text}], **kw)


def test_gateway_serves_deterministic_contracts_without_touching_the_inner_gateway():
    inner, sink = FakeInner(["SHOULD NOT BE USED"]), []
    gw = ContractEnforcedGateway(inner, evidence_sink=sink.append)
    for text, out in (("Reply exactly:\nREADY", "READY"), ("2 + 3", "5"), ('Return valid JSON:\n{"status":"ready"}', '{"status":"ready"}')):
        resp = asyncio.run(gw.generate(req(text)))
        assert resp.output == out and resp.runtime == "orneur-contract-engine" and resp.prompt_tokens == 0 and resp.completion_tokens == 0 and resp.cost_usd == 0.0
        chunks = []

        async def collect():
            async for c in gw.stream(req(text)):
                chunks.append(c)
        asyncio.run(collect())
        assert [c.delta for c in chunks] == [out] and chunks[0].finish_reason == "stop"
    assert inner.calls == 0 and len(sink) == 6 and all(e["model_calls"] == 0 and e["contract_status"] == "SATISFIED" and e["request_id"] == "r1" for e in sink)


def test_gateway_passes_free_text_through_unchanged_and_ignores_system_prompts_for_contracts():
    inner = FakeInner(["chatty answer"])
    gw = ContractEnforcedGateway(inner)
    r = req("Tell me about cats")
    resp = asyncio.run(gw.generate(r))
    assert resp.output == "chatty answer" and resp.runtime == "fake" and inner.calls == 1
    sysreq = InferenceRequest(request_id="r2", model_id="m", messages=[{"role": "user", "content": "hello"}], system="Reply exactly:\nREADY")
    assert asyncio.run(gw.generate(sysreq)).output == "chatty answer"
    multi = InferenceRequest(request_id="r3", model_id="m", messages=[{"role": "user", "content": "Reply exactly:\nREADY"}, {"role": "assistant", "content": "READY"}, {"role": "user", "content": "thanks"}])
    assert asyncio.run(gw.generate(multi)).output == "chatty answer"                                                  # only the LAST user message defines the contract
    parts = InferenceRequest(request_id="r4", model_id="m", messages=[{"role": "user", "content": [{"type": "text", "text": "2 + 3"}]}])
    assert asyncio.run(gw.generate(parts)).output == "chatty answer"                                                  # non-string content is not interpreted
    chunks = []

    async def collect():
        async for c in gw.stream(req("chat with me")):
            chunks.append(c.delta)
    asyncio.run(collect())
    assert chunks == ["hello"]


def test_gateway_validates_generated_strict_contracts_before_emission_and_fails_closed():
    good = ContractEnforcedGateway(FakeInner(['{"name":"Ada","age":36}']))
    resp = asyncio.run(good.generate(req(SCHEMA_PROMPT)))
    assert resp.output == '{"name":"Ada","age":36}' and resp.runtime == "fake" and any("validated" in w for w in resp.warnings)
    recover = FakeInner(["oops", '{"name":"Ada","age":36}'])
    r2 = asyncio.run(ContractEnforcedGateway(recover).generate(req(SCHEMA_PROMPT)))
    assert r2.output == '{"name":"Ada","age":36}' and recover.calls == 2 and recover.requests[1].messages[-1]["role"] == "user" and "rejected by the ORNEUR contract validator" in recover.requests[1].messages[-1]["content"]
    sink = []
    bad = ContractEnforcedGateway(FakeInner(["not json"]), evidence_sink=sink.append)
    with pytest.raises(ContractViolationError):
        asyncio.run(bad.generate(req(SCHEMA_PROMPT)))
    assert sink and sink[0]["contract_status"] == "UNSATISFIABLE" and sink[0]["final_output"] is None
    chunks = []

    async def collect():
        async for c in bad.stream(req(SCHEMA_PROMPT)):
            chunks.append(c)
    with pytest.raises(ContractViolationError):
        asyncio.run(collect())
    assert chunks == []                                                                                                # nothing was streamed before validation


def test_gateway_stays_model_independent():
    src = (CONTRACT_DIR / "gateway.py").read_text()
    assert "model_id" in src and not re.search(r"model_id\s*(==|in|startswith)", src) and "deployment_id ==" not in src


# ══ property / fuzz tests (seeded stdlib random: reproducible, no extra dependency) ═════════════════════════════════════════
def _gen_expr(rng, depth=0):
    """(expression text, exact expected Fraction) built together from an independent reference. Compound operands are always parenthesised, so precedence never matters."""
    return _gen_expr3(rng, depth)[:2]


def _gen_expr3(rng, depth=0):
    if depth > 3 or rng.random() < 0.3:
        whole = rng.randint(0, 999)
        if rng.random() < 0.4:
            frac = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 3)))
            return f"{whole}.{frac}", Fraction(f"{whole}.{frac}"), True
        return str(whole), Fraction(whole), True
    op = rng.choice("+-*/")
    (lt, lv, la), (rt, rv, ra) = _gen_expr3(rng, depth + 1), _gen_expr3(rng, depth + 1)
    if op == "/" and rv == 0:
        op = "+"
    lt, rt = (lt if la else f"({lt})"), (rt if ra else f"({rt})")
    val = {"+": lv + rv, "-": lv - rv, "*": lv * rv, "/": (lv / rv if rv != 0 else Fraction(0))}[op]
    text = f"{lt} {op} {rt}"
    if rng.random() < 0.5:
        return f"({text})", val, True
    return text, val, False


def test_property_arithmetic_matches_an_independent_reference_and_never_calls_a_model():
    rng = random.Random(20260926)
    for _ in range(600):
        text, want = _gen_expr(rng)
        if len(text) > 150:
            continue
        got, _ = arith.evaluate(text)
        assert got == want, text
        r = E.execute(text, boom)
        if r.spec.contract_type is ContractType.DETERMINISTIC_MATH:                                                    # bare single literals/tight forms may legitimately stay FREE_TEXT
            assert r.status is ContractStatus.SATISFIED and r.evidence.model_calls == 0
            canon, _ = arith.format_result(want)
            assert r.final_output == canon
            assert "e" not in r.final_output.lower() and not r.final_output.endswith(".") and validate(r.spec, r.final_output).ok


def test_property_arithmetic_parser_never_executes_code_or_raises_unexpectedly():
    rng = random.Random(7)
    alphabet = string.printable + "é中２−×"
    payloads = ["__import__('os').system('touch /tmp/pwned_by_contract_test')", "(lambda: 1)()", "1 + (2).__class__", "0 if 1 else 2", "[x for x in range(3)]", "1;2", "print(1)", "2**99999999", "(1<<9999)"]
    sentinel = Path("/tmp/pwned_by_contract_test")
    sentinel.unlink(missing_ok=True)
    for text in payloads + ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60))) for _ in range(2500)]:
        try:
            arith.evaluate(text)
        except (arith.ArithmeticSyntaxError, arith.ArithmeticDomainError):
            pass
        spec = route(text)                                                                                           # routing never raises either
        if re.search(r"[^0-9.\s+\-*/()=?]", text):
            assert spec.contract_type is not ContractType.DETERMINISTIC_MATH, repr(text)
    assert not sentinel.exists()


def _gen_json(rng, depth=0):
    if depth > 3 or rng.random() < 0.35:
        return rng.choice([None, True, False, rng.randint(-10**6, 10**6), round(rng.uniform(-1e6, 1e6), 3), "".join(rng.choice(string.ascii_letters + " é✓\"\\\n\t") for _ in range(rng.randint(0, 12)))])
    if rng.random() < 0.5:
        return [_gen_json(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {"".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(1, 6))) + str(i): _gen_json(rng, depth + 1) for i in range(rng.randint(0, 4))}


def test_property_json_serializer_always_emits_parseable_strictly_equal_canonical_json():
    rng = random.Random(4242)
    for _ in range(400):
        value = _gen_json(rng)
        pretty = json.dumps(value, indent=rng.choice([None, 1, 4]), ensure_ascii=rng.random() < 0.5)
        if "\n" in pretty and pretty.lstrip()[:1] not in "{[":
            continue
        r = E.execute("Return valid JSON:\n" + pretty, boom)
        assert r.status is ContractStatus.SATISFIED and r.spec.contract_type is ContractType.JSON_LITERAL and r.evidence.model_calls == 0, pretty
        assert r.final_output == json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        assert strict_equal(json.loads(r.final_output), value) and r.final_output == r.final_output.strip() and validate(r.spec, r.final_output).ok


def test_property_exact_text_output_equals_its_literal_exactly():
    rng = random.Random(99)
    pool = string.ascii_letters + string.digits + " \t\n.,;:!?-_()[]{}<>/\\@#%&*+=é世界✓"
    checked = 0
    for _ in range(600):
        lit = "".join(rng.choice(pool) for _ in range(rng.randint(1, 80)))
        stripped = lit.strip()
        if not stripped or lit.endswith(("\n", "\r")) or (len(stripped) >= 2 and stripped[0] in "\"'`" and stripped[-1] == stripped[0]):
            continue
        r = E.execute("Reply exactly:\n" + lit, boom)
        assert r.spec.contract_type is ContractType.EXACT_TEXT and r.final_output == lit and r.evidence.model_calls == 0 and r.status is ContractStatus.SATISFIED, repr(lit)
        checked += 1
    assert checked > 300


def test_property_deterministic_contracts_never_call_the_model_backend():
    rng = random.Random(31337)
    counting = Counting()
    prompts = ["Reply exactly:\nREADY", "2 + 3", 'Return valid JSON: {"a":[1,2]}', "calculate 7 * 6", "Reply exactly: héllo"]
    prompts += [_gen_expr(rng)[0] for _ in range(200)] + ["Return valid JSON: " + json.dumps(_gen_json(rng)) for _ in range(100)]
    deterministic = 0
    for p in prompts:
        r = E.execute(p, counting)
        if r.spec.contract_type is not ContractType.FREE_TEXT:
            deterministic += 1
            assert r.evidence.model_calls == 0
    assert deterministic > 200 and counting.calls == len(prompts) - deterministic


def test_property_router_is_pure_and_total():
    rng = random.Random(5)
    for _ in range(1500):
        text = "".join(rng.choice(string.printable + "é中​") for _ in range(rng.randint(0, 120)))
        assert route(text) == route(text)                                                                            # pure
        assert route(text).contract_type in ContractType


# ══ system qualification + historical integrity ════════════════════════════════════════════════════════════════════════════
def test_system_contract_qualification_is_real_separate_and_needs_no_model_gpu_or_provider():
    q = sysq.run_system_contract_qualification()
    assert q["qualification_type"] == "SYSTEM_CONTRACT_QUALIFICATION" and q["suite"] == "ORNEUR_SYSTEM_CONTRACT_QUALIFICATION"
    assert q["model_calls"] == 0 and q["gpu_calls"] == 0 and q["provider_calls"] == 0 and q["all_contracts_satisfied"] is True and q["verdict"] == "SYSTEM_CONTRACT_QUALIFIED"
    assert {k: (v["detected_contract_type"], v["final_output"], v["passed"]) for k, v in q["cases"].items()} == {
        "A": ("EXACT_TEXT", "READY", True), "B": ("DETERMINISTIC_MATH", "5", True), "C": ("JSON_LITERAL", '{"status":"ready"}', True)}


def test_the_verdict_is_earned_never_fabricated():
    class Broken(ContractEngine):                                                        # an engine whose exact-text producer is wrong must NOT qualify
        @staticmethod
        def _produce(spec):
            text, tool, tr = ContractEngine._produce(spec)
            return (text + " " if spec.contract_type is ContractType.EXACT_TEXT else text), tool, tr
    q = sysq.run_system_contract_qualification(Broken())
    assert q["verdict"] == "SYSTEM_CONTRACT_NOT_QUALIFIED" and q["all_contracts_satisfied"] is False and q["cases"]["A"]["passed"] is False and q["cases"]["A"]["contract_status"] == "UNSATISFIABLE"


def test_a_model_backend_that_explodes_is_never_called_for_a_b_c():
    calls = []

    def exploding_model(_req):
        calls.append(1)
        raise AssertionError("model must not be called")
    for text in ("Reply exactly:\nREADY", "2 + 3", 'Return valid JSON:\n{"status":"ready"}'):
        assert E.execute(text, exploding_model).status is ContractStatus.SATISFIED
    assert calls == []


def test_qualification_artifact_matches_the_real_engine_and_states_the_separation():
    art = json.loads(QUALIFICATION.read_text())
    assert art["qualification_type"] == "SYSTEM_CONTRACT_QUALIFICATION" and art["verdict"] == "SYSTEM_CONTRACT_QUALIFIED" and art["all_contracts_satisfied"] is True
    assert (art["model_calls"], art["gpu_calls"], art["provider_calls"]) == (0, 0, 0) and art["no_gpu_used"] and art["no_modal_used"] and art["no_provider_call"] and art["generated_output_executed"] is False
    assert "NOT a model" in art["statement"] and "RUNTIME_QUALIFIED = false" in art["statement"]
    live = sysq.run_system_contract_qualification()
    for sid in "ABC":
        a, b = art["cases"][sid], live["cases"][sid]
        assert {k: a[k] for k in ("input", "expected_contract_type", "detected_contract_type", "expected_output", "final_output", "validator", "validator_result", "contract_status", "passed")} == \
               {k: b[k] for k in ("input", "expected_contract_type", "detected_contract_type", "expected_output", "final_output", "validator", "validator_result", "contract_status", "passed")}
        assert a["final_output_byte_equal"] is True and a["model_calls"] == 0 and a["evidence"]["final_output_sha256"] == hashlib.sha256(a["final_output"].encode()).hexdigest()


def test_raw_model_control_results_and_evidence_are_unchanged_and_separate():
    h = sysq.historical_control_state(EVIDENCE)
    assert h["control_evidence_aggregate_sha256"] == CONTROL_EVIDENCE_AGGREGATE_SHA256 and h["file_count"] >= 40
    m = h["raw_model_results_unchanged_and_separate"]
    assert {k: v["locked_smokes"] for k, v in m.items()} == {"Qwen3-8B": ["PASS", "FAIL", "PASS"], "Mistral-Nemo-Instruct-2407": ["FAIL", "FAIL", "FAIL"], "Phi-4": ["PASS", "FAIL", "FAIL"]}
    assert all(v["RUNTIME_QUALIFIED"] is False and v["runtime_qualification_status"] == "FAILED" and v["capability_status"] == "UNPROVEN" for v in m.values())
    art = json.loads(QUALIFICATION.read_text())
    assert art["historical_control_state"]["control_evidence_aggregate_sha256"] == CONTROL_EVIDENCE_AGGREGATE_SHA256                     # recorded at qualification time == today
    matrix = (REPO_ROOT / "docs/orneur/phase-21/GENESIS_CONTROL_RUNTIME_QUALIFICATION_MATRIX_2026-09-24.md").read_text()
    assert "**No control is RUNTIME_QUALIFIED.**" in matrix


def test_contract_engine_documentation_states_the_required_boundaries():
    doc = (REPO_ROOT / "docs/orneur/contracts/ORNEUR_CONTRACT_ENGINE.md").read_text()
    for needle in ("RAW_MODEL_RUNTIME_QUALIFICATION", "SYSTEM_CONTRACT_QUALIFICATION", "does NOT guarantee", "fail-closed", "MODEL GENERATES INTELLIGENCE", "EXACT_TEXT", "DETERMINISTIC_MATH", "JSON_LITERAL", "JSON_SCHEMA",
                   "FREE_TEXT", "Security considerations", "never trusted"):
        assert needle in doc, needle
