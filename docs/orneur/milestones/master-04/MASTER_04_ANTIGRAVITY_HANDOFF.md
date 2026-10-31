# MASTER-04 — Antigravity independent retest handoff

Retest the **exact PR branch HEAD** of `cursor/master-04-vector-backup-security-integration` (record SHA+tree from that tip). Code identity for the lock/consistency fixes: `d3afeccb281887c25b629067cd43582a9384ea77` / tree `13da074378c7bfc413d57673e6a1e6c2ba91fb90`. Merge ancestry commit `4295550b7991972e7a6b5cd1d25123b58355cbf1`.

Do not certify from Cursor engineering claims alone.

## Must verify with OWN_EVIDENCE
1. Ancestry: M03 tip + L03 code/doc are ancestors; missing objects fail closed; no shallow bypass.
2. Owner holds B6 serving_lock; restore refuses while owner up; owner refuses under restore exclusive lock (exit/unavailable — not ready).
3. Backup `consistent` never true for active-owner vector copy without quiesce/barrier.
4. Deletion restore path: tombstones + sweep; distinguish access revoked / logical delete / collection removed / reclamation / physical erasure unproven.
5. Multi-process restore races fail closed.
6. MASTER-03 security/functionality still holds (TOTP/B3/B6/auth/streaming/RAG/RSE/governance/training denial).
7. Public image still lacks chromadb/backup crypto extras.
8. Suite `tests/qualification/test_master04_integration.py` green on this SHA in CI.

Reference (not merged): Antigravity audit-test commit `167e0ca0b53a1f3bda5a7813155dd009ee1e9a00`.
