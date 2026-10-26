# Engineering preparation scorecard

Measured on the M01–M03 successor of the #119 reconciliation head `42c81e0c2339bf4fc76169f32e5bb0ca69215ce2`. Parent histories of PRs #116, #117 and #118 remain ancestors. PR #115 is not in this tree. This scorecard is not the 95-row acceptance register. The verified count is not increased by this security remediation.

| Metric | Result |
| --- | --- |
| Engineering gates at `VERIFIED_ENGINEERING` | 16 / 50 (32%) |
| Engineering gates at `INDEPENDENTLY_QUALIFIED` | 0 / 50 |
| Integrated product journeys demonstrated | 0 (A–F). The authenticated local-fixture mission is an API workflow. It is not one of the named product journeys, and no frozen frontend screen was changed. |
| Official pretraining acceptance | 0 / 95 |
| Acceptance ledger SHA-256 | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| Native checkpoints | GENESIS `INTERFACE_ONLY`. NOVUS and AETERNUM `NOT_AVAILABLE` on the canonical registry. No checkpoint was created. |
| Training authorization | `NO-GO` |

`VERIFIED_ENGINEERING` means this session implemented the behavior, ran the cited test to a passing exit, and left inspectable evidence. It does not mean Antigravity has qualified it. Documentation, an existing un-run module, or a refusal-only stub is not counted.

## Inventory

Classifications below are for `origin/main` plus this branch. Open PR #115 (`5ead4b426cd3d93705119f00353448bdea4bac4f`) is not in this tree. Its read-only browser, voice, and opportunity modules stay on that branch.

- `IMPLEMENTED_AND_VERIFIED` this session: `orca/sovereign_mission/` via `tests/test_sovereign_mission.py`, and the browser remediation in `orca/browser_engine/` (DevTools pipe, symlink refusal, grant mint, CGNAT and IPv6). The verified count stays 16. Independent qualification stays 0. The gradient-norm left fold restores the existing golden digest on CPython 3.12 and does not add a pretraining acceptance row.
- `IMPLEMENTED_BUT_UNQUALIFIED`: `orca/serve/model_identity.py`, `orca/mission/state_machine.py`, `orca/mission/mission_store.py`, `orca/agent/runtime.py`, `orca/rse/imp1/locks.py` (all seven locks return false). The Phase 15 mission store was not re-run and was not used.
- `PARTIAL_OR_CONTRACT_ONLY`: Phase 15 mission lifecycle still has no `INTERRUPTED_UNKNOWN` or `OUTCOME_UNKNOWN`. Agent tool runtime is not ten specialist handlers. Memory and conversation modules were not re-tested.
- `MISSING_OR_BLOCKED`: public browser destinations, deny-all principal adapter (that principal is on PR #115, not here), opportunity and voice on this branch, native training (denied), pause/resume, an effective browser memory cap.

## Gates

Owner for new work is Cursor. Independent review is `pending` unless noted. Positive and negative evidence refer to commands that actually finished.

### A — Browser

**A1.** Criterion: a real Chrome process renders a local JavaScript page. Files: `orca/browser_engine/engine.py`. Test: `tests/test_browser_engine.py::test_live_local_workflow_and_isolation`. Positive: `innerText` became `JS-RENDERED` and no longer contained `STATIC`. Negative: live test skips, and does not pass, when the real binary is absent. Dependency: local Chrome, not CI. Review: pending. Blocker: none for this host. Status: `VERIFIED_ENGINEERING`.

**A2.** Criterion: click, fill, scroll, a second tab, a PNG screenshot, and an evidence file. Files: `orca/browser_engine/engine.py`. Test: same live test. Positive: page showed `CLICKED`, `hello-field`, `SCROLLED`, `SECOND-PAGE`, and a PNG. Negative: fill and scroll raise `fill_failed` or `scroll_failed` when the observed value does not change. Dependency: A1. Review: pending. Blocker: none on this host. Status: `VERIFIED_ENGINEERING`.

**A3.** Criterion: per-user profiles, short grants, page text is not authority, resume checks state. Files: `orca/browser_engine/engine.py`, `orca/browser_engine/policy.py`. Test: live workflow plus `test_grant_bounds_and_download_names` and `test_page_text_cannot_grant_authority`. Positive: user B's page showed `EMPTY` after user A's `secret=alpha` cookie; resume restored the cookie only with matching state. Negative: tampered state is `resume_refused`; captcha is `unsupported_challenge`; evidence file does not contain the page text. Dependency: A1. Review: pending. Blocker: the engine still does not accept a product session by itself. Sovereign Mission issues the loopback grant after authentication. Status: `VERIFIED_ENGINEERING`.

**A4.** Criterion: metadata, private, rebinding, redirect, and download traversal are refused. Files: `orca/browser_engine/policy.py`, `orca/browser_engine/proxy.py`, `orca/browser_engine/engine.py`. Tests: `test_network_policy_refusals`, `test_dns_rebinding_is_refused_before_connect`, `test_proxy_refuses_metadata_private_and_rebinding`, `test_allowlist_port_does_not_open_other_ports`, `test_cgnat_and_unique_local_are_refused`, `test_ipv6_allowlist_and_unbracketed_connect`, `test_grant_bounds_and_download_names`, live redirect. Positive: allowed loopback HTTP is forwarded. Negative: `169.254.169.254`, metadata CONNECT, private `10.1.2.3`, `100.64.1.5`, unique-local IPv6, alternating DNS, unbracketed IPv6 CONNECT, `../escape.txt`, and a live redirect to metadata. Dependency: Chrome uses the proxy, including loopback (`--proxy-bypass-list=<-loopback>`). Review: pending. Blocker: a live public HTTPS tunnel was not opened. Status: `VERIFIED_ENGINEERING`.

**A5.** Criterion: no `--no-sandbox`, cancel during navigation, crash becomes `browser_dead`, resource limits are set. Files: `orca/browser_engine/engine.py`. Tests: `test_wrapper_binary_is_refused`, `test_live_cancel_and_crash`, live cmdline check. Positive: live command line had `--remote-debugging-pipe` and no `--no-sandbox` or `--remote-debugging-port`; profile processes had no listening TCP port; CPU, open-file, and file-size limits were not `unlimited`. Negative: wrapper script and symlink refused; cancel and `SIGKILL` failed the next call closed. Dependency: A1. Review: pending. Blocker: no effective memory cap. `RLIMIT_AS` aborts this Chrome (signal 5). The memory cgroup directory was not writable. Status: `VERIFIED_ENGINEERING`.

### B — Mission

**B1.** Criterion: an authenticated user creates a mission and the objective is persisted. Files: `orca/sovereign_mission/service.py`, `orca/auth/store.py`. Test: `tests/test_sovereign_mission.py::test_two_users_cannot_read_each_other` and `test_http_denies_the_other_user`. Positive: the owner read the stored objective after a new `SovereignMission()` and after an HTTP create. Negative: the other user's HTTP and service reads returned `access_denied` and did not include the objective. Dependency: the product SQLite auth database. Review: pending. Blocker: the Phase 15 Postgres store was not used. Status: `VERIFIED_ENGINEERING`.

**B2.** Criterion: an explicit plan and stored steps classified by capability and risk. Files: `orca/sovereign_mission/service.py`. Test: `test_refuses_unapproved_tampered_and_unqualified_actions` and `test_live_browser_mission_isolates_users`. Positive: the browser step was stored with risk `local_fixture`. Negative: `shell` is `capability_unavailable`; `download` is `action_unqualified`; a click without a `#` selector is `plan_refused`; `https://example.com` and `http://localhost` are `public_browser_unqualified`. Dependency: B1. Review: pending. Blocker: none for this classifier. Status: `VERIFIED_ENGINEERING`.

**B3.** Criterion: no execution without a fresh approval. Files: `orca/sovereign_mission/service.py`. Test: `test_approval_expiry_replay_and_public_browser_refusal`, `test_refuses_unapproved_tampered_and_unqualified_actions`, `test_concurrent_dispatch_runs_one_effect`. Positive: an approved local marker ran once. Negative: dispatch before approval is `not_authorized`; a second approval is `approval_replay_refused`; the other user is `access_denied`; an expired approval writes no file; a changed approval destination is `approval_refused`; two overlapping dispatches produced one file. Dependency: B1. Review: pending. Blocker: none for this one-time approval. Status: `VERIFIED_ENGINEERING`.

**B4.** Criterion: execute a real tool and record side-effect intent separately from outcome. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: `test_duplicate_effect_and_unknown_outcome` and `test_live_browser_mission_isolates_users`. Positive: the marker file contained `owner-only` and the live page's click handler set `CLICKED`, which was not present before JavaScript ran. The browser evidence file stayed `performed_unverified`. The mission claim for that click is `unverified`. Negative: a failed outcome write left `EXECUTING` until the same worker's authenticated recover recorded `OUTCOME_UNKNOWN` and did not write the marker again. A second constructor does not sweep a live worker. Dependency: B1 and A1. Review: pending. Blocker: mission `verified` is an independent file receipt, not untrusted DOM text. Status: `VERIFIED_ENGINEERING`.

**B5.** Criterion: pause, cancel, resume, and preserve `INTERRUPTED_UNKNOWN` / `OUTCOME_UNKNOWN`. Files: `orca/sovereign_mission/states.py`, `orca/sovereign_mission/service.py`. Test: `test_cancel_before_effect_and_after_uncertain_outcome` and `test_live_cancel_revoke_and_crash_do_not_claim_success`. Positive: cancel before an effect confirmed `CANCELLED`; a killed Chrome became `INTERRUPTED_UNKNOWN`; a lost outcome write became `OUTCOME_UNKNOWN` after authenticated recover. Negative: cancel after `effect_started` returned `cancel_confirmed` false and a claim of `unknown`. Dependency: B1. Review: pending. Blocker: pause and resume are not implemented. The Phase 15 enum was not changed. Status: `PARTIAL`.

### C — Identity, memory, persistence

**C1.** Criterion: verified product authentication and session validation. Files: `orca/auth/store.py`, `orca/auth/crypto.py`, `orca/auth/middleware.py`. Test: `test_bad_password_expired_and_revoked_tokens` and `test_http_denies_the_other_user`. Positive: a correct password issued a session token that read the owner's mission. Negative: a wrong password, an expired token, a revoked `jti`, a token older than `tokens_valid_after`, and a missing bearer were rejected. Dependency: auth database. Review: pending. Blocker: API keys and `orca/serve/session_store.py` were not exercised. Status: `VERIFIED_ENGINEERING`.

**C2.** Criterion: adapter in front of the deny-all runtime principal, without trusting caller claims. Files: none on this branch. `orca/core_runtime/principal.py` is on PR #115. Test: none. Positive: none. Negative: none. Dependency: PR #115 stays isolated. Review: pending. Blocker: principal module is not in this tree; it must not be switched to trust caller claims. Status: `NOT_STARTED`.

**C3.** Criterion: durable conversations, including temporary conversations, survive restart. Files: `orca/serve/conversations.py`. Test: not run. Positive: none this session. Negative: none. Dependency: conversation store. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**C4.** Criterion: memory consent, deletion, retention, and authorized search. Files: `orca/memory/deletion.py`, `orca/memory/store.py`, `orca/serve/retention.py`. Test: not run. Positive: none this session. Negative: none. Dependency: memory store. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**C5.** Criterion: two authenticated users cannot read or execute each other's conversation, memory, mission, or browser. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: `test_two_users_cannot_read_each_other`, `test_unauthorized_cancel_and_revoke_cannot_stop_a_running_mission`, and `test_live_browser_mission_isolates_users`. Positive: user B received `access_denied` for the mission, its evidence, dispatch, cancel, and revoke. During user A's open tool step, user B's calls left `_STOP`, `_LIVE`, the mission row, and the marker untouched, and A's step still finished `verified`. User B's browser profile was not created. Negative: conversation and memory isolation were not attempted. Dependency: C1. Review: pending. Blocker: conversation and memory remain untested. Same-OS-user filesystem access is not a tenant boundary. Status: `PARTIAL`.

### D — Specialist agents

**D1.** Criterion: versioned registry; unavailable roles stay unavailable. Files: `orca/agent/tool_registry.py`. Test: not run. Positive: none. Negative: none. Dependency: none. Review: pending. Blocker: this is a tool registry, not a specialist-role registry. Status: `NOT_STARTED`.

**D2.** Criterion: dispatch, bounded concurrency, deadline, and cancellation. Files: `orca/agent/runtime.py`. Test: not run. Positive: the module documents a deadline and a single execution path. Negative: not attacked. Dependency: D1. Review: pending. Blocker: not re-qualified and not tied to specialist roles. Status: `PARTIAL`.

**D3.** Criterion: delegated tools cannot escalate authority. Files: `orca/agent/delegation.py`, `orca/agent/policy.py`. Test: not run. Positive: none this session. Negative: none. Dependency: D2. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**D4.** Criterion: ten real handlers (research, planning, coding, data, retrieval, verification, security, documentation, tools, mission coordination). Files: none for that set. Test: none. Positive: none. Negative: none. Dependency: D1. Review: pending. Blocker: handlers were not added. A count of empty classes would not pass. Status: `NOT_STARTED`.

**D5.** Criterion: dependency order, evidence aggregation, and failure recovery across those handlers. Files: `orca/agent/runtime.py` replan path only. Test: not run. Positive: none. Negative: none. Dependency: D4. Review: pending. Blocker: D4. Status: `NOT_STARTED`.

### E — Proof and evidence

**E1.** Criterion: the six completion states are enforced for mission and tool results. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: `test_live_browser_mission_isolates_users`, `test_live_cancel_revoke_and_crash_do_not_claim_success`, `test_cancel_before_effect_and_after_uncertain_outcome`. Positive: the marker mission produced `verified`. Browser click produced `unverified`. Also `failed`, `unknown`, `refused`, and `authorized_not_performed`. The browser log for the click stayed `performed_unverified`. Negative: an unmet `PWNED` expectation was `FAILED`, a preexisting `CLICKED` string was not `verified`, and a killed browser was not `verified`. Dependency: B4. Review: pending. Blocker: none for these names. `verified` at the mission layer is an independent receipt, not the browser tool's own `verified`. Status: `VERIFIED_ENGINEERING`.

**E2.** Criterion: provenance and digests, without treating a hash as authorship. Files: `orca/sovereign_mission/store.py`, `orca/browser_engine/engine.py`. Test: `test_evidence_aggregate_mismatch_is_withheld` and the live evidence assertions. Positive: evidence stores `content_sha256` and the browser log stores hashes. Negative: changing the aggregate hash made the claim `withheld` and returned no records. Dependency: E1. Review: pending. Blocker: a caller who rewrites the record, its hash, and the aggregate together is not detected. There is no external witness. Status: `VERIFIED_ENGINEERING`.

**E3.** Criterion: a missing, forged, stale, or unverifiable effect cannot be reported as success. Files: `orca/sovereign_mission/service.py`, `orca/sovereign_mission/states.py`. Test: `test_approval_expiry_replay_and_public_browser_refusal`, `test_revoke_before_dispatch_and_evidence_tamper`, `test_duplicate_effect_and_unknown_outcome`. Positive: the intact marker mission reported `verified` only after the file existed. Negative: expired approval wrote nothing; tampered `record_json` was `withheld`; `OUTCOME_UNKNOWN` and `INTERRUPTED_UNKNOWN` cannot transition to `COMPLETED_VERIFIED`. Dependency: E1. Review: pending. Blocker: full evidence replacement by a database writer is the E2 residual. Status: `VERIFIED_ENGINEERING`.

**E4.** Criterion: redaction and tenant boundaries on evidence. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: live mission evidence assertions and `test_http_denies_the_other_user`. Positive: the evidence JSON contained neither `CLICKED` nor the page's instruction sentence, and user B's evidence response did not contain the marker text. Negative: user B received 403. Dependency: C5. Review: pending. Blocker: process logs outside these evidence files were not audited. Status: `VERIFIED_ENGINEERING`.

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

**J1.** Criterion: authentication before protected data, deny by default. Files: `orca/sovereign_mission/routes.py`, `orca/sovereign_mission/service.py`, `orca/auth/middleware.py`. Test: `test_http_denies_the_other_user` and `test_unauthorized_cancel_and_revoke_cannot_stop_a_running_mission`. Positive: the owner's bearer token created, approved, and dispatched a marker. Negative: a missing bearer returned 401. The other user's approval, evidence, cancel, and revoke requests returned 403 and did not include the objective. A body field `owner_user_id` did not select the owner. Dependency: C1. Review: pending. Blocker: routes outside `/api/sovereign` were not re-run. Status: `VERIFIED_ENGINEERING`.

**J2.** Criterion: tenant isolation under adversarial access. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: `test_two_users_cannot_read_each_other`, `test_unauthorized_cancel_and_revoke_cannot_stop_a_running_mission`, and the live mission test. Positive: user B could not read, dispatch, collect evidence, cancel, or revoke user A's mission. A denied cancel during `EXECUTING` left A's stop table, live browser handle, row, and marker unchanged. Negative: user B's profile directory was absent. Conversation, memory, and other resource types were not attacked. Dependency: C5. Review: pending. Blocker: isolation is enforced in the service, not by separate OS accounts. Status: `PARTIAL`.

**J3.** Criterion: cancellation is not confirmation, and revocation beats dispatch. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: `test_revoke_before_dispatch_and_evidence_tamper`, `test_owner_stop_is_durable_before_any_signal`, and `test_live_cancel_revoke_and_crash_do_not_claim_success`. Positive: revoke before dispatch wrote no marker. The owner row reached `CANCELLED` or `REVOKED` before the process stop was armed, and revoke during an open step wrote no marker. Negative: live cancel after `effect_started` was not confirmed, a cancel after the effect flag stayed `OUTCOME_UNKNOWN` across a new process, and live revoke did not report `verified`. A stop entry with no committed owner decision did not cancel the mission. Dependency: B5. Review: pending. Blocker: pause is still absent, so B5 stays partial. Status: `VERIFIED_ENGINEERING`.

**J4.** Criterion: timeouts, restart, and no unbounded retry. Files: `orca/sovereign_mission/service.py`, browser proxy timeouts, `orca/agent/runtime.py` (`_MAX_ACTION_RETRIES = 1`, read only). Test: `test_duplicate_effect_and_unknown_outcome` and `test_live_cancel_revoke_and_crash_do_not_claim_success`. Positive: a restarted process recorded `OUTCOME_UNKNOWN` or `INTERRUPTED_UNKNOWN`, and a second dispatch was `duplicate_effect_refused`. Negative: the agent retry path was not executed. Dependency: D2. Review: pending. Blocker: agent path not run. One refusal is not a durable cross-process lock. Status: `PARTIAL`.

**J5.** Criterion: no secret in logs or evidence, no hidden paid fallback. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: live evidence assertions. Positive: mission evidence and the browser JSONL omitted the rendered page text and the injected instruction. No paid API was called. Negative: server logs outside these files were not audited. Dependency: F5. Review: pending. Blocker: log audit is incomplete. Status: `PARTIAL`.

## Count

`VERIFIED_ENGINEERING`: A1, A2, A3, A4, A5, B1, B2, B3, B4, C1, E1, E2, E3, E4, J1, J3 (16).

`INDEPENDENTLY_QUALIFIED`: none.

`IMPLEMENTED_UNVERIFIED`: F1, F4 (2).

`PARTIAL`: B5, C3, C4, C5, D2, D3, F2, F3, G1, G3, H5, I1, I2, I3, I4, I5, J2, J4, J5 (19).

`NOT_STARTED`: C2, D1, D4, D5, E5, F5, G2, G4, G5, H1, H2, H3, H4 (13).

`BLOCKED_EXTERNAL`: none as a sole status. External blockers are recorded on the gates above (public browser unqualified, no Postgres re-run, no authorized model, no corpus, no founder training grant, no external evidence witness).

16 + 2 + 19 + 13 = 50. The verified fraction is 16/50. That is 32 percent. It is not 90 percent. The previous verified count on the browser parent was 5/50. This revision adds only the gates whose tests passed in this session.

Training, GPU, spending, corpus generation, protected merge, and production launch remain denied.
