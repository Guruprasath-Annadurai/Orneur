"""
Phase 21B.4.20 -- control runtime qualification on LIGHTNING AI (operator side).

Provider migration from Modal (see GENESIS_CONTROL_PROVIDER_MIGRATION_MODAL_TO_LIGHTNING_2026-09-24.json).
Owner cash is INR 0: only complimentary Lightning credits are used; no payment card is ever added and no
credits are ever purchased. This script drives ONE Lightning Studio through the official SDK:

  preflight     READ-ONLY. Fresh account state + gate decision, written as an artifact.
  stage-env     (free CPU) install the pinned vLLM in a venv inside the Studio.
  stage-model   (free CPU) download + hash-verify the exact pinned revision of one control.
  verify-idle   READ-ONLY. Studio is on CPU and no GPU machine is running.
  run           (spends credits) one control, one attempt: gate -> GPU -> serve+smoke -> back to CPU
                -> cleanup proof -> credit-meter proof -> validated record.
  cleanup       force the Studio back to CPU / stopped and verify (safety net; free).

Hard rules enforced here: expected account only; FREE plan; no payment method; unrestricted 1-GPU machine;
worst-case cost (rate x hard cap) <= 1.00 credit and credits >= worst case + 1.00 reserve; never two
GPU machines; a Studio-side watchdog stops the Studio independently of this process; generated text is
data and is never executed; no benchmark, no frontier call, no automatic retry.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
import types
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
RUNNER = REPO_ROOT / "scripts/phase21b_4_20_lightning_runner.py"
MODAL_HARNESS = REPO_ROOT / "scripts/phase21b_4_20_control_runtime_qualification.py"
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"

PHASE = "21B.4.20"
DATE_TAG = "2026-09-24"
STUDIO = {"name": "ml-experiment-tracker-devbox", "teamspace": "ml-workflow-improvement-project", "org": "orneur"}
ORG_ID = "01m39tmvmye8xqq2zv7j6g8jj6"
PROJECT_ID = "01m39tmvpf2kfkkzaj17y8yxsc"
CLUSTER_ID = "lightning-public-prod"
GPU_MACHINE_NAME = "L40S"                 # lightning_sdk Machine.L40S == slug lit-l40s-1 (1 x NVIDIA L40S 48 GB)
GPU_CATALOG_SLUG_MULTI_CLOUD = "lit-l40s-1"  # == AWS g6e.4xlarge in the account's accelerator catalog
HARD_CAP_SECONDS = 900                    # 15 min at 3.54 credits/h = 0.885 credits <= 1.00 per-attempt cap
WATCHDOG_SECONDS = 840                    # Studio-side stop, independent of this process
POLL_SECONDS = 15
METER_POLL_SECONDS = 30
METER_MAX_SECONDS = 300
WORK = "$HOME/p4420"
REMOTE_RUNNER = "$HOME/p4420/runner.py"
REMOTE_PY = "$HOME/p4420/venv/bin/python"

CONTROL_KEYS = ("qwen3_8b", "mistral_nemo", "phi4")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, data: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_modal_constants() -> types.ModuleType:
    """Import CONTROLS/SMOKES from the Modal harness WITHOUT the Modal SDK (stand-in module)."""
    class _Chain:
        def __getattr__(self, _n):
            return lambda *a, **k: self

    stub = types.ModuleType("modal")
    stub.Image = type("Image", (), {"from_registry": classmethod(lambda cls, *a, **k: _Chain())})
    stub.App = lambda n: types.SimpleNamespace(name=n, function=lambda **k: (lambda f: f))
    stub.exception = types.SimpleNamespace(TimeoutError=TimeoutError)
    saved = sys.modules.get("modal")
    sys.modules["modal"] = stub
    try:
        spec = importlib.util.spec_from_file_location("p21b420_modal_consts", MODAL_HARNESS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop("modal", None)
        else:
            sys.modules["modal"] = saved
    return mod


CONSTS = load_modal_constants()
CONTROLS = CONSTS.CONTROLS
from orca.eval import locked_smoke_protocol as LOCKED_PROTOCOL
from orca.eval.control_runtime_qualification import (  # noqa: E402
    FAILURE_DOMAIN_BY_OUTCOME, LIGHTNING_PROVIDER, LOCKED_CONTROL_IDENTITIES, derive_runtime_status,
    lightning_gate_decision, to_decimal, validate_control_runtime_record,
)


# ══════════════════════════════════════════════════════════════════════════
# Account state (read-only)
# ══════════════════════════════════════════════════════════════════════════

def _client():
    from lightning_sdk.lightning_cloud.rest_client import LightningClient

    return LightningClient(max_tries=2)


def _studio():
    from lightning_sdk import Studio

    return Studio(name=STUDIO["name"], teamspace=STUDIO["teamspace"], org=STUDIO["org"], create_ok=False)


def live_gpu_machine_count() -> tuple[int, list[dict]]:
    from lightning_sdk import Teamspace

    ts = Teamspace(name=STUDIO["teamspace"], org=STUDIO["org"])
    rows, gpu = [], 0
    for st in ts.studios:
        status = str(st.status)
        machine = st.machine
        is_cpu = machine is None or getattr(machine, "family", "") == "CPU"
        rows.append({"studio": st.name, "status": status, "machine": None if machine is None else machine.name})
        if "Running" in status and not is_cpu:
            gpu += 1
    return gpu, rows


def capture_state() -> dict:
    c = _client()
    me = c.auth_service_get_user()
    org_bal = c.billing_service_get_org_balance(ORG_ID).to_dict()
    proj_bal = c.billing_service_get_project_balance(PROJECT_ID).to_dict()
    sub = c.billing_service_get_billing_subscription(org_id=ORG_ID).to_dict()
    feats = {f["key"]: {"limit": f["limit"], "hit_limit": f["hit_limit"], "current_usage": f["current_usage"]}
             for f in sub.get("features", []) if f["key"] in (
                 "requires_credit_card_verification", "concurrent_gpus", "gpu_cores", "advanced_gpu_hours", "included_credits",
                 "multi_gpu")}
    accel = c.cluster_service_list_project_cluster_accelerators(project_id=PROJECT_ID, id=CLUSTER_ID).to_dict()["accelerator"]
    mach = next(a for a in accel if a.get("slug_multi_cloud") == GPU_CATALOG_SLUG_MULTI_CLOUD)
    gpu_live, studios = live_gpu_machine_count()
    return {
        "captured_at_utc": _now(), "username": me.username,
        "plan": sub.get("name"), "subscription_amount_usd": sub.get("amount"),
        "payment_method_present": bool(sub.get("card_last4") or sub.get("card_verified") or sub.get("stripe_managed")),
        "card_last4_present": bool(sub.get("card_last4")), "card_verified": sub.get("card_verified"),
        "stripe_managed": sub.get("stripe_managed"),
        "credits_available": str(org_bal["balance"]), "project_credits": str(proj_bal["balance"]),
        "balance_limit": str(org_bal["balance_limit"]),
        "plan_features": feats,
        "machine": {"catalog_slug": mach["slug"], "slug_multi_cloud": mach["slug_multi_cloud"], "family": mach["family"],
                    "gpus": mach["resources"]["gpu"], "gpu_type": mach["resources"]["gpu_type"],
                    "rate_credits_per_hour": mach["cost"], "enabled": mach["enabled"], "tier_restricted": mach["is_tier_restricted"],
                    "out_of_capacity": mach.get("out_of_capacity"), "provider": mach["provider"],
                    "available_in_seconds": mach.get("available_in_seconds")},
        "live_gpu_machines": gpu_live, "studios": studios,
    }


def state_for_gate(state: dict) -> dict:
    return {"username": state["username"], "plan": state["plan"], "payment_method_present": state["payment_method_present"],
            "credits_available": state["credits_available"], "balance_limit": state["balance_limit"],
            "machine": state["machine"], "live_gpu_machines": state["live_gpu_machines"],
            "known_provider_gpu_block": known_provider_gpu_block(state)}


PROVIDER_REJECTION_GLOB = "GENESIS_LIGHTNING_PROVIDER_GPU_REJECTION_*.json"


def known_provider_gpu_block(state: dict) -> str | None:
    """A persisted provider rejection (HTTP 400 PermissionDenied: a verified payment method is required to start GPU
    compute) blocks every GPU run while the account still has no payment method. Adding a card is forbidden by the
    zero-owner-cash rule, so this stays blocked until the evidence is superseded by a new fresh account state."""
    if state.get("payment_method_present") is not False:
        return None
    for f in sorted(EVIDENCE_DIR.glob(PROVIDER_REJECTION_GLOB)):
        rej = json.loads(f.read_text())
        if rej.get("blocks_gpu_while_no_payment_method") is True:
            return f"{rej['provider_message']} (evidence: {f.name})"
    return None


def gate(state: dict, *, prior_positive: bool) -> dict:
    return lightning_gate_decision(state_for_gate(state), machine_rate_credits_per_hour=state["machine"]["rate_credits_per_hour"],
                                   hard_runtime_cap_seconds=HARD_CAP_SECONDS, prior_positive_owner_charge=prior_positive)


# ══════════════════════════════════════════════════════════════════════════
# Attempt bookkeeping
# ══════════════════════════════════════════════════════════════════════════

def attempts_path(tag: str) -> Path:
    return EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPTS_{DATE_TAG}.json"


def record_path(tag: str) -> Path:
    return EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_{DATE_TAG}.json"


def load_attempts(tag: str) -> list[dict]:
    p = attempts_path(tag)
    return json.loads(p.read_text())["attempts"] if p.is_file() else []


def any_positive_owner_charge() -> bool:
    return any(to_decimal(a["owner_billed_delta_usd"], "delta") != 0 for k in CONTROLS.values() for a in load_attempts(k["tag"]))


def registry_control(name: str) -> dict:
    return next(c for c in json.loads(REGISTRY_PATH.read_text())["controls"] if c["canonical_candidate_name"] == name)


def preflight(control_key: str, *, purpose: str = "run") -> tuple[dict, dict, Path, str]:
    cfg = CONTROLS[control_key]
    n = len(load_attempts(cfg["tag"])) + 1
    state = capture_state()
    decision = gate(state, prior_positive=any_positive_owner_charge())
    art = {"evidence_type": "LIGHTNING_FINANCIAL_PREFLIGHT", "phase": PHASE, "control_name": cfg["control_name"], "attempt_number": n,
           "purpose": purpose, "provider": LIGHTNING_PROVIDER, "state": state, "gate_decision": decision,
           "hard_runtime_cap_seconds": HARD_CAP_SECONDS, "watchdog_seconds": WATCHDOG_SECONDS,
           "rules": "owner cash INR 0; complimentary credits only; no card; no purchases; per-attempt cap 1.00 credit; reserve 1.00 credit",
           "gpu_execution_allowed": bool(decision["allowed"]) and purpose == "run"}
    path = EVIDENCE_DIR / f"GENESIS_CONTROL_{cfg['tag']}_LIGHTNING_ATTEMPT{n}_{'PREFLIGHT_ONLY' if purpose == 'preflight' else 'PREFLIGHT'}_{_now().replace(':', '')}.json"
    return art, state, path, cfg["tag"]


# ══════════════════════════════════════════════════════════════════════════
# Studio helpers
# ══════════════════════════════════════════════════════════════════════════

def studio_running_on_cpu(st) -> bool:
    m = st.machine
    return "Running" in str(st.status) and m is not None and getattr(m, "family", "") == "CPU"


def sh(st, cmd: str, *, allow_fail: bool = False) -> tuple[str, int]:
    out, code = st.run_with_exit_code(cmd)
    if code != 0 and not allow_fail:
        raise RuntimeError(f"studio command failed ({code}): {cmd[:120]}\n{out[-800:]}")
    return out, code


def push_runner(st) -> str:
    st.upload_file(str(RUNNER), "p4420/runner.py", progress_bar=False)
    local, remote = sha_of(RUNNER), ""
    for _ in range(10):  # the uploaded file can take a few seconds to become visible inside the Studio
        out, _c = sh(st, f"sha256sum {REMOTE_RUNNER} 2>/dev/null | cut -d' ' -f1", allow_fail=True)
        remote = out.strip().splitlines()[-1].strip() if out.strip() else ""
        if remote == local:
            return local
        time.sleep(5)
    raise RuntimeError(f"uploaded runner hash mismatch: remote {remote!r} != local {local}")


def wait_marker(st, marker: str, timeout_s: int, poll_s: int = 20) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        out, _ = sh(st, f"test -f {marker} && echo YES || echo NO", allow_fail=True)
        if out.strip().endswith("YES"):
            return True
        time.sleep(poll_s)
    return False


def cmd_stage_env() -> int:
    st = _studio()
    if not studio_running_on_cpu(st):
        print("Studio is not Running on CPU; refusing to stage")
        return 2
    sh(st, f"mkdir -p {WORK}")
    push_runner(st)
    sh(st, f"rm -f {WORK}/stage_env.done {WORK}/stage_env.fail; cd {WORK} && nohup sh -c "
           f"'python runner.py stage-env > stage_env.out 2>&1 && touch stage_env.done || touch stage_env.fail' >/dev/null 2>&1 &")
    for _ in range(90):  # up to ~30 min
        out, _ = sh(st, f"ls {WORK} | grep -E 'stage_env\\.(done|fail)' || true", allow_fail=True)
        if "stage_env.done" in out or "stage_env.fail" in out:
            break
        time.sleep(20)
    out, _ = sh(st, f"tail -c 2500 {WORK}/stage_env.out", allow_fail=True)
    print(out)
    return 0 if "stage_env.done" in sh(st, f"ls {WORK}", allow_fail=True)[0] else 3


def cmd_stage_model(control_key: str) -> int:
    st = _studio()
    if not studio_running_on_cpu(st):
        print("Studio is not Running on CPU; refusing to stage")
        return 2
    push_runner(st)
    tag = control_key
    sh(st, f"rm -f {WORK}/stage_{tag}.done {WORK}/stage_{tag}.fail; cd {WORK} && nohup sh -c "
           f"'{REMOTE_PY} runner.py stage-model --control {control_key} > stage_{tag}.out 2>&1 && touch stage_{tag}.done || touch stage_{tag}.fail' >/dev/null 2>&1 &")
    for _ in range(180):  # up to ~60 min
        out, _ = sh(st, f"ls {WORK} | grep -E 'stage_{tag}\\.(done|fail)' || true", allow_fail=True)
        if f"stage_{tag}.done" in out or f"stage_{tag}.fail" in out:
            break
        time.sleep(20)
    out, _ = sh(st, f"tail -c 2500 {WORK}/stage_{tag}.out", allow_fail=True)
    print(out)
    ok = f"stage_{tag}.done" in sh(st, f"ls {WORK}", allow_fail=True)[0]
    if ok:
        dst = EVIDENCE_DIR / f"GENESIS_CONTROL_{CONTROLS[control_key]['tag']}_LIGHTNING_STAGE_MANIFEST_{DATE_TAG}.json"
        for i in range(8):  # a just-written file can take a few seconds to become downloadable
            try:
                st.download_file(f"p4420/stage_{control_key}.json", str(dst))
                break
            except RuntimeError:
                if i == 7:
                    raise
                time.sleep(6)
    return 0 if ok else 3


def cmd_verify_idle() -> int:
    st = _studio()
    gpu, rows = live_gpu_machine_count()
    print(json.dumps({"studio_status": str(st.status), "machine": None if st.machine is None else st.machine.name,
                      "live_gpu_machines": gpu, "studios": rows}, indent=2))
    return 0 if gpu == 0 else 4


def force_cpu_and_verify(st) -> dict:
    """Best-effort cleanup: back to CPU, else stop. Returns evidence of the final state."""
    from lightning_sdk import Machine

    notes = []
    for attempt in range(3):
        try:
            m = st.machine
            if m is not None and getattr(m, "family", "") != "CPU" and "Running" in str(st.status):
                st.switch_machine(Machine.CPU)
                notes.append(f"switch_machine(CPU) ok (try {attempt + 1})")
            break
        except Exception as e:  # noqa: BLE001
            notes.append(f"switch_machine(CPU) error {type(e).__name__}: {str(e)[:120]}")
            time.sleep(10)
    gpu, rows = live_gpu_machine_count()
    if gpu != 0:
        try:
            st.stop()
            notes.append("studio.stop() issued")
        except Exception as e:  # noqa: BLE001
            notes.append(f"studio.stop error {type(e).__name__}: {str(e)[:120]}")
        time.sleep(10)
        gpu, rows = live_gpu_machine_count()
    return {"captured_at_utc": _now(), "notes": notes, "live_gpu_machines": gpu, "studios": rows}


def cmd_cleanup() -> int:
    ev = force_cpu_and_verify(_studio())
    print(json.dumps(ev, indent=2))
    return 0 if ev["live_gpu_machines"] == 0 else 4


def meter_proof() -> dict:
    """Poll the org credit balance until two consecutive readings agree (meter stopped) or time runs out."""
    c = _client()
    samples, stable, last = [], 0, None
    t0 = time.time()
    while time.time() - t0 < METER_MAX_SECONDS:
        bal = str(c.billing_service_get_org_balance(ORG_ID).to_dict()["balance"])
        samples.append({"t": round(time.time() - t0, 1), "credits": bal, "at": _now()})
        stable = stable + 1 if bal == last else 0
        last = bal
        if stable >= 2:
            break
        time.sleep(METER_POLL_SECONDS)
    return {"stopped": stable >= 2, "samples": samples, "final_credits": last}


def build_lightning_record(control_key, result, attempt_no, attempt, fin, log_path, log_sha, started, finished, stage_manifest) -> dict:
    cfg, locked = CONTROLS[control_key], LOCKED_CONTROL_IDENTITIES[CONTROLS[control_key]["control_name"]]
    reg = registry_control(cfg["control_name"])
    result = result or {}
    vers, log = result.get("versions", {}), result.get("server_log", "")
    import re

    unobservable: dict[str, str] = {}

    def metric(key, value, why):
        if value is None:
            unobservable[key] = why
        return value

    load_m = re.search(r"[Ll]oading (?:model )?weights took ([0-9.]+) seconds", log) or re.search(r"Model loading took [0-9.]+ GiB.*?([0-9.]+) seconds", log)
    backend_m = re.search(r"Using ([A-Za-z0-9_ .\-]*(?:[Aa]ttention|FLASH|Flash|FlashInfer|backend)[A-Za-z0-9_ .\-]*?)(?: backend| for|\.|$)", log, re.MULTILINE)
    smokes = result.get("smoke_results", [])
    first = next((s for s in smokes if s["smoke_id"] == "A"), {})
    total_tokens = sum((s.get("usage") or {}).get("completion_tokens", 0) for s in smokes) if smokes else None
    total_latency = sum(s.get("latency_seconds", 0) for s in smokes) if smokes else None
    tps = (total_tokens / total_latency) if total_tokens and total_latency else None
    peak, steady = result.get("peak_gpu_memory_used_mib"), result.get("steady_gpu_memory_used_mib")
    weight_bytes = result.get("weight_bytes_observed")
    model_id, revision = reg["artifact_repository"], reg["exact_immutable_revision"]
    ident = {
        "pinned_revision_matches_runtime_artifact": bool(result.get("snapshot_dir_name") == revision),
        "runtime_served_model_matches_pinned_id": bool((result.get("models_endpoint") or {}).get("data")
                                                       and result["models_endpoint"]["data"][0].get("id") == model_id),
        "weight_bytes_observed": weight_bytes, "weight_bytes_expected_for_pinned_revision": locked["expected_weight_bytes"],
        "no_silent_model_fallback": bool(result.get("snapshot_dir_name") == revision and weight_bytes == locked["expected_weight_bytes"]),
        "cpu_stage_manifest_all_lfs_sha256_match": bool(stage_manifest and stage_manifest.get("all_lfs_sha256_match")),
        "identity_evidence_strength": "HF snapshot dir == pinned commit AND summed shard bytes == recorded exact bytes AND every staged file's sha256 equals the Hugging Face LFS sha256 (CPU stage manifest) AND /v1/models id == pinned repo id AND server started from that local snapshot with HF_HUB_OFFLINE=1. vLLM exposes no separate runtime revision field.",
        "snapshot_dir_names": result.get("snapshot_dir_names"), "weight_shard_files": result.get("weight_shard_files"),
        "models_endpoint": result.get("models_endpoint"),
    }
    outputs = []
    for s in smokes:
        raw = s.get("raw_response") or ""
        outputs.append({"smoke_id": s["smoke_id"], "http_status": s.get("http_status"), "raw_response": raw,
                        "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(), "content": s.get("content"),
                        "finish_reason": s.get("finish_reason"), "usage": s.get("usage"), "latency_seconds": s.get("latency_seconds"),
                        "ttft_seconds": s.get("ttft_seconds"), "matches_expected_exactly": s.get("matches_expected_exactly"),
                        "chat_template_kwargs_sent": s.get("chat_template_kwargs_sent"), "prompt_sha256_sent": s.get("prompt_sha256_sent"), "executed": False})
    if attempt["outcome"] == "TECHNICAL_SUCCESS":
        technical = "QUALIFIED"
    elif attempt["outcome"] == "TECHNICAL_FAILURE" and attempt.get("valid_runtime_attempt") is True:
        technical = "FAILED"
    else:
        technical = "NOT_PROVEN"
    owner_delta = to_decimal(fin["owner_cash_delta_usd"], "owner delta")
    financial = "PASS" if owner_delta == 0 and fin["credits_after_nonnegative"] else "FAILED"
    cleanup_pass = attempt["cleanup_result"] == "PASS"
    runtime = derive_runtime_status(technical=technical, financial_acceptance=financial, cleanup=attempt["cleanup_result"],
                                    owner_billed_delta_usd=owner_delta, live_resources_after_cleanup=fin["live_gpu_machines_after"])
    lf = {k: v for k, v in fin.items() if k not in ("credits_after_nonnegative", "live_gpu_machines_after")}
    return {
        "phase": PHASE, "evidence_kind": "RUNTIME_QUALIFICATION_SMOKE", "control_name": cfg["control_name"],
        "model_id": model_id, "model_revision": revision, "tokenizer_revision": metric("tokenizer_revision", revision, "n/a"),
        "architecture": reg.get("architecture"), "license": reg.get("license_identifier"),
        "runtime_name": "vLLM (pip venv inside a Lightning AI Studio, OpenAI-compatible server)",
        "runtime_version": metric("runtime_version", vers.get("vllm"), "vLLM version not reported"),
        "container_image": metric("container_image", None, "not applicable: pip-installed vLLM in a Lightning Studio venv (no container image)"),
        "container_digest": metric("container_digest", None, "not applicable: no container image on Lightning Studio"),
        "gpu_provider": LIGHTNING_PROVIDER, "gpu_type": "NVIDIA L40S 48GB (Lightning lit-l40s-1 = AWS g6e.4xlarge)", "gpu_count": 1,
        "tensor_parallel": 1, "precision": "bfloat16", "max_model_len": 4096,
        "attention_backend": metric("attention_backend", backend_m.group(1).strip() if backend_m else None, "no attention-backend line matched in the vLLM server log"),
        "reasoning_parser": cfg["reasoning_parser"], "reasoning_mode": cfg["reasoning_mode"],
        "chat_template_source": cfg["chat_template_source"], "stop_behavior": cfg["stop_behavior"],
        "started_at_utc": started, "finished_at_utc": finished,
        "cold_start_seconds": metric("cold_start_seconds", result.get("cold_start_seconds"), "server never became ready"),
        "load_seconds": metric("load_seconds", float(load_m.group(1)) if load_m else None, "no model-load duration line matched in the vLLM server log"),
        "download_seconds": result.get("download_seconds"),
        "peak_gpu_memory_bytes": metric("peak_gpu_memory_bytes", None if peak is None else peak * 1024 * 1024, "no nvidia-smi samples captured"),
        "steady_gpu_memory_bytes": metric("steady_gpu_memory_bytes", None if steady is None else steady * 1024 * 1024, "server never reached steady state"),
        "smoke_prompts": [{"smoke_id": s["smoke_id"], "purpose": s["purpose"], "messages": [{"role": "user", "content": s["user"]}],
                           "expected": s["expected"]} for s in CONSTS.SMOKES],
        "smoke_protocol": LOCKED_PROTOCOL.protocol_document(),
        "generation_config": result.get("generation_config_sent") or {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": cfg["smoke_max_tokens"]},
        "smoke_outputs": outputs,
        "latency_seconds": metric("latency_seconds", None if not smokes else round(sum(s.get("latency_seconds", 0) for s in smokes), 4), "no smoke request completed"),
        "ttft_seconds": metric("ttft_seconds", first.get("ttft_seconds"), "no streamed first token observed"),
        "generated_tokens": metric("generated_tokens", total_tokens, "no usage data returned"),
        "tokens_per_second": metric("tokens_per_second", None if tps is None else round(tps, 2), "tiny-smoke metric only; not a performance claim"),
        "technical_serving_status": technical, "financial_preflight_status": "PASSED", "financial_acceptance_status": financial,
        "owner_billed_delta_usd": str(owner_delta), "runtime_qualification_status": runtime, "capability_status": "UNPROVEN",
        "cleanup_status": attempt["cleanup_result"], "live_resources_after_cleanup": fin["live_gpu_machines_after"],
        "raw_log_artifact": log_path.name, "raw_log_sha256": log_sha,
        "notes": "Runtime-compatibility evidence only. Capability is UNPROVEN: no benchmark, Genesis eval item, or holdout was run. Metrics come from tiny smoke requests. Generated output was treated as data and never executed. Executed on Lightning AI with complimentary credits (migrated from Modal; earlier Modal attempt preserved in attempts).",
        "attempts": None,  # filled by caller (history preserved)
        "identity_verification": ident, "financial_evidence": {"provider": LIGHTNING_PROVIDER, "see": "lightning_financial"},
        "lightning_financial": lf, "generated_output_executed": False,
        "unobservable_reasons": {**unobservable, **({"reasoning_parser": "not applicable: non-reasoning model with no reasoning parser"} if cfg["reasoning_parser"] is None else {})},
        "versions": vers, "server_argv_sanitized": result.get("server_argv_sanitized"), "server_exit_code": result.get("server_exit_code"),
        "orphan_vllm_processes_after_shutdown": result.get("orphan_vllm_processes_after_shutdown"),
        "gpu_memory_used_mib_before_after": [result.get("gpu_memory_used_mib_before"), result.get("gpu_memory_used_mib_after")],
        "health_status": result.get("health_status"), "version_endpoint": result.get("version_endpoint"),
    }


def cmd_run(control_key: str) -> int:
    from lightning_sdk import Machine

    cfg = CONTROLS[control_key]
    tag = cfg["tag"]
    art, state, pre_path, _ = preflight(control_key, purpose="run")
    attempt_no = art["attempt_number"]
    pre_sha = write_json(pre_path, art)
    print(json.dumps({"gate": art["gate_decision"], "preflight": pre_path.name}, indent=2))
    if not art["gate_decision"]["allowed"]:
        print("FINANCIAL GATE BLOCKED -- NO GPU STARTED")
        return 3

    st = _studio()
    if not studio_running_on_cpu(st):
        print("Studio is not Running on CPU; refusing to start a GPU run")
        return 2
    out, code = sh(st, f"cat {WORK}/stage_{control_key}.json", allow_fail=True)
    stage = json.loads(out) if code == 0 else None
    if not (stage and stage.get("staging_verified") is True):
        print(f"model {control_key} is not staged and verified on the CPU Studio; refusing to spend GPU time")
        return 2
    sh(st, f"test -x {REMOTE_PY}")
    runner_sha = push_runner(st)

    credits_before = Decimal(state["credits_available"])
    before_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_LIGHTNING_ATTEMPT{attempt_no}_CREDITS_BEFORE_{DATE_TAG}.json"
    before_sha = write_json(before_path, {"evidence_type": "LIGHTNING_CREDITS_BEFORE_GPU", "captured_at_utc": state["captured_at_utc"],
                                          "credits": state["credits_available"], "project_credits": state["project_credits"],
                                          "balance_limit": state["balance_limit"], "owner_charge_usd": "0",
                                          "owner_charge_evidence": {"plan": state["plan"], "subscription_amount_usd": state["subscription_amount_usd"],
                                                                    "card_last4_present": state["card_last4_present"], "card_verified": state["card_verified"],
                                                                    "stripe_managed": state["stripe_managed"]}})
    rate = Decimal(str(state["machine"]["rate_credits_per_hour"]))
    out_json = f"{WORK}/result_{control_key}_attempt{attempt_no}.json"
    started, t_start = _now(), time.time()
    outcome, reason, result, error_text = "HARNESS_FAILURE", "unset", None, None
    gpu_ready_s = None
    try:
        st.switch_machine(getattr(Machine, GPU_MACHINE_NAME))   # blocking until provisioned; the meter runs from here
        gpu_ready_s = round(time.time() - t_start, 1)
        m = st.machine
        if m is None or getattr(m, "family", "") != GPU_MACHINE_NAME:
            raise RuntimeError(f"Studio is on {None if m is None else m.name}, not {GPU_MACHINE_NAME}")
        sh(st, f"rm -f {out_json}; cd {WORK} && nohup python runner.py watchdog --seconds {WATCHDOG_SECONDS} > watchdog.out 2>&1 &")
        sh(st, f"cd {WORK} && nohup {REMOTE_PY} runner.py serve --control {control_key} --out {out_json} --deadline 420 > serve_{control_key}.out 2>&1 &")
        done = False
        while time.time() - t_start < HARD_CAP_SECONDS - 45:
            time.sleep(POLL_SECONDS)
            o, _ = sh(st, f"test -f {out_json} && echo YES || echo NO", allow_fail=True)
            if o.strip().endswith("YES"):
                done = True
                break
        if done:
            local_json = EVIDENCE_DIR / f".tmp_{control_key}_result.json"
            st.download_file(f"p4420/result_{control_key}_attempt{attempt_no}.json", str(local_json))
            result = json.loads(local_json.read_text())
            local_json.unlink()
        else:
            outcome, reason = "ABORTED_FINANCIAL_GUARD", f"hard runtime cap reached ({HARD_CAP_SECONDS}s) before a result was written"
    except Exception as e:  # noqa: BLE001
        error_text = f"{type(e).__name__}: {str(e)[:400]}"
        reason = error_text
    finally:
        cleanup_ev = force_cpu_and_verify(st)
    t_end = time.time()
    finished = _now()
    meter = meter_proof()

    tech_ok = bool(result and not result.get("error") and result.get("server_ready") and len(result.get("smoke_results", [])) == 3
                   and all(s.get("http_status") == 200 and s.get("content") and not s.get("error") for s in result["smoke_results"])
                   and result.get("orphan_vllm_processes_after_shutdown") == 0)
    if error_text is None and outcome != "ABORTED_FINANCIAL_GUARD":
        if result is not None and (result.get("server_argv_sanitized") or result.get("error")):
            outcome = "TECHNICAL_SUCCESS" if tech_ok else "TECHNICAL_FAILURE"
            reason = "server ready, 3 smoke requests HTTP 200 with non-empty content, clean shutdown" if tech_ok else (result.get("error") or "smoke/teardown criteria not met")
        else:
            outcome, reason = "HARNESS_FAILURE", "no usable result JSON returned"
    valid_runtime = bool(result and result.get("server_argv_sanitized") and not error_text and outcome != "ABORTED_FINANCIAL_GUARD")

    credits_after = Decimal(meter["final_credits"]) if meter["final_credits"] is not None else None
    window_s = round(t_end - t_start, 1)
    observed = None if credits_after is None else credits_before - credits_after
    after_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_LIGHTNING_ATTEMPT{attempt_no}_CREDITS_AFTER_{DATE_TAG}.json"
    c = _client()
    sub_after = c.billing_service_get_billing_subscription(org_id=ORG_ID).to_dict()
    after_sha = write_json(after_path, {"evidence_type": "LIGHTNING_CREDITS_AFTER_GPU", "captured_at_utc": _now(),
                                        "credits": None if credits_after is None else str(credits_after), "meter": meter, "cleanup": cleanup_ev,
                                        "owner_charge_usd": "0" if not (sub_after.get("card_last4") or sub_after.get("card_verified")) else "UNKNOWN",
                                        "owner_charge_evidence": {"subscription_amount_usd": sub_after.get("amount"), "card_last4_present": bool(sub_after.get("card_last4")),
                                                                  "card_verified": sub_after.get("card_verified")}})
    owner_after = Decimal(0) if not (sub_after.get("card_last4") or sub_after.get("card_verified")) and (credits_after is not None and credits_after >= 0) else Decimal("1")
    fin = {
        "plan": str(state["plan"]).upper(), "payment_method_present": bool(sub_after.get("card_last4") or sub_after.get("card_verified")),
        "machine_slug": state["machine"]["slug_multi_cloud"], "machine_rate_credits_per_hour": str(rate),
        "gpu_runtime_seconds": window_s, "gpu_ready_after_seconds": gpu_ready_s,
        "credits_before": str(credits_before), "credits_after": None if credits_after is None else str(credits_after),
        "credit_delta": None if observed is None else str(observed),
        "expected_credit_cost": str((rate * Decimal(str(window_s)) / Decimal(3600)).quantize(Decimal("0.0001"))),
        "observed_credit_cost": None if observed is None else str(observed),
        "owner_charge_before_usd": "0", "owner_charge_after_usd": str(owner_after), "owner_cash_delta_usd": str(owner_after),
        "balance_limit": state["balance_limit"], "credit_meter_stopped": meter["stopped"], "hard_runtime_cap_seconds": HARD_CAP_SECONDS,
        "watchdog_seconds": WATCHDOG_SECONDS, "per_attempt_credit_cap": "1.00",
        "artifacts": {"preflight": {"artifact": pre_path.name, "sha256": pre_sha},
                      "credits_before": {"artifact": before_path.name, "sha256": before_sha},
                      "credits_after": {"artifact": after_path.name, "sha256": after_sha}},
        "credits_after_nonnegative": credits_after is not None and credits_after >= 0, "live_gpu_machines_after": cleanup_ev["live_gpu_machines"],
        "runner_sha256": runner_sha, "cap_breached": bool(observed is not None and observed > Decimal("1.00")),
    }
    log_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_LIGHTNING_ATTEMPT{attempt_no}_RAW_LOG_{DATE_TAG}.txt"
    log_text = ("\n".join(result.get("events", [])) + "\n\n===== vLLM server log (tail) =====\n" + result.get("server_log", "")) if result else f"NO RESULT RETURNED: {reason}\n"
    log_path.write_text(log_text)
    log_sha = sha_of(log_path)
    cleanup_pass = cleanup_ev["live_gpu_machines"] == 0
    attempt = {
        "attempt_number": attempt_no, "provider": LIGHTNING_PROVIDER, "outcome": outcome, "status": outcome,
        "failure_domain": FAILURE_DOMAIN_BY_OUTCOME[outcome], "valid_runtime_attempt": valid_runtime, "reason": reason,
        "resource_type": f"Lightning Studio machine {GPU_MACHINE_NAME} (1 GPU)", "duration_seconds": window_s,
        "owner_billed_delta_usd": str(owner_after), "credits_consumed": None if observed is None else str(observed),
        "cleanup_result": "PASS" if cleanup_pass else "FAIL", "started_at_utc": started, "finished_at_utc": finished,
        "raw_log_artifact": log_path.name, "raw_log_sha256": log_sha,
    }
    attempts = load_attempts(tag) + [attempt]
    write_json(attempts_path(tag), {"control_name": cfg["control_name"], "attempts": attempts})
    stage_manifest = json.loads((EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_LIGHTNING_STAGE_MANIFEST_{DATE_TAG}.json").read_text()) \
        if (EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_LIGHTNING_STAGE_MANIFEST_{DATE_TAG}.json").is_file() else stage
    record = build_lightning_record(control_key, result, attempt_no, attempt, fin, log_path, log_sha, started, finished, stage_manifest)
    record["attempts"] = attempts
    validation_error = None
    try:
        validate_control_runtime_record(record, evidence_root=EVIDENCE_DIR)
    except Exception as e:  # noqa: BLE001
        validation_error = f"{type(e).__name__}: {e}"
        record["validator_note"] = f"record FAILED its own validator: {validation_error}"
    write_json(record_path(tag), record)
    print(json.dumps({k: record[k] for k in ("technical_serving_status", "financial_acceptance_status", "owner_billed_delta_usd",
                                              "runtime_qualification_status", "cleanup_status", "live_resources_after_cleanup")}, indent=2))
    print(json.dumps({"credits_before": str(credits_before), "credits_after": fin["credits_after"], "observed_credit_cost": fin["observed_credit_cost"],
                      "window_s": window_s, "meter_stopped": meter["stopped"], "cap_breached": fin["cap_breached"]}, indent=2))
    print("validator:", validation_error or "OK")
    if fin["cap_breached"] or not meter["stopped"] or not cleanup_pass:
        print("STOP FOR REVIEW: per-attempt credit cap breached, meter not proven stopped, or cleanup failed")
        return 4
    return 0 if record["runtime_qualification_status"] == "RUNTIME_QUALIFIED" and not validation_error else 1


def cmd_preflight(control_key: str) -> int:
    art, state, path, _ = preflight(control_key, purpose="preflight")
    write_json(path, art)
    print(json.dumps({"gate": art["gate_decision"], "artifact": path.name, "credits": state["credits_available"],
                      "plan": state["plan"], "payment_method_present": state["payment_method_present"],
                      "live_gpu_machines": state["live_gpu_machines"]}, indent=2))
    return 0 if art["gate_decision"]["allowed"] else 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=("preflight", "stage-env", "stage-model", "verify-idle", "run", "cleanup"))
    ap.add_argument("--control", choices=CONTROL_KEYS)
    a = ap.parse_args()
    if a.mode in ("preflight", "stage-model", "run") and not a.control:
        ap.error("--control is required for this mode")
    if a.mode == "preflight":
        return cmd_preflight(a.control)
    if a.mode == "stage-env":
        return cmd_stage_env()
    if a.mode == "stage-model":
        return cmd_stage_model(a.control)
    if a.mode == "verify-idle":
        return cmd_verify_idle()
    if a.mode == "cleanup":
        return cmd_cleanup()
    return cmd_run(a.control)


if __name__ == "__main__":
    sys.exit(main())
