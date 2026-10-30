# MASTER-01 — Repository Dependency Graph

**Mission:** Cross-workstream integration readiness (assessment only — **not** merge authorization).  
**Verdict context:** Local integrated evidence ≠ independent qualification ≠ mainline acceptance.  
**SHA refresh (2026-10-30):** all verified starting refs **unchanged** after `git fetch` from GitHub.

## 1. Exact-SHA inventory

| Stream | PR | Head branch | Base branch | Exact HEAD SHA | vs main commits | Exact-head CI (author) |
|---|---|---|---|---|---|---|
| **main** | — | `main` | — | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` | — | N/A (baseline) |
| **F02** | [#140](https://github.com/Guruprasath-Annadurai/Orneur/pull/140) | `cursor/foundation-02-phase1-evidence-closure-8108` | `main` | `649d90f84069fc618ba4d69b4c26a66bed731caa` | 110 | GREEN (19/19) |
| **F03** | [#142](https://github.com/Guruprasath-Annadurai/Orneur/pull/142) draft | `cursor/foundation-03-rse-consumer-verification-9658` | `cursor/foundation-02-phase1-evidence-closure-8108` | `9cdc22bfc64f35e46e57769e3e255dabf5d11cb4` | 112 (via F02) | GREEN run `41049054165` (9/9 push jobs) |
| **L01** | [#136](https://github.com/Guruprasath-Annadurai/Orneur/pull/136) draft | `claude/b01-real-sse-chatbot-integration` | `cursor/b01-kernel-incremental-streaming-1cdf` @ `15befec7…` | `9cb864c99ad323d11626063498a7d1cef0d7d4b5` | 76 | GREEN (10/10) |
| **L02** | [#139](https://github.com/Guruprasath-Annadurai/Orneur/pull/139) draft | `claude/landmark-02-customer-trust-reliability` | `claude/b01-real-sse-chatbot-integration` | `38e0d311991875366f2bc88a39690c7b2b6ea3ee` | 105 | GREEN (10/10) |
| **L02-B3** | [#141](https://github.com/Guruprasath-Annadurai/Orneur/pull/141) draft | `claude/l02-b3-apikey-reauth` | `claude/landmark-02-customer-trust-reliability` | `66ce8aeace2077b89195735211d75ebd566716c8` | 108 | GREEN (10/10) |
| **L02-B6** | [#143](https://github.com/Guruprasath-Annadurai/Orneur/pull/143) draft | `claude/l02-b6-backup-privacy` | `claude/landmark-02-customer-trust-reliability` | `b1c56b98a52bdc3c448011f482251c238b329c5c` | 108 | GREEN (10/10) — **not independently qualified** |

**SHA delta vs verified starting refs:** none (0 changed).

## 2. Ancestry / dependency graph

```
main 20a8546
├── F02 649d90f  (#140 → main)
│     └── F03 9cdc22b  (#142 → F02 branch)
│           ├── code tip 0fe98e0 (C06/C07 impl+tests)
│           └── docs tip 9cdc22b (3 milestone docs only; no code after 0fe98e0)
│
└── L01-base 15befec (cursor/b01-kernel-incremental-streaming-1cdf; ancestor of L01)
      └── L01 9cb864c  (#136 → L01-base; includes main)
            └── L02 38e0d31  (#139 → L01)
                  ├── L02-B3 66ce8ae  (#141 → L02)   ⎫ siblings; merge-base = L02
                  └── L02-B6 b1c56b9  (#143 → L02)   ⎭ NOT stacked on each other
```

### Merge-base facts

| Pair | Merge-base | Ancestor relation |
|---|---|---|
| F02 ∩ F03 | `649d90f` | F02 ancestor of F03 |
| L01 ∩ L02 | `9cb864c` | L01 ancestor of L02 |
| L02 ∩ B3 / B6 | `38e0d31` | L02 ancestor of both |
| B3 ∩ B6 | `38e0d31` | **neither** is ancestor of the other |
| Foundation ∩ Landmark | `20a8546` (main) | **divergent stacks** — share only main |

## 3. Shared commits / duplicates / superseded

| Observation | Detail |
|---|---|
| Shared trunk | All streams contain `main@20a8546` |
| No cross-stack duplicate feature commits | Foundation (pretraining/RSE matrix) and Landmark (serve/SSE/trust) do not share unique commits beyond main |
| F03 vs Antigravity suite | Antigravity `75a7a648984d9883774292f35a511089e6ffd474` lives on `antigravity/phase01-independent-qualification`, **not** on PR #142 lineage. Parent is `e8d5bfd` (L02-B3 qual suite). Merge-base with `0fe98e0` = `main`. Suite hardcodes external worktree `/home/pc/projects/Orneur-pr142-f03` auditing candidate `0fe98e0` |
| L02-B3 vs L02-B6 | Sibling remediations of L02 open items B3 and B6; overlapping touch of `.github/workflows/test.yml` and `l02_04_login_timing.json` |
| Superseded plaintext backup | On L02 (and B3), `orca/serve/backup.py` still uses plaintext `MANIFEST.json` directory format. B6 replaces with `orneur-backup/2` encrypted format — **incompatible**, not a fast-forward of B3 |

## 4. Overlapping active work (file-level)

| Intersection | Overlapping paths | Risk |
|---|---|---|
| F02 ∩ L01 | `.github/workflows/test.yml`, `pyproject.toml`, `tests/conftest.py` | CI/packaging merge churn (observed clean auto-merge in disposable tree) |
| F02 ∩ L02 / B3 / B6 | `.github/workflows/test.yml` | CI job list union |
| F03 ∩ Landmark | *(none unique)* | F03 is RSE consumer path only |
| B3 ∩ B6 | `.github/workflows/test.yml`, `docs/.../l02_04_login_timing.json` | **content conflict** when both merged |

## 5. Green ≠ merge-safe without parents

| PR | Parent required before meaningful mainline consideration |
|---|---|
| #142 F03 | **#140 F02** (PR base is F02 branch, not main) |
| #139 L02 | **#136 L01** |
| #141 B3 | **#139 L02** (hence L01) |
| #143 B6 | **#139 L02** (hence L01); **conflicts with #141** if both desired |
| Landmark stack vs Foundation | Combining into one mainline candidate requires an explicit integration merge (disposable experiment only below) — green per-PR CI does **not** prove cross-stack safety |

## 6. F03 Phase-0 verification (sibling closure accepted)

Sibling [RSE consumer verification](bc-32d038cb-7551-5b9c-90ff-c63397059658) closed FOUNDATION-03. MASTER-01 verified only:

- Draft unmerged; base F02 @ `649d90f…`
- Qualified code `0fe98e0…`; tip `9cdc22b…` (docs-only after code)
- Exact-head CI `41049054165` **success** on tip
- Three milestone docs committed under `docs/orneur/milestones/foundation-03/`
- Formal acceptance **0/95**; C06/C07 `VERIFIED_ENGINEERING` in tested software scope only; register rows remain non-accepted
- Store closure: `/cursor/stores/self/docs/foundation-03-closure-report.md`

**Do not merge #142.**
