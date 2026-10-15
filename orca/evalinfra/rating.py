"""Human-judge rubric, blinded double-rating assignment, agreement statistics and an adjudication state machine.

NO LLM JUDGE: every rater must be registered with kind == "HUMAN"; any other kind is refused. (The repository's GENESIS_JUDGE_PROTOCOL_SPEC.md describes a
multi-LLM-judge design; this module is the human-only counterpart and implements none of the LLM-judge layers.)

Blinding: raters receive only {blind_id, item_id, response_ref}; the arm behind a blind_id lives in a separate BlindingKey that is never put in a rater
packet. A response's own TEXT may still reveal its arm (e.g. house style) -- that cannot be detected here and is a documented limitation.
"""
from __future__ import annotations

import hashlib
import itertools
import random
from collections import Counter

from orca.evalinfra.canon import canonical, is_int
from orca.evalinfra.errors import RatingError, SchemaViolation

RUBRIC_VERSION = "orneur-evalinfra-rubric/1"
RUBRIC_KEYS = frozenset({"schema_version", "rubric_id", "criteria", "disagreement_threshold"})
CRITERION_KEYS = frozenset({"id", "description", "scale"})
LEVEL_KEYS = frozenset({"value", "anchor"})
ARM_TOKENS = ("B0", "B1", "B2", "T1", "T2", "R")
_ARM_TOKEN = __import__("re").compile(r"(?<![A-Za-z0-9])(?:B0|B1|B2|T1|T2|R)(?![A-Za-z0-9])", __import__("re").IGNORECASE)


# ------------------------------------------------------------------------------------------------------------------------------ rubric
def validate_rubric(r) -> dict:
    if not isinstance(r, dict) or set(r) != RUBRIC_KEYS:
        raise SchemaViolation("RUBRIC_SCHEMA", "exact keys " + str(sorted(RUBRIC_KEYS)))
    if r["schema_version"] != RUBRIC_VERSION or not (isinstance(r["rubric_id"], str) and r["rubric_id"]):
        raise SchemaViolation("RUBRIC_HEADER")
    if not is_int(r["disagreement_threshold"]) or r["disagreement_threshold"] < 0:
        raise SchemaViolation("RUBRIC_THRESHOLD", "disagreement_threshold must be a non-negative integer (max tolerated |difference| on the scale)")
    crit = r["criteria"]
    if not isinstance(crit, list) or not crit:
        raise SchemaViolation("RUBRIC_NO_CRITERIA")
    seen = set()
    for c in crit:
        if not isinstance(c, dict) or set(c) != CRITERION_KEYS:
            raise SchemaViolation("RUBRIC_CRITERION_SCHEMA")
        if not (isinstance(c["id"], str) and c["id"]) or c["id"] in seen:
            raise SchemaViolation("RUBRIC_CRITERION_ID", str(c.get("id")))
        seen.add(c["id"])
        if not (isinstance(c["description"], str) and len(c["description"].strip()) >= 10):
            raise SchemaViolation("RUBRIC_DESCRIPTION", c["id"])
        sc = c["scale"]
        if not isinstance(sc, list) or len(sc) < 2:
            raise SchemaViolation("RUBRIC_SCALE", f"{c['id']}: at least 2 levels")
        vals = []
        for lv in sc:
            if not isinstance(lv, dict) or set(lv) != LEVEL_KEYS or not is_int(lv["value"]) or not (isinstance(lv["anchor"], str) and lv["anchor"].strip()):
                raise SchemaViolation("RUBRIC_LEVEL", c["id"])
            vals.append(lv["value"])
        if vals != list(range(vals[0], vals[0] + len(vals))):
            raise SchemaViolation("RUBRIC_SCALE_NOT_CONSECUTIVE", c["id"])
    return r


def scale_of(rubric: dict) -> dict:
    return {c["id"]: [lv["value"] for lv in c["scale"]] for c in rubric["criteria"]}


# ------------------------------------------------------------------------------------------------------------------------------ raters / blinding
def validate_raters(raters: list) -> dict:
    out = {}
    for r in raters:
        if not isinstance(r, dict) or set(r) != {"id", "kind", "conflicts"}:
            raise SchemaViolation("RATER_SCHEMA", "rater needs exactly {id, kind, conflicts}")
        if r["kind"] != "HUMAN":
            raise RatingError("NON_HUMAN_RATER_REFUSED", f"{r.get('id')}: only registered humans may rate (no LLM judges)")
        if not (isinstance(r["id"], str) and r["id"]) or r["id"] in out:
            raise SchemaViolation("RATER_ID", str(r.get("id")))
        if not isinstance(r["conflicts"], list):
            raise SchemaViolation("RATER_CONFLICTS")
        out[r["id"]] = r
    return out


class BlindingKey:
    """blind_id -> (item_id, arm). Held by the analyst; NEVER included in a rater packet."""

    def __init__(self, mapping: dict):
        self._m = dict(mapping)

    def arm_of(self, blind_id: str) -> str:
        return self._m[blind_id][1]

    def item_of(self, blind_id: str) -> str:
        return self._m[blind_id][0]

    def __len__(self) -> int:
        return len(self._m)

    def __repr__(self) -> str:
        return f"BlindingKey(<{len(self._m)} sealed entries>)"


def blind_units(units: list, *, seed: int) -> tuple:
    """units: [{"item_id","arm","response_ref"}]. Returns (rater_packets, BlindingKey). Packets carry no arm label."""
    packets, mapping = [], {}
    for u in units:
        if not isinstance(u, dict) or set(u) != {"item_id", "arm", "response_ref"}:
            raise SchemaViolation("UNIT_SCHEMA")
        bid = "bl-" + hashlib.sha256(f"{seed}|{u['item_id']}|{u['arm']}".encode()).hexdigest()[:16]
        if bid in mapping:
            raise SchemaViolation("DUPLICATE_UNIT", f"{u['item_id']}/{u['arm']}")
        mapping[bid] = (u["item_id"], u["arm"])
        packets.append({"blind_id": bid, "item_id": u["item_id"], "response_ref": u["response_ref"]})
    rng = random.Random(seed)
    rng.shuffle(packets)
    for p in packets:
        assert_blinded(p)
    return packets, BlindingKey(mapping)


def assert_blinded(packet) -> None:
    """Refuse any packet that exposes an arm label as a key or an exact string value."""
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k) in ARM_TOKENS or str(k).lower() in ("arm", "arm_label", "system", "condition"):
                    raise RatingError("ARM_LABEL_EXPOSED", f"key {k!r}")
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, str) and _ARM_TOKEN.search(o):
            raise RatingError("ARM_LABEL_EXPOSED", "a value contains an arm token (response references must be opaque)")
    walk(packet)


def assign_double_rating(packets: list, raters: list, *, seed: int) -> dict:
    """Each blinded unit gets exactly two DISTINCT humans, load-balanced, honoring declared conflicts. Needs >= 3 humans so a third rater always exists."""
    pool = validate_raters(raters)
    if len(pool) < 3:
        raise RatingError("TOO_FEW_RATERS", "at least 3 registered humans are required (two raters + an independent third for escalations)")
    rng = random.Random(seed)
    load = Counter({r: 0 for r in pool})
    assignment = {}
    for p in packets:
        eligible = [r for r in pool if p["item_id"] not in pool[r]["conflicts"] and p["blind_id"] not in pool[r]["conflicts"]]
        if len(eligible) < 3:
            raise RatingError("NO_ELIGIBLE_RATERS", f"fewer than 3 non-conflicted raters for {p['item_id']}")
        order = sorted(eligible, key=lambda r: (load[r], rng.random(), r))
        pick = order[:2]
        for r in pick:
            load[r] += 1
        assignment[p["blind_id"]] = tuple(sorted(pick))
    return assignment


# ------------------------------------------------------------------------------------------------------------------------------ agreement
def cohens_kappa(r1: list, r2: list, *, weights: str | None = None, categories: list | None = None) -> dict:
    """Cohen's kappa for two raters over the same units; weights in (None, 'linear', 'quadratic') for ordered categories."""
    if len(r1) != len(r2) or not r1:
        raise RatingError("KAPPA_INPUT", "raters must rate the same non-empty set of units")
    cats = sorted(set(categories) if categories is not None else set(r1) | set(r2))
    if not set(r1) | set(r2) <= set(cats):
        raise RatingError("KAPPA_CATEGORY", "rating outside the declared categories")
    k, n = len(cats), len(r1)
    idx = {c: i for i, c in enumerate(cats)}
    obs = [[0.0] * k for _ in range(k)]
    for a, b in zip(r1, r2):
        obs[idx[a]][idx[b]] += 1.0 / n
    row = [sum(obs[i]) for i in range(k)]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    def w(i, j):
        if weights is None:
            return 0.0 if i == j else 1.0
        d = abs(i - j) / (k - 1) if k > 1 else 0.0
        if weights == "linear":
            return d
        if weights == "quadratic":
            return d * d
        raise RatingError("KAPPA_WEIGHTS", str(weights))
    do = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k))
    de = sum(w(i, j) * row[i] * col[j] for i in range(k) for j in range(k))
    kappa = None if de == 0 else 1.0 - do / de
    po = sum(obs[i][i] for i in range(k))
    return {"kappa": kappa, "observed_agreement": po, "n": n, "weights": weights, "categories": cats}


def krippendorff_alpha(units: list, level: str = "nominal") -> dict:
    """Krippendorff's alpha. units: list of units, each a list of the values given by the raters who rated it (None = missing). Units with fewer than 2
    values are not pairable and are ignored. level: nominal | ordinal | interval | ratio. alpha is None when expected disagreement is 0 (no variation)."""
    if level not in ("nominal", "ordinal", "interval", "ratio"):
        raise RatingError("ALPHA_LEVEL", level)
    vals_by_unit = [[v for v in u if v is not None] for u in units]
    vals_by_unit = [u for u in vals_by_unit if len(u) >= 2]
    if not vals_by_unit:
        raise RatingError("ALPHA_NO_PAIRABLE_UNITS")
    cats = sorted({v for u in vals_by_unit for v in u})
    if level != "nominal" and not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in cats):
        raise RatingError("ALPHA_NUMERIC_REQUIRED", level)
    o: dict = {}
    for u in vals_by_unit:
        m = len(u)
        for i, j in itertools.permutations(range(m), 2):
            o[(u[i], u[j])] = o.get((u[i], u[j]), 0.0) + 1.0 / (m - 1)
    nc = {c: sum(o.get((c, k), 0.0) for k in cats) for c in cats}
    n = sum(nc.values())
    if n <= 1:
        raise RatingError("ALPHA_TOO_FEW_VALUES")

    def delta2(c, k):
        if c == k:
            return 0.0
        if level == "nominal":
            return 1.0
        if level == "interval":
            return float(c - k) ** 2
        if level == "ratio":
            return ((c - k) / (c + k)) ** 2
        lo, hi = (c, k) if c < k else (k, c)
        s = sum(nc[g] for g in cats if lo <= g <= hi) - (nc[c] + nc[k]) / 2.0
        return s * s
    d_o = sum(cnt * delta2(c, k) for (c, k), cnt in o.items()) / n
    d_e = sum(nc[c] * nc[k] * delta2(c, k) for c in cats for k in cats) / (n * (n - 1))
    return {"alpha": None if d_e == 0 else 1.0 - d_o / d_e, "observed_disagreement": d_o, "expected_disagreement": d_e, "level": level,
            "n_pairable_values": n, "n_units": len(vals_by_unit)}


# ------------------------------------------------------------------------------------------------------------------------------ adjudication
ASSIGNED, RATED_ONCE, THIRD_REQUIRED, THIRD_ASSIGNED, ADJUDICATION_REQUIRED = "ASSIGNED", "RATED_ONCE", "THIRD_RATER_REQUIRED", "THIRD_RATER_ASSIGNED", "ADJUDICATION_REQUIRED"
AGREED, RESOLVED_BY_THIRD, ADJUDICATED = "AGREED", "RESOLVED_BY_THIRD", "ADJUDICATED"
TERMINAL = (AGREED, RESOLVED_BY_THIRD, ADJUDICATED)
_ALLOWED = {ASSIGNED: {RATED_ONCE}, RATED_ONCE: {AGREED, THIRD_REQUIRED}, THIRD_REQUIRED: {THIRD_ASSIGNED},
            THIRD_ASSIGNED: {RESOLVED_BY_THIRD, ADJUDICATION_REQUIRED}, ADJUDICATION_REQUIRED: {ADJUDICATED}}


def _median3(a, b, c):
    return sorted((a, b, c))[1]


class AdjudicationCase:
    """One blinded unit's rating lifecycle. Disagreement above the rubric threshold on ANY criterion forces a third rater; if the third rating does not
    land within the threshold of at least one earlier rating, a documented adjudication by a fifth party is required. Illegal transitions raise."""

    def __init__(self, blind_id: str, rubric: dict, assigned: tuple, *, third_pool: list):
        validate_rubric(rubric)
        if len(set(assigned)) != 2:
            raise RatingError("NEED_TWO_DISTINCT_RATERS")
        self.blind_id, self._rubric, self._scale = blind_id, rubric, scale_of(rubric)
        self._thr = rubric["disagreement_threshold"]
        self.assigned = tuple(assigned)
        self._third_pool = list(third_pool)
        self.state = ASSIGNED
        self.ratings: dict = {}
        self.third_rater = None
        self.adjudicator = None
        self.final: dict | None = None
        self.history = [ASSIGNED]

    def _go(self, new: str) -> None:
        if new not in _ALLOWED.get(self.state, set()):
            raise RatingError("ILLEGAL_TRANSITION", f"{self.state} -> {new}")
        self.state = new
        self.history.append(new)

    def _check_scores(self, scores: dict) -> None:
        if not isinstance(scores, dict) or set(scores) != set(self._scale):
            raise RatingError("RATING_CRITERIA_MISMATCH", "a rating must score exactly the rubric's criteria")
        for c, v in scores.items():
            if not is_int(v) or v not in self._scale[c]:
                raise RatingError("RATING_OUT_OF_SCALE", c)

    def view_for(self, rater: str) -> dict:
        """What a rater is shown: the blinded unit id only. Never another rater's score."""
        if rater not in self.assigned and rater != self.third_rater:
            raise RatingError("RATER_NOT_ASSIGNED", rater)
        return {"blind_id": self.blind_id, "rubric_id": self._rubric["rubric_id"]}

    def submit_rating(self, rater: str, scores: dict) -> str:
        self._check_scores(scores)
        if self.state in (ASSIGNED, RATED_ONCE):
            if rater not in self.assigned:
                raise RatingError("RATER_NOT_ASSIGNED", rater)
            if rater in self.ratings:
                raise RatingError("DUPLICATE_RATING", rater)
            self.ratings[rater] = dict(scores)
            if self.state == ASSIGNED:
                self._go(RATED_ONCE)
            if len(self.ratings) == 2:
                a, b = (self.ratings[r] for r in self.assigned)
                if all(abs(a[c] - b[c]) <= self._thr for c in a):
                    self.final = {c: (a[c] + b[c]) / 2 for c in a}
                    self._go(AGREED)
                else:
                    self._go(THIRD_REQUIRED)
            return self.state
        if self.state == THIRD_ASSIGNED:
            if rater != self.third_rater:
                raise RatingError("RATER_NOT_ASSIGNED", rater)
            self.ratings[rater] = dict(scores)
            a, b = (self.ratings[r] for r in self.assigned)
            t = self.ratings[rater]
            if all(min(abs(t[c] - a[c]), abs(t[c] - b[c])) <= self._thr for c in t):
                self.final = {c: float(_median3(a[c], b[c], t[c])) for c in t}
                self._go(RESOLVED_BY_THIRD)
            else:
                self._go(ADJUDICATION_REQUIRED)
            return self.state
        raise RatingError("ILLEGAL_TRANSITION", f"no rating accepted in state {self.state}")

    def assign_third(self, rater: str) -> None:
        if self.state != THIRD_REQUIRED:
            raise RatingError("ILLEGAL_TRANSITION", f"cannot assign a third rater in {self.state}")
        if rater in self.assigned:
            raise RatingError("THIRD_RATER_NOT_INDEPENDENT", "the third rater must differ from both original raters")
        if rater not in self._third_pool:
            raise RatingError("THIRD_RATER_NOT_ELIGIBLE", rater)
        self.third_rater = rater
        self._go(THIRD_ASSIGNED)

    def adjudicate(self, adjudicator: str, final_scores: dict, rationale: str) -> None:
        if self.state != ADJUDICATION_REQUIRED:
            raise RatingError("ILLEGAL_TRANSITION", f"cannot adjudicate in {self.state}")
        if adjudicator in self.ratings:
            raise RatingError("ADJUDICATOR_NOT_INDEPENDENT", "the adjudicator must not have rated this unit")
        self._check_scores(final_scores)
        if not isinstance(rationale, str) or len(rationale.strip()) < 20:
            raise RatingError("RATIONALE_REQUIRED", "a written rationale of >= 20 characters is required")
        self.adjudicator = adjudicator
        self.final = {c: float(v) for c, v in final_scores.items()}
        self._go(ADJUDICATED)

    def final_scores(self) -> dict:
        if self.state not in TERMINAL or self.final is None:
            raise RatingError("NOT_FINAL", self.state)
        return dict(self.final)

    def digest(self) -> str:
        return hashlib.sha256(canonical({"blind_id": self.blind_id, "history": self.history, "ratings": self.ratings, "final": self.final}).encode()).hexdigest()
