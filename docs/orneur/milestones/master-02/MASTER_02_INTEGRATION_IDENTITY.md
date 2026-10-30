# MASTER-02 — Integration Identity

**Mission:** Reproducible integration candidate (assessment only).  
**Do not merge to main. Do not authorize training.**

## Exact SHAs (refreshed 2026-10-30)

| Ref | Role | Full SHA |
|---|---|---|
| `main` | Canonical base (protected, unchanged) | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` |
| #140 F02 | Source tip (ancestor) | `649d90f84069fc618ba4d69b4c26a66bed731caa` |
| #142 F03 | Source tip (ancestor) | `9cdc22bfc64f35e46e57769e3e255dabf5d11cb4` |
| F03 engineering | Code-only tip inside #142 | `0fe98e04c2e0c77c7a4e9dc4abfc97bbb3a54d51` |
| L01 Kernel base | Inside #136 complete history | `15befec7191a1992286d7fa027236002f7d385db` |
| #136 L01 | Source tip (ancestor) | `9cb864c99ad323d11626063498a7d1cef0d7d4b5` |
| #139 L02 | Source tip (ancestor) | `38e0d311991875366f2bc88a39690c7b2b6ea3ee` |
| #141 L02-B3 | Source tip (ancestor) | `66ce8aeace2077b89195735211d75ebd566716c8` |
| #143 L02-B6 | **EXCLUDED** (current remote) | `e5266c71d8a9a50e2571eaef1ca30f1c976d5f59` |
| #143 (MASTER-01) | **EXCLUDED** (prior recorded) | `b1c56b98a52bdc3c448011f482251c238b329c5c` |
| #144 MASTER-01 | Context only | `d05531ff81b8b8119ffb86db6405aac12c376aad` |
| Antigravity F03 | Original audit suite commit | `75a7a648984d9883774292f35a511089e6ffd474` |

## Integration branch

| Field | Value |
|---|---|
| Branch | `cursor/master-02-integration-candidate-316a` |
| Merge order | main → #140 → #142 → #136 (complete parent history) → #139 → #141 |
| Merge strategy | `git merge --no-ff` (exact source tips as second parents) |
| **Merge-tip HEAD** | `7fb78a3d9c522edff26335a551ceadc5d500f941` |
| **Merge-tip TREE** | `7a980d4ae918bc4dbec374772a2ec20e36d3107f` |
| Tree digest (sha256 of tree hex) | `14a96085501bc36a2935ce569263dc6f6ce18c7aafb26315f0a55fb25ee99207` |
| Match MASTER-01 disposable tree | **YES** (identical to `ee8cb2a…` tree) |

## Merge ancestry (complete)

| Step | Merge commit | Parents (left = prior integration, right = source tip) | Tree |
|---|---|---|---|
| 1 F02 | `25b794a50689c7801b074fb586aa1f95c449206d` | `20a8546…` + `649d90f…` | `20940dd…` |
| 2 F03 | `d064b67bfe0c2e87f0efcec13cf857f2f31c19b9` | `25b794a…` + `9cdc22b…` | `42f929c…` |
| 3 L01 | `9434ff5de9937b5713061ca9cda26250ff7cdca9` | `d064b67…` + `9cb864c…` | `5c05657…` |
| 4 L02 | `ef90c8b881d8a9d875bed98872d5e00be2c483fd` | `9434ff5…` + `38e0d31…` | `66b7d76…` |
| 5 B3 | `7fb78a3d9c522edff26335a551ceadc5d500f941` | `ef90c8b…` + `66ce8ae…` | `7a980d4…` |

L01 merge includes complete parent history: tip `9cb864c…` already contains Kernel streaming base `15befec…` (66 commits) + L01 delta (10 commits).

## Explicit exclusions / protections

- **#143 entirely excluded** — neither current nor MASTER-01 tip is an ancestor of the merge tip.
- **Protected `main` unchanged** at `20a8546…`.
- **Source PR heads not rewritten** — preserved as merge parents.
- Post-merge **test-harness / docs commits** (if present on the PR tip) are separately traceable and do **not** alter the merge-tip tree identity above.

## Machine-readable

See repo `docs/orneur/milestones/master-02/evidence/merge-ancestry.json` (committed with evidence package).
