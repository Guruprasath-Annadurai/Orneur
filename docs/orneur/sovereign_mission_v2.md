# Sovereign Mission V2

Authenticated mission execution on the product SQLite auth database. This is the backend contract for a later frontend. It does not change Claude-owned screens.

Parent commit: `f7bf4077a5541e219d6c2bf7f219e14c55e31e1a` (browser PR #116). PR #115 (`5ead4b426cd3d93705119f00353448bdea4bac4f`) is a separate governance branch and is not in this tree. Its deny-all principal was not copied and was not turned into a caller-controlled bypass.

## What this is not

- Not the Phase 15 Postgres mission store (`orca/mission/`). That store needs `ORNEUR_MISSION_DATABASE_URL`. This process did not provision Neon, and that enum cannot represent an unknown outcome. Its files are unchanged.
- Not a model call. The model router is not on this path.
- Not the agent tool registry. The mission allowlist is `local_marker` and `browser` only.
- Not a public browser. Until Browser-01 is independently qualified, a real browser step accepts only `http://127.0.0.1:<port>` or `http://[::1]:<port>`. Any other destination, including `localhost` and HTTPS, is `public_browser_unqualified` at plan time.
- Not training, spending, GPU, or production authorization. The acceptance ledger SHA-256 remains `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` (0/95). Training stays `NO-GO`.

## Authentication

Sessions are the existing product sessions.

1. `POST /api/auth/login` with `email` and `password`.
2. The response field `token` is a session token. A wrong password returns 401 and no token.
3. Send `Authorization: Bearer <token>` on every mission route.
4. The token must have `type` `session`, an unrevoked `jti`, and `iat` not older than `tokens_valid_after`.
5. The authenticated user id is both `owner_user_id` and `tenant_id`. A JSON field `owner_user_id` is ignored.
6. Another user's mission id returns `access_denied` without the objective or evidence. An unknown id returns `mission_not_found`.

`DISTRIBUTED` mode requires Postgres for auth. This mission store then refuses to open (`sqlite_auth_required`). It does not silently create a second database.

## Lifecycle

`CREATED → PLANNED → AWAITING_APPROVAL → AUTHORIZED → EXECUTING → VERIFYING → COMPLETED_VERIFIED`

Also `FAILED`, `CANCELLED`, `REVOKED`, `INTERRUPTED_UNKNOWN`, and `OUTCOME_UNKNOWN`.

`COMPLETED_VERIFIED` is reachable only from `VERIFYING` with an intact evidence hash. `INTERRUPTED_UNKNOWN` and `OUTCOME_UNKNOWN` cannot become `COMPLETED_VERIFIED`. A new `SovereignMission` reconciles rows left in `EXECUTING`: an `effect_started` row with no outcome becomes `OUTCOME_UNKNOWN`; an intent with no effect becomes `INTERRUPTED_UNKNOWN`. Recovery does not report success.

Claims:

| Claim | When |
| --- | --- |
| `authorized_not_performed` | Planned or authorized, and no effect has started. |
| `verified` | `COMPLETED_VERIFIED` and the evidence hash matches. |
| `failed` | `FAILED`. |
| `refused` | `CANCELLED` or `REVOKED` with no unknown effect. |
| `unknown` | `INTERRUPTED_UNKNOWN`, `OUTCOME_UNKNOWN`, or executing after a cancel request. |
| `withheld` | A stored evidence record or the mission aggregate does not match its hash. The records are not returned. |

`verified` means this process observed the predeclared expectation. For a marker, it wrote the file. For a browser step, the untrusted DOM text contained `expect`. The browser tool's own navigation and click records remain `performed_unverified`. A hash is not authorship and is not an external witness.

## HTTP

Prefix `/api/sovereign`. Mission errors use `detail.code`, and the full application copies that to the top-level `code` field. `access_denied` is 403. `mission_not_found` and `step_not_found` are 404. Other mission errors are 409. A missing bearer is 401. On the full application the existing handler reports that as `auth_required`. A mission-layer token rejection uses `unauthenticated`.

| Method | Path | Body |
| --- | --- | --- |
| POST | `/missions` | `{"objective": "<1..500 chars>"}` |
| GET | `/missions/{id}` | |
| POST | `/missions/{id}/plan` | `{"steps": [{"tool": "local_marker"\|"browser", "arguments": {...}}]}` |
| POST | `/missions/{id}/approval-request` | |
| POST | `/missions/{id}/approvals` | `{"step_id": "...", "ttl_seconds": 1..120}` |
| POST | `/missions/{id}/dispatch` | `{"step_id": "..."}` |
| POST | `/missions/{id}/cancel` | |
| POST | `/missions/{id}/revoke` | |
| GET | `/missions/{id}/evidence` | |
| GET | `/missions/{id}/result` | |

Approval expiry uses the server clock on the HTTP path. A consumed approval cannot be replayed. Dispatch of a finished step returns the stored claim with `replayed: true` and does not repeat the effect. Dispatch after an intent or an unknown outcome is `duplicate_effect_refused`.

Cancel response includes `cancel_confirmed`. That is true only when no external effect had started and the state is `CANCELLED`. A cancel after `effect_started` leaves `OUTCOME_UNKNOWN` or `INTERRUPTED_UNKNOWN`. Revoke consumes unused approvals. Revoke after an effect has started does not become success.

### Browser arguments

```json
{
  "tool": "browser",
  "arguments": {
    "url": "http://127.0.0.1:9/",
    "actions": ["navigate", "click", "read"],
    "selector": "#go",
    "expect": "CLICKED"
  }
}
```

`actions` may contain `navigate`, `read`, `click`, `fill`, `scroll`, and `screenshot`. `download` is refused. `click` and `fill` require a `#` selector of the browser engine's form. `expect` is required, at most 64 characters, and cannot contain a newline. The grant issued to Chrome adds `navigate` and `read` when the step needs them to open the page and observe it. It never adds `download`. The grant is bound to the authenticated user, the mission, the loopback endpoint, the action set, and a 60-second expiry. The caller cannot supply a grant.

Page text is untrusted. A sentence in the page does not change the grant, the plan, or the recorded actions. Evidence stores hashes of the observed text, not the text. If the expectation string appears inside a browser evidence record, the mission fails with `evidence_leak`.

`local_marker` writes one exclusive file under the mission workspace. The file bytes are the external effect. The HTTP claim is not that effect.

## Residuals Antigravity should attack

These are not independently enforced here:

- Public and hostname browser destinations stay closed until Browser-01 is qualified. This branch's live proof is a local fixture only.
- Tenant isolation is the service check `owner_user_id == tenant_id == authenticated user`. Both users share the service OS account. Mode `0600` evidence does not stop that account.
- A database writer who replaces `record_json`, `record_sha256`, and `evidence_sha256` together is not detected. A partial edit is `withheld`.
- Mission `verified` has no external witness. The DOM check is a substring of untrusted text, so a fixture page can contain the operator's `expect` string without having performed the intended action. The grant still cannot grow.
- Chrome has CPU and open-file limits and no memory cap. The mission path refuses a binary whose bytes contain `--no-sandbox` because the browser engine does. The live crash test checked the mission Chrome command line.
- There is no pause or resume.
- An unknown outcome is not retried. That prevents a duplicate effect; it also leaves a mission that never reached the peer stuck.
- `effect_started` is committed immediately before the external call. A crash in that window is unknown even if the peer saw nothing.
- SQLite serializes writers in one process. This is not a multi-host lock.
- API keys and `orca/serve/session_store.py` were not part of the mission tests.
- Process logs outside the evidence files were not audited.
- No independent qualification has been recorded. `INDEPENDENTLY_QUALIFIED` remains 0/50.

## Tests that have to stay honest

`tests/test_sovereign_mission.py` starts real Chrome for the two live tests and skips those two only when `chrome_binary()` refuses the binary. A skip is not a pass. The non-live tests use a real marker file, the product password hasher, and the product session token. They are not a substitute for the live browser mission.
