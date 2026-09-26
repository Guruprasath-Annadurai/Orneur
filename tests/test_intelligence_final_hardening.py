"""Final pre-freeze hardening: epistemic vs non-epistemic output, digest binding, trusted provenance,
claim-level verification, corrected Genesis funnel, computed freeze readiness."""
from __future__ import annotations

import dataclasses
import json
import re
import shutil
from pathlib import Path

import pytest

from orca.contracts import ContractEngine, ContractStatus
from orca.eval import genesis_funnel as gf
from orca.intelligence import freeze as FR
from orca.intelligence import protocol as P
from orca.intelligence import spec as S

ROOT = Path(__file__).resolve().parents[1]
ARCH_MD = ROOT / "docs/orneur/intelligence/ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.md"
ARCH_JSON = ROOT / "docs/orneur/intelligence/ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.json"
EVAL_MD = ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V1_DESIGN.md"
dg = P.content_digest
OD = dg("5")
K = P.OutputKind


@pytest.fixture()
def led():
    return P.ProvenanceLedger()


class Kit:
    """Builds results whose provenance is minted by a real ledger."""

    def __init__(self, led):
        self.led = led

    def prov(self, kind, output_digest=OD, input_digest=None, component_id=None, authority="ev"):
        return self.led.issue(component_id=component_id or f"{kind.lower()}-1", component_kind=kind, execution_ref="exec-1",
                              authority_evidence_ref=authority, input_digest=input_digest or dg("in"), output_digest=output_digest)

    def router(self, kind):
        return self.prov("ROUTER", output_digest=P.classification_digest(kind))

    def ver(self, output_ref="out", digest=OD, claim=None, verdict="PASSED", verifier="verifier-1", provenance=True, **kw):
        seen = claim.claim_digest if claim else digest
        base = dict(verification_id=f"v-{verifier}-{claim.claim_id if claim else 'whole'}", subject_ref=output_ref, method="TOOL",
                    verdict=verdict, evidence_refs=("ev",), verifier_id=verifier, producer_id="producer", subject_digest=digest,
                    claim_id=claim.claim_id if claim else None, claim_digest=claim.claim_digest if claim else None,
                    provenance=self.prov("VERIFIER", input_digest=seen, component_id=verifier) if provenance else None)
        base.update(kw)
        return P.VerificationResult(**base)

    def claim(self, text="The capital of X is Y", cid="c1", output_ref="out", digest=OD):
        return P.ClaimBinding(cid, output_ref, digest, dg(text), canonical_claim=text)

    def base(self, kind, **kw):
        b = dict(request_id="r", status="COMPLETED", output_ref="out", evidence_refs=("e",), verifications=(), confidence=0.8,
                 output_kind=kind, output_digest=OD, presented_as=P.PRESENTATION[kind], classification_provenance=self.router(kind))
        b.update(kw)
        return P.CognitiveResult(**b)

    def det(self, kind=K.DETERMINISTIC_MATH, ctype="DETERMINISTIC_MATH", **kw):
        b = dict(contract_type=ctype, contract_status="SATISFIED", contract_evidence_ref="ce", contract_output_digest=OD, model_calls=0,
                 deterministic_provenance=self.prov("DETERMINISTIC_AUTHORITY", authority="ce"), confidence=1.0, evidence_refs=())
        b.update(kw)
        return self.base(kind, **b)

    def epi(self, vs=None, **kw):
        return self.base(K.GENERATED_EPISTEMIC, verifications=(self.ver(),) if vs is None else vs, **kw)

    def structured(self, vs=None, **kw):
        b = dict(contract_type="JSON_SCHEMA", contract_status="SATISFIED", contract_evidence_ref="sc",
                 verifications=(self.ver(),) if vs is None else vs)
        b.update(kw)
        return self.base(K.GENERATED_STRUCTURED_EPISTEMIC, **b)

    def transform(self, **kw):
        b = dict(source_digests=(dg("supplied paragraph"),), screening_provenance=self.prov("EPISTEMIC_SCREENER"))
        b.update(kw)
        return self.base(K.GENERATED_TRANSFORMATIVE, **b)

    def creative(self, **kw):
        b = dict(screening_provenance=self.prov("EPISTEMIC_SCREENER"))
        b.update(kw)
        return self.base(K.GENERATED_CREATIVE, **b)


@pytest.fixture()
def kit(led):
    return Kit(led)


# =============================================================== 1. epistemic vs non-epistemic
def test_output_kinds_distinguish_epistemic_from_non_epistemic():
    assert {k.value for k in K} == {"DETERMINISTIC_EXACT_TEXT", "DETERMINISTIC_MATH", "DETERMINISTIC_JSON_LITERAL", "GENERATED_EPISTEMIC",
                                    "GENERATED_STRUCTURED_EPISTEMIC", "GENERATED_TRANSFORMATIVE", "GENERATED_CREATIVE"}
    assert P.EPISTEMIC_KINDS == {K.GENERATED_EPISTEMIC, K.GENERATED_STRUCTURED_EPISTEMIC}
    assert P.NON_EPISTEMIC_GENERATED_KINDS == {K.GENERATED_TRANSFORMATIVE, K.GENERATED_CREATIVE}
    sem = S.build_spec_core()["output_semantics"]
    assert sem["transformative_requires_factual_verification"] is False and sem["creative_requires_factual_verification"] is False
    assert sem["creative_may_be_presented_as_fact"] is False and sem["contract_compliance_is_truth_verification"] is False
    assert sem["fail_closed_for_strict_contracts_weakened"] is False


def test_rewrite_completes_as_transformative_without_factual_verification(kit, led):
    r = kit.transform()
    assert r.verifications == () and r.problems(led) == []


def test_fictional_story_completes_as_creative_without_factual_verification(kit, led):
    r = kit.creative()
    assert r.verifications == () and r.problems(led) == []


def test_factual_statement_is_epistemic_and_needs_verification(kit, led):
    assert kit.epi(vs=()).problems(led)
    assert kit.epi().problems(led) == []


def test_valid_json_with_factual_claims_is_structured_epistemic_and_schema_alone_is_insufficient(kit, led):
    schema_only = kit.structured(vs=())
    assert any("contract compliance does not substitute" in p for p in schema_only.problems(led))
    assert kit.structured().problems(led) == []
    assert kit.structured(contract_status="VIOLATED").problems(led)            # verification alone is not enough either
    assert kit.structured(contract_evidence_ref=None).problems(led)
    assert kit.structured(contract_type="EXACT_TEXT").problems(led)
    assert kit.structured(contract_output_digest=dg("other")).problems(led)


def test_transformation_that_introduces_new_claims_is_epistemic_for_those_claims(kit, led):
    c = kit.claim()
    unverified = kit.transform(claim_bindings=(c,))
    assert any("no passing, trusted, digest-bound claim verification" in p for p in unverified.problems(led))
    assert kit.transform(claim_bindings=(c,), verifications=(kit.ver(claim=c),)).problems(led) == []
    assert kit.transform(claim_bindings=(c,), verifications=(kit.ver(claim=c, verdict="FAILED"),)).problems(led)


def test_creative_content_is_never_silently_presented_as_factual(kit, led):
    assert kit.creative(presented_as="VERIFIED_CLAIMS").problems(led)
    assert kit.transform(presented_as="VERIFIED_CLAIMS").problems(led)
    assert kit.creative(presented_as=None).problems(led)
    assert kit.epi(presented_as="FICTION_OR_IDEATION").problems(led)          # and epistemic output is only ever 'verified claims'
    c = kit.claim("Paris is the capital of France")
    assert kit.creative(claim_bindings=(c,)).problems(led)                    # embedded factual claim without verification
    assert kit.creative(claim_bindings=(c,), verifications=(kit.ver(claim=c),)).problems(led) == []


def test_non_epistemic_kinds_need_trusted_screening_and_transformations_need_sources(kit, led):
    assert kit.creative(screening_provenance=None).problems(led)
    assert kit.transform(screening_provenance=None).problems(led)
    assert kit.transform(source_digests=()).problems(led)
    assert kit.transform(source_digests=("not-a-digest",)).problems(led)
    assert kit.creative(screening_provenance=kit.prov("EPISTEMIC_SCREENER", output_digest=dg("different output"))).problems(led)


def test_kind_cannot_be_downgraded_by_reusing_another_kinds_router_provenance(kit, led):
    """A creative classification cannot be reused to escape verification for an epistemic answer."""
    creative_router = kit.router(K.GENERATED_CREATIVE)
    r = kit.epi(vs=(), classification_provenance=creative_router)
    assert any("output_kind classification provenance output_digest" in p for p in r.problems(led))
    laundered = kit.base(K.GENERATED_CREATIVE, classification_provenance=kit.router(K.GENERATED_EPISTEMIC),
                         screening_provenance=kit.prov("EPISTEMIC_SCREENER"))
    assert laundered.problems(led)


@pytest.mark.parametrize("kind,ctype", [(K.DETERMINISTIC_EXACT_TEXT, "EXACT_TEXT"), (K.DETERMINISTIC_MATH, "DETERMINISTIC_MATH"),
                                        (K.DETERMINISTIC_JSON_LITERAL, "JSON_LITERAL")])
def test_deterministic_kinds_complete_on_their_authority_alone(kit, led, kind, ctype):
    r = kit.det(kind, ctype)
    assert r.verifications == () and r.problems(led) == []


@pytest.mark.parametrize("kw", [dict(model_calls=1), dict(contract_status="VIOLATED"), dict(contract_evidence_ref=None),
                                dict(contract_output_digest=dg("x")), dict(contract_output_digest=None), dict(contract_type="JSON_SCHEMA"),
                                dict(deterministic_provenance=None)])
def test_deterministic_bypass_stays_narrow_and_fail_closed(kit, led, kw):
    assert kit.det(**kw).problems(led)


def test_strict_contract_engine_results_still_gate_the_deterministic_bypass(kit, led):
    def boom(_r):
        raise AssertionError("no model for deterministic math")

    eng = ContractEngine()
    ok = eng.execute("2 + 3", boom)
    assert ok.status is ContractStatus.SATISFIED and ok.final_output == "5"
    d = dg(ok.final_output)
    assert ok.evidence.final_output_sha256 == d                       # the engine's own evidence digest IS the protocol digest
    r = kit.det(output_digest=d, contract_output_digest=ok.evidence.final_output_sha256, contract_evidence_ref="ce",
                classification_provenance=kit.router(K.DETERMINISTIC_MATH),
                deterministic_provenance=kit.prov("DETERMINISTIC_AUTHORITY", output_digest=d, authority="ce"))
    assert r.problems(led) == []
    bad = eng.execute("1 / 0", boom)
    assert bad.status is not ContractStatus.SATISFIED and bad.final_output is None
    assert kit.det(contract_status=bad.status.value).problems(led)     # an unsatisfied contract can never ride the bypass


def test_contract_engine_still_qualified_and_unchanged_by_this_pass():
    art = json.loads((ROOT / "docs/orneur/phase-21/evidence/ORNEUR_SYSTEM_CONTRACT_QUALIFICATION_2026-09-26.json").read_text())
    assert art["verdict"] == "SYSTEM_CONTRACT_QUALIFIED" and art["model_calls"] == 0


def test_only_deterministic_kinds_bypass_and_contract_engine_is_not_a_verification_method():
    assert {k.value for k in P.DETERMINISTIC_KINDS} == {"DETERMINISTIC_EXACT_TEXT", "DETERMINISTIC_MATH", "DETERMINISTIC_JSON_LITERAL"}
    assert "CONTRACT_ENGINE" not in P.VERIFICATION_METHODS
    b = S.build_spec_core()["contract_compliance_vs_verification"]
    assert b["distinct_concepts"] is True and b["generated_json_schema_satisfaction_bypasses_verification"] is False


# =============================================================== 2. digest binding / TOCTOU
def test_correct_ref_and_digest_pass(kit, led):
    assert kit.epi().problems(led) == []


def test_matching_ref_with_mismatching_digest_fails(kit, led):
    assert kit.epi(vs=(kit.ver(digest=dg("older bytes")),)).problems(led)


def test_matching_digest_with_wrong_subject_ref_fails(kit, led):
    assert kit.epi(vs=(kit.ver(output_ref="some-other-output"),)).problems(led)


def test_changing_output_digest_invalidates_prior_verification(kit, led):
    verified = kit.epi()
    assert verified.problems(led) == []
    mutated_digest = dg("5 (edited after verification)")
    edited = dataclasses.replace(verified, output_digest=mutated_digest,
                                 classification_provenance=kit.router(K.GENERATED_EPISTEMIC))
    assert any("requires a passing, trusted, digest-bound Verification" in p for p in edited.problems(led))


def test_verification_of_an_older_version_cannot_qualify_a_newer_output(kit, led):
    v1_digest, v2_digest = dg("answer v1"), dg("answer v2")
    old_verification = kit.ver(digest=v1_digest)
    newer = kit.epi(vs=(old_verification,), output_digest=v2_digest)
    assert newer.problems(led)
    fresh = kit.epi(vs=(kit.ver(digest=v2_digest),), output_digest=v2_digest)
    assert fresh.problems(led) == []


def test_verifier_provenance_must_show_it_consumed_the_same_bytes(kit, led):
    v = kit.ver()
    saw_other = dataclasses.replace(v, provenance=kit.prov("VERIFIER", input_digest=dg("other bytes"), component_id="verifier-1"))
    assert kit.epi(vs=(saw_other,)).problems(led)
    wrong_component = dataclasses.replace(v, provenance=kit.prov("VERIFIER", input_digest=OD, component_id="impostor"))
    assert kit.epi(vs=(wrong_component,)).problems(led)


def test_digests_must_be_lowercase_sha256(kit, led):
    for bad in (OD.upper(), OD[:-1], "", "g" * 64, None):
        assert kit.epi(output_digest=bad).problems(led)
        assert kit.ver(digest=bad if isinstance(bad, str) else "").problems()


def test_missing_digest_fields_fail_closed(kit, led):
    assert kit.epi(output_digest=None).problems(led)
    v = P.VerificationResult("v", "out", "TOOL", "PASSED", ("e",), "verifier-1", "producer")   # no subject_digest at all
    assert any("subject_digest" in p for p in v.problems())


def test_release_time_recheck_detects_check_then_swap(kit, led):
    text = "5"
    r = kit.epi(output_digest=dg(text))
    assert r.release_matches(text) and r.release_matches(text.encode("utf-8"))
    assert not r.release_matches("5 ")            # any swap after verification changes the bytes and is caught
    assert not r.release_matches("6")
    assert dg(text) == dg(text.encode()) and re.fullmatch(r"[0-9a-f]{64}", dg(text))


def test_deterministic_evidence_is_bound_to_the_same_output_digest(kit, led):
    assert kit.det(contract_output_digest=OD).problems(led) == []
    assert kit.det(contract_output_digest=dg("6")).problems(led)
    assert kit.det(deterministic_provenance=kit.prov("DETERMINISTIC_AUTHORITY", output_digest=dg("6"), authority="ce")).problems(led)
    assert kit.det(deterministic_provenance=kit.prov("DETERMINISTIC_AUTHORITY", authority="another-evidence")).problems(led)


def test_toctou_protection_is_documented():
    t = ARCH_MD.read_text()
    for w in ("time-of-check/time-of-use", "output_digest", "subject_digest", "release_matches", "opaque names",
              "older version cannot qualify a newer output", "matching ref with a different digest fails"):
        assert w in t, w
    j = S.build_spec_core()["content_binding"]
    assert "toctou" in j and "subject_digest == output_digest" in j["qualifying_verification_requires"]


# =============================================================== 3. trusted provenance
def test_string_authority_declarations_carry_no_authority(kit, led):
    forged = P.RuntimeProvenance("ORNEUR_ROUTER", "ORNEUR_ROUTER", "ROUTER", "x", "deterministic_arith", dg("i"), P.classification_digest(K.DETERMINISTIC_MATH), "0" * 64)
    r = kit.det(classification_provenance=forged)
    assert any("not verifiable by the trusted ledger" in p for p in r.problems(led))
    assert kit.det(deterministic_provenance=P.RuntimeProvenance("p", "orca.contracts.arith", "DETERMINISTIC_AUTHORITY", "x", "ce", dg("i"), OD, "f" * 64)).problems(led)
    assert not {"output_kind_assigned_by", "deterministic_authority"} & {f.name for f in dataclasses.fields(P.CognitiveResult)}


def test_completed_results_fail_closed_without_a_trusted_ledger(kit):
    good = kit.det()
    assert any("trusted ProvenanceLedger" in p for p in good.problems())
    assert any("trusted ProvenanceLedger" in p for p in good.problems(None))
    with pytest.raises(P.ProtocolViolation):
        good.assert_valid()


def test_foreign_ledger_and_tampered_fields_do_not_verify(kit, led):
    other = P.ProvenanceLedger()
    assert kit.det().problems(other)
    p = kit.prov("DETERMINISTIC_AUTHORITY", authority="ce")
    assert led.verify(p)
    for field, value in (("output_digest", dg("tampered")), ("component_id", "someone-else"), ("authority_evidence_ref", "other"),
                         ("component_kind", "ROUTER"), ("input_digest", dg("x")), ("execution_ref", "e2"), ("seal", "0" * 64)):
        assert not led.verify(dataclasses.replace(p, **{field: value})), field
    assert not led.verify("ORNEUR_ROUTER") and not led.verify(None)


def test_wrong_component_kind_cannot_stand_in_for_another(kit, led):
    assert kit.det(deterministic_provenance=kit.prov("ROUTER", authority="ce")).problems(led)
    assert kit.det(classification_provenance=kit.prov("VERIFIER", output_digest=P.classification_digest(K.DETERMINISTIC_MATH))).problems(led)
    assert kit.creative(screening_provenance=kit.prov("ROUTER")).problems(led)


def test_provenance_survives_serialisation_only_with_its_seal_and_only_for_its_ledger(kit, led):
    p = kit.prov("ROUTER")
    d = p.to_dict()
    assert led.verify(P.RuntimeProvenance(**d))                    # a faithful copy of a ledger-issued record still verifies
    assert not P.ProvenanceLedger().verify(P.RuntimeProvenance(**d))
    d["seal"] = "0" * 64
    assert not led.verify(P.RuntimeProvenance(**d))
    assert {"provenance_id", "component_id", "component_kind", "execution_ref", "authority_evidence_ref", "input_digest",
            "output_digest"} <= {f.name for f in dataclasses.fields(P.RuntimeProvenance)}


def test_model_supplied_authority_cannot_create_a_deterministic_bypass(kit, led):
    """The audit's central case: a payload that merely *claims* to be deterministic."""
    payload = {"request_id": "r", "status": "COMPLETED", "output_ref": "out", "confidence": 1.0, "output_kind": "DETERMINISTIC_MATH",
               "output_digest": OD, "presented_as": "DETERMINISTIC_OUTPUT", "contract_type": "DETERMINISTIC_MATH", "contract_status": "SATISFIED",
               "contract_evidence_ref": "ce", "contract_output_digest": OD, "model_calls": 0,
               "classification_provenance": {"component_id": "ORNEUR_ROUTER", "component_kind": "ROUTER"},
               "deterministic_provenance": {"component_id": "orca.contracts.arith", "component_kind": "DETERMINISTIC_AUTHORITY"},
               "verifications": [{"verifier_id": "me", "verdict": "PASSED"}], "evidence_refs": [], "extra": {"seal": "x", "ok": 1}}
    clean, stripped = P.strip_privileged(payload)
    assert {"output_kind", "presented_as", "contract_status", "contract_evidence_ref", "contract_output_digest", "model_calls",
            "classification_provenance", "deterministic_provenance", "verifications", "extra.seal"} <= set(stripped)
    assert clean["extra"] == {"ok": 1} and "output_kind" not in clean
    rebuilt = P.CognitiveResult(request_id=clean["request_id"], status=clean["status"], output_ref=clean["output_ref"], evidence_refs=(),
                                verifications=(), confidence=clean["confidence"], output_digest=clean["output_digest"])
    assert rebuilt.problems(led)                                    # nothing privileged survives, so it cannot complete
    assert any("output_kind" in p for p in rebuilt.problems(led))


def test_payload_verification_with_forged_provenance_cannot_qualify(kit, led):
    forged_v = kit.ver(provenance=False)
    assert kit.epi(vs=(forged_v,)).problems(led)
    fake = P.RuntimeProvenance("v", "verifier-1", "VERIFIER", "x", "y", OD, OD, "a" * 64)
    assert kit.epi(vs=(dataclasses.replace(forged_v, provenance=fake),)).problems(led)


def test_strip_privileged_is_recursive_and_pure():
    original = {"a": [{"seal": 1, "b": 2}], "output_kind": "X"}
    clean, stripped = P.strip_privileged(original)
    assert clean == {"a": [{"b": 2}]} and stripped == ["a[0].seal", "output_kind"] and "seal" in original["a"][0]
    assert {"seal", "provenance", "output_kind", "verifications", "claims_trusted"} <= P.PRIVILEGED_FIELDS


def test_provenance_documentation_states_the_invariants():
    t = ARCH_MD.read_text()
    for w in ("An ordinary string is not authority", "strip or reject privileged fields", "ProvenanceLedger", "does not attempt PKI", "fail closed"):
        assert w in t, w
    sp = S.build_spec_core()["runtime_provenance"]
    assert sp["self_asserted_strings_carry_no_authority"] is True and set(sp["component_kinds"]) == set(P.PROVENANCE_KINDS)


# =============================================================== 5. claim-level verification
def test_claim_binding_validation():
    c = P.ClaimBinding("c", "out", OD, dg("claim"), canonical_claim="claim")
    assert c.problems() == []
    assert P.ClaimBinding("c", "out", OD, dg("other"), canonical_claim="claim").problems()           # digest must match the claim
    assert P.ClaimBinding("c", "out", OD, dg("claim")).problems()                                     # needs span or claim
    assert P.ClaimBinding("c", "out", OD, dg("claim"), span_start=5, span_end=3).problems()
    assert P.ClaimBinding("c", "out", OD, dg("claim"), span_start=0, span_end=None).problems()
    assert P.ClaimBinding("c", "out", OD.upper(), dg("claim"), canonical_claim="claim").problems()
    assert not any("reason" in f.name or "thought" in f.name for f in dataclasses.fields(P.ClaimBinding))


def test_claim_span_binds_to_the_exact_released_text():
    text = "Intro sentence. Paris is the capital of France. Closing."
    span = (16, 47)
    claim = P.ClaimBinding("c1", "out", dg(text), dg(text[span[0]:span[1]]), span_start=span[0], span_end=span[1])
    assert claim.problems() == [] and claim.matches_output(text)
    assert not claim.matches_output(text.replace("Paris", "Lyon"))
    assert not claim.matches_output(text + "!")
    assert not P.ClaimBinding("c1", "out", dg(text), dg("x"), span_start=0, span_end=10**6).matches_output(text)


def test_claim_level_coverage_completes_without_whole_output_verification(kit, led):
    a, b = kit.claim("A is 1", "c1"), kit.claim("B is 2", "c2")
    r = kit.base(K.GENERATED_EPISTEMIC, claim_bindings=(a, b), verifications=(kit.ver(claim=a), kit.ver(claim=b, verifier="verifier-2")),
                 claim_extraction_provenance=kit.prov("CLAIM_EXTRACTOR"))
    assert r.problems(led) == []                       # non-claim prose needed no verification of its own


@pytest.mark.parametrize("case", ["no_extraction_provenance", "unverified_claim", "failed_claim", "claim_other_output", "verification_wrong_claim",
                                  "verification_wrong_digest", "extractor_wrong_kind", "no_claims_no_verification"])
def test_claim_level_coverage_fails_closed(kit, led, case):
    a, b = kit.claim("A is 1", "c1"), kit.claim("B is 2", "c2")
    ex = kit.prov("CLAIM_EXTRACTOR")
    kw = dict(claim_bindings=(a, b), verifications=(kit.ver(claim=a), kit.ver(claim=b, verifier="verifier-2")), claim_extraction_provenance=ex)
    if case == "no_extraction_provenance":
        kw["claim_extraction_provenance"] = None
    elif case == "unverified_claim":
        kw["verifications"] = (kit.ver(claim=a),)
    elif case == "failed_claim":
        kw["verifications"] = (kit.ver(claim=a), kit.ver(claim=b, verifier="verifier-2", verdict="FAILED"))
    elif case == "claim_other_output":
        kw["claim_bindings"] = (a, kit.claim("B is 2", "c2", digest=dg("another output")))
    elif case == "verification_wrong_claim":
        kw["verifications"] = (kit.ver(claim=a), kit.ver(claim=kit.claim("B is 3", "c2"), verifier="verifier-2"))
    elif case == "verification_wrong_digest":
        kw["verifications"] = (kit.ver(claim=a), kit.ver(claim=b, verifier="verifier-2", digest=dg("stale")))
    elif case == "extractor_wrong_kind":
        kw["claim_extraction_provenance"] = kit.prov("ROUTER")
    elif case == "no_claims_no_verification":
        kw = dict(claim_bindings=(), verifications=(), claim_extraction_provenance=ex)
    assert kit.base(K.GENERATED_EPISTEMIC, **kw).problems(led)


def test_verification_can_bind_to_whole_output_or_a_specific_claim(kit, led):
    c = kit.claim()
    whole, claim_level = kit.ver(), kit.ver(claim=c)
    assert whole.claim_id is None and claim_level.claim_id == "c1" and claim_level.claim_digest == c.claim_digest
    assert kit.ver(claim_id="c1", claim_digest=None).problems()
    assert kit.ver(claim_id=None, claim_digest=dg("x")).problems()
    # a claim-level verification does not double as a whole-output verification
    assert kit.epi(vs=(claim_level,)).problems(led)
    assert S.build_spec_core()["claim_level_verification"]["verification_engine_implemented"] is False


# =============================================================== 4 + 6. corrected Genesis funnel / selection
COMPAT = {f"m{i}": {"all_checks_passed": True} for i in range(6)} | {"broken": {"all_checks_passed": False}}


def test_stage1_probes_all_stage0_compatible_models_regardless_of_size_or_recency():
    compat = gf.stage0_compatible(COMPAT)
    assert compat == [f"m{i}" for i in range(6)]
    assert gf.stage1_pool(compat) == compat
    huge = {m: {**r, "parameter_count": 10 ** (i + 8), "release_date": f"20{20 + i}-01-01", "popularity": i} for i, (m, r) in enumerate(COMPAT.items())}
    assert gf.stage0_compatible(huge) == compat            # size / date / popularity fields are never read


def test_stage1_cost_is_an_explicit_cap_not_a_size_preference():
    assert gf.stage1_cap_usd(15) == round(15 * 0.25 * 3.95, 2) == 14.81
    assert gf.stage1_cap_usd(0) == 0
    assert gf.STAGE1_MAX_GPU_HOURS_PER_MODEL == 0.25


def test_stage1_drops_only_models_confidently_below_a_frozen_floor():
    floors = {"reasoning": 0.5, "coding": 0.4, "strict_contracts": 0.9}
    res = {"clear": {"reasoning": {"upper95": 0.9}, "coding": {"upper95": 0.8}},
           "confidently_below": {"reasoning": {"upper95": 0.3}, "coding": {"upper95": 0.8}},
           "uncertain": {"reasoning": {"upper95": 0.55}, "coding": {"upper95": 0.5}},
           "low_power_low": {"reasoning": {"upper95": 0.1, "low_power": True}, "coding": {"upper95": 0.8}},
           "strict_contracts_terrible": {"reasoning": {"upper95": 0.9}, "coding": {"upper95": 0.8}, "strict_contracts": {"upper95": 0.0}}}
    assert gf.stage1_survivors(res, floors) == ["clear", "low_power_low", "strict_contracts_terrible", "uncertain"]


def test_stage2_admits_all_when_under_cap_and_applies_a_transparent_cost_gate_otherwise():
    s = {"a": {"cost_usd": 5, "family": "F1"}, "b": {"cost_usd": 9, "family": "F1"}, "c": {"cost_usd": 20, "family": "F2"},
         "d": {"cost_usd": 3, "family": "F3"}}
    assert gf.stage2_entrants(s, cap_usd=100) == {"entrants": ["a", "b", "c", "d"], "cost_cap_applied": False, "deferred_for_cost": []}
    over = gf.stage2_entrants(s, cap_usd=30)
    assert over["cost_cap_applied"] is True and set(over["entrants"]) >= {"a", "d", "c"}     # one per family first
    assert "b" in over["deferred_for_cost"] and sum(s[m]["cost_usd"] for m in over["entrants"]) <= 30


FIN = {"x": {"capability": {"reasoning": 0.8, "coding": 0.7, "verification": 0.7, "evidence_use": 0.7}, "cost_usd": 4, "family": "A"},
       "y": {"capability": {"reasoning": 0.6, "coding": 0.9, "verification": 0.8, "evidence_use": 0.6}, "cost_usd": 6, "family": "B"},
       "z": {"capability": {"reasoning": 0.5, "coding": 0.5, "verification": 0.5, "evidence_use": 0.5}, "cost_usd": 9, "family": "C"},   # dominated
       "w": {"capability": {"reasoning": 0.7, "coding": 0.8, "verification": 0.75, "evidence_use": 0.65}, "cost_usd": 5, "family": "A"},
       "v": {"capability": {"reasoning": 0.65, "coding": 0.95, "verification": 0.6, "evidence_use": 0.9}, "cost_usd": 7, "family": "D"}}


def test_stage3_entrants_come_from_pre_trainability_information_only():
    base = gf.stage3_entrants(FIN)
    assert "z" not in base and len(base) <= gf.STAGE3_MAX_FINALISTS
    with_t = {m: {**r, "trainability": 0.99 if m == "z" else 0.0} for m, r in FIN.items()}
    reversed_t = {m: {**r, "trainability": 0.0 if m == "z" else 0.99} for m, r in FIN.items()}
    assert gf.stage3_entrants(with_t) == base == gf.stage3_entrants(reversed_t)      # a trainability value is ignored by construction
    capability_with_t = {m: {**r, "capability": {**r["capability"], "trainability": 1.0 if m == "z" else 0.0}} for m, r in FIN.items()}
    assert gf.stage3_entrants(capability_with_t) == base
    assert gf.stage3_entrants(capability_with_t, max_n=10) == gf.stage3_entrants(FIN, max_n=10)   # z stays dominated even with room for all
    assert "z" not in gf.stage3_entrants(capability_with_t, max_n=10)


def test_stage3_entry_ignores_size_date_and_popularity():
    noisy = {m: {**r, "parameter_count": 10 ** (9 + i), "release_date": f"2026-0{i + 1}-01", "popularity": 100 - i} for i, (m, r) in enumerate(FIN.items())}
    flipped = {m: {**r, "parameter_count": 10 ** (13 - i), "release_date": f"2020-0{i + 1}-01", "popularity": i} for i, (m, r) in enumerate(FIN.items())}
    assert gf.stage3_entrants(noisy) == gf.stage3_entrants(flipped) == gf.stage3_entrants(FIN)


def test_stage3_prefers_architecture_diversity_before_filling_by_cost():
    order = gf.stage3_entrants(FIN)
    fams = [FIN[m]["family"] for m in order]
    assert len(set(fams)) == len(fams) or len(fams) > len({FIN[m]["family"] for m in gf.pareto_nondominated(FIN)})
    assert order == sorted(order, key=lambda m: (FIN[m]["cost_usd"], m)) or len(set(fams)) == len(fams)


def test_no_foundation_may_be_selected_until_all_finalists_complete_the_same_pilot():
    fin = ["x", "y", "v"]
    ok = {m: {"status": "COMPLETE", "protocol_id": gf.PILOT_PROTOCOL_ID, "trainability_score": 0.5} for m in fin}
    assert gf.selection_allowed(fin, ok)
    assert not gf.selection_allowed(fin, {**ok, "v": {"status": "RUNNING", "protocol_id": gf.PILOT_PROTOCOL_ID}})
    assert not gf.selection_allowed(fin, {**ok, "v": {"status": "COMPLETE", "protocol_id": "a-different-pilot"}})
    assert not gf.selection_allowed(fin, {m: p for m, p in ok.items() if m != "y"})
    assert not gf.selection_allowed([], ok)
    results = {m: FIN[m] for m in fin}
    partial = gf.rank_finalists(results, {"x": ok["x"]}, floors={"reasoning": 0.4})
    assert partial["status"] == "NO_SELECTION_YET" and partial["ranking"] == []


def test_ranking_uses_verification_evidence_trainability_cost_and_ignores_strict_contracts_size_and_dates():
    fin = ["x", "y", "v"]
    pilots = {m: {"status": "COMPLETE", "protocol_id": gf.PILOT_PROTOCOL_ID, "trainability_score": t} for m, t in zip(fin, (0.5, 0.5, 0.5))}
    base = gf.rank_finalists({m: FIN[m] for m in fin}, pilots, floors={"reasoning": 0.4})
    assert base["status"] == "RANKED" and base["ranking"][0] == "y"                           # highest verification
    noisy = {m: {**FIN[m], "capability": {**FIN[m]["capability"], "strict_contracts": (i * 0.4) % 1},
                 "parameter_count": 10 ** (9 + i), "release_date": f"2026-0{i + 1}-01"} for i, m in enumerate(fin)}
    assert gf.rank_finalists(noisy, pilots, floors={"reasoning": 0.4}) == base                # strict_contracts / size / date are not read
    tie_break = {m: {**p, "trainability_score": 0.9 if m == "x" else 0.1} for m, p in pilots.items()}
    assert gf.rank_finalists({m: FIN[m] for m in fin}, tie_break, floors={"reasoning": 0.4})["ranking"][0] == "y"   # verification outranks trainability
    assert gf.RANKING_ORDER == ("verification", "evidence_use", "trainability", "cost") and "strict_contracts" not in gf.RANKING_ORDER
    assert "strict_contracts" in gf.REPORT_ONLY_CATEGORIES


def test_ties_go_to_the_owner():
    same = {m: {"capability": {"verification": 0.7, "evidence_use": 0.7, "reasoning": 0.7}, "cost_usd": 5, "family": m} for m in ("p", "q")}
    pilots = {m: {"status": "COMPLETE", "protocol_id": gf.PILOT_PROTOCOL_ID, "trainability_score": 0.5} for m in same}
    out = gf.rank_finalists(same, pilots, floors={"reasoning": 0.5})
    assert out["status"] == "OWNER_DECISION_REQUIRED_TIE" and out["tied_for_first"] == ["p", "q"]
    assert gf.rank_finalists(same, pilots, floors={"reasoning": 0.9})["status"] == "NO_MODEL_QUALIFIES"


def test_funnel_module_never_reads_forbidden_selection_inputs():
    src = (ROOT / "orca/eval/genesis_funnel.py").read_text()
    for word in ("parameter_count", "release_date", "popularity", "model_size_proxy", "vendor_benchmark_claims"):
        assert not re.search(rf"(\[|\.get\(|\bin\b)\s*[\"']{word}[\"']", src), word     # never indexed, fetched or tested
        assert word in src                                                                   # but is named as forbidden
    assert set(gf.FORBIDDEN_SELECTION_INPUTS) == {"release_date", "parameter_count", "popularity", "vendor_benchmark_claims", "model_size_proxy"}


def test_eval_design_document_matches_the_corrected_funnel():
    t = EVAL_MD.read_text()
    low = t.lower()
    assert "nearest" not in low and "lean" not in t and "floor margin" not in low
    assert "report-only recovery-cost signal; never a floor and never a ranking input" in t
    assert "PRE-TRAINABILITY" in t and "same trainability pilot" in t and "NO_SELECTION_YET" in t
    assert "ALL" in t and "no pre-selection of any kind" in t
    for cap in ("0.25 GPU-hours", "USD 14.81", "USD 40", "USD 25", "USD 79.81", gf.PILOT_PROTOCOL_ID):
        assert cap in t, cap
    assert "Release date, parameter count and popularity are never inputs" in t
    assert "trainability" in t and "Stage-3 finalists only" in t
    assert "cannot be selected" in t


def test_funnel_spec_is_embedded_in_the_architecture_json_and_consistent():
    j = json.loads(ARCH_JSON.read_text())["genesis_capability_eval_v1"]
    assert j == json.loads(json.dumps(gf.funnel_spec()))
    assert j["selection_precondition"] == "every finalist completed the SAME trainability pilot"
    assert j["stages"][1]["who"] == "ALL Stage-0-compatible models" and j["stages"][3]["entry_order"].startswith("Pareto-non-dominated")
    assert "strict_contracts" not in j["ranking_order"] and "strict_contracts" in j["report_only_categories"]
    assert j["cost_planning_usd"]["kind"] == "PLANNING_ONLY_NOT_AUTHORIZATION"


def test_selection_rule_in_landscape_matches_the_funnel(refresh=None):
    from orca.eval import foundation_landscape as fl
    r = fl.SELECTION_RULE
    assert "same trainability pilot" in r and "report-only recovery-cost" in r and "verification, then evidence_use, then trainability, then cost" in r
    assert "Release date, parameter count and popularity are never inputs" in r


# =============================================================== 7. freeze readiness
def test_freeze_flags_are_computed_true_only_when_checks_pass_and_never_frozen():
    fr = FR.freeze_readiness(ROOT)
    for k in ("ETERNAL_ARCHITECTURE_V1_FREEZE_READY", "CORE_INTELLIGENCE_PROTOCOL_V1_FREEZE_READY", "GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY"):
        assert fr[k] is True, (k, {a: [n for n, v in c.items() if not v] for a, c in fr["checks"].items()})
    assert fr["frozen"] is False and "exact-SHA CI green" in fr["freeze_requires_beyond_ready"]
    assert all(all(v.values()) for v in fr["checks"].values()) and sum(len(v) for v in fr["checks"].values()) >= 30


def test_freeze_status_is_recorded_in_json_and_docs_and_agrees_with_computation():
    fr = FR.freeze_readiness(ROOT)
    j = json.loads(ARCH_JSON.read_text())["freeze_status"]
    assert j == json.loads(json.dumps(fr))
    for doc, key in ((ARCH_MD, "ETERNAL_ARCHITECTURE_V1_FREEZE_READY"), (ARCH_MD, "CORE_INTELLIGENCE_PROTOCOL_V1_FREEZE_READY"),
                     (EVAL_MD, "GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY")):
        m = re.search(rf"^{key} = (true|false)$", doc.read_text(), re.M)
        assert m and (m.group(1) == "true") is fr[key], (doc.name, key)
    assert re.search(r"^frozen = false$", ARCH_MD.read_text(), re.M)


def _tree(tmp_path) -> Path:
    for rel in ("docs/orneur/intelligence", "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V1_DESIGN.md", "orca/intelligence/protocol.py"):
        src, dst = ROOT / rel, tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst) if src.is_dir() else shutil.copy(src, dst)
    return tmp_path


def test_a_regression_flips_the_relevant_freeze_flag_to_false(tmp_path):
    root = _tree(tmp_path)
    assert FR.freeze_readiness(root)["GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY"] is True
    ev = root / FR.EVAL
    ev.write_text(ev.read_text() + "\nStage 1 takes the model nearest 9B per family.\n")
    assert FR.freeze_readiness(root)["GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY"] is False
    shutil.copy(ROOT / FR.EVAL, ev)
    ev.write_text(ev.read_text().replace("report-only recovery-cost signal", "floor margin signal"))
    assert FR.freeze_readiness(root)["GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY"] is False
    shutil.copy(ROOT / FR.EVAL, ev)
    pr = root / "orca/intelligence/protocol.py"
    pr.write_text(pr.read_text() + "\n# uses qwen internally\n")
    assert FR.freeze_readiness(root)["CORE_INTELLIGENCE_PROTOCOL_V1_FREEZE_READY"] is False
    shutil.copy(ROOT / "orca/intelligence/protocol.py", pr)
    arch = root / FR.ARCH
    arch.write_text(arch.read_text().replace("Transport-level retraction is **not** claimed", "Retraction is fine"))
    assert FR.freeze_readiness(root)["ETERNAL_ARCHITECTURE_V1_FREEZE_READY"] is False


def test_versions_were_bumped_before_freeze_for_the_breaking_protocol_change():
    assert P.PROTOCOL_VERSION == "orneur.core-protocol/1.1.0" and S.ARCHITECTURE_VERSION == "orneur.eternal-architecture/1.1.0"
    t = ARCH_MD.read_text()
    assert "breaking change relative to `orneur.core-protocol/1.0.0`" in t and "before any freeze" in t
    assert json.loads(ARCH_JSON.read_text())["protocol_version"] == P.PROTOCOL_VERSION


def test_doctrine_and_audited_corrections_are_still_present():
    t = ARCH_MD.read_text()
    for w in ("Models are replaceable organs", "Nothing is sacred merely because ORNEUR previously built it", "not tied to 14B, 70B, 500B",
              "Transport-level retraction is **not** claimed", "decider_qualification_ref"):
        assert w in t, w
    assert "parent_digest must be a lowercase sha256" in (P.__doc__ or "") or "lowercase sha256" in (ROOT / "orca/intelligence/protocol.py").read_text()
