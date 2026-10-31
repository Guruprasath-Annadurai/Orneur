# GENESIS Foundation Sprint 2 — Workstream F: Native Pretraining Training Governance Foundation

Status date: 2026-10-16. Branch: `claude/genesis-workstream-f-2026-10-16`,
branched from **PR #55's exact head, `88ac6da8450f7751e002aa243053c541d5eae4e5`**
(GENESIS Foundation Sprint 1) -- the lowest valid existing dependency
(Mission F6), not PR #61 or PR #63. **No native pretraining, no
model-weight modification, no founder signing-key provisioning, no real
signed training grant, no GPU provisioning or spend, no merges, and no
change to frozen acceptance criteria occurred anywhere in this work.**

## Mission F5 — Workstream A findings preserved, not silently fixed

Posted A-07 through A-11 as independent-review targets on PR #63 (GitHub
comment, not a code change): unbounded accepted-record/shard-list memory
accumulation, resume potentially overwriting prior shard contents, manifest
loading without automatic re-verification, insufficient cryptographic
binding of transformation lineage/tokenizer file/produced shards to the
manifest ID, and a `clean=True` read that can be vacuously true when no
checks ran. **None of these were fixed in this workstream** -- per explicit
instruction, Workstream F does not fix Workstream A defects itself; it
flags them for independent Antigravity review and, in its own design,
**refuses to treat unqualified Workstream A dataset evidence as sufficient
for training authorization** (see Mission F3 below).

## Mission F1 — Existing authority-system investigation

Two separate, real, already-built trust systems were found, neither of
which represents GENESIS native pretraining correctly today:

1. **`orca.train.authorization`**: the per-run operational gate for the
   LoRA/QLoRA fine-tune path. Real: Ed25519-signed records, a pinned
   (empty) authority-key registry, an append-only hash-chained audit log,
   a durable on-disk run-slot ledger. Its shape is built around
   `TrainingConfig` -- no dataset-manifest-identity field, no
   architecture-version concept, and (per PR #61's own C-01 finding) its
   records carry nothing that structurally distinguishes a LoRA grant from
   a GENESIS-intended one except a `cfg_fingerprint` a caller could
   coincidentally satisfy.
2. **`scripts/acceptance/acceptance_engine.py`**: the project-wide
   requirement-acceptance ledger governing whether GENESIS native
   pretraining has been independently reviewed and founder-accepted AT ALL
   as a readiness milestone (R65/G1/AUTH-1/FINAL-1 and 91 further rows).
   `docs/orneur/acceptance/acceptance_ledger.json` is `[]` and
   `PINNED_BOOTSTRAP_ROOT_KEYS` is an empty `frozenset()` -- **confirmed by
   a direct test in this workstream** (`test_the_real_acceptance_ledger_is_empty_and_denies_everything`)
   that calling this engine's own `evaluate()` against the real, committed
   files returns nothing accepted for any of the four gating rows this
   workstream requires.

Also inspected: GENESIS Workstream C's `RunIdentity`/`GenesisTrainingRun`
(PR #61, mutable dataset-digest field, no replay-resistant nonce concept at
the authorization layer), Workstream A's `GenesisDatasetManifest` (PR #63,
real content digests but no binding to a training-authorization record),
checkpoint verification (`checkpoint_integrity.py`, PR #58, independently
under `CONDITIONAL_REMEDIATION_REQUIRED`), and the existing NO-GO controls
(`NATIVE_MODEL_TRAINING_AUTHORIZATION = NO-GO` stated throughout this
program's own prior directives, now additionally enforced structurally by
this module's mandatory, currently-unsatisfiable founder-acceptance check).

**Decision**: do not build a duplicate security system, and do not
silently repurpose a LoRA grant as native-pretraining authorization. A new
signing domain, schema, and registry were built
(`orca/genesis/governance/authorization.py`), reusing the Ed25519/pinned-
registry/sealed-grant DESIGN PATTERN `orca.train.authorization` already
established, but as a genuinely separate, non-interchangeable trust root
(see Mission F2).

## Mission F2 — Native pretraining authorization contracts

`orca/genesis/governance/authorization.py`'s `NativePretrainingRequest` /
signed-record schema covers every required binding field:

| Required field | Implemented as |
|---|---|
| Unique training run ID + replay-resistant nonce | `run_id`, `nonce` (checked for format, matched exactly, AND tracked against replay -- see F4) |
| Exact model family + architecture version | `model_family`, `architecture_version` |
| Model configuration digest | `model_config_digest` -- real SHA-256, via `_content_digest()` over the actual dataclass fields |
| Tokenizer model/content digest | `tokenizer_digest` |
| Dataset manifest identity | `dataset_manifest_id` |
| Exact authorized dataset-shard content hashes | `authorized_shard_digests` (tuple, order-independent comparison, every entry format-checked) |
| Transformation/code identity | `transformation_code_digest` |
| Training optimizer and hyperparameter configuration | `optimizer_config_digest` |
| Authorized repository/code revision | `reviewed_commit_sha` |
| Hardware environment | `environment_class` |
| GPU/runtime limits | `gpu_allowed`, `max_wall_clock_minutes` |
| Maximum spend, currently zero | `max_spend_usd` -- **structurally required to equal exactly 0**; any non-zero value in the record OR the request is rejected (`SPEND_MUST_BE_ZERO_WHILE_NOGO` / `SPEND_REQUESTED_WHILE_NOGO`) |
| Authorization issuance and expiry | `issued_at`, `expires_at`, bounded to a 14-day max validity window |
| Founder authority identity | `authorizing_authority: {identity, role, key_id}`, verified against the (empty, pinned) registry |
| Cryptographic verification + revocation status | Ed25519 signature over a GENESIS-specific `SIGNING_DOMAIN`; revocation-id list check |

**The committed registry, record, and revocations files are empty/
`NOT_AUTHORIZED`, exactly like `orca.train.authorization`'s own.**
`PINNED_REGISTRY_SHA256` is hardcoded (not computed at import time from
`empty_registry()`, which would make the pin trivially self-satisfying
regardless of the real on-disk file -- a design mistake caught and fixed
during implementation, see below) and verified to match the real committed
file by a dedicated test. All synthetic testing uses freshly generated,
in-memory-only Ed25519 keys, written to no real file.

## Mission F3 — Fail-closed governance integration

- **Dataset identity from verified contents, not a caller digest**:
  `DatasetManifestLike` is a `Protocol` (not a hard import of
  `orca.genesis.data.manifest.GenesisDatasetManifest` -- Mission F6
  isolation) requiring `verify_against_records()`; this module's design
  requires dataset identity to come from that re-verification, never from
  trusting a bare string, mirroring exactly the model-config digest's own
  `_content_digest()` derivation from a real object.
- **Exact workload binding**: `verify()` checks all 19 binding fields
  exhaustively; a signature alone is insufficient if any field mismatches.
- **No fabricated record, matching string, or synthetic LoRA grant can pass
  superficial checks**: `verify_signature()` requires the registered key's
  role/identity to match AND the signature to verify over the GENESIS-
  specific `SIGNING_DOMAIN` -- a `TrainingGrant` from `orca.train.authorization`
  cannot satisfy this type at all (different Python class, different
  signing domain, different registry file). `NativePretrainingGrant` can
  only be constructed via the module-private seal (same unforgeable
  pattern as `TrainingGrant`).
- **Mandatory live revocation at execution boundaries**: `assert_execution_permitted()`
  (the Workstream-C-equivalent "start-time" re-check) REQUIRES a
  `revocation_check` callable -- `None` is rejected
  (`REVOCATION_CHECK_REQUIRED`), and if the callable itself raises (the
  service is unavailable), that is ALSO a denial
  (`REVOCATION_CHECK_UNAVAILABLE:...`), never a silent pass. The exact
  same mandatory (non-optional) design is enforced at `authorize_native_pretraining()`
  itself.
- **Strict distinction preserved**: `NativePretrainingGrant` has NO
  progress, completion, or evaluator-approval field at all -- confirmed by
  a structural test (`test_the_grant_object_carries_no_progress_completion_or_evaluator_fields`).
  Execution evidence and evaluator approval remain Workstream C's own,
  separately-verified responsibility (`ExecutionEvent`/`CompletionEvidence`/
  `EvaluatorApprovalClaim`); this module's grant is purely a permission
  object and cannot be used to smuggle a forged progress or approval claim.

## Mission F4 — Adversarial acceptance tests

`tests/test_genesis_governance_authorization.py`, **34/34 passing**, real
Ed25519 synthetic keys via a dedicated `World` fixture (same pattern as
`tests/test_training_authorization_gate.py`'s own, never touching the real
committed files):

| Required case | Covered by |
|---|---|
| 1. Wrong-model grant substitution | `test_wrong_model_config_digest_is_rejected`, `test_wrong_architecture_version_is_rejected` |
| 2. Wrong-dataset grant substitution | `test_wrong_dataset_manifest_id_is_rejected`, `test_wrong_dataset_content_digest_is_rejected` |
| 3. Tampered tokenizer/model configuration | `test_tampered_tokenizer_digest_is_rejected`, `test_tampering_a_signed_field_after_signing_invalidates_the_signature` |
| 4. Changed training shards after authorization | `test_changed_authorized_shards_after_authorization_is_rejected`, `test_an_extra_unauthorized_shard_added_to_the_request_is_rejected` |
| 5. Reused or expired grants | `test_an_already_expired_record_is_rejected`, `test_a_validity_window_longer_than_the_max_is_rejected`, `test_reusing_the_same_nonce_twice_is_rejected` |
| 6. Revocation during pause and recovery | `test_assert_execution_permitted_denies_on_live_revocation` |
| 7. Missing revocation authority | `test_missing_revocation_authority_denies_even_with_everything_else_valid`, `test_assert_execution_permitted_requires_a_revocation_check`, `test_assert_execution_permitted_denies_on_an_unavailable_revocation_service` |
| 8. Process restart and replay | `test_reusing_the_same_nonce_twice_is_rejected`, `test_reset_in_process_nonce_guard_allows_a_simulated_new_process` (explicitly documents the in-process-only boundary -- see Known Limitations) |
| 9. Forged progress records | `test_the_grant_object_carries_no_progress_completion_or_evaluator_fields` (structural: no such field exists to forge) |
| 10. Forged independent evaluator approval | same structural test |
| 11. Resource requests exceeding the signed budget | `test_requesting_more_wall_clock_than_authorized_is_rejected`, `test_any_nonzero_spend_request_is_rejected_while_no_go`, `test_a_record_with_nonzero_max_spend_is_rejected_structurally`, `test_requesting_gpu_without_gpu_permission_is_rejected` |
| 12. Unauthorized transition toward training execution | `test_a_hand_constructed_grant_lookalike_is_rejected`, `test_grant_cannot_be_pickled_or_copied`, `test_assert_execution_permitted_denies_on_tampered_grant` |

Plus: `test_authorize_against_the_real_repo_state_is_denied` (confirms the
REAL repo, unmodified, denies every request), and three tests confirming
the real committed registry/record/ledger are exactly as claimed.

## A design mistake found and corrected during implementation

The first draft computed `PINNED_REGISTRY_SHA256 = registry_digest(empty_registry())`
at import time -- this makes the "pin" trivially self-satisfying regardless
of what is actually written to `REGISTRY_PATH` on disk, defeating the
entire point of pinning (the real security property is "the FILE ON DISK
must match a value fixed independently of whatever that file currently
contains"). Caught before committing by re-reading the pattern
`orca.train.authorization.PINNED_REGISTRY_SHA256` actually uses (a
hardcoded hex literal, separately verified to equal the committed file's
digest) -- fixed by computing the value once and hardcoding it as a literal,
with a dedicated test (`test_the_real_committed_registry_is_empty_and_pinned`)
confirming the hardcoded constant matches the real committed file.

A second test-construction bug was also caught and fixed before being
reported as passing: the `World.authorize()` test helper originally could
not distinguish "caller passed `revocation_check=None` to test the
mandatory-check requirement" from "caller didn't pass anything, use the
default" -- both collapsed to the same default lambda, silently defeating
`test_revocation_check_is_mandatory_not_optional`. Fixed with an explicit
sentinel default.

## Mission F6 — Branch dependencies

Branched from PR #55 (Sprint 1) exact head `88ac6da` -- not PR #61 or
PR #63. The CORE governance contract is deliberately import-isolated: it
uses a `Protocol` (`DatasetManifestLike`) rather than importing
`orca.genesis.data.manifest.GenesisDatasetManifest` (PR #63) or
`orca.genesis.training.orchestration.GenesisTrainingRun` (PR #61) at all --
confirmed by this branch containing neither PR's own files.

**NOT yet implemented in this workstream**: a genuine end-to-end
integration test binding a real `GenesisDatasetManifest` object (PR #63)
and a real `GenesisTrainingRun` (PR #61) through this new authorization
layer together, in one call chain. Per Mission F6's own instruction, this
would require "a separate draft integration branch with exact ancestry,
explicitly recording that both parents remain unaccepted" -- not attempted
in this already-substantial increment. This is the explicit next
engineering requirement (see below), not silently claimed as done.

## Mission F7 — Testing and handoff, truthful status per requirement

| Requirement | Status |
|---|---|
| F1 investigation | `IMPLEMENTED`, `TESTED` (3 dedicated tests confirm real repo state) |
| F2 authorization contract (all 19 binding fields) | `IMPLEMENTED`, `TESTED` |
| F3 fail-closed integration (dataset-identity-from-verification contract, mandatory revocation, strict evidence separation) | `IMPLEMENTED`, `TESTED` |
| F4 adversarial acceptance tests (all 12 categories) | `IMPLEMENTED`, `TESTED` |
| F5 Workstream A findings preserved | `IMPLEMENTED` (posted to PR #63) |
| F6 isolated governance contracts (Protocol-based, no PR #61/#63 import) | `IMPLEMENTED`, `TESTED` |
| F6 cross-branch end-to-end integration test (real `GenesisDatasetManifest` + real `GenesisTrainingRun` together) | `NOT_IMPLEMENTED` -- explicit next requirement |
| CI on this exact commit | pending at time of writing -- will be reported once pushed and observed |
| Independent audit | `READY_FOR_INDEPENDENT_AUDIT` for everything marked `IMPLEMENTED`/`TESTED` above |

Full regression (`/Users/ag/orca/.venv`, Python 3.11.15):

```
tests/test_genesis_governance_authorization.py ....................... 34 passed
tests/test_acceptance_engine.py (unmodified) .......................... all passing
tests/test_genesis_model_architecture.py, test_genesis_training_primitives.py,
tests/test_genesis_tokenizer.py, test_genesis_eval_v1.py,
tests/test_training_authorization_gate.py (all pre-existing, unmodified) ... all passing

== 321 passed in 74.77s ==
```

No existing file was modified; this workstream added two new files
(`orca/genesis/governance/authorization.py`,
`tests/test_genesis_governance_authorization.py`) plus the three committed-
empty JSON files under `docs/orneur/authorization/genesis_native_pretraining/`.

## Known limitations (not claimed as solved)

- The nonce-replay guard (`_consumed_nonces`) is explicitly in-process-only,
  the same documented limitation as Workstream C's own
  `_consumed_authorization_ids` -- a genuinely durable, cross-process replay
  defense would need its own on-disk ledger (not attempted; would risk
  duplicating `orca.train.authorization`'s own ledger if done carelessly).
- `check_founder_acceptance_ledger()` passes `trust_snapshot=None`/
  `root_state=None`/`bootstrap_root_key_hex=""` to the real
  `acceptance_engine.evaluate()` -- correct and sufficient for today's
  EMPTY ledger (which short-circuits before touching trust material, per
  that engine's own docstring), but this call would need real trust
  material wired in once the ledger is ever non-empty; not needed or
  attempted here since the real ledger is empty.
- No cross-branch integration test yet (see Mission F6 above) -- the single
  largest remaining gap before this contract could be considered complete
  end-to-end.
- This module does not itself determine WHO is allowed to become a
  registered authority key -- provisioning real keys remains an explicit,
  separate, founder-approved action this module cannot take and does not
  attempt to automate.

## Verdict

**`READY_FOR_INDEPENDENT_AUDIT`** for the governance contract as
implemented and tested above (Missions F1-F5, and F6's isolation
requirement). The cross-branch end-to-end integration test (Mission F6's
second half) is `NOT_IMPLEMENTED` and is the explicit next engineering
requirement. No native pretraining, GPU use, spend, merges, founder
signing-key provisioning, or real signed training grant occurred or was
issued anywhere in this work. `NATIVE_MODEL_TRAINING_AUTHORIZATION` remains
`NO-GO`, now additionally enforced structurally by this module's mandatory
and currently-unsatisfiable founder-acceptance check.
