"""ORNEUR Eternal Intelligence Architecture: protocol contracts, spec, foundation-landscape refresh, invariants."""
from __future__ import annotations

import copy
import dataclasses
import importlib.util
import json
import re
from pathlib import Path

import pytest

from orca.eval import foundation_landscape as fl
from orca.eval.system_contract_qualification import historical_control_state
from orca.intelligence import protocol as P
from orca.intelligence import spec as S

ROOT = Path(__file__).resolve().parents[1]
INTEL = ROOT / "docs/orneur/intelligence"
PH21 = ROOT / "docs/orneur/phase-21"
EVID = PH21 / "evidence"
CONTROL_EVIDENCE_AGGREGATE_SHA256 = "125db85c9abbbe2af9671c688a4335169162d8483c3f35bf763bf87688c2d358"
SYSTEM_QUAL_ARTIFACT_SHA256 = "9b14c4cf90d1022cfd76467d73d82202177698e6c4c16d98a39988938111ca19"
SHA = "a" * 64
T = "2026-09-26T00:00:00Z"
REFRESH_JSON = PH21 / "GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.json"
REFRESH_MD = PH21 / "GENESIS_FOUNDATION_LANDSCAPE_REFRESH_2026-09-26.md"
ARCH_MD = INTEL / "ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.md"
ARCH_JSON = INTEL / "ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.json"
DOCS = [ARCH_MD, INTEL / "ORNEUR_DISCOVERY_INTELLIGENCE.md", INTEL / "ORNEUR_SELF_EVOLVING_EXPERT_MESH.md",
        INTEL / "ORNEUR_ARCHITECTURE_MIGRATION_PROTOCOL.md", REFRESH_MD, PH21 / "GENESIS_CAPABILITY_EVAL_V1_DESIGN.md"]


@pytest.fixture(scope="module")
def raw():
    return fl.load_raw(ROOT)


@pytest.fixture(scope="module")
def refresh():
    return json.loads(REFRESH_JSON.read_text())


# ------------------------------------------------------------------ helpers
def discovery(**kw):
    base = dict(discovery_id="d1", objective_id="o1", discovery_type="RISK", statement="s", why_non_obvious="w",
                evidence_refs=("e1",), counter_evidence_refs=(), counter_evidence_status=P.CounterEvidenceStatus.SEARCHED_NONE_FOUND,
                assumptions=("a",), confidence=0.6, estimated_importance=0.5, falsification_condition="f",
                suggested_experiment="x", potential_action="p", affected_prior_decisions=(),
                outcome_status=P.DiscoveryOutcome.PROPOSED, created_at=T, updated_at=T, tenant_id="t1")
    base.update(kw)
    return P.Discovery(**base)


def outcome(**kw):
    base = dict(outcome_id="oc1", tenant_id="t1", objective_id="o1", decision_ref="dec", action_ref="act",
                expected_outcome="x", time_horizon="30d", success_metric="m", source=P.OutcomeSource.MEASURED_METRIC)
    base.update(kw)
    return P.Outcome(**base)


def promo(**kw):
    base = dict(decision_id="pd1", candidate_id="cand1", candidate_produced_by="learner1", decided_by="gate1",
                decider_kind="QUALIFIED_GATE_SERVICE", verdict=P.PromotionVerdict.PROMOTE, frozen_eval_ref="f",
                adversarial_eval_ref="a", regression_eval_ref="r", shadow_deployment_ref="s",
                measured_improvement=0.05, regressions_found=0)
    base.update(kw)
    return P.PromotionDecision(**base)


def manifest(**kw):
    src = P.ArchitectureDescriptor("arch-a", 1, "label-a")
    dst = P.ArchitectureDescriptor("arch-b", 2, "label-b")
    assets = tuple(P.AssetMigration(a, (P.MigrationMechanism.REPLAY,), ("ev",)) for a in P.MigrationAsset)
    base = dict(manifest_id="m1", source=src, target=dst, assets=assets, shadow_comparison_ref=None,
                rollback_plan_ref=None, obsolescence_review_ref=None)
    base.update(kw)
    return P.ArchitectureMigrationManifest(**base)


# ------------------------------------------------------------------ 1. modes are not parameter counts
def test_modes_not_defined_by_parameter_counts():
    spec = S.build_spec()
    cm = spec["compute_modes"]
    assert cm["defined_by_parameter_count"] is False and cm["current_implementation_binding"] is None
    assert set(cm["modes"]) == {"FAST", "REASON", "FRONTIER"} and cm["future_modes_allowed"] is True
    blob = json.dumps(cm["modes"])
    assert not re.search(r"\b\d+(\.\d+)?\s*[BbMmTt]\b|parameter", blob)
    for cls in (P.ComputeBudget, P.CognitiveRequest, P.ExpertRequest):
        names = {f.name for f in dataclasses.fields(cls)}
        assert not any(re.search(r"param|billion|size|weights", n) for n in names), names


def test_frontier_doc_states_no_fixed_size():
    txt = ARCH_MD.read_text()
    assert "not tied to 14B, 70B, 500B or any other size" in txt
    assert "not sizes" in txt


def test_future_modes_are_legal_but_unknown_modes_are_not():
    ok = P.CognitiveRequest("r", "t1", "FUTURE:deliberate-long", "in")
    assert ok.problems() == []
    assert P.CognitiveRequest("r", "t1", "TURBO", "in").problems()
    assert P.CognitiveRequest("r", "t1", "FAST", "in", budget=P.ComputeBudget(latency_target_ms=-1)).problems()


# ------------------------------------------------------------------ 2. versioning
def test_architecture_and_protocol_versioning():
    assert re.fullmatch(r"orneur\.eternal-architecture/\d+\.\d+\.\d+", S.ARCHITECTURE_VERSION)
    assert re.fullmatch(r"orneur\.core-protocol/\d+\.\d+\.\d+", P.PROTOCOL_VERSION)
    j = json.loads(ARCH_JSON.read_text())
    assert j["architecture_version"] == S.ARCHITECTURE_VERSION and j["protocol_version"] == P.PROTOCOL_VERSION
    assert P.CognitiveRequest("r", "t", "FAST", "i", protocol_version="orneur.core-protocol/0.0.1").problems()
    assert P.WorldState("w", "t", 0, None, SHA, T).protocol_version == P.PROTOCOL_VERSION


def test_json_companion_matches_single_source_of_truth():
    assert json.loads(ARCH_JSON.read_text()) == json.loads(json.dumps(S.build_spec()))


def test_pipeline_matches_required_loop_in_order():
    ids = [s["id"] for s in S.build_spec()["pipeline"]]
    required = ["user", "objective_graph", "reality_compiler", "living_world_model", "world_delta_engine",
                "discovery_intelligence", "hypothesis_laboratory", "expert_mesh", "adaptive_compute", "compute_modes",
                "verification_engine", "evidence_graph", "confidence_calibration", "authority_runtime",
                "contract_compliance", "action", "outcome_capture", "failure_genome", "learning_pipeline",
                "qualification_promotion", "architecture_migration"]
    assert ids == required
    j = S.build_spec()
    assert j["cross_cutting"]["instant_response_fabric"]["operates_across_entire_system"] is True
    assert j["pipeline_closes_loop_into"].startswith("improved ORNEUR")


def test_interfaces_are_all_defined_in_protocol():
    for name in S.INTERFACES:
        assert hasattr(P, name), name
    assert len(S.INTERFACES) == 17


# ------------------------------------------------------------------ 3. migration is a first-class contract
def test_migration_manifest_requires_every_asset_class():
    assert manifest().problems() == []
    partial = manifest(assets=manifest().assets[:-1])
    assert any("is not covered" in p for p in partial.problems())
    assert len(list(P.MigrationAsset)) == 11
    with pytest.raises(P.ProtocolViolation):
        partial.assert_valid()


def test_cutover_requires_shadow_rollback_obsolescence_and_preservation_evidence():
    assert manifest(cutover_approved=True).problems()
    ok = manifest(cutover_approved=True, shadow_comparison_ref="s", rollback_plan_ref="r", obsolescence_review_ref="o")
    assert ok.problems() == []
    bare = tuple(P.AssetMigration(a, (P.MigrationMechanism.REPLAY,)) for a in P.MigrationAsset)
    assert any("preservation_eval_refs" in p for p in dataclasses.replace(ok, assets=bare).problems())


def test_migration_source_and_target_must_differ_and_mechanisms_required():
    a = P.ArchitectureDescriptor("same", 1, "x")
    assert any("must differ" in p for p in manifest(source=a, target=a).problems())
    empty = tuple(P.AssetMigration(x, ()) for x in P.MigrationAsset)
    assert manifest(assets=empty).problems()


def test_protocol_never_branches_on_family_label_or_model_names():
    src = (ROOT / "orca/intelligence/protocol.py").read_text()
    assert "family_label" in src  # informational field exists
    assert not re.search(r"\.family_label\s*(==|in|!=)", src)
    lowered = src.lower()
    for name in ("qwen", "mistral", "phi-", "llama", "gemma", "deepseek", "gpt", "claude", "gemini", "transformer"):
        assert name not in lowered, name


def test_migration_doc_lists_mechanisms_and_self_obsolescence_rule():
    txt = (INTEL / "ORNEUR_ARCHITECTURE_MIGRATION_PROTOCOL.md").read_text()
    for w in ("distillation", "continued training", "representation", "adapter conversion", "re-indexing", "replay",
              "shadow comparison", "dual-running", "eval-preserving cutover", "Nothing is sacred merely because"):
        assert w.lower() in txt.lower(), w
    assert "Nothing is sacred merely because ORNEUR previously built it" in ARCH_MD.read_text()


# ------------------------------------------------------------------ 4. no self-promotion
def test_valid_promotion_passes():
    assert promo().problems() == []


@pytest.mark.parametrize("kw", [
    dict(decided_by="learner1"), dict(decided_by="cand1"), dict(frozen_eval_ref=None), dict(adversarial_eval_ref=""),
    dict(regression_eval_ref=None), dict(shadow_deployment_ref=None), dict(measured_improvement=0.0),
    dict(measured_improvement=None), dict(regressions_found=1), dict(regressions_found=None),
    dict(decider_kind="THE_MODEL_ITSELF"),
])
def test_promotion_is_evidence_gated_and_cannot_self_promote(kw):
    assert promo(**kw).problems()


def test_reject_and_hold_need_no_gates_but_still_cannot_self_decide():
    assert promo(verdict=P.PromotionVerdict.REJECT, frozen_eval_ref=None, measured_improvement=None, regressions_found=None).problems() == []
    assert promo(verdict=P.PromotionVerdict.HOLD, decided_by="learner1").problems()


def test_self_improvement_spec_forbids_live_mutation_and_self_promotion():
    si = S.build_spec()["self_improvement"]
    assert si["live_weight_mutation_allowed"] is False and si["self_promotion_allowed"] is False
    assert si["loop"] == S.SELF_IMPROVEMENT_LOOP and si["loop"][-1].startswith("periodic distillation")


# ------------------------------------------------------------------ 5. discoveries
def test_valid_discovery_passes_and_revision_chain_is_immutable():
    d = discovery()
    assert d.problems() == []
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.statement = "changed"  # type: ignore[misc]
    r1 = d.revise("2026-09-27T00:00:00Z", statement="s2")
    assert r1.revision == 1 and r1.parent_digest == d.digest() and d.statement == "s" and r1.problems() == []
    assert dataclasses.replace(r1, parent_digest=None).problems()


@pytest.mark.parametrize("kw", [
    dict(evidence_refs=()), dict(falsification_condition=""), dict(why_non_obvious=" "), dict(discovery_type="VIBES"),
    dict(confidence=1.5), dict(estimated_importance=-0.1), dict(tenant_id=""),
    dict(counter_evidence_status=P.CounterEvidenceStatus.SEARCHED_FOUND, counter_evidence_refs=()),
    dict(counter_evidence_refs=("c1",)),  # SEARCHED_NONE_FOUND but refs present
    dict(counter_evidence_status=P.CounterEvidenceStatus.NOT_SEARCHED, confidence=0.9),
    dict(counter_evidence_status=P.CounterEvidenceStatus.NOT_SEARCHED, confidence=0.4, outcome_status=P.DiscoveryOutcome.CONFIRMED),
])
def test_discovery_requires_evidence_and_counter_evidence_discipline(kw):
    assert discovery(**kw).problems()


def test_discovery_has_all_required_fields():
    need = {"discovery_id", "objective_id", "discovery_type", "statement", "why_non_obvious", "evidence_refs",
            "counter_evidence_refs", "assumptions", "confidence", "estimated_importance", "falsification_condition",
            "suggested_experiment", "potential_action", "affected_prior_decisions", "outcome_status", "created_at", "updated_at"}
    assert need <= {f.name for f in dataclasses.fields(P.Discovery)}


def test_hypothesis_verdicts_require_executed_tests():
    h = P.Hypothesis("h", "t", "s", ("e",), (), ("a",), "p", "ft")
    assert h.problems() == []
    assert dataclasses.replace(h, verdict=P.HypothesisVerdict.SUPPORTED).problems()
    assert dataclasses.replace(h, verdict=P.HypothesisVerdict.FALSIFIED, result_refs=("r",)).problems()  # no experiment
    assert dataclasses.replace(h, verdict=P.HypothesisVerdict.FALSIFIED, result_refs=("r",), experiment_ref="x").problems() == []
    assert dataclasses.replace(h, falsification_test="").problems()


def test_verification_must_be_independent_of_producer():
    v = P.VerificationResult("v", "s", "DETERMINISTIC", "PASSED", ("e",), "verifier", "producer")
    assert v.problems() == []
    assert dataclasses.replace(v, verifier_id="producer").problems()
    assert dataclasses.replace(v, evidence_refs=()).problems()
    assert dataclasses.replace(v, method="VIBES").problems()


# ------------------------------------------------------------------ 6. outcomes vs preference
def test_outcome_is_distinct_from_preference_feedback():
    assert P.Outcome is not P.PreferenceFeedback
    assert not ({"signal", "rating", "response_ref"} & {f.name for f in dataclasses.fields(P.Outcome)})
    assert {"observed_outcome", "success_metric", "expected_outcome", "time_horizon"} <= {f.name for f in dataclasses.fields(P.Outcome)}
    assert outcome(source=P.OutcomeSource.USER_PREFERENCE).problems()
    assert P.PreferenceFeedback("f", "t", "resp", "thumbs_up", T).problems() == []


def test_outcome_observed_requires_observation_and_evidence():
    assert outcome().problems() == []
    assert outcome(status="OBSERVED").problems()
    assert outcome(status="OBSERVED", observed_outcome="worked").problems()
    assert outcome(status="OBSERVED", observed_outcome="worked", observation_evidence_refs=("e",)).problems() == []
    assert outcome(observed_outcome="worked").problems()  # PENDING cannot carry an observation
    assert S.build_spec()["outcome_learning"]["distinct_from_preference_feedback"] is True


def test_failure_genome_tenant_privacy():
    e = P.FailureGenomeEntry("f", "t1", "class", ("trig",), "gap", ("ev",))
    assert e.problems() == []
    assert dataclasses.replace(e, scope="ANONYMIZED_SHAREABLE").problems()
    assert dataclasses.replace(e, scope="ANONYMIZED_SHAREABLE", anonymization_evidence_ref="anon").problems() == []
    assert dataclasses.replace(e, scope="PUBLIC").problems()


# ------------------------------------------------------------------ 7. world model
def test_world_versions_and_delta_are_explicit():
    assert P.WorldState("w", "t", 0, None, SHA, T).problems() == []
    assert P.WorldState("w", "t", 3, 2, SHA, T).problems() == []
    assert P.WorldState("w", "t", 3, 1, SHA, T).problems()
    assert P.WorldState("w", "t", 0, 0, SHA, T).problems()
    ch = ({"kind": "UPDATE", "target_ref": "e1", "evidence_refs": ["ev1"]},)
    assert P.WorldDelta("d", "w", "t", 3, 4, ch, T).problems() == []
    assert P.WorldDelta("d", "w", "t", 3, 5, ch, T).problems()
    assert P.WorldDelta("d", "w", "t", 3, 4, (), T).problems()
    assert P.WorldDelta("d", "w", "t", 3, 4, ({"kind": "UPDATE", "target_ref": "e1"},), T).problems()
    assert P.WorldDelta("d", "w", "t", 3, 4, ({"kind": "MUTATE", "target_ref": "e", "evidence_refs": ["x"]},), T).problems()
    assert "WorldDelta" in S.build_spec()["core_protocol_interfaces"]


def test_delta_propagation_reaches_assumptions_conclusions_and_objectives():
    edges = {"obs1": ["asm1"], "asm1": ["concl1", "concl2"], "concl1": ["obj1"], "asm2": ["concl3"]}
    kinds = {"asm1": "assumption", "asm2": "assumption", "concl1": "conclusion", "concl2": "conclusion",
             "concl3": "conclusion", "obj1": "objective"}
    out = P.propagate_delta(edges, kinds, ["obs1"])
    assert out == {"assumption": ["asm1"], "conclusion": ["concl1", "concl2"], "objective": ["obj1"], "other": []}
    assert P.propagate_delta(edges, kinds, ["unrelated"]) == {"assumption": [], "conclusion": [], "objective": [], "other": []}
    assert P.propagate_delta({"a": ["b"], "b": ["a"]}, {}, ["a"])["other"] == ["a", "b"]  # cycles terminate


# ------------------------------------------------------------------ 8. remaining protocol contracts
def test_cognitive_result_rules():
    ok = P.CognitiveResult("r", "COMPLETED", "out", ("e",), ("v",), 0.8)
    assert ok.problems() == []
    assert P.CognitiveResult("r", "COMPLETED", "out", (), (), 0.8).problems()
    assert P.CognitiveResult("r", "COMPLETED", "out", (), (), 0.8, contract_status="SATISFIED").problems() == []
    assert P.CognitiveResult("r", "COMPLETED", None, ("e",), ("v",), 0.8).problems()
    assert P.CognitiveResult("r", "FAILED_CLOSED", "leaked", (), (), None).problems()
    assert P.CognitiveResult("r", "NEEDS_INFORMATION", None, (), (), None).problems()
    q = P.InformationGainQuery("Which contract governs this?", "governing contract", 0.6, ("ask about dates",))
    assert P.CognitiveResult("r", "NEEDS_INFORMATION", None, (), (), None, information_request=q).problems() == []
    assert P.InformationGainQuery("One? Two?", "u", 0.5, ()).problems()
    assert P.InformationGainQuery("One?", "u", 1.5, ()).problems()


def test_expert_contracts_allow_unknown_kinds_but_never_trust_claims():
    e = P.ExpertCapability("x1", "FUTURE:quantum-planner", "FUTURE:photonic-net", ("planning",), P.QualificationState.CANDIDATE)
    assert e.problems() == []
    assert dataclasses.replace(e, state=P.QualificationState.QUALIFIED).problems()
    assert dataclasses.replace(e, state=P.QualificationState.QUALIFIED, qualification_eval_refs=("ev",)).problems() == []
    assert dataclasses.replace(e, kind="bad kind!").problems()
    assert P.ExpertResult("r", "x1", "OK", "out").problems() == []
    assert P.ExpertResult("r", "x1", "OK", "out", claims_trusted=True).problems()
    assert P.ExpertResult("r", "x1", "OK", None).problems()
    assert P.ExpertRequest("r", "x1", "t", "task").problems() == []


def test_cognitive_primitive_never_stores_raw_reasoning():
    p = P.CognitivePrimitive("p", 1, "class", ("step",), ("works",), ("fails",), ("ev",))
    assert p.problems() == []
    assert dataclasses.replace(p, raw_reasoning_trace_stored=True).problems()
    assert dataclasses.replace(p, state=P.QualificationState.QUALIFIED).problems()
    assert dataclasses.replace(p, version=0).problems()
    assert not any("trace" in f.name and f.name != "raw_reasoning_trace_stored" for f in dataclasses.fields(P.CognitivePrimitive))
    assert S.build_spec()["cognitive_primitives"]["stores_raw_reasoning_traces"] is False


def test_objective_and_evidence_reference_validation():
    assert P.Objective("o", "t", "s", ("m",), created_at=T).problems() == []
    assert P.Objective("o", "t", "s", (), created_at=T).problems()
    assert P.EvidenceReference("e", "doc", "file://x", SHA, T, "t").problems() == []
    assert P.EvidenceReference("e", "doc", "file://x", "nothex", T, "t").problems()


def test_contracts_are_frozen_and_digest_is_stable():
    d = discovery()
    assert d.digest() == discovery().digest() and d.digest() != discovery(statement="other").digest()
    with pytest.raises(dataclasses.FrozenInstanceError):
        promo().verdict = P.PromotionVerdict.HOLD  # type: ignore[misc]


# ------------------------------------------------------------------ 9. historical integrity
def test_historical_control_evidence_unchanged():
    state = historical_control_state(EVID)
    assert state["control_evidence_aggregate_sha256"] == CONTROL_EVIDENCE_AGGREGATE_SHA256
    assert state["file_count"] == 78
    res = state["raw_model_results_unchanged_and_separate"]
    assert {k: v["RUNTIME_QUALIFIED"] for k, v in res.items()} == {"Qwen3-8B": False, "Mistral-Nemo-Instruct-2407": False, "Phi-4": False}


def test_contract_engine_qualification_unchanged():
    import hashlib
    art = EVID / "ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json"
    assert hashlib.sha256(art.read_bytes()).hexdigest() == SYSTEM_QUAL_ARTIFACT_SHA256
    d = json.loads(art.read_text())
    assert d["verdict"] == "SYSTEM_CONTRACT_QUALIFIED" and d["model_calls"] == 0 and d["gpu_calls"] == 0
    assert S.build_spec()["historical_integrity"]["contract_engine_qualification"] == "SYSTEM_CONTRACT_QUALIFIED"


def test_phase21_closeout_still_selects_nothing():
    pkg = json.loads((PH21 / "GENESIS_FOUNDATION_DECISION_PACKAGE_2026-09-26.json").read_text())
    assert pkg["selected_foundation"] is None and pkg["gpu_authorized"] is False
    assert pkg["training_authorized"] is False and pkg["phase_21c_authorized"] is False
    assert pkg["verdict"] == "FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL"


# ------------------------------------------------------------------ 10. foundation landscape: gate-based admission
def test_raw_evidence_records_no_weights_gpu_or_provider(raw):
    assert raw["weights_downloaded"] is False and raw["gpu_used"] is False and raw["provider_inference"] is False
    assert len(raw["models"]) >= 40


def test_refresh_json_is_reproducible_from_raw_evidence(raw, refresh):
    assert json.loads(json.dumps(fl.build_document(raw), sort_keys=True)) == refresh


def test_refresh_md_is_reproducible_from_raw_evidence(raw):
    spec = importlib.util.spec_from_file_location("lbuild", ROOT / "scripts/orneur_foundation_landscape_build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.md(fl.build_document(raw)) == REFRESH_MD.read_text()


def test_classes_partition_every_model_and_admission_equals_all_gates_pass(refresh):
    members = [m for v in refresh["class_membership"].values() for m in v]
    assert sorted(members) == sorted(refresh["models"]) and len(members) == len(set(members))
    for mid, r in refresh["models"].items():
        all_pass = all(r["gates"][g]["status"] == "PASS" for g in fl.GATES)
        assert set(r["gates"]) == set(fl.GATES)
        if r["class"] == "GENESIS_TRAINABLE_NOW":
            assert r["admitted_to_capability_eval"] and all_pass, mid
        if r["class"] in {"TEACHER_REFERENCE", "FUTURE_FRONTIER_ARCHITECTURE_REFERENCE", "FUTURE_REASON_CANDIDATE", "NOT_ADMITTED"}:
            assert not r["admitted_to_capability_eval"], mid
        if not all_pass:
            assert not r["admitted_to_capability_eval"], mid


def test_unverified_or_failed_gate_blocks_admission(raw):
    base = fl.build_refresh(raw)
    trainable = [m for m, r in base.items() if r["class"] == "GENESIS_TRAINABLE_NOW"]
    assert len(trainable) >= 10
    victim = trainable[0]
    mutations = {
        "license": lambda r: r.update(license_card="other", license_name="custom"),
        "gated": lambda r: r.update(gated="manual"),
        "no_revision": lambda r: r.update(revision_sha=None),
        "no_safetensors": lambda r: r.update(safetensors=None),
        "no_config": lambda r: r.update(config_subset={}),
    }
    for name, mut in mutations.items():
        r2 = copy.deepcopy(raw)
        mut(r2["models"][victim])
        again = fl.build_refresh(r2)[victim]
        assert not again["admitted_to_capability_eval"], name
        assert again["class"] != "GENESIS_TRAINABLE_NOW", name


def test_template_probe_missing_blocks_admission(raw):
    r2 = copy.deepcopy(raw)
    victim = next(m for m, r in fl.build_refresh(raw).items() if r["class"] == "GENESIS_TRAINABLE_NOW")
    r2["ecosystem"]["template_and_layer_probes"][victim]["template_present"] = False
    assert not fl.build_refresh(r2)[victim]["admitted_to_capability_eval"]


def test_admission_ignores_recency_popularity_and_size_ranking(raw):
    base = fl.build_refresh(raw)
    r2 = copy.deepcopy(raw)
    for row in r2["models"].values():
        row["created_at"] = "2099-01-01T00:00:00Z"
        row["last_modified"] = "2099-01-01T00:00:00Z"
    again = fl.build_refresh(r2)
    for mid in base:
        assert base[mid]["class"] == again[mid]["class"], mid
        assert {g: v["status"] for g, v in base[mid]["gates"].items()} == {g: v["status"] for g, v in again[mid]["gates"].items()}


def test_largest_is_not_admitted_and_giants_are_not_trainable(refresh):
    models = refresh["models"]
    assert refresh["selected_foundation"] is None and refresh["foundation_selected"] is False
    trainable = refresh["class_membership"]["GENESIS_TRAINABLE_NOW"]
    assert all((models[m]["total_parameters_b"] or 0) <= 40 for m in trainable)
    largest = max(models, key=lambda m: models[m]["total_parameters_b"] or 0)
    assert largest not in trainable
    # the newest-released and the largest models must never be auto-admitted as the base
    for m in refresh["class_membership"]["TEACHER_REFERENCE"] + refresh["class_membership"]["FUTURE_FRONTIER_ARCHITECTURE_REFERENCE"]:
        assert not models[m]["admitted_to_capability_eval"]


def test_controls_are_baselines_not_automatic_candidates(refresh):
    ctrl = {"Qwen/Qwen3-8B", "mistralai/Mistral-Nemo-Instruct-2407", "microsoft/phi-4"}
    assert set(refresh["class_membership"]["BASELINE_ONLY_CONTROL"]) == ctrl
    assert not ctrl & set(refresh["class_membership"]["GENESIS_TRAINABLE_NOW"])


def test_license_screen_catches_assistant_business_restrictions(refresh):
    m = refresh["models"]
    for bad in ("Qwen/Qwen3.8-Flash-Next", "zai-org/GLM-5.3", "LiquidAI/LFM2.5-2.6B", "meta-llama/Llama-3.3-70B-Instruct",
                "meta-llama/Llama-4-Scout-17B-16E-Instruct"):
        assert m[bad]["gates"]["A_license"]["status"] == "FAIL", bad
        assert not m[bad]["admitted_to_capability_eval"]
    assert m["Qwen/Qwen3.8-Flash-Next"]["class"] == "FUTURE_FRONTIER_ARCHITECTURE_REFERENCE"


def test_moe_and_natively_quantized_models_are_not_silently_trainable(refresh):
    m = refresh["models"]
    for mid in ("Qwen/Qwen3.5-35B-A3B", "google/gemma-4-26B-A4B-it", "openai/gpt-oss-20b", "zai-org/GLM-4.7-Flash",
                "mistralai/Ministral-3-8B-Instruct-2512"):
        assert m[mid]["gates"]["E_peft_qlora_feasible"]["status"] == "UNVERIFIED", mid
        assert m[mid]["class"] == "FUTURE_REASON_CANDIDATE"


def test_every_gate_result_carries_status_basis_and_note_and_dense_peft_is_labelled_inferred(refresh):
    for mid, r in refresh["models"].items():
        for g in fl.GATES:
            gate = r["gates"][g]
            assert gate["status"] in {"PASS", "FAIL", "UNVERIFIED"} and gate["basis"] and gate["note"]
    dense = refresh["models"]["Qwen/Qwen3.5-9B"]["gates"]["E_peft_qlora_feasible"]
    assert dense["status"] == "PASS" and dense["basis"] == "INFERRED_NOT_EXECUTED"


def test_required_admission_record_fields_present(refresh):
    need = {"model", "revision_sha", "license", "architecture", "total_parameters_b", "active_parameters_b", "context_tokens",
            "multimodality", "tool_calling_template", "structured_output", "reasoning_template", "quantization_support",
            "known_caveats", "primary_sources", "gates", "class", "class_reason"}
    for mid, r in refresh["models"].items():
        assert need <= set(r), mid
        assert r["primary_sources"] and all(u.startswith("https://") for u in r["primary_sources"])
    for mid in refresh["class_membership"]["GENESIS_TRAINABLE_NOW"]:
        r = refresh["models"][mid]
        assert re.fullmatch(r"[0-9a-f]{40}", r["revision_sha"]) and "estimates" in r
        assert r["estimates"]["kind"] == "ESTIMATE_NOT_MEASUREMENT"


def test_active_parameters_are_labelled_by_source_never_presented_as_verified(refresh):
    for mid, r in refresh["models"].items():
        if r["active_parameters_b"]:
            assert re.match(r"(NAME_DERIVED|VENDOR_CLAIM|PRIOR_LANDSCAPE_DOC_VENDOR_CLAIM)", r["active_parameters_source"]), mid


def test_moe_models_are_never_labelled_dense(refresh):
    moes = [m for m, r in refresh["models"].items() if r["is_moe"]]
    assert len(moes) >= 10
    for m in moes:
        assert refresh["models"][m]["active_parameters_source"] != "DENSE", m
    for m in ("deepseek-ai/DeepSeek-V4-Pro-0813", "mistralai/Mistral-Small-4-119B-2603", "openai/gpt-oss-120b"):
        assert refresh["models"][m]["is_moe"] is True and refresh["models"][m]["active_parameters_b"] in (None, 5.1)
    assert refresh["models"]["Qwen/Qwen3.5-9B"]["is_moe"] is False


def test_cost_estimator_matches_audited_decision_package_range():
    lo, hi = fl.usd_per_million_tokens(8.2)
    assert (0.21 <= lo <= 0.23) and (0.35 <= hi <= 0.37)  # closeout: Qwen3-8B 0.22-0.36 USD per 1M tokens
    assert fl.usd_per_million_tokens(20)[0] > fl.usd_per_million_tokens(8)[0]
    assert fl.qlora_vram_gb(10)[0] < fl.qlora_vram_gb(10)[1]


def test_budget_section_is_planning_only(refresh):
    b = refresh["budget_planning"]
    assert b["kind"] == "PLANNING_ONLY_NOT_AUTHORIZATION" and b["frontier_pretraining_possible_within_budget"] is False
    txt = REFRESH_MD.read_text()
    assert "cannot pretrain or continue-pretrain a frontier model" in txt
    assert "initial adaptation cost" in txt and "production inference cost" in txt and "future full-pretraining" in txt


def test_selection_rule_excludes_recency_size_and_popularity(refresh):
    assert "never inputs" in refresh["selection_rule"] and "Release date, parameter count and popularity" in refresh["selection_rule"]


# ------------------------------------------------------------------ 11. authorizations
def test_no_phase21c_gpu_training_or_provider_authorization_anywhere(refresh):
    spec = S.build_spec()["authorizations"]
    assert spec == {"training": False, "gpu": False, "provider_inference": False, "phase_21c": False, "foundation_selected": False}
    for k in ("training_authorized", "gpu_authorized", "provider_inference_authorized", "phase_21c_authorized", "foundation_selected"):
        assert refresh[k] is False
    for p in DOCS:
        t = p.read_text().lower()
        assert not re.search(r"(gpu|training|phase 21c)[a-z _]*authorized\s*[=:]\s*true", t), p


def test_no_training_artifacts_or_weights_committed_in_new_paths():
    bad = {".safetensors", ".pt", ".pth", ".bin", ".gguf", ".ckpt", ".onnx"}
    for d in (INTEL, PH21, EVID):
        assert not [p for p in d.rglob("*") if p.suffix in bad], d


def test_new_code_makes_no_network_gpu_or_provider_calls():
    for rel in ("orca/intelligence/protocol.py", "orca/intelligence/spec.py", "orca/eval/foundation_landscape.py"):
        src = (ROOT / rel).read_text()
        assert not re.search(r"\b(import|from)\s+(requests|httpx|urllib|socket|torch|modal|openai|anthropic|vllm)\b", src), rel


# ------------------------------------------------------------------ 12. documents
def test_all_required_documents_exist_and_are_nonempty():
    for p in DOCS + [ARCH_JSON, REFRESH_JSON]:
        assert p.exists() and p.stat().st_size > 1500, p


def test_no_marketing_overclaims():
    forbidden = [r"\bis (now )?agi\b", r"achieves? agi", r"\bis (self-aware|conscious|sentient)\b", r"guarantees? (that )?ornEur will survive",
                 r"better than (gpt|claude|gemini)", r"outperforms? (gpt|claude|gemini)", r"\bautonomously (self-)?evolves\b"]
    for p in DOCS:
        t = p.read_text().lower()
        for pat in forbidden:
            assert not re.search(pat.lower(), t), (p.name, pat)
    arch = ARCH_MD.read_text()
    for w in ("general intelligence", "self-awareness", "consciousness", "autonomous self-evolution", "perfect reasoning",
              "survives 20 years", "frontier capability", "roadmap and a set of contracts"):
        assert w in arch, w
    assert set(S.NON_CLAIMS) >= {"AGI", "consciousness", "autonomous self-evolution", "perfect reasoning"}


def test_instant_response_fabric_is_specified_with_design_targets_only():
    f = S.build_spec()["cross_cutting"]["instant_response_fabric"]
    assert f["measured_slo_claimed"] is False and f["latency_targets_are_design_targets_only"] is True
    assert f["strict_contracts"] == "validate before release" and "progressively verified" in f["free_text"]
    assert {"model generation", "memory retrieval", "search", "tool preparation", "evidence construction",
            "verification", "confidence calculation"} == set(f["parallel_lanes"])
    txt = ARCH_MD.read_text()
    for rule in ("Never serialize independent work", "Never invoke more intelligence than the request requires",
                 "Verification runs beside generation when safe", "without making ORNEUR feel visibly slower", "DESIGN TARGETS ONLY"):
        assert rule.lower() in txt.lower(), rule


def test_architecture_doc_covers_required_sections():
    t = ARCH_MD.read_text()
    for w in ("Reality Compiler", "Living World Model", "World Delta", "Hypothesis Laboratory", "Self-Evolving Expert Mesh",
              "Controlled self-improvement", "Outcome Learning", "Cognitive primitives", "Information-gain",
              "Cross-domain", "Self-Obsolescence Rule", "Instant Response Fabric", "Permanent versus replaceable",
              "Models are replaceable organs", "not tied to 14B, 70B, 500B"):
        assert w.lower() in t.lower(), w
    perm = S.build_spec()["permanent_components"]
    assert "architecture migration machinery" in perm and "Contract Compliance" in perm
    rep = " ".join(S.build_spec()["replaceable_components"]).lower()
    for w in ("transformers", "moe", "rag", "tokenizers", "checkpoint families", "parameter-count"):
        assert w in rep, w


def test_eval_design_has_all_categories_and_no_single_score():
    t = PH21.joinpath("GENESIS_CAPABILITY_EVAL_V1_DESIGN.md").read_text()
    for c in S.CAPABILITY_EVAL_CATEGORIES:
        assert f"`{c}`" in t, c
    assert "No single \"smartness\" score" in t and "pre-registered" in t.lower()
    assert len(S.CAPABILITY_EVAL_CATEGORIES) == 21
    for d in S.DISCOVERY_EVAL_DIMENSIONS:
        assert d.replace("_", " ") in re.sub(r"[-_]", " ", t.lower()), d
    for w in ("ORNEUR_DISCOVERY_EVAL", "ORNEUR_SELF_IMPROVEMENT_EVAL", "CROSS_DOMAIN_TRANSFER", "not claimed today", "design only"):
        assert w in t, w
    assert "false-promotion count (must be 0)" in t


def test_discovery_and_mesh_docs_state_key_rules():
    d = (INTEL / "ORNEUR_DISCOVERY_INTELLIGENCE.md").read_text()
    for w in ("why_non_obvious", "counter_evidence_status", "falsification_condition", "parent_digest", "NOT_SEARCHED"):
        assert w in d, w
    m = (INTEL / "ORNEUR_SELF_EVOLVING_EXPERT_MESH.md").read_text()
    for w in ("claims_trusted", "cannot promote its own candidate", "external temporary teacher", "symbolic engine", "simulator", "retriever"):
        assert w.lower() in m.lower(), w


def test_reality_compiler_spec_is_protocol_only():
    rc = S.build_spec()["reality_compiler"]
    assert rc["model_independent"] is True and rc["connectors_built_now"] is False
    for w in ("entities", "relationships", "events", "claims", "evidence", "contradictions", "timelines", "objectives",
              "constraints", "obligations", "decisions", "risks", "assumptions", "unknowns"):
        assert w in rc["canonical_objects"], w
    for w in ("email", "calendar", "spreadsheets", "sensors", "agent results"):
        assert w in rc["inputs"], w
