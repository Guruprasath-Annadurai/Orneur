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

# bindings that can only be filled once the private corpus itself exists; they MUST be null in a draft. Everything else (code hashes, runner
# identity, storage verification digest, resource/spend limits) can be bound honestly before any corpus exists, once the owner environment is set up.
DEFERRED = ("private_corpus_aggregate_commitment",)

# A filled JSON binding is not automatically an APPROVED one (audit finding: "22/23 filled must NOT be interpreted as 22/23 approved").
# binding_status makes that distinction explicit per binding:
#   BOUND                  — a real, non-corpus-dependent value (protocol/design constant, a computed hash of committed code, etc.)
#                             that needs no further operational qualification to be trustworthy as bound.
#   OPERATIONALLY_CONFIGURED — bound to a real running system/artifact that exists and works, but is NOT yet independently qualified
#                             (e.g. sandbox_ready=false, semantic engine CONFIGURED_LOCAL_ONLY not QUALIFIED, runner REGISTERED_NOT_AUTHORIZED).
#   QUALIFIED               — bound AND independently audited/approved. Nothing reaches this state before independent ChatGPT audit.
#   DEFERRED                — intentionally null; only legal for keys in DEFERRED.
#   NOT_APPLICABLE          — reserved for a future binding that does not apply in the current phase.
BINDING_STATUS_VALUES = ("BOUND", "OPERATIONALLY_CONFIGURED", "QUALIFIED", "DEFERRED", "NOT_APPLICABLE")


def validate_binding_status(d) -> list:
    p = []
    bs = d.get("binding_status")
    if not isinstance(bs, dict) or set(bs) != set(BINDINGS):
        return [f"binding_status must cover exactly {sorted(BINDINGS)}"]
    b = d.get("bindings") or {}
    for k, v in bs.items():
        if v not in BINDING_STATUS_VALUES:
            p.append(f"binding_status[{k}]: must be one of {BINDING_STATUS_VALUES}")
        elif k in DEFERRED:
            if v != "DEFERRED":
                p.append(f"binding_status[{k}]: a DEFERRED binding must have binding_status DEFERRED")
        elif v == "DEFERRED":
            p.append(f"binding_status[{k}]: DEFERRED is only legal for {DEFERRED}")
        elif v == "QUALIFIED" and b.get(k) is None:
            p.append(f"binding_status[{k}]: cannot be QUALIFIED while the binding itself is null")
    return p


def schema() -> dict:
    return {"schema_version": SCHEMA_VERSION, "required_top_level": ["schema_version", "status", "frozen", "bindings", "binding_status", "floors_status",
                                                                       "first_candidate_run_at", "candidate_results", "frozen_at", "record_sha256"],
            "required_bindings": list(BINDINGS), "deferred_until_corpus_exists": list(DEFERRED), "binding_status_values": list(BINDING_STATUS_VALUES),
            "status_values": ["DRAFT_NOT_FROZEN", "FROZEN"], "floors_status_values": ["PROPOSED_NOT_LOCKED", "LOCKED"],
            "rules": ["a FROZEN record has every binding non-null and floors LOCKED", "candidate_results must be empty until frozen_at is set",
                      "floors may not change after freeze or after first_candidate_run_at", "record_sha256 covers every other field",
                      "a filled binding is not automatically an approved one: binding_status distinguishes BOUND/OPERATIONALLY_CONFIGURED/QUALIFIED/DEFERRED/NOT_APPLICABLE per binding"]}


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
            p.append(f"{k} can only be bound after the private corpus exists and must be null in a draft")
    for k in BINDINGS:
        if k not in DEFERRED and b.get(k) is None:
            p.append(f"{k} must be honestly bound before freeze-readiness (only {DEFERRED} may remain null in a draft)")
    if d.get("floors_status") != "PROPOSED_NOT_LOCKED":
        p.append("draft floors must be PROPOSED_NOT_LOCKED")
    if b["eval_version"] != spec.EVAL_VERSION or b["corpus_version"] != spec.CORPUS_VERSION:
        p.append("eval/corpus version mismatch")
    p += validate_binding_status(d)
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
    p += validate_binding_status(d)
    if d.get("record_sha256") != record_hash(d):
        p.append("record_sha256 mismatch")
    return p


def assert_floors_unchanged(frozen: dict, current: dict) -> None:
    """No floor may change once the record is frozen (or a candidate has run). Raises ValueError."""
    if frozen.get("status") == "FROZEN" or frozen.get("first_candidate_run_at"):
        if frozen["bindings"]["floors"] != current["bindings"]["floors"]:
            raise ValueError("floors are immutable after freeze / first candidate run")
