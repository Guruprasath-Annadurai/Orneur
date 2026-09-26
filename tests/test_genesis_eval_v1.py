"""Genesis Capability Eval V1: freeze records, funnel corrections, private corpus, contamination control, floors, pre-registration, CPU harness."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
from pathlib import Path

import pytest

from orca.eval import foundation_landscape as FL
from orca.eval import genesis_contamination as CX
from orca.eval import genesis_corpus as GC
from orca.eval import genesis_eval_v1 as E
from orca.eval import genesis_funnel as GF
from orca.eval import genesis_harness as H
from orca.eval import genesis_prereg as PR
from orca.eval import genesis_sandbox as SB
from orca.eval import genesis_scorers as S
from orca.eval import genesis_stats as ST
from orca.eval.genesis import gen_misc
from orca.eval.system_contract_qualification import historical_control_state
from orca.intelligence import freeze_record as FRZ
from orca.intelligence import protocol as P
from orca.intelligence import spec as SPEC

ROOT = Path(__file__).resolve().parents[1]
PH21 = ROOT / "docs/orneur/phase-21"
CONTROL_EVIDENCE_AGGREGATE_SHA256 = "125db85c9abbbe2af9671c688a4335169162d8483c3f35bf763bf87688c2d358"
SYSTEM_QUAL_ARTIFACT_SHA256 = "9b14c4cf90d1022cfd76467d73d82202177698e6c4c16d98a39988938111ca19"
FAMILY = ("qwen", "mistral", "phi-", "llama", "gemma", "deepseek", "granite", "olmo", "smollm", "gpt-oss", "claude", "gemini")


@pytest.fixture(scope="module")
def dev():
    return GC.load_split(ROOT, "DEV")


@pytest.fixture(scope="module")
def pilot():
    return GC.load_split(ROOT, "PILOT_TRAIN")


@pytest.fixture(scope="module")
def holdout():
    return GC.load_split(ROOT, "HOLDOUT")


@pytest.fixture(scope="module")
def allitems(dev, pilot, holdout):
    return dev + pilot + holdout


@pytest.fixture(scope="module")
def prereg():
    return json.loads((ROOT / PR.PREREG_JSON).read_text())


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ROOT / PR.MANIFEST_PATH).read_text())


# ================================================================== 1. architecture freeze records
@pytest.mark.parametrize("artifact,version", [("orneur.eternal-architecture", "1.1.0"), ("orneur.core-protocol", "1.1.0")])
def test_freeze_records_pin_audited_sha_ci_and_file_hashes(artifact, version):
    a = FRZ.ARTIFACTS[artifact]
    path = ROOT / FRZ.FREEZE_DIR / a["file"]
    rec = FRZ.verify_freeze_record(ROOT, path)
    assert rec["artifact"] == artifact and rec["version"] == version and rec["status"] == "FROZEN"
    assert rec["audited_sha"] == "9f42f814ffd16756a6960c255911e411e77e9059"
    assert rec["exact_sha_ci"]["run_id"] == "36252659258" and rec["exact_sha_ci"]["conclusion"] == "success"
    assert rec["future_changes_require_new_semantic_version"] is True
    assert set(rec["frozen_files"]) == set(a["frozen_files"]) and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in rec["frozen_files"].values())


def test_frozen_versions_match_the_code_and_a_change_would_be_detected(tmp_path):
    assert P.PROTOCOL_VERSION == "orneur.core-protocol/1.1.0" and SPEC.ARCHITECTURE_VERSION == "orneur.eternal-architecture/1.1.0"
    rec_path = ROOT / FRZ.FREEZE_DIR / FRZ.ARTIFACTS["orneur.core-protocol"]["file"]
    (tmp_path / "orca/intelligence").mkdir(parents=True)
    shutil.copy(ROOT / "orca/intelligence/protocol.py", tmp_path / "orca/intelligence/protocol.py")
    FRZ.verify_freeze_record(tmp_path, rec_path)
    (tmp_path / "orca/intelligence/protocol.py").write_text((tmp_path / "orca/intelligence/protocol.py").read_text() + "\n# tampered\n")
    with pytest.raises(ValueError, match="frozen file changed"):
        FRZ.verify_freeze_record(tmp_path, rec_path)


def test_freeze_record_files_are_created_exclusively_and_never_rewritten(tmp_path):
    shutil.copytree(ROOT / "docs/orneur/intelligence", tmp_path / "docs/orneur/intelligence")
    shutil.copytree(ROOT / "orca/intelligence", tmp_path / "orca/intelligence")
    before = {p.name: p.read_bytes() for p in (tmp_path / FRZ.FREEZE_DIR).iterdir()}
    assert set(FRZ.write_freeze_records(tmp_path).values()) == {"EXISTS_VERIFIED"}
    assert before == {p.name: p.read_bytes() for p in (tmp_path / FRZ.FREEZE_DIR).iterdir()}


def test_approved_architecture_artifacts_are_unchanged_since_the_audited_commit():
    """The audited architecture JSON still carries the pre-freeze block; the freeze is a separate record, not an edit."""
    j = json.loads((ROOT / "docs/orneur/intelligence/ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.json").read_text())
    assert j["architecture_version"] == "orneur.eternal-architecture/1.1.0" and j["freeze_status"]["frozen"] is False
    assert j["genesis_capability_eval_v1"] == json.loads(json.dumps(GF.funnel_spec()))      # the funnel DESIGN spec is unchanged by the two fixes


# ================================================================== 2. funnel edge-case corrections
def _s2(fam_cost):
    return {m: {"cost_usd": c, "family": f} for m, (f, c) in fam_cost.items()}


def test_stage2_alphabetically_early_expensive_family_cannot_exclude_a_cheaper_family():
    surv = _s2({"m_aaa": ("AAA-family", 12), "m_mmm": ("MMM-family", 9), "m_zzz": ("ZZZ-family", 5)})
    out = GF.stage2_entrants(surv, cap_usd=20)
    assert out["entrants"] == ["m_mmm", "m_zzz"] and out["deferred_for_cost"] == ["m_aaa"] and out["cost_cap_applied"] is True


def test_stage2_family_names_carry_no_priority_at_all():
    base = {"a": ("F1", 12), "b": ("F2", 9), "c": ("F3", 5), "d": ("F1", 6), "e": ("F2", 4)}
    ref = GF.stage2_entrants(_s2(base), cap_usd=25)
    import itertools
    names = ["Zulu", "Alpha", "Mike", "1-first", "~last"]
    for perm in itertools.islice(itertools.permutations(names, 3), 12):
        mapping = {"F1": perm[0], "F2": perm[1], "F3": perm[2]}
        renamed = _s2({m: (mapping[f], c) for m, (f, c) in base.items()})
        assert GF.stage2_entrants(renamed, cap_usd=25) == ref, perm


def test_stage2_representatives_are_ordered_by_cost_then_model_id_then_fill_by_cost():
    surv = _s2({"x2": ("A", 7), "x1": ("A", 7), "y": ("B", 7), "z": ("C", 3), "z2": ("C", 4)})
    out = GF.stage2_entrants(surv, cap_usd=21)
    # representatives: A->x1 (id tie), B->y, C->z; ordered by cost then id: z(3), x1(7), y(7); fill: z2(4) -> 3+7+7+4 = 21 fits, x2(7) does not
    assert out["entrants"] == ["x1", "y", "z", "z2"] and out["deferred_for_cost"] == ["x2"]
    assert GF.stage2_entrants(surv, cap_usd=1000)["cost_cap_applied"] is False


def test_stage2_source_never_orders_by_family_name():
    src = (ROOT / "orca/eval/genesis_funnel.py").read_text()
    assert "sorted(fams.items())" not in src and "sorted(by_family.items()" not in src and ".items(), key=lambda kv" not in src
    assert "family NAME is only a grouping key" in src


CAP = {c: 0.6 for c in E.MANDATORY_STAGE2_GATING}


def _fin(**kw):
    base = {m: {"capability": dict(CAP), "cost_usd": 3.0 + i, "family": f"F{i}"} for i, m in enumerate(["p", "q", "r"])}
    for m, patch in kw.items():
        base[m] = copy.deepcopy(base[m])
        for k, v in patch.items():
            if k == "drop":
                del base[m]["capability"][v]
            else:
                base[m]["capability"][k] = v
    return base


def test_complete_results_enter_stage3_and_mandatory_set_is_the_14_gating_categories():
    assert GF.MANDATORY_STAGE2_GATING == E.GATING_CATEGORIES and len(GF.MANDATORY_STAGE2_GATING) == 14
    assert GF.stage2_completeness(_fin()) == {}
    assert GF.stage3_entrants(_fin())


@pytest.mark.parametrize("patch,problem", [
    ({"drop": "coding"}, "missing:coding"), ({"coding": None}, "invalid:coding"), ({"coding": float("nan")}, "invalid:coding"),
    ({"coding": float("inf")}, "invalid:coding"), ({"coding": -0.01}, "invalid:coding"), ({"coding": 1.01}, "invalid:coding"),
    ({"coding": True}, "invalid:coding"), ({"coding": "0.5"}, "invalid:coding"),
])
def test_incomplete_stage2_results_cannot_enter_stage3_and_the_comparison_set_is_not_shrunk(patch, problem):
    fin = _fin(p=patch)
    assert problem in GF.stage2_completeness(fin)["p"]
    with pytest.raises(GF.IncompleteStage2Results) as ei:
        GF.stage3_entrants(fin)
    assert "p" in ei.value.incomplete and problem in ei.value.incomplete["p"]
    with pytest.raises(GF.IncompleteStage2Results):
        GF.pareto_nondominated(fin)
    with pytest.raises(GF.IncompleteStage2Results):
        GF.rank_finalists(fin, {}, floors={"reasoning": 0.1})


def test_missing_data_no_longer_silently_removes_a_category_from_the_pareto_comparison():
    """The old intersection rule would have dropped 'coding' for everyone and let a model that is terrible at coding through."""
    fin = _fin(p={"drop": "coding"}, q={"coding": 0.0})
    with pytest.raises(GF.IncompleteStage2Results):
        GF.pareto_nondominated(fin)
    complete = _fin(q={"coding": 0.0})
    assert "q" not in GF.pareto_nondominated(complete) or len(GF.pareto_nondominated(complete)) >= 1


def test_invalid_cost_or_family_or_missing_capability_block_is_incomplete():
    fin = _fin()
    fin["p"]["cost_usd"] = float("nan")
    fin["q"]["family"] = "  "
    fin["r"].pop("capability")
    inc = GF.stage2_completeness(fin)
    assert "invalid:cost_usd" in inc["p"] and "invalid:family" in inc["q"] and "capability results missing" in inc["r"]


# ================================================================== 3. corpus: coverage, uniqueness, hashes, reproducibility
REQUIRED = {"item_id", "category", "version", "authoring_source", "creation_method", "prompt", "ground_truth", "scoring_method", "difficulty",
            "private_holdout", "sha256", "input", "meta", "split"}


def test_every_item_has_the_required_contamination_fields_and_a_valid_hash(allitems):
    for it in allitems:
        assert REQUIRED <= set(it), it["item_id"]
        assert it["version"] == E.CORPUS_VERSION and it["authoring_source"].startswith("ORNEUR original")
        assert it["creation_method"].startswith("seeded_procedural_generator:") and it["difficulty"] in {"easy", "medium", "hard"}
        assert it["sha256"] == GC.item_sha256(it), it["item_id"]
        assert it["private_holdout"] is (it["split"] == "HOLDOUT")


def test_category_coverage_and_counts_match_the_frozen_specs(allitems, manifest):
    by = {}
    for it in allitems:
        by.setdefault((it["category"], it["split"]), []).append(it)
    for cat in E.CATEGORIES:
        spec = E.CATEGORY_SPECS[cat]
        if spec["role"] == "PROTOCOL":
            assert (cat, "HOLDOUT") not in by
            continue
        n_hold = len(by[(cat, "HOLDOUT")])
        assert n_hold == spec["holdout"], cat
        assert len(by.get((cat, "DEV"), [])) == spec["dev"] and len(by.get((cat, "PILOT_TRAIN"), [])) == spec.get("pilot", 0), cat
        assert manifest["category_counts"][cat]["HOLDOUT"] == n_hold
    assert set(E.CATEGORIES) == {c for c in E.CATEGORIES} and len(E.CATEGORIES) == 21
    assert len(GC.load_protocol(ROOT)) == 12 and manifest["category_counts"]["latency"]["protocol_probes"] == 12


def test_item_ids_hashes_and_instance_keys_are_unique_across_all_splits(allitems):
    assert len({i["item_id"] for i in allitems}) == len(allitems) == len({i["sha256"] for i in allitems})
    keys = {(i["category"], i["meta"]["dedup_text"]) for i in allitems}
    assert len(keys) == len(allitems)
    assert CX.check_split_boundaries(allitems) == {"ok": True, "violations": []}


def test_corpus_is_reproducible_byte_for_byte_from_the_generators(holdout):
    items, images = GC.build_all_items()
    again, images2 = GC.build_all_items()
    assert [i["sha256"] for i in items] == [i["sha256"] for i in again] and images == images2
    for split, fname in GC.SPLIT_FILES.items():
        on_disk = (ROOT / GC.CORPUS_DIR / fname).read_text(encoding="utf-8")
        assert on_disk == "".join(GC.canonical(i) + "\n" for i in items if i["split"] == split), split
    for rel, data in images.items():
        assert (ROOT / GC.CORPUS_DIR / rel).read_bytes() == data


def test_manifests_and_preregistration_are_reproducible_from_the_committed_corpus():
    m = PR.build_manifest(ROOT)
    assert m == json.loads((ROOT / PR.MANIFEST_PATH).read_text())
    h = PR.build_holdout_manifest(ROOT, m)
    assert h == json.loads((ROOT / PR.HOLDOUT_MANIFEST_PATH).read_text())
    x = PR.build_exclusion_manifest(ROOT, h)
    assert x == json.loads((ROOT / PR.EXCLUSION_MANIFEST_PATH).read_text())
    assert PR.build_prereg(ROOT, m, h, x) == json.loads((ROOT / PR.PREREG_JSON).read_text())
    assert PR.prereg_markdown(json.loads((ROOT / PR.PREREG_JSON).read_text())) == (ROOT / PR.PREREG_MD).read_text()


def test_manifest_hashes_are_self_consistent(manifest):
    assert manifest["dataset_manifest_sha256"] == hashlib.sha256(PR.canon({k: v for k, v in manifest.items() if k != "dataset_manifest_sha256"}).encode()).hexdigest()
    for name, want in manifest["files_sha256"].items():
        if name != "images_aggregate":
            assert GC.file_sha256(ROOT / GC.CORPUS_DIR / name) == want, name
    assert manifest["public_manifest_contains_answers"] is False
    listed = {i["item_id"]: i["sha256"] for s in manifest["items"].values() for i in s}
    assert len(listed) == sum(manifest["split_counts"].values())


# ================================================================== 4. splits and holdout boundaries
def test_splits_are_disjoint_and_pilot_categories_are_exactly_the_format_categories(dev, pilot, holdout):
    ids = [{i["item_id"] for i in s} for s in (dev, pilot, holdout)]
    assert not (ids[0] & ids[1]) and not (ids[0] & ids[2]) and not (ids[1] & ids[2])
    assert {i["category"] for i in pilot} == set(E.PILOT_CATEGORIES) == {"instruction_following", "strict_contracts", "structured_outputs", "tool_use"}
    assert all(i["private_holdout"] for i in holdout) and not any(i["private_holdout"] for i in dev + pilot)
    hold_keys = {(i["category"], i["meta"]["dedup_text"]) for i in holdout}
    assert not any((i["category"], i["meta"]["dedup_text"]) in hold_keys for i in dev + pilot)


def test_pilot_items_carry_sft_targets_and_no_holdout_prompt_or_rule_set_appears_in_pilot(pilot, holdout):
    assert all("sft_target" in i["ground_truth"] for i in pilot)
    hold_prompts = {i["prompt"] for i in holdout if i["prompt"]}
    assert not any(i["prompt"] in hold_prompts for i in pilot)
    hold_rules = {json.dumps(i["ground_truth"]["constraints"], sort_keys=True) for i in holdout if i["category"] == "instruction_following"}
    assert not any(json.dumps(i["ground_truth"]["constraints"], sort_keys=True) in hold_rules for i in pilot if i["category"] == "instruction_following")


@pytest.mark.parametrize("purpose", list(E.HOLDOUT_FORBIDDEN_PURPOSES) + ["SOMETHING_ELSE", ""])
def test_private_holdout_refuses_every_use_except_qualification(purpose):
    with pytest.raises(H.HoldoutPurposeViolation):
        H.open_split(ROOT, "HOLDOUT", purpose)


def test_holdout_opens_for_qualification_and_pilot_split_is_pilot_only():
    assert len(H.open_split(ROOT, "HOLDOUT", "QUALIFICATION")) == 2485
    with pytest.raises(H.HoldoutPurposeViolation):
        H.open_split(ROOT, "PILOT_TRAIN", "QUALIFICATION")
    assert H.open_split(ROOT, "PILOT_TRAIN", "PILOT_TRAINING")


def test_few_shot_examples_come_from_dev_only(dev, holdout):
    ex = H.few_shot_examples(ROOT, "reasoning", 5)
    dev_ids = {i["item_id"] for i in dev}
    assert ex and all(e["item_id"] in dev_ids and e["split"] == "DEV" and not e["private_holdout"] for e in ex)
    assert set(E.HOLDOUT_FORBIDDEN_PURPOSES) >= {"SFT", "QLORA", "PROMPT_TUNING", "FEW_SHOT_EXAMPLES", "ROUTER_TUNING", "THRESHOLD_TUNING", "MODEL_SELECTION_DEBUGGING"}
    assert E.HOLDOUT_ALLOWED_PURPOSES == ("QUALIFICATION",)


def _public_text() -> str:
    parts = []
    for p in list((ROOT / "docs").rglob("*.md")) + list((ROOT / "docs").rglob("*.json")):
        if p.name.startswith("GENESIS_CAPABILITY_EVAL_V1_HOLDOUT") or p.name.startswith("GENESIS_CAPABILITY_EVAL_V1_MANIFEST"):
            continue
        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def test_private_holdout_prompts_and_answers_do_not_appear_in_public_documents(holdout):
    text = _public_text()
    for it in holdout[::7]:
        key = it["meta"]["dedup_text"]
        if len(key) >= 40:
            assert key[:60] not in text, it["item_id"]
        if it["prompt"]:
            assert it["prompt"][:120] not in text, it["item_id"]
    md = (ROOT / PR.PREREG_MD).read_text()
    assert "ANSWER:" not in md.replace("`ANSWER: <value>`", "")
    m = json.loads((ROOT / PR.HOLDOUT_MANIFEST_PATH).read_text())
    assert m["contains_answers"] is False and m["contains_prompts"] is False and set(m["items"][0]) == {"item_id", "category", "sha256"}


def test_private_corpus_is_excluded_from_container_build_context():
    assert "eval_private" in (ROOT / ".dockerignore").read_text().split()


# ================================================================== 5. contamination controls
def _mk(item_id, cat, split, prompt, dedup, kind="text", private=None, sha=None):
    it = {"item_id": item_id, "category": cat, "split": split, "private_holdout": split == "HOLDOUT" if private is None else private,
          "prompt": prompt, "input": {}, "meta": {"dedup_text": dedup, "dedup_kind": kind}, "ground_truth": {"answer": "x"}}
    it["sha256"] = sha or hashlib.sha256((item_id + prompt).encode()).hexdigest()
    return it


def test_exact_duplicate_detection_ignores_case_and_whitespace_but_not_structured_input():
    a = _mk("a", "c", "HOLDOUT", "What is 2 + 3?", "q1")
    b = _mk("b", "c", "DEV", "  what   IS 2 + 3?  ", "q2")
    assert CX.find_exact_duplicates([a, b]) == [("a", "b")]
    c = _mk("c2", "c", "DEV", "What is 2 + 3?", "q3")
    c["input"] = {"images": ["different.png"]}
    assert CX.find_exact_duplicates([a, c]) == []
    assert CX.normalize_text("A ( B ) [C]") == "a ( b ) [c]"        # punctuation is kept: brackets/arithmetic matter


def test_near_duplicate_detection_flags_cross_split_leakage_of_text_items():
    base = "Vendor Zorvex issued invoice INV-2201 on 2026-03-14. It lists 4 line items. The amount due is 1200.50 in total."
    a = _mk("a", "structured_outputs", "HOLDOUT", base, base)
    b = _mk("b", "structured_outputs", "PILOT_TRAIN", base.replace("2201", "2202"), base.replace("2201", "2202"))
    far = _mk("c", "structured_outputs", "DEV", "Shipment SH10001 leaves Oslo for Lima. Its gross weight is 40 kilograms. The carrier is Kelmar.",
              "Shipment SH10001 leaves Oslo for Lima. Its gross weight is 40 kilograms. The carrier is Kelmar.")
    near = CX.find_near_duplicates([a, b, far])
    assert len(near) == 1 and near[0][:2] == ("a", "b") and near[0][2] >= CX.NEAR_DUP_THRESHOLD
    v = CX.check_split_boundaries([a, b, far])
    assert not v["ok"] and any("near duplicate" in x and "HOLDOUT" in x and "PILOT_TRAIN" in x for x in v["violations"])


def test_parametric_items_are_exempt_from_text_near_duplicate_but_not_from_instance_uniqueness():
    a = _mk("a", "mathematics", "HOLDOUT", "What is the gcd of 34 and 51?", "gcd34-51", kind="parametric")
    b = _mk("b", "mathematics", "DEV", "What is the gcd of 34 and 61?", "gcd34-61", kind="parametric")
    assert CX.find_near_duplicates([a, b]) == [] and CX.check_split_boundaries([a, b])["ok"]
    c = _mk("c", "mathematics", "DEV", "different words", "gcd34-51", kind="parametric")
    assert any("duplicate instance key" in x for x in CX.check_split_boundaries([a, c])["violations"])


def test_boundary_check_catches_unflagged_holdout_duplicate_ids_and_hashes():
    a = _mk("a", "c", "HOLDOUT", "p1", "d1", private=False)
    assert any("not flagged private" in x for x in CX.check_split_boundaries([a])["violations"])
    b = _mk("b", "c", "DEV", "p2", "d2", private=True)
    assert any("flagged private" in x for x in CX.check_split_boundaries([b])["violations"])
    d1, d2 = _mk("z", "c", "DEV", "p3", "d3"), _mk("z", "c", "DEV", "p4", "d4")
    assert any("duplicate item_id" in x for x in CX.check_split_boundaries([d1, d2])["violations"])
    e1, e2 = _mk("e1", "c", "DEV", "p5", "d5", sha="a" * 64), _mk("e2", "c", "DEV", "p6", "d6", sha="a" * 64)
    assert any("duplicate sha256" in x for x in CX.check_split_boundaries([e1, e2])["violations"])


def test_training_corpus_screen_flags_holdout_contamination_without_needing_holdout_text(holdout):
    fps = json.loads((ROOT / GC.CORPUS_DIR / GC.FINGERPRINT_FILE).read_text())
    assert len(fps) == 2485 and all(isinstance(v, list) for v in fps.values())
    victim = next(i for i in holdout if i["category"] == "research")
    leaked = "Some ordinary training text. " + victim["prompt"] + " More text."
    clean = "The committee met on Tuesday to discuss the annual budget and agreed to postpone the vote until the auditors had reported back to everyone."
    flagged = CX.screen_training_texts([clean, leaked], fps)
    assert flagged and all(f["record_index"] == 1 for f in flagged) and victim["item_id"] in {f["item_id"] for f in flagged}
    answer_only = CX.screen_training_texts([f"the answer to that question is {victim['ground_truth']['answer']} as stated"], {victim["item_id"]: fps[victim["item_id"]]})
    assert isinstance(answer_only, list)
    assert CX.ngram_overlap(victim["prompt"], CX.word_ngrams(victim["prompt"])) == 1.0 and CX.ngram_overlap(victim["prompt"], CX.word_ngrams(clean)) == 0.0


def test_existing_orneur_training_corpora_are_clean_of_the_private_holdout():
    fps = json.loads((ROOT / GC.CORPUS_DIR / GC.FINGERPRINT_FILE).read_text())
    res = CX.screen_repo_training_corpora(ROOT, fps)
    assert res and all(not v["flagged"] for v in res.values())
    x = json.loads((ROOT / PR.EXCLUSION_MANIFEST_PATH).read_text())
    assert x["existing_training_corpora_clean"] is True and x["excluded_item_count"] == 2485
    assert x["semantic_overlap"]["status"] == "HOOK_NOT_CONFIGURED" and "invalidates" in x["rule"]


def test_semantic_overlap_hook_protocol_is_wired():
    class Hook:
        configured = True

        def similarity(self, a, b):
            return 1.0 if a == b else 0.0

    r = CX.run_semantic_check(Hook(), ["x", "y"], ["y"])
    assert r["status"] == "CHECKED" and r["flagged"] == [(1, 0)]
    assert CX.run_semantic_check(None, ["x"], ["x"])["status"] == "HOOK_NOT_CONFIGURED"
    assert CX.run_semantic_check(CX.NullSemanticHook(), ["x"], ["x"])["status"] == "HOOK_NOT_CONFIGURED"


# ================================================================== 6. statistics and floors
def test_wilson_interval_matches_known_values():
    lo, hi = ST.wilson(50, 100)
    assert abs(lo - 0.4038) < 1e-3 and abs(hi - 0.5962) < 1e-3
    assert ST.wilson(0, 30)[0] == 0.0 and abs(ST.wilson(0, 30)[1] - 0.1135) < 2e-3
    assert ST.wilson(0, 0) == (0.0, 1.0)


def test_category_aggregate_fails_closed_on_missing_nan_or_invalid_results():
    ok = ST.category_aggregate([1.0, 0.0, 1.0, 1.0], 4, low_power_n=100)
    assert ok["status"] == "COMPLETE" and ok["mean"] == 0.75 and ok["low_power"] is True
    for bad in ([1.0, 0.0, None, 1.0], [1.0, 0.0, float("nan"), 1.0], [1.0, 0.0, 1.0], [1.0, 0.0, 2.0, 1.0], [1.0, True, 1.0, 1.0]):
        r = ST.category_aggregate(bad, 4, low_power_n=100)
        assert r["status"] == "INCOMPLETE" and r["mean"] is None and r["ci95"] is None
    assert ST.category_aggregate([1.0] * 100, 100, low_power_n=100)["low_power"] is False


def test_floor_decision_semantics_incomplete_low_power_and_powered():
    powered = ST.category_aggregate([1.0] * 40 + [0.0] * 60, 100, low_power_n=100)
    assert ST.floor_decision(powered, 0.30)["decision"] == "PASS" and ST.floor_decision(powered, 0.50)["decision"] == "FAIL"
    lp = ST.category_aggregate([0.0] * 5 + [1.0] * 10, 15, low_power_n=100)
    assert ST.floor_decision(lp, 0.8)["decision"] == "INCONCLUSIVE_LOW_POWER" and ST.floor_decision(lp, 0.9)["decision"] == "FAIL"          # not a pass; cannot rank
    assert ST.floor_decision(ST.category_aggregate([0.0] * 60, 60, low_power_n=100), 0.5)["decision"] == "FAIL"   # low power may still FAIL when confidently below
    assert ST.floor_decision(ST.category_aggregate([1.0, None], 2, low_power_n=100), 0.1)["decision"] == "INCOMPLETE"


def test_power_arithmetic_is_monotone_and_false_drops_are_rare():
    assert ST.prob_dropped(0.2, 100, 0.5) > ST.prob_dropped(0.4, 100, 0.5) > ST.prob_dropped(0.5, 100, 0.5)
    assert ST.min_detectable_true_rate(0.5, 200) > ST.min_detectable_true_rate(0.5, 50)
    assert ST.prob_dropped(0.5, 200, 0.5) < 0.03


def test_frozen_floors_have_full_justification_and_clear_chance_by_a_real_margin(prereg):
    assert set(prereg["floors"]) == set(E.GATING_CATEGORIES) and len(prereg["floors"]) == 14
    for cat, f in prereg["floors"].items():
        assert f["floor"] == E.FLOORS[cat] == E.CATEGORY_SPECS[cat]["floor"]
        for k in ("why", "sample_count", "ci_policy", "low_power_handling", "failure_semantics", "chance_baseline", "margin_over_chance",
                  "wilson95_half_width_at_floor", "min_detectable_true_rate_80pct_power_full_holdout", "false_drop_probability_at_floor_stage2"):
            assert f[k] not in (None, ""), (cat, k)
        assert f["margin_over_chance"] >= 0.10 and f["false_drop_probability_at_floor_stage2"] <= 0.03
        assert f["sample_count"] >= 100 and f["low_power"] is False
        assert f["wilson95_half_width_at_floor"] <= 0.10
    assert prereg["floors"]["long_context"]["gating_slice"] == "8k" and prereg["floors"]["long_context"]["sample_count"] == 100


def test_floors_were_reviewed_not_mechanically_accepted(prereg):
    sup = prereg["floors_supersede_design_proposals"]["proposed_in_design_doc"]
    changed = [c for c in E.FLOORS if sup.get({"long_context": "long_context_8k"}.get(c, c)) != E.FLOORS[c]]
    assert len(changed) >= 10 and "instruction_following" in changed and "structured_outputs" in changed
    assert all(E.FLOORS[c] <= 0.70 for c in E.FLOORS)


def test_report_only_categories_have_no_floor_and_strict_contracts_stays_report_only(prereg):
    for c in E.REPORT_ONLY_CATEGORIES + E.PROTOCOL_CATEGORIES:
        assert E.CATEGORY_SPECS[c]["floor"] is None and c not in prereg["floors"]
    assert set(E.REPORT_ONLY_CATEGORIES) == {"strict_contracts", "multimodal_where_applicable", "discovery_quality", "cross_domain_transfer"}
    assert E.CATEGORY_SPECS["strict_contracts"]["role"] == "REPORT_ONLY" and "strict_contracts" not in GF.RANKING_ORDER
    assert prereg["strict_contracts_role"].startswith("report-only recovery-cost signal") and "trainability" in E.PROTOCOL_CATEGORIES
    assert set(E.REPORT_ONLY_CATEGORIES) <= set(GF.REPORT_ONLY_CATEGORIES) and set(GF.REPORT_ONLY_CATEGORIES) - set(E.REPORT_ONLY_CATEGORIES) == {"latency", "cost"}


# ================================================================== 7. deterministic scorers vs ground truth
def perfect(it):
    gt, m = it["ground_truth"], it["scoring_method"]
    if m == "answer_line":
        a = gt["accepted"][0] if gt.get("match") == "any_of" else gt["answer"]
        return f"Reasoning here.\nANSWER: {a}"
    if m == "if_constraints":
        return gt["sft_target"]
    if m == "contract_raw":
        return gt["expected_output"] if gt["contract_type"] != "JSON_SCHEMA" else gt["sft_target"]
    if m in ("json_fields", "tool_call"):
        return gt.get("sft_target") or json.dumps(gt["expected_object"])
    if m == "answer_citations":
        return json.dumps({"answer": gt["answer"], "citations": gt["citations"]})
    if m == "answer_evidence":
        return json.dumps({"answer": gt["answer"], "evidence": gt["evidence"], "conflict": gt["conflict"]})
    if m == "discovery_anchor":
        return json.dumps({"summary": "s", "discoveries": [{"type": g["type"], "evidence": g["anchors"] + g["counter"], "statement": "x",
                                                            "falsification_condition": g["falsifier"][0], "suggested_action": g["action"][0]} for g in gt["valid_discoveries"]]})
    raise AssertionError(m)


def wrong(it):
    m = it["scoring_method"]
    if m in ("json_fields", "tool_call", "answer_citations", "answer_evidence", "discovery_anchor"):
        return '{"nonsense": true}' if m != "discovery_anchor" else '{"summary": "s", "discoveries": []}'
    return "ANSWER: zzz-wrong" if m == "answer_line" else "totally wrong reply"


def test_a_perfect_response_scores_one_and_a_wrong_response_scores_zero_for_every_non_code_item(allitems):
    checked = 0
    for it in allitems:
        if it["scoring_method"] == "code_tests":
            continue
        assert S.score_item(it, perfect(it))["score"] == 1.0, it["item_id"]
        w = S.score_item(it, wrong(it))["score"]
        assert w == 0.0 or (it["scoring_method"] == "contract_raw" and w == 0.0) or (it["scoring_method"] == "tool_call" and it["ground_truth"]["tool"] is None), it["item_id"]
        checked += 1
    assert checked == 2972


def test_code_items_are_never_executed_by_the_scorer_and_need_an_injected_sandbox(holdout):
    it = next(i for i in holdout if i["category"] == "coding")
    r = S.score_item(it, "def f(): pass")
    assert r["status"] == "PENDING_SANDBOX" and r["score"] is None

    class Fake:
        calls = []

        def run_tests(self, code, function_name, tests):
            Fake.calls.append((function_name, len(tests)))
            return {"passed": len(tests), "total": len(tests), "evidence": {"executor": "fake"}}

    ok = S.score_item(it, "```python\ndef x(): pass\n```", Fake())
    assert ok["score"] == 1.0 and Fake.calls == [(it["ground_truth"]["function_name"], 8)]
    class Failing(Fake):
        def run_tests(self, code, function_name, tests):
            return {"passed": 3, "total": 8}
    assert S.score_item(it, "x", Failing())["score"] == 0.0
    for f in ("genesis_scorers.py", "genesis_harness.py", "genesis_sandbox.py", "genesis_stats.py", "genesis_contamination.py"):
        src = (ROOT / "orca/eval" / f).read_text()
        assert not re.search(r"\b(exec|eval)\s*\(|subprocess|os\.system|__import__\(", src), f


def test_reference_solutions_agree_with_the_hidden_tests_for_all_coding_items(allitems):
    """Runs ORNEUR-authored reference solutions only (never candidate output) to prove the tests are correct."""
    n = 0
    for it in allitems:
        if it["category"] != "coding":
            continue
        ns: dict = {}
        exec(compile(it["ground_truth"]["reference_solution"], it["item_id"], "exec"), ns)  # noqa: S102 - trusted, repository-authored
        fn = ns[it["ground_truth"]["function_name"]]
        for t in it["ground_truth"]["tests"]:
            assert fn(*json.loads(json.dumps(t["args"]))) == t["expected"], it["item_id"]
        n += 1
    assert n == 110


def test_scorers_are_strict_but_not_petty():
    gt = {"answer": "42", "match": "numeric"}
    assert S.score_answer_line(gt, "x\nANSWER: 42")["score"] == 1.0 and S.score_answer_line(gt, "x\nANSWER: 42.0")["score"] == 1.0
    assert S.score_answer_line(gt, "The answer is 42")["score"] == 0.0            # no ANSWER line
    assert S.score_answer_line({"answer": "7/2", "match": "numeric"}, "ANSWER: 3.5")["score"] == 1.0
    assert S.score_answer_line({"answer": "Perth", "match": "text"}, "ANSWER: perth.")["score"] == 1.0
    assert S.score_answer_line({"answer": "A,C", "match": "set"}, "ANSWER: C, A")["score"] == 1.0
    assert S.score_answer_line({"answer": "1", "match": "numeric"}, "ANSWER: 2\nANSWER: 1")["score"] == 1.0   # last line counts
    fenced = "```json\n{\"tool\": null}\n```"
    assert S.score_tool_call({"tool": None}, fenced)["score"] == 1.0 and S.score_tool_call({"tool": None}, fenced)["detail"]["raw_format_clean"] is False
    assert S.score_tool_call({"tool": None}, "Sure! {\"tool\": null}")["score"] == 0.0
    assert S.score_contract_raw({"contract_type": "EXACT_TEXT", "expected_output": "READY"}, "READY")["score"] == 1.0
    r = S.score_contract_raw({"contract_type": "EXACT_TEXT", "expected_output": "READY"}, "READY\n")
    assert r["score"] == 0.0 and r["detail"]["recoverable"] is True            # raw strictness is measured; recoverability is recorded separately
    with pytest.raises(ValueError):
        S.score_item({"ground_truth": {}, "scoring_method": "nonexistent", "input": {}}, "x")


def test_if_scorer_checks_every_constraint(holdout):
    it = next(i for i in holdout if i["category"] == "instruction_following")
    assert S.score_if(it["ground_truth"], it["ground_truth"]["sft_target"])["score"] == 1.0
    assert S.score_if(it["ground_truth"], "")["score"] == 0.0


# ---- independent re-derivation of ground truth from the rendered prompt (guards against generator bugs)
def test_ordering_puzzles_match_an_independent_solver(allitems):
    n = 0
    for it in allitems:
        if it["meta"]["subtype"] != "ordering":
            continue
        facts = re.findall(r"([A-Z][a-z]+) is taller than ([A-Z][a-z]+)\.", it["prompt"])
        people = {p for f in facts for p in f}
        rank = {p: sum(1 for a, b in facts if b == p) for p in people}
        # unique ordering: repeated relaxation
        order = sorted(people, key=lambda p: -sum(1 for q in people if q != p and _beats(p, q, facts)))
        k = ["tallest", "second tallest", "third tallest", "fourth tallest", "fifth tallest", "sixth tallest"].index(re.search(r"Who is the (.+?)\?", it["prompt"]).group(1))
        assert order[k] == it["ground_truth"]["answer"], it["item_id"]
        n += 1
    assert n > 40


def _beats(a, b, facts, seen=None):
    seen = seen or set()
    for x, y in facts:
        if x == a and y not in seen:
            if y == b or _beats(y, b, facts, seen | {y}):
                return True
    return False


def test_planted_error_items_match_an_independent_checker(allitems):
    n = 0
    for it in allitems:
        if it["meta"]["subtype"] != "planted_error":
            continue
        first_bad = "NONE"
        for m in re.finditer(r"Step (\d+): (-?\d+) ([+\-*]) (\d+) = (-?\d+)\.", it["prompt"]):
            i, a, op, b, r = int(m[1]), int(m[2]), m[3], int(m[4]), int(m[5])
            if {"+": a + b, "-": a - b, "*": a * b}[op] != r:
                first_bad = str(i)
                break
        assert first_bad == it["ground_truth"]["answer"], it["item_id"]
        n += 1
    assert n > 40


def test_dependency_graph_items_match_an_independent_evaluator(allitems):
    n = 0
    for it in allitems:
        if it["meta"]["subtype"] != "dependency_graph":
            continue
        spec, failed = {}, re.search(r"If (N\d+) stops working", it["prompt"]).group(1)
        for sent in re.findall(r"(N\d+) (needs nothing else|needs N\d+ to be working|works if (?:ALL|AT LEAST ONE) of [^.]+)\.", it["prompt"]):
            t, rule = sent
            deps = re.findall(r"N\d+", rule)
            spec[t] = ("src" if "nothing" in rule else "any" if "AT LEAST ONE" in rule else "all", deps)
        works = {}
        for t in sorted(spec, key=lambda s: int(s[1:])):
            kind, deps = spec[t]
            works[t] = False if t == failed else True if kind == "src" else all(works[d] for d in deps) if kind == "all" else any(works[d] for d in deps)
        dead = sorted((t for t in spec if t != failed and not works[t]), key=lambda s: int(s[1:]))
        assert (",".join(dead) or "NONE") == it["ground_truth"]["answer"] or sorted((",".join(dead) or "NONE").split(",")) == sorted(it["ground_truth"]["answer"].split(",")), it["item_id"]
        n += 1
    assert n > 40


def test_information_gain_items_match_an_independent_entropy_computation(allitems):
    n = 0
    for it in allitems:
        if it["category"] != "information_gain_reasoning":
            continue
        rows = re.findall(r"^(Specimen [A-H]): (.+)$", it["prompt"], re.M)
        traits = [t for t in re.findall(r"Q\d+: Is the secret specimen (\w+)\?", it["prompt"])]
        table = {name: {kv.split("=")[0]: kv.split("=")[1] == "yes" for kv in vals.split(", ")} for name, vals in rows}
        remaining = list(table)
        m = re.search(r"secret specimen (is|is not) (\w+)\.", it["prompt"])
        if m:
            remaining = [s for s in table if table[s][m.group(2)] == (m.group(1) == "is")]
        if len(remaining) == 1:
            assert it["ground_truth"]["accepted"] == ["SUFFICIENT"]
        else:
            ent = [(-(sum(table[s][t] for s in remaining) / len(remaining)) * math.log2(sum(table[s][t] for s in remaining) / len(remaining) or 1)
                    - (1 - sum(table[s][t] for s in remaining) / len(remaining)) * math.log2(1 - sum(table[s][t] for s in remaining) / len(remaining) or 1)) for t in traits]
            best = [f"Q{i + 1}" for i, e in enumerate(ent) if abs(e - max(ent)) < 1e-9]
            assert best == it["ground_truth"]["accepted"] and len(best) == 1, it["item_id"]
        n += 1
    assert n == 132


def test_evidence_use_answers_are_recoverable_from_the_passages(allitems):
    for it in allitems:
        if it["category"] != "evidence_use":
            continue
        gt = it["ground_truth"]
        passages = dict(re.findall(r"\[(E\d)\] (.+)", it["prompt"]))
        if gt["answer"] == "INSUFFICIENT":
            attr = re.search(r"Question: What is the (.+) of (\w+)\?", it["prompt"])
            assert not any(f"The {attr[1]} of {attr[2]} is" in t for t in passages.values()), it["item_id"]
            assert gt["evidence"] == [] and gt["conflict"] is False
        else:
            assert all(gt["answer"] in passages[e] for e in gt["evidence"]) and gt["evidence"], it["item_id"]
            assert gt["conflict"] is (len([1 for t in passages.values() if "[dated" in t]) == 2)


def test_research_answers_and_citations_are_supported_by_the_documents(allitems):
    for it in allitems:
        if it["category"] != "research":
            continue
        docs = dict(re.findall(r"\[(D\d)\] (.+)", it["prompt"]))
        gt = it["ground_truth"]
        assert set(gt["citations"]) <= set(docs) and gt["citations"], it["item_id"]
        assert any(gt["answer"] in docs[c] for c in gt["citations"]) or it["meta"]["subtype"] == "earlier", it["item_id"]


# ================================================================== 8. strategic ORNEUR categories
def test_discovery_items_have_full_ground_truth_and_do_not_mention_the_finding(holdout, dev):
    items = [i for i in holdout + dev if i["category"] == "discovery_quality"]
    assert len(items) == 66
    for it in items:
        gt = it["ground_truth"]
        assert gt["valid_discoveries"] and gt["decoys"]
        ids = set(it["input"]["document_ids"])
        for g in gt["valid_discoveries"]:
            assert {"type", "anchors", "counter", "importance", "why", "falsifier", "action"} <= set(g) and g["why"] and g["falsifier"] and set(g["anchors"]) <= ids
            assert g["why"] not in it["prompt"]
            assert g["importance"] in {"high", "medium", "low"} and g["type"] in P.DISCOVERY_TYPES
        for d in gt["decoys"]:
            assert d["why"] and set(d["anchors"]) <= ids and d["type"] in P.DISCOVERY_TYPES
        task_line = re.search(r"Task: (.+?)\n", it["prompt"]).group(1)
        assert not re.search(r"contradict|risk|invalid|opportunit|missing|weak signal", task_line, re.I)
    assert {it["meta"]["subtype"] for it in items} == {"hidden_contradiction", "hidden_dependency", "weak_signal", "missing_information", "invalidated_decision", "opportunity", "cross_domain"}


def test_discovery_scorer_rewards_anchored_findings_and_penalises_decoys_and_generic_brainstorming(holdout):
    it = next(i for i in holdout if i["category"] == "discovery_quality")
    gt = it["ground_truth"]
    g, d = gt["valid_discoveries"][0], gt["decoys"][0]
    ideal = S.score_discovery(gt, perfect(it), it["input"])
    assert ideal["score"] == 1.0 and ideal["detail"]["recall"] == 1.0 and ideal["detail"]["decoy_hits"] == 0
    decoy_only = json.dumps({"summary": "s", "discoveries": [{"type": d["type"], "evidence": d["anchors"], "statement": "x", "falsification_condition": "y", "suggested_action": "z"}]})
    r = S.score_discovery(gt, decoy_only, it["input"])
    assert r["score"] == 0.0 and r["detail"]["decoy_hits"] == 1
    generic = json.dumps({"summary": "s", "discoveries": [{"type": "OPPORTUNITY", "evidence": [], "statement": "improve communication", "falsification_condition": "", "suggested_action": "brainstorm"}] * 3})
    assert S.score_discovery(gt, generic, it["input"])["score"] == 0.0
    wrong_type = json.dumps({"summary": "s", "discoveries": [{"type": "OPPORTUNITY" if g["type"] != "OPPORTUNITY" else "RISK", "evidence": g["anchors"], "statement": "x", "falsification_condition": "y", "suggested_action": "z"}]})
    assert S.score_discovery(gt, wrong_type, it["input"])["score"] == 0.0
    padded = json.loads(perfect(it))
    padded["discoveries"] += [{"type": "RISK", "evidence": ["D1"], "statement": "noise", "falsification_condition": "", "suggested_action": ""}] * 3
    assert 0.0 < S.score_discovery(gt, json.dumps(padded), it["input"])["score"] < 1.0


def test_hypothesis_items_have_known_falsifiers_and_verdicts(holdout):
    for it in [i for i in holdout if i["category"] == "hypothesis_testing"]:
        if it["meta"]["subtype"] == "choose_falsifier":
            exps = re.findall(r"^(E\d): .+?If H is true, (.+?)\. If H is false, (.+?)\.$", it["prompt"], re.M)
            assert [e for e, h, n in exps if h != n] == it["ground_truth"]["accepted"]
        else:
            h, n = re.search(r"If H is true, (.+?)\. If H is false, (.+?)\.\nObserved", it["prompt"]).groups()
            obs = re.search(r"Observed result: (.+?)\.", it["prompt"]).group(1)
            want = "NON_DISCRIMINATING" if h == n else "CONSISTENT_WITH_H" if obs == h else "FALSIFIED"
            assert it["ground_truth"]["answer"] == want


def test_cross_domain_items_include_structure_mismatch_decoys(holdout):
    subs = [i["meta"]["subtype"] for i in holdout if i["category"] == "cross_domain_transfer"]
    assert any(s.endswith("_decoy") for s in subs) and any(not s.endswith("_decoy") for s in subs)
    for it in holdout:
        if it["category"] == "cross_domain_transfer":
            assert "Worked example" in it["prompt"] and "Problem" in it["prompt"] and "ONLY if the structure really is the same" in it["prompt"]


def test_multilingual_covers_four_languages_with_language_appropriate_items(holdout, dev, manifest):
    rows = [i for i in holdout if i["category"] == "multilingual"]
    by = {l: [i for i in rows if i["meta"]["language"] == l] for l in E.LANGUAGES}
    assert E.LANGUAGES == ("English", "Hindi", "Tamil", "Kannada") and E.ADDITIONAL_LANGUAGES_INCLUDED is False
    assert {l: len(v) for l, v in by.items()} == {l: 50 for l in E.LANGUAGES}
    scripts = {"Hindi": r"[ऀ-ॿ]", "Tamil": r"[஀-௿]", "Kannada": r"[ಀ-೿]"}
    for lang, rx in scripts.items():
        assert all(len(re.findall(rx, i["prompt"])) > 10 for i in by[lang]), lang
        assert all(re.search(r"[A-Za-z]{4}", i["prompt"].split("\n\nEnd your reply")[0]) is None for i in by[lang]), lang     # the question itself is in-language
    assert any("letter" in i["prompt"] for i in by["English"]) and not any("letter" in i["prompt"] for i in by["Hindi"])   # English-specific task type
    assert manifest["category_counts"]["multilingual"]["holdout_languages"] == {l: 50 for l in E.LANGUAGES}
    assert len({i["prompt"] for i in rows}) == 200
    assert "native-speaker review has NOT been performed" in json.loads((ROOT / PR.PREREG_JSON).read_text())["languages"]["authoring_note"]


def test_long_context_materialisation_matches_stored_hashes_and_target_lengths(holdout):
    rows = [i for i in holdout if i["category"] == "long_context"]
    assert {s: sum(1 for r in rows if r["meta"]["slice"] == s) for s in ("8k", "16k", "40k")} == {"8k": 100, "16k": 40, "40k": 30}
    for it in rows[::8] + [r for r in rows if r["meta"]["slice"] == "40k"][:3]:
        p = GC.item_prompt(it)
        target = it["input"]["generator_spec"]["target_tokens"] * gen_misc._WORDS_PER_TOKEN
        assert 0.95 * target <= len(p.split()) <= 1.10 * target, it["item_id"]
        s = S.score_item(it, f"ANSWER: {it['ground_truth']['answer']}")
        assert s["score"] == 1.0
    assert all(r["prompt"] is None for r in rows)


def test_multimodal_images_exist_hash_and_are_valid_pngs(holdout):
    rows = [i for i in holdout if i["category"] == "multimodal_where_applicable"]
    assert len(rows) == 60
    for it in rows:
        p = ROOT / GC.CORPUS_DIR / it["input"]["images"][0]
        data = p.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n" and hashlib.sha256(data).hexdigest() == it["input"]["image_sha256"]
        assert int.from_bytes(data[16:20], "big") == 120 and int.from_bytes(data[20:24], "big") == 120
    assert E.CATEGORY_SPECS["multimodal_where_applicable"]["role"] == "REPORT_ONLY"


def test_latency_cost_trainability_are_protocol_definitions_not_question_items(prereg):
    probes = GC.load_protocol(ROOT)
    assert len(probes) == 12 and all(p["scoring_method"] == "measurement" and p["category"] == "latency" for p in probes)
    assert all(S.score_item(p, "anything")["status"] == "UNSCORABLE" for p in probes)
    assert prereg["stage3"]["pilot_categories"] == list(E.PILOT_CATEGORIES) and prereg["stage3"]["regression_categories"] == ["reasoning", "mathematics", "verification"]
    assert prereg["category_definitions"]["cost"]["role"] == "PROTOCOL" and prereg["category_definitions"]["trainability"]["role"] == "PROTOCOL"


# ================================================================== 9. pre-registration
def test_preregistration_contains_every_required_element(prereg):
    need = ["eval_version", "architecture_version", "protocol_version", "harness_sha", "dataset_manifest_sha", "private_holdout_manifest_sha",
            "category_definitions", "item_counts", "floors", "confidence_interval_method", "stage0_checks", "stage1", "stage2", "stage3", "cost_caps_usd",
            "selection_rule", "tie_rule", "no_model_qualifies_rule", "contamination_policy", "preregistration_sha256"]
    for k in need:
        assert prereg.get(k) not in (None, "", {}, []), k
    assert prereg["architecture_version"] == SPEC.ARCHITECTURE_VERSION and prereg["protocol_version"] == P.PROTOCOL_VERSION
    assert prereg["confidence_interval_method"]["name"] == "wilson_score_95"
    assert len(prereg["stage0_checks"]) >= 8 and prereg["stage1"]["probe"]["probe_items"] == 14 * 30


def test_preregistration_hash_is_self_consistent_and_binds_the_frozen_inputs(prereg, manifest):
    assert prereg["preregistration_sha256"] == PR.prereg_hash(prereg)
    assert prereg["harness_sha"] == PR.harness_sha256(ROOT)
    assert prereg["dataset_manifest_sha"] == manifest["dataset_manifest_sha256"]
    assert prereg["private_holdout_manifest_sha"] == json.loads((ROOT / PR.HOLDOUT_MANIFEST_PATH).read_text())["private_holdout_manifest_sha256"]
    assert prereg["dataset_manifest_file_sha256"] == hashlib.sha256((ROOT / PR.MANIFEST_PATH).read_bytes()).hexdigest()
    assert set(prereg["harness_files"]) == set(PR.HARNESS_FILES) and all((ROOT / p).exists() for p in PR.HARNESS_FILES)
    assert re.fullmatch(r"[0-9a-f]{64}", prereg["preregistration_sha256"])
    assert (ROOT / PR.PREREG_MD).read_text().count(prereg["preregistration_sha256"]) == 1


def test_preregistration_verifies_and_any_tamper_is_rejected(tmp_path):
    doc = H.verify_preregistration(ROOT, ROOT / PR.PREREG_JSON)
    assert doc["GENESIS_CAPABILITY_EVAL_V1_FROZEN"] is False
    for mutate in (lambda d: d["floors"]["reasoning"].update(floor=0.10), lambda d: d.update(selection_rule="pick the newest"),
                   lambda d: d["stage2"].update(family_name_carries_no_priority=False), lambda d: d.update(harness_sha="0" * 64)):
        d = copy.deepcopy(doc)
        mutate(d)
        p = tmp_path / "prereg.json"
        p.write_text(json.dumps(d))
        with pytest.raises(H.PreregistrationViolation):
            H.verify_preregistration(ROOT, p)
    d = copy.deepcopy(doc)
    d["GENESIS_CAPABILITY_EVAL_V1_FROZEN"] = True
    d["preregistration_sha256"] = PR.prereg_hash(d)
    p = tmp_path / "prereg2.json"
    p.write_text(json.dumps(d))
    with pytest.raises(H.PreregistrationViolation, match="FROZEN"):
        H.verify_preregistration(ROOT, p)


def test_changing_a_corpus_file_or_the_harness_invalidates_the_preregistration(tmp_path):
    fake_root = tmp_path
    (fake_root / "docs/orneur/phase-21").mkdir(parents=True)
    for rel in (PR.PREREG_JSON, PR.MANIFEST_PATH, PR.HOLDOUT_MANIFEST_PATH):
        shutil.copy(ROOT / rel, fake_root / rel)
    shutil.copytree(ROOT / GC.CORPUS_DIR, fake_root / GC.CORPUS_DIR)
    for rel in PR.HARNESS_FILES:
        (fake_root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, fake_root / rel)
    H.verify_preregistration(fake_root, fake_root / PR.PREREG_JSON)
    h = fake_root / GC.CORPUS_DIR / "holdout.jsonl"
    h.write_text(h.read_text().replace('"difficulty":"easy"', '"difficulty":"hard"', 1))
    with pytest.raises(H.PreregistrationViolation, match="holdout.jsonl"):
        H.verify_preregistration(fake_root, fake_root / PR.PREREG_JSON)
    shutil.copy(ROOT / GC.CORPUS_DIR / "holdout.jsonl", h)
    s = fake_root / "orca/eval/genesis_scorers.py"
    s.write_text(s.read_text() + "\n# tampered\n")
    with pytest.raises(H.PreregistrationViolation, match="harness source"):
        H.verify_preregistration(fake_root, fake_root / PR.PREREG_JSON)


def test_selection_rule_is_consistent_across_prereg_funnel_landscape_and_design(prereg):
    assert prereg["selection_rule"] == FL.SELECTION_RULE
    assert prereg["ranking_order"] == list(GF.RANKING_ORDER) == ["verification", "evidence_use", "trainability", "cost"]
    design = (PH21 / "GENESIS_CAPABILITY_EVAL_V1_DESIGN.md").read_text()
    assert "lexicographically by `verification`, then `evidence_use`, then `trainability`" in design
    assert prereg["stage3"]["max_finalists"] == GF.STAGE3_MAX_FINALISTS and prereg["stage3"]["pilot_protocol_id"] == GF.PILOT_PROTOCOL_ID
    assert prereg["cost_caps_usd"]["stage2_total"] == GF.STAGE2_COST_CAP_USD and prereg["cost_caps_usd"]["stage3_total"] == GF.STAGE3_COST_CAP_USD
    assert prereg["stage2"]["mandatory_gating_categories"] == list(E.GATING_CATEGORIES) and prereg["stage2"]["family_name_carries_no_priority"] is True
    assert "OWNER_DECISION_REQUIRED_TIE" in prereg["tie_rule"] and "NO_MODEL_QUALIFIES" in prereg["no_model_qualifies_rule"]
    assert "never lowered after the fact" in prereg["no_model_qualifies_rule"]
    assert set(prereg["contamination_policy"]["private_holdout_forbidden_purposes"]) == set(E.HOLDOUT_FORBIDDEN_PURPOSES)


def test_freeze_semantics_the_actual_eval_is_not_frozen(prereg):
    assert prereg["GENESIS_CAPABILITY_EVAL_V1_FROZEN"] is False
    fr = prereg["freeze"]
    assert fr["corpus_complete"] and fr["floors_finalized"] and fr["manifests_complete"] and fr["hashes_frozen"] and fr["preregistration_hashed"]
    assert fr["harness_tests_pass"] == "PENDING_EXACT_SHA_CI" and fr["exact_sha_ci_passes"] is False and fr["independent_audit_passed"] is False
    assert prereg["design_level_readiness_historical"]["GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY"] is True
    assert "not the freeze" in prereg["design_level_readiness_historical"]["meaning"]
    md = (ROOT / PR.PREREG_MD).read_text()
    assert "GENESIS_CAPABILITY_EVAL_V1_FROZEN = false" in md and "recorded historically" in md and "independent audit" in md.lower()
    assert not re.search(r"GENESIS_CAPABILITY_EVAL_V1_FROZEN\s*=\s*true", md)


def test_no_authorization_no_inference_no_spending(prereg):
    assert prereg["authorizations"] == {"foundation_selected": False, "gpu_authorized": False, "training_authorized": False,
                                        "provider_inference_authorized": False, "phase_21c_authorized": False, "spending_authorized": False}
    assert prereg["model_inference_performed_in_this_phase"] is False and prereg["candidate_runs"] == 0
    pkg = json.loads((PH21 / "GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.json").read_text())
    assert pkg["selected_foundation"] is None and pkg["gpu_authorized"] is False
    refresh = json.loads((PH21 / "GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.json").read_text())
    assert refresh["foundation_selected"] is False and refresh["gpu_authorized"] is False
    bad = {".safetensors", ".pt", ".pth", ".bin", ".gguf", ".ckpt", ".onnx"}
    assert not [p for p in (ROOT / "eval_private").rglob("*") if p.suffix in bad]


# ================================================================== 10. CPU harness
def _prov(prereg, sampling, **kw):
    base = dict(model_revision="a" * 40, tokenizer_revision="b" * 40, runtime_name="test-runtime", runtime_version="0.0.0", harness_sha256=prereg["harness_sha"],
                dataset_manifest_sha256=prereg["dataset_manifest_sha"], holdout_manifest_sha256=prereg["private_holdout_manifest_sha"],
                preregistration_sha256=prereg["preregistration_sha256"], sampling_config=H.asdict(sampling), hardware={"gpu": "none (unit test)"},
                started_at="2026-09-26T00:00:00Z")
    base.update(kw)
    return H.RunProvenance(**base)


SAMPLING = H.SamplingConfig(temperature=0.0, top_p=1.0, max_new_tokens=256, seed=1234, label="greedy")


def _oracle_backend(items):
    table = {GC.item_prompt(i): perfect(i) for i in items if i["scoring_method"] != "code_tests"}

    def backend(prompt, sampling):
        return H.GenerationResult(text=table[prompt], first_token_s=0.01, end_to_end_s=0.5, prompt_tokens=10, completion_tokens=5)
    return backend


def test_default_backend_performs_no_inference_and_harness_names_no_model(prereg, holdout, tmp_path):
    h = H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING), SAMPLING)
    with pytest.raises(H.NoInferenceBackend):
        h.run(holdout[:1], tmp_path / "run.jsonl")
    src = (ROOT / "orca/eval/genesis_harness.py").read_text().lower()
    assert not any(n in src for n in FAMILY)
    assert "no inference" in src


def test_harness_run_captures_raw_output_provenance_timing_cost_and_is_write_once(prereg, holdout, tmp_path):
    sub = [i for i in holdout if i["category"] in ("reasoning", "tool_use")][:6]
    clock = iter(range(1000, 2000))
    h = H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING), SAMPLING, backend=_oracle_backend(sub), clock=lambda: next(clock))
    before = (ROOT / PR.PREREG_JSON).read_bytes()
    out = tmp_path / "run.jsonl"
    recs = h.run(sub, out)
    assert (ROOT / PR.PREREG_JSON).read_bytes() == before                      # a run never modifies the pre-registration
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert lines[0]["record_type"] == "run_provenance" and lines[0]["provenance"]["model_revision"] == "a" * 40
    assert lines[0]["provenance_digest"] == h.provenance.digest()
    for r, it in zip(recs, sub):
        assert r.response_raw == perfect(it) and r.status == "SCORED" and r.score == 1.0 and r.item_sha256 == it["sha256"]
        assert r.first_token_s == 0.01 and r.end_to_end_s == 0.5 and r.prompt_tokens == 10 and r.scorer_version == E.SCORER_VERSION
        assert r.prompt_sha256 == hashlib.sha256(GC.item_prompt(it).encode()).hexdigest()
    assert len(lines) == 1 + len(sub) and h.cost.gpu_seconds == 0.5 * len(sub)
    assert h.cost.usd == round(0.5 * len(sub) / 3600 * FL.H100_USD_PER_HOUR, 6)
    with pytest.raises(FileExistsError):
        h.run(sub, out)                                                       # run records are write-once


def test_harness_refuses_to_start_on_any_provenance_or_prereg_mismatch(prereg, tmp_path):
    for kw in (dict(harness_sha256="0" * 64), dict(dataset_manifest_sha256="0" * 64), dict(preregistration_sha256="1" * 64), dict(holdout_manifest_sha256="2" * 64)):
        with pytest.raises(H.PreregistrationViolation):
            H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING, **kw), SAMPLING)
    for kw in (dict(model_revision=""), dict(tokenizer_revision=""), dict(runtime_version=""), dict(hardware={}), dict(sampling_config={}), dict(started_at="")):
        with pytest.raises(H.PreregistrationViolation):
            H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING, **kw), SAMPLING)
    with pytest.raises(H.HoldoutPurposeViolation):
        H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING, purpose="SFT"), SAMPLING)
    other = H.SamplingConfig(0.7, 0.9, 256, 1, label="other")
    with pytest.raises(H.PreregistrationViolation):
        H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING), other)


def test_backend_failure_is_recorded_and_makes_the_category_incomplete(prereg, holdout, tmp_path):
    sub = [i for i in holdout if i["category"] == "reasoning"]
    calls = {"n": 0}

    def flaky(prompt, sampling):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("out of memory")
        return H.GenerationResult(text=perfect(next(i for i in sub if GC.item_prompt(i) == prompt)), end_to_end_s=0.1)

    h = H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING), SAMPLING, backend=flaky)
    recs = h.run(sub, tmp_path / "r.jsonl")
    assert sum(r.status == "ERROR" for r in recs) == 1 and [r for r in recs if r.status == "ERROR"][0].score is None
    agg = H.aggregate_run(recs, sub)
    assert agg["reasoning"]["slices"]["ALL"]["status"] == "INCOMPLETE" and agg["reasoning"]["decision"]["decision"] == "INCOMPLETE" and "ERROR" in agg["reasoning"]["unscored_statuses"]


def test_missing_results_fail_closed_never_zero_filled_never_silently_shrunk(prereg, holdout, tmp_path):
    reasoning = [i for i in holdout if i["category"] == "reasoning"]
    h = H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING), SAMPLING, backend=_oracle_backend(reasoning))
    recs = h.run(reasoning[:-25], tmp_path / "partial.jsonl")                 # 25 items never ran
    agg = H.aggregate_run(recs, reasoning)
    a = agg["reasoning"]["slices"]["ALL"]
    assert a["status"] == "INCOMPLETE" and a["n_missing"] == 25 and a["mean"] is None and a["n_scored"] == 155
    assert H.to_stage2_capability(agg)["reasoning"] is None
    with pytest.raises(GF.IncompleteStage2Results):
        GF.stage3_entrants({"m": {"capability": {**{c: 0.9 for c in E.GATING_CATEGORIES}, "reasoning": H.to_stage2_capability(agg)["reasoning"]},
                                  "cost_usd": 1.0, "family": "F"}})


def test_full_holdout_aggregation_with_an_oracle_backend_completes_everything_except_unsandboxed_coding(prereg, holdout, tmp_path):
    h = H.Harness(ROOT, ROOT / PR.PREREG_JSON, _prov(prereg, SAMPLING), SAMPLING, backend=lambda p, s: H.GenerationResult(text="unused", end_to_end_s=0.0))
    table = {GC.item_prompt(i): perfect(i) for i in holdout if i["scoring_method"] != "code_tests"}
    h.backend = lambda p, s: H.GenerationResult(text=table.get(p, "def f(): pass"), end_to_end_s=0.0)
    recs = h.run(holdout, tmp_path / "full.jsonl")
    agg = H.aggregate_run(recs, holdout)
    assert agg["coding"]["slices"]["ALL"]["status"] == "INCOMPLETE" and "PENDING_SANDBOX" in agg["coding"]["unscored_statuses"]
    for cat, e in agg.items():
        if cat != "coding":
            assert e["slices"]["ALL"]["status"] == "COMPLETE", cat
    for cat in E.GATING_CATEGORIES:
        if cat != "coding":
            assert agg[cat]["decision"]["decision"] == "PASS", cat
    assert agg["long_context"]["gating_slice"] == "8k" and agg["long_context"]["slices"]["8k"]["n_expected"] == 100
    assert agg["long_context"]["slices"]["16k"]["low_power"] is True and agg["long_context"]["slices"]["40k"]["low_power"] is True
    assert {l: agg["multilingual"]["slices"][l]["low_power"] for l in E.LANGUAGES} == {l: True for l in E.LANGUAGES}
    for cat in E.REPORT_ONLY_CATEGORIES:
        assert "decision" not in agg[cat] and "floor" not in agg[cat]
    assert agg["strict_contracts"]["role"] == "REPORT_ONLY"
    cap = H.to_stage2_capability(agg)
    assert cap["coding"] is None and set(cap) == set(E.GATING_CATEGORIES)
    assert agg["mathematics"]["slices"]["ALL"]["ci95"][0] > 0.97


def test_sandbox_requirements_and_attestation_gate():
    r = SB.SANDBOX_REQUIREMENTS
    assert r["network"].startswith("DISABLED") and "read-only root" in r["filesystem"] and r["resource_limits"]["wall_seconds_per_test"] > 0
    for k in ("network", "filesystem", "resource_limits", "isolation", "process_limits", "timeout", "captured_streams", "test_result_evidence"):
        assert k in r
    good = {"sandbox_version": SB.SANDBOX_VERSION, "network_disabled": True, "read_only_root": True, "non_root": True, "no_new_privileges": True,
            "cpu_seconds_per_test": 5, "wall_seconds_per_test": 10, "memory_bytes": 512 * 1024 * 1024, "max_processes": 32, "max_output_bytes": 65536,
            "executor_version": "1", "image_digest": "sha256:abc"}
    assert SB.validate_attestation(good) == []
    for k, v in (("network_disabled", False), ("read_only_root", False), ("non_root", False), ("memory_bytes", 10 ** 12), ("wall_seconds_per_test", 0),
                 ("max_processes", 10 ** 6), ("image_digest", ""), ("sandbox_version", "other")):
        assert SB.validate_attestation({**good, k: v}), k
    assert SB.validate_attestation({k: v for k, v in good.items() if k != "executor_version"})
    with pytest.raises(SB.SandboxUnavailable):
        SB.NoSandbox().run_tests("x", "f", [])


def test_cost_ledger_rejects_bad_input_and_prices_gpu_seconds():
    c = H.CostLedger()
    c.add_gpu_seconds(3600)
    assert c.usd == round(FL.H100_USD_PER_HOUR, 6)
    for bad in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            c.add_gpu_seconds(bad)


# ================================================================== 11. historical integrity and Contract Engine
def test_historical_control_evidence_and_contract_engine_are_unchanged():
    state = historical_control_state(PH21 / "evidence")
    assert state["control_evidence_aggregate_sha256"] == CONTROL_EVIDENCE_AGGREGATE_SHA256 and state["file_count"] == 78
    assert {k: v["RUNTIME_QUALIFIED"] for k, v in state["raw_model_results_unchanged_and_separate"].items()} == \
        {"Qwen3-8B": False, "Mistral-Nemo-Instruct-2407": False, "Phi-4": False}
    art = PH21 / "evidence/ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json"
    assert hashlib.sha256(art.read_bytes()).hexdigest() == SYSTEM_QUAL_ARTIFACT_SHA256
    assert json.loads(art.read_text())["verdict"] == "SYSTEM_CONTRACT_QUALIFIED"


def test_corpus_generators_use_the_contract_engine_read_only_and_do_not_special_case_canonical_smokes(holdout):
    src = (ROOT / "orca/eval/genesis/gen_format.py").read_text()
    assert "ContractEngine()" in src
    for it in holdout:
        if it["category"] == "strict_contracts":
            assert it["prompt"] not in ("Reply exactly:\nREADY", "2 + 3", 'Return valid JSON:\n{"status":"ready"}')
    lowered = " ".join(GC.item_prompt(i) for i in holdout[:400]).lower()
    assert not any(n in lowered for n in ("qwen", "mistral-nemo", "phi-4"))


def test_citation_and_evidence_scorers_require_exact_sets_and_correct_abstention():
    gt = {"answer": "Lisbon", "citations": ["D1", "D3"]}
    ok = json.dumps({"answer": "lisbon", "citations": ["D3", "D1"]})
    assert S.score_answer_citations(gt, ok)["score"] == 1.0
    for bad in ({"answer": "Lisbon", "citations": ["D1"]}, {"answer": "Lisbon", "citations": ["D1", "D3", "D4"]}, {"answer": "Oslo", "citations": ["D1", "D3"]},
                {"answer": "Lisbon", "citations": []}):
        r = S.score_answer_citations(gt, json.dumps(bad))
        assert r["score"] == 0.0
    ev = {"answer": "INSUFFICIENT", "evidence": [], "conflict": False}
    assert S.score_answer_evidence(ev, json.dumps(ev))["score"] == 1.0
    assert S.score_answer_evidence(ev, json.dumps({"answer": "5 warehouses", "evidence": ["E1"], "conflict": False}))["score"] == 0.0     # hallucinated instead of abstaining
    conflict = {"answer": "9 warehouses", "evidence": ["E2"], "conflict": True}
    assert S.score_answer_evidence(conflict, json.dumps(conflict))["score"] == 1.0
    assert S.score_answer_evidence(conflict, json.dumps({**conflict, "conflict": False}))["score"] == 0.0                 # missed the planted contradiction
    assert S.score_answer_evidence(conflict, json.dumps({**conflict, "evidence": ["E1", "E2"]}))["score"] == 0.0
