"""
Genesis Frontier statistical contract (Phase 21B.4.9/.1/.2 methodology,
encoded as tested, executable code in Phase 21B.4.10, corrected in
Phase 21B.4.10.1).

The Phase 21B.4.9.x documents (`docs/orneur/phase-21/
GENESIS_FRONTIER_SCORING_CONTRACT.md` and `GENESIS_FRONTIER_DECISION_
GATES.md`) locked a paired-bootstrap statistical framework and five
numeric margins BEFORE any candidate result exists. This module is the
single source of truth for those numbers and the classification rules
built on them -- they must never be duplicated as scattered magic
numbers elsewhere in the codebase. No candidate data is used here; every
test exercising this module uses synthetic fixtures only.

Nothing in this module evaluates a real Genesis candidate, executes
`genesis-eval-v1`, or authors any private holdout content -- it exists
so that WHEN a future, separately-authorized execution phase produces
real per-task scores, the classification rules those scores are judged
against are already implemented and tested, not improvised at that
point.

Phase 21B.4.10.1 (contract version bumped v1 -> v2) closed four gaps an
independent audit found in the v1 implementation:

1. THE ESTIMAND: v1's bootstrap resampled StatisticalUnits but then
   flattened every resampled unit's task_ids into one big list and took
   ONE overall mean -- meaning a 10-task cluster contributed 10x the
   weight of a singleton unit, exactly defeating the purpose of
   `statistical_unit_id` (weighting BY unit, not by raw task count). Now
   each unit contributes exactly ONE unit-level mean (`mean(scores for
   tasks in that unit)`), and the bootstrap resamples and averages those
   unit-level means/differences -- "STATISTICAL UNIT, NOT RAW TASK
   COUNT, IS THE INFERENCE WEIGHT."
2. VALIDATION: a new `validate_statistical_units()` fails closed on
   empty unit IDs, duplicate unit IDs, a task_id appearing in more than
   one unit, a duplicate task_id inside one unit, a unit's task missing
   from either score dict, a NaN/infinite score, an out-of-[0,1] score,
   and (when an expected task set is supplied) any task silently omitted
   from the units -- closing the "obtain a favorable CI via a
   conveniently incomplete subset" gap.
3. THE ACTUAL COMPARATORS: `bootstrap_frontier_median_ci()`,
   `bootstrap_best_reference_ci()`, and `bootstrap_control_superiority_ci()`
   now recompute the reference median / strongest reference / strongest
   control INSIDE each bootstrap resample, over the SAME sampled units
   the candidate is scored on -- never a precomputed per-task
   median/max, which would silently invent a synthetic "model" no real
   reference/control actually represents.
4. QUORUM HARDENING: the frontier reference and control quorum
   validators now check identity against a REGISTERED set locked in
   this module (name -> organization for the six frontier references;
   the three control names), rejecting unknown/duplicate/misattributed
   entries rather than trusting whatever tuples a caller supplies.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from enum import Enum

FRONTIER_STATISTICAL_CONTRACT_VERSION = "genesis-frontier-stats-v2"

# Phase 21B.4.10.1 migration note: v1's bootstrap implementation
# (task-count-weighted, not unit-weighted) is SUPERSEDED, not
# deprecated-with-a-shim. No real candidate/reference/control result
# has ever been produced under v1 (Phase 21B.4.10's own report confirms
# zero real evaluations occurred) -- there is therefore no historical
# benchmark result anywhere that needs conversion or re-interpretation.
# v1's constants (the five delta margins, confidence level, resample
# count) are UNCHANGED; only the bootstrap algorithm's internal
# weighting and the addition of dedicated comparator functions changed.

# ── Locked constants (GENESIS_FRONTIER_SCORING_CONTRACT.md §5.2, §5.4, §8.3) ──

CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_RESAMPLES = 10_000

DELTA_FRONTIER = 0.08
DELTA_BEST_REFERENCE = 0.20
DELTA_CONTROL_SUPERIORITY = 0.10
DELTA_TIE = 0.03
DELTA_QUANTIZATION = 0.05

JUDGE_DISAGREEMENT_THRESHOLD = 0.15

STABILITY_REPEAT_COUNT = 3

# ── Quorum constants + registered identities (GENESIS_FRONTIER_DECISION_
# GATES.md §"Frontier reference quorum" / §"Control comparator quorum") ──

FRONTIER_TARGET_REFERENCES = 6
FRONTIER_REFERENCE_QUORUM_MIN = 4
FRONTIER_REFERENCE_QUORUM_MIN_LINEAGES = 3

# Locked in code (Phase 21B.4.10.1): the exact six registered frontier
# references and their organizations, exactly as registered in
# docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json. A
# caller can no longer satisfy quorum with arbitrary/fabricated
# reference names.
REGISTERED_FRONTIER_REFERENCES: dict[str, str] = {
    "DeepSeek V4.1-Flash": "DeepSeek AI",
    "GLM-5.3 (flagship)": "Zhipu AI / Z.ai",
    "Mistral Large 3": "Mistral AI",
    "MiniMax M3": "MiniMax",
    "Qwen3.8-Max": "Alibaba",
    "Kimi K3": "Moonshot AI",
}

CONTROL_TARGET_SET = ("Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4")
CONTROL_QUORUM_REQUIRED = len(CONTROL_TARGET_SET)  # all 3, no partial quorum


class Classification(str, Enum):
    """Every possible classifier outcome across all five locked checks.
    A given classifier function only ever returns a subset of these --
    see each function's docstring."""
    NON_INFERIOR = "NON_INFERIOR"
    MATERIAL_GAP = "MATERIAL_GAP"
    CEILING_NONINFERIOR = "CEILING_NONINFERIOR"
    DRAMATICALLY_BEHIND_CEILING = "DRAMATICALLY_BEHIND_CEILING"
    SUBSTANTIALLY_SUPERIOR = "SUBSTANTIALLY_SUPERIOR"
    NOT_SATISFIED = "NOT_SATISFIED"
    PRACTICALLY_EQUIVALENT = "PRACTICALLY_EQUIVALENT"
    A_MEANINGFULLY_AHEAD = "A_MEANINGFULLY_AHEAD"
    B_MEANINGFULLY_AHEAD = "B_MEANINGFULLY_AHEAD"
    CERTIFIED_FOR_SCREENING = "CERTIFIED_FOR_SCREENING"
    NOT_CERTIFIED = "NOT_CERTIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


class QuorumStatus(str, Enum):
    QUORUM_MET = "QUORUM_MET"
    REFERENCE_SET_INCOMPLETE = "REFERENCE_SET_INCOMPLETE"
    CONTROL_SET_INCOMPLETE = "CONTROL_SET_INCOMPLETE"


class StatisticalUnitValidationError(ValueError):
    """A statistical-unit/score input to the bootstrap or a quorum
    validator fails closed: an empty or duplicate unit ID, a task_id
    claimed by more than one unit, a duplicate task_id inside one unit,
    a unit task missing from a required score dict, a NaN/infinite or
    out-of-[0,1] score, a task silently omitted relative to an expected
    task set, or (for the quorum validators) an unknown/duplicate/
    misattributed reference or control name. Never silently tolerated --
    a caller cannot obtain a favorable result by supplying a
    conveniently incomplete or fabricated input."""


@dataclass(frozen=True)
class ConfidenceInterval:
    """A two-sided confidence interval for a paired difference `D`.
    `lower` and `upper` are on the same normalized [-1,1] scale as `D`
    itself (both terms of `D` are normalized to [0,1] before differencing
    -- GENESIS_FRONTIER_SCORING_CONTRACT.md §5.1)."""
    lower: float
    upper: float

    def __post_init__(self):
        if self.lower > self.upper:
            raise ValueError(f"lower bound {self.lower} exceeds upper bound {self.upper}")


@dataclass(frozen=True)
class StatisticalUnit:
    """A cluster of one or more task_ids that must be resampled TOGETHER
    in the paired bootstrap (Phase 21B.4.10 §6 audit finding): task
    variants sharing a common scenario, source document, repository,
    base prompt/template, or generated fixture are NOT independent
    observations, and bootstrapping them as if they were separate tasks
    would understate the true resampling variance. If a task genuinely
    stands alone, its `statistical_unit_id` equals its own `task_id` and
    `task_ids` is the length-1 tuple `(task_id,)` -- this is the default
    produced by `independent_units()` below.

    Phase 21B.4.10.1: a unit's contribution to the bootstrap is always
    ONE unit-level mean, regardless of how many task_ids it contains --
    see the module docstring's "THE ESTIMAND" fix."""
    statistical_unit_id: str
    task_ids: tuple[str, ...]

    def __post_init__(self):
        if not self.task_ids:
            raise ValueError(f"StatisticalUnit {self.statistical_unit_id!r} has no task_ids")


def independent_units(task_ids: list[str]) -> list[StatisticalUnit]:
    """The default case: every task is its own statistical unit
    (`statistical_unit_id == task_id`). Use this only when the tasks are
    genuinely independent observations -- see `clustered_units()` for
    tasks that share a scenario/template/source family."""
    return [StatisticalUnit(statistical_unit_id=tid, task_ids=(tid,)) for tid in task_ids]


def clustered_units(clusters: dict[str, list[str]]) -> list[StatisticalUnit]:
    """Builds statistical units from an explicit cluster map:
    `{statistical_unit_id: [task_id, ...]}`. All tasks sharing a
    `statistical_unit_id` are resampled together, as one unit, in
    `paired_bootstrap_ci()` -- never independently. This is how a future
    holdout's variant families (Phase 21B.4.10 §6, `GENESIS_FRONTIER_
    HOLDOUT_SPEC.md`'s `statistical_unit_id` requirement) plug into the
    bootstrap. No private holdout tasks are authored by this module."""
    return [StatisticalUnit(statistical_unit_id=uid, task_ids=tuple(tids)) for uid, tids in clusters.items()]


def validate_statistical_units(
    units: list[StatisticalUnit],
    score_dicts: list[dict[str, float]],
    *,
    expected_task_ids: frozenset[str] | None = None,
) -> None:
    """Phase 21B.4.10.1 §2: fails closed on every malformed input before
    any bootstrap runs. `score_dicts` is every score mapping the caller
    intends to use with `units` (e.g. `[candidate_scores,
    comparator_scores]`, or `[candidate_scores, *reference_scores.values()]`)
    -- every unit's task_ids must be present, with a finite score in
    `[0,1]`, in EVERY supplied score dict.

    Raises `StatisticalUnitValidationError` on:
      - an empty `statistical_unit_id`;
      - a duplicate `statistical_unit_id`;
      - a task_id claimed by more than one unit (overlap);
      - a duplicate task_id inside one unit;
      - a unit's task_id missing from any supplied score dict;
      - a NaN or infinite score;
      - a score outside `[0,1]`;
      - (when `expected_task_ids` is supplied) the units' combined
        task_id set disagreeing with it in either direction -- a
        silently omitted OR an unexpected extra task."""
    if not units:
        raise StatisticalUnitValidationError("no statistical units provided")

    seen_unit_ids: set[str] = set()
    seen_task_ids: set[str] = set()
    all_task_ids: set[str] = set()

    for unit in units:
        if not unit.statistical_unit_id:
            raise StatisticalUnitValidationError("a StatisticalUnit has an empty statistical_unit_id")
        if unit.statistical_unit_id in seen_unit_ids:
            raise StatisticalUnitValidationError(f"duplicate statistical_unit_id: {unit.statistical_unit_id!r}")
        seen_unit_ids.add(unit.statistical_unit_id)

        unit_task_seen: set[str] = set()
        for tid in unit.task_ids:
            if tid in unit_task_seen:
                raise StatisticalUnitValidationError(
                    f"duplicate task_id {tid!r} inside statistical unit {unit.statistical_unit_id!r}"
                )
            unit_task_seen.add(tid)
            if tid in seen_task_ids:
                raise StatisticalUnitValidationError(
                    f"task_id {tid!r} appears in more than one statistical unit -- a task belongs to "
                    "exactly one unit."
                )
            seen_task_ids.add(tid)
            all_task_ids.add(tid)

            for scores in score_dicts:
                if tid not in scores:
                    raise StatisticalUnitValidationError(
                        f"task_id {tid!r} (unit {unit.statistical_unit_id!r}) is missing from a required "
                        "score dict."
                    )
                value = scores[tid]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise StatisticalUnitValidationError(f"task_id {tid!r} has a non-numeric score: {value!r}")
                if math.isnan(value) or math.isinf(value):
                    raise StatisticalUnitValidationError(f"task_id {tid!r} has a NaN/infinite score: {value!r}")
                if value < 0.0 or value > 1.0:
                    raise StatisticalUnitValidationError(
                        f"task_id {tid!r} has a score {value!r} outside the required [0,1] range."
                    )

    if expected_task_ids is not None:
        missing = expected_task_ids - all_task_ids
        unexpected = all_task_ids - expected_task_ids
        if missing or unexpected:
            problems = []
            if missing:
                problems.append(f"missing {len(missing)} expected task(s): {sorted(missing)[:10]}")
            if unexpected:
                problems.append(f"{len(unexpected)} unexpected task(s) not in the expected set: {sorted(unexpected)[:10]}")
            raise StatisticalUnitValidationError(
                "statistical units do not exactly cover the expected task set -- " + "; ".join(problems)
            )


def _unit_means(units: list[StatisticalUnit], scores: dict[str, float]) -> list[float]:
    """One mean per unit, in the same order as `units` -- this is the
    per-unit "observation" the bootstrap resamples. A 10-task cluster
    and a 1-task singleton each contribute exactly one value here."""
    return [statistics.fmean(scores[tid] for tid in unit.task_ids) for unit in units]


def _percentile_ci(diffs: list[float], confidence: float) -> ConfidenceInterval:
    diffs = sorted(diffs)
    resamples = len(diffs)
    alpha = 1.0 - confidence
    lower_idx = max(0, min(int((alpha / 2) * resamples), resamples - 1))
    upper_idx = max(0, min(int((1 - alpha / 2) * resamples) - 1, resamples - 1))
    if upper_idx < lower_idx:
        upper_idx = lower_idx
    return ConfidenceInterval(lower=diffs[lower_idx], upper=diffs[upper_idx])


def _resolved_rng(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


def paired_bootstrap_ci(
    candidate_scores: dict[str, float],
    comparator_scores: dict[str, float],
    units: list[StatisticalUnit],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE_LEVEL,
    rng: random.Random | None = None,
    expected_task_ids: frozenset[str] | None = None,
) -> ConfidenceInterval:
    """The two-series paired-bootstrap-over-statistical-units
    implementation (GENESIS_FRONTIER_SCORING_CONTRACT.md §5.2), used for
    the pairwise-finalist tie region and the quantization regression
    test. For the frontier/best-reference/control comparators, use the
    dedicated `bootstrap_frontier_median_ci()` / `bootstrap_best_
    reference_ci()` / `bootstrap_control_superiority_ci()` below instead
    -- those recompute their comparator INSIDE each resample, which this
    two-series function cannot do (it only ever compares exactly two
    series).

    `candidate_scores` and `comparator_scores` map task_id -> a score
    already normalized to [0,1] (§5.1 -- normalization happens before
    this function is called, never inside it).

    Phase 21B.4.10.1 correction (THE ESTIMAND): each `StatisticalUnit`
    contributes exactly ONE unit-level mean per series
    (`unit_score = mean(scores for tasks in that unit)`), computed ONCE
    before resampling begins. Each bootstrap resample draws unit indices
    WITH REPLACEMENT and averages the PRECOMPUTED unit-level differences
    (`unit_difference = candidate_unit_score - comparator_unit_score`)
    for the sampled units -- a unit is never re-expanded into its raw
    task_ids and flat-averaged, which would let a large cluster
    dominate the estimate in proportion to its task count rather than
    contributing the same weight as a singleton unit.
    STATISTICAL UNIT, NOT RAW TASK COUNT, IS THE INFERENCE WEIGHT.

    The returned interval is the `[alpha/2, 1-alpha/2]` percentile
    interval of the resample distribution (percentile bootstrap method).
    `rng` defaults to an unseeded `random.Random()` for real use;
    callers (including this module's own tests) pass a seeded
    `random.Random(seed)` for reproducibility."""
    validate_statistical_units(units, [candidate_scores, comparator_scores], expected_task_ids=expected_task_ids)
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")

    generator = _resolved_rng(rng)
    n_units = len(units)
    cand_unit_means = _unit_means(units, candidate_scores)
    comp_unit_means = _unit_means(units, comparator_scores)
    unit_diffs = [c - r for c, r in zip(cand_unit_means, comp_unit_means)]

    diffs: list[float] = []
    for _ in range(resamples):
        sampled = [unit_diffs[generator.randrange(n_units)] for _ in range(n_units)]
        diffs.append(statistics.fmean(sampled))

    return _percentile_ci(diffs, confidence)


def bootstrap_frontier_median_ci(
    candidate_scores: dict[str, float],
    reference_scores_by_name: dict[str, dict[str, float]],
    units: list[StatisticalUnit],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE_LEVEL,
    rng: random.Random | None = None,
    expected_task_ids: frozenset[str] | None = None,
) -> ConfidenceInterval:
    """Phase 21B.4.10.1 §3: the ACTUAL frontier-median comparator. For
    EVERY bootstrap resample: (1) resample statistical units; (2) take
    the candidate's mean over the sampled units; (3) take EACH available
    registered reference's mean over the SAME sampled units; (4) take
    the median of those reference-level means; (5) store `D_frontier =
    candidate_mean - frontier_reference_median`. Never a precomputed
    per-task median computed once outside the resampling loop -- that
    would not propagate reference-side sampling uncertainty into the
    interval at all.

    `reference_scores_by_name` maps reference_name -> {task_id: score}
    for every reference to include in this resample's median (callers
    are responsible for only including references that pass quorum
    requirements elsewhere -- this function performs no quorum check
    itself, only the arithmetic)."""
    if not reference_scores_by_name:
        raise ValueError("no reference scores provided -- cannot compute a frontier median")
    validate_statistical_units(
        units, [candidate_scores, *reference_scores_by_name.values()], expected_task_ids=expected_task_ids,
    )
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")

    generator = _resolved_rng(rng)
    n_units = len(units)
    cand_unit_means = _unit_means(units, candidate_scores)
    ref_unit_means = {name: _unit_means(units, scores) for name, scores in reference_scores_by_name.items()}

    diffs: list[float] = []
    for _ in range(resamples):
        idxs = [generator.randrange(n_units) for _ in range(n_units)]
        cand_mean = statistics.fmean(cand_unit_means[i] for i in idxs)
        ref_means_this_resample = [statistics.fmean(means[i] for i in idxs) for means in ref_unit_means.values()]
        median_ref = statistics.median(ref_means_this_resample)
        diffs.append(cand_mean - median_ref)

    return _percentile_ci(diffs, confidence)


def bootstrap_best_reference_ci(
    candidate_scores: dict[str, float],
    reference_scores_by_name: dict[str, dict[str, float]],
    units: list[StatisticalUnit],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE_LEVEL,
    rng: random.Random | None = None,
    expected_task_ids: frozenset[str] | None = None,
) -> ConfidenceInterval:
    """Phase 21B.4.10.1 §4: the ACTUAL best-reference (ceiling-guard)
    comparator. For every resample, selects the STRONGEST reference's
    mean FOR THAT RESAMPLE (never `max()` over per-task scores, which
    would synthesize a "model" no real reference represents by picking
    the best-performing reference independently on every task) and
    stores `D_best = candidate_mean - strongest_reference_mean_this_resample`."""
    if not reference_scores_by_name:
        raise ValueError("no reference scores provided -- cannot compute a best-reference comparator")
    validate_statistical_units(
        units, [candidate_scores, *reference_scores_by_name.values()], expected_task_ids=expected_task_ids,
    )
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")

    generator = _resolved_rng(rng)
    n_units = len(units)
    cand_unit_means = _unit_means(units, candidate_scores)
    ref_unit_means = {name: _unit_means(units, scores) for name, scores in reference_scores_by_name.items()}

    diffs: list[float] = []
    for _ in range(resamples):
        idxs = [generator.randrange(n_units) for _ in range(n_units)]
        cand_mean = statistics.fmean(cand_unit_means[i] for i in idxs)
        ref_means_this_resample = [statistics.fmean(means[i] for i in idxs) for means in ref_unit_means.values()]
        strongest_ref = max(ref_means_this_resample)
        diffs.append(cand_mean - strongest_ref)

    return _percentile_ci(diffs, confidence)


def bootstrap_control_superiority_ci(
    candidate_scores: dict[str, float],
    control_scores_by_name: dict[str, dict[str, float]],
    units: list[StatisticalUnit],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE_LEVEL,
    rng: random.Random | None = None,
    expected_task_ids: frozenset[str] | None = None,
) -> ConfidenceInterval:
    """Phase 21B.4.10.1 §5: the ACTUAL strongest-control comparator,
    mirroring `bootstrap_best_reference_ci()` -- for every resample,
    selects the strongest of the (up to three) registered controls'
    means FOR THAT RESAMPLE, never a precomputed per-task maximum."""
    if not control_scores_by_name:
        raise ValueError("no control scores provided -- cannot compute a control-superiority comparator")
    validate_statistical_units(
        units, [candidate_scores, *control_scores_by_name.values()], expected_task_ids=expected_task_ids,
    )
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")

    generator = _resolved_rng(rng)
    n_units = len(units)
    cand_unit_means = _unit_means(units, candidate_scores)
    control_unit_means = {name: _unit_means(units, scores) for name, scores in control_scores_by_name.items()}

    diffs: list[float] = []
    for _ in range(resamples):
        idxs = [generator.randrange(n_units) for _ in range(n_units)]
        cand_mean = statistics.fmean(cand_unit_means[i] for i in idxs)
        control_means_this_resample = [statistics.fmean(means[i] for i in idxs) for means in control_unit_means.values()]
        strongest_control = max(control_means_this_resample)
        diffs.append(cand_mean - strongest_control)

    return _percentile_ci(diffs, confidence)


# ── Locked classifiers (pure functions over a ConfidenceInterval only) ──


def classify_frontier_gap(ci: ConfidenceInterval) -> Classification:
    """D = candidate_score - frontier_reference_median_score (from
    `bootstrap_frontier_median_ci()`). GENESIS_FRONTIER_DECISION_GATES.md
    §"Frontier gap metric"."""
    if ci.lower >= -DELTA_FRONTIER:
        return Classification.NON_INFERIOR
    if ci.upper < -DELTA_FRONTIER:
        return Classification.MATERIAL_GAP
    return Classification.INCONCLUSIVE


def classify_best_reference(ci: ConfidenceInterval) -> Classification:
    """D = candidate_score - strongest_reference_score (from
    `bootstrap_best_reference_ci()`). GENESIS_FRONTIER_DECISION_GATES.md
    §"Best-reference ceiling guard" -- three states; INCONCLUSIVE does
    NOT pass the ceiling guard (never resolves in the candidate's
    favor)."""
    if ci.lower >= -DELTA_BEST_REFERENCE:
        return Classification.CEILING_NONINFERIOR
    if ci.upper < -DELTA_BEST_REFERENCE:
        return Classification.DRAMATICALLY_BEHIND_CEILING
    return Classification.INCONCLUSIVE


def classify_control_superiority(ci: ConfidenceInterval) -> Classification:
    """D = candidate_score - strongest_control_score (from
    `bootstrap_control_superiority_ci()`). GENESIS_FRONTIER_DECISION_GATES.md
    §"Control superiority" -- no separate INCONCLUSIVE state: this is
    one of several AND-ed conditions in the frontier-class threshold, so
    anything short of SUBSTANTIALLY_SUPERIOR simply means the condition
    is not satisfied."""
    if ci.lower >= DELTA_CONTROL_SUPERIORITY:
        return Classification.SUBSTANTIALLY_SUPERIOR
    return Classification.NOT_SATISFIED


def classify_pairwise_finalist(ci: ConfidenceInterval) -> Classification:
    """D = A_score - B_score. GENESIS_FRONTIER_SCORING_CONTRACT.md
    §5.5 -- the exact, gap-free four-way partition (Phase 21B.4.9.2
    correction). Locked worked examples this function must reproduce
    exactly: [+0.04,+0.10]->A_MEANINGFULLY_AHEAD; [-0.10,-0.04]->
    B_MEANINGFULLY_AHEAD; [+0.01,+0.04]->INCONCLUSIVE;
    [-0.02,+0.02]->PRACTICALLY_EQUIVALENT; [-0.05,+0.01]->INCONCLUSIVE."""
    if ci.lower >= -DELTA_TIE and ci.upper <= DELTA_TIE:
        return Classification.PRACTICALLY_EQUIVALENT
    if ci.lower > DELTA_TIE:
        return Classification.A_MEANINGFULLY_AHEAD
    if ci.upper < -DELTA_TIE:
        return Classification.B_MEANINGFULLY_AHEAD
    return Classification.INCONCLUSIVE


def classify_quantization(ci: ConfidenceInterval) -> Classification:
    """D = native_score - quantized_score.
    GENESIS_FRONTIER_SCORING_CONTRACT.md §8.3 -- Round-A precision is
    CERTIFIED_FOR_SCREENING only if the upper bound is within the
    acceptable-degradation margin; otherwise NOT_CERTIFIED (which
    escalates that category to a higher-precision screening
    configuration -- it never disqualifies the candidate outright)."""
    if ci.upper <= DELTA_QUANTIZATION:
        return Classification.CERTIFIED_FOR_SCREENING
    return Classification.NOT_CERTIFIED


# ── Quorum validators (Phase 21B.4.10.1: hardened against fabricated identities) ──


def validate_frontier_reference_quorum(available_references: list[tuple[str, str]]) -> QuorumStatus:
    """`available_references`: a list of (reference_name, organization)
    pairs for references successfully evaluated on the shared task set
    for one critical category.

    Phase 21B.4.10.1 hardening: every name/organization pair is checked
    against the REGISTERED_FRONTIER_REFERENCES set locked in this
    module -- an unknown reference name, a duplicate reference name, or
    a known name paired with the wrong organization all raise
    `StatisticalUnitValidationError` rather than silently counting
    toward quorum. Only once every entry is confirmed genuine does this
    function check: at least FRONTIER_REFERENCE_QUORUM_MIN (4) UNIQUE
    registered references available, spanning at least
    FRONTIER_REFERENCE_QUORUM_MIN_LINEAGES (3) distinct organizations."""
    seen: dict[str, int] = {}
    for name, org in available_references:
        if name not in REGISTERED_FRONTIER_REFERENCES:
            raise StatisticalUnitValidationError(
                f"unknown frontier reference {name!r} is not part of the registered six-reference set: "
                f"{sorted(REGISTERED_FRONTIER_REFERENCES)}"
            )
        expected_org = REGISTERED_FRONTIER_REFERENCES[name]
        if org != expected_org:
            raise StatisticalUnitValidationError(
                f"frontier reference {name!r} was supplied with organization {org!r}, but the registered "
                f"organization for this reference is {expected_org!r}."
            )
        seen[name] = seen.get(name, 0) + 1

    duplicates = sorted(name for name, count in seen.items() if count > 1)
    if duplicates:
        raise StatisticalUnitValidationError(f"duplicate frontier reference(s) counted toward quorum: {duplicates}")

    if len(seen) < FRONTIER_REFERENCE_QUORUM_MIN:
        return QuorumStatus.REFERENCE_SET_INCOMPLETE
    lineages = {REGISTERED_FRONTIER_REFERENCES[name] for name in seen}
    if len(lineages) < FRONTIER_REFERENCE_QUORUM_MIN_LINEAGES:
        return QuorumStatus.REFERENCE_SET_INCOMPLETE
    return QuorumStatus.QUORUM_MET


def validate_control_quorum(available_controls: list[str]) -> QuorumStatus:
    """GENESIS_FRONTIER_DECISION_GATES.md §"Control comparator quorum":
    ALL THREE registered controls (CONTROL_TARGET_SET) must be
    available -- there is no partial-quorum fallback, unlike the
    frontier reference set, because dropping even one of only three
    controls changes what "strongest of three" means.

    Phase 21B.4.10.1 hardening: an unknown control name (not one of the
    three registered controls) raises `StatisticalUnitValidationError`
    outright -- a superset containing unknown names must never be able
    to silently change the comparator set by slipping past validation.
    A duplicate control name is likewise rejected."""
    unknown = sorted(set(c for c in available_controls if c not in CONTROL_TARGET_SET))
    if unknown:
        raise StatisticalUnitValidationError(
            f"unknown control name(s) not part of the registered control set {CONTROL_TARGET_SET}: {unknown}"
        )
    seen: dict[str, int] = {}
    for c in available_controls:
        seen[c] = seen.get(c, 0) + 1
    duplicates = sorted(name for name, count in seen.items() if count > 1)
    if duplicates:
        raise StatisticalUnitValidationError(f"duplicate control name(s): {duplicates}")

    if not set(CONTROL_TARGET_SET).issubset(seen.keys()):
        return QuorumStatus.CONTROL_SET_INCOMPLETE
    return QuorumStatus.QUORUM_MET
