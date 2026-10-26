"""Network policy for the browser engine.

An allowlist entry may name only a loopback address. Hostnames, private
networks, link-local metadata addresses, and a resolution that changes
before connect are refused.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_METADATA_HOSTS = frozenset({
    "metadata",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "instance-data.ec2.internal",
})
_LINK_LOCAL = ipaddress.ip_network("169.254.0.0/16")
_EC2_IPV6 = ipaddress.ip_address("fd00:ec2::254")
_MAX_URL = 2048
# Python's is_private / is_reserved miss carrier-grade NAT and treat some
# documentation and unique-local ranges inconsistently across versions.
_EXTRA_BLOCKED = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fec0::/10"),
    ipaddress.ip_network("2001:db8::/32"),
)


class PolicyError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def page_content_not_authority(text: object) -> str:
    """Text from a page cannot create a grant or change a user."""
    del text
    return "page_content_not_authority"


def _unwrap(address: ipaddress.IPv4Address | ipaddress.IPv6Address):
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped if mapped is not None else address


def _parse_ip(text: str):
    try:
        return _unwrap(ipaddress.ip_address(text.split("%", 1)[0]))
    except ValueError:
        return None


def metadata_address(text: str) -> bool:
    address = _parse_ip(text)
    if address is None:
        return False
    if address.version == 4 and address in _LINK_LOCAL:
        return True
    return address == _EC2_IPV6


def blocked_address(text: str) -> bool:
    address = _parse_ip(text)
    if address is None:
        return False
    site_local = getattr(address, "is_site_local", False)
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or site_local
        or metadata_address(text)
        or any(address in network for network in _EXTRA_BLOCKED)
    )


def _loopback(text: str) -> bool:
    address = _parse_ip(text)
    return bool(address is not None and address.is_loopback and not metadata_address(text))


def _split_host_port(entry: str) -> tuple[str, str]:
    """Split a host or host:port. A port-specific entry does not allow other ports."""
    if entry.startswith("["):
        end = entry.find("]")
        if end < 1:
            raise PolicyError("allowlist_refused")
        host = entry[1:end]
        rest = entry[end + 1 :]
        if rest == "":
            return host, ""
        if not rest.startswith(":") or not rest[1:].isdigit():
            raise PolicyError("allowlist_refused")
        return host, rest[1:]
    if _parse_ip(entry) is not None:
        return entry, ""
    host, separator, port = entry.rpartition(":")
    if separator and port.isdigit() and host and _parse_ip(host) is not None:
        return host, port
    if separator:
        raise PolicyError("allowlist_refused")
    return entry, ""


def validate_allowlist(entries: tuple[str, ...] | list[str]) -> frozenset[str]:
    """Allow only a loopback IP literal, optionally with one port.

    ``127.0.0.1:9`` allows that endpoint only. ``127.0.0.1`` allows every
    port on that address. Hostnames are refused.
    """
    allowed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str) or not entry or "://" in entry or "@" in entry:
            raise PolicyError("allowlist_refused")
        host, port = _split_host_port(entry)
        if not _loopback(host):
            raise PolicyError("allowlist_refused")
        literal = _parse_ip(host)
        if literal is None:
            raise PolicyError("allowlist_refused")
        canonical = str(literal)
        if port:
            number = int(port)
            if number < 1 or number > 65535:
                raise PolicyError("allowlist_refused")
            allowed.add(f"{canonical}:{number}")
        else:
            allowed.add(canonical)
    return frozenset(allowed)


def resolve_all(host: str, resolver=None) -> tuple[str, ...]:
    if resolver is not None:
        return tuple(resolver(host))
    literal = _parse_ip(host)
    if literal is not None:
        return (str(literal),)
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PolicyError("name_resolution_refused") from exc
    addresses = []
    for info in infos:
        addresses.append(str(_unwrap(ipaddress.ip_address(info[4][0]))))
    if not addresses:
        raise PolicyError("name_resolution_refused")
    return tuple(dict.fromkeys(addresses))


def check_destination(url: str, allow_loopback: frozenset[str], *, resolver=None) -> tuple[str, ...]:
    """Return the pinned addresses for one navigation or proxy hop."""
    if not isinstance(url, str) or len(url) > _MAX_URL:
        raise PolicyError("url_refused")
    try:
        parts = urlsplit(url)
        explicit_port = parts.port
    except ValueError as exc:
        raise PolicyError("url_refused") from exc
    if parts.username or parts.password:
        raise PolicyError("credentials_in_url_refused")
    scheme = parts.scheme.casefold()
    host = (parts.hostname or "").casefold().rstrip(".")
    literal = _parse_ip(host)
    if literal is not None:
        host = str(literal)
    if scheme not in {"http", "https"} or not host:
        raise PolicyError("scheme_refused")
    if host in _METADATA_HOSTS or metadata_address(host):
        raise PolicyError("metadata_refused")
    port = explicit_port or (443 if scheme == "https" else 80)
    if port < 1 or port > 65535:
        raise PolicyError("url_refused")
    endpoint = f"{host}:{port}"
    loopback_literal = _loopback(host)
    allow_hit = endpoint in allow_loopback or host in allow_loopback
    if loopback_literal or host in {"localhost"}:
        if not allow_hit or host in {"localhost"}:
            raise PolicyError("loopback_refused")
        if scheme != "http":
            raise PolicyError("scheme_refused")
        return (host,)
    first = resolve_all(host, resolver)
    second = resolve_all(host, resolver)
    if set(first) != set(second):
        raise PolicyError("dns_rebinding_refused")
    for address in first:
        if metadata_address(address):
            raise PolicyError("metadata_refused")
        if blocked_address(address):
            raise PolicyError("private_network_refused")
    if scheme != "https":
        raise PolicyError("scheme_refused")
    return first
