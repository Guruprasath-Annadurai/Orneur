"""Supplementary privacy patterns that ``orca.serve.dlp`` does not cover (international phone numbers, JWTs, Slack tokens, IPv4 addresses,
checksum-valid IBANs, credentials embedded in URLs). Counts per category only; the matched value is never returned. Pattern floor, not ceiling."""
from __future__ import annotations

import re

_INTL_PHONE = re.compile(r"(?<![\w+])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?!\d)")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_SLACK = re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")
_URL_CRED = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")
_IPV4 = re.compile(r"(?<![\w.])((?:\d{1,3})\.(?:\d{1,3})\.(?:\d{1,3})\.(?:\d{1,3}))(?![\w.]*\w)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")


def _iban_ok(s: str) -> bool:
    r = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in r)) % 97 == 1


def _ipv4_ok(s: str) -> bool:
    parts = s.split(".")
    return all(p == str(int(p)) and int(p) <= 255 for p in parts)


def scan(text: str) -> dict:
    """Return {category: count}; categories are prefixed ``secret:`` or ``pii:``."""
    out = {
        "pii:intl_phone": len(_INTL_PHONE.findall(text)),
        "secret:jwt": len(_JWT.findall(text)),
        "secret:slack_token": len(_SLACK.findall(text)),
        "secret:url_credentials": len(_URL_CRED.findall(text)),
        "pii:ipv4": sum(1 for m in _IPV4.findall(text) if _ipv4_ok(m)),
        "pii:iban": sum(1 for m in _IBAN.findall(text) if _iban_ok(m)),
    }
    return {k: v for k, v in out.items() if v}
