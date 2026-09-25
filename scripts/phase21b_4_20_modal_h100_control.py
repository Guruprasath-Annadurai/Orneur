"""
Phase 21B.4.20 -- control runtime qualification on MODAL, H100 80GB (canonical provider; simplified harness).

Supersedes the A100 harness `phase21b_4_20_control_runtime_qualification.py` (kept unchanged as history). The design is
deliberately small:

  * one Modal Volume caches the EXACT pinned model revision (CPU-only `precache`, hash-verified against the Hugging Face LFS
    sha256 and the recorded byte sums) BEFORE any GPU time is spent;
  * the GPU step is ONE blocking `serve_and_smoke.remote()` call whose Modal function `timeout` is the hard active-H100 cap
    (900 s, inside the 20-minute maximum). No polling loop, no cancel logic: Modal itself enforces the cap;
  * the serving/smoke function is the SAME code used by every provider (`phase21b_4_20_lightning_runner.serve_and_smoke`,
    mounted into the image), so the smoke protocol cannot drift;
  * the financial gate (existing, strict) runs before every launch; billing is read before/after and object-specific
    evidence (the app's own created/stopped timestamps and billing rows) is captured.

Modes:  preflight | precache | run     (each with --control qwen3_8b|mistral_nemo|phi4)

Generated text is data only: never executed/imported/compiled/shelled out. the Modal sandbox product is never used.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import modal

VLLM_IMAGE_TAG = "vllm/vllm-openai:v0.29.0"
VLLM_IMAGE_DIGEST = "sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b"
VLLM_IMAGE_REF = f"vllm/vllm-openai@{VLLM_IMAGE_DIGEST}"
GPU_TYPE = "H100"                      # Modal: 1 x NVIDIA H100 80GB
HARD_TIMEOUT_SECONDS = 900             # active-H100 hard cap per control (maximum allowed by the owner: 1200)
CPU_CORES = 4
GPU_MEMORY_MIB = 24576
PRECACHE_MEMORY_MIB = 16384
PRECACHE_TIMEOUT_SECONDS = 1800
CACHE_VOLUME = "orneur-p21b420-model-cache"
MOUNT = "/models"
CREDIT_POOL_USD = "30.00"              # owner-derived pool (see the Modal billing gate history)
RESERVE_USD = "5.00"
SETTLE_READINGS = 3
SETTLE_INTERVAL_SECONDS = 90
PHASE = "21B.4.20"
DATE_TAG = "2026-09-24"
REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
RUNNER = REPO_ROOT / "scripts/phase21b_4_20_lightning_runner.py"     # provider-neutral serving function (stdlib only)
LIGHTNING_CONTROL = REPO_ROOT / "scripts/phase21b_4_20_lightning_control.py"
PROTOCOL_FILE = REPO_ROOT / "orca/eval/locked_smoke_protocol.py"      # the ONE canonical locked-smoke protocol, shipped beside the runner
CONFIG_FILE = REPO_ROOT / "orca/eval/control_runtime_configuration.py"   # the ONE canonical per-control runtime configuration, shipped beside the runner
CONTROL_KEYS = ("qwen3_8b", "mistral_nemo", "phi4")

image = (
    modal.Image.from_registry(
        VLLM_IMAGE_REF, add_python=None,
        setup_dockerfile_commands=["RUN which python || ln -s $(which python3) /usr/local/bin/python"],
    )
    .entrypoint([])
    .add_local_file(str(RUNNER), "/root/runner.py")
    .add_local_file(str(PROTOCOL_FILE), "/root/locked_smoke_protocol.py")
    .add_local_file(str(CONFIG_FILE), "/root/control_runtime_configuration.py")
)
volume = modal.Volume.from_name(CACHE_VOLUME, create_if_missing=True)
app = modal.App("orneur-p21b420-h100-control-runtime")


def _container_env() -> None:
    import os

    os.environ["P4420_WORK"] = f"{MOUNT}/p4420"
    os.environ["HF_HOME"] = f"{MOUNT}/hf"
    os.environ.update({"VLLM_NO_USAGE_STATS": "1", "DO_NOT_TRACK": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
    Path(f"{MOUNT}/p4420").mkdir(parents=True, exist_ok=True)
    if "/root" not in sys.path:
        sys.path.insert(0, "/root")


def _container_proof(runner, cfg: dict, result: dict) -> dict:
    """Proof, computed INSIDE the GPU container from what was actually used/sent, of the runtime configuration and the locked protocol."""
    argv = result.get("server_argv_sanitized") or []

    def flag(name):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None

    smokes = result.get("smoke_results") or []
    models = ((result.get("models_endpoint") or {}).get("data") or [{}])
    return {"runtime_configuration_id": (cfg.get("runtime_configuration") or {}).get("id"),
            "runtime_configuration_id_applied": result.get("runtime_configuration_id_applied"),
            "runtime_configuration_sha256": runner.RUNTIME_CONFIGS.configuration_sha256(cfg["model_id"]),
            "runtime_policy_sha256": runner.RUNTIME_CONFIGS.runtime_policy_sha256(),
            "chat_template_kwargs_sent": {x["smoke_id"]: x.get("chat_template_kwargs_sent") for x in smokes},
            "smoke_protocol_sha256": runner.LOCKED_PROTOCOL.protocol_sha256(),
            "prompt_sha256_sent": {x["smoke_id"]: x.get("prompt_sha256_sent") for x in smokes},
            "model_id": cfg["model_id"], "served_model_id": models[0].get("id"), "revision": result.get("snapshot_dir_name"),
            "precision": flag("--dtype"), "quantization": flag("--quantization"), "reasoning_parser": flag("--reasoning-parser"),
            "tokenizer_mode": flag("--tokenizer-mode"), "config_format": flag("--config-format"), "load_format": flag("--load-format")}


# ══════════════════════════════════════════════════════════════════════════
# CPU: exact-revision pre-cache + verification (no GPU)
# ══════════════════════════════════════════════════════════════════════════
@app.function(image=image, cpu=CPU_CORES, memory=PRECACHE_MEMORY_MIB, timeout=PRECACHE_TIMEOUT_SECONDS, volumes={MOUNT: volume})
def precache(control: str) -> dict:
    _container_env()
    import runner  # type: ignore  # /root/runner.py (mounted)

    rc = runner.cmd_stage_model(control)
    volume.commit()
    manifest = json.loads(Path(f"{MOUNT}/p4420/stage_{control}.json").read_text())
    return {"rc": rc, "manifest": manifest}


# ══════════════════════════════════════════════════════════════════════════
# GPU: ONE call. The function timeout is the hard cap on active H100 time.
# Trusted inference only; generated text is data.
# ══════════════════════════════════════════════════════════════════════════
@app.function(image=image, gpu=GPU_TYPE, cpu=CPU_CORES, memory=GPU_MEMORY_MIB, timeout=HARD_TIMEOUT_SECONDS, volumes={MOUNT: volume})
def serve_and_smoke(control: str) -> dict:
    import os

    _container_env()
    volume.reload()
    os.environ["HF_HUB_OFFLINE"] = "1"      # weights come only from the verified cache; no network fetch on GPU time
    import runner  # type: ignore

    cfg = runner.serving_config(control, 420)          # the ONE assembly path (includes the control's runtime configuration, if any)
    result = runner.serve_and_smoke(cfg)
    result["runtime_configuration_proof"] = _container_proof(runner, cfg, result)
    try:
        result["stage_manifest"] = json.loads(Path(f"{MOUNT}/p4420/stage_{control}.json").read_text())
    except Exception as e:  # noqa: BLE001
        result["stage_manifest"] = None
        result["stage_manifest_error"] = f"{type(e).__name__}"
    return result


# ══════════════════════════════════════════════════════════════════════════
# Local orchestrator (never treats generated text as anything but data)
# ══════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _modal_cli() -> str:
    return str(Path(sys.executable).parent / "modal")


def _cli_json(*args: str):
    out = subprocess.run([_modal_cli(), *args], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"modal {' '.join(args)} failed: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def billing_summary() -> dict:
    return _cli_json("billing", "summary", "--json")


def write_json(path: Path, data: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_lightning_control():
    spec = importlib.util.spec_from_file_location("p21b420_lightning_control_for_modal", LIGHTNING_CONTROL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if modal.is_local():  # the container only needs the remote functions; orca is not shipped to it
    from orca.eval import control_runtime_configuration as runtime_config  # noqa: E402
    from orca.eval import locked_smoke_protocol as locked_protocol  # noqa: E402
    from orca.eval.control_runtime_qualification import (  # noqa: E402
        FAILURE_DOMAIN_BY_OUTCOME, LOCKED_CONTROL_IDENTITIES, assess_settlement, build_financial_reconciliation,
        compute_smoke_acceptance, derive_runtime_status, smoke_locked_acceptance, financial_gate_decision, to_decimal, validate_control_runtime_record,
    )


def rates() -> dict:
    r = _cli_json("billing", "rates", "--json")
    return {"h100": Decimal(str(r["gpu_hour_cost_h100"])), "cpu": Decimal(str(r["cpu_hour_cost"])), "mem": Decimal(str(r["mem_gib_hour_cost"]))}


def worst_case_cost(r: dict, *, gpu: bool, cores: int, memory_mib: int, seconds: int) -> Decimal:
    hourly = (r["h100"] if gpu else Decimal(0)) + r["cpu"] * Decimal(cores) + r["mem"] * Decimal(memory_mib) / Decimal(1024)
    return hourly * Decimal(seconds) / Decimal(3600)


def cleanup_snapshot() -> dict:
    apps, containers, volumes = _cli_json("app", "list", "--json"), _cli_json("container", "list", "--json"), _cli_json("volume", "list", "--json")
    running = sum(int(a.get("tasks", 0) or 0) for a in apps)
    non_idle = [a for a in apps if a.get("state") not in ("stopped", "deployed") or int(a.get("tasks", 0) or 0) > 0]
    unexpected_volumes = [v for v in volumes if v.get("name", v.get("Name")) != CACHE_VOLUME]
    return {"captured_at_utc": _now(), "apps": apps, "containers": containers, "volumes": volumes, "running_tasks_total": running,
            "non_idle_apps": non_idle, "expected_cache_volume": CACHE_VOLUME,
            "live_resources": len(containers) + len(unexpected_volumes) + running + len(non_idle)}


def _attempts_path(tag: str) -> Path:
    return EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPTS_{DATE_TAG}.json"


def _load_attempts(tag: str) -> list[dict]:
    p = _attempts_path(tag)
    return json.loads(p.read_text())["attempts"] if p.is_file() else []


def _modal_attempts():
    for tag in ("QWEN3_8B", "MISTRAL_NEMO", "PHI4"):
        for a in _load_attempts(tag):
            if a.get("provider") in (None, "Modal"):
                yield tag, a


def any_positive_billing_seen() -> bool:
    return any(to_decimal(a["owner_billed_delta_usd"], "delta") != 0 for _t, a in _modal_attempts())


WAIVER_TAG, WAIVER_ATTEMPT = "QWEN3_8B", 1        # the ONLY (control, attempt) an owner waiver can ever apply to
WAIVER_TOP_KEYS = {"artifact_type", "phase", "authorized_by", "decision", "created_at_utc", "scope", "authorization_text", "asserts",
                   "does_not_waive", "does_not_authorize", "authorized_execution", "note"}
WAIVER_SCOPE_KEYS = {"provider", "control", "historical_attempt", "waiver", "historical_only"}
WAIVER_ASSERT_KEYS = {"attempt_1_cost_was_zero", "settlement_resolved", "attempt_1_valid_model_qualification_attempt", "attempt_1_status",
                      "attempt_1_billing_settlement_status", "attempt_1_conservative_exposure_reserved_usd"}
WAIVER_EXEC_KEYS = {"controls_in_order", "provider", "gpu", "precision", "quantization", "model_substitution", "sequential_only"}
WAIVER_REQUIRED_NOT_WAIVED = ("zero_owner_cash_invariant", "promotional_credit_sufficiency", "model_identity_and_revision_verification",
                              "cleanup_requirements", "evidence_integrity", "security_controls")
WAIVER_REQUIRED_NOT_AUTHORIZED = ("frontier_inference", "benchmarks", "genesis_training", "phase_21c")
WAIVER_CONTROLS_IN_ORDER = ["Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4"]


def waiver_path(tag: str, attempt_number: int) -> Path:
    return EVIDENCE_DIR / f"GENESIS_OWNER_SETTLEMENT_WAIVER_{tag}_ATTEMPT{attempt_number}_{DATE_TAG}.json"


def validate_owner_settlement_waiver(tag: str, a: dict) -> tuple[str, list[str]]:
    """Strict semantic validation of the owner waiver for exactly Modal / Qwen3-8B / historical attempt 1.
    Returns (status, reasons): WAIVER_ABSENT (no file), WAIVER_INVALID (any defect), WAIVER_ACCEPTED. Fail-closed: file existence
    alone is never authorization. Accepting a waiver only lifts the settlement-unresolved gate; it never authorizes a GPU launch,
    never marks the settlement resolved and never reduces the conservative exposure deduction."""
    if tag != WAIVER_TAG or a.get("attempt_number") != WAIVER_ATTEMPT:
        return "WAIVER_ABSENT", ["a waiver can only apply to Modal Qwen3-8B historical attempt 1"]
    path = waiver_path(tag, WAIVER_ATTEMPT)
    if not path.is_file():
        return "WAIVER_ABSENT", ["no owner waiver artifact at the canonical path"]
    bad: list[str] = []
    try:
        w = json.loads(path.read_text())
    except (ValueError, OSError) as e:
        return "WAIVER_INVALID", [f"unreadable/malformed JSON: {type(e).__name__}"]
    if not isinstance(w, dict):
        return "WAIVER_INVALID", ["waiver root is not a JSON object"]

    def obj(key, allowed):
        v = w.get(key)
        if not isinstance(v, dict):
            bad.append(f"{key} missing or not an object")
            return {}
        if set(v) - allowed:
            bad.append(f"{key} has unknown keys {sorted(set(v) - allowed)}")
        if allowed - set(v):
            bad.append(f"{key} missing keys {sorted(allowed - set(v))}")
        return v

    if set(w) - WAIVER_TOP_KEYS:
        bad.append(f"unknown top-level keys {sorted(set(w) - WAIVER_TOP_KEYS)}")
    if WAIVER_TOP_KEYS - set(w):
        bad.append(f"missing top-level keys {sorted(WAIVER_TOP_KEYS - set(w))}")
    for k, want in (("artifact_type", "OWNER_SETTLEMENT_WAIVER"), ("phase", PHASE), ("authorized_by", "ORNEUR_OWNER"), ("decision", "AUTHORIZED")):
        if w.get(k) != want:
            bad.append(f"{k} != {want!r}")
    ts = w.get("created_at_utc")
    try:
        if not isinstance(ts, str) or not ts:
            raise ValueError
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        bad.append("created_at_utc is not a non-empty UTC timestamp (YYYY-MM-DDTHH:MM:SSZ)")
    if not isinstance(w.get("authorization_text"), str) or not w.get("authorization_text", "").strip():
        bad.append("authorization_text missing or empty")
    if "note" in w and not isinstance(w["note"], str):
        bad.append("note is not a string")

    sc = obj("scope", WAIVER_SCOPE_KEYS)
    if sc.get("provider") != "Modal" or sc.get("control") != "Qwen3-8B":
        bad.append("scope.provider/control must be Modal / Qwen3-8B")
    if type(sc.get("historical_attempt")) is not int or sc.get("historical_attempt") != 1:
        bad.append("scope.historical_attempt must be the integer 1")
    if sc.get("waiver") != "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE":
        bad.append("scope.waiver must be BILLING_SETTLEMENT_NOT_YET_OBSERVABLE")
    if sc.get("historical_only") is not True:
        bad.append("scope.historical_only must be true")

    asr = obj("asserts", WAIVER_ASSERT_KEYS)
    if asr.get("attempt_1_cost_was_zero") is not False:
        bad.append("asserts.attempt_1_cost_was_zero must be false (historical cost may not be declared zero)")
    if asr.get("settlement_resolved") is not False:
        bad.append("asserts.settlement_resolved must be false (the waiver is not a settlement resolution)")
    if asr.get("attempt_1_valid_model_qualification_attempt") is not False:
        bad.append("asserts.attempt_1_valid_model_qualification_attempt must be false")
    if asr.get("attempt_1_status") != "HARNESS_FAILURE":
        bad.append("asserts.attempt_1_status must be HARNESS_FAILURE")
    if asr.get("attempt_1_billing_settlement_status") != "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE":
        bad.append("asserts.attempt_1_billing_settlement_status must be BILLING_SETTLEMENT_NOT_YET_OBSERVABLE")
    exp = asr.get("attempt_1_conservative_exposure_reserved_usd")
    try:
        if isinstance(exp, bool) or not isinstance(exp, (str, int)) or to_decimal(exp, "exposure") < 0:
            raise ValueError
    except Exception:  # noqa: BLE001
        bad.append("asserts.attempt_1_conservative_exposure_reserved_usd must be a non-negative decimal string")

    for key, required in (("does_not_waive", WAIVER_REQUIRED_NOT_WAIVED), ("does_not_authorize", WAIVER_REQUIRED_NOT_AUTHORIZED)):
        v = w.get(key)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            bad.append(f"{key} must be a list of strings")
        elif set(required) - set(v):
            bad.append(f"{key} missing {sorted(set(required) - set(v))}")

    ex = obj("authorized_execution", WAIVER_EXEC_KEYS)
    if ex.get("controls_in_order") != WAIVER_CONTROLS_IN_ORDER:
        bad.append(f"authorized_execution.controls_in_order must be exactly {WAIVER_CONTROLS_IN_ORDER}")
    for k, want in (("provider", "Modal"), ("gpu", "H100 80GB"), ("precision", "BF16")):
        if ex.get(k) != want:
            bad.append(f"authorized_execution.{k} != {want!r}")
    for k, want in (("quantization", False), ("model_substitution", False), ("sequential_only", True)):
        if ex.get(k) is not want:
            bad.append(f"authorized_execution.{k} must be {str(want).lower()}")

    # the waiver must agree with the historical attempt record it names (no contradictory evidence)
    if a.get("outcome") != "HARNESS_FAILURE" or a.get("billing_settlement_status") != "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE":
        bad.append("waiver contradicts the historical attempt record (must be HARNESS_FAILURE / BILLING_SETTLEMENT_NOT_YET_OBSERVABLE)")
    return ("WAIVER_INVALID", bad) if bad else ("WAIVER_ACCEPTED", [])


def settlement_resolved(tag: str, a: dict) -> bool:
    """Observed in-run, OR a read-only reconciliation artifact for that exact attempt reports OBSERVED with 0 live resources,
    OR a STRICTLY VALIDATED owner waiver for exactly Modal/Qwen3-8B/attempt 1 (never created by this script). The waiver never
    changes the historical record and never removes the conservative exposure deduction (see unresolved_settlement_upper_bound_usd)."""
    if a.get("billing_settlement_status") == "OBSERVED":
        return True
    for f in sorted(EVIDENCE_DIR.glob(f"GENESIS_CONTROL_{tag}_ATTEMPT{a['attempt_number']}_SETTLEMENT_RECONCILIATION_*.json")):
        r = json.loads(f.read_text())
        if r.get("attempt_number") == a["attempt_number"] and r.get("settlement", {}).get("status") == "OBSERVED" and r.get("live_resources") == 0:
            return True
    return validate_owner_settlement_waiver(tag, a)[0] == "WAIVER_ACCEPTED"


def unresolved_settlement_upper_bound_usd() -> Decimal:
    """Conservative runway input: every prior Modal attempt whose settlement is unresolved is charged its UPPER BOUND (rate x
    duration at the highest Modal GPU rate seen), because its actual cost has not appeared in the account data."""
    total = Decimal(0)
    for tag, a in _modal_attempts():
        if not settlement_resolved(tag, a) or a.get("billing_settlement_status") != "OBSERVED":
            total += Decimal("3.95") * Decimal(str(a.get("duration_seconds", 0))) / Decimal(3600)
    return total


def _preflight(kind: str, control_key: str, *, gpu: bool):
    lc = _load_lightning_control()
    cfg = lc.CONTROLS[control_key]
    r = rates()
    if gpu:
        worst = worst_case_cost(r, gpu=True, cores=CPU_CORES, memory_mib=GPU_MEMORY_MIB, seconds=HARD_TIMEOUT_SECONDS)
    else:
        worst = worst_case_cost(r, gpu=False, cores=CPU_CORES, memory_mib=PRECACHE_MEMORY_MIB, seconds=PRECACHE_TIMEOUT_SECONDS)
    before = billing_summary()
    snap = cleanup_snapshot()
    deduction = unresolved_settlement_upper_bound_usd()
    pool = Decimal(CREDIT_POOL_USD) - deduction
    unresolved = gpu and any(not settlement_resolved(t, a) for t, a in _modal_attempts())
    decision = financial_gate_decision(before, worst_case_job_cost_usd=str(worst), credit_pool_usd=str(pool), reserve_usd=RESERVE_USD,
                                       prior_positive_billing_seen=any_positive_billing_seen(), prior_settlement_unresolved=unresolved)
    for t, at in _modal_attempts():
        w_status, w_reasons = validate_owner_settlement_waiver(t, at)
        if w_status == "WAIVER_INVALID":
            decision = dict(decision, allowed=False, reasons=list(decision["reasons"]) + [f"WAIVER_INVALID: {w_reasons}"])
    if snap["live_resources"] != 0:
        decision = dict(decision, allowed=False, reasons=list(decision["reasons"]) + [f"{snap['live_resources']} live Modal resource(s) exist before launch"])
    return cfg, r, worst, before, snap, deduction, decision


def cmd_preflight(a) -> int:
    gpu = a.kind == "gpu"
    cfg, r, worst, before, snap, deduction, decision = _preflight(a.kind, a.control, gpu=gpu)
    art = {"evidence_type": "MODAL_H100_FINANCIAL_PREFLIGHT", "phase": PHASE, "control_name": cfg["control_name"], "kind": a.kind, "captured_at_utc": _now(),
           "rates_usd_per_hour": {k: str(v) for k, v in r.items()}, "hard_timeout_seconds": HARD_TIMEOUT_SECONDS if gpu else PRECACHE_TIMEOUT_SECONDS,
           "cpu_cores": CPU_CORES, "memory_mib": GPU_MEMORY_MIB if gpu else PRECACHE_MEMORY_MIB, "worst_case_cost_usd": str(worst.quantize(Decimal('0.0001'))),
           "billing_summary_live": before, "credit_pool_usd": CREDIT_POOL_USD,
           "unresolved_prior_settlement_upper_bound_deducted_usd": str(deduction.quantize(Decimal('0.0001'))),
           "reserve_usd": RESERVE_USD, "cleanup_snapshot_before": snap, "gate_decision": decision,
           "billing_discrepancy_observation": "GENESIS_BILLING_DISCREPANCY_OBSERVATION_2026-09-24.json"}
    path = EVIDENCE_DIR / f"GENESIS_CONTROL_{cfg['tag']}_MODAL_H100_{a.kind.upper()}_PREFLIGHT_{_now().replace(':', '')}.json"
    write_json(path, art)
    print(json.dumps({"gate": decision, "worst_case_usd": art["worst_case_cost_usd"], "artifact": path.name}, indent=2))
    return 0 if decision["allowed"] else 3


def cmd_precache(a) -> int:
    cfg, r, worst, before, snap, deduction, decision = _preflight("cpu", a.control, gpu=False)
    print(json.dumps({"gate": decision, "worst_case_usd": str(worst.quantize(Decimal('0.0001')))}, indent=2))
    if not decision["allowed"]:
        print("FINANCIAL GATE BLOCKED -- NOTHING STARTED")
        return 3
    t0 = _now()
    with app.run():
        out = precache.remote(a.control)
    m = out["manifest"]
    lock = LOCKED_CONTROL_IDENTITIES[cfg["control_name"]]
    ok = bool(out["rc"] == 0 and m.get("staging_verified") and m.get("revision") == lock["revision"] and m.get("weight_bytes_observed") == lock["expected_weight_bytes"]
              and m.get("all_lfs_sha256_match"))
    art = {"evidence_type": "MODAL_MODEL_PRECACHE_MANIFEST", "phase": PHASE, "control_name": cfg["control_name"], "captured_at_utc": _now(), "started_at_utc": t0,
           "cache_volume": CACHE_VOLUME, "gpu_used": False, "verified": ok, "manifest": m}
    path = EVIDENCE_DIR / f"GENESIS_CONTROL_{cfg['tag']}_MODAL_PRECACHE_MANIFEST_{DATE_TAG}.json"
    sha = write_json(path, art)
    after = billing_summary()
    snap2 = cleanup_snapshot()
    print(json.dumps({"verified": ok, "artifact": path.name, "sha256": sha, "billed_before": before["billed_cost"], "billed_after": after["billed_cost"],
                      "live_resources_after": snap2["live_resources"]}, indent=2))
    return 0 if ok and to_decimal(after["billed_cost"], "billed") == to_decimal(before["billed_cost"], "billed") and snap2["live_resources"] == 0 else 1


def _same_json(a, b) -> bool:
    """Strict JSON equality (True != 1, 0 != False): compares canonical dumps."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def container_proof_problems(result, model_id: str, locked_revision: str, extra_args=None) -> list[str]:
    """Every way the container's proof can fail to establish the approved runtime configuration + canonical protocol. Empty list == proven.
    A control WITHOUT an approved configuration must prove that NO extra request setting was sent."""
    proof = (result or {}).get("runtime_configuration_proof")
    if not isinstance(proof, dict):
        return ["the container returned no runtime_configuration_proof"]
    approved = runtime_config.configuration_for_model(model_id)
    want_id = approved["id"] if approved else None
    want_kwargs = approved["chat_template_kwargs"] if approved else None
    bad: list[str] = []
    if proof.get("runtime_configuration_id") != want_id or proof.get("runtime_configuration_id_applied") != want_id:
        bad.append(f"runtime_configuration_id (declared {proof.get('runtime_configuration_id')!r}, applied {proof.get('runtime_configuration_id_applied')!r}) != {want_id!r}")
    sent = proof.get("chat_template_kwargs_sent")
    if not isinstance(sent, dict) or sorted(sent) != list(locked_protocol.smoke_ids()) or not all(_same_json(v, want_kwargs) for v in sent.values()):
        bad.append(f"chat_template_kwargs actually sent {sent!r} != {want_kwargs!r} for every locked smoke")
    if proof.get("runtime_configuration_sha256") != runtime_config.configuration_sha256(model_id):
        bad.append("runtime configuration fingerprint differs from the canonical one")
    if proof.get("runtime_policy_sha256") != runtime_config.PINNED_RUNTIME_POLICY_SHA256:
        bad.append("container runtime-policy sha256 differs from the locally pinned runtime-policy sha256")
    if proof.get("smoke_protocol_sha256") != locked_protocol.protocol_sha256():
        bad.append("locked smoke protocol fingerprint differs from the canonical one")
    if proof.get("prompt_sha256_sent") != {sid: locked_protocol.prompt_sha256(sid) for sid in locked_protocol.smoke_ids()}:
        bad.append("per-prompt sha256 values sent differ from the canonical prompts")
    if proof.get("model_id") != model_id or proof.get("served_model_id") != model_id:
        bad.append("served model id differs from the locked model id")
    if proof.get("revision") != locked_revision:
        bad.append("served revision differs from the locked revision")
    if proof.get("precision") != "bfloat16" or proof.get("quantization") is not None:
        bad.append(f"precision/quantization ({proof.get('precision')!r}/{proof.get('quantization')!r}) != bfloat16/None")
    if approved and proof.get("reasoning_parser") != approved["reasoning_parser"]:
        bad.append("reasoning parser differs from the approved configuration")
    if extra_args is not None:                     # the exact locked server flags for this control: nothing missing, nothing leaked in from another control
        want = dict(zip(extra_args[0::2], extra_args[1::2]))
        for key, flag in (("reasoning_parser", "--reasoning-parser"), ("tokenizer_mode", "--tokenizer-mode"), ("config_format", "--config-format"), ("load_format", "--load-format")):
            if proof.get(key) != want.get(flag):
                bad.append(f"server flag {flag} proven as {proof.get(key)!r}, locked value {want.get(flag)!r}")
    return bad


METADATA_CORRECTION_KEYS = ("reasoning_mode", "metadata_correction")     # descriptive fields a documented correction may change


def _only_documented_metadata_correction(current: dict, snapshot: dict, snap_path: Path) -> bool:
    """True iff `current` differs from the immutable `snapshot` ONLY in descriptive metadata and says so, referencing the snapshot by sha256."""
    note = current.get("metadata_correction")
    if not isinstance(note, dict) or note.get("snapshot_sha256") != sha_of(snap_path) or note.get("reclassifies_attempt") is not False:
        return False
    strip = lambda d: {k: v for k, v in d.items() if k not in METADATA_CORRECTION_KEYS}
    return strip(current) == strip(snapshot)


def archive_prior_record(tag: str) -> str | None:
    """Before a new attempt may write the control's runtime record, keep the CURRENT one (with its raw smoke outputs) as an immutable
    byte-identical snapshot named after its final attempt. Fail closed if a snapshot exists but differs from the current record."""
    rec_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_{DATE_TAG}.json"
    if not rec_path.is_file():
        return None
    record = json.loads(rec_path.read_text())
    prev = (record.get("attempts") or [{}])[-1].get("attempt_number")
    if not prev or not record.get("smoke_outputs"):
        return None
    snap = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_ATTEMPT{prev}_SNAPSHOT_{DATE_TAG}.json"
    if not snap.exists():
        snap.write_bytes(rec_path.read_bytes())
    elif snap.read_bytes() != rec_path.read_bytes() and not _only_documented_metadata_correction(record, json.loads(snap.read_text()), snap):
        raise RuntimeError(f"{snap.name} differs from the current record; refusing to overwrite prior-attempt evidence")
    return snap.name


def _app_row(name: str, app_id: str | None):
    rows = _cli_json("app", "list", "--json")
    for row in rows:
        if row.get("description") == name and (app_id is None or row.get("app_id") == app_id):
            return row
    return None


def cmd_run(a) -> int:
    lc = _load_lightning_control()
    cfg, r, worst, before, snap, deduction, decision = _preflight("gpu", a.control, gpu=True)
    tag = cfg["tag"]
    pre_manifest = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_MODAL_PRECACHE_MANIFEST_{DATE_TAG}.json"
    if not pre_manifest.is_file() or not json.loads(pre_manifest.read_text()).get("verified"):
        print("the exact model revision is not pre-cached and verified; refusing to spend GPU time")
        return 2
    n = len(_load_attempts(tag)) + 1
    prefix = f"GENESIS_CONTROL_{tag}_MODAL_H100_ATTEMPT{n}"
    pre_art = {"evidence_type": "MODAL_H100_FINANCIAL_PREFLIGHT", "phase": PHASE, "control_name": cfg["control_name"], "attempt_number": n, "kind": "gpu",
               "captured_at_utc": _now(), "rates_usd_per_hour": {k: str(v) for k, v in r.items()}, "hard_timeout_seconds": HARD_TIMEOUT_SECONDS,
               "cpu_cores": CPU_CORES, "memory_mib": GPU_MEMORY_MIB, "worst_case_cost_usd": str(worst.quantize(Decimal('0.0001'))), "billing_summary_live": before,
               "credit_pool_usd": CREDIT_POOL_USD, "unresolved_prior_settlement_upper_bound_deducted_usd": str(deduction.quantize(Decimal('0.0001'))),
               "reserve_usd": RESERVE_USD, "cleanup_snapshot_before": snap, "gate_decision": decision, "precache_manifest": pre_manifest.name,
               "billing_discrepancy_observation": "GENESIS_BILLING_DISCREPANCY_OBSERVATION_2026-09-24.json"}
    pre_path = EVIDENCE_DIR / f"{prefix}_FINANCIAL_PREFLIGHT_{DATE_TAG}.json"
    pre_sha = write_json(pre_path, pre_art)
    before_path = EVIDENCE_DIR / f"{prefix}_BILLING_BEFORE_{DATE_TAG}.json"
    before_sha = write_json(before_path, {"evidence_type": "MODAL_BILLING_SNAPSHOT_BEFORE_GPU_ALLOCATION", "captured_at_utc": _now(), "billing_summary": before})
    print(json.dumps({"gate": decision, "worst_case_usd": pre_art["worst_case_cost_usd"], "preflight": pre_path.name}, indent=2))
    if not decision["allowed"]:
        print("FINANCIAL GATE BLOCKED -- NO GPU STARTED")
        return 3

    try:
        archived = archive_prior_record(tag)
    except RuntimeError as e:
        print(f"REFUSING TO START: {e}")
        return 2
    if archived:
        print(f"prior-attempt record preserved as {archived}")
    billed_before = to_decimal(before["billed_cost"], "billed_before")
    started, t0 = _now(), time.time()
    outcome, reason, result, error_text = "HARNESS_FAILURE", "unset", None, None
    try:
        with app.run():
            app_id = app.app_id
            result = serve_and_smoke.remote(a.control)          # blocking; Modal's function timeout is the hard active-H100 cap
    except BaseException as e:  # noqa: BLE001  (includes Modal's function-timeout error)
        error_text = f"{type(e).__name__}: {str(e)[:300]}"
        app_id = getattr(app, "app_id", None)
    duration = round(time.time() - t0, 1)
    finished = _now()

    time.sleep(10)
    cleanup = cleanup_snapshot()
    row = _app_row(app.name, app_id)
    readings, t_settle = [], time.time()
    for i in range(SETTLE_READINGS):
        live = billing_summary()
        readings.append({"t": round(time.time() - t_settle, 1), "billed": live["billed_cost"], "metered": live["metered_cost"], "credits": live["adjustments"]["credits"]})
        if i < SETTLE_READINGS - 1:
            time.sleep(SETTLE_INTERVAL_SECONDS)
    after = live
    peak = max(to_decimal(x["billed"], "billed reading") for x in readings)
    delta = peak - billed_before                                  # STRICT: any positive reading is positive owner billing
    recon = build_financial_reconciliation(before, after, credit_pool_usd=str(Decimal(CREDIT_POOL_USD) - deduction), reserve_usd=RESERVE_USD,
                                           max_run_cost_usd=str(worst), peak_billed_usd=str(peak))
    try:
        report = _cli_json("billing", "report", "--start", started[:10], "--end", (datetime.fromisoformat(started[:10]) + timedelta(days=2)).strftime("%Y-%m-%d"),
                           "--resolution", "h", "--json")
        mine = [x for x in report if isinstance(x, dict) and x.get("object_id") == app_id]      # by object id: every attempt's app shares one description
        visible = sum((Decimal(str(x["cost"])) for x in mine), Decimal(0))
    except Exception as e:  # noqa: BLE001
        mine, visible = [], None
    settlement = assess_settlement(recon, run_report_metered_usd=None if visible is None else str(visible))
    after_path = EVIDENCE_DIR / f"{prefix}_BILLING_AFTER_{DATE_TAG}.json"
    after_sha = write_json(after_path, {"evidence_type": "MODAL_BILLING_SNAPSHOT_AFTER_GPU_ALLOCATION", "captured_at_utc": _now(), "billing_summary_settled": after,
                                        "billed_before_usd": str(billed_before), "peak_observed_billed_usd": str(peak), "owner_billed_delta_usd": str(delta),
                                        "post_run_readings": readings, "financial_reconciliation": recon, "billing_settlement": settlement,
                                        "app_row": row, "app_id": app_id, "itemized_rows_for_app": mine, "duration_seconds_wall": duration, "cleanup_snapshot": cleanup,
                                        "object_specific_note": "the app's own created/stopped timestamps (Modal) are the authoritative active window; itemized billing rows may lag"})

    # LOCKED smoke semantics: HTTP 200 + non-empty content is NOT enough; each response must satisfy its exact locked requirement
    smokes_ok = bool(result and len(result.get("smoke_results", [])) == 3
                     and all(smoke_locked_acceptance(x.get("smoke_id"), x.get("content"))[0] for x in result["smoke_results"]))
    tech_ok = bool(result and not result.get("error") and result.get("server_ready") and smokes_ok
                   and all(x.get("http_status") == 200 and x.get("content") and not x.get("error") for x in result["smoke_results"])
                   and result.get("orphan_vllm_processes_after_shutdown") == 0)
    locked_identity = LOCKED_CONTROL_IDENTITIES[cfg["control_name"]]
    proof_problems = container_proof_problems(result, locked_identity["model_id"], locked_identity["revision"], cfg["extra_args"]) if result is not None else []
    if error_text is None and result is not None and proof_problems:
        outcome, reason = "HARNESS_FAILURE", "the container did not prove the approved runtime configuration and canonical locked smoke protocol: " + "; ".join(proof_problems)
    elif error_text is None:
        if result is not None and (result.get("server_argv_sanitized") or result.get("error")):
            outcome = "TECHNICAL_SUCCESS" if tech_ok else "TECHNICAL_FAILURE"
            reason = ("server ready, all 3 LOCKED smokes matched exactly, clean shutdown" if tech_ok else
                      (result.get("error") or ("locked smoke contract not met: " + "; ".join(f"{x.get('smoke_id')}: {smoke_locked_acceptance(x.get('smoke_id'), x.get('content'))[1]}"
                                                                                           for x in result.get("smoke_results", []) if not smoke_locked_acceptance(x.get("smoke_id"), x.get("content"))[0])
                                               if result.get("server_ready") and not smokes_ok else "smoke/teardown criteria not met")))
        else:
            outcome, reason = "HARNESS_FAILURE", "no usable result returned"
    else:
        outcome = "ABORTED_FINANCIAL_GUARD" if "Timeout" in error_text else "HARNESS_FAILURE"
        reason = error_text
    valid_runtime = bool(result and result.get("server_argv_sanitized") and outcome in ("TECHNICAL_SUCCESS", "TECHNICAL_FAILURE"))
    cleanup_pass = cleanup["live_resources"] == 0
    log_path = EVIDENCE_DIR / f"{prefix}_RAW_LOG_{DATE_TAG}.txt"
    log_path.write_text(("\n".join(result.get("events", [])) + "\n\n===== vLLM server log (tail) =====\n" + result.get("server_log", "")) if result else f"NO RESULT RETURNED: {reason}\n")
    log_sha = sha_of(log_path)
    attempt = {"attempt_number": n, "provider": "Modal", "outcome": outcome, "status": outcome, "failure_domain": FAILURE_DOMAIN_BY_OUTCOME[outcome],
               "valid_runtime_attempt": valid_runtime, "reason": reason, "resource_type": f"Modal ephemeral function {GPU_TYPE}x1 (H100 80GB), timeout {HARD_TIMEOUT_SECONDS}s",
               "duration_seconds": duration, "owner_billed_delta_usd": str(delta), "billing_settlement_status": settlement["status"],
               "cleanup_result": "PASS" if cleanup_pass else "FAIL", "started_at_utc": started, "finished_at_utc": finished, "modal_app_name": app.name,
               "modal_app_id": app_id, "raw_log_artifact": log_path.name, "raw_log_sha256": log_sha}
    attempts = _load_attempts(tag) + [attempt]
    write_json(_attempts_path(tag), {"control_name": cfg["control_name"], "attempts": attempts})

    stage = (result or {}).get("stage_manifest")
    fin = {"owner_cash_delta_usd": str(delta), "credits_after_nonnegative": True, "live_gpu_machines_after": cleanup["live_resources"]}
    record = lc.build_lightning_record(a.control, result, n, attempt, fin, log_path, log_sha, started, finished, stage)
    record.pop("lightning_financial", None)
    record.update({
        "gpu_provider": "Modal", "gpu_type": "NVIDIA H100 80GB (Modal H100)", "container_image": VLLM_IMAGE_TAG, "container_digest": VLLM_IMAGE_DIGEST,
        "runtime_name": "vLLM (official vllm/vllm-openai image on Modal, OpenAI-compatible server; model from a verified Modal Volume cache)",
        "attempts": attempts,
        "financial_evidence": {"preflight_artifact": pre_path.name, "preflight_sha256": pre_sha, "billing_before_artifact": before_path.name,
                               "billing_before_sha256": before_sha, "billing_after_artifact": after_path.name, "billing_after_sha256": after_sha},
        "financial_reconciliation": recon, "billing_settlement": settlement,
        "billing_discrepancy_observation": {"artifact": "GENESIS_BILLING_DISCREPANCY_OBSERVATION_2026-09-24.json",
                                            "sha256": sha_of(EVIDENCE_DIR / "GENESIS_BILLING_DISCREPANCY_OBSERVATION_2026-09-24.json")},
        "notes": "Runtime-compatibility evidence only. Capability is UNPROVEN: no benchmark, Genesis eval item, or holdout was run. Metrics come from tiny smoke requests. Generated output was "
                 "treated as data and never executed. Executed on Modal (canonical provider) on 1 x H100 80GB with weights from a hash-verified Modal Volume cache; earlier Modal, Lightning, "
                 "Hugging Face and razorBridge attempts are preserved in attempts.",
    })
    for k in ("container_image", "container_digest"):
        record["unobservable_reasons"].pop(k, None)
    approved_cfg = runtime_config.configuration_for_model(locked_identity["model_id"])
    record["runtime_configuration"] = None if approved_cfg is None else {
        "id": approved_cfg["id"], "chat_template_kwargs": approved_cfg["chat_template_kwargs"],
        "configuration_sha256": runtime_config.configuration_sha256(locked_identity["model_id"]),
        "runtime_policy_sha256": runtime_config.PINNED_RUNTIME_POLICY_SHA256,
        "container_proof": (result or {}).get("runtime_configuration_proof")}
    record["reasoning_mode"] = runtime_config.effective_reasoning_mode(record.get("reasoning_mode"), record["runtime_configuration"])   # effective config, not template capability
    record["smoke_acceptance"] = compute_smoke_acceptance(record)      # derived from the raw outputs; the raw outputs themselves are never altered
    record["runtime_qualification_status"] = derive_runtime_status(
        technical=record["technical_serving_status"], financial_acceptance=record["financial_acceptance_status"], cleanup=record["cleanup_status"],
        owner_billed_delta_usd=record["owner_billed_delta_usd"], live_resources_after_cleanup=record["live_resources_after_cleanup"],
        settlement_status=settlement["status"])          # delayed settlement => PENDING_SETTLEMENT_OBSERVATION, never a false RUNTIME_QUALIFIED
    validation_error = None
    try:
        validate_control_runtime_record(record, evidence_root=EVIDENCE_DIR)
    except Exception as e:  # noqa: BLE001
        validation_error = f"{type(e).__name__}: {e}"
        record["validator_note"] = f"record FAILED its own validator: {validation_error}"
    out = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_{DATE_TAG}.json"
    write_json(out, record)
    print(json.dumps({k: record[k] for k in ("technical_serving_status", "financial_acceptance_status", "owner_billed_delta_usd", "runtime_qualification_status",
                                              "cleanup_status", "live_resources_after_cleanup")}, indent=2))
    print(json.dumps({"wall_seconds": duration, "app_row": row, "settlement": settlement["status"], "settlement_reasons": settlement["reasons"],
                      "billed_delta": str(delta), "worst_case_usd": str(worst.quantize(Decimal('0.0001')))}, indent=2, default=str))
    print("validator:", validation_error or "OK")
    if delta != 0:
        print("POSITIVE OWNER BILLING -- STOP ALL FURTHER GPU RUNS")
        return 4
    return 0 if record["runtime_qualification_status"] == "RUNTIME_QUALIFIED" and not validation_error else 1


def _breakdown_total(summary: dict) -> Decimal | None:
    parts = summary.get("metered_cost_breakdown")
    if not isinstance(parts, dict) or not parts:
        return None
    return sum((Decimal(str(v)) for v in parts.values()), Decimal(0))


def _json_file(path: Path) -> dict:
    return json.loads(path.read_text())


def _verified_artifact(name: str, want_sha: str | None = None) -> tuple[dict | None, str | None, str | None]:
    """(content, sha256, error). Any missing/mismatching original evidence is an error (fail closed)."""
    path = EVIDENCE_DIR / name
    if not path.is_file():
        return None, None, f"missing original evidence {name}"
    sha = sha_of(path)
    if want_sha is not None and sha != want_sha:
        return None, sha, f"hash of {name} does not match the recorded sha256"
    return (json.loads(path.read_text()) if name.endswith(".json") else {}), sha, None


def cmd_reconcile(a) -> int:
    """STRICTLY READ-ONLY delayed-settlement reconciliation for a completed Modal H100 attempt.
    Reads Modal billing/app/container/volume state and local evidence, writes ONE timestamped reconciliation artifact and, only when
    settlement is OBSERVED and every gate holds, finalizes the existing runtime record WITHOUT rerunning anything. It never allocates
    a GPU, never starts a Modal function or container, never touches the owner waiver, and never executes generated output."""
    lc = _load_lightning_control()
    cfg = lc.CONTROLS[a.control]
    tag = cfg["tag"]
    att = next((x for x in _load_attempts(tag) if x.get("attempt_number") == a.attempt), None)
    if att is None or att.get("provider") != "Modal" or not att.get("modal_app_id"):
        print(f"unknown or non-Modal-H100 attempt {a.attempt} for {a.control}; refusing")
        return 2
    prefix = f"GENESIS_CONTROL_{tag}_MODAL_H100_ATTEMPT{a.attempt}"
    rec_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_{DATE_TAG}.json"
    record = _json_file(rec_path) if rec_path.is_file() else None
    if record is None or record.get("attempts", [{}])[-1].get("attempt_number") != a.attempt:
        print("the runtime record does not end with the requested attempt; refusing")
        return 2
    fin = record["financial_evidence"]
    errors: list[str] = []
    originals = {}
    for key, art, sha in (("preflight", "preflight_artifact", "preflight_sha256"), ("billing_before", "billing_before_artifact", "billing_before_sha256"),
                          ("billing_after", "billing_after_artifact", "billing_after_sha256")):
        content, _sha, err = _verified_artifact(fin[art], fin[sha])
        originals[key] = content
        if err:
            errors.append(err)
    _c, log_sha, err = _verified_artifact(att["raw_log_artifact"], att["raw_log_sha256"])
    if err:
        errors.append(err)
    if errors:
        print("ORIGINAL EVIDENCE INTEGRITY FAILURE:", errors)
        return 6

    pre, baseline_doc, after_doc = originals["preflight"], originals["billing_before"], originals["billing_after"]
    baseline = baseline_doc["billing_summary"]
    now = billing_summary()
    cleanup = cleanup_snapshot()
    app_id = att["modal_app_id"]
    row = _app_row(att["modal_app_name"], app_id)
    start = att["started_at_utc"][:10]
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    report = _cli_json("billing", "report", "--start", start, "--end", end, "--resolution", "h", "--json")
    mine = [x for x in report if isinstance(x, dict) and x.get("object_id") == app_id]
    visible = sum((Decimal(str(x["cost"])) for x in mine), Decimal(0))
    peak_recorded = to_decimal(after_doc["peak_observed_billed_usd"], "recorded peak billed")
    billed_before = to_decimal(baseline["billed_cost"], "billed_before")
    peak = max(peak_recorded, to_decimal(now["billed_cost"], "billed now"))
    owner_delta = peak - billed_before
    pool = Decimal(pre["credit_pool_usd"]) - Decimal(pre["unresolved_prior_settlement_upper_bound_deducted_usd"])
    recon = build_financial_reconciliation(baseline, now, credit_pool_usd=str(pool), reserve_usd=pre["reserve_usd"],
                                           max_run_cost_usd=pre["worst_case_cost_usd"], peak_billed_usd=str(peak))
    settlement = assess_settlement(recon, run_report_metered_usd=str(visible))
    metered_delta = to_decimal(recon["metered_delta_usd"], "metered_delta")
    # the account-level metered_cost total is rounded to the cent; the per-category breakdown is exact, so use it for attribution when present
    precise = _breakdown_total(now), _breakdown_total(baseline)
    metered_delta_precise = precise[0] - precise[1] if None not in precise else metered_delta
    unattributed = metered_delta_precise - visible
    reasons = list(settlement["reasons"])
    if settlement["status"] == "OBSERVED" and unattributed > Decimal("0.0001"):
        reasons.append(f"metered growth {metered_delta_precise} exceeds the run's own itemized cost {visible} by {unattributed}; the excess cannot be attributed to this run")
    app_stopped = bool(row) and row.get("state") == "stopped" and int(row.get("tasks", 0) or 0) == 0
    if not app_stopped:
        reasons.append("the attempt's Modal app is not in state 'stopped' with 0 tasks")
    if cleanup["live_resources"] != 0 or cleanup["containers"]:
        reasons.append(f"live Modal resources are not zero ({cleanup['live_resources']})")
    if owner_delta != 0:
        reasons.append(f"POSITIVE OWNER BILLING observed (delta {owner_delta})")
    observed = settlement["status"] == "OBSERVED" and not reasons
    settlement = {"status": "OBSERVED" if observed else "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", "reasons": reasons, "stop_before_next_control": not observed}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {"evidence_type": "ATTEMPT_SETTLEMENT_RECONCILIATION_READ_ONLY", "phase": PHASE, "control_name": cfg["control_name"], "attempt_number": a.attempt,
           "captured_at_utc": _now(), "modal_app_id": app_id, "modal_app_name": att["modal_app_name"],
           "original_run_window_utc": [att["started_at_utc"], att["finished_at_utc"]], "wall_seconds": att["duration_seconds"],
           "original_evidence": {"preflight": fin["preflight_artifact"], "billing_before": fin["billing_before_artifact"], "billing_after": fin["billing_after_artifact"],
                                 "raw_log": att["raw_log_artifact"], "raw_log_sha256": log_sha, "financial_evidence_sha256": {k: fin[k] for k in fin if k.endswith("_sha256")}},
           "original_billing_baseline": baseline, "fresh_billing_state": now, "itemized_rows_attributable_to_run": mine,
           "itemized_run_cost_usd": str(visible), "itemized_report_range": [start, end], "financial_reconciliation": recon,
           "metered_delta_total_usd": str(metered_delta), "metered_delta_precise_usd": str(metered_delta_precise),
           "metered_delta_precision_note": "metered_cost totals are rounded to the cent; the exact figure is the sum of metered_cost_breakdown categories when present",
           "metered_unattributed_usd": str(unattributed),
           "promotional_credit_delta_attributable_usd": str(visible) if observed else None,
           "credits_applied_delta_usd": str(to_decimal(recon["credits_applied_postrun_usd"], "c1") - to_decimal(recon["credits_applied_baseline_usd"], "c0")),
           "owner_cash_delta_usd": str(owner_delta), "owner_billed_delta_usd": str(owner_delta), "settlement": settlement,
           "app_row": row, "app_stopped_with_zero_tasks": app_stopped, "cleanup_snapshot": cleanup, "live_resources": cleanup["live_resources"],
           "cache_volume_counted_as_live_resource": False,
           "waiver_applies": False, "waiver_note": "the attempt-1 owner waiver never applies to this attempt; settlement here is evidenced, not waived",
           "no_gpu_started": True, "no_modal_function_called": True,
           "verdict": "SETTLEMENT_OBSERVED" if observed else "SETTLEMENT_STILL_NOT_OBSERVABLE"}
    path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPT{a.attempt}_SETTLEMENT_RECONCILIATION_{stamp}.json"
    sha = write_json(path, out)
    print(json.dumps({"artifact": path.name, "sha256": sha, "verdict": out["verdict"], "reasons": reasons, "itemized_run_cost_usd": str(visible),
                      "metered_delta_usd": str(metered_delta), "owner_billed_delta_usd": str(owner_delta), "live_resources": cleanup["live_resources"]}, indent=2))
    if owner_delta != 0:
        print("POSITIVE OWNER BILLING -- STOP")
        return 4
    if not observed:
        print("BILLING_SETTLEMENT_NOT_YET_OBSERVABLE -- qualification stays pending; reconcile again later")
        _set_pending_status(record, rec_path)
        _downgrade_contaminated_settlement(record, rec_path, path, sha, out, att, after_doc, app_id)
        return 5
    return _finalize_record(record, rec_path, path, sha, out, att)


def _downgrade_contaminated_settlement(record: dict, rec_path: Path, art_path: Path, art_sha: str, art: dict, att: dict, after_doc: dict, app_id: str) -> None:
    """If the in-run settlement said OBSERVED but was computed from itemized rows that belong to OTHER apps (an earlier version matched rows by the shared app
    description), and the exact-attribution reconciliation cannot confirm it, correct the SETTLEMENT claim honestly: the original is preserved, the technical
    result and status are untouched, and the settlement gate for later controls stays closed until a reconciliation observes it."""
    if record.get("billing_settlement", {}).get("status") != "OBSERVED" or "settlement_correction" in record:
        return
    foreign = [r for r in after_doc.get("itemized_rows_for_app", []) if isinstance(r, dict) and r.get("object_id") != app_id]
    if not foreign:
        return
    final = json.loads(json.dumps(record))
    final["original_in_run_billing_settlement"] = record["billing_settlement"]
    final["billing_settlement"] = art["settlement"]
    final["settlement_correction"] = {
        "reason": "the in-run OBSERVED was computed from itemized rows that included another attempt's app (rows were matched by the shared app description, not by object id); "
                  "the read-only exact-attribution reconciliation cannot confirm settlement", "foreign_rows_in_original_itemization": foreign,
        "reconciliation_artifact": art_path.name, "reconciliation_sha256": art_sha, "reclassifies_attempt": False,
        "unchanged": ["raw responses", "raw log", "smoke outputs", "container proof", "technical result and status", "owner billed delta"]}
    validate_control_runtime_record(final, evidence_root=EVIDENCE_DIR)
    write_json(rec_path, final)
    tag = _tag_of_record(final)
    attempts = _load_attempts(tag)
    for i, x in enumerate(attempts):
        if x.get("attempt_number") == att["attempt_number"] and x.get("billing_settlement_status") == "OBSERVED":
            attempts[i] = dict(x, billing_settlement_status="BILLING_SETTLEMENT_NOT_YET_OBSERVABLE", original_in_run_billing_settlement_status="OBSERVED",
                               settlement_correction=f"see {art_path.name}")
    write_json(_attempts_path(tag), {"control_name": final["control_name"], "attempts": attempts})
    print("in-run settlement claim corrected to BILLING_SETTLEMENT_NOT_YET_OBSERVABLE (original preserved); technical status unchanged")


def _tag_of_record(record: dict) -> str:
    return {"Qwen3-8B": "QWEN3_8B", "Mistral-Nemo-Instruct-2407": "MISTRAL_NEMO", "Phi-4": "PHI4"}[record["control_name"]]


def _set_pending_status(record: dict, rec_path: Path) -> None:
    """Correct a self-inconsistent label only (technical evidence untouched): a technically+financially clean run whose settlement is
    not yet observed is PENDING_SETTLEMENT_OBSERVATION, not RUNTIME_QUALIFIED."""
    if record.get("runtime_qualification_status") == "PENDING_SETTLEMENT_OBSERVATION" or record["billing_settlement"]["status"] == "OBSERVED":
        return
    record.setdefault("original_validator_note", record.pop("validator_note", None))
    record["status_correction"] = {"from": record["runtime_qualification_status"], "to": "PENDING_SETTLEMENT_OBSERVATION",
                                   "reason": "RUNTIME_QUALIFIED requires observed settlement (validator); no technical evidence was altered"}
    record["runtime_qualification_status"] = "PENDING_SETTLEMENT_OBSERVATION"
    validate_control_runtime_record(record, evidence_root=EVIDENCE_DIR)
    write_json(rec_path, record)


def _finalize_record(record: dict, rec_path: Path, art_path: Path, art_sha: str, art: dict, att: dict) -> int:
    """Finalize WITHOUT rerunning anything. Original in-run settlement/reconciliation are preserved as history; the later reconciliation
    artifact is the evidence that settlement subsequently became OBSERVED. RUNTIME_QUALIFIED only if the shared validator passes."""
    final = json.loads(json.dumps(record))
    final.setdefault("original_in_run_billing_settlement", record["billing_settlement"])
    final.setdefault("original_in_run_financial_reconciliation", record["financial_reconciliation"])
    final["billing_settlement"] = art["settlement"]
    final["financial_reconciliation"] = art["financial_reconciliation"]
    final["settlement_reconciliation"] = {"artifact": art_path.name, "sha256": art_sha, "promotional_credit_used_usd": art["itemized_run_cost_usd"],
                                          "owner_cash_delta_usd": art["owner_cash_delta_usd"]}
    if final.get("runtime_qualification_status") == "PENDING_SETTLEMENT_OBSERVATION" or final.get("validator_note"):
        final.setdefault("original_validator_note", final.pop("validator_note", None))
    final["runtime_qualification_status"] = derive_runtime_status(
        technical=final["technical_serving_status"], financial_acceptance=final["financial_acceptance_status"], cleanup=final["cleanup_status"],
        owner_billed_delta_usd=final["owner_billed_delta_usd"], live_resources_after_cleanup=final["live_resources_after_cleanup"],
        settlement_status=final["billing_settlement"]["status"])
    try:
        validate_control_runtime_record(final, evidence_root=EVIDENCE_DIR)
    except Exception as e:  # noqa: BLE001
        print(f"FINALIZED RECORD FAILED VALIDATION -- record left unchanged: {type(e).__name__}: {e}")
        return 1
    final.pop("validator_note", None)
    write_json(rec_path, final)
    print(json.dumps({"runtime_qualification_status": final["runtime_qualification_status"], "record_sha256": sha_of(rec_path),
                      "promotional_credit_used_usd": art["itemized_run_cost_usd"], "owner_cash_delta_usd": art["owner_cash_delta_usd"]}, indent=2))
    return 0 if final["runtime_qualification_status"] == "RUNTIME_QUALIFIED" else 1


def cmd_reevaluate_smokes(a) -> int:
    """CPU-ONLY, no Modal, no GPU. Re-derives the honest status of a persisted attempt from its RAW smoke outputs under the locked
    smoke semantics. Raw outputs, raw log, financial evidence and settlement evidence are never modified. If any locked smoke fails,
    the attempt is reclassified TECHNICAL_FAILURE (valid runtime attempt, model-runtime domain) with the original classification
    preserved, and the record becomes technical FAILED / runtime FAILED -- never RUNTIME_QUALIFIED."""
    lc = _load_lightning_control()
    cfg = lc.CONTROLS[a.control]
    tag = cfg["tag"]
    rec_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_{DATE_TAG}.json"
    record = _json_file(rec_path)
    att = record["attempts"][-1]
    if att.get("attempt_number") != a.attempt or att.get("provider") != "Modal":
        print("requested attempt is not the final Modal attempt of the record; refusing")
        return 2
    acceptance = compute_smoke_acceptance(record)
    failed = [x for x in acceptance if not x["accepted"]]
    final = json.loads(json.dumps(record))
    final["smoke_acceptance"] = acceptance
    if not failed:
        final["runtime_qualification_status"] = derive_runtime_status(
            technical=final["technical_serving_status"], financial_acceptance=final["financial_acceptance_status"], cleanup=final["cleanup_status"],
            owner_billed_delta_usd=final["owner_billed_delta_usd"], live_resources_after_cleanup=final["live_resources_after_cleanup"],
            settlement_status=final["billing_settlement"]["status"])
    else:
        summary = "; ".join(f"{x['smoke_id']}: {x['reason']}" for x in failed)
        new_att = dict(att)
        new_att.setdefault("original_classification", {"outcome": att["outcome"], "status": att["status"], "failure_domain": att["failure_domain"], "reason": att["reason"],
                                                       "note": "originally judged on HTTP 200 + non-empty content only; reclassified after the independent audit applied the LOCKED smoke semantics to the unchanged raw outputs"})
        new_att.update({"outcome": "TECHNICAL_FAILURE", "status": "TECHNICAL_FAILURE", "failure_domain": "MODEL_RUNTIME", "valid_runtime_attempt": True,
                        "reason": f"locked smoke contract not met ({summary}); server, identity, BF16 load, cleanup and financial gates passed"})
        final["attempts"] = record["attempts"][:-1] + [new_att]
        final.setdefault("superseded_classification", {"technical_serving_status": record["technical_serving_status"],
                                                       "runtime_qualification_status": record["runtime_qualification_status"],
                                                       "reason": "audit finding: locked Smoke B (exact '5') was not satisfied; HTTP 200 + non-empty is not acceptance"})
        final["technical_serving_status"] = "FAILED"
        final["runtime_qualification_status"] = derive_runtime_status(
            technical="FAILED", financial_acceptance=final["financial_acceptance_status"], cleanup=final["cleanup_status"],
            owner_billed_delta_usd=final["owner_billed_delta_usd"], live_resources_after_cleanup=final["live_resources_after_cleanup"],
            settlement_status=final["billing_settlement"]["status"])
        final["failure_analysis"] = {"kind": "LOCKED_SMOKE_CONTRACT_NOT_MET (model response behaviour), not an infrastructure or identity failure",
                                     "failed_smokes": failed, "infrastructure": "server ready, exact identity PASS, BF16 PASS, cleanup PASS, 0 live resources, owner billed delta 0"}
    try:
        validate_control_runtime_record(final, evidence_root=EVIDENCE_DIR)
    except Exception as e:  # noqa: BLE001
        print(f"RE-EVALUATED RECORD FAILED VALIDATION -- nothing written: {type(e).__name__}: {e}")
        return 1
    write_json(rec_path, final)
    attempts_all = _load_attempts(tag)
    attempts_all[-1] = final["attempts"][-1]
    write_json(_attempts_path(tag), {"control_name": cfg["control_name"], "attempts": attempts_all})
    print(json.dumps({"technical_serving_status": final["technical_serving_status"], "runtime_qualification_status": final["runtime_qualification_status"],
                      "smoke_acceptance": [(x["smoke_id"], x["accepted"]) for x in acceptance]}, indent=2))
    return 0


def cmd_correct_reasoning_mode(a) -> int:
    """CPU-ONLY, no Modal, no GPU. Corrects ONLY the descriptive `reasoning_mode` of a record whose approved runtime configuration is
    non-thinking. Snapshots the record first (immutable, byte-identical), changes no raw output/log/financial/settlement/proof/attempt
    outcome, does not reclassify the attempt, and records the correction with the snapshot's sha256."""
    lc = _load_lightning_control()
    cfg = lc.CONTROLS[a.control]
    tag = cfg["tag"]
    rec_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_{DATE_TAG}.json"
    record = _json_file(rec_path)
    last = record["attempts"][-1]
    rc = record.get("runtime_configuration")
    if last.get("attempt_number") != a.attempt or not isinstance(rc, dict):
        print("requested attempt is not the record's final attempt or it has no runtime configuration; refusing")
        return 2
    snap_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_ATTEMPT{a.attempt}_SNAPSHOT_{DATE_TAG}.json"
    if not snap_path.exists():
        if "metadata_correction" in record:
            print("record already corrected but its snapshot is missing; refusing")
            return 2
        snap_path.write_bytes(rec_path.read_bytes())
    corrected = runtime_config.effective_reasoning_mode(record.get("reasoning_mode"), rc)
    if corrected == record.get("reasoning_mode"):
        print("reasoning_mode already reflects the effective runtime configuration; nothing to do")
        return 0
    final = json.loads(json.dumps(record))
    final["reasoning_mode"] = corrected
    final["metadata_correction"] = {
        "field": "reasoning_mode", "from": record.get("reasoning_mode"), "to": corrected, "reclassifies_attempt": False,
        "kind": "DESCRIPTIVE METADATA ONLY: the stale value described the model's default template capability, not the effective approved runtime configuration",
        "unchanged": ["raw responses", "raw log", "financial evidence", "settlement evidence", "container proof", "smoke outputs", "attempt outcomes", "runtime/technical status"],
        "snapshot_artifact": snap_path.name, "snapshot_sha256": sha_of(snap_path), "evidence_of_effective_mode": "reasoning_tokens == 0 for every smoke; container proof chat_template_kwargs_sent == {enable_thinking: false}"}
    try:
        validate_control_runtime_record(final, evidence_root=EVIDENCE_DIR)
    except Exception as e:  # noqa: BLE001
        print(f"CORRECTED RECORD FAILED VALIDATION -- nothing written: {type(e).__name__}: {e}")
        return 1
    if not _only_documented_metadata_correction(final, json.loads(snap_path.read_text()), snap_path):
        print("internal check failed: the correction changed more than descriptive metadata; nothing written")
        return 1
    write_json(rec_path, final)
    print(json.dumps({"reasoning_mode": corrected, "snapshot": snap_path.name, "snapshot_sha256": sha_of(snap_path), "record_sha256": sha_of(rec_path)}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=("preflight", "precache", "run", "reconcile", "reevaluate-smokes", "correct-reasoning-mode"))
    ap.add_argument("--control", required=True, choices=CONTROL_KEYS)
    ap.add_argument("--attempt", type=int, help="reconcile only: the completed attempt number")
    ap.add_argument("--kind", choices=("gpu", "cpu"), default="gpu", help="preflight only")
    a = ap.parse_args()
    if a.mode == "preflight":
        return cmd_preflight(a)
    if a.mode == "precache":
        return cmd_precache(a)
    if a.mode == "correct-reasoning-mode":
        return cmd_correct_reasoning_mode(a) if a.attempt else 2
    if a.mode == "reevaluate-smokes":
        return cmd_reevaluate_smokes(a) if a.attempt else 2
    if a.mode == "reconcile":
        return cmd_reconcile(a) if a.attempt else 2
    return cmd_run(a)


if __name__ == "__main__":
    sys.exit(main())
