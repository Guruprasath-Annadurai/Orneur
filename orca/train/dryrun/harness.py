"""Synthetic training-execution harness: the real control flow of a training run (authorization -> binding -> budget -> step -> atomic
checkpoint -> ledger -> resume -> seal), driven by a pure-Python toy model. It cannot train anything real: there is no tensor library, model,
tokenizer, GPU, network or protected-data access in this process, and the sentinel guard (sentinel.py) makes that a checked fact.

Two entry points:
  run_synthetic(...)        needs a live SyntheticOnlyGuard; grants nothing and claims nothing about authorization.
  rehearse_with_grant(...)  needs a genuine orca.train.authorization.TrainingGrant (require_grant + assert_files + single-use), applies the
                            grant's wall clock, then runs the same synthetic run. authorize_and_rehearse() calls the REAL gate first.
Neither entry point has a "skip authorization" switch, and neither can create or alter a TrainingGrant.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from orca.train.authorization import TrainingGrant, TrainingNotAuthorized, authorize_training, require_grant
from orca.train.config import resolve_training_data_inputs
from orca.train.dryrun.binding import Binding, verify_binding
from orca.train.dryrun.budget import BudgetMeter, HardStop, KillSwitch, ResourceBudget
from orca.train.dryrun.ckpt import latest_verified, load_state, quarantine_checkpoint, quarantine_uncommitted, save_checkpoint
from orca.train.dryrun.ledger import RunLedger, build_run_manifest, complete_pending_seal, seal_run_manifest
from orca.train.dryrun.sentinel import SyntheticOnlyGuard
from orca.train.dryrun.toy import NonFiniteValue, Plan, ToyEngine, TrainState, initial_state

ALL_STATE = frozenset({"optimizer", "scheduler", "rng", "cursor"})
_CONSUMED_IN_PROCESS: set = set()


class RunRefused(RuntimeError):
    def __init__(self, reasons):
        self.reasons = sorted(set(reasons))
        super().__init__("synthetic run refused: " + ", ".join(self.reasons))


@dataclass
class Fault:
    """Test-only fault injection. Production callers never pass one."""
    raise_at: tuple | None = None                 # (step_index, micro_index) -> RuntimeError inside the in-flight step
    nan_at_step: int | None = None                # step_index whose loss becomes NaN
    crash_ckpt_at: dict = field(default_factory=dict)   # step -> "files" | "renamed": simulate dying mid-checkpoint (no finalization runs)
    on_micro: Callable | None = None              # (step_index, micro_index) hook, e.g. engage the kill switch or advance a fake clock


@dataclass
class RunOutcome:
    status: str                    # FINISHED | STOPPED | ABORTED | REFUSED
    reason: str | None
    state: TrainState | None
    steps: int
    checkpoints: list
    usage: dict
    ledger_head: tuple
    manifest_path: Path | None
    final_checkpoint_digest: str | None

    def summary(self) -> dict:
        return {"status": self.status, "reason": self.reason, "steps": self.steps, "state_sha256": self.state.sha256 if self.state else None,
                "checkpoints": list(self.checkpoints),
                "usage": {k: v for k, v in self.usage.items() if k != "elapsed_s"},      # wall time is not deterministic; the caps it enforces are "ledger_head_seq": self.ledger_head[0],
                "ledger_head_hash": self.ledger_head[1], "final_checkpoint_digest": self.final_checkpoint_digest}


def _apply_restore(state: TrainState, plan: Plan, restore) -> TrainState:
    """`restore` names which parts of the checkpointed state are honoured. Production always passes ALL_STATE; the negative-control tests
    drop one part to prove each part matters (resuming without it changes the result)."""
    fresh = initial_state(plan)
    if "optimizer" not in restore:
        state.opt = fresh.opt
    if "scheduler" not in restore:
        state.sched_step = 0
    if "rng" not in restore:
        state.rng_state = fresh.rng_state
    if "cursor" not in restore:
        state.examples_seen = 0
    return state


# Ceilings that are bound into the chained run_started record. `max_steps` is deliberately not one of them: it is the per-invocation pause
# control (the run is bounded by Plan.total_steps, which is plan-hash-bound) and resuming with a larger step allowance is how a paused run continues.
_BOUND_UPPER = ("max_tokens", "max_wall_clock_s", "max_spend_usd")


def _raised_ceilings(bound, budget: ResourceBudget) -> list:
    """Names of ceilings the resuming caller loosened relative to the budget bound at run start. A missing/garbled bound fails closed."""
    if not isinstance(bound, dict):
        return ["budget_unreadable"]
    now = budget.as_dict()
    out = []
    for n in _BOUND_UPPER:
        if not isinstance(bound.get(n), (int, float)) or now[n] > bound[n]:
            out.append(n)
    if not isinstance(bound.get("sim_cost_usd_per_step"), (int, float)) or now["sim_cost_usd_per_step"] < bound["sim_cost_usd_per_step"]:
        out.append("sim_cost_usd_per_step")                                # a cheaper per-step cost would stretch the same spend ceiling
    return out


def _settle_pending_seal(ledger: RunLedger, manifests_dir: Path, run_id: str) -> None:
    """After a crash, a stop/finish may have a manifest file on disk that was never chained. Complete the seal when it is intact and binds the
    current head; otherwise move the unusable file aside (nothing is deleted) so the next seal can use the name."""
    if ledger.last_type() not in ("run_finished", "run_stopped"):
        return
    path = manifests_dir / f"{run_id}.seg{ledger.sealed_count() + 1}.manifest.json"
    if not path.exists():
        return
    if not complete_pending_seal(ledger, path):
        q = manifests_dir / "quarantine"
        q.mkdir(exist_ok=True)
        n = 0
        while (q / f"{path.name}.{n}").exists():
            n += 1
        os.rename(path, q / f"{path.name}.{n}")


def _default_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_core(plan: Plan, root, *, run_id: str, budget: ResourceBudget, binding: Binding, env_manifest_sha256: str, resume: bool = False,
             clock: Callable[[], float] = time.monotonic, kill_switch: KillSwitch | None = None, restore=ALL_STATE, fault: Fault | None = None,
             grant_info: dict | None = None, wall_cap_override_s: float | None = None, timestamp_fn: Callable[[], str] = _default_ts,
             anchor_key: bytes | None = None) -> RunOutcome:
    """The run loop. No guard check here (see run_synthetic); everything it touches lives under `root`."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    ckdir = root / "checkpoints"
    ledger = RunLedger(root / "ledger.jsonl", anchor_key=anchor_key)
    engine = ToyEngine(plan)
    fault = fault or Fault()
    t_start = timestamp_fn()
    meter = BudgetMeter(budget, clock=clock, kill_switch=kill_switch, wall_clock_cap_override_s=wall_cap_override_s)
    manifests_dir = root / "manifests"

    def seal(failure_state):
        names = [r["body"]["name"] for r in ledger.records() if r["body"]["type"] == "checkpoint_saved"]
        seg = sum(1 for r in ledger.records() if r["body"]["type"] == "manifest_sealed") + 1
        m = build_run_manifest(run_id=run_id, plan=plan, binding=binding.as_dict(), ledger=ledger, checkpoint_names=names,
                               failure_state=failure_state, final_state_sha256=state.sha256 if state is not None else None,
                               env_manifest_sha256=env_manifest_sha256, start_time=t_start, end_time=timestamp_fn())
        return seal_run_manifest(ledger, m, manifests_dir, filename=f"{run_id}.seg{seg}.manifest.json")      # one immutable file per segment

    state: TrainState | None = None
    if not resume:
        if ledger.chain.path.exists() and ledger.chain.path.stat().st_size:
            raise RunRefused(["LEDGER_ALREADY_EXISTS_USE_RESUME"])
        if budget.is_zero or meter.wall_cap_s <= 0:
            ledger.append("run_refused", reasons=["ZERO_BUDGET"])
            return RunOutcome("REFUSED", "ZERO_BUDGET", None, 0, [], meter.usage(), ledger.chain.head(), seal("REFUSED:ZERO_BUDGET"), None)
        state = initial_state(plan)
        ledger.append("run_started", plan_sha256=plan.sha256, binding=binding.as_dict(), synthetic=True, grant=grant_info,
                      env_manifest_sha256=env_manifest_sha256, budget=budget.as_dict())
    else:
        started = ledger.run_started_body()
        if started is None:
            raise RunRefused(["LEDGER_MISSING_OR_NOT_INTACT"])
        if started["plan_sha256"] != plan.sha256:
            raise RunRefused(["PLAN_HASH_MISMATCH"])
        if budget.is_zero or meter.wall_cap_s <= 0:                       # nothing at all (not even "finish an already-done run") on a zero budget
            raise RunRefused(["ZERO_BUDGET"])
        raised = _raised_ceilings(started.get("budget"), budget)
        if raised:
            raise RunRefused(["BUDGET_RAISED_AFTER_BIND:" + n for n in raised])
        verify_binding(started["binding"], binding)                       # BindingRefused: code / dataset / config changed since the run began
        _settle_pending_seal(ledger, manifests_dir, run_id)              # crash between "manifest written" and "manifest hash chained"
        if ledger.is_sealed_finished() or ledger.last_type() == "run_finished":     # already done: resuming is an idempotent no-op (+ seal if unsealed)
            vc, _ = latest_verified(ckdir, plan, expected_digests=ledger.checkpoint_digests(), require_listed=True, expected_run_id=run_id)
            if vc is None:
                raise RunRefused(["NO_VERIFIED_CHECKPOINT"])
            state = load_state(vc, plan)
            if state.sha256 != ledger.final_committed_state_sha256():
                raise RunRefused(["FINAL_STATE_MISMATCH"])
            mpath = None if ledger.is_sealed_finished() else seal(None)
            n = ledger.sealed_count()
            mpath = mpath or manifests_dir / f"{run_id}.seg{n}.manifest.json"
            meter.steps, meter.tokens, meter.spend_micro = state.step, state.tokens_seen, state.step * meter._step_cost_micro
            return RunOutcome("FINISHED", None, state, state.step, [r["body"]["name"] for r in ledger.records() if r["body"]["type"] == "checkpoint_saved"],
                              meter.usage(), ledger.chain.head(), mpath, vc.digest)
        orphans = quarantine_uncommitted(ckdir)                          # crash between rename and commit: never loadable, move aside
        vc, rejected = latest_verified(ckdir, plan, expected_digests=ledger.checkpoint_digests(), require_listed=True, expected_run_id=run_id)
        if vc is None and ledger.checkpoint_digests():
            raise RunRefused(["NO_VERIFIED_CHECKPOINT"] + sorted("REJECTED_" + n for n in rejected))
        for name in rejected:                                            # corrupt / unlisted checkpoints newer than the one we resume from
            quarantine_checkpoint(ckdir, name)
        if vc is None:                                                   # crashed before ANY checkpoint was committed: the initial state is deterministic
            state, from_digest = initial_state(plan), "initial-state:" + initial_state(plan).sha256
        else:
            state, from_digest = _apply_restore(load_state(vc, plan), plan, restore), vc.digest
        # Caps are cumulative across resumes: consumption is re-derived from the verified state, never reset by resuming.
        meter.steps, meter.tokens = state.step, state.tokens_seen
        meter.spend_micro = state.step * meter._step_cost_micro
        ledger.append("run_resumed", from_step=state.step, from_digest=from_digest, binding=binding.as_dict(), restore=sorted(restore),
                      rejected_checkpoints=sorted(set(rejected) | set(orphans)))

    stop_reason, status, pending_exc = None, "FINISHED", None
    start_step = state.step

    def save_ckpt(st: TrainState) -> str:
        h = save_checkpoint(ckdir, st, plan, run_id, crash_at=fault.crash_ckpt_at.get(st.step))
        ledger.append("checkpoint_saved", step=st.step, name=h.name, digest=h.digest)
        return h.digest

    def before_micro(step_index: int, micro: int) -> None:
        if fault.on_micro is not None:
            fault.on_micro(step_index, micro)
        meter.check_micro()
        if fault.raise_at == (step_index, micro):
            raise RuntimeError("injected fault")

    while state.step < plan.total_steps:
        try:
            meter.check_before_step(plan.tokens_per_step)                  # the cap is enforced BEFORE the step that would exceed it
        except HardStop as hs:
            stop_reason, status = hs.reason, "STOPPED"
            break
        try:
            new = engine.compute_step(state, before_micro, poison_nan=(fault.nan_at_step == state.step))
        except HardStop as hs:                                             # kill switch / wall clock tripped mid-step -> discard the in-flight step
            ledger.append("step_aborted", step=state.step + 1, reason=hs.reason)
            stop_reason, status = hs.reason, "STOPPED"
            break
        except NonFiniteValue:
            ledger.append("step_aborted", step=state.step + 1, reason="NON_FINITE_LOSS")
            stop_reason, status = "NON_FINITE_LOSS", "ABORTED"
            break
        except Exception as e:                                             # noqa: BLE001 -- recorded, rolled back, reported
            ledger.append("step_aborted", step=state.step + 1, reason="EXCEPTION:" + type(e).__name__)
            stop_reason, status = "EXCEPTION:" + type(e).__name__, "ABORTED"
            break
        except BaseException as e:                                         # KeyboardInterrupt / guard violation: roll back, record, re-raise
            ledger.append("step_aborted", step=state.step + 1, reason="INTERRUPTED:" + type(e).__name__)
            stop_reason, status, pending_exc = "INTERRUPTED:" + type(e).__name__, "ABORTED", e
            break
        state = new                                                        # COMMIT: the only place committed state changes
        meter.commit_step(plan.tokens_per_step)
        ledger.append("step_committed", step=state.step, state_sha256=state.sha256, tokens_seen=state.tokens_seen, spend_micro_usd=meter.spend_micro)
        if state.step % plan.checkpoint_every == 0 or state.step == plan.total_steps:
            save_ckpt(state)

    have = ledger.checkpoint_digests()
    if stop_reason is None:
        ledger.append("run_finished", step=state.step, state_sha256=state.sha256)
        outcome_status, outcome_reason = "FINISHED", None
        failure = None
    else:
        if state.step > start_step and state.step not in have:
            save_ckpt(state)                                               # persist the rolled-back (last committed) state so resume has a target
        ledger.append("run_stopped", reason=stop_reason, step=state.step, state_sha256=state.sha256)
        outcome_status, outcome_reason = status, stop_reason
        failure = f"{status}:{stop_reason}"
    manifest_path = seal(failure)
    have = ledger.checkpoint_digests()
    out = RunOutcome(outcome_status, outcome_reason, state, state.step, [r["body"]["name"] for r in ledger.records() if r["body"]["type"] == "checkpoint_saved"],
                     meter.usage(), ledger.chain.head(), manifest_path, have.get(state.step))
    if pending_exc is not None:
        raise pending_exc
    return out


def run_synthetic(plan: Plan, root, *, guard: SyntheticOnlyGuard, **kw) -> RunOutcome:
    """Run under the sentinel. Fails closed (SyntheticGuaranteeUnavailable) if the guarantee cannot be established, and re-checks for swallowed
    violations afterwards."""
    with guard as attestation:
        attestation.assert_active()
        outcome = run_core(plan, root, **kw)
        attestation.assert_no_violations()
    return outcome


# ─── grant-gated rehearsal ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _consume_grant(grant: TrainingGrant, consumed_dir) -> None:
    """A grant authorizes ONE run. Replaying the same grant object is refused (in-process set + exclusive marker file)."""
    key = (grant.authorization_id, grant.run_slot, grant.record_sha256)
    if key in _CONSUMED_IN_PROCESS:
        raise TrainingNotAuthorized(["GRANT_ALREADY_CONSUMED"])
    d = Path(consumed_dir)
    d.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(d / f"{grant.authorization_id}-{grant.record_sha256[:16]}-slot{grant.run_slot}"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise TrainingNotAuthorized(["GRANT_ALREADY_CONSUMED"]) from None
    os.close(fd)
    _CONSUMED_IN_PROCESS.add(key)


def _recheck_authority(grant: TrainingGrant) -> None:
    """A grant is a snapshot; authority can be revoked or the record withdrawn after it was issued. Re-read both at the moment of use, from the
    same repository-resident files the gate reads. Unreadable means refused, never 'nothing revoked'. Read-only; cannot create or alter a grant."""
    from orca.train import authorization as gate
    root = gate._default_root()
    rev = gate._load_json(root / gate.REVOCATIONS_PATH)
    if not (isinstance(rev, dict) and rev.get("schema_version") == gate.REVOCATIONS_SCHEMA_VERSION and isinstance(rev.get("revoked_authorization_ids"), list)):
        raise TrainingNotAuthorized(["REVOCATION_LIST_UNREADABLE"])
    if grant.authorization_id in rev["revoked_authorization_ids"]:
        raise TrainingNotAuthorized(["AUTHORIZATION_REVOKED"])
    rec = gate._load_json(root / gate.RECORD_PATH)
    if not (isinstance(rec, dict) and rec.get("status") == "AUTHORIZED" and rec.get("authorization_id") == grant.authorization_id):
        raise TrainingNotAuthorized(["AUTHORIZATION_RECORD_WITHDRAWN"])


def rehearse_with_grant(cfg, grant, *, environment_class: str, plan: Plan, root, consumed_dir, guard: SyntheticOnlyGuard, run_id: str,
                        budget: ResourceBudget, binding: Binding, env_manifest_sha256: str, **kw) -> RunOutcome:
    """Refuses (TrainingNotAuthorized) without a genuine, unexpired, config-matching, file-matching, unconsumed grant. The grant's wall clock can
    only tighten the budget's. Still synthetic: no trainer exists on this path."""
    g = require_grant(grant, cfg, environment_class=environment_class)       # NO_TRAINING_GRANT / GRANT_FORGED_OR_TAMPERED / CONFIG_CHANGED / EXPIRED
    resolved = resolve_training_data_inputs(cfg)
    g.assert_files(resolved.train_path, resolved.eval_path)                  # TRAIN_DATA_CHANGED_AFTER_AUTHORIZATION etc.
    _recheck_authority(g)                                                    # revoked / withdrawn since issuance -> refused at USE, before consuming
    _consume_grant(g, consumed_dir)
    info = {"authorization_id": g.authorization_id, "run_slot": g.run_slot, "key_id": g.key_id, "record_sha256": g.record_sha256}
    return run_synthetic(plan, root, guard=guard, run_id=run_id, budget=budget, binding=binding, env_manifest_sha256=env_manifest_sha256,
                         grant_info=info, wall_cap_override_s=g.max_wall_clock_minutes * 60.0, **kw)


def authorize_and_rehearse(cfg, *, environment_class: str, plan: Plan, root, consumed_dir, guard: SyntheticOnlyGuard, run_id: str,
                           budget: ResourceBudget, binding: Binding, env_manifest_sha256: str, dataset_manifest_ids=None,
                           dataset_bundle_id=None, now=None, **kw) -> RunOutcome:
    """Calls the REAL gate first (denials -> TrainingNotAuthorized with the gate's own reason codes, and no run directory is created)."""
    grant = authorize_training(cfg, environment_class=environment_class, dataset_manifest_ids=dataset_manifest_ids,
                               dataset_bundle_id=dataset_bundle_id, requested_spend_usd=float(budget.max_spend_usd), now=now)
    return rehearse_with_grant(cfg, grant, environment_class=environment_class, plan=plan, root=root, consumed_dir=consumed_dir, guard=guard,
                               run_id=run_id, budget=budget, binding=binding, env_manifest_sha256=env_manifest_sha256, **kw)


__all__ = ["ALL_STATE", "Fault", "RunOutcome", "RunRefused", "run_core", "run_synthetic", "rehearse_with_grant", "authorize_and_rehearse"]
