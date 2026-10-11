"""(3) Teacher-model output-use rights REGISTER and ingestion gate.

The register records, per teacher model, whether ORNEUR has a RECORDED review of that provider's output-use terms. It asserts NO legal conclusion:
every seeded teacher is UNREVIEWED with null ``terms_source_url`` / ``reviewed_by``. The gate REFUSES any model-generated record whose teacher is not
PERMITTED_RECORDED, and a teacher can only be PERMITTED_RECORDED if the register carries a cited terms record, source URL, human reviewer, review
date and an explicit list of covered revisions (the validator rejects anything less).

The register carries a ``content_sha256`` (canonical-JSON digest of everything else). That detects accidental edits and silent drift; it is NOT a
signature -- anyone who edits the file can recompute it. Authority for a status change lives in review, not in this checksum.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from orca.dataquality import SCHEMA_VERSION  # noqa: F401  (re-exported for callers)
from orca.dataquality._common import digest_of, sha256_file

REGISTER_SCHEMA = "orneur-teacher-rights-register/1"
STATUSES = ("PERMITTED_RECORDED", "RESTRICTED", "UNREVIEWED", "PROHIBITED")
DEFAULT_REGISTER_PATH = Path(__file__).resolve().parent / "data" / "teacher_rights_register.json"
UNATTRIBUTED_TEACHER = "unattributed-provider-teacher"
_TEACHER_KEYS = frozenset({
    "teacher_id", "aliases", "status", "revisions", "terms_record_id", "terms_source_url", "reviewed_by", "reviewed_at", "permitted_uses",
    "restrictions", "inventory_corpus_ids", "inventory_record_count", "notes",
})
_REGISTER_KEYS = frozenset({"schema_version", "register_version", "legal_conclusions_asserted", "derived_from", "teachers", "content_sha256"})
_DISTILL_LOG = re.compile(r"^local-distilllog-distill_(?P<model>.+)_(?P<ts>\d+)$")


class IngestRefused(Exception):
    """Raised by enforce_ingest when at least one record is refused by the teacher-rights gate."""

    def __init__(self, refusals: list):
        super().__init__(f"{len(refusals)} record(s) refused by the teacher-rights gate")
        self.refusals = refusals


def register_digest(register: dict) -> str:
    body = {k: v for k, v in register.items() if k != "content_sha256"}
    return digest_of(body)


def seal(register: dict) -> dict:
    out = dict(register)
    out["content_sha256"] = register_digest(register)
    return out


def _blank(v) -> bool:
    return not (isinstance(v, str) and v.strip())


def validate_register(register) -> list:
    """Return a list of problems (empty = valid). Never raises."""
    errs: list = []
    if not isinstance(register, dict):
        return ["register is not an object"]
    if register.get("schema_version") != REGISTER_SCHEMA:
        errs.append(f"schema_version must be {REGISTER_SCHEMA!r}")
    extra = sorted(set(register) - _REGISTER_KEYS)
    if extra:
        errs.append(f"unexpected register keys: {extra}")
    if register.get("legal_conclusions_asserted") is not False:
        errs.append("legal_conclusions_asserted must be false (the register records review status only)")
    if _blank(register.get("register_version")):
        errs.append("register_version missing")
    teachers = register.get("teachers")
    if not isinstance(teachers, list) or not teachers:
        errs.append("teachers must be a non-empty list")
        teachers = []
    seen: set = set()
    for i, t in enumerate(teachers):
        w = f"teachers[{i}]"
        if not isinstance(t, dict):
            errs.append(f"{w} is not an object")
            continue
        tid = t.get("teacher_id")
        if _blank(tid):
            errs.append(f"{w}.teacher_id missing")
        else:
            for name in [tid, *(t.get("aliases") or [])]:
                if name in seen:
                    errs.append(f"{w}: duplicate teacher id/alias {name!r}")
                seen.add(name)
        extra = sorted(set(t) - _TEACHER_KEYS)
        if extra:
            errs.append(f"{w}: unexpected keys {extra}")
        st = t.get("status")
        if st not in STATUSES:
            errs.append(f"{w}.status must be one of {STATUSES}")
            continue
        for lst in ("revisions", "permitted_uses", "restrictions", "aliases", "inventory_corpus_ids"):
            if lst in t and not (isinstance(t[lst], list) and all(isinstance(x, str) and x for x in t[lst])):
                errs.append(f"{w}.{lst} must be a list of non-empty strings")
        if st == "PERMITTED_RECORDED":
            for f in ("terms_record_id", "terms_source_url", "reviewed_by", "reviewed_at"):
                if _blank(t.get(f)):
                    errs.append(f"{w}: PERMITTED_RECORDED requires {f} (cited terms record)")
            if isinstance(t.get("reviewed_by"), str) and t["reviewed_by"].startswith("model:"):
                errs.append(f"{w}: reviewed_by must be a human, not a model identity")
            if not t.get("revisions"):
                errs.append(f"{w}: PERMITTED_RECORDED requires an explicit non-empty revisions list")
            if not t.get("permitted_uses"):
                errs.append(f"{w}: PERMITTED_RECORDED requires a non-empty permitted_uses list")
        elif st == "UNREVIEWED":
            for f in ("terms_record_id", "terms_source_url", "reviewed_by", "reviewed_at"):
                if t.get(f) is not None:
                    errs.append(f"{w}: UNREVIEWED must have {f} = null")
    sha = register.get("content_sha256")
    if not isinstance(sha, str) or sha != register_digest(register):
        errs.append("content_sha256 does not match the register body (edited without re-sealing, or tampered)")
    return errs


def load_register(path=None) -> dict:
    p = Path(path) if path else DEFAULT_REGISTER_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def derive_seed(inventory: dict, *, inventory_path: str = "", inventory_sha256: str = "") -> dict:
    """Derive the seed register from the corpus inventory's ``distillation_data`` corpora. Every teacher defaults to UNREVIEWED."""
    ids = list(inventory["class_coverage"]["distillation_data"]["corpus_ids"])
    by_id = {c["corpus_id"]: c for c in inventory["corpora"]}
    groups: dict = {}
    for cid in ids:
        m = _DISTILL_LOG.match(cid)
        tid = m.group("model") if m else UNATTRIBUTED_TEACHER
        g = groups.setdefault(tid, {"ids": [], "count": 0})
        g["ids"].append(cid)
        g["count"] += int(by_id[cid].get("record_count", 0))
    teachers = []
    for tid in sorted(groups):
        note = ("Seeded from the corpus inventory; output-use terms NOT reviewed. No legal conclusion is asserted by this entry."
                if tid != UNATTRIBUTED_TEACHER else
                "Raw distilled files whose inventory provenance says 'provider/teacher model outputs (see distill_logs)'; the specific teacher per record is "
                "not recorded in the repository. Treated as UNREVIEWED. No legal conclusion is asserted by this entry.")
        teachers.append({
            "teacher_id": tid, "aliases": [], "status": "UNREVIEWED", "revisions": [],
            "terms_record_id": None, "terms_source_url": None, "reviewed_by": None, "reviewed_at": None,
            "permitted_uses": [], "restrictions": [],
            "inventory_corpus_ids": sorted(groups[tid]["ids"]), "inventory_record_count": groups[tid]["count"], "notes": note,
        })
    reg = {"schema_version": REGISTER_SCHEMA, "register_version": "1", "legal_conclusions_asserted": False,
           "derived_from": {"path": inventory_path, "sha256": inventory_sha256, "class": "distillation_data"}, "teachers": teachers}
    return seal(reg)


def derive_seed_from_file(inventory_path) -> dict:
    p = Path(inventory_path)
    return derive_seed(json.loads(p.read_text(encoding="utf-8")), inventory_path=p.as_posix(), inventory_sha256=sha256_file(p))


# ---------------------------------------------------------------- gate
def _find(register: dict, model_id) -> dict | None:
    if not isinstance(model_id, str):
        return None
    for t in register.get("teachers", []):
        if model_id == t.get("teacher_id") or model_id in (t.get("aliases") or []):
            return t
    return None


def gate_provenance(prov, register: dict) -> dict:
    """Decision for one provenance block. ``allowed`` is True only for non-model generators and for PERMITTED_RECORDED teachers with the revision covered."""
    if not isinstance(prov, dict) or not isinstance(prov.get("generator"), dict):
        return {"allowed": False, "reason": "no_generator_declared"}
    gen = prov["generator"]
    kind = gen.get("kind")
    if kind in ("human", "program"):
        return {"allowed": True, "reason": f"generator_kind_{kind}"}
    if kind != "model":
        return {"allowed": False, "reason": "unknown_generator_kind"}
    t = _find(register, gen.get("model_id"))
    if t is None:
        return {"allowed": False, "reason": "teacher_not_in_register"}
    if t["status"] != "PERMITTED_RECORDED":
        return {"allowed": False, "reason": f"teacher_status_{t['status']}", "teacher_id": t["teacher_id"]}
    if _blank(t.get("terms_record_id")) or _blank(t.get("terms_source_url")):
        return {"allowed": False, "reason": "no_cited_terms_record", "teacher_id": t["teacher_id"]}
    if gen.get("model_revision") not in (t.get("revisions") or []):
        return {"allowed": False, "reason": "revision_not_covered_by_review", "teacher_id": t["teacher_id"]}
    return {"allowed": True, "reason": "permitted_recorded", "teacher_id": t["teacher_id"], "terms_record_id": t["terms_record_id"]}


def gate_lines(lines: list, register: dict, *, default_provenance=None) -> dict:
    """Run the gate over parsed JSONL lines. A register that fails validation refuses everything (fail closed)."""
    problems = validate_register(register)
    refusals, accepted = [], []
    for l in lines:
        if l.error is not None or not isinstance(l.obj, dict):
            refusals.append({"line": l.line, "reason": "unparseable_record"})
            continue
        prov = l.obj.get("provenance", default_provenance)
        if problems:
            refusals.append({"line": l.line, "reason": "register_invalid"})
            continue
        d = gate_provenance(prov, register)
        (accepted if d["allowed"] else refusals).append({"line": l.line, **{k: v for k, v in d.items() if k != "allowed"}})
    by_reason: dict = {}
    for r in refusals:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    return {
        "check": "teacher_rights", "status": "PASS" if not refusals and not problems and lines else "FAIL",
        "register_valid": not problems, "register_problems": problems, "register_content_sha256": register.get("content_sha256"),
        "records_total": len(lines), "accepted_count": len(accepted), "refused_count": len(refusals),
        "refusals_by_reason": dict(sorted(by_reason.items())), "refusals": refusals[:1000], "refusals_truncated": len(refusals) > 1000,
    }


def enforce_ingest(lines: list, register: dict, *, default_provenance=None) -> list:
    """Return the accepted lines or raise IngestRefused. Use as the ingestion gate in front of any dataset build."""
    res = gate_lines(lines, register, default_provenance=default_provenance)
    if res["refused_count"] or not res["register_valid"]:
        raise IngestRefused(res["refusals"] or [{"line": 0, "reason": "register_invalid"}])
    return lines
