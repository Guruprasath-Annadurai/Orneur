# Negative and withheld results

These are failures to demonstrate a capability, not tuning of a passed benchmark.

- `mode=dense-neural` without an injected embedder returns `backend_unavailable`. `synthetic_hash_v1` is not a neural embedding result.
- `mode=colbert`, `audio`, and `video` return `backend_unavailable`.
- English query `Chennai report` does not retrieve the Tamil fixture. Retrieval of that fixture needs the shared token `R7` or an explicit glossary entry. That is not translation.
- Calling the same `synthetic-template-backend` for three role names yields `independent_backends=1`.
- A lifecycle chain that passes every link still returns `chain_complete_training_not_authorized`.
- A proposal author cannot accept the proposal. A protected acceptance path cannot be proposed.
- Latency outside the in-memory kernel was not measured. No quality gain over Truth Fabric was measured, because that suite was not re-run.
- X2's positive count is limited to six synthetic items. It does not show a general reduction in unsupported answers.
