#!/usr/bin/env python3
"""Bounded Phase 14B remote smoke probe.

This script intentionally performs only read-only HTTP checks and never accepts
or prints ORNEUR database/authentication secrets. It can be used against a
Northflank local port-forward before public ingress exists, or against the
Cloudflare staging hostname after the tunnel is configured.

Examples:
  python scripts/phase14b_remote_smoke.py http://127.0.0.1:7337
  python scripts/phase14b_remote_smoke.py https://api-staging.orneur.com --expect-ready
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass


@dataclass
class ProbeResult:
    path: str
    status: int | None
    ok: bool
    elapsed_ms: float
    detail: str


def _fetch(base_url: str, path: str, timeout: float) -> ProbeResult:
    url = base_url.rstrip("/") + path
    started = time.monotonic()
    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "orneur-phase14b-smoke/1"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(64 * 1024)
            elapsed = (time.monotonic() - started) * 1000
            detail = body.decode("utf-8", errors="replace")[:1000]
            return ProbeResult(path, response.status, 200 <= response.status < 300, elapsed, detail)
    except urllib.error.HTTPError as exc:
        elapsed = (time.monotonic() - started) * 1000
        body = exc.read(64 * 1024).decode("utf-8", errors="replace")[:1000]
        return ProbeResult(path, exc.code, False, elapsed, body)
    except Exception as exc:  # network errors are reported, never hidden
        elapsed = (time.monotonic() - started) * 1000
        return ProbeResult(path, None, False, elapsed, f"{type(exc).__name__}: {exc}")


def _require_safe_base_url(value: str, allow_http: bool) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("credentials must never be embedded in the base URL")
    if parsed.scheme == "http" and not allow_http:
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("remote staging must use HTTPS; use --allow-http only for an intentional private test")
    return value.rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Phase 14B remote smoke checks")
    parser.add_argument("base_url", help="Northflank forwarded URL or Cloudflare staging URL")
    parser.add_argument("--expect-ready", action="store_true", help="require /readyz HTTP 2xx")
    parser.add_argument("--allow-http", action="store_true", help="allow non-loopback HTTP intentionally")
    parser.add_argument("--samples", type=int, default=5, help="number of /livez samples (1-20)")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between /livez samples")
    parser.add_argument("--timeout", type=float, default=5.0, help="per-request timeout seconds")
    args = parser.parse_args()

    if not 1 <= args.samples <= 20:
        parser.error("--samples must be between 1 and 20")
    if not 0 <= args.interval <= 30:
        parser.error("--interval must be between 0 and 30 seconds")
    if not 0.1 <= args.timeout <= 30:
        parser.error("--timeout must be between 0.1 and 30 seconds")

    try:
        base_url = _require_safe_base_url(args.base_url, args.allow_http)
    except ValueError as exc:
        parser.error(str(exc))

    results: list[ProbeResult] = []
    live_ok = True
    for index in range(args.samples):
        result = _fetch(base_url, "/livez", args.timeout)
        results.append(result)
        if not result.ok:
            live_ok = False
        else:
            try:
                payload = json.loads(result.detail)
                if payload.get("status") != "alive":
                    live_ok = False
                    result.ok = False
                    result.detail = "unexpected /livez JSON contract"
            except json.JSONDecodeError:
                live_ok = False
                result.ok = False
                result.detail = "invalid /livez JSON"
        if index + 1 < args.samples:
            time.sleep(args.interval)

    health = _fetch(base_url, "/healthz", args.timeout)
    results.append(health)

    ready = _fetch(base_url, "/readyz", args.timeout)
    results.append(ready)

    ready_ok = ready.ok if args.expect_ready else True
    summary = {
        "base_url": base_url,
        "live_samples": args.samples,
        "live_pass": live_ok,
        "health_status": health.status,
        "ready_status": ready.status,
        "ready_required": args.expect_ready,
        "overall_pass": bool(live_ok and ready_ok),
        "results": [asdict(item) for item in results],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["overall_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
