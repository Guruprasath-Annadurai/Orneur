# Evidence and proof contract

`orca/pretrain_foundation/evidence_contract.py`

A claim moves to `VERIFIED` only when all of these hold:

- The actor is not the producer.
- The outcome is `passed`.
- Every span is authorized.
- Every span digest equals SHA-256 of its own bytes.
- Every span text equals the claim text.

Otherwise the transition raises `EvidenceContractError`. `classify_claim` never returns `verified: true`. A citation that fails the digest check is not proof.

`arbitrate_claims` returns `not_majority_vote`. Two different texts stay `DISPUTED`. `VERIFIED` together with `REFUTED` stays unresolved pending a reproducible check.

The contract does not call the Truth Fabric, does not retrieve documents, and does not accept an LLM explanation as a mathematical proof.
