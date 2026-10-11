#!/usr/bin/env python3
"""Machine-readable ORNEUR readiness scorecard (Workstream I).

NON_NORMATIVE. Authorizes nothing. It never emits a single readiness
percentage: it reports twelve independent dimensions, each with its own state
and evidence pointer, plus a per-requirement classification of the master
register.

Only the canonical acceptance engine (``scripts/acceptance/acceptance_engine``)
decides which requirements are VERIFIED_ACCEPTED. This module never writes,
edits or infers acceptance: with the committed (empty) ledger the accepted
count is 0 by construction.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACC = ROOT / "docs" / "orneur" / "acceptance"
DIMENSIONS_PATH = ROOT / "docs" / "orneur" / "status" / "scorecard_dimensions.json"

REQUIREMENT_CLASSES = (
    "VERIFIED_ACCEPTED",
    "IMPLEMENTED_AWAITING_REVIEW",
    "PARTIAL",
    "MISSING",
    "BLOCKED_OWNER",
    "BLOCKED_EXTERNAL",
    "FAILED",
)

DIMENSION_KEYS = (
    "code_implemented",
    "tests_passing",
    "independent_security_review",
    "formal_cryptographic_acceptance",
    "dataset_readiness",
    "evaluation_readiness",
    "foundation_selection",
    "training_environment_readiness",
    "training_authorization",
    "model_capability",
    "product_readiness",
    "production_authorization",
)

# Conservative, order-independent mapping of register status -> class.
# Nothing maps to VERIFIED_ACCEPTED; that class is engine-only.
_STATUS_CLASS = {
    "UNMERGED_NOT_ACCEPTED": "IMPLEMENTED_AWAITING_REVIEW",
    "OPEN_PR_UNREVIEWED": "IMPLEMENTED_AWAITING_REVIEW",
    "PRESENT_ON_MAIN": "IMPLEMENTED_AWAITING_REVIEW",
    "DESIGNED_ONLY": "PARTIAL",
    "NOT_ACCEPTED": "PARTIAL",
    "NOT_STARTED": "MISSING",
    "OPEN": "MISSING",
    "NOT_AUTHORIZED": "BLOCKED_OWNER",
    "NOT_VERIFIABLE": "BLOCKED_EXTERNAL",
    "BLOCKED_LICENSE": "BLOCKED_EXTERNAL",
    "EXTERNALLY_REPORTED": "BLOCKED_EXTERNAL",
}


def classify(node: dict) -> str:
    status = node.get("status", "")
    if status not in _STATUS_CLASS:
        return "MISSING"
    cls = _STATUS_CLASS[status]
    # A founder-held act the engineering side cannot perform is an owner block.
    if cls == "MISSING" and node.get("founder_act") not in (None, "", "NONE"):
        return "BLOCKED_OWNER"
    return cls


def canonical_accepted_ids(root: Path = ROOT) -> list[str]:
    """Run the canonical engine over the committed ledger. Never infers."""
    acc = root / "docs" / "orneur" / "acceptance"
    eng_dir = str(root / "scripts" / "acceptance")
    if eng_dir not in sys.path:
        sys.path.insert(0, eng_dir)
    from acceptance_engine import evaluate  # type: ignore

    def load(name):
        return json.loads((acc / name).read_text(encoding="utf-8"))

    graph = load("register_graph.json")
    ledger = load("acceptance_ledger.json")
    accepted = evaluate(
        graph["nodes"],
        ledger,
        trust_snapshot=load("reviewer_trust.json"),
        root_state=load("founder_root_keys.json"),
        bootstrap_root_key_hex=load("BOOTSTRAP_ROOT_KEY.json").get("public_key_hex", ""),
        trust_checkpoint=load("TRUST_CHECKPOINT.json"),
        pinned_checkpoint_hash=load("TRUST_CHECKPOINT_PIN.json").get("pinned_checkpoint_hash", ""),
        subject_sha="0" * 40,
    )
    return sorted(accepted)


def build(root: Path = ROOT) -> dict:
    graph = json.loads((root / "docs" / "orneur" / "acceptance" / "register_graph.json").read_text(encoding="utf-8"))
    dims = json.loads((root / "docs" / "orneur" / "status" / "scorecard_dimensions.json").read_text(encoding="utf-8"))
    accepted = set(canonical_accepted_ids(root))
    rows = []
    for node in graph["nodes"]:
        cls = "VERIFIED_ACCEPTED" if node["id"] in accepted else classify(node)
        rows.append({
            "id": node["id"],
            "denominator": node["denominator"],
            "register_status": node["status"],
            "class": cls,
            "implementation_owner": node.get("implementation_owner"),
            "independent_reviewer": node.get("independent_reviewer"),
        })
    pre = [r for r in rows if r["denominator"] == "PRE_TRAINING"]
    by_class = Counter(r["class"] for r in pre)
    return {
        "schema": "orneur.scorecard/1",
        "non_normative": True,
        "single_readiness_percentage": None,
        "note": "No aggregate readiness number exists by design; see dimensions and per-class counts.",
        "training_status": "NOT_AUTHORIZED",
        "dimensions": dims["dimensions"],
        "acceptance": {
            "source": "scripts/acceptance/acceptance_engine.py over committed ledger",
            "pretraining_denominator": len(pre),
            "pretraining_accepted": sum(1 for r in pre if r["class"] == "VERIFIED_ACCEPTED"),
            "pretraining_by_class": {c: by_class.get(c, 0) for c in REQUIREMENT_CLASSES},
            "all_nodes": len(rows),
        },
        "requirements": rows,
    }


def validate(card: dict) -> list[str]:
    errs = []
    if card.get("single_readiness_percentage") is not None:
        errs.append("a single readiness percentage is forbidden")
    if card.get("training_status") != "NOT_AUTHORIZED":
        errs.append("training_status must remain NOT_AUTHORIZED")
    keys = tuple(d["key"] for d in card.get("dimensions", []))
    if keys != DIMENSION_KEYS:
        errs.append(f"dimension keys differ from the required twelve: {keys}")
    for d in card.get("dimensions", []):
        if not d.get("evidence"):
            errs.append(f"dimension {d['key']} has no evidence pointer")
        if d["key"] in ("training_authorization", "production_authorization") and d.get("state") != "NOT_AUTHORIZED":
            errs.append(f"{d['key']} must be NOT_AUTHORIZED")
    for r in card.get("requirements", []):
        if r["class"] not in REQUIREMENT_CLASSES:
            errs.append(f"{r['id']}: bad class {r['class']}")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    card = build()
    errs = validate(card)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    text = json.dumps(card, indent=2, sort_keys=True) + "\n"
    out = ROOT / "docs" / "orneur" / "status" / "SCORECARD.json"
    if args.write:
        out.write_text(text, encoding="utf-8")
    if args.check and (not out.exists() or out.read_text(encoding="utf-8") != text):
        print("SCORECARD.json drift; run with --write", file=sys.stderr)
        return 1
    a = card["acceptance"]
    print(f"accepted={a['pretraining_accepted']}/{a['pretraining_denominator']} {a['pretraining_by_class']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
