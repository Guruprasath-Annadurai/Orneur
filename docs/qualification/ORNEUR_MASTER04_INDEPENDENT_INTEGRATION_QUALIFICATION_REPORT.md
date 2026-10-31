# ORNEUR — INDEPENDENT INTEGRATION QUALIFICATION REPORT
## MASTER-04: Vector-Owner Security, Encrypted Backup Consistency & Customer Data Integrity
### Final Evidence Closure & Adversarial Verification

**Executive Authority:** GPT-6 — ORNEUR Technical CTO  
**Independent Qualification Authority:** Antigravity  
**Date of Audit:** 31 October 2026  
**Candidate Pull Request:** [PR #148](https://github.com/Guruprasath-Annadurai/Orneur/pull/148) (`cursor/master-04-vector-backup-security-integration`)  
**Verified Candidate PR HEAD:** `da699a01bdb811ac54ef00cf0c9585f70eb74a57` (Tree: `106487db24a66672c7ca3e660a1d1e0792281238`)  
**Verified Candidate Code SHA:** `cadad0e525c5f84698af9945d048b9ba36aa4f0e` (Tree: `d1742759c1ecf25629f7bca1376719a75bd52d71`)  
**Integration Merge Commit:** `4295550b7991972e7a6b5cd1d25123b58355cbf1`  
**Parent PRs Integrated:**
- MASTER-03 (PR #146): `b96cc3260078b6f677a22381b05fe1f72026256f` (Tree: `168a6a2c75bd11e0cbac113e06ff4d50e88f9cae`)
- LANDMARK-03 (PR #147): `bfeaae2bc7470251262b3526e32fede7412996d8` (Code: `c8b0f54bafe364c18e507425570d34be1e7b8dd7`)
- Canonical Protected Main: `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`  
**Deterministic GitHub Actions CI:**
- Engineering Code CI: Run `41196122676` (10/10 passing)
- Final Documentation PR HEAD CI: Run `41197716243` (10/10 passing)  
**Independent Qualification Branch:** `antigravity/phase01-independent-qualification`  
**Independent Qualification Test Suite:** 16 passed in 17.07s (`tests/qualification/test_master04_independent_qualification.py`)

---

## 1. Executive Disposition & Mandatory Governance Ledger

### Formal Verdict
```
========================================================================================
FINAL DISPOSITION: MASTER-04 FINAL LIMITED-SCOPE EVIDENCE CLOSED
========================================================================================
```

> [!IMPORTANT]
> **GOVERNANCE & PRETRAINING ADMISSION INVARIANTS:**
> 1. **Model Training Authorization:** **STRICT NO-GO**. Zero GPU hours and zero compute spending authorized.
> 2. **Formal Native Pretraining Acceptance Ledger:** **Strictly 0/95** (`pretraining=95, numerator=0`). This audit qualifies vector-service runtime isolation, encrypted backup consistency, crash recovery, and customer data non-resurrection within MASTER-04 integration scope; it confers **zero** pretraining admissions.
> 3. **Draft Preservation:** Candidate PR #148 must remain in **Draft** status. No protected branch merges to `main` or release tags.
> 4. **Production Packaging Reality:** ChromaDB and backup cryptography are optional extras; containers deploying MASTER-04 must explicitly install the `memory` and `backup` extras via `uv pip install --system -e ".[postgres,memory]"`.

---

## 2. Errata & Evidence Corrections

Pursuant to the CTO Final Evidence Closure Order, the following initial audit reporting assertions have been formally corrected:

### Errata 1: Physical Erasure vs. Active Storage Byte Scan
- **Previous Statement:** *"Customer A raw secret text is 100% purged from disk."*
- **Correction:** Antigravity's empirical evidence proves strictly that **the tested plaintext marker was completely absent from scanned active storage files (`memory/vectors/*`) following reclamation and SQLite VACUUM**.
- **Crucial Distinction:** This active storage scan does **not** establish legal or forensic erasure, SSD NAND flash block reclamation (wear-leveling / un-overwritten physical blocks), underlying filesystem journaling/snapshots, OS swap, or pre-existing external backup archives.

### Errata 2: Container Packaging & Deployment Tooling
- **Previous Statement:** Prescribed `poetry install -E memory`.
- **Correction:** The repository does not use Poetry in Docker; it standardizes on `uv`. The production `Dockerfile` executes:
  ```dockerfile
  RUN uv pip install --system -e ".[postgres]"
  ```
  The optional `memory` extra (`chromadb`) and `backup` extra (`cryptography`) are **not** bundled in the base production container. Running vector owner services in production requires extending the build to install `.[postgres,memory]`.

### Errata 3: Qualification Scope & Attribution Boundaries
To prevent conflation of different assurance layers, all findings are strictly categorized:
1. **Source Inspection:** Code inspection of `server.py`, `client.py`, `backup.py`, `datadir_lock.py`.
2. **Cursor Reference Tests:** Cursor's 9 integration tests in `test_master04_integration.py`.
3. **Earlier LANDMARK-03 Findings:** Baseline freeze reproduction, AF_UNIX socket token boundaries, and memory RSS separation.
4. **New MASTER-04 Independent Adversarial Tests:** 16 tests in `test_master04_independent_qualification.py` (concurrency timeline mutual exclusion, `/proc/locks` kernel inspection, real SIGKILL crash fault-injection, and prefix collision defenses).
5. **Untested Scenarios:** Multi-host NFS locking, hardware failure during flash writes, production cloud multi-node deployments.

---

## 3. Task A: Concurrency Mutual Exclusion Timeline & Kernel `/proc/locks` Evidence

### Multi-Process Synchronization & Timeline
Eight independent OS processes (4 exclusive restore workers + 4 shared vector-owner workers) were synchronized using a multiprocessing barrier (`mp.Barrier(8)`) to force simultaneous contention over `home/.server.lock` (inode `134335`).

A machine-readable event log recorded every transition:
- Process start
- Lock acquisition attempt
- Critical section acquisition timestamp ($T_{\text{enter}}$)
- Kernel lock verification via `/proc/locks`
- Critical section release timestamp ($T_{\text{exit}}$)
- Refusal and exit

### Machine-Readable Event Sequence (Sample Run):
```
[2866.4790] PID 16118 (owner-2):   attempt
[2866.4790] PID 16113 (restore-0): attempt
[2866.4791] PID 16114 (owner-0):   attempt
[2866.4791] PID 16115 (restore-1): attempt
[2866.4792] PID 16116 (owner-1):   attempt
[2866.4792] PID 16117 (restore-2): attempt
[2866.4802] PID 16115 (restore-1): refused (RestoreFailed: another restore is in progress)
[2866.4802] PID 16118 (owner-2):   refused (RestoreFailed: a restore is in progress)
[2866.4802] PID 16114 (owner-0):   refused (RestoreFailed: a restore is in progress)
[2866.4803] PID 16117 (restore-2): refused (RestoreFailed: another restore is in progress)
[2866.4803] PID 16116 (owner-1):   refused (RestoreFailed: a restore is in progress)
[2866.4804] PID 16113 (restore-0): acquired (Holding EXCLUSIVE LOCK)
[2866.5306] PID 16113 (restore-0): released
```

### Kernel File-Descriptor Verification (`/proc/locks`)
While PID 16113 held the critical section, inspection of `/proc/locks` confirmed:
```
1: FLOCK  ADVISORY  WRITE 16113 00:1a:134335 0 EOF
```
- Inode: Matches `.server.lock` (`134335`).
- Mode: `WRITE` (exclusive).
- Holder PID: `16113`.
- Competing shared and exclusive callers: Rejected immediately with `RestoreFailed`.

### Mathematical Mutual Exclusion Invariant
Across all contention intervals:
$$\forall i, j: [T_{\text{enter}}^{R_i}, T_{\text{exit}}^{R_i}] \cap [T_{\text{enter}}^{O_j}, T_{\text{exit}}^{O_j}] = \emptyset$$
$$\forall i \neq j: [T_{\text{enter}}^{R_i}, T_{\text{exit}}^{R_i}] \cap [T_{\text{enter}}^{R_j}, T_{\text{exit}}^{R_j}] = \emptyset$$
**Measured Overlap: 0.0000s.** Zero critical-section collisions observed.

### Supervisor Restart Under Restore Lock
When `exclusive_data_dir(home)` is held, the vector supervisor's attempt to start or restart an owner results in the owner process exiting with code `2` after logging `vector owner refused to start: a restore is in progress`. The supervisor raises `VectorUnavailable`, does **not** write a PID file, and does **not** falsely advertise readiness.

---

## 4. Task B: Real Interrupted-Restore Crash Fault-Injection Evidence

Rather than simulating crash states via pre-fabricated files, Antigravity executed genuine process-level fault injection (`os.kill(os.getpid(), signal.SIGKILL)`) into live B6 restoration child processes across two distinct recovery transitions:

```
+---------------------------------------------------------------------------------------+
| REAL CRASH FAULT-INJECTION RESULTS (SIGKILL / SIGNAL 9)                              |
+--------------------------+---------------------+-------------------+------------------+
| Interruption Stage       | Transition Point    | Child Exit Code   | Recovery Result  |
+--------------------------+---------------------+-------------------+------------------+
| Transition 1             | After moving aside, | -9 (SIGKILL)      | 100% Original    |
| (Pre-Placement)          | before stage place  |                   | Files Restored   |
+--------------------------+---------------------+-------------------+------------------+
| Transition 2             | After stage place,  | -9 (SIGKILL)      | Clean Rollback,  |
| (Post-Placement)         | before journal wipe |                   | Re-Restore OK    |
+--------------------------+---------------------+-------------------+------------------+
```

### Transition 1 Lifecycle:
1. Child process enters `_swap()`, writes journal, moves original `auth.db` into `.pre-restore-*`.
2. Fault hook issues `SIGKILL`. Process terminates instantly with exit code `-9`. No Python finally blocks or cleanup handlers execute.
3. Parent inspects directory:
   - `(home / JOURNAL)` exists and is durable.
   - `restore_pending(home)` evaluates to `True`.
   - Subsequent `backup.restore()` refuses with `RestoreFailed: an earlier restore did not finish: run recover first`.
   - `/readyz` dependency status sets `restore: interrupted, ready: false`.
4. Parent executes `datadir_lock.recover_interrupted(home)`.
5. Integrity check: Original `auth.db` and vector collections are put back; journal is unlinked; `restore_pending(home)` becomes `False`.
6. VectorStore recall verifies `"verifiable secret data prior to crash"` is retrievable.

### Transition 2 Lifecycle:
1. Child process moves files aside and places staged files into `home`.
2. Fault hook issues `SIGKILL`. Process terminates with exit code `-9`.
3. Target directory contains partial stage replacement and durable journal.
4. Parent executes `recover_interrupted(home)`.
5. Replacement files are removed; original files are restored from aside; journal is cleaned.
6. A clean subsequent restore is executed and completes with `verified: True`.

---

## 5. Gate C: Vector Backup Consistency & Barrier Enforcement

### Strict Truth in Backup Advertising
1. **Unquiesced Active Owner:**
   Creating a backup with `quiesce_vector=False` while the vector owner is active flags `consistent: False` in the manifest and records:
   ```json
   "unstable_files": ["memory/vectors/(owner_active_no_quiesce_no_barrier)"]
   ```
   Restoring this archive without `allow_inconsistent=True` fails closed with:
   ```python
   BackupIncompleteError: the backup was taken while files were changing (flagged inconsistent: memory/vectors/(owner_active_no_quiesce_no_barrier))
   ```
2. **Quiesced Owner:**
   Creating a backup with `quiesce_vector=True` quiesces the owner process, snapshots SQLite, acquires the exclusive owner lock barrier, and records `consistent: True` with zero unstable files. Restoring back into the home directory completes with `verified: True` and all vector collections intact.

---

## 6. Gate D: Customer Data Non-Resurrection & Active Storage Scanning

### End-to-End Deletion & Restoration Lifecycle
- **Customer A (`user_a`) & Customer B (`user_b`):** Both customers created private memories and sessions. Encrypted backup was captured.
- **Customer A Deletion:** Customer A executed `deletions.begin / deletions.run`. Tombstones and SHA-chained entries were appended to `deletion_ledger.jsonl`.
- **Restoration of Older Backup:** Older backup (containing Customer A's deleted data) was restored using `backup.restore(overwrite=True)`.
- **Immediate Tombstone Revocation:** `_apply_deletions` inserted tombstones into `session_deletions` with state `revoked` and deleted session rows from `turns.db`. An immediate query to Customer A's memory returned `[]` (access revoked).
- **Maintenance Sweep:** Executing `deletions.resume_pending()` swept the pending deletions:
  - Collection `orca_<sid_a[:8]>` was removed.
  - Active storage SQLite VACUUM executed.
  - Byte scan across active files in `memory/vectors/*` confirmed Customer A's target secret plaintext marker was **completely absent**.
- **Customer B Isolation:** Customer B's retained memory (`BETA_SAFE`) remained intact and retrievable.
- **Missing Ledger Defense:** Restoring into an environment lacking a deletion ledger raised `DeletionHistoryUnavailable`. Passing `unsafe_without_deletion_history=True` succeeded with `deleted_data_may_be_present: True` and explicit statement warnings.

---

## 7. Gate H: Production Image Packaging Architecture

### Dockerfile Reality
Inspection of `Dockerfile` at candidate HEAD `da699a0` confirmed:
- Build command: `uv pip install --system -e ".[postgres]"`
- Base image does **not** include `chromadb` (vector owner) or `cryptography` (backup encryption).
- For deployments requiring out-of-process vector containment, the build must specify:
  ```dockerfile
  RUN uv pip install --system -e ".[postgres,memory,backup]"
  ```
- Deploying the default slim image is appropriate for relational-only workloads, but vector service initialization will cleanly fail closed or fall back without crashing the container.

---

## 8. Gate K: Governance Immutability & Model Truth

### Pretraining Acceptance Ledger
Inspection of `docs/orneur/acceptance/register_graph.json` confirmed:
- `denominator_pretraining_ids`: Exactly 95 IDs.
- `numerator_pretraining`: **0**.
- `published_pretraining_percentage`: `null` (0%).
- `FINAL-2`, `EXEC-1`, `AUTH-2`, `AUTH-3`: All status `NOT_AUTHORIZED`.
- Training authorization: **STRICT NO-GO**.

---

## 9. Residual Blocker Register: MASTER-04 Final Closure

```
+----------------------------------------------------------------------------------------------------+
| MASTER-04 RESIDUAL BLOCKER REGISTER & FINAL AUDIT DISPOSITION                                       |
+----------+-------------------------------------------------------+------------------+--------------+
| Blocker  | Description                                           | Status           | Disposition  |
+----------+-------------------------------------------------------+------------------+--------------+
| M04-B1   | Vector Owner & Restore Mutual Exclusion (Gate H)      | RESOLVED         | Verified Pass|
| M04-B2   | Owner Lock Refusal Fail-Closed Exit 2                 | RESOLVED         | Verified Pass|
| M04-B3   | Active Owner Inconsistent Backup Flagging             | RESOLVED         | Verified Pass|
| M04-B4   | Quiesced Owner Consistent Vector Backup               | RESOLVED         | Verified Pass|
| M04-B5   | Active Storage Text Absence Following Deletion Sweep  | RESOLVED         | Verified Pass|
| M04-B6   | Missing Deletion History Refusal & Warning Flags      | RESOLVED         | Verified Pass|
| M04-B7   | Real Crash SIGKILL Fault-Injection & Recovery         | RESOLVED         | Verified Pass|
| M04-B8   | Session 8-Character Prefix Collision Defense          | RESOLVED         | Verified Pass|
| M04-B9   | Integration DAG Ancestry Preservation                 | RESOLVED         | Verified Pass|
| M04-B10  | Same-UID Filesystem Socket Token Local Boundary       | DOCUMENTED RISK  | Architecture |
| M04-B11  | Production Docker Image Requires Optional Extras      | DOCUMENTED RISK  | Operations   |
| M04-B12  | Formal Pretraining Ledger Admissions (0/95)           | UNRESOLVED (HOLD)| Pretraining  |
+----------+-------------------------------------------------------+------------------+--------------+
```

---

## 10. Independent Test Reproducibility

To independently reproduce the complete 16-test qualification suite:
```bash
git fetch origin antigravity/phase01-independent-qualification
git checkout antigravity/phase01-independent-qualification
pytest tests/qualification/test_master04_independent_qualification.py -v
```

**Passing Test Output:**
```
============================= test session starts ==============================
platform linux -- Python 3.11.18, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/pc/projects/Orneur
configfile: pyproject.toml
collected 16 items

tests/qualification/test_master04_independent_qualification.py::test_gate_a_integration_dag_ancestry_and_code_doc_separation PASSED [  6%]
tests/qualification/test_master04_independent_qualification.py::test_gate_a_fail_closed_ancestry_under_shallow_or_missing_objects PASSED [ 12%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_restore_refuses_while_vector_owner_serves PASSED [ 18%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_owner_refuses_under_exclusive_restore_lock PASSED [ 25%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_concurrency_timeline_mutual_exclusion_and_proc_locks PASSED [ 31%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_supervisor_restart_under_held_restore_lock PASSED [ 37%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_frozen_owner_holding_serving_lock_refuses_restore PASSED [ 43%]
tests/qualification/test_master04_independent_qualification.py::test_gate_c_unquiesced_owner_never_claims_consistency PASSED [ 50%]
tests/qualification/test_master04_independent_qualification.py::test_gate_c_quiesced_owner_allows_consistent_backup_and_verifies_data PASSED [ 56%]
tests/qualification/test_master04_independent_qualification.py::test_gate_d_customer_non_resurrection_after_backup_and_sweep PASSED [ 62%]
tests/qualification/test_master04_independent_qualification.py::test_gate_d_missing_deletion_history_refusal_and_unsafe_override PASSED [ 68%]
tests/qualification/test_master04_independent_qualification.py::test_gate_e_real_interrupted_restore_sigkill_fault_injection PASSED [ 75%]
tests/qualification/test_master04_independent_qualification.py::test_gate_e_synthetic_journal_fail_closed_recovery PASSED [ 81%]
tests/qualification/test_master04_independent_qualification.py::test_gate_f_session_prefix_truncation_collision_isolation PASSED [ 87%]
tests/qualification/test_master04_independent_qualification.py::test_gate_h_dockerfile_packaging_reality PASSED [ 93%]
tests/qualification/test_master04_independent_qualification.py::test_governance_immutability_and_formal_acceptance_zero PASSED [100%]

============================= 16 passed in 17.07s ==============================
```

---
**Report signed by:**  
*Antigravity — Independent Engineering, Security & Qualification Authority*  
*ORNEUR System Integrity Directorate*
