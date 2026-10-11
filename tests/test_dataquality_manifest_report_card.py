"""Deterministic manifests + tamper detection, the aggregated quality report (no collapsed score), and data-card generation gating."""
import copy
import json

import pytest

from orca.dataquality import datacard as DC
from orca.dataquality import manifest as M
from orca.dataquality import report as R
from orca.dataquality._common import canonical_json, pretty_json
from tests.dataquality_support import chatml, distinct_records, prov, source_registry, with_prov, write_jsonl

SHA = "a" * 40


@pytest.fixture
def files(tmp_path):
    t = write_jsonl(tmp_path / "train.jsonl", distinct_records(8, offset=100))
    e = write_jsonl(tmp_path / "eval.jsonl", distinct_records(3, offset=500))
    return t, e


def build(files, **kw):
    t, e = files
    args = dict(dataset_id="synthetic-fixture", version="v1", purpose="test", creation_code_sha=SHA, schema='{"text": str}')
    args.update(kw)
    return M.build(t, e, **args)


# ------------------------------------------------------------------ manifests
def test_manifest_is_byte_reproducible_and_has_no_timestamp_unless_now(files, tmp_path):
    a, b = build(files), build(files)
    assert pretty_json(a) == pretty_json(b)
    assert a["manifest"]["created_at"] == "NOT_RECORDED"
    assert build(files, now="2026-10-11T00:00:00Z")["manifest"]["created_at"] == "2026-10-11T00:00:00Z"
    assert a["manifest"]["record_count"] == 11 and len(a["record_digests"]["train"]) == 8 and len(a["record_digests"]["eval"]) == 3


def test_manifest_reuses_the_registry_dataclass_fields():
    import dataclasses
    from orca.registry.dataset_manifest import DatasetManifest
    env = {f.name for f in dataclasses.fields(DatasetManifest)}
    assert env >= {"dataset_id", "train_checksum", "eval_checksum", "creation_code_sha", "approval_state", "frozen"}


def test_verify_passes_on_untouched_files(files):
    t, e = files
    assert M.verify(build(files), t, e)["status"] == "PASS"


def test_verify_detects_edited_record_with_line_number(files):
    t, e = files
    env = build(files)
    lines = t.read_text().splitlines()
    lines[2] = lines[2].replace("a", "b", 1) if "a" in lines[2] else lines[2] + " "
    t.write_text("\n".join(lines) + "\n")
    res = M.verify(env, t, e)
    codes = {p["code"] for p in res["problems"]}
    assert res["status"] == "FAIL" and {"train_checksum_mismatch", "train_records_changed"} <= codes
    assert res["detail"]["train"]["changed_lines"] == [3]


def test_verify_detects_appended_removed_and_reordered_records(files):
    t, e = files
    env = build(files)
    orig = t.read_text()
    t.write_text(orig + json.dumps(chatml("extra", "row")) + "\n")
    assert "train_record_count_mismatch" in {p["code"] for p in M.verify(env, t, e)["problems"]}
    rows = orig.splitlines()
    t.write_text("\n".join(rows[:-1]) + "\n")
    assert "train_record_count_mismatch" in {p["code"] for p in M.verify(env, t, e)["problems"]}
    t.write_text("\n".join([rows[1], rows[0]] + rows[2:]) + "\n")
    res = M.verify(env, t, e)
    assert res["status"] == "FAIL" and res["detail"]["train"]["changed_lines"] == [1, 2]
    t.write_text(orig)
    assert M.verify(env, t, e)["status"] == "PASS"


def test_verify_detects_tampered_eval_and_tampered_manifest(files):
    t, e = files
    env = build(files)
    e.write_text(e.read_text() + "\n")
    assert any(p["code"].startswith("eval_") for p in M.verify(env, t, e)["problems"])
    e.write_text(e.read_text().rstrip("\n") + "\n")
    env2 = copy.deepcopy(build(files))
    env2["manifest"]["approval_state"] = "APPROVED"
    res = M.verify(env2, t, e)
    assert res["status"] == "FAIL" and "manifest_digest_mismatch" in {p["code"] for p in res["problems"]}
    env3 = copy.deepcopy(build(files))
    env3["manifest"]["train_checksum"] = "0" * 64
    env3["manifest_digest"] = M._digest_envelope(env3)   # attacker re-seals the manifest: the file hash still disagrees
    assert "train_checksum_mismatch" in {p["code"] for p in M.verify(env3, t, e)["problems"]}


def test_verify_rejects_bad_format_unknown_fields_and_missing_split(files):
    t, e = files
    assert M.verify({"format": "nope"}, t, e)["status"] == "FAIL"
    env = copy.deepcopy(build(files))
    env["manifest"]["surprise"] = 1
    env["manifest_digest"] = M._digest_envelope(env)
    assert "manifest_fields_invalid" in {p["code"] for p in M.verify(env, t, e)["problems"]}
    assert "eval_file_not_supplied" in {p["code"] for p in M.verify(build(files), t, None)["problems"]}


def test_build_rejects_unsafe_ids(files):
    with pytest.raises(Exception):
        build(files, dataset_id="../evil")


def test_manifest_without_eval_roundtrips(tmp_path):
    t = write_jsonl(tmp_path / "t.jsonl", distinct_records(3))
    env = M.build(t, None, dataset_id="x", version="v1", purpose="p", creation_code_sha=SHA)
    assert env["manifest"]["eval_checksum"] == M.NOT_APPLICABLE and M.verify(env, t, None)["status"] == "PASS"


# ------------------------------------------------------------------ report
def full_report(files, **kw):
    t, e = files
    return R.build_report(t, e, source_registry=source_registry(), default_provenance=prov("human"), **kw)


def test_report_lists_every_status_and_never_collapses_to_a_score(files):
    rep = full_report(files)
    names = [s["check"] for s in rep["statuses"]]
    for expected in ("schema", "provenance", "teacher_rights", "dedup", "diversity", "semantic_diversity", "contamination", "contamination.exact",
                     "contamination.near", "contamination.canary", "contamination.fingerprint_set", "privacy", "balance", "manifest_verify"):
        assert expected in names
    assert {s["status"] for s in rep["statuses"]} <= {"PASS", "FAIL", "NOT_EVALUATED"}
    assert rep["aggregate_quality_score"] == "NONE_BY_DESIGN"
    assert not {"score", "quality_score", "overall", "ok", "passed"} & set(rep)
    assert sum(rep["status_counts"].values()) == len(rep["statuses"])


def test_report_marks_unsupplied_inputs_not_evaluated_and_fails_missing_provenance(files):
    t, e = files
    rep = R.build_report(t, e)    # no registry, no provenance
    st = {s["check"]: s["status"] for s in rep["statuses"]}
    assert st["provenance"] == "FAIL" and st["teacher_rights"] == "FAIL"           # fail closed
    assert st["semantic_diversity"] == st["balance"] == st["manifest_verify"] == "NOT_EVALUATED"
    assert st["contamination.canary"] == st["contamination.fingerprint_set"] == "NOT_EVALUATED"
    assert st["schema"] == st["dedup"] == st["privacy"] == "PASS"


def test_report_with_manifest_and_canary_inputs(files):
    t, e = files
    rep = full_report(files, manifest_env=build(files), canaries=["ZZ-CANARY-" + "q" * 12], fingerprint_set=None)
    st = {s["check"]: s["status"] for s in rep["statuses"]}
    assert st["manifest_verify"] == "PASS" and st["contamination.canary"] == "PASS" and st["provenance"] == "PASS" and st["teacher_rights"] == "PASS"


def test_report_is_deterministic_and_timestamp_only_with_now(files):
    a, b = full_report(files), full_report(files)
    assert canonical_json(a) == canonical_json(b) and "generated_at" not in a
    assert full_report(files, now="T")["generated_at"] == "T"


def test_report_failing_data_shows_fail_statuses(tmp_path):
    recs = distinct_records(5) + [distinct_records(1)[0], chatml("leak", "sk-" + "Zz9Y8x7W" * 4)]
    t = write_jsonl(tmp_path / "t.jsonl", recs)
    st = {s["check"]: s["status"] for s in R.build_report(t).__getitem__("statuses")}
    assert st["dedup"] == "FAIL" and st["privacy"] == "FAIL"


# ------------------------------------------------------------------ data card
ID = "c" * 64


def evidence(identity=ID):
    d1 = {"format": DC.DATA1_FORMAT, "bound_corpus_identity_sha256": identity, "creation_digest_sha256": "d" * 64,
          "sources": [{"source_id": "s", "license_id": "l"}]}
    d2 = {"format": DC.DATA2_FORMAT, "bound_corpus_identity_sha256": identity, "holdout_fingerprint_set_sha256": "e" * 64,
          "contamination_check": {"check": "contamination", "status": "PASS", "sub_checks": [{"name": n, "status": "PASS"} for n in ("exact", "near", "canary", "fingerprint_set")]}}
    d5 = {"format": DC.DATA5_FORMAT, "bound_corpus_identity_sha256": identity, "custodian": "custodian-b", "creator": "creator-a", "rehash_sha256": identity}
    return d1, d2, d5


def test_draft_card_is_always_possible_and_clearly_watermarked(files):
    rep = full_report(files)
    card = DC.build_card(build(files), rep)
    md = DC.render_markdown(card)
    assert card["card_status"] == "DRAFT" and card["watermark"].startswith("DRAFT") and md.startswith("> **DRAFT") and md.rstrip().splitlines()[-1].startswith("> **DRAFT")
    assert card["note"] is None
    assert [s["status"] for s in card["quality_statuses"]] == [s["status"] for s in rep["statuses"]]
    assert card["bound_evidence"] is None and DC.render_json(card).endswith("\n")


@pytest.mark.parametrize("drop", ["d1", "d2", "d5"])
def test_final_card_refused_when_any_evidence_missing(files, drop):
    d = dict(zip(("d1", "d2", "d5"), evidence()))
    d[drop] = None
    with pytest.raises(DC.DataCardRefused) as ei:
        DC.build_card(build(files), full_report(files), final=True, corpus_identity_sha256=ID, data1=d["d1"], data2=d["d2"], data5=d["d5"])
    assert any("not supplied" in p for p in ei.value.problems)


def test_final_card_refused_without_any_evidence_or_identity(files):
    with pytest.raises(DC.DataCardRefused) as ei:
        DC.build_card(build(files), full_report(files), final=True)
    assert len(ei.value.problems) >= 4


def test_final_card_refused_for_inconsistent_evidence(files):
    d1, d2, d5 = evidence()
    cases = {
        "mismatched identity": (d1, dict(d2, bound_corpus_identity_sha256="f" * 64), d5),
        "failing contamination": (d1, dict(d2, contamination_check={"check": "contamination", "status": "NOT_EVALUATED", "sub_checks": []}), d5),
        "creator is custodian": (d1, d2, dict(d5, custodian="Creator-A")),
        "rehash differs": (d1, d2, dict(d5, rehash_sha256="9" * 64)),
        "no sources": (dict(d1, sources=[]), d2, d5),
        "wrong format": (dict(d1, format="x"), d2, d5),
    }
    for name, (a, b, c) in cases.items():
        with pytest.raises(DC.DataCardRefused):
            DC.build_card(build(files), full_report(files), final=True, corpus_identity_sha256=ID, data1=a, data2=b, data5=c)
        assert name


def test_final_card_refused_when_report_is_for_a_different_train_file(files, tmp_path):
    other = write_jsonl(tmp_path / "other.jsonl", distinct_records(4, offset=9000))
    rep = R.build_report(other)
    with pytest.raises(DC.DataCardRefused) as ei:
        DC.build_card(build(files), rep, final=True, corpus_identity_sha256=ID, data1=evidence()[0], data2=evidence()[1], data5=evidence()[2])
    assert any("different train file" in p for p in ei.value.problems)
    draft = DC.build_card(build(files), rep)
    assert draft["card_status"] == "DRAFT" and draft["draft_problems"]


def test_final_card_produced_only_with_consistent_evidence_and_says_it_is_not_acceptance(files):
    d1, d2, d5 = evidence()
    card = DC.build_card(build(files), full_report(files), final=True, corpus_identity_sha256=ID, data1=d1, data2=d2, data5=d5)
    md = DC.render_markdown(card)
    assert card["card_status"] == "FINAL" and card["watermark"] is None and "WATERMARK" not in md and "> **DRAFT" not in md
    assert "NOT acceptance" in card["note"] and "DATA-4" in card["note"] and card["bound_evidence"]["corpus_identity_sha256"] == ID
    assert card["card_digest"] == DC.digest_of({k: v for k, v in card.items() if k != "card_digest"})
