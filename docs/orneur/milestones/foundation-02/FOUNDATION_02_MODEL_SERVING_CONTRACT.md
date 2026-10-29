# FOUNDATION-02 Model Serving Interface Contract

**Ownership boundary:** interface handoff only. No competing chatbot implementation.
Does not modify Claude LANDMARK product PRs.

## Module

`orca/pretrain_foundation/serving_contract.py`

## Required fields

See `REQUIRED_SERVING_FIELDS` (family, revision, provenance, served identity,
qualification, third-party disclosure, tokenizer digest, context window,
operations, streaming, cancellation, safety metadata).

## Defaults

`handoff_defaults()` yields honest INTERFACE_ONLY / NOT_QUALIFIED identities for
GENESIS/NOVUS/AETERNUM with `refuse_unsupported` only — no live UI injection.

## Tests

`tests/test_foundation02_serving_contract.py`
