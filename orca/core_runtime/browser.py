"""Read-only retrieval policy and page extraction.

Name resolution is pinned to one address and checked again before connect.
A change, a non-public answer, or a proxy is not followed. A permitted GET
is not a cloud-browser service. Page text is untrusted data and cannot
grant an action.
"""
from __future__ import annotations

import http.client
import ipaddress
import shutil
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit

_BLOCKED_HOSTS = frozenset({"localhost", "metadata", "metadata.google.internal"})
_CHROMIUM_BINARIES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_MAX_URL = 2048


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


def _ip(text: str):
    try:
        return ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None


def _blocked_ip(text: str) -> bool:
    address = _ip(text)
    if address is None:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    site_local = getattr(address, "is_site_local", False)
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or site_local
    )


def _same_ip(left: str, right: str) -> bool:
    first = _ip(left)
    second = _ip(right)
    if first is None or second is None:
        return False
    if getattr(first, "ipv4_mapped", None) is not None:
        first = first.ipv4_mapped
    if getattr(second, "ipv4_mapped", None) is not None:
        second = second.ipv4_mapped
    return first == second


def _resolve(host: str, port: int) -> frozenset[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    found = [item[4][0] for item in infos if item[4]]
    if not found:
        raise socket.gaierror(host)
    return frozenset(found)


def _pin(addresses: frozenset[str]) -> str:
    return sorted(addresses, key=lambda item: (":" in item, item))[0]


def classify_url(url: str, *, allow_hosts: frozenset[str] = frozenset()) -> dict:
    """Return whether a read-only GET of ``url`` is permitted.

    ``allow_hosts`` is an explicit operator permit. It is empty by default,
    so loopback and private addresses are refused. The returned addresses
    are the set that a later fetch must still observe before it connects.
    """
    if not isinstance(url, str) or len(url) > _MAX_URL:
        return {"allowed": False, "code": "url_refused", "host": "", "addresses": []}
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if parts.scheme not in {"http", "https"}:
        return {"allowed": False, "code": "scheme_refused", "host": host, "addresses": []}
    if parts.username or parts.password:
        return {"allowed": False, "code": "credentials_refused", "host": host, "addresses": []}
    if port < 1 or port > 65535:
        return {"allowed": False, "code": "port_refused", "host": host, "addresses": []}
    if not host or host in _BLOCKED_HOSTS or host.endswith(".local"):
        return {"allowed": False, "code": "host_refused", "host": host, "addresses": []}
    permitted = host in {item.lower() for item in allow_hosts}
    if _blocked_ip(host) and not permitted:
        return {"allowed": False, "code": "non_public_address", "host": host, "addresses": []}
    try:
        addresses = _resolve(host, port)
    except socket.gaierror:
        return {"allowed": False, "code": "dns_failed", "host": host, "addresses": []}
    if any(_blocked_ip(address) for address in addresses) and not permitted:
        return {"allowed": False, "code": "resolved_non_public", "host": host, "addresses": sorted(addresses)}
    return {
        "allowed": True,
        "code": "ok",
        "host": host,
        "explicit_permit": permitted,
        "addresses": sorted(addresses),
        "port": port,
    }


def chromium_status() -> dict:
    found = [name for name in _CHROMIUM_BINARIES if shutil.which(name)]
    return {
        "installed": bool(found),
        "binaries": found,
        "cloud_browser_service": False,
        "production_cloud_browser": False,
        "supported_external_browsers": [],
        "unsupported_external_browsers": ["chrome", "safari", "firefox", "edge"],
    }


def _host_header(host: str, port: int, scheme: str) -> str:
    default = 443 if scheme == "https" else 80
    literal = _ip(host) is not None and isinstance(_ip(host), ipaddress.IPv6Address)
    name = f"[{host}]" if literal else host
    if port == default:
        return name
    return f"{name}:{port}"


def _read_response(sock: socket.socket, *, body_limit: int) -> tuple[int, str, bytes]:
    response = http.client.HTTPResponse(sock)
    try:
        response.begin()
        if response.status in _REDIRECTS:
            raise NavigationRefused("redirect_refused")
        if response.status != 200:
            raise NavigationRefused(f"http_{response.status}")
        content_type = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if content_type not in {"text/html", "text/plain"}:
            raise NavigationRefused("content_type_refused")
        raw = response.read(body_limit + 1)
        if len(raw) > body_limit:
            raise NavigationRefused("body_limit")
        return response.status, content_type, raw
    finally:
        response.close()


def fetch_readonly(url: str, *, allow_hosts: frozenset[str] = frozenset(), timeout: float = 2.0, body_limit: int = 262144) -> dict:
    """GET one pinned address. Proxy environment variables are ignored.

    The second lookup must equal the classified set. A redirect is refused
    and is not fetched. This is not a production cloud browser.
    """
    decision = classify_url(url, allow_hosts=allow_hosts)
    if not decision["allowed"]:
        raise NavigationRefused(decision["code"])
    parts = urlsplit(url)
    host = decision["host"]
    port = int(decision["port"])
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    if any(char in path for char in "\r\n "):
        raise NavigationRefused("path_refused")
    try:
        again = _resolve(host, port)
    except socket.gaierror as exc:
        raise NavigationRefused("dns_failed") from exc
    pinned_set = frozenset(decision["addresses"])
    if again != pinned_set:
        raise NavigationRefused("dns_rebinding")
    if any(_blocked_ip(address) for address in again) and not decision["explicit_permit"]:
        raise NavigationRefused("resolved_non_public")
    pinned = _pin(again)
    sock = None
    try:
        # Direct connect to the pinned address. urllib and env proxies are not used.
        sock = socket.create_connection((pinned, port), timeout=timeout)
        peer = sock.getpeername()[0]
        if not _same_ip(peer, pinned):
            raise NavigationRefused("host_mismatch")
        if parts.scheme == "https":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)
            peer = sock.getpeername()[0]
            if not _same_ip(peer, pinned):
                raise NavigationRefused("host_mismatch")
        header = _host_header(host, port, parts.scheme)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {header}\r\n"
            "Accept: text/html,text/plain\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        sock.sendall(request)
        _status, _content_type, raw = _read_response(sock, body_limit=body_limit)
    except NavigationRefused:
        raise
    except (TimeoutError, socket.timeout) as exc:
        raise NavigationRefused("fetch_failed") from exc
    except (OSError, http.client.HTTPException, ssl.SSLError, UnicodeError) as exc:
        raise NavigationRefused("fetch_failed") from exc
    finally:
        if sock is not None:
            sock.close()
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    extracted = " ".join(parser.parts)
    return {
        "url": url,
        "host": host,
        "pinned_address": pinned,
        "explicit_permit": decision["explicit_permit"],
        "title": " ".join(parser.title).strip(),
        "text": extracted,
        "untrusted_content": True,
        "instructions_in_page_are_not_authority": True,
        "production_cloud_browser": False,
        "proxy_ignored": True,
        "chromium": chromium_status(),
        "audit": {"method": "GET", "decision": "allowed", "pinned_address": pinned},
    }


def perform_action(action: str, *, grant_actions: frozenset[str]) -> dict:
    """A grant does not perform an external browser action by itself."""
    if action != "browse_read" or action not in grant_actions:
        return {
            "performed": False,
            "authorized": False,
            "external_action": False,
            "production_cloud_browser": False,
            "code": "browser_action_refused",
            "action": action,
        }
    return {
        "performed": False,
        "authorized": True,
        "external_action": False,
        "production_cloud_browser": False,
        "code": "authorized_not_performed",
        "action": action,
    }
