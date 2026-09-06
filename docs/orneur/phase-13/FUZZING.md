# Phase 13.1 — Fuzzing / Property Testing

## Framework

No new dependency added — Hypothesis is not installed in this
environment, and spec §18 explicitly permits a bounded, deterministic
mutation generator instead ("Do not add an enormous dependency solely
for this phase unless justified"). `tests/test_redteam_fuzz.py` uses
`random.Random(SEED)` with a **fixed, recorded seed**: `SEED = 20260904`
(the date this file was written), so every run is byte-for-byte
reproducible. `CASES_PER_FAMILY = 25` (exceeds the spec's 20+ minimum).

## Target families (11 tests total)

| Family | Property tested | Cases | Bugs found |
|---|---|---|---|
| Godmode canonicalizer | Key-order invariance | 25 | 0 |
| Godmode canonicalizer | Bool/int never collide | 25 | 0 |
| Godmode canonicalizer | Unicode NFC/NFD always equal | 25 | 0 |
| Godmode canonicalizer | Tampered payload never collides with original | 25 | 0 |
| Godmode canonicalizer | Array order is significant (sanity check) | 25 | 0 |
| Resource-scope matching | Normalization never widens scope | 25 | 0 |
| Resource-scope matching | Case/trailing-slash variants match | 25 | 0 |
| Filesystem path resolution | No traversal variant escapes root | 25 | 0 |
| Filesystem path resolution | Absolute paths outside root always rejected | 25 | 0 |
| URL/SSRF guard | Known bypass variants (17 curated: decimal/hex/octal IP, IPv6, userinfo, metadata IP, mixed scheme) all rejected | 17 | 0 |
| URL/SSRF guard | Case/whitespace variants of loopback all rejected | 25 | 0 |

**Zero bugs found across all 11 fuzz families.** This is reported as real
evidence of robustness in these four specific mechanisms
(`orca.godmode.canonical`, `orca.godmode.resolution._canonicalize`,
`orca.godmode.file_elevation._resolve_within_root`,
`orca.truth.fetch._is_ssrf_risk`), not a claim that fuzzing "found
nothing is wrong anywhere" — see `PHASE_13_FINAL_CLOSURE.md` for the two
real vulnerabilities this phase's OTHER (non-fuzz) campaigns did find.

## Note on the canonicalizer depth bomb

The Godmode canonicalizer's real vulnerability found this phase (RES-01,
see `RESOURCE_EXHAUSTION.md`) was found by a **targeted depth-escalation
probe** (`_build_nested(depth)` at increasing depths), not by the random
mutation fuzzer above — the random generator's `_random_nested_value()`
caps recursion at `depth >= 3`, so it never explores deep enough to
trigger the crash. This is disclosed honestly: the fuzz harness and the
targeted resource-exhaustion probe are complementary, not redundant, and
neither alone would have found everything the other found.
