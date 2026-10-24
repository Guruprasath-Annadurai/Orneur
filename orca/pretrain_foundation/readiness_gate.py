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


def _ignored_identifiers(supplied: object) -> list[str]:
    """Copy caller identifiers for the audit trail. They are not authority."""
    if supplied is None:
        return []
    if isinstance(supplied, dict):
        return sorted(str(key) for key in supplied)
    if isinstance(supplied, (list, tuple)):
        return [str(item) for item in supplied]
    return ["UNREADABLE"]


def report(observation: Observation, accepted_ids: object = None) -> dict:
    """Synthetic observation report.

    Reproduced before this boundary: a cleared `Observation` plus a caller
    dict containing `EXEC-1` and `FINAL-2` made `execution_allowed` and
    `founder_authorized` true. This function no longer reads that dict as
    an acceptance result. `formally_accepted` stays empty.
    """
    blockers = blocker_codes(observation)
    return {
        "interface": "SYNTHETIC_OBSERVATION",
        "authorization_source": "none",
        "counted": observation.counted,
        "numerator": observation.numerator,
        "formally_accepted": [],
        "supplied_identifiers_ignored": _ignored_identifiers(accepted_ids),
        "blockers": blockers,
        "readiness_reportable": False,
        "founder_authorized": False,
        "execution_allowed": False,
        "gate": "BLOCKED" if blockers else "BLOCKERS_CLEAR_NOT_ACCEPTED",
    }


def _claims_for_engine_map(
    observation: Observation,
    accepted: object,
    *,
    pretraining_ids: tuple[str, ...] | list[str],
    known_ids: set[str],
) -> dict:
    """Interpret a map returned by `acceptance_engine.evaluate`.

    This helper is not an authorization API. `report()` does not call it.
    Only `production_report` and `report_evaluated` pass the object just
    returned by `evaluate`.
    """
    blockers = blocker_codes(observation)
    structural = None
    if not isinstance(accepted, dict):
        structural = "engine_result_not_a_map"
        accepted_map: dict = {}
    else:
        accepted_map = dict(accepted)
    unknown = sorted(set(accepted_map) - set(known_ids))
    missing = [item for item in pretraining_ids if item not in accepted_map]
    complete = (
        structural is None
        and not unknown
        and not missing
        and len(pretraining_ids) == observation.counted
        and observation.counted > 0
    )
    return {
        "formally_accepted": sorted(accepted_map),
        "unknown_identifiers": unknown,
        "missing_pretraining_ids": len(missing),
        "engine_map_complete": complete,
        "readiness_reportable": complete and not blockers,
        "founder_authorized": complete and not blockers and "FINAL-2" in accepted_map,
        "execution_allowed": complete and not blockers and "EXEC-1" in accepted_map,
        "structural_error": structural,
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
    subject_sha = "0" * 40
    try:
        accepted = engine.evaluate(
            graph["nodes"],
            ledger,
            trust_snapshot=trust,
            root_state=root_state,
            bootstrap_root_key_hex=bootstrap.get("public_key_hex", ""),
            subject_sha=subject_sha,
            trust_checkpoint=checkpoint,
            pinned_checkpoint_hash=pin.get("pinned_checkpoint_hash", ""),
        )
        engine_error = None
    except engine.AcceptanceRejected as exc:
        accepted = {}
        engine_error = exc.code
    if LEDGER_PATH.read_bytes() != before:
        raise RuntimeError("readiness report changed the acceptance ledger")
    known_ids = _known_requirement_ids(graph)
    claims = _claims_for_engine_map(
        production_observation(),
        accepted,
        pretraining_ids=tuple(graph["denominator_pretraining_ids"]),
        known_ids=known_ids,
    )
    result = report(production_observation())
    result["interface"] = "ACCEPTANCE_ENGINE"
    result["authorization_source"] = "acceptance_engine.evaluate"
    result["formally_accepted"] = claims["formally_accepted"]
    result["readiness_reportable"] = claims["readiness_reportable"]
    result["founder_authorized"] = claims["founder_authorized"]
    result["execution_allowed"] = claims["execution_allowed"]
    result["engine_error"] = engine_error
    result["ledger_accepted_count"] = len(accepted) if isinstance(accepted, dict) else 0
    return result


def _known_requirement_ids(graph: dict) -> set[str]:
    known = {node["id"] for node in graph["nodes"]}
    for key in (
        "denominator_pretraining_ids",
        "denominator_execution_ids",
        "denominator_post_training_ids",
        "denominator_application_ids",
    ):
        known.update(graph.get(key) or [])
    return known


def report_evaluated(
    records: object,
    *,
    subject_sha: str,
    observation: Observation,
    nodes: list,
    pretraining_ids: list[str] | tuple[str, ...],
    known_ids: set[str],
    trust_snapshot: dict,
    root_state: dict,
    bootstrap_root_key_hex: str,
    trust_checkpoint: dict,
    pinned_checkpoint_hash: str,
) -> dict:
    """Evaluate one in-memory ledger. This does not write the committed ledger.

    Caller-supplied acceptance maps are not an argument. Identifiers are
    read from ledger records and then only from `evaluate`'s return value.
    """
    result = report(observation)
    result["interface"] = "ACCEPTANCE_ENGINE"
    result["authorization_source"] = "acceptance_engine.evaluate"
    reasons: list[str] = []
    if not isinstance(records, list):
        reasons.append("ledger_not_a_list")
        records = []
    seen: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            reasons.append("record_not_object")
            continue
        requirement_id = record.get("requirement_id")
        if not requirement_id:
            reasons.append("missing_authority")
            continue
        if requirement_id in seen:
            reasons.append("duplicate_identifier")
        else:
            seen.append(str(requirement_id))
        if requirement_id not in known_ids:
            reasons.append("wrong_denominator_id")
        git_sha = record.get("git_sha")
        if isinstance(git_sha, str) and git_sha and git_sha != subject_sha:
            reasons.append("stale_evidence")
    engine = _engine()
    accepted: dict = {}
    engine_error = None
    if not reasons:
        try:
            accepted = engine.evaluate(
                nodes,
                records,
                trust_snapshot=trust_snapshot,
                root_state=root_state,
                bootstrap_root_key_hex=bootstrap_root_key_hex,
                subject_sha=subject_sha,
                trust_checkpoint=trust_checkpoint,
                pinned_checkpoint_hash=pinned_checkpoint_hash,
            )
        except engine.AcceptanceRejected as exc:
            engine_error = exc.code
            if exc.code == "UNPINNED_BOOTSTRAP":
                reasons.append("missing_authority")
            elif exc.code == "DUPLICATE":
                reasons.append("duplicate_identifier")
            elif exc.code in {"STALE", "WRONG_SHA"}:
                reasons.append("stale_evidence")
            elif exc.code == "UNKNOWN_REQUIREMENT":
                reasons.append("wrong_denominator_id")
            else:
                reasons.append("missing_authority")
    claims = _claims_for_engine_map(
        observation,
        accepted,
        pretraining_ids=pretraining_ids,
        known_ids=known_ids,
    )
    if reasons:
        claims = {
            **claims,
            "readiness_reportable": False,
            "founder_authorized": False,
            "execution_allowed": False,
            "engine_map_complete": False,
        }
    result.update(claims)
    result["refusal_reasons"] = reasons
    result["engine_error"] = engine_error
    result["execution_allowed"] = False if reasons else claims["execution_allowed"]
    result["founder_authorized"] = False if reasons else claims["founder_authorized"]
    result["readiness_reportable"] = False if reasons else claims["readiness_reportable"]
    return result
