# ORNEUR foundation and backend programme — engineering handoff

Date: 23 October 2026 (Asia/Calcutta). Engineering completion only. Independent acceptance is separate. This file does not write `docs/orneur/acceptance/acceptance_ledger.json`.

## Protected baselines (not production acceptance)

| Item | SHA | Status |
|---|---|---|
| PR #83 | `3833f55cad4d236a8023649918edbbf8be57de5e` | Protected engineering baseline |
| PR #86 Darwin lock race | `5d9c6f747169e3f74c7d100994fc64bef376afb4` (`c153b92` implementation) | Linux tests exist; native Apple Silicon qualification is independent and **not merge-authorized** |

Do not treat Linux CI as Darwin PASS.

## Increments shipped this programme (open, not merge-authorized)

| Inc | PR | Branch | SHA | What |
|---|---|---|---|---|
| 1 G-026 | [#87](https://github.com/Guruprasath-Annadurai/Orneur/pull/87) | `cursor/g026-kernel-direct-stream-c04e` | `753ac8b0b8f08365c4c70117d8e23b8828a2c24e` | Kernel-direct `/api/stream` via `gateway.stream()`, ownership before kernel |
| 2 A5 | [#88](https://github.com/Guruprasath-Annadurai/Orneur/pull/88) | `cursor/a5-dataset-manifest-bind-c04e` | `1482a58ad5251da94e756fabc0a74a50123e4069` | `validate()` requires verified `dataset_manifest`+`dataset_records` |
| 3 G9 product retrieval | [#89](https://github.com/Guruprasath-Annadurai/Orneur/pull/89) | `cursor/g9-authorized-product-retrieval-c04e` | `1ea44fad6390930c22841a3dd1d5f201e7d5d4fe` | Authenticated upload/chat/stream gated on `AuthorizedIndex` |

Each PR is based on `cursor/genesis-darwin-lock-race-c04e` (PR #86), not stacked on each other, so they can be reviewed independently.

## Architecture snapshot

- Durable ingest, manifests, shard rehash, isolated worker, grant liveness, and founder-ledger deny remain on the #83/#86 baselines.
- Product backend (`orca/serve/api.py`) already had auth, conversations, catalog, cancellation ownership, and evidence APIs. G-026 and G9 close streaming and authorized-retrieval gaps without editing Claude UI.
- RAG-X research kernel (`orca/rag_x`) is still not the product path. Canonical retrieval is `run_authorized_retrieval`.
- Native families GENESIS / NOVUS / AETERNUM remain first-class **untrained** objectives. Pretraining admission is fail-closed (`ExecutionAcceptanceIncompleteError`, empty ledger).

## API contract with Claude

- Increment 1: `docs/orneur/cursor/ORNEUR_BACKEND_API_CONTRACT.md` (`orneur.backend.api/1`) on PR #87.
- Increment 3 adds optional `authorized_retrieval` on authenticated document chats. Existing fields unchanged.
- No edits under `orca/serve/web/*`.

## Security controls and limitations

Preserved: session ownership (404, not 403), grant signatures, on-disk shard rehash, live revocation, founder ledger empty, no fake model outputs.

Remaining:

- PR #86 Darwin `ENOENT` retry is not native-macOS qualified here.
- AuthorizedIndex TrustedSession is process-bound; restart needs a new bind.
- Anonymous DocStore is not G9-qualified.
- Isolated worker same-uid is not a privilege boundary.
- No production neural encoder qualification.
- Ledger numerator **0 / 95**.

## Tests (Linux)

- A5 torch-gated genesis files: 169 passed, 1 historical Audit #077 domain-c deselected (same as CI).
- G9 + product/tenant suites: 53 passed, 3 xfailed on the #86 base (G-026 xfail remains until #87 lands).
- Historical vulnerability-demonstration files are not claimed green.

## Acceptance ledger

Unchanged: `[]`. `validate_register_graph.py` denominator 95, numerator 0. Founder-controlled qualification only.

## Antigravity independent audit

1. Review PRs #87, #88, #89 against exact SHAs above; do not merge.
2. Re-run Linux CI on each exact head; do not relabel Darwin skip as PASS.
3. For A5: attempt `GenesisTrainingRun.validate(dataset_digest=<well-formed hex>)` without records; expect REJECTED.
4. For G9: two accounts, upload on A, chat on B with A's session_id (expect 404); revoke A's trusted session and chat (expect 403).
5. Confirm `docs/orneur/acceptance/acceptance_ledger.json` is still `[]`.
6. Do not run GPU training or spend.

## What this programme does not claim

Not a production-ready global LLM. Not native-model training. Not protected merges. Not global deploy. Not paid infrastructure.
