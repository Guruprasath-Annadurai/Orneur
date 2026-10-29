# FOUNDATION-02 Antigravity Handoff

1. Checkout `cursor/foundation-02-pretraining-hardening-1cdf` at the exact-head SHA in `FOUNDATION_02_EXACT_HEAD_CI.md`.
2. Confirm `python scripts/acceptance/validate_register_graph.py --check` → `pretraining=95 numerator=0`.
3. Confirm ledger/trust files untouched (empty ledger).
4. Re-run the CPU foundation suites listed in `FOUNDATION_02_REPRODUCIBILITY.md`.
5. Challenge authorization negatives, checkpoint forgery, serving-contract forbidden statuses.
6. Do **not** inherit Cursor self-cert as G13 independent qualification.
7. Do **not** authorize training from this milestone.
