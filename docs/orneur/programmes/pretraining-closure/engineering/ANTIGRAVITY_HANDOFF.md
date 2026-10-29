# Antigravity Handoff — Phase 0/1 Evidence Honesty Closure

1. Start from PR #138 lineage. Prior independently tested code SHA: `4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4` (CI run `40860060023`).
2. Retest honesty probe tip `cd1e557a685b529c57bf4bf2f594b088cbeb5172` on `cursor/foundation-02-phase1-evidence-closure-8108`. Exact-head CI green on docs tip `b3fbda01ea1f4cb23a5fa6da5cd6398a4f3d862a` — Test Suite [`40866502460`](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40866502460) (9/9 success). See `PHASE_1_EXACT_HEAD_CI.md`.
3. Confirm `python scripts/acceptance/validate_register_graph.py --check` → `pretraining=95 numerator=0`.
4. Confirm `docs/orneur/acceptance/acceptance_ledger.json` is `[]`. Do not treat engineering VERIFIED rows as formal acceptance.
5. Run adversarial honesty suite: `python -m pytest tests/test_foundation02_probe_honesty.py -q`.
6. Re-run matrix builder probes on the exact tip: `python scripts/foundation02/build_requirement_matrix.py`.
7. Confirm probes JSON has:
   - no `/home/ubuntu/` or absolute `/workspace/.venv` in `pytest_command` / `pythonpath`
   - schema `orneur-foundation-02-verification-probes/3`
   - `passed_probe` false for zero-collected / skip-only / xfail-only / SHA mismatch
   - `training_authorization: NO-GO`
8. Confirm G4 residual: `tests/test_training_authorization_assurance.py::test_truncating_the_audit_log_tail_is_detected` remains `@pytest.mark.xfail(strict=True)` and failing; see `FOUNDATION_02_AUDIT_TAIL_RESIDUAL.md`.
9. Challenge any claim that an xfail or skip is a PASS.
10. Do **not** inherit Cursor self-cert as G13. Do **not** authorize training. Do **not** invent R65 policy text.

Read-only export for Claude: `docs/orneur/programmes/pretraining-closure/engineering/`.
