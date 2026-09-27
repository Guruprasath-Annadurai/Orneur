"""Genesis Capability Eval V2 preregistration: schema + draft/freeze validators. DRAFT ONLY in this phase: nothing is frozen, no candidate has a result,
and no floor may change after freeze or after the first candidate run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orca.eval.genesis_v2 import spec

SCHEMA_VERSION = "genesis-v2-preregistration/1"
DRAFT_PATH = "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json"
SCHEMA_PATH = "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_SCHEMA.json"

BINDINGS = ("eval_version", "corpus_version", "private_corpus_aggregate_commitment", "category_counts", "gating_report_only_status", "floors", "scoring_algorithms",
            "confidence_statistical_method", "template_cluster_methodology", "screen_policy", "qualification_holdout_policy", "contamination_algorithm_versions",
            "semantic_review_mechanism_version", "sandbox_policy_version", "model_run_constraints", "allowed_candidate_lineage_rules", "stage_protocols",
            "resource_spend_limits", "trainability_protocol", "latency_cost_protocols", "code_hashes", "runner_identity", "storage_verification_digest")

# bindings that can only be filled once the private corpus / vault / runner exist; they MUST be null in a draft
DEFERRED = ("private_corpus_aggregate_commitment", "code_hashes", "runner_identity", "storage_verification_digest", "resource_spend_limits")


def schema() -> dict:
    return {"schema_version": SCHEMA_VERSION, "required_top_level": ["schema_version", "status", "frozen", "bindings", "floors_status", "first_candidate_run_at",
                                                                       "candidate_results", "frozen_at", "record_sha256"],
            "required_bindings": list(BINDINGS), "deferred_until_corpus_exists": list(DEFERRED),
            "status_values": ["DRAFT_NOT_FROZEN", "FROZEN"], "floors_status_values": ["PROPOSED_NOT_LOCKED", "LOCKED"],
            "rules": ["a FROZEN record has every binding non-null and floors LOCKED", "candidate_results must be empty until frozen_at is set",
                      "floors may not change after freeze or after first_candidate_run_at", "record_sha256 covers every other field"]}


def record_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in d.items() if k != "record_sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_draft(d) -> list:
    p = []
    if not isinstance(d, dict) or d.get("schema_version") != SCHEMA_VERSION:
        return ["schema_version mismatch"]
    if d.get("status") != "DRAFT_NOT_FROZEN" or d.get("frozen") is not False or d.get("frozen_at") is not None:
        p.append("a draft must be DRAFT_NOT_FROZEN with frozen=false and no frozen_at")
    if d.get("candidate_results") != [] or d.get("first_candidate_run_at") is not None:
        p.append("no candidate results may exist before freeze")
    b = d.get("bindings")
    if not isinstance(b, dict) or set(b) != set(BINDINGS):
        return p + ["bindings must be exactly the required set"]
    for k in DEFERRED:
        if b[k] is not None:
            p.append(f"{k} can only be bound after the corpus/vault/runner exist and must be null in a draft")
    if d.get("floors_status") != "PROPOSED_NOT_LOCKED":
        p.append("draft floors must be PROPOSED_NOT_LOCKED")
    if b["eval_version"] != spec.EVAL_VERSION or b["corpus_version"] != spec.CORPUS_VERSION:
        p.append("eval/corpus version mismatch")
    if d.get("record_sha256") != record_hash(d):
        p.append("record_sha256 mismatch")
    return p


def validate_for_freeze(d) -> list:
    """Everything that must be true before a record may claim FROZEN. The draft never satisfies this."""
    p = []
    if not isinstance(d, dict) or d.get("schema_version") != SCHEMA_VERSION:
        return ["schema_version mismatch"]
    b = d.get("bindings") or {}
    for k in BINDINGS:
        if b.get(k) is None:
            p.append(f"binding {k} is not bound")
    if d.get("status") != "FROZEN" or d.get("frozen") is not True or not d.get("frozen_at"):
        p.append("record is not FROZEN")
    if d.get("floors_status") != "LOCKED":
        p.append("floors are not LOCKED")
    if d.get("candidate_results") and not d.get("frozen_at"):
        p.append("candidate results exist before freeze")
    if d.get("record_sha256") != record_hash(d):
        p.append("record_sha256 mismatch")
    return p


def assert_floors_unchanged(frozen: dict, current: dict) -> None:
    """No floor may change once the record is frozen (or a candidate has run). Raises ValueError."""
    if frozen.get("status") == "FROZEN" or frozen.get("first_candidate_run_at"):
        if frozen["bindings"]["floors"] != current["bindings"]["floors"]:
            raise ValueError("floors are immutable after freeze / first candidate run")
