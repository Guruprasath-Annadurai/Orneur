"""Resilience #2-#6 and #8 for the synthetic dry-run: byte-stable content-addressed manifests, checkpoint run-id / hash-chain verification,
crash-at-every-durable-write recovery (never double-counts, never skips), resume-evidence byte identity, cost ceilings that cannot be raised or
bypassed on resume, and one-call tamper-evident run evidence. Pure Python, synthetic, no GPU/network/trainer."""
from __future__ import annotations

import os
import shutil
from unittest import mock

import pytest

from orca.train.dryrun.canon import canonical_bytes
from orca.train.dryrun.ckpt import CheckpointUnverified, SimulatedCrash, save_checkpoint, verify_checkpoint
from orca.train.dryrun.evidence import (EvidenceError, effective_timeline, final_evidence_bytes, manifest_content_id, publish_content_addressed,
                                        verify_checkpoint_set, verify_content_addressed, verify_run_evidence)
from orca.train.dryrun.harness import Fault, RunRefused
from orca.train.dryrun.ledger import RunLedger
from orca.train.dryrun.toy import Plan, ToyEngine, initial_state
from tests.trainprep_support import big_budget, run

PLAN = Plan(checkpoint_every=4)
TS = lambda: "2026-01-01T00:00:00Z"            # noqa: E731 -- fixed clock so evidence is comparable byte for byte


def r(root, plan=PLAN, run_id="r", **kw):
    kw.setdefault("timestamp_fn", TS)
    return run(plan, root, run_id=run_id, **kw)


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    root = tmp_path_factory.mktemp("full") / "run"
    out = r(root)
    return root, out


# ── #2 run manifests: deterministic, byte-stable, content-addressed ──────────────────────────────────────────────────────────

def test_two_identical_runs_seal_byte_identical_manifests_and_ledgers(full, tmp_path):
    root, out = full
    other = r(tmp_path / "again")
    assert other.manifest_path.read_bytes() == out.manifest_path.read_bytes()
    assert (tmp_path / "again" / "ledger.jsonl").read_bytes() == (root / "ledger.jsonl").read_bytes()


def test_manifest_is_content_addressed_and_identical_runs_share_an_address(full, tmp_path):
    root, out = full
    store = tmp_path / "store"
    p = publish_content_addressed(out.manifest_path, store)
    assert p.name == f"sha256-{manifest_content_id(out.manifest_path.read_bytes())}.manifest.json"
    assert verify_content_addressed(p) == []
    again = publish_content_addressed(r(tmp_path / "again").manifest_path, store)         # same content -> same address, idempotent
    assert again == p and len(list(store.iterdir())) == 1


def test_a_different_run_gets_a_different_address(full, tmp_path):
    other = r(tmp_path / "o", plan=Plan(seed=7, checkpoint_every=4))
    assert manifest_content_id(other.manifest_path.read_bytes()) != manifest_content_id(full[1].manifest_path.read_bytes())


def test_edited_or_renamed_content_addressed_manifest_is_detected(full, tmp_path):
    p = publish_content_addressed(full[1].manifest_path, tmp_path / "s")
    os.chmod(p, 0o644)
    p.write_bytes(p.read_bytes().replace(b"synthetic", b"syntheti_"))
    assert verify_content_addressed(p) == ["CONTENT_ADDRESS_MISMATCH"]
    liar = tmp_path / "s" / ("sha256-" + "f" * 64 + ".manifest.json")
    shutil.copy(full[1].manifest_path, liar)
    assert verify_content_addressed(liar) == ["CONTENT_ADDRESS_MISMATCH"]
    assert verify_content_addressed(tmp_path / "s" / "plain.manifest.json") == ["NOT_A_CONTENT_ADDRESSED_NAME"]


def test_publishing_over_a_conflicting_address_is_refused(full, tmp_path):
    store = tmp_path / "s"
    p = publish_content_addressed(full[1].manifest_path, store)
    os.chmod(p, 0o644)
    p.write_bytes(b"{}")
    with pytest.raises(EvidenceError):
        publish_content_addressed(full[1].manifest_path, store)


# ── #3 checkpoint verification: run id, hash chain, ordering ─────────────────────────────────────────────────────────────────

def _saved(tmp_path, run_id="run-x"):
    eng, st = ToyEngine(PLAN), initial_state(PLAN)
    for _ in range(3):
        st = eng.compute_step(st)
    save_checkpoint(tmp_path / "ck", st, PLAN, run_id)
    return tmp_path / "ck"


def test_wrong_run_id_is_refused(tmp_path):
    ck = _saved(tmp_path)
    assert verify_checkpoint(ck, "ckpt-000003", expected_plan_sha256=PLAN.sha256, expected_run_id="run-x").step == 3
    with pytest.raises(CheckpointUnverified):
        verify_checkpoint(ck, "ckpt-000003", expected_plan_sha256=PLAN.sha256, expected_run_id="run-y")


def test_a_checkpoint_transplanted_from_another_run_is_quarantined_on_resume(tmp_path):
    r(tmp_path / "a", budget=big_budget(max_steps=8))
    r(tmp_path / "evil", run_id="evil", budget=big_budget(max_steps=8))                       # same plan => byte-identical artifact digest
    a = tmp_path / "a" / "checkpoints"
    shutil.rmtree(a / "ckpt-000008")
    (a / "ckpt-000008.manifest.json").unlink()
    shutil.copytree(tmp_path / "evil" / "checkpoints" / "ckpt-000008", a / "ckpt-000008")
    shutil.copy(tmp_path / "evil" / "checkpoints" / "ckpt-000008.manifest.json", a / "ckpt-000008.manifest.json")
    out = r(tmp_path / "a", resume=True)
    assert out.status == "FINISHED" and (a / "quarantine").is_dir() and any((a / "quarantine").glob("ckpt-000008.*"))
    assert out.state.sha256 == r(tmp_path / "ref").state.sha256


def test_resume_refuses_when_every_recorded_checkpoint_belongs_to_another_run(tmp_path):
    r(tmp_path / "a", budget=big_budget(max_steps=4))
    r(tmp_path / "evil", run_id="evil", budget=big_budget(max_steps=4))
    a = tmp_path / "a" / "checkpoints"
    shutil.rmtree(a / "ckpt-000004")
    shutil.copytree(tmp_path / "evil" / "checkpoints" / "ckpt-000004", a / "ckpt-000004")
    shutil.copy(tmp_path / "evil" / "checkpoints" / "ckpt-000004.manifest.json", a / "ckpt-000004.manifest.json")
    with pytest.raises(RunRefused) as e:
        r(tmp_path / "a", resume=True)
    assert "NO_VERIFIED_CHECKPOINT" in e.value.reasons


def test_checkpoint_set_of_a_clean_run_verifies_and_has_a_deterministic_chain_head(full, tmp_path):
    root, _ = full
    rep = verify_checkpoint_set(root, PLAN, "r")
    assert rep.problems == [] and len(rep.chain_head) == 64 and rep.names == ["ckpt-000004", "ckpt-000008", "ckpt-000012"]
    r(tmp_path / "again")
    assert verify_checkpoint_set(tmp_path / "again", PLAN, "r").chain_head == rep.chain_head
    other = r(tmp_path / "o", plan=Plan(seed=7, checkpoint_every=4))
    assert verify_checkpoint_set(tmp_path / "o", Plan(seed=7, checkpoint_every=4), "r").chain_head != rep.chain_head and other


def test_checkpoint_set_wrong_run_id_truncated_corrupted_missing_or_extra_are_refused(tmp_path):
    def fresh(name):
        r(tmp_path / name)
        return tmp_path / name

    assert any(p.startswith("CHECKPOINT_UNVERIFIED_ckpt-000004") for p in verify_checkpoint_set(fresh("w"), PLAN, "not-r").problems)
    t = fresh("t")
    f = t / "checkpoints" / "ckpt-000008" / "state.json"
    os.chmod(f, 0o644)
    f.write_bytes(f.read_bytes()[:-5])
    assert any(p.startswith("CHECKPOINT_UNVERIFIED_ckpt-000008") for p in verify_checkpoint_set(t, PLAN, "r").problems)
    c = fresh("c")
    f = c / "checkpoints" / "ckpt-000008" / "state.json"
    os.chmod(f, 0o644)
    b = bytearray(f.read_bytes())
    b[10] ^= 1
    f.write_bytes(bytes(b))
    assert any(p.startswith("CHECKPOINT_UNVERIFIED_ckpt-000008") for p in verify_checkpoint_set(c, PLAN, "r").problems)
    m = fresh("m")
    shutil.rmtree(m / "checkpoints" / "ckpt-000008")
    (m / "checkpoints" / "ckpt-000008.manifest.json").unlink()
    assert "CHECKPOINT_MISSING_ckpt-000008" in verify_checkpoint_set(m, PLAN, "r").problems
    x = fresh("x")
    shutil.copytree(x / "checkpoints" / "ckpt-000004", x / "checkpoints" / "ckpt-000005")
    shutil.copy(x / "checkpoints" / "ckpt-000004.manifest.json", x / "checkpoints" / "ckpt-000005.manifest.json")
    assert any(p.startswith("CHECKPOINT_UNLISTED_ckpt-000005") for p in verify_checkpoint_set(x, PLAN, "r").problems)


def test_checkpoints_swapped_between_names_are_refused(tmp_path):
    r(tmp_path / "s")
    ck = tmp_path / "s" / "checkpoints"
    for n in ("ckpt-000004", "ckpt-000008"):
        os.chmod(ck / n, 0o755)
    os.rename(ck / "ckpt-000004", ck / "tmp-a")
    os.rename(ck / "ckpt-000008", ck / "ckpt-000004")
    os.rename(ck / "tmp-a", ck / "ckpt-000008")
    probs = verify_checkpoint_set(tmp_path / "s", PLAN, "r").problems
    assert any("ckpt-000004" in p for p in probs) and any("ckpt-000008" in p for p in probs)


def test_checkpoints_recorded_out_of_order_in_the_ledger_are_refused(tmp_path):
    root = tmp_path / "o"
    eng, st = ToyEngine(PLAN), initial_state(PLAN)
    states = {}
    for i in range(1, 9):
        st = eng.compute_step(st)
        if i in (4, 8):
            states[i] = st
    led = RunLedger(root / "ledger.jsonl")
    led.append("run_started", plan_sha256=PLAN.sha256, binding={}, synthetic=True, grant=None, env_manifest_sha256="d" * 64, budget={})
    for step in (8, 4):                                                    # a step-8 checkpoint "saved" before the step-4 one
        h = save_checkpoint(root / "checkpoints", states[step], PLAN, "r")
        led.append("checkpoint_saved", step=step, name=h.name, digest=h.digest)
    assert "CHECKPOINT_ORDER" in verify_checkpoint_set(root, PLAN, "r").problems


# ── #4 failure recovery: die at every durable write; #5 resume consistency ──────────────────────────────────────────────────────

def _total_appends(tmp_path):
    n = {"c": 0}
    orig = RunLedger.append

    def count(self, *a, **k):
        n["c"] += 1
        return orig(self, *a, **k)
    with mock.patch.object(RunLedger, "append", count):
        r(tmp_path / "count")
    return n["c"]


def _crash_then_recover(plan, root, n, when):
    orig, calls = RunLedger.append, {"c": 0}

    def dying(self, *a, **k):
        calls["c"] += 1
        if calls["c"] == n and when == "before":
            raise SimulatedCrash(f"died before ledger write #{n}")
        res = orig(self, *a, **k)
        if calls["c"] == n and when == "after":
            raise SimulatedCrash(f"died after ledger write #{n}")
        return res
    with mock.patch.object(RunLedger, "append", dying):
        with pytest.raises(SimulatedCrash):
            r(root, plan)
    led = root / "ledger.jsonl"
    return r(root, plan, resume=led.exists() and led.stat().st_size > 0)


@pytest.mark.parametrize("when", ["before", "after"])
def test_dying_at_every_ledger_write_recovers_without_double_counting_or_skipping(full, tmp_path, when):
    root_full, out_full = full
    ref = final_evidence_bytes(root_full, PLAN)
    for n in range(1, _total_appends(tmp_path) + 1):
        root = tmp_path / f"{when}-{n}"
        out = _crash_then_recover(PLAN, root, n, when)
        tag = f"crash {when} write #{n}"
        assert out.status == "FINISHED" and out.steps == PLAN.total_steps, tag
        assert out.state.sha256 == out_full.state.sha256, tag
        tl, problems = effective_timeline(RunLedger(root / "ledger.jsonl"))
        assert problems == [] and [e["step"] for e in tl] == list(range(1, PLAN.total_steps + 1)), tag      # none skipped, none twice
        assert out.usage["steps"] == PLAN.total_steps and out.usage["tokens"] == PLAN.total_steps * PLAN.tokens_per_step, tag
        assert out.usage["spend_micro_usd"] == PLAN.total_steps * 10_000, tag                              # 0.01 USD/step, counted once
        assert verify_run_evidence(root, PLAN, "r") == [], tag
        assert final_evidence_bytes(root, PLAN) == ref, tag                                                # resumed == uninterrupted


def test_dying_while_saving_a_checkpoint_at_either_point_recovers(full, tmp_path):
    ref = final_evidence_bytes(full[0], PLAN)
    for where in ("files", "renamed"):
        for step in (4, 8, 12):
            root = tmp_path / f"{where}{step}"
            with pytest.raises(SimulatedCrash):
                r(root, fault=Fault(crash_ckpt_at={step: where}))
            out = r(root, resume=True)
            assert out.status == "FINISHED" and verify_run_evidence(root, PLAN, "r") == [] and final_evidence_bytes(root, PLAN) == ref


def test_an_exception_in_every_step_and_micro_batch_recovers_to_the_same_evidence(full, tmp_path):
    ref = final_evidence_bytes(full[0], PLAN)
    for step in range(PLAN.total_steps):
        for micro in range(PLAN.grad_accum):
            root = tmp_path / f"e{step}-{micro}"
            first = r(root, fault=Fault(raise_at=(step, micro)))
            assert first.status == "ABORTED" and first.steps == step
            out = r(root, resume=True)
            tl, problems = effective_timeline(RunLedger(root / "ledger.jsonl"))
            assert problems == [] and len(tl) == PLAN.total_steps and final_evidence_bytes(root, PLAN) == ref and out.status == "FINISHED"


class Kill(BaseException):
    """Stands in for SIGKILL-like interruption (not an Exception, so the harness's generic handler does not absorb it)."""


def _die_at(step, micro):
    def hook(s, m):
        if (s, m) == (step, micro):
            raise Kill()
    return hook


def test_a_crash_before_the_first_checkpoint_restarts_from_the_deterministic_initial_state(full, tmp_path):
    root = tmp_path / "early"
    with pytest.raises(Kill):
        r(root, fault=Fault(on_micro=_die_at(2, 0)))
    out = r(root, resume=True)
    assert out.status == "FINISHED" and out.state.sha256 == full[1].state.sha256
    assert final_evidence_bytes(root, PLAN) == final_evidence_bytes(full[0], PLAN) and verify_run_evidence(root, PLAN, "r") == []


def test_killed_at_every_step_and_micro_batch_then_resumed_matches_the_uninterrupted_evidence(full, tmp_path):
    ref = final_evidence_bytes(full[0], PLAN)
    for step in range(PLAN.total_steps):
        for micro in range(PLAN.grad_accum):
            root = tmp_path / f"k{step}-{micro}"
            with pytest.raises(Kill):
                r(root, fault=Fault(on_micro=_die_at(step, micro)))
            out = r(root, resume=True)
            assert out.status == "FINISHED" and final_evidence_bytes(root, PLAN) == ref and verify_run_evidence(root, PLAN, "r") == [], (step, micro)


def test_resuming_a_sealed_finished_run_is_an_idempotent_noop(full, tmp_path):
    root = tmp_path / "done"
    r(root)
    before = (root / "ledger.jsonl").read_bytes()
    out = r(root, resume=True)
    assert out.status == "FINISHED" and out.state.sha256 == full[1].state.sha256 and (root / "ledger.jsonl").read_bytes() == before


def test_timeline_flags_a_skipped_and_a_double_counted_step(tmp_path):
    led = RunLedger(tmp_path / "l.jsonl")
    led.append("run_started", plan_sha256=PLAN.sha256, binding={}, synthetic=True, grant=None, env_manifest_sha256="d" * 64, budget={})
    led.append("step_committed", step=1, state_sha256="a" * 64, tokens_seen=1, spend_micro_usd=1)
    led.append("step_committed", step=3, state_sha256="b" * 64, tokens_seen=2, spend_micro_usd=2)
    assert effective_timeline(led)[1] == ["STEP_SKIPPED_AT_3"]
    led2 = RunLedger(tmp_path / "l2.jsonl")
    led2.append("run_started", plan_sha256=PLAN.sha256, binding={}, synthetic=True, grant=None, env_manifest_sha256="d" * 64, budget={})
    led2.append("step_committed", step=1, state_sha256="a" * 64, tokens_seen=1, spend_micro_usd=1)
    led2.append("step_committed", step=1, state_sha256="a" * 64, tokens_seen=1, spend_micro_usd=1)
    assert effective_timeline(led2)[1] == ["STEP_DOUBLE_COUNTED_AT_1"]


# ── #6 cost ceilings ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cap", ["max_steps", "max_tokens", "max_wall_clock_s", "max_spend_usd"])
def test_any_zero_cap_refuses_everything_even_a_zero_cost_run(tmp_path, cap):
    root = tmp_path / "z"
    out = r(root, budget=big_budget(**{cap: 0, "sim_cost_usd_per_step": 0.0}))
    assert out.status == "REFUSED" and out.reason == "ZERO_BUDGET" and out.steps == 0
    assert not (root / "checkpoints").exists() or not list((root / "checkpoints").glob("ckpt-*"))
    assert [x["body"]["type"] for x in RunLedger(root / "ledger.jsonl").records()] == ["run_refused", "manifest_sealed"]


def test_resume_with_a_zero_budget_refuses_and_writes_nothing(tmp_path):
    r(tmp_path / "a", budget=big_budget(max_steps=4))
    before = (tmp_path / "a" / "ledger.jsonl").read_bytes()
    with pytest.raises(RunRefused) as e:
        r(tmp_path / "a", resume=True, budget=big_budget(max_steps=0))
    assert "ZERO_BUDGET" in e.value.reasons and (tmp_path / "a" / "ledger.jsonl").read_bytes() == before


def test_resume_with_a_zero_budget_cannot_touch_a_finished_run_either(full, tmp_path):
    root = tmp_path / "f"
    r(root)
    before = (root / "ledger.jsonl").read_bytes()
    with pytest.raises(RunRefused) as e:
        r(root, resume=True, budget=big_budget(max_spend_usd=0))
    assert "ZERO_BUDGET" in e.value.reasons and (root / "ledger.jsonl").read_bytes() == before


@pytest.mark.parametrize("raised", [{"max_tokens": 10 ** 10}, {"max_wall_clock_s": 10 ** 7}, {"max_spend_usd": 5000.0},
                                    {"sim_cost_usd_per_step": 0.001}])
def test_a_ceiling_cannot_be_raised_after_the_run_is_bound(tmp_path, raised):
    r(tmp_path / "a", budget=big_budget(max_steps=4))
    with pytest.raises(RunRefused) as e:
        r(tmp_path / "a", resume=True, budget=big_budget(**raised))
    assert any(x.startswith("BUDGET_RAISED_AFTER_BIND") for x in e.value.reasons)


def test_resume_with_the_same_or_a_tighter_budget_is_still_allowed(tmp_path):
    r(tmp_path / "a", budget=big_budget(max_steps=4))
    out = r(tmp_path / "a", resume=True, budget=big_budget(max_steps=900, max_spend_usd=500.0, sim_cost_usd_per_step=0.02))
    assert out.status == "FINISHED"


def test_editing_the_ceiling_in_the_ledger_or_the_manifest_does_not_move_it(tmp_path):
    from orca.train.dryrun.ledger import verify_sealed_manifest
    out = r(tmp_path / "a", budget=big_budget(max_steps=4))
    led = tmp_path / "a" / "ledger.jsonl"
    led.write_bytes(led.read_bytes().replace(b'"max_steps":4,', b'"max_steps":9999,', 1))               # rewrite the bound budget in place
    with pytest.raises(RunRefused) as e:
        r(tmp_path / "a", resume=True, budget=big_budget(max_steps=9999))
    assert "LEDGER_MISSING_OR_NOT_INTACT" in e.value.reasons
    os.chmod(out.manifest_path, 0o644)                                                                # and the sealed manifest is hash-bound too
    out.manifest_path.write_bytes(out.manifest_path.read_bytes().replace(b"synthetic", b"syntheti_", 1))
    assert verify_sealed_manifest(out.manifest_path, RunLedger(led)) != []


def test_caps_stay_cumulative_when_the_run_is_recovered_after_a_crash(tmp_path):
    b = big_budget(max_steps=6)
    orig, calls = RunLedger.append, {"c": 0}

    def dying(self, *a, **k):
        calls["c"] += 1
        res = orig(self, *a, **k)
        if calls["c"] == 8:
            raise SimulatedCrash("died")
        return res
    with mock.patch.object(RunLedger, "append", dying):
        with pytest.raises(SimulatedCrash):
            r(tmp_path / "c", budget=b)
    out = r(tmp_path / "c", resume=True, budget=b)
    assert (out.status, out.reason, out.steps) == ("STOPPED", "STEP_CAP", 6)


# ── #8 evidence integrity: one call, every artifact ────────────────────────────────────────────────────────────────────────────

def _copy(full, tmp_path, name="ev"):
    dst = tmp_path / name
    shutil.copytree(full[0], dst)
    return dst


def _lines(p):
    return p.read_bytes().splitlines(keepends=True)


def test_clean_run_evidence_verifies(full):
    assert verify_run_evidence(full[0], PLAN, "r") == []


@pytest.mark.parametrize("mutate", ["duplicate", "swap", "delete", "edit", "truncate_tail", "drop_anchor"])
def test_ledger_tampering_is_always_reported(full, tmp_path, mutate):
    d = _copy(full, tmp_path)
    p = d / "ledger.jsonl"
    ls = _lines(p)
    if mutate == "duplicate":
        ls.insert(3, ls[3])
    elif mutate == "swap":
        ls[2], ls[3] = ls[3], ls[2]
    elif mutate == "delete":
        del ls[4]
    elif mutate == "edit":
        i = next(k for k, ln in enumerate(ls) if b"step_committed" in ln)
        ls[i] = ls[i].replace(b"step_committed", b"step_commitxed")
    elif mutate == "truncate_tail":
        ls = ls[:-2]
    elif mutate == "drop_anchor":
        (d / "ledger.jsonl.head").unlink()
    if mutate != "drop_anchor":
        p.write_bytes(b"".join(ls))
    probs = verify_run_evidence(d, PLAN, "r")
    assert probs and probs[0].startswith("LEDGER_NOT_INTACT")


def test_manifest_deleted_edited_or_swapped_is_reported(full, tmp_path):
    d = _copy(full, tmp_path, "m1")
    m = next((d / "manifests").iterdir())
    os.chmod(m, 0o644)
    m.write_bytes(m.read_bytes().replace(b"synthetic", b"syntheti_", 1))
    assert any(p.startswith("MANIFEST_") for p in verify_run_evidence(d, PLAN, "r"))
    d2 = _copy(full, tmp_path, "m2")
    next((d2 / "manifests").iterdir()).unlink()
    assert "SEALED_MANIFEST_FILE_MISSING" in verify_run_evidence(d2, PLAN, "r")
    other = r(tmp_path / "othr", plan=Plan(seed=7, checkpoint_every=4))
    d3 = _copy(full, tmp_path, "m3")
    tgt = next((d3 / "manifests").iterdir())
    os.chmod(tgt, 0o644)
    tgt.write_bytes(other.manifest_path.read_bytes())
    assert any(p.startswith("MANIFEST_") for p in verify_run_evidence(d3, PLAN, "r"))


def test_checkpoint_tampering_surfaces_in_run_evidence(full, tmp_path):
    d = _copy(full, tmp_path, "c1")
    f = d / "checkpoints" / "ckpt-000012" / "meta.json"
    os.chmod(f, 0o644)
    f.write_bytes(f.read_bytes() + b" ")
    assert any(p.startswith("CHECKPOINT_UNVERIFIED_ckpt-000012") for p in verify_run_evidence(d, PLAN, "r"))


def test_final_evidence_differs_if_any_committed_step_differs(full, tmp_path):
    other = r(tmp_path / "o", plan=Plan(seed=8, checkpoint_every=4))
    assert other and final_evidence_bytes(tmp_path / "o", Plan(seed=8, checkpoint_every=4)) != final_evidence_bytes(full[0], PLAN)
    assert canonical_bytes({"x": 1})                                       # (canonical encoder sanity)
