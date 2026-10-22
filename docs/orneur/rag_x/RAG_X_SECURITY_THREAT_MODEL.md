# RAG-X security threat model

In scope for the tests in `tests/test_rag_x_foundation.py`:

- A document in another tenant, workspace, or principal is not scored.
- Revocation removes a previously visible document.
- Raw SQL is rejected. Structured SQL filters always include the caller tenant.
- A connector result from another tenant is dropped and named in `partial_reasons`.
- A connector exception is named and is not reported as a successful search.
- Document text that says to change the principal does not change `AuthorizedRetrievalScope`.
- An email in the query is redacted in `Corpus.log`.
- A grant token that appears inside the evidence text does not authorize `authorize_action`.
- Native model ids return `model_not_trained` and do not produce evidence.

Out of scope, and not claimed:

- Kernel sandboxing, SSRF, HTML sanitization, embedding inversion, and a real vector-database ACL.
- Same-uid filesystem attacks beyond the corpus pipeline's directory descriptor checks on PR #80.
- The C02 mission authorization path. It was not modified.
- Production tenant directory, KMS, or log pipeline behavior.

No cross-tenant disclosure was observed in the qualifying in-memory tests. That sentence is about those tests only.

## Authorized index

`tests/test_truth_authorized_index.py` covers the canonical path:

- A forged `TrustedSession`, a dict tenant claim, and another session are denied.
- Two session indexes do not return each other's rows.
- `search_documents` raises `PermissionError` when the connector identity tenant and the instance tenant differ, before `DocStore` is opened.
- Replacing `chunks.jsonl` with a symlink raises `AccessDenied` and does not read the target.
- A rewritten chunk whose stored digest does not match the text is dropped and named.
- A corrupt JSON line is skipped and named.
- Deletion revokes that digest. Re-admitting the same bytes is refused. A new text under the same filename is a new version.
- Revoking the session makes later search and replay fail.
- Cache hits require the same file stamp. A content change is not served from the previous ranking.
- `deadline_s <= 0` returns no hits and the reason `deadline`.
- An encoder that raises is a sparse result with `dense encoder failed`, not a hybrid result.
- `synthetic_hash_v1` stays sparse and `refused:synthetic-hash-research-only`.
- A local test encoder can produce `hybrid-rrf` with `production_neural` false.
- Instruction text in a passage does not set `tool_grant` and does not change `tenant_id`.
- Conflicting `KEY = value` passages abstain with `CONTRADICTED`.
- A one-sided claim with strong lexical overlap is `PARTIALLY_SUPPORTED`, not `SUPPORTED`.
- `TruthFabric.assess_evidence` reads the index only when `access` is the current session.
- `assess_lifecycle` does not call `authorize_native_pretraining`.

Not shown: an enterprise identity provider, a kernel sandbox, SSRF, a production vector ACL, or Darwin filesystem execution.
