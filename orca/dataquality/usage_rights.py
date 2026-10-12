"""(1)/(7) Source-manifest validation and per-record usage-rights check. FAIL CLOSED: nothing is assumed permissive.

Extends the source registry shape of ``orca.dataquality.provenance`` (which is left unchanged) with a recorded usage-rights entry per source::

    {"source_id": "...", "license_id": "...", "terms_id": "<id of the recorded terms/licence review>",
     "usage_rights": {"permitted_uses": ["training", "evaluation", ...], "restrictions": ["no-redistribution", ...]}}

A source with no ``terms_id`` or no ``usage_rights`` is invalid, so every record resolving to it fails. A use is allowed only when it is listed in
``permitted_uses`` and no ``no-<use>`` restriction is recorded. The tool records what the manifest says; it asserts no legal conclusion.
"""
from __future__ import annotations

from orca.dataquality import FAIL, PASS
from orca.dataquality.provenance import SOURCE_REGISTRY_SCHEMA, validate_source_registry

USES = ("training", "evaluation", "redistribution", "commercial_use")
_SOURCE_KEYS = frozenset({"source_id", "license_id", "terms_id", "description", "usage_rights"})
_REGISTRY_KEYS = frozenset({"schema_version", "licenses", "sources", "description"})


def _blank(v) -> bool:
    return not (isinstance(v, str) and v.strip())


def validate_source_manifest(reg) -> list:
    """Problems with a source manifest (empty list = valid). Never raises."""
    if not isinstance(reg, dict):
        return ["source manifest is not an object"]
    errs = list(validate_source_registry(reg))
    if reg.get("schema_version") != SOURCE_REGISTRY_SCHEMA:
        return errs
    extra = sorted(set(reg) - _REGISTRY_KEYS)
    if extra:
        errs.append(f"unexpected manifest keys: {extra}")
    lic = reg.get("licenses")
    if isinstance(lic, list) and len(set(lic)) != len(lic):
        errs.append("licenses contains duplicates")
    srcs = reg.get("sources")
    if isinstance(srcs, list) and not srcs:
        errs.append("sources must be a non-empty list")
    for i, s in enumerate(srcs if isinstance(srcs, list) else []):
        if not isinstance(s, dict):
            continue
        w = f"sources[{i}]"
        extra = sorted(set(s) - _SOURCE_KEYS)
        if extra:
            errs.append(f"{w}: unexpected keys {extra}")
        if _blank(s.get("terms_id")):
            errs.append(f"{w}: terms_id missing (no recorded terms review)")
        ur = s.get("usage_rights")
        if not isinstance(ur, dict):
            errs.append(f"{w}: usage_rights missing")
            continue
        pu, rs = ur.get("permitted_uses"), ur.get("restrictions")
        if not isinstance(pu, list) or not pu or not all(x in USES for x in pu) or len(set(pu)) != len(pu):
            errs.append(f"{w}: usage_rights.permitted_uses must be a non-empty list of unique values from {USES}")
        if not isinstance(rs, list) or not all(isinstance(x, str) and x for x in rs):
            errs.append(f"{w}: usage_rights.restrictions must be a list of non-empty strings")
        extra = sorted(set(ur) - {"permitted_uses", "restrictions"})
        if extra:
            errs.append(f"{w}: usage_rights unexpected keys {extra}")
    return errs


def check_source_manifest(reg) -> dict:
    problems = validate_source_manifest(reg)
    n = len(reg.get("sources", [])) if isinstance(reg, dict) and isinstance(reg.get("sources"), list) else 0
    return {"check": "source_manifest", "status": PASS if not problems else FAIL, "sources": n, "problem_count": len(problems), "problems": problems[:200]}


def _v(line, code, msg):
    return {"line": line, "code": code, "message": msg}


def check_usage_rights(lines: list, reg, *, intended_use: str = "training", default_provenance=None) -> dict:
    if intended_use not in USES:
        raise ValueError(f"intended_use must be one of {USES}")
    problems = validate_source_manifest(reg)
    sources = {s["source_id"]: s for s in reg.get("sources", []) if isinstance(s, dict) and "source_id" in s} if not problems else {}
    viol: list = []
    ok = 0
    for l in lines:
        if l.error is not None or not isinstance(l.obj, dict):
            viol.append(_v(l.line, "unparseable_record", "record did not parse"))
            continue
        if problems:
            viol.append(_v(l.line, "source_manifest_invalid", "source manifest missing or invalid; nothing is assumed permissive"))
            continue
        prov = l.obj.get("provenance", default_provenance)
        sid = prov.get("source_id") if isinstance(prov, dict) else None
        if not isinstance(prov, dict):
            viol.append(_v(l.line, "provenance_missing", "no provenance block"))
        elif sid not in sources:
            viol.append(_v(l.line, "source_id_unresolved", "source_id is not in the source manifest"))
        else:
            ur = sources[sid]["usage_rights"]
            if f"no-{intended_use}" in ur["restrictions"]:
                viol.append(_v(l.line, "use_restricted", f"source records a no-{intended_use} restriction"))
            elif intended_use not in ur["permitted_uses"]:
                viol.append(_v(l.line, "use_not_permitted", f"source does not list {intended_use} as a permitted use"))
            else:
                ok += 1
    by_code: dict = {}
    for v in viol:
        by_code[v["code"]] = by_code.get(v["code"], 0) + 1
    return {"check": "usage_rights", "status": PASS if (lines and not viol and not problems) else FAIL, "intended_use": intended_use,
            "records_total": len(lines), "records_permitted": ok, "source_manifest_problems": problems[:200], "violation_count": len(viol),
            "violations_by_code": dict(sorted(by_code.items())), "violations": viol[:1000], "violations_truncated": len(viol) > 1000}
