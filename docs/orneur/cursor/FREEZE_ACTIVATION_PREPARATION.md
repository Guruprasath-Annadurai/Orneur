# Prepared freeze activation

Status: `NOT_ACTIVATED`

This file prepares the governance change. It does not apply it. `tests/test_evalinfra_governance.py` is unchanged. `test_no_frozen_or_private_path_differs_from_the_branch_point` still requires an empty diff against the historical baseline and still fails on the three denial files.

Baseline: `cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d`

Proposal SHA-256: `08daabb09d79c22b241691bc92c8a519f065519303a368cb44e5afb972f6996a`

| Path | SHA-256 |
| --- | --- |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORITY_REGISTRY.json` | `13874861f20d7eabf7da5ed3f4ef8875046467ee51b6fa165b605a6245c75d84` |
| `docs/orneur/authorization/genesis_native_pretraining/AUTHORIZATION.json` | `88d0379632963cd4f871701c74ef55d50d54027f4bd8621e07e623081a61ea49` |
| `docs/orneur/authorization/genesis_native_pretraining/REVOCATIONS.json` | `2b5da1678f8fd35b35fc8a9153ed7c011fc8d776a39be31fbfdccfbf7c9300e3` |

## The gate that is not wired

`orca.founder_enrollment.future_exception_applies` returns true only when the frozen-diff reasons, the approval problems, and the enrollment problems are all empty, and the operational observation anchor is the established pin. In this commit the pin is absent, and a loader that claims a pin is caller-supplied, so the function returns false. The live test does not call the function.

A later commit may wire the test only after a real enrollment is independently pinned and a founder signature over `orneur-freeze-amendment-approval/1` verifies. That commit must keep `cd6af2a` as the baseline. It must not point the test at a newer tree. The only permitted difference remains the three paths and digests above.

The wired test must still fail closed when `cd6af2a` is absent. It must still reject:

- an unauthorized fourth file
- modified bytes in any of the three permitted files
- a deleted or modified historically frozen file
- changed acceptance-ledger content
- changed training authorization or trust roots
- missing approval provenance
- a forged, revoked, replayed, or conflicting signature
- a synthetic identity, a witness who holds the founder key, a stale enrollment, and an unknown key

`classify_diff` in `orca/freeze_amendment.py` is the diff classifier those rejections use. `review_approval_binding` is the approval check. `gate_problems` adds `synthetic_key_refused` for every synthetic review and `independent_anchor_absent` while the pin is missing.

## What this commit does not change

The acceptance ledger, the register graph, `orca/train/authorization.py`, and the pinned trust-root files stay at the baseline bytes. The three denial files stay at the digests above. `evaluate` still returns `activated` false. GENESIS stays `INTERFACE_ONLY`. NOVUS and AETERNUM stay `NOT_AVAILABLE`. Formal acceptance stays 0/95.
