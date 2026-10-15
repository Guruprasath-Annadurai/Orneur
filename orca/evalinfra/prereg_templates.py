"""Validator for the machine-readable research PREREGISTRATION TEMPLATES (tracks C1, C2, C3) under docs/orneur/research/preregistration/.

These are DRAFT TEMPLATES. They are not frozen, not approved, hold no result, name no model, and authorize nothing. The validator enforces exactly that
(a template that claims to be frozen/approved, carries a result, selects a model or authorizes training/GPU/spend is INVALID here: freezing is done through
the evalinfra chain with a real approval, never by editing a template) plus the programme-wide rules from
docs/orneur/research/ORNEUR_DIFFERENTIATION_RESEARCH_PROGRAMME.md section 0.
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.evalinfra.stats_paired import MIN_RESAMPLES

TEMPLATE_SCHEMA = "orneur-research-prereg-template/1"
TRACKS = ("C1", "C2", "C3")
STATUS = "DRAFT_TEMPLATE_NOT_FROZEN_NOT_APPROVED"
REQUIRED_ARMS = ["B0", "B1", "B2", "T2"]
ZERO_TOLERANCE = [10, 14, 15, 17]
MAX_PROGRAMME_PRIMARY = 4
TOP_KEYS = frozenset({"schema_version", "track", "title", "status", "frozen", "approved", "approved_by", "frozen_at", "prereg_record_sha256", "analysis_plan_sha256",
                      "authorizes", "training_authorization", "no_result_exists", "results", "selected_model", "source_document", "banner", "hypothesis", "arms",
                      "effects_reported", "hidden_categories", "endpoints", "non_regression", "statistics", "failure_criteria", "negative_result_policy", "blockers",
                      "prior_art_to_survey_first", "placeholders_to_fill_before_freeze"})
OPTIONAL_KEYS = frozenset({"execution_environment", "candidate_workflows", "cost_model"})
ENDPOINT_KEYS = frozenset({"id", "kind", "treatment", "control", "metric", "threshold"})
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "docs/orneur/research/preregistration"


def _p(problems: list, cond, msg: str) -> None:
    if not cond:
        problems.append(msg)


def validate_template(doc, *, expected_track: str | None = None) -> list:
    """Problems (empty == valid draft template). Never raises."""
    try:
        return _validate(doc, expected_track)
    except Exception as e:
        return [f"validator error ({type(e).__name__}); refused"]


def _validate(doc, expected_track) -> list:
    if not isinstance(doc, dict):
        return ["template is not an object"]
    p: list = []
    keys = set(doc)
    _p(p, TOP_KEYS <= keys <= TOP_KEYS | OPTIONAL_KEYS, f"keys must be the required set plus at most {sorted(OPTIONAL_KEYS)}; missing {sorted(TOP_KEYS - keys)} extra {sorted(keys - TOP_KEYS - OPTIONAL_KEYS)}")
    if p:
        return p
    _p(p, doc["schema_version"] == TEMPLATE_SCHEMA, "schema_version")
    _p(p, doc["track"] in TRACKS and (expected_track is None or doc["track"] == expected_track), "track must be C1, C2 or C3 (and match the file)")
    # draft-only guarantees
    _p(p, doc["status"] == STATUS, f"status must be {STATUS!r} (a template is never frozen or approved)")
    _p(p, doc["frozen"] is False and doc["approved"] is False, "frozen and approved must both be false")
    _p(p, doc["approved_by"] is None and doc["frozen_at"] is None and doc["prereg_record_sha256"] is None and doc["analysis_plan_sha256"] is None,
       "approved_by / frozen_at / prereg_record_sha256 / analysis_plan_sha256 must be null in a template")
    _p(p, doc["authorizes"] == [], "a template authorizes nothing (authorizes must be [])")
    _p(p, doc["training_authorization"] == "NOT_AUTHORIZED", "training_authorization must be NOT_AUTHORIZED")
    _p(p, doc["no_result_exists"] is True and doc["results"] == [], "a template carries no result")
    _p(p, doc["selected_model"] is None, "no model may be selected in a template")
    _p(p, isinstance(doc["banner"], str) and "NOT FROZEN" in doc["banner"] and "NOT APPROVED" in doc["banner"], "banner must state NOT FROZEN / NOT APPROVED")
    _p(p, isinstance(doc["placeholders_to_fill_before_freeze"], list) and bool(doc["placeholders_to_fill_before_freeze"]), "placeholders_to_fill_before_freeze must list what is still open")
    # arms
    a = doc["arms"]
    _p(p, isinstance(a, dict) and a.get("required") == REQUIRED_ARMS and a.get("numbering") == {"B0": 1, "B1": 2, "B2": 3, "T2": 4}, "arms.required must be B0,B1,B2,T2 with numbering 1..4")
    _p(p, isinstance(a, dict) and a.get("primary_comparison") == {"treatment": "T2", "control": "B2"}, "primary comparison must be T2 (arm 4) vs B2 (arm 3)")
    _p(p, isinstance(a, dict) and isinstance(a.get("identity_rule"), str) and "byte-identical" in a["identity_rule"], "arms.identity_rule must state the byte-identical system requirement")
    _p(p, isinstance(doc["effects_reported"], list) and len(doc["effects_reported"]) == 3, "effects_reported must list the three arm-labelled effects")
    # hypothesis
    h = doc["hypothesis"]
    mde = h.get("minimum_detectable_effect") if isinstance(h, dict) else None
    _p(p, isinstance(h, dict) and isinstance(h.get("id"), str) and isinstance(mde, dict) and isinstance(mde.get("absolute_points"), (int, float)) and 0 < mde["absolute_points"] < 1,
       "hypothesis needs an id and a minimum_detectable_effect in (0, 1) fixed before any data")
    # endpoints
    eps = doc["endpoints"]
    ok_eps = isinstance(eps, list) and bool(eps) and all(isinstance(e, dict) and ENDPOINT_KEYS <= set(e) for e in eps)
    _p(p, ok_eps, "endpoints must be a non-empty list of objects with id/kind/treatment/control/metric/threshold")
    if ok_eps:
        _p(p, len({e["id"] for e in eps}) == len(eps), "endpoint ids must be unique")
        _p(p, all(e["kind"] in ("PRIMARY", "EXPLORATORY") for e in eps), "every endpoint is labelled PRIMARY or EXPLORATORY")
        prim = [e for e in eps if e["kind"] == "PRIMARY"]
        _p(p, 1 <= len(prim) <= 2, "a track declares 1 primary plus at most 1 safety primary")
        _p(p, sum(1 for e in prim if e.get("safety_endpoint")) <= 1, "at most one safety endpoint per track")
        _p(p, all(isinstance(e["threshold"], (int, float)) and e["threshold"] >= 0 for e in prim), "every PRIMARY endpoint needs a numeric threshold (QUAL-3)")
        _p(p, all(e["treatment"] == "T2" and e["control"] == "B2" for e in prim), "every PRIMARY endpoint is the T2-vs-B2 comparison")
        _p(p, all(e["threshold"] is None or isinstance(e["threshold"], (int, float)) for e in eps), "threshold must be null or numeric")
    nr = doc["non_regression"]
    _p(p, isinstance(nr, dict) and nr.get("zero_tolerance_categories") == ZERO_TOLERANCE, f"non_regression.zero_tolerance_categories must be {ZERO_TOLERANCE}")
    # statistics
    s = doc["statistics"]
    _p(p, isinstance(s, dict) and isinstance(s.get("bootstrap_resamples"), int) and s["bootstrap_resamples"] >= MIN_RESAMPLES, f"bootstrap_resamples must be >= {MIN_RESAMPLES}")
    _p(p, isinstance(s, dict) and s.get("min_training_seeds", 0) >= 3, "min_training_seeds must be >= 3")
    _p(p, isinstance(s, dict) and s.get("min_items_per_primary_endpoint", 0) >= 600, "min_items_per_primary_endpoint must be >= 600")
    _p(p, isinstance(s, dict) and s.get("design") and isinstance(s.get("multiplicity"), dict) and s["multiplicity"].get("method") == "holm", "paired design and Holm multiplicity required")
    _p(p, isinstance(s, dict) and set(s.get("ci_methods", [])) == {"percentile", "bca"}, "ci_methods must be percentile and bca")
    for k in ("hidden_categories", "failure_criteria", "blockers"):
        _p(p, isinstance(doc[k], list) and bool(doc[k]), f"{k} must be non-empty")
    _p(p, any("founder authorization" in b for b in doc["blockers"] if isinstance(b, str)), "blockers must name the founder-authorization dependency")
    return p


def validate_programme(docs: dict) -> list:
    """Cross-template rules: all three tracks present, each valid, and at most 4 PRIMARY endpoints programme-wide."""
    p: list = []
    _p(p, set(docs) == set(TRACKS), f"templates for exactly {TRACKS} are required")
    n = 0
    for t, d in docs.items():
        sub = validate_template(d, expected_track=t)
        p += [f"{t}: {x}" for x in sub]
        if not sub:
            n += sum(1 for e in d["endpoints"] if e["kind"] == "PRIMARY")
    _p(p, n <= MAX_PROGRAMME_PRIMARY, f"programme-wide PRIMARY endpoints ({n}) exceed {MAX_PROGRAMME_PRIMARY}")
    return p


def load_templates(directory=None) -> dict:
    d = Path(directory) if directory else DEFAULT_DIR
    out = {}
    for t in TRACKS:
        files = sorted(d.glob(f"{t}_*.json"))
        if len(files) != 1:
            raise FileNotFoundError(f"expected exactly one {t}_*.json in {d}")
        out[t] = json.loads(files[0].read_text())
    return out
