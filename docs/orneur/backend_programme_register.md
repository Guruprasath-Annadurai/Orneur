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

Public browser remains unqualified. Training remains `NO-GO`.
