# PR #125 Security Remediation — Antigravity Handoff

**Corrective branch:** `cursor/pr125-security-remediation-e8f0`  
**Starting SHA (frozen PR #125 head):** `9298b157fe22c95c897d7afbcc9f2e21a99d256e`
**Remediation commit:** `89f485f9e1609a934e2debb939ff43ed26666cdd`
**Exact tip:** `dd7cd6867f5ca8cca28a0844143682d603f6fe11`  
**Does not rewrite** PR #125 / #126 audited SHAs. No merge to production.

## Failures closed

### A1 — Streaming PEM / secret DLP

**Failing-before (at `9298b15`):** character-by-character PEM streaming emitted the full private-key body. Incomplete-suffix holding had gaps at `-----B…` transitions; `scan_output` on an open `sk-` candidate redacted at the 20-char minimum and leaked the remainder.

**Fix:** bounded stateful `StreamRedactor` (`orca/serve/stream_dlp.py`):
- PEM state machine holds from incomplete BEGIN prefix through matching END (or fail-closed)
- All supported delimiters: PKCS#8, RSA, EC, DSA, OPENSSH, ENCRYPTED
- Raw-buffer hold before scan (never redact-and-release mid-token)
- Cancel / unclosed PEM / overflow fail closed; persist only `safe_text()`

**Tests:** `tests/test_critical_sse_dlp.py` (char-by-char PEM, all delimiters, SSE vs transcript)

### A2 — Quota reservation + request-ID replay

**Failing-before:** `consumed` reservations returned `ok=True` (free replay / second dispatch). No user or fingerprint binding.

**Fix:** (`orca/auth/store.py`, `orca/serve/inference.py`)
- Reservation bound to `user_id` + immutable `fingerprint`
- Cross-user / fingerprint mismatch → refuse
- `consumed` → no provider dispatch; authorized replay of committed response only when stored
- In-progress duplicate → `request_in_progress` (no second inference)
- Heartbeat via `touch_reservation` for long streams; atomic admit + refund unchanged

**Tests:** `tests/test_serving_policy_adversarial.py` (49/50, consumed replay, cross-user, fingerprint, in-progress)

**HTTP note:** public `/api/inference/*` still mints server-side request IDs. Consumed-replay and foreign-reuse are proven at the service layer; they are not a distinct public HTTP ID injection surface today.

### A3 — Transactional transcript integrity

**Failing-before:** `_persist` appended JSONL before unchecked Redis CAS; stale fences polluted authoritative history.

**Fix:** `orca/serve/turn_commit.py`
- Verify session owner
- Enforce expected conversation version (message count)
- Stage pending turn → Redis CAS + lease fence → JSONL append only on success
- Failed commits leave JSONL untouched
- Idempotent `commit_id`; `recover_pending` for crash completion/discard

**Tests:** `tests/test_turn_commit_integrity.py`, `tests/test_redis_integration_gap.py::test_stale_fence_commit_does_not_mutate_jsonl`

## Remaining limitations

- Pattern DLP is floor-not-ceiling (unrecognized secret shapes can still stream)
- Without Redis, cross-process fencing is limited to process-local turn locks + version checks
- Committed-response replay store is best-effort with the auth DB; prune with terminal retention
- Product `/api/stream` (AgentLoop path) is out of this inference-module remediation scope for A1 wiring beyond shared DLP helpers

## Qualification request

Independently re-run Antigravity A1/A2/A3 against this branch tip. Preserve frozen `9298b15`. Do not merge.
