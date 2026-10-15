"""
P1 deletion-assurance, test-isolation correction (2026-10-15): regression
coverage for the autouse isolation `tests/conftest.py` applies to
`orca.brain.memory`/`orca.memory.episodic`/`orca.memory.store`, and for
the fail-closed guard that backs it.

Real risk this closes: a forensic, read-only audit of the developer's
actual `~/.orca/memory/vectors` found that `tests/test_deletion_end_to_end.py`
had no fixture isolating `MEMORY_DIR` from the real default directory --
every run of that file's deletion tests (this project's own end-to-end
deletion-assurance tests) was a genuine write+delete cycle against real,
months-accumulated data, not a tmp directory. The read-only audit found
no pre-existing real data was corrupted or deleted (every test uses a
fresh random session_id and only ever deletes its own exact collection by
exact name), but did find leftover test-created collections and ledger
files sitting in the real store from past unisolated runs. This file
proves the fix actually isolates storage, and that the fail-closed guard
genuinely fails closed rather than merely existing unexercised.
"""
from __future__ import annotations

import os

import pytest

from tests.conftest import assert_path_is_isolated_test_storage


def test_memory_module_constants_are_isolated_under_tmp_path(tmp_path):
    """The autouse fixture in conftest.py must have already redirected
    these constants by the time any test body runs -- confirms the fix
    for the real gap, not just the guard function in isolation."""
    import orca.brain.memory as brain_memory_mod
    import orca.memory.episodic as episodic_mod
    import orca.memory.store as memory_store_mod

    real_home = os.path.realpath(os.path.expanduser("~"))

    for resolved in (
        str(brain_memory_mod.MEMORY_DIR),
        str(brain_memory_mod.CACHE_DIR),
        str(episodic_mod.EPISODIC_DIR),
        str(memory_store_mod.MEMORY_ROOT),
    ):
        resolved_real = os.path.realpath(resolved)
        assert not resolved_real.startswith(real_home + os.sep), (
            f"{resolved!r} resolves under the real home directory -- "
            f"isolation is not active for this test."
        )


def test_isolation_guard_passes_for_a_genuinely_isolated_path(tmp_path):
    """Sanity check: the guard must NOT raise for the normal, correct case."""
    isolated = tmp_path / "memory"  # already created by the autouse fixture itself
    isolated.mkdir(exist_ok=True)
    assert_path_is_isolated_test_storage(str(isolated), "test_label", tmp_path)


def test_isolation_guard_fails_closed_for_the_real_home_directory(tmp_path):
    """The actual regression this exists to prevent: if a future change
    accidentally re-points a memory-module constant at the real home
    directory (or anywhere outside this test's own tmp_path), the guard
    must raise rather than silently allow it -- proven here by calling it
    with exactly that misconfiguration, not merely asserting it exists."""
    real_home = os.path.expanduser("~")
    with pytest.raises(AssertionError):
        assert_path_is_isolated_test_storage(real_home, "test_label", tmp_path)


def test_isolation_guard_fails_closed_for_an_unrelated_tmp_directory(tmp_path, tmp_path_factory):
    """A path that is a legitimate tmp directory, but NOT this specific
    test's own tmp_path, must also be rejected -- the guard checks against
    the exact tmp_path passed in, not "any tmp-looking path", which is
    what actually prevents one test/worker from writing into another's
    live test database (CTO directive: "Ensure parallel workers cannot
    reuse another worker's live test database")."""
    other_tmp = tmp_path_factory.mktemp("someone_elses_test_run")
    with pytest.raises(AssertionError):
        assert_path_is_isolated_test_storage(str(other_tmp), "test_label", tmp_path)


def test_each_test_gets_a_distinct_isolated_memory_dir(tmp_path):
    """Distinct tmp_path per test (pytest's own guarantee, which holds
    under pytest-xdist parallel workers too) means two different test
    invocations can never resolve to the same MEMORY_DIR -- the actual
    property that prevents cross-test/cross-worker data reuse or
    collision. Recorded here as a property of THIS test's own resolved
    path so a regression in the fixture's redirection (e.g. hard-coding a
    directory name instead of using tmp_path) is caught."""
    import orca.brain.memory as brain_memory_mod

    assert str(brain_memory_mod.MEMORY_DIR).startswith(str(tmp_path))
