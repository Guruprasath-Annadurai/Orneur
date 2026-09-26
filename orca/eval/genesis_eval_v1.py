"""Genesis Capability Eval V1: frozen category definitions, floors, split policy (constants only).

Nothing here runs a model. Floors are the values recorded in the pre-registration artifact; changing any of them
requires Eval V2 (a test pins the pre-registration hash).
"""
from __future__ import annotations

EVAL_VERSION = "genesis-capability-eval/1.0.0"
CORPUS_VERSION = "genesis-corpus/1.0.0"
SPLITS = ("DEV", "PILOT_TRAIN", "HOLDOUT")
LOW_POWER_N = 100          # a full-holdout category/slice with fewer scored items than this is LOW_POWER
STAGE1_MIN_N = 30          # a Stage-1 probe slice needs at least this many items per gating category to be allowed to drop a model
HOLDOUT_FORBIDDEN_PURPOSES = ("SFT", "QLORA", "PEFT_TRAINING", "PROMPT_TUNING", "FEW_SHOT_EXAMPLES", "ROUTER_TUNING",
                              "THRESHOLD_TUNING", "MODEL_SELECTION_DEBUGGING", "DATA_AUGMENTATION", "SYNTHETIC_DATA_SEEDING")
HOLDOUT_ALLOWED_PURPOSES = ("QUALIFICATION",)
LANGUAGES = ("English", "Hindi", "Tamil", "Kannada")
ADDITIONAL_LANGUAGES_INCLUDED = False

CATEGORIES = ("instruction_following", "strict_contracts", "structured_outputs", "reasoning", "coding", "mathematics", "research",
              "tool_use", "long_context", "multilingual", "multimodal_where_applicable", "verification", "evidence_use",
              "counterfactual_reasoning", "hypothesis_testing", "discovery_quality", "cross_domain_transfer",
              "information_gain_reasoning", "latency", "cost", "trainability")

# role: GATING (frozen floor, may fail a model), REPORT_ONLY (published, never floors/ranks), PROTOCOL (harness definition, no Q&A items)
# holdout/dev/pilot: item counts per split. floor: frozen pass line on the mean item score.
CATEGORY_SPECS: dict[str, dict] = {
    "instruction_following": {"role": "GATING", "floor": 0.45, "holdout": 200, "dev": 20, "pilot": 100,
        "why": "every item needs 2-4 jointly satisfiable verifiable constraints ALL met (chance is near 0); a competent instruction-tuned model "
               "commonly meets multi-constraint prompts on roughly half to most items, so 0.45 rejects models that cannot follow explicit format rules without rejecting borderline ones"},
    "strict_contracts": {"role": "REPORT_ONLY", "floor": None, "holdout": 150, "dev": 15, "pilot": 100,
        "why": "raw-model contract behaviour is a recovery-cost signal only; SYSTEM_CONTRACT_QUALIFICATION belongs to ORNEUR itself"},
    "structured_outputs": {"role": "GATING", "floor": 0.65, "holdout": 180, "dev": 18, "pilot": 100,
        "why": "extraction from an explicit passage into a stated schema is the easiest gated skill; the Contract Engine can retry once, so the floor is set below "
               "the earlier 0.85 no-repair proposal but well above chance (which is near 0 for exact field values)"},
    "reasoning": {"role": "GATING", "floor": 0.35, "holdout": 180, "dev": 18, "pilot": 0,
        "why": "unique-answer logic puzzles with answer spaces of 3-6 (chance about 0.2); 0.35 requires clearly better than guessing while accepting small models"},
    "coding": {"role": "GATING", "floor": 0.30, "holdout": 100, "dev": 10, "pilot": 0,
        "why": "small, specified functions with hidden tests; requires the hermetic sandbox (results without it are INCOMPLETE, never guessed)"},
    "mathematics": {"role": "GATING", "floor": 0.45, "holdout": 180, "dev": 18, "pilot": 0,
        "why": "exact numeric answers (chance near 0); short multi-step arithmetic/number-theory items, so 0.45 separates models that compute from those that pattern-match"},
    "research": {"role": "GATING", "floor": 0.45, "holdout": 120, "dev": 12, "pilot": 0,
        "why": "multi-hop answer AND exact citation set must both be right (chance near 0); 0.45 accepts models that ground answers in supplied documents"},
    "tool_use": {"role": "GATING", "floor": 0.55, "holdout": 120, "dev": 12, "pilot": 60,
        "why": "tool name plus exact arguments, including refusal when no tool applies or an argument is missing; explicit specs make this comparatively easy"},
    "long_context": {"role": "GATING", "floor": 0.45, "holdout": 170, "dev": 6, "pilot": 0, "gating_slice": "8k",
        "slices": {"8k": 100, "16k": 40, "40k": 30},
        "why": "gated on the 8k slice only (n=100); 16k and 40k are LOW_POWER report-only slices because vendor-supported context differs across models"},
    "multilingual": {"role": "GATING", "floor": 0.40, "holdout": 200, "dev": 20, "pilot": 0,
        "why": "overall over English/Hindi/Tamil/Kannada (50 each); per-language results are LOW_POWER report-only; the floor is lower than monolingual floors because "
               "low-resource-script items are harder for small models"},
    "multimodal_where_applicable": {"role": "REPORT_ONLY", "floor": None, "holdout": 60, "dev": 6, "pilot": 0,
        "why": "N/A for text-only models (not a fail); n=60 is LOW_POWER"},
    "verification": {"role": "GATING", "floor": 0.50, "holdout": 180, "dev": 18, "pilot": 0,
        "why": "strategic; planted-error step identification and claim-vs-evidence labels have chance about 0.2-0.33, so 0.50 requires real checking ability"},
    "evidence_use": {"role": "GATING", "floor": 0.50, "holdout": 165, "dev": 16, "pilot": 0,
        "why": "strategic; correct answer AND exact supporting evidence ids or a correct abstention; chance is near 0.05"},
    "counterfactual_reasoning": {"role": "GATING", "floor": 0.35, "holdout": 120, "dev": 12, "pilot": 0,
        "why": "exact set/number answers computed from dependency graphs and formula systems; chance near 0.05; hard for small models so the floor is modest"},
    "hypothesis_testing": {"role": "GATING", "floor": 0.50, "holdout": 120, "dev": 12, "pilot": 0,
        "why": "choose a discriminating experiment or a verdict; chance about 0.25-0.33, so 0.50 is comfortably above guessing"},
    "discovery_quality": {"role": "REPORT_ONLY", "floor": None, "holdout": 60, "dev": 6, "pilot": 0,
        "why": "anchor-matched discoveries; n=60 is LOW_POWER; V1 reports precision/recall/decoy rate only"},
    "cross_domain_transfer": {"role": "REPORT_ONLY", "floor": None, "holdout": 60, "dev": 6, "pilot": 0,
        "why": "capability not claimed today; n=60 is LOW_POWER; reserved so the roadmap cannot silently omit it"},
    "information_gain_reasoning": {"role": "GATING", "floor": 0.35, "holdout": 120, "dev": 12, "pilot": 0,
        "why": "pick the single question with maximal information gain (ties accepted) or recognise sufficiency; chance about 0.2-0.25"},
    "latency": {"role": "PROTOCOL", "floor": None, "holdout": 0, "dev": 0, "pilot": 0, "probes": 12,
        "why": "measured by the harness under recorded hardware; report-only"},
    "cost": {"role": "PROTOCOL", "floor": None, "holdout": 0, "dev": 0, "pilot": 0,
        "why": "derived from measured GPU time x the persisted rate; report-only"},
    "trainability": {"role": "PROTOCOL", "floor": None, "holdout": 0, "dev": 0, "pilot": 0,
        "why": "Stage-3 finalists only: common pilot on PILOT_TRAIN, then re-run of format categories and a regression check; a measurement, never an entry floor"},
}

GATING_CATEGORIES = tuple(c for c in CATEGORIES if CATEGORY_SPECS[c]["role"] == "GATING")
REPORT_ONLY_CATEGORIES = tuple(c for c in CATEGORIES if CATEGORY_SPECS[c]["role"] == "REPORT_ONLY")
PROTOCOL_CATEGORIES = tuple(c for c in CATEGORIES if CATEGORY_SPECS[c]["role"] == "PROTOCOL")
FLOORS = {c: CATEGORY_SPECS[c]["floor"] for c in GATING_CATEGORIES}
PILOT_CATEGORIES = tuple(c for c in CATEGORIES if CATEGORY_SPECS[c].get("pilot", 0) > 0)
TRAINABILITY_REGRESSION_CATEGORIES = ("reasoning", "mathematics", "verification")
TRAINABILITY_FORMAT_CATEGORIES = PILOT_CATEGORIES
MANDATORY_STAGE2_GATING = GATING_CATEGORIES
SCORER_VERSION = "genesis-scorers/1.0.0"
