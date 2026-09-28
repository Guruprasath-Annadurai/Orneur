"""Single deterministic owner-setup preflight: everything WORKSTREAM 11 asks for, in one place. Never generates a corpus, secret or key; only reports."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from orca.eval.genesis_v2 import authority_registry as AR
from orca.eval.genesis_v2 import closure_manifest as CM
from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import inventory as INV
from orca.eval.genesis_v2 import prereg as PR
from orca.eval.genesis_v2 import reviewer_registry as RR
from orca.eval.genesis_v2 import runner_registry as RN
from orca.eval.genesis_v2 import secret_manager as SM
from orca.eval.genesis_v2 import spec

SCHEMA_VERSION = "genesis-v2-owner-preflight/1"


def _current_main_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def run(root: Path) -> dict:
    root = Path(root)
    checks: dict = {}

    vault_rec = json.loads((root / "docs/orneur/phase-21/GENESIS_V2_VAULT_VERIFICATION.json").read_text()) if (root / "docs/orneur/phase-21/GENESIS_V2_VAULT_VERIFICATION.json").is_file() else None
    checks["vault_verification_record_present_and_pass"] = bool(vault_rec and vault_rec.get("pass") is True)

    checks["secret_manager_policy_valid"] = SM.validate_policy() == []
    checks["secret_manager_mechanism_available"] = SM.probe_secret_manager()["available"]

    ar_doc, ar_problems = AR.load(root / AR.REGISTRY_PATH)
    checks["authority_registry_valid"] = ar_doc is not None and not ar_problems
    checks["authority_key_registered_and_valid"] = bool(ar_doc is not None and not ar_problems and AR.active_authority_keys(ar_doc))
    rr_doc, rr_problems = RR.load(root / RR.REGISTRY_PATH)
    checks["reviewer_registry_valid"] = rr_doc is not None and not rr_problems
    checks["separation_of_duties_clean"] = bool(ar_doc is not None and rr_doc is not None and not RR.check_separation_of_duties(ar_doc, rr_doc))
    reviewer_path_operational = bool(rr_doc is not None and not rr_problems and rr_doc.get("records"))

    inv = json.loads((root / INV.INVENTORY_PATH).read_text())
    active_keys = AR.active_authority_keys(ar_doc) if ar_doc else None
    policy_path = root / "docs/orneur/phase-21/GENESIS_V2_UNAVAILABLE_CORPUS_ACCEPTANCE_POLICY.json"
    acceptance_policy = json.loads(policy_path.read_text()) if policy_path.is_file() else None
    checks["corpus_inventory_state_known"] = True   # always knowable; PASS is a separate, harder bar tracked below
    # The pre-corpus gate: is the owner's SIGNED attestation itself valid (real signature, digest binding, honest declarations,
    # unresolved classes covered by a frozen policy)? This is deliberately narrower than full contamination qualification below,
    # which structurally cannot PASS before the private corpus exists (nothing to resolve/compare yet) — requiring that here would
    # make corpus_inventory_attested_pass permanently unsatisfiable pre-corpus, a stage-boundary defect, not a real safeguard.
    pre_corpus_res = INV.evaluate_pre_corpus_attestation(inv, authority_keys=active_keys, acceptance_policy=acceptance_policy)
    checks["corpus_inventory_attested_pass"] = pre_corpus_res.status == C.PASS
    # Informational only, never a hard requirement pre-corpus: full contamination qualification remains fail-closed and correctly
    # cannot reach PASS until a real V2 corpus exists to compare against (source resolvability, hashes, contamination_check_status).
    full_res = INV.evaluate(inv, root, authority_keys=active_keys)
    checks["corpus_inventory_full_contamination_qualification_status"] = full_res.status

    sem_rec_path = root / "docs/orneur/phase-21/GENESIS_V2_SEMANTIC_ENGINE_RECORD.json"
    sem_rec = json.loads(sem_rec_path.read_text()) if sem_rec_path.is_file() else None
    checks["semantic_engine_configured"] = bool(sem_rec and sem_rec.get("state") == "CONFIGURED_LOCAL_ONLY")
    checks["semantic_or_reviewer_path_operational"] = checks["semantic_engine_configured"] or reviewer_path_operational

    # Cross-check: the canonical status file's contamination_status.semantic_overlap must agree with the semantic-engine record's
    # actual `state` (an audit finding: these had drifted — record said CONFIGURED_LOCAL_ONLY while status said NOT_CONFIGURED).
    SEMANTIC_STATE_TO_STATUS = {"CONFIGURED_LOCAL_ONLY": "CONFIGURED_LOCAL_ONLY_NOT_QUALIFIED", "NOT_CONFIGURED": "NOT_CONFIGURED"}
    status_path = root / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json"
    status_doc = json.loads(status_path.read_text()) if status_path.is_file() else {}
    reported_semantic = (status_doc.get("contamination_status") or {}).get("semantic_overlap")
    expected_semantic = SEMANTIC_STATE_TO_STATUS.get((sem_rec or {}).get("state"))
    checks["canonical_status_agrees_with_semantic_engine_record"] = bool(expected_semantic is not None and reported_semantic == expected_semantic)

    sandbox_rec_path = root / "docs/orneur/phase-21/GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json"
    sandbox_rec = json.loads(sandbox_rec_path.read_text()) if sandbox_rec_path.is_file() else None
    checks["sandbox_image_pinned_by_digest"] = bool(sandbox_rec and sandbox_rec.get("image_digest"))
    checks["sandbox_containment_evidence_present"] = bool(sandbox_rec and sandbox_rec.get("containment_test_result_digest"))
    checks["sandbox_exact_sha_evidence_valid"] = bool(sandbox_rec and sandbox_rec.get("tested_implementation_sha")
                                                       and sandbox_rec["tested_implementation_sha"] != "PENDING_COMMIT_WILL_BE_SET_AT_PUSH_TIME")
    checks["sandbox_ready"] = bool(sandbox_rec and sandbox_rec.get("sandbox_ready") is True)

    runner_qual_path = root / "docs/orneur/phase-21/GENESIS_V2_QUALIFICATION_RUNNER_QUALIFICATION_RECORD.json"
    runner_qual = json.loads(runner_qual_path.read_text()) if runner_qual_path.is_file() else None
    checks["qualification_runner_qualified"] = bool(runner_qual and runner_qual.get("same_environment_proof", {}).get("match") is True)
    checks["sandbox_runner_class_matches_qualification_runner"] = bool(
        runner_qual and sandbox_rec
        and runner_qual["same_environment_proof"]["sandbox_test_runner_class"] == sandbox_rec.get("test_runner_class")
        and runner_qual["same_environment_proof"]["qualification_runner_class"] == runner_qual["machine_facts"]["runner_class"])

    rn_doc = json.loads((root / RN.REGISTRY_PATH).read_text())
    checks["runner_identity_registered"] = RN.validate(rn_doc) == [] and len(rn_doc["records"]) > 0
    checks["runner_not_authorized_for_holdout_yet"] = RN.to_ledger_registered_processes(rn_doc) == {}   # REGISTERED_NOT_AUTHORIZED grants nothing

    ledger_rec_path = root / "docs/orneur/phase-21/GENESIS_V2_LEDGER_DEPLOYMENT_RECORD.json"
    ledger_rec = json.loads(ledger_rec_path.read_text()) if ledger_rec_path.is_file() else None
    checks["ledger_operational_ready"] = bool(ledger_rec and ledger_rec.get("pass") is True)

    draft = json.loads((root / PR.DRAFT_PATH).read_text())
    checks["preregistration_draft_consistent"] = PR.validate_draft(draft) == []
    checks["preregistration_not_frozen"] = draft.get("status") == "DRAFT_NOT_FROZEN"

    manifest_path = root / CM.RECORD_PATH
    manifest_doc = json.loads(manifest_path.read_text()) if manifest_path.is_file() else None
    checks["closure_manifest_present"] = manifest_doc is not None
    checks["closure_manifest_evidence_fresh"] = bool(manifest_doc is not None and CM.freshness_problems(root, manifest_doc) == [])

    checks["v2_not_frozen"] = spec.GENESIS_CAPABILITY_EVAL_V2_FROZEN is False
    from orca.eval.genesis_v2 import privacy_scan as PS
    scan = PS.scan_repository(root)
    checks["no_private_corpus_exists"] = scan["pass"] is True
    checks["model_authorization_not_authorized"] = json.loads((root / "docs/orneur/authorization/MODEL_EVAL_AUTHORIZATION.json").read_text())["status"] == "NOT_AUTHORIZED"

    # Everything WORKSTREAM 9 (Final Pre-Corpus Closure) requires, at minimum, for READY_FOR_PRIVATE_CORPUS_AUTHORIZATION.
    # Deliberately NOT required here: private_corpus_aggregate_commitment, a corpus secret, or a real benchmark AES key —
    # those intentionally do not exist yet and never gate this preflight.
    hard_requirements = ["v2_not_frozen", "no_private_corpus_exists", "model_authorization_not_authorized", "preregistration_not_frozen",
                        "runner_not_authorized_for_holdout_yet", "secret_manager_policy_valid", "authority_registry_valid", "reviewer_registry_valid",
                        "separation_of_duties_clean", "preregistration_draft_consistent", "ledger_operational_ready", "vault_verification_record_present_and_pass",
                        "sandbox_image_pinned_by_digest", "sandbox_containment_evidence_present", "sandbox_exact_sha_evidence_valid",
                        "runner_identity_registered", "authority_key_registered_and_valid", "corpus_inventory_attested_pass",
                        "semantic_or_reviewer_path_operational", "qualification_runner_qualified", "sandbox_runner_class_matches_qualification_runner",
                        "canonical_status_agrees_with_semantic_engine_record", "closure_manifest_present", "closure_manifest_evidence_fresh"]
    ready = all(checks.get(k) is True for k in hard_requirements)
    result = "READY_FOR_PRIVATE_CORPUS_AUTHORIZATION" if ready else "NOT_READY"
    return {"schema_version": SCHEMA_VERSION, "current_main_sha": _current_main_sha(), "checks": checks, "result": result,
            "outstanding_for_ready": [k for k in hard_requirements if not checks.get(k)]}
