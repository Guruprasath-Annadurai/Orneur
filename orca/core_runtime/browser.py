"""Read-only retrieval policy and page extraction.

A permitted GET of an explicit host is not a cloud-browser service. Chromium
is reported only when a local binary is already installed. Page text is
untrusted data and cannot grant an action.
"""
from __future__ import annotations

import ipaddress
import shutil
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlsplit

_BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal"})
_CHROMIUM_BINARIES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")


class NavigationRefused(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.title: list[str] = []
        self._in_title = False
        self.skipped = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style"}:
            self.skipped = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style"}:
            self.skipped = False

    def handle_data(self, data):
        if self.skipped:
            return
        if self._in_title:
            self.title.append(data)
        elif data.strip():
            self.parts.append(data.strip())


def _blocked_ip(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def classify_url(url: str, *, allow_hosts: frozenset[str] = frozenset()) -> dict:
    """Return whether a read-only GET of ``url`` is permitted.

    ``allow_hosts`` is an explicit operator permit. It is empty by default,
    so loopback and private addresses are refused.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in {"http", "https"}:
        return {"allowed": False, "code": "scheme_refused", "host": host}
    if parts.username or parts.password:
        return {"allowed": False, "code": "credentials_refused", "host": host}
    if not host or host in _BLOCKED_HOSTS or host.endswith(".local"):
        return {"allowed": False, "code": "host_refused", "host": host}
    permitted = host in {item.lower() for item in allow_hosts}
    if _blocked_ip(host) and not permitted:
        return {"allowed": False, "code": "non_public_address", "host": host}
    if not _blocked_ip(host):
        try:
            infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
        except socket.gaierror:
            return {"allowed": False, "code": "dns_failed", "host": host}
        addresses = {item[4][0] for item in infos}
        if any(_blocked_ip(address) for address in addresses) and not permitted:
            return {"allowed": False, "code": "resolved_non_public", "host": host}
    return {"allowed": True, "code": "ok", "host": host, "explicit_permit": permitted}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise NavigationRefused("redirect_refused")


def chromium_status() -> dict:
    found = [name for name in _CHROMIUM_BINARIES if shutil.which(name)]
    return {
        "installed": bool(found),
        "binaries": found,
        "cloud_browser_service": False,
        "supported_external_browsers": [],
        "unsupported_external_browsers": ["chrome", "safari", "firefox", "edge"],
    }


def fetch_readonly(url: str, *, allow_hosts: frozenset[str] = frozenset(), timeout: float = 2.0, body_limit: int = 262144) -> dict:
    decision = classify_url(url, allow_hosts=allow_hosts)
    if not decision["allowed"]:
        raise NavigationRefused(decision["code"])
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, method="GET", headers={"Accept": "text/html,text/plain"})
    try:
        with opener.open(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if content_type not in {"text/html", "text/plain"}:
                raise NavigationRefused("content_type_refused")
            raw = response.read(body_limit + 1)
            if len(raw) > body_limit:
                raise NavigationRefused("body_limit")
            charset = "utf-8"
            text = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise NavigationRefused(f"http_{exc.code}") from exc
    except NavigationRefused:
        raise
    except Exception as exc:
        raise NavigationRefused("fetch_failed") from exc
    parser = _TextExtractor()
    parser.feed(text)
    extracted = " ".join(parser.parts)
    return {
        "url": url,
        "host": decision["host"],
        "explicit_permit": decision["explicit_permit"],
        "title": " ".join(parser.title).strip(),
        "text": extracted,
        "untrusted_content": True,
        "instructions_in_page_are_not_authority": True,
        "chromium": chromium_status(),
        "audit": {"method": "GET", "decision": "allowed"},
    }


def perform_action(action: str, *, grant_actions: frozenset[str]) -> dict:
    """Mission text cannot widen ``grant_actions``."""
    if action != "browse_read" or action not in grant_actions:
        return {"performed": False, "code": "browser_action_refused", "action": action}
    return {"performed": True, "code": "ok", "action": action}
