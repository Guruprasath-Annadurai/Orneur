"""Computed freeze-readiness for the pre-freeze pass.

``READY`` means "every structural and behavioural check below passed on this tree". It does NOT mean frozen:
freezing additionally requires exact-SHA CI and an independent audit, neither of which a file can attest.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from orca.eval import genesis_funnel as gf
from orca.intelligence import protocol as P

ARCH = "docs/orneur/intelligence/ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.md"
EVAL = "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V1_DESIGN.md"
INTEL_DOCS = ["ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.md", "ORNEUR_DISCOVERY_INTELLIGENCE.md",
              "ORNEUR_SELF_EVOLVING_EXPERT_MESH.md", "ORNEUR_ARCHITECTURE_MIGRATION_PROTOCOL.md"]
T = "2026-09-26T00:00:00Z"
FAMILY_NAMES = ("qwen", "mistral", "phi-", "llama", "gemma", "deepseek", "gpt", "claude", "gemini", "transformer")


def _selftest_protocol() -> dict[str, bool]:
    led = P.ProvenanceLedger()
    dg = P.content_digest
    out_text = "5"
    od = dg(out_text)

    def prov(kind, **kw):
        base = dict(component_id=kw.pop("component_id", f"{kind.lower()}-1"), component_kind=kind, execution_ref="exec-1",
                    authority_evidence_ref=kw.pop("authority_evidence_ref", "ev"), input_digest=dg("in"), output_digest=od)
        base.update(kw)
        return led.issue(**base)

    def det(**kw):
        b = dict(request_id="r", status="COMPLETED", output_ref="out", evidence_refs=(), verifications=(), confidence=1.0,
                 output_kind=P.OutputKind.DETERMINISTIC_MATH, output_digest=od, presented_as="DETERMINISTIC_OUTPUT",
                 contract_type="DETERMINISTIC_MATH", contract_status="SATISFIED", contract_evidence_ref="ce",
                 contract_output_digest=od, model_calls=0,
                 classification_provenance=prov("ROUTER", output_digest=P.classification_digest(P.OutputKind.DETERMINISTIC_MATH)),
                 deterministic_provenance=prov("DETERMINISTIC_AUTHORITY", authority_evidence_ref="ce"))
        b.update(kw)
        return P.CognitiveResult(**b)

    def epi(vs, **kw):
        b = dict(request_id="r", status="COMPLETED", output_ref="out", evidence_refs=("e",), verifications=vs, confidence=0.8,
                 output_kind=P.OutputKind.GENERATED_EPISTEMIC, output_digest=od, presented_as="VERIFIED_CLAIMS",
                 classification_provenance=prov("ROUTER", output_digest=P.classification_digest(P.OutputKind.GENERATED_EPISTEMIC)))
        b.update(kw)
        return P.CognitiveResult(**b)

    def ver(**kw):
        b = dict(verification_id="v", subject_ref="out", method="TOOL", verdict="PASSED", evidence_refs=("e",),
                 verifier_id="verifier-1", producer_id="producer", subject_digest=od,
                 provenance=prov("VERIFIER", component_id="verifier-1", input_digest=od))
        b.update(kw)
        return P.VerificationResult(**b)

    forged = P.RuntimeProvenance("x", "router", "ROUTER", "e", "a", dg("i"), dg("o"), "0" * 64)
    other = P.ProvenanceLedger()
    creative = P.CognitiveResult("r", "COMPLETED", "out", (), (), 0.5, P.OutputKind.GENERATED_CREATIVE, od, "FICTION_OR_IDEATION",
                                 classification_provenance=prov("ROUTER", output_digest=P.classification_digest(P.OutputKind.GENERATED_CREATIVE)),
                                 screening_provenance=prov("EPISTEMIC_SCREENER"))
    return {
        "deterministic_bypass_valid": det().problems(led) == [],
        "deterministic_without_ledger_fails_closed": bool(det().problems()),
        "forged_router_provenance_rejected": bool(det(classification_provenance=forged).problems(led)),
        "foreign_ledger_rejected": bool(det().problems(other)),
        "deterministic_with_model_calls_rejected": bool(det(model_calls=1).problems(led)),
        "epistemic_without_verification_rejected": bool(epi(()).problems(led)),
        "epistemic_with_bound_verification_valid": epi((ver(),)).problems(led) == [],
        "digest_mismatch_rejected": bool(epi((ver(subject_digest=dg("older")),)).problems(led)),
        "ref_mismatch_rejected": bool(epi((ver(subject_ref="other"),)).problems(led)),
        "self_asserted_verifier_rejected": bool(epi((ver(provenance=forged),)).problems(led)),
        "creative_valid_without_factual_verification": creative.problems(led) == [],
        "creative_cannot_be_presented_as_verified": bool(P.CognitiveResult(**{**creative.__dict__, "presented_as": "VERIFIED_CLAIMS"}).problems(led)),
        "privileged_fields_stripped_from_untrusted_payload": P.strip_privileged({"output_kind": "X", "a": {"seal": "s"}})[1] == ["a.seal", "output_kind"],
    }


def _selftest_promotion_and_discovery() -> dict[str, bool]:
    base = dict(decision_id="d", candidate_id="c", candidate_produced_by="learner", decided_by="gate",
                decider_kind="QUALIFIED_GATE_SERVICE", verdict=P.PromotionVerdict.PROMOTE, decider_qualification_ref="q",
                frozen_eval_ref="f", adversarial_eval_ref="a", regression_eval_ref="r", shadow_deployment_ref="s",
                measured_improvement=0.1, regressions_found=0)
    return {"promotion_valid": P.PromotionDecision(**base).problems() == [],
            "self_promotion_rejected": bool(P.PromotionDecision(**{**base, "decided_by": "learner"}).problems()),
            "unqualified_service_rejected": bool(P.PromotionDecision(**{**base, "decider_qualification_ref": None}).problems())}


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text()


def _checks(root: Path) -> dict[str, dict[str, Callable[[], bool]]]:
    from orca.intelligence import spec as S
    arch, ev = _read(root, ARCH), _read(root, EVAL)
    arch_l = arch.lower()
    spec_pipeline = [p[0] for p in S.PIPELINE]
    eternal = {
        "pipeline_has_21_ordered_stages": lambda: len(spec_pipeline) == 21 and spec_pipeline[0] == "user" and spec_pipeline[-1] == "architecture_migration",
        "all_intelligence_docs_present": lambda: all((root / "docs/orneur/intelligence" / d).stat().st_size > 1500 for d in INTEL_DOCS),
        "doctrine_present": lambda: all(w in arch for w in ("Models are replaceable organs", "Nothing is sacred merely because ORNEUR previously built it",
                                                          "not tied to 14B, 70B, 500B or any other size")),
        "streaming_has_no_transport_retraction": lambda: "Transport-level retraction is **not** claimed" in arch and "visible correction event" in arch,
        "epistemic_and_provenance_sections_present": lambda: all(w in (arch_l if w == "epistemic" else arch) for w in ("epistemic", "output_digest", "RuntimeProvenance", "ClaimBinding")),
        "authorizations_all_false": lambda: S.build_spec_core()["authorizations"] == {"training": False, "gpu": False, "provider_inference": False, "phase_21c": False, "foundation_selected": False},
        "no_overclaims": lambda: not re.search(r"achieves? agi|is (self-aware|conscious|sentient)|better than (gpt|claude|gemini)", arch.lower()),
        "versions_are_semver": lambda: bool(re.fullmatch(r"orneur\.eternal-architecture/\d+\.\d+\.\d+", S.ARCHITECTURE_VERSION)),
    }
    proto = {name: (lambda v=v: v) for name, v in {**_selftest_protocol(), **_selftest_promotion_and_discovery()}.items()}
    proto.update({
        "all_17_interfaces_defined": lambda: all(hasattr(P, n) for n in S.INTERFACES) and len(S.INTERFACES) == 17,
        "protocol_names_no_model_family": lambda: not any(n in (root / "orca/intelligence/protocol.py").read_text().lower() for n in FAMILY_NAMES),
        "protocol_version_semver": lambda: bool(re.fullmatch(r"orneur\.core-protocol/\d+\.\d+\.\d+", P.PROTOCOL_VERSION)),
        "claim_binding_and_digest_fields_exist": lambda: all(hasattr(P, n) for n in ("ClaimBinding", "RuntimeProvenance", "ProvenanceLedger", "content_digest")),
    })
    fun = gf.funnel_spec()
    evaln = {
        "eval_doc_uses_all_stage_caps": lambda: all(str(x) in ev for x in (gf.STAGE1_MAX_GPU_HOURS_PER_MODEL, int(gf.STAGE2_COST_CAP_USD), int(gf.STAGE3_COST_CAP_USD), gf.STAGE3_MAX_FINALISTS)),
        "no_parameter_count_preselection": lambda: "nearest" not in ev.lower() and "LEAN" not in ev,
        "strict_contracts_report_only_no_floor_margin": lambda: "floor margin" not in ev and "report-only recovery-cost signal" in ev,
        "stage3_entry_is_pre_trainability": lambda: "PRE-TRAINABILITY" in ev and "same trainability pilot" in ev,
        "selection_inputs_forbidden": lambda: all(w in ev for w in ("release date", "parameter count", "popularity")),
        "funnel_ranking_excludes_strict_contracts": lambda: "strict_contracts" not in fun["ranking_order"],
        "eval_categories_21": lambda: len(S.CAPABILITY_EVAL_CATEGORIES) == 21 and all(f"`{c}`" in ev for c in S.CAPABILITY_EVAL_CATEGORIES),
        "eval_design_only_no_authorization": lambda: "gpu_authorized=false" in ev and "design only" in ev.lower(),
    }
    return {"ETERNAL_ARCHITECTURE_V1": eternal, "CORE_INTELLIGENCE_PROTOCOL_V1": proto, "GENESIS_CAPABILITY_EVAL_V1": evaln}


def freeze_readiness(root: Path) -> dict:
    res: dict = {"checks": {}}
    for area, checks in _checks(root).items():
        detail = {}
        for name, fn in checks.items():
            try:
                detail[name] = bool(fn())
            except Exception:  # a crashing check is a failed check, never a pass
                detail[name] = False
        res["checks"][area] = detail
    res["ETERNAL_ARCHITECTURE_V1_FREEZE_READY"] = all(res["checks"]["ETERNAL_ARCHITECTURE_V1"].values())
    res["CORE_INTELLIGENCE_PROTOCOL_V1_FREEZE_READY"] = all(res["checks"]["CORE_INTELLIGENCE_PROTOCOL_V1"].values())
    res["GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY"] = all(res["checks"]["GENESIS_CAPABILITY_EVAL_V1"].values())
    res["frozen"] = False
    res["freeze_requires_beyond_ready"] = ["exact-SHA CI green", "independent audit approval"]
    res["ready_semantics"] = "all computed checks passed on this tree; READY is not FROZEN"
    return res
