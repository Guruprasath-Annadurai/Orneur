"""CLI: ``python -m orca.dataquality <command> ...``. Emits canonical JSON (sorted keys, 2-space indent, ASCII) to stdout or ``--out``.

Exit codes: 0 = PASS, 1 = at least one FAIL, 3 = no FAIL but something NOT_EVALUATED, 2 = usage / input error.
No timestamps are emitted unless ``--now <string>`` is passed explicitly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orca.dataquality import balance as B
from orca.dataquality import contamination as CT
from orca.dataquality import datacard as DC
from orca.dataquality import dedup as D
from orca.dataquality import diversity as DV
from orca.dataquality import manifest as M
from orca.dataquality import privacy as PR
from orca.dataquality import provenance as PV
from orca.dataquality import report as R
from orca.dataquality import schema as SC
from orca.dataquality import teacher_rights as TR
from orca.dataquality._common import load_jsonl, pretty_json


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit(obj, out) -> None:
    text = pretty_json(obj)
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _code(obj) -> int:
    sts = [s["status"] for s in obj["statuses"]] if "statuses" in obj else [obj.get("status", "PASS")]
    if "FAIL" in sts:
        return 1
    return 3 if "NOT_EVALUATED" in sts else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m orca.dataquality", description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default=None, help="write JSON here instead of stdout")
    common.add_argument("--now", default=None, help="explicit timestamp string to embed; omitted by default so output is reproducible")
    sp = ap.add_subparsers(dest="cmd", required=True)
    _orig = sp.add_parser
    sp.add_parser = lambda name, **kw: _orig(name, parents=[common], **kw)   # --out/--now accepted after the command

    s = sp.add_parser("schema"); s.add_argument("file"); s.add_argument("--kind", default="auto", choices=SC.KINDS); s.add_argument("--strict-keys", action="store_true")
    s.add_argument("--max-chars", type=int, default=SC.DEFAULT_MAX_CHARS)
    s = sp.add_parser("provenance"); s.add_argument("file"); s.add_argument("--sources", required=True); s.add_argument("--default-provenance")
    s = sp.add_parser("ingest-gate", help="teacher-rights gate; exit 1 if any record is refused")
    s.add_argument("file"); s.add_argument("--register"); s.add_argument("--default-provenance")
    s = sp.add_parser("teacher-register"); s.add_argument("action", choices=("validate", "derive", "seal")); s.add_argument("--register"); s.add_argument("--inventory")
    s = sp.add_parser("dedup"); s.add_argument("file"); s.add_argument("--threshold", type=float, default=D.DEFAULT_THRESHOLD)
    s.add_argument("--shingle-n", type=int, default=D.DEFAULT_SHINGLE_N); s.add_argument("--max-near-fraction", type=float, default=D.DEFAULT_MAX_NEAR_RECORD_FRACTION)
    s = sp.add_parser("legacy-quick-ratio", help="reproduce the documented difflib quick_ratio figure over the pooled files")
    s.add_argument("files", nargs="+")
    s = sp.add_parser("diversity"); s.add_argument("file")
    s = sp.add_parser("fingerprint", help="build a hashed eval fingerprint set"); s.add_argument("--eval", required=True)
    s = sp.add_parser("contamination"); s.add_argument("--train", required=True); s.add_argument("--eval"); s.add_argument("--canaries", help="text file, one canary per line")
    s.add_argument("--fingerprints")
    s = sp.add_parser("privacy"); s.add_argument("file")
    s = sp.add_parser("balance"); s.add_argument("file"); s.add_argument("--field", action="append"); s.add_argument("--labels"); s.add_argument("--min-share", type=float, default=0.05)
    s = sp.add_parser("manifest"); s.add_argument("action", choices=("build", "verify")); s.add_argument("--train", required=True); s.add_argument("--eval")
    s.add_argument("--manifest"); s.add_argument("--dataset-id"); s.add_argument("--version"); s.add_argument("--purpose", default=""); s.add_argument("--creation-code-sha", default="")
    s.add_argument("--source-path", action="append"); s.add_argument("--schema", default=""); s.add_argument("--filters-applied", default="")
    s.add_argument("--dedup-result", default=""); s.add_argument("--limitation", action="append"); s.add_argument("--target-model-family", default="")
    s = sp.add_parser("report"); s.add_argument("--train", required=True); s.add_argument("--eval"); s.add_argument("--kind", default="auto", choices=SC.KINDS)
    s.add_argument("--sources"); s.add_argument("--default-provenance"); s.add_argument("--register"); s.add_argument("--canaries"); s.add_argument("--fingerprints")
    s.add_argument("--manifest"); s.add_argument("--labels"); s.add_argument("--field", action="append"); s.add_argument("--min-share", type=float, default=0.05)
    s.add_argument("--threshold", type=float, default=D.DEFAULT_THRESHOLD); s.add_argument("--legacy-pool", action="append", help="repeat to pool files for the legacy quick_ratio figure")
    s = sp.add_parser("public-sft", help="regenerate manifests+reports for the PUBLIC_SFT files in notebooks/data"); s.add_argument("--root", default=".")
    s.add_argument("--out-dir", required=True)
    s = sp.add_parser("datacard"); s.add_argument("--manifest", required=True); s.add_argument("--report", required=True); s.add_argument("--final", action="store_true")
    s.add_argument("--corpus-identity-sha256"); s.add_argument("--data1"); s.add_argument("--data2"); s.add_argument("--data5"); s.add_argument("--md-out")
    return ap


def _canaries(p):
    return [x for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()] if p else None


def run(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return _run(a)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, DC.DataCardRefused) as e:
        sys.stderr.write(f"error: {type(e).__name__}: {e}\n")
        return 2


def _run(a) -> int:
    c = a.cmd
    if c == "schema":
        res = SC.validate_file(a.file, a.kind, max_chars=a.max_chars, strict_keys=a.strict_keys)
    elif c == "provenance":
        res = PV.check_provenance(load_jsonl(a.file), _json(a.sources), default_provenance=_json(a.default_provenance) if a.default_provenance else None)
    elif c == "ingest-gate":
        res = TR.gate_lines(load_jsonl(a.file), TR.load_register(a.register), default_provenance=_json(a.default_provenance) if a.default_provenance else None)
    elif c == "teacher-register":
        if a.action == "derive":
            if not a.inventory:
                raise ValueError("derive needs --inventory")
            res = TR.derive_seed_from_file(a.inventory)
        else:
            reg = TR.load_register(a.register)
            if a.action == "seal":
                res = TR.seal(reg)
            else:
                probs = TR.validate_register(reg)
                res = {"check": "teacher_register", "status": "PASS" if not probs else "FAIL", "problems": probs, "content_sha256": reg.get("content_sha256"),
                       "status_counts": {s: sum(1 for t in reg.get("teachers", []) if t.get("status") == s) for s in TR.STATUSES}}
    elif c == "dedup":
        res = D.analyze(load_jsonl(a.file), threshold=a.threshold, shingle_n=a.shingle_n, max_near_record_fraction=a.max_near_fraction)
    elif c == "legacy-quick-ratio":
        res = {"check": "legacy_quick_ratio", **D.legacy_quick_ratio({Path(f).name: load_jsonl(f) for f in a.files})}
        res["status"] = "PASS" if res.get("status") == "MEASURED" else res["status"]
    elif c == "diversity":
        res = DV.lexical_structural(load_jsonl(a.file))
    elif c == "fingerprint":
        res = CT.build_fingerprint_set(load_jsonl(a.eval))
        _emit(res, a.out)
        return 0
    elif c == "contamination":
        res = CT.check(load_jsonl(a.train), load_jsonl(a.eval) if a.eval else None, canaries=_canaries(a.canaries), fingerprint_set=_json(a.fingerprints) if a.fingerprints else None)
    elif c == "privacy":
        res = PR.scan_lines(load_jsonl(a.file), label=Path(a.file).name, raw_bytes=Path(a.file).read_bytes())
    elif c == "balance":
        res = B.balance(load_jsonl(a.file), fields=tuple(a.field) if a.field else B.DEFAULT_FIELDS, labels=_json(a.labels) if a.labels else None, min_share=a.min_share)
    elif c == "manifest":
        if a.action == "build":
            if not (a.dataset_id and a.version and a.creation_code_sha):
                raise ValueError("manifest build needs --dataset-id, --version and --creation-code-sha")
            res = M.build(a.train, a.eval, dataset_id=a.dataset_id, version=a.version, purpose=a.purpose, creation_code_sha=a.creation_code_sha, source_paths=a.source_path,
                          schema=a.schema, filters_applied=a.filters_applied, deduplication_result=a.dedup_result, known_limitations=a.limitation, now=a.now,
                          target_model_family=a.target_model_family)
            _emit(res, a.out)
            return 0
        if not a.manifest:
            raise ValueError("manifest verify needs --manifest")
        res = M.verify(M.load(a.manifest), a.train, a.eval)
    elif c == "report":
        pool = {Path(f).name: load_jsonl(f) for f in a.legacy_pool} if a.legacy_pool else None
        res = R.build_report(a.train, a.eval, kind=a.kind, source_registry=_json(a.sources) if a.sources else None,
                             default_provenance=_json(a.default_provenance) if a.default_provenance else None, teacher_register=a.register,
                             dedup_threshold=a.threshold, canaries=_canaries(a.canaries), fingerprint_set=_json(a.fingerprints) if a.fingerprints else None,
                             category_fields=tuple(a.field) if a.field else B.DEFAULT_FIELDS, labels=_json(a.labels) if a.labels else None, min_share=a.min_share,
                             manifest_env=_json(a.manifest) if a.manifest else None, legacy_quick_ratio_pool=pool, now=a.now)
    elif c == "public-sft":
        from orca.dataquality import public_sft
        res = {"check": "public_sft", "status": "PASS", "written": [Path(p).name for p in public_sft.generate(a.root, a.out_dir)]}
    elif c == "datacard":
        manifest, report = _json(a.manifest), _json(a.report)
        card = DC.build_card(manifest, report, final=a.final, corpus_identity_sha256=a.corpus_identity_sha256,
                             data1=_json(a.data1) if a.data1 else None, data2=_json(a.data2) if a.data2 else None, data5=_json(a.data5) if a.data5 else None)
        if a.md_out:
            Path(a.md_out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.md_out).write_text(DC.render_markdown(card), encoding="utf-8")
        _emit(card, a.out)
        return 0
    else:  # pragma: no cover
        raise ValueError(f"unknown command {c}")
    _emit(res, a.out)
    return _code(res)


def main() -> None:  # pragma: no cover
    sys.exit(run())
