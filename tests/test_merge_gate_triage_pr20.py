"""
ORNEUR — FINAL BOUNDED PRE-MERGE TRIAGE (PR #20, CodeAnt findings).

Covers the three items from CodeAnt's PR #20 review that got a real,
narrowly-scoped fix in this follow-up branch:

  2. setuptools pin under pip vs uv installations -- [tool.uv]
     constraint-dependencies only applies to uv-driven installs; a plain
     `pip install orneur[lens]` never reads it. Fixed with a portable
     PEP 508 marker directly in the `lens`/`train` extras.
  3. Missing cross_refs validation in the acceptance register --
     validate_register_graph.py's cross_refs loop never appended to
     `errors` on any path. Fixed to actually record both a dangling
     (recognized-prefix-but-not-found) and a malformed (unrecognized-
     prefix) cross_ref.
  4. Symlink and ownership safety of the cache-directory hardening --
     _mkdir_owner_only (added in PR #20) followed symlinks and never
     checked ownership of a pre-existing directory, undermining its own
     stated security property. Fixed to refuse both.

Item 1 (SyntheticFence constructor / historical journal adoption) got a
documented, non-blocking disposition instead of a code fix -- see
test_KNOWN_LIMITATION_synthetic_fence_constructor_bypasses_no_adoption_rule
below for why, and the FINAL_MERGE_GATE_TRIAGE report for the full
reasoning.
"""
from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- Item 3: cross_refs validation ----------------------------------------

def _load_real_nodes():
    with open(REPO_ROOT / "docs/orneur/acceptance/register_graph.json") as f:
        graph = json.load(f)
    return graph["nodes"] if isinstance(graph, dict) and "nodes" in graph else graph


def test_real_register_graph_has_zero_cross_ref_errors():
    import importlib
    import scripts.acceptance.validate_register_graph as v
    importlib.reload(v)

    errors = v.validate(copy.deepcopy(_load_real_nodes()))
    assert errors == []


def test_dangling_cross_ref_is_now_rejected():
    """
    Regression guard for the CodeAnt finding: injecting a nonexistent but
    correctly-prefixed cross_ref into a real node used to return zero
    errors (the loop never appended anything on the failing path).
    """
    import importlib
    import scripts.acceptance.validate_register_graph as v
    importlib.reload(v)

    nodes = copy.deepcopy(_load_real_nodes())
    target = next(n for n in nodes if "cross_refs" in n)
    target["cross_refs"] = list(target["cross_refs"]) + ["C-DOES-NOT-EXIST-999"]

    errors = v.validate(nodes)
    assert any("unresolved cross_ref C-DOES-NOT-EXIST-999" in e for e in errors)


def test_malformed_prefix_cross_ref_is_now_rejected():
    import importlib
    import scripts.acceptance.validate_register_graph as v
    importlib.reload(v)

    nodes = copy.deepcopy(_load_real_nodes())
    target = next(n for n in nodes if "cross_refs" in n)
    target["cross_refs"] = list(target["cross_refs"]) + ["ZZZ-BADPREFIX"]

    errors = v.validate(nodes)
    assert any("malformed cross_ref ZZZ-BADPREFIX" in e for e in errors)


# --- Item 4: symlink / ownership safety of _mkdir_owner_only --------------

def test_mkdir_owner_only_still_creates_a_normal_directory_at_0700(tmp_path):
    from orca.config import _mkdir_owner_only

    target = tmp_path / "normal"
    _mkdir_owner_only(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_mkdir_owner_only_refuses_a_preexisting_symlink(tmp_path):
    """
    Reproduces the CodeAnt-flagged gap: chmod follows symlinks, so a
    pre-planted symlink at `path` used to get silently chmod'd through --
    restricting the ATTACKER's target directory, while every later
    diskcache read/write against `path` transparently followed the
    symlink into attacker-controlled storage. Must now be refused.
    """
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    real_target = tmp_path / "attacker_owned"
    real_target.mkdir(mode=0o777)
    victim = tmp_path / "victim"
    victim.symlink_to(real_target)

    with pytest.raises(UntrustedStoreDirectory):
        _mkdir_owner_only(victim)


def test_mkdir_owner_only_refuses_a_directory_owned_by_another_uid(tmp_path, monkeypatch):
    """
    Reproduces the second half of the CodeAnt-flagged gap: chmod(0700)
    only ever restricts the OWNING user's access -- if a pre-existing
    directory is owned by someone else, chmod changes the mode bits but
    not the owner, so that other owner keeps full access regardless.
    Can't create a real cross-uid directory without root in CI, so this
    monkeypatches os.geteuid() to simulate "this process is not the
    owner" against a directory this test process really did create.
    """
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    target = tmp_path / "owned_by_someone_else"
    target.mkdir(mode=0o755)
    real_owner_uid = target.stat().st_uid

    monkeypatch.setattr(os, "geteuid", lambda: real_owner_uid + 1)

    with pytest.raises(UntrustedStoreDirectory):
        _mkdir_owner_only(target)


def test_mkdir_owner_only_accepts_a_preexisting_directory_owned_by_this_process(tmp_path):
    """Companion to the ownership-mismatch test: the same-owner case (the
    normal "retroactively fix a looser-permission directory" scenario from
    PR #20) must still work after this fix."""
    from orca.config import _mkdir_owner_only

    target = tmp_path / "owned_by_us"
    target.mkdir(mode=0o755)
    _mkdir_owner_only(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


# --- Item 2: setuptools pin portability (pip vs uv) -----------------------

def test_lens_and_train_extras_carry_a_portable_setuptools_floor():
    """
    [tool.uv] constraint-dependencies only applies to uv-driven installs.
    A plain `pip install orneur[lens]` on Python >= 3.12 never reads it,
    and torch's own declared floor (setuptools>=77.0.3, confirmed against
    PyPI's published metadata) leaves room for a vulnerable version from a
    lagging mirror/cache. Both extras that pull in torch must carry their
    own portable (PEP 508) floor so pip enforces it too.
    """
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    extras = data["project"]["optional-dependencies"]
    for extra_name in ("lens", "train"):
        deps = extras[extra_name]
        matches = [d for d in deps if d.replace(" ", "").startswith("setuptools>=83.0.0")]
        assert matches, f"[project.optional-dependencies].{extra_name} is missing a portable setuptools>=83.0.0 floor"
        assert "python_full_version" in matches[0], (
            f"{extra_name}'s setuptools floor should be marker-scoped to "
            "python_full_version >= '3.12', matching where torch actually "
            "needs it"
        )


def test_uv_require_hashes_still_accepts_the_exact_pin_constraint():
    """
    Companion regression to the prior CI break: scripts/ci/
    run_rse_dependency_audit.sh runs `uv pip install --require-hashes`,
    which rejects any [tool.uv] constraint-dependencies entry that isn't
    an exact `==` pin. The new portable PEP 508 floors added to `lens`/
    `train` above must not have reintroduced a range form in [tool.uv].
    """
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    constraints = data["tool"]["uv"]["constraint-dependencies"]
    setuptools_constraints = [c for c in constraints if c.replace(" ", "").startswith("setuptools")]
    assert len(setuptools_constraints) == 1
    assert setuptools_constraints[0].replace(" ", "").startswith("setuptools=="), (
        "the [tool.uv] constraint must stay an exact '==' pin for "
        "--require-hashes mode"
    )


# --- Item 1: SyntheticFence -- documented, non-blocking disposition ------

def test_KNOWN_LIMITATION_synthetic_fence_constructor_bypasses_no_adoption_rule():
    """
    CodeAnt PR #20 finding: SyntheticFence.pin_observed() deliberately
    FailCloseds any attempt to adopt a historical (generation, digest)
    pair outside of a real advance() commit -- but the constructor itself
    accepts floor= and digest= directly, producing an equally non-virgin
    fence with an arbitrary historical pair, with no advance() ever
    called. That forged fence passes the exact `not fence.virgin` gate
    that orca/rse/imp3/ledger.py and orca/rse/imp3/session.py use to
    authorize boot/restore.

    NOT fixed in this triage: confirmed (via `grep -rn "SyntheticFence("
    orca/` and `grep -rln "from orca.rse.imp3" .`) that no production code
    outside tests/ constructs a SyntheticFence or calls .boot()/.restore()
    at all -- orca/rse/imp4/ocr1.py, the only real caller of anything
    under orca.rse.imp3, imports only egress.ZERO_ACCEPTANCE_AUTHORITY and
    ledger.enrolment_key, neither of which touches this fence. Same
    "confirmed unreachable from any tool-calling surface" disposition this
    repo already uses for fetch_page's SSRF gap in docs/SECURITY_AUDIT.md.
    A real fix needs an API change (the constructor can no longer freely
    accept floor/digest) that risks being broader than "narrowly scoped"
    for a bounded triage -- tracked here instead of attempted blind.
    """
    from orca.rse.imp3.journal import SyntheticFence

    forged = SyntheticFence(floor=7, digest=b"X" * 32)
    assert forged.virgin is False, (
        "if this ever becomes False by default, the constructor bypass is "
        "closed and this test (and its KNOWN_LIMITATION framing) should be "
        "updated or removed"
    )


def test_synthetic_fence_is_not_constructed_anywhere_outside_tests():
    """Confirms the "currently unreachable" half of the SyntheticFence
    disposition above stays true -- fails loudly if a future change wires
    SyntheticFence construction into a production code path without this
    triage's constructor-bypass finding being revisited first."""
    result = subprocess.run(
        ["grep", "-rn", "SyntheticFence(", "orca/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    offending = [
        line for line in result.stdout.splitlines()
        if "/tests/" not in line and not line.split(":", 1)[0].endswith("orca/rse/imp3/journal.py")
    ]
    assert offending == [], (
        "SyntheticFence is now constructed outside tests/ and its own "
        f"definition file -- re-triage the constructor-bypass finding before "
        f"shipping this: {offending}"
    )
