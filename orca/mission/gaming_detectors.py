"""
Phase 15.9 -- bounded, explainable AST-based anti-gaming detectors
(spec sections 5-13).

Every detector operates on REAL source text reconstructed from REAL
git revisions via `orca.mission.git_diff_analysis`. None of these
detectors claim perfect semantic-equivalence detection (spec section
6: "Do not claim perfect semantic equivalence detection. Detect
structurally obvious weakening.") -- each is a bounded, disclosed
heuristic. An uncertain case is reported with a low/medium severity
and a `confidence_basis` describing exactly what was compared, never
silently ignored and never asserted with unwarranted certainty.

A rename detected by git (high-similarity `RenamedFile`) is NEVER
misclassified as a deletion (spec section 5's explicit distinction).
"""
from __future__ import annotations

import ast
import uuid

from orca.mission.anti_gaming import AntiGamingFinding, FindingCategory, Severity
from orca.mission.git_diff_analysis import DiffSummary, read_file_at_revision

DETECTOR_VERSION = "15.9.0"

#: Path substrings that elevate a finding to CRITICAL when matched --
#: this repository's own security-sensitive domains (spec section 10).
DEFAULT_SECURITY_PATHS: frozenset[str] = frozenset({
    "orca/godmode/", "orca/auth/", "orca/mission/operation_store.py",
    "orca/mission/authority_bridge.py", "orca/mission/sandbox_executor.py",
    "orca/mission/container_executor.py", "tests/test_godmode",
    "tests/test_auth", "tests/test_tenant", "tests/test_authority",
    "tests/test_operation_store", "tests/test_sandbox_adversarial.py",
    "tests/test_container_adversarial.py",
})


def _fid() -> str:
    return f"gaming_{uuid.uuid4().hex[:16]}"


def is_security_relevant(file_path: str) -> bool:
    return any(marker in file_path for marker in DEFAULT_SECURITY_PATHS)


def _parse_functions(source: str) -> dict[str, ast.FunctionDef]:
    """Maps qualified test function name (`ClassName.method_name` or
    just `func_name` for module-level) -> its AST node. Only
    `test_*`-named functions/methods are considered (pytest's own
    collection convention)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    functions: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                    functions[f"{node.name}.{item.name}"] = item
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            # only module-level (not already captured as a class method)
            functions.setdefault(node.name, node)
    return functions


def _decorator_names(func: ast.FunctionDef) -> set[str]:
    names = set()
    for dec in func.decorator_list:
        node = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


def _assert_count(func: ast.FunctionDef) -> int:
    return sum(1 for n in ast.walk(func) if isinstance(n, ast.Assert))


def _raises_exception_types(func: ast.FunctionDef) -> list[str]:
    """Names of exception types passed to `pytest.raises(...)` inside
    this function."""
    types = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            call_target = node.func
            is_raises = (
                (isinstance(call_target, ast.Attribute) and call_target.attr == "raises")
                or (isinstance(call_target, ast.Name) and call_target.id == "raises")
            )
            if is_raises and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Name):
                    types.append(arg.id)
                elif isinstance(arg, ast.Attribute):
                    types.append(arg.attr)
    return types


def _eq_and_in_comparisons(func: ast.FunctionDef) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Maps the dumped left-hand-side expression of every single-op
    `==`/`in` Compare inside `func` to its right-hand-side value(s) --
    used to detect the specific "assert x == single_value" ->
    "assert x in (single_value, other_value)" broadening pattern
    (spec section 6's own example)."""
    eq_compares: dict[str, str] = {}
    in_compares: dict[str, list[str]] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left_dump = ast.dump(node.left)
            if isinstance(node.ops[0], ast.Eq):
                eq_compares[left_dump] = ast.dump(node.comparators[0])
            elif isinstance(node.ops[0], ast.In):
                comparator = node.comparators[0]
                if isinstance(comparator, (ast.Tuple, ast.List)):
                    in_compares[left_dump] = [ast.dump(e) for e in comparator.elts]
    return eq_compares, in_compares


def _except_pass_count(source: str) -> int:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                # bare except or `except Exception`/`except BaseException`
                if node.type is None or (
                    isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")
                ):
                    count += 1
    return count


def detect_test_deletions(
    diff: DiffSummary, repo_path: str, *, mission_id: str | None,
) -> tuple[AntiGamingFinding, ...]:
    """Deleted test FILES, and test FUNCTIONS removed from a modified
    file that persisted at that path (not accounted for by a git-
    detected rename -- spec section 5's explicit "do not classify a
    rename as deletion" rule)."""
    findings = []
    renamed_new_paths = {r.new_path for r in diff.renamed_files}

    for path in diff.deleted_files:
        if not path.startswith("tests/") and "/tests/" not in f"/{path}":
            continue
        findings.append(AntiGamingFinding(
            finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
            baseline_revision=diff.baseline_revision, category=FindingCategory.TEST_DELETED,
            severity=Severity.CRITICAL if is_security_relevant(path) else Severity.HIGH,
            file_path=path, description=f"Test file {path} was deleted entirely.",
            detector_id="detect_test_deletions", detector_version=DETECTOR_VERSION,
            confidence_basis=f"git diff --name-status shows {path} as deleted (status D), "
                              f"not accounted for by any detected rename.",
            security_relevance=is_security_relevant(path), blocking=is_security_relevant(path),
        ))

    for path in diff.modified_files:
        if path in renamed_new_paths:
            continue
        if not (path.startswith("tests/") or "/tests/" in f"/{path}"):
            continue
        baseline_src = read_file_at_revision(repo_path, diff.baseline_revision, path)
        candidate_src = read_file_at_revision(repo_path, diff.candidate_revision, path)
        if baseline_src is None or candidate_src is None:
            continue
        baseline_funcs = _parse_functions(baseline_src)
        candidate_funcs = _parse_functions(candidate_src)
        removed = set(baseline_funcs) - set(candidate_funcs)
        for name in sorted(removed):
            findings.append(AntiGamingFinding(
                finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
                baseline_revision=diff.baseline_revision, category=FindingCategory.TEST_DELETED,
                severity=Severity.CRITICAL if is_security_relevant(path) else Severity.MEDIUM,
                file_path=path, description=f"Test function/method {name!r} present at baseline is absent at candidate.",
                detector_id="detect_test_deletions", detector_version=DETECTOR_VERSION,
                confidence_basis=f"AST parse of {path} at both revisions: {name!r} defined at "
                                  f"{diff.baseline_revision}, not defined at {diff.candidate_revision}, "
                                  f"and {path} was not identified as a git rename target.",
                test_ids=(name,), security_relevance=is_security_relevant(path),
                blocking=is_security_relevant(path),
            ))
    return tuple(findings)


def detect_skip_additions(
    diff: DiffSummary, repo_path: str, *, mission_id: str | None,
) -> tuple[AntiGamingFinding, ...]:
    findings = []
    skip_markers = {"skip", "skipif", "xfail"}
    for path in diff.modified_files:
        if not (path.startswith("tests/") or "/tests/" in f"/{path}"):
            continue
        baseline_src = read_file_at_revision(repo_path, diff.baseline_revision, path)
        candidate_src = read_file_at_revision(repo_path, diff.candidate_revision, path)
        if baseline_src is None or candidate_src is None:
            continue
        baseline_funcs = _parse_functions(baseline_src)
        candidate_funcs = _parse_functions(candidate_src)
        for name, cand_func in candidate_funcs.items():
            base_func = baseline_funcs.get(name)
            if base_func is None:
                continue
            base_decs = _decorator_names(base_func) & skip_markers
            cand_decs = _decorator_names(cand_func) & skip_markers
            newly_added = cand_decs - base_decs
            if newly_added:
                findings.append(AntiGamingFinding(
                    finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
                    baseline_revision=diff.baseline_revision, category=FindingCategory.TEST_SKIPPED,
                    severity=Severity.CRITICAL if is_security_relevant(path) else Severity.MEDIUM,
                    file_path=path,
                    description=f"Test {name!r} gained new skip/xfail marker(s) {sorted(newly_added)!r} "
                                f"not present at baseline.",
                    detector_id="detect_skip_additions", detector_version=DETECTOR_VERSION,
                    confidence_basis=f"decorator set at baseline: {sorted(base_decs)!r}; "
                                      f"decorator set at candidate: {sorted(cand_decs)!r}.",
                    test_ids=(name,), security_relevance=is_security_relevant(path),
                    blocking=is_security_relevant(path),
                ))
    return tuple(findings)


def detect_assertion_weakening(
    diff: DiffSummary, repo_path: str, *, mission_id: str | None,
) -> tuple[AntiGamingFinding, ...]:
    findings = []
    for path in diff.modified_files:
        if not (path.startswith("tests/") or "/tests/" in f"/{path}"):
            continue
        baseline_src = read_file_at_revision(repo_path, diff.baseline_revision, path)
        candidate_src = read_file_at_revision(repo_path, diff.candidate_revision, path)
        if baseline_src is None or candidate_src is None:
            continue
        baseline_funcs = _parse_functions(baseline_src)
        candidate_funcs = _parse_functions(candidate_src)
        for name, cand_func in candidate_funcs.items():
            base_func = baseline_funcs.get(name)
            if base_func is None:
                continue
            base_asserts = _assert_count(base_func)
            cand_asserts = _assert_count(cand_func)
            if cand_asserts < base_asserts:
                findings.append(AntiGamingFinding(
                    finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
                    baseline_revision=diff.baseline_revision, category=FindingCategory.ASSERTION_REMOVED,
                    severity=Severity.CRITICAL if is_security_relevant(path) else Severity.MEDIUM,
                    file_path=path,
                    description=f"Test {name!r} has fewer assert statements at candidate "
                                f"({cand_asserts}) than baseline ({base_asserts}).",
                    detector_id="detect_assertion_weakening", detector_version=DETECTOR_VERSION,
                    confidence_basis=f"AST Assert-node count for {name!r}: baseline={base_asserts}, "
                                      f"candidate={cand_asserts}.",
                    test_ids=(name,), security_relevance=is_security_relevant(path),
                    blocking=is_security_relevant(path),
                ))

            base_raises = _raises_exception_types(base_func)
            cand_raises = _raises_exception_types(cand_func)
            if base_raises and "Exception" in cand_raises and "Exception" not in base_raises:
                findings.append(AntiGamingFinding(
                    finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
                    baseline_revision=diff.baseline_revision, category=FindingCategory.ASSERTION_WEAKENED,
                    severity=Severity.CRITICAL if is_security_relevant(path) else Severity.MEDIUM,
                    file_path=path,
                    description=f"Test {name!r}'s pytest.raises() was widened from {base_raises!r} "
                                f"to include bare 'Exception' at candidate.",
                    detector_id="detect_assertion_weakening", detector_version=DETECTOR_VERSION,
                    confidence_basis=f"pytest.raises() argument at baseline: {base_raises!r}; "
                                      f"at candidate: {cand_raises!r}.",
                    test_ids=(name,), security_relevance=is_security_relevant(path),
                    blocking=is_security_relevant(path),
                ))

            base_eq, _base_in = _eq_and_in_comparisons(base_func)
            _cand_eq, cand_in = _eq_and_in_comparisons(cand_func)
            for left_dump, base_value in base_eq.items():
                candidate_broadened = cand_in.get(left_dump)
                if candidate_broadened and base_value in candidate_broadened and len(candidate_broadened) > 1:
                    findings.append(AntiGamingFinding(
                        finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
                        baseline_revision=diff.baseline_revision, category=FindingCategory.ASSERTION_WEAKENED,
                        severity=Severity.CRITICAL if is_security_relevant(path) else Severity.MEDIUM,
                        file_path=path,
                        description=f"Test {name!r} broadened a strict equality assertion into an "
                                    f"'in (...)' check accepting {len(candidate_broadened)} possible values "
                                    f"where baseline required exactly one.",
                        detector_id="detect_assertion_weakening", detector_version=DETECTOR_VERSION,
                        confidence_basis=f"baseline: single-value == comparison; candidate: 'in' comparison "
                                          f"against a {len(candidate_broadened)}-element tuple/list including "
                                          f"the original value, for the same left-hand expression.",
                        test_ids=(name,), security_relevance=is_security_relevant(path),
                        blocking=is_security_relevant(path),
                    ))
    return tuple(findings)


def detect_error_suppression(
    diff: DiffSummary, repo_path: str, *, mission_id: str | None,
) -> tuple[AntiGamingFinding, ...]:
    findings = []
    for path in diff.modified_files:
        baseline_src = read_file_at_revision(repo_path, diff.baseline_revision, path)
        candidate_src = read_file_at_revision(repo_path, diff.candidate_revision, path)
        if baseline_src is None or candidate_src is None or not path.endswith(".py"):
            continue
        base_count = _except_pass_count(baseline_src)
        cand_count = _except_pass_count(candidate_src)
        if cand_count > base_count:
            findings.append(AntiGamingFinding(
                finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
                baseline_revision=diff.baseline_revision, category=FindingCategory.ERROR_SUPPRESSED,
                severity=Severity.CRITICAL if is_security_relevant(path) else Severity.LOW,
                file_path=path,
                description=f"{path} gained {cand_count - base_count} new broad "
                            f"'except Exception/BaseException: pass'-shaped handler(s).",
                detector_id="detect_error_suppression", detector_version=DETECTOR_VERSION,
                confidence_basis=f"except-Exception-then-pass handler count: baseline={base_count}, "
                                  f"candidate={cand_count}.",
                security_relevance=is_security_relevant(path), blocking=is_security_relevant(path),
            ))
    return tuple(findings)


def _imported_names(source: str) -> set[str]:
    """Real imported symbol names (not a substring search) -- so a
    LOCAL VARIABLE that happens to share a name with a real function
    (e.g. `run_in_container = MagicMock()`) is never mistaken for
    still importing/using the real thing."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


def detect_mock_replacing_real_behavior(
    diff: DiffSummary, repo_path: str, *, mission_id: str | None,
    real_call_markers: frozenset[str] = frozenset({
        "run_in_container", "get_conn", "authorize_operation", "run_command",
        "resolve_and_consume_lease",
    }),
) -> tuple[AntiGamingFinding, ...]:
    """Heuristic proxy (spec section 11 explicitly does not demand
    perfect detection): a test file that IMPORTED a real integration
    call at baseline, and at candidate no longer imports it (checked
    via AST import analysis, not substring search -- a local variable
    reassignment like `run_in_container = MagicMock()` does not count
    as "still importing the real thing") while introducing `Mock`/
    `MagicMock`/`monkeypatch.setattr`, is flagged for review -- the
    concern is losing real integration coverage while a test file's
    NAME/labeling implies it still exercises the real thing."""
    findings = []
    for path in diff.modified_files:
        if not (path.startswith("tests/") or "/tests/" in f"/{path}"):
            continue
        baseline_src = read_file_at_revision(repo_path, diff.baseline_revision, path)
        candidate_src = read_file_at_revision(repo_path, diff.candidate_revision, path)
        if baseline_src is None or candidate_src is None:
            continue
        baseline_imports = _imported_names(baseline_src)
        candidate_imports = _imported_names(candidate_src)
        for marker in real_call_markers:
            if marker in baseline_imports and marker not in candidate_imports:
                gained_mock = ("MagicMock" in candidate_src or "Mock(" in candidate_src
                               or "monkeypatch.setattr" in candidate_src) and (
                    "MagicMock" not in baseline_src and "Mock(" not in baseline_src
                    and "monkeypatch.setattr" not in baseline_src
                )
                if gained_mock:
                    findings.append(AntiGamingFinding(
                        finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
                        baseline_revision=diff.baseline_revision,
                        category=FindingCategory.MOCK_REPLACES_REQUIRED_BEHAVIOR,
                        severity=Severity.HIGH,
                        file_path=path,
                        description=f"{path} referenced real call {marker!r} at baseline; at candidate "
                                    f"that reference is gone and mocking was introduced -- review whether "
                                    f"this test still verifies real integration behavior.",
                        detector_id="detect_mock_replacing_real_behavior", detector_version=DETECTOR_VERSION,
                        confidence_basis=f"{marker!r} imported at baseline (AST import analysis), "
                                          f"no longer imported at candidate; "
                                          f"Mock/MagicMock/monkeypatch.setattr newly present in candidate.",
                        security_relevance=is_security_relevant(path), blocking=False,
                    ))
    return tuple(findings)


def detect_hardcoded_bypass(
    diff: DiffSummary, repo_path: str, *, mission_id: str | None,
) -> tuple[AntiGamingFinding, ...]:
    """Bounded pattern check (spec section 12: not perfect-detection
    claimed) for non-test source files that newly special-case the
    test environment itself."""
    findings = []
    suspicious_markers = ("PYTEST_CURRENT_TEST", "is_running_under_pytest", "if __name__ == \"pytest\"")
    for path in diff.modified_files + diff.added_files:
        if path.startswith("tests/") or "/tests/" in f"/{path}" or not path.endswith(".py"):
            continue
        baseline_src = read_file_at_revision(repo_path, diff.baseline_revision, path) or ""
        candidate_src = read_file_at_revision(repo_path, diff.candidate_revision, path)
        if candidate_src is None:
            continue
        for marker in suspicious_markers:
            if marker in candidate_src and marker not in baseline_src:
                findings.append(AntiGamingFinding(
                    finding_id=_fid(), mission_id=mission_id, revision=diff.candidate_revision,
                    baseline_revision=diff.baseline_revision, category=FindingCategory.HARDCODED_TEST_OUTPUT,
                    severity=Severity.CRITICAL if is_security_relevant(path) else Severity.HIGH,
                    file_path=path,
                    description=f"{path} (non-test source) newly special-cases the test environment "
                                f"via {marker!r} -- production code branching on 'am I under test' is a "
                                f"structurally obvious bypass pattern.",
                    detector_id="detect_hardcoded_bypass", detector_version=DETECTOR_VERSION,
                    confidence_basis=f"{marker!r} absent from {path} at baseline, present at candidate.",
                    security_relevance=is_security_relevant(path), blocking=is_security_relevant(path),
                ))
    return tuple(findings)


def analyze_revisions(
    repo_path: str, baseline_revision: str, candidate_revision: str, *, mission_id: str | None = None,
) -> tuple[AntiGamingFinding, ...]:
    """Runs every detector and returns the combined finding tuple."""
    from orca.mission.git_diff_analysis import get_diff_summary

    diff = get_diff_summary(repo_path, baseline_revision, candidate_revision)
    findings: list[AntiGamingFinding] = []
    findings.extend(detect_test_deletions(diff, repo_path, mission_id=mission_id))
    findings.extend(detect_skip_additions(diff, repo_path, mission_id=mission_id))
    findings.extend(detect_assertion_weakening(diff, repo_path, mission_id=mission_id))
    findings.extend(detect_error_suppression(diff, repo_path, mission_id=mission_id))
    findings.extend(detect_mock_replacing_real_behavior(diff, repo_path, mission_id=mission_id))
    findings.extend(detect_hardcoded_bypass(diff, repo_path, mission_id=mission_id))
    return tuple(findings)
