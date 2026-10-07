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
ROLE_MONITOR = 4
ROLE_TYPES = frozenset(range(1, 5))

DEST_MEDIUM = 1
DEST_RECIPIENT_ROLE = 2
DEST_EXPORT_TARGET = 3
DEST_KINDS = frozenset(range(1, 4))

WITNESS_ROUTINE = 1
WITNESS_IRREVERSIBLE = 2
WITNESS_IRREVERSIBLE_OC = 3
WITNESS_REQUIREMENTS = frozenset(range(1, 4))

# W-grant format. Only a non-executable weight format is accepted. RECOMMENDED code.
W_FORMAT_NO_CODE = 1

# R-grant reason. Opaque to the freeze; non-zero closed set. RECOMMENDED.
RETIRE_REASONS = frozenset(range(1, 5))

COMMON_LEN = 274
NAME_LEN = 64
MAX_ENTRIES = 1024
MAX_REGISTRY_BYTES = 1 << 20
MAX_NAME_CHARS = 64

# Tail sizes. POLICY, ENROLMENT, DESTINATION and HOLDOUT widths that the freeze
# did not number are the recommended profiles below.
TAIL_LEN = {
    CODE: 0,
    ROLE_IMAGE: 36,
    FOUNDATION_MODEL: 256,
    TOKENIZER: 64,
    MODEL: 129,
    CORPUS: 165,
    ENROLMENT: 101,
    POLICY: 70,
    DESTINATION: 65,
    HOLDOUT_SET: 40,
}

REG_MAGIC = b"OREG"  # RECOMMENDED framing; the freeze does not name a magic
REG_FORMAT_VERSION = 1
REG_SIG_DOMAIN = b"OREG-SIG"  # RECOMMENDED; parallel to OCG1-SIG
TOKEN_ID_DOMAIN = b"OREG-TOKEN"

GRANT_MAGIC = b"OCG1"
GRANT_VERSION = 1
GRANT_SIG_DOMAIN = b"OCG1-SIG"
SAS_DOMAIN = b"OCR-SAS-v1"

# Merkle profile applied to entry IDs. RECOMMENDED: RFC 6962 §2.1.
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
    ord("K"): ("RECOVERY", "RE-ROOT"),
    ord("Q"): ("QUALIFICATION", "QUALIFY"),
    ord("T"): ("TRAINING", "TRAIN"),
    ord("W"): ("WEIGHTS EXPORT", "EXPORT"),
    ord("D"): ("DEPLOYMENT", "DEPLOY"),
    ord("R"): ("RETIREMENT", "RETIRE"),
}

# Synthetic family labels. Not a foundation-model selection.
FAMILY_LABELS = ("GENESIS", "NOVUS", "AETERNUM")

# Checks this milestone does not claim.
NOT_CLAIMED = (
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
