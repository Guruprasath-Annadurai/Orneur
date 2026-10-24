# Sprint 2 — customer-facing correctness (G-015, G-023, G-024, G-026, G-027)

Status: **IMPLEMENTED_TESTED against a test-double model — NOT_INDEPENDENTLY_AUDITED.** `FakeOllama` proves ORNEUR's own request path (routing, labels, errors,
retrieval plumbing). It says nothing about any real model's quality, and none of this makes a model "work".

All additions are **additive** to the existing JSON/SSE payloads (existing keys unchanged, `detail` kept on HTTP errors).

## G-015 — `model_identity` (chat response, stream `model` event, stream `done`)
| field | meaning |
|---|---|
| `requested_tier` | what the request/UI asked for (`core` if unspecified) |
| `served_tier`, `served_model` | what generated the text (`served_tier` is `null` when it cannot be determined — never guessed) |
| `substituted`, `substitution_reason` | `kernel_routing` · `entitlement_limit` · `registry_fallback` · `cost_routing_escalation` · `sovereignty_override` |
| `fallback_from` | the model that was wanted when the registry had to fall back (not installed) |
| `backend`, `data_left_infrastructure` | `ollama` or the external provider; whether data left the deployment |
| `lifecycle`, `disclosure` | from the public-serving authority (`EXPERIMENTAL`, …; `UNKNOWN` if undeterminable; `null` for external providers) |

Known limit: on the AgentLoop path, auxiliary planning/reflection calls use the same session brain; `served_model` describes the answering model. A per-call
model ledger would need the Gateway contract (not changed here).

## G-023 — error vocabulary (`orca/serve/errors.py::ERROR_CATALOG`)
`auth_required` 401 · `forbidden` 403 · `model_access_denied` 402 · `quota_exceeded` 429 (+`used`,`limit`) · `rate_limited` 429 · `content_refused` 400 ·
`request_abstained` 422 (+`reason`) · `invalid_request` 422 · `not_found` 404 · `conflict` 409 · `capability_disabled` 403 · `model_unavailable` 503 ·
`upstream_timeout` · `backend_unreachable` · `backend_error` · `server_busy` 503 · `cancelled` · `internal_error` 500. Shape: `{error, code, error_id, …}`
(SSE: `{type:"error", text, code, error_id}`). `HTTPException`, validation errors and unhandled exceptions all pass through it; exception text is never returned.
Chat/stream keep HTTP 500 for backend failures (codes carry the distinction). `cancelled` is a classification (client disconnect is audited; there is no one to answer).
Not yet retrofitted: the ~20 remaining ad-hoc `JSONResponse({"error": …})` sites on non-chat routes get the status-derived default code only through the
`HTTPException` handler when they raise; direct `JSONResponse` returns are unchanged.

## G-024 — documents in `/api/chat`
Same rule as `/api/stream`: the Kernel's no-retrieval direct answer is used only when the session has no documents or the Kernel grounded the answer itself.
Otherwise deep-RAG context is injected. A retrieval failure is an error, never a silent answer without the file. Ownership (G-006) gates the session, so another
user's documents are unreachable (tested both ways).

## G-026 — stream delivery
`stream` event: `{delivery: "upstream"|"replayed", cancellable: bool}`; `done.delivery` repeats it.
* `upstream` — Kernel-direct `/api/stream` and AgentLoop forward `ModelGateway.stream()` / backend chunks; closing the connection cancels generation.
* `replayed` — the answer was already complete (Truth Fabric citation verification, frontier `generate()`). One chunk with `replayed: true`. Do not offer stop.

## G-027 — `orneur.sources/1`
`sources[]` = passages really supplied to the model (`ref` `[D#]`, `kind`, `filename`/`url`, `doc_id` when unambiguous, `locator`, `excerpt`, `excerpt_sha256`,
`retrieved_at`, `cited_in_answer`). `source_summary.grounding`: `none` · `retrieved_not_cited` · `cited` · `evidence_state_only`. A hallucinated `[D9]` never becomes a source;
no retrieval ⇒ `sources: []`, `retrieval_performed: false`. Truth-Fabric answers now expose their passages through a new **optional** field
`CognitiveResult.evidence_passages` (additive; default `None`).

## Residual risks
* Locator is a chunk index (no page/offset yet); excerpt is the first 300 characters of the chunk.
* `cited_in_answer` is a marker match, not a semantic check that the claim is supported (the Truth Fabric's own claim verification remains the authority for that).
* Web UI does not yet render `model`/`stream`/`sources` events — UI work is gated on founder approval of the PR #29 design.
