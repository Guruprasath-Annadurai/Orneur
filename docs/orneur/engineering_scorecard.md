# Engineering preparation scorecard

Measured on `cursor/backend-programme-ae9d` parent `#121` `637efeceaab65193b31f7c64dd9babf0cf5634df`. Parent histories of PRs #116–#121 remain ancestors. PR #111 and PR #115 are not in this tree. This scorecard is not the 95-row acceptance register.

| Metric | Result |
| --- | --- |
| Engineering gates at `VERIFIED_ENGINEERING` | 35 / 50 (70%) |
| Engineering gates at `INDEPENDENTLY_QUALIFIED` | 0 / 50 |
| Integrated product journeys demonstrated | 0 (A–F). The authenticated local-fixture mission is an API workflow. It is not one of the named product journeys, and no frozen frontend screen was changed. |
| Official pretraining acceptance | 0 / 95 |
| Acceptance ledger SHA-256 | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
| Native checkpoints | GENESIS `INTERFACE_ONLY`. NOVUS and AETERNUM `NOT_AVAILABLE` on the canonical registry. No checkpoint was created. |
| Training authorization | `NO-GO` |

`VERIFIED_ENGINEERING` means this session implemented the behavior, ran the cited test to a passing exit, and left inspectable evidence. It does not mean Antigravity has qualified it. Documentation, an existing un-run module, or a refusal-only stub is not counted.

## Inventory

Classifications below are for `origin/main` plus this branch. Open PR #115 (`5ead4b426cd3d93705119f00353448bdea4bac4f`) is not in this tree. Its read-only browser, voice, and opportunity modules stay on that branch.

- `IMPLEMENTED_AND_VERIFIED` this session: pause/resume before effects; deny-all principal adapter; ten specialist handlers and DAG orchestrator; local evidence recompute; upload store; usage accounting that refuses paid backends; honest voice unavailable contract. Prior browser/mission gates remain. Independent qualification stays 0. No pretraining acceptance row was added.
- `IMPLEMENTED_BUT_UNQUALIFIED`: `orca/mission/state_machine.py`, `orca/mission/mission_store.py`, `orca/agent/runtime.py`, `orca/rse/imp1/locks.py` (all seven locks return false). The Phase 15 mission store was not re-run and was not used.
- `PARTIAL_OR_CONTRACT_ONLY`: opportunity discovery without a live source; voice retention of synthetic transcripts; conversation temporary-chat follow-up remains Claude-owned; Phase 15 mission enum unchanged.
- `MISSING_OR_BLOCKED`: public browser destinations, PR #115 merge, native training (denied), effective browser memory cap, external evidence witness, speech backend, paid model calls.

## Gates

Owner for new work is Cursor. Independent review is `pending` unless noted. Positive and negative evidence refer to commands that actually finished.

### A — Browser

**A1.** Criterion: a real Chrome process renders a local JavaScript page. Files: `orca/browser_engine/engine.py`. Test: `tests/test_browser_engine.py::test_live_local_workflow_and_isolation`. Positive: `innerText` became `JS-RENDERED` and no longer contained `STATIC`. Negative: live test skips, and does not pass, when the real binary is absent. Dependency: local Chrome, not CI. Review: pending. Blocker: none for this host. Status: `VERIFIED_ENGINEERING`.

**A2.** Criterion: click, fill, scroll, a second tab, a PNG screenshot, and an evidence file. Files: `orca/browser_engine/engine.py`. Test: same live test. Positive: page showed `CLICKED`, `hello-field`, `SCROLLED`, `SECOND-PAGE`, and a PNG. Negative: fill and scroll raise `fill_failed` or `scroll_failed` when the observed value does not change. Dependency: A1. Review: pending. Blocker: none on this host. Status: `VERIFIED_ENGINEERING`.

**A3.** Criterion: per-user profiles, short grants, page text is not authority, resume checks state. Files: `orca/browser_engine/engine.py`, `orca/browser_engine/policy.py`. Test: live workflow plus `test_grant_bounds_and_download_names` and `test_page_text_cannot_grant_authority`. Positive: user B's page showed `EMPTY` after user A's `secret=alpha` cookie; resume restored the cookie only with matching state. Negative: tampered state is `resume_refused`; captcha is `unsupported_challenge`; evidence file does not contain the page text. Dependency: A1. Review: pending. Blocker: the engine still does not accept a product session by itself. Sovereign Mission issues the loopback grant after authentication. Status: `VERIFIED_ENGINEERING`.

**A4.** Criterion: metadata, private, rebinding, redirect, and download traversal are refused. Files: `orca/browser_engine/policy.py`, `orca/browser_engine/proxy.py`, `orca/browser_engine/engine.py`. Tests: `test_network_policy_refusals`, `test_dns_rebinding_is_refused_before_connect`, `test_proxy_refuses_metadata_private_and_rebinding`, `test_allowlist_port_does_not_open_other_ports`, `test_cgnat_and_unique_local_are_refused`, `test_ipv6_allowlist_and_unbracketed_connect`, `test_grant_bounds_and_download_names`, live redirect. Positive: allowed loopback HTTP is forwarded. Negative: `169.254.169.254`, metadata CONNECT, private `10.1.2.3`, `100.64.1.5`, unique-local IPv6, alternating DNS, unbracketed IPv6 CONNECT, `../escape.txt`, and a live redirect to metadata. Dependency: Chrome uses the proxy, including loopback (`--proxy-bypass-list=<-loopback>`). Review: pending. Blocker: a live public HTTPS tunnel was not opened. Status: `VERIFIED_ENGINEERING`.

**A5.** Criterion: no `--no-sandbox`, cancel during navigation, crash becomes `browser_dead`, resource limits are set. Files: `orca/browser_engine/engine.py`. Tests: `test_wrapper_binary_is_refused`, `test_live_cancel_and_crash`, live cmdline check. Positive: live command line had `--remote-debugging-pipe` and no `--no-sandbox` or `--remote-debugging-port`; profile processes had no listening TCP port; CPU, open-file, and file-size limits were not `unlimited`. Negative: wrapper script and symlink refused; cancel and `SIGKILL` failed the next call closed. Dependency: A1. Review: pending. Blocker: no effective memory cap. `RLIMIT_AS` aborts this Chrome (signal 5). The memory cgroup directory was not writable. Status: `VERIFIED_ENGINEERING`.

### B — Mission

**B1.** Criterion: an authenticated user creates a mission and the objective is persisted. Files: `orca/sovereign_mission/service.py`, `orca/auth/store.py`. Test: `tests/test_browser_sovereign_mission.py::test_two_users_cannot_read_each_other` and `test_http_denies_the_other_user`. Positive: the owner read the stored objective after a new `SovereignMission()` and after an HTTP create. Negative: the other user's HTTP and service reads returned `access_denied` and did not include the objective. Dependency: the product SQLite auth database. Review: pending. Blocker: the Phase 15 Postgres store was not used. Status: `VERIFIED_ENGINEERING`.

**B2.** Criterion: an explicit plan and stored steps classified by capability and risk. Files: `orca/sovereign_mission/service.py`. Test: `test_refuses_unapproved_tampered_and_unqualified_actions` and `test_live_browser_mission_isolates_users`. Positive: the browser step was stored with risk `local_fixture`. Negative: `shell` is `capability_unavailable`; `download` is `action_unqualified`; a click without a `#` selector is `plan_refused`; `https://example.com` and `http://localhost` are `public_browser_unqualified`. Dependency: B1. Review: pending. Blocker: none for this classifier. Status: `VERIFIED_ENGINEERING`.

**B3.** Criterion: no execution without a fresh approval. Files: `orca/sovereign_mission/service.py`. Test: `test_approval_expiry_replay_and_public_browser_refusal`, `test_refuses_unapproved_tampered_and_unqualified_actions`, `test_concurrent_dispatch_runs_one_effect`. Positive: an approved local marker ran once. Negative: dispatch before approval is `not_authorized`; a second approval is `approval_replay_refused`; the other user is `access_denied`; an expired approval writes no file; a changed approval destination is `approval_refused`; two overlapping dispatches produced one file. Dependency: B1. Review: pending. Blocker: none for this one-time approval. Status: `VERIFIED_ENGINEERING`.

**B4.** Criterion: execute a real tool and record side-effect intent separately from outcome. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: `test_duplicate_effect_and_unknown_outcome` and `test_live_browser_mission_isolates_users`. Positive: the marker file contained `owner-only` and the live page's click handler set `CLICKED`, which was not present before JavaScript ran. The browser evidence file stayed `performed_unverified`. The mission claim for that click is `unverified`. Negative: a failed outcome write left `EXECUTING` until the same worker's authenticated recover recorded `OUTCOME_UNKNOWN` and did not write the marker again. A second constructor does not sweep a live worker. Dependency: B1 and A1. Review: pending. Blocker: mission `verified` is an independent file receipt, not untrusted DOM text. Status: `VERIFIED_ENGINEERING`.

**B5.** Criterion: pause, cancel, resume, and preserve `INTERRUPTED_UNKNOWN` / `OUTCOME_UNKNOWN`. Files: `orca/sovereign_mission/states.py`, `orca/sovereign_mission/service.py`. Tests: `tests/test_mission_pause.py`, `test_cancel_before_effect_and_after_uncertain_outcome`. Positive: pause from `AUTHORIZED` stored `PAUSED`; resume returned `AUTHORIZED` and then wrote the marker once; cancel from `PAUSED` confirmed `CANCELLED` with no file. Negative: dispatch while paused is `not_authorized`; pause after a completed effect is `pause_unsafe` or `pause_refused`; the other user received `access_denied`. Dependency: B1. Review: pending. Blocker: pause is refused after any `effect_started`. There is no pause during `EXECUTING`. The Phase 15 enum was not changed. Status: `VERIFIED_ENGINEERING`.

### C — Identity, memory, persistence

**C1.** Criterion: verified product authentication and session validation. Files: `orca/auth/store.py`, `orca/auth/crypto.py`, `orca/auth/middleware.py`. Test: `test_bad_password_expired_and_revoked_tokens` and `test_http_denies_the_other_user`. Positive: a correct password issued a session token that read the owner's mission. Negative: a wrong password, an expired token, a revoked `jti`, a token older than `tokens_valid_after`, and a missing bearer were rejected. Dependency: auth database. Review: pending. Blocker: API keys and `orca/serve/session_store.py` were not exercised. Status: `VERIFIED_ENGINEERING`.

**C2.** Criterion: adapter in front of the deny-all runtime principal, without trusting caller claims. Files: `orca/governance/deny_principal.py`. Test: `tests/test_deny_principal.py`. Positive: none — every call is a denial. Negative: `authenticate()` with founder/admin claims, empty claims, and `authorize()` all raised `principal_not_authenticated`. Dependency: PR #115 stays isolated and was not copied. Review: pending. Blocker: this adapter is not the #115 `core_runtime` module. Status: `VERIFIED_ENGINEERING`.

**C3.** Criterion: durable conversations, including temporary conversations, survive restart. Files: `orca/serve/conversations.py`. Test: not run. Positive: none this session. Negative: none. Dependency: conversation store. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**C4.** Criterion: memory consent, deletion, retention, and authorized search. Files: `orca/memory/deletion.py`, `orca/memory/store.py`, `orca/serve/retention.py`. Test: not run. Positive: none this session. Negative: none. Dependency: memory store. Review: pending. Blocker: not re-qualified. Status: `PARTIAL`.

**C5.** Criterion: two authenticated users cannot read or execute each other's conversation, memory, mission, or browser. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`, `orca/serve/conversations.py`, `orca/memory`. Tests: `test_two_users_cannot_read_each_other`, `tests/test_b_conversations.py::test_other_users_cannot_read_search_export_or_delete_a_conversation`, `tests/test_memory_security.py::test_cross_user_memory_does_not_leak_via_recall`. Positive: user B received `access_denied` on the owner's mission; conversation search/export/delete by the other user failed; memory recall did not leak the other scope. Negative: same-OS-user filesystem access is not a tenant boundary. Dependency: C1. Review: pending. Blocker: OS identity is shared. Status: `VERIFIED_ENGINEERING`.

### D — Specialist agents

**D1.** Criterion: versioned registry; unavailable roles stay unavailable. Files: `orca/specialists/registry.py`. Test: `tests/test_specialists.py::test_registry_hides_disabled_roles`. Positive: version `orneur.specialists/1` listed only `research` when that was the enabled set. Negative: `coding` raised `role_unavailable`. Dependency: none. Review: pending. Blocker: none for this registry. `orca/agent/tool_registry.py` is unchanged. Status: `VERIFIED_ENGINEERING`.

**D2.** Criterion: dispatch, bounded concurrency, deadline, and cancellation. Files: `orca/specialists/orchestrator.py`. Tests: `test_orchestrator_orders_and_aggregates_evidence`, `test_orchestrator_cancel_and_unknown_irreversible`, `test_cancel_during_dispatch_is_observed`. Positive: three dependent specialists ran in order with `max_workers=2`. Negative: pre-cancel and mid-dispatch cancel raised `cancelled`; irreversible work without a receipt stayed `unknown`. Dependency: D1. Review: pending. Blocker: `orca/agent/runtime.py` was not the dispatch path under test. Status: `VERIFIED_ENGINEERING`.

**D3.** Criterion: delegated tools cannot escalate authority. Files: `orca/specialists/orchestrator.py`. Test: `test_orchestrator_blocks_privilege_escalation_and_cross_tenant`. Positive: a coding task with `code.read` ran only with that grant. Negative: `security.read` on a runtime that only had `code.read` raised `privilege_escalation`; a foreign `tenant_id` raised `tenant_mismatch`. Dependency: D2. Review: pending. Blocker: Phase 8 `orca/agent/delegation.py` was not re-run. Status: `VERIFIED_ENGINEERING`.

**D4.** Criterion: ten real handlers (research, planning, coding, data, retrieval, verification, security, documentation, tools, mission coordination). Files: `orca/specialists/handlers.py`. Test: `test_ten_handlers_are_distinct_and_useful` and `test_coding_refuses_eval_and_does_not_run_it`. Positive: research split two subquestions and invented no sources; planning ordered `a` then `b`; coding listed `add` without executing; data analysis mean 3; retrieval cited only the tenant document; verification matched `digest(record)`; security flagged `AKIA…` and `169.254.169.254`; documentation extracted `ping`; tool execution hashed `abc`; mission coordination refused `OUTCOME_UNKNOWN` as verified. Negative: `eval` is `refused` and `executed` is false; `tool=shell` is `tool_refused`; cycles are `cycle_refused`. Dependency: D1. Review: pending. Blocker: research without fixtures is `unavailable`, not a live search. Status: `VERIFIED_ENGINEERING`.

**D5.** Criterion: dependency order, evidence aggregation, and failure recovery across those handlers. Files: `orca/specialists/orchestrator.py`. Test: `test_orchestrator_orders_and_aggregates_evidence`. Positive: planning then coding then documentation; `evidence_sha256` was produced. Negative: a failed dependency is `dependency_failed`; unknown irreversible work does not become completed. Dependency: D4. Review: pending. Blocker: durable specialist task rows are in-memory for the call only. Status: `VERIFIED_ENGINEERING`.

### E — Proof and evidence

**E1.** Criterion: the six completion states are enforced for mission and tool results. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: `test_live_browser_mission_isolates_users`, `test_live_cancel_revoke_and_crash_do_not_claim_success`, `test_cancel_before_effect_and_after_uncertain_outcome`. Positive: the marker mission produced `verified`. Browser click produced `unverified`. Also `failed`, `unknown`, `refused`, and `authorized_not_performed`. The browser log for the click stayed `performed_unverified`. Negative: an unmet `PWNED` expectation was `FAILED`, a preexisting `CLICKED` string was not `verified`, and a killed browser was not `verified`. Dependency: B4. Review: pending. Blocker: none for these names. `verified` at the mission layer is an independent receipt, not the browser tool's own `verified`. Status: `VERIFIED_ENGINEERING`.

**E2.** Criterion: provenance and digests, without treating a hash as authorship. Files: `orca/sovereign_mission/store.py`, `orca/browser_engine/engine.py`. Test: `test_evidence_aggregate_mismatch_is_withheld` and the live evidence assertions. Positive: evidence stores `content_sha256` and the browser log stores hashes. Negative: changing the aggregate hash made the claim `withheld` and returned no records. Dependency: E1. Review: pending. Blocker: a caller who rewrites the record, its hash, and the aggregate together is not detected. There is no external witness. Status: `VERIFIED_ENGINEERING`.

**E3.** Criterion: a missing, forged, stale, or unverifiable effect cannot be reported as success. Files: `orca/sovereign_mission/service.py`, `orca/sovereign_mission/states.py`. Test: `test_approval_expiry_replay_and_public_browser_refusal`, `test_revoke_before_dispatch_and_evidence_tamper`, `test_duplicate_effect_and_unknown_outcome`. Positive: the intact marker mission reported `verified` only after the file existed. Negative: expired approval wrote nothing; tampered `record_json` was `withheld`; `OUTCOME_UNKNOWN` and `INTERRUPTED_UNKNOWN` cannot transition to `COMPLETED_VERIFIED`. Dependency: E1. Review: pending. Blocker: full evidence replacement by a database writer is the E2 residual. Status: `VERIFIED_ENGINEERING`.

**E4.** Criterion: redaction and tenant boundaries on evidence. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: live mission evidence assertions and `test_http_denies_the_other_user`. Positive: the evidence JSON contained neither `CLICKED` nor the page's instruction sentence, and user B's evidence response did not contain the marker text. Negative: user B received 403. Dependency: C5. Review: pending. Blocker: process logs outside these evidence files were not audited. Status: `VERIFIED_ENGINEERING`.

**E5.** Criterion: an independent party can re-verify a result. Files: `orca/sovereign_mission/verify.py`. Test: `tests/test_evidence_reverify.py`. Positive: `verify_record` and `verify_aggregate` matched recomputed SHA-256; a marker file with the expected text was `verified`. Negative: a wrong aggregate or missing file is `mismatch` / `missing`. Dependency: E2. Review: pending. Blocker: the witness is `local_recompute`. A writer who replaces record, hash, and aggregate together still matches. No external immutable witness exists. Status: `VERIFIED_ENGINEERING`.

### F — Model gateway

**F1.** Criterion: native families keep canonical identity. Files: `orca/serve/model_identity.py`, `orca/serve/usage.py`, `orca/rse/imp1/locks.py`. Test: `tests/test_uploads_usage_identity.py::test_model_identity_keeps_external_name` and `test_usage_refuses_paid_and_native_mislabel`. Positive: an OpenAI-backed response kept `served_model=gpt-test` and `backend=openai`. Negative: recording usage as family `genesis` with backend `ollama` raised `native_identity_refused`. Dependency: none. Review: pending. Blocker: no native checkpoint exists. Status: `VERIFIED_ENGINEERING`.

**F2.** Criterion: missing providers return unavailable, not a native name. Files: `orca/serve/availability.py`. Test: `tests/test_model_availability.py`. Positive: `discover(installed=[])` reported GENESIS/NOVUS/AETERNUM and Ollama as `NOT_AVAILABLE`. Negative: a missing resolver returned `provider_unavailable` with `served_model=None`; an OpenAI resolution while spending is denied returned `paid_backend_refused` and did not keep `gpt-test`. Dependency: no authorized local model in this session. Review: pending. Blocker: `resolve_tier_backend` itself was not rewritten. Status: `VERIFIED_ENGINEERING`.

**F3.** Criterion: streaming, cancellation, and timeouts. Files: `orca/serve/streaming.py`. Test: `tests/test_serve_streaming.py` (18 passed, 1 skipped this session). Positive: helper yields in order; client-disconnect tests close the generator. Negative: admission rejects at capacity; shutdown refuses new work. Dependency: a real model backend is still absent. Review: pending. Blocker: no authorized model was called; the skipped case is not a pass. Status: `PARTIAL`.

**F4.** Criterion: fallback cannot present an external model as GENESIS, NOVUS, or AETERNUM. Files: `orca/serve/model_identity.py`, `orca/serve/usage.py`. Test: `test_model_identity_keeps_external_name`. Positive: `served_model` stayed `gpt-test` with `substitution_reason=cost_routing_escalation`. Negative: `genesis` did not appear as `served_model`. Dependency: F2. Review: pending. Blocker: full `routing.py` fallback was not executed against a live registry. Status: `VERIFIED_ENGINEERING`.

**F5.** Criterion: usage accounting with no paid call and no download. Files: `orca/serve/usage.py`. Test: `test_usage_refuses_paid_and_native_mislabel`. Positive: local backend recorded 3/5 tokens; `paid_calls` stayed 0; the other user's snapshot had 0 calls. Negative: `backend=openai` raised `paid_backend_refused` while spending is unauthorized. Dependency: F2. Review: pending. Blocker: this is process-local, not a billing system. Status: `VERIFIED_ENGINEERING`.

### G — Code, files, retrieval

**G1.** Criterion: untrusted code runs only inside a real isolation boundary. Files: `orca/code/untrusted.py`, `orca/mission/sandbox_executor.py`. Test: `tests/test_authorized_document_task.py::test_untrusted_code_stays_disabled_without_isolator`. Positive: none — execution is refused. Negative: with no docker binary, `execute` raised `isolation_unavailable`. Dependency: Docker or an equivalent isolator. Review: pending. Blocker: this host has no docker; untrusted execution stays disabled. AST filtering is not treated as a pass. Status: `PARTIAL`.

**G2.** Criterion: uploads are size-limited, parsed safely, and isolated by user. Files: `orca/serve/uploads.py`. Test: `tests/test_uploads_usage_identity.py::test_uploads_are_tenant_separated`. Positive: user A stored and read `note.txt`. Negative: user B `not_found`; `../escape.txt` refused; payload over 1 MiB refused; delete removed the file. Dependency: G1. Review: pending. Blocker: this is directory isolation, not a container. Status: `VERIFIED_ENGINEERING`.

**G3.** Criterion: retrieval returns real citations the caller is allowed to see. Files: `orca/docs/authorized_task.py`, `orca/serve/citations.py`. Test: `tests/test_authorized_document_task.py::test_authenticated_document_task_cites_only_owner_bytes`. Positive: citations pointed at `note.txt` and excerpt hashes matched the supplied passages. Negative: user B could not read user A's upload. Dependency: G2. Review: pending. Blocker: keyword retrieval, not live Deep RAG / Ollama embeddings. Status: `VERIFIED_ENGINEERING`.

**G4.** Criterion: synthetic retrieval stays labeled synthetic. Files: `orca/serve/citations.py`, `orca/specialists/handlers.py`. Test: `tests/test_citation_synthetic_label.py` and specialist retrieval in `test_ten_handlers_are_distinct_and_useful`. Positive: `[D1]` from a fixture kept `synthetic=true`; specialist citations copied the document flag. Negative: an unlabeled uploaded excerpt stayed `synthetic=false`. Dependency: G3. Review: pending. Blocker: this labels caller-supplied flags; it does not detect unlabeled synthetic text automatically. Status: `VERIFIED_ENGINEERING`.

**G5.** Criterion: one authenticated document or code task returns evidence. Files: `orca/docs/authorized_task.py`. Test: `tests/test_authorized_document_task.py`. Positive: upload, keyword retrieval, citation hashes, and `verified=true` for user A's document; delete reported `local_absent` and did not claim other replicas. Negative: user B `not_found` on A's file; untrusted code is `isolation_unavailable`. Dependency: G2, G3. Review: pending. Blocker: not a live model-grounded chat turn. Status: `VERIFIED_ENGINEERING`.

### H — Opportunity, voice, relay

**H1.** Criterion: opportunity records with provenance, timestamps, and deduplication from a real source. Files: none on this branch. `orca/core_runtime/opportunity.py` is on PR #115. Test: none here. Positive: none. Negative: none. Dependency: an authorized data source, which was not added. Review: pending. Blocker: no live source, and this branch does not absorb PR #115. Status: `NOT_STARTED`.

**H2.** Criterion: user-owned saved opportunities and an explained ranking. Files: `orca/opportunity/bridge.py`. Test: `tests/test_opportunity_voice.py::test_opportunity_unavailable_without_live_feed`. Positive: fixture listings for user A could be saved and ranked. Negative: ranking as another user is `access_denied`; `live_source` save is refused; `execute_external` is `execution_not_authorized`. Dependency: H1. Review: pending. Blocker: listings are caller fixtures, not a live feed. Status: `PARTIAL`.

**H3.** Criterion: speech input and output contracts with an honest unavailable state. Files: `orca/voice/contracts.py`. Test: `tests/test_opportunity_voice.py::test_voice_unavailable_and_consent`. Positive: capability reports `NOT_AVAILABLE` and `provider=None`. Negative: `transcribe` with consent raised `speech_unavailable`; without consent raised `consent_required`. Dependency: a real speech backend. No speech backend was called. Review: pending. Blocker: no backend. Status: `VERIFIED_ENGINEERING`.

**H4.** Criterion: audio consent, retention, and deletion. Files: `orca/voice/contracts.py`. Test: `test_voice_unavailable_and_consent`. Positive: a synthetic transcript retained with consent could be deleted. Negative: the other user could not read it; transcribe without consent is `consent_required`. Dependency: H3. Review: pending. Blocker: no audio bytes were recognized; retention is in-process. Status: `PARTIAL`.

**H5.** Criterion: authenticated relay for missions and files, with no new OAuth or background permission. Files: `orca/mission/relay_store.py`, `orca/mission/relay_security.py`. Test: not run. Positive: none. Negative: no OAuth provider was enabled by this branch. Dependency: B1. Review: pending. Blocker: not re-qualified and not connected to the browser. Status: `PARTIAL`.

### I — Pretraining foundation

**I1.** Criterion: GENESIS shape and math checks on synthetic CPU fixtures, with no new weights. Files: `orca/train/dryrun/`. Test: not run this session. Positive: none. Negative: training locks still return false in source. Dependency: existing dry-run package. Review: pending. Blocker: not re-run. No weights were written. Status: `PARTIAL`.

**I2.** Criterion: tokenizer integrity and dataset admission using synthetic fixtures only. Files: `orca/train/dryrun/`. Test: not run. Positive: none. Negative: no corpus was read and the acceptance ledger hash is unchanged. Dependency: founder authorization for any real corpus. Review: pending. Blocker: tokenizer work was not added, and protected corpus use is denied. Status: `PARTIAL`.

**I3.** Criterion: CPU dry-run of loss, gradients, optimizer, seeds, and NaN rejection on toy data. Files: `orca/train/dryrun/toy.py`, `orca/train/dryrun/harness.py`. Test: not run. Positive: none. Negative: `training_authorized()` returns false. Dependency: I1. Review: pending. Blocker: not re-run. A passing dry run would still not be pretraining. Status: `PARTIAL`.

**I4.** Criterion: atomic checkpoint publication, crash recovery, and stale-checkpoint refusal. Files: `orca/train/dryrun/ckpt.py`. Test: not run. Positive: none. Negative: no checkpoint was published. Dependency: I3. Review: pending. Blocker: not re-run. Status: `PARTIAL`.

**I5.** Criterion: separate GENESIS, NOVUS, and AETERNUM contracts, evaluation without invented scores, and a read-only compute note. Files: `orca/train/genesis_eval.py`, `orca/train/novus_eval.py`, `orca/train/aeternum_eval.py`, `orca/rse/imp1/locks.py`. Test: not run. Positive: none. Negative: no family was promoted and no GPU was requested. This session did not measure the host's CPU or RAM, so no feasibility number is claimed. Dependency: no native checkpoint exists. Review: pending. Blocker: not re-run. Status: `PARTIAL`.

### J — Security and reliability

**J1.** Criterion: authentication before protected data, deny by default. Files: `orca/sovereign_mission/routes.py`, `orca/sovereign_mission/service.py`, `orca/auth/middleware.py`. Test: `test_http_denies_the_other_user` and `test_unauthorized_cancel_and_revoke_cannot_stop_a_running_mission`. Positive: the owner's bearer token created, approved, and dispatched a marker. Negative: a missing bearer returned 401. The other user's approval, evidence, cancel, and revoke requests returned 403 and did not include the objective. A body field `owner_user_id` did not select the owner. Dependency: C1. Review: pending. Blocker: routes outside `/api/sovereign` were not re-run. Status: `VERIFIED_ENGINEERING`.

**J2.** Criterion: tenant isolation under adversarial access. Files: `orca/sovereign_mission/service.py`, `orca/serve/conversations.py`, `orca/memory`, `orca/serve/uploads.py`, `orca/specialists/orchestrator.py`. Tests: mission isolation tests, `test_other_users_cannot_read_search_export_or_delete_a_conversation`, `test_cross_user_memory_does_not_leak_via_recall`, `test_uploads_are_tenant_separated`, `test_orchestrator_blocks_privilege_escalation_and_cross_tenant`. Positive: the other user could not read missions, conversations, memories, or uploads. Negative: OS accounts are still shared. Dependency: C5. Review: pending. Blocker: isolation is in process and path hashes, not separate UIDs. Status: `VERIFIED_ENGINEERING`.

**J3.** Criterion: cancellation is not confirmation, and revocation beats dispatch. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: `test_revoke_before_dispatch_and_evidence_tamper`, `test_owner_stop_is_durable_before_any_signal`, and `test_live_cancel_revoke_and_crash_do_not_claim_success`. Positive: revoke before dispatch wrote no marker. The owner row reached `CANCELLED` or `REVOKED` before the process stop was armed, and revoke during an open step wrote no marker. Negative: live cancel after `effect_started` was not confirmed, a cancel after the effect flag stayed `OUTCOME_UNKNOWN` across a new process, and live revoke did not report `verified`. A stop entry with no committed owner decision did not cancel the mission. Dependency: B5. Review: pending. Blocker: pause is still absent, so B5 stays partial. Status: `VERIFIED_ENGINEERING`.

**J4.** Criterion: timeouts, restart, and no unbounded retry. Files: `orca/sovereign_mission/service.py`, browser proxy timeouts, `orca/agent/runtime.py` (`_MAX_ACTION_RETRIES = 1`, read only). Test: `test_duplicate_effect_and_unknown_outcome` and `test_live_cancel_revoke_and_crash_do_not_claim_success`. Positive: a restarted process recorded `OUTCOME_UNKNOWN` or `INTERRUPTED_UNKNOWN`, and a second dispatch was `duplicate_effect_refused`. Negative: the agent retry path was not executed. Dependency: D2. Review: pending. Blocker: agent path not run. One refusal is not a durable cross-process lock. Status: `PARTIAL`.

**J5.** Criterion: no secret in logs or evidence, no hidden paid fallback. Files: `orca/sovereign_mission/service.py`, `orca/browser_engine/engine.py`. Test: live evidence assertions. Positive: mission evidence and the browser JSONL omitted the rendered page text and the injected instruction. No paid API was called. Negative: server logs outside these files were not audited. Dependency: F5. Review: pending. Blocker: log audit is incomplete. Status: `PARTIAL`.

## Count

`VERIFIED_ENGINEERING`: A1, A2, A3, A4, A5, B1, B2, B3, B4, B5, C1, C2, C5, D1, D2, D3, D4, D5, E1, E2, E3, E4, E5, F1, F2, F4, F5, G2, G3, G4, G5, H3, J1, J2, J3 (35).

`INDEPENDENTLY_QUALIFIED`: none.

`IMPLEMENTED_UNVERIFIED`: none.

`PARTIAL`: C3, C4, F3, G1, H2, H4, H5, I1, I2, I3, I4, I5, J4, J5 (14).

`NOT_STARTED`: H1 (1).

`BLOCKED_EXTERNAL`: none as a sole status. External blockers remain: public browser unqualified, no Postgres re-run, no authorized model, no corpus, no founder training grant, no external evidence witness.

35 + 0 + 14 + 1 = 50. The verified fraction is 35/50. That is 70 percent. Independent qualification remains 0/50. H1 stays not started because no authorized live opportunity source exists. Pretraining I-gates stay partial: authorization and checkpoint tests passed here; sentinel child tests failed on this host (`pydantic` missing in the isolated interpreter) and are not counted as a pass. Exact-head CI for `43020779f23d3cc475a341cbd02d52ea6a2079cf`: GitHub Actions run `40569838397` (9/9).

Training, GPU, spending, corpus generation, protected merge, and production launch remain denied.
