# FOUNDATION-02 Architecture & Tokenizer Integrity

## Family registry (honest)

| Family | Status | Notes |
|---|---|---|
| GENESIS | `INTERFACE_ONLY` | `genesis-arch-v1` interface + training-step code; no trained checkpoint |
| NOVUS | `NOT_AVAILABLE` | Contract fields only |
| AETERNUM | `NOT_AVAILABLE` | Contract fields only |

Forbidden statuses (`TRAINED`, `AVAILABLE`, `FRONTIER_QUALIFIED`, …) are rejected by
`orca.genesis.model.family_registry`.

## Synthetic compatibility coverage

`tests/test_genesis_model_architecture.py`, `tests/test_genesis_tokenizer.py`,
`tests/test_cursor_tokenizer_*`.

## Non-claim

No third-party base model is labeled as a newly trained ORNEUR model.
