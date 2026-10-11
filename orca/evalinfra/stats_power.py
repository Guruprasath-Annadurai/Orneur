"""Power / minimum-detectable-effect / sample-size tools for PAIRED BINARY outcomes (McNemar design).

Parametrization (as in docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md section 6.6): n paired items; p_d = fraction of items where exactly one
arm is correct (discordant rate); delta = true accuracy difference (treatment - control) = p10 - p01, so p10 = (p_d + delta)/2, p01 = (p_d - delta)/2.

  closed form   : n = ((z_{1-a/2} sqrt(p_d) + z_{power} sqrt(p_d - delta^2)) / delta)^2   (normal approximation to McNemar; Connor 1987)
  exact power   : sum over D ~ Bin(n, p_d) of the rejection probability of the EXACT two-sided binomial (McNemar) test (slightly conservative vs closed form)
  simulation    : seeded Monte-Carlo of the exact test, an independent cross-check of both
"""
from __future__ import annotations

import math
import random
from fractions import Fraction
from functools import lru_cache
from statistics import NormalDist

from orca.evalinfra.errors import SchemaViolation

_N = NormalDist()


def _check(delta: float, p_d: float, alpha: float, power: float) -> None:
    if not (0.0 < alpha < 1.0) or not (0.0 < power < 1.0):
        raise SchemaViolation("BAD_ALPHA_OR_POWER")
    if not (0.0 < p_d <= 1.0):
        raise SchemaViolation("BAD_DISCORDANT_RATE")
    if not (0.0 < delta <= p_d):
        raise SchemaViolation("BAD_EFFECT", "need 0 < delta <= p_d (delta cannot exceed the discordant rate)")


def required_n_raw(delta: float, p_d: float, alpha: float = 0.05, power: float = 0.80) -> float:
    _check(delta, p_d, alpha, power)
    za, zb = _N.inv_cdf(1 - alpha / 2), _N.inv_cdf(power)
    return ((za * math.sqrt(p_d) + zb * math.sqrt(p_d - delta * delta)) / delta) ** 2


def required_n(delta: float, p_d: float, alpha: float = 0.05, power: float = 0.80, *, rounding: str = "ceil") -> int:
    """Integer n from the closed form. rounding='ceil' (default) is the smallest n that reaches the target power. rounding='nearest' reproduces the blueprint's
    section 6.6 table exactly (it rounds to nearest: three cells differ from ceil -- (8pts, p_d .10) 120.25 -> 120 vs 121; (10pts, .10) 76.09 -> 76 vs 77; (10pts, .30) 233.09 -> 233 vs 234)."""
    raw = required_n_raw(delta, p_d, alpha, power)
    if rounding == "ceil":
        return math.ceil(raw - 1e-9)
    if rounding == "nearest":
        return int(raw + 0.5)
    raise SchemaViolation("BAD_ROUNDING", rounding)


def mde(n: int, p_d: float, alpha: float = 0.05, power: float = 0.80) -> float | None:
    """Minimum detectable accuracy difference at n paired items (closed form inverted by bisection). None if even delta = p_d is not detectable."""
    if n < 2:
        raise SchemaViolation("BAD_N")
    if required_n_raw(p_d, p_d, alpha, power) > n:
        return None
    lo, hi = 1e-9, p_d
    for _ in range(200):
        mid = (lo + hi) / 2
        if required_n_raw(mid, p_d, alpha, power) > n:
            lo = mid
        else:
            hi = mid
    return hi


def bonferroni_alpha(alpha: float, k: int) -> float:
    if k < 1:
        raise SchemaViolation("BAD_FAMILY_SIZE")
    return alpha / k


# ------------------------------------------------------------------------------------------------------------------------------ exact power
def _log_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log(1 - p)


@lru_cache(maxsize=None)
def _critical_k(d: int, alpha: float) -> int:
    """Largest k with exact two-sided p = 2 * P(Bin(d, 1/2) <= k) <= alpha; -1 if the test cannot reject at this d."""
    if d == 0:
        return -1
    cum, k_best = 0, -1
    for k in range(d + 1):
        cum += math.comb(d, k)
        if 2 * cum <= Fraction(alpha) * 2 ** d and k < d - k:
            k_best = k
        else:
            break
    return k_best


def exact_power(n: int, p_d: float, delta: float, alpha: float = 0.05) -> float:
    """Exact power of the two-sided exact McNemar test (no normal approximation)."""
    _check(delta, p_d, alpha, 0.5)
    theta = (p_d + delta) / (2 * p_d)           # P(b-type | discordant)
    total = 0.0
    for d in range(1, n + 1):
        lp = _log_pmf(d, n, p_d)
        if lp == -math.inf:
            continue
        pd = math.exp(lp)
        if pd < 1e-15:
            continue
        kc = _critical_k(d, alpha)
        if kc < 0:
            continue
        rej = sum(math.exp(_log_pmf(k, d, theta)) + math.exp(_log_pmf(d - k, d, theta)) for k in range(kc + 1))
        total += pd * rej
    return min(1.0, total)


@lru_cache(maxsize=None)
def _p_exact(b: int, c: int) -> float:
    n, k = b + c, min(b, c)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def simulate_power(n: int, p_d: float, delta: float, alpha: float = 0.05, *, reps: int = 4000, seed: int = 20260101) -> float:
    """Seeded Monte-Carlo estimate of the power of the exact McNemar test (item-level simulation; independent of the closed form)."""
    _check(delta, p_d, alpha, 0.5)
    rng = random.Random(seed)
    p_b, p_c = (p_d + delta) / 2, (p_d - delta) / 2
    rej = 0
    for _ in range(reps):
        b = c = 0
        for _ in range(n):
            u = rng.random()
            if u < p_b:
                b += 1
            elif u < p_b + p_c:
                c += 1
        if _p_exact(b, c) <= alpha:
            rej += 1
    return rej / reps


def sample_size_table(deltas=(0.03, 0.05, 0.08, 0.10), p_ds=(0.10, 0.20, 0.30), alpha: float = 0.05, power: float = 0.80, *, rounding: str = "ceil") -> dict:
    return {d: {p: required_n(d, p, alpha, power, rounding=rounding) for p in p_ds} for d in deltas}


def mde_table(ns=(40, 80, 100, 120, 420, 1000), p_d: float = 0.20, alpha: float = 0.05, power: float = 0.80) -> dict:
    return {n: mde(n, p_d, alpha, power) for n in ns}
