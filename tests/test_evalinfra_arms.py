"""Arm-definition validator: B2 (arm 3) and T2 (arm 4) must share a byte-identical system configuration; arm 2's prompt must be registered and budget-matched.
SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY. Pure config hashing; no model is loaded."""
import copy

import pytest

from orca.evalinfra import arms as AR
from orca.evalinfra.arms import ArmRefusal
from orca.evalinfra.config_lock import config_hash


def D():
    return copy.deepcopy(AR.make_example_definitions())


def arm(d, a):
    return next(x for x in d["arms"] if x["arm"] == a)


def refused(d, needle=None):
    ps = AR.problems(d)
    assert ps, "the comparison must be refused"
    with pytest.raises(ArmRefusal) as e:
        AR.require_valid(d)
    assert e.value.code == "COMPARISON_REFUSED"
    if needle:
        assert needle in " ".join(ps), ps


def test_example_is_valid_and_systems_identical():
    d = D()
    assert AR.problems(d) == []
    info = AR.require_valid(d)
    assert AR.system_config_hash(arm(d, "B2")) == AR.system_config_hash(arm(d, "T2")) == info["system_config_hash"]
    assert AR.run_config_without_model(arm(d, "B2")) == AR.run_config_without_model(arm(d, "T2"))
    assert info["banner"] == AR.BANNER


MUTATIONS = {
    "prompt": lambda s: s["prompts"].__setitem__("system", "f" * 64),
    "extra_prompt": lambda s: s["prompts"].__setitem__("extra", "e" * 64),
    "retrieval_top_k": lambda s: s["retrieval"].__setitem__("top_k", 5),
    "retrieval_corpus": lambda s: s["retrieval"].__setitem__("corpus_sha256", "d" * 64),
    "tool_set": lambda s: s.__setitem__("tool_set", ["calculator"]),
    "decoding": lambda s: s["decoding"].__setitem__("max_new_tokens", 65),
    "budgets": lambda s: s["budgets"].__setitem__("max_tool_calls", 5),
    "code_sha": lambda s: s.__setitem__("code_sha", "9" * 40),
    "engineering": lambda s: s.__setitem__("engineering_iterations", 6),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_t2_system_differing_from_b2_is_refused(name):
    """failing-before: without the validator a tuned arm could silently get a different prompt/tool set/budget and the 'training effect' would be confounded."""
    d = D()
    MUTATIONS[name](arm(d, "T2")["system"])
    refused(d)


def test_system_mismatch_reports_the_hash_reason():
    d = D()
    arm(d, "T2")["system"]["tool_set"] = ["calculator"]
    refused(d, "SYSTEM_CONFIG_MISMATCH")


def test_arm_level_decoding_or_budget_drift_refused():
    d = D()
    arm(d, "T2")["budgets"]["max_wall_clock_s"] = 31
    refused(d)
    d = D()
    arm(d, "T2")["decoding"]["max_new_tokens"] = 128
    refused(d)


def test_t2_may_differ_only_in_model_identity():
    d = D()
    assert arm(d, "T2")["model"] != arm(d, "B2")["model"]
    d["arms"] = [a if a["arm"] != "T2" else {**a, "model": dict(arm(d, "B2")["model"])} for a in d["arms"]]
    refused(d)                                                  # same identity => not a tuned arm
    d = D()
    arm(d, "T2")["base_model"] = {"id": "synthetic/other-base", "revision": "1" * 40}
    refused(d, "base_model")
    d = D()
    arm(d, "B1")["model"] = {**arm(d, "B1")["model"], "revision": "2" * 40}
    refused(d, "identical base model")


@pytest.mark.parametrize("missing", AR.ARM_IDS)
def test_missing_arm_is_refused(missing):
    d = D()
    d["arms"] = [a for a in d["arms"] if a["arm"] != missing]
    refused(d, "MISSING_ARM")


def test_duplicate_extra_and_malformed_arms_refused():
    d = D()
    d["arms"].append(copy.deepcopy(arm(d, "B2")))
    refused(d, "duplicate")
    d = D()
    d["arms"].append({**copy.deepcopy(arm(d, "B2")), "arm": "T1"})
    refused(d, "unknown arm")
    for bad in (None, [], "x", {"schema_version": AR.ARMS_SCHEMA}):
        assert AR.problems(bad)                                 # fail closed on garbage
        with pytest.raises(ArmRefusal):
            AR.require_valid(bad)


def test_arm_two_prompt_must_be_registered():
    d = D()
    arm(d, "B1")["prompt_id"] = "not-registered"
    refused(d, "PROMPT_NOT_REGISTERED")
    d = D()
    d["prompt_registry"] = {}
    refused(d, "PROMPT_NOT_REGISTERED")
    d = D()
    arm(d, "B1")["prompt_id"] = None
    refused(d)


def test_arm_two_prompt_must_be_budget_matched():
    d = D()
    d["prompt_registry"]["std-prompt-v1"]["token_count"] = 9999
    refused(d, "PROMPT_OVER_BUDGET")
    d = D()
    d["prompt_registry"]["std-prompt-v1"]["engineering_iterations"] = 1
    refused(d, "PROMPT_EFFORT_NOT_MATCHED")
    d = D()
    arm(d, "B1")["budgets"]["max_output_tokens"] = 128
    refused(d, "budget-matched")
    d = D()
    arm(d, "B0")["decoding"]["temperature"] = 0.7
    refused(d)


def test_arm_one_and_two_cannot_carry_the_system_and_others_cannot_carry_the_prompt():
    d = D()
    arm(d, "B1")["system"] = copy.deepcopy(arm(d, "B2")["system"])
    refused(d, "must not carry")
    d = D()
    arm(d, "B2")["prompt_id"] = "std-prompt-v1"
    refused(d, "prompt_id must be null")


def test_standardized_prompt_cannot_be_the_system_prompt():
    d = D()
    d["prompt_registry"]["std-prompt-v1"]["sha256"] = arm(d, "B2")["system"]["prompts"]["system"]
    refused(d, "different artifact")


def test_synthetic_only_and_primary_comparison_fixed():
    d = D()
    d["synthetic"] = False
    refused(d, "synthetic")
    d = D()
    d["primary_comparison"] = {"treatment": "B2", "control": "B1"}
    refused(d, "primary_comparison")
    d = D()
    d["banner"] = "x"
    refused(d, "banner")


def test_mutable_revisions_refused():
    d = D()
    arm(d, "T2")["model"]["revision"] = "main"
    refused(d)


def test_lock_configs_derive_mechanically_and_b2_t2_differ_only_by_model():
    d = D()
    c = {a: AR.to_lock_config(d, a) for a in AR.ARM_IDS}
    strip = lambda x: {k: v for k, v in x.items() if k not in ("arm", "model")}       # noqa: E731
    assert strip(c["B2"]) == strip(c["T2"]) and c["B2"]["model"] != c["T2"]["model"]
    assert config_hash(c["B2"]) != config_hash(c["T2"])
    assert len({config_hash(x) for x in c.values()}) == 4
    bad = D()
    arm(bad, "T2")["system"]["tool_set"] = ["calculator"]
    with pytest.raises(ArmRefusal):
        AR.to_lock_config(bad, "T2")                           # no lock can be derived from an invalid comparison
