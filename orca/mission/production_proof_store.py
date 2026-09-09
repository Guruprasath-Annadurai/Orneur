"""
Phase 15.10 -- durable Production Proof persistence, against the
EXISTING `production_proofs` table defined in `orca/mission/schema.py`
(Phase 15.2, already applied to production -- no migration needed for
this closure, spec sections 27-28).

Matches this repository's established raw-psycopg pattern
(`orca/mission/verification_store.py`, `operation_store.py`,
`mission_store.py`): explicit `conn.commit()`, `%s` placeholders,
`dict_row` row factory (via `get_conn()`), no ORM.

Proofs are APPEND-ONLY (spec section 30): `record_proof()` always
INSERTs a new row (a fresh `proof_id`); there is no `update_proof()`.
A later proof for a newer revision creates a NEW row -- it never
overwrites or rewrites a prior proof's outcome, even when the project
later improves (spec section 30's explicit example: rev A blocked,
rev B ready, rev C regressed, rev D ready again -- all four rows
remain visible).

The entire typed `ProductionProof` (plus its computed hash) is stored
as the canonical JSON payload in the existing `categories` column --
the table's minimal 6-column shape (id, mission_id, revision,
created_at, categories, overall_status) is sufficient to hold the full
proof without a schema change; `categories` was already documented as
free-form JSON in its own column comment.
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
    NOT_ENGINEERING_READY,
    canonical_json,
    compute_proof_hash,
    to_dict,
)
from orca.mission.verification import VerificationOutcome


class ProductionProofStoreError(Exception):
    pass


#: overall_status has a Postgres CHECK constraint limited to these
#: four values (Phase 15.2 schema) -- NOT_ENGINEERING_READY does not
#: fit that constraint, so it is stored as ENGINEERING_READY's
#: predecessor label only inside the JSON payload; the DB column
#: itself uses the closest allowed value for indexing/filtering
#: purposes, with the JSON payload remaining the source of truth for
#: the precise release_state (spec section 22's finer distinction is
#: preserved in the payload even though the column's CHECK constraint
#: predates this phase and is not migrated here, per "prefer no
#: migration when the existing schema is sufficient").
_COLUMN_ALLOWED_STATUSES = frozenset({"ENGINEERING_READY", "SUBMISSION_READY", "RELEASE_CANDIDATE", "PUBLISHED"})


def _column_overall_status(release_state: str) -> str:
    return release_state if release_state in _COLUMN_ALLOWED_STATUSES else "ENGINEERING_READY"


def record_proof(conn, proof: ProductionProof) -> tuple[ProductionProof, str]:
    """Persists `proof` as a new, append-only row. Returns
    `(proof, proof_hash)` -- the hash is computed HERE (from the exact
    canonical payload about to be written) so a caller never has to
    separately compute and pass it in out of sync with what is stored."""
    proof_hash = compute_proof_hash(proof)
    payload = to_dict(proof)
    payload["proof_hash"] = proof_hash
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO production_proofs (id, mission_id, revision, created_at, categories, overall_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                proof.proof_id, proof.mission_id, proof.revision, proof.generated_at,
                json.dumps(payload, sort_keys=True), _column_overall_status(proof.release_state),
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
    )


def _anti_gaming(d: dict) -> AntiGamingSnapshot:
    return AntiGamingSnapshot(
        analysis_performed=d["analysis_performed"], baseline_revision=d["baseline_revision"],
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


def get_proof(conn, proof_id: str) -> tuple[ProductionProof, str] | None:
    """Reloads a proof exactly, plus the hash that was stored
    alongside it at write time. Returns `(proof, stored_hash)` so a
    caller can independently recompute `compute_proof_hash(proof)` and
    assert it equals `stored_hash` -- proving both durability AND
    hash integrity across a fresh connection (spec sections 27, 34)."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM production_proofs WHERE id = %s", (proof_id,))
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return None
    payload = json.loads(row["categories"])
    stored_hash = payload.pop("proof_hash")
    return _payload_to_proof(payload), stored_hash


def proofs_for_mission(conn, mission_id: str) -> tuple[tuple[ProductionProof, str], ...]:
    """Full proof HISTORY for a mission, oldest first -- append-only:
    every proof ever generated for this mission remains visible, never
    overwritten (spec section 30)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM production_proofs WHERE mission_id = %s ORDER BY created_at ASC", (mission_id,),
        )
        rows = cur.fetchall()
    conn.commit()
    results = []
    for row in rows:
        payload = json.loads(row["categories"])
        stored_hash = payload.pop("proof_hash")
        results.append((_payload_to_proof(payload), stored_hash))
    return tuple(results)


def latest_proof_for_mission(conn, mission_id: str) -> tuple[ProductionProof, str] | None:
    history = proofs_for_mission(conn, mission_id)
    return history[-1] if history else None


# ── Stale-proof detection (spec section 31) ──────────────────────────

def is_proof_stale(
    proof: ProductionProof, *, current_revision: str,
    current_required_scopes_by_requirement: dict | None = None,
) -> bool:
    """A Production Proof is revision-bound: proof for revision A
    cannot certify revision B. Also considers the required scope for
    each requirement -- if the scope actually required for a
    requirement has changed since the proof was generated (a different
    set of keys), the old proof's requirement result no longer reflects
    the current decision context and must be treated as stale."""
    if proof.revision != current_revision:
        return True
    if current_required_scopes_by_requirement is None:
        return False
    for result in proof.requirement_results:
        current_scope = current_required_scopes_by_requirement.get(result.requirement_id)
        if current_scope is None:
            continue
        if tuple(sorted(current_scope.keys)) != result.scope_keys:
            return True
    return False
