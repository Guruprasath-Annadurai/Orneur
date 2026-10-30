#!/usr/bin/env python3
"""Write the pretraining requirement gap register from the acceptance graph.

The register is a coverage report. It does not accept a row, edit the
ledger, enroll a key, or publish a readiness percentage.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "docs" / "orneur" / "cursor" / "ORNEUR_PRETRAINING_100_PERCENT_REQUIREMENT_GAP_REGISTER.md"
GRAPH_PATH = ROOT / "docs" / "orneur" / "acceptance" / "register_graph.json"
LEDGER_PATH = ROOT / "docs" / "orneur" / "acceptance" / "acceptance_ledger.json"
POLICY_PATH = ROOT / "docs" / "orneur" / "acceptance" / "ACCEPTANCE_POLICY.md"
REGISTER_MD = ROOT / "docs" / "orneur" / "ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md"
TRUST_PATH = ROOT / "docs" / "orneur" / "acceptance" / "reviewer_trust.json"
ROOT_PATH = ROOT / "docs" / "orneur" / "acceptance" / "founder_root_keys.json"
BOOTSTRAP_PATH = ROOT / "docs" / "orneur" / "acceptance" / "BOOTSTRAP_ROOT_KEY.json"
CHECKPOINT_PATH = ROOT / "docs" / "orneur" / "acceptance" / "TRUST_CHECKPOINT.json"
PIN_PATH = ROOT / "docs" / "orneur" / "acceptance" / "TRUST_CHECKPOINT_PIN.json"

# Observed with git rev-parse. This file does not check out or edit that branch.
# The PR body also names a5d4e1f705e4635848bb44093c4c95f135b0d01b, which was
# not present in the fetched objects at inspection.
INSPECTED_PR99_HEAD = "c395dba09c54f10d626156ed57512dc635f1e9b8"
INSPECTED_PR99_BODY_SHA_ABSENT = "a5d4e1f705e4635848bb44093c4c95f135b0d01b"
BASE_SHA = "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a"

FIELDS = (
    ("stable_requirement_id", "id"),
    ("exact_source_authority", "source"),
    ("intended_technical_meaning", "rationale"),
    ("register_recorded_evidence", "current_evidence"),
    ("required_artifact", "evidence_required"),
    ("test_and_ci_evidence_states", "evidence_states"),
    ("independent_reviewer_identity", "independent_reviewer"),
    ("founder_approval_requirement", "founder_approval"),
    ("founder_act", "founder_act"),
    ("dependency_chain", "depends_on"),
    ("register_status", "status"),
    ("remaining_blocker", "escalation"),
    ("exit_condition", "exit"),
    ("engineering_owner", "implementation_owner"),
    ("independent_qualification_requirement", "pass_rule"),
    ("class", "class"),
    ("denominator", "denominator"),
    ("counts", "counts"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_engine():
    path = ROOT / "scripts" / "acceptance" / "acceptance_engine.py"
    spec = importlib.util.spec_from_file_location("orneur_acceptance_engine", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("acceptance engine could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cell(value) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value) if value else "(none)"
    elif value is None or value == "":
        text = "(empty)"
    else:
        text = str(value)
    return text.replace("\n", " ").replace("|", "\\|")


def _measured_state(node: dict) -> str:
    states = ",".join(node.get("evidence_states") or [])
    return (
        f"register_status={node.get('status')}; evidence_states={states}; "
        "engine_accepted=false; acceptance_eligibility=NOT_ELIGIBLE"
    )


def build_markdown() -> str:
    engine = _load_engine()
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    trust = json.loads(TRUST_PATH.read_text(encoding="utf-8"))
    root_state = json.loads(ROOT_PATH.read_text(encoding="utf-8"))
    bootstrap = json.loads(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    nodes = graph["nodes"]
    by_id = {node["id"]: node for node in nodes}
    ids = list(graph["denominator_pretraining_ids"])
    accepted = engine.evaluate(
        nodes,
        ledger,
        trust_snapshot=trust,
        root_state=root_state,
        bootstrap_root_key_hex=bootstrap.get("public_key_hex", ""),
        subject_sha=BASE_SHA,
        trust_checkpoint=checkpoint,
        pinned_checkpoint_hash=pin.get("pinned_checkpoint_hash", ""),
    )
    baseline_errors = engine.assert_published_baseline(
        nodes,
        REGISTER_MD.read_text(encoding="utf-8"),
        ledger,
        trust,
        root_state=root_state,
        bootstrap=bootstrap,
        trust_checkpoint=checkpoint,
    )
    from orca.rse.imp1.profiles import DEFERRED_CLASSES, SEMANTIC_CLASSES

    r65_children = sorted(node_id for node_id in by_id if str(node_id).startswith("R65-"))
    lines = [
        "# ORNEUR pretraining requirement gap register",
        "",
        "The title means every counted pretraining requirement is listed. It does not mean readiness is accepted.",
        "",
        "This document is non-normative. It copies fields from `docs/orneur/acceptance/register_graph.json` and records measurements from the acceptance engine. It does not change the denominator, the numerator, the ledger, the policy, or any trust file.",
        "",
        "## Baseline measured by regenerating this file",
        "",
        f"- Branch base SHA: `{BASE_SHA}`.",
        f"- Counted pretraining ids: {len(ids)}.",
        f"- Unique counted ids: {len(set(ids))}.",
        f"- Graph numerator: {graph.get('numerator_pretraining')}.",
        f"- Published percentage: {graph.get('published_pretraining_percentage')!r}.",
        f"- Ledger JSON: `{json.dumps(ledger)}`.",
        f"- `acceptance_engine.evaluate` on that ledger returned `{len(accepted)}` accepted ids.",
        f"- `assert_published_baseline` returned {len(baseline_errors)} errors.",
        f"- Rows whose register status is ACCEPTED: {sum(1 for node_id in ids if by_id[node_id].get('status') == 'ACCEPTED')}.",
        f"- R65 child ids in the graph: {len(r65_children)}.",
        f"- Class K code point {ord('K')} is in `DEFERRED_CLASSES`: {ord('K') in DEFERRED_CLASSES}.",
        f"- Class K code point is in `SEMANTIC_CLASSES`: {ord('K') in SEMANTIC_CLASSES}.",
        f"- Draft PR #99 GitHub head inspected and not modified: `{INSPECTED_PR99_HEAD}`.",
        f"- Draft PR #99 body also names `{INSPECTED_PR99_BODY_SHA_ABSENT}`. That object was not in the fetched repository at inspection, so it is not treated as the audit head.",
        "",
        "Authority file hashes at generation:",
        "",
        f"- `acceptance_ledger.json` `{_sha256(LEDGER_PATH)}`",
        f"- `register_graph.json` `{_sha256(GRAPH_PATH)}`",
        f"- `ACCEPTANCE_POLICY.md` `{_sha256(POLICY_PATH)}`",
        f"- `BOOTSTRAP_ROOT_KEY.json` `{_sha256(BOOTSTRAP_PATH)}`",
        f"- `founder_root_keys.json` `{_sha256(ROOT_PATH)}`",
        f"- `reviewer_trust.json` `{_sha256(TRUST_PATH)}`",
        f"- `TRUST_CHECKPOINT.json` `{_sha256(CHECKPOINT_PATH)}`",
        f"- `TRUST_CHECKPOINT_PIN.json` `{_sha256(PIN_PATH)}`",
        "",
        "The engine names three events. None is recorded in the ledger, and this document does not assert that any of them occurred: `PRETRAINING_READINESS_ACCEPTED`, `FOUNDER_AUTHORIZATION_GRANTED`, `TRAINING_EXECUTION_ALLOWED`.",
        "",
        "## R65",
        "",
        "Source authority, copied from the graph: The founder's canonical 65 rules. No file in this tree contains that set.",
        "",
        "Approval dependency: `founder_approval` is REQUIRED. The implementation owner is FOUNDER. The independent reviewer is PRODUCT_MANAGEMENT.",
        "",
        "This pass did not find a founder-approved source file and did not construct an expansion proposal. Child rules are absent. R65 remains the unmapped placeholder. The acceptance engine rejects an acceptance record whose id is `R65` or begins with `R65-`.",
        "",
        "## G1",
        "",
        "Source authority: RSE12_06 §7 step 1 and §8.",
        "",
        "Required artifact: an architecture review, stored where a later reader can open it, by a person who did not author RSE-ARCH-1.2.",
        "",
        "Register-recorded evidence: no such review file was found. This pass did not name a reviewer and did not add a review. `independent_reviewer` and `implementation_owner` are both `UNRESOLVED_EXTERNAL`.",
        "",
        "## DEC-K and C27",
        "",
        "DEC-K asks for a founder decision that class K recovery stays deferred and that C27 therefore stays unmet, until a later architecture-change authorization exists. The graph status of DEC-K is `NOT_AUTHORIZED`. Accepting that decision would not accept C27 and would not implement class K.",
        "",
        "C27 requires re-enrolment records for a TPM or board replacement that refuse a lower-generation restore, produced by an authorized class-K path. Its dependencies are DEC-K, G5, and HW-02. Its graph status is `NOT_STARTED`.",
        "",
        "Measured code: `orca/rse/imp1/profiles.py` places `ord(\"K\")` in `DEFERRED_CLASSES` and keeps `SEMANTIC_CLASSES` to `ord(\"G\")` and `ord(\"V\")`. `orca/rse/imp1/authority.py` raises `UNSUPPORTED_CURRENT_MILESTONE` when a grant class is outside `SEMANTIC_CLASSES`. This pass does not authorize or implement class K.",
        "",
        "## Acceptance trust procedure",
        "",
        "The committed trust files are empty. `BOOTSTRAP_ROOT_KEY.json` has an empty `public_key_hex`. `founder_root_keys.json` has no roots. `reviewer_trust.json` has no entries. `TRUST_CHECKPOINT.json` has empty hashes and an empty signature. `TRUST_CHECKPOINT_PIN.json` has an empty pin. `PINNED_BOOTSTRAP_ROOT_KEYS` in the acceptance engine is empty, so no caller-supplied bootstrap key can verify a real root state.",
        "",
        "Procedure when a real founder later chooses to enroll, without this document creating a key:",
        "",
        "1. The founder generates the bootstrap key outside this repository. The private key is not committed.",
        "2. A reviewed change records the public key in `BOOTSTRAP_ROOT_KEY.json` and in `PINNED_BOOTSTRAP_ROOT_KEYS`. Either location alone is not sufficient.",
        "3. The founder signs `founder_root_keys.json` for the exact commit SHA under evaluation.",
        "4. The founder signs `reviewer_trust.json` for that same SHA. Each reviewer key's role must equal the row's `independent_reviewer`, and that role must differ from the row's `implementation_owner`.",
        "5. The founder signs `TRUST_CHECKPOINT.json` over the hashes of that root state and that trust snapshot. The checkpoint hash is pinned in `TRUST_CHECKPOINT_PIN.json` from outside the engine. The engine compares the pin. It does not choose the newest generation.",
        "6. Revocation is a new root state, a new trust snapshot, and a new checkpoint pin bound to the new commit. A snapshot that names an ancestor SHA is stale. A same-commit snapshot whose checkpoint hash does not equal the pin is refused.",
        "7. A signed ledger record still has to present artifact bytes, or a non-disclosing custody signature for a protected corpus class. A signature over a digest is not possession.",
        "",
        "This pass performed none of those steps.",
        "",
        "## Counted rows",
        "",
        "Each row below is copied from the graph. `acceptance_eligibility` is `NOT_ELIGIBLE` because the ledger accepts nothing and the trust anchors are empty. That is a measurement, not a new register status.",
        "",
    ]
    for node_id in ids:
        node = by_id[node_id]
        lines.append(f"### {node_id}")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        for label, key in FIELDS:
            lines.append(f"| {label} | {_cell(node.get(key))} |")
        lines.append(f"| actual_measured_state | {_cell(_measured_state(node))} |")
        lines.append("| acceptance_eligibility | NOT_ELIGIBLE |")
        lines.append("")
    lines.append("## Other denominators")
    lines.append("")
    lines.append(
        "The graph also counts "
        f"{len(graph.get('denominator_application_ids') or [])} application ids, "
        f"{len(graph.get('denominator_execution_ids') or [])} execution ids, and "
        f"{len(graph.get('denominator_post_training_ids') or [])} post-training ids. "
        "They are not added to the 95."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate or check the pretraining gap register")
    parser.add_argument("--check", action="store_true", help="Exit 1 if the committed register differs")
    parser.add_argument("--write", action="store_true", help="Write the register")
    args = parser.parse_args()
    text = build_markdown()
    if args.check:
        current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else ""
        if current != text:
            print("gap register differs from the acceptance graph", file=sys.stderr)
            return 1
        print(f"gap register matches {OUT_PATH.relative_to(ROOT)}")
        return 0
    if args.write:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {OUT_PATH.relative_to(ROOT)}")
        return 0
    parser.error("pass --check or --write")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
