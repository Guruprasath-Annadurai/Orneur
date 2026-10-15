"""CLI behaviour (canonical JSON, exit codes, no timestamps) and the committed public-SFT reports (reproducible, pinned to the classified bytes)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from orca.dataquality import cli
from orca.dataquality import public_sft
from orca.dataquality._common import pretty_json, sha256_file
from tests.dataquality_support import chatml, distinct_records, prov, source_registry, with_prov, write_jsonl

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "docs/orneur/status/dataquality/reports"


def run(args, tmp_path, capsys=None):
    out = tmp_path / "out.json"
    rc = cli.run([*args, "--out", str(out)])
    return rc, json.loads(out.read_text()), out.read_text()


def test_schema_command_exit_codes_and_canonical_output(tmp_path):
    good = write_jsonl(tmp_path / "g.jsonl", distinct_records(4))
    rc, doc, text = run(["schema", str(good)], tmp_path)
    assert rc == 0 and doc["status"] == "PASS" and text == pretty_json(doc)      # canonical: sorted keys, stable formatting
    bad = tmp_path / "b.jsonl"
    bad.write_text("{nope\n")
    rc, doc, _ = run(["schema", str(bad)], tmp_path)
    assert rc == 1 and doc["violations"][0]["line"] == 1


def test_output_has_no_timestamp_unless_now_is_passed(tmp_path):
    t = write_jsonl(tmp_path / "t.jsonl", distinct_records(6))
    rc, doc, _ = run(["report", "--train", str(t)], tmp_path)
    assert "generated_at" not in doc and rc == 1                       # provenance fails closed
    rc, doc, _ = run(["report", "--train", str(t), "--now", "FIXED"], tmp_path)
    assert doc["generated_at"] == "FIXED"
    a = run(["report", "--train", str(t)], tmp_path)[2]
    assert a == run(["report", "--train", str(t)], tmp_path)[2]


def test_not_evaluated_exit_code_3(tmp_path):
    t = write_jsonl(tmp_path / "t.jsonl", distinct_records(6))
    sources = tmp_path / "s.json"
    sources.write_text(json.dumps(source_registry()))
    d = tmp_path / "d.json"
    d.write_text(json.dumps(prov("human")))
    rc, doc, _ = run(["report", "--train", str(t), "--sources", str(sources), "--default-provenance", str(d)], tmp_path)
    st = {s["check"]: s["status"] for s in doc["statuses"]}
    assert st["provenance"] == "PASS" and st["teacher_rights"] == "PASS" and "FAIL" not in st.values() and rc == 3


def test_ingest_gate_command_refuses_unreviewed_teacher(tmp_path):
    f = write_jsonl(tmp_path / "m.jsonl", [with_prov(chatml("q", "a"), prov("model", model_id="llama3.1:8b", model_revision="x"))])
    rc, doc, _ = run(["ingest-gate", str(f)], tmp_path)
    assert rc == 1 and doc["refusals_by_reason"] == {"teacher_status_UNREVIEWED": 1}


def test_teacher_register_commands(tmp_path):
    rc, doc, _ = run(["teacher-register", "validate"], tmp_path)
    assert rc == 0 and doc["status_counts"]["UNREVIEWED"] == 3 and doc["status_counts"]["PERMITTED_RECORDED"] == 0
    inv = ROOT / "docs/orneur/phase-21/GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json"
    rc, derived, _ = run(["teacher-register", "derive", "--inventory", str(inv)], tmp_path)
    assert rc == 0 and [t["status"] for t in derived["teachers"]] == ["UNREVIEWED"] * 3


def test_manifest_build_and_verify_commands(tmp_path):
    t = write_jsonl(tmp_path / "t.jsonl", distinct_records(4))
    m = tmp_path / "m.json"
    assert cli.run(["manifest", "build", "--train", str(t), "--dataset-id", "ds", "--version", "v1", "--creation-code-sha", "a" * 40, "--out", str(m)]) == 0
    rc, doc, _ = run(["manifest", "verify", "--train", str(t), "--manifest", str(m)], tmp_path)
    assert rc == 0 and doc["status"] == "PASS"
    t.write_text(t.read_text() + "\n")
    assert run(["manifest", "verify", "--train", str(t), "--manifest", str(m)], tmp_path)[0] == 1


def test_contamination_and_fingerprint_commands(tmp_path):
    tr = write_jsonl(tmp_path / "t.jsonl", distinct_records(5, offset=10))
    ev = write_jsonl(tmp_path / "e.jsonl", distinct_records(2, offset=900))
    fp = tmp_path / "fp.json"
    assert cli.run(["fingerprint", "--eval", str(ev), "--out", str(fp)]) == 0
    can = tmp_path / "c.txt"
    can.write_text("A-VERY-UNIQUE-CANARY-STRING-12345\n")
    rc, doc, _ = run(["contamination", "--train", str(tr), "--eval", str(ev), "--canaries", str(can), "--fingerprints", str(fp)], tmp_path)
    assert rc == 0 and doc["status"] == "PASS"


def test_datacard_command_draft_ok_final_refused(tmp_path):
    t = write_jsonl(tmp_path / "t.jsonl", distinct_records(5))
    man, rep = tmp_path / "m.json", tmp_path / "r.json"
    cli.run(["manifest", "build", "--train", str(t), "--dataset-id", "ds", "--version", "v1", "--creation-code-sha", "a" * 40, "--out", str(man)])
    cli.run(["report", "--train", str(t), "--out", str(rep)])
    md = tmp_path / "card.md"
    rc, card, _ = run(["datacard", "--manifest", str(man), "--report", str(rep), "--md-out", str(md)], tmp_path)
    assert rc == 0 and card["card_status"] == "DRAFT" and md.read_text().startswith("> **DRAFT")
    assert cli.run(["datacard", "--manifest", str(man), "--report", str(rep), "--final", "--out", str(tmp_path / "x.json")]) == 2
    assert not (tmp_path / "x.json").exists()


def test_usage_errors_return_2(tmp_path):
    assert cli.run(["schema", str(tmp_path / "missing.jsonl")]) == 2
    assert cli.run(["manifest", "build", "--train", str(tmp_path / "x")]) == 2


def test_python_dash_m_entrypoint_emits_json(tmp_path):
    f = write_jsonl(tmp_path / "g.jsonl", distinct_records(3))
    p = subprocess.run([sys.executable, "-m", "orca.dataquality", "schema", str(f)], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert p.returncode == 0 and json.loads(p.stdout)["status"] == "PASS"


# ------------------------------------------------------------------ committed public-SFT reports
def test_public_reports_regenerate_byte_identically(tmp_path):
    written = public_sft.generate(ROOT, tmp_path)
    assert len(written) == 8
    for p in written:
        assert p.read_text() == (REPORTS / p.name).read_text(), f"{p.name} drifted from the committed report; regenerate with `python -m orca.dataquality public-sft`"


def test_public_reports_are_bound_to_the_classified_bytes():
    cls = json.loads((ROOT / public_sft.CLASSIFICATION).read_text())["files"]
    for name in public_sft.PAIRS:
        rep = json.loads((REPORTS / f"{name}.report.json").read_text())
        for side in ("train", "eval"):
            info = rep["dataset"][side]
            assert cls[info["path"]]["sha256"] == info["sha256"] == sha256_file(ROOT / info["path"])
        assert "generated_at" not in rep and rep["aggregate_quality_score"] == "NONE_BY_DESIGN"


def test_generate_refuses_files_that_are_not_the_classified_bytes(tmp_path):
    import shutil
    shutil.copytree(ROOT / "docs/orneur/phase-21", tmp_path / "docs/orneur/phase-21", ignore=shutil.ignore_patterns("*.pdf"))
    (tmp_path / "notebooks").mkdir()
    shutil.copytree(ROOT / "notebooks/data", tmp_path / "notebooks/data")
    victim = tmp_path / "notebooks/data/orca_nano_combined_train_v1.jsonl"
    victim.write_text(victim.read_text() + "\n")
    with pytest.raises(RuntimeError, match="refusing to measure"):
        public_sft.generate(tmp_path, tmp_path / "out")


def test_measured_public_findings_are_pinned():
    """Facts measured on the committed public SFT files; if a data file or a metric changes, this must be re-reviewed, not silently updated."""
    def rep(n):
        r = json.loads((REPORTS / f"{n}.report.json").read_text())
        return {c["check"]: c for c in r["checks"]}, r
    nano, nr = rep("orca_nano_combined_v1")
    lq = nr["supplementary"]["legacy_quick_ratio"]
    assert (lq["quick_ratio_pairs_over_threshold"], lq["pairs_total"], lq["ratio_pairs_over_threshold"]) == (192, 666, 0)
    assert nano["dedup"]["near_duplicates"]["pairs_at_or_above_threshold"] == 0 and nano["dedup"]["template_concentration"]["opening_skeleton"]["top1_share"] == 0.5882
    core, _ = rep("orca_core_combined_v2")
    assert core["dedup"]["exact_normalized"]["groups_by_line"] == [[3, 36, 55], [21, 54, 56, 58], [29, 32, 37, 64]]
    ex = {s["name"]: s for s in core["contamination"]["sub_checks"]}["exact"]
    assert ex["status"] == "FAIL" and ex["train_lines"] == [3, 36, 55]
    for n in public_sft.PAIRS:
        c, r = rep(n)
        st = {s["check"]: s["status"] for s in r["statuses"]}
        assert st["schema"] == "PASS" and st["privacy"] == "PASS" and st["provenance"] == "FAIL" and st["teacher_rights"] == "FAIL"
        assert st["balance"] == st["semantic_diversity"] == st["contamination.canary"] == "NOT_EVALUATED"
