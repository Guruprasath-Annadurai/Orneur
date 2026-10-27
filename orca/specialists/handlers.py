"""Ten distinct specialist handlers. None of these invent live sources or execute untrusted code."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from orca.specialists.contracts import SpecialistError, SpecialistResult
from orca.sovereign_mission.store import digest

_SECRET = re.compile(
    r"(AKIA[0-9A-Z]{16})|(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)|"
    r"(sk-[A-Za-z0-9]{20,})|(ghp_[A-Za-z0-9]{20,})"
)
_SSRF_HOSTS = frozenset({"169.254.169.254", "metadata.google.internal", "localhost", "127.0.0.1", "0.0.0.0"})
_SQLI = re.compile(r"(?i)(\bunion\b.+\bselect\b)|(\bor\b\s+1\s*=\s*1)|(;--)|(\bdrop\s+table\b)")
_STOP = frozenset({"the", "a", "an", "of", "and", "or", "to", "in", "for", "on", "is", "it"})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _result(role: str, tenant_id: str, status: str, output: dict, *, synthetic: bool = False, error: str | None = None) -> SpecialistResult:
    fingerprint = digest({"role": role, "output": output, "status": status})
    return SpecialistResult(
        role=role,
        status=status,
        output=output,
        evidence={
            "role": role,
            "tenant_id": tenant_id,
            "at": _now(),
            "output_sha256": fingerprint,
            "status": status,
        },
        tenant_id=tenant_id,
        synthetic=synthetic,
        error=error,
    )


def _tenant(payload: dict) -> str:
    tenant = payload.get("tenant_id")
    if not isinstance(tenant, str) or not tenant.strip():
        raise SpecialistError("tenant_required")
    return tenant


def research_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise SpecialistError("query_refused")
    parts = [p.strip() for p in re.split(r"[?;]| and then | then ", query) if p.strip()]
    subquestions = parts if len(parts) > 1 else [query.strip()]
    fixtures = payload.get("sources") or []
    if not fixtures:
        return _result(
            "research",
            tenant,
            "unavailable",
            {
                "subquestions": subquestions,
                "sources": [],
                "disagreements": [],
                "provider": None,
                "reason": "no_authorized_search_provider",
                "invented_sources": False,
            },
        )
    seen: set[str] = set()
    labeled = []
    for source in fixtures:
        if source.get("tenant_id") not in (None, tenant):
            continue
        locator = str(source.get("locator") or source.get("url") or source.get("id") or "")
        if locator in seen:
            continue
        seen.add(locator)
        labeled.append(
            {
                "locator": locator,
                "excerpt": source.get("excerpt") or source.get("text") or "",
                "freshness": source.get("freshness"),
                "synthetic": True,
                "kind": "fixture",
            }
        )
    disagreements = []
    texts = [row["excerpt"] for row in labeled if row["excerpt"]]
    if len(texts) >= 2 and texts[0] and texts[1] and texts[0] != texts[1]:
        disagreements.append({"a": labeled[0]["locator"], "b": labeled[1]["locator"], "kind": "excerpt_mismatch"})
    return _result(
        "research",
        tenant,
        "fixture_only",
        {
            "subquestions": subquestions,
            "sources": labeled,
            "disagreements": disagreements,
            "provider": None,
            "invented_sources": False,
        },
        synthetic=True,
    )


def planning_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise SpecialistError("plan_refused")
    ids = []
    deps: dict[str, set[str]] = {}
    for raw in tasks:
        task_id = str(raw.get("id") or "").strip()
        if not task_id or task_id in deps:
            raise SpecialistError("plan_refused")
        ids.append(task_id)
        deps[task_id] = {str(d) for d in raw.get("depends_on") or []}
    unknown = {dep for needed in deps.values() for dep in needed if dep not in deps}
    if unknown:
        raise SpecialistError("unknown_dependency")
    ordered: list[str] = []
    remaining = set(ids)
    while remaining:
        ready = [task_id for task_id in ids if task_id in remaining and deps[task_id].isdisjoint(remaining)]
        if not ready:
            raise SpecialistError("cycle_refused")
        pick = ready[0]
        ordered.append(pick)
        remaining.remove(pick)
    return _result("planning", tenant, "completed", {"order": ordered, "task_count": len(ordered)})


def coding_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        raise SpecialistError("source_refused")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return _result("coding", tenant, "failed", {"error": "syntax_error", "lineno": exc.lineno})
    functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    dangerous = sorted({name for name in calls if name in {"eval", "exec", "compile", "__import__"}})
    status = "refused" if dangerous else "completed"
    return _result(
        "coding",
        tenant,
        status,
        {
            "functions": functions,
            "classes": classes,
            "dangerous_calls": dangerous,
            "executed": False,
            "lines": source.count("\n") + 1,
        },
        error="unsafe_construct" if dangerous else None,
    )


def data_analysis_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    rows = payload.get("rows")
    column = payload.get("column")
    if not isinstance(rows, list) or not rows or not isinstance(column, str):
        raise SpecialistError("table_refused")
    values = []
    missing = 0
    for row in rows:
        if not isinstance(row, dict) or column not in row or row[column] is None:
            missing += 1
            continue
        try:
            values.append(float(row[column]))
        except (TypeError, ValueError):
            missing += 1
    if not values:
        raise SpecialistError("numeric_refused")
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    outliers = [value for value in values if stdev and abs(value - mean) > 3 * stdev]
    return _result(
        "data_analysis",
        tenant,
        "completed",
        {
            "n": len(values),
            "missing": missing,
            "mean": mean,
            "median": statistics.median(values),
            "stdev": stdev,
            "min": min(values),
            "max": max(values),
            "outliers": outliers,
        },
    )


def retrieval_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    query = payload.get("query")
    documents = payload.get("documents") or []
    if not isinstance(query, str) or not query.strip():
        raise SpecialistError("query_refused")
    terms = [tok for tok in re.findall(r"[a-z0-9]+", query.lower()) if tok not in _STOP]
    ranked = []
    for doc in documents:
        if doc.get("tenant_id") not in (None, tenant):
            continue
        text = str(doc.get("text") or "")
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        counts = Counter(tokens)
        score = sum(counts[term] for term in terms)
        if score <= 0:
            continue
        loc = int(doc.get("locator") or 0)
        excerpt = text[:240]
        ranked.append(
            {
                "doc_id": doc.get("doc_id"),
                "locator": loc,
                "score": score,
                "excerpt": excerpt,
                "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                "synthetic": bool(doc.get("synthetic")),
            }
        )
    ranked.sort(key=lambda row: (-row["score"], str(row["doc_id"])))
    return _result(
        "retrieval",
        tenant,
        "completed" if ranked else "empty",
        {"citations": ranked[:8], "query_terms": terms},
        synthetic=any(row["synthetic"] for row in ranked),
    )


def evidence_verification_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    records = payload.get("records") or []
    mismatches = []
    intact = []
    for item in records:
        record = item.get("record")
        claimed = item.get("record_sha256")
        if not isinstance(record, dict) or not isinstance(claimed, str):
            mismatches.append({"error": "shape_refused"})
            continue
        computed = digest(record)
        row = {"computed": computed, "claimed": claimed, "match": computed == claimed}
        (intact if row["match"] else mismatches).append(row)
    status = "verified" if intact and not mismatches else "unverified"
    return _result(
        "evidence_verification",
        tenant,
        status,
        {"intact": len(intact), "mismatches": mismatches, "witness": "local_recompute"},
    )


def security_analysis_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    blob = payload.get("text")
    if not isinstance(blob, str):
        raise SpecialistError("text_refused")
    findings = []
    for match in _SECRET.finditer(blob):
        findings.append({"kind": "secret", "span": match.span()})
    for match in _SQLI.finditer(blob):
        findings.append({"kind": "sqli_pattern", "span": match.span()})
    for url in re.findall(r"https?://[^\s]+", blob):
        host = (urlsplit(url).hostname or "").lower()
        if host in _SSRF_HOSTS or host.endswith(".internal"):
            findings.append({"kind": "ssrf_host", "host": host})
    return _result(
        "security_analysis",
        tenant,
        "completed",
        {"findings": findings, "secret_count": sum(1 for f in findings if f["kind"] == "secret")},
    )


def documentation_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        raise SpecialistError("source_refused")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        raise SpecialistError("syntax_error") from None
    pages = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            args = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [arg.arg for arg in node.args.args]
            pages.append(
                {
                    "name": node.name,
                    "kind": type(node).__name__,
                    "args": args,
                    "doc": ast.get_docstring(node) or "",
                }
            )
    return _result("documentation", tenant, "completed", {"pages": pages, "count": len(pages)})


def tool_execution_handler(payload: dict) -> SpecialistResult:
    tenant = _tenant(payload)
    tool = payload.get("tool")
    body = payload.get("input")
    allowed = {"sha256", "canonical_json", "token_count"}
    if tool not in allowed:
        raise SpecialistError("tool_refused")
    if tool == "sha256":
        if not isinstance(body, (str, bytes)):
            raise SpecialistError("input_refused")
        data = body.encode() if isinstance(body, str) else body
        output = {"digest": hashlib.sha256(data).hexdigest(), "nbytes": len(data)}
    elif tool == "canonical_json":
        if not isinstance(body, dict):
            raise SpecialistError("input_refused")
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
        output = {"canonical": encoded, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}
    else:
        text = body if isinstance(body, str) else json.dumps(body)
        output = {"tokens": len(re.findall(r"\S+", text))}
    return _result("tool_execution", tenant, "completed", {"tool": tool, "result": output, "network": False, "fs": False})


def mission_coordination_handler(payload: dict) -> SpecialistResult:
    """Inspect a mission snapshot. Does not dispatch SovereignMission or emit effects."""
    tenant = _tenant(payload)
    snapshot = payload.get("mission")
    if not isinstance(snapshot, dict):
        raise SpecialistError("mission_refused")
    owner = snapshot.get("owner_user_id") or snapshot.get("tenant_id")
    if owner is not None and owner != tenant:
        raise SpecialistError("access_denied")
    state = snapshot.get("state")
    from orca.sovereign_mission import states as mission_states

    terminal = state in {
        mission_states.COMPLETED_VERIFIED,
        mission_states.COMPLETED_UNVERIFIED,
        mission_states.FAILED,
        mission_states.CANCELLED,
        mission_states.REVOKED,
        mission_states.OUTCOME_UNKNOWN,
        mission_states.INTERRUPTED_UNKNOWN,
    }
    unknown = state in {mission_states.OUTCOME_UNKNOWN, mission_states.INTERRUPTED_UNKNOWN}
    claim = snapshot.get("claim")
    if unknown and claim in {"verified", "COMPLETED_VERIFIED"}:
        status = "refused"
        note = "unknown_cannot_be_verified"
    else:
        status = "completed"
        note = "inspect_only"
    return _result(
        "mission_coordination",
        tenant,
        status,
        {
            "state": state,
            "terminal": terminal,
            "unknown": unknown,
            "dispatched": False,
            "note": note,
            "steps": len(snapshot.get("steps") or []),
        },
        error=None if status == "completed" else note,
    )


HANDLERS: dict[str, Callable[[dict[str, Any]], SpecialistResult]] = {
    "research": research_handler,
    "planning": planning_handler,
    "coding": coding_handler,
    "data_analysis": data_analysis_handler,
    "retrieval": retrieval_handler,
    "evidence_verification": evidence_verification_handler,
    "security_analysis": security_analysis_handler,
    "documentation": documentation_handler,
    "tool_execution": tool_execution_handler,
    "mission_coordination": mission_coordination_handler,
}
