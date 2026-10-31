# FOUNDATION CONSOLIDATION — Tree Equivalence

```
STATUS: PREFLIGHT — DRY-RUN TREE == QUALIFIED #148 TREE
```

---

## 1) Qualified reference trees

| Identity | Commit | Tree |
|---|---|---|
| `main` | `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a` | `4707492d800aea61a4c6f159a1adf3d59d8a23d6` |
| #145 | `d8827409248dcdb5da55a010d8224d9e0e3bddbe` | `615c6a3483e64acc3bdb6ccc2d2351d4f63ca96e` |
| #146 | `b96cc3260078b6f677a22381b05fe1f72026256f` | `168a6a2c75bd11e0cbac113e06ff4d50e88f9cae` |
| #148 eng tip | `cadad0e525c5f84698af9945d048b9ba36aa4f0e` | `d1742759c1ecf25629f7bca1376719a75bd52d71` |
| #148 PR HEAD (qualified M04 tip) | `da699a01bdb811ac54ef00cf0c9585f70eb74a57` | **`106487db24a66672c7ca3e660a1d1e0792281238`** |

Eng tip tree ≠ PR HEAD tree (docs-only evidence-binding commits after eng). **Qualified consolidation target for tree compare = PR HEAD tree** `106487d…`.

---

## 2) Dry-run comparisons

| Compare | Left | Right | Result |
|---|---|---|---|
| Sequential `--no-ff` sim tip tree | `106487db24a66672c7ca3e660a1d1e0792281238` | #148 PR HEAD tree | **EQUAL** |
| Sequential `--ff-only` tip | commit `da699a0…` | #148 PR HEAD | **EQUAL** (same commit) |
| Direct merge index tree onto `main` | `106487db24a66672c7ca3e660a1d1e0792281238` | #148 PR HEAD tree | **EQUAL** |
| Sim tip tree vs eng tip tree | `106487d…` | `d174275…` | **NOT EQUAL** (expected: PR HEAD includes evidence docs) |

---

## 3) Meaning for founder decision

- A future founder-authorized merge that lands the current #148 tip content onto current `main` (FF or merge commit) yields **the same tree** as qualified M04 PR HEAD.
- Engineering code identity for Antigravity binding remains eng tip `cadad0e` / tree `d174275…`; PR HEAD additionally binds evidence docs.
- Tree equivalence of an isolated dry-run is **not** Phase H authorization.

---

## 4) Non-equivalence notes

| Pair | Relation |
|---|---|
| #149 tree `fc10e6d…` vs #148 | unrelated docs-only readiness package; **not** stack substitute |
| Antigravity `83978d4` tree `9c04e89…` vs #148 | qualification branch; **not** merged |
