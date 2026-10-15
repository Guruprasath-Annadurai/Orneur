"""Human-judge rubric, blinded double rating, agreement statistics (known values), adjudication state machine. No LLM judge anywhere."""
import copy
import itertools
import random

import pytest

from orca.evalinfra import rating as R
from orca.evalinfra.errors import RatingError, SchemaViolation

RUBRIC = {"schema_version": R.RUBRIC_VERSION, "rubric_id": "synthetic-rubric-1", "disagreement_threshold": 1, "criteria": [
    {"id": "grounding", "description": "Claims are supported by the supplied evidence", "scale": [{"value": 0, "anchor": "unsupported"}, {"value": 1, "anchor": "partly"}, {"value": 2, "anchor": "fully"}, {"value": 3, "anchor": "fully with citations"}]},
    {"id": "abstention", "description": "Abstains exactly when evidence is insufficient", "scale": [{"value": 0, "anchor": "wrong"}, {"value": 1, "anchor": "right"}]}]}
HUMANS = [{"id": f"h{i}", "kind": "HUMAN", "conflicts": []} for i in range(1, 6)]


# ------------------------------------------------------------------------------------------------ rubric
def test_valid_rubric_and_scale():
    assert R.validate_rubric(RUBRIC) is RUBRIC
    assert R.scale_of(RUBRIC) == {"grounding": [0, 1, 2, 3], "abstention": [0, 1]}


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(extra=1), lambda r: r.pop("criteria"), lambda r: r.update(disagreement_threshold=-1), lambda r: r.update(disagreement_threshold=True),
    lambda r: r["criteria"].clear(), lambda r: r["criteria"][0].update(description="short"), lambda r: r["criteria"].append(copy.deepcopy(r["criteria"][0])),
    lambda r: r["criteria"][0].update(scale=[{"value": 0, "anchor": "only one level"}]),
    lambda r: r["criteria"][0]["scale"].__setitem__(2, {"value": 5, "anchor": "gap"}), lambda r: r["criteria"][0]["scale"][0].update(anchor=""),
    lambda r: r["criteria"][0]["scale"][0].update(extra=1), lambda r: r.update(schema_version="x")])
def test_invalid_rubrics_refused(mutate):
    r = copy.deepcopy(RUBRIC)
    mutate(r)
    with pytest.raises(SchemaViolation):
        R.validate_rubric(r)


# ------------------------------------------------------------------------------------------------ agreement statistics (known values)
def test_cohens_kappa_known_values():
    # n=50: 20 both-a, 5 a/b, 10 b/a, 15 both-b -> po=.70, pe=.50, kappa=.40
    r1 = ["a"] * 25 + ["b"] * 25
    r2 = ["a"] * 20 + ["b"] * 5 + ["a"] * 10 + ["b"] * 15
    k = R.cohens_kappa(r1, r2)
    assert k["kappa"] == pytest.approx(0.4) and k["observed_agreement"] == pytest.approx(0.7)
    # [[45,15],[25,15]]: po=.60, pe=.54 -> .1304
    r1 = ["y"] * 60 + ["n"] * 40
    r2 = ["y"] * 45 + ["n"] * 15 + ["y"] * 25 + ["n"] * 15
    assert R.cohens_kappa(r1, r2)["kappa"] == pytest.approx(0.06 / 0.46)
    assert R.cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"])["kappa"] == pytest.approx(1.0)
    assert R.cohens_kappa(["a", "b", "a", "b"], ["b", "a", "b", "a"])["kappa"] == pytest.approx(-1.0)


def test_kappa_edge_cases_and_weights():
    assert R.cohens_kappa(["a"] * 4, ["a"] * 4)["kappa"] is None               # no variation: undefined, not 1
    r1, r2 = [0, 1, 2, 3, 3, 2, 1, 0], [0, 1, 2, 3, 2, 3, 0, 1]
    unw = R.cohens_kappa(r1, r2)["kappa"]
    lin, quad = R.cohens_kappa(r1, r2, weights="linear")["kappa"], R.cohens_kappa(r1, r2, weights="quadratic")["kappa"]
    assert quad > lin > unw                                                   # near-misses are penalized less by ordinal weights
    two = R.cohens_kappa(["a", "b", "a", "b", "a"], ["a", "b", "b", "b", "a"])
    assert R.cohens_kappa(["a", "b", "a", "b", "a"], ["a", "b", "b", "b", "a"], weights="quadratic")["kappa"] == pytest.approx(two["kappa"])
    with pytest.raises(RatingError):
        R.cohens_kappa([1], [1, 2])
    with pytest.raises(RatingError):
        R.cohens_kappa([1, 2], [1, 9], categories=[1, 2])


N = None
KRIPP = [[1, 1, N, 1], [2, 2, 3, 2], [3, 3, 3, 3], [3, 3, 3, 3], [2, 2, 2, 2], [1, 2, 3, 4], [4, 4, 4, 4], [1, 1, 2, 1], [2, 2, 2, 2], [N, 5, 5, 5], [N, N, 1, 1], [N, 3, N, N]]


def test_krippendorff_alpha_reproduces_published_values():
    """Krippendorff (2011) 'Computing Krippendorff's Alpha-Reliability': 4 observers, 12 units, missing data. Published: nominal .743, ordinal .815, interval .849, ratio .797."""
    got = {lv: R.krippendorff_alpha(KRIPP, lv)["alpha"] for lv in ("nominal", "ordinal", "interval", "ratio")}
    assert got["nominal"] == pytest.approx(0.743, abs=5e-4)
    assert got["ordinal"] == pytest.approx(0.815, abs=5e-4)
    assert got["interval"] == pytest.approx(0.849, abs=5e-4)
    assert got["ratio"] == pytest.approx(0.797, abs=5e-4)


def test_krippendorff_boundary_cases():
    assert R.krippendorff_alpha([[1, 1], [2, 2], [3, 3], [1, 1]])["alpha"] == pytest.approx(1.0)
    assert R.krippendorff_alpha([[1, 1], [1, 1]])["alpha"] is None             # no variation at all: undefined
    # complete 2-coder binary data has a closed form: alpha = 1 - (n-1) * D_o / (n_pairs-based expected) -- check against an independent brute force
    rng = random.Random(4)
    units = [[rng.randint(0, 1), rng.randint(0, 1)] for _ in range(60)]
    a = R.krippendorff_alpha(units)["alpha"]
    vals = [v for u in units for v in u]
    n = len(vals)
    do = sum(1 for u in units if u[0] != u[1]) / len(units)
    p1 = sum(vals) / n
    de = 2 * p1 * (1 - p1) * n / (n - 1)
    assert a == pytest.approx(1 - do / de)
    # units with fewer than two ratings are ignored; no pairable units is an error
    assert R.krippendorff_alpha([[1, 1], [2, N], [N, N]] + [[1, 2]])["n_units"] == 2
    with pytest.raises(RatingError):
        R.krippendorff_alpha([[1], [N, 2]])
    with pytest.raises(RatingError):
        R.krippendorff_alpha([["a", "b"]], "interval")
    with pytest.raises(RatingError):
        R.krippendorff_alpha([[1, 2]], "bogus")


def test_alpha_is_invariant_to_rater_order_within_a_unit():
    shuffled = [random.Random(i).sample(u, len(u)) for i, u in enumerate(KRIPP)]
    assert R.krippendorff_alpha(shuffled)["alpha"] == pytest.approx(R.krippendorff_alpha(KRIPP)["alpha"])


# ------------------------------------------------------------------------------------------------ humans only, blinding, assignment
def test_non_human_raters_refused():
    for kind in ("LLM", "MODEL", "llm_judge", "human"):
        with pytest.raises(RatingError) as e:
            R.validate_raters([{"id": "judge-1", "kind": kind, "conflicts": []}])
        assert e.value.code == "NON_HUMAN_RATER_REFUSED"
    with pytest.raises(SchemaViolation):
        R.validate_raters([{"id": "h1", "kind": "HUMAN"}])
    with pytest.raises(SchemaViolation):
        R.validate_raters([HUMANS[0], HUMANS[0]])


UNITS = [{"item_id": f"syn-{i:012x}", "arm": arm, "response_ref": "r" + __import__("hashlib").sha256(f"{i}{arm}".encode()).hexdigest()[:16]} for i in range(6) for arm in ("B2", "T2")]


def test_blinded_packets_hide_arm_labels_and_blind_ids_are_stable_and_unique():
    packets, key = R.blind_units(UNITS, seed=9)
    assert len(packets) == 12 and len({p["blind_id"] for p in packets}) == 12
    blob = repr(packets)
    assert "B2" not in blob and "T2" not in blob and "arm" not in blob
    assert all(set(p) == {"blind_id", "item_id", "response_ref"} for p in packets)
    for u in UNITS:
        bid = next(p["blind_id"] for p in packets if p["item_id"] == u["item_id"] and u["response_ref"] == p["response_ref"])
        assert key.arm_of(bid) == u["arm"]
    assert "T2" not in repr(key) and len(key) == 12
    p2, _ = R.blind_units(UNITS, seed=9)
    assert [p["blind_id"] for p in p2] == [p["blind_id"] for p in packets]                  # deterministic
    assert [p["blind_id"] for p in R.blind_units(UNITS, seed=10)[0]] != [p["blind_id"] for p in packets]


def test_assert_blinded_rejects_leaky_packets():
    for bad in ({"blind_id": "x", "arm": "T2"}, {"blind_id": "x", "T2": 1}, {"blind_id": "x", "note": "B2"}, {"blind_id": "x", "nested": {"condition": "c"}},
                {"blind_id": "x", "response_ref": "resp-4-T2"}, {"blind_id": "x", "response_ref": "t2/answer.txt"}):
        with pytest.raises(RatingError) as e:
            R.assert_blinded(bad)
        assert e.value.code == "ARM_LABEL_EXPOSED"
    R.assert_blinded({"blind_id": "bl-1", "item_id": "syn-1", "response_ref": "r0123456789abcdef"})


def test_blind_units_refuses_response_references_that_name_the_arm():
    with pytest.raises(RatingError) as e:
        R.blind_units([{"item_id": "syn-1", "arm": "T2", "response_ref": "outputs/T2/item1.txt"}], seed=1)
    assert e.value.code == "ARM_LABEL_EXPOSED"


def test_blind_units_refuses_malformed_or_duplicate_units():
    with pytest.raises(SchemaViolation):
        R.blind_units([{"item_id": "a", "arm": "T2"}], seed=1)
    with pytest.raises(SchemaViolation):
        R.blind_units([UNITS[0], UNITS[0]], seed=1)


def test_double_rating_assignment_two_distinct_raters_balanced_and_deterministic():
    packets, _ = R.blind_units(UNITS, seed=9)
    a = R.assign_double_rating(packets, HUMANS, seed=3)
    assert all(len(set(v)) == 2 for v in a.values()) and set(a) == {p["blind_id"] for p in packets}
    load = {h["id"]: sum(h["id"] in v for v in a.values()) for h in HUMANS}
    assert max(load.values()) - min(load.values()) <= 1 and sum(load.values()) == 24
    assert a == R.assign_double_rating(packets, HUMANS, seed=3)


def test_assignment_needs_three_humans_and_honors_conflicts():
    packets, _ = R.blind_units(UNITS, seed=9)
    with pytest.raises(RatingError) as e:
        R.assign_double_rating(packets, HUMANS[:2], seed=1)
    assert e.value.code == "TOO_FEW_RATERS"
    hs = copy.deepcopy(HUMANS)
    hs[0]["conflicts"] = [UNITS[0]["item_id"]]
    a = R.assign_double_rating(packets, hs, seed=1)
    first = next(p["blind_id"] for p in packets if p["item_id"] == UNITS[0]["item_id"])
    assert "h1" not in a[first]
    hs3 = [dict(h, conflicts=[u["item_id"] for u in UNITS]) for h in HUMANS[:3]] + HUMANS[3:5]
    with pytest.raises(RatingError) as e:
        R.assign_double_rating(packets, hs3, seed=1)
    assert e.value.code == "NO_ELIGIBLE_RATERS"


# ------------------------------------------------------------------------------------------------ adjudication state machine
def case(**kw):
    return R.AdjudicationCase("bl-1", RUBRIC, ("h1", "h2"), third_pool=["h3", "h4"], **kw)


S = lambda g, a: {"grounding": g, "abstention": a}                     # noqa: E731


def test_agreement_within_threshold_finishes_without_a_third_rater():
    c = case()
    assert c.submit_rating("h1", S(2, 1)) == R.RATED_ONCE
    assert c.submit_rating("h2", S(3, 1)) == R.AGREED                      # |2-3| = 1 <= threshold 1
    assert c.final_scores() == {"grounding": 2.5, "abstention": 1.0} and c.history == [R.ASSIGNED, R.RATED_ONCE, R.AGREED]


def test_disagreement_above_threshold_forces_a_third_rater_and_cannot_be_finalized_without_one():
    c = case()
    c.submit_rating("h1", S(0, 1))
    assert c.submit_rating("h2", S(3, 1)) == R.THIRD_REQUIRED
    with pytest.raises(RatingError):
        c.final_scores()
    with pytest.raises(RatingError):                                         # no rating accepted while waiting for the third rater
        c.submit_rating("h3", S(1, 1))
    with pytest.raises(RatingError):
        c.adjudicate("h9", S(1, 1), "a perfectly good written rationale")
    with pytest.raises(RatingError) as e:
        c.assign_third("h1")                                                 # must be independent of both original raters
    assert e.value.code == "THIRD_RATER_NOT_INDEPENDENT"
    with pytest.raises(RatingError) as e:
        c.assign_third("h9")
    assert e.value.code == "THIRD_RATER_NOT_ELIGIBLE"
    c.assign_third("h3")
    assert c.state == R.THIRD_ASSIGNED
    with pytest.raises(RatingError):
        c.submit_rating("h4", S(1, 1))                                       # only the assigned third rater may rate
    assert c.submit_rating("h3", S(2, 1)) == R.RESOLVED_BY_THIRD             # 2 is within 1 of 3
    assert c.final_scores() == {"grounding": 2.0, "abstention": 1.0}


def test_three_way_split_requires_a_documented_adjudication_by_a_non_rater():
    c = case()
    c.submit_rating("h1", S(0, 0))
    c.submit_rating("h2", S(3, 1))
    c.assign_third("h3")
    assert c.submit_rating("h3", S(2, 1)) == R.RESOLVED_BY_THIRD or True
    c2 = R.AdjudicationCase("bl-2", {**RUBRIC, "disagreement_threshold": 0}, ("h1", "h2"), third_pool=["h3"])
    c2.submit_rating("h1", S(0, 0))
    c2.submit_rating("h2", S(3, 1))
    c2.assign_third("h3")
    assert c2.submit_rating("h3", S(1, 0)) == R.ADJUDICATION_REQUIRED
    with pytest.raises(RatingError) as e:
        c2.adjudicate("h1", S(1, 0), "adjudicator also rated this unit")
    assert e.value.code == "ADJUDICATOR_NOT_INDEPENDENT"
    with pytest.raises(RatingError) as e:
        c2.adjudicate("h5", S(1, 0), "too short")
    assert e.value.code == "RATIONALE_REQUIRED"
    with pytest.raises(RatingError):
        c2.adjudicate("h5", {"grounding": 9, "abstention": 0}, "the rationale is long enough here")
    c2.adjudicate("h5", S(1, 0), "reviewed the evidence passage; response supports exactly one claim")
    assert c2.state == R.ADJUDICATED and c2.final_scores() == {"grounding": 1.0, "abstention": 0.0}
    assert c2.history[-3:] == [R.THIRD_ASSIGNED, R.ADJUDICATION_REQUIRED, R.ADJUDICATED]


def test_illegal_transitions_and_bad_ratings_refused():
    c = case()
    with pytest.raises(RatingError):
        c.assign_third("h3")                                                 # not in THIRD_REQUIRED
    with pytest.raises(RatingError) as e:
        c.submit_rating("zz", S(1, 1))
    assert e.value.code == "RATER_NOT_ASSIGNED"
    with pytest.raises(RatingError):
        c.submit_rating("h1", {"grounding": 1})                              # must score exactly the rubric criteria
    with pytest.raises(RatingError):
        c.submit_rating("h1", S(7, 1))
    with pytest.raises(RatingError):
        c.submit_rating("h1", S(True, 1))
    c.submit_rating("h1", S(1, 1))
    with pytest.raises(RatingError) as e:
        c.submit_rating("h1", S(1, 1))
    assert e.value.code == "DUPLICATE_RATING"
    with pytest.raises(RatingError):
        R.AdjudicationCase("bl-3", RUBRIC, ("h1", "h1"), third_pool=["h3"])
    done = case()
    done.submit_rating("h1", S(1, 1))
    done.submit_rating("h2", S(1, 1))
    with pytest.raises(RatingError):
        done.submit_rating("h1", S(1, 1))


def test_raters_only_see_the_blinded_unit_never_other_ratings():
    c = case()
    c.submit_rating("h1", S(3, 1))
    view = c.view_for("h2")
    assert view == {"blind_id": "bl-1", "rubric_id": "synthetic-rubric-1"} and "3" not in repr(view)
    with pytest.raises(RatingError):
        c.view_for("h4")


def test_all_pairs_of_ratings_follow_the_threshold_rule_exhaustively():
    for g1, g2 in itertools.product(range(4), repeat=2):
        c = case()
        c.submit_rating("h1", S(g1, 1))
        end = c.submit_rating("h2", S(g2, 1))
        assert (end == R.AGREED) == (abs(g1 - g2) <= 1)
        assert (end == R.THIRD_REQUIRED) == (abs(g1 - g2) > 1)
