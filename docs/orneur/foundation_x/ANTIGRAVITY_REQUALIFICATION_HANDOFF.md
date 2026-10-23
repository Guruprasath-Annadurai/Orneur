# Antigravity requalification handoff — P0 foundation security recovery

Do not merge. Do not train. Do not treat Linux CI as Darwin qualification.

## Stack (preserve; do not flatten onto main)

| PR | Branch | Audited / expected role |
|---|---|---|
| #80 | `cursor/orneur-pretraining-foundation-p0-4e55` | `fc1eb1dd098377e8506485dbcd82d6ed148b52b3` |
| #82 | `cursor/foundation-x-rag-x-4e55` | `177f54801eeaa079b67c9290ed89e3df0b3f6278` stacked on #80 |
| recovery | `cursor/p0-foundation-security-recovery-c04e` | stacked on #82; requalify `git rev-parse HEAD` on this branch |

## Commands

```bash
git rev-parse HEAD
git merge-base --is-ancestor 177f54801eeaa079b67c9290ed89e3df0b3f6278 HEAD
python3 -m pytest tests/test_darwin_f_getpath_native.py tests/test_authorized_index_adversarial.py tests/test_foundation_lifecycle_grant_liveness.py tests/test_truth_authorized_index.py tests/test_rag_x_foundation.py tests/test_cursor_progress_db_portability.py tests/test_genesis_governance_authorization.py -v
python3 -m pytest tests/test_genesis_data_pipeline.py tests/test_genesis_tokenizer.py tests/test_genesis_checkpoint_integrity.py tests/test_connector_document_store.py tests/test_connector_tenant_isolation.py tests/test_connector_federated_retrieval.py tests/test_g006_tenant_isolation.py -v
bash scripts/ci/run_deterministic_tests.sh
```

Darwin (authorized Mac only; do not mock success):

```bash
python3 -m pytest tests/test_darwin_f_getpath_native.py -v
# Must execute test_native_darwin_* rather than skip them.
```

Vulnerable-commit reproduction (read-only; Darwin crash may abort the process):

```bash
git switch --detach fc1eb1dd098377e8506485dbcd82d6ed148b52b3
# Darwin: invoke orca.genesis.data.pipeline._darwin_descriptor_path on an open directory fd
git switch --detach 177f54801eeaa079b67c9290ed89e3df0b3f6278
# Lifecycle: assess_lifecycle on an integrity-valid expired NativePretrainingGrant
# Index: parent symlink and SHA-256-only coordinated edit
```

## Linux results in this engineering run

- Focused security/foundation: 98 passed, 3 skipped (the three native Darwin tests).
- Pipeline / tokenizer / checkpoint / connector / tenant: 99 passed, 4 skipped, 2 xfailed.
- Acceptance ledger: `docs/orneur/acceptance/acceptance_ledger.json` is `[]`.

Report skipped, deselected, and xfailed tests separately. A crashing Darwin test is a fail, not a skip.

## Honest limits

- HMAC authenticity assumes the process can keep `.mac.key` out of the untrusted index body. An attacker who can write the key file can mint MACs.
- Contradiction scan is lexical (`KEY=value` and copula). Unextractable discourse is `uncertain`, not model-backed entailment.
- `TrustedOllamaEncoder.qualified()` requires the backend to return a `model` field on embed. An HTTP probe is not qualification.
- Lifecycle completeness is never training authorization.
