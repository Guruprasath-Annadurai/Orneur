# Phase 9 — Credential Security

## Opaque references only

`ConnectorCredentialRef` never carries a secret value -- only a
`credential_ref_id` and `auth_mode`. Resolution to an actual credential
happens only at the connector execution boundary (a future real
provider's adapter dispatch); no credential value is ever constructed as
part of `orca.connectors.contracts`, and none of the dataclasses defined
here have a field that could hold one.

## No real third-party credential storage exists yet

Per `CURRENT_CONNECTOR_ARCHITECTURE.md`'s audit: this codebase has no
OAuth flow, no encrypted-at-rest credential vault, and no real
GitHub/Slack/Drive/Calendar/Ticketing/CRM/Database client. This is
disclosed honestly, not glossed over -- see CONNECTOR FAMILIES in the
final Phase 9 report. `ConnectorCredentialRef` is the CONTRACT for where
such a credential resolution would plug in; building the actual
credential vault and OAuth flows is out of scope for this phase and is
listed as a remaining blocker.

## Redaction

`orca.connectors.security.redact_secrets()` applies a bounded, tested
regex pattern list (API keys/tokens/passwords, OpenAI `sk-`, GitHub
`ghp_`, Slack `xox[baprs]-`, PEM private keys) to any free-text field
(audit `operation` strings, tool result error messages) before it is
ever recorded. `orca.connectors.audit.record_audit_event()` applies this
unconditionally to the `operation` field. Verified directly against each
pattern class in `tests/test_connector_security.py`.
