"""Genesis V2 contamination controls + SCREEN/QUALIFICATION_HOLDOUT isolation. All V2 items here are synthetic in-test values (no private corpus)."""
import copy
import json
import re
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import isolation as ISO
from orca.eval.genesis_v2 import similarity as S
from orca.eval.genesis_v2 import spec

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "eval_private/genesis_capability_eval_v1"


@pytest.fixture(scope="module")
def v1_rows():
    return [json.loads(l) for f in ("dev", "pilot_train", "holdout") for l in (V1 / f"{f}.jsonl").read_text().splitlines() if l.strip()]


@pytest.fixture(scope="module")
def v1_recs():
    recs, err = C.load_v1_reference(ROOT)
    assert recs, err
    return recs


def pick(rows, cat, pred=lambda r: True, nth=0):
    return [r for r in rows if r["category"] == cat and pred(r)][nth]


def v2(base: dict, i: int, **over) -> dict:
    d = copy.deepcopy(base)
    for k in ("sha256", "private_holdout", "authoring_source"):
        d.pop(k, None)
    d.update({"item_id": "gce2-" + f"{i:024x}", "split": "SCREEN", "cluster": f"c{i}"})
    d.update(over)
    return d


TEXTS = [
    "Harbour authorities publish tide tables every quarter, so a pilot planning a night arrival must decide which of the three published windows leaves the widest safety margin below the keel.",
    "When a bakery doubles its oven capacity but keeps a single delivery van, which stage of the morning routine becomes the bottleneck, and what measurement would confirm that guess?",
    "Consider a glacier survey team choosing between drones and ground radar: list the failure modes each tool hides, then recommend one, giving the observation that would overturn your pick.",
    "A library digitising rare maps finds that scanner colour drift correlates with room humidity; propose the cheapest experiment separating humidity from lamp ageing as the cause.",
]


def fresh(i: int, cat="research") -> dict:
    """A structurally and lexically unrelated synthetic item."""
    return {"item_id": "gce2-" + f"{i:024x}", "split": "SCREEN", "category": cat, "cluster": f"fresh{i}", "difficulty": "medium",
            "prompt": TEXTS[i % len(TEXTS)] + f" (variant marker {i})", "input": {}, "system": None,
            "ground_truth": {"answer": f"synthetic-answer-{i}", "match": "text"}, "meta": {"note": f"fresh-{i}"}, "creation_method": f"unit-test-{i}"}


def status(results, name):
    return next(r for r in results if r.name == name)


# ---------------------------------------------------------------- A. exact reuse
def test_clean_item_passes_every_v1_check(v1_recs):
    res = C.check_v1_contamination([fresh(0), fresh(1), fresh(2), fresh(3)], v1_recs)
    assert all(r.status == C.PASS for r in res), [(r.name, r.status) for r in res if r.status != C.PASS]


def test_exact_prompt_reuse_blocked(v1_recs, v1_rows):
    src = pick(v1_rows, "reasoning")
    r = status(C.check_v1_contamination([v2(src, 1)], v1_recs), "v1_exact_reuse")
    assert r.status == C.FAIL and {f["kind"] for f in r.findings} >= {"PROMPT_NORMALIZED", "CONTENT"}


def test_normalized_prompt_reuse_blocked(v1_recs, v1_rows):
    src = pick(v1_rows, "reasoning")
    it = v2(src, 2, prompt=src["prompt"].upper().replace(".", " ;; ").replace(",", " -- "))
    r = status(C.check_v1_contamination([it], v1_recs), "v1_exact_reuse")
    assert r.status == C.FAIL and any(f["kind"] == "PROMPT_NORMALIZED" for f in r.findings)


def test_v1_item_id_reuse_blocked(v1_recs, v1_rows):
    it = fresh(5)
    it["item_id"] = v1_rows[0]["item_id"]
    r = status(C.check_v1_contamination([it], v1_recs), "v1_exact_reuse")
    assert r.status == C.FAIL and any(f["kind"] == "ITEM_ID" for f in r.findings)


def test_v1_answer_reuse_blocked_when_prompt_is_new(v1_recs, v1_rows):
    src = pick(v1_rows, "structured_outputs")
    it = fresh(6)
    it["ground_truth"] = copy.deepcopy(src["ground_truth"])
    r = status(C.check_v1_contamination([it], v1_recs), "v1_answer_reuse")
    assert r.status == C.FAIL and r.findings[0]["kind"] == "ANSWER_EXACT_HIGH_ENTROPY"


def test_low_entropy_answer_alone_is_not_flagged_but_with_similar_prompt_it_is(v1_recs, v1_rows):
    src = pick(v1_rows, "reasoning")
    assert not C.high_entropy_answer(S.make_rec(src))                     # short answers: innocent collisions are expected
    it = fresh(7)
    it["ground_truth"] = copy.deepcopy(src["ground_truth"])
    assert status(C.check_v1_contamination([it], v1_recs), "v1_answer_reuse").status == C.PASS
    clone = v2(src, 8, prompt=src["prompt"] + " Take care.")              # answer identical AND prompt similar
    assert status(C.check_v1_contamination([clone], v1_recs), "v1_answer_reuse").status == C.FAIL


def test_reference_solution_reuse_blocked(v1_recs, v1_rows):
    src = pick(v1_rows, "coding")
    leaves = [x for x in S.string_leaves(src["ground_truth"]) if len(S.normalize(x)) >= S.MIN_LEAF_CHARS]
    assert leaves, "coding items must carry a long reference/solution string"
    it = fresh(9, "coding")
    it["ground_truth"] = {"reference": leaves[0], "tests": ["assert True"]}
    r = status(C.check_v1_contamination([it], v1_recs), "v1_reference_solution_reuse")
    assert r.status == C.FAIL and r.findings[0]["kind"] == "REFERENCE_LEAF"


def test_generator_instance_material_reuse_blocked(v1_recs, v1_rows):
    src = pick(v1_rows, "mathematics")
    it = fresh(10, "mathematics")
    it["meta"], it["creation_method"] = copy.deepcopy(src["meta"]), src["creation_method"]
    r = status(C.check_v1_contamination([it], v1_recs), "v1_instance_seed_reuse")
    assert r.status == C.FAIL and r.findings[0]["kind"] == "INSTANCE_MATERIAL"


# ---------------------------------------------------------------- B. near-duplicate, C. structural/template
def test_near_duplicate_prompt_blocked(v1_recs, v1_rows):
    src = pick(v1_rows, "research")
    words = src["prompt"].split(" ")
    words[len(words) // 2] = "REPLACED"
    it = v2(src, 11, prompt=" ".join(words), ground_truth={"answer": "different", "match": "text"})
    res = C.check_v1_contamination([it], v1_recs)
    assert status(res, "v1_near_duplicate").status == C.FAIL and status(res, "v1_near_duplicate").findings[0]["score"] >= C.NEAR_DUP_JACCARD


NAMES = ["Zed", "Quill", "Brannoch", "Ottoline", "Pemberly", "Tamsin", "Wystan", "Ilvane"]


def _rename_and_renumber(prompt: str) -> str:
    seen = {}

    def name(m):
        w = m.group(0)
        if w not in seen:
            seen[w] = NAMES[len(seen) % len(NAMES)] + ("x" * (len(seen) // len(NAMES)))
        return seen[w]
    out = re.sub(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", name, prompt)
    return re.sub(r"\d+", lambda m: str(int(m.group(0)) * 3 + 7), out)


@pytest.mark.parametrize("cat", ["instruction_following", "research", "hypothesis_testing", "tool_use", "evidence_use", "counterfactual_reasoning"])
def test_renamed_and_renumbered_clone_is_blocked(v1_recs, v1_rows, cat):
    src = pick(v1_rows, cat, lambda r: len((r["prompt"] or "").split()) >= 30)
    clone = v2(src, 12, prompt=_rename_and_renumber(src["prompt"]), ground_truth={"answer": "zzz-different", "match": "text"}, meta={"x": 1}, creation_method="unit-test")
    assert clone["prompt"] != src["prompt"]
    res = C.check_v1_contamination([clone], v1_recs)
    st = status(res, "v1_structural_clone")
    assert st.status == C.FAIL and st.findings[0]["score"] >= C.STRUCT_CLONE_JACCARD, (cat, st.findings[:1])


def test_reordered_sentences_are_still_a_structural_clone(v1_recs, v1_rows):
    src = pick(v1_rows, "information_gain_reasoning", lambda r: len(re.split(r"(?<=[.?!])\s+", r["prompt"])) >= 5)
    sents = re.split(r"(?<=[.?!])\s+", src["prompt"])
    clone = v2(src, 13, prompt=" ".join(reversed(sents)), ground_truth={"answer": "q", "match": "text"}, meta={"x": 2}, creation_method="unit-test")
    res = C.check_v1_contamination([clone], v1_recs)
    assert status(res, "v1_structural_clone").status == C.FAIL or status(res, "v1_near_duplicate").status == C.FAIL


def test_short_prompts_are_reported_structurally_unassessable_never_pass(v1_recs):
    short = fresh(14)
    short["prompt"] = "What is two plus five?"
    r = status(C.check_v1_contamination([short], v1_recs), "v1_structure_assessability")
    assert r.status == C.INCOMPLETE and "manual" in r.note


def test_threshold_mutation_makes_detection_disappear_so_the_tests_are_not_vacuous(v1_recs, v1_rows, monkeypatch):
    src = pick(v1_rows, "research")
    clone = v2(src, 15, prompt=_rename_and_renumber(src["prompt"]), ground_truth={"answer": "n", "match": "text"}, meta={"x": 3}, creation_method="u")
    assert status(C.check_v1_contamination([clone], v1_recs), "v1_structural_clone").status == C.FAIL
    monkeypatch.setattr(C, "STRUCT_CLONE_JACCARD", 1.01)
    assert status(C.check_v1_contamination([clone], v1_recs), "v1_structural_clone").status == C.PASS


def test_thresholds_are_documented_with_their_calibration():
    doc = C.__doc__
    assert "0.414" in doc and "0.565" in doc and "3082" in doc and C.NEAR_DUP_JACCARD == 0.60 and C.STRUCT_CLONE_JACCARD == 0.75


def test_v1_reference_unavailable_or_tampered_is_dataset_unavailable_not_pass(tmp_path):
    recs, err = C.load_v1_reference(tmp_path)
    assert recs is None and err
    res = C.check_v1_contamination([fresh(0)], recs, unavailable_reason=err)
    assert [r.status for r in res] == [C.DATASET_UNAVAILABLE] and not C.overall(res)["pass"]
    import shutil
    dst = tmp_path / "repo"
    (dst / "docs/orneur/phase-21").mkdir(parents=True)
    shutil.copy(ROOT / C.STATUS_RECORD, dst / C.STATUS_RECORD)
    (dst / C.V1_DIR).mkdir(parents=True)
    for f in C.V1_FILES:
        shutil.copy(ROOT / C.V1_DIR / f, dst / C.V1_DIR / f)
    assert C.load_v1_reference(dst)[0]
    (dst / C.V1_DIR / "dev.jsonl").write_text((dst / C.V1_DIR / "dev.jsonl").read_text() + "\n")
    assert C.load_v1_reference(dst)[0] is None


# ---------------------------------------------------------------- E. training corpora
def _corpus(tmp_path, name, texts):
    p = tmp_path / f"{name}.jsonl"
    p.write_text("\n".join(json.dumps({"text": t}) for t in texts) + "\n")
    return C.FileTrainingCorpus(name, p)


def test_training_corpora_unavailable_is_fail_closed(tmp_path):
    items = [fresh(0)]
    missing = C.FileTrainingCorpus("adapt", tmp_path / "nope.jsonl")
    assert C.check_training_corpora(items, {"adapt": missing}, required=("adapt",), declared_complete=True)[0].status == C.DATASET_UNAVAILABLE
    assert C.check_training_corpora(items, {}, required=("adapt",), declared_complete=True)[0].status == C.DATASET_UNAVAILABLE
    r = C.check_training_corpora(items, {"adapt": _corpus(tmp_path, "adapt", ["x"])}, required=("adapt",), declared_complete=False)[0]
    assert r.status == C.INCOMPLETE                                        # list of corpora not declared complete => never PASS
    assert not C.overall([r])["pass"]


def test_training_corpus_overlap_is_detected_and_clean_passes(tmp_path):
    items = [fresh(0), fresh(1)]
    clean = _corpus(tmp_path, "sft", ["An entirely unrelated instruction about repotting orchids in winter with a bark mix."])
    assert C.check_training_corpora(items, {"sft": clean}, required=("sft",), declared_complete=True)[0].status == C.PASS
    dirty = _corpus(tmp_path, "sft2", [items[0]["prompt"], "another"])
    r = C.check_training_corpora(items, {"sft2": dirty}, required=("sft2",), declared_complete=True)[0]
    assert r.status == C.FAIL and r.findings[0]["kind"] in ("EXACT", "NEAR_DUPLICATE")
    near = _corpus(tmp_path, "sft3", [items[1]["prompt"].replace("cheapest", "costliest")])
    assert C.check_training_corpora(items, {"sft3": near}, required=("sft3",), declared_complete=True)[0].status == C.FAIL


def test_real_public_sft_corpora_are_available_sources_and_clean_item_passes():
    cls = json.loads((ROOT / "docs/orneur/phase-21/PUBLIC_SFT_DATASET_CLASSIFICATION.json").read_text())
    srcs = {Path(p).stem: C.FileTrainingCorpus(Path(p).stem, ROOT / p) for p in cls["files"]}
    assert all(s.available() for s in srcs.values())
    r = C.check_training_corpora([fresh(0)], srcs, required=tuple(srcs), declared_complete=True)[0]
    assert r.status == C.PASS


# ---------------------------------------------------------------- F. semantic hook
def test_semantic_checker_is_not_configured_and_never_passes():
    r = C.check_semantic(C.NotConfiguredSemanticChecker(), [fresh(0)], [])
    assert r.status == C.NOT_CONFIGURED and "not performed" in r.note

    class Liar:                                   # claims PASS but is not configured
        configured, local_private = False, True

        def check(self, a, b):
            return C.CheckResult("semantic_overlap", C.PASS, [])
    assert C.check_semantic(Liar(), [], []).status == C.NOT_CONFIGURED

    class Remote:                                 # configured but not local/private => refused (no provider inference)
        configured, local_private = True, False

        def check(self, a, b):
            return C.CheckResult("semantic_overlap", C.PASS, [])
    assert C.check_semantic(Remote(), [], []).status == C.NOT_CONFIGURED


def test_contamination_controls_pass_requires_semantic_and_training(v1_recs):
    res = C.check_v1_contamination([fresh(0), fresh(1)], v1_recs)
    assert not C.contamination_controls_pass(res)                                     # training + semantic missing
    res2 = res + [C.CheckResult("training_corpora", C.PASS, [])]
    assert not C.contamination_controls_pass(res2)                                    # semantic still missing
    res3 = res2 + [C.check_semantic(C.NotConfiguredSemanticChecker(), [], [])]
    assert not C.contamination_controls_pass(res3)                                    # NOT_CONFIGURED is not PASS

    class Stub:                                                                        # test-only stand-in for a future authorized local mechanism
        configured, local_private = True, True

        def check(self, a, b):
            return C.CheckResult("semantic_overlap", C.PASS, [])
    res4 = res2 + [C.check_semantic(Stub(), [], [])]
    assert C.contamination_controls_pass(res4)
    assert not C.contamination_controls_pass(res4[:-1])
    st = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert st["contamination_status"]["contamination_controls_pass"] is False and st["freeze_prerequisites"]["contamination_controls_pass"] is False


# ---------------------------------------------------------------- SCREEN vs QUALIFICATION_HOLDOUT isolation
def hold(i, **kw):
    d = fresh(i)
    d.update({"split": "QUALIFICATION_HOLDOUT", "item_id": "gce2-" + f"{i + 500:024x}", "cluster": f"h{i}"})
    d.update(kw)
    return d


def _iso(items):
    return {r.name: r for r in ISO.check_split_isolation(items)}


def test_separation_policy_table_is_explicit_and_fail_by_default():
    assert not ISO.policy_problems()
    assert set(ISO.SEPARATION_POLICY) == set(spec.CATEGORIES)
    for c, p in ISO.SEPARATION_POLICY.items():
        if p["applicable"]:
            assert p["shared_cluster_policy"] == "FAIL" and p["near_duplicate"] == "FAIL" and p["independence_justification"] is None
    assert ISO.SEPARATION_POLICY["long_context"]["structural_fingerprint"].startswith("LIMITED")
    assert not ISO.SEPARATION_POLICY["latency"]["applicable"]


def test_clean_splits_in_reliable_category_pass_isolation():
    items = [fresh(0), fresh(1), hold(2), hold(3)]
    res = _iso(items)
    assert all(r.status == C.PASS for r in res.values()), {n: (r.status, r.findings) for n, r in res.items() if r.status != C.PASS}
    assert ISO.screen_holdout_separation_pass(list(res.values()))


def test_limited_structure_categories_never_pass_without_manual_review():
    a, b = fresh(0, "mathematics"), hold(2, category="mathematics")
    res = _iso([a, b])
    assert res["isolation_structure_review"].status == C.INCOMPLETE
    assert not ISO.screen_holdout_separation_pass(list(res.values()))


def test_duplicate_item_id_and_content_and_text_fail():
    a = fresh(0)
    assert _iso([a, hold(2, item_id=a["item_id"])])["isolation_item_id"].status == C.FAIL
    twin = hold(3, prompt=a["prompt"], ground_truth=a["ground_truth"], input=a["input"], system=a["system"])
    res = _iso([a, twin])
    assert res["isolation_content_commitment"].status == C.FAIL and res["isolation_text_fingerprint"].status == C.FAIL
    punct = hold(3, prompt=a["prompt"].upper().replace(",", ";"))
    assert _iso([a, punct])["isolation_text_fingerprint"].status == C.FAIL


def test_duplicate_hidden_answer_fails_when_high_entropy_and_ignored_when_trivial():
    a = fresh(0)
    a["ground_truth"] = {"answer": "a long, specific, high-entropy hidden reference answer string", "match": "text"}
    b = hold(2, ground_truth=copy.deepcopy(a["ground_truth"]))
    assert _iso([a, b])["isolation_hidden_answer"].status == C.FAIL
    c, d = fresh(0), hold(2)
    c["ground_truth"], d["ground_truth"] = {"answer": "B"}, {"answer": "B"}
    assert _iso([c, d])["isolation_hidden_answer"].status == C.PASS            # trivial answers collide innocently
    e = fresh(0)
    e["ground_truth"] = {"reference": "def solve(xs):\n    return sorted(set(xs))[1:]  # hidden reference solution"}
    f = hold(2, ground_truth={"solution": "def solve(xs):\n    return sorted(set(xs))[1:]  # hidden reference solution", "note": "x"})
    assert _iso([e, f])["isolation_hidden_answer"].status == C.FAIL             # same reference under different field names


def test_near_duplicate_across_splits_fails():
    a = fresh(0)
    words = a["prompt"].split(" ")
    words[5] = "CHANGED"
    assert _iso([a, hold(2, prompt=" ".join(words))])["isolation_near_duplicate"].status == C.FAIL


def test_cross_split_structural_clone_fails():
    a = fresh(0)
    clone = hold(2, prompt=re.sub(r"\b(Harbour|tide|tables|pilot|night|arrival|published|windows|safety|margin|keel|quarter|authorities)\b", "zork", a["prompt"]))
    res = _iso([a, clone])
    assert res["isolation_structural_clone"].status == C.FAIL or res["isolation_near_duplicate"].status == C.FAIL


def test_shared_high_risk_template_cluster_fails_and_missing_cluster_fails():
    a, b = fresh(0), hold(2, cluster="fresh0")                                  # same generation cluster in both splits
    r = _iso([a, b])["isolation_shared_cluster"]
    assert r.status == C.FAIL and r.findings[0]["category"] == "research"
    c, d = fresh(0), hold(2)
    c["cluster"] = ""
    assert _iso([c, d])["isolation_shared_cluster"].status == C.FAIL
    assert ISO.check_split_isolation([fresh(0)])[0].status == C.INCOMPLETE      # one split only => INCOMPLETE, never PASS


def test_relaxing_a_category_requires_documented_independence(monkeypatch):
    pol = copy.deepcopy(ISO.SEPARATION_POLICY)
    pol["research"]["shared_cluster_policy"] = "ALLOW"
    monkeypatch.setattr(ISO, "SEPARATION_POLICY", pol)
    assert any("research" in p for p in ISO.policy_problems())
    pol["research"]["independence_justification"] = "clusters are drawn from disjoint document collections with independently sourced ground truth, audited manually"
    assert not [p for p in ISO.policy_problems() if "research" in p]


def test_isolation_findings_never_contain_item_content():
    a = fresh(0)
    b = hold(2, prompt=a["prompt"], ground_truth=a["ground_truth"])
    blob = json.dumps([r.as_dict() for r in ISO.check_split_isolation([a, b])])
    assert a["prompt"] not in blob and "synthetic-answer" not in blob
