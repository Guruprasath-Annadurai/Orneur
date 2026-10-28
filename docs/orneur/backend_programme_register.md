# ORNEUR backend programme register

Engineering status only. Independent qualification is not awarded here.

## Provenance

| Ref | SHA |
| --- | --- |
| Working branch | `cursor/backend-programme-ae9d` |
| Parent (#121 lease pump) | `637efeceaab65193b31f7c64dd9babf0cf5634df` |
| origin/main (at Wave 0) | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` |
| PR #111 Claude product candidate | `57bf22870249415da93ed03ceafcb852fe49cab9` |
| PR #115 founder runtime | `5ead4b426cd3d93705119f00353448bdea4bac4f` |
| PR #120 mission security | `defb0c5` lineage; not merged into this programme as a second engine |
| Merge-base #111 vs #121 | `origin/main` — do not merge #111 or #115 into this branch |

Authoritative mission runtime on this tree: `orca/sovereign_mission` (product SQLite). Phase 15 `orca/mission` remains a separate store and is not a third engine. `orca/agent` remains the Phase 8 tool runtime. Specialists live in `orca/specialists` and do not dispatch missions.

Claude owns conversation B11 follow-up. This branch does not rewrite `orca/serve/conversations.py`.

## Work this increment

- C2 deny-all principal adapter (`orca/governance/deny_principal.py`) without copying PR #115.
- B5 pause/resume only from `AUTHORIZED` before any effect.
- D1/D4/D5 ten specialist handlers + versioned registry + DAG orchestrator.
- E5 local recompute verifier (`orca/sovereign_mission/verify.py`). Witness is local, not external.
- H1/H2/H3/H4 honest `NOT_AVAILABLE` opportunity and voice contracts. No live listings or speech backend.
- G2 tenant upload store with size and name limits.
- F5 local usage accounting that refuses paid backends while spending is unauthorized.
- F2 honest availability discovery (`NOT_AVAILABLE` for native families and paid backends while spending is denied).
- G3/G5 authenticated document task: upload, keyword cite, excerpt hash, delete without replica claims.
- G1 untrusted execution remains disabled without docker.

Public browser remains unqualified. Training remains `NO-GO`.

## Exact-head CI

| Head | Run | Result |
| --- | --- | --- |
| `00c30785d45af0097b9294e1ddce9ad1ad7cbda4` | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40569660383 | 9/9 success |
| `43020779f23d3cc475a341cbd02d52ea6a2079cf` | https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/40569838397 | 9/9 success |

Independent qualification is not awarded by a green CI badge.

## CTO continuation (after `0ef5fb8`)

- Uploads: exclusive temp + `os.link` publish, nofollow/lstat, write-failure cleanup, `User`-typed `store_for`.
- Document task: extract-before-persist; split claims (upload / excerpt / grounding / external).
- Orchestrator: absolute deadline; cancel does not claim threads killed.
- Availability: live tags probe is `reachable_not_inferred`, never inference.
- HTTP `/api/documents` and `/api/specialists/run` bind owner from the session.
- Memory `require_consent` helper exists; existing writers are not all gated.

## Remaining (authorized but unfinished)

- Official A–F UI journeys: 0. Do not mark complete without frozen frontend.
- C3 temporary-chat: Claude B11. Do not rewrite conversations.py.
- F3 live streaming against a real local model: blocked if Ollama generate is absent.
- G1 untrusted execution: docker absent.
- H1 live opportunity source: absent.
- I2/I5 tokenizer/family eval foundations.
- Do not merge #111 or #115 into this PR.

Resume from the branch head after push; re-run exact-head CI before any handover report.

## F3/G1/H1/I2/I5 continuation from `e48f5a3`

- Authenticated `/api/inference/complete` POSTs Ollama `/api/generate`. `/api/inference/stream` uses `OllamaRuntime.stream` (`/api/chat`) as SSE. History is SQLite, per `user.id`.
- Live on this engineering host: Ollama 0.12.6 serving `smollm:135m` (91 MB Q4_0). Generate `tokens_in=20` `tokens_out=64` `latency_ms≈1779`. Stream produced 64 chunks. Identity stayed `served_model=smollm:135m`, `backend=ollama`, `native_family=null`.
- Fixture HTTP tests remain labeled `synthetic_provider`. Unreachable host is `provider_unavailable`, not a pass.
- GitHub Actions: live tests skip unless the runner has Ollama and a tag. That skip is BLOCKED on CI, not a live pass.
- Docker G1 continues on branch `cursor/g1-docker-isolation-ae9d` (does not modify PR #122 `ea9bb95`).
- Opportunity live source: **none authorized**. `availability().required_dependency` names a licensed adapter + `ORNEUR_OPPORTUNITY_SOURCE`. H1 remains not started. PR #115 was not merged.
- Synthetic byte tokenizer + family foundation status without official scores. GENESIS `INTERFACE_ONLY`; NOVUS/AETERNUM `NOT_AVAILABLE`; official scores null.
- Frontend contract for the authenticated serving journey (frozen UI not edited):
  - `POST /api/auth/login` then `Authorization: Bearer <token>`
  - `POST /api/inference/complete` `{message, model}` → `{text, model, backend, identity, latency_ms, tokens_in, tokens_out, live, native_family}`
  - `POST /api/inference/stream` SSE `data: {type: chunk|done|cancelled|error, ...}`
  - `GET /api/inference/history` owner-only turns
  - Claude owns B11/B13, temporary-chat, Redis consistency. This branch did not edit `orca/serve/conversations.py`.

## G1 Docker isolator (`cursor/g1-docker-isolation-ae9d`)

Based on audited PR #122 `ea9bb95`. Does not rewrite inference.

- Product path: `orca/code/untrusted.execute` → `docker run` with `--network none`, `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--user 65534:65534`, tmpfs `/workspace` and `/tmp` (uid 65534), no host binds, no docker.sock, no inherited secrets.
- Allowlisted image: `python:3.11-alpine` digest `sha256:79440cc1dfa86a5f98d67efcd219726a8e9d8083cc0aafd27c7bef5976c38868`.
- HTTP `POST /api/untrusted/task` requires auth and `ORNEUR_UNTRUSTED_EXECUTION=development`. `/api/code/run` stays `capability_disabled`. Path avoids G-020 `exec`/`orca.code` serve-import bans.
- Callers cannot set privileged, image, network, or mounts.
- Shared-kernel Docker remains disclosed. Production stays off.

