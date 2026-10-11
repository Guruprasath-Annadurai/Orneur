"""Provenance/licensing validator (fail closed) and the teacher-output-use rights register + ingestion gate."""
import copy
import json
from pathlib import Path

import pytest

from orca.dataquality import provenance as PV
from orca.dataquality import teacher_rights as TR
from tests.dataquality_support import chatml, lines_of, prov, source_registry, with_prov

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/orneur/phase-21/GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json"


def base():
    return chatml("question one", "answer one")


def codes(res):
    return {(v["line"], v["code"]) for v in res["violations"]}


# ------------------------------------------------------------------ provenance
def test_fully_resolved_records_pass(tmp_path):
    recs = [with_prov(base(), prov("human")), with_prov(chatml("q2", "a2"), prov("program", program="builder.py")),
            with_prov(chatml("q3", "a3"), prov("model", model_id="m", model_revision="r1"))]
    res = PV.check_provenance(lines_of(tmp_path, recs), source_registry())
    assert res["status"] == "PASS" and res["records_resolved"] == 3 and res["digests_computed_by_tool"] == 0


def test_missing_provenance_fails_closed(tmp_path):
    res = PV.check_provenance(lines_of(tmp_path, [base(), with_prov(base(), prov("human"))]), source_registry())
    assert res["status"] == "FAIL" and (1, "provenance_missing") in codes(res) and res["records_unresolved"] == 1


@pytest.mark.parametrize("mutate,code", [
    (lambda p: p.update(source_id="nope"), "source_id_unresolved"),
    (lambda p: p.pop("source_id"), "source_id_missing"),
    (lambda p: p.update(license_id="UNKNOWN"), "license_missing_or_unknown"),
    (lambda p: p.pop("license_id"), "license_missing_or_unknown"),
    (lambda p: p.update(license_id="internal-synthetic-test"), "license_conflicts_with_registry"),
    (lambda p: p.pop("creation_code_sha"), "creation_code_sha_missing_or_malformed"),
    (lambda p: p.update(creation_code_sha="XYZ"), "creation_code_sha_missing_or_malformed"),
    (lambda p: p.pop("generator"), "generator_kind_missing_or_unknown"),
    (lambda p: p.update(generator={"kind": "oracle"}), "generator_kind_missing_or_unknown"),
    (lambda p: p.update(generator={"kind": "model", "model_id": "m"}), "generator_model_incomplete"),
    (lambda p: p.update(generator={"kind": "program"}), "generator_program_incomplete"),
    (lambda p: p.update(digest="notahash"), "digest_malformed"),
])
def test_each_missing_or_unknown_field_is_a_violation(tmp_path, mutate, code):
    p = prov("human")
    mutate(p)
    res = PV.check_provenance(lines_of(tmp_path, [with_prov(base(), p, digest=False)]), source_registry())
    assert res["status"] == "FAIL" and (1, code) in codes(res)


def test_digest_mismatch_detects_edited_record(tmp_path):
    rec = with_prov(base(), prov("human"))
    rec["text"] = rec["text"] + " tampered"
    res = PV.check_provenance(lines_of(tmp_path, [rec]), source_registry())
    assert (1, "digest_mismatch") in codes(res)


def test_default_provenance_applies_and_digest_is_computed_by_tool(tmp_path):
    res = PV.check_provenance(lines_of(tmp_path, [base(), chatml("b", "c")]), source_registry(), default_provenance=prov("human"))
    assert res["status"] == "PASS" and res["digests_computed_by_tool"] == 2 and res["default_provenance_applied"] is True


def test_invalid_or_missing_source_registry_fails_everything(tmp_path):
    recs = [with_prov(base(), prov("human"))]
    assert PV.check_provenance(lines_of(tmp_path, recs), None)["status"] == "FAIL"
    bad = source_registry()
    bad["licenses"].append("TBD")
    res = PV.check_provenance(lines_of(tmp_path, recs), bad)
    assert res["status"] == "FAIL" and res["source_registry_problems"]
    bad2 = source_registry()
    bad2["sources"][0]["license_id"] = "not-listed"
    assert PV.check_provenance(lines_of(tmp_path, recs), bad2)["status"] == "FAIL"


def test_unparseable_record_is_unresolved(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text("{oops\n")
    from orca.dataquality._common import load_jsonl
    res = PV.check_provenance(load_jsonl(p), source_registry())
    assert res["status"] == "FAIL" and (1, "unparseable_record") in codes(res)


# ------------------------------------------------------------------ teacher register
def test_committed_seed_register_is_valid_and_every_teacher_is_unreviewed():
    reg = TR.load_register()
    assert TR.validate_register(reg) == []
    ids = {t["teacher_id"] for t in reg["teachers"]}
    assert {"llama3.1:8b", "nvidia-nemotron-3-ultra-550b-a55b", TR.UNATTRIBUTED_TEACHER} <= ids
    for t in reg["teachers"]:
        assert t["status"] == "UNREVIEWED"
        assert t["terms_source_url"] is None and t["reviewed_by"] is None and t["terms_record_id"] is None and t["reviewed_at"] is None
    assert reg["legal_conclusions_asserted"] is False


def test_seed_register_is_exactly_derived_from_the_corpus_inventory():
    derived = TR.derive_seed_from_file(INVENTORY)
    committed = TR.load_register()
    derived["derived_from"]["path"] = committed["derived_from"]["path"]   # path spelling is the only free field
    assert TR.seal(derived) == committed, "register drifted from the inventory: re-run `teacher-register derive`"
    inv = json.loads(INVENTORY.read_text())
    n = sum(t["inventory_record_count"] for t in committed["teachers"])
    assert n == sum(c["record_count"] for c in inv["corpora"] if c["corpus_class"] == "distillation_data")


def reg_with(**teacher_fields):
    reg = copy.deepcopy(TR.load_register())
    reg["teachers"][0].update(teacher_fields)
    return TR.seal(reg)


def permitted(**over):
    f = {"status": "PERMITTED_RECORDED", "revisions": ["rev-1"], "terms_record_id": "TERMS-REC-1", "terms_source_url": "https://example.invalid/terms",
         "reviewed_by": "human-reviewer", "reviewed_at": "2026-01-01", "permitted_uses": ["training_data_generation"]}
    f.update(over)
    return f


def test_edited_register_without_reseal_is_rejected():
    reg = copy.deepcopy(TR.load_register())
    reg["teachers"][0]["status"] = "PROHIBITED"
    assert any("content_sha256" in e for e in TR.validate_register(reg))


@pytest.mark.parametrize("missing", ["terms_record_id", "terms_source_url", "reviewed_by", "reviewed_at"])
def test_permitted_recorded_requires_cited_terms_and_reviewer(missing):
    errs = TR.validate_register(reg_with(**permitted(**{missing: None})))
    assert any(missing in e for e in errs)


def test_permitted_recorded_requires_revisions_uses_and_human_reviewer():
    assert any("revisions" in e for e in TR.validate_register(reg_with(**permitted(revisions=[]))))
    assert any("permitted_uses" in e for e in TR.validate_register(reg_with(**permitted(permitted_uses=[]))))
    assert any("human" in e for e in TR.validate_register(reg_with(**permitted(reviewed_by="model:claude"))))
    assert TR.validate_register(reg_with(**permitted())) == []


def test_unreviewed_must_not_carry_review_fields_and_bad_status_or_dupes_rejected():
    assert any("UNREVIEWED" in e for e in TR.validate_register(reg_with(reviewed_by="someone")))
    assert any("status" in e for e in TR.validate_register(reg_with(status="MAYBE")))
    reg = copy.deepcopy(TR.load_register())
    reg["teachers"][1]["teacher_id"] = reg["teachers"][0]["teacher_id"]
    assert any("duplicate" in e for e in TR.validate_register(TR.seal(reg)))
    reg2 = copy.deepcopy(TR.load_register())
    reg2["legal_conclusions_asserted"] = True
    assert any("legal_conclusions" in e for e in TR.validate_register(TR.seal(reg2)))


def model_rec(model_id, rev="rev-1", i=1):
    return with_prov(chatml(f"q{i}", f"a{i}"), prov("model", model_id=model_id, model_revision=rev))


def test_gate_refuses_every_seeded_teacher_because_all_are_unreviewed(tmp_path):
    reg = TR.load_register()
    recs = [model_rec("llama3.1:8b", i=1), model_rec("nvidia-nemotron-3-ultra-550b-a55b", i=2)]
    res = TR.gate_lines(lines_of(tmp_path, recs), reg)
    assert res["status"] == "FAIL" and res["accepted_count"] == 0 and res["refusals_by_reason"] == {"teacher_status_UNREVIEWED": 2}
    with pytest.raises(TR.IngestRefused) as ei:
        TR.enforce_ingest(lines_of(tmp_path, recs), reg)
    assert len(ei.value.refusals) == 2


def test_gate_refuses_unknown_teacher_missing_generator_and_unparseable(tmp_path):
    reg = TR.load_register()
    p = tmp_path / "g.jsonl"
    p.write_text(json.dumps(model_rec("never-heard-of-it")) + "\n" + json.dumps(chatml("q", "a")) + "\n{bad\n")
    from orca.dataquality._common import load_jsonl
    res = TR.gate_lines(load_jsonl(p), reg)
    assert res["refusals_by_reason"] == {"teacher_not_in_register": 1, "no_generator_declared": 1, "unparseable_record": 1}


@pytest.mark.parametrize("status", ["RESTRICTED", "PROHIBITED", "UNREVIEWED"])
def test_gate_refuses_non_permitted_statuses(tmp_path, status):
    extra = {"terms_record_id": "T", "terms_source_url": "u", "reviewed_by": "h", "reviewed_at": "d"} if status != "UNREVIEWED" else {}
    reg = reg_with(status=status, **extra)
    assert TR.validate_register(reg) == []
    res = TR.gate_lines(lines_of(tmp_path, [model_rec(reg["teachers"][0]["teacher_id"])]), reg)
    assert res["refused_count"] == 1 and res["refusals"][0]["reason"] == f"teacher_status_{status}"


def test_gate_accepts_only_permitted_recorded_with_covered_revision(tmp_path):
    reg = reg_with(**permitted())
    tid = reg["teachers"][0]["teacher_id"]
    ok = TR.gate_lines(lines_of(tmp_path, [model_rec(tid, "rev-1")]), reg)
    assert ok["status"] == "PASS" and ok["accepted_count"] == 1
    bad_rev = TR.gate_lines(lines_of(tmp_path, [model_rec(tid, "rev-2")]), reg)
    assert bad_rev["refusals"][0]["reason"] == "revision_not_covered_by_review"
    other = TR.gate_lines(lines_of(tmp_path, [model_rec(reg["teachers"][1]["teacher_id"], "rev-1")]), reg)
    assert other["refused_count"] == 1
    assert TR.enforce_ingest(lines_of(tmp_path, [model_rec(tid, "rev-1")]), reg)


def test_human_and_program_generators_do_not_need_a_teacher(tmp_path):
    reg = TR.load_register()
    res = TR.gate_lines(lines_of(tmp_path, [with_prov(chatml("q", "a"), prov("human")), with_prov(chatml("q2", "a2"), prov("program", program="p"))]), reg)
    assert res["status"] == "PASS"


def test_invalid_register_refuses_everything_fail_closed(tmp_path):
    reg = copy.deepcopy(reg_with(**permitted()))
    reg["teachers"][0]["status"] = "PERMITTED_RECORDED"
    reg["content_sha256"] = "0" * 64   # tampered
    res = TR.gate_lines(lines_of(tmp_path, [with_prov(chatml("q", "a"), prov("human"))]), reg)
    assert res["status"] == "FAIL" and res["register_valid"] is False and res["refusals"][0]["reason"] == "register_invalid"


def test_alias_resolves_to_teacher(tmp_path):
    reg = copy.deepcopy(TR.load_register())
    reg["teachers"][0].update(permitted())
    reg["teachers"][0]["aliases"] = ["llama3.1:8b-instruct"]
    reg = TR.seal(reg)
    assert TR.validate_register(reg) == []
    res = TR.gate_lines(lines_of(tmp_path, [model_rec("llama3.1:8b-instruct", "rev-1")]), reg)
    assert res["accepted_count"] == 1
