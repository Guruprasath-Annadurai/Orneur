"""
Phase 15.10 -- durable Production Proof persistence, against the
`production_proofs` table defined in `orca/mission/schema.py` (Phase
15.2). Matches this repository's established raw-psycopg pattern
(`orca/mission/verification_store.py`, `operation_store.py`,
`mission_store.py`): explicit `conn.commit()`, `%s` placeholders,
`dict_row` row factory (via `get_conn()`), no ORM.

Proofs are APPEND-ONLY (spec section 30): `record_proof()` always
INSERTs a new row (a fresh `proof_id`); there is no `update_proof()`.

PHASE 15.10.1 CLOSURE item 8 (OVERALL-STATUS INTEGRITY): the original
Phase 15.10 implementation silently mapped `NOT_ENGINEERING_READY` to
`'ENGINEERING_READY'` for the `overall_status` column, because the
Phase 15.2 CHECK constraint only allows the 4 canonical `LaunchReadiness`
values -- a blocked proof's DURABLE ROW claimed the software was
engineering-ready. This was a hard integrity defect: a durable index
must never contradict its canonical payload.

`record_proof()` now writes `proof.release_state` EXACTLY, with no
translation. Against the CURRENT (unmigrated) production schema, this
means writing a `NOT_ENGINEERING_READY` proof will raise a Postgres
CHECK-constraint violation rather than silently lying -- this is the
intended, honest interim behavior until the migration in
`orca/mission/production_proof_schema.py` (validated on a disposable
Neon branch, NOT applied to production without explicit owner
approval -- see PHASE15_EVIDENCE.md's "PHASE 15.10.1" section) is
approved and applied. `get_proof()`/`proofs_for_mission()` additionally
detect (and refuse to silently accept) any row whose `overall_status`
column disagrees with its own JSON payload's `release_state`.
"""
from __future__ import annotations

import json

from orca.mission.production_proof import (
    AntiGamingSnapshot,
    CourtSnapshot,
    DeploymentResult,
    DeploymentState,
    ProductionProof,
    ProofCategory,
    RegressionResult,
    RequirementResult,
    RollbackResult,
    TestCategoryResult,
    compute_proof_hash,
    is_proof_stale,
    to_dict,
)
from orca.mission.verification import VerificationOutcome

__all__ = [
    "ProductionProofStoreError",
    "record_proof",
    "get_proof",
    "proofs_for_mission",
    "latest_proof_for_mission",
    "is_proof_stale",
]


class ProductionProofStoreError(Exception):
    pass


#: The Phase 15.2 CHECK constraint's current allowed values. Any
#: `release_state` outside this set (i.e. `NOT_ENGINEERING_READY`)
#: cannot be written to the CURRENT schema at all -- see module
#: docstring. This set is used only to give a clear, actionable error
#: message before the raw Postgres exception would otherwise surface.
_CURRENT_SCHEMA_ALLOWED_STATUSES = frozenset({
    "ENGINEERING_READY", "SUBMISSION_READY", "RELEASE_CANDIDATE", "PUBLISHED",
})


def record_proof(conn, proof: ProductionProof) -> tuple[ProductionProof, str]:
    """Persists `proof` as a new, append-only row, writing
    `proof.release_state` EXACTLY into `overall_status` -- no lying
    translation (Phase 15.10.1 closure item 8). Returns `(proof,
    proof_hash)`."""
    proof_hash = compute_proof_hash(proof)
    payload = to_dict(proof)
    payload["proof_hash"] = proof_hash
    if proof.release_state not in _CURRENT_SCHEMA_ALLOWED_STATUSES:
        raise ProductionProofStoreError(
            f"record_proof(): release_state {proof.release_state!r} cannot be written to the "
            f"CURRENT production_proofs.overall_status CHECK constraint (Phase 15.2 schema, "
            f"limited to {sorted(_CURRENT_SCHEMA_ALLOWED_STATUSES)!r}). The Phase 15.10.1 "
            f"migration that widens this constraint has been validated on a disposable Neon "
            f"branch but NOT applied to production pending explicit owner approval -- see "
            f"orca/mission/production_proof_schema.py and PHASE15_EVIDENCE.md's 'PHASE 15.10.1' "
            f"section. This proof cannot be durably persisted with its true release_state until "
            f"that migration is approved and applied; it is NOT silently mislabeled as "
            f"ENGINEERING_READY."
        )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO production_proofs (id, mission_id, revision, created_at, categories, overall_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                proof.proof_id, proof.mission_id, proof.revision, proof.generated_at,
                json.dumps(payload, sort_keys=True), proof.release_state,
            ),
        )
    conn.commit()
    return proof, proof_hash


def _outcome(value) -> VerificationOutcome:
    return VerificationOutcome(value)


def _category(d: dict) -> ProofCategory:
    return ProofCategory(
        status=_outcome(d["status"]), summary=d["summary"], evidence_refs=tuple(d["evidence_refs"]),
        not_applicable_reason=d.get("not_applicable_reason"),
    )


def _test_category(d: dict) -> TestCategoryResult:
    return TestCategoryResult(
        status=_outcome(d["status"]), collected=d["collected"], passed=d["passed"], failed=d["failed"],
        skipped=d["skipped"], errors=d["errors"], duration_seconds=d["duration_seconds"],
        revision=d["revision"], evidence_refs=tuple(d["evidence_refs"]), summary=d["summary"],
    )


def _regression(d: dict) -> RegressionResult:
    return RegressionResult(
        baseline_revision=d["baseline_revision"], candidate_revision=d["candidate_revision"],
        baseline_collected=d["baseline_collected"], candidate_collected=d["candidate_collected"],
        new_tests=tuple(d["new_tests"]), removed_tests=tuple(d["removed_tests"]),
        new_failures=tuple(d["new_failures"]), resolved_failures=tuple(d["resolved_failures"]),
        known_pre_existing_failures=tuple(d["known_pre_existing_failures"]), notes=d["notes"],
    )


def _court(d: dict) -> CourtSnapshot:
    return CourtSnapshot(
        decision_id=d["decision_id"], mission_id=d["mission_id"], revision=d["revision"],
        risk_level=d["risk_level"], roles_invoked=tuple(d["roles_invoked"]), verdict=d["verdict"],
        findings_considered=tuple(d["findings_considered"]), verification_refs=tuple(d["verification_refs"]),
        reasoning_summary=d["reasoning_summary"], durable=d["durable"],
        evidence_source=d["evidence_source"], context_bound=d["context_bound"],
    )


def _anti_gaming(d: dict) -> AntiGamingSnapshot:
    return AntiGamingSnapshot(
        analysis_performed=d["analysis_performed"], analysis_id=d.get("analysis_id"),
        baseline_revision=d["baseline_revision"],
        candidate_revision=d["candidate_revision"], blocking_finding_ids=tuple(d["blocking_finding_ids"]),
        critical_finding_ids=tuple(d["critical_finding_ids"]), total_findings=d["total_findings"],
        detector_ids=tuple(d["detector_ids"]),
    )


def _deployment(d: dict) -> DeploymentResult:
    return DeploymentResult(
        state=DeploymentState(d["state"]), revision=d["revision"], environment_identity=d["environment_identity"],
        deployed_at=d["deployed_at"], notes=d["notes"],
    )


def _rollback(d: dict) -> RollbackResult:
    return RollbackResult(
        strategy_documented=d["strategy_documented"], procedure_tested=d["procedure_tested"],
        proven_for_current_deployment=d["proven_for_current_deployment"], method=d["method"], notes=d["notes"],
    )


def _requirement_result(d: dict) -> RequirementResult:
    return RequirementResult(
        requirement_id=d["requirement_id"], scope_keys=tuple(d["scope_keys"]), outcome=_outcome(d["outcome"]),
        contributing_record_ids=tuple(d["contributing_record_ids"]), missing_keys=tuple(d["missing_keys"]),
        limitations=d["limitations"],
    )


def _payload_to_proof(payload: dict) -> ProductionProof:
    return ProductionProof(
        proof_id=payload["proof_id"], mission_id=payload["mission_id"], repository=payload["repository"],
        branch=payload["branch"], base_revision=payload["base_revision"], revision=payload["revision"],
        generated_at=payload["generated_at"], proof_schema_version=payload["proof_schema_version"],
        generator_id=payload["generator_id"], generator_version=payload["generator_version"],
        decision_context_fingerprint=payload["decision_context_fingerprint"],
        required_requirement_ids=tuple(payload["required_requirement_ids"]),
        requirement_results=tuple(_requirement_result(r) for r in payload["requirement_results"]),
        requirements_satisfied=tuple(payload["requirements_satisfied"]),
        requirements_unresolved=tuple(payload["requirements_unresolved"]),
        requirements_failed=tuple(payload["requirements_failed"]),
        build=_category(payload["build"]), unit_tests=_test_category(payload["unit_tests"]),
        integration_tests=_test_category(payload["integration_tests"]), e2e_tests=_test_category(payload["e2e_tests"]),
        regression=_regression(payload["regression"]), security=_category(payload["security"]),
        authority=_category(payload["authority"]), anti_test_gaming=_anti_gaming(payload["anti_test_gaming"]),
        cognitive_court=_court(payload["cognitive_court"]),
        supply_chain=_category(payload["supply_chain"]), licensing=_category(payload["licensing"]),
        accessibility=_category(payload["accessibility"]), performance=_category(payload["performance"]),
        release_build=_category(payload["release_build"]), deployment=_deployment(payload["deployment"]),
        post_deploy_smoke=_category(payload["post_deploy_smoke"]), rollback=_rollback(payload["rollback"]),
        known_limitations=tuple(payload["known_limitations"]),
        unverified_assumptions=tuple(payload["unverified_assumptions"]),
        blockers=tuple(payload["blockers"]), warnings=tuple(payload["warnings"]),
        evidence_refs=tuple(payload["evidence_refs"]),
        artifact_hashes=tuple(tuple(x) for x in payload["artifact_hashes"]),
        verifier_versions=tuple(tuple(x) for x in payload["verifier_versions"]),
        tool_versions=tuple(tuple(x) for x in payload["tool_versions"]),
        release_state=payload["release_state"],
    )


def _row_to_proof(row: dict) -> tuple[ProductionProof, str]:
    """Phase 15.10.1 closure item 8: detects (and refuses to silently
    accept) a row whose SQL `overall_status` column disagrees with its
    own JSON payload's `release_state` -- a durable index must never
    contradict its canonical payload."""
    payload = json.loads(row["categories"])
    stored_hash = payload.pop("proof_hash")
    proof = _payload_to_proof(payload)
    if row["overall_status"] != proof.release_state:
        raise ProductionProofStoreError(
            f"production_proofs row {row['id']!r}: SQL overall_status "
            f"{row['overall_status']!r} does not match its own JSON payload's "
            f"release_state {proof.release_state!r} -- refusing to silently accept "
            f"contradictory durable state (Phase 15.10.1 closure item 8)."
        )
    return proof, stored_hash


def get_proof(conn, proof_id: str) -> tuple[ProductionProof, str] | None:
    """Reloads a proof exactly, plus the hash that was stored alongside
    it at write time. Returns `(proof, stored_hash)`."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM production_proofs WHERE id = %s", (proof_id,))
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    return _row_to_proof(dict(row))


def proofs_for_mission(conn, mission_id: str) -> tuple[tuple[ProductionProof, str], ...]:
    """Full proof HISTORY for a mission, oldest first -- append-only."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM production_proofs WHERE mission_id = %s ORDER BY created_at ASC", (mission_id,),
        )
        rows = cur.fetchall()
    conn.commit()
    return tuple(_row_to_proof(dict(r)) for r in rows)


def latest_proof_for_mission(conn, mission_id: str) -> tuple[ProductionProof, str] | None:
    history = proofs_for_mission(conn, mission_id)
    return history[-1] if history else None
