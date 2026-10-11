# Public Serving Authority — threat model and design

Status: **IMPLEMENTED_TESTED, NO_GRANTS_ISSUED, NOT_INDEPENDENTLY_AUDITED.** Nothing here promotes, qualifies, activates or deploys any model. The committed
authority registry has zero keys and the grants file is empty, so **no unqualified model is publicly served by this change**. RSE-ARCH-1.2, Manifest V3,
the model-promotion registry and every frozen contract are untouched.

## 1. Problem (reproduced against PR #25 head `0db1a59`, `scripts/security/serving_authority_repro.py`)

| Scenario (public edge) | PR #25 | This change |
|---|---|---|
| unqualified Novus, no flag | refused | refused |
| unqualified Novus, `ORNEUR_ALLOW_EXPERIMENTAL_SERVING=1` only | **served** | refused |
| the Novus artifact aliased onto the `nano` tier (`ORNEUR_NANO_MODEL=<novus tag>`) | **served** (labelled `LEGACY_PRODUCTION_SERVING` because the *tier* was `nano`) | refused (EXPERIMENTAL) |
| the documented legacy Genesis checkpoint `orca-nano-v7` | served (founder decision, kept) | served, pinned by artifact identity |
| private / local deployment | served | served |

An environment variable is not evidence, and a tier name is not an artifact.

## 2. Rules (all fail closed)

* **Flag:** `ORNEUR_ALLOW_EXPERIMENTAL_SERVING` is *reported* by `/api/models` (`experimental_flag_has_authorizing_effect: false`) and otherwise ignored.
* **Public edge + EXPERIMENTAL self-hosted model →** served only under a **public-serving grant** (`orca/gateway/serving_authority.py`):
  Ed25519 signature over `orneur-public-serving-grant/1\n` + canonical JSON (domain-separated: a training or eval signature cannot verify here);
  authority key from a registry whose canonical SHA-256 is **pinned in source**; names the exact `model_family`, `tier`, Ollama tag **and the artifact digest
  Ollama reports for that tag**; window ≤ 30 days; explicit eligibility (user ids and/or a signup-order cohort — no open-to-everyone grants; anonymous
  callers never eligible); an exact disclosure label that must state the model is *experimental* and *not qualified*; revocable by grant id or authority.
* **Digest binding:** the installed artifact's digest is read at request time (15 s cache). Re-pulling a different artifact under the same tag, a missing
  artifact, or an unreachable runtime → refused.
* **Legacy exemption** is pinned to artifact names (`LEGACY_GENESIS_ARTIFACTS = {orca-nano-v7}`), tier `nano`, family `orneur-genesis`. It is still labelled
  `LEGACY_PRODUCTION_SERVING` ("not the canonical, qualified Genesis model").
* **No silent downgrade:** a request for tier *X* that the registry steps down to another artifact is judged as *(X, that artifact)*. A grant for the core tier
  does not cover an ultra request served from the core artifact; fallback needs its own signed grant naming exactly that pairing.
* **Errors:** a routing refusal is `503 {"code":"model_unavailable"}` (SSE: `type:error, code:model_unavailable`) with a fixed message; no model name, lifecycle,
  grant or digest is disclosed.
* A grant is **not a promotion**: lifecycle stays `EXPERIMENTAL`, and the disclosure label travels with the decision (`/api/models` → `disclosure`).

## 3. Threats

| # | Threat | Mitigation | Test |
|---|---|---|---|
| S1 | flag/env promotes a model | flag has no authorizing effect | `test_the_flag_alone_never_authorizes_public_serving`, `test_no_value_of_the_flag_authorizes_the_public_edge` |
| S2 | alias / tier-name relabel inherits legacy status | exemption pinned to artifact identity | `test_pointing_the_nano_tier_at_another_model_…`, `test_only_the_pinned_legacy_artifact_is_legacy_…` |
| S3 | forged / unsigned / wrong-key / cross-purpose signature | pinned registry + domain separation | `test_unsigned_and_wrongly_signed_…`, `test_a_forged_registry_…`, `test_a_signature_for_another_purpose_domain_…` |
| S4 | edit after signing | signature covers every field | `test_any_edit_after_signing_breaks_the_signature` (8 fields) |
| S5 | stale / replaced artifact, missing artifact, runtime down | digest bound at request time | `test_scope_is_exact`, `test_wiring_serves_only_an_eligible_viewer_…` |
| S6 | config change after signing | tag/tier/family scope | `test_config_change_after_signing_is_not_covered` |
| S7 | expired / not-yet-valid / over-long grant | window checked, ≤ 30 days | `test_validity_window` |
| S8 | revoked grant or authority | revocation list, key flag | `test_revocation_of_the_grant_and_of_the_authority` |
| S9 | untruthful or over-broad grant | label must say experimental + not qualified; eligibility required | `test_structurally_unacceptable_grants_are_denied_even_when_signed` |
| S10 | stale persisted lifecycle record | lifecycle recomputed and re-saved each process | `test_a_stale_persisted_legacy_record_is_overwritten_…` |
| S11 | crash or information leak on refusal | classified as `model_unavailable` | `test_a_routing_refusal_is_a_clean_model_unavailable_error_…` |
| S12 | unreadable / malformed trust files | deny, never "nothing revoked" | `test_unreadable_or_malformed_trust_files_deny` |

## 4. Founder provisioning (NOT performed)

A public experiment requires: an offline Ed25519 key; a reviewed PR adding the authority to the registry **and** updating `PINNED_REGISTRY_SHA256`; a signed
grant naming the exact artifact digest, invited users or cohort, window and label; independent audit of that PR. Revoke by adding the id to
`PUBLIC_SERVING_REVOCATIONS.json`.

## 5. Behaviour changes to know

* **Genesis served under the default alias `orca-nano` is no longer treated as legacy** on a public edge (only `orca-nano-v7` is). If production runs the alias,
  set `ORNEUR_NANO_MODEL=orca-nano-v7` or it will be refused (503 `model_unavailable`). This is the cost of binding to an identity.
* `ORNEUR_ALLOW_EXPERIMENTAL_SERVING` no longer has any effect.
* `/api/models` gains per-tier `lifecycle`, `publicly_served`, `disclosure` (additive).

## 6. Residual risks / boundary (stop point)

* **Same-process trust.** The registry pin lives in the serving process's source tree: an attacker who can edit the code, the pin and the grants together, or run
  their own server, is outside what this code can stop. A *independently enforced* serving authority — a separate policy enforcement point the serving process
  cannot rewrite — would need an architectural change that touches the frozen RSE/Manifest boundary; **this is a design proposal only and I stopped there
  pending founder approval.**
* A grant proves the founder authorized an *experiment*, not that the model is safe or capable; **no independently verifiable qualification evidence exists
  for any ORNEUR model** (Genesis `NOT_TRAINED` canonical; Novus `EXPERIMENTAL / NOT_PROMOTABLE`).
* The digest is whatever the local Ollama reports; a compromised host can lie.
* Per-response lifecycle disclosure in chat/stream payloads (register G-015) is not added; only `/api/models` carries it.
* Frontier backends are not covered (not ORNEUR-trained; separate transparency notice).
* `/api/vision` calls a vision model directly and is not routed through the gateway.
