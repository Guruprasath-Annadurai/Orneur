"""V2 constants, split taxonomy and freeze gate. This module holds NO item content, seeds, keys or answers."""
from __future__ import annotations

import math

from orca.eval.genesis_eval_v1 import CATEGORIES, CATEGORY_SPECS

EVAL_VERSION = "genesis-capability-eval/2.0.0"
CORPUS_VERSION = "genesis-corpus/2.0.0"
V1_EVAL_VERSION = "genesis-capability-eval/1.0.0"

SPLITS = ("DEV", "PILOT_TRAIN", "SCREEN", "QUALIFICATION_HOLDOUT")
PUBLIC_SPLITS = ("DEV", "PILOT_TRAIN")
PRIVATE_SPLITS = ("SCREEN", "QUALIFICATION_HOLDOUT")
STAGE_SPLIT = {"STAGE_1": "SCREEN", "STAGE_2": "QUALIFICATION_HOLDOUT"}

# Split lifecycle. QUALIFICATION_HOLDOUT: SEALED -> OPENED (once, by one candidate lineage) -> RETIRED.
STATE_SEALED, STATE_OPENED, STATE_RETIRED = "SEALED", "OPENED", "RETIRED"

PURPOSE_STAGE1 = "STAGE1_SCREEN"
PURPOSE_QUALIFICATION = "QUALIFICATION_RUN"
PURPOSE_RETIREMENT = "POST_RETIREMENT_DISCLOSURE"
ALLOWED_PURPOSES = {"SCREEN": (PURPOSE_STAGE1,), "QUALIFICATION_HOLDOUT": (PURPOSE_QUALIFICATION, PURPOSE_RETIREMENT)}
FORBIDDEN_PURPOSES = ("DEBUGGING", "TUNING", "ERROR_ANALYSIS", "ANSWER_INSPECTION", "SFT", "QLORA", "PEFT_TRAINING",
                      "PROMPT_TUNING", "FEW_SHOT_EXAMPLES", "ROUTER_TUNING", "MODEL_SELECTION_BY_ITEM")

SECRET_ENV = "ORNEUR_GENESIS_V2_CORPUS_SECRET"
ENC_KEY_ENV = "ORNEUR_GENESIS_V2_ENCRYPTION_KEY"
STORE_ENV = "ORNEUR_GENESIS_V2_PRIVATE_STORE"
STORE_TOKEN_ENV = "ORNEUR_GENESIS_V2_STORE_TOKEN"
MIN_SECRET_BYTES = 32

GENESIS_CAPABILITY_EVAL_V2_FROZEN = False
FREEZE_PREREQUISITES = (
    "private_storage_genuinely_configured",
    "new_secret_corpus_generated",
    "privacy_audit_pass",
    "screen_holdout_separation_pass",
    "contamination_controls_pass",
    "hashes_and_preregistration_frozen",
    "sandbox_ready",
    "exact_sha_ci_green",
    "independent_chatgpt_audit_approval",
)

# Keys that may NEVER appear in a public artifact.
FORBIDDEN_PUBLIC_KEYS = frozenset({
    "prompt", "input", "system", "ground_truth", "answer", "answers", "reference_solution", "sft_target", "scoring_key",
    "secret_seed", "generator_seed", "master_seed", "seed", "seeds", "generation_state", "rng_state", "salt", "private_holdout",
    "expected", "expected_output", "gold", "citations_gold", "image_path", "document_text", "meta",
})


def planned_counts() -> dict:
    """Design-target counts only (no items exist). QUALIFICATION_HOLDOUT mirrors V1 holdout power; SCREEN is ~30% (min 10)."""
    out: dict = {}
    for c in CATEGORIES:
        h = CATEGORY_SPECS[c]["holdout"]
        out[c] = {"QUALIFICATION_HOLDOUT": h, "SCREEN": (max(10, math.ceil(0.3 * h)) if h else 0),
                  "role": CATEGORY_SPECS[c]["role"], "floor": CATEGORY_SPECS[c]["floor"]}
    return out


def freeze_status(evidence: dict | None = None) -> dict:
    """V2 is frozen only if EVERY prerequisite is affirmatively evidenced; the module constant is the committed state."""
    evidence = evidence or {}
    missing = [p for p in FREEZE_PREREQUISITES if evidence.get(p) is not True]
    return {"frozen": (not missing) and GENESIS_CAPABILITY_EVAL_V2_FROZEN, "missing_prerequisites": missing}
