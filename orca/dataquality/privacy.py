"""(7) Sensitive-data scan wrapper. REUSES the existing scanners, adds no new patterns:

  * orca.serve.dlp.scan_output      -> secret-shaped strings (API keys, bearer tokens, private-key blocks, GitHub tokens) and, via
                                       orca.docs.pii_redact.redact_pii, SSN / email / phone / Luhn-valid card numbers
  * orca.eval.genesis_v2.privacy_scan._scan_bytes -> protected-corpus markers (private-holdout flags, generator-seed keys, gce2 private item content)

FAIL CLOSED: any finding, any unparseable line and any scanner exception is a FAIL. Findings carry line number, category and count -- NEVER the matched
value. These are pattern scanners (a floor, not a ceiling): a PASS means "no known pattern matched", not "no sensitive data".
"""
from __future__ import annotations

from pathlib import Path

from orca.dataquality import FAIL, NOT_EVALUATED, PASS, privacy_extra
from orca.dataquality._common import string_leaves


def scan_lines(lines: list, *, label: str = "dataset.jsonl", raw_bytes: bytes | None = None, allow_pii: tuple = (), extra_patterns: bool = True) -> dict:
    from orca.eval.genesis_v2 import privacy_scan as P
    from orca.serve import dlp

    findings: list = []
    by_cat: dict = {}
    errors: list = []
    for l in lines:
        if l.error is not None or not isinstance(l.obj, dict):
            errors.append({"line": l.line, "code": l.error or "not_an_object"})
            continue
        try:
            res = dlp.scan_output("\n".join(string_leaves(l.obj)))
        except Exception as e:  # scanner failure must never read as clean
            errors.append({"line": l.line, "code": f"scanner_error_{type(e).__name__}"})
            continue
        cats: dict = {}
        for k, v in res["secrets_redacted"].items():
            cats[f"secret:{k}"] = v
        for k, v in res["pii_flagged"].items():
            if k not in allow_pii:
                cats[f"pii:{k}"] = v
        if extra_patterns:
            for k, v in privacy_extra.scan("\n".join(string_leaves(l.obj))).items():
                if k.split(":", 1)[1] not in allow_pii:
                    cats[k] = cats.get(k, 0) + v
        if cats:
            findings.append({"line": l.line, "categories": dict(sorted(cats.items()))})
            for k, v in cats.items():
                by_cat[k] = by_cat.get(k, 0) + v
    markers: list = []
    if raw_bytes is not None:
        try:
            markers = sorted({rule for _, rule, _ in P._scan_bytes(Path(label).name, raw_bytes)})
        except Exception as e:
            errors.append({"line": 0, "code": f"marker_scanner_error_{type(e).__name__}"})
    bad = bool(findings or errors or markers)
    return {
        "check": "privacy", "status": FAIL if bad else (PASS if lines else NOT_EVALUATED),
        "records_scanned": len(lines), "records_with_findings": len(findings), "findings_by_category": dict(sorted(by_cat.items())),
        "protected_corpus_marker_rules": markers, "errors": errors[:200], "errors_count": len(errors),
        "findings": findings[:1000], "findings_truncated": len(findings) > 1000,
        "scanners": ["orca.serve.dlp.scan_output", "orca.docs.pii_redact.redact_pii", "orca.eval.genesis_v2.privacy_scan._scan_bytes"],
        "values_in_report": "never",
        "scope_note": "pattern scanners (floor, not ceiling): PASS = no known pattern matched",
    }
