"""
Antigravity Audit #007 remediation -- cache-directory trust boundary.

Finding 1: descriptor-validated canonical location vs. an attacker-
redirectable pathname used by downstream diskcache opens.
Finding 2: LensJobQueue(cache_dir=...) bypassing the directory hardening.

Invariant under test (see orca.config._mkdir_owner_only): the path it
RETURNS is the verified canonical chain -- no symlink in it, every component
root/us-owned, and either unwritable-by-others or sealed (0700) -- so no other
non-root account can make it resolve elsewhere after validation.

Tests marked needs_root create other-uid objects (uid 65534) and are skipped
on a non-root runner; they are executed in the root run recorded in the PR.
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

import pytest

NOBODY = 65534
needs_root = pytest.mark.skipif(os.geteuid() != 0, reason="needs root to create other-uid objects")


@pytest.fixture
def unsealed_base():
    """0755 directory under sticky /tmp (like a normal home): not sealed."""
    if not os.path.isdir("/tmp") or not (os.stat("/tmp").st_mode & stat.S_ISVTX):
        pytest.skip("needs a sticky /tmp")
    base = Path(tempfile.mkdtemp(dir="/tmp"))
    os.chmod(base, 0o755)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _chown_dir(path: Path, mode: int) -> Path:
    path.mkdir(mode=mode, exist_ok=True)
    os.chown(path, NOBODY, NOBODY)
    os.chmod(path, mode)
    return path


def _as_attacker(fn) -> int:
    """Run fn() in a forked child as uid 65534; return its exit code
    (0 = fn raised PermissionError, i.e. the attack was blocked)."""
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups([])
            os.setgid(NOBODY)
            os.setuid(NOBODY)
            fn()
            os._exit(1)  # attack succeeded
        except PermissionError:
            os._exit(0)
        except BaseException:
            os._exit(2)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


# --- Finding 1: returned path is the verified canonical chain -------------

def test_returned_path_contains_no_symlink_even_when_walk_followed_one(tmp_path):
    from orca.config import _mkdir_owner_only

    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "abs").symlink_to(real)
    (tmp_path / "rel").symlink_to("real")
    (real / "sub").mkdir()
    (tmp_path / "dotdot").symlink_to("real/sub/..")  # target containing ..

    for entry in ("abs", "rel", "dotdot"):
        ret = _mkdir_owner_only(tmp_path / entry / "queue")
        assert ret == Path(os.path.realpath(ret)), f"{entry}: returned path still has a symlink"
        assert ret == real / "queue"
        assert stat.S_IMODE(ret.stat().st_mode) == 0o700


def test_returned_path_for_plain_dir_is_the_same_dir(tmp_path):
    from orca.config import _mkdir_owner_only

    assert _mkdir_owner_only(tmp_path / "a" / "b", parents=True) == tmp_path / "a" / "b"


@needs_root
def test_attacker_cannot_redirect_the_returned_path(unsealed_base):
    """End to end for the audited exploit. The only symlink in the supplied
    path is owned by root (us), in a sticky dir. Every way another uid could
    redirect the RETURNED canonical path -- unlink/rename our link, replace
    or rename any directory in the chain -- is denied by the kernel."""
    from orca.config import _mkdir_owner_only

    stick = unsealed_base / "tmp"
    stick.mkdir()
    os.chmod(stick, 0o1777)
    safe = unsealed_base / "safe"
    safe.mkdir(mode=0o700)
    evil = _chown_dir(unsealed_base / "evil", 0o777)
    link = stick / "ours"
    os.symlink(safe, link)

    ret = _mkdir_owner_only(link / "cache")
    assert ret == safe / "cache"

    attacks = [
        lambda: os.unlink(link),
        lambda: os.rename(link, stick / "moved"),
        lambda: os.symlink(evil, stick / "ours2") or os.rename(stick / "ours2", link),
        lambda: os.rename(safe, unsealed_base / "safe_moved"),
        lambda: os.rename(ret, evil / "stolen"),
        lambda: shutil.rmtree(ret),
        lambda: os.mkdir(ret / "planted"),
        lambda: os.listdir(safe),
    ]
    for i, attack in enumerate(attacks):
        assert _as_attacker(attack) == 0, f"attack #{i} was not blocked"
    assert os.path.realpath(ret) == str(ret) and list(evil.iterdir()) == []


@needs_root
def test_attacker_owned_symlink_in_sticky_dir_refused_before_any_open(unsealed_base):
    """The Audit #007 / reviewer exploit: attacker-owned link -> safe target,
    later repointed. Refused at validation; nothing is created in either dir."""
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    stick = unsealed_base / "tmp"
    stick.mkdir()
    os.chmod(stick, 0o1777)
    safe = unsealed_base / "safe"
    safe.mkdir(mode=0o700)
    evil = _chown_dir(unsealed_base / "evil", 0o777)
    link = stick / "x"
    os.symlink(safe, link)
    os.lchown(link, NOBODY, NOBODY)
    with pytest.raises(UntrustedStoreDirectory, match="symlink"):
        _mkdir_owner_only(link / "cache")
    link.unlink()
    os.symlink(evil, link)
    os.lchown(link, NOBODY, NOBODY)
    with pytest.raises(UntrustedStoreDirectory):
        _mkdir_owner_only(link / "cache")
    assert list(safe.iterdir()) == [] and list(evil.iterdir()) == []


@needs_root
def test_attacker_cannot_traverse_sealed_subtree(tmp_path):
    """Why deeper group/other-writable bits are harmless below a 0700 dir."""
    from orca.config import _mkdir_owner_only

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    inner = home / "lens"
    inner.mkdir(mode=0o777)
    os.chmod(inner, 0o777)
    ret = _mkdir_owner_only(inner / "queue")
    assert _as_attacker(lambda: os.mkdir(ret / "x")) == 0
    assert _as_attacker(lambda: os.rename(inner, home / "lens2")) == 0


# --- compatibility: umask, sealed subtree, pre-existing release layouts ---

@pytest.mark.parametrize("mask", [0o077, 0o027, 0o022, 0o002, 0o000])
def test_umask_does_not_leak_into_created_or_tightened_dirs(tmp_path, mask):
    from orca.config import _mkdir_owner_only

    old = os.umask(mask)
    try:
        ret = _mkdir_owner_only(tmp_path / f"m{mask:o}" / "a" / "b", parents=True)
        again = _mkdir_owner_only(ret)  # idempotent
    finally:
        os.umask(old)
    assert again == ret
    for d in (ret, ret.parent, ret.parent.parent):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700


def test_looser_leftover_dir_below_sealed_home_is_accepted_and_tightened(tmp_path):
    """Upgrade path: a prior release under `umask 002` left ~/.orca/lens 0775
    and queue 0775. ORCA_HOME is 0700 (sealed), so these are unreachable by
    others; import must not start failing -- and the leaf is tightened."""
    from orca.config import _mkdir_owner_only

    home = tmp_path / ".orca"
    home.mkdir(mode=0o700)
    (home / "lens").mkdir()
    os.chmod(home / "lens", 0o775)
    (home / "lens" / "queue").mkdir()
    os.chmod(home / "lens" / "queue", 0o775)
    ret = _mkdir_owner_only(home / "lens" / "queue", parents=True)
    assert stat.S_IMODE(ret.stat().st_mode) == 0o700
    assert stat.S_IMODE((home / "lens").stat().st_mode) == 0o775  # untouched, not ours to rewrite


def test_group_writable_ancestor_above_an_unsealed_chain_is_still_refused(unsealed_base):
    from orca.config import _mkdir_owner_only, UntrustedStoreDirectory

    shared = unsealed_base / "shared"
    shared.mkdir()
    os.chmod(shared, 0o775)
    with pytest.raises(UntrustedStoreDirectory, match="writable"):
        _mkdir_owner_only(shared / "cache")


def test_unsupported_platform_fails_closed(tmp_path, monkeypatch):
    import orca.config as cfg

    monkeypatch.setattr(cfg, "_DIRFD_SUPPORTED", False)
    with pytest.raises(cfg.UntrustedStoreDirectory, match="unsupported platform"):
        cfg._mkdir_owner_only(tmp_path / "x")
    assert not (tmp_path / "x").exists()


def test_config_module_constants_are_canonical_and_private():
    import orca.config as cfg

    for d in (cfg.ORCA_HOME, cfg.MEMORY_DIR, cfg.CACHE_DIR, cfg.VAULT_DIR):
        assert d == Path(os.path.realpath(d))
        assert stat.S_IMODE(d.stat().st_mode) == 0o700 and d.stat().st_uid == os.geteuid()


# --- Finding 2: LensJobQueue explicit cache_dir ---------------------------

def test_default_queue_dir_is_hardened_and_queue_round_trips(tmp_path):
    import orca.lens.queue as q

    assert stat.S_IMODE(q.QUEUE_DIR.stat().st_mode) == 0o700
    assert q.QUEUE_DIR == Path(os.path.realpath(q.QUEUE_DIR))
    jq = q.LensJobQueue(cache_dir=tmp_path / "custom")
    job_id = jq.submit("hello")
    assert jq.get_status(job_id).status == "pending"
    jq._cache.close()


def test_custom_cache_dir_safe_directory_still_works_and_is_tightened(tmp_path):
    from orca.lens.queue import LensJobQueue

    d = tmp_path / "mine"
    d.mkdir()
    os.chmod(d, 0o777)
    jq = LensJobQueue(cache_dir=d)
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    jq._cache.close()


def test_custom_cache_dir_accepts_str_and_relative(tmp_path, monkeypatch):
    from orca.lens.queue import LensJobQueue

    monkeypatch.chdir(tmp_path)
    jq = LensJobQueue(cache_dir="relq")  # type: ignore[arg-type]
    assert (tmp_path / "relq").is_dir()
    jq._cache.close()


def test_custom_cache_dir_symlink_leaf_refused(tmp_path):
    from orca.config import UntrustedStoreDirectory
    from orca.lens.queue import LensJobQueue

    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "q").symlink_to(target)
    with pytest.raises(UntrustedStoreDirectory):
        LensJobQueue(cache_dir=tmp_path / "q")
    assert list(target.iterdir()) == []


@needs_root
def test_custom_cache_dir_foreign_owned_and_foreign_parent_refused(tmp_path):
    from orca.config import UntrustedStoreDirectory
    from orca.lens.queue import LensJobQueue

    evil = _chown_dir(tmp_path / "evil", 0o755)
    with pytest.raises(UntrustedStoreDirectory):
        LensJobQueue(cache_dir=evil)  # leaf owned by someone else
    with pytest.raises(UntrustedStoreDirectory):
        LensJobQueue(cache_dir=evil / "q")  # parent owned by someone else
    assert list(evil.iterdir()) == []


def test_custom_cache_dir_world_writable_unsealed_parent_refused(unsealed_base):
    from orca.config import UntrustedStoreDirectory
    from orca.lens.queue import LensJobQueue

    shared = unsealed_base / "shared"
    shared.mkdir()
    os.chmod(shared, 0o777)
    with pytest.raises(UntrustedStoreDirectory):
        LensJobQueue(cache_dir=shared / "q")


@needs_root
def test_lens_queue_via_own_symlink_stores_in_the_verified_directory(unsealed_base):
    from orca.lens.queue import LensJobQueue

    safe = unsealed_base / "safe"
    safe.mkdir(mode=0o700)
    (unsealed_base / "link").symlink_to(safe)
    jq = LensJobQueue(cache_dir=unsealed_base / "link" / "q")
    jq.submit("x")
    jq._cache.close()
    assert (safe / "q" / "cache.db").exists()


# --- other diskcache construction site: SemanticMemory --------------------

def _semantic(monkeypatch, cache_dir: Path):
    import orca.brain.memory as mem

    monkeypatch.setattr(mem, "CACHE_DIR", cache_dir)
    return mem.SemanticMemory()


def test_semantic_memory_normal_and_tightened(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    (cache / "semantic").mkdir()
    os.chmod(cache / "semantic", 0o777)
    sm = _semantic(monkeypatch, cache)
    sm.store_fact("k", {"v": 1})
    assert sm.recall_fact("k") == {"v": 1}
    assert stat.S_IMODE((cache / "semantic").stat().st_mode) == 0o700
    sm._cache.close()


def test_semantic_memory_refuses_preplanted_symlink(tmp_path, monkeypatch):
    from orca.config import UntrustedStoreDirectory

    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    target = tmp_path / "attacker"
    target.mkdir()
    (cache / "semantic").symlink_to(target)
    with pytest.raises(UntrustedStoreDirectory):
        _semantic(monkeypatch, cache)
    assert list(target.iterdir()) == []


@needs_root
def test_semantic_memory_refuses_foreign_owned_dir(tmp_path, monkeypatch):
    from orca.config import UntrustedStoreDirectory

    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    _chown_dir(cache / "semantic", 0o755)
    with pytest.raises(UntrustedStoreDirectory):
        _semantic(monkeypatch, cache)


# --- G-019: execute-only ancestors -----------------------------------------------------------------------------------------------------

@needs_root
def test_execute_only_ancestor_owned_by_another_user_is_traversable():
    """The walk used to open every ancestor O_RDONLY, which needs READ permission. A root-owned 0711 directory on the way to the user's own
    0700 home made startup fail with PermissionError for no security reason: the ancestor is only traversed."""
    from orca.config import _mkdir_owner_only

    base = Path(tempfile.mkdtemp(dir="/tmp"))
    try:
        os.chmod(base, 0o711)                                   # root-owned, execute-only for everyone else
        home = base / "nb"
        home.mkdir(mode=0o700)
        os.chown(home, NOBODY, NOBODY)

        def attempt():
            ret = _mkdir_owner_only(home / "queue" / "inner", parents=True)
            os._exit(0 if ret == home / "queue" / "inner" else 3)

        pid = os.fork()
        if pid == 0:
            try:
                os.setgroups([])
                os.setgid(NOBODY)
                os.setuid(NOBODY)
                attempt()
            except BaseException:
                os._exit(1)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert stat.S_IMODE((home / "queue" / "inner").stat().st_mode) == 0o700
    finally:
        shutil.rmtree(base, ignore_errors=True)
