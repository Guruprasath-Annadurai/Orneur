# L02-05 — Resource and deployment reconciliation

Evidence state: **VERIFIED_ENGINEERING** (synthetic fixtures only; no production resource was touched). Code: `orca/gateway/{reconcile,deployment,wiring}.py`, `/api/admin/reconcile`. Tests: `tests/test_l02_resource_reconciliation.py` (16). Baseline defect: `evidence/l02_05_baseline_deployment_listing_9cb864c.txt` (an orphan/corrupt deployment record broke listing and accumulated forever).

## Framework
Ledger of candidates → **observe twice** (a resource must look orphaned on two sweeps ≥ one interval apart) → **quarantine** (moved, not deleted) → later purge; bounded per sweep (`MAX_ACTIONS_PER_SWEEP=25`), bounded retries (`MAX_ATTEMPTS=5`, then `blocked` and reported without stopping other work), lease-guarded (`LEASE_S=120 s`) so concurrent workers do not double-act.

* **Live announcements:** each worker announces the deployment ids it serves (`LIVE_TTL_S=600 s`); announced ids are never treated as orphans.
* **Protected resources** (anything referenced by a registry record, a legacy-production deployment, or a pinned artifact) are never touched.
* **Atomic saves** of deployment records (write-temp + `os.replace`); listing tolerates a corrupt record.
* **Orphan document chunks** and temp remnants are handled by the same ledger.
* **Operator diagnostics:** `GET /api/admin/reconcile` (permission `manage_users`) reports ledger state; nothing is acted on without the two observations.

## Limits
Only the deployment-record store, orphaned chunks and temp remnants are covered. Cloud resources are out of scope (no cloud provisioned). Thresholds are conservative defaults, not tuned.
