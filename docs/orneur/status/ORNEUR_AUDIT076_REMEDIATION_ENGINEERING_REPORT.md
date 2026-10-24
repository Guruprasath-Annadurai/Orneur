# ORNEUR — Audit #076 Remediation, Checkpoint IPC Hardening and Successor Audit Handoff

**Directives covered**: "Audit #076 Critical Remediation and Final Synthetic Integration Qualification" (Phases 1–6 of that directive, originally numbered as Missions/Workstreams 1–6), followed immediately by "CTO Final Engineering Closeout: Audit #076 Remediation, Checkpoint IPC Hardening and Successor Audit Handoff" (Phases 1–6 of THIS directive, which found two further real issues in the first response and is what this report's Phase numbering below follows).

**Verified baseline at start of this phase**:
- Development PR #73: `9743e6282b71ac225982e75175c9fb0451cda4a1`
- Audit #076 PR #76: `6fc2580607d22a23dd608856a1088b73769981dd`
- Foundation PR #65: `87cc7ad1a2e269de3a05edd626a61cca6fbdb760` (unchanged throughout)

**Commits produced this phase** (in order): `907c402` (Workstreams 1/2/4 — bounded shard streaming, adversarial tests, genuine end-to-end chain), `9e5d8a3` (CI gating fix for the new end-to-end test), and the commit this report accompanies (Phases 2–4 of the final-closeout directive: the oversized-record parsing fix, checkpoint IPC hardening, and restart-equivalence verification). All verified against live `git log`/`gh pr view` before any change, every turn.

---

## Phase 1 — This report

Distinguishes, throughout, **engineering tests** (this phase's own adversarial reproductions, run and reported honestly) from **independently qualified security properties** (anything Antigravity itself, as the independent auditor, has separately signed off on) — this phase does not claim the latter for anything only this phase's own tests have exercised.

---

## Phase 2 — Oversized-record parsing weakness: investigated, reproduced, fixed

**Investigation**: `GenesisBlockDataset._build_and_publish_block_store()`'s per-shard streaming loop, upon detecting `len(leftover) > max_record_bytes`, reset `leftover = b""` and continued the SAME chunk-processing loop as if nothing unusual had happened — it did not track that the file position was still mid-physical-line.

**Reproduction** (`tests/test_genesis_data_loader.py::test_audit076_phase2_oversized_record_cannot_smuggle_a_crafted_suffix_as_a_separate_record`): constructed one physical JSONL line as `[oversized garbage prefix, exactly 5× the module's own `_SHARD_READ_CHUNK_BYTES`, no newline] + [a small, well-formed, crafted JSON record] + [the line's one real newline]`. The exact-multiple prefix length deterministically aligns the `leftover` reset to a chunk boundary — the precise condition under which the weakness is exploitable. Confirmed BEFORE fixing: the crafted JSON fragment was accepted as an entirely separate, legitimate record and tokenized into the published block store, verified by searching the store's own token contents for the fragment's token sequence.

**Fix**: a `discarding_until_newline` state machine. The moment the oversized-record threshold is crossed, exactly ONE rejection is counted and this flag is set; every subsequent chunk, for as long as it is set, is scanned only for the next real newline — everything up to and including it is discarded outright, never appended to `leftover`, never split, never handed to the per-line parser. Only bytes after that real newline resume normal processing. If the file ends while still in this state, nothing further is processed (no fragment is silently accepted); the single rejection already counted stands.

**Verified, all five required properties**:
1. **Exactly one rejection per oversized physical record** — `records_rejected_malformed == 1` for both the no-newline case and the crafted-suffix case (previously the no-newline case produced 5+ separate rejections, one per chunk re-triggering the old reset logic).
2. **No fragment of a rejected record can enter the training set** — directly verified by scanning the published block store's own tokens for the crafted fragment's sequence; absent.
3. **Memory remains bounded** — discarding is a constant-time scan-and-drop per chunk, never an accumulation; re-verified against the existing `test_audit076_one_oversized_record_with_no_newline_is_rejected_not_unbounded` memory-bound test (now additionally asserting exactly one rejection, not merely "at least one").
4. **Parsing resumes correctly at the next genuine newline** — the normal record immediately preceding the malicious physical line in the same shard file is still correctly read, tokenized, and published (`records_read == 1`, matching the one legitimate record).
5. **Byte-level integrity verification remains intact** — the running SHA-256 digest still covers every byte read (including the discarded ones), unchanged by this fix; the shard's own digest check is unaffected.

---

## Phase 3 — Checkpoint IPC authorization: investigated, three real violations confirmed, fixed

**Investigation, against each named vector**:

| Vector | Confirmed? | Finding |
|---|---|---|
| Checkpoint path outside authorized workspace | **YES** | `payload["path"]` was used directly with zero validation — a client could direct `save_checkpoint`/`restore_checkpoint` to read or write anywhere the worker process has filesystem permission to touch. |
| Dataset identity different from the worker's verified grant | **YES** | `DatasetIdentity(**payload["dataset_identity"])` was constructed directly from client-supplied data, never checked against the run's own actual, validated identity. |
| A different ledger run ID | **YES** | `payload["ledger_run_id"]` was accepted from the client outright, letting a client redirect the anti-rollback ledger check to an unrelated run's ledger entry. |
| A configuration fingerprint not derived from the actual running model | **YES** | `payload["config_fingerprint"]` was a client-supplied string, never recomputed from the worker's own `model_cfg`/`step_cfg`. |
| An unrelated but valid checkpoint | **YES (consequence of the above four)** | Because the "expected" values the resume-equivalence check compares against were themselves client-supplied, a client could get an entirely unrelated checkpoint accepted by also supplying matching (self-chosen) expectations — the equivalence check was checking the client's claims against itself, not against the worker's own ground truth. |
| A checkpoint command after grant revocation/expiration | **YES** | Neither handler called any live authorization check at all — only `step` did. A revoked or expired grant left `save_checkpoint`/`restore_checkpoint` fully functional indefinitely. |

**Fix, the smallest viable correction for each, in the same handlers**:
- `WorkerStartupConfig.checkpoint_workspace_dir` (new field; `None` by default) is the ONLY directory a checkpoint path may resolve under. No workspace configured means the commands are refused entirely — fail-closed, not merely "unrestricted."
- `config_fingerprint` and `dataset_identity` are now ALWAYS derived inside the worker from its own already-verified startup config (`compute_config_fingerprint(cfg.model_cfg, cfg.step_cfg)` and a `DatasetIdentity` built from `cfg.dataset_manifest_ids[0]`/`cfg.dataset_digest`/`cfg.tokenizer_digest`) — these fields were removed from the wire protocol and the client-side method signatures entirely; the worker no longer reads them from the payload at all, so no amount of payload crafting can reintroduce them.
- `ledger_run_id` is always `cfg.run_id` — likewise removed from the client API.
- `verify_live_authorization_or_raise()` (extracted from `execute_authorized_training_step()` into a reusable function in `learning_governance.py`, not duplicated) now runs before both handlers do anything; on failure, the worker fails exactly like a `step` authorization failure — it terminates its own process, not merely refusing that one command.

**Adversarial tests added** (`tests/test_genesis_isolated_worker.py`, 5 new): path-outside-workspace rejection; no-workspace-configured fail-closed default; a raw IPC message that still tries to smuggle the three removed fields, proven to have zero effect; an unrelated checkpoint from a genuinely different model, rejected by the worker's own derived fingerprint; and a checkpoint command after revocation, which now fails closed and terminates the worker exactly like a revoked `step`.

**The worker now derives expected identities from its own verified configuration and authorization — it does not, and structurally cannot, let a client manufacture the expected values against which its own checkpoint is verified.**

---

## Phase 4 — Restart equivalence: verified, with one real determinism gap found and fixed

**Investigation finding, independent of the three Phase 3 findings**: while building the restart-equivalence test, two separately-spawned worker processes constructed with the IDENTICAL `model_cfg`/`step_cfg` produced genuinely DIFFERENT random initial model weights — `_worker_main()` never seeded torch's RNG before constructing the model, and a freshly `spawn`ed Python interpreter has no fixed seed of its own. This silently undermined exact restart-equivalence for any worker that starts fresh (not via restore) using the same configuration twice. **Fixed**: `_worker_main()` now calls `set_deterministic_seed(cfg.step_cfg.seed)` immediately before constructing the model — the same determinism primitive every other GENESIS synthetic-learning test already relies on.

**`tests/test_genesis_end_to_end_synthetic_integration.py::test_restart_equivalence_against_uninterrupted_training`** drives the IDENTICAL deterministic batch sequence (same `ReproducibleSampler` seed, same real loader-produced batches) through two scenarios — one uninterrupted worker running all 40 steps, and one split across two SEPARATE worker processes (20 steps, checkpoint, restart, 20 more steps) — and compares, with every comparison's own explicit method and tolerance:

| Property | Comparison method | Result |
|---|---|---|
| Model parameters | `torch.allclose(atol=1e-5)` per parameter tensor | within tolerance (explicitly NOT asserted bit-identical) |
| Optimizer state (`exp_avg`, `exp_avg_sq` per parameter) | `torch.allclose(atol=1e-5)` | within tolerance |
| Step progression | exact integer equality | `full_final_step == resumed_final_step == 40` |
| Scheduler progression | exact LR equality (`pytest.approx(abs=1e-9)`) — a pure function of step | matched |
| Sampler position | exact integer equality | matched |
| RNG state | restored via `TrainingState.restore()` (Python + torch RNG, already part of the existing checkpoint mechanism); verified indirectly via the probe-loss comparison below | consistent |
| Numerical loss (one further identical probe batch fed to both final states) | `pytest.approx(abs=1e-4)` | matched |
| Held-out evaluation, before vs. after the resumed phase | next-token accuracy on an unseen seed, compared with an explicit non-regression margin (`accuracy_after >= accuracy_before - 0.1`) | non-regressing |

**This phase never describes any of the above as bit-identical** — every comparison states its own explicit tolerance, per the directive's own instruction. Genuine bit-for-bit reproducibility across a real process boundary (not merely within one process) is a stronger claim this phase does not make.

---

## Phase 5 — Audit #076 correction request

Prepared as a **separate document**, `ORNEUR_AUDIT076_CORRECTION_REQUEST_TO_ANTIGRAVITY.md`, alongside this report — a factual correction request, never a rewrite of Antigravity's own findings. Antigravity remains the party who must correct its own evidence.

---

## Phase 6 — Engineering closeout

### Measured memory results (Workstream 1 of the original Audit #076 directive, re-confirmed this phase)
- An 82.6 MB synthetic shard: **~2.1 MB peak** (tracemalloc), independently re-verified unaffected by the Phase 2 discard-state fix (discarding is still O(chunk size), not O(record size)).
- Process RSS (not merely tracemalloc) growth during ingestion of a >20 MB shard stays under 25% of the shard's own size.
- A 300,000-byte oversized record with no newline: peak memory stays a small fraction of the record's own size; exactly one rejection, not an unbounded accumulation.

### Source-level trust assumptions (restated, unchanged by this phase unless noted)
- `authorized_shard_digests` and `tokenizer_digest` remain caller-asserted identity at the loader layer — not independently re-derived from raw tokenizer/dataset bytes.
- The derived block-store's per-block digest is a plain SHA-256, not an HMAC — **unkeyed cache integrity remains explicitly documented as unresolved**, per this directive's own restriction.
- The anti-rollback ledger remains a local, filesystem-resident artifact with no independent, externally-anchored trust root — **local-only rollback protection remains explicitly documented as unresolved**.
- The isolated worker's strongest isolation tier (`PEER_VERIFIED_UID_SEPARATED`) requires root and was not exercised end-to-end in this phase's own environment — **the same-UID worker threat boundary remains explicitly documented as unresolved**.
- Checkpoint IPC identity/fingerprint fields are now worker-derived, not client-supplied (Phase 3) — this closes a concrete trust violation but does NOT change any of the three structural limitations above.

### Full regression reconciliation
Full GENESIS-prefixed suite (`tests/test_genesis*.py tests/test_audit_genesis*.py tests/test_audit74_successor_adversarial_requalification.py tests/test_audit076_master_qualification.py tests/test_native_learning_engine_adversarial_audit.py`), run to completion after all Phase 2/3/4 fixes in this report: **3317 passed, 17 skipped, 28 failed** (1373.94s).

All 28 failures are confined to exactly the three historical, verbatim-imported adversarial evidence files, none of which this phase modifies — the same 28 (5 + 11 + 12) failures reconciled in the Audit #075 report, unchanged by this phase's loader/checkpoint-IPC work. `tests/test_audit076_master_qualification.py::test_audit_a_path_read_bytes_and_block_digests_heap_scaling` did NOT fail this run (it still weakly "passes" its own assertion at its small, 1.84 MB fixture scale — see the correction request's item 5 for why that is expected and not evidence the underlying defect persists). Zero unexpected failures across 3317 passing tests.

PR #65 foundation regression (`test_genesis_training_orchestration.py`, `test_genesis_cross_workstream_integration.py`, `test_genesis_workstream_a_end_to_end.py`, `test_genesis_data_manifest.py`, `test_genesis_data_pipeline.py`, `test_genesis_data_contamination.py`, `test_audit_genesis_hardening_remediation.py`): re-verified, zero regression.

### GitHub CI evidence
**Exact-head CI** (commit `d4228713dd37711e008ca2675062ca562d7645ca`, run [39153735638](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/39153735638)): **all 9 checks pass.** Pulled the actual job logs, not just the green badges:
- **Training Math Unit Tests (Torch)**: `489 passed in 167.08s`, zero failures. All 7 new Phase 2/3/4 tests individually confirmed `PASSED` by name: `test_audit076_phase2_oversized_record_cannot_smuggle_a_crafted_suffix_as_a_separate_record`, the 5 `test_phase3_*` checkpoint-IPC hardening tests, and `test_restart_equivalence_against_uninterrupted_training`.
- **Deterministic Unit Tests**: `8895 passed, 383 skipped, 43 deselected, 7 xfailed in 883.33s`, zero failures, clean collection (43 deselected = the two intentionally-excluded verbatim audit-evidence files).
- All 7 remaining jobs also pass.

This is real, observed, exact-head CI evidence, not assumed in advance.

### Independent reproduction instructions for successor requalification #077
```
pytest tests/test_genesis_data_loader.py -v
pytest tests/test_genesis_isolated_worker.py -v
pytest tests/test_genesis_end_to_end_synthetic_integration.py -v
pytest tests/test_genesis_resumable_checkpoint.py tests/test_genesis_learning_governance.py -v
pytest tests/test_audit076_master_qualification.py -v   # Audit #076's own evidence, imported verbatim
```
Specifically for the two new findings in this response:
```
pytest tests/test_genesis_data_loader.py::test_audit076_phase2_oversized_record_cannot_smuggle_a_crafted_suffix_as_a_separate_record -v
pytest tests/test_genesis_isolated_worker.py -k phase3 -v
pytest tests/test_genesis_end_to_end_synthetic_integration.py::test_restart_equivalence_against_uninterrupted_training -v
```

### Restrictions honored
No real-corpus training, GPU use, paid infrastructure, founder-grant issuance, protected-mainline merge, production deployment, or foundation-freeze tagging occurred anywhere in this phase.

---

## Final verdict

**`PARTIAL`**

Two genuine, independently-reproduced defects (the oversized-record parsing weakness; three checkpoint-IPC trust violations plus a cross-process determinism gap) were found, fixed, and proven fixed with reproducing adversarial tests in this response — none of them were previously known or claimed closed. This is why the verdict remains `PARTIAL`, not `READY_FOR_INDEPENDENT_REAUDIT`: finding two more real issues during this phase's OWN investigation (as explicitly instructed) is itself evidence that further independent adversarial review is warranted before a stronger verdict is appropriate. The three structural limitations named in this directive's own restrictions (same-UID worker security, unkeyed cache integrity, local-only rollback protection) remain explicitly open, not resolved by this phase's loader/checkpoint-IPC work, and are not claimed otherwise.
