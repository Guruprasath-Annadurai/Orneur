"""`python -m orca.train.dryrun`: run the SYNTHETIC dry-run and print one machine-readable JSON document.

It asserts, with before/after evidence, that the run changed no authorization state: the corpus / qualification / model-selection / GPU /
provider / spending / training locks are still false, and every docs/orneur/authorization/*.json (TRAINING_AUTHORIZATION.json included) is
byte-identical. Exit codes: 0 ok; 2 usage; 3 binding refused (dirty tree / no git SHA); 4 an authorization file or lock changed (never expected).

The CLI never calls authorize_training() (that would append to the gate's audit log under ORCA_HOME); instead it evaluates the gate's PURE
verify() against the committed record, to show the real record still denies. No key is read or created, no network/GPU/model is touched.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import orca.train.authorization as A
from orca.rse.imp1 import locks as L
from orca.train.dryrun.binding import BindingRefused, collect_binding, manifest_hash, synthetic_dataset_manifest
from orca.train.dryrun.budget import ResourceBudget
from orca.train.dryrun.canon import atomic_write_bytes, canonical_bytes, file_sha256, hash_obj
from orca.train.dryrun.envmanifest import build_env_manifest
from orca.train.dryrun.harness import run_synthetic
from orca.train.dryrun.ledger import RunLedger, verify_sealed_manifest
from orca.train.dryrun.lockcheck import check_lock_file, train_extra_requirements
from orca.train.dryrun.sentinel import SyntheticOnlyGuard, forbidden_modules_loaded
from orca.train.dryrun.toy import Plan

RESULT_SCHEMA = "orneur-dryrun-result/1"
REPO = Path(__file__).resolve().parents[3]
FIXED_TS = "1970-01-01T00:00:00Z"                 # deterministic placeholder: the synthetic result carries no wall-clock time


def lock_snapshot(repo: Path) -> dict:
    auth_dir = repo / "docs" / "orneur" / "authorization"
    files = {p.name: file_sha256(p) for p in sorted(auth_dir.glob("*.json"))}
    record = json.loads((repo / A.RECORD_PATH).read_text())
    proof = L.prove_authorization_locks(repo)
    return {
        "authorization_json_sha256": files,
        "training_authorization_status": record.get("status"),
        "training_authorization_sha256": files.get("TRAINING_AUTHORIZATION.json"),
        "functions": {"corpus_generation_authorized": L.corpus_generation_authorized(), "qualification_authorized": L.qualification_authorized(),
                      "model_selection_authorized": L.model_selection_authorized(), "gpu_authorized": L.gpu_authorized(),
                      "provider_authorized": L.provider_authorized(), "spending_authorized": L.spending_authorized(),
                      "training_authorized": L.training_authorized()},
        "prove_authorization_locks": str(getattr(proof, "decision", proof)),
    }


def locks_all_denied(snap: dict) -> bool:
    return (all(v is False for v in snap["functions"].values()) and snap["training_authorization_status"] == "NOT_AUTHORIZED"
            and snap["prove_authorization_locks"].endswith("CHECKS_PASSED"))


def gate_probe(repo: Path, binding_sha: str, plan: Plan) -> dict:
    """The gate's PURE verdict for a perfectly formed request against the real committed record/registry/revocations. No I/O side effects."""
    record = json.loads((repo / A.RECORD_PATH).read_text())
    registry = json.loads((repo / A.REGISTRY_PATH).read_text())
    revoked = json.loads((repo / A.REVOCATIONS_PATH).read_text())["revoked_authorization_ids"]
    req = A.Request(head_sha=binding_sha, reviewed_commit_is_ancestor=True, working_tree_clean=True,
                    current_code_tree_sha256=A.code_tree_sha256(repo), family=A.GENERIC_FAMILY, base_model="synthetic/toy-linear-v1",
                    base_model_revision=None, train_sha256=plan.sha256, eval_sha256=None, dataset_manifest_ids=(), dataset_bundle_id=None,
                    environment_class="SELF_HOSTED_GPU", purpose="EXPERIMENTAL_PILOT", epochs=1, lora_rank=1, max_seq_length=1,
                    requested_spend_usd=0.0)
    v = A.verify(record, req, registry, revoked)
    return {"authorized": bool(v.authorized), "reasons": list(v.reasons)}


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m orca.train.dryrun", description="SYNTHETIC training dry-run (no training, no GPU, no network).")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--max-tokens", type=int, default=1000)
    ap.add_argument("--max-wall-clock-s", type=float, default=60.0)
    ap.add_argument("--max-spend-usd", type=float, default=1.0, help="SIMULATED spend cap (no money is involved)")
    ap.add_argument("--sim-cost-usd-per-step", type=float, default=0.01)
    ap.add_argument("--out", type=str, default=None, help="also write the JSON here (atomic)")
    return ap


def run_cli(argv=None, *, repo: Path = REPO) -> int:
    args = _parser().parse_args(argv)
    before = lock_snapshot(repo)
    plan = Plan()
    ds_manifest = synthetic_dataset_manifest(plan)
    result: dict = {"schema": RESULT_SCHEMA, "synthetic": True, "note": "SYNTHETIC pure-Python toy run; nothing real was trained, loaded, downloaded or authorized."}
    code = 0
    try:
        binding = collect_binding(repo, config=plan.as_dict(), dataset_manifests=[ds_manifest])
    except BindingRefused as e:
        result.update({"status": "REFUSED_BINDING", "reasons": e.reasons})
        binding, code = None, 3
    if binding is not None:
        lock_path = repo / "requirements" / "train.txt"
        lock_rep = check_lock_file(lock_path, required_names=train_extra_requirements(repo / "pyproject.toml"))
        env = build_env_manifest(code_sha=binding.git_sha, dataset_bundle_sha256=manifest_hash(ds_manifest), seeds={"seed": plan.seed, "data_seed": plan.data_seed},
                                 lock_path=lock_path)
        budget = ResourceBudget(max_steps=args.max_steps, max_tokens=args.max_tokens, max_wall_clock_s=args.max_wall_clock_s,
                                max_spend_usd=args.max_spend_usd, sim_cost_usd_per_step=args.sim_cost_usd_per_step)
        sandbox = Path(tempfile.mkdtemp(prefix="orneur-dryrun-"))
        common = dict(binding=binding, env_manifest_sha256=env["manifest_sha256"], timestamp_fn=lambda: FIXED_TS)
        full = run_synthetic(plan, sandbox / "uninterrupted", guard=SyntheticOnlyGuard(sandbox), run_id="dryrun-uninterrupted", budget=budget, **common)
        first = resumed = None
        if full.status == "FINISHED":                       # only a run that really completed can be compared with an interrupted + resumed one
            cut = ResourceBudget(max_steps=5, max_tokens=args.max_tokens, max_wall_clock_s=args.max_wall_clock_s, max_spend_usd=args.max_spend_usd,
                                 sim_cost_usd_per_step=args.sim_cost_usd_per_step)
            first = run_synthetic(plan, sandbox / "interrupted", guard=SyntheticOnlyGuard(sandbox), run_id="dryrun-interrupted", budget=cut, **common)
            resumed = run_synthetic(plan, sandbox / "interrupted", guard=SyntheticOnlyGuard(sandbox), run_id="dryrun-interrupted", budget=budget,
                                    resume=True, **common)
        zero = run_synthetic(plan, sandbox / "zero", guard=SyntheticOnlyGuard(sandbox), run_id="dryrun-zero-budget", budget=ResourceBudget(), **common)
        verified = {}
        for name, dirname in (("uninterrupted", "uninterrupted"), ("interrupted", "interrupted"), ("zero_budget", "zero")):
            if name == "interrupted" and first is None:
                continue
            led = RunLedger(sandbox / dirname / "ledger.jsonl")
            res = led.verify()
            manifests = sorted((sandbox / dirname / "manifests").glob("*.manifest.json"))
            verified[name] = {"ledger_ok": res.ok and res.count > 0, "records": res.count, "head": res.last_hash, "manifests": len(manifests),
                              "manifests_ok": bool(manifests) and all(not verify_sealed_manifest(p, led) for p in manifests)}
        runs = {"uninterrupted": full.summary(), "zero_budget": zero.summary()}
        equivalent = None
        if first is not None:
            runs.update({"interrupted_first_segment": first.summary(), "interrupted_resumed": resumed.summary()})
            equivalent = bool(resumed.state is not None and resumed.state.sha256 == full.state.sha256
                              and resumed.final_checkpoint_digest == full.final_checkpoint_digest)
        result.update({
            "status": "OK" if full.status == "FINISHED" else "OK_BUDGET_LIMITED", "git_sha": binding.git_sha, "plan_sha256": plan.sha256, "env_manifest": env,
            "lock": {"path": "requirements/train.txt", "structure_ok": lock_rep.ok, "problems": lock_rep.problems, "packages": lock_rep.packages, "hashes": lock_rep.hashes,
                     "sha256": lock_rep.sha256},
            "runs": runs, "resume_equivalent": equivalent, "verification": verified,
            "sentinel": {"forbidden_modules_loaded": forbidden_modules_loaded(), "guard_runs": 2 + (2 if first is not None else 0)},
            "gate_probe": gate_probe(repo, binding.git_sha, plan),
        })
        if not ((equivalent is True or first is None) and all(v["ledger_ok"] and v["manifests_ok"] for v in verified.values()) and lock_rep.ok
                and not result["gate_probe"]["authorized"] and not result["sentinel"]["forbidden_modules_loaded"]
                and zero.status == "REFUSED" and (first is None or first.reason == "STEP_CAP")):
            result["status"] = "SELF_CHECK_FAILED"
            code = code or 5
    after = lock_snapshot(repo)
    unchanged = before == after
    result["authorization"] = {"locks_before": before, "locks_after": after, "authorization_files_byte_identical": unchanged,
                               "locks_still_false": locks_all_denied(before) and locks_all_denied(after)}
    if not (unchanged and result["authorization"]["locks_still_false"]):
        result["status"] = "AUTHORIZATION_STATE_CHANGED"
        code = 4
    result["result_sha256"] = hash_obj({k: v for k, v in result.items() if k != "result_sha256"})
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(text)
    if args.out:
        atomic_write_bytes(Path(args.out), text.encode())
    return code


__all__ = ["run_cli", "lock_snapshot", "locks_all_denied", "gate_probe", "canonical_bytes"]
