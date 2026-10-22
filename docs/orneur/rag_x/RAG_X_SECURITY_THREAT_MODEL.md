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
