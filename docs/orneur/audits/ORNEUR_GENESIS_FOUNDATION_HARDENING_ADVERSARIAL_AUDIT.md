# ORNEUR GENESIS FOUNDATION HARDENING — INDEPENDENT ADVERSARIAL AUDIT REPORT

**Audit Date:** 2026-10-17  
**Auditor:** Antigravity / Gemini — Independent Security, Research, and Model Assurance Lead  
**Target Repository:** `Guruprasath-Annadurai/Orneur`  
**Execution Mode:** Adversarial, Empirical, Evidence-Driven  
**Training Authorization:** STRICTLY NO-GO (`NATIVE_MODEL_TRAINING_AUTHORIZATION = NO-GO`)  
**GPU Spend / Allocation:** ₹0.00 / 0 GPUs  

---

## 1. Executive Summary & PR Qualification Matrix

This audit constitutes the independent qualification of Claude's latest GENESIS foundation hardening and native-authorization convergence workstreams across Pull Requests **#65**, **#68**, **#69**, and **#70**.

Every claimed defect resolution, architectural assumption, and security boundary was independently audited against the source code, executed against adversarial fixtures, and tested with automated reproduction suites.

### PR Audit Verdict Summary

| PR # | Branch Name | Audited Commit SHA | Scope / Responsibility | Individual Verdict |
|---|---|---|---|---|
| **#65** | `claude/genesis-cross-workstream-integration-2026-10-16` | `24693fb5bd3e20f791d7ed0b91a044303591bf6d` | Cross-workstream integration (A + C + F), combined regression suite | **CONDITIONAL_REMEDIATION_REQUIRED** |
| **#68** | `claude/genesis-mission2-native-authorization-2026-10-16` | `19d740383a446ce814e8b3809556b38887b4c1b6` | Mission 2 native authorization state machine, durable replay claims | **CONDITIONAL_REMEDIATION_REQUIRED** |
| **#69** | `claude/genesis-workstream-f-grant-fields-2026-10-16` | `0942169c2753359283e098f0ea1380f85818faeb` | Workstream F grant identity schema extension (M2-01) | **PASS** |
| **#70** | `claude/genesis-workstream-a-hardening-2026-10-16` | `f03af2f3aa1f639fa6b4cf591e022e0aed32df12` | Dataset pipeline crash recovery, manifest identity, cross-split checks | **CONDITIONAL_REMEDIATION_REQUIRED** |

### Overall Combined Verdict: **CONDITIONAL_REMEDIATION_REQUIRED**

**Key Finding:** While significant architectural progress has been made (in particular, genuine cryptographic grant binding in PR #69 and sub-linear streaming memory in PR #70), our adversarial inspection identified **three high-priority defects (P0)** and **two boundary limitations (P1)** that require remediation before these branches can be approved for merge. Notably, one defect dismissed by Claude as "already correct" (P0-02) was empirically proven broken.

---

## 2. Exact Git and CI Qualification

### 2.1 Commit Verification

All audit targets were verified to match the exact directives:
- **PR #65 HEAD:** `24693fb5bd3e20f791d7ed0b91a044303591bf6d` (`docs(genesis): final hardening engineering report (P0-01..P1-03)`)
- **PR #68 HEAD:** `19d740383a446ce814e8b3809556b38887b4c1b6` (`docs(genesis): P1-03 -- explicitly document and test marker-deletion/cross-host replay residuals`)
- **PR #69 HEAD:** `0942169c2753359283e098f0ea1380f85818faeb` (`fix(genesis): carry full signed identity into NativePretrainingGrant (M2-01)`)
- **PR #70 HEAD:** `f03af2f3aa1f639fa6b4cf591e022e0aed32df12` (`fix(genesis): P1-02 -- explicit scalability limit on cross-split near-dup screening`)

All four pull requests remain **OPEN**, marked as **DRAFT**, and **UNMERGED**.

### 2.2 CI Workflow Status

Exact-SHA GitHub Actions runs were verified using `gh run list --commit <sha>`:
- `24693fb5bd3e20f791d7ed0b91a044303591bf6d` (PR #65): **GREEN** (Test Suite, Eval Harness)
- `19d740383a446ce814e8b3809556b38887b4c1b6` (PR #68): **GREEN** (Test Suite)
- `0942169c2753359283e098f0ea1380f85818faeb` (PR #69): **GREEN** (Test Suite)
- `f03af2f3aa1f639fa6b4cf591e022e0aed32df12` (PR #70): **GREEN** (Test Suite)

---

## 3. Adversarial Audit Findings & Empirical Reproductions

All 6 findings specified in the directive were tested. An automated adversarial regression suite has been implemented in [`tests/test_audit_genesis_hardening_adversarial.py`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py) confirming every finding.

### AUDIT-P0-01: Post-Authorization Shard Tampering Undetected During Transitions
* **Location:** `orca/genesis/training/orchestration.py:637-695` (`GenesisTrainingRun._reverify_grant_or_transition()`)
* **Severity:** **P0 — Security Critical**
* **Mechanism:**
  `GenesisTrainingRun.authorize()` verifies that the signed grant matches the run's declared `authorized_shard_digests`. However, at every subsequent state transition (`start()`, `pause()`, `resume()`, `recovered()`), `_reverify_grant_or_transition()` only compares the grant and current snapshot against in-memory attributes (`self.identity.authorized_shard_digests`).
  **The shard files on disk are never re-hashed or re-read during state transitions.**
  If an operator, background job, or malicious process modifies, swaps, or replaces the shard files on disk *after* `authorize()`, `run.start()` and `run.resume()` execute without detecting the modified bytes.
* **Empirical Proof:**
  [`test_audit_p0_01_post_authorization_shard_tampering_undetected`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py#L137): A shard file was bit-flipped and re-hashed on disk after `authorize()`. `run.start()` and `run.resume()` transitioned cleanly to `RUNNING` with zero exceptions.
* **Remediation Required:**
  `_reverify_grant_or_transition()` (or `start()`/`resume()`) must re-compute and verify the on-disk shard digests (`compute_shard_digests(shard_dir)`) against `self._authorized_identity.authorized_shard_digests` prior to entering `RUNNING`.

---

### AUDIT-P0-02: Progress-State Persistence Fails on Empty Pending Batches
* **Location:** `orca/genesis/data/pipeline.py:483-513` (`process_corpus()`, `_commit_batch()`)
* **Severity:** **P0 — Data Integrity / Crash Safety Defect**
* **Mechanism:**
  In `pipeline.py`, line 484 begins with:
  ```python
  def _commit_batch() -> None:
      if not pending:
          return
  ```
  `pending` accumulates only *kept* records (`pending.append(...)`). If a run processes records that are all corrupt, exact duplicates, near duplicates, quality-rejected, or PII-rejected (e.g., 0 kept records), or if a run ends with a trailing sequence of rejected records after the last kept record batch:
  `_commit_batch()` is called at the end of the loop (line 563), evaluates `if not pending: return`, and **aborts without committing anything to SQLite**.
  Consequently, `report.resume_offset`, `report.lines_read`, and all rejection counters are **lost**. Upon restart, `_load_progress()` reads no row or a stale row, causing the pipeline to re-read from line 0 or re-process trailing records.
  *(Note: Claude's engineering report lines 67-73 erroneously claimed this scenario was investigated and "already correct". Empirical testing proves it fails.)*
* **Empirical Proof:**
  [`test_audit_p0_02_progress_not_persisted_when_run_ends_with_rejected_records`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py#L206) and [`test_audit_p0_02_progress_trailing_duplicates_not_persisted`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py#L236):
  1. For a 5-line corrupt corpus, `progress` table had zero rows committed (`row is None`). Resumption restarted from line 0.
  2. For 1 kept record followed by 5 duplicate records, `resume_offset` remained frozen at 1 instead of advancing to 6, and `exact_duplicates` remained 0 instead of 5.
* **Remediation Required:**
  In `_commit_batch()`, decouple the progress and sliding-window persistence from `if not pending: return`. The progress table and near-dup window must always be committed at batch boundary or loop exit, even if `pending` kept records is empty.

---

### AUDIT-P0-03: Artifact Recovery Integrity Checks File Size Only
* **Location:** `orca/genesis/data/pipeline.py:284-328` (`_verify_and_recover_missing_or_corrupted_shard_output()`)
* **Severity:** **P0 — Corruption Recovery Bypass**
* **Mechanism:**
  Line 314 implements the recovery check:
  ```python
  actual_size = p.stat().st_size if p.exists() else -1
  if actual_size >= safe_offset:
      continue  # present and at least as large as what we believe was durably flushed -- fine
  ```
  The recovery procedure performs **no cryptographic or content integrity verification**. If a flushed shard file is overwritten with garbage bytes, malicious text, or padded with null bytes to equal or exceed `safe_offset`, the procedure assumes the shard is valid (`continue`) and leaves `kept_records.flushed = 1`. The corrupted file is neither truncated nor regenerated from SQLite.
* **Empirical Proof:**
  [`test_audit_p0_03_artifact_recovery_fooled_by_same_size_tampering`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py#L267): A shard file was replaced with junk bytes of identical length. `_verify_and_recover_missing_or_corrupted_shard_output()` executed and reported 0 unflushed records, leaving the junk content on disk.
* **Remediation Required:**
  The recovery mechanism must verify content integrity—either via block hashes, shard rolling digests, or parsing verification—rather than treating file size alone as proof of intact data.

---

### AUDIT-P0-04: Manifest Identity Omits `normalization_rule` from Binding Fields
* **Location:** `orca/genesis/data/manifest.py:141-170` (`GenesisDatasetManifest._binding_fields()`)
* **Severity:** **P1/P0 — Provenance Boundary Discrepancy**
* **Mechanism:**
  In PR #70, `_binding_fields()` was refactored to bind `transformation_lineage` and `source_record_count`. However, `normalization_rule` was omitted:
  ```python
  return {
      "schema_version": schema_version, "dataset_name": dataset_name, "version": version,
      "origins": origins, "source_content_digest": source_content_digest,
      "source_record_count": source_record_count,
      "transformation_lineage": transformation_lineage, "tokenizer_binding": tokenizer_binding,
  }
  ```
  `required_keys` in `load()` mandates that `normalization_rule` be present in JSON. But because it is excluded from `_binding_fields()`, an attacker can mutate `normalization_rule` in an existing manifest file (e.g. changing it to arbitrary text or misleading claims), and `GenesisDatasetManifest.load()` will verify `recomputed_id == claimed_manifest_id` and accept the file without raising `ManifestTamperedError`.
* **Empirical Proof:**
  [`test_audit_p0_04_manifest_id_invariant_under_normalization_rule_mutation`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py#L295): A manifest file had its `normalization_rule` mutated to an attack payload. `GenesisDatasetManifest.load()` accepted it without error.
* **Remediation Required:**
  Include `"normalization_rule": normalization_rule` in `_binding_fields()`, or formally document `normalization_rule` as an unverified informational field excluded from the cryptographic manifest identity.

---

### AUDIT-P1-01: Replay & Concurrency Limits (Marker Deletion & Cross-Host Boundary)
* **Location:** `orca/genesis/training/orchestration.py:326-344` (`_claim_native_pretraining_authorization()`)
* **Severity:** **P1 — Architectural Boundary Limitation**
* **Analysis & Verification:**
  1. **Marker Deletion:** Replay protection is implemented via `os.open(f"{auth_id}.claimed", O_CREAT | O_EXCL)`. If a local operator or script deletes this marker file, the grant can be re-authorized and claimed again.
  2. **Same-Host Concurrency:** `O_CREAT | O_EXCL` is atomic across concurrent threads/processes on the same local filesystem.
  3. **Cross-Host Replay:** The marker is stored purely under local `ORCA_HOME`. It provides **zero cross-host replay protection**. If a grant is replayed on another machine in a cluster, both machines will grant authorization independently.
* **Empirical Proof:**
  [`test_audit_p1_01_marker_deletion_allows_replay_and_no_cross_host_isolation`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py#L342) confirms both marker reclaim and cross-host replay.

---

### AUDIT-P1-02: Contamination Screening Limits & Cross-Batch Leakage Blind Spot
* **Location:** `orca/genesis/data/contamination.py:112-160` (`find_near_duplicates_across_splits()`)
* **Severity:** **P1 — Algorithmic Scaling Limitation**
* **Analysis & Verification:**
  1. **Quadratic Scaling:** Pairwise comparison has no index (MinHash/LSH) and enforces `max_total_records = 5000`. Exceeding this raises `CrossSplitScreeningTooLargeError`.
  2. **Batching Blind Spot:** If a user chunks a 100,000-record dataset into batches of 5,000 to circumvent the limit, near-duplicates that span different batches (e.g. Train record in Batch 1 and Val record in Batch 2) will never be compared, causing silent contamination leakage.
  3. **Short String Substring Filter:** In `find_normalized_substring_matches()`, strings with `len(norm_p) < 40` are skipped, ignoring short benchmark problems.
* **Empirical Proof:**
  [`test_audit_p1_02_cross_split_screening_limits_and_batching_leakage_blindspot`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py#L370) confirms the 5,000 limit and demonstrates that batching misses cross-batch near-duplicates.

---

## 4. Evaluation of Existing Test Suites & Claude's Claims

1. **Claude's 16 Regression Tests:**
   Claude added 16 regression tests in PRs #68 and #70. We verified that all 16 pass.
2. **Combined Integration Regression:**
   We executed the full repository test suite under Python 3.12:
   - **Result:** **3,174 passed, 17 skipped, 0 failures** in 460.83 seconds.
3. **Adversarial Audit Suite:**
   Our independent adversarial suite ([`tests/test_audit_genesis_hardening_adversarial.py`](file:///Users/ag/Downloads/Orneur/tests/test_audit_genesis_hardening_adversarial.py)) executes in 23.43 seconds:
   - **Result:** **7 passed, 0 failures**.

---

## 5. Review of Ancestor Findings & NOVUS Continuation Proposal

### 5.1 Unresolved Ancestor Findings (PR #58 / Audit #017)
PR #58's conditional remediation requirements (Workstreams B, D, E) remain unmerged and unaccepted. They carry forward into PR #65.

### 5.2 NOVUS Fine-Tuning Continuation Proposal (Read-Only Review)
Section 10 of Claude's report (`ORNEUR_GENESIS_FINAL_HARDENING_ENGINEERING_REPORT.md`) outlines a proposal for a new NOVUS continuation run:
- **Baseline:** `orca-core` QLoRA adapter (`sha256:094de7b23a0ce1b343b560c4c0354e408c48c2e1d74c84e03fbd4d65694ed5e4`), `unsloth/meta-llama-3.1-8b-instruct-unsloth-bnb-4bit`.
- **Initialization vs Resumption:** Genuinely NEW run with fresh AdamW optimizer state. Accurately acknowledges that historical optimizer momentum/variance states are non-existent.
- **Compute & Cost:** Single T4 GPU kernel (Kaggle quota), runtime <1 hr, budget ₹0.
- **Auditor Assessment:** The proposal is technically sound and candid about historical limitations. As mandated, no training was authorized or initiated.

---

## 6. Detailed Remediation Plan & Conditions for Acceptance

To achieve a full `PASS` and enable PR approval:

1. **Remediate AUDIT-P0-01 (Shard Disk Re-verification):**
   Update `GenesisTrainingRun._reverify_grant_or_transition()` to verify actual on-disk shard files (e.g. via `compute_shard_digests`) against `self._authorized_identity.authorized_shard_digests` whenever transitioning to `RUNNING`.
2. **Remediate AUDIT-P0-02 (Progress Commit on Empty Pending):**
   In `process_corpus()`, remove `if not pending: return` from the progress commit path. Ensure `progress` row (`resume_offset`, `lines_read`, rejection counters) and `near_dup_window` are persisted on loop exit even when 0 records are kept.
3. **Remediate AUDIT-P0-03 (Content-Aware Recovery):**
   In `_verify_and_recover_missing_or_corrupted_shard_output()`, replace `actual_size >= safe_offset` with cryptographic or structure verification before skipping recovery.
4. **Remediate AUDIT-P0-04 (Manifest Normalization Rule Binding):**
   Add `"normalization_rule": normalization_rule` to `_binding_fields()` in `manifest.py`, or document it as an unverified informational field.

---

## 7. Mandatory Governance Declarations

1. **No Merges:** No pull request has been merged to `main`.
2. **No Branch Alterations:** Claude's branches were inspected in read-only mode and left untouched.
3. **Zero Spend / No GPUs:** No cloud resources were provisioned, no training was initiated, and no money was spent (₹0).
4. **Training Authorization:** Native model training remains **STRICTLY NOT AUTHORIZED** (`NATIVE_MODEL_TRAINING_AUTHORIZATION = NO-GO`).
