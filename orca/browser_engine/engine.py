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
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from orca.browser_engine.cdp import CdpClient
from orca.browser_engine.policy import PolicyError, check_destination, validate_allowlist
from orca.browser_engine.proxy import FilteringProxy

_MAX_GRANT_SECONDS = 120
_MAX_TABS = 4
_ACTIONS = frozenset({"navigate", "click", "fill", "scroll", "screenshot", "read", "download"})
_SELECTOR = re.compile(r"^#[A-Za-z][A-Za-z0-9_-]{0,62}$")
_SESSION_SCHEMA = "orneur-browser-session/1"
_NO_PROXY = urllib.request.ProxyHandler({})


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
    )


def chrome_binary() -> Path:
    configured = os.environ.get("ORNEUR_CHROME_BINARY", "/opt/google/chrome/chrome")
    path = Path(configured)
    if path.is_symlink() or not path.is_file():
        raise BrowserError("chrome_binary_refused")
    sample = path.read_bytes()[:256]
    if sample.startswith(b"#!") or b"--no-sandbox" in sample:
        raise BrowserError("sandbox_refused")
    return path


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
        self._cdp: CdpClient | None = None
        self._tabs: dict[str, str] = {}
        self._active: str | None = None
        self._active_target: str | None = None
        self._closed = False
        self.profile = self.root / grant.user_id / grant.mission_id / "profile"
        self.quarantine = self.root / grant.user_id / grant.mission_id / "downloads"
        self.evidence_path = self.root / grant.user_id / grant.mission_id / "evidence.jsonl"
        self.state_path = self.root / grant.user_id / grant.mission_id / "state.json"

    def start(self, now: datetime | None = None) -> None:
        self._require_grant("navigate", now)
        if self._process is not None:
            raise BrowserError("browser_already_started")
        binary = chrome_binary()
        self.profile.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.state_path.exists():
            self._validate_state()
        elif self.profile.exists():
            raise BrowserError("resume_refused")
        self.profile.mkdir(mode=0o700, exist_ok=True)
        self.quarantine.mkdir(mode=0o700, exist_ok=True)
        self._proxy = FilteringProxy(self.grant.allow_loopback, self.resolver)
        self._proxy.start()
        port = _free_port()
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
            "--no-default-browser-check",
            "--disable-features=DnsOverHttps,WebRTC",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--window-size=1280,800",
            f"--user-data-dir={self.profile}",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--proxy-server={self._proxy.endpoint}",
            "--proxy-bypass-list=<-loopback>",
            "--disable-dev-shm-usage",
            "about:blank",
        ]
        if any(arg == "--no-sandbox" or arg.startswith("--no-sandbox=") for arg in command):
            raise BrowserError("sandbox_refused")
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=_contain_child,
        )
        deadline = time.monotonic() + 8
        version = None
        opener = urllib.request.build_opener(_NO_PROXY)
        while time.monotonic() < deadline:
            self._assert_sandboxed()
            try:
                with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=0.4) as response:
                    version = json.load(response)
                    break
            except Exception:
                if self._process.poll() is not None:
                    self.close()
                    raise BrowserError("browser_exited")
                time.sleep(0.05)
        if version is None:
            self.close()
            raise BrowserError("browser_exited")
        try:
            self._cdp = CdpClient(version["webSocketDebuggerUrl"])
            try:
                self._cdp.call(
                    "Browser.setDownloadBehavior",
                    {
                        "behavior": "allow",
                        "downloadPath": str(self.quarantine),
                        "eventsEnabled": True,
                    },
                )
            except Exception:
                pass
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
        result = self._call("Page.navigate", {"url": url}, timeout=8)
        if result.get("errorText"):
            self._record("navigate", url, "failed", detail="navigation_failed")
            raise BrowserError("navigation_failed")
        state = ""
        final = ""
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            ready = self._call("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
            located = self._call("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
            state = str(ready.get("result", {}).get("value") or "")
            final = str(located.get("result", {}).get("value") or "")
            if state in {"interactive", "complete"} and final:
                break
            time.sleep(0.05)
        text = self.read_text(now=now, granted=True)
        matched = state in {"interactive", "complete"} and _same_url(url, final)
        completion = "performed_unverified" if matched else "failed"
        if matched:
            detail = ""
        elif "metadata_refused" in self.proxy_refusals:
            detail = "metadata_refused"
        elif self.proxy_refusals:
            detail = self.proxy_refusals[-1]
        else:
            detail = "final_url_mismatch"
        record = self._record("navigate", url, completion, content=text["text"], detail=detail)
        if completion != "performed_unverified":
            raise BrowserError(detail or "navigation_failed")
        return record

    def read_text(self, now: datetime | None = None, granted: bool = False) -> dict:
        if not granted:
            self._require_grant("read", now)
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
        target.write_bytes(raw)
        os.chmod(target, 0o600)
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
        fd = os.open(target, flags, 0o600)
        try:
            os.write(fd, body)
        finally:
            os.close(fd)
        self._record("download", safe, "verified")
        return target

    def resume(self, now: datetime | None = None) -> None:
        """Restart this user and mission only when the saved state matches."""
        if self._process is not None and self._process.poll() is None:
            raise BrowserError("browser_already_started")
        if not self.state_path.is_file():
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
                if not remaining:
                    break
                try:
                    os.killpg(pid, signal)
                except ProcessLookupError:
                    pass
                for child in remaining:
                    try:
                        os.kill(child, signal)
                    except ProcessLookupError:
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

    def _write_state(self) -> None:
        payload = {
            "schema": _SESSION_SCHEMA,
            "user_id": self.grant.user_id,
            "mission_id": self.grant.mission_id,
        }
        self.state_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(self.state_path, 0o600)

    def _validate_state(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
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
        try:
            command = Path(f"/proc/{self._process.pid}/cmdline").read_bytes().replace(b"\x00", b" ")
        except FileNotFoundError as exc:
            raise BrowserError("browser_dead") from exc
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
        self.evidence_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with self.evidence_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        os.chmod(self.evidence_path, 0o600)
        return record

    @property
    def proxy_refusals(self) -> tuple[str, ...]:
        if self._proxy is None:
            return ()
        return tuple(self._proxy.refusals)


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


def _profile_processes(profile: Path) -> list[int]:
    needle = str(profile).encode()
    found = []
    proc = Path("/proc")
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


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def remove_profile(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
