"""Synthetic-only guarantee: a runtime sentinel that makes the dry-run FAIL CLOSED instead of trusting itself.

While a SyntheticOnlyGuard is active:
  * importing any real-trainer / tensor / HF / experiment-tracking package raises SyntheticGuaranteeViolation (a BaseException, so a stray
    `except Exception` / `except ImportError` cannot swallow it; every violation is ALSO recorded and re-checked at the end);
  * socket creation, DNS, connect/bind/send, ctypes.dlopen (GPU driver libraries), subprocess/exec/fork are blocked (PEP 578 audit hook);
  * file reads outside {sandbox, interpreter + stdlib + site-packages, the orca package source, /dev/null, /dev/urandom} are blocked, and
    ALL writes/creations/removals outside the sandbox are blocked -- so protected data (eval_private/, ~/.orca, secrets), GPU device nodes
    and anything else on disk are unreachable;
  * the guard refuses to start (SyntheticGuaranteeUnavailable) if it cannot establish the guarantee: a forbidden package is already imported,
    the sandbox is not a real directory under the system temp dir, or its own start-up self-test (it must be able to see itself block a
    socket and a forbidden import) fails.

Honest limits (documented, tested where testable):
  * This is a tripwire for ORNEUR's own code, not a security sandbox against hostile code in the same process: code that can run arbitrary
    Python can undo in-process state. PEP 578 audit hooks cannot be removed once installed, so after the guard exits the hook stays
    installed but INERT (it only enforces while a guard is active).
  * Modules already imported BEFORE the guard starts are the caller's responsibility (heavy imports must happen first; the guard rejects
    forbidden ones). Reads performed by the interpreter's own C code without an audit event are not seen.
  * The guarantee is per-process; the pytest proofs run in a SUBPROCESS so the permanent hook never leaks into the test runner.
"""
from __future__ import annotations

import os
import sys
import sysconfig
import tempfile
import threading
from importlib.abc import MetaPathFinder
from pathlib import Path

FORBIDDEN_TOP_LEVEL = (
    "torch", "torchvision", "torchaudio", "triton", "transformers", "tokenizers", "unsloth", "unsloth_zoo", "trl", "peft", "bitsandbytes",
    "accelerate", "datasets", "deepspeed", "tensorflow", "keras", "jax", "jaxlib", "flax", "xformers", "vllm", "safetensors", "wandb",
    "optimum", "sentencepiece", "huggingface_hub",
)
_BLOCKED_EVENT_PREFIXES = ("socket.", "ctypes.dlopen", "ctypes.dlsym", "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
                           "os.fork", "os.forkpty")
_WRITE_PATH_EVENTS = {"os.mkdir": (0,), "os.remove": (0,), "os.rmdir": (0,), "os.rename": (0, 1), "os.truncate": (0,), "os.chmod": (0,),
                      "os.chown": (0,), "os.link": (0, 1), "os.symlink": (1,), "os.utime": (0,), "shutil.rmtree": (0,), "shutil.copyfile": (0, 1),
                      "shutil.move": (0, 1)}
_READ_PATH_EVENTS = {"os.listdir": (0,), "os.scandir": (0,), "glob.glob": (0,)}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class SyntheticGuaranteeViolation(BaseException):
    """The synthetic-only guarantee was broken (forbidden import / network / out-of-sandbox path). BaseException on purpose."""


class SyntheticGuaranteeUnavailable(RuntimeError):
    """The guarantee cannot be established here, so the dry-run must not start (fail closed)."""


class _State:
    lock = threading.RLock()
    active = False
    token = None
    sandbox = None
    read_roots: tuple = ()
    list_ok: frozenset = frozenset()
    violations: list = []
    hook_installed = False
    in_hook = threading.local()


def _real(p) -> str:
    return os.path.realpath(os.fsdecode(p))


def _under(path: str, roots) -> bool:
    return any(path == r or path.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def path_decision(path, *, write: bool, sandbox: str, read_roots) -> bool:
    """Pure policy used by the audit hook (and unit-testable): may this path be touched?"""
    rp = _real(path)
    if _under(rp, (sandbox,)):
        return True
    return (not write) and _under(rp, read_roots)


def default_read_roots() -> tuple:
    import orca
    roots = {_real(sys.prefix), _real(sys.base_prefix), _real(sys.exec_prefix), _real(Path(orca.__file__).resolve().parent)}
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        roots.add(_real(sysconfig.get_paths()[key]))
    roots.update(_real(p) for p in sys.path if p and os.path.isdir(p) and "site-packages" in p)
    roots.update({"/dev/null", "/dev/urandom", "/dev/random"})
    return tuple(sorted(roots))


class _BlockingFinder(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if _State.active and fullname.partition(".")[0] in FORBIDDEN_TOP_LEVEL:
            _violate("import", fullname)
        return None


def _violate(event: str, detail: str):
    _State.violations.append((event, detail))
    raise SyntheticGuaranteeViolation(f"synthetic-only guarantee violated: {event} {detail}")


def _audit(event, args):
    if not _State.active or getattr(_State.in_hook, "busy", False):
        return
    _State.in_hook.busy = True
    try:
        if event.startswith(_BLOCKED_EVENT_PREFIXES):
            _violate(event, "blocked")
        if event == "open":
            target, mode, flags = args[0], args[1], args[2]
            if isinstance(target, int):
                return
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and bool(flags & _WRITE_FLAGS))
            if not path_decision(target, write=write, sandbox=_State.sandbox, read_roots=_State.read_roots):
                _violate("open-write" if write else "open-read", _real(target))
        elif event in _WRITE_PATH_EVENTS:
            for i in _WRITE_PATH_EVENTS[event]:
                if i < len(args) and isinstance(args[i], (str, bytes, os.PathLike)) and not path_decision(
                        args[i], write=True, sandbox=_State.sandbox, read_roots=()):
                    _violate(event, _real(args[i]))
        elif event in _READ_PATH_EVENTS:
            for i in _READ_PATH_EVENTS[event]:
                if i < len(args) and isinstance(args[i], (str, bytes, os.PathLike)) and _real(args[i]) not in _State.list_ok \
                        and not path_decision(args[i], write=False, sandbox=_State.sandbox, read_roots=_State.read_roots):
                    _violate(event, _real(args[i]))
    finally:
        _State.in_hook.busy = False


class GuardAttestation:
    """Proof, checked by the harness on every run, that THIS guard instance is the live one. Cannot be constructed by callers."""
    _MINT = object()

    def __init__(self, token, mint):
        if mint is not GuardAttestation._MINT:
            raise SyntheticGuaranteeUnavailable("attestations are minted by SyntheticOnlyGuard only")
        self._token = token

    def assert_active(self) -> None:
        with _State.lock:
            if not (_State.active and _State.token is not None and _State.token is self._token):
                raise SyntheticGuaranteeUnavailable("synthetic-only guard is not active")
        _probe_blocks()

    def assert_no_violations(self) -> None:
        if _State.violations:
            raise SyntheticGuaranteeViolation("violations were recorded during the run: " + repr(_State.violations[:5]))


def _probe_blocks() -> None:
    """Positive self-test: the guard must be SEEN blocking a socket and a forbidden import right now, otherwise it is not really on."""
    import socket
    seen = set()
    n = len(_State.violations)
    try:
        socket.socket()
    except SyntheticGuaranteeViolation:
        seen.add("socket")
    except OSError:
        pass
    try:
        __import__("torch")
    except SyntheticGuaranteeViolation:
        seen.add("import")
    except ImportError:
        pass
    del _State.violations[n:]                     # the probe's own violations are not run violations
    if seen != {"socket", "import"}:
        raise SyntheticGuaranteeUnavailable("guard self-test failed: the sentinel is not blocking sockets and forbidden imports")


class SyntheticOnlyGuard:
    def __init__(self, sandbox):
        self.sandbox = Path(sandbox)
        self._finder = _BlockingFinder()
        self._saved_env: dict = {}
        self._saved_dwb = None
        self._token = object()

    @property
    def violations(self) -> list:
        return list(_State.violations)

    def _preflight(self) -> str:
        if _State.active:
            raise SyntheticGuaranteeUnavailable("a guard is already active (guards do not nest)")
        loaded = sorted(m for m in sys.modules if m.partition(".")[0] in FORBIDDEN_TOP_LEVEL)
        if loaded:
            raise SyntheticGuaranteeUnavailable(f"forbidden package(s) already imported: {loaded}")
        if self.sandbox.is_symlink() or not self.sandbox.is_dir():
            raise SyntheticGuaranteeUnavailable("sandbox must be an existing real directory")
        sb = _real(self.sandbox)
        if not _under(sb, (_real(tempfile.gettempdir()),)) or sb == _real(tempfile.gettempdir()):
            raise SyntheticGuaranteeUnavailable("sandbox must be a directory strictly inside the system temp dir")
        if os.stat(sb).st_uid != os.geteuid():
            raise SyntheticGuaranteeUnavailable("sandbox is not owned by the current user")
        return sb

    def __enter__(self) -> GuardAttestation:
        with _State.lock:
            sb = self._preflight()
            _State.sandbox = sb
            _State.read_roots = default_read_roots()
            # The import system lists sys.path directories (names only) to find modules; allow exactly those listings, nothing else.
            _State.list_ok = frozenset(_real(p or os.getcwd()) for p in sys.path)
            _State.violations = []
            if not _State.hook_installed:
                sys.addaudithook(_audit)
                _State.hook_installed = True
            sys.meta_path.insert(0, self._finder)
            self._saved_dwb, sys.dont_write_bytecode = sys.dont_write_bytecode, True
            for k, v in (("CUDA_VISIBLE_DEVICES", ""), ("HF_HUB_OFFLINE", "1"), ("TRANSFORMERS_OFFLINE", "1"), ("WANDB_MODE", "disabled")):
                self._saved_env[k] = os.environ.get(k)
                os.environ[k] = v
            _State.token, _State.active = self._token, True
        att = GuardAttestation(self._token, GuardAttestation._MINT)
        try:
            att.assert_active()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return att

    def __exit__(self, exc_type, exc, tb):
        with _State.lock:
            _State.active, _State.token = False, None
            try:
                sys.meta_path.remove(self._finder)
            except ValueError:
                pass
            if self._saved_dwb is not None:
                sys.dont_write_bytecode = self._saved_dwb
            for k, v in self._saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            self._saved_env = {}
        return False


def forbidden_modules_loaded() -> list:
    return sorted(m for m in sys.modules if m.partition(".")[0] in FORBIDDEN_TOP_LEVEL)
