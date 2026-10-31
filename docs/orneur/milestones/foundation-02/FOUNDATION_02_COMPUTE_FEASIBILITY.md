# FOUNDATION-02 Compute & Memory Feasibility

## Measured vs analytical

| Class | Kind | Frontier pretraining? |
|---|---|---|
| synthetic_cpu | measured suitable for unit tensors | **No** |
| single_workstation | analytical label (incl. ₹2.5L class) | **No** |
| experimental_finetune | hardware not selected | **No** |
| native_pretraining | not provisioned | **No** |
| frontier_scale | not provisioned | **No** |

Source: `orca/pretrain_foundation/compute_scenarios.py`  
`frontier_pretraining_available()` always returns `False`.

## Formulas (analytical placeholders)

For a dense transformer of parameter count `P`, bytes/param `B` (2 for fp16, 4 for fp32):

- Weights ≈ `P * B`
- Adam states ≈ `2 * P * 4` (fp32 moments) when used
- Activations scale with `batch * seq * hidden * layers` (implementation-dependent)

No GPU prices, availability, or performance invented. No GPUs reserved.
Workstation WSL is **not** treated as frontier pretraining capacity.
