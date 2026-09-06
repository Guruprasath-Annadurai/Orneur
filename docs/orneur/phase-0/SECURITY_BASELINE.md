# Orneur Phase 0 — Security Baseline

Verified by direct code audit, cross-checked against `docs/SECURITY_AUDIT.md`'s existing claims (not just repeated as fact).

## Dangerous-pattern census (direct grep, orca/ only, excluding caches)

- `TODO`/`FIXME`/`XXX`/`HACK`: **0 hits**.
- `NotImplementedError`: **0 hits**.
- Bare `except:`: **0 hits**.
- `eval(`/`exec(`: **0 hits**.
- `shell=True`: **1 hit** — `orca/doctor.py:448`, a local CLI health-check "fix" runner. Input is built from internal doctor-check definitions, not exposed to untrusted/remote input directly — real but low severity. A second look at whether any `fix` string can be influenced by remote/attacker-controlled data is worth a Phase 1 follow-up, not urgent.
- `while True`: 4 occurrences, all verified bounded — 3 are human-driven interactive CLI REPLs (bounded by EOF/exit), 1 breaks cleanly on `asyncio.QueueEmpty`. **No unbounded agent-loop or retry pattern found anywhere in the codebase.**

## Authorization model — real, not superficial

- **RBAC**: rank-based (`owner:40 > admin:30 > member:20 > viewer:10`), real permission sets, FastAPI dependency-injected checks.
- **Multi-tenant**: org-scoped roles distinct from global user role, real schema (`orgs`/`org_members` tables).
- **Password hashing**: PBKDF2-HMAC-SHA256, 260,000 iterations, per-password salt, constant-time compare — not plaintext, not a weak hash.
- **API keys**: prefixed, hashed at rest, revocable.
- **Tokens**: two systems (long-lived session tokens, short-lived single-purpose tokens for verify/reset/2FA-pending), both HMAC-signed, both use timing-safe comparison, both fail closed on any exception.
- **2FA**: standard TOTP (RFC 6238).
- **"God-mode" naming confirmed NOT tied to any privilege bypass** (see `MEMORY_AGENT_STATUS.md`).

## Real, currently-open gaps

1. **Auth secret fallback**: `_SECRET`/`_secret()` default to hardcoded dev-fallback strings if `ORCA_AUTH_SECRET` isn't set in the environment. This is a real risk *if* that env var is ever left unset in an actual production deploy — whether it's actually enforced/set correctly in any current deployment was **not verified** (would require inspecting live deployment config, out of scope for a static repo audit).
2. **No session/JWT revocation beyond API-key revocation** — session tokens appear stateless/expiry-only; no revoke-by-jti mechanism was found.
3. **`fs_server.py` prefix-confusion path bug** (new finding, not in the existing `docs/SECURITY_AUDIT.md`) — see `MEMORY_AGENT_STATUS.md` for detail. Separate code path from the properly-hardened workspace sandbox; needs the same fix pattern.
4. **`run_shell`'s allowlist has no path restriction** — an allowlisted read command can still reach files outside the workspace (e.g. `~/.ssh/id_rsa`). Already documented in `docs/SECURITY_AUDIT.md` as a known, unaddressed gap — confirmed still true.
5. **`fetch_page`'s SSRF guard is dead code** — the check function is real and correct, but nothing calls it. Confirmed still true from the existing doc.
6. **Rate-limiter fails open** on Redis outage, and trusts `X-Forwarded-For` unconditionally — a spoofable rate-limit bucket if Orneur is ever deployed without a proxy that correctly sets/strips that header.
7. **Full endpoint-level rate-limit coverage was not exhaustively re-verified** in this audit — only the limiter primitive itself was confirmed correct; whether every relevant route actually calls it needs a dedicated pass.

## Previously-documented fixes — independently re-verified as still present in current code

All four "FIXED" items in `docs/SECURITY_AUDIT.md` were independently confirmed still in place (not just trusted from the doc):
- `run_python` arbitrary code execution — FIXED (AST denylist, stripped env, timeout). Known limitation (string-concat+getattr AST bypass) is itself documented and tested.
- `read_file`/`write_file` arbitrary path access — FIXED (proper `.relative_to()`-based workspace sandboxing).
- `fetch_page` SSRF — FIXED at the function level, but the function is unreachable dead code (item 5 above).
- `run_shell` command injection — FIXED (`shell=False`, allowlist), but path-restriction gap remains (item 4 above).

## Dependency CVEs

`diskcache` and `chromadb` remain on unpinned/unpatched minimum-version constraints in `pyproject.toml`, consistent with `docs/SECURITY_AUDIT.md`'s own statement that no patched version exists yet for either CVE and that both are assessed as not currently exploitable in Orca's deployment (chromadb only used via local `PersistentClient`, never server mode; diskcache never fed untrusted network data). **Not independently re-verified against external CVE databases** — UNVERIFIED at that level; only doc-vs-code consistency was checked.

## Hardcoded secrets

Targeted regex scan for API-key/secret/password/token literal assignments returned **zero real matches** — the only "secret"-like strings found are the explicitly-labeled dev-fallback defaults (item 1 above), not leaked real credentials.

## Bottom line for Orneur

The security posture inherited from Orca is genuinely stronger than a typical early-stage project's — real RBAC, real password/token hashing, a documented and independently-re-verified history of fixing real vulnerabilities (not just claiming to), and an honest published audit that doesn't overstate what's fixed. The gaps that remain (items 1–7 above) are specific, bounded, and already mostly known — none of them are "the whole security model is fake." The one genuinely new finding from this audit (`fs_server.py`'s prefix-confusion bug) should be fixed early in Phase 1, using the same pattern already proven correct in `orca/tools/__init__.py`.
