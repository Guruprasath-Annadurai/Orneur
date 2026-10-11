"""Paired comparison statistics (pure standard library; deterministic).

Arms: B0 (base), B1 (base + engineered prompt), B2 (base + full ORNEUR system), T1 (tuned adapter), T2 (tuned adapter + system), R (external reference).
Every comparison is PAIRED on the same items. Differences are always (treatment - control).

  * McNemar exact test (two-sided, binomial on discordant pairs) for binary outcomes;
  * paired bootstrap CI (percentile AND BCa), seeded random.Random, >= 10,000 resamples (fewer is refused), optional cluster resampling;
  * effect sizes: mean difference, Cohen's d_z (+ Hedges correction), odds ratio of discordant pairs (Haldane-Anscombe), Cohen's g;
  * category-level breakdown -- there is NO function in this module that merges categories into one score;
  * multiple-comparison correction inside explicitly DEFINED families: Bonferroni, Holm (step-down), Benjamini-Hochberg (FDR).
"""
from __future__ import annotations

import math
import random
from fractions import Fraction
from statistics import NormalDist

from orca.evalinfra.errors import EvalInfraError, SchemaViolation

ARMS = ("B0", "B1", "B2", "T1", "T2", "R")
MIN_RESAMPLES = 10_000
_N = NormalDist()
CORRECTIONS = ("bonferroni", "holm", "benjamini_hochberg")


# ------------------------------------------------------------------------------------------------------------------------------ alignment
def align(treatment: dict, control: dict) -> tuple:
    """Return (item_ids, x, y) with identical item sets or raise. Pairing is never repaired by silently dropping items."""
    if set(treatment) != set(control):
        raise SchemaViolation("UNPAIRED_ITEMS", f"arms differ in item sets ({len(set(treatment) ^ set(control))} items not paired)")
    ids = sorted(treatment)
    for d in (treatment, control):
        for i in ids:
            v = d[i]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (math.inf, -math.inf):
                raise SchemaViolation("BAD_OUTCOME", f"item {i}: outcomes must be finite numbers")
    return ids, [float(treatment[i]) for i in ids], [float(control[i]) for i in ids]


def is_binary(xs) -> bool:
    return all(v in (0.0, 1.0) for v in xs)


# ------------------------------------------------------------------------------------------------------------------------------ McNemar
def discordant_counts(x: list, y: list) -> dict:
    """b = treatment correct & control wrong; c = treatment wrong & control correct."""
    b = sum(1 for p, q in zip(x, y) if p == 1.0 and q == 0.0)
    c = sum(1 for p, q in zip(x, y) if p == 0.0 and q == 1.0)
    n11 = sum(1 for p, q in zip(x, y) if p == 1.0 and q == 1.0)
    n00 = sum(1 for p, q in zip(x, y) if p == 0.0 and q == 0.0)
    return {"n11": n11, "b": b, "c": c, "n00": n00}


def mcnemar_exact(b: int, c: int) -> dict:
    """Exact two-sided McNemar: under H0 the b discordant pairs among n=b+c are Binomial(n, 1/2). p = min(1, 2 * P(X <= min(b,c)))."""
    if b < 0 or c < 0:
        raise SchemaViolation("BAD_COUNTS")
    n, k = b + c, min(b, c)
    if n == 0:
        return {"b": b, "c": c, "n_discordant": 0, "p_two_sided": 1.0, "p_mid": 1.0}
    tail = sum(math.comb(n, i) for i in range(k + 1))
    p = min(Fraction(1), Fraction(2 * tail, 2 ** n))
    pmid = min(Fraction(1), Fraction(2 * tail - math.comb(n, k), 2 ** n))
    return {"b": b, "c": c, "n_discordant": n, "p_two_sided": float(p), "p_mid": float(pmid)}


# ------------------------------------------------------------------------------------------------------------------------------ bootstrap
def _quantile(sorted_vals: list, q: float) -> float:
    """Linear interpolation (R type 7) on an already sorted list."""
    if not sorted_vals:
        raise EvalInfraError("EMPTY")
    q = min(1.0, max(0.0, q))
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (pos - lo) * (sorted_vals[hi] - sorted_vals[lo])


def _units(diffs: list, clusters: list | None) -> tuple:
    """Resampling units as parallel (sum, count) lists. Without clusters every item is its own unit."""
    if clusters is None:
        return list(diffs), [1] * len(diffs)
    if len(clusters) != len(diffs):
        raise SchemaViolation("CLUSTER_LENGTH_MISMATCH")
    agg: dict = {}
    for d, c in zip(diffs, clusters):
        s, k = agg.get(c, (0.0, 0))
        agg[c] = (s + d, k + 1)
    keys = sorted(agg, key=str)
    return [agg[k][0] for k in keys], [agg[k][1] for k in keys]


def paired_bootstrap(diffs: list, *, seed: int, n_resamples: int = MIN_RESAMPLES, confidence: float = 0.95, clusters: list | None = None) -> dict:
    """Percentile and BCa intervals for the mean paired difference. Deterministic given (diffs, seed, n_resamples, clusters)."""
    if not isinstance(n_resamples, int) or n_resamples < MIN_RESAMPLES:
        raise SchemaViolation("TOO_FEW_RESAMPLES", f"at least {MIN_RESAMPLES} bootstrap resamples are required")
    if not (0.0 < confidence < 1.0):
        raise SchemaViolation("BAD_CONFIDENCE")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise SchemaViolation("BAD_SEED")
    n = len(diffs)
    if n < 2:
        raise SchemaViolation("TOO_FEW_ITEMS", "a bootstrap interval needs at least 2 paired items")
    sums, cnts = _units(diffs, clusters)
    m = len(sums)
    total_n = sum(cnts)
    theta = sum(sums) / total_n
    rng = random.Random(seed)
    rnd = rng.random
    boots = []
    if all(c == 1 for c in cnts):
        for _ in range(n_resamples):
            boots.append(sum(sums[int(rnd() * m)] for _ in range(m)) / m)
    else:
        for _ in range(n_resamples):
            ix = [int(rnd() * m) for _ in range(m)]
            boots.append(sum(sums[i] for i in ix) / sum(cnts[i] for i in ix))
    boots.sort()
    alpha = 1.0 - confidence
    out = {"point": theta, "n_items": n, "n_units": m, "n_resamples": n_resamples, "seed": seed, "confidence": confidence,
           "percentile": [_quantile(boots, alpha / 2), _quantile(boots, 1 - alpha / 2)], "bca": None, "bca_unavailable_reason": None,
           "boot_se": math.sqrt(sum((b - sum(boots) / len(boots)) ** 2 for b in boots) / (len(boots) - 1))}
    # BCa
    less = sum(1 for b in boots if b < theta)
    eq = sum(1 for b in boots if b == theta)
    frac = (less + 0.5 * eq) / n_resamples
    if frac <= 0.0 or frac >= 1.0 or m < 3:
        out["bca_unavailable_reason"] = "degenerate bootstrap distribution (bias-correction undefined)" if m >= 3 else "fewer than 3 resampling units"
        return out
    z0 = _N.inv_cdf(frac)
    tot_s, tot_c = sum(sums), total_n
    jack = [(tot_s - sums[i]) / (tot_c - cnts[i]) for i in range(m) if tot_c - cnts[i] > 0]
    jm = sum(jack) / len(jack)
    num = sum((jm - j) ** 3 for j in jack)
    den = 6.0 * (sum((jm - j) ** 2 for j in jack) ** 1.5)
    a = num / den if den > 0 else 0.0
    bounds = []
    for q in (alpha / 2, 1 - alpha / 2):
        zq = _N.inv_cdf(q)
        d = 1.0 - a * (z0 + zq)
        if d <= 0:
            out["bca_unavailable_reason"] = "acceleration makes the BCa adjustment undefined"
            return out
        bounds.append(_N.cdf(z0 + (z0 + zq) / d))
    out["bca"] = [_quantile(boots, bounds[0]), _quantile(boots, bounds[1])]
    out["bca_z0"], out["bca_acceleration"] = z0, a
    return out


# ------------------------------------------------------------------------------------------------------------------------------ effect sizes
def effect_sizes(diffs: list, x: list | None = None, y: list | None = None) -> dict:
    n = len(diffs)
    mean = sum(diffs) / n
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1)) if n > 1 else float("nan")
    out = {"mean_difference": mean, "sd_difference": sd if sd == sd else None, "cohens_dz": None, "hedges_gz": None}
    if n > 1 and sd > 0:
        dz = mean / sd
        j = 1 - 3 / (4 * (n - 1) - 1)
        out["cohens_dz"], out["hedges_gz"] = dz, dz * j
    if x is not None and y is not None and is_binary(x) and is_binary(y):
        t = discordant_counts(x, y)
        out["odds_ratio_discordant"] = (t["b"] + 0.5) / (t["c"] + 0.5)
        out["cohens_g"] = (t["b"] / (t["b"] + t["c"]) - 0.5) if (t["b"] + t["c"]) else None
        out["risk_difference"] = mean
    return out


# ------------------------------------------------------------------------------------------------------------------------------ comparison
def compare_pair(treatment: dict, control: dict, *, seed: int, n_resamples: int = MIN_RESAMPLES, confidence: float = 0.95, clusters: dict | None = None) -> dict:
    """One paired comparison on ONE set of items (callers pass the items of a single category). Returns every statistic with its n."""
    ids, x, y = align(treatment, control)
    diffs = [p - q for p, q in zip(x, y)]
    cl = None if clusters is None else [clusters[i] for i in ids]
    boot = paired_bootstrap(diffs, seed=seed, n_resamples=n_resamples, confidence=confidence, clusters=cl)
    res = {"n": len(ids), "mean_treatment": sum(x) / len(x), "mean_control": sum(y) / len(y), "difference": boot["point"], "bootstrap": boot,
           "effect": effect_sizes(diffs, x, y), "binary": is_binary(x) and is_binary(y), "mcnemar": None}
    if res["binary"]:
        t = discordant_counts(x, y)
        res["discordant"] = t
        res["mcnemar"] = mcnemar_exact(t["b"], t["c"])
    return res


def compare_by_category(outcomes: dict, categories: dict, treatment_arm: str, control_arm: str, *, seed: int, n_resamples: int = MIN_RESAMPLES,
                        confidence: float = 0.95, clusters: dict | None = None, only_categories=None) -> dict:
    """Category-level breakdown: one independent comparison per category. Categories are NEVER merged. A category seed is derived from (seed, category)
    so adding a category cannot change another category's interval."""
    for a in (treatment_arm, control_arm):
        if a not in ARMS:
            raise SchemaViolation("UNKNOWN_ARM", a)
        if a not in outcomes:
            raise SchemaViolation("ARM_NOT_EVALUATED", f"{a} has no outcomes (NOT_EVALUATED is never estimated)")
    t_all, c_all = outcomes[treatment_arm], outcomes[control_arm]
    if set(t_all) != set(c_all):
        raise SchemaViolation("UNPAIRED_ITEMS", "arms differ in item sets")
    cats = sorted({categories[i] for i in t_all}, key=str)
    if only_categories is not None:
        cats = [c for c in cats if c in only_categories]
    out = {}
    for c in cats:
        ids = [i for i in t_all if categories[i] == c]
        out[c] = compare_pair({i: t_all[i] for i in ids}, {i: c_all[i] for i in ids}, seed=_derive_seed(seed, treatment_arm, control_arm, c),
                              n_resamples=n_resamples, confidence=confidence, clusters=None if clusters is None else {i: clusters[i] for i in ids})
    return out


def _derive_seed(seed: int, a: str, b: str, category) -> int:
    import hashlib
    h = hashlib.sha256(f"{seed}|{a}|{b}|{category}".encode()).digest()
    return int.from_bytes(h[:8], "big")


# ------------------------------------------------------------------------------------------------------------------------------ multiplicity
def adjust_pvalues(pvalues: dict, method: str) -> dict:
    """Adjusted p-values for ONE family (all keys of `pvalues` form the family). Bonferroni/Holm control FWER; Benjamini-Hochberg controls FDR."""
    if method not in CORRECTIONS:
        raise SchemaViolation("UNKNOWN_CORRECTION", method)
    if not pvalues:
        return {}
    for k, p in pvalues.items():
        if not isinstance(p, (int, float)) or isinstance(p, bool) or not (0.0 <= p <= 1.0):
            raise SchemaViolation("BAD_PVALUE", str(k))
    m = len(pvalues)
    order = sorted(pvalues, key=lambda k: (pvalues[k], str(k)))
    adj = {}
    if method == "bonferroni":
        return {k: min(1.0, pvalues[k] * m) for k in pvalues}
    if method == "holm":
        run = 0.0
        for i, k in enumerate(order):
            run = max(run, (m - i) * pvalues[k])
            adj[k] = min(1.0, run)
        return adj
    run = 1.0
    for i in range(m - 1, -1, -1):
        k = order[i]
        run = min(run, pvalues[k] * m / (i + 1))
        adj[k] = min(1.0, run)
    return adj


def apply_families(families: list, pvalues: dict, method: str, *, exploratory: tuple = ()) -> dict:
    """families: [{"name", "alpha", "endpoints": [ids]}]. Every non-exploratory p-value must belong to EXACTLY one family; correction is applied within
    a family only. Exploratory endpoints are returned unadjusted and labelled -- they can never be 'significant after correction'."""
    owner: dict = {}
    for f in families:
        for e in f["endpoints"]:
            if e in owner:
                raise SchemaViolation("ENDPOINT_IN_TWO_FAMILIES", str(e))
            owner[e] = f["name"]
    out: dict = {}
    for f in families:
        missing = [e for e in f["endpoints"] if e not in pvalues]
        if missing:
            raise SchemaViolation("FAMILY_ENDPOINT_WITHOUT_RESULT", f"{f['name']}: {missing}")
        adj = adjust_pvalues({e: pvalues[e] for e in f["endpoints"]}, method)
        for e in f["endpoints"]:
            out[e] = {"family": f["name"], "family_size": len(f["endpoints"]), "method": method, "raw_p": pvalues[e], "adjusted_p": adj[e],
                      "alpha": f["alpha"], "significant_after_correction": adj[e] <= f["alpha"], "status": "CONFIRMATORY"}
    for e, p in pvalues.items():
        if e in out:
            continue
        if e in exploratory:
            out[e] = {"family": None, "family_size": None, "method": None, "raw_p": p, "adjusted_p": None, "alpha": None,
                      "significant_after_correction": False, "status": "EXPLORATORY_UNADJUSTED"}
        else:
            raise SchemaViolation("ENDPOINT_WITHOUT_FAMILY", f"{e} is neither in a family nor declared exploratory")
    return out


# ------------------------------------------------------------------------------------------------------------------------------ seeds / zero tolerance
def aggregate_replicates(replicates: list) -> dict:
    """Per-item mean over run replicates (seeds). Every replicate must cover exactly the same items."""
    if not replicates:
        raise SchemaViolation("NO_REPLICATES")
    ids = set(replicates[0])
    if any(set(r) != ids for r in replicates):
        raise SchemaViolation("REPLICATES_DIFFER_IN_ITEMS")
    return {i: sum(r[i] for r in replicates) / len(replicates) for i in ids}


def seed_replication(per_seed: dict, treatment_arm: str, control_arm: str, *, min_seeds: int = 3) -> dict:
    """per_seed: {seed: {arm: {item: score}}}. Reports each seed's mean difference and whether the SIGN is consistent across all seeds."""
    if len(per_seed) < min_seeds:
        raise SchemaViolation("TOO_FEW_SEEDS", f"{len(per_seed)} < {min_seeds}")
    diffs = {}
    for s, arms in sorted(per_seed.items()):
        ids, x, y = align(arms[treatment_arm], arms[control_arm])
        diffs[s] = sum(p - q for p, q in zip(x, y)) / len(ids)
    pos = [d > 0 for d in diffs.values()]
    return {"per_seed_difference": diffs, "n_seeds": len(diffs), "all_positive": all(pos), "all_negative": all(d < 0 for d in diffs.values())}


def zero_tolerance_summary(outcomes: dict, categories: dict, zero_tolerance_categories) -> dict:
    """Counts of FAILED items (score < 1) per arm and zero-tolerance category. Any failure is a blocking event; no statistics, no averaging."""
    out = {}
    zt = set(zero_tolerance_categories)
    for arm, d in sorted(outcomes.items()):
        rows = {}
        for c in sorted(zt, key=str):
            ids = [i for i in d if categories[i] == c]
            rows[c] = {"n": len(ids), "failures": sum(1 for i in ids if d[i] < 1.0)}
        out[arm] = rows
    return out
