"""(10) Single machine-readable quality report aggregating checks 1-9.

Every check keeps its own status (PASS / FAIL / NOT_EVALUATED). ``statuses`` lists them all, with the contamination sub-checks flattened in, and is never
collapsed; there is deliberately NO overall score and no boolean 'ok'. A check whose required input was not supplied is NOT_EVALUATED, never PASS.
The report has no timestamp unless ``now`` is passed, so the same inputs always give byte-identical output.
"""
from __future__ import annotations

from pathlib import Path

from orca.dataquality import NOT_EVALUATED, SCHEMA_VERSION
from orca.dataquality import balance as B
from orca.dataquality import contamination as CT
from orca.dataquality import dedup as D
from orca.dataquality import diversity as DV
from orca.dataquality import manifest as M
from orca.dataquality import privacy as PR
from orca.dataquality import provenance as PV
from orca.dataquality import schema as SC
from orca.dataquality import teacher_rights as TR
from orca.dataquality._common import load_jsonl, parsed, sha256_file

REPORT_FORMAT = "orneur-dataquality-report/1"


def _file_info(path, lines, label=None) -> dict:
    return {"path": label or Path(path).as_posix(), "sha256": sha256_file(path), "lines": len(lines), "parseable_records": len(parsed(lines))}


def build_report(train_path, eval_path=None, *, kind: str = "auto", strict_keys: bool = False, source_registry=None, default_provenance=None,
                 teacher_register=None, dedup_threshold: float = D.DEFAULT_THRESHOLD, dedup_shingle_n: int = D.DEFAULT_SHINGLE_N,
                 max_near_record_fraction: float = D.DEFAULT_MAX_NEAR_RECORD_FRACTION, canaries=None, fingerprint_set=None, semantic_embedder=None,
                 category_fields: tuple = B.DEFAULT_FIELDS, labels=None, min_share: float = 0.05, manifest_env=None,
                 legacy_quick_ratio_pool: dict | None = None, allow_pii: tuple = (), now: str | None = None,
                 train_label: str | None = None, eval_label: str | None = None) -> dict:
    train_lines = load_jsonl(train_path)
    eval_lines = load_jsonl(eval_path) if eval_path else None
    register = teacher_rights_register(teacher_register)
    checks = [
        SC.validate_lines(train_lines, kind, strict_keys=strict_keys),
        PV.check_provenance(train_lines, source_registry, default_provenance=default_provenance),
        TR.gate_lines(train_lines, register, default_provenance=default_provenance),
        D.analyze(train_lines, threshold=dedup_threshold, shingle_n=dedup_shingle_n, max_near_record_fraction=max_near_record_fraction),
        DV.lexical_structural(train_lines),
        DV.semantic(train_lines, semantic_embedder),
        CT.check(train_lines, eval_lines, canaries=canaries, fingerprint_set=fingerprint_set),
        PR.scan_lines(train_lines, label=Path(train_path).name, raw_bytes=Path(train_path).read_bytes(), allow_pii=allow_pii),
        B.balance(train_lines, fields=category_fields, labels=labels, min_share=min_share),
    ]
    if manifest_env is None:
        checks.append({"check": "manifest_verify", "status": NOT_EVALUATED, "reason": "no manifest supplied"})
    else:
        checks.append(M.verify(manifest_env, train_path, eval_path))
    statuses = []
    for c in checks:
        statuses.append({"check": c["check"], "status": c["status"]})
        for s in c.get("sub_checks", []):
            statuses.append({"check": f"{c['check']}.{s['name']}", "status": s["status"]})
    counts = {"PASS": 0, "FAIL": 0, "NOT_EVALUATED": 0}
    for s in statuses:
        counts[s["status"]] += 1
    rep = {
        "report_format": REPORT_FORMAT, "schema_version": SCHEMA_VERSION,
        "dataset": {"train": _file_info(train_path, train_lines, train_label), "eval": _file_info(eval_path, eval_lines, eval_label) if eval_path else None},
        "statuses": statuses, "status_counts": counts, "aggregate_quality_score": "NONE_BY_DESIGN",
        "checks": checks,
        "supplementary": {},
    }
    if legacy_quick_ratio_pool:
        rep["supplementary"]["legacy_quick_ratio"] = D.legacy_quick_ratio(legacy_quick_ratio_pool)
    if now:
        rep["generated_at"] = now
    return rep


def teacher_rights_register(r):
    return r if isinstance(r, dict) else TR.load_register(r)
