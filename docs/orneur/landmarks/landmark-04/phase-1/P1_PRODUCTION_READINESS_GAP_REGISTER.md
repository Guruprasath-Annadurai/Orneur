# P1 — Production Readiness Gap Register

Readiness ladder (kept separate on purpose): ENGINEERING COMPLETE → STAGING CANDIDATE READY → INDEPENDENTLY QUALIFIED → PUBLIC RELEASE READY.
**This work claims at most: engineering verified, independent qualification pending.** No staging-readiness, qualification or launch claim is made. No public launch is authorised.

| Gate | State | What is missing |
|---|---|---|
| Engineering complete (Phase 1 scope) | achieved for the verified items in the other documents | open items P1-X-01…09 |
| Staging candidate | **not asserted** | a reproducible build + operational configuration have not been exercised in a staging environment; production image installs no `chromadb` (inherited L03-B6, vector features inactive there) |
| Independent qualification | **pending** (Antigravity) | the whole handoff |
| Public release | **not ready** | everything below |

## External / founder-controlled blockers
| Item | Type | Detail |
|---|---|---|
| Real email delivery (verification, reset) | BLOCKED_EXTERNAL | needs an authorised mail service, sending domain, SPF/DKIM, credentials; only the local sink was used |
| Provider capacity / external providers | BLOCKED_EXTERNAL | only a local 1B model; no external provider, key, budget or spend policy exists or was used |
| Metering of background model calls | founder policy | P1-X-04 |
| MFA recovery model | founder/security decision | P1-X-02 |
| Billing / plans / pricing | not touched | no policy invented |
| Deployment, TLS/HSTS, CDN/WAF, secrets management, backups, monitoring, incident process | not exercised | no deployment is authorised |
| Privacy/legal review of data handling and retention | not performed | |
| Scaling beyond one workstation | not measured | no capacity claim |
| Accessibility certification (screen readers, contrast, zoom) | not performed | P1-X-08 |
| Browsers other than Chromium; real devices | not run | |
| CSP nonce migration | engineering follow-up | P1-X-03 |

## Governance (unchanged by this work)
`FORMAL_PRETRAINING_ACCEPTANCE = 0/95` · `TRAINING_AUTHORIZATION = NOT_AUTHORIZED` · `GENESIS = INTERFACE_ONLY` · `NOVUS = NOT_AVAILABLE` · `AETERNUM = NOT_AVAILABLE`. No training, corpus, GPU, trust-root, billing, deployment, tag or merge action was taken.
