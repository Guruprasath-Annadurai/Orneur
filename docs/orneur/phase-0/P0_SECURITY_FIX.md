# P0 Security Fix — `orca/mcp/fs_server.py` Path-Traversal / Prefix-Confusion

## Vulnerability

`_safe_path()` validated a resolved path against `_allowed_roots` using a plain string `startswith()` check:

```python
if not any(str(path).startswith(str(r)) for r in _allowed_roots):
```

A sibling directory whose name is a superstring of the allowed root's own path string defeats this check — e.g. allowed root `/safe/data` also matches `/safe/database-secret`, because the STRING `"/safe/database-secret"` starts with the STRING `"/safe/data"`, even though that directory is not inside the allowed root at all.

## TDD process followed

1. Wrote `tests/test_mcp_fs_server_sandbox.py` first, covering: a valid in-root path, `../` traversal, absolute-path escape, the sibling-prefix-confusion case (the actual named vulnerability), and a symlink escape.
2. Ran the tests against the **unfixed** code — 4 of 5 passed, and `test_sibling_prefix_confusion_is_rejected` **failed** with `DID NOT RAISE PermissionError`, reproducing the vulnerability exactly as predicted before any fix was written.
3. Fixed `_safe_path()` to use `Path.relative_to()` ancestry checking (the same pattern already proven correct in `orca/tools/__init__.py`'s `_resolve_in_workspace()`), instead of string prefix matching:

```python
def _safe_path(p: str) -> Path:
    path = Path(p).resolve()
    for root in _allowed_roots:
        try:
            path.relative_to(root.resolve())
            return path
        except ValueError:
            continue
    raise PermissionError(f"Path {p} is outside allowed directories")
```

4. Re-ran the same regression tests — all 5 now pass, including the previously-failing sibling-prefix case.

## Verification results

```
tests/test_mcp_fs_server_sandbox.py :: 5 passed (valid path, ../ traversal,
absolute escape, sibling-prefix confusion, symlink escape)

Existing security suite (test_tools_security_scan.py, test_tools_file_sandbox.py,
test_run_shell_sandbox.py, test_web_ssrf_guard.py) :: 42 passed, 0 failed

Full suite: 414 passed, 0 failed, 0 skipped, 5.51s
  (409 baseline + 5 new regression tests, zero regressions)
```

## Scope discipline

No functionality was weakened to make the test pass — the fix is strictly more correct than the original (rejects a real bypass while still accepting every previously-valid path, confirmed by the "valid path inside allowed root" test still passing). No other files were touched as part of this fix. This was the only implementation change authorized during Phase 0.5.
