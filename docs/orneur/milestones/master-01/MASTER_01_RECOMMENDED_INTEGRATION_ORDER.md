# MASTER-01 — Recommended Integration Order

**Not merge authorization.** Classifications are preflight judgments for founder/CTO review queues.

## Classification vocabulary

| Class | Meaning |
|---|---|
| `READY_FOR_FOUNDER_REVIEW` | Engineering package + exact-head CI coherent enough for human review; **not** “merge now” |
| `REQUIRES_INDEPENDENT_QUALIFICATION` | Engineering claims exist; Antigravity/OWN_EVIDENCE on exact head still required |
| `ENGINEERING_REMEDIATION_REQUIRED` | Known unresolved defect/bypass or packaging hazard |
| `BLOCKED_BY_DEPENDENCY` | Parent PR/stack not landed or not reviewable yet |
| `SUPERSEDED/DUPLICATE` | Replaced or redundant (none of the six heads fully superseded) |

## Recommended order

| Step | PR | Stream | Classification | Parent / gate | Rollback & merge risk |
|---|---|---|---|---|---|
| 1 | **#140** | F02 | `READY_FOR_FOUNDER_REVIEW` + residual `REQUIRES_INDEPENDENT_QUALIFICATION` for counted OWN_EVIDENCE | `main@20a8546` | Doc/evidence-heavy; training remains NO-GO. Rollback = revert PR. Risk: large surface (191 files) but base is main |
| 2 | **#142** | F03 | `BLOCKED_BY_DEPENDENCY` (#140) then `REQUIRES_INDEPENDENT_QUALIFICATION` | F02 branch tip `649d90f` | Docs+RSE only after `0fe98e0`. Rollback trivial. **Do not merge ahead of #140.** Formal C06/C07 still not accept |
| 3 | **#136** | L01 | `REQUIRES_INDEPENDENT_QUALIFICATION` (B-02) | Intermediate base `15befec` (already in L01 tip); effectively stacks on main | Large serve/SSE surface (76 commits). Rollback complex once dependents exist |
| 4 | **#139** | L02 | `BLOCKED_BY_DEPENDENCY` (#136) + `REQUIRES_INDEPENDENT_QUALIFICATION` (L02-Q) | L01 tip | Adds deletion/RAG/account/ops. Open L02-B6 plaintext until remediated/qualified elsewhere |
| 5 | **#141** | L02-B3 | `BLOCKED_BY_DEPENDENCY` (#139) + `REQUIRES_INDEPENDENT_QUALIFICATION` | L02 tip | Small auth schema additive (`auth_stepup_totp_used`). Conflicts with #143 CI/evidence files |
| 6 | **#143** | L02-B6 | `ENGINEERING_REMEDIATION_REQUIRED` + `REQUIRES_INDEPENDENT_QUALIFICATION` + `BLOCKED_BY_DEPENDENCY` (#139) | L02 tip; **sibling of #141** | **Incompatible backup format**; plaintext bypass/unqualified. **Cannot enter “integration-ready” set.** Resolve CI/evidence conflicts with #141 before any dual consideration |

### Parallelism note

Foundation stack (1→2) and Landmark stack (3→4→5) are **ancestry-disjoint** above main. Disposable experiment showed F02+F03+L01+L02+B3 **auto-merges cleanly**, but that is **not** a substitute for ordered review, independent qualification, or mainline CI on a real integration SHA.

## What cannot enter main yet

| Item | Why |
|---|---|
| Anything claiming training-ready / launch-ready | Authorization NO-GO; freeze NOT_FROZEN; 0/95 |
| #142 without #140 | Wrong parent; base is F02 branch |
| #139/#141/#143 without #136 | Landmark parent chain |
| #143 as qualified backup privacy | Unresolved legacy plaintext bypass; not independently qualified |
| B3+B6 dual merge without conflict resolve | CI workflow + timing evidence conflicts |
| C06/C07/G2/G3 register promotion | Local/engineering evidence insufficient |
| Combined disposable tip `ee8cb2a…` | Local-only; unpushed; unqualified |

## Migrations / rollback summary

| PR | Migration character | Rollback |
|---|---|---|
| #140 | Mostly evidence/probes + genesis foundation code paths | Git revert; no customer DB migration |
| #142 | Additive RSE module + tests + docs | Git revert |
| #136/#139 | Auth/serve/SQLite behavior; Redis/journey assumptions | Revert cascade; operational runbooks needed if ever deployed |
| #141 | Additive step-up ledger table | Revert + drop table if deployed |
| #143 | **Breaking** backup format; deletion ledger file | Old plaintext backups not restorable via new tool; high ops risk |

## Merge-risk heatmap

```
main ← #140 (F02) ← #142 (F03)
main ← #136 (L01) ← #139 (L02) ← #141 (B3)
                              ↖ #143 (B6)  [conflict with #141; NOT integration-ready]
```
