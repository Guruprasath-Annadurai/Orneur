# Phase 21B.4.1 -- Compute-Ready Genesis Baseline Execution Closure

Documents the REAL infrastructure built this closure: the container-
isolated evaluation sandbox (replacing Phase 21B.4's subprocess-only
sandbox), the first real `ModelAdapter` implementation
(`TransformersModelAdapter`), the operator-facing execution CLI with a
machine-readable preflight mode, and the adversarial re-review /
concurrency hardening of the baseline-freeze transaction.

**No real foundation model was executed to produce this document.**
Every code path below has been exercised against `python:3.11-slim`
(the sandbox's own pinned test image, not a candidate model) and mocked
`transformers` calls (the adapter's own unit tests). See "Resource
check" at the end of this document for the current, honestly-stated
blocker.

## 1. Sandbox re-audit -- what was actually found

Phase 21B.4's subprocess-only sandbox (`orca/eval/sandbox.py`) was
re-audited live this closure against the full threat checklist in spec
§2, run for real (not assumed) against this host's actual sandbox
implementation. Findings:

**Closed already (confirmed, re-verified)**: subprocess/fork escape via
object introspection, infinite loops (timeout), direct
`socket.connect()`.

**NEWLY FOUND OPEN this closure** (not previously identified):

- **DNS resolution succeeded** (`socket.gethostbyname('example.com')`
  returned a real IP) despite the Python-level network guard --
  `gethostbyname()` does not route through `socket.socket()`, the only
  call the guard intercepted.
- **`ctypes.CDLL(None)` gave raw libc access** -- a Python-level guard
  is fundamentally unable to close this class of bypass, since `ctypes`
  can call arbitrary C functions (including raw socket syscalls)
  without ever touching the `socket` module.
- **Filesystem access was, and remains in the subprocess-only sandbox,
  fully open** -- confirmed live (again) that generated code can write
  to this project's own repository directory and the real developer's
  home directory, and read the real host's `/etc/passwd`.

These findings directly justified spec §3's requirement for a real OS
boundary, rather than iterating further on Python-level guards.

## 2. Container sandbox (`orca/eval/sandbox_docker.py`)

Docker was found installed and functional on this development host
(`docker version`, `docker info`, and a real `docker run --rm
python:3.11-slim ...` all succeeded live). `run_sandboxed_docker()`
launches one freshly-created, ephemeral container per candidate
function call:

```
docker run --rm -i \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,exec,size=64m \
  --memory 256m --memory-swap 256m \
  --cpus 1 \
  --pids-limit 32 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user 65534:65534 \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  python:3.11-slim python3 -I -S -
```

Candidate code is piped via stdin -- there is no bind mount of any host
path, ever.

### Live re-test of the exact prior exploits, against the container

| Attack | Subprocess sandbox (Phase 21B.4) | Container sandbox (this closure) |
|---|---|---|
| `socket.connect()` | blocked (Python guard) | **blocked (kernel-level -- no interface exists)** |
| `socket.gethostbyname()` | **NOT blocked** (real IP returned) | **blocked** (`gaierror`) |
| `ctypes.CDLL(None)` raw libc | not blocked | still succeeds *inside* the container, but the container has no network reachable regardless of syscall path used |
| Write to this repo | **succeeded** | **blocked -- path does not exist inside the container** |
| Write to real home dir | **succeeded** | not applicable (no host mount at all) |
| Write to container's own `/usr/local` (read-only root) | n/a | blocked (`Read-only file system`) |
| Infinite loop | killed by timeout | killed by timeout (re-confirmed) |
| Memory bomb (500MB into a 128MB limit) | not limited | **killed by OOM (exit 137)** |
| Fork bomb | blocked (`RLIMIT_NPROC=0`) | blocked (`--pids-limit`) |
| 5MB stdout | unbounded | **detected/truncated at the 1MB output cap** |
| Real host env vars (secrets) | inherited none (subprocess sandbox already stripped env) | confirmed none of this test process's real `os.environ` leaked in |

All rows above were verified live this closure with real Docker
commands and real Python reproduction scripts, not assumed from the
container architecture alone.

### Honestly stated remaining limitation

A subprocess spawned *inside* the container can still run (pids-limit
permits a handful of processes) and can read/write the container's own
filesystem (its image + the ephemeral tmpfs) -- but confirmed live, it
cannot reach the network (the isolation is at the container's network
namespace, not the top-level process), and it cannot reach the host
filesystem (no bind mount exists at any level). This is a materially
different, much lower-severity situation than the prior subprocess-only
sandbox's host-level escape. A payload deliberately targeting a
CPython/kernel/Docker-runtime vulnerability itself is out of scope for
this closure's isolation guarantee, same as any container-based
sandbox.

## 3. Sandbox security contract (`orca/eval/sandbox_contract.py`)

`current_docker_contract()` returns a versioned, explicit record
(`SandboxContract`) of every isolation parameter in force: backend,
image tag + resolved digest, network/filesystem policy text, CPU/
memory/PID/timeout/output limits, environment policy, mounted paths
(always `[]`), Python runtime version, host platform, and whether
Docker was actually available at contract-construction time.
`contract_id()` derives a deterministic identity hash so a future
result can be checked for contract drift against whatever scored it.

## 4. `TransformersModelAdapter` (`orca/eval/adapters/transformers_adapter.py`)

Implements `orca.eval.runner.ModelAdapter`. Family-agnostic --
`AutoModelForCausalLM`/`AutoTokenizer` work across Qwen3, Mistral-Nemo,
Phi-4/mini, or any other `transformers`-supported causal LM without
family-specific code. Key properties:

- **Revision enforcement** (`TransformersAdapterConfig.__post_init__`):
  rejects `revision` or `tokenizer_revision` that is empty or a known
  mutable marker (`main`/`latest`/`head`/`master`) before any load is
  attempted.
- **Native chat templates, never forced parity**: `render_prompt()`
  uses the candidate's own `tokenizer.apply_chat_template()` -- two
  different model families legitimately produce different rendered text
  for the same semantic system+user content, which is correct, not a
  parity bug (spec §8).
- **Resolved-identity capture**: records `resolved_model_revision`/
  `resolved_tokenizer_revision` from the loaded object's own
  `_commit_hash` when the installed `transformers` version exposes it,
  falling back to the requested (still-exact) revision otherwise.
- **Chat-template digest**: `chat_template_digest` (sha256 of the
  template Jinja source) recorded at load time.
- **Structured failures**: load errors raise `AdapterLoadError`;
  generation errors are caught and returned as a `GenerationResult`
  with `error` set, never raised past `generate()`.
- **Explicit, clean unload**: `unload()` drops references and calls
  `gc.collect()` / `torch.cuda.empty_cache()` -- safe to call even if
  never loaded.
- **Tests are fully mocked** (`tests/test_transformers_adapter.py`, 16
  tests) -- `transformers.AutoModelForCausalLM.from_pretrained` and
  `AutoTokenizer.from_pretrained` are patched to return fake objects. No
  real model weights are downloaded anywhere in this test file. A
  passing test here is evidence of the ADAPTER's own logic being
  correct, never evidence any real candidate was evaluated.

## 5. Execution CLI (`orca/eval/run_genesis_baseline.py`)

```
python -m orca.eval.run_genesis_baseline --preflight \
    --candidate qwen3-8b --upstream-model Qwen/Qwen3-8B \
    --artifact-repo unsloth/Qwen3-8B --exact-revision <sha> \
    --backend transformers --quantization 4bit --device cuda [--json]
```

`--preflight` performs zero inference and returns a machine-readable
`{"ready": bool, "blockers": [...], "checks": {...}}` -- readiness is
never a subjective log line. Checks: candidate ID syntax, exact-revision
pinning, suite digest computability + persisted/frozen state, Docker
availability + full sandbox contract (including whether the pinned
image has actually been pulled locally), result-destination
writability + free disk space, `transformers`/`torch` availability +
versions, and CUDA/MPS visibility matching the requested `--device`.

**Live-verified this closure**: a fully-valid CPU invocation against
this real host returned `READY FOR REAL BASELINE` (`ready: true`, zero
blockers) with a complete, real sandbox contract embedded. An invocation
with `--exact-revision main --device cuda` correctly returned
`NOT READY` with two explicit blockers (unpinned revision; CUDA
unavailable on this host).

Real execution (no `--preflight`) re-runs the preflight check
internally and refuses to proceed if not ready. If preflight IS ready,
the CLI still does not wire up and invoke real inference
automatically -- it prints that a human must separately confirm owner
resource authorization (spec §12's second gate is a human decision, not
a technical check this CLI can itself verify) before the adapter/runner
wiring in `orca.eval.runner`/`orca.eval.adapters` is actually invoked.

## 6. Baseline/freeze transaction -- adversarial re-review (§15) results

Two real bugs were found and fixed via live reproduction against the
NOW-real adapter-backed pipeline:

1. **Result-references-wrong-suite**: `record_baseline_and_freeze_suite()`
   never cross-checked `result.suite_id`/`result.suite_version` against
   its own `suite_id`/`suite_version` parameters. Reproduced live: a
   result claiming `suite_id="totally-different-suite"` was silently
   accepted and finalized while the CORRECT suite was frozen underneath
   it. Fixed: explicit check, `BaselineIntegrityError` on mismatch.
2. **Duplicate `run_id` silently overwrites a finalized result**.
   Reproduced live: candidate A's finalized result was replaced by
   candidate B's data under the same `run_id`, with no error. Fixed:
   `DuplicateRunIdError` raised if a finalized result already exists
   under that `run_id`.

Both fixes are covered by dedicated regression tests
(`tests/test_evaluation_baseline_freeze.py`), including live
reproduction of the exact original bug before the fix, and a
verification the corrected code path is now what actually runs.

## 7. Concurrency hardening (§16)

`_suite_freeze_lock(suite_id, suite_version)` wraps the ENTIRE
baseline-freeze transaction in a POSIX advisory exclusive file lock
(`fcntl.flock`), keyed per `(suite_id, suite_version)`, under
`ORCA_HOME/registry/evaluation_locks/`. Verified with a REAL
multi-threaded test (`test_concurrent_baseline_attempts_never_both_believe_they_froze_first`,
using actual `threading.Thread`, not a mock): two concurrent attempts to
record the first baseline against the same suite version always
resolve to exactly one `is_first_baseline=True` and one `False`, never
both, never neither, and the suite manifest on disk ends up frozen
exactly once.

**Honest limitation**: `fcntl.flock` is a single-host advisory lock. It
does not serialize two processes on physically different machines --
this project's `ORCA_HOME` registry is a local filesystem tree, not a
distributed store, and no distributed lock service exists in this
codebase. Stated explicitly rather than implied to be stronger than it
is.

## 8. Reproduction / next steps

1. Re-verify Docker availability and pull/verify the pinned sandbox
   image (`docker pull python:3.11-slim`; `resolve_image_digest()`
   confirms the digest).
2. Run `python -m orca.eval.run_genesis_baseline --preflight` with the
   real candidate's exact, freshly re-verified revision SHA -- confirm
   `READY FOR REAL BASELINE`.
3. Construct a `TransformersAdapterConfig` + `TransformersModelAdapter`,
   `adapter.load()`.
4. `result, scored_task_ids = orca.eval.runner.run_suite(adapter, candidate_config)`.
5. `orca.eval.baseline.record_baseline_and_freeze_suite(tasks=orca.eval.genesis_suite.all_tasks(), result=result, scored_task_ids=scored_task_ids)`.
6. `adapter.unload()`.
7. Update `GENESIS_BASELINE_RESULTS.md` with the real, factual results.

## 9. Resource check (Step 23, performed at closure time)

```
$ nvidia-smi                    -> command not found
$ system_profiler SPDisplaysDataType -> Apple M4 (integrated GPU)
$ python -c "import torch; print(torch.cuda.is_available(), torch.backends.mps.is_available())"
False True
```

This host has **no CUDA-capable GPU**, but DOES have an Apple M4
integrated GPU visible to PyTorch via the MPS backend -- a materially
different fact than Phase 21B.4's "no GPU" finding, stated honestly
here rather than repeated unchanged. This is a consumer laptop-class
GPU (10 cores, shared unified memory with the OS), not equivalent to
the datacenter-class CUDA resource this project's shootout runbook
anticipates (Kaggle/Colab/Modal/Race Engineering), and it has **not**
been explicitly authorized by the owner as a resource for real Genesis
baseline execution. No candidate model weights were downloaded, and no
real inference was attempted on it, in this closure -- per spec §12's
two-gate requirement, technical readiness alone (even if this MPS
device were judged sufficient) does not authorize execution without a
separate, explicit owner resource authorization.
