# Phase 10 — Authority Levels

```python
class AuthorityLevel(str, Enum):
    UNTRUSTED = "UNTRUSTED"
    NORMAL = "NORMAL"
    PRIVILEGED = "PRIVILEGED"
    ELEVATED = "ELEVATED"
    GODMODE = "GODMODE"
```

Named distinctly from "ultra" (confirmed by
`CURRENT_AUTHORITY_ARCHITECTURE.md` to be an unrelated commercial/model-
tier term) to avoid conflating two unrelated concepts.

## Critical rule

**Level alone never grants a capability.** `AuthorityLevel` appears only
as context/policy input on `GodmodeSession` (`requested_level`,
`effective_level`) — no function in `orca/godmode/` takes an
`AuthorityLevel` and returns a capability set. The actual grant always
comes from resolving a named `CapabilityLease` through
`orca.godmode.resolution.resolve_lease()`. A session at
`AuthorityLevel.GODMODE` with zero active leases can execute exactly
zero elevated actions — this is a structural property, not a policy
choice that could be misconfigured, because
`compute_effective_capabilities()` and `evaluate_elevated_policy()` both
require an explicit `lease_id`, never a level.

## Rank

`level_rank()` gives a total order (UNTRUSTED < NORMAL < PRIVILEGED <
ELEVATED < GODMODE) for logging/display and for a future policy that
might want to say "PRIVILEGED or above may request elevation" — this
ordering is never consulted by `resolve_lease()`/`evaluate_elevated_policy()`
themselves, which only ever look at the specific lease named.
