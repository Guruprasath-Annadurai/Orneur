"""
Phase 21B.4.20 -- control runtime qualification on razorBridge (operator side).

Owner cash is EUR 0 / INR 0: only the EUR 10 promotional signup credit is used; no card, no purchase, no top-up.
A razorBridge blade is started and stopped ONLY in the web app (the CLI/API cannot), so the two billing-relevant
clicks -- Start and Stop -- are done by the operator/agent in the owner's logged-in browser. This script does everything
in between over SSH (the blade password is read from the environment and never written to disk) and everything after:

  gate-artifact  write the account-side gate evidence (values read from the logged-in web app) + evaluate the gate
  run            SSH into the running blade: probe, stage vLLM + the pinned model, serve + smoke, fetch results.
                 A wall-clock deadline (measured from the Start click) aborts early so the blade can be stopped in time.
  finalize       after the blade is stopped: build the credits before/after artifacts, the validated record and history.

Generated text is data only: never executed, imported, compiled or shelled out. No benchmark, no frontier call.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
RUNNER = REPO_ROOT / "scripts/phase21b_4_20_lightning_runner.py"   # provider-neutral Studio/blade runner (same serving function)
LIGHTNING_CONTROL = REPO_ROOT / "scripts/phase21b_4_20_lightning_control.py"
TMP = Path("/tmp/p4420")

PHASE = "21B.4.20"
DATE_TAG = "2026-09-24"
GPU_SLUG = "gpu-h100x1-80gb"
GPU_LABEL = "NVIDIA H100 80GB (razorBridge gpu-h100x1-80gb)"
RATE_EUR_PER_HOUR = Decimal("4.29")
HARD_CAP_SECONDS = 1200        # 20 min total blade runtime target
ABORT_SECONDS = 1080           # after 18 min no new step starts; the blade must be stopped
PER_ATTEMPT_AUTH_EUR = Decimal("1.50")
REMOTE = "p4420"
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


def _load_lightning_control():
    spec = importlib.util.spec_from_file_location("p21b420_lightning_control_for_rb", LIGHTNING_CONTROL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


from orca.eval.control_runtime_qualification import (  # noqa: E402
    FAILURE_DOMAIN_BY_OUTCOME, RAZORBRIDGE_PROVIDER, razorbridge_gate_decision, to_decimal, validate_control_runtime_record,
)


# ══════════════════════════════════════════════════════════════════════════
# gate-artifact (values are READ by the operator from the logged-in web app; nothing here contacts razorBridge)
# ══════════════════════════════════════════════════════════════════════════

def cmd_gate_artifact(a) -> int:
    d = razorbridge_gate_decision(
        balance_eur=a.balance, payment_method_present=False, auto_topup_available=False, owner_payable_eur="0",
        rate_eur_per_hour=a.rate, hard_runtime_cap_seconds=HARD_CAP_SECONDS, h100_selectable=True,
        prior_positive_owner_cash=_any_positive_owner_cash(), live_blades=a.live_blades)
    art = {
        "evidence_type": "RAZORBRIDGE_ACCOUNT_GATE", "phase": PHASE, "provider": RAZORBRIDGE_PROVIDER, "captured_at_utc": _now(),
        "source": "the owner's logged-in razorBridge web app (Hub), read-only pages, plus the provider's public docs and pricing page",
        "account": {"name": "[redacted]", "email": "[not persisted]", "email_verified": True, "credentials": "[not persisted]"},
        "balance_eur": str(a.balance), "ledger": [{"type": "credit", "source": "grant", "description": "Signup grant", "amount_eur": "10", "balance_after_eur": "10"}],
        "payment_method": {"present": False, "evidence": "no payment-method, card or billing-details section exists in the Account or Credits pages; docs: self-serve purchase is not available"},
        "auto_topup": {"available": False, "evidence": "no top-up, checkout or auto-recharge control exists in the Hub; docs: self-serve purchase not available yet"},
        "owner_payable_eur": "0", "owner_payable_evidence": "prepaid model; the ledger holds only the signup grant; no invoice or debit",
        "gpu_type_selector": {"h100_80gb": {"slug": GPU_SLUG, "rate_eur_per_hour": str(a.rate), "selectable": True},
                              "h200_141gb": {"slug": "gpu-h200x1-141gb", "rate_eur_per_hour": "4.49"},
                              "durations_hours": [1, 2, 4, 8], "default_gpu_preselected_in_form": "RTX 4000 Ada (never submitted)"},
        "h100_live_availability": "NOT SHOWN: the pricing page's availability dots are all neutral; availability is only proven by provisioning, and a failed provisioning is documented as not billed",
        "stop_control": "the Actions column of the GPU Sessions table (docs: Stop); not visible until a session exists -- to be confirmed at launch",
        "billing_granularity": "docs: exact elapsed wall-clock seconds, no rounding, no minimum; the ledger entry is written once when the blade stops",
        "hard_limits": {"source": "docs (account-specific values not visible in the UI)", "concurrent_self_serve_blades": 2, "max_session_hours": 8, "monthly_spend_eur": 50,
                        "balance_teardown": "a running blade is stopped when its accrued cost reaches the balance; no debt"},
        "platform_session_check": "a 1-hour minimum session is checked against the balance up front (4.29 EUR for the H100)",
        "gate_decision": d, "gpu_execution_allowed": bool(d["allowed"]),
        "hard_rules": ["owner cash EUR 0 / INR 0", "no card", "no purchased credit", "no top-up", "one H100 blade at a time", "no model substitution or quantization",
                       "20 minute runtime target, 1.50 EUR per-attempt authorization", "capability stays UNPROVEN"],
    }
    path = EVIDENCE_DIR / f"GENESIS_RAZORBRIDGE_ACCOUNT_GATE_{a.control.upper()}_{DATE_TAG}.json"
    sha = write_json(path, art)
    print(json.dumps({"gate": d, "artifact": path.name, "sha256": sha}, indent=2))
    return 0 if d["allowed"] else 3


def _attempts_path(tag: str) -> Path:
    return EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPTS_{DATE_TAG}.json"


def _load_attempts(tag: str) -> list[dict]:
    p = _attempts_path(tag)
    return json.loads(p.read_text())["attempts"] if p.is_file() else []


def _any_positive_owner_cash() -> bool:
    for tag in ("QWEN3_8B", "MISTRAL_NEMO", "PHI4"):
        for at in _load_attempts(tag):
            if to_decimal(at["owner_billed_delta_usd"], "delta") != 0:
                return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# run: everything on the billed blade, over SSH
# ══════════════════════════════════════════════════════════════════════════

class Blade:
    def __init__(self, host, port, user, password, t_start):
        import paramiko

        self.paramiko, self.t_start = paramiko, t_start
        self.cli = paramiko.SSHClient()
        self.cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())   # blades are ephemeral (documented)
        self.args = dict(hostname=host, port=int(port), username=user, password=password, timeout=20, banner_timeout=30,
                         allow_agent=False, look_for_keys=False)

    def elapsed(self) -> float:
        return time.time() - self.t_start

    def connect(self, wait_s: int) -> None:
        t0, last = time.time(), None
        while time.time() - t0 < wait_s:
            try:
                self.cli.connect(**self.args)
                return
            except Exception as e:  # noqa: BLE001
                last = f"{type(e).__name__}"
                time.sleep(10)
        raise RuntimeError(f"SSH not reachable within {wait_s}s ({last})")

    def sh(self, cmd: str, timeout: int = 120) -> tuple[int, str]:
        _i, o, _e = self.cli.exec_command(cmd + " 2>&1", timeout=timeout)
        out = o.read().decode(errors="replace")
        return o.channel.recv_exit_status(), out

    def put(self, local: Path, remote: str) -> None:
        sftp = self.cli.open_sftp()
        try:
            sftp.put(str(local), remote)
        finally:
            sftp.close()

    def get(self, remote: str, local: Path) -> None:
        sftp = self.cli.open_sftp()
        try:
            sftp.get(remote, str(local))
        finally:
            sftp.close()

    def bg(self, name: str, cmd: str, timeout_s: int) -> bool:
        """Run `cmd` detached; poll marker files; abort at the global deadline. Returns True on success."""
        self.sh(f"cd ~/{REMOTE} && rm -f {name}.done {name}.fail && nohup sh -c '{cmd} > {name}.out 2>&1 && touch {name}.done || touch {name}.fail' >/dev/null 2>&1 &")
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if self.elapsed() > ABORT_SECONDS:
                return False
            _c, o = self.sh(f"ls ~/{REMOTE} | grep -E '^{name}\\.(done|fail)$' || true", timeout=30)
            if f"{name}.done" in o:
                return True
            if f"{name}.fail" in o:
                return False
            time.sleep(10)
        return False


def cmd_run(a) -> int:
    pw = os.environ.get("RB_BLADE_PASSWORD")
    if not pw:
        print("RB_BLADE_PASSWORD is not set")
        return 2
    lc = _load_lightning_control()
    ctrl = lc.CONTROLS[a.control]
    TMP.mkdir(exist_ok=True)
    steps: list[dict] = []
    state = {"control": a.control, "provider": RAZORBRIDGE_PROVIDER, "started_epoch": a.t_start, "steps": steps, "abort": False}

    def mark(name, ok, extra=None):
        steps.append({"step": name, "ok": ok, "elapsed_s": round(time.time() - a.t_start, 1), **(extra or {})})
        print(f"[{steps[-1]['elapsed_s']:7.1f}s] {name}: {'OK' if ok else 'FAIL'}", flush=True)

    b = Blade(a.host, a.port, a.user, pw, a.t_start)
    rc = 1
    try:
        b.connect(min(600, ABORT_SECONDS - int(b.elapsed())))
        mark("ssh_connect", True)
        _c, probe = b.sh("id -un; nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader; python3 --version; "
                         "python3 -m pip --version; python3 -c 'import venv;print(\"venv ok\")'; df -h ~ | tail -1; nproc; free -g | head -2; "
                         "grep -E '^(PRETTY_NAME)' /etc/os-release; (nvcc --version | tail -1) || true", timeout=60)
        state["environment_probe"] = probe.replace(a.user, "<user>")
        mark("environment_probe", True)
        b.sh(f"mkdir -p ~/{REMOTE}")
        b.put(RUNNER, f"{REMOTE}/runner.py")
        _c, o = b.sh(f"sha256sum ~/{REMOTE}/runner.py | cut -d' ' -f1")
        state["runner_sha256"] = o.strip().splitlines()[-1]
        ok = state["runner_sha256"] == sha_of(RUNNER)
        mark("runner_uploaded", ok)
        if not ok:
            raise RuntimeError("runner hash mismatch")
        ok = b.bg("stage_env", "python3 runner.py stage-env", 660)
        mark("stage_env", ok)
        if not ok:
            raise RuntimeError("stage-env failed or deadline")
        ok = b.bg("stage_model", f"./venv/bin/python runner.py stage-model --control {a.control}", 480)
        mark("stage_model", ok)
        if not ok:
            raise RuntimeError("stage-model failed or deadline")
        out = f"result_{a.control}.json"
        ok = b.bg("serve", f"./venv/bin/python runner.py serve --control {a.control} --out {out} --deadline 420", max(60, int(ABORT_SECONDS - b.elapsed())))
        mark("serve_and_smoke", ok)
        for remote, local in ((out, f"rb_{a.control}_result.json"), (f"stage_{a.control}.json", f"rb_{a.control}_stage.json"),
                              ("stage_env.json", f"rb_{a.control}_stage_env.json")):
            try:
                b.get(f"{REMOTE}/{remote}", TMP / local)
            except Exception:  # noqa: BLE001
                pass
        for name in ("stage_env", "stage_model", "serve"):
            _c, tail = b.sh(f"tail -c 1500 ~/{REMOTE}/{name}.out", timeout=30)
            state.setdefault("step_output_tails", {})[name] = tail
        rc = 0 if ok else 4
    except Exception as e:  # noqa: BLE001
        state["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        state["abort"] = b.elapsed() > ABORT_SECONDS
        mark("exception", False, {"error": state["error"]})
        rc = 5
    finally:
        state["total_elapsed_s"] = round(time.time() - a.t_start, 1)
        (TMP / f"rb_run_{a.control}.json").write_text(json.dumps(state, indent=2))
        try:
            b.cli.close()
        except Exception:  # noqa: BLE001
            pass
    print(f"RUN DONE rc={rc} elapsed={state['total_elapsed_s']}s -- STOP THE BLADE IN THE WEB APP NOW")
    return rc


# ══════════════════════════════════════════════════════════════════════════
# finalize (offline; after the blade is stopped and the ledger read)
# ══════════════════════════════════════════════════════════════════════════

def cmd_finalize(a) -> int:
    lc = _load_lightning_control()
    cfg = lc.CONTROLS[a.control]
    tag = cfg["tag"]
    run = json.loads((TMP / f"rb_run_{a.control}.json").read_text())
    rp = TMP / f"rb_{a.control}_result.json"
    result = json.loads(rp.read_text()) if rp.is_file() else None
    sp = TMP / f"rb_{a.control}_stage.json"
    stage = json.loads(sp.read_text()) if sp.is_file() else None
    attempts = _load_attempts(tag)
    n = len(attempts) + 1
    gate = EVIDENCE_DIR / f"GENESIS_RAZORBRIDGE_ACCOUNT_GATE_{a.control.upper()}_{DATE_TAG}.json"
    gate_sha = sha_of(gate)
    before, after = to_decimal(a.credits_before, "credits_before"), to_decimal(a.credits_after, "credits_after")
    delta = before - after
    bp = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RAZORBRIDGE_ATTEMPT{n}_CREDITS_BEFORE_{DATE_TAG}.json"
    ap = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RAZORBRIDGE_ATTEMPT{n}_CREDITS_AFTER_{DATE_TAG}.json"
    b_sha = write_json(bp, {"evidence_type": "RAZORBRIDGE_CREDITS_BEFORE_GPU", "observed_at_utc": a.before_observed_utc, "credits_eur": str(before),
                            "owner_payable_eur": "0", "source": "web app Credits page (ledger and balance)"})
    a_sha = write_json(ap, {"evidence_type": "RAZORBRIDGE_CREDITS_AFTER_GPU", "observed_at_utc": a.after_observed_utc, "credits_eur": str(after),
                            "ledger_debit_note": a.ledger_note, "blade_status_after": a.blade_status_after, "live_blades_after": a.live_blades_after,
                            "owner_payable_eur": "0", "source": "web app Credits page and GPU Sessions table"})
    tech_ok = bool(result and not result.get("error") and result.get("server_ready") and len(result.get("smoke_results", [])) == 3
                   and all(s.get("http_status") == 200 and s.get("content") and not s.get("error") for s in result["smoke_results"])
                   and result.get("orphan_vllm_processes_after_shutdown") == 0)
    aborted = bool(run.get("abort"))
    if aborted:
        outcome, reason = "ABORTED_FINANCIAL_GUARD", "the wall-clock runtime deadline was reached before a result was written"
    elif result is not None and (result.get("server_argv_sanitized") or result.get("error")):
        outcome = "TECHNICAL_SUCCESS" if tech_ok else "TECHNICAL_FAILURE"
        reason = "server ready, 3 smoke requests HTTP 200 with non-empty content, clean shutdown" if tech_ok else (result.get("error") or "smoke/teardown criteria not met")
    else:
        outcome, reason = "HARNESS_FAILURE", run.get("error") or "no usable result JSON returned (a setup step failed before the server started)"
    valid_runtime = bool(result and result.get("server_argv_sanitized") and outcome in ("TECHNICAL_SUCCESS", "TECHNICAL_FAILURE"))
    expected = (RATE_EUR_PER_HOUR * Decimal(str(a.blade_runtime_seconds)) / Decimal(3600)).quantize(Decimal("0.0001"))
    meter_stopped = bool(a.meter_stopped)
    cleanup_pass = a.live_blades_after == 0 and meter_stopped
    fin = {"owner_cash_delta_usd": "0", "credits_after_nonnegative": after >= 0, "live_gpu_machines_after": a.live_blades_after}
    log_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RAZORBRIDGE_ATTEMPT{n}_RAW_LOG_{DATE_TAG}.txt"
    log_text = ("\n".join(result.get("events", [])) + "\n\n===== vLLM server log (tail) =====\n" + result.get("server_log", "")) if result else f"NO RESULT RETURNED: {reason}\n"
    log_text += "\n\n===== run steps =====\n" + json.dumps(run.get("steps"), indent=1) + "\n\n===== environment probe =====\n" + str(run.get("environment_probe"))
    log_path.write_text(log_text)
    log_sha = sha_of(log_path)
    attempt = {"attempt_number": n, "provider": RAZORBRIDGE_PROVIDER, "outcome": outcome, "status": outcome, "failure_domain": FAILURE_DOMAIN_BY_OUTCOME[outcome],
               "valid_runtime_attempt": valid_runtime, "reason": reason, "resource_type": f"razorBridge self-serve blade {GPU_SLUG}",
               "duration_seconds": a.blade_runtime_seconds, "owner_billed_delta_usd": "0", "credits_consumed": str(delta),
               "cleanup_result": "PASS" if cleanup_pass else "FAIL", "started_at_utc": a.started_utc, "finished_at_utc": a.stopped_utc,
               "raw_log_artifact": log_path.name, "raw_log_sha256": log_sha}
    attempts = attempts + [attempt]
    write_json(_attempts_path(tag), {"control_name": cfg["control_name"], "attempts": attempts})
    record = lc.build_lightning_record(a.control, result, n, attempt, fin, log_path, log_sha, a.started_utc, a.stopped_utc, stage)
    record.pop("lightning_financial", None)
    env = (run.get("environment_probe") or "").splitlines()
    record.update({
        "gpu_provider": RAZORBRIDGE_PROVIDER, "gpu_type": GPU_LABEL,
        "runtime_name": "vLLM (pip venv on a razorBridge GPU blade, OpenAI-compatible server)",
        "attempts": attempts,
        "financial_evidence": {"provider": RAZORBRIDGE_PROVIDER, "see": "razorbridge_financial"},
        "notes": "Runtime-compatibility evidence only. Capability is UNPROVEN: no benchmark, Genesis eval item, or holdout was run. Metrics come from tiny smoke requests. "
                 "Generated output was treated as data and never executed. Executed on razorBridge with the promotional signup credit (migrated from Modal, Lightning and Hugging Face; earlier attempts are preserved in attempts).",
        "razorbridge_financial": {
            "payment_method_present": False, "auto_topup_available": False, "gpu_type": GPU_LABEL, "gpu_rate_eur_per_hour": str(RATE_EUR_PER_HOUR),
            "blade_runtime_seconds": a.blade_runtime_seconds, "credits_before_eur": str(before), "credits_after_eur": str(after), "credit_delta_eur": str(delta),
            "expected_max_charge_eur": str(expected), "observed_charge_eur": str(delta), "owner_payable_before_eur": "0", "owner_payable_after_eur": "0",
            "owner_cash_delta_eur": "0", "credit_meter_stopped": meter_stopped, "hard_runtime_cap_seconds": HARD_CAP_SECONDS,
            "per_attempt_authorization_eur": str(PER_ATTEMPT_AUTH_EUR), "live_blades_after": a.live_blades_after,
            "cap_breached": delta > PER_ATTEMPT_AUTH_EUR, "runner_sha256": run.get("runner_sha256"),
            "artifacts": {"account_gate": {"artifact": gate.name, "sha256": gate_sha}, "credits_before": {"artifact": bp.name, "sha256": b_sha},
                          "credits_after": {"artifact": ap.name, "sha256": a_sha}}},
        "environment_probe_summary": [l for l in env if not l.startswith("uid=")][:12],
    })
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
    print(json.dumps({"credits_before": str(before), "credits_after": str(after), "credit_consumed_eur": str(delta), "expected_max_charge": str(expected),
                      "blade_runtime_seconds": a.blade_runtime_seconds, "cap_breached": delta > PER_ATTEMPT_AUTH_EUR}, indent=2))
    print("validator:", validation_error or "OK")
    return 0 if record["runtime_qualification_status"] == "RUNTIME_QUALIFIED" and not validation_error else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    g = sub.add_parser("gate-artifact")
    g.add_argument("--control", required=True, choices=CONTROL_KEYS)
    g.add_argument("--balance", required=True)
    g.add_argument("--rate", default=str(RATE_EUR_PER_HOUR))
    g.add_argument("--live-blades", type=int, default=0)
    r = sub.add_parser("run")
    r.add_argument("--control", required=True, choices=CONTROL_KEYS)
    r.add_argument("--host", required=True)
    r.add_argument("--port", required=True)
    r.add_argument("--user", required=True)
    r.add_argument("--t-start", type=float, default=None, help="epoch seconds of the Start click (default: now)")
    f = sub.add_parser("finalize")
    f.add_argument("--control", required=True, choices=CONTROL_KEYS)
    for name in ("credits-before", "credits-after", "before-observed-utc", "after-observed-utc", "started-utc", "stopped-utc", "ledger-note", "blade-status-after"):
        f.add_argument("--" + name, required=True)
    f.add_argument("--blade-runtime-seconds", type=float, required=True)
    f.add_argument("--live-blades-after", type=int, required=True)
    f.add_argument("--meter-stopped", type=lambda s: s.lower() == "true", required=True)
    a = ap.parse_args()
    if a.mode == "gate-artifact":
        return cmd_gate_artifact(a)
    if a.mode == "run":
        a.t_start = a.t_start or time.time()
        return cmd_run(a)
    return cmd_finalize(a)


if __name__ == "__main__":
    sys.exit(main())
