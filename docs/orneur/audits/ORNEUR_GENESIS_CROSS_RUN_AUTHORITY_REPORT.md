# ORNEUR GENESIS CHECKPOINT SECURITY — CROSS-RUN AUTHORITY AUDIT REPORT (G02)

**Defect ID:** AUDIT-P0-G02  
**Severity:** CRITICAL / P0 SECURITY & AUTHORITY DEFECT  
**Target:** `orca/genesis/training/resumable_checkpoint.py` & `isolated_worker.py`  
**Classification:** Cross-Run Checkpoint Hijacking / Unbounded Authority Delegation  
**Test Reproduction:** `tests/test_genesis_checkpoint_adversarial_regression.py::test_g02_*`  
**Lead Auditor:** Antigravity / Gemini Engineering & Independent Audit Agent  

---

## 1. Vulnerability Summary

In ORNEUR GENESIS, training runs are strictly partitioned by founder execution grants and unique `run_id` identifiers. Each run possesses distinct resource limits, model configurations, and cryptographic authorizations.

Our independent audit discovered that **`run_id` is omitted from the checkpoint manifest's HMAC-tagged fields**. 

Consequently, an authorized checkpoint produced by Run A (`run-001`) can be arbitrarily loaded and resumed by Run B (`run-002`) without founder migration authorization, provided Run B uses the same integrity key and compatible model configuration. The anti-rollback ledger check is completely bypassed because Run B's ledger is at step 0, trivially accepting Run A's step.

---

## 2. Root Cause Analysis

### Omission of `run_id` from HMAC Binding in `resumable_checkpoint.py`:

```python
# Lines 216-226: ResumableManifest definition
@dataclass(frozen=True)
class ResumableManifest:
    schema_version: str
    inner_checkpoint_sha256: str
    global_step: int
    microbatch_in_cycle: int
    sampler_position: int
    sampler_seed: int
    sampler_num_blocks: int
    config_fingerprint: str
    dataset_identity: DatasetIdentity
    # NOTE: run_id is completely absent from the manifest!
```

### Manifest Tag Computation (Lines 290–305):

```python
def _compute_manifest_hmac(manifest: ResumableManifest, integrity_key: bytes) -> str:
    tag_payload = (
        f"{manifest.schema_version}:"
        f"{manifest.inner_checkpoint_sha256}:"
        f"{manifest.global_step}:"
        f"{manifest.microbatch_in_cycle}:"
        f"{manifest.sampler_position}:"
        f"{manifest.sampler_seed}:"
        f"{manifest.sampler_num_blocks}:"
        f"{manifest.config_fingerprint}:"
        f"{manifest.dataset_identity.to_digest()}"
    ).encode("utf-8")
    return hmac.new(integrity_key, tag_payload, hashlib.sha256).hexdigest()
```

### Exploit Scenario:
1. Run A (`run_id="run-genesis-alpha"`) trains up to step 1,000 under a restricted grant.
2. Run B (`run_id="run-genesis-beta"`) starts fresh. Run B's monotonic ledger for `run-genesis-beta` is initialized to step 0.
3. An adversary or misconfigured worker invokes `restore_resumable_checkpoint(path="alpha_step1000.pt", run_id="run-genesis-beta")`.
4. `_read_ledger("run-genesis-beta", key)` returns `0`.
5. Check `manifest.global_step (1000) < ledger_highest (0)` is `False`.
6. Manifest HMAC verification succeeds because `run_id` was never included in the tag payload.
7. Run B resumes from Run A's state, **crossing security boundaries without founder migration approval**.

---

## 3. Independent Adversarial Reproduction

The vulnerability is deterministically verified in `tests/test_genesis_checkpoint_adversarial_regression.py`:

```python
def test_g02_checkpoint_authority_manifest_omits_run_id_allowing_cross_run_restore(tmp_path):
    # Demonstrates that a checkpoint saved under run_id="run_A" is successfully restored
    # under run_id="run_B" without raising any authority or tamper exceptions.
```

Test result:
```
tests/test_genesis_checkpoint_adversarial_regression.py::test_g02_checkpoint_authority_manifest_omits_run_id_allowing_cross_run_restore PASSED [ 75%]
```

---

## 4. Minimal Remediating Architecture

To enforce cryptographic run confinement:
1. **Add `origin_run_id: str`** to `ResumableManifest`.
2. **Include `origin_run_id` in `tag_payload`** during HMAC tag computation.
3. **Assert `manifest.origin_run_id == run_id`** in `restore_resumable_checkpoint`.
4. **Migration Protocol:** Cross-run restoration should only be permitted if an explicit `FounderMigrationGrant` (signed by the founder's private key) is supplied to authorise the transfer from `origin_run_id` to `target_run_id`.

```diff
--- a/orca/genesis/training/resumable_checkpoint.py
+++ b/orca/genesis/training/resumable_checkpoint.py
@@ -226,6 +226,7 @@ class ResumableManifest:
     config_fingerprint: str
     dataset_identity: DatasetIdentity
+    origin_run_id: str

@@ -299,6 +300,7 @@ def _compute_manifest_hmac(manifest: ResumableManifest, integrity_key: bytes) -
         f"{manifest.config_fingerprint}:"
-        f"{manifest.dataset_identity.to_digest()}"
+        f"{manifest.dataset_identity.to_digest()}:"
+        f"{manifest.origin_run_id}"
     ).encode("utf-8")
```
