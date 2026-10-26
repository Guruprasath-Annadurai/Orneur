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

`COMPLETED_VERIFIED` is reachable only from `VERIFYING` with an intact evidence hash and an independent receipt (`local_marker` file bytes). `COMPLETED_UNVERIFIED` is the honest terminal when the only observation is untrusted DOM text or a DOM mutation. `INTERRUPTED_UNKNOWN` and `OUTCOME_UNKNOWN` cannot become either completed state.

Ordinary construction of `SovereignMission` does not sweep `EXECUTING` rows. Each instance has a worker id, takes a lease at dispatch, and heartbeats while it holds execution authority. A second live instance cannot recover a mission whose lease is still fresh. Recovery is `POST /missions/{id}/recover` (owner session only) or `shutdown()` for this worker's own leases. An expired lease is fenced and recorded as unknown; it is not proof the previous worker has stopped, and it is not a retry. A fenced worker cannot commit `COMPLETED_VERIFIED`. SQLite on one host is not a multi-host lock.

Claims:

| Claim | When |
| --- | --- |
| `authorized_not_performed` | Planned or authorized, and no effect has started. |
| `verified` | `COMPLETED_VERIFIED` and the evidence hash matches. Independent file receipt only. |
| `unverified` | `COMPLETED_UNVERIFIED`. Untrusted page text or a DOM delta is not an external transaction. |
| `failed` | `FAILED`. |
| `refused` | `CANCELLED` or `REVOKED` with no unknown effect. |
| `unknown` | `INTERRUPTED_UNKNOWN`, `OUTCOME_UNKNOWN`, or executing after a cancel request. |
| `withheld` | A stored evidence record or the mission aggregate does not match its hash. The records are not returned. |

`verified` means this process produced and read back an independent receipt. For a marker, that receipt is the exclusive file: after the write, the process reopens the path and hashes the bytes it actually read. A browser step never uses substring presence of `expect` as verified completion. Pre-action and post-action hashes are stored; page text stays untrusted. If `expect` was already in the page, the detail is `expectation_preexisting` and the claim is not `verified`. The browser tool's own navigation and click records remain `performed_unverified`. A hash is not authorship and is not an external witness.

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
| POST | `/missions/{id}/recover` | |
| GET | `/missions/{id}/evidence` | |
| GET | `/missions/{id}/result` | |

Approval expiry uses the server clock on the HTTP path. A consumed approval cannot be replayed. Each approval stores a version-1 canonical scope digest over mission, owner, step, tool, risk, full URL path and query, actions, selector, input/form values, expect, verification policy, ttl, and the single-use approval id and nonce. Dispatch recomputes that digest before consuming authorization. A missing digest is `approval_scope_missing`. Any altered scope is `approval_scope_mismatch`. Old rows are not grandfathered. Dispatch of a finished step returns the stored claim with `replayed: true` and does not repeat the effect. Dispatch after an intent or an unknown outcome is `duplicate_effect_refused`.

Cancel response includes `cancel_confirmed`. That is true only when no external effect had started and the state is `CANCELLED`. A cancel after `effect_started` leaves `OUTCOME_UNKNOWN`. Revoke consumes the caller's unused approvals. Revoke after an effect has started leaves `OUTCOME_UNKNOWN` and does not become success. Revoke while `EXECUTING`, before the effect flag, commits `REVOKED`.

Cancel and revoke check the authenticated owner and commit that decision before they write the process stop table or close a live browser. A denied caller raises `access_denied` or `mission_not_found` and does not change `_STOP`, `_LIVE`, the mission row, an external effect, or evidence. Execution reads the committed row. A process-local stop entry is not authority, including a stop planted for another user's mission. A finished `COMPLETED_VERIFIED` or `FAILED` row is not turned back into a cancellation by a later flag.

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

A transient Chrome navigation error (`net::ERR_ABORTED` and the other connection resets listed in the engine) is retried once inside the same authorized step. The loaded URL still has to match the granted destination. Any other navigation error fails the step.

Page text is untrusted. A sentence in the page does not change the grant, the plan, or the recorded actions. Evidence stores hashes of the observed text, not the text. If the expectation string appears inside a browser evidence record, the mission fails with `evidence_leak`.

`local_marker` writes one exclusive file under the mission workspace. The file bytes are the external effect. The HTTP claim is not that effect.

## Residuals Antigravity should attack

These are not independently enforced here:

- PR #116's browser substrate remains independently unqualified. The proxy `poll()` correction and the one-shot transient navigation retry live on this child branch, not in that parent's history.
- Public and hostname browser destinations stay closed until Browser-01 is qualified. This branch's live proof is a local fixture only.
- Focus the next adversarial pass on this stop boundary: cross-user cancel and revoke during `EXECUTING` (service and HTTP), a planted `_STOP` or `_LIVE` entry, cancel after `effect_started`, revoke before the file or browser call, restart from `OUTCOME_UNKNOWN`, and a crash between the effect flag and the outcome write. A same-process caller who can already invoke `engine.cancel` on a live object is inside the service, not a second tenant.
- Tenant isolation is the service check `owner_user_id == tenant_id == authenticated user`. Both users share the service OS account. Mode `0600` evidence does not stop that account.
- A database writer who replaces `record_json`, `record_sha256`, and `evidence_sha256` together is not detected. A partial edit is `withheld`.
- Browser `COMPLETED_UNVERIFIED` is still not an external transaction witness. Independent receipts for browser effects are not implemented on the local fixture. The grant still cannot grow.
- Worker leases are SQLite-local. Tests do not establish multi-host readiness. Lease grace is 45 seconds so a slow Chrome DevTools handshake is not treated as a dead worker.
- Recovery of an expired lease fences commit authority; it does not prove the previous process is dead.
- Chrome has CPU and open-file limits and no memory cap. The mission path refuses a binary whose bytes contain `--no-sandbox` because the browser engine does. The live crash test checked the mission Chrome command line. Chrome profiles are under `/tmp/orneur-chrome/<scope>/c` so the DevTools singleton socket fits `AF_UNIX`; a nested mission workspace path was observed to make Chrome exit before CDP was ready.
- There is no pause or resume.
- An unknown outcome is not retried. That prevents a duplicate effect; it also leaves a mission that never reached the peer stuck.
- `effect_started` is committed immediately before the external call. A crash in that window is unknown even if the peer saw nothing.
- SQLite serializes writers in one process. This is not a multi-host lock.
- API keys and `orca/serve/session_store.py` were not part of the mission tests.
- Process logs outside the evidence files were not audited.
- No independent qualification has been recorded. `INDEPENDENTLY_QUALIFIED` remains 0/50.

## Tests that have to stay honest

`tests/test_browser_sovereign_mission.py` starts real Chrome for the live tests and skips those only when `chrome_binary()` refuses the binary. It sits next to `tests/test_browser_engine.py` so Chrome is started before the rest of the deterministic suite has exhausted the runner. A skip is not a pass. The non-live tests use a real marker file, the product password hasher, and the product session token. They are not a substitute for the live browser mission.
