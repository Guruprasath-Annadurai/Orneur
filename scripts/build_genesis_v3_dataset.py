"""
Builds the canonical `orneur-genesis-v3` SFT dataset -- Phase 21B.3's
expansion of the v2 (19-record, six-domain) dataset into genuinely broad
BROAD EXECUTABLE INTELLIGENCE coverage, per the Phase 21B.3 spec's
explicit instruction that Genesis is not a narrow coding model.

HONEST SCOPE, per the spec's own "quality > raw record count" instruction
(section 10): this build reads 84 individually hand-authored records
(each composed for this closure, not templated or mass-generated from a
prompt-variation script) spanning 11 domain clusters and ~50 distinct
subcategories: general_intelligence, business, quantitative,
science_engineering, software_product, execution, collaboration,
epistemic_behavior, capability_expansion, presence_mode, and
human_sovereignty. This is a real, material expansion over v2 (84 vs 19,
~4.4x), but it is explicitly NOT claimed to be a production-scale SFT
corpus (which would need low-thousands of diverse records at minimum) --
see docs/orneur/phase-21/GENESIS_DATASET_V3.md's adequacy assessment for
the honest gap analysis. synthetic_percentage is recorded as 100 (every
record is LLM-authored, not sourced from an external dataset or
templated) -- this is distinct from and does not represent the
"thousands of near-identical templates" pattern the spec explicitly
forbids; see the per-record diversity (unique domain/subcategory/prompt
combinations, verified by exact-duplicate and near-duplicate screening
below) as the actual quality signal, not the record count alone.

Formatted via ChatML (`orca.data.formatter.to_chatml`), matching v2's
(correct, Qwen-native) template choice -- the canonical Genesis base
remains a Qwen model family throughout Phase 21B.3 (unchanged pending
owner approval of a foundation-model switch).

Usage: python3 scripts/build_genesis_v3_dataset.py
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from orca.data.formatter import to_chatml

ORCA_HOME = Path.home() / ".orca"
V3_SEED_PATH = ORCA_HOME / "training" / "raw" / "genesis_v3_seed_20260917.jsonl"
OUT_DIR = Path(__file__).resolve().parent.parent / "notebooks" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
EVAL_FRACTION = 0.15

SYSTEM_PROMPT = (
    "You are Orneur Genesis, ORNEUR's Builder / Executor model. You propose and implement "
    "software and broader executable outcomes across business, quantitative, scientific, and "
    "everyday-professional domains, but you never claim work is verified unless it genuinely "
    "has been, you never execute governed/authority-bearing actions yourself -- you propose "
    "them for a human or ORNEUR's deterministic governance layer to authorize -- and you never "
    "fabricate progress, evidence, or approval."
)

REQUIRED_SCHEMA_KEYS = {"domain", "subcategory", "difficulty", "prompt", "response"}
VALID_DIFFICULTIES = {"basic", "intermediate", "advanced"}

# Near-duplicate detection thresholds. HONEST LIMITATION (documented per
# spec section 16): this is normalized token-set Jaccard similarity, a
# purely lexical/structural signal. It catches templated near-duplicates
# (the same scaffolding with a name/number swapped) but does NOT detect
# semantic contamination -- two records with completely different
# wording that convey the same underlying task are invisible to this
# scan. No claim of semantic contamination detection is made anywhere in
# this script or its output.
NEAR_DUP_JACCARD_THRESHOLD = 0.85


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current_git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _normalized_token_set(text: str) -> set[str]:
    """Lowercase, strip punctuation, split on whitespace -- a simple,
    transparent normalization for both near-duplicate detection and the
    proxy token-count estimate below. Not a real tokenizer (see
    estimate_token_count()'s docstring)."""
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    return set(normalized.split())


def estimate_token_count(text: str) -> int:
    """PROXY token estimate ONLY -- whitespace-split word count times a
    fixed 1.3 words-per-token fudge factor, a common rough heuristic for
    English text under BPE-style tokenizers. This is explicitly NOT an
    exact tokenizer count (Phase 21B.3 spec section 33 forbids
    downloading model weights merely to count tokens; a real tokenizer
    count would additionally require the exact target tokenizer, which
    is not yet fixed pending the foundation-model decision). Every
    consumer of this number in this script's output is labeled
    "proxy_estimate", never "exact"."""
    word_count = len(text.split())
    return max(1, round(word_count * 1.3))


# Trivial, explicitly non-exhaustive PII heuristic -- flags patterns that
# LOOK like an email address, a US-style SSN, or a long digit run that
# could be a credit-card/phone number. Documented limitation: this is a
# regex heuristic, not a real PII detector, and produces both false
# positives (e.g., version numbers, hashes) and false negatives (names,
# addresses, non-US formats). Used here only to confirm this
# ORNEUR-authored fixture corpus contains none of the obvious patterns,
# not as a general-purpose PII screening claim.
_PII_PATTERNS = {
    "email_like": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "long_digit_run": re.compile(r"\b\d{9,}\b"),
}


def load_seed_examples() -> list[dict]:
    """Fail-closed schema validation, matching v2's discipline: every
    record must have exactly the required keys with non-empty string
    values, a valid difficulty tier, and no duplicate (domain,
    subcategory, prompt) triple -- a malformed or duplicate record
    aborts the build."""
    if not V3_SEED_PATH.exists():
        raise FileNotFoundError(
            f"Genesis v3 seed file not found: {V3_SEED_PATH}\n"
            "This file is a local, untracked, ORNEUR-authored training-data source "
            "(matching v2's existing convention -- see ~/.orca/ in .gitignore), not "
            "committed to the repository."
        )

    examples: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()
    with open(V3_SEED_PATH) as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            missing = REQUIRED_SCHEMA_KEYS - record.keys()
            if missing:
                raise ValueError(f"{V3_SEED_PATH}:{line_no}: record missing required keys {missing}")
            for key in REQUIRED_SCHEMA_KEYS:
                if not isinstance(record[key], str) or not record[key].strip():
                    raise ValueError(f"{V3_SEED_PATH}:{line_no}: field {key!r} must be a non-empty string")
            if record["difficulty"] not in VALID_DIFFICULTIES:
                raise ValueError(
                    f"{V3_SEED_PATH}:{line_no}: difficulty {record['difficulty']!r} not in {VALID_DIFFICULTIES}"
                )
            dedup_key = (record["domain"], record["subcategory"], record["prompt"])
            if dedup_key in seen_keys:
                raise ValueError(f"{V3_SEED_PATH}:{line_no}: duplicate (domain, subcategory, prompt) {dedup_key!r}")
            seen_keys.add(dedup_key)
            examples.append(record)

    if not examples:
        raise ValueError(f"{V3_SEED_PATH} contains no records -- refusing to build an empty dataset")

    # Exact-duplicate scan (byte-identical prompt+response pairs across
    # DIFFERENT domain/subcategory tags, which the dedup_key above
    # wouldn't catch since it's keyed on domain+subcategory+prompt).
    exact_seen: dict[str, int] = {}
    for r in examples:
        combined = r["prompt"] + "\x00" + r["response"]
        digest = _sha256_of_text(combined)
        if digest in exact_seen:
            raise ValueError(f"Exact duplicate prompt+response pair detected (first seen at index {exact_seen[digest]})")
        exact_seen[digest] = len(exact_seen)

    return examples


def scan_near_duplicates(examples: list[dict]) -> list[dict]:
    """O(n^2) normalized-token-set Jaccard similarity scan over prompts
    -- fine at this corpus size (84 records => ~3.5k pairs), would need
    a smarter approach (e.g. MinHash/LSH) at production scale. Returns
    a list of {i, j, similarity} for every pair at or above
    NEAR_DUP_JACCARD_THRESHOLD. See NEAR_DUP_JACCARD_THRESHOLD's
    docstring for the honest limitation of this method."""
    token_sets = [_normalized_token_set(r["prompt"]) for r in examples]
    flagged = []
    for i in range(len(examples)):
        for j in range(i + 1, len(examples)):
            a, b = token_sets[i], token_sets[j]
            if not a or not b:
                continue
            jaccard = len(a & b) / len(a | b)
            if jaccard >= NEAR_DUP_JACCARD_THRESHOLD:
                flagged.append({"i": i, "j": j, "similarity": round(jaccard, 3)})
    return flagged


def scan_pii(examples: list[dict]) -> dict:
    findings: dict[str, int] = {name: 0 for name in _PII_PATTERNS}
    for r in examples:
        text = r["prompt"] + " " + r["response"]
        for name, pattern in _PII_PATTERNS.items():
            if pattern.search(text):
                findings[name] += 1
    return findings


def to_conversation_text(record: dict) -> str:
    conv = {
        "conversations": [
            {"role": "system", "value": SYSTEM_PROMPT},
            {"role": "human", "value": record["prompt"]},
            {"role": "gpt", "value": record["response"]},
        ]
    }
    return to_chatml(conv)


def build() -> dict:
    examples = load_seed_examples()

    near_dups = scan_near_duplicates(examples)
    pii_findings = scan_pii(examples)

    formatted = [
        {
            "text": to_conversation_text(r),
            "domain": r["domain"],
            "subcategory": r["subcategory"],
            "difficulty": r["difficulty"],
        }
        for r in examples
    ]

    rng = random.Random(SEED)
    indices = list(range(len(formatted)))
    rng.shuffle(indices)
    eval_count = max(1, round(len(formatted) * EVAL_FRACTION))
    eval_indices = set(indices[:eval_count])

    train_records = [formatted[i] for i in range(len(formatted)) if i not in eval_indices]
    eval_records = [formatted[i] for i in eval_indices]

    # Exact train/eval leakage check (fail closed).
    train_texts = {r["text"] for r in train_records}
    eval_texts = {r["text"] for r in eval_records}
    leakage = train_texts & eval_texts
    if leakage:
        raise ValueError(f"Train/eval leakage detected in {len(leakage)} record(s) -- refusing to write output")

    train_path = OUT_DIR / "orneur_genesis_v3_train.jsonl"
    eval_path = OUT_DIR / "orneur_genesis_v3_eval.jsonl"
    with open(train_path, "w") as f:
        for r in train_records:
            f.write(json.dumps({"text": r["text"]}) + "\n")
    with open(eval_path, "w") as f:
        for r in eval_records:
            f.write(json.dumps({"text": r["text"]}) + "\n")

    train_checksum = _sha256_of_text(train_path.read_text())
    eval_checksum = _sha256_of_text(eval_path.read_text())

    domain_counts = Counter(r["domain"] for r in formatted)
    subcategory_counts = Counter(r["subcategory"] for r in formatted)
    difficulty_counts = Counter(r["difficulty"] for r in formatted)

    token_estimates = [estimate_token_count(r["text"]) for r in formatted]
    token_estimates_sorted = sorted(token_estimates)

    def _percentile(sorted_vals: list[int], pct: float) -> int:
        if not sorted_vals:
            return 0
        idx = min(len(sorted_vals) - 1, round(pct * (len(sorted_vals) - 1)))
        return sorted_vals[idx]

    summary = {
        "dataset_id": "orneur-genesis-v3",
        "version": "v1",
        "record_count": len(formatted),
        "train_count": len(train_records),
        "eval_count": len(eval_records),
        "domains": dict(sorted(domain_counts.items())),
        "subcategories": dict(sorted(subcategory_counts.items())),
        "difficulty_distribution": dict(sorted(difficulty_counts.items())),
        "train_path": str(train_path),
        "eval_path": str(eval_path),
        "train_checksum": f"sha256:{train_checksum}",
        "eval_checksum": f"sha256:{eval_checksum}",
        "creation_code_sha": _current_git_sha(),
        "seed": SEED,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "source_id": "orneur-authored-v3-seed-20260917",
            "source_reference": str(V3_SEED_PATH),
            "license": "ORNEUR-internal (no third-party rights encumbrance; every record individually authored for this closure)",
            "retrieval_date": "2026-09-17",
            "transformation_method": "direct hand-authoring, formatted to ChatML via orca.data.formatter.to_chatml",
            "attribution_requirement": "none",
            "record_contribution_count": len(formatted),
        },
        "synthetic_percentage": 100,
        "manually_authored_percentage": 0,
        "transformed_open_data_percentage": 0,
        "dedup_summary": {
            "exact_duplicates_found": 0,  # load_seed_examples() raises before reaching here if any exist
            "near_duplicate_pairs_found": len(near_dups),
            "near_duplicate_jaccard_threshold": NEAR_DUP_JACCARD_THRESHOLD,
            "near_duplicate_method": "normalized token-set Jaccard similarity over prompts (lexical/structural only -- does not detect semantic contamination; see script docstring)",
            "near_duplicate_pairs": near_dups,
        },
        "pii_screening_summary": {
            "method": "regex heuristic (email-like, SSN-like, long-digit-run patterns) -- not a comprehensive PII detector",
            "findings": pii_findings,
        },
        "token_statistics": {
            "method": "PROXY ESTIMATE (word_count * 1.3) -- NOT an exact tokenizer count; see estimate_token_count() docstring",
            "total_estimated_tokens": sum(token_estimates),
            "median_estimated_tokens": _percentile(token_estimates_sorted, 0.50),
            "p90_estimated_tokens": _percentile(token_estimates_sorted, 0.90),
            "p95_estimated_tokens": _percentile(token_estimates_sorted, 0.95),
            "max_estimated_tokens": max(token_estimates) if token_estimates else 0,
        },
    }
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    build()
