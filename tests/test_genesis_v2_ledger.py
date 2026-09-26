"""Genesis V2 access ledger: transactional SQLite append, write-once lifecycle, concurrency and crash safety."""
import hashlib
import json
import multiprocessing as mp
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import ledger as L
from orca.eval.genesis_v2 import spec

ROOT = Path(__file__).resolve().parents[1]
CODE = hashlib.sha256(b"registered-qualifier").hexdigest()
DIG = hashlib.sha256(b"corpus").hexdigest()
REG = {"qual": L.RegisteredProcess("qual", CODE, (spec.PURPOSE_QUALIFICATION, spec.PURPOSE_RETIREMENT), ("QUALIFICATION_HOLDOUT",)),
       "stage1": L.RegisteredProcess("stage1", CODE, (spec.PURPOSE_STAGE1,), ("SCREEN",))}
FROZEN = {"frozen": True}


def req(**kw):
    base = dict(process_id="qual", code_sha256=CODE, purpose=spec.PURPOSE_QUALIFICATION, split="QUALIFICATION_HOLDOUT",
                eval_version=spec.EVAL_VERSION, corpus_digest=DIG, run_id="run-1", candidate_revision="rev-a", candidate_lineage="lin-a",
                timestamp_utc="2026-09-27T00:00:00Z")
    base.update(kw)
    return L.AccessRequest(**base)


def code_of(fn, *a, **k):
    with pytest.raises(L.AccessDenied) as e:
        fn(*a, **k)
    return e.value.code


def test_v1_evidence_is_refused_for_v2():
    for rec in ({"eval_version": "genesis-capability-eval/1.0.0"}, {"split": "HOLDOUT"}, {"item_id": "gce1-reasoning-h0001"}):
        assert code_of(L.reject_v1_evidence, rec) == "V1_EVIDENCE_REFUSED"
    L.reject_v1_evidence({"eval_version": spec.EVAL_VERSION, "split": "QUALIFICATION_HOLDOUT"})


def test_ledger_denies_everything_until_frozen(tmp_path):
    led = L.AccessLedger(tmp_path, REG)                       # real committed state: not frozen
    assert code_of(led.request_access, req()) == "EVAL_NOT_FROZEN"
    assert code_of(led.request_access, req(process_id="stage1", purpose=spec.PURPOSE_STAGE1, split="SCREEN")) == "EVAL_NOT_FROZEN"
    assert led.records() == []


def test_ledger_registered_process_and_purpose_rules(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert code_of(led.request_access, req(process_id="rogue")) == "PROCESS_NOT_PREREGISTERED"
    assert code_of(led.request_access, req(code_sha256="0" * 64)) == "CODE_HASH_MISMATCH"
    for purpose in spec.FORBIDDEN_PURPOSES:
        assert code_of(led.request_access, req(purpose=purpose)) == "FORBIDDEN_PURPOSE"
    assert code_of(led.request_access, req(process_id="stage1", purpose=spec.PURPOSE_QUALIFICATION)) == "PURPOSE_NOT_PERMITTED"
    assert code_of(led.request_access, req(process_id="stage1", purpose=spec.PURPOSE_STAGE1)) == "PURPOSE_NOT_PERMITTED"
    assert code_of(led.request_access, req(split="DEV")) == "NOT_A_PRIVATE_SPLIT"
    assert code_of(led.request_access, req(eval_version="genesis-capability-eval/1.0.0")) == "WRONG_EVAL_VERSION"
    assert code_of(led.request_access, req(corpus_digest="nothex")) == "BAD_CORPUS_DIGEST"
    assert code_of(led.request_access, req(run_id="")) == "MISSING_FIELD"
    assert code_of(led.request_access, req(timestamp_utc="")) == "MISSING_FIELD"
    assert led.records() == []


def test_record_contents_chain_and_anchor(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    r0 = led.request_access(req(process_id="stage1", purpose=spec.PURPOSE_STAGE1, split="SCREEN", run_id="s1"))
    r1 = led.request_access(req())
    for f in L.REQUIRED_FIELDS:
        assert r1[f] not in (None, "")
    assert (r0["seq"], r1["seq"]) == (0, 1) and r1["prev_hash"] == r0["record_hash"] and r0["prev_hash"] == L.GENESIS_HASH
    assert led.verify_chain() == 2
    anchor = led.head_anchor()
    assert anchor == {"seq": 1, "record_hash": r1["record_hash"]}
    assert led.verify_chain(expected_head=anchor) == 2
    assert led.get_grant("run-1")["record_hash"] == r1["record_hash"]


def _raw(tmp_path):
    return sqlite3.connect(tmp_path / "ledger.sqlite3", isolation_level=None)


def test_records_are_immutable_at_the_database_level(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    led.request_access(req())
    c = _raw(tmp_path)
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE records SET body='{}' WHERE seq=0")
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM records WHERE seq=0")
    assert led.verify_chain() == 1


def test_tamper_delete_reorder_and_dropped_guards_are_detected(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    led.request_access(req(process_id="stage1", purpose=spec.PURPOSE_STAGE1, split="SCREEN", run_id="s1"))
    led.request_access(req())
    led.request_access(req(run_id="run-2", candidate_lineage="lin-b"))
    anchor = led.head_anchor()
    c = _raw(tmp_path)
    for t in ("records_no_update", "records_no_delete"):
        c.execute(f"DROP TRIGGER {t}")
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain()                                                       # guards removed => refuse
    c.execute("CREATE TRIGGER records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'x'); END")
    c.execute("CREATE TRIGGER records_no_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'x'); END")
    assert led.verify_chain() == 3
    # tamper a body (needs the trigger dropped by an attacker with file access)
    c.execute("DROP TRIGGER records_no_update")
    c.execute("UPDATE records SET body=replace(body,'lin-a','lin-x') WHERE seq=1")
    c.execute("CREATE TRIGGER records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'x'); END")
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain()
    c.execute("DROP TRIGGER records_no_update")
    c.execute("UPDATE records SET body=replace(body,'lin-x','lin-a') WHERE seq=1")
    c.execute("CREATE TRIGGER records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'x'); END")
    assert led.verify_chain() == 3
    # truncation of the newest record is only detectable against the external anchor
    c.execute("DROP TRIGGER records_no_delete")
    c.execute("DELETE FROM records WHERE seq=2")
    c.execute("CREATE TRIGGER records_no_delete BEFORE DELETE ON records BEGIN SELECT RAISE(ABORT,'x'); END")
    assert led.verify_chain() == 2
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain(expected_head=anchor)
    # deleting a middle record => gap
    c.execute("DROP TRIGGER records_no_delete")
    c.execute("DELETE FROM records WHERE seq=0")
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain()


def test_reordered_sequence_is_detected(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    led.request_access(req(process_id="stage1", purpose=spec.PURPOSE_STAGE1, split="SCREEN", run_id="s1"))
    led.request_access(req())
    c = _raw(tmp_path)
    c.execute("DROP TRIGGER records_no_update")
    c.execute("UPDATE records SET seq=100 WHERE seq=0")
    c.execute("UPDATE records SET seq=0 WHERE seq=1")
    c.execute("UPDATE records SET seq=1 WHERE seq=100")
    c.execute("CREATE TRIGGER records_no_update BEFORE UPDATE ON records BEGIN SELECT RAISE(ABORT,'x'); END")
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain()


def test_write_once_per_lineage_and_fresh_version_for_adaptation(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert led.holdout_state(spec.EVAL_VERSION)["state"] == spec.STATE_SEALED
    led.request_access(req())
    assert led.holdout_state(spec.EVAL_VERSION)["state"] == spec.STATE_OPENED
    assert code_of(led.request_access, req(run_id="run-2")) == "HOLDOUT_ALREADY_OPENED"
    assert code_of(led.request_access, req(run_id="run-3", candidate_revision="rev-b")) == "HOLDOUT_ALREADY_OPENED"
    assert code_of(led.request_access, req(run_id="run-4", candidate_lineage="lin-b", candidate_revision="rev-c",
                                           derived_from_lineages=("lin-a",))) == "FRESH_HOLDOUT_VERSION_REQUIRED"
    led.request_access(req(run_id="run-5", candidate_lineage="lin-independent", candidate_revision="rev-z"))
    assert led.verify_chain() == 2


def test_duplicate_run_and_retry_never_create_a_second_authorization(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    first = led.request_access(req())
    for _ in range(3):                                                       # retries of the very same request
        assert code_of(led.request_access, req()) == "RUN_ALREADY_GRANTED"
    assert code_of(led.request_access, req(candidate_lineage="lin-other")) == "RUN_ALREADY_GRANTED"     # same run id, different lineage
    assert len(led.records()) == 1 and led.get_grant("run-1")["record_hash"] == first["record_hash"]


def test_results_are_idempotent_and_conflict_is_refused(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert code_of(led.request_access, req(purpose=spec.PURPOSE_RETIREMENT, run_id="r")) == "NOT_OPENED"
    led.request_access(req())
    rd = hashlib.sha256(b"result").hexdigest()
    assert code_of(led.record_result, "unknown", rd, "t") == "UNKNOWN_RUN"
    assert code_of(led.record_result, "run-1", "nothex", "t") == "BAD_RESULT_DIGEST"
    a = led.record_result("run-1", rd, "2026-09-27T01:00:00Z")
    b = led.record_result("run-1", rd, "2026-09-27T02:00:00Z")               # idempotent: same record, no new row
    assert a["record_hash"] == b["record_hash"] and len(led.records()) == 2
    assert code_of(led.record_result, "run-1", hashlib.sha256(b"different").hexdigest(), "t") == "RESULT_CONFLICT"
    assert led.verify_chain() == 2


def test_retirement_rules(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert code_of(led.request_access, req(purpose=spec.PURPOSE_RETIREMENT, run_id="early")) == "NOT_OPENED"      # cannot disclose while sealed
    led.request_access(req())
    led.request_access(req(purpose=spec.PURPOSE_RETIREMENT, run_id="retire-1"))
    assert led.holdout_state(spec.EVAL_VERSION)["state"] == spec.STATE_RETIRED
    assert code_of(led.request_access, req(run_id="run-9", candidate_lineage="lin-new")) == "HOLDOUT_RETIRED"     # retired holdout qualifies nothing
    assert code_of(led.request_access, req(purpose=spec.PURPOSE_STAGE1, split="SCREEN", process_id="qual", run_id="x")) == "PURPOSE_NOT_PERMITTED"


# ---------------------------------------------------------------- concurrency (real processes) and crash safety
def _worker(args):
    d, code, run_id, lineage = args
    reg = {"qual": L.RegisteredProcess("qual", code, (spec.PURPOSE_QUALIFICATION,), ("QUALIFICATION_HOLDOUT",))}
    led = L.AccessLedger(Path(d), reg, freeze={"frozen": True})
    try:
        r = led.request_access(L.AccessRequest("qual", code, spec.PURPOSE_QUALIFICATION, "QUALIFICATION_HOLDOUT", spec.EVAL_VERSION, DIG, run_id, "rev",
                                               lineage, timestamp_utc="2026-09-27T00:00:00Z"))
        return ("OK", r["seq"])
    except L.AccessDenied as e:
        return (e.code, None)


def test_concurrent_same_lineage_race_grants_exactly_one(tmp_path):
    L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    with mp.get_context("spawn").Pool(8) as pool:
        out = pool.map(_worker, [(str(tmp_path), CODE, f"run-{i}", "lin-same") for i in range(16)])
    assert sum(1 for s, _ in out if s == "OK") == 1
    assert {s for s, _ in out} <= {"OK", "HOLDOUT_ALREADY_OPENED"}
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert led.verify_chain() == 1 and len(led.records()) == 1


def test_concurrent_same_run_id_grants_exactly_one(tmp_path):
    L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    with mp.get_context("spawn").Pool(8) as pool:
        out = pool.map(_worker, [(str(tmp_path), CODE, "run-dup", f"lin-{i}") for i in range(16)])
    assert sum(1 for s, _ in out if s == "OK") == 1 and {s for s, _ in out} <= {"OK", "RUN_ALREADY_GRANTED"}


def test_concurrent_distinct_lineages_get_unique_contiguous_sequence_numbers(tmp_path):
    L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    with mp.get_context("spawn").Pool(8) as pool:
        out = pool.map(_worker, [(str(tmp_path), CODE, f"run-{i}", f"lin-{i}") for i in range(24)])
    assert all(s == "OK" for s, _ in out)
    seqs = sorted(q for _, q in out)
    assert seqs == list(range(24))                                            # exactly one sequence number per record, no gaps/duplicates
    assert L.AccessLedger(tmp_path, REG, freeze=FROZEN).verify_chain() == 24


def test_interrupted_append_rolls_back_and_leaves_no_grant(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    led.request_access(req(run_id="ok-1", candidate_lineage="lin-1"))

    def boom():
        raise RuntimeError("simulated crash before COMMIT")
    led._fault = boom
    with pytest.raises(RuntimeError):
        led.request_access(req(run_id="crash", candidate_lineage="lin-2"))
    led._fault = None
    assert len(led.records()) == 1 and led.get_grant("crash") is None and led.verify_chain() == 1
    led.request_access(req(run_id="after", candidate_lineage="lin-2"))         # lineage was NOT consumed by the rolled-back attempt
    assert led.verify_chain() == 2


def test_process_killed_mid_transaction_leaves_consistent_ledger(tmp_path):
    L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    prog = (
        "import os,sys,hashlib\n"
        "from pathlib import Path\n"
        "from orca.eval.genesis_v2 import ledger as L, spec\n"
        "code=sys.argv[2]\n"
        "reg={'qual':L.RegisteredProcess('qual',code,(spec.PURPOSE_QUALIFICATION,),('QUALIFICATION_HOLDOUT',))}\n"
        "led=L.AccessLedger(Path(sys.argv[1]),reg,freeze={'frozen':True})\n"
        "led._fault=lambda: os._exit(9)\n"          # hard kill after INSERT, before COMMIT
        "led.request_access(L.AccessRequest('qual',code,spec.PURPOSE_QUALIFICATION,'QUALIFICATION_HOLDOUT',spec.EVAL_VERSION,'a'*64,'kill-run','rev','lin-k',timestamp_utc='t'))\n")
    p = subprocess.run([sys.executable, "-c", prog, str(tmp_path), CODE], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True)
    assert p.returncode == 9
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert led.records() == [] and led.verify_chain() == 0                     # nothing half-written
    led.request_access(req(run_id="kill-run", candidate_lineage="lin-k"))      # the run id and lineage are still free
    assert led.verify_chain() == 1


def test_database_file_permissions_are_restrictive(tmp_path):
    L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert (tmp_path / "ledger.sqlite3").stat().st_mode & 0o077 == 0
