# Compute readiness

`orca/pretrain_foundation/compute_scenarios.py` names six classes of work: synthetic CPU tests, one workstation, a future experimental fine-tune, native pretraining, frontier scale, and global inference.

Every row has `frontier_pretraining: false` and `production_inference: false`. `frontier_pretraining_available()` returns false. The workstation note states that a machine in the ₹2.5 lakh class is not globally competitive frontier pretraining capacity.

No throughput, price, or latency figure was measured for this note. Every `scenario()` row now also carries `qualification: COMPUTE_NOT_QUALIFIED`, `price: UNKNOWN`, and `throughput_measured: false`. Unknown is not zero.

`FREE_TIER_OBSERVATIONS` records three publisher pages retrieved on 2026-10-24. Colab's FAQ says the free tier is not guaranteed and does not publish GPU limits. Kaggle's GPU doc says a weekly quota of 30 hours or sometimes higher. Two Hugging Face inference pricing URLs disagreed about a free-user credit, so that amount stays `UNKNOWN`. None of those providers was enrolled. A published quota is not ORNEUR capacity.

Parameter and memory formulas that already exist in `orca/genesis/model/scaling.py` were not changed and were not re-run as a capacity claim.

No GPU was requested. No commercial API was called. No account was topped up.
