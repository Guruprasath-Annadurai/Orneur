"""
IP-based rate limiting — the floor that applies regardless of auth status.

Real gaps this closes:
  - /api/chat and /api/stream only checked quota `if user:` — anonymous
    requests had ZERO limit. Every unauthenticated request burned real
    inference time for free, unbounded.
  - /api/code/run (spawns a subprocess per request) had no limit at all,
    authenticated or not.
  - /api/auth/signup, /login, /forgot-password had no brute-force or
    spam-account protection.

Fixed-window counter, dual backend:
  - Redis (ORCA_REDIS_URL set): INCR + EXPIRE on a window-bucketed key —
    correct across multiple API instances, since all of them share the same
    counter.
  - In-process dict + lock (default): correct for a single instance, which
    is what most Orca deployments actually are. Resets on restart — accepted
    tradeoff, same as every other in-memory fallback in this codebase.

IP extraction respects X-Forwarded-For when present — trusting only
request.client.host breaks behind any reverse proxy/load balancer (Fly.io,
nginx, etc.), since every request would show the proxy's IP, making the
"per-IP" limit actually a single global limit shared by all real clients.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from orca.config import orneur_env
from orca.serve import session_store  # reuses the same Redis client/connection

_local_lock = threading.Lock()
_local_counters: dict[str, tuple[int, int]] = {}  # key -> (window_start, count)


def _trusted_proxy_networks() -> list:
    """`ORNEUR_TRUSTED_PROXY_CIDRS`: comma-separated CIDRs (e.g. the
    private network a Cloudflare Tunnel sidecar connects from). Empty/
    unset (the default) preserves this module's original, unconditional
    "trust X-Forwarded-For whenever present" behavior -- unchanged for
    every existing self-hosted/local/private-staging deployment. Set
    this before exposing the app through any edge/proxy you don't fully
    control the network path to (Phase 14C spec Step 8): once set, XFF
    is trusted ONLY when the DIRECT TCP peer is itself one of these
    networks, so an attacker who can reach the app directly (bypassing
    the intended proxy) cannot simply forge X-Forwarded-For to spoof an
    arbitrary source IP for rate-limit/audit-attribution purposes."""
    raw = orneur_env("TRUSTED_PROXY_CIDRS", "").strip()
    if not raw:
        return []
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue  # malformed entry -- ignored, never crashes request handling
    return networks


def get_client_ip(request: Request) -> str:
    """First IP in X-Forwarded-For if present (reverse-proxy correct),
    else the direct peer -- UNLESS `ORNEUR_TRUSTED_PROXY_CIDRS` is set,
    in which case X-Forwarded-For is trusted only when the direct peer
    (`request.client.host`) is itself inside one of those networks
    (see `_trusted_proxy_networks()`'s docstring). Never raises on a
    malformed peer/CIDR -- falls back to the direct peer."""
    trusted = _trusted_proxy_networks()
    direct = request.client.host if request.client else "unknown"
    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return direct
    if not trusted:
        return xff.split(",")[0].strip()
    try:
        direct_addr = ipaddress.ip_address(direct)
    except ValueError:
        return direct
    if any(direct_addr in net for net in trusted):
        return xff.split(",")[0].strip()
    return direct


def _window_bucket(window_seconds: int) -> int:
    return int(time.time() // window_seconds)


def check_rate_limit(key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
    """
    Returns (allowed, current_count, retry_after_seconds).
    Never raises — a rate limiter that crashes the request it's protecting
    defeats its own purpose; fail open (allow) on any backend error.
    """
    bucket = _window_bucket(window_seconds)
    bucket_key = f"{key}:{bucket}"
    retry_after = window_seconds - int(time.time() % window_seconds)

    if session_store.enabled():
        try:
            client = session_store.get_client()
            count = client.incr(f"orca:ratelimit:{bucket_key}")
            if count == 1:
                client.expire(f"orca:ratelimit:{bucket_key}", window_seconds + 1)
            return (count <= limit, count, retry_after)
        except Exception:
            pass  # fall through to in-process counting on Redis failure

    with _local_lock:
        window_start, count = _local_counters.get(key, (bucket, 0))
        if window_start != bucket:
            window_start, count = bucket, 0
        count += 1
        _local_counters[key] = (window_start, count)
        # Prevent unbounded growth of _local_counters across many distinct IPs
        if len(_local_counters) > 50_000:
            _local_counters.clear()

    return (count <= limit, count, retry_after)


@dataclass
class RateLimitRule:
    limit: int
    window_seconds: int
    label: str = "default"


def enforce(request: Request, rule: RateLimitRule, extra_key: str = "") -> None:
    """
    Raise HTTPException(429) if this IP has exceeded `rule` for this endpoint.
    extra_key lets the same IP have independent buckets per endpoint
    (e.g. "login" vs "signup") — pass the route name.
    """
    ip = get_client_ip(request)
    key = f"{rule.label}:{extra_key}:{ip}" if extra_key else f"{rule.label}:{ip}"
    allowed, count, retry_after = check_rate_limit(key, rule.limit, rule.window_seconds)
    if not allowed:
        from orca import audit
        audit.log("rate_limit_blocked", detail={
            "ip": ip, "rule": rule.label, "endpoint": extra_key,
            "count": count, "limit": rule.limit,
        })
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({rule.limit} requests per {rule.window_seconds}s). Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )


# ── Predefined rules — tune these based on real traffic once launched ────────

AUTH_SIGNUP    = RateLimitRule(limit=5,   window_seconds=3600, label="auth_signup")    # 5/hour/IP
AUTH_LOGIN     = RateLimitRule(limit=10,  window_seconds=300,  label="auth_login")     # 10/5min/IP
AUTH_FORGOT_PW = RateLimitRule(limit=3,   window_seconds=3600, label="auth_forgot_pw") # 3/hour/IP
CHAT_ANY       = RateLimitRule(limit=60,  window_seconds=60,   label="chat")           # 60/min/IP (auth or not)
CODE_RUN       = RateLimitRule(limit=20,  window_seconds=60,   label="code_run")       # 20/min/IP
DOC_UPLOAD     = RateLimitRule(limit=20,  window_seconds=60,   label="doc_upload")     # 20/min/IP
VISION         = RateLimitRule(limit=15,  window_seconds=60,   label="vision")         # 15/min/IP — image uploads cost more than text
