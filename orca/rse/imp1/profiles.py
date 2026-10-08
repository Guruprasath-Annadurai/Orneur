"""Closed constants for the RSE-IMP-1 canonical layouts.

Integer width and order for multi-byte fields follow the only byte order the
frozen package states: big-endian (RSE12_04 §3, envelope integers; I2OSP in
RSE12_04 §7). Entry field order and sizes follow RSE12_01 §2. Grant field order
and sizes follow RSE12_04 §8.

Where the freeze names a field but does not assign a numeric code or a tail
width, the value is marked RECOMMENDED and reported as an architecture-change
request. Those markers are not a second source of authority.
"""

from __future__ import annotations

# --- entry classes (RSE12_01 §2) ---
CODE = 1
ROLE_IMAGE = 2
FOUNDATION_MODEL = 3
TOKENIZER = 4
MODEL = 5
CORPUS = 6
ENROLMENT = 7
POLICY = 8
DESTINATION = 9
HOLDOUT_SET = 10
ENTRY_TYPES = frozenset(range(1, 11))

# Approval states are numbered by the freeze. RETIRED is not an approval state.
PENDING = 1
APPROVED = 2
DEPRECATED = 3
REVOKED = 4
APPROVAL_STATES = frozenset({PENDING, APPROVED, DEPRECATED, REVOKED})
APPROVAL_NAME = {1: "PENDING", 2: "APPROVED", 3: "DEPRECATED", 4: "REVOKED"}

# Listed order, 1-based, same pattern as approval_state. RECOMMENDED.
LIFECYCLE_CANDIDATE = 1
LIFECYCLE_QUALIFIED = 2
LIFECYCLE_ACCEPTED = 3
LIFECYCLE_EXPORTED = 4
LIFECYCLE_DEPLOYED = 5
LIFECYCLE_RETIRED = 6
LIFECYCLE_STATES = frozenset(range(1, 7))

RETIREMENT_ACTIVE = 1
RETIREMENT_RETIRED = 2
RETIREMENT_STATES = frozenset({RETIREMENT_ACTIVE, RETIREMENT_RETIRED})

ROLE_CROWN = 1
ROLE_FORGE = 2
ROLE_WITNESS = 3
ROLE_MONITOR_LITE = 4
ROLE_MONITOR = ROLE_MONITOR_LITE  # same wire code; the name is MONITOR_LITE
ROLE_TYPES = frozenset(range(1, 5))

DEST_MEDIUM = 1
DEST_RECIPIENT_ROLE = 2
DEST_EXPORT_TARGET = 3
DEST_KINDS = frozenset(range(1, 4))

WITNESS_ROUTINE = 1
WITNESS_IRREVERSIBLE = 2
WITNESS_IRREVERSIBLE_OC = 3
WITNESS_REQUIREMENTS = frozenset(range(1, 4))

# W format and foundation artifact_format share this code space (Clarification 1 §8, §12).
DATA_ONLY_TENSOR_V1 = 1
EXECUTABLE_OR_CODE_LOADING = 128
UNINSPECTED = 255
ARTIFACT_FORMATS = frozenset({DATA_ONLY_TENSOR_V1, EXECUTABLE_OR_CODE_LOADING, UNINSPECTED})
W_FORMAT_NO_CODE = DATA_ONLY_TENSOR_V1
APPROVABLE_ARTIFACT_FORMATS = frozenset({DATA_ONLY_TENSOR_V1})

# R-grant reason codes. Parser constants only in this milestone.
RETIRE_SUPERSEDED = 1
RETIRE_COMPROMISED = 2
RETIRE_POLICY = 3
RETIRE_END_OF_LIFE = 4
RETIRE_REASONS = frozenset({RETIRE_SUPERSEDED, RETIRE_COMPROMISED, RETIRE_POLICY, RETIRE_END_OF_LIFE})
RETIRE_NAME = {
    1: "SUPERSEDED",
    2: "COMPROMISED OR SUSPECTED",
    3: "POLICY VIOLATION",
    4: "END OF LIFE",
}

# K scenario codes. Parser and display only; K is not executed.
K_EPOCH_RAISE = 1
K_FORGE_REBUILD = 2
K_WITNESS_REBUILD = 3
K_TPM_REPLACE = 4
K_WITNESS_ENV_UPDATE = 5
K_TOKEN_REPLACE = 6
K_CHECKPOINT_HOLDER_REPLACE = 7
K_CHECKPOINT_ROOT_REESTABLISH = 8
K_ARTIFACT_REPO_RECOVERY = 9
K_CORPUS_RESTORE = 10
K_WEIGHTS_RESTORE = 11
K_LUKS_SLOT_ROTATION = 12
K_RE_ROOT = 13
K_SCENARIO_NAME = {
    1: "EPOCH RAISE",
    2: "FORGE REBUILD",
    3: "WITNESS REBUILD",
    4: "TPM REPLACE",
    5: "WITNESS ENV UPDATE",
    6: "TOKEN REPLACE",
    7: "CHECKPOINT HOLDER REPLACE",
    8: "CHECKPOINT ROOT REESTABLISH",
    9: "ARTIFACT REPO RECOVERY",
    10: "CORPUS RESTORE",
    11: "WEIGHTS RESTORE",
    12: "LUKS SLOT ROTATION",
    13: "RE-ROOT",
}
K_SCENARIOS = frozenset(K_SCENARIO_NAME)

COMMON_LEN = 274
NAME_LEN = 64
MAX_ENTRIES = 1024
MAX_REGISTRY_BYTES = 1 << 20
MAX_NAME_CHARS = 64

# Tail sizes frozen by Clarification 1 §5.
TAIL_LEN = {
    CODE: 0,
    ROLE_IMAGE: 36,
    FOUNDATION_MODEL: 289,
    TOKENIZER: 64,
    MODEL: 129,
    CORPUS: 165,
    ENROLMENT: 101,
    POLICY: 199,
    DESTINATION: 33,
    HOLDOUT_SET: 40,
}

# policy_entry_id is zero on these types. Family-bearing types must name a POLICY.
FAMILY_NEUTRAL_TYPES = frozenset({CODE, ROLE_IMAGE, ENROLMENT, DESTINATION, POLICY})
FAMILY_BEARING_TYPES = frozenset({TOKENIZER, FOUNDATION_MODEL, MODEL, CORPUS, HOLDOUT_SET})
MAX_DESTINATIONS = 4
UNSUPPORTED_CURRENT_MILESTONE = "UNSUPPORTED_CURRENT_MILESTONE"
SEMANTIC_CLASSES = frozenset({ord("G"), ord("V")})
DEFERRED_CLASSES = frozenset({ord("K"), ord("Q"), ord("T"), ord("W"), ord("D"), ord("R")})

REG_MAGIC = b"OREG"
REG_FORMAT_VERSION = 1
REG_SIG_DOMAIN = b"OREG-SIG"
TOKEN_ID_DOMAIN = b"OREG-TOKEN"

GRANT_MAGIC = b"OCG1"
GRANT_VERSION = 1
GRANT_SIG_DOMAIN = b"OCG1-SIG"
SAS_DOMAIN = b"OCR-SAS-v1"

# Registry integrity only. Not the Evidence Ledger tree.
MERKLE_PROFILE = "RFC6962-SHA256-ENTRY-ID-LEAF"

CLASS_BITS = {
    ord("G"): 0,
    ord("V"): 1,
    ord("K"): 2,
    ord("Q"): 3,
    ord("T"): 4,
    ord("W"): 5,
    ord("D"): 6,
    ord("R"): 7,
}
KNOWN_CLASSES = frozenset(CLASS_BITS)

# Exact totals from RSE12_04 §8 (signed prefix + signatures).
CLASS_TOTAL = {
    ord("G"): 418 + 130,
    ord("V"): 358 + 65,
    ord("K"): 576 + 130,
    ord("Q"): 386 + 130,
    ord("T"): 418 + 130,
    ord("W"): 447 + 130,
    ord("D"): 486 + 130,
    ord("R"): 311 + 130,
}
CLASS_SIG_LEN = {klass: (65 if klass == ord("V") else 130) for klass in KNOWN_CLASSES}

# Fixed Crown card text. Class G's phrase is the example in RSE12_01 §4.
# The other phrases are renderer constants, not proposer text.
CLASS_TEXT = {
    ord("G"): ("CORPUS GENERATION", "GENERATE"),
    ord("V"): ("WITNESS VERIFICATION", "VERIFY"),
    ord("K"): ("RECOVERY", "SCENARIO"),
    ord("Q"): ("QUALIFICATION", "QUALIFY"),
    ord("T"): ("TRAINING", "TRAIN"),
    ord("W"): ("WEIGHTS EXPORT", "EXPORT"),
    ord("D"): ("DEPLOYMENT", "DEPLOY"),
    ord("R"): ("RETIREMENT", "RETIRE"),
}

# Already frozen elsewhere. Not executed in IMP-1. Not a success path.
CARRY_FORWARD = (
    "W must equal the model entry qualification_record_digest",
    "T and Q-linked corpora need a non-zero witnessed acceptance record",
    "D may reference an exported or accepted model",
    "K epoch and authority-version rules apply only when K is executable",
    "K Q T and D Crown cards omit future signed fields; those classes stay unsupported and are not executable",
)

# Synthetic family labels. Not a foundation-model selection.
FAMILY_LABELS = ("GENESIS", "NOVUS", "AETERNUM")

# Checks this milestone does not claim.
NOT_CLAIMED = (
    "foundation_backdoor_absence",
    "hardware_anti_rollback",
    "tpm_nv_fence",
    "witness_quorum",
    "prev_checkpoint_ancestry",
    "hpke",
    "real_secret",
    "corpus_generation",
    "qualification",
    "model_selection",
    "gpu",
    "provider",
    "spending",
    "training",
)
