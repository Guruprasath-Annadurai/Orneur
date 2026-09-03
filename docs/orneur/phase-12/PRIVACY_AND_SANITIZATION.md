# Phase 12 — Privacy, Tenant Boundaries, Sanitization

## Tenant/privacy classes (spec §13)

`PrivacyClass`: `PUBLIC | INTERNAL | TENANT_PRIVATE | RESTRICTED`.
`TrainingDestination`: `TENANT_EVAL_ONLY | TENANT_LOCAL_TRAINING |
GLOBAL_TRAINING_ELIGIBLE | DISALLOWED`.

`orca.learning.pipeline.make_candidate_from_event()` maps privacy class to
destination:

| `privacy_class` | `training_destination` |
|---|---|
| `TENANT_PRIVATE` | `TENANT_LOCAL_TRAINING` |
| `PUBLIC` | `GLOBAL_TRAINING_ELIGIBLE` |
| `INTERNAL` / `RESTRICTED` | `TENANT_EVAL_ONLY` |

Enterprise/private connector content defaults `TENANT_PRIVATE`
(`signals.py::from_connector_failure`) — never `GLOBAL_TRAINING_ELIGIBLE`
by default, matching spec §13's explicit requirement.

## Enforcement (spec §64, §13)

`orca.learning.security.enforce_tenant_boundary()` is a second,
independent check beyond the default routing above — it raises
`TenantExfiltrationBlocked` if anything ever attempts to move a
`TENANT_PRIVATE` candidate to `GLOBAL_TRAINING_ELIGIBLE`, or to move it
into `TENANT_LOCAL_TRAINING` for a *different* tenant than its own
`source_lineage` tenant tag. Tested directly:
`test_tenant_boundary_blocks_global_training_for_tenant_private_candidate`,
`test_tenant_boundary_blocks_cross_tenant_local_training`.

## Sanitization (spec §14)

`orca.learning.sanitize.sanitize_for_candidate()` reuses TWO existing
redaction implementations rather than a third:

- `orca.serve.dlp.scan_output` — PII flagged (not redacted, matching its
  own documented posture that a user's own data isn't a leak), secrets
  redacted.
- `orca.connectors.security.redact_secrets` — a second, slightly
  different secret-pattern list (Slack/GitHub-token shapes) run on top.

**Unlike `scan_output`'s chat-output posture** (best-effort redact and
still return the response to the user), a candidate that trips ANY secret
pattern is REJECTED outright, not admitted with best-effort redaction —
this content will be durably persisted and versioned, so the bar is
higher than a single chat turn. `SanitizationResult.rejected=True` +
`reject_reasons` communicate this; the pipeline drops the candidate and
increments `AUDIT.SECRET_IN_CURRICULUM`.

## Adversarial input marking (spec §15)

Jailbreak/adversarial samples are marked via `SecurityClass.ADVERSARIAL_INPUT`
is available on the enum for future adversarial-corpus candidates, and
`orca.learning.security.scan_for_poisoning_attempt()`/
`assert_no_poisoning_attempt()` explicitly treat any candidate's own
source text as inert data — never as an instruction that could change
compiler policy (see `SECURITY.md`).
