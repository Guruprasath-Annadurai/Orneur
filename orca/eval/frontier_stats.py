"""
Genesis Frontier statistical contract (Phase 21B.4.9/.1/.2 methodology,
encoded as tested, executable code in Phase 21B.4.10).

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
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from enum import Enum

FRONTIER_STATISTICAL_CONTRACT_VERSION = "genesis-frontier-stats-v1"

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

# ── Quorum constants (GENESIS_FRONTIER_DECISION_GATES.md §"Frontier
# reference quorum" / §"Control comparator quorum") ──

FRONTIER_TARGET_REFERENCES = 6
FRONTIER_REFERENCE_QUORUM_MIN = 4
FRONTIER_REFERENCE_QUORUM_MIN_LINEAGES = 3

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
    produced by `independent_units()` below."""
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


def paired_bootstrap_ci(
    candidate_scores: dict[str, float],
    comparator_scores: dict[str, float],
    units: list[StatisticalUnit],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = CONFIDENCE_LEVEL,
    rng: random.Random | None = None,
) -> ConfidenceInterval:
    """The one paired-bootstrap-over-statistical-units implementation
    (GENESIS_FRONTIER_SCORING_CONTRACT.md §5.2) used for every locked
    comparison (frontier gap, best-reference ceiling, control
    superiority, pairwise finalist tie region, quantization regression).

    `candidate_scores` and `comparator_scores` map task_id -> a score
    already normalized to [0,1] (§5.1 -- normalization happens before
    this function is called, never inside it). `units` is the list of
    `StatisticalUnit`s to resample WITH REPLACEMENT -- resampling a unit
    resamples every task_id it contains together, preserving the
    correlation structure between related task variants (§6).

    Each resample computes `D = mean(candidate scores over the resampled
    task_ids) - mean(comparator scores over the same resampled task_ids)`
    -- this is what makes the comparison "paired": candidate and
    comparator are always evaluated on the identical resampled task set.
    The returned interval is the `[alpha/2, 1-alpha/2]` percentile
    interval of the resample distribution (percentile bootstrap method).

    `rng` defaults to an unseeded `random.Random()` for real use;
    callers (including this module's own tests) pass a seeded
    `random.Random(seed)` for reproducibility."""
    if not units:
        raise ValueError("no statistical units provided -- cannot compute a paired bootstrap CI")
    if resamples < 1:
        raise ValueError(f"resamples must be >= 1, got {resamples}")

    generator = rng if rng is not None else random.Random()
    n_units = len(units)
    diffs: list[float] = []

    for _ in range(resamples):
        resampled_task_ids: list[str] = []
        for _i in range(n_units):
            unit = units[generator.randrange(n_units)]
            resampled_task_ids.extend(unit.task_ids)
        cand_vals = [candidate_scores[tid] for tid in resampled_task_ids]
        comp_vals = [comparator_scores[tid] for tid in resampled_task_ids]
        diffs.append(statistics.fmean(cand_vals) - statistics.fmean(comp_vals))

    diffs.sort()
    alpha = 1.0 - confidence
    lower_idx = max(0, min(int((alpha / 2) * resamples), resamples - 1))
    upper_idx = max(0, min(int((1 - alpha / 2) * resamples) - 1, resamples - 1))
    if upper_idx < lower_idx:
        upper_idx = lower_idx
    return ConfidenceInterval(lower=diffs[lower_idx], upper=diffs[upper_idx])


# ── Locked classifiers (pure functions over a ConfidenceInterval only) ──


def classify_frontier_gap(ci: ConfidenceInterval) -> Classification:
    """D = candidate_score - frontier_reference_median_score.
    GENESIS_FRONTIER_DECISION_GATES.md §"Frontier gap metric"."""
    if ci.lower >= -DELTA_FRONTIER:
        return Classification.NON_INFERIOR
    if ci.upper < -DELTA_FRONTIER:
        return Classification.MATERIAL_GAP
    return Classification.INCONCLUSIVE


def classify_best_reference(ci: ConfidenceInterval) -> Classification:
    """D = candidate_score - strongest_reference_score.
    GENESIS_FRONTIER_DECISION_GATES.md §"Best-reference ceiling guard" --
    three states; INCONCLUSIVE does NOT pass the ceiling guard (never
    resolves in the candidate's favor)."""
    if ci.lower >= -DELTA_BEST_REFERENCE:
        return Classification.CEILING_NONINFERIOR
    if ci.upper < -DELTA_BEST_REFERENCE:
        return Classification.DRAMATICALLY_BEHIND_CEILING
    return Classification.INCONCLUSIVE


def classify_control_superiority(ci: ConfidenceInterval) -> Classification:
    """D = candidate_score - strongest_control_score.
    GENESIS_FRONTIER_DECISION_GATES.md §"Control superiority" -- no
    separate INCONCLUSIVE state: this is one of several AND-ed
    conditions in the frontier-class threshold, so anything short of
    SUBSTANTIALLY_SUPERIOR simply means the condition is not satisfied."""
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


# ── Quorum validators ──


def validate_frontier_reference_quorum(available_references: list[tuple[str, str]]) -> QuorumStatus:
    """`available_references`: a list of (reference_name, organization)
    pairs for references successfully evaluated on the shared task set
    for one critical category. GENESIS_FRONTIER_DECISION_GATES.md
    §"Frontier reference quorum": valid only if at least
    FRONTIER_REFERENCE_QUORUM_MIN (4) of the FRONTIER_TARGET_REFERENCES
    (6) are available AND they span at least
    FRONTIER_REFERENCE_QUORUM_MIN_LINEAGES (3) distinct organizations."""
    if len(available_references) < FRONTIER_REFERENCE_QUORUM_MIN:
        return QuorumStatus.REFERENCE_SET_INCOMPLETE
    lineages = {org for _name, org in available_references}
    if len(lineages) < FRONTIER_REFERENCE_QUORUM_MIN_LINEAGES:
        return QuorumStatus.REFERENCE_SET_INCOMPLETE
    return QuorumStatus.QUORUM_MET


def validate_control_quorum(available_controls: list[str]) -> QuorumStatus:
    """GENESIS_FRONTIER_DECISION_GATES.md §"Control comparator quorum":
    ALL THREE registered controls (CONTROL_TARGET_SET) must be
    available -- there is no partial-quorum fallback, unlike the
    frontier reference set, because dropping even one of only three
    controls changes what "strongest of three" means."""
    if not set(CONTROL_TARGET_SET).issubset(set(available_controls)):
        return QuorumStatus.CONTROL_SET_INCOMPLETE
    return QuorumStatus.QUORUM_MET
