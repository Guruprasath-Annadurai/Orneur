"""Statistics for Genesis Capability Eval V1: Wilson intervals, power arithmetic, category aggregation.

Pure CPU arithmetic. The confidence-interval method is Wilson score at 95% (z = 1.959963984540054) applied to the
mean item score (items are scored in [0, 1]; for binary items this is the exact Wilson interval on k/n).
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

Z95 = 1.959963984540054
CI_METHOD = "wilson_score_95"


def wilson(k: float, n: int, z: float = Z95) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def _log_binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log(1 - p))


def prob_dropped(true_rate: float, n: int, floor: float) -> float:
    """P(upper 95% Wilson bound of K/n < floor) when K ~ Binomial(n, true_rate): the 'confidently below floor' rule."""
    kmax = -1
    for k in range(n + 1):
        if wilson(k, n)[1] < floor:
            kmax = k
        else:
            break
    if kmax < 0:
        return 0.0
    return min(1.0, sum(math.exp(_log_binom_pmf(k, n, true_rate)) for k in range(kmax + 1)))


def min_detectable_true_rate(floor: float, n: int, power: float = 0.8) -> float | None:
    """Largest true rate below the floor at which the drop rule fires with probability >= power (None if never)."""
    p = floor
    while p > 0.0:
        if prob_dropped(p, n, floor) >= power:
            return round(p, 3)
        p -= 0.005
    return None


def low_power(n: int, low_power_n: int) -> bool:
    return n < low_power_n


def category_aggregate(scores: Sequence[float | None], n_expected: int, *, low_power_n: int) -> dict[str, Any]:
    """Aggregate per-item scores. ``None`` (or NaN) is a MISSING result: the category is INCOMPLETE, never silently shrunk."""
    valid = [s for s in scores if isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s) and 0.0 <= s <= 1.0]
    missing = n_expected - len(valid)
    out: dict[str, Any] = {"n_expected": n_expected, "n_scored": len(valid), "n_missing": missing, "ci_method": CI_METHOD}
    if missing != 0 or len(scores) != n_expected:
        out.update({"status": "INCOMPLETE", "mean": None, "ci95": None, "low_power": None})
        return out
    k = float(sum(valid))
    lo, hi = wilson(k, n_expected)
    out.update({"status": "COMPLETE", "mean": k / n_expected, "ci95": [lo, hi], "low_power": low_power(n_expected, low_power_n)})
    return out


def floor_decision(agg: Mapping[str, Any], floor: float) -> dict[str, Any]:
    """Failure semantics for a gating category with a frozen floor.

    * INCOMPLETE -> the model cannot be judged (fail closed; never a pass).
    * adequately powered: FAIL iff the point estimate < floor; PASS otherwise.
    * LOW_POWER: may only FAIL, and only when the 95% upper bound < floor (confidently below); otherwise INCONCLUSIVE_LOW_POWER,
      which is not a pass for ranking purposes and never lets the category rank a model.
    """
    if agg["status"] != "COMPLETE":
        return {"decision": "INCOMPLETE"}
    mean, (lo, hi) = agg["mean"], agg["ci95"]
    if agg["low_power"]:
        return {"decision": "FAIL" if hi < floor else "INCONCLUSIVE_LOW_POWER"}
    return {"decision": "PASS" if mean >= floor else "FAIL"}
