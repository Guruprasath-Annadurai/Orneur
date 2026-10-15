"""Immutable result manifest: append-only content-addressed hash chain, provenance records, refusal rules, and the verification CLI."""
import copy
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from orca.evalinfra import synthetic as SY
from orca.evalinfra.canon import GENESIS_HASH, canonical, obj_hash
from orca.evalinfra.chain import ChainLog
from orca.evalinfra.config_lock import config_hash
from orca.evalinfra.errors import ChainCorrupt, LeakageDetected, PreregViolation, SchemaViolation
from orca.evalinfra.leakage import LeakGuard
from orca.evalinfra.results import KINDS, RESULT_SCHEMA, EvalLog, verify_log

ROOT = Path(__file__).resolve().parents[1]
CATS = (3, 10, 11, 12, 14, 15, 17)


# ------------------------------------------------------------------------------------------------ the chain itself
def make_chain(tmp_path, n=5):
    c = ChainLog(tmp_path / "c.jsonl")
    for i in range(n):
        c.append("K", {"i": i, "text": f"payload {i}"})
    return c


def lines(c):
    return c.path.read_text().split("\n")[:-1]


def test_chain_is_content_addressed_and_linked(tmp_path):
    c = make_chain(tmp_path)
    es = c.entries()
    assert [e["seq"] for e in es] == list(range(5)) and es[0]["prev_hash"] == GENESIS_HASH
    for a, b in zip(es, es[1:]):
        assert b["prev_hash"] == a["entry_hash"]
    assert all(e["content_id"] == obj_hash(e["payload"]) for e in es)
    assert c.head() == {"seq": 4, "entry_hash": es[-1]["entry_hash"]}
    assert ChainLog(tmp_path / "nope.jsonl").entries() == [] and ChainLog(tmp_path / "nope.jsonl").head() == {"seq": -1, "entry_hash": GENESIS_HASH}


def rewrite(c, ls):
    c.path.write_text("\n".join(ls) + "\n")


def code_of(c, **kw):
    with pytest.raises(ChainCorrupt) as e:
        c.entries(**kw)
    return e.value.code


def test_payload_edit_detected(tmp_path):
    c = make_chain(tmp_path)
    ls = lines(c)
    ls[2] = ls[2].replace("payload 2", "payload X")
    rewrite(c, ls)
    assert code_of(c) in ("ENTRY_HASH_MISMATCH", "CONTENT_ID_MISMATCH")


def test_consistent_rewrite_of_an_entry_still_breaks_the_chain_after_it(tmp_path):
    c = make_chain(tmp_path)
    ls = lines(c)
    e = json.loads(ls[2])
    e["payload"] = {"i": 2, "text": "forged"}
    e["content_id"] = obj_hash(e["payload"])
    e["entry_hash"] = obj_hash({k: v for k, v in e.items() if k != "entry_hash"})
    ls[2] = canonical(e)
    rewrite(c, ls)
    assert code_of(c) == "BROKEN_CHAIN"


def test_deletion_reorder_insertion_and_duplication_detected(tmp_path):
    c = make_chain(tmp_path)
    ls = lines(c)
    rewrite(c, ls[:1] + ls[2:])
    assert code_of(c) == "SEQUENCE_GAP"
    rewrite(c, [ls[0], ls[2], ls[1]] + ls[3:])
    assert code_of(c) == "SEQUENCE_GAP"
    rewrite(c, ls[:3] + [ls[2]] + ls[3:])
    assert code_of(c) == "SEQUENCE_GAP"


def test_truncated_final_line_and_non_canonical_serialization_detected(tmp_path):
    c = make_chain(tmp_path)
    raw = c.path.read_text()
    c.path.write_text(raw[:-20])
    assert code_of(c) == "TRUNCATED_LINE"
    c.path.write_text(raw.replace('"i":1,', '"i": 1,', 1))
    assert code_of(c) in ("NON_CANONICAL_LINE", "ENTRY_HASH_MISMATCH", "CONTENT_ID_MISMATCH")
    c.path.write_text(raw.replace("\n", "\n\n", 1))
    assert code_of(c) in ("UNPARSEABLE_LINE",)


def test_rollback_to_a_clean_prefix_is_only_detectable_with_an_external_anchor(tmp_path):
    c = make_chain(tmp_path)
    anchor = c.head()
    ls = lines(c)
    rewrite(c, ls[:3])                                                          # drop the newest two whole entries
    assert len(c.entries()) == 3                                                # internally consistent: undetectable without the anchor (documented limit)
    assert code_of(c, expected_head=anchor) == "HEAD_MISMATCH"
    c.path.unlink()
    assert code_of(c, expected_head=anchor) == "HEAD_MISMATCH"


def test_unknown_kind_refused_on_append_and_on_read(tmp_path):
    c = ChainLog(tmp_path / "k.jsonl", allowed_kinds=("A",))
    with pytest.raises(ChainCorrupt):
        c.append("B", {})
    ChainLog(tmp_path / "k.jsonl").append("B", {})
    with pytest.raises(ChainCorrupt):
        c.entries()


def test_append_refuses_to_extend_a_corrupt_chain(tmp_path):
    c = make_chain(tmp_path)
    ls = lines(c)
    rewrite(c, ls[:1] + ls[2:])
    with pytest.raises(ChainCorrupt):
        c.append("K", {"i": 99})
    assert len(lines(c)) == 4


def test_concurrent_appends_keep_a_valid_contiguous_chain(tmp_path):
    c = ChainLog(tmp_path / "t.jsonl")
    errs = []

    def work(k):
        try:
            for j in range(5):
                ChainLog(tmp_path / "t.jsonl").append("K", {"t": k, "j": j})
        except Exception as e:           # pragma: no cover
            errs.append(e)
    ts = [threading.Thread(target=work, args=(k,)) for k in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and [e["seq"] for e in c.entries()] == list(range(30))


def test_nan_and_infinity_have_no_canonical_form(tmp_path):
    with pytest.raises(ValueError):
        make_chain(tmp_path, 0).append("K", {"x": float("nan")})


# ------------------------------------------------------------------------------------------------ the evaluation log
@pytest.fixture(scope="module")
def done(tmp_path_factory):
    d = tmp_path_factory.mktemp("res")
    ex = SY.build_experiment(d / "log.jsonl", seed=41, categories=CATS, holdout_per_cat=6, arms=("B0", "B2", "T2"))
    return ex, d / "log.jsonl"


def fresh(tmp_path, arms=("T2",), guard=None):
    items = SY.make_items(51, CATS, {"SCREEN": 2, "QUALIFICATION_HOLDOUT": 4, "DEV": 2, "TRAIN": 2})
    manifest = SY.make_manifest(items)
    prereg = SY.make_prereg(manifest)
    plan = SY.make_plan(prereg, CATS)
    log = EvalLog(tmp_path / "log.jsonl", leak_guard=guard or LeakGuard(items=items, canaries=["CANARY-RES-3a9f1c7e5d2b4086"]))
    log.record_dataset(manifest)
    log.freeze_prereg(prereg, allow_synthetic=True)
    log.freeze_plan(plan)
    cfgs = {a: SY.make_config(a) for a in arms}
    for c in cfgs.values():
        log.lock_config(c)
    part = {p["split"]: p["partition_sha256"] for p in manifest["partitions"]}

    def result(arm="T2", replicate=0, split="QUALIFICATION_HOLDOUT", **over):
        r = {"schema_version": RESULT_SCHEMA, "run_id": f"{arm}-{replicate}", "arm": arm, "replicate": replicate, "split": split, "synthetic": True,
             "provenance": {"code_sha": cfgs[arm]["code_sha"], "config_hash": config_hash(cfgs[arm]), "dataset_commitment": part[split], "prereg_hash": prereg["record_sha256"]},
             "rows": SY.draw_outcomes(items, split, arm, replicate, 1)}
        r.update(over)
        return r
    return log, manifest, result, items


def refused(log, manifest, r, exc=PreregViolation):
    n = len(log.log.entries())
    with pytest.raises(exc) as e:
        log.record_result(r, manifest=manifest)
    assert len(log.log.entries()) == n                                          # a refusal appends nothing
    return e.value.code


def test_leak_guard_must_be_supplied_explicitly(tmp_path):
    with pytest.raises(SchemaViolation) as e:
        EvalLog(tmp_path / "x.jsonl", leak_guard=None)
    assert e.value.code == "LEAK_GUARD_REQUIRED"


def test_valid_result_is_recorded_with_provenance_and_verifies(tmp_path):
    log, manifest, result, _ = fresh(tmp_path)
    e = log.record_result(result(), manifest=manifest)
    assert set(e["payload"]["provenance"]) == {"code_sha", "config_hash", "dataset_commitment", "prereg_hash"}
    s = verify_log(log.log.path)
    assert s["ok"] and s["results"] == 1 and s["synthetic"] is True and s["arms_locked"] == ["T2"] and s["kinds"]["RESULT"] == 1


def test_duplicate_result_for_same_arm_replicate_split_refused_no_overwrite(tmp_path):
    log, manifest, result, _ = fresh(tmp_path)
    log.record_result(result(), manifest=manifest)
    assert refused(log, manifest, result(run_id="again")) == "DUPLICATE_RESULT"
    log.record_result(result(replicate=1), manifest=manifest)


def test_partial_or_mismatched_coverage_refused(tmp_path):
    log, manifest, result, _ = fresh(tmp_path)
    r = result()
    r["rows"] = r["rows"][:-1]
    assert refused(log, manifest, r) == "RESULT_DOES_NOT_COVER_SPLIT"
    r = result()
    r["rows"][0]["category"] = 99
    assert refused(log, manifest, r) == "RESULT_DOES_NOT_COVER_SPLIT"
    r = result()
    r["rows"][0]["item_id"] = "syn-" + "ee" * 12
    assert refused(log, manifest, r) == "RESULT_DOES_NOT_COVER_SPLIT"


def test_provenance_mismatches_refused(tmp_path):
    log, manifest, result, _ = fresh(tmp_path)
    for field, code in (("dataset_commitment", "DATASET_COMMITMENT_MISMATCH"), ("prereg_hash", "PREREG_HASH_MISMATCH"), ("code_sha", "CODE_SHA_MISMATCH")):
        r = result()
        r["provenance"][field] = "7" * (40 if field == "code_sha" else 64)
        assert refused(log, manifest, r) == code
    r = result(split="SCREEN")
    r["provenance"]["dataset_commitment"] = result()["provenance"]["dataset_commitment"]      # the HOLDOUT commitment presented for SCREEN
    assert refused(log, manifest, r) == "DATASET_COMMITMENT_MISMATCH"


def test_manifest_other_than_the_committed_one_refused(tmp_path):
    log, manifest, result, items = fresh(tmp_path)
    other = SY.make_manifest(SY.make_items(77, CATS, {"SCREEN": 2, "QUALIFICATION_HOLDOUT": 4, "DEV": 2, "TRAIN": 2}))
    assert refused(log, other, result()) == "MANIFEST_NOT_THE_COMMITTED_ONE"


def test_synthetic_flag_mismatch_refused(tmp_path):
    log, manifest, result, _ = fresh(tmp_path)
    assert refused(log, manifest, result(synthetic=False)) == "SYNTHETIC_FLAG_MISMATCH"


@pytest.mark.parametrize("mutate,code", [
    (lambda r: r.update(extra=1), "RESULT_SCHEMA"), (lambda r: r["rows"][0].update(prompt="x"), "ROW_SCHEMA"), (lambda r: r["rows"][0].update(note="x"), "ROW_SCHEMA"),
    (lambda r: r["rows"][0].update(score=1.5), "ROW_SCORE"), (lambda r: r["rows"][0].update(score=float("nan")), "ROW_SCORE"), (lambda r: r["rows"][0].update(score=True), "ROW_SCORE"),
    (lambda r: r["rows"].append(copy.deepcopy(r["rows"][0])), "DUPLICATE_ROW"), (lambda r: r.update(arm="Z"), "RESULT_HEADER"), (lambda r: r.update(replicate=-1), "RESULT_HEADER"),
    (lambda r: r["provenance"].pop("config_hash"), "PROVENANCE_SCHEMA"), (lambda r: r["provenance"].update(code_sha="abc"), "PROVENANCE_VALUES"), (lambda r: r.update(rows=[]), "RESULT_NO_ROWS")])
def test_result_schema_is_a_strict_whitelist_with_no_free_text_fields(tmp_path, mutate, code):
    log, manifest, result, _ = fresh(tmp_path)
    r = result()
    mutate(r)
    assert refused(log, manifest, r, SchemaViolation) == code


def test_leakage_is_refused_before_anything_is_appended(tmp_path):
    log, manifest, result, items = fresh(tmp_path)
    r = result(run_id="debug CANARY-RES-3a9f1c7e5d2b4086 dump")
    assert refused(log, manifest, r, LeakageDetected) == "LEAKAGE"
    r = result(run_id=" ".join(next(i for i in items if i["split"] == "QUALIFICATION_HOLDOUT")["prompt"].split()[:12]))
    assert refused(log, manifest, r, LeakageDetected) == "LEAKAGE"


def test_dataset_prereg_and_plan_are_single_shot_and_ordered(tmp_path):
    log, manifest, result, items = fresh(tmp_path)
    with pytest.raises(PreregViolation):
        log.record_dataset(manifest)
    with pytest.raises(PreregViolation):
        log.freeze_prereg(SY.make_prereg(manifest), allow_synthetic=True)
    with pytest.raises(PreregViolation):
        log.freeze_plan(SY.make_plan(SY.make_prereg(manifest), CATS))


# ------------------------------------------------------------------------------------------------ verification from the file alone
def test_verify_accepts_the_genuine_log(done):
    ex, path = done
    s = verify_log(path)
    assert s["ok"] and s["results"] == 9 and s["entries"] == 1 + 1 + 1 + 3 + 9 and s["synthetic"] and not s["mixed_synthetic_and_real"]
    assert verify_log(path, expected_head=s["head"])["ok"]


def forge(tmp_path, mutate_entries):
    """Write a log through the raw chain (bypassing EvalLog's checks) so verify_log must catch semantic violations by itself."""
    log, manifest, result, _ = fresh(tmp_path)
    log.record_result(result(), manifest=manifest)
    es = log.log.entries()
    out = ChainLog(tmp_path / "forged.jsonl")
    for k, p in mutate_entries([(e["kind"], copy.deepcopy(e["payload"])) for e in es]):
        out.append(k, p)
    return out.path


def test_verify_catches_semantically_forged_but_chain_consistent_logs(tmp_path):
    def swap_config_hash(es):
        for k, p in es:
            if k == "RESULT":
                p["provenance"]["config_hash"] = "6" * 64
        return es
    (tmp_path / "a").mkdir()
    with pytest.raises(PreregViolation) as e:
        verify_log(forge(tmp_path / "a", swap_config_hash))
    assert "differs from the locked one" in str(e.value)

    def result_first(es):
        res = [x for x in es if x[0] == "RESULT"]
        return res + [x for x in es if x[0] != "RESULT"]
    (tmp_path / "b").mkdir()
    with pytest.raises(PreregViolation) as e:
        verify_log(forge(tmp_path / "b", result_first))
    assert "missing or recorded after the first result" in str(e.value)

    def dup(es):
        return es + [x for x in es if x[0] == "RESULT"]
    (tmp_path / "c").mkdir()
    with pytest.raises(PreregViolation) as e:
        verify_log(forge(tmp_path / "c", dup))
    assert "duplicate result" in str(e.value)

    def mix(es):
        for k, p in es:
            if k == "RESULT":
                p["synthetic"] = False
        return es
    (tmp_path / "d").mkdir()
    with pytest.raises(PreregViolation):
        verify_log(forge(tmp_path / "d", mix))

    def lock_late(es):
        locks = [x for x in es if x[0] == "CONFIG_LOCK"]
        return [x for x in es if x[0] != "CONFIG_LOCK"] + locks
    (tmp_path / "e").mkdir()
    with pytest.raises(PreregViolation) as e:
        verify_log(forge(tmp_path / "e", lock_late))
    assert "CONFIG_LOCK was recorded after the first result" in str(e.value)

    def two_preregs(es):
        return es[:2] + [x for x in es if x[0] == "PREREG_FROZEN"] + es[2:]
    (tmp_path / "f").mkdir()
    with pytest.raises(PreregViolation) as e:
        verify_log(forge(tmp_path / "f", two_preregs))
    assert "more than once" in str(e.value)


def test_verify_detects_raw_file_tampering_and_rollback(done, tmp_path):
    ex, path = done
    text = path.read_text()
    bad = tmp_path / "bad.jsonl"
    bad.write_text(text.replace('"replicate":0', '"replicate":1', 1))
    with pytest.raises(ChainCorrupt):
        verify_log(bad)
    head = verify_log(path)["head"]
    short = tmp_path / "short.jsonl"
    short.write_text("\n".join(text.split("\n")[:-3]) + "\n")
    assert verify_log(short)["ok"]                                              # still a valid prefix on its own ...
    with pytest.raises(ChainCorrupt):
        verify_log(short, expected_head=head)                                   # ... but not against the anchored head


# ------------------------------------------------------------------------------------------------ verification CLI
def cli(*args):
    return subprocess.run([sys.executable, "-m", "orca.evalinfra", *args], capture_output=True, text=True, cwd=ROOT, timeout=120)


def test_cli_verify_ok_tampered_and_anchored(done, tmp_path):
    ex, path = done
    r = cli("verify", str(path))
    assert r.returncode == 0 and "SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY" in r.stderr
    s = json.loads(r.stdout)
    assert s["ok"] and s["results"] == 9
    ok = cli("verify", str(path), "--head-seq", str(s["head"]["seq"]), "--head-hash", s["head"]["entry_hash"])
    assert ok.returncode == 0
    wrong = cli("verify", str(path), "--head-seq", "3", "--head-hash", "0" * 64)
    assert wrong.returncode == 1 and "REFUSED" in wrong.stderr
    bad = tmp_path / "bad.jsonl"
    bad.write_text(path.read_text().replace('"score":1.0', '"score":0.0', 1))
    t = cli("verify", str(bad))
    assert t.returncode == 1 and "REFUSED" in t.stderr
    missing = cli("verify", str(tmp_path / "missing.jsonl"))
    assert missing.returncode == 0 and json.loads(missing.stdout)["entries"] == 0          # an empty log verifies trivially: anchor it to detect deletion
    assert cli("verify", str(tmp_path / "missing.jsonl"), "--head-seq", "4", "--head-hash", "1" * 64).returncode == 1


def test_kinds_constant_matches_documented_order():
    assert KINDS == ("DATASET_COMMITMENT", "PREREG_FROZEN", "ANALYSIS_PLAN_FROZEN", "CONFIG_LOCK", "RESULT")
