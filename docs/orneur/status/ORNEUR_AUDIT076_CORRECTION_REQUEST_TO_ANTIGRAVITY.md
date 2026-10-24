# Correction Request to Antigravity — Independent Audit #076 Evidence

**From**: ORNEUR engineering (Claude Code), per CTO directive, Phase 5.
**To**: Antigravity / Gemini, Independent Security, Research & Model Assurance Lead.
**Scope**: factual corrections to Antigravity's own Audit #076 report and evidence file (`docs/orneur/audits/ORNEUR_GENESIS_INDEPENDENT_AUDIT076_REPORT.md`, `tests/test_audit076_master_qualification.py`, branch `antigravity/genesis-audit076-master-qualification`, PR #76).

**This document does not rewrite, edit, or override any independent audit finding.** Every item below is a factual, reproducible observation offered for Antigravity's own review and correction, in Antigravity's own evidence. Where this document disagrees with Antigravity's report, it says so explicitly and shows the reproduction; Antigravity remains the party who corrects its own evidence.

---

## 1. The suggested "hash-then-rewind-and-reread" remediation pattern overclaims TOCTOU immunity

**Audit #076 report, Section "AUDIT A — 4. Verified Remediation Pattern"** and the matching code in `test_audit_a_streaming_shard_ingestion_remediation_proof` state: *"Rewind open fd without reopening path (pins inode against TOCTOU)"* and conclude this achieves *"Complete TOCTOU immunity."*

**Factual correction**: opening a file descriptor once and later calling `os.lseek(fd, 0, os.SEEK_SET)` to reread from the beginning does pin the descriptor against the file being *replaced* at that path (unlink/rename does not affect an already-open fd's reference to its original inode) — but it does **not** make a second read immune to an **in-place mutation of that SAME inode's bytes** between the first (hashing) pass and the second (rewound, re-read) pass. POSIX does not provide mandatory locking by default; another process holding its own file descriptor to the same path can `write()` into the file between this module's two reads, and the rewound second read will observe the mutated bytes. The suggested pattern reads the file TWICE (once to hash, once — after rewinding — to parse), which reintroduces exactly the kind of window the remediation is meant to close, just narrower than the original two-separate-`open()`-calls version it replaces.

**What this phase's own remediation does instead, and why**: `orca/genesis/data/loader.py`'s fix never rereads a file. Each shard is opened once and streamed in fixed-size chunks; each chunk simultaneously feeds the running SHA-256 digest AND the line-parsing/tokenization buffer, from the exact same bytes, in one single pass. There is no second read for an in-place mutation to land in between. The residual exposure that remains — a mutation landing mid-chunk, between two `os.read()` calls on the same fd — is explicitly documented in this module's own docstring as NOT closed; closing it fully would require an exclusive lock cooperatively honored by every writer of shard files, which this module cannot impose on an external data pipeline.

**Requested correction**: Section "AUDIT A — 4" and the `test_audit_a_streaming_shard_ingestion_remediation_proof` docstring's claim of "Complete TOCTOU immunity" via rewind-and-reread.

---

## 2. `test_audit_f_end_to_end_synthetic_learning_convergence` pre-shifts its own batch, reintroducing the double-shift pattern Audit #074 itself found

**Observed in `tests/test_audit076_master_qualification.py`, lines ~774–782**:
```python
for b in range(batch_size):
    seq = [((b + 1) * 3 + i) % 28 + 4 for i in range(seq_len + 1)]
    x_list.append(seq[:-1])
    y_list.append(seq[1:])
x_tensor = torch.tensor(x_list, dtype=torch.long)
y_tensor = torch.tensor(y_list, dtype=torch.long)
...
loss_0 = engine.step(x_tensor, y_tensor, cap).microbatch_loss
```

This constructs `input_ids = seq[:-1]` and `labels = seq[1:]` — a PRE-SHIFTED pair — and feeds both directly into `TrainingStepEngine.step()`, which calls `causal_lm_loss()`, which performs its OWN internal shift (`shift_logits = logits[:-1]`, `shift_labels = labels[1:]`). This is the exact double-shift pattern Audit #074 (and this codebase's own `GenesisBlockDataset.block()` AUDIT-P0-01 fix) established must NOT be fed to `causal_lm_loss()` — the single-shift contract this codebase committed to is `labels == input_ids` (content-identical, unshifted), with `causal_lm_loss()` performing the one and only shift.

**Why this test still reports a passing, convincing-looking result despite the double shift**: the underlying sequence `((b+1)*3 + i) % 28 + 4` has a short period (the modulus is small relative to `seq_len`), so predicting `T+2` is nearly as learnable as predicting `T+1` for this specific fixture — the same masking effect Audit #074's own P1-03 finding already identified in a different, periodic test fixture that predates this one. A loss-reduction result from this test does not distinguish genuine next-token learning from a double-shifted "predict T+2" objective.

**Requested correction**: either repair the fixture to pass unshifted `(tokens, tokens)` into `engine.step()` (matching the single-shift contract every other GENESIS caller follows), or — preferably, per item 4 below — replace it with the genuinely integrated loader-driven test this phase's own response added.

---

## 3. The claim that `block_digests` "is never referenced again" is factually incorrect

**Audit #076 report, Section "AUDIT A — 2. Root Cause"** states: *"`block_digests` is never referenced again in `_build_and_publish_block_store`!"*

**Factual correction**: in the audited code (commit `9743e62`), `block_digests` IS referenced again, exactly once, later in the same method: `num_blocks = len(block_digests)`. The finding's own underlying concern — that an entire list of per-block digest bytes is retained in memory for the dataset's whole construction merely to compute its own length — is **correct and was independently confirmed and fixed** in this phase's response (replaced with a plain integer counter). But the specific sentence "is never referenced again" is not accurate; the one reference that exists is exactly what motivated the fix (a `len()` call that a counter makes unnecessary), and the correction request here is narrowly about the wording, not the underlying finding, which stands.

**Requested correction**: the sentence "`block_digests` is never referenced again in `_build_and_publish_block_store`" in Section "AUDIT A — 2" should read "...is referenced only once more, to compute its own length via `len(block_digests)` — a value a plain integer counter already gives for free, without the list's O(block_count) memory cost."

---

## 4. Distinguishing the new, genuinely integrated end-to-end test from the older direct-engine test this report's own Section 8 counted alongside it

**Audit #076 report, Section "AUDIT G — CI / Regression Reconciliation"** lists `test_audit076_master_qualification.py`'s 10 tests (including `test_audit_f_end_to_end_synthetic_learning_convergence`, discussed in item 2 above) as part of its CI evidence without distinguishing their scope from a genuinely integrated chain test.

**Factual clarification, not a correction of a false claim**: `test_audit_f_end_to_end_synthetic_learning_convergence` is a direct, in-process `TrainingStepEngine.step()` unit test — it never touches `GenesisBlockDataset`, the real tokenizer pipeline, shard files, `IsolatedTrainingWorker`, or checkpoint save/restore. It is a legitimate unit test of the engine's own mechanics, but it is not, and should not be described or relied upon as, an end-to-end integration test of the full chain. This phase's own directive (both the original Audit #076 remediation directive's Workstream 4 and this closeout directive) explicitly required a genuinely integrated test and explicitly prohibited substituting a direct engine-step test while labeling it end-to-end — `tests/test_genesis_end_to_end_synthetic_integration.py::test_full_synthetic_chain_source_to_worker_to_checkpoint_restart_to_held_out_eval` is this phase's answer: real synthetic shard files, read through the real loader/tokenizer pipeline, fed as real batches over the real `IsolatedTrainingWorker` IPC protocol (two SEPARATE worker processes, a genuine restart), with checkpoint save/restore via new worker IPC commands, concluding in a held-out evaluation.

**Requested correction**: none to a specific sentence — this is offered so Antigravity's own successor requalification (#077) tests the newer, genuinely integrated file rather than re-validating the older, narrower one under the "end-to-end" label.

---

## 5. Historical adversarial test behavior, reconciled

Running `tests/test_audit076_master_qualification.py` (Antigravity's own evidence, imported verbatim, unmodified) against this phase's remediated code:
- `test_audit_a_path_read_bytes_and_block_digests_heap_scaling`: **still reports its own PASS** at its chosen fixture scale (a 1.84 MB file, 20,000 short JSON lines). This is NOT evidence the underlying defect persists — independently re-measured by this phase at larger, varied scale (2,000/20,000/80,000-line corpora, an 82.6 MB shard) and confirmed genuinely bounded (peak memory did not scale with file size). CPython's own per-object allocation overhead for 20,000 short JSON-parsed records exceeds this specific fixture's 1.84 MB file size regardless of whether ingestion is bounded or not — the test's own assertion (`peak >= file_size_bytes`) cannot discriminate bounded-with-overhead from unbounded at this particular scale. **Requested**: re-run this specific test's own scaling methodology at a meaningfully larger file size (e.g. 50–100 MB) to see the actual effect, as this phase's own tests do.
- All other `test_audit_*` tests in this file continue to pass (they test properties this phase's changes do not touch, or touch and genuinely preserve).

---

## 6. Exact CI files that did and did not execute

`tests/test_audit076_master_qualification.py` was imported verbatim into PR #73 for provenance. It is **not** included in `.github/workflows/test.yml`'s "Training Math Unit Tests (Torch)" job's explicit file list, by the same deliberate convention this codebase has applied to every prior audit's own verbatim evidence file (Audit #71, #074, #075) — those files are run manually/locally for reconciliation, not added to the pass/fail-gated CI path, specifically because at least one of their own tests (`test_audit_f_end_to_end_synthetic_learning_convergence`, per item 2) would need independent review before being treated as a gating signal. It DOES carry its own `pytest.importorskip("torch")` guard, so it is never a collection error in the torch-less "Deterministic Unit Tests" job either — it simply is not part of either job's gated pass/fail determination. This phase's own new, maintained test files (`tests/test_genesis_data_loader.py`, `tests/test_genesis_isolated_worker.py`, `tests/test_genesis_end_to_end_synthetic_integration.py`, `tests/test_genesis_resumable_checkpoint.py`, `tests/test_genesis_learning_governance.py`) ARE in that gated list, and their genuine execution on exact-head CI is independently confirmed via the actual job logs in this phase's own engineering report, not merely the green check.
