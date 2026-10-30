# L02-02 — Document conversations, RAG and Truth Fabric

Evidence state: **IMPLEMENTED; engineering tests and real-Ollama measurements recorded; exact-head CI pending; not independently qualified.**
Baseline `9cb864c99ad323d11626063498a7d1cef0d7d4b5` (PR #136). Model for real runs: third-party `llama3.2:1b` weights served by local Ollama (not an ORNEUR-native model).

## 1. Is the "duplicate answer generation" real? (investigated before changing anything)
Routing of a document question (`orca/serve/api.py` `/api/stream` and `/api/chat`): the Kernel plans; then
* **Truth-Fabric route** (plan has RETRIEVE/SEARCH/VERIFY): the Kernel's answer is verified against the session's documents and is authoritative. Calls: 1 answering call + claim-verification calls. **Not a duplicate**; unchanged. Delivered whole and labelled `replayed` (unverified draft tokens may not be shown — carried-over limitation L-01).
* **Plain (direct) plan in a document session**: the Kernel generated a full non-streamed answer, the API then **threw it away** (`kernel_answered` requires `doc_store.count()==0` or an `evidence_state`) and re-answered through deep-RAG + a streamed AgentLoop call. That first answer is an **accidentally duplicated final-answer generation** — and the quota unit was consumed for it.
* Deep-RAG stages (query rewriting, rerank, sufficiency, contradictions) are **legitimate retrieval/verification calls** and are untouched.

Measured, real `llama3.2:1b` behind the recording tap, question "Summarize the uploaded document in two sentences." (`evidence/real_ollama_document_runs/sbase*.json` vs `sl02_*.json`):

| tree | runs | discarded Kernel answers per run | streamed answers per run | provider requests per run |
|---|---|---|---|---|
| baseline `9cb864c` | 3 | **1, 1, 1** | 1 | 6, 5, 6 |
| this branch | 3 | **0, 0, 0** | 1 | 4, 5, 5 |

Wall-clock times (2.1–4.4 s baseline, 2.7–3.9 s here) overlap and are dominated by model variance; **no latency gain is claimed**. A fixture-provider comparison (deterministic): baseline fails `test_document_session_has_exactly_one_answering_dispatch_and_it_is_streamed`; this branch passes.

For the evidence-routed question "Where in the cell does the Calvin cycle occur, according to my notes?" both trees take the Truth-Fabric route with **0** discarded answers (`base1-5`, `l02_1-5`): request counts overlap (2–5 baseline, 3–9 here, model variance in the number of claims verified), delivery is `replayed` on both. Nothing is claimed about this route.

Fix: `CognitiveRequest.defer_direct_answer` (set by `_run_cognitive_kernel` only when the session's document store holds registered documents and no raw-delta hook is attached). The Kernel returns the existing "deferred" result (`output=None`) **after** the Truth-Fabric branch, so evidence-routed answers, the draft-token protection and the abstention paths are unchanged.

## 2. What was strengthened (defect → fix → test)
| Defect found on the baseline | Fix | Test |
|---|---|---|
| Upload was parsed **before** the conversation's ownership was checked (a stranger or a deleted conversation could make the server parse a hostile file) | `_get_session` + temporary-chat check first | `test_a_stranger_cannot_make_the_server_parse…` (baseline: extractor ran) |
| Whole upload read into memory before the size check | `read_bounded` (1 MiB blocks; 413 the moment the limit is crossed) | `test_oversize_upload_is_refused_without_reading_it_all` |
| Display name taken from the client (path parts, markup, control/bidi characters, 400+ chars) and rendered to users and the model | `safe_filename` (basename, unsafe chars, bidi/control, ≤120 chars) | `test_filename_is_reduced_to_a_safe_display_name` |
| Extension only; binary named `.txt`, fake `.pdf`/`.docx`, a PDF named `.txt`, empty file accepted | `validate_content` (magic bytes, NUL/UTF-8 checks) | `test_binary_disguised_as_text_and_fake_containers_are_refused` |
| Unbounded text, chunks and documents per conversation | 2 M chars, 2 000 chunks, 20 documents | `test_extracted_text_and_document_count_are_bounded` |
| Chunk identity was `(filename, chunk_idx)`: two uploads with the same filename **lost a document's passage in rank fusion**, and `doc_id` on sources was `null` when names collided | `retrieve()` returns `doc_id`; fusion/rerank/citation DNA carry it; sources use the chunk's own `doc_id` | `test_two_documents_with_the_same_filename…`, `test_sources_are_attributed…` |
| Retrieval ignored the registry: orphaned/stale chunks (registry entry gone, half-finished delete) could be retrieved and cited; presence of documents was decided by raw chunk count | `DocStore(enforce_registry=True)` for sessions; `deleting` state hides a document **before** physical removal; `count()` follows the registry | `test_orphaned_chunks…`, `test_a_document_being_deleted_is_out_of_retrieval…` |
| Retrieved text entered the prompt as bare text (a document could forge `[D9] (source: …)` headers or close the quotation) | passages quoted in `<<<passage … passage>>>`, header/delimiter look-alikes neutralised, "UNTRUSTED quotations" instruction | `test_a_document_cannot_forge…`, `test_injected_instructions_reach_the_model_only_inside…` |
| Dense retrieval always returns its nearest chunk, however unrelated, and the sufficiency judge was **fail-open** (an unparsed or unavailable judge counted as "sufficient") → an unrelated question was answered as if the documents supported it | (a) the judge's default is recorded as *not evaluated*, never "sufficient" (`judged`); (b) a model-independent floor: no shared content word with any retrieved passage and no confident judge → no evidence; (c) the model is told explicitly that the documents contain nothing relevant and must not cite | `test_unrelated_question_tells_the_model…` (baseline: passage supplied); real model: `l02_real_unrelated_question.json` |
| A citation the model invented (`[D9]` with no such source) was invisible | `source_summary.unsupported_citations` | `test_a_citation_the_model_invented…` |

Verified and left unchanged (tests added as guards): another user's documents never reach the prompt; the document-turn **Stop** cancels the provider (fixture: `stream_aborted` seen; real Ollama: `open_streams == 0`, `evidence/l02_real_document_stop.json`), charges exactly one unit, stores no turn; a completed document turn commits exactly once; a provider failure refunds the unit and stores nothing; a document cannot trigger a tool by its text alone (tool calls come from model output only).

## 3. Residual risks (not hidden)
1. **Prompt injection is mitigated structurally, not eliminated.** Framing and neutralisation are deterministic and tested; whether a particular model obeys an instruction inside a quotation is model behaviour. A model that is persuaded to *emit* a tool call will still have it executed by the agent loop. Not proven safe against a capable adversary.
2. The rerank and sufficiency judge prompts still interpolate raw passage text (a passage could try to steer a score or a JSON verdict). Impact is bounded to retrieval ranking/abstention; open (register L02-02e).
3. The lexical floor is deliberately conservative toward abstention for zero-word-overlap questions; a pure paraphrase with no shared word is rescued only by a confident model judge.
4. Truth-Fabric answers remain delivered whole (L-01); document pipeline answers stream upstream.
5. Document-level deletion that fails midway stays `deleting` (hidden, retryable by repeating the `DELETE`); there is no background sweep for single documents (conversation-level deletions do have one).


## 4. Update — residuals closed in the final LANDMARK-02 pass
* **L02-02e (judge/rewriter/reranker trust boundary):** passages are nonce-quoted as untrusted, parsers are strict (an unparsed or injected verdict is "not judged", never "sufficient"), and a passage matching the injection screen is never shown to the scorer or judge. 70 tests (`test_l02_judge_trust_boundary.py`); baseline reproduction `evidence/l02_02e_baseline_judge_injection_9cb864c.txt`. This bounds *ranking and abstention* manipulation; it does **not** prove that the answering model will ignore instructions inside document text (structural mitigation only).
* **L02-02f (document-driven tool authority):** `orca/tools/authorization.py` independently authorises every model-produced tool call (schema, range, provenance, call budget); document text cannot grant authority; audit records tool name + reason code only (`test_l02_tool_authority.py`, 12).
* **Upload parsing security:** isolated bounded extraction (subprocess, rlimits, 20 s timeout), zip pre-checks, filename sanitising (bidi), quotas, sha256 dedupe, atomic limits. Real `pypdf`/`pdfminer.six`/`python-docx` against hostile files: `tests/journey/test_l02_upload_parsers_live.py` (7 passed on the final head; **workstation only** — the libraries are an optional extra CI does not install).
* **Embedding-space consistency:** a store holding vectors of one dimension is not queried with another service's embeddings (`test_l02_embedding_consistency.py`).
* **L02-02g:** see `L02_DATA_LIFECYCLE_AND_DELETION.md`.
