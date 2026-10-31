"""Report pretraining blockers around the existing acceptance engine.

This module does not accept a requirement, mint a key, write the ledger,
or report training execution as allowed unless the engine itself has
accepted the execution row. An empty production ledger accepts nothing.
"""
from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROOT / "docs" / "orneur" / "acceptance" / "register_graph.json"
LEDGER_PATH = ROOT / "docs" / "orneur" / "acceptance" / "acceptance_ledger.json"
TRUST_FILES = (
    ROOT / "docs" / "orneur" / "acceptance" / "BOOTSTRAP_ROOT_KEY.json",
    ROOT / "docs" / "orneur" / "acceptance" / "founder_root_keys.json",
    ROOT / "docs" / "orneur" / "acceptance" / "reviewer_trust.json",
    ROOT / "docs" / "orneur" / "acceptance" / "TRUST_CHECKPOINT.json",
    ROOT / "docs" / "orneur" / "acceptance" / "TRUST_CHECKPOINT_PIN.json",
)
EVAL_STATUS_PATH = ROOT / "docs" / "orneur" / "phase-21" / "GENESIS_CAPABILITY_EVAL_V2_STATUS.json"

BLOCKER_CODES = (
    "r65_unmapped",
    "c27_unmet",
    "trust_anchors_absent",
    "protected_corpus_evidence_absent",
    "private_evaluation_unfrozen",
    "foundation_not_selected",
    "compute_unqualified",
    "independent_reviews_missing",
    "real_data_licensing_unresolved",
    "training_authorization_absent",
)


@dataclass(frozen=True)
class Observation:
    """Facts the gate is allowed to see. Flags are measurements, not approvals."""

    r65_status: str
    r65_child_count: int
    c27_status: str
    trust_anchor_empty: bool
    protected_corpus_accepted: bool
    private_eval_frozen: bool
    foundation_selected: bool
    compute_qualified: bool
    independent_review_accepted: bool
    data_licensing_resolved: bool
    training_authorized: bool
    counted: int
    numerator: int


def blocker_codes(observation: Observation) -> list[str]:
    """Return the named blockers that are still present. Order is stable.

    `r65_status="MAPPED"` with 65 children is a fixture-only shape. The
    production graph does not use it, and this function does not write one.
    """
    found = []
    r65_mapped = observation.r65_status == "MAPPED" and observation.r65_child_count == 65
    if not r65_mapped:
        found.append("r65_unmapped")
    if observation.c27_status != "ACCEPTED":
        found.append("c27_unmet")
    if observation.trust_anchor_empty:
        found.append("trust_anchors_absent")
    if not observation.protected_corpus_accepted:
        found.append("protected_corpus_evidence_absent")
    if not observation.private_eval_frozen:
        found.append("private_evaluation_unfrozen")
    if not observation.foundation_selected:
        found.append("foundation_not_selected")
    if not observation.compute_qualified:
        found.append("compute_unqualified")
    if not observation.independent_review_accepted:
        found.append("independent_reviews_missing")
    if not observation.data_licensing_resolved:
        found.append("real_data_licensing_unresolved")
    if not observation.training_authorized:
        found.append("training_authorization_absent")
    return found


def _engine():
    path = ROOT / "scripts" / "acceptance" / "acceptance_engine.py"
    spec = importlib.util.spec_from_file_location("orneur_acceptance_engine_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("acceptance engine could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _empty_trust_file(path: Path) -> bool:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return False
    for value in payload.values():
        if value not in ("", 0, [], None):
            return False
    return True


def production_observation() -> Observation:
    """Read the committed register. This does not write it."""
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    by_id = {node["id"]: node for node in graph["nodes"]}
    children = [node_id for node_id in by_id if str(node_id).startswith("R65-")]
    eval_status = json.loads(EVAL_STATUS_PATH.read_text(encoding="utf-8"))
    authorizations = eval_status.get("authorizations") or {}
    return Observation(
        r65_status=by_id["R65"]["status"],
        r65_child_count=len(children),
        c27_status=by_id["C27"]["status"],
        trust_anchor_empty=all(_empty_trust_file(path) for path in TRUST_FILES),
        protected_corpus_accepted=False,
        private_eval_frozen=bool(eval_status.get("GENESIS_CAPABILITY_EVAL_V2_FROZEN")),
        foundation_selected=bool(authorizations.get("foundation_selection")),
        compute_qualified=False,
        independent_review_accepted=False,
        data_licensing_resolved=False,
        training_authorized=bool(authorizations.get("training")),
        counted=len(graph["denominator_pretraining_ids"]),
        numerator=int(graph.get("numerator_pretraining") or 0),
    )


def report(observation: Observation, accepted_ids: dict | None = None) -> dict:
    """Build a report. `execution_allowed` follows only an engine-accepted EXEC-1."""
    accepted_ids = dict(accepted_ids or {})
    blockers = blocker_codes(observation)
    execution_allowed = "EXEC-1" in accepted_ids and not blockers
    founder_authorized = "FINAL-2" in accepted_ids and not blockers
    return {
        "counted": observation.counted,
        "numerator": observation.numerator,
        "formally_accepted": sorted(accepted_ids),
        "blockers": blockers,
        "readiness_reportable": (
            not blockers and observation.counted > 0 and len(accepted_ids) == observation.counted
        ),
        "founder_authorized": founder_authorized,
        "execution_allowed": execution_allowed,
        "gate": "BLOCKED" if blockers else "BLOCKERS_CLEAR_NOT_ACCEPTED",
    }


def production_report() -> dict:
    """Report the committed repository. The ledger is evaluated, not edited."""
    engine = _engine()
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    trust = json.loads((ROOT / "docs/orneur/acceptance/reviewer_trust.json").read_text(encoding="utf-8"))
    root_state = json.loads((ROOT / "docs/orneur/acceptance/founder_root_keys.json").read_text(encoding="utf-8"))
    bootstrap = json.loads((ROOT / "docs/orneur/acceptance/BOOTSTRAP_ROOT_KEY.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((ROOT / "docs/orneur/acceptance/TRUST_CHECKPOINT.json").read_text(encoding="utf-8"))
    pin = json.loads((ROOT / "docs/orneur/acceptance/TRUST_CHECKPOINT_PIN.json").read_text(encoding="utf-8"))
    before = LEDGER_PATH.read_bytes()
    accepted = engine.evaluate(
        graph["nodes"],
        ledger,
        trust_snapshot=trust,
        root_state=root_state,
        bootstrap_root_key_hex=bootstrap.get("public_key_hex", ""),
        subject_sha="0" * 40,
        trust_checkpoint=checkpoint,
        pinned_checkpoint_hash=pin.get("pinned_checkpoint_hash", ""),
    )
    if LEDGER_PATH.read_bytes() != before:
        raise RuntimeError("readiness report changed the acceptance ledger")
    result = report(production_observation(), accepted)
    result["ledger_accepted_count"] = len(accepted)
    return result
