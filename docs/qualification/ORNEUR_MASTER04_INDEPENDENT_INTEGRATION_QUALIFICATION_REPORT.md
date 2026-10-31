# ORNEUR — INDEPENDENT INTEGRATION QUALIFICATION REPORT
## MASTER-04: Vector-Owner Security, Encrypted Backup Consistency & Customer Data Integrity

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
**Independent Qualification Test Commit:** [`4db2d47`](https://github.com/Guruprasath-Annadurai/Orneur/commit/4db2d47) on branch `antigravity/phase01-independent-qualification`  
**Independent Qualification Suite Result:** 14 passed in 15.19s (`tests/qualification/test_master04_independent_qualification.py`)

---

## 1. Executive Disposition & Mandatory Governance Ledger

### Formal Verdict
```
========================================================================================
FINAL DISPOSITION: QUALIFIED_LIMITED_SCOPE — MASTER-04 INTEGRATION CANDIDATE ONLY
========================================================================================
```

> [!IMPORTANT]
> **GOVERNANCE & PRETRAINING ADMISSION INVARIANTS:**
> 1. **Model Training Authorization:** **STRICT NO-GO**. Zero GPU hours and zero compute spending authorized.
> 2. **Formal Native Pretraining Acceptance Ledger:** **Strictly 0/95** (`pretraining=95, numerator=0`). This audit qualifies vector-service runtime isolation, encrypted backup consistency, and customer data non-resurrection within MASTER-04 integration scope; it confers **zero** pretraining admissions.
> 3. **Draft Preservation:** Candidate PR #148 must remain in **Draft** status. No protected branch merges to `main` or release tags.
> 4. **Production Packaging Boundary:** ChromaDB and backup cryptography are optional extras; containers deploying MASTER-04 must explicitly install the `memory` and `backup` extras.

---

## 2. Candidate Provenance & Code/Documentation Separation

### Exact SHA & Tree Identity Verification
| Component | Verified Value | Verification Status |
| :--- | :--- | :--- |
| **Documentation PR HEAD** | `da699a01bdb811ac54ef00cf0c9585f70eb74a57` | Remote `origin/cursor/master-04-vector-backup-security-integration` verified |
| **Documentation Tree** | `106487db24a66672c7ca3e660a1d1e0792281238` | Clean worktree confirmed |
| **Engineering Code SHA** | `cadad0e525c5f84698af9945d048b9ba36aa4f0e` | Verified exact code tip |
| **Engineering Code Tree** | `d1742759c1ecf25629f7bca1376719a75bd52d71` | Clean executable tree verified |
| **Merge Commit** | `4295550b7991972e7a6b5cd1d25123b58355cbf1` | Verified two-parent merge |
| **Parent 1 (MASTER-03)** | `b96cc3260078b6f677a22381b05fe1f72026256f` | Verified exact tip of PR #146 |
| **Parent 2 (LANDMARK-03)** | `bfeaae2bc7470251262b3526e32fede7412996d8` | Verified exact doc tip of PR #147 |

### Code vs Documentation Separation Verification
A strict diff audit between engineering code SHA `cadad0e` and PR HEAD `da699a0` confirmed that strictly seven documentation and evidence files were modified, all under `docs/orneur/milestones/master-04/`:
- `docs/orneur/milestones/master-04/MASTER_04_ANTIGRAVITY_HANDOFF.md`
- `docs/orneur/milestones/master-04/MASTER_04_BLOCKER_REGISTER.md`
- `docs/orneur/milestones/master-04/MASTER_04_CI_EVIDENCE.md`
- `docs/orneur/milestones/master-04/MASTER_04_CTO_HANDOFF.md`
- `docs/orneur/milestones/master-04/MASTER_04_ENGINEERING_REPORT.md`
- `docs/orneur/milestones/master-04/MASTER_04_RED_TO_GREEN.md`
- `docs/orneur/milestones/master-04/merge-ancestry.json`

Zero lines of application code (`orca/*`), test code (`tests/*`), or governance configuration (`evalinfra/*`, `docs/orneur/acceptance/*`) were modified between `cadad0e` and `da699a0`.

---

## 3. Gate A: Complete Integration DAG Ancestry & Fail-Closed Checks

### Ancestry Preservation
Antigravity independently validated that merge commit `4295550` preserves the direct topological ancestry of all required milestones:
```bash
git merge-base --is-ancestor <commit> 4295550b7991972e7a6b5cd1d25123b58355cbf1
```
- **Canonical Main (`20a8546f`):** Ancestor verified.
- **Foundation F02 & F03:** Ancestor verified.
- **LANDMARK-01 & LANDMARK-02:** Ancestor verified.
- **L02-B3 API-Key Reauthentication (`283e3a46`):** Ancestor verified.
- **L02-B6 Backup Privacy & Restoration (`4ab809df`):** Ancestor verified.
- **MASTER-02 Integration Tip (`d8827409`):** Ancestor verified.
- **MASTER-03 Integration Tip (`b96cc326`):** Ancestor verified (Parent 1).
- **LANDMARK-03 Vector Containment (`bfeaae2b` / code `c8b0f54b`):** Ancestor verified (Parent 2).

### Fail-Closed Ancestry Invariant
In `test_gate_a_fail_closed_ancestry_under_shallow_or_missing_objects`, deliberately checking an unresolvable or missing object SHA resulted in a non-zero exit code. Ancestry gating fails closed and prohibits shallow bypasses.

---

## 4. Gate B: Vector-Owner & Restore Lock Security (P1)

### Bidirectional Mutual Exclusion
MASTER-04 resolves the critical Gate H cross-workstream hazard identified during the LANDMARK-03 audit:
1. **Serving Lock Acquisition in `server.py`:**
   When `orca.vectorstore.server` starts, before advertising readiness or creating PID files, it executes:
   ```python
   serving_cm = datadir_lock.serving_lock(home)
   serving_cm.__enter__()
   ```
   This acquires `fcntl.flock(home / ".server.lock", LOCK_SH)`.
2. **Restore Refusal While Owner Serves:**
   When `backup.restore(..., overwrite=True)` is called while the vector owner is active, `exclusive_data_dir(home)` attempts `fcntl.flock(home / ".server.lock", LOCK_EX | LOCK_NB)`. This is rejected with `RestoreFailed: a server is running on this data directory: stop it before restoring`. The owner remains online and uncorrupted.
3. **Owner Refusal Under Exclusive Restore Lock:**
   When `exclusive_data_dir(home)` is held by a restore, spawning the vector owner process results in:
   - `server.py` catching `RestoreFailed` or `OSError`.
   - `server.py` logging `"vector owner refused to start: ..."` to stderr.
   - `server.py` unlinking `pid_path(home)` and immediately exiting with code `2`.
   - `client.py` detecting the exit code and logged refusal, raising `VectorUnavailable("vector owner refused to start (data-directory lock held by a restore or unavailable)")`.
4. **Frozen Owner (`SIGSTOP`) Protection:**
   Freezing an owner holding `serving_lock` with `SIGSTOP` leaves its lock fd active in the Linux kernel table. An attempt to restore is still rejected with `RestoreFailed`. Once the supervisor or operator terminates the frozen process with `SIGKILL`, the kernel releases the file lock, and subsequent restoration succeeds cleanly.
5. **Multi-Process Concurrency Race:**
   A stress race between 8 simultaneous restore workers and 8 vector owner starters verified that in every instance, either the restore or the owner exclusively held the directory; zero concurrent overlapping executions occurred, and every conflicting process failed closed with expected exceptions.

---

## 5. Gate C: Vector Backup Consistency (P1)

### Consistency Determination Contract
MASTER-04 enforces strict truth in advertising regarding vector snapshot consistency:

```
+---------------------------------------------------------------------------------------+
| VECTOR BACKUP CONSISTENCY STATES                                                      |
+--------------------------+---------------------+-------------------+------------------+
| Vector Owner State       | Parameter Passed    | Declared In Manifest | Unstable Files |
+--------------------------+---------------------+-------------------+------------------+
| Active (No Quiesce)      | quiesce_vector=False| consistent: False | ['memory/vectors/|
|                          |                     |                   | (owner_active...)']
| Quiesced / Barrier Held  | quiesce_vector=True | consistent: True  | [] (Empty)       |
+--------------------------+---------------------+-------------------+------------------+
```

### Invariants Independently Verified:
1. **Never Claim Consistency from a Sample Query:** When the owner process is running without quiescence, even if all vector collections are readable, `backup.create()` records `owner_active_during_copy = True` and forces `consistent: False`.
2. **Fail-Closed Restoration of Inconsistent Backups:** Attempting to restore an inconsistent archive without passing `allow_inconsistent=True` immediately raises:
   ```python
   BackupIncompleteError: the backup was taken while files were changing (flagged inconsistent: memory/vectors/(owner_active_no_quiesce_no_barrier))
   ```
3. **Quiesced Backup Integrity:** Backups created with `quiesce_vector=True` quiesce the owner, take an online SQLite snapshot, hold the owner barrier, and produce a fully consistent archive. Restoring this archive back into the data directory restores all collections, embeddings, and ownership bindings cleanly.

---

## 6. Gate D: Customer Data Non-Resurrection (P1)

### Multi-Tenant Deletion & Sweep Lifecycle
Antigravity verified the end-to-end non-resurrection contract across synthetic Customer A (`custA`) and Customer B (`custB`):

1. **Initial State & Backup:** Customer A and Customer B both store private memories and conversations. An encrypted backup is captured with `quiesce_vector=True`.
2. **Customer A Deletion:** Customer A executes deletion (`deletions.begin(sid_a, ua.id); deletions.run(sid_a, ua.id)`). Deletion tombstones and SHA-chained entries are recorded in `deletion_ledger.jsonl`.
3. **Older Backup Restoration:** The older backup (which contains Customer A's deleted data) is restored using `backup.restore(..., overwrite=True)`.
4. **Immediate Tombstone Revocation:** During `_apply_deletions`, the restorer inspects `deletion_ledger.jsonl`, inserts tombstones into `session_deletions` with state `revoked`, and purges session rows from `turns.db`. An immediate query to Customer A's memory (`recall()`) returns `[]` (access revoked).
5. **Physical Reclamation Sweep:** Executing `deletions.resume_pending()` triggers the deletion sweep:
   - The vector collection `orca_<sid_a[:8]>` is dropped.
   - SQLite tables undergo `PRAGMA secure_delete=ON` and `VACUUM`.
   - A raw byte scan across all files in `memory/vectors/` confirms that Customer A's secret plaintext is **100% purged from disk**.
6. **Customer B Retention:** Customer B's retained memory remains completely intact, queryable, and unaffected by Customer A's deletion sweep.
7. **Missing Deletion History Defense:** Attempting to restore into an environment without an authoritative deletion ledger raises `DeletionHistoryUnavailable`. The unsafe override (`unsafe_without_deletion_history=True`) sets `deleted_data_may_be_present: True` and includes an explicit statement warning.

---

## 7. Gate E: Interrupted Restore Crash & Recovery

### Journal Recovery Invariant
In `test_gate_e_interrupted_restore_journal_and_fail_closed_recovery`:
1. When a restore is interrupted during directory replacement, a `.restore-journal.json` remains in the data directory.
2. `datadir_lock.restore_pending(home)` evaluates to `True`.
3. Any subsequent attempt to restore or start serving fails closed with:
   ```python
   RestoreFailed: an earlier restore did not finish: run recover first
   ```
4. Running `datadir_lock.recover_interrupted(home)` safely reads the journal, moves the replacement files aside, restores the original directory state, and removes the journal. Normal operations resume cleanly.

---

## 8. Gate F: Tenant Ownership & Truncation Collisions

### 8-Character Prefix Collision Protection
1. Two distinct sessions colliding on the first 8 characters (`abcdef01-custA-session` vs `abcdef01-custB-session`) map to collection `orca_abcdef01`.
2. The SQLite binding sidecar (`orneur_bindings.sqlite`) records an immutable mapping to Customer A's session hash.
3. Customer B's attempt to read or write to the collection is rejected with:
   ```python
   VectorOwnershipError: collection belongs to another conversation
   ```
4. Customer B's attempt to delete the collection via `delete_collection` returns `{"refused": "not_owner"}`. Customer A's data remains untouched.

---

## 9. Gate H: Production Image & Packaging Reality

### Container Dependency Reality
Inspection of `Dockerfile` in MASTER-04 confirms:
- The base production container image installs only core dependencies; it does **not** silently include `chromadb` or `cryptography`.
- Enabling the vector owner and encrypted backup features in production requires installing the `memory` and `backup` extras:
  ```bash
  poetry install -E memory
  ```
- Deploying the default slim image without these extras boots the core application safely, but vector service operations will cleanly fall back or report missing dependencies rather than crashing.

---

## 10. Gate K: Governance Immutability & Formal Acceptance Ledger

### Formal Native Pretraining Acceptance Ledger
Inspection of `docs/orneur/acceptance/register_graph.json` confirms:
```json
{
  "denominator_pretraining_ids": 95,
  "numerator_pretraining": 0,
  "published_pretraining_percentage": null,
  "nodes": [
    {"id": "FINAL-2", "status": "NOT_AUTHORIZED"},
    {"id": "EXEC-1",  "status": "NOT_AUTHORIZED"},
    {"id": "AUTH-2",  "status": "NOT_AUTHORIZED"},
    {"id": "AUTH-3",  "status": "NOT_AUTHORIZED"}
  ]
}
```
The formal native pretraining acceptance ledger remains strictly **0/95**. Zero pretraining authorizations or weight creation events occurred.

---

## 11. Residual Blocker Register: MASTER-04

```
+----------------------------------------------------------------------------------------------------+
| MASTER-04 RESIDUAL BLOCKER REGISTER & DISPOSITION                                                  |
+----------+-------------------------------------------------------+------------------+--------------+
| Blocker  | Description                                           | Status           | Disposition  |
+----------+-------------------------------------------------------+------------------+--------------+
| M04-B1   | Vector Owner & Restore Mutual Exclusion (Gate H Defect) | RESOLVED       | Verified Pass|
| M04-B2   | Owner Lock Refusal Fail-Closed Exit 2                 | RESOLVED         | Verified Pass|
| M04-B3   | Active Owner Inconsistent Backup Flagging             | RESOLVED         | Verified Pass|
| M04-B4   | Quiesced Owner Consistent Vector Backup               | RESOLVED         | Verified Pass|
| M04-B5   | Customer Data Non-Resurrection & Physical Byte Purge  | RESOLVED         | Verified Pass|
| M04-B6   | Missing Deletion History Refusal & Warning Flags      | RESOLVED         | Verified Pass|
| M04-B7   | Interrupted Restore Journaling & Crash Recovery       | RESOLVED         | Verified Pass|
| M04-B8   | Session 8-Character Prefix Collision Defense          | RESOLVED         | Verified Pass|
| M04-B9   | Integration DAG Ancestry Preservation                 | RESOLVED         | Verified Pass|
| M04-B10  | Same-UID Filesystem Socket Token Local Boundary       | DOCUMENTED RISK  | Architecture |
| M04-B11  | Production Docker Image Requires Optional Extras      | DOCUMENTED RISK  | Operations   |
| M04-B12  | Formal Pretraining Ledger Admissions (0/95)           | UNRESOLVED (HOLD)| Pretraining  |
+----------+-------------------------------------------------------+------------------+--------------+
```

---

## 12. Independent Qualification Test Reproducibility

To independently reproduce the complete 14-test qualification suite:
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
collected 14 items

tests/qualification/test_master04_independent_qualification.py::test_gate_a_integration_dag_ancestry_and_code_doc_separation PASSED [  7%]
tests/qualification/test_master04_independent_qualification.py::test_gate_a_fail_closed_ancestry_under_shallow_or_missing_objects PASSED [ 14%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_restore_refuses_while_vector_owner_serves PASSED [ 21%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_owner_refuses_under_exclusive_restore_lock PASSED [ 28%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_multiprocess_serving_vs_restore_concurrency_race PASSED [ 35%]
tests/qualification/test_master04_independent_qualification.py::test_gate_b_frozen_owner_holding_serving_lock_refuses_restore PASSED [ 42%]
tests/qualification/test_master04_independent_qualification.py::test_gate_c_unquiesced_owner_never_claims_consistency PASSED [ 50%]
tests/qualification/test_master04_independent_qualification.py::test_gate_c_quiesced_owner_allows_consistent_backup_and_verifies_data PASSED [ 57%]
tests/qualification/test_master04_independent_qualification.py::test_gate_d_customer_non_resurrection_after_backup_and_sweep PASSED [ 64%]
tests/qualification/test_master04_independent_qualification.py::test_gate_d_missing_deletion_history_refusal_and_unsafe_override PASSED [ 71%]
tests/qualification/test_master04_independent_qualification.py::test_gate_e_interrupted_restore_journal_and_fail_closed_recovery PASSED [ 78%]
tests/qualification/test_master04_independent_qualification.py::test_gate_f_session_prefix_truncation_collision_isolation PASSED [ 85%]
tests/qualification/test_master04_independent_qualification.py::test_gate_h_dockerfile_packaging_reality PASSED [ 92%]
tests/qualification/test_master04_independent_qualification.py::test_governance_immutability_and_formal_acceptance_zero PASSED [100%]

============================= 14 passed in 15.19s ==============================
```

---
**Report signed by:**  
*Antigravity — Independent Engineering, Security & Qualification Authority*  
*ORNEUR System Integrity Directorate*
