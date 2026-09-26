"""Genesis Capability Eval V1 funnel and selection logic (pure, deterministic, CPU-only).

Pre-registered design, implemented so that its invariants are testable:

* Parameter count, release date, popularity and vendor benchmark claims are NEVER inputs to any stage.
* Stage 1 probes ALL Stage-0-compatible models under one explicit per-model resource cap.
* Stage 3 finalists are chosen from PRE-TRAINABILITY information only; trainability may not influence entry.
* No foundation may be selected until every finalist has completed the SAME trainability pilot.
* ``strict_contracts`` is report-only: it never gates and never ranks (system contracts belong to ORNEUR itself).
No stage authorizes spending, GPU use or training; the caps are planning constants.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from orca.eval.foundation_landscape import H100_USD_PER_HOUR

FUNNEL_VERSION = "genesis-capability-eval-v1-funnel/2"

FORBIDDEN_SELECTION_INPUTS = ("release_date", "parameter_count", "popularity", "vendor_benchmark_claims", "model_size_proxy")
REPORT_ONLY_CATEGORIES = ("strict_contracts", "multimodal_where_applicable", "discovery_quality", "cross_domain_transfer",
                          "latency", "cost")
RANKING_ORDER = ("verification", "evidence_use", "trainability", "cost")  # strict_contracts is deliberately absent

STAGE1_MAX_GPU_HOURS_PER_MODEL = 0.25
STAGE2_COST_CAP_USD = 40.0
STAGE3_MAX_FINALISTS = 3
STAGE3_COST_CAP_USD = 25.0
PILOT_PROTOCOL_ID = "genesis-trainability-pilot-v1"


def stage1_cap_usd(n_models: int) -> float:
    """Hard Stage-1 ceiling: every Stage-0-compatible model x the per-model GPU-hour cap x the persisted H100 rate."""
    return round(n_models * STAGE1_MAX_GPU_HOURS_PER_MODEL * H100_USD_PER_HOUR, 2)


def stage0_compatible(stage0: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Stage 0 keeps every model whose MEASURED CPU checks all passed. Nothing else is consulted."""
    return sorted(m for m, r in stage0.items() if r.get("all_checks_passed") is True)


def stage1_pool(compatible: Sequence[str]) -> list[str]:
    """The screening probe covers ALL Stage-0-compatible models: no size/family/recency pre-selection."""
    return sorted(compatible)


def confidently_below(upper95: float, floor: float) -> bool:
    return upper95 < floor


def stage1_survivors(results: Mapping[str, Mapping[str, Mapping[str, Any]]], floors: Mapping[str, float]) -> list[str]:
    """A model is dropped only if, on a gating category with enough power, the 95% upper bound is below its floor."""
    keep = []
    for model, cats in sorted(results.items()):
        dropped = False
        for cat, floor in floors.items():
            if cat in REPORT_ONLY_CATEGORIES:
                continue
            r = cats.get(cat)
            if r and not r.get("low_power") and confidently_below(float(r["upper95"]), floor):
                dropped = True
                break
        if not dropped:
            keep.append(model)
    return keep


def _cost_order(models: Mapping[str, Mapping[str, Any]]) -> list[str]:
    return sorted(models, key=lambda m: (float(models[m]["cost_usd"]), m))


def stage2_entrants(survivors: Mapping[str, Mapping[str, Any]], cap_usd: float = STAGE2_COST_CAP_USD) -> dict[str, Any]:
    """Admit every survivor when the projected total fits the cap. Otherwise apply the transparent resource gate:
    first the cheapest survivor of each architecture family (diversity), then remaining survivors by ascending
    projected cost then id, until the cap is consumed. Cost is an explicit resource gate, not a quality signal."""
    total = sum(float(v["cost_usd"]) for v in survivors.values())
    if total <= cap_usd:
        return {"entrants": sorted(survivors), "cost_cap_applied": False, "deferred_for_cost": []}
    chosen: list[str] = []
    spent = 0.0
    fams: dict[str, list[str]] = {}
    for m in _cost_order(survivors):
        fams.setdefault(str(survivors[m]["family"]), []).append(m)
    order = [ms[0] for _, ms in sorted(fams.items())] + [m for m in _cost_order(survivors)]
    for m in order:
        c = float(survivors[m]["cost_usd"])
        if m not in chosen and spent + c <= cap_usd:
            chosen.append(m)
            spent += c
    return {"entrants": sorted(chosen), "cost_cap_applied": True,
            "deferred_for_cost": sorted(set(survivors) - set(chosen))}


def _dominates(a: Mapping[str, Any], b: Mapping[str, Any], cats: Sequence[str]) -> bool:
    ge = all(a["capability"][c] >= b["capability"][c] for c in cats) and float(a["cost_usd"]) <= float(b["cost_usd"])
    gt = any(a["capability"][c] > b["capability"][c] for c in cats) or float(a["cost_usd"]) < float(b["cost_usd"])
    return ge and gt


def pareto_nondominated(finalists: Mapping[str, Mapping[str, Any]]) -> list[str]:
    cats = sorted(set.intersection(*(set(v["capability"]) for v in finalists.values()))) if finalists else []
    cats = [c for c in cats if c not in REPORT_ONLY_CATEGORIES and c != "trainability"]
    return sorted(m for m, v in finalists.items()
                  if not any(_dominates(o, v, cats) for k, o in finalists.items() if k != m))


def stage3_entrants(finalists: Mapping[str, Mapping[str, Any]], max_n: int = STAGE3_MAX_FINALISTS) -> list[str]:
    """Choose pilot finalists from PRE-TRAINABILITY information only (capability results, projected cost, family).

    Any ``trainability`` value present in the input is ignored by construction: it does not exist yet, and if it
    did it must not decide who gets to be measured. Order: Pareto-non-dominated set, then one per architecture
    family (ascending cost), then ascending cost, then id."""
    pool = {m: v for m, v in finalists.items() if m in set(pareto_nondominated(finalists))}
    fams: dict[str, list[str]] = {}
    for m in _cost_order(pool):
        fams.setdefault(str(pool[m]["family"]), []).append(m)
    order = [ms[0] for _, ms in sorted(fams.items(), key=lambda kv: (float(pool[kv[1][0]]["cost_usd"]), kv[0]))]
    order += [m for m in _cost_order(pool) if m not in order]
    return order[:max_n]


def selection_allowed(finalists: Sequence[str], pilots: Mapping[str, Mapping[str, Any]]) -> bool:
    """No foundation may be selected until EVERY finalist has completed the SAME trainability pilot."""
    if not finalists:
        return False
    return all(pilots.get(m, {}).get("status") == "COMPLETE" and pilots[m].get("protocol_id") == PILOT_PROTOCOL_ID
               for m in finalists)


def rank_finalists(results: Mapping[str, Mapping[str, Any]], pilots: Mapping[str, Mapping[str, Any]],
                   floors: Mapping[str, float]) -> dict[str, Any]:
    """Pre-registered selection rule. Returns NO_SELECTION_YET until selection_allowed; ties go to the owner.

    Inputs used: frozen floors, Pareto dominance, then verification -> evidence_use -> trainability -> cost.
    strict_contracts, parameter count, release date and popularity are not read."""
    finalists = sorted(results)
    if not selection_allowed(finalists, pilots):
        return {"status": "NO_SELECTION_YET", "reason": "not every finalist completed the same trainability pilot", "ranking": []}
    ok = {m: r for m, r in results.items()
          if all(r["capability"].get(c, 0.0) >= f for c, f in floors.items() if c not in REPORT_ONLY_CATEGORIES)}
    if not ok:
        return {"status": "NO_MODEL_QUALIFIES", "ranking": []}
    keep = pareto_nondominated(ok)

    def key(m: str) -> tuple:
        cap = ok[m]["capability"]
        return (-cap["verification"], -cap["evidence_use"], -float(pilots[m]["trainability_score"]), float(ok[m]["cost_usd"]))

    ranking = sorted(keep, key=key)
    ties = [m for m in ranking if key(m) == key(ranking[0])]
    return {"status": "OWNER_DECISION_REQUIRED_TIE" if len(ties) > 1 else "RANKED", "ranking": ranking, "tied_for_first": ties}


def funnel_spec() -> dict[str, Any]:
    return {
        "version": FUNNEL_VERSION,
        "forbidden_selection_inputs": list(FORBIDDEN_SELECTION_INPUTS),
        "stages": [
            {"stage": 0, "name": "CPU integrity and compatibility", "who": "ALL GENESIS_EVAL_ADMITTED models",
             "exit": "measured Stage-0 checks all passed", "gpu": False},
            {"stage": 1, "name": "small common screening probe", "who": "ALL Stage-0-compatible models",
             "max_gpu_hours_per_model": STAGE1_MAX_GPU_HOURS_PER_MODEL,
             "drop_rule": "only if the 95% upper bound is below a frozen floor on a gating category with sufficient power"},
            {"stage": 2, "name": "full capability eval", "who": "Stage-1 survivors", "cost_cap_usd": STAGE2_COST_CAP_USD,
             "over_cap_rule": "cheapest survivor per architecture family, then ascending projected cost then id (explicit resource gate)"},
            {"stage": 3, "name": "trainability pilot", "who": f"up to {STAGE3_MAX_FINALISTS} finalists chosen from PRE-TRAINABILITY criteria only",
             "cost_cap_usd": STAGE3_COST_CAP_USD, "protocol_id": PILOT_PROTOCOL_ID,
             "entry_order": "Pareto-non-dominated on capability and cost, then one per architecture family, then ascending cost, then id"},
        ],
        "selection_precondition": "every finalist completed the SAME trainability pilot",
        "ranking_order": list(RANKING_ORDER),
        "report_only_categories": list(REPORT_ONLY_CATEGORIES),
        "strict_contracts_role": "report-only recovery-cost signal; never a floor, never a ranking input",
        "cost_planning_usd": {"stage1_hard_cap_for_15_models": stage1_cap_usd(15), "stage2_cap": STAGE2_COST_CAP_USD,
                              "stage3_cap": STAGE3_COST_CAP_USD,
                              "kind": "PLANNING_ONLY_NOT_AUTHORIZATION"},
    }
