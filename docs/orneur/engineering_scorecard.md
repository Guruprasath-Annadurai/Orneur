# Engineering preparation scorecard

Measured on branch `cursor/builtin-browser-engine-a8b0` from `origin/main` `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`. This scorecard is not the 95-row acceptance register.

| Metric | Result |
| --- | --- |
| Engineering gates at `VERIFIED_ENGINEERING` | 5 / 50 (10%) |
| Engineering gates at `INDEPENDENTLY_QUALIFIED` | 0 / 50 |
| Integrated product journeys demonstrated | 0 (A–F). The browser test is a component workflow, not Journey B. |
| Official pretraining acceptance | 0 / 95 |
| Acceptance ledger SHA-256 | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| Native checkpoints | GENESIS `INTERFACE_ONLY`. NOVUS and AETERNUM `NOT_AVAILABLE` on the canonical registry. No checkpoint was created. |
| Training authorization | `NO-GO` |

`VERIFIED_ENGINEERING` means this session implemented the behavior, ran the cited test to a passing exit, and left inspectable evidence. It does not mean Antigravity has qualified it. Documentation, an existing un-run module, or a refusal-only stub is not counted.

## Inventory

Classifications below are for `origin/main` plus this branch. Open PR #115 (`5ead4b426cd3d93705119f00353448bdea4bac4f`) is not in this tree. Its read-only browser, voice, and opportunity modules stay on that branch.

- `IMPLEMENTED_AND_VERIFIED` this session: `orca/browser_engine/` via `tests/test_browser_engine.py` (11 passed, twice).
- `IMPLEMENTED_BUT_UNQUALIFIED`: `orca/auth/store.py` `authenticate`, `orca/serve/model_identity.py`, `orca/mission/state_machine.py`, `orca/mission/mission_store.py`, `orca/agent/runtime.py`, `orca/rse/imp1/locks.py` (all seven locks return false). Present and not re-run here.
- `PARTIAL_OR_CONTRACT_ONLY`: mission lifecycle (no `INTERRUPTED_UNKNOWN` or `OUTCOME_UNKNOWN`), agent tool runtime (not ten specialist handlers), memory and conversation modules, train dry-run package `orca/train/dryrun/`.
- `MISSING_OR_BLOCKED`: Chromium HTTP product route, mission-to-browser adapter, deny-all principal adapter (that principal is on PR #115, not here), opportunity and voice on this branch, native training (denied).

## Gates

Owner for new work is Cursor. Independent review is `pending` unless noted. Positive and negative evidence refer to commands that actually finished.

### A — Browser

**A1.** Criterion: a real Chrome process renders a local JavaScript page. Files: `orca/browser_engine/engine.py`. Test: `tests/test_browser_engine.py::test_live_local_workflow_and_isolation`. Positive: `innerText` became `JS-RENDERED` and no longer contained `STATIC`. Negative: live test skips, and does not pass, when the real binary is absent. Dependency: local Chrome, not CI. Review: pending. Blocker: none for this host. Status: `VERIFIED_ENGINEERING`.

**A2.** Criterion: click, fill, scroll, a second tab, a PNG screenshot, and an evidence file. Files: `orca/browser_engine/engine.py`. Test: same live test. Positive: page showed `CLICKED`, `hello-field`, `SCROLLED`, `SECOND-PAGE`, and a PNG. Negative: fill and scroll raise `fill_failed` or `scroll_failed` when the observed value does not change. Dependency: A1. Review: pending. Blocker: none on this host. Status: `VERIFIED_ENGINEERING`.

**A3.** Criterion: per-user profiles, short grants, page text is not authority, resume checks state. Files: `orca/browser_engine/engine.py`, `orca/browser_engine/policy.py`. Test: live workflow plus `test_grant_bounds_and_download_names` and `test_page_text_cannot_grant_authority`. Positive: user B's page showed `EMPTY` after user A's `secret=alpha` cookie; resume restored the cookie only with matching state. Negative: tampered state is `resume_refused`; captcha is `unsupported_challenge`; evidence file does not contain the page text. Dependency: A1. Review: pending. Blocker: product authentication is not wired to `issue_grant`. Status: `VERIFIED_ENGINEERING`.

**A4.** Criterion: metadata, private, rebinding, redirect, and download traversal are refused. Files: `orca/browser_engine/policy.py`, `orca/browser_engine/proxy.py`, `orca/browser_engine/engine.py`. Tests: `test_network_policy_refusals`, `test_dns_rebinding_is_refused_before_connect`, `test_proxy_refuses_metadata_private_and_rebinding`, `test_allowlist_port_does_not_open_other_ports`, `test_grant_bounds_and_download_names`, live redirect. Positive: allowed loopback HTTP is forwarded. Negative: `169.254.169.254`, metadata CONNECT, private `10.1.2.3`, alternating DNS, `../escape.txt`, and a live redirect to metadata. Dependency: Chrome uses the proxy, including loopback (`--proxy-bypass-list=<-loopback>`). Review: pending. Blocker: a Chrome bug that bypassed the proxy was not separately proved absent. Status: `VERIFIED_ENGINEERING`.

**A5.** Criterion: no `--no-sandbox`, cancel during navigation, crash becomes `browser_dead`, resource limits are set. Files: `orca/browser_engine/engine.py`. Tests: `test_wrapper_binary_is_refused`, `test_live_cancel_and_crash`, live cmdline check. Positive: live `/proc/pid/cmdline` had no `--no-sandbox`; CPU and open-file limits were not `unlimited`. Negative: wrapper script and symlink refused; cancel and `SIGKILL` failed the next call closed. Dependency: A1. Review: pending. Blocker: no memory cap. Status: `VERIFIED_ENGINEERING`.

### B — Mission

**B1.** Criterion: an authenticated user creates a mission and the objective is persisted. Files: `orca/mission/mission_store.py`, `orca/auth/store.py`. Test: not run this session. Positive: none this session. Negative: none this session. Dependency: Postgres. Review: pending. Blocker: store and auth are not connected to this browser, and this session did not re-run the store tests. Status: `PARTIAL`.

**B2.** Criterion: an explicit plan and stored steps classified by capability and risk. Files: `orca/mission/execution_plan.py`, `orca/mission/requirements.py`. Test: not run. Positive: none this session. Negative: none. Dependency: B1. Review: pending. Blocker: not the requested classifier, and not re-tested. Status: `PARTIAL`.

**B3.** Criterion: no execution without a fresh approval. Files: `orca/mission/state_machine.py` (`WAITING_APPROVAL`). Test: not run. Positive: the state machine's own module requires evidence for `COMPLETED_VERIFIED`; that was read, not executed. Negative: not attacked this session. Dependency: B1. Review: pending. Blocker: approval is not bound to a one-time grant. Status: `PARTIAL`.

**B4.** Criterion: execute a real tool and record side-effect intent separately from outcome. Files: `orca/mission/operation_store.py`, `orca/browser_engine/`. Test: browser evidence only. Positive: browser completions distinguish performed from verified. Negative: no mission dispatched a browser step. Dependency: B1 and A1. Review: pending. Blocker: no adapter. Status: `NOT_STARTED`.

**B5.** Criterion: pause, cancel, resume, and preserve `INTERRUPTED_UNKNOWN` / `OUTCOME_UNKNOWN`. Files: `orca/mission/state_machine.py`. Test: not run. Positive: `PAUSED_USER` and `CANCELLED` exist in the enum. Negative: `INTERRUPTED_UNKNOWN` and `OUTCOME_UNKNOWN` are absent, so those states cannot be represented. Dependency: B1. Review: pending. Blocker: enum does not contain the unknown-outcome states. Status: `PARTIAL`.

### C — Identity, memory, persistence

**C1.** Criterion: verified product authentication and session validation. Files: `orca/auth/store.py`, `orca/auth/tokens.py`, `orca/serve/session_store.py`. Test: not run. Positive: none this session. Negative: none. Dependency: auth database. Review: pending. Blocker: not re-qualified. Status: `IMPLEMENTED_UNVERIFIED`.

**C2.** Criterion: adapter in front of the deny-all runtime principal, without trusting caller claims. Files: none on this branch. `orca/core_runtime/principal.py` is on PR #115. Test: none. Positive: none. Negative: none. Dependency: PR #115 stays isolated. Review: pending. Blocker: principal module is not in this tree; it must not be switched to trust caller claims. Status: `NOT_STARTED`.

**C3.** Criterion: durable conversations, including temporary conversations, survive restart. Files: `orca/serve/conversations.py`. Test: not run. Positive: none this session. Negative: none. Dependency: conversation store. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**C4.** Criterion: memory consent, deletion, retention, and authorized search. Files: `orca/memory/deletion.py`, `orca/memory/store.py`, `orca/serve/retention.py`. Test: not run. Positive: none this session. Negative: none. Dependency: memory store. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**C5.** Criterion: two authenticated users cannot read or execute each other's conversation, memory, mission, or browser. Files: `orca/browser_engine/engine.py` for the browser half only. Test: live browser isolation. Positive: browser profiles and cookies were isolated. Negative: cross-user conversation, memory, and mission were not attempted. Dependency: C1. Review: pending. Blocker: only the browser half ran. Status: `PARTIAL`.

### D — Specialist agents

**D1.** Criterion: versioned registry; unavailable roles stay unavailable. Files: `orca/agent/tool_registry.py`. Test: not run. Positive: none. Negative: none. Dependency: none. Review: pending. Blocker: this is a tool registry, not a specialist-role registry. Status: `NOT_STARTED`.

**D2.** Criterion: dispatch, bounded concurrency, deadline, and cancellation. Files: `orca/agent/runtime.py`. Test: not run. Positive: the module documents a deadline and a single execution path. Negative: not attacked. Dependency: D1. Review: pending. Blocker: not re-qualified and not tied to specialist roles. Status: `PARTIAL`.

**D3.** Criterion: delegated tools cannot escalate authority. Files: `orca/agent/delegation.py`, `orca/agent/policy.py`. Test: not run. Positive: none this session. Negative: none. Dependency: D2. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**D4.** Criterion: ten real handlers (research, planning, coding, data, retrieval, verification, security, documentation, tools, mission coordination). Files: none for that set. Test: none. Positive: none. Negative: none. Dependency: D1. Review: pending. Blocker: handlers were not added. A count of empty classes would not pass. Status: `NOT_STARTED`.

**D5.** Criterion: dependency order, evidence aggregation, and failure recovery across those handlers. Files: `orca/agent/runtime.py` replan path only. Test: not run. Positive: none. Negative: none. Dependency: D4. Review: pending. Blocker: D4. Status: `NOT_STARTED`.

### E — Proof and evidence

**E1.** Criterion: the six completion states are enforced for mission and tool results. Files: `orca/browser_engine/engine.py`, `orca/mission/production_proof.py`. Test: browser tests. Positive: browser records use `performed_unverified`, `verified`, `refused`, and `failed`. Negative: success is not recorded when fill, scroll, or navigation does not match. Dependency: none for the browser. Review: pending. Blocker: `unknown` and `authorized_not_performed` are not yet produced, and missions do not use this record. Status: `PARTIAL`.

**E2.** Criterion: provenance and digests, without treating a hash as authorship. Files: `orca/browser_engine/engine.py`, `docs/orneur/browser_engine.md`. Test: evidence file assertions. Positive: evidence stores hashes, not page text. Negative: none beyond the file-content check. Dependency: E1. Review: pending. Blocker: no external witness. Status: `PARTIAL`.

**E3.** Criterion: a missing, forged, stale, or unverifiable effect cannot be reported as success. Files: `orca/browser_engine/engine.py`, `orca/mission/state_machine.py`. Test: browser negative paths; mission transition not executed. Positive: browser raises on mismatch. Negative: forged mission evidence was not attempted. Dependency: E1. Review: pending. Blocker: mission path not re-tested. Status: `PARTIAL`.

**E4.** Criterion: redaction and tenant boundaries on evidence. Files: `orca/browser_engine/engine.py`. Test: evidence does not contain `secret=alpha` or `hello-field`. Positive: that assertion passed. Negative: log and cache leakage outside this file was not tested. Dependency: C5. Review: pending. Blocker: browser evidence only. Status: `PARTIAL`.

**E5.** Criterion: an independent party can re-verify a result. Files: evidence JSONL. Test: a reviewer can read the file; no second verifier ran. Positive: none. Negative: none. Dependency: E2. Review: pending. Blocker: no independent verifier. Status: `NOT_STARTED`.

### F — Model gateway

**F1.** Criterion: native families keep canonical identity. Files: `orca/serve/model_identity.py`, `orca/rse/imp1/locks.py`. Test: not run. Positive: locks return false. That was read, not executed as a test. Negative: none. Dependency: none. Review: pending. Blocker: not re-qualified. No model was renamed. Status: `IMPLEMENTED_UNVERIFIED`.

**F2.** Criterion: missing providers return unavailable, not a native name. Files: `orca/serve/model_identity.py`, `orca/serve/routing.py`. Test: not run. Positive: none. Negative: none. Dependency: no authorized local model in this session. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**F3.** Criterion: streaming, cancellation, and timeouts. Files: `orca/serve/streaming.py`. Test: not run. Positive: none. Negative: none. Dependency: a real model backend. Review: pending. Blocker: no authorized model was called. Status: `PARTIAL`.

**F4.** Criterion: fallback cannot present an external model as GENESIS, NOVUS, or AETERNUM. Files: `orca/serve/model_identity.py`. Test: not run. Positive: the module's docstring says a substitution keeps a `substitution_reason`. Negative: not attacked. Dependency: F2. Review: pending. Blocker: behavior was not executed. Status: `IMPLEMENTED_UNVERIFIED`.

**F5.** Criterion: usage accounting with no paid call and no download. Files: `orca/serve/metrics.py`. Test: not run. Positive: this session made no paid call and downloaded no model. Negative: the accounting path itself was not tested. Dependency: F2. Review: pending. Blocker: accounting not exercised. Status: `NOT_STARTED`.

### G — Code, files, retrieval

**G1.** Criterion: untrusted code runs only inside a real isolation boundary. Files: `orca/mission/container_executor.py`, `orca/mission/sandbox_executor.py`. Test: not run. Positive: none. Negative: none. Dependency: Docker or an equivalent isolator, if the executor requires it. Review: pending. Blocker: not re-qualified. AST filtering is not treated as a pass. Status: `PARTIAL`.

**G2.** Criterion: uploads are size-limited, parsed safely, and isolated by user. Files: not established as a single checked path this session. Test: not run. Positive: none. Negative: browser quarantine is a different gate (A4). Dependency: G1. Review: pending. Blocker: not implemented as this gate. Status: `NOT_STARTED`.

**G3.** Criterion: retrieval returns real citations the caller is allowed to see. Files: `orca/serve/citations.py`. Test: not run. Positive: none. Negative: none. Dependency: an authorized index. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**G4.** Criterion: synthetic retrieval stays labeled synthetic. Files: not confirmed. Test: not run. Positive: none. Negative: none. Dependency: G3. Review: pending. Blocker: not confirmed in this tree. Status: `NOT_STARTED`.

**G5.** Criterion: one authenticated document or code task returns evidence. Files: none for the combined path. Test: none. Positive: none. Negative: none. Dependency: C1, G1, G3. Review: pending. Blocker: journey not built. Status: `NOT_STARTED`.

### H — Opportunity, voice, relay

**H1.** Criterion: opportunity records with provenance, timestamps, and deduplication from a real source. Files: none on this branch. `orca/core_runtime/opportunity.py` is on PR #115. Test: none here. Positive: none. Negative: none. Dependency: an authorized data source, which was not added. Review: pending. Blocker: no live source, and this branch does not absorb PR #115. Status: `NOT_STARTED`.

**H2.** Criterion: user-owned saved opportunities and an explained ranking. Files: none on this branch. Test: none. Positive: none. Negative: none. Dependency: H1. Review: pending. Blocker: H1. Status: `NOT_STARTED`.

**H3.** Criterion: speech input and output contracts with an honest unavailable state. Files: none on this branch. `orca/core_runtime/voice.py` is on PR #115. Test: none here. Positive: none. Negative: none. Dependency: a real speech backend. No speech backend was called. Review: pending. Blocker: no backend. Status: `NOT_STARTED`.

**H4.** Criterion: audio consent, retention, and deletion. Files: none. Test: none. Positive: none. Negative: none. Dependency: H3. Review: pending. Blocker: H3. Status: `NOT_STARTED`.

**H5.** Criterion: authenticated relay for missions and files, with no new OAuth or background permission. Files: `orca/mission/relay_store.py`, `orca/mission/relay_security.py`. Test: not run. Positive: none. Negative: no OAuth provider was enabled by this branch. Dependency: B1. Review: pending. Blocker: not re-qualified and not connected to the browser. Status: `PARTIAL`.

### I — Pretraining foundation

**I1.** Criterion: GENESIS shape and math checks on synthetic CPU fixtures, with no new weights. Files: `orca/train/dryrun/`. Test: not run this session. Positive: none. Negative: training locks still return false in source. Dependency: existing dry-run package. Review: pending. Blocker: not re-run. No weights were written. Status: `PARTIAL`.

**I2.** Criterion: tokenizer integrity and dataset admission using synthetic fixtures only. Files: `orca/train/dryrun/`. Test: not run. Positive: none. Negative: no corpus was read and the acceptance ledger hash is unchanged. Dependency: founder authorization for any real corpus. Review: pending. Blocker: tokenizer work was not added, and protected corpus use is denied. Status: `PARTIAL`.

**I3.** Criterion: CPU dry-run of loss, gradients, optimizer, seeds, and NaN rejection on toy data. Files: `orca/train/dryrun/toy.py`, `orca/train/dryrun/harness.py`. Test: not run. Positive: none. Negative: `training_authorized()` returns false. Dependency: I1. Review: pending. Blocker: not re-run. A passing dry run would still not be pretraining. Status: `PARTIAL`.

**I4.** Criterion: atomic checkpoint publication, crash recovery, and stale-checkpoint refusal. Files: `orca/train/dryrun/ckpt.py`. Test: not run. Positive: none. Negative: no checkpoint was published. Dependency: I3. Review: pending. Blocker: not re-run. Status: `PARTIAL`.

**I5.** Criterion: separate GENESIS, NOVUS, and AETERNUM contracts, evaluation without invented scores, and a read-only compute note. Files: `orca/train/genesis_eval.py`, `orca/train/novus_eval.py`, `orca/train/aeternum_eval.py`, `orca/rse/imp1/locks.py`. Test: not run. Positive: none. Negative: no family was promoted and no GPU was requested. This session did not measure the host's CPU or RAM, so no feasibility number is claimed. Dependency: no native checkpoint exists. Review: pending. Blocker: not re-run. Status: `PARTIAL`.

### J — Security and reliability

**J1.** Criterion: authentication before protected data, deny by default. Files: `orca/auth/`, `orca/browser_engine/engine.py`. Test: browser grant tests. Positive: browser actions check the grant. Negative: expired grant and missing action fail. Product routes were not re-tested. Dependency: C1. Review: pending. Blocker: product routes not in this run. Status: `PARTIAL`.

**J2.** Criterion: tenant isolation under adversarial access. Files: `orca/browser_engine/engine.py`. Test: live user A / user B. Positive: separate profiles. Negative: user B did not see user A's cookie. Other resource types were not attacked. Dependency: C5. Review: pending. Blocker: browser only. Status: `PARTIAL`.

**J3.** Criterion: cancellation is not confirmation, and revocation beats dispatch. Files: `orca/browser_engine/engine.py`. Test: `test_live_cancel_and_crash`. Positive: `cancel()` closes the process. Negative: the worker's navigation raised `BrowserError` rather than a success record. Mission revocation was not tested. Dependency: B5. Review: pending. Blocker: mission revocation not in this run. Status: `PARTIAL`.

**J4.** Criterion: timeouts, restart, and no unbounded retry. Files: browser proxy timeouts and `orca/agent/runtime.py` (`_MAX_ACTION_RETRIES = 1`, read only). Test: browser cancel. Positive: proxy reads stop after 5 seconds of silence. Negative: agent retries were not executed. Dependency: D2. Review: pending. Blocker: agent path not run. Status: `PARTIAL`.

**J5.** Criterion: no secret in logs or evidence, no hidden paid fallback. Files: `orca/browser_engine/engine.py`. Test: evidence content assertion. Positive: evidence omitted field text and cookie values. Negative: server logs outside this module were not audited. No paid API was called. Dependency: F5. Review: pending. Blocker: log audit is incomplete. Status: `PARTIAL`.

## Count

`VERIFIED_ENGINEERING`: A1, A2, A3, A4, A5 (5).

`INDEPENDENTLY_QUALIFIED`: none.

`IMPLEMENTED_UNVERIFIED`: C1, F1, F4 (3).

`PARTIAL`: B1, B2, B3, B5, C3, C4, C5, D2, D3, E1, E2, E3, E4, F2, F3, G1, G3, H5, I1, I2, I3, I4, I5, J1, J2, J3, J4, J5 (28).

`NOT_STARTED`: B4, C2, D1, D4, D5, E5, F5, G2, G4, G5, H1, H2, H3, H4 (14).

`BLOCKED_EXTERNAL`: none as a sole status. External blockers are recorded on the gates above (no Chrome in CI, no Postgres re-run, no authorized model, no corpus, no founder training grant).

5 + 3 + 28 + 14 = 50. The verified fraction is 5/50. That is 10 percent. It is not 90 percent.

Training, GPU, spending, corpus generation, protected merge, and production launch remain denied.
