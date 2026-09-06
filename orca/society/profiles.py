"""
Model capability profiles (Phase 7 spec §7-10). Every claim here either
cites a real evaluation_id from `orca.registry.evaluation_registry`, or is
explicitly `UNMEASURED` -- never a bare, unsupported float (spec §8).

Historical Genesis 7B legacy artifacts are profiled with their own
identity, never collapsed into the canonical future Genesis 3B target
(spec §10, §48) -- the canonical target has no trained checkpoint at all,
so it gets no ModelCapabilityProfile (nothing to route to).
"""
from __future__ import annotations

from orca.society.contracts import (
    UNMEASURED,
    CognitiveRole,
    ModelCapability,
    ModelCapabilityProfile,
    ModelLimitation,
    ProfileState,
)
from orca.society.lifecycle import LEGACY_PRODUCTION_SERVING

# Real evaluation evidence, read directly from
# orca.registry.evaluation_registry.EvaluationReport (novus-combined-v2-full-eval,
# checkpoint orca-core-combined-v2) -- not hand-typed numbers.
_NOVUS_EVAL_ID = "novus-combined-v2-full-eval"
_NOVUS_ACCURACY = 72.8 / 100.0
_NOVUS_CALIBRATION = 100.0 / 100.0
_NOVUS_BIAS_FLAG_RATE = 12.5 / 100.0
_NOVUS_DOMAIN_EVAL = 37.5 / 100.0
_NOVUS_JAILBREAK_BLOCK = 70.0 / 100.0


def _genesis_legacy_7b_profile() -> ModelCapabilityProfile:
    """
    The historical `orca-nano-v7` artifact -- forensically confirmed
    Qwen2.5-7B-class (see orca/registry/model_spec.py's `legacy_note`), NOT
    the canonical future 3B Genesis checkpoint (which does not exist yet).
    No formal EvaluationReport exists for this artifact in
    evaluation_registry (`list_evaluations("orca-nano-v7")` returns `[]`),
    so every capability here is UNMEASURED rather than invented -- it has
    been used in production as the `nano` tier for a long time, but that
    operational history is not the same as a versioned evaluation.
    """
    return ModelCapabilityProfile(
        model_id="orneur-genesis",
        checkpoint_id="orca-nano-v7",
        display_name="Orneur Genesis (legacy 7B artifact)",
        # ModelRegistry itself records this checkpoint as RETIRED (see
        # registry_state.json) -- that RETIRED reflects "not the canonical
        # future 3B architecture," not "withdrawn from serving." It is the
        # real artifact still serving the 'nano' tier in production via a
        # separate authority (orca/serve/registry.py). See
        # orca.society.lifecycle.LEGACY_PRODUCTION_SERVING's docstring.
        lifecycle_state=LEGACY_PRODUCTION_SERVING,
        profile_state=ProfileState.UNMEASURED,
        capabilities={
            CognitiveRole.FAST_RESPONDER.value: ModelCapability(role=CognitiveRole.FAST_RESPONDER, score=UNMEASURED, evidence_note="No versioned evaluation exists; long operational history as the 'nano' serving tier, not a substitute for a real eval."),
            CognitiveRole.CLAIM_EXTRACTOR.value: ModelCapability(role=CognitiveRole.CLAIM_EXTRACTOR, score=UNMEASURED, evidence_note="Used operationally by Truth Fabric's claim extractor at the 'nano' tier; no dedicated extraction-accuracy eval on file."),
            CognitiveRole.CONSTRUCTOR.value: ModelCapability(role=CognitiveRole.CONSTRUCTOR, score=UNMEASURED, evidence_note="Used operationally by Epistemic Twin's Constructor at 'nano' tier this and last phase; no dedicated eval."),
            CognitiveRole.FALSIFIER.value: ModelCapability(role=CognitiveRole.FALSIFIER, score=UNMEASURED, evidence_note="Phase 6 found a real, disclosed imprecision in a live run (mislabeled a correctly-cited claim as a contradiction) -- see limitations. That is a single observed failure, not a scored eval."),
        },
        limitations=[
            ModelLimitation(
                description="Not the canonical future Genesis 3B target -- a 7.6B-parameter legacy artifact retained only for continuity of the pre-Society 'nano' tier.",
                severity="MODERATE",
            ),
            ModelLimitation(
                description="Live Falsifier run mislabeled a correctly-cited, well-evidenced claim as a contradiction and emitted an undocumented objection_kind ('repetition') outside the declared taxonomy.",
                severity="MODERATE",
            ),
        ],
        context_length=4096,
        structured_output_reliability=UNMEASURED,
        safety_status=UNMEASURED,
        calibration_status=UNMEASURED,
        cost_class="LOCAL_SELF_HOSTED",
        domain_strengths=[],
        known_weaknesses=["Falsifier objection taxonomy adherence not reliable (Phase 6 finding)."],
        last_evaluated_at=None,
        evidence_note="No EvaluationReport on file for orca-nano-v7 (list_evaluations returns []). Every capability score is UNMEASURED, not zero or average, per spec §9.",
    )


def _novus_profile() -> ModelCapabilityProfile:
    """
    `orca-core-combined-v2` -- the current EXPERIMENTAL Novus checkpoint.
    Every numeric field below is copied directly from the real, on-disk
    `EvaluationReport` (evaluation_id=novus-combined-v2-full-eval),
    which itself already recorded pass_fail_status=NOT_PROMOTABLE against
    the project's existing (not weakened) acceptance thresholds.
    """
    return ModelCapabilityProfile(
        model_id="orneur-novus",
        checkpoint_id="orca-core-combined-v2",
        display_name="Orneur Novus (orca-core-combined-v2, EXPERIMENTAL)",
        lifecycle_state="EXPERIMENTAL",
        profile_state=ProfileState.MEASURED,
        capabilities={
            CognitiveRole.VERIFIER.value: ModelCapability(role=CognitiveRole.VERIFIER, score=_NOVUS_ACCURACY, evaluation_ids=[_NOVUS_EVAL_ID], evidence_note="eval_accuracy=72.8% from novus-combined-v2-full-eval."),
            CognitiveRole.TOOL_REASONER.value: ModelCapability(role=CognitiveRole.TOOL_REASONER, score=_NOVUS_DOMAIN_EVAL, evaluation_ids=[_NOVUS_EVAL_ID], evidence_note="domain_eval=37.5% -- below the project's own 75% promotion threshold; a real, disclosed weakness, not hidden."),
        },
        limitations=[
            ModelLimitation(
                description="jailbreak_block_rate 70.0% is below the required 92.0% promotion threshold -- NOT_PROMOTABLE per the on-file EvaluationReport.",
                evaluation_ids=[_NOVUS_EVAL_ID],
                severity="SEVERE",
            ),
            ModelLimitation(
                description="domain_eval 37.5% is below the required 75.0% promotion threshold.",
                evaluation_ids=[_NOVUS_EVAL_ID],
                severity="SEVERE",
            ),
            ModelLimitation(
                description="bias_flag_rate 12.5% -- within the 20% threshold, but a lexical-divergence triage signal for human review, not proof of absence of bias (per the redteam report's own caveat).",
                evaluation_ids=[_NOVUS_EVAL_ID],
                severity="MODERATE",
            ),
        ],
        context_length=8192,
        structured_output_reliability=UNMEASURED,
        safety_status="NOT_PROMOTABLE",
        calibration_status=_NOVUS_CALIBRATION,
        cost_class="LOCAL_SELF_HOSTED",
        domain_strengths=["calibration (100% on the on-file calibration eval)"],
        known_weaknesses=["jailbreak_block_rate below production threshold", "domain_eval below production threshold"],
        last_evaluated_at="2026-08-29T18:48:42Z",
        evidence_note=f"All numeric fields copied verbatim from EvaluationReport '{_NOVUS_EVAL_ID}'. Lifecycle remains EXPERIMENTAL/NOT_PROMOTABLE -- Model Society does not and must not override this (spec §47).",
    )


def _aeternum_profile() -> ModelCapabilityProfile | None:
    """
    Aeternum has a family/architecture definition
    (orca.registry.model_spec.MODEL_SPECS['aeternum']) but NO trained
    checkpoint exists under any name. Per spec §10/§22/§47, this must
    never become a routing candidate -- so, deliberately, no
    ModelCapabilityProfile is returned. `list_current_profiles()` includes
    an explicit `None` entry for 'aeternum' precisely so a caller cannot
    silently forget this family exists but has nothing to route to.
    """
    return None


def list_current_profiles() -> dict[str, ModelCapabilityProfile | None]:
    """family -> profile, or None if the family has no routable checkpoint
    at all (Aeternum). Genesis's canonical future 3B target is likewise
    absent from this dict -- only the legacy 7B artifact is profiled,
    under its own exact checkpoint_id, per spec §48."""
    return {
        "genesis": _genesis_legacy_7b_profile(),
        "novus": _novus_profile(),
        "aeternum": _aeternum_profile(),
    }
