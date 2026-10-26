"""One Chromium process per user and mission.

The binary is the real Chrome executable. A wrapper that injects
``--no-sandbox`` is refused, and a running command line that contains
that flag is killed. Page content cannot mint a grant.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import resource
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from orca.browser_engine.cdp import CdpPipe
from orca.browser_engine.policy import PolicyError, check_destination, validate_allowlist
from orca.browser_engine.proxy import FilteringProxy

_MAX_GRANT_SECONDS = 120
_MAX_TABS = 4
_ACTIONS = frozenset({"navigate", "click", "fill", "scroll", "screenshot", "read", "download"})
_SELECTOR = re.compile(r"^#[A-Za-z][A-Za-z0-9_-]{0,62}$")
_SESSION_SCHEMA = "orneur-browser-session/1"
_GRANT_MINT = object()
_FILE_SIZE_CAP = 256 * 1024 * 1024
_UNIX_SOCKET_PATH_MAX = 107
_SCOPE_CHARS = 16


class BrowserError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Grant:
    grant_id: str
    user_id: str
    mission_id: str
    allow_loopback: frozenset[str]
    actions: frozenset[str]
    expires_at: datetime
    token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.token is not _GRANT_MINT:
            raise BrowserError("grant_refused")

    def permits(self, action: str, now: datetime) -> None:
        if now >= self.expires_at:
            raise BrowserError("grant_expired")
        if action not in self.actions:
            raise BrowserError("action_not_granted")


def issue_grant(*, user_id: str, mission_id: str, allow_loopback: tuple[str, ...], actions: tuple[str, ...], ttl_seconds: int, now: datetime | None = None) -> Grant:
    if (
        not user_id
        or not mission_id
        or user_id in {".", ".."}
        or mission_id in {".", ".."}
        or "/" in user_id
        or "/" in mission_id
        or "\\" in user_id
        or "\\" in mission_id
        or "\x00" in user_id
        or "\x00" in mission_id
    ):
        raise BrowserError("grant_refused")
    if ttl_seconds < 1 or ttl_seconds > _MAX_GRANT_SECONDS:
        raise BrowserError("grant_ttl_refused")
    chosen = frozenset(actions)
    if not chosen or not chosen <= _ACTIONS:
        raise BrowserError("grant_refused")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise BrowserError("naive_clock")
    return Grant(
        grant_id=hashlib.sha256(os.urandom(16)).hexdigest(),
        user_id=user_id,
        mission_id=mission_id,
        allow_loopback=validate_allowlist(allow_loopback),
        actions=chosen,
        expires_at=clock + timedelta(seconds=ttl_seconds),
        token=_GRANT_MINT,
    )


def chrome_binary() -> Path:
    configured = os.environ.get("ORNEUR_CHROME_BINARY", "/opt/google/chrome/chrome")
    path = Path(configured)
    if path.is_symlink() or not path.is_file():
        raise BrowserError("chrome_binary_refused")
    with path.open("rb") as handle:
        sample = handle.read(256)
    if sample.startswith(b"#!") or b"--no-sandbox" in sample:
        raise BrowserError("sandbox_refused")
    return path


def runtime_scope(user_id: str, mission_id: str) -> str:
    """Short directory name so Chrome's SingletonSocket fits AF_UNIX."""
    return hashlib.sha256(f"{user_id}\0{mission_id}".encode()).hexdigest()[:_SCOPE_CHARS]


def chrome_runtime_root() -> Path:
    """Host directory for Chrome user-data dirs.

    Mission workspaces nest UUIDs until the profile path exceeds the Unix
    socket limit and Chrome exits before DevTools is ready. This root stays
    short. Isolation remains per user and mission via ``runtime_scope``.
    """
    configured = os.environ.get("ORNEUR_CHROME_RUNTIME")
    root = Path(configured) if configured else Path("/tmp/orneur-chrome")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    return root


def quarantine_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or name != Path(name).name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or any(ord(char) < 32 for char in name)
    ):
        raise BrowserError("download_refused")
    return name


class BrowserEngine:
    def __init__(self, root: Path, grant: Grant, *, resolver=None):
        self.root = Path(root)
        self.grant = grant
        self.resolver = resolver
        self.evidence: list[dict] = []
        self._process: subprocess.Popen | None = None
        self._proxy: FilteringProxy | None = None
        self._cdp: CdpPipe | None = None
        self._tabs: dict[str, str] = {}
        self._active: str | None = None
        self._active_target: str | None = None
        self._closed = False
        self.scope = runtime_scope(grant.user_id, grant.mission_id)
        self.home = self.root / self.scope
        self.profile = self.home / "c"
        self.quarantine = self.home / "d"
        self.evidence_path = self.home / "evidence.jsonl"
        self.state_path = self.home / "state.json"
        socket_path = str(self.profile / "SingletonSocket")
        if len(socket_path.encode()) > _UNIX_SOCKET_PATH_MAX:
            raise BrowserError("path_refused")

    def start(self, now: datetime | None = None) -> None:
        self._require_grant("navigate", now)
        if self._process is not None:
            raise BrowserError("browser_already_started")
        binary = chrome_binary()
        self._prepare_mission_dirs()
        if self.state_path.exists():
            self._validate_state()
        elif self.profile.exists():
            raise BrowserError("resume_refused")
        self.profile.mkdir(mode=0o700, exist_ok=True)
        self.quarantine.mkdir(mode=0o700, exist_ok=True)
        self._proxy = FilteringProxy(self.grant.allow_loopback, self.resolver)
        self._proxy.start()
        parent_to_chrome_r, parent_to_chrome_w = os.pipe()
        chrome_to_parent_r, chrome_to_parent_w = os.pipe()
        # Chrome reads DevTools from fd 3 and writes it to fd 4. Python's
        # subprocess closer runs after preexec_fn, so the descriptors have to
        # already be 3 and 4 and listed in pass_fds. Dup2 in the parent is
        # restored after the child starts.
        saved: dict[int, int] = {}
        try:
            for target in (3, 4):
                try:
                    saved[target] = os.dup(target)
                except OSError:
                    pass
            os.dup2(parent_to_chrome_r, 3)
            os.dup2(chrome_to_parent_w, 4)
            os.set_inheritable(3, True)
            os.set_inheritable(4, True)
        except Exception:
            for descriptor in (parent_to_chrome_r, parent_to_chrome_w, chrome_to_parent_r, chrome_to_parent_w):
                os.close(descriptor)
            for target, original in saved.items():
                os.dup2(original, target)
                os.close(original)
            self.close()
            raise
        command = [
            str(binary),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-translate",
            "--disable-component-update",
            "--disable-crash-reporter",
            "--no-default-browser-check",
            "--disable-features=DnsOverHttps,WebRTC",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--window-size=1280,800",
            f"--user-data-dir={self.profile}",
            "--remote-debugging-pipe",
            f"--proxy-server={self._proxy.endpoint}",
            "--proxy-bypass-list=<-loopback>",
            "--disable-dev-shm-usage",
            "about:blank",
        ]
        if any(arg == "--no-sandbox" or arg.startswith("--no-sandbox=") for arg in command):
            raise BrowserError("sandbox_refused")
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(3, 4),
                preexec_fn=_contain_child,
            )
        except Exception:
            for descriptor in (parent_to_chrome_r, parent_to_chrome_w, chrome_to_parent_r, chrome_to_parent_w, 3, 4):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            for target, original in saved.items():
                os.dup2(original, target)
                os.close(original)
            self.close()
            raise
        for descriptor in (parent_to_chrome_r, chrome_to_parent_w, 3, 4):
            if descriptor not in (parent_to_chrome_w, chrome_to_parent_r):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        for target, original in saved.items():
            os.dup2(original, target)
            os.close(original)
        self._cdp = CdpPipe(chrome_to_parent_r, parent_to_chrome_w)
        deadline = time.monotonic() + 20
        ready = False
        while time.monotonic() < deadline:
            self._assert_sandboxed()
            if self._process.poll() is not None:
                self.close()
                raise BrowserError("browser_exited")
            try:
                self._cdp.call("Browser.getVersion", {}, timeout=0.4)
                ready = True
                break
            except Exception:
                time.sleep(0.05)
        if not ready:
            self.close()
            raise BrowserError("browser_exited")
        try:
            self._cdp.call("Browser.setDownloadBehavior", {"behavior": "deny", "eventsEnabled": True})
            self._open_tab("about:blank")
        except Exception:
            self.close()
            raise
        self._write_state()
        self._record("start", "about:blank", "performed_unverified")

    def navigate(self, url: str, now: datetime | None = None) -> dict:
        self._require_grant("navigate", now)
        try:
            check_destination(url, self.grant.allow_loopback, resolver=self.resolver)
        except PolicyError as exc:
            self._record("navigate", url, "refused", detail=exc.code)
            raise BrowserError(exc.code) from exc
        error_text = ""
        transient = False
        for attempt in range(2):
            result = self._call("Page.navigate", {"url": url}, timeout=8)
            error_text = str(result.get("errorText") or "")
            transient = _transient_navigation_error(error_text)
            if not error_text or not transient or attempt == 1:
                break
            time.sleep(0.05)
        if error_text and not transient:
            self._record("navigate", url, "failed", detail="navigation_failed")
            raise BrowserError("navigation_failed")
        state = ""
        final = ""
        deadline = time.monotonic() + (8 if transient else 3)
        while time.monotonic() < deadline:
            ready = self._call("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
            located = self._call("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
            state = str(ready.get("result", {}).get("value") or "")
            final = str(located.get("result", {}).get("value") or "")
            if state in {"interactive", "complete"} and final:
                break
            time.sleep(0.05)
        text = self._page_text()
        matched = state in {"interactive", "complete"} and _same_url(url, final)
        completion = "performed_unverified" if matched else "failed"
        if matched:
            detail = ""
        elif "metadata_refused" in self.proxy_refusals:
            detail = "metadata_refused"
        elif self.proxy_refusals:
            detail = self.proxy_refusals[-1]
        elif error_text:
            detail = "navigation_failed"
        else:
            detail = "final_url_mismatch"
        record = self._record("navigate", url, completion, content=text["text"], detail=detail)
        if completion != "performed_unverified":
            raise BrowserError(detail or "navigation_failed")
        return record

    def read_text(self, now: datetime | None = None) -> dict:
        self._require_grant("read", now)
        return self._page_text()

    def element_snapshot(self, selector: str | None, now: datetime | None = None) -> dict:
        self._require_grant("read", now)
        if not selector:
            return {"present": False, "text": "", "value": ""}
        if not isinstance(selector, str) or _SELECTOR.fullmatch(selector) is None:
            raise BrowserError("selector_refused")
        raw = self._eval_value(
            "(() => { const el = document.querySelector("
            + json.dumps(selector)
            + "); if (!el) return {present: false, text: '', value: ''};"
            + " return {present: true, text: String(el.innerText || ''), value: String(el.value || '')}; })()"
        )
        if not isinstance(raw, dict):
            return {"present": False, "text": "", "value": ""}
        return {
            "present": bool(raw.get("present")),
            "text": str(raw.get("text") or ""),
            "value": str(raw.get("value") or ""),
        }

    def _page_text(self) -> dict:
        value = self._call("Runtime.evaluate", {"expression": "document.body ? document.body.innerText : ''", "returnByValue": True})
        text = str(value.get("result", {}).get("value") or "")
        return {"text": text, "untrusted": True, "authority": "page_content_not_authority"}

    def click(self, selector: str, now: datetime | None = None) -> dict:
        self._require_grant("click", now)
        self._pointer(selector, click=True)
        self._record("click", selector, "performed_unverified")
        return {"selector": selector, "completion": "performed_unverified"}

    def fill(self, selector: str, text: str, now: datetime | None = None) -> dict:
        self._require_grant("fill", now)
        if "\n" in text or len(text) > 512:
            raise BrowserError("fill_refused")
        self._pointer(selector, click=True)
        self._call("Input.insertText", {"text": text})
        observed = self._call(
            "Runtime.evaluate",
            {
                "expression": f"document.querySelector({json.dumps(selector)}).value",
                "returnByValue": True,
            },
        )
        matched = observed.get("result", {}).get("value") == text
        completion = "performed_unverified" if matched else "failed"
        self._record("fill", selector, completion, detail="" if matched else "value_mismatch")
        if not matched:
            raise BrowserError("fill_failed")
        return {"selector": selector, "completion": completion}

    def scroll(self, delta_y: int = 200, now: datetime | None = None) -> dict:
        self._require_grant("scroll", now)
        if not isinstance(delta_y, int) or abs(delta_y) > 2000:
            raise BrowserError("scroll_refused")
        before = self._eval_value("window.scrollY")
        if delta_y != 0:
            # Headless Chrome on this host ignores mouseWheel. The scroll
            # gesture is a real input event and moves the viewport.
            self._call(
                "Input.synthesizeScrollGesture",
                {"x": 200, "y": 200, "xDistance": 0, "yDistance": -delta_y},
            )
        after = self._eval_value("window.scrollY")
        moved = isinstance(before, (int, float)) and isinstance(after, (int, float)) and after != before
        completion = "performed_unverified" if moved or delta_y == 0 else "failed"
        self._record("scroll", str(delta_y), completion, detail="" if completion != "failed" else "scroll_unchanged")
        if completion == "failed":
            raise BrowserError("scroll_failed")
        return {"completion": completion}

    def screenshot(self, now: datetime | None = None) -> Path:
        self._require_grant("screenshot", now)
        if self._eval_value("Array.from(document.querySelectorAll('input[type=password]')).some(el => el.value.length > 0)") is True:
            self._record("screenshot", "", "refused", detail="credential_surface")
            raise BrowserError("screenshot_refused")
        payload = self._call("Page.captureScreenshot", {"format": "png"})
        raw = base64.b64decode(payload.get("data") or "")
        if not raw.startswith(b"\x89PNG"):
            self._record("screenshot", "", "failed", detail="screenshot_invalid")
            raise BrowserError("screenshot_failed")
        target = self.evidence_path.parent / f"screenshot-{len(self.evidence)}.png"
        fd = _open_leaf(target.parent, target.name, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            _write_all(fd, raw)
        except Exception:
            os.close(fd)
            target.unlink(missing_ok=True)
            raise
        os.close(fd)
        self._record("screenshot", target.name, "verified")
        return target

    def open_tab(self, url: str, now: datetime | None = None) -> str:
        self._require_grant("navigate", now)
        try:
            check_destination(url, self.grant.allow_loopback, resolver=self.resolver)
        except PolicyError as exc:
            self._record("tab", url, "refused", detail=exc.code)
            raise BrowserError(exc.code) from exc
        tab = self._open_tab(url)
        self._record("tab", url, "performed_unverified")
        return tab

    def tabs(self) -> tuple[str, ...]:
        return tuple(self._tabs)

    def accept_download(self, name: str, body: bytes, now: datetime | None = None) -> Path:
        self._require_grant("download", now)
        safe = quarantine_name(name)
        if not isinstance(body, bytes) or len(body) > 1_000_000:
            raise BrowserError("download_refused")
        root = self.quarantine.resolve()
        target = (self.quarantine / safe).resolve()
        if os.path.commonpath((root, target)) != str(root):
            raise BrowserError("download_refused")
        if target.exists() or target.is_symlink():
            raise BrowserError("download_refused")
        flags = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY
        try:
            fd = os.open(target, flags, 0o600)
        except OSError as exc:
            raise BrowserError("download_refused") from exc
        try:
            _write_all(fd, body)
        except Exception:
            os.close(fd)
            target.unlink(missing_ok=True)
            raise
        os.close(fd)
        self._record("download", safe, "verified")
        return target

    def resume(self, now: datetime | None = None) -> None:
        """Restart this user and mission only when the saved state matches."""
        if self._process is not None and self._process.poll() is None:
            raise BrowserError("browser_already_started")
        try:
            info = self.state_path.lstat()
        except OSError as exc:
            raise BrowserError("resume_refused") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise BrowserError("resume_refused")
        self._validate_state()
        self._process = None
        self._closed = False
        self.start(now)

    def refuse_unsupported(self, kind: str) -> None:
        if kind not in {"captcha", "authentication_challenge"}:
            raise BrowserError("action_not_granted")
        self._record(kind, "", "refused", detail="unsupported_challenge")
        raise BrowserError("unsupported_challenge")

    def cancel(self) -> str:
        self._record("cancel", "", "verified")
        self.close()
        return "cancelled"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._cdp is not None:
            try:
                self._cdp.call("Browser.close", {}, timeout=2)
            except Exception:
                pass
            self._cdp.close()
            self._cdp = None
        if self._process is not None:
            pid = self._process.pid
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            for signal in (15, 9):
                remaining = _profile_processes(self.profile)
                if not remaining and self._process.poll() is not None:
                    break
                try:
                    os.killpg(pid, signal)
                except (ProcessLookupError, PermissionError):
                    pass
                for child in remaining:
                    try:
                        os.kill(child, signal)
                    except (ProcessLookupError, PermissionError):
                        pass
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    continue
        if self._proxy is not None:
            self._proxy.close()
            self._proxy = None

    def _eval_value(self, expression: str):
        value = self._call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return value.get("result", {}).get("value")

    def _prepare_mission_dirs(self) -> None:
        root = self.root.resolve()
        mission = self.home
        if any(path.is_symlink() for path in (mission, self.profile, self.quarantine, self.evidence_path, self.state_path)):
            raise BrowserError("path_refused")
        mission.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        mission.mkdir(mode=0o700, exist_ok=True)
        resolved = mission.resolve()
        if os.path.commonpath((str(root), str(resolved))) != str(root):
            raise BrowserError("path_refused")

    def _write_state(self) -> None:
        payload = {
            "schema": _SESSION_SCHEMA,
            "user_id": self.grant.user_id,
            "mission_id": self.grant.mission_id,
        }
        encoded = json.dumps(payload, sort_keys=True).encode()
        fd = _open_leaf(self.state_path.parent, self.state_path.name, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
        try:
            _write_all(fd, encoded)
        finally:
            os.close(fd)

    def _validate_state(self) -> None:
        try:
            payload = json.loads(_read_leaf(self.state_path).decode())
        except (OSError, UnicodeError, json.JSONDecodeError, BrowserError) as exc:
            raise BrowserError("resume_refused") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != _SESSION_SCHEMA
            or payload.get("user_id") != self.grant.user_id
            or payload.get("mission_id") != self.grant.mission_id
        ):
            raise BrowserError("resume_refused")

    def _open_tab(self, url: str) -> str:
        if len(self._tabs) >= _MAX_TABS:
            raise BrowserError("tab_limit")
        created = self._cdp.call("Target.createTarget", {"url": url})
        attached = self._cdp.call("Target.attachToTarget", {"targetId": created["targetId"], "flatten": True})
        session = attached["sessionId"]
        self._tabs[created["targetId"]] = session
        self._active = session
        self._active_target = created["targetId"]
        self._cdp.call("Target.activateTarget", {"targetId": created["targetId"]})
        self._call("Page.enable", {})
        self._call("Runtime.enable", {})
        self._call("DOM.enable", {})
        self._call("Page.setDownloadBehavior", {"behavior": "deny"})
        return created["targetId"]

    def _pointer(self, selector: str, click: bool) -> None:
        if not isinstance(selector, str) or _SELECTOR.fullmatch(selector) is None:
            raise BrowserError("selector_refused")
        document = self._call("DOM.getDocument", {"depth": -1, "pierce": True})
        found = self._call("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": selector})
        if not found.get("nodeId"):
            raise BrowserError("element_absent")
        box = None
        for _ in range(10):
            try:
                box = self._call("DOM.getBoxModel", {"nodeId": found["nodeId"]})
                break
            except BrowserError:
                time.sleep(0.05)
        if box is None:
            raise BrowserError("element_absent")
        content = box["model"]["content"]
        x = (content[0] + content[2]) / 2
        y = (content[1] + content[5]) / 2
        if click:
            for kind in ("mousePressed", "mouseReleased"):
                self._call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    def _call(self, method: str, params: dict, timeout: float = 10) -> dict:
        if self._cdp is None or self._process is None or self._process.poll() is not None:
            raise BrowserError("browser_dead")
        self._assert_sandboxed()
        try:
            return self._cdp.call(method, params, self._active, timeout=timeout)
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserError("browser_dead") from exc

    def _assert_sandboxed(self) -> None:
        if self._process is None:
            raise BrowserError("browser_dead")
        command = process_command(self._process.pid)
        if not command:
            if self._process.poll() is not None:
                raise BrowserError("browser_dead")
            self.close()
            raise BrowserError("sandbox_refused")
        if b"--no-sandbox" in command:
            self.close()
            raise BrowserError("sandbox_refused")

    def _require_grant(self, action: str, now: datetime | None) -> None:
        if self._closed:
            raise BrowserError("browser_closed")
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None:
            raise BrowserError("naive_clock")
        self.grant.permits(action, clock)

    def _record(self, action: str, subject: str, completion: str, content: str = "", detail: str = "") -> dict:
        record = {
            "action": action,
            "subject_sha256": hashlib.sha256(subject.encode()).hexdigest(),
            "completion": completion,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest() if content else None,
            "detail": detail,
            "user_id": self.grant.user_id,
            "mission_id": self.grant.mission_id,
            "untrusted_page": True,
        }
        self.evidence.append(record)
        fd = _open_leaf(self.evidence_path.parent, self.evidence_path.name, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
        try:
            _write_all(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
        finally:
            os.close(fd)
        return record

    @property
    def proxy_refusals(self) -> tuple[str, ...]:
        if self._proxy is None:
            return ()
        return tuple(self._proxy.refusals)


def _transient_navigation_error(error_text: str) -> bool:
    """Chrome sometimes aborts a load that then commits. Only those codes are retried."""
    return error_text in {
        "net::ERR_ABORTED",
        "net::ERR_CONNECTION_CLOSED",
        "net::ERR_CONNECTION_REFUSED",
        "net::ERR_CONNECTION_RESET",
        "net::ERR_EMPTY_RESPONSE",
        "net::ERR_NETWORK_CHANGED",
        "net::ERR_PROXY_CONNECTION_FAILED",
        "net::ERR_SOCKET_NOT_CONNECTED",
        "net::ERR_TIMED_OUT",
    }


def _same_url(requested: str, final: str) -> bool:
    left = urlsplit(requested)
    right = urlsplit(final)
    left_port = left.port or (443 if left.scheme == "https" else 80)
    right_port = right.port or (443 if right.scheme == "https" else 80)
    return (
        left.scheme == right.scheme
        and (left.hostname or "").casefold() == (right.hostname or "").casefold()
        and left_port == right_port
        and (left.path or "/") == (right.path or "/")
        and left.query == right.query
    )


def _contain_child() -> None:
    nofile = 1024
    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 45))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FILE_SIZE_CAP, _FILE_SIZE_CAP))
    # RLIMIT_AS aborts this Chrome build (signal 5) even at tens of GiB.
    # A memory cgroup is the containment that would work, and this process
    # cannot create one. Do not pretend an address-space rlimit is a cap.


def process_command(pid: int) -> bytes:
    """Command line on Linux via /proc, and on other POSIX hosts via ps."""
    proc = Path(f"/proc/{pid}/cmdline")
    if proc.exists():
        try:
            return proc.read_bytes()
        except OSError:
            return b""
    if not Path("/proc").is_dir():
        try:
            return subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            return b""
    return b""


def listening_ports(pid: int) -> list[int]:
    """Local TCP ports in LISTEN state owned by this process. Empty without /proc."""
    fd_dir = Path(f"/proc/{pid}/fd")
    if not fd_dir.is_dir():
        return []
    inodes = set()
    for entry in fd_dir.iterdir():
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target[len("socket:[") : -1])
    ports: list[int] = []
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = table.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10:
                continue
            if fields[9] not in inodes or fields[3] != "0A":
                continue
            ports.append(int(fields[1].rsplit(":", 1)[1], 16))
    return ports


def _profile_processes(profile: Path) -> list[int]:
    needle = str(profile).encode()
    found = []
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                command = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            if needle in command and b"chrome" in command:
                found.append(int(entry.name))
        return found
    try:
        listing = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return []
    for line in listing.splitlines():
        text = line.strip()
        if not text:
            continue
        pid_text, separator, command = text.partition(b" ")
        if separator and needle in command and b"chrome" in command and pid_text.isdigit():
            found.append(int(pid_text))
    return found


def _open_leaf(directory: Path, name: str, flags: int) -> int:
    if directory.is_symlink():
        raise BrowserError("evidence_refused")
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise BrowserError("evidence_refused") from exc
    try:
        return os.open(name, flags | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    except OSError as exc:
        raise BrowserError("evidence_refused") from exc
    finally:
        os.close(directory_fd)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise BrowserError("download_refused")
        view = view[written:]
    os.fsync(descriptor)


def _read_leaf(path: Path) -> bytes:
    descriptor = _open_leaf(path.parent, path.name, os.O_RDONLY)
    try:
        chunks = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            if sum(len(item) for item in chunks) > 1_000_000:
                raise BrowserError("resume_refused")
    finally:
        os.close(descriptor)


def remove_profile(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
