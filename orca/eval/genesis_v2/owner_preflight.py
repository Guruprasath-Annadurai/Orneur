"""Single deterministic owner-setup preflight: everything WORKSTREAM 11 asks for, in one place. Never generates a corpus, secret or key; only reports."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from orca.eval.genesis_v2 import authority_registry as AR
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
    rr_doc, rr_problems = RR.load(root / RR.REGISTRY_PATH)
    checks["reviewer_registry_valid"] = rr_doc is not None and not rr_problems
    checks["separation_of_duties_clean"] = bool(ar_doc is not None and rr_doc is not None and not RR.check_separation_of_duties(ar_doc, rr_doc))

    inv = json.loads((root / INV.INVENTORY_PATH).read_text())
    inv_res = INV.evaluate(inv, root, authority_keys=(AR.active_authority_keys(ar_doc) if ar_doc else None))
    checks["corpus_inventory_state_known"] = True   # always knowable; PASS is a separate, harder bar tracked below
    checks["corpus_inventory_attested_pass"] = inv_res.status == C.PASS

    from orca.eval.genesis_v2 import semantic as SEM
    checks["semantic_engine_configured"] = False   # honestly NOT_CONFIGURED in this phase; see GENESIS_CAPABILITY_EVAL_V2_STATUS.json

    sandbox_rec_path = root / "docs/orneur/phase-21/GENESIS_V2_SANDBOX_QUALIFICATION_CANDIDATE_RECORD.json"
    sandbox_rec = json.loads(sandbox_rec_path.read_text()) if sandbox_rec_path.is_file() else None
    checks["sandbox_image_pinned_by_digest"] = bool(sandbox_rec and sandbox_rec.get("image_digest"))
    checks["sandbox_containment_evidence_present"] = bool(sandbox_rec and sandbox_rec.get("containment_test_result_digest"))
    checks["sandbox_ready"] = bool(sandbox_rec and sandbox_rec.get("sandbox_ready") is True)

    rn_doc = json.loads((root / RN.REGISTRY_PATH).read_text())
    checks["runner_identity_registered"] = RN.validate(rn_doc) == [] and len(rn_doc["records"]) > 0
    checks["runner_not_authorized_for_holdout_yet"] = RN.to_ledger_registered_processes(rn_doc) == {}   # REGISTERED_NOT_AUTHORIZED grants nothing

    ledger_rec_path = root / "docs/orneur/phase-21/GENESIS_V2_LEDGER_DEPLOYMENT_RECORD.json"
    ledger_rec = json.loads(ledger_rec_path.read_text()) if ledger_rec_path.is_file() else None
    checks["ledger_operational_ready"] = bool(ledger_rec and ledger_rec.get("pass") is True)

    draft = json.loads((root / PR.DRAFT_PATH).read_text())
    checks["preregistration_draft_consistent"] = PR.validate_draft(draft) == []
    checks["preregistration_not_frozen"] = draft.get("status") == "DRAFT_NOT_FROZEN"

    checks["v2_not_frozen"] = spec.GENESIS_CAPABILITY_EVAL_V2_FROZEN is False
    from orca.eval.genesis_v2 import privacy_scan as PS
    scan = PS.scan_repository(root)
    checks["no_private_corpus_exists"] = scan["pass"] is True
    checks["model_authorization_not_authorized"] = json.loads((root / "docs/orneur/authorization/MODEL_EVAL_AUTHORIZATION.json").read_text())["status"] == "NOT_AUTHORIZED"

    hard_requirements = ["v2_not_frozen", "no_private_corpus_exists", "model_authorization_not_authorized", "preregistration_not_frozen",
                        "runner_not_authorized_for_holdout_yet", "secret_manager_policy_valid", "authority_registry_valid", "reviewer_registry_valid",
                        "separation_of_duties_clean", "preregistration_draft_consistent", "ledger_operational_ready", "vault_verification_record_present_and_pass",
                        "sandbox_image_pinned_by_digest", "sandbox_containment_evidence_present", "runner_identity_registered"]
    ready = all(checks.get(k) is True for k in hard_requirements)
    result = "READY_FOR_PRIVATE_CORPUS_AUTHORIZATION" if ready else "NOT_READY"
    if ready and not (checks["corpus_inventory_attested_pass"] and checks["semantic_engine_configured"] and checks["sandbox_ready"]):
        result = "NOT_READY"  # these three remain honestly required before a real corpus authorization, and are known-false in this phase
    return {"schema_version": SCHEMA_VERSION, "current_main_sha": _current_main_sha(), "checks": checks, "result": result,
            "outstanding_for_ready": [k for k in hard_requirements + ["corpus_inventory_attested_pass", "semantic_engine_configured", "sandbox_ready"] if not checks.get(k)]}
