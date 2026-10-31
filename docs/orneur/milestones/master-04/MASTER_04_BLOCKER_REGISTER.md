# MASTER-04 — blocker register

| ID | Sev | Item | State |
|---|---|---|---|
| M04-1 | P1 | B6 restore unaware of vector owner (L03-B1) | **FIXED (engineering)** — owner holds B6 serving_lock fail-closed; restore refuses while owner up; owner refuses under exclusive restore lock |
| M04-2 | P2 | Vector backup `consistent:true` from readable sample (L03-B2) | **FIXED (engineering)** — require quiesce (A) or owner-lock barrier (B); otherwise inconsistent |
| M04-3 | P2 | X2 JSON said RestoreFailed vs blocker said proceeded | **DISCLOSED** — proceeded reproduced; RestoreFailed unconfirmed on this tip |
| M04-4 | — | Independent Antigravity OWN_EVIDENCE / formal acceptance | **OPEN** — Cursor not authorized to certify |
| M04-5 | — | Prod vector backend / Chroma in public image | **BLOCKED** founder |
| M04-6 | — | Backup crypto in public image | **BLOCKED** founder (extra only; Dockerfile stays `.[postgres]`) |
| M04-7 | — | Key custody, retention, off-host anchor, PG dumps, multi-host locks | **BLOCKED** founder |
| M04-8 | — | Paid infra / launch / training / protected merge | **BLOCKED** |
| M04-9 | P2 | Chromadb WAL growth on live collections (L03-B3) | OPEN (engine behaviour) |
| M04-10 | — | Physical erasure of storage medium | **UNPROVEN by design** |
| M04-11 | P1 | Lifespan left `enable_service_mode(True)` sticky → Deterministic CI vector deletions failed (`bad_root`) | **FIXED (engineering)** — lifespan clears service mode + transport cache on exit; Journeys `fetch-depth:0` for ancestry |

Unresolved P0: 0. Engineering P1 for integration: closed pending independent retest / exact-head CI. Formal acceptance **0/95**.
