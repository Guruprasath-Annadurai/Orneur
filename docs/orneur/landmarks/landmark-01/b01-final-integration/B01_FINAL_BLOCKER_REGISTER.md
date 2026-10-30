# B-01 — Final blocker and limitation register

Evidence states used: `IMPLEMENTED_UNVERIFIED`, `VERIFIED_ENGINEERING`, `INDEPENDENTLY_QUALIFIED`, `FAILED`, `BLOCKED`. Only Antigravity can set `INDEPENDENTLY_QUALIFIED`; nothing below claims it.

## A. B-01 and the defects found while closing it

| ID | Sev. | Finding | State |
|---|---|---|---|
| **B-01** | P1 | Default plain-chat answers were one labelled "replayed" chunk; Stop could not cancel generation. | **VERIFIED_ENGINEERING** — the Kernel's real gateway deltas are streamed through `/api/stream`; real-Ollama and real-Chromium evidence attached. *Awaiting Antigravity requalification of the exact head.* |
| B-01a | P1 | PR #135 handoff lifecycle: consumer could wait forever for a terminal marker the sample sends only after the consumer finished; `close()`/`fail()` spawned an untracked task when the queue was full. | **FIXED, VERIFIED_ENGINEERING** — `RawDeltaChannel` rewritten, `KernelRun` added. Reproduced against the original (`evidence/lifecycle_defect_repro.output.txt`). |
| B-01b | P1 (privacy) | `StreamRedactor` released the **last 1–4 characters of a key** after the redaction marker when a chunk boundary fell just past the 20th character; a **PEM header preceded by a non-space character and split after its first dash** let the *whole private-key body* through; an answer ending in `s`/`A`/`B`/`g` **lost its last letter** (`…keys` → `…key`). On the original code, over 36 000 randomized chunkings: 655 stream-only leaks, 8 675 truncated outputs; on this branch: 0 and 0 (`evidence/redactor_differential.output.txt`). The defects are in the redactor shared by `/api/stream`'s document path and `/api/inference/stream*`; all benefit. | **FIXED, VERIFIED_ENGINEERING** |
| B-01c | P2 (privacy) | The Cognitive Kernel handed the model's **raw** text to working-memory/episode ingestion for every Kernel-direct answer on *both* `/api/chat` and `/api/stream` (a credential in an answer could be remembered even though the client was shown a redacted answer). | **FIXED, VERIFIED_ENGINEERING** — redacted before ingestion; whole-`ORNEUR_HOME` byte scan in the live DLP test. |
| B-01d | P1 (hazard) | With the hook set, the Truth-Fabric path would also have streamed its *draft* tokens, which can still be rejected by `verify_answer()` (AUDIT-grade abstention happens after generation). | **FIXED, VERIFIED_ENGINEERING** — hooks withheld for that call. |
| B-01e | P3 | The PR #135 handoff states every pre-admission refusal is an HTTP JSON status; the route actually uses HTTP JSON for auth/rate-limit/ownership/temporary-chat and an SSE `error` event for plan/moderation/quota/busy/store/intent. | **DOCUMENTED, MEASURED** (`B01_KERNEL_TO_SSE_CONTRACT.md` §6). No client contract changed. |

## B. Open items

| ID | Sev. | Finding | State / owner |
|---|---|---|---|
| **B-02** | P1 (process) | This exact head has **no independent qualification**. | OPEN — Antigravity (`B01_ANTIGRAVITY_REQUALIFICATION_HANDOFF.md`). |
| B-04 | P2 | The real-Ollama journeys run on the workstation only; CI covers the fixture-provider variants (including every new B-01 suite). | OPEN — needs a CI runner with Ollama (paid/infra decision not taken). |
| B-06 | P2 | Document sessions still generate the Kernel's answer and then the RAG answer (two model calls). Document sessions are therefore **not** Kernel-streamed; they keep the pre-existing, already-upstream AgentLoop stream. | OPEN — unchanged, out of scope. |
| L-01 | P2 | Truth-Fabric-routed turns (plans with `RETRIEVE/SEARCH/VERIFY`) are delivered whole after verification and labelled `replayed`; this is deliberate (draft tokens are unverified). Without documents such plans mostly abstain (`INSUFFICIENT_EVIDENCE`). | BY DESIGN — a verified-draft streaming design would need CTO input. |
| L-02 | P3 | SSE chunk boundaries change at hyphens (a trailing dash run is held until the next delta, because a PEM header can begin with one). Text is byte-identical; only `test_inference_gateway.py::test_stream_chunks_and_cooperative_cancel` asserted the partition, and is relaxed to "two chunks, same text" (reason in the test). | ACCEPTED |
| L-03 | P3 | After an accepted commit, `_event_stream` spawns the pre-existing fire-and-forget knowledge-graph enrichment task (derived state). It is not part of the stream lifecycle but is a background task that can outlive the request by design. | PRE-EXISTING |
| L-04 | P3 | A client that hangs up *while the server is committing* cannot know whether the commit won (measured: 10 of 36 forced races committed, 26 did not; never partial/duplicate). The reload shows the truth. Same family as B-07. | PRE-EXISTING, now measured |
| L-05 | P3 | Stop **before the first token** (before the `stream` event) still shows the modest "may still be completing on the server" wording even though the server does cancel; only an announced upstream stream earns the stronger wording. | ACCEPTED (truthful, conservative) |
| L-06 | P3 | Billing policy: Stop after the first token costs the unit (consumed at first output). Not changed — CTO approval required. | POLICY |
| B-05, B-07 … B-11 | P2/P3 | Unchanged from LANDMARK-01 / PR #133 (vector-store shredding best-effort; outcome unknown after a severed connection; cognitive 500 mapping; email verification; orphan deployment ids; pattern-floor DLP). | UNCHANGED |

## C. Counts

Outstanding **P0: 0**. Outstanding **P1: 1** (B-02: independent qualification of this head — a process gate, not a known defect). B-01 itself is closed at engineering level. P2: B-04, B-06, L-01. P3: L-02…L-06 plus the unchanged carry-overs.

No finding above is hidden by a skipped test. The only `skip` in the suites run for this work is the pre-existing `test_serve_streaming.py` ASGI-transport disconnect test, which documents that ASGITransport cannot surface a disconnect (the real-socket variant right below it runs).
