"""
Phase 21B.4.20 -- Genesis CONTROL runtime qualification harness + orchestrator.

Qualifies the ACTUAL serving path of the three locked controls (Qwen3-8B,
Mistral-Nemo-Instruct-2407, Phi-4) on Modal GPU as TRUSTED INFERENCE
INFRASTRUCTURE ONLY: a `modal.Function` (never a Modal Sandbox) starts an
official vLLM OpenAI-compatible server for the exact pinned revision, sends
three tiny deterministic smoke prompts, records runtime/identity/latency
evidence, tears the server down, and returns. Generated text is treated
purely as DATA -- it is never executed, evaluated, compiled, imported, sent
to a code runner, or used to build a shell command. No benchmark or Genesis
eval item is run. Capability stays UNPROVEN.

Financial HARD GATE (owner constraint: zero out-of-pocket cash):
  * a FRESH live `modal billing summary --json` is read immediately before
    any allocation and `financial_gate_decision()` must allow the run;
  * worst-case job cost (published rate x margin x hard ceiling) must fit
    under known remaining credit minus a fixed safety reserve;
  * live billing is POLLED during the run and the job is proactively
    cancelled if billed cost rises, the per-job budget cap is exceeded, or
    the projected runway is breached -- a wall-clock ceiling alone is never
    trusted (Phase 21B.4.13 GLM incident);
  * acceptance requires `billed_after == billed_before` (delta exactly 0);
  * this script NEVER retries automatically and refuses to start any run
    if any earlier attempt in this phase saw positive billing.

Usage (from repo root, inside the project venv):
    python scripts/phase21b_4_20_control_runtime_qualification.py --control qwen3_8b --mode preflight
    python scripts/phase21b_4_20_control_runtime_qualification.py --control qwen3_8b --mode run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import modal

# ── pinned runtime (same digest proven for Mistral Small 4 in Phase 21B.4.12.3) ──
VLLM_IMAGE_TAG = "vllm/vllm-openai:v0.29.0"
VLLM_IMAGE_DIGEST = "sha256:082ca6f035279109041ffd3fe0695cb568b29bc580b35c4f297a66a08b216c1b"
VLLM_IMAGE_REF = f"vllm/vllm-openai@{VLLM_IMAGE_DIGEST}"

GPU_TYPE = "A100-80GB"
GPU_COUNT = 1
HARD_CEILING_SECONDS = 20 * 60          # modal kills the function here
READY_DEADLINE_SECONDS = 15 * 60        # give up waiting for server readiness
MAX_MODEL_LEN = 4096
GPU_MEMORY_UTILIZATION = 0.90

# ── financial constants ──
CREDIT_POOL_USD = "30.00"               # owner-figure-derived (credits ceiling observed = 30.00); see preflight evidence
RESERVE_USD = "5.00"                    # fixed safety reserve, never planned against
COST_MARGIN = Decimal("1.5")            # covers CPU/memory/unknown metering on top of the GPU rate
POLL_INTERVAL_SECONDS = 30
SETTLE_POLL_SECONDS = 45
SETTLE_MAX_SECONDS = 900
DISCREPANCY_ARTIFACT = "GENESIS_BILLING_DISCREPANCY_OBSERVATION_2026-09-24.json"

PHASE = "21B.4.20"
DATE_TAG = "2026-09-24"
REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "docs/orneur/phase-21/evidence"
REGISTRY_PATH = REPO_ROOT / "docs/orneur/phase-21/GENESIS_CANDIDATE_EXECUTION_REGISTRY.json"

CONTROLS = {
    "qwen3_8b": {
        "tag": "QWEN3_8B", "control_name": "Qwen3-8B",
        "extra_args": ["--reasoning-parser", "qwen3"], "reasoning_parser": "qwen3",
        "reasoning_mode": "ENABLED (Qwen3 hybrid-thinking template default; canonical control spec launches with --reasoning-parser qwen3)",
        "smoke_max_tokens": 1024,
        "chat_template_source": "tokenizer_config.json chat_template @ pinned revision (4,168 chars; hybrid thinking, enable_thinking default ON)",
        "stop_behavior": "eos_token <|im_end|>; generation_config eos_token_id [151645, 151643]",
    },
    "mistral_nemo": {
        "tag": "MISTRAL_NEMO", "control_name": "Mistral-Nemo-Instruct-2407",
        "extra_args": ["--tokenizer-mode", "hf", "--config-format", "hf", "--load-format", "safetensors"],
        "reasoning_parser": None, "reasoning_mode": "NOT_APPLICABLE (non-reasoning instruct model)",
        "smoke_max_tokens": 64,
        "chat_template_source": "tokenizer_config.json chat_template @ pinned revision (HF path pinned explicitly via --tokenizer-mode hf; mistral-common path NOT used)",
        "stop_behavior": "eos_token </s>; instruction tokens [INST] [/INST]",
    },
    "phi4": {
        "tag": "PHI4", "control_name": "Phi-4",
        "extra_args": [], "reasoning_parser": None, "reasoning_mode": "NOT_APPLICABLE (base phi-4 instruct, no thinking tags)",
        "smoke_max_tokens": 64,
        "chat_template_source": "tokenizer_config.json chat_template @ pinned revision (462 chars; ChatML-like <|im_start|>role<|im_sep|>content<|im_end|>)",
        "stop_behavior": "eos_token <|im_end|>; generation_config eos_token_id [100257, 100265]",
    },
}

def _load_locked_protocol():
    """Load the ONE canonical locked-smoke protocol (stdlib-only). Sibling copy first (container / Studio), repo path otherwise."""
    import importlib.util as _ilu
    here = Path(__file__).resolve()
    for cand in (here.with_name("locked_smoke_protocol.py"), here.parents[1] / "orca" / "eval" / "locked_smoke_protocol.py"):
        if cand.is_file():
            spec = _ilu.spec_from_file_location("locked_smoke_protocol", cand)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)          # verifies the pinned protocol fingerprint on import (fails closed on drift)
            return mod
    raise RuntimeError("locked_smoke_protocol.py not found next to this script or in the repository")


LOCKED_PROTOCOL = _load_locked_protocol()
SMOKES = LOCKED_PROTOCOL.runner_smokes()      # no hand-written smoke string lives in this file


def _meets_acceptance(rule: dict, content) -> bool:
    """Same semantics as the canonical protocol's `acceptance` (a test cross-checks them): strip whitespace, then exact text or exact JSON object."""
    text = (content or "").strip()
    if rule["kind"] == "exact_text":
        return text == rule["expected"]
    try:
        parsed = json.loads(text)
    except ValueError:
        return False
    return isinstance(parsed, dict) and parsed == rule["expected"]

image = (
    modal.Image.from_registry(
        VLLM_IMAGE_REF,
        add_python=None,
        setup_dockerfile_commands=["RUN which python || ln -s $(which python3) /usr/local/bin/python"],
    )
    .entrypoint([])
)
app = modal.App("orneur-p21b420-control-runtime-qualification")


# ══════════════════════════════════════════════════════════════════════════
# In-container function: TRUSTED inference only. Generated text is data.
# ══════════════════════════════════════════════════════════════════════════
@app.function(image=image, gpu=f"{GPU_TYPE}:{GPU_COUNT}", timeout=HARD_CEILING_SECONDS)
def serve_and_smoke(cfg: dict) -> dict:
    import importlib.metadata as md
    import json as _json
    import os
    import re as _re
    import signal
    import statistics
    import subprocess as sp
    import threading
    import time as _time
    import urllib.request

    t0 = _time.time()
    events: list[str] = []

    def ev(msg: str) -> None:
        events.append(f"[{_time.time() - t0:8.2f}s] {msg}")

    result: dict = {"events": events, "error": None}
    server = None
    stop_sampling = threading.Event()
    mem_samples_mib: list[int] = []
    log_path = "/tmp/vllm_server.log"

    def smi_query() -> tuple[str, int]:
        out = sp.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total", "--format=csv,noheader,nounits"],
                     capture_output=True, text=True)
        used = 0
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3 and parts[2].isdigit():
                used += int(parts[2])
        return out.stdout.strip(), used

    def sampler() -> None:
        while not stop_sampling.is_set():
            try:
                mem_samples_mib.append(smi_query()[1])
            except Exception:
                pass
            stop_sampling.wait(2.0)

    def http(method: str, path: str, body: dict | None = None, timeout: float = 120.0):
        req = urllib.request.Request(
            f"http://127.0.0.1:8000{path}", method=method,
            data=None if body is None else _json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(req, timeout=timeout)

    try:
        # ── environment / version capture (no env dump, no secrets) ──
        smi0, used0 = smi_query()
        result["nvidia_smi_before"] = smi0
        result["gpu_memory_used_mib_before"] = used0
        vers = {}
        for pkg in ("vllm", "torch", "transformers", "tokenizers", "safetensors", "huggingface_hub"):
            try:
                vers[pkg] = md.version(pkg)
            except Exception as e:  # noqa: BLE001
                vers[pkg] = f"UNAVAILABLE ({type(e).__name__})"
        try:
            import torch  # type: ignore
            vers["torch_cuda"] = torch.version.cuda
        except Exception as e:  # noqa: BLE001
            vers["torch_cuda"] = f"UNAVAILABLE ({type(e).__name__})"
        result["versions"] = vers
        ev(f"versions: {vers}")

        os.environ.update({"VLLM_NO_USAGE_STATS": "1", "DO_NOT_TRACK": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
        threading.Thread(target=sampler, daemon=True).start()

        # ── exact-revision pre-download (no consolidated duplicates, no secrets) ──
        from huggingface_hub import snapshot_download  # type: ignore

        t_dl = _time.time()
        snap = snapshot_download(
            repo_id=cfg["model_id"], revision=cfg["revision"],
            ignore_patterns=["consolidated*", "original/*", "*.pth", "*.bin", "*.gguf", "*.msgpack", "*.h5", "*.onnx"],
        )
        result["download_seconds"] = round(_time.time() - t_dl, 2)
        result["snapshot_path"] = snap
        ev(f"snapshot_download done in {result['download_seconds']}s -> {snap}")

        snap_dir_name = os.path.basename(snap.rstrip("/"))
        hub_root = os.path.dirname(snap.rstrip("/"))
        result["snapshot_dir_names"] = sorted(os.listdir(hub_root)) if os.path.isdir(hub_root) else []
        shard_bytes = 0
        shard_files = []
        for fn in sorted(os.listdir(snap)):
            if _re.match(r"^model-\d+-of-\d+\.safetensors$", fn):
                size = os.path.getsize(os.path.realpath(os.path.join(snap, fn)))
                shard_bytes += size
                shard_files.append({"filename": fn, "bytes": size})
        result["snapshot_dir_name"] = snap_dir_name
        result["weight_shard_files"] = shard_files
        result["weight_bytes_observed"] = shard_bytes
        ev(f"weight shards observed: {len(shard_files)} files, {shard_bytes} bytes; snapshot dir = {snap_dir_name}")

        # ── start the server (constant argv; no model output ever reaches a command line) ──
        cmd = [
            "python3", "-m", "vllm.entrypoints.openai.api_server",
            "--model", snap, "--served-model-name", cfg["model_id"],
            "--dtype", "bfloat16", "--max-model-len", str(cfg["max_model_len"]),
            "--gpu-memory-utilization", str(cfg["gpu_memory_utilization"]),
            "--host", "127.0.0.1", "--port", "8000", "--seed", "0",
        ] + list(cfg["extra_args"])
        result["server_argv_sanitized"] = [c if c != snap else "<local pinned-revision snapshot dir>" for c in cmd]
        t_server = _time.time()
        logf = open(log_path, "wb")
        server = sp.Popen(cmd, stdout=logf, stderr=sp.STDOUT, start_new_session=True)
        ev(f"vLLM server process started (pid {server.pid})")

        ready = False
        models_body = None
        deadline = t_server + cfg["ready_deadline_seconds"]
        while _time.time() < deadline:
            if server.poll() is not None:
                ev(f"server exited early with code {server.returncode}")
                break
            try:
                with http("GET", "/v1/models", timeout=5) as r:
                    if r.status == 200:
                        models_body = _json.loads(r.read().decode())
                        ready = True
                        break
            except Exception:
                pass
            _time.sleep(3)
        result["server_ready"] = ready
        result["cold_start_seconds"] = round(_time.time() - t_server, 2) if ready else None
        result["seconds_from_function_start_to_ready"] = round(_time.time() - t0, 2) if ready else None
        if not ready:
            result["error"] = "server did not become ready"
            return result
        ev(f"server ready after {result['cold_start_seconds']}s")
        result["models_endpoint"] = models_body
        try:
            with http("GET", "/health", timeout=5) as r:
                result["health_status"] = r.status
        except Exception as e:  # noqa: BLE001
            result["health_status"] = f"ERROR {type(e).__name__}"
        try:
            with http("GET", "/version", timeout=5) as r:
                result["version_endpoint"] = _json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            result["version_endpoint"] = f"UNAVAILABLE {type(e).__name__}"

        _time.sleep(5)
        result["steady_gpu_memory_used_mib"] = smi_query()[1]

        # ── three tiny deterministic smoke requests (data only; never executed) ──
        outputs = []
        gen_cfg = {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": cfg["smoke_max_tokens"]}
        result["generation_config_sent"] = gen_cfg
        for smoke in cfg["smokes"]:
            payload = {"model": cfg["model_id"], "messages": [{"role": "user", "content": smoke["user"]}], **gen_cfg}
            t_req = _time.time()
            entry = {"smoke_id": smoke["smoke_id"], "http_status": None, "raw_response": None}
            try:
                if smoke["stream"]:
                    payload = dict(payload, stream=True, stream_options={"include_usage": True})
                    ttft = None
                    content, reasoning, finish, usage = [], [], None, None
                    with http("POST", "/v1/chat/completions", payload, timeout=300) as r:
                        entry["http_status"] = r.status
                        for raw in r:
                            line = raw.decode().strip()
                            if not line.startswith("data:") or line == "data: [DONE]":
                                continue
                            chunk = _json.loads(line[5:].strip())
                            if chunk.get("usage"):
                                usage = chunk["usage"]
                            for ch in chunk.get("choices", []):
                                delta = ch.get("delta", {})
                                piece_c = delta.get("content") or ""
                                piece_r = delta.get("reasoning_content") or delta.get("reasoning") or ""
                                if (piece_c or piece_r) and ttft is None:
                                    ttft = _time.time() - t_req
                                content.append(piece_c)
                                reasoning.append(piece_r)
                                finish = ch.get("finish_reason") or finish
                    entry["ttft_seconds"] = None if ttft is None else round(ttft, 4)
                    entry["raw_response"] = _json.dumps(
                        {"content": "".join(content), "reasoning_content": "".join(reasoning), "finish_reason": finish, "usage": usage},
                        sort_keys=True)
                    entry["content"] = "".join(content)
                    entry["finish_reason"] = finish
                    entry["usage"] = usage
                else:
                    with http("POST", "/v1/chat/completions", payload, timeout=300) as r:
                        entry["http_status"] = r.status
                        body = r.read().decode()
                    entry["raw_response"] = body
                    parsed = _json.loads(body)
                    msg = parsed["choices"][0]["message"]
                    entry["content"] = msg.get("content") or ""
                    entry["finish_reason"] = parsed["choices"][0].get("finish_reason")
                    entry["usage"] = parsed.get("usage")
                    entry["ttft_seconds"] = None
            except Exception as e:  # noqa: BLE001
                entry["error"] = f"{type(e).__name__}: {e}"
            entry["latency_seconds"] = round(_time.time() - t_req, 4)
            entry["matches_expected_exactly"] = _meets_acceptance(smoke["acceptance"], entry.get("content", ""))
            outputs.append(entry)
            ev(f"smoke {smoke['smoke_id']} status={entry['http_status']} latency={entry['latency_seconds']}s")
        result["smoke_results"] = outputs
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        # ── teardown: stop server, verify nothing remains, capture final state ──
        try:
            if server is not None and server.poll() is None:
                os.killpg(os.getpgid(server.pid), signal.SIGTERM)
                try:
                    server.wait(timeout=60)
                except sp.TimeoutExpired:
                    os.killpg(os.getpgid(server.pid), signal.SIGKILL)
                    server.wait(timeout=30)
            result["server_exit_code"] = None if server is None else server.returncode
        except Exception as e:  # noqa: BLE001
            result["teardown_error"] = f"{type(e).__name__}: {e}"
        _time.sleep(3)
        stop_sampling.set()
        pg = sp.run(["pgrep", "-f", "vllm.entrypoints"], capture_output=True, text=True)
        result["orphan_vllm_processes_after_shutdown"] = len([p for p in pg.stdout.split() if p.strip()])
        smi1, used1 = smi_query()
        result["nvidia_smi_after"] = smi1
        result["gpu_memory_used_mib_after"] = used1
        result["peak_gpu_memory_used_mib"] = max(mem_samples_mib) if mem_samples_mib else None
        result["gpu_memory_sample_count"] = len(mem_samples_mib)
        try:
            with open(log_path, "rb") as f:
                raw = f.read()[-1_500_000:]
            result["server_log"] = raw.decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            result["server_log"] = f"LOG UNAVAILABLE: {type(e).__name__}"
        result["function_wall_seconds"] = round(_time.time() - t0, 2)
    return result


# ══════════════════════════════════════════════════════════════════════════
# Local orchestrator (never sees generated text as anything but data)
# ══════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _modal_cli() -> str:
    return str(Path(sys.executable).parent / "modal")


def _cli_json(*args: str) -> object:
    out = subprocess.run([_modal_cli(), *args], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"modal {' '.join(args)} failed: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def billing_summary() -> dict:
    return _cli_json("billing", "summary", "--json")  # type: ignore[return-value]


def write_json(path: Path, data: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def sha_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_attempts(tag: str) -> list[dict]:
    p = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPTS_{DATE_TAG}.json"
    return json.loads(p.read_text())["attempts"] if p.is_file() else []


def any_positive_billing_seen() -> bool:
    for cfg in CONTROLS.values():
        for a in load_attempts(cfg["tag"]):
            if Decimal(str(a["owner_billed_delta_usd"])) != 0:
                return True
    return False


SHORT_NAME = {"qwen3_8b": "QWEN", "mistral_nemo": "MISTRAL", "phi4": "PHI4"}


def settlement_resolved(tag: str, attempt: dict) -> bool:
    """An attempt's settlement is resolved if it was observed in-run OR a later read-only reconciliation artifact for that
    exact attempt reports OBSERVED with zero live resources."""
    if attempt.get("billing_settlement_status") == "OBSERVED":
        return True
    for f in sorted(EVIDENCE_DIR.glob(f"GENESIS_CONTROL_{tag}_ATTEMPT{attempt['attempt_number']}_SETTLEMENT_RECONCILIATION_*.json")):
        r = json.loads(f.read_text())
        if r.get("attempt_number") == attempt["attempt_number"] and r.get("settlement", {}).get("status") == "OBSERVED" \
                and r.get("live_resources") == 0 and r.get("owner_billed_delta_usd") in ("0", "0E-8", "0.0"):
            return True
    return False


def any_unresolved_settlement() -> bool:
    for cfg in CONTROLS.values():
        for a in load_attempts(cfg["tag"]):
            if not settlement_resolved(cfg["tag"], a):
                return True
    return False


def reconcile_attempt(control_key: str, attempt_number: int) -> int:
    """READ-ONLY. Re-queries Modal billing and decides whether a prior attempt's usage is now identifiable in the account
    data. Never starts any resource. Writes a timestamped reconciliation artifact either way."""
    from orca.eval.control_runtime_qualification import assess_settlement, build_financial_reconciliation

    cfg = CONTROLS[control_key]
    tag = cfg["tag"]
    attempts = load_attempts(tag)
    a = next((x for x in attempts if x["attempt_number"] == attempt_number), None)
    if a is None:
        print(f"no attempt {attempt_number} for {control_key}")
        return 2
    base_file = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPT{attempt_number}_BILLING_BEFORE_{DATE_TAG}.json"
    baseline = json.loads(base_file.read_text())["billing_summary"]
    now = billing_summary()
    start = a["started_at_utc"][:10]
    end = (datetime.fromisoformat(start) + timedelta(days=2)).strftime("%Y-%m-%d")
    rows = _cli_json("billing", "report", "--start", start, "--end", end, "--resolution", "h", "--json")
    mine = [r for r in rows if isinstance(r, dict) and r.get("description") == a["modal_app_name"]]  # type: ignore[union-attr]
    visible = sum((Decimal(str(r["cost"])) for r in mine), Decimal(0))
    cleanup = cleanup_snapshot()
    recon = build_financial_reconciliation(baseline, now, credit_pool_usd=CREDIT_POOL_USD, reserve_usd=RESERVE_USD,
                                           max_run_cost_usd="1.25", peak_billed_usd=now["billed_cost"])
    settlement = assess_settlement(recon, run_report_metered_usd=str(visible))
    out = {
        "evidence_type": "ATTEMPT_SETTLEMENT_RECONCILIATION_READ_ONLY", "phase": PHASE, "control_name": cfg["control_name"],
        "attempt_number": attempt_number, "captured_at_utc": _now(), "modal_app_name": a["modal_app_name"],
        "attempt_window_utc": [a["started_at_utc"], a["finished_at_utc"]],
        "baseline_source": base_file.name, "current_billing_summary": now,
        "itemized_rows_for_attempt_app": mine, "itemized_visible_cost_usd": str(visible),
        "itemized_report_range": [start, end], "itemized_rows_total_in_range": len(rows),  # type: ignore[arg-type]
        "financial_reconciliation": recon, "settlement": settlement,
        "owner_billed_delta_usd": recon["billing_delta_usd"], "live_resources": cleanup["live_resources"],
        "cleanup_snapshot": cleanup,
        "verdict": "SETTLEMENT_OBSERVED" if settlement["status"] == "OBSERVED"
                   else f"{SHORT_NAME[control_key]}_ATTEMPT_{attempt_number}_SETTLEMENT_STILL_UNRESOLVED",
        "no_gpu_started": True,
    }
    path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPT{attempt_number}_SETTLEMENT_RECONCILIATION_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    write_json(path, out)
    print(json.dumps({"artifact": path.name, "verdict": out["verdict"], "reasons": settlement["reasons"],
                      "visible_cost": str(visible), "billed_delta": recon["billing_delta_usd"], "live_resources": cleanup["live_resources"]}, indent=2))
    return 0 if settlement["status"] == "OBSERVED" else 5


def gpu_hour_rate() -> Decimal:
    rates = _cli_json("billing", "rates", "--json")
    return Decimal(str(rates["gpu_hour_cost_a100_80gb"]))  # type: ignore[index]


def worst_case_cost(rate_per_hour: Decimal) -> Decimal:
    return (rate_per_hour / Decimal(3600)) * Decimal(HARD_CEILING_SECONDS) * COST_MARGIN


def registry_control(name: str) -> dict:
    data = json.loads(REGISTRY_PATH.read_text())
    return next(c for c in data["controls"] if c["canonical_candidate_name"] == name)


def cleanup_snapshot() -> dict:
    apps = _cli_json("app", "list", "--json")
    containers = _cli_json("container", "list", "--json")
    volumes = _cli_json("volume", "list", "--json")
    running_tasks = sum(int(a.get("tasks", 0) or 0) for a in apps)  # type: ignore[union-attr]
    live_apps = [a for a in apps if a.get("state") not in ("stopped", "deployed") or int(a.get("tasks", 0) or 0) > 0]  # type: ignore[union-attr]
    return {
        "captured_at_utc": _now(),
        "apps": apps, "containers": containers, "volumes": volumes,
        "running_tasks_total": running_tasks,
        "non_idle_apps": live_apps,
        "live_resources": len(containers) + len(volumes) + running_tasks + len(live_apps),  # type: ignore[arg-type]
    }


def run_control(control_key: str, mode: str) -> int:
    cfg = CONTROLS[control_key]
    tag, name = cfg["tag"], cfg["control_name"]
    reg = registry_control(name)
    model_id, revision = reg["artifact_repository"], reg["exact_immutable_revision"]

    attempts = load_attempts(tag)
    attempt_no = len(attempts) + 1
    prefix = f"GENESIS_CONTROL_{tag}_ATTEMPT{attempt_no}"
    print(f"[{_now()}] control={name} model={model_id}@{revision} attempt={attempt_no} mode={mode}")

    # ── fresh account-specific financial preflight (§7/§8) ──
    rate = gpu_hour_rate()
    worst = worst_case_cost(rate)
    before = billing_summary()
    before_apps = cleanup_snapshot()
    from orca.eval.control_runtime_qualification import financial_gate_decision, to_decimal

    decision = financial_gate_decision(
        before, worst_case_job_cost_usd=str(worst), credit_pool_usd=CREDIT_POOL_USD, reserve_usd=RESERVE_USD,
        prior_positive_billing_seen=any_positive_billing_seen(),
        prior_settlement_unresolved=any_unresolved_settlement(),
    )
    preflight = {
        "evidence_type": "GENESIS_CONTROL_FINANCIAL_PREFLIGHT", "phase": PHASE, "control_name": name,
        "attempt_number": attempt_no, "captured_at_utc": _now(),
        "source": "modal billing summary --json / billing rates --json / app+container+volume list (supported CLI, executed live in this session immediately before any allocation)",
        "provider_account_context": {"provider": "Modal", "workspace_profile_redacted": True},
        "billing_summary_live": before,
        "starting_owner_payable_usd": before["billed_cost"],
        "starting_metered_cost_usd": before["metered_cost"],
        "starting_credits_applied_usd": before["adjustments"]["credits"],
        "credit_pool_usd_assumed": CREDIT_POOL_USD,
        "credit_pool_provenance": "Owner-provided Phase 21B.4.13 billing gate (2026-09-22: credits_remaining ~22.26 with usage 7.74 => pool 30.00) and the credits ceiling observed at exactly -30.00 in the GLM incident record; cross-checked against live adjustments.credits. Modal exposes no direct remaining-credit field, so remaining = pool - credits applied (derived, not read).",
        "known_remaining_credit_usd": decision.get("remaining_credit_usd"),
        "billing_discrepancy_observation": DISCREPANCY_ARTIFACT,
        "gates": "OWNER PAYABLE GATE (billed must not exceed baseline) AND CREDIT-COVERAGE GATE (derived remaining >= reserve + maximum authorized run cost)",
        "gpu_type": GPU_TYPE, "gpu_count": GPU_COUNT, "gpu_hour_rate_usd": str(rate),
        "hard_runtime_timeout_seconds": HARD_CEILING_SECONDS, "hard_container_timeout_seconds": HARD_CEILING_SECONDS,
        "ready_deadline_seconds": READY_DEADLINE_SECONDS,
        "worst_case_cost_method": f"gpu_rate/3600 * {HARD_CEILING_SECONDS}s * {COST_MARGIN} margin (CPU/memory/unknown metering)",
        "estimated_maximum_spend_usd": str(worst.quantize(Decimal('0.0001'))),
        "safety_reserve_usd": RESERVE_USD,
        "financial_acceptance_rule": "OWNER_BILLED_DELTA_USD == 0 exactly (billed_after == billed_before); any positive amount FAILS financial acceptance even if technically successful",
        "live_polling": f"every {POLL_INTERVAL_SECONDS}s; proactive cancel if billed_cost rises, metered growth exceeds the worst-case cap, or projected runway is breached",
        "cleanup_procedure": "cancel call with terminate_containers, exit ephemeral app context, verify zero containers/volumes/running tasks/non-idle apps via modal CLI, then settle-poll billing",
        "resources_before": {"live_resources": before_apps["live_resources"], "apps": before_apps["apps"]},
        "authorization_basis": "Phase 21B.4.20 specification relayed by the owner in a genuine user turn on 2026-09-24 directs GPU-backed runtime qualification of the three locked controls, subject to the section 7-9 hard financial gates. It states no dollar ceiling, so this run imposes its own: worst-case per-job cost above, all controls together well inside remaining credit minus the fixed reserve.",
        "gate_decision": decision,
        "gpu_execution_allowed": bool(decision["allowed"]) and mode == "run",
    }
    # a preflight-only reading never shares a filename with a real run's own (fresh) preflight
    preflight_path = EVIDENCE_DIR / (f"{prefix}_FINANCIAL_PREFLIGHT_ONLY_{DATE_TAG}.json" if mode == "preflight"
                                     else f"{prefix}_FINANCIAL_PREFLIGHT_{DATE_TAG}.json")
    preflight_sha = write_json(preflight_path, preflight)
    print(json.dumps({"gate": decision, "worst_case_usd": str(worst), "preflight_artifact": preflight_path.name}, indent=2))
    if mode == "preflight":
        return 0 if decision["allowed"] else 3
    if not decision["allowed"]:
        print("FINANCIAL GATE BLOCKED -- NO GPU STARTED")
        return 3

    before_path = EVIDENCE_DIR / f"{prefix}_BILLING_BEFORE_{DATE_TAG}.json"
    before_sha = write_json(before_path, {"evidence_type": "MODAL_BILLING_SNAPSHOT_BEFORE_GPU_ALLOCATION", "captured_at_utc": _now(),
                                          "billing_summary": before})
    billed_before = to_decimal(before["billed_cost"], "billed_before")
    metered_before = to_decimal(before["metered_cost"], "metered_before")
    remaining = to_decimal(decision["remaining_credit_usd"], "remaining")

    run_cfg = {
        "model_id": model_id, "revision": revision, "extra_args": cfg["extra_args"], "smokes": SMOKES,
        "max_model_len": MAX_MODEL_LEN, "gpu_memory_utilization": GPU_MEMORY_UTILIZATION,
        "smoke_max_tokens": cfg["smoke_max_tokens"], "ready_deadline_seconds": READY_DEADLINE_SECONDS,
    }
    try:
        report_before = _cli_json("billing", "report", "--for", "today", "--json")
        app_cost_before = sum((Decimal(str(r["cost"])) for r in report_before if isinstance(r, dict) and r.get("description") == app.name), Decimal(0))  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        app_cost_before = Decimal(0)
    started = _now()
    t_start = time.time()
    outcome, reason, result, guard_samples, error_text = "TECHNICAL_FAILURE", "unset", None, [], None
    aborted = False
    with app.run():
        call = serve_and_smoke.spawn(run_cfg)
        try:
            while True:
                try:
                    result = call.get(timeout=POLL_INTERVAL_SECONDS)
                    break
                except (TimeoutError, modal.exception.TimeoutError):  # still running (Modal 1.5.5 raises the BUILTIN TimeoutError from get(timeout=))
                    pass
                elapsed = time.time() - t_start
                live = billing_summary()
                billed_now = to_decimal(live["billed_cost"], "billed_now")
                metered_now = to_decimal(live["metered_cost"], "metered_now")
                growth = metered_now - metered_before
                projected_left = remaining - Decimal(RESERVE_USD) - growth
                guard_samples.append({"t": round(elapsed, 1), "billed": str(billed_now), "metered": str(metered_now), "growth": str(growth)})
                breach = None
                if billed_now > billed_before:
                    breach = f"billed_cost rose {billed_before} -> {billed_now}"
                elif growth > worst:
                    breach = f"metered growth {growth} exceeds worst-case cap {worst}"
                elif projected_left <= 0:
                    breach = f"projected runway exhausted (remaining {remaining} - reserve - growth {growth})"
                elif elapsed > HARD_CEILING_SECONDS + 60:
                    breach = f"wall clock {elapsed:.0f}s beyond ceiling"
                if breach:
                    print(f"FINANCIAL GUARD TRIPPED: {breach} -- cancelling")
                    call.cancel(terminate_containers=True)
                    outcome, reason, aborted = "ABORTED_FINANCIAL_GUARD", breach, True
                    break
        except Exception as e:  # noqa: BLE001
            error_text = f"{type(e).__name__}: {str(e)[:400]}"
            outcome, reason = "HARNESS_FAILURE", error_text
            try:
                call.cancel(terminate_containers=True)
            except Exception:  # noqa: BLE001
                pass
    duration = round(time.time() - t_start, 1)
    finished = _now()

    # ── cleanup verification (§27) ──
    time.sleep(10)
    cleanup = cleanup_snapshot()

    # ── billing settle-poll (§20): judge only once metered cost stops changing ──
    samples, last, stable = [], None, 0
    t_settle = time.time()
    while time.time() - t_settle < SETTLE_MAX_SECONDS:
        live = billing_summary()
        samples.append({"t": round(time.time() - t_settle, 1), "billed": live["billed_cost"], "metered": live["metered_cost"],
                        "credits": live["adjustments"]["credits"]})
        cur = (live["billed_cost"], live["metered_cost"])
        stable = stable + 1 if cur == last else 0
        last = cur
        if stable >= 2:
            break
        time.sleep(SETTLE_POLL_SECONDS)
    after = live
    billed_after = to_decimal(after["billed_cost"], "billed_after")
    observed_billed = [billed_after] + [to_decimal(s["billed"], "settle billed") for s in samples] + \
        [to_decimal(g["billed"], "guard billed") for g in guard_samples]
    peak_billed = max(observed_billed)
    settled_delta = billed_after - billed_before
    # STRICT: any observed positive billed reading (even transient) counts as positive owner billing.
    delta = peak_billed - billed_before
    try:
        report_after = _cli_json("billing", "report", "--for", "today", "--json")
        app_cost_after = sum((Decimal(str(r["cost"])) for r in report_after if isinstance(r, dict) and r.get("description") == app.name), Decimal(0))  # type: ignore[union-attr]
        run_metered = str(app_cost_after - app_cost_before)
    except Exception as e:  # noqa: BLE001
        run_metered = f"UNAVAILABLE ({type(e).__name__})"
    from orca.eval.control_runtime_qualification import FAILURE_DOMAIN_BY_OUTCOME, assess_settlement, build_financial_reconciliation
    recon = build_financial_reconciliation(before, after, credit_pool_usd=CREDIT_POOL_USD, reserve_usd=RESERVE_USD,
                                           max_run_cost_usd=str(worst), peak_billed_usd=str(peak_billed))
    settlement = assess_settlement(recon, run_report_metered_usd=None if run_metered.startswith("UNAVAILABLE") else run_metered)
    print(json.dumps({"reconciliation": recon, "settlement": settlement}, indent=2))
    after_path = EVIDENCE_DIR / f"{prefix}_BILLING_AFTER_{DATE_TAG}.json"
    after_sha = write_json(after_path, {
        "evidence_type": "MODAL_BILLING_SNAPSHOT_AFTER_GPU_ALLOCATION", "captured_at_utc": _now(),
        "billing_summary_settled": after, "billed_before_usd": str(billed_before), "billed_after_usd": str(billed_after),
        "peak_observed_billed_usd": str(peak_billed), "settled_delta_usd": str(settled_delta),
        "owner_billed_delta_usd": str(delta),
        "delta_rule": "owner_billed_delta_usd = (highest billed_cost observed in-run or in the settle window) - billed_before; any positive reading fails acceptance",
        "run_app_metered_cost_usd_from_report": run_metered,
        "financial_reconciliation": recon, "billing_settlement": settlement,
        "settle_samples": samples, "in_run_guard_samples": guard_samples, "cleanup_snapshot": cleanup,
        "telemetry_limitation": "Modal billing is polled via the CLI; provisional metering has been observed to differ from later-settled figures (Phase 21B.4.13 record vs current report). Any positive billed reading during the run or settle window is recorded and fails acceptance.",
    })

    # ── assemble raw log artifact (sanitized by construction: no env, no secrets) ──
    log_path = EVIDENCE_DIR / f"{prefix}_RAW_LOG_{DATE_TAG}.log"
    log_text = ""
    if result:
        log_text = "\n".join(result.get("events", [])) + "\n\n===== vLLM server log (tail) =====\n" + result.get("server_log", "")
    log_path.write_text(log_text if log_text else f"NO RESULT RETURNED: {reason}\n")
    log_sha = sha_of(log_path)

    technical_ok = bool(
        result and not result.get("error") and result.get("server_ready")
        and len(result.get("smoke_results", [])) == 3
        and all(s.get("http_status") == 200 and s.get("content") and not s.get("error") for s in result["smoke_results"])
        and result.get("orphan_vllm_processes_after_shutdown") == 0
    )
    if not aborted and error_text is None:
        outcome = "TECHNICAL_SUCCESS" if technical_ok else "TECHNICAL_FAILURE"
        reason = "server ready, 3 smoke requests returned HTTP 200 with non-empty content, clean shutdown" if technical_ok else (
            (result or {}).get("error") or "smoke/teardown criteria not met")
    cleanup_pass = cleanup["live_resources"] == 0 or (cleanup["live_resources"] == before_apps["live_resources"])
    attempt = {
        "attempt_number": attempt_no, "outcome": outcome, "reason": reason, "resource_type": f"Modal ephemeral function {GPU_TYPE}x{GPU_COUNT}",
        "duration_seconds": duration, "owner_billed_delta_usd": str(delta),
        "billing_settlement_status": settlement["status"],
        "status": outcome,
        "failure_domain": FAILURE_DOMAIN_BY_OUTCOME[outcome],
        "valid_runtime_attempt": bool(result and result.get("server_argv_sanitized") and not error_text and not aborted),
        "cleanup_result": "PASS" if cleanup_pass else "FAIL",
        "started_at_utc": started, "finished_at_utc": finished, "modal_app_name": app.name,
        "raw_log_artifact": log_path.name, "raw_log_sha256": log_sha,
    }
    attempts.append(attempt)
    write_json(EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPTS_{DATE_TAG}.json", {"control_name": name, "attempts": attempts})

    record = build_record(cfg, reg, model_id, revision, result, attempts, attempt, delta, cleanup, log_path, log_sha,
                          preflight_path, preflight_sha, before_path, before_sha, after_path, after_sha, started, finished)
    record["financial_reconciliation"] = recon
    record["billing_settlement"] = settlement
    record["billing_discrepancy_observation"] = {"artifact": DISCREPANCY_ARTIFACT, "sha256": sha_of(EVIDENCE_DIR / DISCREPANCY_ARTIFACT)}
    from orca.eval.control_runtime_qualification import validate_control_runtime_record
    out_path = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_{DATE_TAG}.json"
    validation_error = None
    try:
        validate_control_runtime_record(record, evidence_root=EVIDENCE_DIR)
    except Exception as e:  # noqa: BLE001
        validation_error = f"{type(e).__name__}: {e}"
        record["validator_note"] = f"record FAILED its own validator: {validation_error}"
    write_json(out_path, record)
    print(json.dumps({k: record[k] for k in ("technical_serving_status", "financial_acceptance_status", "owner_billed_delta_usd",
                                              "runtime_qualification_status", "cleanup_status", "live_resources_after_cleanup")}, indent=2))
    print("validator:", validation_error or "OK")
    if settlement["status"] != "OBSERVED":
        print("BILLING_SETTLEMENT_NOT_YET_OBSERVABLE -- STOP BEFORE NEXT CONTROL:", settlement["reasons"])
        return 4
    return 0 if record["runtime_qualification_status"] == "RUNTIME_QUALIFIED" and not validation_error else 1


def build_record(cfg, reg, model_id, revision, result, attempts, attempt, delta, cleanup, log_path, log_sha,
                 preflight_path, preflight_sha, before_path, before_sha, after_path, after_sha, started, finished) -> dict:
    from orca.eval.control_runtime_qualification import LOCKED_CONTROL_IDENTITIES, derive_runtime_status

    locked = LOCKED_CONTROL_IDENTITIES[cfg["control_name"]]
    result = result or {}
    vers = result.get("versions", {})
    log = result.get("server_log", "")
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
    peak_mib = result.get("peak_gpu_memory_used_mib")
    steady_mib = result.get("steady_gpu_memory_used_mib")

    weight_bytes = result.get("weight_bytes_observed")
    ident = {
        "pinned_revision_matches_runtime_artifact": bool(result.get("snapshot_dir_name") == revision),
        "runtime_served_model_matches_pinned_id": bool(
            (result.get("models_endpoint") or {}).get("data") and result["models_endpoint"]["data"][0].get("id") == model_id),
        "weight_bytes_observed": weight_bytes,
        "weight_bytes_expected_for_pinned_revision": locked["expected_weight_bytes"],
        "no_silent_model_fallback": bool(result.get("snapshot_dir_name") == revision and weight_bytes == locked["expected_weight_bytes"]),
        "identity_evidence_strength": "HF snapshot directory name == pinned commit AND summed HF shard bytes == preflight-recorded exact bytes AND /v1/models id == pinned repo id AND server started from that local snapshot path. vLLM exposes no separate runtime revision field; no stronger runtime proof exists.",
        "snapshot_dir_names": result.get("snapshot_dir_names"),
        "weight_shard_files": result.get("weight_shard_files"),
        "models_endpoint": result.get("models_endpoint"),
    }
    smoke_prompts = [{"smoke_id": s["smoke_id"], "purpose": s["purpose"], "messages": [{"role": "user", "content": s["user"]}],
                      "expected": s["expected"]} for s in SMOKES]
    smoke_outputs = []
    for s in smokes:
        raw = s.get("raw_response") or ""
        smoke_outputs.append({
            "smoke_id": s["smoke_id"], "http_status": s.get("http_status"), "raw_response": raw,
            "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(), "content": s.get("content"),
            "finish_reason": s.get("finish_reason"), "usage": s.get("usage"), "latency_seconds": s.get("latency_seconds"),
            "ttft_seconds": s.get("ttft_seconds"), "matches_expected_exactly": s.get("matches_expected_exactly"),
            "executed": False,
        })
    # Attempt result != model-runtime result: only a VALID runtime attempt that failed for model/runtime reasons is FAILED;
    # a harness failure or guard abort leaves runtime compatibility NOT_PROVEN.
    if attempt["outcome"] == "TECHNICAL_SUCCESS":
        technical = "QUALIFIED"
    elif attempt["outcome"] == "TECHNICAL_FAILURE" and attempt.get("valid_runtime_attempt") is True:
        technical = "FAILED"
    else:
        technical = "NOT_PROVEN"
    financial = "PASS" if delta == 0 else "FAILED"
    runtime = derive_runtime_status(technical=technical, financial_acceptance=financial, cleanup=attempt["cleanup_result"],
                                    owner_billed_delta_usd=delta, live_resources_after_cleanup=0 if attempt["cleanup_result"] == "PASS" else cleanup["live_resources"])
    record = {
        "phase": PHASE, "evidence_kind": "RUNTIME_QUALIFICATION_SMOKE", "control_name": cfg["control_name"],
        "model_id": model_id, "model_revision": revision,
        "tokenizer_revision": metric("tokenizer_revision", revision, "n/a"),
        "architecture": reg.get("architecture"), "license": reg.get("license_identifier"),
        "runtime_name": "vLLM (official vllm/vllm-openai image, OpenAI-compatible server)",
        "runtime_version": metric("runtime_version", vers.get("vllm"), "vLLM version not reported by the container"),
        "container_image": VLLM_IMAGE_TAG, "container_digest": VLLM_IMAGE_DIGEST,
        "gpu_provider": "Modal", "gpu_type": GPU_TYPE, "gpu_count": GPU_COUNT, "tensor_parallel": 1, "precision": "bfloat16",
        "max_model_len": MAX_MODEL_LEN,
        "attention_backend": metric("attention_backend", backend_m.group(1).strip() if backend_m else None, "no attention-backend line matched in the vLLM server log"),
        "reasoning_parser": cfg["reasoning_parser"], "reasoning_mode": cfg["reasoning_mode"],
        "chat_template_source": cfg["chat_template_source"], "stop_behavior": cfg["stop_behavior"],
        "started_at_utc": started, "finished_at_utc": finished,
        "cold_start_seconds": metric("cold_start_seconds", result.get("cold_start_seconds"), "server never became ready"),
        "load_seconds": metric("load_seconds", float(load_m.group(1)) if load_m else None, "no model-load duration line matched in the vLLM server log"),
        "download_seconds": result.get("download_seconds"),
        "peak_gpu_memory_bytes": metric("peak_gpu_memory_bytes", None if peak_mib is None else peak_mib * 1024 * 1024, "no nvidia-smi samples captured"),
        "steady_gpu_memory_bytes": metric("steady_gpu_memory_bytes", None if steady_mib is None else steady_mib * 1024 * 1024, "server never reached steady state"),
        "smoke_prompts": smoke_prompts, "smoke_protocol": LOCKED_PROTOCOL.protocol_document(), "generation_config": result.get("generation_config_sent") or {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": cfg["smoke_max_tokens"]},
        "smoke_outputs": smoke_outputs,
        "latency_seconds": metric("latency_seconds", None if not smokes else round(sum(s.get("latency_seconds", 0) for s in smokes), 4), "no smoke request completed"),
        "ttft_seconds": metric("ttft_seconds", first.get("ttft_seconds"), "no streamed first token observed"),
        "generated_tokens": metric("generated_tokens", total_tokens, "no usage data returned"),
        "tokens_per_second": metric("tokens_per_second", None if tps is None else round(tps, 2), "no usage/latency data (tiny-smoke metric only; not a performance claim)"),
        "technical_serving_status": technical, "financial_preflight_status": "PASSED", "financial_acceptance_status": financial,
        "owner_billed_delta_usd": str(delta), "runtime_qualification_status": runtime, "capability_status": "UNPROVEN",
        "cleanup_status": attempt["cleanup_result"],
        "live_resources_after_cleanup": 0 if attempt["cleanup_result"] == "PASS" else cleanup["live_resources"],
        "raw_log_artifact": log_path.name, "raw_log_sha256": log_sha,
        "notes": "Runtime-compatibility evidence only. Capability is UNPROVEN: no benchmark, Genesis eval item, or holdout was run. Metrics come from tiny smoke requests and are not performance claims. Generated output was treated as data and never executed.",
        "attempts": attempts, "identity_verification": ident,
        "financial_evidence": {
            "preflight_artifact": preflight_path.name, "preflight_sha256": preflight_sha,
            "billing_before_artifact": before_path.name, "billing_before_sha256": before_sha,
            "billing_after_artifact": after_path.name, "billing_after_sha256": after_sha,
        },
        "generated_output_executed": False,
        "unobservable_reasons": {**unobservable, **({"reasoning_parser": "not applicable: this control is a non-reasoning model with no reasoning parser"}
                                                    if cfg["reasoning_parser"] is None else {})},
        "versions": vers, "server_argv_sanitized": result.get("server_argv_sanitized"),
        "server_exit_code": result.get("server_exit_code"),
        "orphan_vllm_processes_after_shutdown": result.get("orphan_vllm_processes_after_shutdown"),
        "gpu_memory_used_mib_before_after": [result.get("gpu_memory_used_mib_before"), result.get("gpu_memory_used_mib_after")],
        "health_status": result.get("health_status"), "version_endpoint": result.get("version_endpoint"),
        "cleanup_snapshot": cleanup,
    }
    return record


def write_not_tested(control_key: str, reason: str) -> int:
    """CPU-only. Writes a validator-checked record stating that NO GPU
    execution occurred for this control. Nothing is fabricated: every
    unobserved metric is null with a recorded reason, capability stays
    UNPROVEN, and the attempt history is empty (no GPU attempt exists)."""
    from orca.eval.control_runtime_qualification import validate_control_runtime_record

    cfg = CONTROLS[control_key]
    tag, name = cfg["tag"], cfg["control_name"]
    reg = registry_control(name)
    pre = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_ATTEMPT1_FINANCIAL_PREFLIGHT_ONLY_{DATE_TAG}.json"
    if not pre.is_file():
        print(f"missing preflight-only artifact {pre.name}; run --mode preflight first")
        return 2
    not_run = "not executed: GPU launch did not occur in this session (no provider resources were created)"
    fields_null = ("tokenizer_revision", "runtime_version", "attention_backend", "cold_start_seconds", "load_seconds",
                   "peak_gpu_memory_bytes", "steady_gpu_memory_bytes", "latency_seconds", "ttft_seconds",
                   "generated_tokens", "tokens_per_second")
    record = {
        "phase": PHASE, "evidence_kind": "RUNTIME_QUALIFICATION_SMOKE", "control_name": name,
        "model_id": reg["artifact_repository"], "model_revision": reg["exact_immutable_revision"],
        "architecture": reg.get("architecture"), "license": reg.get("license_identifier"),
        "runtime_name": "vLLM (official vllm/vllm-openai image, OpenAI-compatible server) -- PLANNED",
        "container_image": VLLM_IMAGE_TAG, "container_digest": VLLM_IMAGE_DIGEST,
        "gpu_provider": "Modal", "gpu_type": f"{GPU_TYPE} (planned)", "gpu_count": GPU_COUNT, "tensor_parallel": 1,
        "precision": "bfloat16 (planned)", "max_model_len": MAX_MODEL_LEN,
        "reasoning_parser": cfg["reasoning_parser"], "reasoning_mode": cfg["reasoning_mode"],
        "chat_template_source": cfg["chat_template_source"], "stop_behavior": cfg["stop_behavior"],
        "started_at_utc": _now(), "finished_at_utc": _now(),
        "smoke_prompts": [{"smoke_id": s["smoke_id"], "purpose": s["purpose"], "messages": [{"role": "user", "content": s["user"]}],
                           "expected": s["expected"]} for s in SMOKES],
        "smoke_protocol": LOCKED_PROTOCOL.protocol_document(),
        "generation_config": {"temperature": 0, "top_p": 1, "seed": 0, "max_tokens": cfg["smoke_max_tokens"], "note": "planned"},
        "smoke_outputs": [],
        "technical_serving_status": "NOT_TESTED", "financial_preflight_status": "PASSED",
        "financial_acceptance_status": "NOT_TESTED", "owner_billed_delta_usd": "0",
        "runtime_qualification_status": "NOT_TESTED", "capability_status": "UNPROVEN",
        "cleanup_status": "NOT_APPLICABLE", "live_resources_after_cleanup": 0,
        "raw_log_artifact": None, "raw_log_sha256": None,
        "notes": f"NO GPU EXECUTION OCCURRED. {reason} The fresh read-only financial preflight (see financial_evidence) PASSED, so this is NOT a zero-cash-runway block; the run simply has not been launched. Capability is UNPROVEN and nothing was benchmarked.",
        "attempts": [],
        "identity_verification": {"verified_at_runtime": False, "reason": not_run,
                                  "pinned_revision_from_registry": reg["exact_immutable_revision"]},
        "financial_evidence": {"preflight_artifact": pre.name, "preflight_sha256": sha_of(pre)},
        "generated_output_executed": False,
        "unobservable_reasons": {**{k: not_run for k in fields_null},
                                 **({"reasoning_parser": "not applicable: this control is a non-reasoning model with no reasoning parser"}
                                    if cfg["reasoning_parser"] is None else {})},
        "planned_topology": {"gpu": f"{GPU_TYPE} x{GPU_COUNT}", "tensor_parallel": 1, "max_model_len": MAX_MODEL_LEN,
                             "gpu_memory_utilization": GPU_MEMORY_UTILIZATION, "extra_vllm_args": cfg["extra_args"]},
    }
    for k in fields_null:
        record[k] = None
    validate_control_runtime_record(record, evidence_root=EVIDENCE_DIR)
    out = EVIDENCE_DIR / f"GENESIS_CONTROL_{tag}_RUNTIME_QUALIFICATION_{DATE_TAG}.json"
    write_json(out, record)
    print(f"wrote {out.name} (NOT_TESTED, validator OK)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--control", required=True, choices=sorted(CONTROLS))
    ap.add_argument("--mode", required=True, choices=("preflight", "run", "record-not-tested", "reconcile"))
    ap.add_argument("--reason", default="GPU launch was not permitted in this session.")
    ap.add_argument("--attempt", type=int, default=1)
    args = ap.parse_args()
    if args.mode == "reconcile":
        return reconcile_attempt(args.control, args.attempt)
    if args.mode == "record-not-tested":
        return write_not_tested(args.control, args.reason)
    return run_control(args.control, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
