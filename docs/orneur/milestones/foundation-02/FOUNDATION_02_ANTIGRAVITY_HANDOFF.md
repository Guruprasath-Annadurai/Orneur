# FOUNDATION-02 Antigravity Handoff

1. Prior independently tested code SHA: `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4` on PR #138 — Test Suite [`40860060023`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40860060023).
2. Retest honesty tip `cd1e557a685b529c57bf4bf2f594b088cbeb5172` on `cursor/foundation-02-phase1-evidence-closure-8108` (exact HEAD after any docs-only tip). See also `docs/orneur/programmes/pretraining-closure/engineering/ANTIGRAVITY_HANDOFF.md`.
3. Confirm `python scripts/acceptance/validate_register_graph.py --check` → `pretraining=95 numerator=0`.
4. Confirm ledger empty; do not treat engineering VERIFIED rows as formal acceptance.
5. Re-run probes / suites in `FOUNDATION_02_REPRODUCIBILITY.md` plus:
   - `tests/test_foundation02_probe_honesty.py` (adversarial — must not manufacture PASS)
   - `tests/test_foundation02_serving_contract.py`
   - `tests/test_foundation02_requirement_matrix.py`
6. Challenge INTERFACE_ONLY/NOT_AVAILABLE live-serving claims (generate/deployable/checkpoint).
7. Review audit-tail residual (`FOUNDATION_02_AUDIT_TAIL_RESIDUAL.md`); strict xfail must remain failing.
8. Confirm probes JSON has no `/home/ubuntu/` or absolute `/workspace/.venv` argv; schema v3 honesty rules applied.
9. Do **not** inherit Cursor self-cert as G13. Do **not** authorize training.
