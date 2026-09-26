"""
Deterministic, CONSERVATIVE contract detection and routing. Priority (explicit, tested):
    0. machine-declared contract in request metadata          -> JSON_SCHEMA (the only metadata form supported in V1)
    1. explicit exact literal   ("Reply exactly: <literal>")   -> EXACT_TEXT
    2. safe pure arithmetic expression                          -> DETERMINISTIC_MATH
    3. explicit requested JSON value ("Return valid JSON: <v>") -> JSON_LITERAL
    4. explicit schema requirement ("... matching this schema:")-> JSON_SCHEMA
    5. everything else                                          -> FREE_TEXT
The whole message must BE the directive: a directive buried in ordinary conversation, vague wording, quote-wrapped or fenced literals and ambiguous framing are never routed
deterministically (they stay FREE_TEXT, or fail closed as INVALID_CONTRACT when a strict contract is unmistakably declared but cannot be honoured). Nothing here
depends on a model name, a prompt id or any benchmark string.
"""
from __future__ import annotations

import re

from . import arith
from .jsonutil import MAX_JSON_CHARS, StrictJSONError, canonical_dumps, strict_loads
from .schema import check_schema
from .types import ContractSpec, ContractType, sha256_text

MAX_EXACT_LITERAL_CHARS = 2000

_EXACT = re.compile(r"^\s*(?:please\s+)?(?:reply|respond|answer|output|print|say|write)\s+(?:with\s+)?(?:exactly|verbatim)(?:\s+(?:the\s+following(?:\s+text)?|this(?:\s+text)?|the\s+text|the\s+word))?\s*:(?P<rest>[\s\S]*)$", re.IGNORECASE)
_JSON_LIT = re.compile(r"^\s*(?:please\s+)?(?:return|respond\s+with|reply\s+with|output|produce)\s+(?:only\s+)?(?:this\s+|the\s+following\s+)?(?:valid\s+)?json\s*:(?P<rest>[\s\S]*)$", re.IGNORECASE)
_SCHEMA = re.compile(r"^\s*(?:please\s+)?(?:return|respond|reply|output|produce)\s+(?:only\s+)?(?:with\s+)?(?:valid\s+)?json\s+(?:that\s+)?(?:matching|matches|conforming\s+to|conforms\s+to|following|validating\s+against)\s+(?:this|the\s+following)\s+(?:json\s+)?schema\s*:(?P<rest>[\s\S]*)$", re.IGNORECASE)
_MATH_LEAD = re.compile(r"^\s*(?:please\s+)?(?:(?:calculate|compute|evaluate|solve)|what(?:'s|\s+is))\s+", re.IGNORECASE)
_MATH_TRAIL = re.compile(r"\s*(?:=\s*)?\??\s*$")
_ARITH_CHARS = re.compile(r"^[0-9.\s+\-*/()]+$")
_QUOTE_PAIRS = (("\"", "\""), ("'", "'"), ("`", "`"), ("“", "”"), ("‘", "’"))


def _spec(t: ContractType, basis: str, src: str, **kw) -> ContractSpec:
    return ContractSpec(contract_type=t, detection_basis=basis, source_sha256=sha256_text(src), **kw)


def free_text(src: str, basis: str = "no strict contract detected") -> ContractSpec:
    return _spec(ContractType.FREE_TEXT, basis, src)


def detect_exact_text(text: str) -> ContractSpec | None:
    m = _EXACT.match(text)
    if not m:
        return None
    rest = m.group("rest")
    # exactly one leading separator (a single newline or a single space/tab) and at most one trailing newline are framing, everything else is the literal
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest[:1] in ("\n", " ", "\t"):
        rest = rest[1:]
    if rest.endswith("\r\n"):
        rest = rest[:-2]
    elif rest.endswith("\n"):
        rest = rest[:-1]
    basis = "explicit exact-literal directive at the start of the message"
    if rest.strip() == "":
        return _spec(ContractType.EXACT_TEXT, basis, text, invalid_reason="the exact literal is empty or whitespace-only")
    if len(rest) > MAX_EXACT_LITERAL_CHARS:
        return _spec(ContractType.EXACT_TEXT, basis, text, invalid_reason=f"the exact literal exceeds {MAX_EXACT_LITERAL_CHARS} characters")
    if any(ord(c) < 32 and c not in "\n\t\r" for c in rest) or "\x7f" in rest:
        return _spec(ContractType.EXACT_TEXT, basis, text, invalid_reason="the exact literal contains control characters")
    stripped = rest.strip()
    if len(stripped) >= 2 and any(stripped[0] == a and stripped[-1] == b for a, b in _QUOTE_PAIRS):
        return free_text(text, "quote-wrapped literal is ambiguous (quotes may or may not belong to the answer); not routed deterministically")
    return _spec(ContractType.EXACT_TEXT, basis, text, literal=rest)


def detect_math(text: str) -> ContractSpec | None:
    core, lead = text, _MATH_LEAD.match(text)
    if lead:
        core = text[lead.end():]
    core = _MATH_TRAIL.sub("", core, count=1).strip()                    # optional trailing '=' and/or '?'
    if not core or not _ARITH_CHARS.match(core) or not re.search(r"[0-9]", core) or not re.search(r"[-+*/]", core):
        return None
    if not lead and re.search(r"[0-9)](?:-|/)[0-9(]", core):            # tight 'a-b' / 'a/b' without a verb is ambiguous (ranges, dates, phone numbers): not routed
        return None
    basis = "the whole message is a pure arithmetic expression" + (" with an explicit calculate/what-is lead-in" if lead else "")
    try:
        _v, ops = arith.evaluate(core)
    except arith.ArithmeticDomainError:
        return _spec(ContractType.DETERMINISTIC_MATH, basis, text, expression=core)      # well formed, no value (division by zero): UNSATISFIABLE at execution
    except arith.ArithmeticSizeError as e:
        return _spec(ContractType.DETERMINISTIC_MATH, basis, text, invalid_reason=f"arithmetic expression exceeds the supported size/nesting ({e})")
    except arith.ArithmeticSyntaxError:
        return None                                                     # looks arithmetic-ish but is not a valid expression: leave it to normal conversation
    if ops < 1:
        return None
    return _spec(ContractType.DETERMINISTIC_MATH, basis, text, expression=core)


def detect_json_literal(text: str) -> ContractSpec | None:
    m = _JSON_LIT.match(text)
    if not m:
        return None
    rest = m.group("rest").strip()
    basis = "explicit requested JSON value after a 'return valid JSON:' directive"
    if rest == "":
        return None
    if rest.startswith("```"):
        return free_text(text, "a Markdown-fenced JSON literal is ambiguous framing; not routed deterministically")
    looks_json = rest[0] in '{["-0123456789' or rest.startswith(("true", "false", "null"))
    if not looks_json:
        return None
    if len(rest) > MAX_JSON_CHARS:
        return _spec(ContractType.JSON_LITERAL, basis, text, invalid_reason=f"the JSON literal exceeds {MAX_JSON_CHARS} characters")
    try:
        value = strict_loads(rest)
    except StrictJSONError as e:
        if rest[0] in "{[":                                             # an object/array literal was clearly intended but cannot be honoured: fail closed
            return _spec(ContractType.JSON_LITERAL, basis, text, invalid_reason=f"the supplied JSON literal is malformed or ambiguous: {e}")
        return None
    return _spec(ContractType.JSON_LITERAL, basis, text, expected_json=canonical_dumps(value))


def detect_json_schema(text: str, metadata: dict | None = None) -> ContractSpec | None:
    decl = (metadata or {}).get("response_contract") if isinstance(metadata, dict) else None
    if isinstance(decl, dict) and decl.get("type") == "json_schema":
        schema = decl.get("schema")
        reason = check_schema(schema)
        if reason:
            return _spec(ContractType.JSON_SCHEMA, "machine-declared response_contract in request metadata", text, invalid_reason=f"unsupported or invalid schema: {reason}", declared_by="REQUEST_METADATA")
        return _spec(ContractType.JSON_SCHEMA, "machine-declared response_contract in request metadata", text, schema_json=canonical_dumps(schema), declared_by="REQUEST_METADATA")
    m = _SCHEMA.match(text)
    if not m:
        return None
    rest = m.group("rest").strip()
    basis = "explicit 'JSON matching this schema:' directive"
    try:
        schema = strict_loads(rest)
    except StrictJSONError as e:
        return _spec(ContractType.JSON_SCHEMA, basis, text, invalid_reason=f"the supplied schema is not valid JSON: {e}")
    reason = check_schema(schema)
    if reason:
        return _spec(ContractType.JSON_SCHEMA, basis, text, invalid_reason=f"unsupported or invalid schema: {reason}")
    return _spec(ContractType.JSON_SCHEMA, basis, text, schema_json=canonical_dumps(schema))


def route(text: str, metadata: dict | None = None) -> ContractSpec:
    """The ONE deterministic router. Pure: same input, same contract."""
    if not isinstance(text, str):
        return free_text(str(text), "non-text request")
    declared = detect_json_schema(text, metadata) if isinstance(metadata, dict) and metadata.get("response_contract") else None
    if declared is not None:
        return declared
    for fn in (detect_exact_text, detect_math, detect_json_literal):
        spec = fn(text)
        if spec is not None:
            return spec
    spec = detect_json_schema(text, None)
    return spec if spec is not None else free_text(text)
