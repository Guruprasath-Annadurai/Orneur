"""Manual review pipeline with cryptographically bound decisions (fallback / complement to the local semantic engine).

Public review artifacts carry opaque ids, digests and dispositions ONLY. A decision binds: item id, eval version, reviewer identity + role + key, purpose,
the exact corpus digest, the digest of the similarity evidence the reviewer saw, disposition, timestamp and schema version, under an Ed25519 signature by a
reviewer key registered in TRUSTED_REVIEWER_KEYS.json (empty today => no review can validate). Content review happens privately; only the decision is public.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import spec

SCHEMA_VERSION = "genesis-v2-manual-review/1"
KEYS_PATH = "docs/orneur/authorization/TRUSTED_REVIEWER_KEYS.json"  # deprecated; kept only as a legacy artifact, no longer read (see REVIEWER_REGISTRY.json)
DISPOSITIONS = ("CLEAR", "REJECT_CONTAMINATED", "NEEDS_REGENERATION", "INCONCLUSIVE")
PURPOSES = ("CONTAMINATION_REVIEW", "SPLIT_ISOLATION_REVIEW", "STRUCTURAL_UNASSESSABLE_REVIEW", "SEMANTIC_AMBIGUITY_REVIEW", "FULL_MANUAL_REVIEW")
ROLES = ("PRIVATE_BENCHMARK_REVIEWER", "OWNER")
REVIEW_KEYS = frozenset({"review_schema_version", "item_id", "eval_version", "reviewer", "review_purpose", "corpus_digest", "similarity_evidence_digest",
                         "disposition", "timestamp", "signature"})
MANIFEST_KEYS = frozenset({"review_schema_version", "eval_version", "corpus_digest", "reviews", "manifest_sha256"})
_ID = re.compile(r"^gce2-[0-9a-f]{24}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def evidence_digest(item_id: str, findings: list) -> str:
    """Digest of the (ids/scores-only) similarity evidence for one item; decisions bind to it so stale reviews cannot be reused."""
    rel = sorted((json.dumps(f, sort_keys=True) for f in findings if item_id in (f.get("v2"), f.get("screen"), f.get("holdout"), f.get("item"))))
    return hashlib.sha256(json.dumps([item_id, rel], sort_keys=True).encode()).hexdigest()


def signing_bytes(review: dict) -> bytes:
    return json.dumps({k: v for k, v in review.items() if k != "signature"}, sort_keys=True, separators=(",", ":")).encode()


def manifest_hash(m: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in m.items() if k != "manifest_sha256"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_manifest(reviews: list, corpus_digest: str) -> dict:
    m = {"review_schema_version": SCHEMA_VERSION, "eval_version": spec.EVAL_VERSION, "corpus_digest": corpus_digest, "reviews": reviews}
    m["manifest_sha256"] = manifest_hash(m)
    return m


def load_keys(root: Path) -> list:
    """Active reviewer public keys, derived from the canonical REVIEWER_REGISTRY.json (see reviewer_registry.py)."""
    from orca.eval.genesis_v2 import reviewer_registry as RR
    doc, problems = RR.load(Path(root) / RR.REGISTRY_PATH)
    if problems or doc is None:
        return []
    return RR.active_reviewer_keys(doc)


def _verify_sig(review: dict, keys: list) -> str | None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        return "SIGNATURE_VERIFIER_UNAVAILABLE"
    rv = review["reviewer"]
    key = next((k for k in keys if isinstance(k, dict) and k.get("key_id") == rv.get("key_id")), None)
    if key is None or key.get("identity") != rv.get("identity") or key.get("role") != rv.get("role"):
        return "REVIEWER_KEY_NOT_REGISTERED"
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"])).verify(bytes.fromhex(str(review["signature"])), signing_bytes(review))
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return "SIGNATURE_INVALID"
    return None


def validate_manifest(m, keys: list, expected_corpus_digest: str) -> list:
    """Problems (empty == every review is well-formed, bound to this corpus, and validly signed by a registered reviewer)."""
    if not isinstance(m, dict) or set(m) != MANIFEST_KEYS:
        return ["MANIFEST_SCHEMA_MISMATCH"]
    p = []
    if m["review_schema_version"] != SCHEMA_VERSION or m["eval_version"] != spec.EVAL_VERSION:
        p.append("SCHEMA_OR_EVAL_VERSION_MISMATCH")
    if m["corpus_digest"] != expected_corpus_digest or not _HEX.match(str(m["corpus_digest"])):
        p.append("CORPUS_DIGEST_MISMATCH")
    if m["manifest_sha256"] != manifest_hash(m):
        p.append("MANIFEST_HASH_MISMATCH")
    if not isinstance(m["reviews"], list):
        return p + ["REVIEWS_NOT_A_LIST"]
    for r in m["reviews"]:
        if not isinstance(r, dict) or set(r) != REVIEW_KEYS:
            p.append("REVIEW_SCHEMA_MISMATCH")
            continue
        rv = r["reviewer"]
        if not _ID.match(str(r["item_id"])):
            p.append("ITEM_ID_NOT_OPAQUE")
        if r["review_schema_version"] != SCHEMA_VERSION or r["eval_version"] != spec.EVAL_VERSION or r["corpus_digest"] != expected_corpus_digest:
            p.append("REVIEW_NOT_BOUND_TO_THIS_CORPUS")
        if r["disposition"] not in DISPOSITIONS or r["review_purpose"] not in PURPOSES:
            p.append("DISPOSITION_OR_PURPOSE_INVALID")
        if not (isinstance(rv, dict) and set(rv) == {"identity", "role", "key_id"} and rv["role"] in ROLES and rv["identity"] and rv["key_id"]):
            p.append("REVIEWER_INVALID")
            continue
        if not _HEX.match(str(r["similarity_evidence_digest"])) or not _TS.match(str(r["timestamp"])):
            p.append("EVIDENCE_DIGEST_OR_TIMESTAMP_INVALID")
        if not keys:
            p.append("NO_TRUSTED_REVIEWER_KEY_REGISTERED")
        else:
            s = _verify_sig(r, keys)
            if s:
                p.append(s)
    return sorted(set(p))


def review_status(m, required: dict, keys: list, expected_corpus_digest: str, name: str = "manual_review") -> C.CheckResult:
    """required: {item_id: evidence_digest}. PASS only if EVERY required item's latest valid review is CLEAR against the current evidence digest.
    REJECT_CONTAMINATED / NEEDS_REGENERATION => FAIL. INCONCLUSIVE, missing or stale-evidence reviews => INCOMPLETE (never PASS)."""
    if not required:
        return C.CheckResult(name, C.PASS, [], "no item requires manual review")
    problems = validate_manifest(m, keys, expected_corpus_digest)
    if problems:
        return C.CheckResult(name, C.FAIL, [{"problem": x} for x in problems], "review manifest invalid")
    latest = {}
    for r in sorted(m["reviews"], key=lambda r: r["timestamp"]):
        latest[r["item_id"]] = r
    fail, inc = [], []
    for iid, ev in required.items():
        r = latest.get(iid)
        if r is None:
            inc.append({"item": iid, "why": "NOT_REVIEWED"})
        elif r["similarity_evidence_digest"] != ev:
            inc.append({"item": iid, "why": "STALE_EVIDENCE"})
        elif r["disposition"] in ("REJECT_CONTAMINATED", "NEEDS_REGENERATION"):
            fail.append({"item": iid, "disposition": r["disposition"]})
        elif r["disposition"] == "INCONCLUSIVE":
            inc.append({"item": iid, "why": "INCONCLUSIVE"})
    if fail:
        return C.CheckResult(name, C.FAIL, fail + inc, "items rejected or need regeneration")
    if inc:
        return C.CheckResult(name, C.INCOMPLETE, inc, "unreviewed, stale or INCONCLUSIVE items")
    return C.CheckResult(name, C.PASS, [], f"{len(required)} items reviewed CLEAR against current evidence")


def review_requirements(items: list, contamination_results: list, iso_limited_categories: set, semantic_result: C.CheckResult | None = None) -> dict:
    """Items needing private manual review: structurally unassessable, in a limited-structure category, or in the semantic ambiguity band.
    Returns {item_id: evidence_digest}."""
    findings = [f for r in contamination_results for f in r.findings]
    if semantic_result is not None:
        findings += semantic_result.findings
    need = set()
    for r in contamination_results:
        if r.name == "v1_structure_assessability":
            need |= {f["v2"] for f in r.findings}
    need |= {i["item_id"] for i in items if i.get("category") in iso_limited_categories}
    if semantic_result is not None:
        need |= {f["v2"] for f in semantic_result.findings if f.get("band") == "AMBIGUOUS"}
    return {i: evidence_digest(i, findings) for i in sorted(need)}


def combine_semantic_and_manual(semantic: C.CheckResult, manual_flagged: C.CheckResult, manual_full: C.CheckResult | None = None) -> C.CheckResult:
    """The mandatory 'semantic_overlap' check. PASS iff (an accepted local semantic engine PASSED and every flagged item was cleared by review)
    OR (a FULL manual review of every item is CLEAR). Anything else is never PASS."""
    if manual_full is not None and manual_full.status == C.PASS:
        return C.CheckResult("semantic_overlap", C.PASS, [], "full manual review of every item: CLEAR")
    if semantic.status == C.PASS and manual_flagged.status == C.PASS:
        return C.CheckResult("semantic_overlap", C.PASS, [], "local semantic engine PASS + flagged items cleared by manual review")
    for res in (semantic, manual_flagged, manual_full):
        if res is not None and res.status == C.FAIL:
            return C.CheckResult("semantic_overlap", C.FAIL, res.findings, f"{res.name} FAIL")
    if semantic.status == C.NOT_CONFIGURED:
        return C.CheckResult("semantic_overlap", C.NOT_CONFIGURED, [], "no configured semantic engine and no complete manual review; semantic review not performed")
    return C.CheckResult("semantic_overlap", C.INCOMPLETE, [], "semantic/manual review incomplete")
