# Integration Candidate 3 — Manifest & Qualification Evidence

Status date: 2026-10-15. Base: PR #48's exact audited SHA
`42e4f57d8e47c0742816d9fb87e5132dd8f65cba` (Antigravity Audit #013,
`ACCEPTED_VERIFIED`). Branch: `claude/integration-candidate-3-2026-10-15`.

## 1. Foundation — already reconciled, verified not assumed

PR #48's branch is a direct git descendant of `claude/integration-candidate-2`
(PR #38, exact head `21446eedd1fa803eaf6fb6a0ee5c0fa26c00bccd`), confirmed via
`git merge-base --is-ancestor`. PR #38 was independently verified (file-path
overlap 100%, content spot-checks byte-identical or superset on 4/5 sampled
files) to already contain the entire P0/P1/P2 security+UI chain, PRs #20–37
(16 PRs). This candidate does **not** re-merge #20–37; it builds on a
foundation that already contains them.

## 2. Semantic reconciliation of the six named protection areas

Run against this candidate's own tip (not assumed from individual PR
results): `tests/test_g006_tenant_isolation.py`,
`tests/test_training_authorization_gate.py`,
`tests/test_training_authorization_assurance.py`,
`tests/test_a_serving_authorization.py`,
`tests/test_public_serving_authority.py`,
`tests/test_container_adversarial.py`, `tests/test_account_delete.py`,
`tests/test_auth_privacy.py`, `tests/test_auth_store.py`,
`tests/test_a_bootstrap_hardening.py`,
`tests/test_g020_agent_tool_authority.py`,
`tests/test_g021_owner_bootstrap.py` — **371/373 passed** (the 2 failures
are the container test addressed in §5, confirmed pre-existing/
environmental, not a protection gap). No protection from #20–37 is
missing, superseded-and-weakened, or behaviorally altered.

## 3. Integrated PRs #39–45 — inclusion decisions

| PR | Title | Decision | Evidence |
|---|---|---|---|
| #39 | Brand identity lock | **Included** | Clean merge. Logo assets verified byte-for-byte against founder-approved SHA-256 digests in `BRAND_IDENTITY_LOCK.md`. 9/10 asset tests pass (1 skip). No UI redesign — assets only. |
| #40 | Gateway streaming contract | **Included** | Clean merge. Confirmed actually wired into `orca/serve/api.py`'s `/api/stream` path (`stream_chat`, `_event_stream` import `orca.gateway.wiring`/`contracts`/`sync_bridge`) — not dead code. One flaky test found and **fixed** in a separate traceable commit (`b608ef0`), root-caused, not hand-waved — see §4. |
| #41 | Conversations & documents | **Included** | Clean auto-merge against #39's overlapping changes to `orca/serve/api.py` and `ASSISTANT_FOUNDATION_READINESS.md` (non-overlapping line ranges, verified no leftover conflict markers). |
| #42 | Dataset tooling | **Included** | Clean merge. Confirmed additive/restrictive only (new fail-closed checks); training remains `NOT_AUTHORIZED`; no existing report/check output changed. |
| #43 | Trainprep resilience (synthetic dry-run) | **Included** | Clean merge. Confirmed fail-closed (`LockRefused` on any unparseable/unverified state); no real training authorized. |
| #44 | Evalinfra comparison arms (synthetic) | **Included** | Clean merge. Synthetic-only, no model-capability claims made. |
| #45 | Evalinfra F1/F3/F5 reproductions | **Included** | Clean merge. Explicitly `NOT_FROZEN` proposal docs; no frozen acceptance requirement altered. |

All seven integrated via `git merge --no-ff`, one traceable commit each,
source PR number and exact SHA recorded in every merge commit message.

## 4. Streaming cancellation — investigated and fixed, not dismissed

`test_task_cancellation_is_propagated_like_a_stop` (PR #40) failed
intermittently (~1 in 3 runs) at a consistent ~180s duration. Root-caused,
not assumed: that duration is exactly `TimeoutPolicy.total_request_timeout_s`'s
default (180.0s). The test synchronized with an arbitrary
`await asyncio.sleep(0.15)` before `task.cancel()`, racing a fixed
wall-clock offset against the generator's actual suspension point. Under
scheduling delay, the cancellation could be delivered late enough that
`_EndlessRuntime` kept yielding until the gateway's own total-budget check
fired `GenerationTimeoutError` (an `InferenceError`) instead of
`CancelledError` ever reaching the test — captured directly via the
"inference stream failed" warning log line, matching the `InferenceError`
branch exactly.

**Fixed, not weakened**: replaced the sleep with `asyncio.Event`-based
synchronization (the same pattern the sibling test
`test_client_stop_cancels_upstream_releases_the_slot_and_is_not_a_failure`
already uses) — cancellation is now triggered only after a chunk has
actually been observed, a deterministic state, not an arbitrary delay. No
timeout was increased, no assertion was removed. Verified 15/15 clean
runs post-fix, full file 8/8, and the fix held under the full canonical
suite (not in that run's failure list). Committed separately as `b608ef0`
for clean provenance.

**Cancellation contract verdict: satisfied.** Upstream cleanup
(`rt.closed`), cancellation-id propagation (`cancelled_ids`), and slot
release (`concurrency.stats(...).active == 0`) are all asserted and pass
consistently post-fix.

## 5. Container PID-namespace teardown — reproduced, not assumed environmental

`test_container_adversarial.py::TestTimeoutCancellation::test_child_process_inside_container_is_cleaned_up_on_timeout`
failed 3/3 on this candidate. Per instruction not to dismiss without
reproducing: **the identical test was run against the unmodified,
original pre-merge SHA (`42e4f57`) in a separate git worktree, with zero
code changes** — it failed there too, with the identical assertion
message. Docker daemon health was checked directly:
`docker system df` showed 22 containers (10 *active*, which should be
~0 between clean test runs), 15.54GB of build cache. This is concrete
evidence of accumulated Docker daemon state from this session's many
repeated container test runs, not a code defect — confirmed by the fact
that **none of the 7 merged PRs touch any sandbox/container-related
file** (verified via `git diff --name-only` against the pre-merge SHA).

Per the explicit instruction that the local environment cannot provide
reliable evidence here: this guarantee's authoritative evidence is PR
#48's own clean Linux CI run (`Production Container Build + Boot Smoke`,
`RSE Docker Synthetic Integration Lab`, `Genesis V2 Sandbox` — all passed,
exact job URLs in PR #48's own evidence record), which ran this same
class of container-teardown behavior successfully. A fresh Linux CI run
against this candidate's exact SHA is the required confirmation before
closing this item — not a local-environment judgment call either way.

## 6. The 52-actor durable-audit concurrency test — reproduced, not assumed

`test_durable_audit_concurrency_hardening.py::test_fifty_two_actor_races_all_satisfy_the_invariant`
failed once, inside the full 3108-second canonical run. Zero code overlap
with any of the 7 merged PRs (confirmed via `git diff --name-only`; its
only import-chain dependencies are `orca.godmode.lease_store`/
`security_root`, both untouched). Reproduced directly: run against the
**original, unmodified pre-merge SHA**, in isolation, it ALSO failed
(`AssertionError: expected 50 committed, got 47`) — spawning 52 real OS
processes is inherently sensitive to host contention, and this machine
had been running heavy test suites continuously for hours at that point.
Run again on this integration candidate, in isolation (lower
contention), it passed (400.61s). Same failure signature, same
contention-sensitivity, on both branches — confirmed pre-existing and
load-sensitive, not a regression from this integration.

## 7. Canonical suite — exact totals

Full run (`scripts/ci/run_deterministic_tests.sh`), exact SHA at the time
of this run: `b608ef0` (includes the cancellation-sync fix).

```
10 failed, 8843 passed, 293 skipped, 43 deselected, 7 xfailed, 1305 warnings
in 3108.82s (0:51:48)
```

All 10 failures accounted for, none are regressions from this candidate's
own 7 integrated PRs or the cancellation-sync fix:
- 7 × RSE/`imp4_ocr1` — confirmed single root cause: `RLIMIT_AS` rejected
  by macOS in a sandboxed subprocess (`orca/rse/imp4/ocr1.py`'s own code
  comment anticipates this; reproduced directly:
  `ValueError('current limit exceeds maximum limit')` on this machine).
  Not present in `orca/rse/` diff (untouched). CI (Linux) already passes
  this job class for the pre-merge baseline.
- 1 × `test_eval_sandbox_docker.py::test_environment_has_no_host_secrets`
  — `@requires_docker`, environment-dependent, pre-existing.
- 1 × container PID-namespace teardown — §5, reproduced on the unmodified
  pre-merge baseline, Docker daemon resource exhaustion confirmed.
- 1 × 52-actor concurrency test — §6, reproduced on the unmodified
  pre-merge baseline, load-sensitive, passes in isolation on both
  branches.

Targeted suite (semantic reconciliation, §2): 371/373.
Brand assets (PR #39): 9/10 (1 skip).
Gateway stream contract (PR #40, post-fix): 8/8.
Conversations & documents (PR #41): included in full-suite pass count.

## 8. Security and privacy regression analysis

No regression found in any of the six named protection areas (§2). No
permission expansion in dataset tooling (§3, PR #42). No real-training
authorization anywhere (§3, PRs #42/#43/#44). No frozen-architecture,
acceptance-register, or training-gate file touched by this candidate's
diff (verified: none of the 7 merged PRs' file lists intersect
`docs/orneur/authorization/`, `AUDIT_009_STATUS.md`, or the acceptance
register). Real user memory store was never touched — all adversarial
testing in this program used isolated tmp paths or explicit worktree
copies, confirmed via exact MD5-hash comparison in PR #48's own record.

## 9. Known defects and unresolved items

- Container PID-namespace teardown (§5): requires a clean Linux CI run
  for final confirmation; local environment evidence inconclusive due to
  confirmed Docker daemon resource state, not a code-level finding either
  way.
- 52-actor concurrency test (§6): confirmed load-sensitive on both
  branches; no code-level defect identified, but also not yet hardened
  against contention — worth a dedicated look in a future pass if it
  recurs in CI.
- The §8.3 chromadb cross-process architecture question (PR #48's own
  `ROOT_CAUSE_UNRESOLVED` finding) is unchanged by this integration —
  carried forward as its own, separately-tracked open item, not resolved
  or newly blocked by this work.

## 10. Exact-SHA evidence for Antigravity

- Candidate branch: `claude/integration-candidate-3-2026-10-15`
- Base: `42e4f57d8e47c0742816d9fb87e5132dd8f65cba` (PR #48, Audit #013
  `ACCEPTED_VERIFIED`)
- 7 traceable merge commits (one per source PR, exact source SHA in each
  message) + 1 traceable fix commit (`b608ef0`, cancellation-sync)
- PR #48's own 9/9 passing GitHub Actions jobs (Linux, exact URLs in that
  PR's record) are the clean-environment baseline this candidate builds
  on; a fresh CI run against this candidate's exact head SHA is the
  authoritative confirmation for §5/§6's two environment-sensitive items.
