# ORNEUR — Synthetic Foundation Freeze Proposal (Founder Review)

**Prepared by**: ORNEUR engineering (Claude Code), per the CTO's post-Audit-#078 execution directive, Phase 1.
**Status**: PROPOSAL ONLY. This document requests founder review and explicit approval. It does **not** itself tag a release, merge PR #78, or mark the foundation as founder-frozen — none of those actions have been taken, and none will be taken without a separate, explicit founder decision.

---

## 1. Exact repository state proposed for freeze

| Item | Value |
|---|---|
| Draft PR | [#78](https://github.com/Guruprasath-Annadurai/Orneur/pull/78) (OPEN, draft, not merged) |
| Branch | `claude/genesis-audit077-p0-remediation-2026-10-21` |
| Exact head SHA | `55eb4fea5c5c4820db6b15e1a2aac5885bddce78` |
| Security implementation SHAs | `a58a027105687e64f6504c066f858e657cb14492`, `1ed7aa6c3170a238645ec161f90635ee84d45ccc` |
| Observed exact-head CI | [`39517769106`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39517769106) — conclusion `success`, 9/9 jobs green |
| Independent audit | Antigravity, branch `antigravity/pr78-final-targeted-requalification`, head `ed5e8b837f112cc8aa35ef2b5485deb85ff30bd5` |
| Independent audit's own test suite | `tests/test_audit078_final_requalification.py` (imported verbatim into this repo for provenance) — 5/5 passed, independently re-run against this proposal's own exact commit, not merely accepted on report |

All SHAs above were verified directly against live `git log`/`git ls-remote`/`gh pr view` output before this proposal was written, not assumed from either party's own report.

## 2. Threat model this freeze covers

A **single-host, single-tenant synthetic pre-training foundation**, operated by a trusted operator, with:
- No real-corpus training.
- No GPU or paid infrastructure provisioning.
- No multi-tenant isolation requirement.
- No untrusted, co-resident process with the same OS UID as the training worker.
- No requirement to survive a host-level storage snapshot rollback.

This is explicitly **narrower** than a production or multi-tenant deployment threat model — see Section 4 for what remains unresolved outside this narrow scope.

## 3. What has been independently verified (both by this engineering effort and by Antigravity's own independent, adversarial re-testing)

- **G01 (checkpoint path/directory TOCTOU)**: closed via `orca.config._open_dir_no_symlinks()`, holding one directory descriptor across validation and every subsequent save/restore filesystem operation. Independently reproduced-then-closed: the intermediate-ancestor symlink substitution Antigravity's own Audit #077 requalification demonstrated now fails closed with `UntrustedStoreDirectory`, confirmed over the real isolated-worker IPC path (not just the validation helper in isolation), with zero files escaping the workspace.
- **G02 (cross-run migration override)**: `allow_cross_run_migration=True` is disabled on every callable path (direct Python call and raw IPC), raising `CrossRunMigrationDisabledError`/`CrossRunCheckpointAccessError` respectively, confirmed by both this engineering effort's own tests and Antigravity's independent suite.
- **Linux-specific descriptor correctness**: the `O_PATH`/`fsync()` bug this proposal's own commit `1ed7aa6` fixed (a genuine, Linux-only `EBADF` that macOS-only local testing could not have caught) is independently confirmed fixed — the leaf directory descriptor is fsync-capable, and tempfile failure cleanup unlinks in-flight temp files correctly.
- **CI qualification coverage**: both Audit #077 requalification suites, and now Audit #078's own suite, run as required, exact-head CI gates (not merely asserted locally), with only the 3 established, intentional historical vulnerability-demonstration tests individually deselected and documented — never hidden, never silently excluded wholesale.
- **Ordinary same-run checkpoint restoration** is confirmed unaffected by any of the above fixes.

## 4. Residual limitations — explicitly NOT resolved, NOT hidden

These three remain open, pre-existing (not newly discovered in this phase), and are **blockers for any multi-tenant or production deployment**, though assessed as non-blocking for the narrow synthetic freeze scope in Section 2:

1. **Same-UID worker isolation.** A co-resident process running under the same OS UID as the isolated training worker can `ptrace`/read `/proc/<pid>/mem`; `drop_to_uid` exists but requires root and has never been exercised end-to-end in this codebase's own tests.
2. **Unkeyed derived-cache integrity.** Derived tokenization/dataset-index caches are content-addressed with plain SHA-256, not HMAC-tagged; a coordinated rewrite of cache content and its own digest together goes undetected.
3. **Local-only, single-machine anti-rollback ledger.** A host-level storage snapshot restore resets the ledger's own recorded step monotonicity, defeating `CheckpointRollbackError`'s protection.

A separate, prioritized backlog item should be opened for each of these three ahead of any stronger-trust-model or global-deployment milestone — this proposal does not waive, close, or deprioritize any of them.

## 5. Correction to the independent audit's own evidence (per CTO directive)

Antigravity's own `test_check5_normal_same_run_checkpoint_restoration_succeeds` (`tests/test_audit078_final_requalification.py`) carries a docstring claiming: *"step, weights, optimizer state, and RNG state are restored accurately."* Its actual assertions check only `restore_resp["result"]["global_step"]` and `["sampler_position"]` — the two fields the worker's own IPC response ever returns, by design (no tensor crosses the wire; weights/optimizer/RNG state are restored **inside** the isolated worker process and never serialized back to the test). The test's docstring overstates what it itself verifies. This is a documentation inaccuracy in the test's own claim, not a defect in the restoration mechanism itself — the actual weight/optimizer/RNG restoration correctness is independently covered elsewhere in this codebase (e.g. `tests/test_genesis_resumable_checkpoint.py`'s own in-process round-trip tests, which do have direct access to the restored tensors). Per the established provenance-preservation discipline for all imported audit evidence, this test file is imported verbatim and not edited; this correction is recorded here, and a parallel factual note should be sent to Antigravity requesting the docstring itself be corrected in their own copy.

## 6. The unresolved concurrent-writer failure — kept open, not closed

`tests/test_genesis_audit016_remediation.py::test_defect02_concurrent_writers_do_not_corrupt_the_checkpoint` failed once during the full combined regression (under this machine's own heavy, unrelated resource contention) and passed when re-run standalone immediately after, repeatedly. Per the CTO's explicit instruction, this is recorded as an **intermittent** issue, not a "confirmed flake" with its root cause established — no root-cause investigation (e.g. instrumenting the lock-acquisition path under controlled contention, or testing on an otherwise-idle machine) has actually been performed. It remains open as a backlog item: re-investigate under controlled load before treating its environmental explanation as settled.

## 7. Prohibited operations under this freeze

Per the CTO directive's explicit restrictions, none of the following are authorized by this proposal, and none have been performed:
- Creating a release tag.
- Merging PR #78 into any mainline/base branch.
- Marking the foundation as "founder-frozen" in any durable record.
- Real-corpus model training.
- GPU or paid infrastructure provisioning.
- Any founder-grant issuance or invented migration authorization.
- Any modification to founder-approved UI designs (none were touched by this phase's work, which is backend/security-only).

## 8. Requested founder decision

Founder review and explicit, recorded approval is requested for exactly one of:
- **(a)** Approve freezing the synthetic foundation at commit `55eb4fe` under the narrow threat model in Section 2, with the Section 4 backlog items tracked separately; or
- **(b)** Request further remediation before freeze; or
- **(c)** Decline the freeze at this time.

No tag, merge, or founder-frozen marking will occur until one of the above is explicitly recorded by the founder.
