# Typed contracts for the 100 roles

`RoleContract` in `orca/pretrain_foundation/role_registry.py` fixes the fields required for a planning row: id, group, version, purpose, task, schemas, trust classification, qualification state, model and tool dependency, authority, allowed and forbidden actions, tenant scope, budget, evidence contract, retry limit, timeout, cancellation, failure behavior, privacy, and verification method.

Shared forbidden actions on every row: self-promotion, training, spend, weight mutation, ledger edit, cross-tenant read, silent deployment.

Message types that handlers actually construct:

| Type | Module | Rule |
|---|---|---|
| `EvidenceSpan` | `evidence_contract.py` | Digest is SHA-256 of the span bytes. |
| `Claim` | `evidence_contract.py` | State is one of OBSERVED, VERIFIED, INFERRED, DISPUTED, UNKNOWN, REFUTED, STALE. |
| `DenialReceipt` | `evidence_contract.py` | Records a denial on `decide_authority` only. |
| `PromotionProposal` | `evidence_contract.py` | `applied` cannot be constructed true. The decider cannot be the producer or the candidate. |

Handler results are JSON objects passed through the existing `Orchestrator` result check. They are not system instructions. `screen_untrusted` sets `as_instruction` false.

Unimplemented roles keep `required_authority=not-granted` and are not returned by `role_for_task`.
