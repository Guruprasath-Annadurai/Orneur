# ORNEUR — Native GENESIS Foundation Finalization: Audit #075 Remediation

**Directive**: "Native GENESIS Foundation Finalization: Execution Isolation & Dataset Integrity" (Mission A–F), followed by a CTO pre-handoff security directive independently challenging the resulting architecture before any `READY_FOR_INDEPENDENT_REAUDIT` claim.

**Starting point**: PR #73 (`claude/genesis-native-learning-engine-phase1-2026-10-17`), commit `5a1f095bb89852554883768cbdf81cf517c89dc2`.
**Independent successor Audit #075**: PR #75 (`antigravity/genesis-audit74-successor-requalification`), commit `41722fe1ab610e9d2a0e7c3cf20e704b32713735`, verdict `CONDITIONAL_REMEDIATION_REQUIRED`.
**Foundation PR #65**: `87cc7ad1a2e269de3a05edd626a61cca6fbdb760` (unchanged).

All four were verified against live `git log`/`gh pr view` output before any change.

---

## 0. How this report is organized

The CTO pre-handoff directive explicitly re-opened and challenged several claims this phase's own implementation initially made. Rather than writing one narrative and a separate "corrections" addendum, this report states the FINAL, challenged-and-answered position for each item directly — where an earlier internal draft overclaimed something, that is noted inline as "initially stated X; corrected to Y," not hidden.

---

## 1. Mission A / Mission 2 — Grant authority: the worker never fabricates authorization

**Verified property**: `orca/genesis/training/isolated_worker.py`'s `_worker_main()` calls exactly one function to obtain a `NativePretrainingGrant`: `orca.genesis.governance.authorization.authorize_native_pretraining()` — the SAME, unmodified choke point every other GENESIS caller uses. The worker never instantiates `NativePretrainingGrant(...)` directly (its constructor requires a module-private `_seal` sentinel the worker's own code never holds) and never sets `_mac` by hand. Structurally verified, not merely argued: `test_the_worker_never_constructs_a_grant_itself_only_verifies_one` (`tests/test_genesis_isolated_worker.py`) inspects the worker module's own source and asserts neither `NativePretrainingGrant(` nor `_seal=` appears in it at all.

**Synthetic test grants cannot be promoted into production authorization**, proven two ways:
1. `test_a_production_configured_worker_can_never_reach_running`: a `WorkerStartupConfig` with `test_only_bypass_founder_ledger=False` (the only field distinguishing a "test" from a "production" configuration) always fails — because the REAL, unmodified `check_founder_acceptance_ledger()` is still intentionally empty, exactly as every other GENESIS entrypoint requires today.
2. `test_test_only_founder_ledger_bypass_never_weakens_grant_signature_verification`: even WITH the test-only founder-ledger bypass active, a record with a forged/invalid Ed25519 signature is still rejected. The bypass stubs exactly one gate (the founder-acceptance ledger) and nothing else — it does not, and structurally cannot, touch `verify()`'s own Ed25519 signature check inside `authorize_native_pretraining()`.

**No founder signing keys were generated or substituted anywhere in this phase.** The test fixtures generate their OWN throwaway Ed25519 keys and their OWN throwaway registry (exactly mirroring the established pattern already used by `tests/test_audit74_successor_adversarial_requalification.py`'s own `_mint_grant()` helper) — this is a synthetic authority for a synthetic test, never claimed as, or capable of being mistaken for, a real founder-issued one. `NativePretrainingGrant`'s own per-process-random-key MAC (`authorization.py`'s `_PROCESS_KEY = secrets.token_bytes(32)`, generated fresh at import time) independently guarantees a grant minted in one process can never simply be pickled into another and trusted — which is precisely why the worker mints its OWN grant, inside its OWN process, from the raw signed inputs (`record`, `registry`, `req`), rather than receiving a pre-built grant object from its controller.

---

## 2. Mission A — Worker isolation, re-examined under the CTO directive

**Initial internal framing (corrected)**: an early draft of this module's docstring leaned on "`multiprocessing`'s `spawn` start method" and "a genuinely separate OS process" as if that alone were the isolation story. The CTO directive is right to reject that framing on its own. The current, final position:

### 2.1 UID/GID separation
Default posture: the worker runs as the SAME uid as whatever spawned it — `WorkerStartupConfig.drop_to_uid`/`drop_to_gid` exist to drop to a distinct, lower-privileged account, but this requires the spawning process to already be root, and `start()` fails closed (`IsolationPropertiesUnavailableError`) if a drop is requested but root is unavailable (`test_strict_uid_isolation_fails_closed_when_not_root`). No same-uid separation is claimed by default.

### 2.2 Unix-socket ownership and permissions
The socket directory must be owned by the current uid and have no group/other access bits (`_verify_socket_dir_isolation()`), checked both at worker bind time and at client connect time; a world-readable socket directory is refused before the worker ever binds (`test_socket_directory_accessible_to_others_is_rejected`).

### 2.3 Peer credential validation — new in this response
Socket file permissions only gate who can OPEN the socket; they do not verify who actually DID. Added `_get_peer_credentials()`, using Linux's `SO_PEERCRED` (kernel-verified `(pid, uid, gid)` of the actual connected peer — never self-reported by the peer in any message payload) to reject a connection from the wrong uid BEFORE processing any command on it. Honestly scoped: **no portable macOS-equivalent is implemented** (this phase's own development machine is macOS, where `SO_PEERCRED` does not exist); on any platform without it, this check is simply unavailable, and the worker reports that fact rather than silently proceeding as if verified.

### 2.4 Protection of signing/verification secrets
The IPC shared secret (`auth_token`) and the per-engine capability token (`TrainingStepEngine._capability_token`) are generated with `secrets.token_bytes(32)`/passed only via `multiprocessing`'s own in-memory argument-passing to a `spawn`-started child — never written to disk, an environment variable, or process argv (so never visible via `ps` or `/proc/<pid>/environ`). This is a confidentiality property against OTHER users/observers of the host, not against a same-uid co-resident process — see 2.5.

### 2.5 Linux ptrace/`/proc` and process-access assumptions, stated explicitly
A same-uid process can, on Linux, generally `ptrace` or read `/proc/<pid>/mem` of another same-uid process (subject to `ptrace_scope` and capability checks this module does not configure). **This module does not defend against that.** It is explicitly out of scope unless `drop_to_uid` achieves genuine uid separation.

### 2.6 Worker lifecycle and revocation behavior
`test_revocation_mid_session_stops_the_worker_process_entirely`: revoking the authorization mid-session causes the NEXT `step` command to fail with `AUTHORIZATION_DENIED`, and the worker process terminates itself entirely (verified via `worker.join()` + `is_alive`) — a fresh connection attempt afterward fails because no process is listening at all, not merely because that one command was refused.

### 2.7 Replay and cross-run IPC rejection
`test_replaying_a_previously_sent_message_is_rejected` (identical framed bytes resent, rejected via sequence+nonce check) and `test_a_request_for_a_different_workload_id_is_rejected` (a differently-addressed, correctly-signed message rejected before any training logic runs).

### 2.8 No client access to model, optimizer, or worker-owned execution capabilities
`test_client_never_holds_a_reference_to_the_model_optimizer_or_engine` (structural attribute check on the client object) and `test_a_forged_in_process_capability_is_never_reachable_from_the_client` (a payload that TRIES to smuggle a capability-shaped field has no effect — the wire protocol has no field for one; the worker always mints its own, internally).

### 2.9 Honest isolation-qualification reporting — the directive's own requested mechanism
`IsolatedTrainingWorker.isolation_qualification` is now set, every single `start()` call, to exactly one of three labels the worker itself computes before serving anything:
- `ISOLATION_NOT_QUALIFIED` — the default/conservative label: either peer-credential checking is unavailable on this platform, or no uid drop occurred (or both).
- `PEER_VERIFIED_SAME_UID` — `SO_PEERCRED` available, every connection's peer uid kernel-verified, but worker and client still share one uid.
- `PEER_VERIFIED_UID_SEPARATED` — `SO_PEERCRED` available AND a genuine `drop_to_uid` succeeded. **This is the only label this module considers genuine OS-level privilege isolation.**

`test_isolation_qualification_is_reported_and_never_overclaimed` proves that, on this development/CI environment (no root, macOS locally / Linux in CI without a uid drop configured), the worker NEVER reports `PEER_VERIFIED_UID_SEPARATED`.

**Per the directive's own instruction: on this environment, with the default configuration exercised by every test in this suite, the honest, final status is `ISOLATION_NOT_QUALIFIED` or, where `SO_PEERCRED` is available (Linux), `PEER_VERIFIED_SAME_UID` — never a stronger claim.** True privilege isolation (`PEER_VERIFIED_UID_SEPARATED`) is implemented and fails closed when unsatisfiable, but was not, and could not be, exercised end-to-end in this phase's own test environment (it requires root). This is reported, not asserted away.

---

## 3. Mission B — Removing production bypass paths, re-examined

**Initial internal framing (corrected)**: an early draft relied on `"pytest" in sys.modules` as part of the honesty story for `ExecutionCapability.for_unchecked_synthetic_test()`. The CTO directive correctly rejects this as a trustworthy security control (it is trivially defeated by `import pytest` or monkeypatching `sys.modules`), and this report does not retract that the guard still exists in `learning_step.py` (it does — as misuse-resistance only, explicitly documented as such and never relied upon below) — but it reframes what actually closes Mission B:

**The actual, structural closure is architectural, not a runtime check**: `orca/genesis/training/isolated_worker.py`'s own source code contains **zero references** to `ExecutionCapability.for_unchecked_synthetic_test` or to the `_unchecked` flag at all — independently verified by `test_the_worker_module_never_references_the_synthetic_test_bypass`, which inspects the actual module source via `inspect.getsource()`, not runtime behavior. There is no code path, under any configuration, no matter what `sys.modules` contains, by which the worker could ever construct or accept an unchecked capability — it only ever calls `execute_authorized_training_step()` → `TrainingStepEngine._issue_capability_for_governance()`, the real, governance-gated path, every single time.

- `revalidate_every_n_calls` (Audit #075's own named finding): removed entirely from `execute_authorized_training_step()` — not defaulted safely, deleted. There is no parameter of any name that can widen the revalidation window.
- `ExecutionCapability.for_unchecked_synthetic_test()`: still exists (required — the directive's own governing objectives and this phase's restrictions explicitly permit "synthetic, ephemeral CPU tests"), still carries the `pytest`-import guard as misuse-resistance, but is now ALSO structurally unreachable from the one real production entrypoint (the worker), which is the property that actually matters and is independently, structurally tested.
- `TrainingStepEngine._issue_capability_for_governance()`: still exists (the worker calls it, legitimately, via `execute_authorized_training_step()`), still single-underscore (Python offers no stronger access control), but a direct external caller can never reach a worker-run `TrainingStepEngine` instance at all — it is private to the worker's own process.

---

## 4. Mission C — Dataset block-store integrity, re-examined point by point

1. **Cache identity binds the complete authorized input and transformation identity**: `compute_block_store_cache_id()` hashes schema version, split, packing mode, `seq_len`, `pad_id`, `eos_id`, caller-supplied `tokenizer_digest`, and the full `authorized_shard_digests` mapping. **Honestly scoped**: `tokenizer_digest` is caller-supplied, exactly like `authorized_shard_digests` always has been — this module does not independently re-derive it from real tokenizer bytes; it binds whatever identity string the caller asserts. This mirrors the SAME, already-documented limitation `authorized_shard_digests` has always had at this layer.
2. **Collision-resistant identifier + schema version**: SHA-256 over the canonical payload above; `BLOCK_STORE_SCHEMA_VERSION = "genesis-block-store/2"`.
3. **Stable lock-file coordination for concurrent writers**: `fcntl.flock` (exclusive) on a dedicated `.lock` file, held for the entire check-cache→build→publish sequence. `test_audit075_concurrent_constructors_do_not_corrupt_each_others_build` runs 8 threads concurrently constructing against the SAME cache id and confirms every one reports an identical block count.
4. **Built in unique temp files, published only after validation + atomic replacement**: `tempfile.mkstemp()` in the same directory (same-filesystem rename guarantee), `os.fsync` on each file, `os.replace()` for the actual publish, with a best-effort directory `fsync` for durability.
5. **Readers never observe partially constructed stores**: the canonical filename only ever refers to a complete file (atomic rename), and the three files are published in a fixed order (store → digests → manifest) — the manifest, which `_load_cached_report_if_valid()` requires to exist for a cache to be trusted at all, is always the LAST thing published.
6. **Exact block byte lengths checked before decoding**: `block()` raises `BlockStoreCorruptionError` if a read does not return exactly `seq_len * 8` bytes — `test_audit075_truncated_store_file_is_rejected_not_silently_undersized`.
7. **Bound to a trusted digest or per-block integrity structure**: a second, fixed-width binary sidecar (`.digests.bin`) holds a truncated SHA-256 per block, read the same O(1) `seek()`-based way as the blocks themselves; `block()` recomputes and compares on every read — `test_audit075_post_publication_tampering_is_detected_at_read_time`.
8. **Detect post-construction tampering**: same mechanism as #7, independently demonstrated.
9. **Source verification-to-consumption race, closed**: the PRIOR version of this phase's own work (written earlier in this same session) called `_verify_shard_integrity()` once, then opened each shard file AGAIN, separately, for tokenization — leaving a TOCTOU window. **Fixed in this response**: each shard file is now read exactly ONCE per build (`path.read_bytes()`), its SHA-256 computed over those exact bytes and checked against the authorized digest, and those SAME bytes (not a fresh read) are then decoded and tokenized. The verified bytes and the consumed bytes are now provably identical, not two independent reads of a mutable file.
10. **Oversized records cannot defeat memory ceilings**: `LoaderConfig.max_tokens_per_record` (defaults to `construction_buffer_tokens`) rejects any single record producing more tokens than the configured cap — `test_audit075_max_tokens_per_record_rejects_oversized_records`.
11. **Disk exhaustion, crashes, symlink attacks fail safely**:
    - Disk exhaustion: `test_audit075_disk_exhaustion_during_construction_leaves_no_partial_publish` injects an `OSError(ENOSPC)` from `os.fsync` mid-construction and confirms no store/digests/manifest file is ever published at the canonical path, and no stray `.tmp` files remain (the pre-existing lock file itself is expected to persist — that is its own, separate, by-design lifecycle, not a leftover).
    - Crashes: the build-then-atomic-publish design means a crash at any point before the final `os.replace()` leaves the canonical path either absent or still holding a PRIOR valid publish — never a torn one.
    - Symlink attacks: `test_audit075_symlinked_lock_path_is_rejected`, plus `_load_cached_report_if_valid()`'s own symlink check on the store/manifest/digests paths.
12. **Cache paths restricted and path-substitution prevented**: all derived paths resolve underneath `Path(cfg.shard_dir).resolve()`; every one is explicitly checked `not is_symlink()` before being trusted or bound.

**Residual, honestly stated limitation, unchanged from the first draft of this work and reaffirmed here**: the per-block digest is a plain (truncated) SHA-256, not an HMAC against a secret key — it detects accidental corruption and after-the-fact tampering by a party who does not simultaneously control the digest sidecar, but it is NOT cryptographic protection against an adversary who can rewrite the store, its digest table, and its manifest together, self-consistently, in one coordinated action. The directive's own item 4 bullet 4 ("Derived-block integrity roots cannot be rewritten unnoticed by an attacker within the claimed threat model") is answered honestly here: within THIS threat model (accidental corruption, partial writes, non-simultaneous tampering, a process that bypasses the lock), rewrites ARE caught. Against a fully coordinated, simultaneous rewrite of all three files, they are not — no claim to the contrary is made.

---

## 5. Mission D — Checkpoint anti-rollback, re-examined under direct challenge

The CTO directive specifically challenged: *"Challenge simultaneous replay of an old checkpoint and old valid ledger. Determine whether rollback prevention has an independent trusted monotonic state anchor. If both checkpoint and ledger are stored under the same attacker-controlled filesystem without independent anchoring, do NOT claim full anti-rollback protection."*

**Answer, reproduced and documented, not merely asserted**: it does NOT have an independent anchor, and this phase does not claim full anti-rollback protection. `tests/test_genesis_resumable_checkpoint.py::test_audit075_simultaneous_old_checkpoint_and_old_ledger_replay_is_not_detected` independently reproduces the EXACT attack the directive names: an attacker who saved a copy of the `run_id` ledger file from an earlier, legitimate point (requiring only filesystem read access at that earlier time, and filesystem WRITE access later — never `integrity_key`, since the replayed ledger's HMAC was genuinely computed by this same process and remains valid verbatim) replaces the CURRENT ledger with that OLD snapshot, together with the matching OLD checkpoint+manifest pair, and `restore_resumable_checkpoint()` **accepts it**. The test's own assertion documents this as a known, unresolved gap — it is written to FAIL (flagging that the gap has been closed) if a future phase adds independent anchoring, not to silently pass forever as "fine."

`resumable_checkpoint.py`'s own "Rollback protection" docstring section was rewritten in this response to state this precisely: the mechanism provides HMAC field-tampering integrity and a LOCAL, process-relative monotonic claim, but checkpoint body, manifest, and ledger all share ONE filesystem trust boundary. Genuinely closing this requires an external, independently-writable-but-not-rewritable anchor (a remote append-only service, or a hardware monotonic counter) — explicitly out of scope given this phase's "no paid infrastructure" restriction.

**What IS still true and still tested, kept separate from the above (per the directive's own instruction to "keep HMAC integrity and monotonic local progress claims separate")**:
- Field-level tampering of the CURRENT, un-replayed ledger or checkpoint sidecar (editing a value in place without replacing the whole file) is still caught by HMAC (`test_audit075_tampered_ledger_file_is_rejected`, and the pre-existing sidecar-field tests).
- A rollback attempted while the CURRENT, un-replayed ledger is still in place (the simpler case — the attacker has only the old checkpoint, not a saved old ledger snapshot) is still caught (`test_audit075_rollback_to_an_older_checkpoint_is_rejected`).
- Weak-key custody is still enforced (`MIN_INTEGRITY_KEY_BYTES = 32`).

---

## 6. Mission E — Complete adversarial test inventory added this phase

| Area | Test file | Tests added |
|---|---|---|
| Block-store cache identity, concurrency, tampering, memory, disk exhaustion | `tests/test_genesis_data_loader.py` | 9 |
| Checkpoint anti-rollback, weak keys, simultaneous replay | `tests/test_genesis_resumable_checkpoint.py` | 5 |
| Governance cadence removal (covered by existing + Audit #075 evidence flip) | `tests/test_genesis_learning_governance.py` | 0 new (existing 9 unaffected; Audit #075's own cadence-bypass test now flips) |
| Isolated worker: boot, structural isolation, auth, replay, cross-workload, revocation, UID-drop fail-closed, socket perms, isolation-qualification reporting, grant-authority structural proofs | `tests/test_genesis_isolated_worker.py` | 15 (new file) |

Full qualified numerical suite (objective/gradients/checkpoints) re-run and unaffected by this phase's changes: `tests/test_genesis_synthetic_learning_proof.py` (11 tests, all still pass).

---

## 7. Mission F — Integration/merge plan

- **PR #65** (qualified foundation): unchanged this phase, confirmed zero regression (192/192 foundation tests pass).
- **PR #73** (this learning engine + Audit #074 + Audit #075 remediation): the draft branch this phase's commits land on. Recommended NEXT step is Antigravity's own re-audit of this exact commit, not a merge.
- **PR #75** (Audit #075 evidence branch): its two files (`docs/.../ORNEUR_GENESIS_AUDIT74_SUCCESSOR_REQUALIFICATION_REPORT.md`, `tests/test_audit74_successor_adversarial_requalification.py`) were imported verbatim into PR #73 for provenance; PR #75 itself should NOT be merged directly (overlapping implementation ancestry with PR #73, per the directive's own caution) — it is superseded, as evidence, by this commit.
- **No other component branches were touched or require action this phase.**
- **Outstanding factual correction to flag for Antigravity**: Audit #075's own report (Section 3.1, finding 1) describes the pre-remediation cache collision as affecting `seq_len` and tokenizer identity "or" — confirmed, both axes independently verified fixed in this phase (`test_audit075_differing_seq_len_never_collide_on_the_same_cache_path`, `test_audit075_differing_tokenizer_digest_never_collide_on_the_same_cache_path`). No other factual corrections identified.

---

## 8. Full regression results

**Full GENESIS-prefixed suite** (`tests/test_genesis*.py tests/test_audit_genesis*.py tests/test_audit74_successor_adversarial_requalification.py tests/test_native_learning_engine_adversarial_audit.py`, run to completion, post-all-fixes-in-this-response): **3290 passed, 17 skipped, 28 failed** (812.71s).

All 28 failures are confined to exactly the three historical, verbatim-imported adversarial evidence files, none of which this phase modifies:
- `tests/test_audit_genesis_hardening_adversarial.py` (5 failures) — the PRIOR Audit #71 phase's own evidence file, intentionally failing since that remediation; unrelated to this phase.
- `tests/test_audit74_successor_adversarial_requalification.py` (11 failures) — THIS phase's imported Audit #075 evidence file; every failure here is an intended flip (the vulnerability it demonstrated no longer exists) — see Sections 1–5 above for the mapping from each failing test name to the specific fix that closed it.
- `tests/test_native_learning_engine_adversarial_audit.py` (12 failures) — the PRIOR Audit #074 phase's own evidence file, unaffected by this phase, consistent with its own report's accounting.

Zero unexpected failures anywhere else across 3290 passing tests. **PR #65 foundation regression** (`test_genesis_training_orchestration.py`, `test_genesis_cross_workstream_integration.py`, `test_genesis_workstream_a_end_to_end.py`, `test_genesis_data_manifest.py`, `test_genesis_data_pipeline.py`, `test_genesis_data_contamination.py`, `test_audit_genesis_hardening_remediation.py`): **192 passed, 0 failed** — zero regression to the qualified foundation.

**Exact-head GitHub Actions CI**: verified against the actual pushed commit once available; see this report's own commit history on PR #73 for the real, observed result (not assumed in advance).

---

## 9. Residual limitations and prohibited configurations, stated without hedging

1. **`PEER_VERIFIED_UID_SEPARATED` (genuine OS-level privilege isolation) was never exercised end-to-end in this phase's own test environment** — it requires root, which this phase's CPU-only, no-paid-infrastructure test environment does not run as. The fail-closed path (refusing to proceed under a weaker isolation than requested) IS tested; the success path is implemented but unverified live.
2. **Peer-credential verification (`SO_PEERCRED`) has no macOS equivalent implemented** — on macOS, this worker always reports `ISOLATION_NOT_QUALIFIED`.
3. **Checkpoint anti-rollback has no independent trust anchor** — see Section 5. A coordinated, simultaneous replay of checkpoint + ledger together defeats it. Reproduced and documented, not fixed.
4. **The derived block-store's per-block integrity is a plain SHA-256, not an HMAC** — defends against accidental corruption and non-simultaneous tampering, not a fully coordinated rewrite of store+digests+manifest together.
5. **`tokenizer_digest` and `authorized_shard_digests` remain caller-asserted identity, not independently re-derived from raw tokenizer/dataset bytes at this layer** — unchanged, pre-existing, already-documented limitation.
6. **Linux `ptrace`/`/proc` same-uid co-resident access is not defended against** absent a genuine `drop_to_uid`.
7. **No real-corpus training, GPU allocation, paid spending, production deployment, founder grant issuance, mainline merge, or NOVUS/AETERNUM training occurred anywhere in this phase.**

**Prohibited going forward, restated from the directive**: no real model training, no founder grants, no GPU use, no production deployment, no merge to mainline, until these residual limitations are independently re-assessed.

---

## Final verdict

**`PARTIAL`**

Rationale: every Mission A–F item the directive raised has been implemented, tested, and — where this phase's OWN first draft overclaimed something — corrected and re-documented honestly under the CTO pre-handoff directive's direct challenge, with reproducing tests for both the fixes AND the two residual gaps that remain genuinely open (checkpoint anti-rollback's lack of an independent anchor; the lack of exercised, root-requiring UID-separated isolation). This is why the verdict is `PARTIAL`, not `READY_FOR_INDEPENDENT_REAUDIT`: two of the directive's own six challenge areas (Mission 2/worker isolation's strongest tier, and Mission 5/checkpoint anti-rollback's independent anchor) are honestly reported as unresolved rather than closed. Nothing in this phase should be read as a self-declared PASS on either.
