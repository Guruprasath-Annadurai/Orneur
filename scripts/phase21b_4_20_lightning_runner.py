"""
Lightning AI Studio-side runner for Phase 21B.4.20 control runtime qualification.

Runs INSIDE the Lightning Studio (never on the operator machine). Trusted inference
only: it serves one locked control with vLLM, sends the three fixed smoke prompts, records
the raw responses as DATA, and tears the server down. Generated text is never executed,
imported, compiled, shelled out or sent to a code runner. No benchmark, no frontier call.

`serve_and_smoke` below is the SAME function used by the Modal harness (a test asserts
the two bodies are identical apart from the interpreter used to start vLLM), so the
smoke protocol, metrics and teardown checks do not change with the provider.

Subcommands (all argv constant; nothing derived from model output):
  stage-env    create the pinned venv and install vllm==0.29.0 (CPU, free)
  stage-model  download the exact pinned revision and verify sizes + LFS sha256 (CPU, free)
  serve        (GPU) serve + smoke + teardown, write a result JSON
  watchdog     sleep N seconds then stop THIS Studio (independent hard cost cap)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

VLLM_VERSION = "0.29.0"
WORK = Path(os.environ.get("P4420_WORK", str(Path.home() / "p4420")))
VENV = WORK / "venv"
MAX_MODEL_LEN = 4096
GPU_MEMORY_UTILIZATION = 0.90
READY_DEADLINE_SECONDS = 420

# Locked identities (a test asserts equality with orca.eval.control_runtime_qualification).
LOCKED = {
    "qwen3_8b": {"model_id": "Qwen/Qwen3-8B", "revision": "b968826d9c46dd6066d109eabc6255188de91218",
                 "expected_weight_bytes": 16381516776, "extra_args": ["--reasoning-parser", "qwen3"], "smoke_max_tokens": 1024},
    "mistral_nemo": {"model_id": "mistralai/Mistral-Nemo-Instruct-2407", "revision": "04d8a90549d23fc6bd7f642064003592df51e9b3",
                     "expected_weight_bytes": 24495607104,
                     "extra_args": ["--tokenizer-mode", "hf", "--config-format", "hf", "--load-format", "safetensors"], "smoke_max_tokens": 64},
    "phi4": {"model_id": "microsoft/phi-4", "revision": "2db69c1c3e91a05d2c64a3185acfbaf36f744e25",
             "expected_weight_bytes": 29319042992, "extra_args": [], "smoke_max_tokens": 64},
}

def _load_canonical(name: str):
    """Load a canonical stdlib-only module (locked smoke protocol / runtime configuration). Sibling copy first (container / Studio),
    repo path otherwise. Each verifies its own integrity on import."""
    import importlib.util as _ilu
    here = Path(__file__).resolve()
    for cand in (here.with_name(f"{name}.py"), here.parents[1] / "orca" / "eval" / f"{name}.py"):
        if cand.is_file():
            spec = _ilu.spec_from_file_location(name, cand)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise RuntimeError(f"{name}.py not found next to this script or in the repository")


LOCKED_PROTOCOL = _load_canonical("locked_smoke_protocol")
RUNTIME_CONFIGS = _load_canonical("control_runtime_configuration")
SMOKES = LOCKED_PROTOCOL.runner_smokes()      # no hand-written smoke string lives in this file


def capture_http_error(entry: dict, exc) -> None:
    """Persist an HTTP error response of a smoke call (urllib raises HTTPError before any status/body is recorded): status, safe headers, the error BODY as
    DATA (never parsed for execution), its sha256 and, if it parses as JSON, the structured error. Works for streamed and non-streamed calls."""
    raw = exc.read() or b""
    text = raw.decode("utf-8", errors="replace")
    structured = None
    try:
        parsed = json.loads(text)
        structured = parsed if isinstance(parsed, (dict, list)) else None
    except ValueError:
        structured = None
    entry["http_status"] = exc.code
    entry["raw_response"] = text
    entry["error"] = f"{type(exc).__name__}: HTTP Error {exc.code}: {exc.reason}"
    entry["http_error"] = {"smoke_id": entry["smoke_id"], "error_class": type(exc).__name__, "status": exc.code, "reason": str(exc.reason),
                           "headers": {k: v for k, v in exc.headers.items() if k.lower() in ("content-type", "content-length", "date", "server")},
                           "body_sha256": hashlib.sha256(raw).hexdigest(), "body_bytes": len(raw), "structured_error": structured}


def run_smoke_call(cfg: dict, smoke: dict, gen_cfg: dict, http) -> dict:
    """One locked smoke call (streamed or not) -> its persisted entry. HTTP error responses are CAPTURED (status, safe headers, body, sha256, structured
    error) for both modes; generated/response text is DATA ONLY and is never executed."""
    _json, _time = json, time
    payload = build_chat_payload(cfg, smoke, gen_cfg)
    t_req = _time.time()
    entry = {"smoke_id": smoke["smoke_id"], "http_status": None, "raw_response": None,
             "chat_template_kwargs_sent": payload.get("chat_template_kwargs"),
             "prompt_sha256_sent": hashlib.sha256(payload["messages"][0]["content"].encode("utf-8")).hexdigest()}
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
    except urllib.error.HTTPError as he:
        capture_http_error(entry, he)
    except Exception as e:  # noqa: BLE001
        entry["error"] = f"{type(e).__name__}: {e}"
    entry["latency_seconds"] = round(_time.time() - t_req, 4)
    entry["matches_expected_exactly"] = LOCKED_PROTOCOL.acceptance(smoke["smoke_id"], entry.get("content", ""))[0]
    return entry


def build_chat_payload(cfg: dict, smoke: dict, gen_cfg: dict) -> dict:
    """The exact chat-completions body for one locked smoke -- the ONLY place a request body is built. A control's runtime configuration
    (if it has one) adds exactly its chat_template_kwargs to EVERY smoke; controls without a configuration get no extra field."""
    payload = {"model": cfg["model_id"], "messages": [{"role": "user", "content": smoke["user"]}], **gen_cfg}
    kwargs = (cfg.get("runtime_configuration") or {}).get("chat_template_kwargs")
    if kwargs is not None:
        payload["chat_template_kwargs"] = json.loads(json.dumps(kwargs))
    return payload

IGNORE_PATTERNS = ["consolidated*", "original/*", "*.pth", "*.bin", "*.gguf", "*.msgpack", "*.h5", "*.onnx"]


# ══════════════════════════════════════════════════════════════════════════
# Trusted inference only. Generated text is data.
# ══════════════════════════════════════════════════════════════════════════
def serve_and_smoke(cfg: dict) -> dict:
    import importlib.metadata as md
    import json as _json
    import os
    import re as _re
    import signal
    import sys
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
            sys.executable, "-m", "vllm.entrypoints.openai.api_server",
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
        result["runtime_configuration_id_applied"] = (cfg.get("runtime_configuration") or {}).get("id")
        for smoke in cfg["smokes"]:
            entry = run_smoke_call(cfg, smoke, gen_cfg, http)
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
# Staging (CPU) + CLI
# ══════════════════════════════════════════════════════════════════════════

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_stage_env() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    if not (VENV / "bin" / "python").exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    py = str(VENV / "bin" / "python")
    subprocess.run([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
    subprocess.run([py, "-m", "pip", "install", "--quiet", f"vllm=={VLLM_VERSION}"], check=True)
    freeze = subprocess.run([py, "-m", "pip", "freeze"], capture_output=True, text=True, check=True).stdout
    keep = [l for l in freeze.splitlines() if l.split("==")[0].lower() in
            {"vllm", "torch", "transformers", "tokenizers", "safetensors", "huggingface-hub", "xformers", "flashinfer-python"}]
    out = {"vllm_requested": VLLM_VERSION, "python": sys.version.split()[0], "pinned_packages": keep,
           "venv_python": py, "staged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (WORK / "stage_env.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


def cmd_stage_model(control: str) -> int:
    from huggingface_hub import HfApi, snapshot_download  # type: ignore

    lock = LOCKED[control]
    info = HfApi().model_info(lock["model_id"], revision=lock["revision"], files_metadata=True)
    remote = {s.rfilename: s for s in info.siblings}
    t0 = time.time()
    snap = snapshot_download(repo_id=lock["model_id"], revision=lock["revision"], ignore_patterns=IGNORE_PATTERNS)
    dl_s = round(time.time() - t0, 1)
    files, weight_bytes, verified = [], 0, True
    for name in sorted(os.listdir(snap)):
        real = os.path.realpath(os.path.join(snap, name))
        size = os.path.getsize(real)
        entry = {"filename": name, "bytes": size}
        r = remote.get(name)
        lfs = getattr(r, "lfs", None) if r else None
        if lfs and getattr(lfs, "sha256", None):
            local = _sha256_file(real)
            entry.update(sha256=local, hf_lfs_sha256=lfs.sha256, sha256_matches=(local == lfs.sha256))
            verified = verified and entry["sha256_matches"]
        files.append(entry)
        if name.startswith("model-") and name.endswith(".safetensors"):
            weight_bytes += size
    ok = verified and os.path.basename(snap.rstrip("/")) == lock["revision"] and weight_bytes == lock["expected_weight_bytes"]
    manifest = {"control": control, "model_id": lock["model_id"], "revision": lock["revision"], "snapshot_dir": snap,
                "snapshot_dir_name": os.path.basename(snap.rstrip("/")), "weight_bytes_observed": weight_bytes,
                "weight_bytes_expected": lock["expected_weight_bytes"], "all_lfs_sha256_match": verified,
                "download_seconds": dl_s, "files": files, "staging_verified": ok}
    (WORK / f"stage_{control}.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=2))
    return 0 if ok else 3


def serving_config(control: str, ready_deadline_seconds: int = READY_DEADLINE_SECONDS) -> dict:
    """The complete serve_and_smoke configuration for a control -- the ONE place it is assembled (runner CLI and Modal harness both call it).
    The control's runtime configuration comes from the canonical module by model id; controls without one carry None."""
    lock = LOCKED[control]
    return {"model_id": lock["model_id"], "revision": lock["revision"], "extra_args": lock["extra_args"], "smokes": SMOKES,
            "max_model_len": MAX_MODEL_LEN, "gpu_memory_utilization": GPU_MEMORY_UTILIZATION, "smoke_max_tokens": lock["smoke_max_tokens"],
            "ready_deadline_seconds": ready_deadline_seconds, "runtime_configuration": RUNTIME_CONFIGS.configuration_for_model(lock["model_id"])}


def cmd_serve(control: str, out: str, deadline: int) -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"   # weights must come from the verified staged snapshot; no network fetch on GPU time
    result = serve_and_smoke(serving_config(control, min(deadline, READY_DEADLINE_SECONDS)))
    Path(out).write_text(json.dumps(result, indent=2))
    print(f"wrote {out} (error={result.get('error')})")
    return 0


def cmd_watchdog(seconds: int) -> int:
    time.sleep(seconds)
    from lightning_sdk import Studio  # type: ignore

    Studio().stop()  # inside a Studio the SDK resolves THIS studio from its environment
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stage-env")
    for name in ("stage-model", "serve"):
        p = sub.add_parser(name)
        p.add_argument("--control", required=True, choices=sorted(LOCKED))
        if name == "serve":
            p.add_argument("--out", required=True)
            p.add_argument("--deadline", type=int, default=READY_DEADLINE_SECONDS)
    w = sub.add_parser("watchdog")
    w.add_argument("--seconds", type=int, required=True)
    a = ap.parse_args()
    if a.cmd == "stage-env":
        return cmd_stage_env()
    if a.cmd == "stage-model":
        return cmd_stage_model(a.control)
    if a.cmd == "serve":
        return cmd_serve(a.control, a.out, a.deadline)
    return cmd_watchdog(a.seconds)


if __name__ == "__main__":
    sys.exit(main())
