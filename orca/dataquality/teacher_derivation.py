"""(2) Teacher-terms-on-record check. A record derived from a model output must CARRY a teacher-terms entry that resolves, in the teacher-rights
register, to a PERMITTED_RECORDED teacher whose cited terms record matches, whose permitted uses cover the intended use, with no recorded
``no-<use>`` restriction and (for a declared model generator) a covered revision. Unknown / unrecorded terms => refused; nothing is assumed permissive.

Record shape (``teacher_terms`` at record level or inside ``provenance``)::

    {"teacher_terms": {"teacher_id": "<register id or alias>", "terms_record_id": "<register terms_record_id>"}}

Model derivation is detected from ``provenance.generator.kind == "model"`` OR any of the marker keys below (top level or inside ``provenance``), so a
record cannot dodge the check by declaring a ``human`` / ``program`` generator while carrying teacher markers. Pattern floor, not proof of absence.
The existing ``teacher_rights.gate_lines`` is unchanged; this check is stricter and additive.
"""
from __future__ import annotations

from orca.dataquality import FAIL, PASS
from orca.dataquality.teacher_rights import _find, validate_register

DEFAULT_USE = "training_data_generation"
MARKER_KEYS = ("teacher", "teacher_model", "teacher_id", "distilled_from", "distillation", "model_output", "source_model", "derived_from_model")


def _present(v) -> bool:
    return v not in (None, False, "", [], {})


def derives_from_model(obj: dict) -> bool:
    prov = obj.get("provenance")
    gen = prov.get("generator") if isinstance(prov, dict) else None
    if isinstance(gen, dict) and gen.get("kind") == "model":
        return True
    return any(_present(o.get(k)) for o in (obj, prov if isinstance(prov, dict) else {}) for k in MARKER_KEYS)


def decide(obj: dict, register: dict, intended_use: str = DEFAULT_USE, default_provenance=None) -> str | None:
    """Return a refusal reason, or None when the derived record is allowed."""
    prov = obj.get("provenance", default_provenance)
    terms = obj.get("teacher_terms") if "teacher_terms" in obj else (prov.get("teacher_terms") if isinstance(prov, dict) else None)
    if terms is None:
        return "teacher_terms_missing"
    if not (isinstance(terms, dict) and isinstance(terms.get("teacher_id"), str) and terms["teacher_id"].strip()
            and isinstance(terms.get("terms_record_id"), str) and terms["terms_record_id"].strip()):
        return "teacher_terms_malformed"
    t = _find(register, terms["teacher_id"])
    if t is None:
        return "teacher_not_in_register"
    if t["status"] != "PERMITTED_RECORDED":
        return f"teacher_status_{t['status']}"
    if terms["terms_record_id"] != t.get("terms_record_id"):
        return "terms_record_mismatch"
    gen = prov.get("generator") if isinstance(prov, dict) else None
    if isinstance(gen, dict) and gen.get("kind") == "model":
        if _find(register, gen.get("model_id")) is not t:
            return "teacher_mismatch"
        if gen.get("model_revision") not in (t.get("revisions") or []):
            return "revision_not_covered_by_review"
    if f"no-{intended_use}" in (t.get("restrictions") or []):
        return "use_restricted"
    if intended_use not in (t.get("permitted_uses") or []):
        return "use_not_permitted"
    return None


def check(lines: list, register: dict, *, intended_use: str = DEFAULT_USE, default_provenance=None) -> dict:
    problems = validate_register(register)
    refusals: list = []
    derived = 0
    for l in lines:
        if l.error is not None or not isinstance(l.obj, dict):
            refusals.append({"line": l.line, "reason": "unparseable_record"})
            continue
        probe = dict(l.obj)
        if "provenance" not in probe and default_provenance is not None:
            probe["provenance"] = default_provenance
        if not derives_from_model(probe):
            continue
        derived += 1
        reason = "register_invalid" if problems else decide(l.obj, register, intended_use, default_provenance)
        if reason:
            refusals.append({"line": l.line, "reason": reason})
    by_reason: dict = {}
    for r in refusals:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    return {"check": "teacher_terms", "status": PASS if (lines and not refusals) else FAIL, "intended_use": intended_use, "records_total": len(lines),
            "derived_records": derived, "refused_count": len(refusals), "refusals_by_reason": dict(sorted(by_reason.items())),
            "register_valid": not problems, "refusals": refusals[:1000], "refusals_truncated": len(refusals) > 1000}
