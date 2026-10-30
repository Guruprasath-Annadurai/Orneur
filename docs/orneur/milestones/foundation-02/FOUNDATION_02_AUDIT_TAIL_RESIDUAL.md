# FOUNDATION-02 Audit-Tail Truncation Residual

**Status:** Unresolved residual — **not** a pass  
**Test:** `tests/test_training_authorization_assurance.py::test_truncating_the_audit_log_tail_is_detected`  
**Marker:** `@pytest.mark.xfail(strict=True)` (expected failure; must not silently flip)

## Reproduction

1. Authorize once (writes a `TRAINING_AUTHORIZED` event into `events.jsonl`).
2. Append a later event.
3. Truncate the file to the first line only (drop the tail).
4. `verify_event_chain(state)` still returns `True` because the remaining prefix is a valid hash chain starting from genesis.

## Impact within the supported threat model

| Actor | Can truncate `events.jsonl`? | Effect |
|---|---|---|
| Remote network attacker without host FS write | No | No impact |
| Caller through ORNEUR APIs without state-dir write | No | No impact |
| Local operator / same-user process with state-dir write | Yes | Can remove prior `TRAINING_AUTHORIZED` events so `_authorized_event_count` under-counts |

Budget enforcement uses **two** ledgers: per-authorization slot files (`O_CREAT|O_EXCL`) and the audit event count. Truncating the audit tail alone does not recreate deleted slot files. Combined deletion of **both** the slot directory and the audit tail can reset `max_runs` while other grant bindings (signature, expiry, code-tree hash, dataset hashes) still apply.

This matches the documented residual already stated in `orca/train/authorization.py` and `TRAINING_AUTHORIZATION_ASSURANCE.md`: detecting tail truncation requires an append-only anchor **outside** the operator’s write access (remote sealed log / HSM / founder-held witness).

## Severity

**P2 — Residual integrity gap under local state-directory control.**  
Not a remote authorization bypass. Not an env-var bypass. Does not mint a grant without a signed `AUTHORIZED` record and pinned registry key (registry remains empty → NO-GO).

## Mitigation today

- Empty authority registry + `NOT_AUTHORIZED` record → nothing can authorize.
- Slot files still consume budget unless also deleted.
- Grant HMAC / seal / code-tree / dataset bindings still apply after any local reset.
- `xfail(strict=True)` keeps the residual visible; it is **not** counted as PASS.

## Why not “fixed” in FOUNDATION-02

A correct detection needs a high-water tip attested by a secret or service the operator cannot rewrite together with `events.jsonl`. FOUNDATION-02 does not provision founder keys, remote append-only infrastructure, or paid services. Shipping a tip file HMAC’d with a process-local key would not survive restart and would not stop an operator who deletes the tip file.

## Qualification dependency

Independent qualification may treat this as an accepted residual **only** if the threat model continues to exclude “operator with write access to the authorization state directory.” Closing it requires an external sealed audit anchor under founder/ops ownership.

## Non-claims

- This residual is **not** marked fixed.
- The xfail is **not** a pass.
- Training remains **NO-GO**.
