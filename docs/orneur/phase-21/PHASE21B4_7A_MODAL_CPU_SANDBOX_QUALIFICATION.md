# Phase 21B.4.7A — Modal Live CPU Sandbox Security Qualification

## Outcome: 10 of 11 required properties PASS with live, conclusive evidence; 1 (memory hard-limit) INCONCLUSIVE

This is a live qualification, not a documentation review. Every test
below ran `orca.eval.sandbox_modal.run_sandboxed_modal()` — the actual
production code path `ModalSandboxBackend.run()` delegates to —
against a real, authenticated Modal Starter account (workspace
`guruprasath-annadurai`), never a hand-rolled bypass of the ORNEUR
adapter.

## Two genuine bugs found and fixed before most tests could even run

1. `DEFAULT_MEMORY_REQUEST_MIB=64` — Modal rejects any request below
   128 MiB. First live call failed with `InvalidError`. Fixed to 128,
   plus a defensive fail-closed guard for any caller-supplied limit
   below that.
2. `timeout=int(timeout_seconds)+2` with no floor — Modal rejects any
   timeout below 10s. A 5.0s test call failed with `InvalidError`.
   Added `MODAL_MIN_TIMEOUT_SECONDS=10` and clamped.

Neither was a security defect — both failed closed correctly
(`SandboxBackendUnavailable`, never a silent fallback) — but neither
would have worked for any real invocation. Both fixed, regression-
tested, and mock-suite-verified before further live spend.

## Live adversarial evidence matrix

| Property | Expected | Observed | Verdict | Evidence |
|---|---|---|---|---|
| Filesystem isolation | No macOS/host paths visible | `/Users/ag/orca`, `/Users/ag`, `/Users`, `/System`, `/Applications` all `exists: false`; root listing is a clean, minimal Linux container (`bin, boot, dev, etc, home, lib, ...`); cwd=`/tmp` contains only Modal's own marker file | **PASS** | Live JSON result, test A |
| Repository isolation | No `.git`/repo files reachable | `repo_markers_in_root: []` (checked `.git`, `pyproject.toml`, `CLAUDE.md`) | **PASS** | Live JSON result, test B |
| Secrets/environment isolation | No Modal/GitHub/HF/Anthropic/OpenAI/AWS credentials | 28 env vars total, all build/runtime plumbing (`PATH`, `PYTHON_VERSION`, `MODAL_SANDBOX_ID`, `OMP_NUM_THREADS`, etc.); `suspicious_names_found: []` against patterns `MODAL_TOKEN\|GITHUB\|HF_TOKEN\|ANTHROPIC\|OPENAI\|AWS_\|SECRET\|API_KEY\|PASSWORD` | **PASS** | Live JSON result, test C (names only, no values ever printed) |
| DNS isolation | Outbound DNS fails | `gaierror(-3, 'Temporary failure in name resolution')` | **PASS** | Live JSON result, test D |
| TCP isolation | Outbound TCP connect fails | `OSError(101, 'Network is unreachable')` | **PASS** | Live JSON result, test D |
| HTTP isolation | Outbound HTTP fails | `URLError(gaierror(...))` | **PASS** | Live JSON result, test D |
| Raw UDP isolation | Outbound UDP fails | `OSError(101, 'Network is unreachable')` | **PASS** | Live JSON result, test D |
| ctypes/raw-libc containment | Network boundary holds even bypassing Python's socket module | `ctypes.CDLL(None)` loaded fine and `socket()` syscall succeeded (fd=3) — expected, not a failure per spec's own framing — but the actual `connect()` syscall returned failure (`returncode: -1`) and raw `getaddrinfo()` also failed (`returncode: -3`); the network boundary held at the kernel/gVisor level even when Python's socket module was bypassed entirely | **PASS** | Live JSON result, test E — this is the exact attack class Phase 21B.4.1 found broke the Docker sandbox's earlier Python-level-only guard; here the boundary held |
| Subprocess containment | Child confined, child's network also blocked | `subprocess.run(["echo",...])` succeeded (`child_spawned: true`); a nested `python3 -c "socket.gethostbyname(...)"` from within the child also failed with the same `gaierror` | **PASS** | Live JSON result, test F |
| Timeout enforcement | Sandbox terminates, no orphan | Modal itself raised `SandboxTimeoutError()` after the clamp fix (10s), correctly propagated by our code as `SandboxBackendUnavailable` — fail closed, never a false success; `sb.terminate()` still runs in the `finally` block regardless | **PASS** | Live exception, test H (retry after fix) |
| Output flooding | Bounded/truncated, not accepted as valid | 2MB flood correctly failed closed as `"sandbox output was not valid JSON"` rather than being silently accepted | **PASS** | Live result, test I |
| Ephemeral filesystem / persistence | No cross-task persistence | Sandbox 1 wrote `/tmp/orneur_marker_test.txt` (`written: true`); a completely fresh Sandbox 2 confirmed `marker_exists_in_fresh_sandbox: false` | **PASS** | Live result, test J (two separate real Sandboxes) |
| Sandbox destruction / cleanup | No unnecessary live Sandboxes remain | `modal.Sandbox.list(app_id=...)` after all tests returned zero entries | **PASS** | Live CLI/SDK query |
| **CPU/memory hard-limit enforcement** | Allocation beyond the 128 MiB limit fails/kills the process | Three separate live attempts (production path with a 128MiB limit attempting 2GB allocation; a manual direct `modal.Sandbox.create` call checking `sb.returncode`, which came back `0` with empty stdout/stderr; a cgroup-file-read + forced page-touching variant) all produced ambiguous signals that could not distinguish "process OOM-killed before printing" from "some other silent failure" — no attempt showed a successful print of allocation results, but none produced an unambiguous kill signal (e.g. a nonzero/negative returncode) either | **INCONCLUSIVE** | Three live attempts, test G — see below |

## The one open finding, stated honestly

This is **not a discovered security failure** — no test showed memory
actually escaping any boundary, and Modal's own documented behavior
(hard hard hard limits via the `(request, limit)` tuple, "CPU
throttling will prevent a container from exceeding its specified
limit") gives reason to expect the memory limit works the same way.
But per this project's explicit standard ("No assumed PASS values.
Only live evidence counts"), three genuine attempts to get conclusive
live evidence did not produce it, and asserting PASS anyway would
violate the entire purpose of this qualification phase. This is
reported as an unresolved **evidentiary gap**, not a security
weakness — the follow-up needed is a better-instrumented CPU-only
test (e.g. checking kernel OOM-killer logs inside the container, or
using `sb.exec()` with finer-grained `poll()`-based monitoring to
distinguish "SIGKILL mid-execution" from "ran to completion"), not any
change to the adapter's actual security posture.

## Billing

Baseline (before any live Sandbox): $0.00 billed, $0.00 metered.
Final: `metered_cost_breakdown.deployed_apps: 0.00052282` (~$0.0005),
`billed_cost: $0.00` (fully covered by included credits — the $0
spend limit never triggered because nothing exceeded it). Roughly
0.05% of the phase's $1 ceiling. Spend limit confirmed still $0
throughout (no dashboard change was made or needed this phase). Zero
live Modal resources remained after testing.

## Genesis truth

Unaffected. Qwen3-8B, Mistral-Nemo-Instruct-2407, Phi-4, and
Phi-4-mini-instruct were NOT downloaded. `genesis-eval-v1` was not
executed, inspected, or frozen. Genesis lifecycle remains without a
trained canonical checkpoint; availability remains UNAVAILABLE. This
phase used CPU-only Modal Sandboxes exclusively — no GPU was
requested or started.

## Phase 21C

Remains locked. Not authorized. Not started.
