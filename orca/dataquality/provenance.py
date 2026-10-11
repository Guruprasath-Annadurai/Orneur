"""(2) Provenance + licensing validator. FAIL CLOSED: a record passes only if it resolves to a registered source id carrying a known license/terms id,
a generator kind (human / model+revision / program), a creation-code SHA and a content digest. Missing or unknown => violation.

Provenance block (per record under ``provenance``; a dataset-level default may be supplied for records that omit it)::

    {"source_id": "...", "license_id": "...",
     "generator": {"kind": "human"} | {"kind": "model", "model_id": "...", "model_revision": "..."} | {"kind": "program", "program": "..."},
     "creation_code_sha": "<40 or 64 hex>", "digest": "<sha256 of canonical record without 'provenance'>"}

When a record carries its own ``digest`` it must equal the recomputed one (tamper evidence). When it is absent (dataset-level default) the tool
computes it, so the digest is resolved but self-asserted by the tool rather than by the producer; the report says how many were computed.

Source registry (``sources``)::

    {"schema_version": "orneur-source-registry/1", "licenses": ["CC0-1.0", ...],
     "sources": [{"source_id": "...", "license_id": "...", "terms_id": null|"...", "description": "..."}]}
"""
from __future__ import annotations

import re

from orca.dataquality import FAIL, PASS
from orca.dataquality._common import digest_of

SOURCE_REGISTRY_SCHEMA = "orneur-source-registry/1"
UNKNOWN_LICENSES = frozenset({"", "unknown", "unspecified", "none", "tbd", "n/a", "unlicensed"})
_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
KINDS = ("human", "model", "program")


def validate_source_registry(reg) -> list:
    errs: list = []
    if not isinstance(reg, dict) or reg.get("schema_version") != SOURCE_REGISTRY_SCHEMA:
        return [f"source registry schema_version must be {SOURCE_REGISTRY_SCHEMA!r}"]
    lic = reg.get("licenses")
    if not isinstance(lic, list) or not all(isinstance(x, str) and x.strip().lower() not in UNKNOWN_LICENSES for x in lic):
        errs.append("licenses must be a list of known (non-placeholder) license ids")
        lic = []
    seen = set()
    srcs = reg.get("sources")
    if not isinstance(srcs, list):
        return errs + ["sources must be a list"]
    for i, s in enumerate(srcs):
        if not isinstance(s, dict) or not isinstance(s.get("source_id"), str) or not s["source_id"].strip():
            errs.append(f"sources[{i}].source_id missing")
            continue
        if s["source_id"] in seen:
            errs.append(f"duplicate source_id {s['source_id']!r}")
        seen.add(s["source_id"])
        if s.get("license_id") not in lic:
            errs.append(f"sources[{i}] ({s['source_id']}) license_id is missing/unknown or not in licenses[]")
    return errs


def record_digest(obj: dict) -> str:
    return digest_of({k: v for k, v in obj.items() if k != "provenance"})


def _v(line, code, msg):
    return {"line": line, "code": code, "message": msg}


def validate_provenance_block(line: int, prov, registry_sources: dict, out: list) -> None:
    if not isinstance(prov, dict):
        out.append(_v(line, "provenance_missing", "no provenance block"))
        return
    sid = prov.get("source_id")
    if not isinstance(sid, str) or not sid.strip():
        out.append(_v(line, "source_id_missing", "provenance.source_id missing"))
    elif sid not in registry_sources:
        out.append(_v(line, "source_id_unresolved", "source_id is not in the source registry"))
    else:
        reg_lic = registry_sources[sid].get("license_id")
        rec_lic = prov.get("license_id")
        if not isinstance(rec_lic, str) or rec_lic.strip().lower() in UNKNOWN_LICENSES:
            out.append(_v(line, "license_missing_or_unknown", "provenance.license_id missing or a placeholder"))
        elif rec_lic != reg_lic:
            out.append(_v(line, "license_conflicts_with_registry", "record license_id differs from the source registry"))
    gen = prov.get("generator")
    if not isinstance(gen, dict) or gen.get("kind") not in KINDS:
        out.append(_v(line, "generator_kind_missing_or_unknown", f"generator.kind must be one of {KINDS}"))
    elif gen["kind"] == "model":
        for f in ("model_id", "model_revision"):
            if not isinstance(gen.get(f), str) or not gen[f].strip():
                out.append(_v(line, "generator_model_incomplete", f"model generator needs {f}"))
    elif gen["kind"] == "program" and (not isinstance(gen.get("program"), str) or not gen["program"].strip()):
        out.append(_v(line, "generator_program_incomplete", "program generator needs 'program'"))
    sha = prov.get("creation_code_sha")
    if not isinstance(sha, str) or not _SHA.match(sha):
        out.append(_v(line, "creation_code_sha_missing_or_malformed", "creation_code_sha must be 40 or 64 lowercase hex chars"))
    d = prov.get("digest")
    if d is not None and (not isinstance(d, str) or not _SHA256.match(d)):
        out.append(_v(line, "digest_malformed", "provenance.digest must be sha256 hex"))


def check_provenance(lines: list, source_registry, *, default_provenance=None) -> dict:
    viol: list = []
    reg_problems = validate_source_registry(source_registry) if source_registry is not None else ["no source registry supplied"]
    sources = {s["source_id"]: s for s in (source_registry or {}).get("sources", []) if isinstance(s, dict) and "source_id" in s} if not reg_problems else {}
    resolved = computed = 0
    for l in lines:
        if l.error is not None or not isinstance(l.obj, dict):
            viol.append(_v(l.line, "unparseable_record", "record did not parse"))
            continue
        prov = l.obj.get("provenance", default_provenance)
        n0 = len(viol)
        if reg_problems:
            viol.append(_v(l.line, "source_registry_invalid", "source registry missing or invalid"))
            continue
        validate_provenance_block(l.line, prov, sources, viol)
        if isinstance(prov, dict):
            actual = record_digest(l.obj)
            if prov.get("digest") is None:
                computed += 1
            elif prov["digest"] != actual:
                viol.append(_v(l.line, "digest_mismatch", "provenance.digest does not match the record content"))
        resolved += len(viol) == n0
    by_code: dict = {}
    for v in viol:
        by_code[v["code"]] = by_code.get(v["code"], 0) + 1
    return {
        "check": "provenance", "status": PASS if (lines and not viol and not reg_problems) else FAIL,
        "records_total": len(lines), "records_resolved": resolved, "records_unresolved": len(lines) - resolved,
        "digests_computed_by_tool": computed, "default_provenance_applied": default_provenance is not None,
        "source_registry_problems": reg_problems, "violation_count": len(viol), "violations_by_code": dict(sorted(by_code.items())),
        "violations": viol[:1000], "violations_truncated": len(viol) > 1000,
    }
