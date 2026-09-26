"""Single source of truth for ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE.json.

``build_spec()`` is deterministic; a test asserts the committed JSON equals it.
The architecture is a ROADMAP and a set of contracts, not a capability claim.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from orca.eval import genesis_funnel as _funnel
from orca.intelligence.protocol import PROTOCOL_VERSION

ARCHITECTURE_VERSION = "orneur.eternal-architecture/1.1.0"

PIPELINE = [
    ("user", "User", "CognitiveRequest"),
    ("objective_graph", "Persistent Objective Graph", "Objective"),
    ("reality_compiler", "Reality Compiler", "CompiledReality (canonical IR)"),
    ("living_world_model", "Living World Model", "WorldState"),
    ("world_delta_engine", "World Delta Engine", "WorldDelta"),
    ("discovery_intelligence", "Discovery Intelligence", "Discovery"),
    ("hypothesis_laboratory", "Hypothesis Laboratory", "Hypothesis"),
    ("expert_mesh", "Self-Evolving Expert Mesh", "ExpertCapability/ExpertRequest/ExpertResult"),
    ("adaptive_compute", "Adaptive Compute Engine", "ComputeBudget"),
    ("compute_modes", "Fast / Reason / Frontier / future modes", "CognitiveRequest.mode"),
    ("verification_engine", "Verification Engine", "VerificationResult"),
    ("evidence_graph", "Evidence Graph", "EvidenceReference"),
    ("confidence_calibration", "Confidence Calibration", "CognitiveResult.confidence"),
    ("authority_runtime", "Authority Runtime", "authority decision (existing ORNEUR runtime)"),
    ("contract_compliance", "Contract Compliance", "orca.contracts (SYSTEM_CONTRACT_QUALIFIED)"),
    ("action", "Action", "CognitiveResult"),
    ("outcome_capture", "Outcome Capture", "Outcome"),
    ("failure_genome", "Failure Genome", "FailureGenomeEntry"),
    ("learning_pipeline", "Learning Pipeline", "candidate data / expert / strategy"),
    ("qualification_promotion", "Qualification / Promotion", "PromotionDecision"),
    ("architecture_migration", "Architecture Migration Engine", "ArchitectureMigrationManifest"),
]

PERMANENT = [
    "ORNEUR Core Intelligence Protocol", "persistent objectives", "Reality Compiler",
    "Living World Model", "World Delta", "Discovery Intelligence", "hypothesis/falsification system",
    "Outcome Learning", "Failure Genome", "Self-Evolving Expert Mesh", "evaluation suites",
    "qualified cognitive strategies", "Verification + Evidence", "Authority Runtime",
    "Contract Compliance", "memory / knowledge state", "architecture migration machinery",
]

REPLACEABLE = [
    "any neural architecture (Transformers, MoE, state-space, hybrid, future)",
    "retrieval mechanisms (RAG included)", "tokenizers", "checkpoint families",
    "parameter-count targets", "individual experts and adapters", "serving stacks",
    "training recipes", "quantization formats",
]

MODES = {
    "FAST": {
        "definition": "minimum compute necessary for a reliable response",
        "properties": ["extremely low first-token latency", "deterministic/tool path where possible",
                       "lightweight expert activation", "everyday multimodal intelligence",
                       "normal conversational use"],
    },
    "REASON": {
        "definition": "adaptive deeper compute with an adjustable reasoning budget",
        "properties": ["multiple experts when useful", "coding", "mathematics", "science", "research",
                       "planning", "tool orchestration", "stronger verification"],
    },
    "FRONTIER": {
        "definition": "maximum available ORNEUR intelligence configuration at that generation",
        "properties": ["dynamic expert ensemble", "discovery loops", "hypothesis generation",
                       "adversarial verification", "search / simulation / tools", "highest compute budget"],
    },
}

INTERFACES = [
    "CognitiveRequest", "CognitiveResult", "Objective", "WorldState", "WorldDelta", "Discovery",
    "Hypothesis", "EvidenceReference", "VerificationResult", "ExpertCapability", "ExpertRequest",
    "ExpertResult", "Outcome", "FailureGenomeEntry", "CognitivePrimitive",
    "ArchitectureMigrationManifest", "PromotionDecision",
]

REALITY_COMPILER_INPUTS = ["text", "documents", "email", "calendar", "spreadsheets", "databases", "web",
                           "images", "video", "audio", "code", "tools", "sensors", "agent results"]
REALITY_COMPILER_OBJECTS = ["entities", "relationships", "events", "claims", "evidence", "contradictions",
                            "timelines", "objectives", "constraints", "obligations", "decisions", "risks",
                            "assumptions", "unknowns"]

SELF_IMPROVEMENT_LOOP = [
    "real failure / successful outcome", "Failure Genome", "capability gap", "candidate training data",
    "candidate expert / adapter / strategy", "frozen eval", "adversarial eval", "regression eval",
    "shadow deployment", "promotion decision", "qualified capability",
    "periodic distillation into next ORNEUR generation",
]

CAPABILITY_EVAL_CATEGORIES = [
    "instruction_following", "strict_contracts", "structured_outputs", "reasoning", "coding", "mathematics",
    "research", "tool_use", "long_context", "multilingual", "multimodal_where_applicable", "verification",
    "evidence_use", "counterfactual_reasoning", "hypothesis_testing", "discovery_quality",
    "cross_domain_transfer", "information_gain_reasoning", "latency", "cost", "trainability",
]

DISCOVERY_EVAL_DIMENSIONS = ["novelty", "relevance", "evidence_quality", "counter_evidence_awareness",
                             "actionability", "falsifiability", "importance", "non_obviousness"]

# DESIGN TARGETS ONLY. Nothing here is a measured SLO.
LATENCY_DESIGN_TARGETS = [
    {"path": "strict deterministic contract", "target": "server-side overhead well under one human-perceptible frame", "ms": 50},
    {"path": "FAST model path", "target": "first token", "ms": 300},
    {"path": "REASON", "target": "first visible progress signal", "ms": 1000},
    {"path": "FRONTIER", "target": "acknowledgement plus progressively verified updates", "ms": 1500},
]

NON_CLAIMS = ["AGI", "self-awareness", "consciousness", "autonomous self-evolution", "perfect reasoning",
              "20-year guaranteed survival", "superiority over any named commercial model",
              "frontier capability", "any measured latency SLO", "cross-domain transfer capability today"]


def build_spec_core() -> dict[str, Any]:
    return {
        "document": "ORNEUR_ETERNAL_INTELLIGENCE_ARCHITECTURE",
        "architecture_version": ARCHITECTURE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "status": "ROADMAP_AND_CONTRACTS_NOT_A_CAPABILITY_CLAIM",
        "base_sha": "1eb31d92508a1da227d9457dd0e16ee370217c9a",
        "doctrine": "Models are replaceable organs. ORNEUR itself is permanent.",
        "pipeline": [{"order": i + 1, "id": a, "name": b, "contract": c} for i, (a, b, c) in enumerate(PIPELINE)],
        "pipeline_closes_loop_into": "improved ORNEUR (next qualified generation)",
        "cross_cutting": {"instant_response_fabric": {
            "operates_across_entire_system": True,
            "rules": ["never serialize independent work", "never invoke more intelligence than the request requires",
                      "verification runs beside generation when safe",
                      "trustworthiness must increase without making ORNEUR feel visibly slower"],
            "strict_contracts": "validate before release",
            "free_text": "progressively verified streaming",
            "free_text_release_policy": {
                "non_claim_text": "may stream immediately",
                "claim_bearing_spans": ["HOLD_UNTIL_VERIFIED", "LABEL_PROVISIONAL_BEFORE_EMISSION"],
                "post_emission_recourse": "VISIBLE_CORRECTION_EVENT",
                "transport_retraction_claimed": False,
                "silently_treat_emitted_unverified_text_as_verified": False},
            "parallel_lanes": ["model generation", "memory retrieval", "search", "tool preparation",
                               "evidence construction", "verification", "confidence calculation"],
            "latency_targets_are_design_targets_only": True,
            "measured_slo_claimed": False,
            "design_targets": LATENCY_DESIGN_TARGETS,
        }},
        "permanent_components": PERMANENT,
        "replaceable_components": REPLACEABLE,
        "compute_modes": {
            "defined_by_parameter_count": False,
            "defined_as": "compute/capability expressions realised by whichever implementation is qualified",
            "modes": MODES,
            "future_modes_allowed": True,
            "current_implementation_binding": None,
        },
        "contract_compliance_vs_verification": {
            "contract_compliance_proves": "format/contract correctness only",
            "factual_verification_proves": "content is supported by independent evidence",
            "distinct_concepts": True,
            "verification_bypass_only_for": ["EXACT_TEXT", "DETERMINISTIC_MATH", "JSON_LITERAL"],
            "bypass_requires": ["router-assigned output_kind (trusted provenance)", "SATISFIED contract with evidence",
                                "contract_output_digest == output_digest", "trusted DETERMINISTIC_AUTHORITY provenance", "model_calls == 0"],
            "generated_json_schema_satisfaction_bypasses_verification": False,
            "model_self_report_bypasses_verification": False},
        "output_semantics": {
            "kinds": ["DETERMINISTIC_EXACT_TEXT", "DETERMINISTIC_MATH", "DETERMINISTIC_JSON_LITERAL", "GENERATED_EPISTEMIC",
                      "GENERATED_STRUCTURED_EPISTEMIC", "GENERATED_TRANSFORMATIVE", "GENERATED_CREATIVE"],
            "epistemic_requires": "bound, trusted Verification of the exact output (whole output or every enumerated claim)",
            "transformative_requires_factual_verification": False,
            "transformative_new_claims": "any new factual claim is epistemic for that claim (ClaimBinding + claim-level verification)",
            "creative_requires_factual_verification": False,
            "creative_may_be_presented_as_fact": False,
            "contract_compliance_is_truth_verification": False,
            "fail_closed_for_strict_contracts_weakened": False},
        "content_binding": {"digest": "lowercase sha256 of the exact UTF-8 bytes released (no normalisation)",
                            "fields": ["CognitiveResult.output_digest", "VerificationResult.subject_digest", "ClaimBinding.output_digest",
                                       "ClaimBinding.claim_digest"],
                            "qualifying_verification_requires": ["subject_ref == output_ref", "subject_digest == output_digest",
                                                                 "trusted VERIFIER provenance whose input_digest is the verified digest"],
                            "toctou": "references are opaque names; identity is the digest; the release path must re-hash the bytes it emits"},
        "runtime_provenance": {"contract": "RuntimeProvenance", "fields": ["provenance_id", "component_id", "component_kind", "execution_ref",
                                                                         "authority_evidence_ref", "input_digest", "output_digest", "seal"],
                               "component_kinds": ["ROUTER", "DETERMINISTIC_AUTHORITY", "CLAIM_EXTRACTOR", "EPISTEMIC_SCREENER", "VERIFIER"],
                               "trust_anchor": "ProvenanceLedger (HMAC seal; in-process, not PKI)",
                               "self_asserted_strings_carry_no_authority": True,
                               "untrusted_deserialisation": "privileged fields must be stripped or the payload rejected (strip_privileged)"},
        "claim_level_verification": {"contract": "ClaimBinding", "fields": ["claim_id", "output_ref", "output_digest", "claim_digest",
                                                                             "span_start", "span_end", "canonical_claim"],
                                     "verification_scope": ["WHOLE_OUTPUT", "CLAIM"], "non_claim_prose_needs_no_verification": True,
                                     "stores_hidden_reasoning": False, "verification_engine_implemented": False},
        "genesis_capability_eval_v1": _funnel.funnel_spec(),
        "promotion_authority": {"deciders": ["HUMAN_OWNER", "QUALIFIED_GATE_SERVICE"],
                                "qualified_gate_service_requires": "decider_qualification_ref",
                                "producer_or_candidate_may_promote": False},
        "core_protocol_interfaces": INTERFACES,
        "reality_compiler": {"model_independent": True, "inputs": REALITY_COMPILER_INPUTS,
                             "canonical_objects": REALITY_COMPILER_OBJECTS,
                             "connectors_built_now": False},
        "living_world_model": {"versioned": True, "immutable_versions": True, "delta_explicit": True,
                               "update_rule": "V(n) + WorldDelta -> V(n+1) without full recomputation"},
        "world_delta_propagation": ["World Delta", "dependency graph", "impacted assumptions",
                                    "impacted conclusions", "impacted objectives", "selective re-verification"],
        "self_improvement": {"live_weight_mutation_allowed": False, "self_promotion_allowed": False,
                             "loop": SELF_IMPROVEMENT_LOOP, "every_promotion_evidence_gated": True},
        "outcome_learning": {"distinct_from_preference_feedback": True,
                             "tenant_boundaries_preserved": True},
        "cognitive_primitives": {"stores_raw_reasoning_traces": False, "versioned": True,
                                 "qualification_required": True},
        "architecture_migration": {"first_class_contract": "ArchitectureMigrationManifest",
                                   "no_architecture_is_permanent": True,
                                   "self_obsolescence_rule": "Every major generation must evaluate what is now "
                                                              "unnecessary or inferior; proven-better replacements "
                                                              "retire the old mechanism."},
        "eval_families": {
            "GENESIS_CAPABILITY_EVAL_V1_categories": CAPABILITY_EVAL_CATEGORIES,
            "single_smartness_score": False,
            "ORNEUR_DISCOVERY_EVAL_dimensions": DISCOVERY_EVAL_DIMENSIONS,
            "ORNEUR_SELF_IMPROVEMENT_EVAL": "designed, not executed",
            "CROSS_DOMAIN_TRANSFER": "future category; capability not claimed today",
        },
        "authorizations": {"training": False, "gpu": False, "provider_inference": False,
                           "phase_21c": False, "foundation_selected": False},
        "historical_integrity": {"contract_engine_qualification": "SYSTEM_CONTRACT_QUALIFIED",
                                 "raw_model_runtime_qualified": {"Qwen3-8B": False, "Mistral-Nemo": False, "Phi-4": False}},
        "non_claims": NON_CLAIMS,
    }


def build_spec(root: Path | None = None) -> dict[str, Any]:
    """Core spec plus computed freeze readiness (READY is not FROZEN)."""
    from orca.intelligence.freeze import freeze_readiness

    root = root or Path(__file__).resolve().parents[2]
    spec = build_spec_core()
    fr = freeze_readiness(root)
    spec["freeze_status"] = fr
    return spec
