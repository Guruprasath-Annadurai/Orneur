# P1 — Security and Adversarial Results

Independent security qualification has **not** happened; these are engineering results. Synthetic accounts and synthetic content only; no secrets are written into this evidence.

| Area | Attack / probe | Outcome |
|---|---|---|
| XSS | 14 payloads (script, img/onerror, svg/onload, iframe javascript:, four URL-scheme variants incl. tab-split, quote break-out, handler in bold/code, fenced HTML, citation-marker button); hostile user text; hostile conversation title. Live render **and** reopened history | all inert; no dialog, no global set, no page error. **Mutation check:** with `esc()` disabled the same test goes red (15 injected elements, script executed) |
| Clickjacking | another origin frames `/conversation` | refused (CSP `frame-ancestors 'none'` + `X-Frame-Options: DENY`), browser C5 |
| Exfiltration | page script `fetch`/`sendBeacon` to another origin | blocked by `connect-src 'self'`, violation reported for the exact URL, C3/C4 |
| Auth bypass | invalid/forged bearer, token after logout, token after password change, token after account deletion | 401 in every case |
| MFA | code replay, wrong-code guessing, pending-token reuse | replay refused, per-account lockout, lock holds even for the right code (fixed this phase) |
| Sensitive operations | stolen session + password on a 2FA account; password guessing via change-password / delete | refused / locked (fixed this phase) |
| Recovery | reset-link replay; reset for unknown vs known address | replay refused; identical response (no enumeration) |
| Tenant isolation | read/export/rename/delete/stream-into/search across two users | fail closed; refused stream never reached the provider |
| Rate/abuse | signup rate limiter hit while preparing load users (5/hour/IP) | limiter works as designed |
| Quota evasion | concurrent burst at the limit | cannot overspend |
| Resource exhaustion | 30 MB body limit exists (existing test); 20 MB junk body → 422 after read; 200 000-character message accepted | no crash; no token budget (P1-X-06) |
| Error disclosure | malformed JSON | structured 422 with generic public message; no stack trace |
| Headers | `nosniff`, referrer policy, permissions policy (existing) + CSP, `DENY`, auth `no-store` (new) | present |
| CORS | preflight from a foreign origin | `*` outside a public edge; bearer-header auth, no auth cookies, so no cookie CSRF; public-edge mode already refuses to start with a wildcard (P1-X-05) |
| Dependencies | CI jobs "Dependency Vulnerability Scan" and "RSE dependency lock and vulnerability scan" | see the CI report for their conclusions on the exact head; no local audit |
| Logs / URLs | credentials in URLs or console | none in the account journey (A9) |

Not attempted: provider-redirect/SSRF probing of the Ollama host setting, supply-chain review, fuzzing of the SSE parser, long-running abuse, HTTPS-only/HSTS behaviour (local HTTP only).
Defects belonging to the protected foundation or native training code: none found; nothing there was modified.
