"""Twenty-step provenance gate for local synthetic fixtures.

This module does not fetch a URL, write a protected corpus, or treat a
license string as permission to train. `training_admitted` is always
false. Independent custody and publication clearance stay blocked
because this process has no enrolled custodian and no founder grant.

A record is `admitted_synthetic` only when every local check passes and
the license is the fixture label `synthetic-fixture` with usage
`local-test-only`. Any other license, including a well-known open-source
name or a public-web claim, is metadata at most.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from orca.eval.genesis_contamination import jaccard, normalize_text, word_ngrams
from orca.genesis.data.contamination import (
    find_exact_matches,
    find_near_duplicates_across_splits,
    find_normalized_substring_matches,
)
from orca.genesis.data.manifest import normalize_record_text
from orca.genesis.data.pipeline import (
    NEAR_DUP_JACCARD_THRESHOLD,
    NEAR_DUP_WINDOW,
    NEAR_DUP_WORD_NGRAM,
    deterministic_split,
)
from orca.learning.sanitize import sanitize_for_candidate

SCHEMA = "orneur-synthetic-provenance/1"
SYNTHETIC_LICENSE = "synthetic-fixture"
SYNTHETIC_USAGE = "local-test-only"
ACCOUNTING_METHOD = "whitespace-and-utf8-bytes-v1"
# Hoffmann et al., 2022, report a compute-optimal rule of thumb near
# 20 tokens per parameter. This constant is that literature reference.
# It is not an ORNEUR-selected budget and no tokens are acquired here.
LITERATURE_TOKENS_PER_PARAMETER = 20

STEPS: tuple[tuple[str, str], ...] = (
    ("source_identity", "Source identity"),
    ("license_and_usage_rights", "License and usage-rights verification"),
    ("document_provenance", "Document-level provenance"),
    ("consent_and_contract", "Consent and contractual restrictions"),
    ("pii_and_secrets", "PII and secret detection"),
    ("quality_and_language", "Quality scoring and language identification"),
    ("exact_and_near_duplicate", "Exact and near-duplicate detection"),
    ("poison_and_malicious", "Poisoning and malicious-content screening"),
    ("code_separation", "Code-quality and executable-content separation"),
    ("language_domain_balance", "Language and domain balance"),
    ("split_isolation", "Train/validation/test isolation"),
    ("eval_contamination", "Evaluation and benchmark contamination checks"),
    ("removal_and_exclusion", "Removal requests and source exclusions"),
    ("per_record_hash", "Per-record hashing"),
    ("immutable_manifest", "Immutable corpus manifest"),
    ("independent_custody", "Independent custody"),
    ("token_accounting", "Reproducible token accounting"),
    ("distribution_version", "Distribution/version tracking"),
    ("publication_rights", "Publication rights review"),
    ("ingestion_errors_and_rollback", "Provenance-preserving ingestion errors and rollback"),
)

_PUBLIC_WEB = frozenset({
    "public-web",
    "public web",
    "web",
    "internet",
    "unspecified",
    "unknown",
    "all public text",
    "public text",
})
_POISON = (
    "ignore previous",
    "grant admin",
    "you are now",
    "system:",
    "<script",
    "curl | sh",
    "rm -rf",
)
_SCRIPT_FOR_LANGUAGE = {
    "en": "latin",
    "english": "latin",
    "hi": "devanagari",
    "hindi": "devanagari",
    "zh": "cjk",
    "chinese": "cjk",
    "ar": "arabic",
    "arabic": "arabic",
}


class ProvenanceError(ValueError):
    """The fixture batch cannot be screened as given."""


@dataclass(frozen=True)
class RecordDecision:
    record_id: str
    record_hash: str
    outcome: str
    reasons: tuple[str, ...]
    split: str | None
    script: str
    domain_bucket: str
    whitespace_tokens: int
    utf8_bytes: int


def literature_token_requirement(parameter_count: int) -> dict:
    """Return a literature token figure with acquisition still at zero."""
    if parameter_count < 1:
        raise ProvenanceError("parameter_count must be positive")
    return {
        "formula": f"{LITERATURE_TOKENS_PER_PARAMETER} * parameter_count",
        "source": "Hoffmann et al. 2022 compute-optimal rule of thumb",
        "tokens": LITERATURE_TOKENS_PER_PARAMETER * parameter_count,
        "tokens_acquired": 0,
        "selected": False,
        "status": "REQUIREMENT_NOT_AUTHORIZED",
    }


def _canonical_hash(payload: Mapping) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _script_family(text: str) -> str:
    counts = {"latin": 0, "devanagari": 0, "cjk": 0, "arabic": 0, "other": 0}
    for char in text:
        code = ord(char)
        if char.isascii() and char.isalpha():
            counts["latin"] += 1
        elif 0x0900 <= code <= 0x097F:
            counts["devanagari"] += 1
        elif 0x4E00 <= code <= 0x9FFF:
            counts["cjk"] += 1
        elif 0x0600 <= code <= 0x06FF:
            counts["arabic"] += 1
        elif char.isalpha():
            counts["other"] += 1
    total = sum(counts.values())
    if total == 0:
        return "undetermined"
    return max(counts, key=counts.get)


def _public_web_claim(license_name: str) -> bool:
    folded = " ".join(license_name.casefold().split())
    return folded in _PUBLIC_WEB or "public web" in folded or "public-web" in folded


def _looks_like_code(text: str, domain: str) -> bool:
    if domain == "code":
        return True
    stripped = text.lstrip()
    return domain == "mixed" and (
        stripped.startswith("#!") or stripped.startswith("def ") or stripped.startswith("import ")
    )


def _quality_score(normalized: str) -> float:
    if not normalized:
        return 0.0
    letters = sum(1 for char in normalized if char.isalpha())
    return letters / len(normalized)


def _as_record(raw: Mapping) -> dict:
    if not isinstance(raw, Mapping):
        raise ProvenanceError("each record must be a mapping")
    return dict(raw)


def qualify_synthetic_records(
    records: Sequence[Mapping],
    *,
    eval_items: Sequence[Mapping] = (),
    removed_record_ids: Sequence[str] = (),
    excluded_source_ids: Sequence[str] = (),
    publication_decision: Mapping | None = None,
    custodian_public_key_hex: str = "",
    fail_after_record_id: str | None = None,
    near_dup_window: int = NEAR_DUP_WINDOW,
) -> dict:
    """Screen records in memory and publish a synthetic manifest or roll back.

    `publication_decision` and `custodian_public_key_hex` are accepted so a
    caller cannot smuggle approval by omitting the arguments. Both are
    ignored as authority. A non-empty key is refused rather than enrolled.
    """
    if not records:
        raise ProvenanceError("at least one record is required")
    if near_dup_window < 1:
        raise ProvenanceError("near_dup_window must be >= 1")
    if custodian_public_key_hex:
        raise ProvenanceError("this module does not enroll custodian keys")
    if publication_decision is not None and not isinstance(publication_decision, Mapping):
        raise ProvenanceError("publication_decision must be a mapping when supplied")

    removed = set(removed_record_ids)
    excluded_sources = set(excluded_source_ids)
    prepared = [_as_record(raw) for raw in records]
    seen_exact: dict[str, str] = {}
    seen_normalized: list[tuple[str, str, frozenset]] = []
    decisions: list[RecordDecision] = []
    discarded: list[str] = []
    rolled_back = False
    rollback_error = None

    for raw in prepared:
        record_id = str(raw.get("record_id") or "")
        record_hash = _canonical_hash(raw)
        if fail_after_record_id and record_id == fail_after_record_id:
            rolled_back = True
            rollback_error = {
                "record_id": record_id,
                "record_hash": record_hash,
                "reason": "injected ingestion fault",
            }
            discarded = [row.record_id for row in decisions]
            decisions = []
            break
        decisions.append(_screen_one(
            raw,
            record_hash=record_hash,
            seen_exact=seen_exact,
            seen_normalized=seen_normalized,
            removed=removed,
            excluded_sources=excluded_sources,
            eval_items=eval_items,
            near_dup_window=near_dup_window,
        ))

    decisions = _reject_cross_split(decisions, prepared, rolled_back=rolled_back)
    admitted = [row for row in decisions if row.outcome == "admitted_synthetic"]
    versions = {str(raw.get("distribution_version") or "") for raw in prepared}
    version_conflict = len(versions) != 1 or "" in versions
    distribution_version = next(iter(versions)) if not version_conflict else ""

    cross_split = [
        row.record_id for row in decisions if "cross_split_near_duplicate" in row.reasons
    ]
    manifest = None
    if admitted and not rolled_back and not version_conflict and not cross_split:
        manifest = _manifest(admitted, distribution_version)

    balance = _balance(admitted)
    token_total = sum(row.whitespace_tokens for row in admitted)
    byte_total = sum(row.utf8_bytes for row in admitted)
    code_rows = [row for row in decisions if row.outcome == "separated_code"]
    steps = _step_report(
        decisions=decisions,
        balance=balance,
        manifest=manifest,
        rolled_back=rolled_back,
        version_conflict=version_conflict,
        publication_supplied=publication_decision is not None,
    )
    return {
        "schema": SCHEMA,
        "training_admitted": False,
        "protected_corpus_generated": False,
        "tokens_acquired": 0,
        "decisions": decisions,
        "discarded_after_rollback": tuple(discarded),
        "rolled_back": rolled_back,
        "rollback_error": rollback_error,
        "distribution_version": distribution_version,
        "distribution_version_conflict": version_conflict,
        "cross_split_near_duplicates": tuple(cross_split),
        "code_separated": tuple(row.record_id for row in decisions if row.outcome == "separated_code"),
        "manifest": manifest,
        "balance": balance,
        "quality_distribution_target": "UNSET",
        "balance_qualified": False,
        "accounting_method": ACCOUNTING_METHOD,
        "whitespace_tokens": token_total,
        "utf8_bytes": byte_total,
        "code_whitespace_tokens": sum(row.whitespace_tokens for row in code_rows),
        "independent_custody": "BLOCKED",
        "publication_rights": "BLOCKED",
        "publication_input_ignored": publication_decision is not None,
        "steps": steps,
        "near_dup_scope": "full_batch" if len(prepared) <= near_dup_window else "bounded_window_not_full_corpus",
    }


def _screen_one(
    raw: Mapping,
    *,
    record_hash: str,
    seen_exact: dict[str, str],
    seen_normalized: list[tuple[str, str, frozenset]],
    removed: set[str],
    excluded_sources: set[str],
    eval_items: Sequence[Mapping],
    near_dup_window: int,
) -> RecordDecision:
    reasons: list[str] = []
    record_id = raw.get("record_id")
    text = raw.get("text")
    if not isinstance(record_id, str) or not record_id.strip():
        reasons.append("record_id_missing")
        record_id = ""
    source_id = raw.get("source_id")
    source_uri = raw.get("source_uri")
    if not isinstance(source_id, str) or not source_id.strip():
        reasons.append("source_id_missing")
    if not isinstance(source_uri, str) or not source_uri.startswith("synthetic://"):
        reasons.append("source_uri_not_synthetic")
    if isinstance(source_id, str) and source_id in excluded_sources:
        reasons.append("source_excluded")
    if record_id in removed or raw.get("removed") is True:
        reasons.append("removal_requested")

    license_name = raw.get("license")
    usage = raw.get("usage_restrictions")
    if not isinstance(license_name, str) or not license_name.strip():
        reasons.append("license_missing")
        license_name = ""
    elif _public_web_claim(license_name):
        reasons.append("public_web_not_cleared")
    elif license_name != SYNTHETIC_LICENSE:
        reasons.append("license_metadata_not_a_training_grant")
    if not isinstance(usage, str) or not usage.strip():
        reasons.append("usage_restrictions_missing")
    elif "no-train" in usage.casefold() or "no train" in usage.casefold():
        reasons.append("contract_forbids_training")
    elif usage != SYNTHETIC_USAGE:
        reasons.append("usage_not_local_test_only")

    digest = raw.get("document_digest")
    if not isinstance(text, str):
        reasons.append("document_text_missing")
        text = ""
    expected_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not isinstance(digest, str) or digest != expected_digest:
        reasons.append("document_digest_mismatch")

    consent = raw.get("consent")
    contract = raw.get("contract_restriction")
    if contract == "no_train":
        reasons.append("contract_forbids_training")
    if consent == "refused" or consent == "absent":
        reasons.append("consent_refused_or_absent")
    elif consent == "recorded":
        reasons.append("consent_claim_unverified")
    elif consent != "not_required" or license_name != SYNTHETIC_LICENSE:
        if "consent_refused_or_absent" not in reasons and "consent_claim_unverified" not in reasons:
            reasons.append("consent_not_established")

    normalized = normalize_record_text(text) if text else ""
    if text:
        sanitized = sanitize_for_candidate(text)
        if sanitized.rejected or sanitized.pii_flagged:
            reasons.append("pii_or_secret")
        lowered = text.casefold()
        if any(marker in lowered for marker in _POISON):
            reasons.append("malicious_marker")
        score = _quality_score(normalized)
        if len(normalized) < 8 or score < 0.5:
            reasons.append("quality_below_floor")
    else:
        score = 0.0
        reasons.append("quality_below_floor")

    script = _script_family(normalized)
    language = str(raw.get("language") or "").casefold()
    expected_script = _SCRIPT_FOR_LANGUAGE.get(language)
    if expected_script is None or script != expected_script:
        reasons.append("language_not_identified")

    domain = str(raw.get("domain") or "")
    if domain not in {"prose", "code", "mixed"}:
        reasons.append("domain_missing")
        domain_bucket = "rejected"
    elif _looks_like_code(text, domain):
        domain_bucket = "code"
    else:
        domain_bucket = "prose"

    exact_key = hashlib.sha256(normalize_text(normalized).encode("utf-8")).hexdigest() if normalized else ""
    if exact_key:
        prior = seen_exact.get(exact_key)
        if prior is not None:
            reasons.append("exact_duplicate")
        else:
            seen_exact[exact_key] = record_id
            shingles = frozenset(word_ngrams(normalized, NEAR_DUP_WORD_NGRAM))
            window = seen_normalized[-near_dup_window:]
            if any(jaccard(shingles, other) >= NEAR_DUP_JACCARD_THRESHOLD for _, _, other in window):
                reasons.append("near_duplicate")
            seen_normalized.append((record_id, normalized, shingles))

    if _contaminates(normalized, eval_items):
        reasons.append("eval_contamination")

    unique: list[str] = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    if unique or not normalized:
        outcome = "rejected"
        split = None
        kept_bucket = "rejected"
    elif domain_bucket == "code":
        outcome = "separated_code"
        split = deterministic_split(normalized)
        kept_bucket = "code"
    else:
        outcome = "admitted_synthetic"
        split = deterministic_split(normalized)
        kept_bucket = "prose"
    return RecordDecision(
        record_id=record_id,
        record_hash=record_hash,
        outcome=outcome,
        reasons=tuple(unique),
        split=split,
        script=script,
        domain_bucket=kept_bucket,
        whitespace_tokens=len(normalized.split()) if normalized else 0,
        utf8_bytes=len(text.encode("utf-8")),
    )


def _reject_cross_split(
    decisions: Sequence[RecordDecision],
    prepared: Sequence[Mapping],
    *,
    rolled_back: bool,
) -> list[RecordDecision]:
    """Drop records whose near-duplicate sits in another split.

    Within-batch near-duplicates are already rejected. This pass covers a
    pair that fell outside the bounded near-duplicate window.
    """
    if rolled_back or len(decisions) != len(prepared):
        return list(decisions)
    grouped: dict[str, list[tuple[int, str]]] = {}
    for index, row in enumerate(decisions):
        if row.split is None:
            continue
        grouped.setdefault(row.split, []).append((index, str(prepared[index].get("text") or "")))
    if len(grouped) < 2:
        return list(decisions)
    pairs = find_near_duplicates_across_splits(
        {name: [text for _, text in rows] for name, rows in grouped.items()}
    )
    if not pairs:
        return list(decisions)
    flagged: set[int] = set()
    for split_a, idx_a, split_b, idx_b in pairs:
        flagged.add(grouped[split_a][idx_a][0])
        flagged.add(grouped[split_b][idx_b][0])
    updated: list[RecordDecision] = []
    for index, row in enumerate(decisions):
        if index not in flagged:
            updated.append(row)
            continue
        reasons = tuple(dict.fromkeys((*row.reasons, "cross_split_near_duplicate")))
        updated.append(RecordDecision(
            record_id=row.record_id,
            record_hash=row.record_hash,
            outcome="rejected",
            reasons=reasons,
            split=None,
            script=row.script,
            domain_bucket="rejected",
            whitespace_tokens=row.whitespace_tokens,
            utf8_bytes=row.utf8_bytes,
        ))
    return updated


def _contaminates(normalized: str, eval_items: Sequence[Mapping]) -> bool:
    if not normalized or not eval_items:
        return False
    prompts = []
    expected = []
    for item in eval_items:
        if not isinstance(item, Mapping):
            raise ProvenanceError("eval item must be a mapping")
        prompt = str(item.get("prompt") or "")
        answer = str(item.get("expected") or "")
        if prompt:
            prompts.append(prompt)
        if answer:
            expected.append(answer)
    protected = prompts + expected
    if find_exact_matches([normalized], protected):
        return True
    return bool(find_normalized_substring_matches([normalized], protected, min_len=40))


def _balance(admitted: Sequence[RecordDecision]) -> dict:
    by_script: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for row in admitted:
        by_script[row.script] = by_script.get(row.script, 0) + 1
        by_domain[row.domain_bucket] = by_domain.get(row.domain_bucket, 0) + 1
    return {"by_script": by_script, "by_domain": by_domain, "admitted_synthetic": len(admitted)}


def _manifest(admitted: Sequence[RecordDecision], distribution_version: str) -> dict:
    body = {
        "schema": SCHEMA,
        "corpus_class": "synthetic-fixture",
        "protected_corpus": False,
        "training_grant": False,
        "distribution_version": distribution_version,
        "record_hashes": sorted(row.record_hash for row in admitted),
    }
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    body["manifest_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return body


def _step_report(
    *,
    decisions: Sequence[RecordDecision],
    balance: Mapping,
    manifest: Mapping | None,
    rolled_back: bool,
    version_conflict: bool,
    publication_supplied: bool,
) -> tuple[dict, ...]:
    reason_set = {reason for row in decisions for reason in row.reasons}

    def checked(flag: bool) -> str:
        return "CHECKED_CLEAN" if flag else "CHECKED_REJECTIONS_PRESENT"

    if any(row.outcome == "separated_code" for row in decisions):
        code_status = "MEASURED"
    elif "domain_missing" in reason_set:
        code_status = "CHECKED_REJECTIONS_PRESENT"
    else:
        code_status = "CHECKED_CLEAN"
    rows = {
        "source_identity": checked(
            "record_id_missing" not in reason_set
            and "source_id_missing" not in reason_set
            and "source_uri_not_synthetic" not in reason_set
        ),
        "license_and_usage_rights": checked(
            "public_web_not_cleared" not in reason_set
            and "license_missing" not in reason_set
            and "license_metadata_not_a_training_grant" not in reason_set
            and "usage_restrictions_missing" not in reason_set
            and "usage_not_local_test_only" not in reason_set
        ),
        "document_provenance": checked(
            "document_digest_mismatch" not in reason_set and "document_text_missing" not in reason_set
        ),
        "consent_and_contract": checked(
            "consent_refused_or_absent" not in reason_set
            and "consent_claim_unverified" not in reason_set
            and "consent_not_established" not in reason_set
            and "contract_forbids_training" not in reason_set
        ),
        "pii_and_secrets": checked("pii_or_secret" not in reason_set),
        "quality_and_language": checked(
            "quality_below_floor" not in reason_set and "language_not_identified" not in reason_set
        ),
        "exact_and_near_duplicate": checked(
            "exact_duplicate" not in reason_set
            and "near_duplicate" not in reason_set
            and "cross_split_near_duplicate" not in reason_set
        ),
        "poison_and_malicious": checked("malicious_marker" not in reason_set),
        "code_separation": code_status,
        "language_domain_balance": "MEASURED",
        "split_isolation": checked("cross_split_near_duplicate" not in reason_set),
        "eval_contamination": checked("eval_contamination" not in reason_set),
        "removal_and_exclusion": checked(
            "removal_requested" not in reason_set and "source_excluded" not in reason_set
        ),
        "per_record_hash": "CHECKED_CLEAN" if decisions and all(len(row.record_hash) == 64 for row in decisions) else "CHECKED_REJECTIONS_PRESENT",
        "immutable_manifest": "CHECKED_CLEAN" if manifest is not None else "CHECKED_REJECTIONS_PRESENT",
        "independent_custody": "BLOCKED",
        "token_accounting": "MEASURED",
        "distribution_version": "CHECKED_REJECTIONS_PRESENT" if version_conflict else "CHECKED_CLEAN",
        "publication_rights": "BLOCKED",
        "ingestion_errors_and_rollback": "CHECKED_REJECTIONS_PRESENT" if rolled_back else "CHECKED_CLEAN",
    }
    detail = {
        "language_domain_balance": f"target UNSET; observed={balance['by_script']}",
        "independent_custody": "no custodian key is enrolled",
        "publication_rights": "supplied decision ignored" if publication_supplied else "no publication review",
        "token_accounting": ACCOUNTING_METHOD,
        "code_separation": "code records are counted apart from prose",
        "immutable_manifest": "published" if manifest is not None else "not published",
    }
    report = []
    for step_id, title in STEPS:
        report.append({
            "step_id": step_id,
            "title": title,
            "status": rows[step_id],
            "detail": detail.get(step_id, title),
        })
    return tuple(report)
