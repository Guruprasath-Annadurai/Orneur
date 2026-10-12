"""Finding F1 (docs/orneur/status/evalinfra/INVENTORY.md): a genuinely filled private_corpus_aggregate_commitment must not be forced to keep
binding_status DEFERRED. Synthetic only; the repository draft is read, never modified."""
import copy
import json
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import prereg as PR

DRAFT = json.loads((Path(__file__).resolve().parents[1] / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json").read_text())


def _filled_frozen_record(status):
    d = copy.deepcopy(DRAFT)
    for k in PR.DEFERRED:
        d["bindings"][k] = {"bound": k}
        d["binding_status"][k] = status
    d.update({"status": "FROZEN", "frozen": True, "frozen_at": "2026-10-01T00:00:00Z", "floors_status": "LOCKED"})
    d["record_sha256"] = PR.record_hash(d)
    return d


# xfail(strict): this REPRODUCES F1 against the unmodified validator. The one-line fix was implemented and verified, then deliberately NOT shipped:
# orca/eval/genesis_v2/prereg.py is hash-bound in the frozen phase-21 DRAFT code_hashes and GENESIS_V2_PRE_CORPUS_CLOSURE_MANIFEST.json, so editing it
# breaks owner_preflight / closure freshness tests and would need edits under frozen docs/orneur/phase-21. See FOUNDER_DECISIONS_F1_F3_F5.md (F1).
# When the founder approves the patch, delete the xfail marker (strict=True makes the suite fail loudly once the bug is fixed, forcing that cleanup).
@pytest.mark.xfail(strict=True, reason="F1 reproduced: validator forces DEFERRED on a filled commitment; fix withheld (prereg.py is hash-bound in frozen artifacts)")
@pytest.mark.parametrize("status", ["BOUND", "OPERATIONALLY_CONFIGURED", "QUALIFIED"])
def test_f1_filled_deferred_binding_with_a_non_deferred_status_passes_freeze_validation(status):
    assert PR.validate_for_freeze(_filled_frozen_record(status)) == []


def test_f1_legacy_filled_but_still_deferred_remains_accepted_for_backward_compatibility():
    assert PR.validate_for_freeze(_filled_frozen_record("DEFERRED")) == []


def test_f1_null_deferred_binding_must_still_be_marked_deferred():
    d = copy.deepcopy(DRAFT)
    for k in PR.DEFERRED:
        d["binding_status"][k] = "BOUND"                      # binding is null => BOUND would be a false claim
    d["record_sha256"] = PR.record_hash(d)
    assert any("must have binding_status DEFERRED" in p for p in PR.validate_draft(d))


def test_f1_deferred_remains_illegal_for_other_bindings_and_draft_is_unchanged():
    d = copy.deepcopy(DRAFT)
    d["binding_status"]["eval_version"] = "DEFERRED"
    assert PR.validate_binding_status(d) != []
    assert PR.validate_draft(DRAFT) == []
    assert all(DRAFT["binding_status"][k] == "DEFERRED" and DRAFT["bindings"][k] is None for k in PR.DEFERRED)
