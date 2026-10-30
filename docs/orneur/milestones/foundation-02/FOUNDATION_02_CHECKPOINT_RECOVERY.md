# FOUNDATION-02 Checkpoint & Resume Integrity

**Proof scope:** local filesystem synthetic artifacts.  
**Not claimed:** multi-node GPU recovery qualification.

## Properties exercised

Atomic publication, content hashing/fingerprints, schema validation, concurrent
writer locks, truncated/missing/wrong-hash rejection, unauthorized resume refusal
paths in genesis checkpoint modules.

## Tests

- `tests/test_genesis_checkpoint_integrity.py`
- `tests/test_genesis_resumable_checkpoint.py`
