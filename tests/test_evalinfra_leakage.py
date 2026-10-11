"""Prompt/answer leakage checks for result artifacts: structural keys, canaries, prompt n-grams, answer text; findings never echo the leaked text."""
import copy

import pytest

from orca.evalinfra import synthetic as SY
from orca.evalinfra.errors import LeakageDetected, SchemaViolation
from orca.evalinfra.leakage import LeakGuard

ITEMS = SY.make_items(5, (3, 10), {"QUALIFICATION_HOLDOUT": 4, "SCREEN": 3})
CANARY = "CANARY-HOLDOUT-5d3c9e7a1b2f4086"


@pytest.fixture(scope="module")
def guard():
    return LeakGuard(items=ITEMS, canaries=[CANARY])


CLEAN = {"schema": "result", "rows": [{"item_id": "syn-abcdef123456", "category": 3, "score": 1.0}], "arm": "T2", "note": "run finished with 4 items scored"}


def kinds(g, art):
    return {f["kind"] for f in g.scan(art)}


def test_clean_result_artifact_passes(guard):
    assert guard.scan(CLEAN) == []
    guard.assert_clean(CLEAN)
    assert guard.has_private_material


def test_forbidden_content_keys_caught_at_any_depth(guard):
    for k in ("prompt", "ground_truth", "answer", "reference_solution", "seed", "salt", "expected_output"):
        art = copy.deepcopy(CLEAN)
        art["rows"][0][k] = "anything"
        assert "FORBIDDEN_KEY" in kinds(guard, art), k
    art = {"deep": {"er": [{"est": {"answer": 1}}]}}
    assert "FORBIDDEN_KEY" in kinds(guard, art)


def test_synthetic_canary_in_value_or_key_caught(guard):
    art = copy.deepcopy(CLEAN)
    art["note"] = f"debug dump {CANARY} end"
    assert "CANARY" in kinds(guard, art)
    art = copy.deepcopy(CLEAN)
    art[CANARY.lower()] = 1                                        # canary smuggled as a KEY, different case
    assert "CANARY" in kinds(guard, art)
    art = copy.deepcopy(CLEAN)
    art["note"] = CANARY.replace("-", "_")                          # punctuation changes do not hide it
    assert "CANARY" in kinds(guard, art)


def test_private_prompt_text_caught_even_when_partially_quoted(guard):
    p = ITEMS[0]["prompt"]
    words = p.split()
    art = copy.deepcopy(CLEAN)
    art["note"] = "the model was asked: " + " ".join(words[4:16])         # 12 consecutive words from the middle of a private prompt
    assert "PROMPT_TEXT" in kinds(guard, art)
    art["note"] = " ".join(words[:7])                                      # fewer than 8 consecutive words: below the detection window
    assert "PROMPT_TEXT" not in kinds(guard, art)


def test_private_answer_text_caught(guard):
    ans = ITEMS[1]["ground_truth"]["answer"]
    art = copy.deepcopy(CLEAN)
    art["note"] = f"expected was {ans}"
    assert "ANSWER_TEXT" in kinds(guard, art)


def test_findings_never_contain_the_leaked_text(guard):
    art = copy.deepcopy(CLEAN)
    art["note"] = f"{CANARY} " + " ".join(ITEMS[0]["prompt"].split()[2:14]) + " " + ITEMS[1]["ground_truth"]["answer"]
    blob = repr(guard.scan(art))
    assert CANARY not in blob and ITEMS[1]["ground_truth"]["answer"] not in blob and ITEMS[0]["prompt"].split()[5] + " " + ITEMS[0]["prompt"].split()[6] not in blob
    with pytest.raises(LeakageDetected) as e:
        guard.assert_clean(art)
    assert CANARY not in str(e.value)


def test_overlong_free_text_flagged_as_suspicious(guard):
    art = copy.deepcopy(CLEAN)
    art["note"] = "x" * 600
    assert "LONG_STRING" in kinds(guard, art)


def test_string_artifacts_scanned_too(guard):
    assert "CANARY" in kinds(guard, f"# report\n\nsome text {CANARY}")
    assert guard.scan("# report\n\nall good") == []


def test_short_hidden_answers_are_a_documented_limitation_covered_by_structure(guard):
    short = LeakGuard(items=[{"prompt": "irrelevant short prompt", "ground_truth": {"answer": "42"}}])
    assert short.scan({"note": "the answer is 42"}) == []            # text search cannot responsibly find a 2-char answer ...
    assert "FORBIDDEN_KEY" in {f["kind"] for f in short.scan({"answer": "42"})}      # ... the structural whitelist is what protects it


def test_short_canary_refused():
    with pytest.raises(SchemaViolation):
        LeakGuard(canaries=["abc"])


def test_empty_guard_has_no_private_material_and_still_checks_structure():
    g = LeakGuard()
    assert g.has_private_material is False
    assert "FORBIDDEN_KEY" in kinds(g, {"prompt": "x"})
