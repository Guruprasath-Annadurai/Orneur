# FOUNDATION-02 Model Serving Interface Contract

**Candidate tip (pre-corrective commit parent):** `b384348fa3bc789585bf69d81a772c8a4d75d493`  
**Ownership boundary:** interface handoff only. No competing chatbot implementation.
Does not modify Claude LANDMARK product PRs (#136).

## Module

`orca/pretrain_foundation/serving_contract.py`

## Structured capability states

`REFUSE_ONLY` | `THIRD_PARTY_PROXY` | `QUALIFIED_NATIVE` (refused without evidence)

## Corrective findings (failing-before / fixed-after)

| Gap | Before | After |
|---|---|---|
| INTERFACE_ONLY + generate/stream + deployable=True | accepted | refused |
| INTERFACE_ONLY + served_model_identity / revision / checkpoint | accepted | refused |
| NOT_AVAILABLE + generate | accepted | refused |
| QUALIFIED_NATIVE without evidence | N/A | refused |
| THIRD_PARTY_PROXY without disclosure / with native identity | N/A | refused / requires disclosure |

Phrase denylist removed; registry-aligned capability validation is authoritative.

## Tests

`tests/test_foundation02_serving_contract.py` (adversarial)
