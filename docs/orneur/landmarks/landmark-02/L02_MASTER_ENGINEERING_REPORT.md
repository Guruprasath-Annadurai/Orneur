# LANDMARK-02 — master engineering report (interim: L02-01 and L02-02 delivered)

**Milestone status: PARTIAL.** Delivered and verified at engineering level: L02-01 (data lifecycle & deletion) and L02-02 (document conversations). **Not started:** L02-03 recovery contract, L02-04 account verification, L02-05 resource reconciliation, L02-06 operational readiness, L02-07 customer journeys, L02-08 model-identity audit. The milestone cannot be marked complete until those are done. Nothing here is independently qualified; nothing is merged or deployed.

Lineage: PR #134 `8d72baab…` → PR #135 `15befec7…` → PR #136 `9cb864c9…` (unmodified, under Antigravity qualification) → this branch (draft PR #139). Last product-code SHA: `11801a8`.

## Delivered
* **L02-01** — see `L02_DATA_LIFECYCLE_AND_DELETION.md`. Durable deletion identity + access-revoking tombstone; `200` only when every store confirmed, `202` partial with per-store status; ownership kept until complete; resume sweep; dual-store document deletion. Reproduced baseline defects: partial failure reported as success with ownership released; document delete left keyword-index text retrievable and swallowed errors.
* **L02-02** — see `L02_DOCUMENT_RAG_CORRECTNESS.md`. Measured (real `llama3.2:1b`): plain-plan document questions generated one **discarded** Kernel answer per turn on the baseline (3/3 runs) and none now (3/3). Plus upload hardening, chunk identity and multi-document attribution, registry-enforced retrieval, untrusted-content framing, fail-closed abstention, unsupported-citation reporting.

## Test evidence (this branch)
New: `test_l02_deletion_lifecycle.py` (15), `test_l02_doc_store_deletion.py` (4), `test_l02_document_dispatch.py` (7), `test_l02_document_rag.py` (18), `tests/journey/test_l02_document_real_live.py` (3, real Ollama, workstation). Baseline red: 15/18 of the document-RAG tests and 2/4 of the first dispatch tests fail on `9cb864c`; the rest are regression guards for behaviour that was already correct. Changed existing assertions (stronger, reasons recorded): `tests/test_b_conversations.py` ×2 (deleted conversation is now `404`, store verified empty).

B-01 regressions kept green in CI and locally: lifecycle/cleanup (`test_b01_raw_delta_lifecycle`, `test_b01_stream_cleanup`), refusal protocol, DLP equivalence, quota admission, turn authority, temporary chat, tenant isolation.

## Honest limits
Prompt injection is mitigated structurally only; the judge prompts still carry raw passage text; Truth-Fabric answers are still delivered whole; real-Ollama evidence is workstation-only; no capacity or latency claim is made from fixture or single-workstation runs.

## Blockers
See `L02_BLOCKER_REGISTER.md`.
