"""P1 dataset-quality gap closures: usage rights, source-manifest validation, teacher-terms-on-record, frozen-eval pinning, extra privacy
patterns, and the report/CLI wiring. Synthetic fixtures only; every secret/PII value below is a documented example or an invented token."""
import copy
import json

import pytest

from orca.dataquality import cli
from orca.dataquality import frozen_eval as FE
from orca.dataquality import privacy as PR
from orca.dataquality import report as R
from orca.dataquality import teacher_derivation as TD
from orca.dataquality import teacher_rights as TR
from orca.dataquality import usage_rights as UR
from orca.dataquality._common import canonical_json, load_jsonl, sha256_file
from tests.dataquality_support import chatml, distinct_records, lines_of, prov, with_prov, words, write_jsonl


def rights_registry(**over):
    reg = {"schema_version": "orneur-source-registry/1", "licenses": ["CC0-1.0", "internal-synthetic-test"], "sources": [
        {"source_id": "src-human", "license_id": "CC0-1.0", "terms_id": "TERMS-H-1",
         "usage_rights": {"permitted_uses": ["training", "evaluation"], "restrictions": []}},
        {"source_id": "src-prog", "license_id": "internal-synthetic-test", "terms_id": "TERMS-P-1",
         "usage_rights": {"permitted_uses": ["evaluation"], "restrictions": []}}]}
    reg.update(over)
    return reg


def codes(res):
    return {(v["line"], v["code"]) for v in res["violations"]}


# ------------------------------------------------------------- (1)/(7) usage rights + source-manifest validation
def test_valid_source_manifest_passes():
    assert UR.check_source_manifest(rights_registry())["status"] == "PASS"


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r["sources"][0].pop("usage_rights"), "usage_rights"),
    (lambda r: r["sources"][0].pop("terms_id"), "terms_id"),
    (lambda r: r["sources"][0].update(terms_id="  "), "terms_id"),
    (lambda r: r["sources"][0]["usage_rights"].update(permitted_uses=[]), "permitted_uses"),
    (lambda r: r["sources"][0]["usage_rights"].update(permitted_uses=["anything-goes"]), "permitted_uses"),
    (lambda r: r["sources"][0].update(surprise=1), "unexpected"),
    (lambda r: r["sources"].append(dict(r["sources"][0])), "duplicate"),
    (lambda r: r.update(sources=[]), "sources"),
    (lambda r: r.update(licenses=["CC0-1.0", "CC0-1.0", "internal-synthetic-test"]), "licenses"),
])
def test_source_manifest_fails_closed_on_missing_or_unknown_rights(mutate, needle):
    reg = copy.deepcopy(rights_registry())
    mutate(reg)
    res = UR.check_source_manifest(reg)
    assert res["status"] == "FAIL" and any(needle in p for p in res["problems"])


def test_usage_rights_check_is_per_record_and_fail_closed(tmp_path):
    recs = [with_prov(chatml("q1", "a1"), prov("human")),                    # training permitted
            with_prov(chatml("q2", "a2"), prov("program", program="b.py"))]  # source only permits evaluation
    res = UR.check_usage_rights(lines_of(tmp_path, recs), rights_registry(), intended_use="training")
    assert res["status"] == "FAIL" and codes(res) == {(2, "use_not_permitted")} and res["records_permitted"] == 1


def test_usage_rights_unrecorded_and_restricted_are_violations(tmp_path):
    reg = rights_registry()
    del reg["sources"][0]["usage_rights"]
    res = UR.check_usage_rights(lines_of(tmp_path, [with_prov(chatml("q", "a"), prov("human"))]), reg)
    assert res["status"] == "FAIL"           # invalid manifest => nothing is assumed permissive
    reg2 = rights_registry()
    reg2["sources"][0]["usage_rights"]["restrictions"] = ["no-training"]
    res2 = UR.check_usage_rights(lines_of(tmp_path, [with_prov(chatml("q", "a"), prov("human"))]), reg2)
    assert res2["status"] == "FAIL" and (1, "use_restricted") in codes(res2)


def test_usage_rights_missing_provenance_and_unresolved_source_fail(tmp_path):
    p = prov("human")
    p["source_id"] = "nope"
    res = UR.check_usage_rights(lines_of(tmp_path, [chatml("a", "b"), with_prov(chatml("c", "d"), p)]), rights_registry())
    assert {(1, "provenance_missing"), (2, "source_id_unresolved")} <= codes(res)


def test_usage_rights_no_records_is_fail_not_pass(tmp_path):
    assert UR.check_usage_rights(lines_of(tmp_path, []), rights_registry())["status"] == "FAIL"


# ------------------------------------------------------------- (2) teacher terms carried by the record
def reg_permitted(uses=("training_data_generation",), revisions=("rev-1",)):
    reg = copy.deepcopy(TR.load_register())
    reg["teachers"][0].update(status="PERMITTED_RECORDED", revisions=list(revisions), terms_record_id="TERMS-REC-1",
                              terms_source_url="https://example.invalid/terms", reviewed_by="human-reviewer", reviewed_at="2026-01-01",
                              permitted_uses=list(uses))
    return TR.seal(reg), reg["teachers"][0]["teacher_id"]


def derived(tid, rev="rev-1", terms="default", **extra):
    p = prov("model", model_id=tid, model_revision=rev)
    rec = chatml("q", "a")
    if terms == "default":
        rec["teacher_terms"] = {"teacher_id": tid, "terms_record_id": "TERMS-REC-1"}
    elif terms is not None:
        rec["teacher_terms"] = terms
    rec.update(extra)
    return with_prov(rec, p)


def test_model_derived_record_with_matching_terms_entry_passes(tmp_path):
    reg, tid = reg_permitted()
    res = TD.check(lines_of(tmp_path, [derived(tid)]), reg)
    assert res["status"] == "PASS" and res["derived_records"] == 1


def test_model_record_without_teacher_terms_entry_fails_even_if_teacher_is_permitted(tmp_path):
    reg, tid = reg_permitted()
    res = TD.check(lines_of(tmp_path, [derived(tid, terms=None)]), reg)
    assert res["status"] == "FAIL" and res["refusals_by_reason"] == {"teacher_terms_missing": 1}


@pytest.mark.parametrize("terms,reason", [
    ({"teacher_id": "x"}, "teacher_terms_malformed"),
    ("TERMS-REC-1", "teacher_terms_malformed"),
    ({"teacher_id": "unknown-model", "terms_record_id": "TERMS-REC-1"}, "teacher_not_in_register"),
    ({"teacher_id": "SELF", "terms_record_id": "TERMS-OTHER"}, "terms_record_mismatch"),
])
def test_bad_teacher_terms_entries_are_refused(tmp_path, terms, reason):
    reg, tid = reg_permitted()
    if isinstance(terms, dict) and terms.get("teacher_id") == "SELF":
        terms = {**terms, "teacher_id": tid}
    res = TD.check(lines_of(tmp_path, [derived(tid, terms=terms)]), reg)
    assert res["status"] == "FAIL" and reason in res["refusals_by_reason"]


def test_unreviewed_teacher_and_unrecorded_terms_fail_closed(tmp_path):
    reg = TR.load_register()   # seeded: every teacher UNREVIEWED
    tid = reg["teachers"][0]["teacher_id"]
    res = TD.check(lines_of(tmp_path, [derived(tid, terms={"teacher_id": tid, "terms_record_id": "TERMS-REC-1"})]), reg)
    assert res["status"] == "FAIL" and res["refusals_by_reason"] == {"teacher_status_UNREVIEWED": 1}


def test_permitted_teacher_whose_uses_exclude_training_is_refused(tmp_path):
    reg, tid = reg_permitted(uses=("evaluation_only",))
    res = TD.check(lines_of(tmp_path, [derived(tid)]), reg)
    assert res["refusals_by_reason"] == {"use_not_permitted": 1}


def test_restriction_and_uncovered_revision_are_refused(tmp_path):
    reg, tid = reg_permitted()
    assert TD.check(lines_of(tmp_path, [derived(tid, rev="rev-9")]), reg)["refusals_by_reason"] == {"revision_not_covered_by_review": 1}
    reg2 = copy.deepcopy(reg)
    reg2["teachers"][0]["restrictions"] = ["no-training_data_generation"]
    assert TD.check(lines_of(tmp_path, [derived(tid)]), TR.seal(reg2))["refusals_by_reason"] == {"use_restricted": 1}


def test_model_origin_hidden_behind_human_or_program_generator_is_caught(tmp_path):
    reg, tid = reg_permitted()
    sneaky = [with_prov({**chatml("q", "a"), "teacher": "llama3.1:8b"}, prov("human")),
              with_prov({**chatml("q2", "a2"), "distilled_from": "some-model"}, prov("program", program="b.py")),
              with_prov(chatml("q3", "a3"), {**prov("human"), "derived_from_model": "some-model"})]
    res = TD.check(lines_of(tmp_path, sneaky), reg)
    assert res["status"] == "FAIL" and res["derived_records"] == 3 and res["refusals_by_reason"] == {"teacher_terms_missing": 3}


def test_pure_human_and_program_records_need_no_teacher_and_invalid_register_fails_derived(tmp_path):
    recs = [with_prov(chatml("q", "a"), prov("human")), with_prov(chatml("q2", "a2"), prov("program", program="b.py"))]
    assert TD.check(lines_of(tmp_path, recs), TR.load_register())["status"] == "PASS"
    bad = copy.deepcopy(TR.load_register())
    bad["teachers"][0]["status"] = "PROHIBITED"
    res = TD.check(lines_of(tmp_path, [derived("llama3.1:8b")]), bad)
    assert res["status"] == "FAIL" and res["refusals_by_reason"] == {"register_invalid": 1}


def test_missing_provenance_on_unparseable_or_empty_input_is_fail(tmp_path):
    assert TD.check(lines_of(tmp_path, []), TR.load_register())["status"] == "FAIL"
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json\n", encoding="utf-8")
    assert TD.check(load_jsonl(p), TR.load_register())["refusals_by_reason"] == {"unparseable_record": 1}


# ------------------------------------------------------------- (6) leakage against a frozen, digest-pinned eval set
def frozen(tmp_path, eval_recs):
    ev = write_jsonl(tmp_path / "eval.jsonl", eval_recs)
    return ev, sha256_file(ev)


def test_frozen_eval_without_pin_is_not_evaluated_never_pass(tmp_path):
    ev, _ = frozen(tmp_path, [chatml(words(1), words(2))])
    res = FE.check(lines_of(tmp_path, distinct_records(3)), ev, expected_sha256=None)
    assert res["status"] == "NOT_EVALUATED"


def test_frozen_eval_digest_mismatch_fails_before_comparing(tmp_path):
    ev, _ = frozen(tmp_path, [chatml(words(1), words(2))])
    res = FE.check(lines_of(tmp_path, distinct_records(3)), ev, expected_sha256="0" * 64)
    assert res["status"] == "FAIL" and res["reason"] == "eval_digest_mismatch" and "sub_checks" not in res


def test_frozen_eval_clean_pass_and_leak_detected_via_eval_derived_fingerprints(tmp_path):
    ev, d = frozen(tmp_path, [chatml(words(901, 30), words(902, 30))])
    clean = FE.check(lines_of(tmp_path, distinct_records(4, offset=500)), ev, expected_sha256=d)
    assert clean["status"] == "PASS" and {s["name"] for s in clean["sub_checks"]} == {"eval_pin", "exact", "near", "fingerprint_set"}
    leaky = FE.check(lines_of(tmp_path, distinct_records(4, offset=500) + [chatml(words(901, 30), words(902, 30))], "t.jsonl"), ev, expected_sha256=d)
    assert leaky["status"] == "FAIL"
    assert "901" not in canonical_json(leaky) and words(901, 30)[:20] not in canonical_json(leaky)


def test_frozen_eval_empty_eval_is_fail(tmp_path):
    ev = tmp_path / "e.jsonl"
    ev.write_text("", encoding="utf-8")
    assert FE.check(lines_of(tmp_path, distinct_records(2)), ev, expected_sha256=sha256_file(ev))["status"] == "FAIL"


# ------------------------------------------------------------- (5) extra privacy patterns (synthetic documented examples only)
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


@pytest.mark.parametrize("text,cat", [
    ("call +44 20 7946 0958 now", "pii:intl_phone"),
    ("token " + JWT, "secret:jwt"),
    ("hook xoxb-" + "123456789012-" * 2 + "abcdefghijklmnopqrstuvwx", "secret:slack_token"),
    ("host 192.168.10.45 down", "pii:ipv4"),
    ("pay GB82WEST12345698765432 today", "pii:iban"),
    ("fetch https://svc:hunter2pass@example.invalid/x", "secret:url_credentials"),
])
def test_extra_privacy_patterns_detected_without_echoing_values(tmp_path, text, cat):
    res = PR.scan_lines(lines_of(tmp_path, [chatml("hello", text)]))
    assert res["status"] == "FAIL" and cat in res["findings_by_category"]
    assert text.split()[1] not in canonical_json(res)


def test_extra_privacy_patterns_have_no_false_positive_on_clean_or_bad_checksum(tmp_path):
    clean = [chatml("version 1.2.3 released", "the value 300.400.500.600 is not an address; GB00WEST12345698765432 fails the checksum")]
    assert PR.scan_lines(lines_of(tmp_path, clean))["status"] == "PASS"


# ------------------------------------------------------------- (8) report + CLI wiring, byte-stable
def _fixture(tmp_path):
    recs = [with_prov(r, prov("human")) for r in distinct_records(6)]
    t = write_jsonl(tmp_path / "t.jsonl", recs)
    ev = write_jsonl(tmp_path / "e.jsonl", [chatml(words(901, 30), words(902, 30))])
    (tmp_path / "src.json").write_text(json.dumps(rights_registry()), encoding="utf-8")
    return t, ev


def test_report_includes_new_checks_only_when_requested_and_is_byte_stable(tmp_path):
    t, ev = _fixture(tmp_path)
    base = R.build_report(t, ev, source_registry=rights_registry())
    assert not {"source_manifest", "usage_rights", "teacher_terms", "frozen_eval"} & {s["check"] for s in base["statuses"]}
    kw = dict(source_registry=rights_registry(), intended_use="training", expected_eval_sha256=sha256_file(ev))
    a, b = R.build_report(t, ev, **kw), R.build_report(t, ev, **kw)
    assert canonical_json(a) == canonical_json(b) and "generated_at" not in a
    st = {s["check"]: s["status"] for s in a["statuses"]}
    assert st["source_manifest"] == "PASS" and st["usage_rights"] == "PASS" and st["teacher_terms"] == "PASS"
    assert st["frozen_eval"] == "PASS" and a["aggregate_quality_score"] == "NONE_BY_DESIGN"


def test_report_intended_use_without_eval_pin_marks_frozen_eval_not_evaluated(tmp_path):
    t, ev = _fixture(tmp_path)
    r = R.build_report(t, ev, source_registry=rights_registry(), intended_use="training")
    assert {s["check"]: s["status"] for s in r["statuses"]}["frozen_eval"] == "NOT_EVALUATED"


def test_cli_source_manifest_usage_rights_and_teacher_terms(tmp_path, capsys):
    t, ev = _fixture(tmp_path)
    assert cli.run(["source-manifest", str(tmp_path / "src.json")]) == 0
    assert cli.run(["usage-rights", str(t), "--sources", str(tmp_path / "src.json"), "--use", "training"]) == 0
    assert cli.run(["usage-rights", str(t), "--sources", str(tmp_path / "src.json"), "--use", "redistribution"]) == 1
    assert cli.run(["teacher-terms", str(t)]) == 0
    assert cli.run(["frozen-eval", "--train", str(t), "--eval", str(ev), "--eval-sha256", sha256_file(ev)]) == 0
    assert cli.run(["frozen-eval", "--train", str(t), "--eval", str(ev), "--eval-sha256", "0" * 64]) == 1
    capsys.readouterr()
