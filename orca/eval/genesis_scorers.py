"""Deterministic per-item scorers for Genesis Capability Eval V1 (no model, no network, no code execution).

Every scorer returns {"status": SCORED|PENDING_SANDBOX|UNSCORABLE, "score": float in [0,1] or None, "detail": {...}}.
A missing response is never scored 0 by a scorer: the harness marks it MISSING (fail closed). A present-but-wrong response scores 0.
Code items are NEVER executed here: they need an injected sandbox executor that satisfies the SandboxExecutor protocol.
"""
from __future__ import annotations

import json
import re
import unicodedata
from fractions import Fraction
from typing import Any, Mapping, Protocol

from orca.contracts.jsonutil import canonical_dumps, strict_equal, strict_loads
from orca.contracts.schema import check_schema, validate
from orca.eval.genesis.gen_format import check_constraint

_ANSWER = re.compile(r"^ANSWER:[ \t]*(.*?)[ \t]*$", re.M)
_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.S)


def _res(score: float | None, status: str = "SCORED", **detail: Any) -> dict:
    return {"status": status, "score": score, "detail": detail}


def extract_answer(text: str) -> str | None:
    m = _ANSWER.findall(text or "")
    return m[-1] if m else None


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s).strip().strip("`*\"'").strip()
    s = re.sub(r"\s+", " ", s)
    if s.endswith(".") and not re.search(r"\d\.$", s):
        s = s[:-1]
    return s.casefold()


def _to_fraction(s: str) -> Fraction | None:
    s = s.strip().replace(",", "") if re.fullmatch(r"[+-]?\d{1,3}(,\d{3})+(\.\d+)?", s.strip()) else s.strip()
    try:
        if re.fullmatch(r"[+-]?\d+/\d+", s):
            return Fraction(s)
        if re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
            return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None
    return None


def score_answer_line(gt: Mapping[str, Any], response: str) -> dict:
    ans = extract_answer(response)
    if ans is None:
        return _res(0.0, reason="no_answer_line")
    mode = gt.get("match", "text")
    if mode == "any_of":
        ok = _norm_text(ans) in {_norm_text(a) for a in gt["accepted"]}
    elif mode == "numeric":
        g, r = _to_fraction(str(gt["answer"])), _to_fraction(ans)
        tol = Fraction(1, 200) if "." in str(gt["answer"]) else Fraction(0)
        ok = g is not None and r is not None and abs(g - r) <= tol
    elif mode == "set":
        ok = sorted(x.strip() for x in ans.split(",") if x.strip()) == sorted(x.strip() for x in str(gt["answer"]).split(",") if x.strip())
    else:
        ok = _norm_text(ans) == _norm_text(str(gt["answer"]))
    return _res(1.0 if ok else 0.0, extracted=ans)


def score_if(gt: Mapping[str, Any], response: str) -> dict:
    per = [bool(check_constraint(c, response)) for c in gt["constraints"]]
    return _res(1.0 if all(per) else 0.0, per_constraint=per)


def lenient_json(text: str) -> tuple[Any, bool]:
    """(value, raw_clean). Accepts bare JSON or exactly one fenced block; anything else raises ValueError. raw_clean is False if a fence was needed."""
    t = text.strip()
    clean = True
    m = _FENCE.match(t)
    if m:
        t, clean = m.group(1), False
    return strict_loads(t), clean


def score_contract_raw(gt: Mapping[str, Any], response: str) -> dict:
    if gt["contract_type"] == "JSON_SCHEMA":
        return score_json_fields(gt, response, strict_format=True)
    exp = gt["expected_output"]
    if response == exp:
        return _res(1.0, raw_satisfied=True, recoverable=False)
    stripped = response.strip()
    fenced = _FENCE.match(stripped)
    rec = stripped == exp or (fenced is not None and fenced.group(1).strip() == exp)
    return _res(0.0, raw_satisfied=False, recoverable=bool(rec))


def score_json_fields(gt: Mapping[str, Any], response: str, strict_format: bool = False) -> dict:
    try:
        val, clean = lenient_json(response)
    except Exception:
        return _res(0.0, valid_json=False)
    if strict_format and not clean:
        return _res(0.0, valid_json=True, raw_format_clean=False)
    schema = gt["schema"]
    assert check_schema(schema) is None
    errs = validate(val, schema)
    ok = not errs and strict_equal(val, gt["expected_object"])
    return _res(1.0 if ok else 0.0, valid_json=True, schema_valid=not errs, raw_format_clean=clean, schema_errors=errs[:3])


def score_tool_call(gt: Mapping[str, Any], response: str) -> dict:
    try:
        val, clean = lenient_json(response)
    except Exception:
        return _res(0.0, valid_json=False)
    if not isinstance(val, dict) or "tool" not in val:
        return _res(0.0, reason="malformed")
    if gt["tool"] is None:
        return _res(1.0 if val.get("tool") is None else 0.0, raw_format_clean=clean)
    ok = val.get("tool") == gt["tool"] and strict_equal(val.get("arguments"), gt["arguments"])
    return _res(1.0 if ok else 0.0, raw_format_clean=clean)


def score_answer_citations(gt: Mapping[str, Any], response: str) -> dict:
    try:
        val, clean = lenient_json(response)
    except Exception:
        return _res(0.0, valid_json=False)
    if not isinstance(val, dict) or not isinstance(val.get("citations"), list):
        return _res(0.0, reason="malformed")
    a_ok = isinstance(val.get("answer"), str) and _norm_text(val["answer"]) == _norm_text(gt["answer"])
    c_ok = sorted(map(str, val["citations"])) == sorted(gt["citations"])
    return _res(1.0 if a_ok and c_ok else 0.0, answer_correct=a_ok, citations_exact=c_ok)


def score_answer_evidence(gt: Mapping[str, Any], response: str) -> dict:
    try:
        val, clean = lenient_json(response)
    except Exception:
        return _res(0.0, valid_json=False)
    if not isinstance(val, dict) or not isinstance(val.get("evidence"), list):
        return _res(0.0, reason="malformed")
    a_ok = isinstance(val.get("answer"), str) and _norm_text(val["answer"]) == _norm_text(gt["answer"])
    e_ok = sorted(map(str, val["evidence"])) == sorted(gt["evidence"])
    c_ok = val.get("conflict") is gt["conflict"]
    return _res(1.0 if a_ok and e_ok and c_ok else 0.0, answer_correct=a_ok, evidence_exact=e_ok, conflict_correct=c_ok,
                abstained_correctly=(gt["answer"] == "INSUFFICIENT" and a_ok))


def score_discovery(gt: Mapping[str, Any], response: str, item_input: Mapping[str, Any]) -> dict:
    """Anchor-based, judge-free. Precision/recall/decoy rate and per-dimension diagnostics; the item score is F1."""
    try:
        val, clean = lenient_json(response)
    except Exception:
        return _res(0.0, valid_json=False)
    cands = val.get("discoveries") if isinstance(val, dict) else None
    if not isinstance(cands, list):
        return _res(0.0, reason="malformed")
    valid_ids = set(item_input.get("document_ids", []))
    gold, decoys = gt["valid_discoveries"], gt["decoys"]
    matched: set[int] = set()
    decoy_hits = 0
    dims = {"evidence_quality": [], "counter_evidence_awareness": [], "actionability": [], "falsifiability": []}
    emitted = 0
    for c in cands:
        if not isinstance(c, dict):
            continue
        emitted += 1
        ev = {str(x) for x in c.get("evidence", []) if isinstance(c.get("evidence", []), list)}
        typ = c.get("type")
        hit = None
        for gi, g in enumerate(gold):
            if gi not in matched and typ == g["type"] and set(g["anchors"]) <= ev:
                hit = gi
                break
        if hit is not None:
            matched.add(hit)
            g = gold[hit]
            dims["evidence_quality"].append(1.0 if ev <= valid_ids and ev <= set(g["anchors"]) | set(g["counter"]) else 0.5 if ev <= valid_ids else 0.0)
            dims["counter_evidence_awareness"].append(1.0 if (not g["counter"] or set(g["counter"]) <= ev) else 0.0)
            act, fal = str(c.get("suggested_action", "")).casefold(), str(c.get("falsification_condition", "")).casefold()
            dims["actionability"].append(1.0 if any(k in act for k in g["action"]) else 0.0)
            dims["falsifiability"].append(1.0 if any(k in fal for k in g["falsifier"]) else 0.0)
        elif any(typ == d["type"] and set(d["anchors"]) <= ev for d in decoys):
            decoy_hits += 1
    recall = len(matched) / len(gold) if gold else 1.0
    precision = len(matched) / emitted if emitted else (1.0 if not gold else 0.0)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    mean = lambda xs: (sum(xs) / len(xs)) if xs else None
    return _res(f1, precision=precision, recall=recall, decoy_hits=decoy_hits, emitted=emitted,
                dimensions={k: mean(v) for k, v in dims.items()},
                importance=[gold[i]["importance"] for i in sorted(matched)], non_obvious=[gold[i]["why"] for i in sorted(matched)])


class SandboxExecutor(Protocol):
    """Future hermetic executor (see genesis_sandbox.SANDBOX_REQUIREMENTS). NOT implemented in this phase."""

    def run_tests(self, code: str, function_name: str, tests: list[dict]) -> dict: ...


def score_code(gt: Mapping[str, Any], response: str, sandbox: SandboxExecutor | None) -> dict:
    if sandbox is None:
        return _res(None, status="PENDING_SANDBOX", reason="hermetic sandbox executor not configured; candidate code is never executed here")
    code = response.strip()
    m = _FENCE.match(code)
    if m:
        code = m.group(1)
    out = sandbox.run_tests(code, gt["function_name"], gt["tests"])
    passed, total = int(out["passed"]), int(out["total"])
    return _res(1.0 if total > 0 and passed == total else 0.0, passed=passed, total=total, evidence=out.get("evidence"))


def score_item(item: Mapping[str, Any], response: str, sandbox: SandboxExecutor | None = None) -> dict:
    gt, m = item["ground_truth"], item["scoring_method"]
    if m == "answer_line":
        return score_answer_line(gt, response)
    if m == "if_constraints":
        return score_if(gt, response)
    if m == "contract_raw":
        return score_contract_raw(gt, response)
    if m == "json_fields":
        return score_json_fields(gt, response)
    if m == "tool_call":
        return score_tool_call(gt, response)
    if m == "answer_citations":
        return score_answer_citations(gt, response)
    if m == "answer_evidence":
        return score_answer_evidence(gt, response)
    if m == "discovery_anchor":
        return score_discovery(gt, response, item["input"])
    if m == "code_tests":
        return score_code(gt, response, sandbox)
    if m == "measurement":
        return _res(None, status="UNSCORABLE", reason="measurement protocol item")
    raise ValueError(f"unknown scoring_method {m}")
