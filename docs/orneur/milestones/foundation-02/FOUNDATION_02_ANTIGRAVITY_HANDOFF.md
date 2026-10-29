# FOUNDATION-02 Antigravity Handoff

1. Checkout `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4` on `cursor/foundation-02-pretraining-hardening-1cdf` (PR #138). Exact-head CI green — Test Suite [`40860060023`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40860060023).
2. Confirm `python scripts/acceptance/validate_register_graph.py --check` → `pretraining=95 numerator=0`.
3. Confirm ledger empty; do not treat engineering VERIFIED rows as formal acceptance.
4. Re-run probes / suites in `FOUNDATION_02_REPRODUCIBILITY.md` plus:
   - `tests/test_foundation02_serving_contract.py`
   - `tests/test_foundation02_requirement_matrix.py`
5. Challenge INTERFACE_ONLY/NOT_AVAILABLE live-serving claims (generate/deployable/checkpoint).
6. Review audit-tail residual (`FOUNDATION_02_AUDIT_TAIL_RESIDUAL.md`); strict xfail must remain failing.
7. Do **not** inherit Cursor self-cert as G13. Do **not** authorize training.
