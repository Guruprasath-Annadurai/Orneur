# P1-F — Model Routing, Availability and Quotas

No router or registry was added. Existing routing, capability truth and serving authorisation were preserved. No automatic "intelligent routing" was implemented, and no plan, price or billing rule was invented or changed (free tier limit 50/day is existing policy).

| Behaviour | Test | Result |
|---|---|---|
| Daily limit reached → stable `quota_exceeded`, **zero** provider calls, usage unchanged | `test_p1_quota_live.py::Q2` | VERIFIED |
| Concurrent burst larger than the remaining allowance: exactly the remaining count is served (atomic reservation) | Q2 (10 requests, 4 remaining → 4 served, 4 streamed provider calls) | VERIFIED |
| Provider failure (503) → error reported, not "saved", **not charged** | Q1 | VERIFIED |
| Client cancel → no stored completion, provider hung up | Q4 | VERIFIED |
| Unconfigured tier is never served by an unlisted model name | Q3 (only models the provider really has were requested) | VERIFIED |
| Served identity disclosed truthfully, including substitution and third-party origin | real-inference probe | VERIFIED |
| Request admission fails closed when usage accounting is unavailable | existing unit tests (`test_a_serving_authorization`, `test_serving_policy_adversarial`) | VERIFIED (existing) |

## Open
- **P1-X-04:** every served turn also makes one non-streamed background model call (knowledge extraction) that is **not metered**. It is now bounded (default 2 concurrent, overflow skipped), but whether to meter, disable or accept it is a founder policy decision and stays open. With the local provider it costs no money.
- Retry accounting and token accounting beyond the per-message unit were not newly measured; multiworker quota consistency relies on the existing shared reservation store and its tests.
- No external provider was configured, so external-spend prevention is only structural (no external provider path was exercised).
