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

import ast
import copy
import errno
import json
import threading
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


# --- Item 4 follow-up: symlink-swap races, attacker-writable ancestors ----

_NOBODY = 65534
needs_root = pytest.mark.skipif(os.geteuid() != 0, reason="needs root to create other-uid directories")


def _attacker_dir(path: Path, mode: int = 0o755) -> Path:
    path.mkdir(mode=mode, exist_ok=True)
    os.chown(path, _NOBODY, _NOBODY)
    os.chmod(path, mode)
    return path


def test_ancestor_other_writable_is_refused(tmp_path):
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    parent = tmp_path / "shared"
    parent.mkdir()
    os.chmod(parent, 0o777)
    with pytest.raises(UntrustedStoreDirectory, match="writable"):
        _mkdir_owner_only(parent / "cache")
    assert not (parent / "cache").exists()


def test_ancestor_group_writable_is_refused(tmp_path):
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    parent = tmp_path / "grp"
    parent.mkdir()
    os.chmod(parent, 0o775)
    with pytest.raises(UntrustedStoreDirectory, match="writable"):
        _mkdir_owner_only(parent / "cache")


@needs_root
def test_ancestor_owned_by_other_uid_is_refused(tmp_path):
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    evil = _attacker_dir(tmp_path / "evil")
    with pytest.raises(UntrustedStoreDirectory, match="uid"):
        _mkdir_owner_only(evil / "cache")


@needs_root
def test_intermediate_dir_owned_by_attacker_is_refused_with_parents(tmp_path):
    """parents=True used to create/accept intermediates with no checks at all:
    <home>/<attacker-owned>/<leaf>."""
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    _attacker_dir(home / "lens")
    with pytest.raises(UntrustedStoreDirectory):
        _mkdir_owner_only(home / "lens" / "queue", parents=True)
    assert not (home / "lens" / "queue").exists()


@needs_root
def test_planted_intermediate_symlink_to_attacker_dir_is_refused(tmp_path):
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    target = _attacker_dir(tmp_path / "attacker_target", 0o777)
    (home / "lens").symlink_to(target)
    with pytest.raises(UntrustedStoreDirectory):
        _mkdir_owner_only(home / "lens" / "queue", parents=True)
    assert stat.S_IMODE(target.stat().st_mode) == 0o777, "attacker target must not be touched"
    assert list(target.iterdir()) == []


def test_intermediate_symlink_to_our_own_safe_dir_is_allowed(tmp_path):
    """Documented benign case: a symlink that resolves into a directory chain
    that itself passes the ownership/mode test cannot hand control to anyone."""
    from orca.config import _mkdir_owner_only

    safe = tmp_path / "safe"
    safe.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(safe)
    _mkdir_owner_only(tmp_path / "link" / "queue")
    assert stat.S_IMODE((safe / "queue").stat().st_mode) == 0o700


@needs_root
def test_sticky_root_owned_world_writable_parent_is_accepted(tmp_path):
    """/tmp-style: sticky stops other users renaming entries we own."""
    from orca.config import _mkdir_owner_only

    stick = tmp_path / "sticky"
    stick.mkdir()
    os.chmod(stick, 0o1777)
    _mkdir_owner_only(stick / "mine")
    assert stat.S_IMODE((stick / "mine").stat().st_mode) == 0o700


def test_missing_parent_without_parents_flag_still_fails(tmp_path):
    from orca.config import _mkdir_owner_only

    with pytest.raises(FileNotFoundError):
        _mkdir_owner_only(tmp_path / "missing" / "leaf")


def test_parents_true_creates_intermediates_at_0700(tmp_path):
    from orca.config import _mkdir_owner_only

    _mkdir_owner_only(tmp_path / "a" / "b" / "c", parents=True)
    for d in ("a", "a/b", "a/b/c"):
        assert stat.S_IMODE((tmp_path / d).stat().st_mode) == 0o700


def test_regular_file_at_leaf_is_refused_not_chmodded(tmp_path):
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    f = tmp_path / "file"
    f.write_text("x")
    os.chmod(f, 0o644)
    with pytest.raises(UntrustedStoreDirectory):
        _mkdir_owner_only(f)
    assert stat.S_IMODE(f.stat().st_mode) == 0o644


@needs_root
def test_race_leaf_swapped_for_symlink_after_mkdir_is_never_followed(tmp_path, monkeypatch):
    """Deterministic TOCTOU: the instant our mkdirat returns, the attacker
    replaces the new leaf with a symlink to their directory. The old code's
    post-mkdir is_symlink() window and path.chmod() both re-resolved the name;
    the fd-based walk opens with O_NOFOLLOW and must fail closed."""
    import orca.config as cfg

    target = _attacker_dir(tmp_path / "attacker_target", 0o777)
    victim = tmp_path / "victim"
    real_mkdir = os.mkdir

    def swapping_mkdir(name, mode=0o777, *, dir_fd=None):
        real_mkdir(name, mode, dir_fd=dir_fd)
        if name == "victim":
            os.rmdir(name, dir_fd=dir_fd)
            os.symlink(str(target), name, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", swapping_mkdir)
    with pytest.raises(cfg.UntrustedStoreDirectory):
        cfg._mkdir_owner_only(victim)
    assert stat.S_IMODE(target.stat().st_mode) == 0o777


@needs_root
def test_race_ancestor_swapped_for_symlink_before_open_fails_closed(tmp_path, monkeypatch):
    """Attacker swaps an ancestor for a symlink to their directory right
    before our openat. O_NOFOLLOW rejects the entry as a directory; the
    resulting target chain is attacker-owned and refused. Nothing is written
    into, and the mode is untouched on, the attacker's directory."""
    import orca.config as cfg

    home = tmp_path / "home"
    (home / "lens").mkdir(parents=True, mode=0o700)
    target = _attacker_dir(tmp_path / "attacker_target", 0o777)
    real_open = os.open
    swapped = []

    def swapping_open(name, flags, mode=0o777, *, dir_fd=None):
        if name == "lens" and dir_fd is not None and not swapped:
            swapped.append(1)
            (home / "lens").rmdir()
            (home / "lens").symlink_to(target)
        return real_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapping_open)
    with pytest.raises(cfg.UntrustedStoreDirectory):
        cfg._mkdir_owner_only(home / "lens" / "queue")
    assert swapped
    assert list(target.iterdir()) == []
    assert stat.S_IMODE(target.stat().st_mode) == 0o777


@needs_root
def test_attacker_owned_symlink_in_sticky_dir_is_refused_even_if_target_is_safe(tmp_path):
    """Reviewer-reported TOCTOU: in a root-owned sticky dir (/tmp) an attacker
    plants THEIR OWN symlink pointing at a trusted-looking directory. Validating
    only the resolved target would pass, after which they repoint the entry at
    attacker storage and diskcache reopens the original pathname. The symlink's
    own owner must be root/us; this one is nobody's and must be refused."""
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    stick = tmp_path / "tmp"
    stick.mkdir()
    os.chmod(stick, 0o1777)
    safe = tmp_path / "safe"
    safe.mkdir(mode=0o700)
    evil = _attacker_dir(tmp_path / "attacker_store", 0o777)
    link = stick / "x"
    os.symlink(safe, link)
    os.lchown(link, _NOBODY, _NOBODY)

    with pytest.raises(UntrustedStoreDirectory, match="symlink"):
        _mkdir_owner_only(link / "cache")
    assert list(safe.iterdir()) == [] and list(evil.iterdir()) == []

    # the attacker's follow-up (repoint) is only possible because they own the
    # entry; having been refused above, nothing was created through it.
    link.unlink()
    os.symlink(evil, link)
    os.lchown(link, _NOBODY, _NOBODY)
    with pytest.raises(UntrustedStoreDirectory):
        _mkdir_owner_only(link / "cache")
    assert list(evil.iterdir()) == []


@needs_root
def test_attacker_cannot_replace_a_root_owned_symlink_in_sticky_dir(tmp_path):
    """Why following a root/us-owned symlink is safe: sticky forbids another
    uid from unlinking/renaming it, and our walk accepts it."""
    from orca.config import _mkdir_owner_only

    stick = tmp_path / "tmp"
    stick.mkdir()
    os.chmod(stick, 0o1777)
    safe = tmp_path / "safe"
    safe.mkdir(mode=0o700)
    link = stick / "ours"
    os.symlink(safe, link)  # created by root

    pid = os.fork()
    if pid == 0:  # child: drop to the attacker uid and try to repoint the link
        try:
            os.setgid(_NOBODY)
            os.setuid(_NOBODY)
            os.unlink(link)
            os._exit(1)  # unlink succeeded -> invariant broken
        except PermissionError:
            os._exit(0)
        except BaseException:
            os._exit(2)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0, "attacker was able to remove our symlink"
    _mkdir_owner_only(link / "cache")
    assert stat.S_IMODE((safe / "cache").stat().st_mode) == 0o700


def test_symlink_loop_is_refused(tmp_path):
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    (tmp_path / "a").symlink_to(tmp_path / "b")
    (tmp_path / "b").symlink_to(tmp_path / "a")
    with pytest.raises(UntrustedStoreDirectory):
        _mkdir_owner_only(tmp_path / "a" / "leaf")


def test_absolute_and_relative_own_symlinks_are_followed(tmp_path):
    from orca.config import _mkdir_owner_only

    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "abs").symlink_to(real)
    (tmp_path / "rel").symlink_to("real")
    _mkdir_owner_only(tmp_path / "abs" / "q1")
    _mkdir_owner_only(tmp_path / "rel" / "q2")
    assert (real / "q1").is_dir() and (real / "q2").is_dir()


@needs_root
def test_lens_queue_with_caller_supplied_dir_goes_through_hardening(tmp_path):
    from orca.config import UntrustedStoreDirectory
    from orca.lens.queue import LensJobQueue

    loose = tmp_path / "loose"
    loose.mkdir(mode=0o777)
    os.chmod(loose, 0o777 & ~0o022 | 0o700)
    q = LensJobQueue(cache_dir=tmp_path / "q" / "inner")
    assert stat.S_IMODE((tmp_path / "q" / "inner").stat().st_mode) == 0o700
    q._cache.close()

    evil = _attacker_dir(tmp_path / "evil")
    with pytest.raises(UntrustedStoreDirectory):
        LensJobQueue(cache_dir=evil / "q")


@needs_root
def test_race_stress_never_touches_attacker_target(tmp_path):
    """Concurrent attacker flips the leaf between a real directory and a
    symlink to their 0777 directory while we call repeatedly. Whatever the
    interleaving, the attacker's target must never be chmod'ed or written."""
    import orca.config as cfg

    target = _attacker_dir(tmp_path / "attacker_target", 0o777)
    victim = tmp_path / "victim"
    stop = threading.Event()

    def attacker():
        while not stop.is_set():
            try:
                if victim.is_symlink():
                    victim.unlink()
                elif victim.exists():
                    victim.rmdir()
                victim.symlink_to(target)
                victim.unlink()
                victim.mkdir()
            except OSError:
                pass

    t = threading.Thread(target=attacker)
    t.start()
    try:
        for _ in range(3000):
            try:
                cfg._mkdir_owner_only(victim)
            except (cfg.UntrustedStoreDirectory, OSError):
                pass
            assert stat.S_IMODE(target.stat().st_mode) == 0o777
            assert list(target.iterdir()) == []
    finally:
        stop.set()
        t.join()


def test_every_diskcache_store_lives_under_a_hardened_directory():
    """Enforceable invariant for the code after _mkdir_owner_only returns:
    diskcache.Cache(...) is only ever opened on CACHE_DIR/QUEUE_DIR (or the
    queue's cache_dir parameter, which is itself passed through
    _mkdir_owner_only before use) -- i.e. a directory
    that passed the walk above and is 0700, owned by us, in a chain no other
    non-root account can write to."""
    allowed = ("CACHE_DIR", "QUEUE_DIR", "directory")
    seen = 0
    for py in (REPO_ROOT / "orca").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("diskcache.Cache"):
                seen += 1
                assert any(a in ast.unparse(n.args[0]) for a in allowed), (
                    f"{py}:{n.lineno} opens diskcache outside a hardened dir: {ast.unparse(n)}"
                )
    assert seen >= 2
    # `directory` in the queue is the return value of the hardening call.
    assert "directory = _mkdir_owner_only(Path(cache_dir), parents=True)" in (
        REPO_ROOT / "orca/lens/queue.py"
    ).read_text(encoding="utf-8")


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


_FENCE = "SyntheticFence"


def _synthetic_fence_use_sites(root: Path) -> list[str]:
    """AST scan of every non-test .py file under `root` (journal.py, where
    the class is defined, is NOT exempt) for anything that could construct a
    SyntheticFence: a direct call, a call through an alias (`import ... as`
    or `X = SyntheticFence`), a subclass, or a getattr/__import__ lookup by
    the string name. The class definition itself and plain isinstance /
    annotation references are the only uses allowed to pass.

    Known limitation (static analysis): construction through `type(obj)(...)`,
    copy/pickle of an existing instance, or fully dynamic names built at
    runtime is not detected. The fence stays a test-only synthetic object
    regardless -- see SYNTHETIC_NOT_REAL_HARDWARE_PROOF."""
    hits: list[str] = []
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root)
        if rel.parts[0] in {"tests", "node_modules", "notebooks"} or any(
            p.startswith(".") or p in {"venv", "site-packages"} for p in rel.parts
        ):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            hits.append(f"{rel}: unparseable (cannot prove it is clean)")
            continue
        aliases = {_FENCE}

        def refs(node) -> bool:
            return (isinstance(node, ast.Name) and node.id in aliases) or (
                isinstance(node, ast.Attribute) and node.attr in aliases
            )

        changed = True
        while changed:  # fixpoint over `A = SyntheticFence; B = A`
            changed = False
            for n in ast.walk(tree):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    for a in n.names:
                        if a.asname and a.name.split(".")[-1] in aliases and a.asname not in aliases:
                            aliases.add(a.asname)
                            hits.append(f"{rel}:{n.lineno}: aliased import of {_FENCE}")
                            changed = True
                elif isinstance(n, ast.Assign) and refs(n.value):
                    for t in n.targets:
                        if isinstance(t, ast.Name) and t.id not in aliases:
                            aliases.add(t.id)
                            hits.append(f"{rel}:{n.lineno}: alias assignment of {_FENCE}")
                            changed = True
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                if refs(n.func):
                    hits.append(f"{rel}:{n.lineno}: call to {_FENCE}")
                if any(isinstance(a, ast.Constant) and a.value == _FENCE for a in n.args):
                    hits.append(f"{rel}:{n.lineno}: dynamic lookup of {_FENCE} by name")
            elif isinstance(n, ast.ClassDef) and any(refs(b) for b in n.bases):
                hits.append(f"{rel}:{n.lineno}: subclass of {_FENCE}")
    return hits


def test_synthetic_fence_is_not_constructed_anywhere_outside_tests():
    """Confirms the "currently unreachable" half of the SyntheticFence
    disposition stays true. Unlike the earlier grep-based version, this
    does not exempt journal.py, so a new call inside the defining module
    is caught too."""
    assert _synthetic_fence_use_sites(REPO_ROOT) == []


@pytest.mark.parametrize(
    "source",
    [
        "class SyntheticFence:\n    pass\n\ndef forge():\n    return SyntheticFence(floor=7, digest=b'X' * 32)\n",
        "class SyntheticFence:\n    pass\n\n_f = SyntheticFence()\n",
        "class SyntheticFence:\n    pass\n\nF = SyntheticFence\nx = F(1, b'')\n",
        "from orca.rse.imp3.journal import SyntheticFence as SF\nx = SF()\n",
        "import orca.rse.imp3.journal as j\nx = j.SyntheticFence()\n",
        "class SyntheticFence:\n    pass\n\nclass Sub(SyntheticFence):\n    pass\n",
        "import importlib\nm = importlib.import_module('x')\nc = getattr(m, 'SyntheticFence')\n",
    ],
)
def test_synthetic_fence_scanner_catches_evasions_including_inside_journal_py(tmp_path, source):
    """Scanner self-test: each of these -- notably a call placed inside
    journal.py itself, the file the old grep exempted -- must be reported."""
    journal = tmp_path / "orca" / "rse" / "imp3" / "journal.py"
    journal.parent.mkdir(parents=True)
    journal.write_text(source)
    assert _synthetic_fence_use_sites(tmp_path) != []


def test_synthetic_fence_scanner_allows_definition_isinstance_and_docs(tmp_path):
    mod = tmp_path / "orca" / "ok.py"
    mod.parent.mkdir(parents=True)
    mod.write_text(
        '"""SyntheticFence( in a docstring is not a call."""\n'
        "from orca.rse.imp3.journal import SyntheticFence\n"
        "# SyntheticFence() in a comment\n"
        "def gate(f: SyntheticFence) -> bool:\n    return isinstance(f, SyntheticFence) and not f.virgin\n"
    )
    assert _synthetic_fence_use_sites(tmp_path) == []


def test_synthetic_fence_is_labelled_synthetic_not_hardware_trust():
    """The fence is a deterministic software counter, not a TPM NV index or
    any hardware-backed monotonic counter; its own label must keep saying so."""
    from orca.rse.imp3.journal import SYNTHETIC_NOT_REAL_HARDWARE_PROOF, SyntheticFence

    assert SYNTHETIC_NOT_REAL_HARDWARE_PROOF == "SYNTHETIC_NOT_REAL_HARDWARE_PROOF"
    assert SyntheticFence.label == SYNTHETIC_NOT_REAL_HARDWARE_PROOF
