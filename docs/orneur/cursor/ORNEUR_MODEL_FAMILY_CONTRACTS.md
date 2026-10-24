# GENESIS, NOVUS, and AETERNUM contracts

`orca/genesis/model/family_registry.py`

Default records:

| Family | Status | Meaning |
|---|---|---|
| GENESIS | `INTERFACE_ONLY` | `genesis-arch-v1` code exists. No checkpoint digest. Not trained. Not frontier-qualified. |
| NOVUS | `NOT_AVAILABLE` | No native checkpoint is registered by this module. |
| AETERNUM | `NOT_AVAILABLE` | No native checkpoint is registered by this module. |

`AVAILABLE`, `TRAINED`, `PROMOTABLE`, and `FRONTIER_QUALIFIED` raise `ModelFamilyContractError`. `EVIDENCE_RECORDED_NOT_ACCEPTED` still requires a checkpoint digest, a training run id, and an eval report digest, and the status text says it is not acceptance.

`assert_parameter_count` compares a claimed count to `GenesisModelConfig.total_parameters()`.

Contract field names for each family are listed in `REQUIRED_CONTRACT_FIELDS`. A field name is an interface slot, not a completed evaluation.

Tests: `tests/test_cursor_model_family.py`.
