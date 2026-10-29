# FOUNDATION-02 Antigravity Handoff

1. Checkout PR #138 tip after corrective exact-head CI green (see `FOUNDATION_02_EXACT_HEAD_CI.md`).
2. Confirm `python scripts/acceptance/validate_register_graph.py --check` → `pretraining=95 numerator=0`.
3. Confirm ledger empty; do not treat engineering VERIFIED rows as formal acceptance.
4. Re-run probes / suites in `FOUNDATION_02_REPRODUCIBILITY.md` plus:
   - `tests/test_foundation02_serving_contract.py`
   - `tests/test_foundation02_requirement_matrix.py`
5. Challenge INTERFACE_ONLY/NOT_AVAILABLE live-serving claims (generate/deployable/checkpoint).
6. Review audit-tail residual (`FOUNDATION_02_AUDIT_TAIL_RESIDUAL.md`); xfail must remain failing under strict xfail.
7. Do **not** inherit Cursor self-cert as G13. Do **not** authorize training.
