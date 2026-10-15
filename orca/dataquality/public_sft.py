"""Reproducible quality reports for the already-public SFT files in notebooks/data (classified PUBLIC_SFT in
docs/orneur/phase-21/PUBLIC_SFT_DATASET_CLASSIFICATION.json). Only those files are read. Outputs are byte-reproducible (no timestamps, repo-relative labels).

Inputs deliberately NOT supplied (so those checks report FAIL / NOT_EVALUATED honestly): source registry + provenance (the public files carry none),
canary strings, a protected-holdout fingerprint set, category labels, a local semantic embedder. The fingerprint check that IS run uses the PUBLIC SFT
eval split of the same dataset as the 'eval' side; it is NOT the protected Genesis V2 holdout.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.dataquality import contamination as CT
from orca.dataquality import manifest as M
from orca.dataquality import report as R
from orca.dataquality._common import load_jsonl, pretty_json, sha256_file

CLASSIFICATION = "docs/orneur/phase-21/PUBLIC_SFT_DATASET_CLASSIFICATION.json"
NB = "notebooks/data/"
PAIRS = {
    "orca_nano_combined_v1": ("orca_nano_combined_train_v1.jsonl", "orca_nano_combined_eval_v1.jsonl", "v1"),
    "orca_core_combined_v2": ("orca_core_combined_train_v2.jsonl", "orca_core_combined_eval_v2.jsonl", "v2"),
    "orneur_genesis_v2": ("orneur_genesis_v2_train.jsonl", "orneur_genesis_v2_eval.jsonl", "v2"),
    "orneur_genesis_v3": ("orneur_genesis_v3_train.jsonl", "orneur_genesis_v3_eval.jsonl", "v3"),
}
KNOWN_LIMITATIONS = [
    "creation_code_sha is NOT_RECORDED: the build-script commit for these public SFT files is not recorded in the repository",
    "no per-record provenance, license or generator metadata exists in these files",
    "manifest built by orca.dataquality from the files as they are; it records identity, it does not vouch for provenance",
]


def _classification(root: Path) -> dict:
    return json.loads((root / CLASSIFICATION).read_text())["files"]


def generate(root, out_dir) -> list:
    root, out = Path(root), Path(out_dir)
    cls = _classification(root)
    written = []
    for name, (tr, ev, ver) in sorted(PAIRS.items()):
        tr_rel, ev_rel = NB + tr, NB + ev
        for rel in (tr_rel, ev_rel):
            if cls[rel]["classification"] != "PUBLIC_SFT" or cls[rel]["sha256"] != sha256_file(root / rel):
                raise RuntimeError(f"{rel}: not the classified PUBLIC_SFT bytes; refusing to measure")
        env = M.build(root / tr_rel, root / ev_rel, dataset_id="public-sft-" + name.replace("_", "-"), version=ver, purpose="public SFT dataset quality measurement",
                      creation_code_sha=M.NOT_RECORDED, source_paths=[tr_rel, ev_rel], schema='{"text": str}', known_limitations=KNOWN_LIMITATIONS,
                      deduplication_result="see report dedup check")
        mp = M.write(env, out / f"{name}.manifest.json")
        ev_lines = load_jsonl(root / ev_rel)
        pool = {Path(tr_rel).name: load_jsonl(root / tr_rel), Path(ev_rel).name: ev_lines}
        rep = R.build_report(root / tr_rel, root / ev_rel, manifest_env=env, fingerprint_set=CT.build_fingerprint_set(ev_lines), legacy_quick_ratio_pool=pool,
                             train_label=tr_rel, eval_label=ev_rel)
        rp = out / f"{name}.report.json"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(pretty_json(rep), encoding="utf-8")
        written += [mp, rp]
    return written
