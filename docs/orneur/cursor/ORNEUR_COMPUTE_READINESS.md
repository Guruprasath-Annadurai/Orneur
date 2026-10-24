# Compute readiness

`orca/pretrain_foundation/compute_scenarios.py` names six classes of work: synthetic CPU tests, one workstation, a future experimental fine-tune, native pretraining, frontier scale, and global inference.

Every row has `frontier_pretraining: false` and `production_inference: false`. `frontier_pretraining_available()` returns false. The workstation note states that a machine in the ₹2.5 lakh class is not globally competitive frontier pretraining capacity.

No throughput, price, or latency figure was measured for this note. Parameter and memory formulas that already exist in `orca/genesis/model/scaling.py` were not changed and were not re-run as a capacity claim.

No GPU was requested. No commercial API was called.
