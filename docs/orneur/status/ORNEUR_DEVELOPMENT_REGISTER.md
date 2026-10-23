# ORNEUR Development Register

**The single authoritative statement of development state.** If another document disagrees with this one about readiness, status or
authorization, this register is the one to correct (see §7 for conflicts already found). Nothing here is an acceptance, an authorization, or a
launch claim. Register date: **2026-10-11**. Maintained by the primary engineering lead; updated at the end of each work package.

Evidence tags: `VERIFIED` (checked in this repository/CI by me), `REPORTED_NOT_VERIFIED` (a repository document says so; no primary evidence
available), `UNKNOWN`, `NOT_APPLICABLE`. Audit depth: `READ` (code read), `SURFACE` (grep/test-count scan only), `NOT_EXAMINED`.

---

## 1. Integration and security baseline

| PR | Head SHA | Scope | Exact-SHA CI | Independent audit |
|---|---|---|---|---|
| #19 | not re-verified in this pass | application/governance integration (original integration PR) | — | not re-verified here |
| #20 | `a2b53b3` | PYSEC-2026-2447/3447 remediation | passed | reported independently accepted (PR #21 description); not re-verified here |
| #21 | `26fe4b7` | merge-gate hardening | 9/9 | superseded by #22/#23 findings |
| #22 | `dfa9188` | descriptor-based directory validation | 9/9 | Audit #007 `REMEDIATION_REQUIRED` against `045a826` |
| #23 | `bd3072c` | Audit #007 remediation | **9/9** | **Audit #008 not received** (no comment on #22/#23 as of this register) |
| #24 | `ce3d58c` | P0 training authorization gate | **9/9** | none yet |
| #25 | `0db1a59` | P0 experimental-serving policy | **9/9** | none yet |
| #26 | `52ad8fa` | P1 development register + flaky-test fix | **9/9** | none yet |
| #27 | `f29a133` | G-003 non-root containers | **9/9** (incl. container build + boot smoke) | none yet |
| #28 | `0065256` | G-019 `O_PATH` for ancestors | **9/9** | none yet |
| #29 | `bb00f5d` | P2 UI design spec + Light/Dark mock (design only) | **9/9** at `2da93b1` (first head `bdd23c1` failed 3 tests: f-string backslash invalid on Python 3.11; fixed) | none (founder review D-2) |
| #30 | `f7c5eba` | **G-006** tenant-isolation tests + fixes (F1–F9), report `G006_TENANT_ISOLATION_REPORT.md` | **9/9** | none yet |
| #31 | `d1aa871` | **Task B** public-serving authority: env flag can no longer authorize public serving; signed/scoped/expiring grants (none issued) | **9/9** | none yet |
| #32 | `fef50b6` | **Task C** training gate assurance: 16 bypass attacks fixed, entry-point inventory | **9/9** | none yet |
| #33 | `23e4d16` | **Task D** container verification (22 checks, now in CI against the built image), partial-migration fix; stacked on #28 | **9/9** | none yet |
| #34 | `f4cc265` | **Task F** end-to-end flow evidence (test double), G-025 fix, register update | **9/9** (register-only commits since are docs) | none yet |
| #35 | `4369e5b` | **Sprint 2 P0** G-020 (no server-authority tools on the web; `/api/code/run` disabled) + G-021 (owner bootstrap) | **9/9** at `4369e5b` | none yet |
| #36 | see PR | **Sprint 2 P1** G-015/023/024/026/027 customer-facing correctness (stacked on #35, merges #31) | pending | none yet |

Ancestry (VERIFIED): `main(464b602) ⊂ #20 ⊂ #21 ⊂ #22 ⊂ #23 ⊂ #24 ⊂ #25`. Nothing is merged. `main` is unchanged at `464b602f3f25`.
Local full deterministic suite on #25: **7273 passed, 6 failed, 413 skipped** (§6, G-013 for the six).

## 2. Model status register

Eight questions are answered **separately**, per model. No cell is inferred from another.

### 2.1 GENESIS

| Question | Answer | Evidence |
|---|---|---|
| Historical experimental training | **Yes — legacy only.** Qwen2.5-**7B**-Instruct QLoRA (r=16, lr 2e-4, 2–3 epochs, T4) and a safety+honesty DPO round. Retired from the canonical programme. `REPORTED_NOT_VERIFIED` (no logs/outputs: all 16 notebooks have zero recorded cell outputs) | `notebooks/orca_nano_*`, `docs/ORCA_BLUEPRINT.md:74`, `GENESIS_MODEL_IDENTITY.md` |
| Training completion | **UNKNOWN** — steps, tokens, final state unrecorded (`step_or_epoch: "unknown"`) | `scripts/import_historical_checkpoints.py` |
| Artifact existence | Legacy `orca-nano`, `orca-nano-v4` (same digest), `orca-nano-v7` existed in the owner's Ollama store. **Not in this repository or this environment.** `REPORTED_NOT_VERIFIED` | same script, sha256 `671e7777…`, `5ce043a5…` |
| Checkpoint integrity | Hashes recorded; **cannot be re-verified here**. Tracked dataset `orca_nano_combined_train_v1/eval_v1` re-hashed and **match** their documented checksums (`VERIFIED`) | `GENESIS_DATASET_BASELINE.md` |
| Capability evaluation | Pre-tune baseline 0.76 only. **No post-tune evaluation exists.** Loss-curve overfitting flag (val loss rose after step 100) is `REPORTED_NOT_VERIFIED` | `ORCA_BLUEPRINT.md:74,281` |
| Independent qualification | **None** | — |
| Training authorization | **NO-GO.** Canonical Genesis has never been trained; `NOT_TRAINED`/`UNAVAILABLE` in the router. Code-level gate now enforced (PR #24), committed registry empty | `PHASE20_INTELLIGENCE_ROUTER_SPEC.md`, `docs/orneur/authorization/TRAINING_AUTHORIZATION_DESIGN.md` |
| Production authorization | **None** for the canonical model. Legacy 7B still serves the nano tier as disclosed `LEGACY_PRODUCTION_SERVING` (founder decision D-1) | `orca/society/lifecycle.py` |

**Foundation:** `UNRESOLVED`. Records conflict (§7): `model_spec.py` pins Qwen2.5-3B-Instruct (rev `7548fff1…`) as the "canonical V1 target" and
the router says "base model SELECTED", while the Phase 21 status record says `foundation_selected: null` and the decision package verdict is
`FOUNDATION_DECISION_REQUIRES_CAPABILITY_EVAL`. Candidates studied: the Phase 21 shortlist/landscape documents (their "admitted" pool is tied to the invalid V1 eval, so I do not rely on it); three runtime controls (Qwen3-8B,
Mistral-Nemo-Instruct-2407, Phi-4) failed locked runtime qualification — a serving-contract result, **not** a capability result.
The V1 capability eval holdout is public and **invalid** (`GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json`): historical evidence only. V2 is unfrozen
(no private corpus, no reviewer keys).

### 2.2 NOVUS

| Question | Answer | Evidence |
|---|---|---|
| Historical experimental training | **Yes — documented.** Llama-3.1-8B-Instruct: SFT (r=64, 2 epochs) → probe-grounded DPO → failed calibration SFT → combined SFT attempts 2 and 3 (plain PEFT `Trainer`, lr 1e-4, 3 epochs, 65 train examples, warm-start from adapter). `REPORTED_NOT_VERIFIED` | `notebooks/orca_core_*`, `MODEL_TRAINING_STATUS.md`, kernel metadata `orca-core-combined-sft-kernel-v1` v5 (T4) |
| Training completion | **UNKNOWN** — final stage ≈15 optimizer steps is *my derived estimate*, not a log | derived from notebook config + dataset size |
| Artifact existence | `orca-core-combined-v2` GGUF (4,920,738,816 B, Q4_K_M) existed on the owner's machine. Adapters/GGUF referenced on private Kaggle (`orca-core-combined-adapter-v2`, `orca-core-sft-adapter-v2`, `orca-core-dpo-merge-export-v1`, …). **Nothing recovered here.** `REPORTED_NOT_VERIFIED` | `import_historical_checkpoints.py`, `NOVUS_FRESH_EVALUATION.md` |
| Checkpoint integrity | sha256 `c519cba17b68…` recorded; **unverifiable here**. No optimizer/scheduler state recorded | same |
| Capability evaluation | jailbreak 70.0% strict / 90.0% avg; bias 12.5%; calibration 100%; accuracy 72.8%; domain 37.5%. **Document-derived**; raw report JSONs never committed | `NOVUS_PROMOTION_DECISION.md`, commit `95f3dac` |
| Independent qualification | **None.** `NOT_PROMOTABLE` (jailbreak 70 < 92; domain 37.5 < 75) | same |
| Training authorization | **Resumption unauthorized.** Exact resume impossible (no optimizer/scheduler state). Gate enforced in code (PR #24) | §3 |
| Production authorization | **None.** `EXPERIMENTAL`. Live-serving exposure: see §3.2 | `LIVE_SERVING_CUTOVER.md:57` |

## 3. Findings that changed behaviour

### 3.1 Training authorization bypass — P0, fixed in PR #24 (unaccepted)
All four training entry paths reached real-work boundaries with no authorization (reproduced on `bd3072c`). Now fail closed; threat model in
`docs/orneur/authorization/TRAINING_AUTHORIZATION_DESIGN.md`. Training remains **NO-GO**: the founder has provisioned no key.

### 3.2 Experimental NOVUS serving exposure — P0, fixed in PR #25 (unaccepted)
- `orca/gateway/wiring.py` hard-coded `allow_experimental=True` for every live request. The tier resolver serves whatever Ollama model is installed
  under the configured name. **The repo default core name is `orca-core`, not `orca-core-combined-v2`**; the docs say the owner's environment sets the
  latter. Therefore actual exposure is deployment-dependent and **UNKNOWN from the repository**: I cannot see the owner's environment.
- Now: unchanged locally; on a public edge (`ORNEUR_PUBLIC_EDGE`) EXPERIMENTAL self-hosted models are refused unless
  `ORNEUR_ALLOW_EXPERIMENTAL_SERVING` is set. Legacy Genesis behaviour unchanged (D-1).
- **To determine real exposure the owner should check** the live host's `ollama list`, the value of `ORNEUR_CORE_MODEL`, and whether
  `ORNEUR_PUBLIC_EDGE` is set. I have not and cannot.

## 4. Subsystem classification

Vocabulary: `COMPLETE_VERIFIED` · `IMPLEMENTED_NOT_VERIFIED` · `PARTIAL` · `STUB_OR_MOCK` · `MISSING` · `BLOCKED`.
**No subsystem is `COMPLETE_VERIFIED`**: no end-to-end user-level verification of any workflow exists in this repository (unit tests and CI ≠
working product). Evidence depth `E2E-DOUBLE` below means: exercised end to end through the real FastAPI app against a **test-double model** (`tests/fake_ollama.py`,
`tests/test_product_flows_fake_ollama.py`) -- it verifies the application's own request lifecycle, not any model's capability. No browser run, no real model, no live Redis/Postgres.

| # | Subsystem | Class | Depth | Evidence / notes |
|---|---|---|---|---|
| 1 | Frontend & design system | **PARTIAL** | READ (grep) | One 4,293-line `orca/serve/web/index.html`; no theme system (0 `prefers-color-scheme`, 0 `data-theme`), none of the locked brand colours, **0 `aria-label`**, 1 `@media`, 76 `innerHTML` uses, no `AbortController`. Greeting/wordmark not present. Only an SSE diagnostics test exists. Needs the approved redesign. |
| 2 | Backend APIs | **PARTIAL** | E2E-DOUBLE | chat, stream, sessions, docs, limits, deletion exercised against a test double (10 passing flows + 5 pinned gaps). Gaps: G-015 (served model not disclosed), G-023 (no error code on the cognitive path), G-024 (chat ignores an uploaded document for plain questions), G-026 (simple answers not streamed), G-027 (no structured sources). |
| 3 | Authentication & account lifecycle | **PARTIAL** | TESTED | signup/login/me/roles/API keys/password change+reset exercised; #30 fixed token-type confusion (2FA bypass), no session invalidation, replayable reset link, default signing secret, admin→owner escalation. **Open:** no logout endpoint / per-token revocation (stateless 30-day tokens), first-user-owner bootstrap (G-021); email delivery and live TOTP not verified. |
| 4 | User & tenant isolation | **PARTIAL** (first adversarial pass done, not independently reviewed) | TESTED (41 tests) | G-006: 9 confirmed defects fixed in #30 (session listing/title/save, prefix-collision memory+docs leak, path traversal, owner-claim race, admin→owner escalation, token-type confusion incl. 2FA bypass, no session invalidation, default signing secret). **Unfixed:** agent tools run with server authority and one shared workspace (G-020); first-user-owner bootstrap (G-021); 8-char storage keys (G-022). Background jobs: NOT_IMPLEMENTED. |
| 5 | Conversation persistence & history | **PARTIAL** | E2E-DOUBLE | save → list → export → load verified; sessions scoped to their owner (#30). `_sessions` is process-local; durability across restarts/replicas only with opt-in Redis (G-007, untested). |
| 6 | Streaming & cancellation | **PARTIAL** | E2E-DOUBLE | SSE contract verified (`session`, `chunk`, `done`+`message_id`). **Client disconnect cancels the backend generation on the streaming path** (handler returns in 0.43 s, backend sees the hang-up after 3 of 40 chunks). BUT a simple question is generated non-streaming and delivered as one chunk after completion (G-026); UI has no `AbortController`. |
| 7 | Research & citations | **PARTIAL** | SURFACE | `orca/truth/*` (17 test files) is a real claims/citation pipeline; **the stream `done` event carries only a `citation_compliance` note, no structured sources (G-027)**; live search is a DuckDuckGo HTML scraper (`tools/web.py`, `truth/search_provider.py`) — fragile, no licensed search API; SSRF check fails closed when DNS is unavailable. |
| 8 | File upload, parsing, retrieval | **PARTIAL** | E2E-DOUBLE | upload/list/delete verified; document text reaches the model on `/api/stream`; on `/api/chat` only when the question triggers retrieval (G-024). Cross-user doc access closed (#30). Embedding path (real Ollama/Chroma) not exercised. |
| 9 | Code workspace & execution | **PARTIAL** | READ | `orca/code/sandbox.py`: AST pre-check + subprocess; the module itself states network/FS isolation is limited. Not container-isolated. `/api/code/run`. |
| 10 | Tools & integrations | **STUB_OR_MOCK** (external connectors) | READ | Connectors framework exists but the only provider in the repo is `fake_provider.py`; MCP module present. No real third-party connector verified. |
| 11 | Memory & personalization | IMPLEMENTED_NOT_VERIFIED | SURFACE | episodic/semantic memory; semantic cache hardened (PR #23). |
| 12 | Model routing & serving | IMPLEMENTED_NOT_VERIFIED | READ+E2E-DOUBLE | Gateway + tier resolver; exposure fixed in #25; #31 removes the env-flag path (signed, scoped, expiring public-serving grants; none issued). **A `core` request was served by the planning tier (`orca-nano`) and the response does not say so (G-015).** Every ORNEUR model is `EXPERIMENTAL`/`NOT_TRAINED`. |
| 13 | Safety & prompt-injection controls | PARTIAL | SURFACE | moderation, DLP, red-team suite (12 test files). The only measured ORNEUR model fails its jailbreak bar (70% vs 92%). |
| 14 | Privacy, logging, retention | **PARTIAL** | E2E-DOUBLE | account deletion verified end to end (data removed, token invalid); **found and fixed (#34): a deleted user's conversation title was resurrected into `session_titles.json` by the next rename**. Retention policy not verified; Chroma/semantic residue only checked for the test content. |
| 15 | Reliability & failure recovery | **PARTIAL** | E2E-DOUBLE | backend 5xx → safe error, next request recovers (verified); failed calls do not consume quota; but no machine-readable error code on the cognitive path (G-023). No load/soak evidence. |
| 16 | Billing / subscription | IMPLEMENTED_NOT_VERIFIED | SURFACE+E2E-DOUBLE | **daily usage limit verified** (free tier 50/day → 429 with a clear message; failures not counted). Stripe checkout + signature-verified webhook never exercised (no keys). |
| 17 | Deployment infrastructure | **PARTIAL** | TESTED (real image, #33) | non-root (UID 10001) verified against a built image with a real Docker daemon: 22 checks (volumes, migration, Fly entrypoint, k8s init capability set, no-capabilities, read-only rootfs start-up, execute-only ancestors, symlinks, boot). One defect found and fixed (partial migration). Not verified: Fly image build, real cluster, volume drivers; `readOnlyRootFilesystem` not enabled. |
| 18 | Mobile & accessibility | **PARTIAL** | READ (grep) | viewport meta present; 0 aria labels; 1 media query; no a11y verification. |
| 19 | Observability & operations | IMPLEMENTED_NOT_VERIFIED | SURFACE | `/metrics`, hash-chained audit log + verify endpoint, `/livez|readyz|healthz`; no alerting config seen. |
| 20 | Model training pipeline | IMPLEMENTED_NOT_VERIFIED / **BLOCKED** for execution | READ+TESTED | QLoRA pipeline + provenance exist; real runs blocked by design (PR #24, NO-GO). #32: 16 gate-bypass attacks found and fixed (grant forgery via `dataclasses.replace`/copy/pickle, budget reset by deleting slot files, unnoticed audit-log edits); 14 notebooks run off-host outside the gate by nature. |
| 21 | Governance / acceptance / RSE | IMPLEMENTED_NOT_VERIFIED | READ | Frozen; pre-training `95` rows, numerator `0` (validator re-run: `pretraining=95 numerator=0`). |

## 5. Gap inventory (prioritized)

| ID | Pri | Gap | Source | Impact | Depends on | Acceptance criteria |
|---|---|---|---|---|---|---|
| G-001 | P0 | Training entry points unguarded | `orca/train/*`, `cli.py` | unauthorized spend/egress/lineage | — | **Fixed in #24** → Antigravity review |
| G-002 | P0 | Experimental models serve public traffic | `orca/gateway/wiring.py` | unqualified model shown to users | — | **Fixed in #25** → review; D-1 decided |
| G-003 | P0/P1 | **Fixed in #27, verified against a real image in #33 (22 checks; one more defect fixed):** production containers ran as root | `Dockerfile`, `Dockerfile.fly`, `k8s/deployment.yaml` | container escape blast radius | image build | non-root `USER`, `runAsNonRoot`, read-only rootfs where possible; CI boot smoke still passes |
| G-004 | P1 | Code execution is AST+subprocess only | `orca/code/sandbox.py` | arbitrary-code risk if exposed | G-003 | execution only in the qualified container/sandbox backend; escape tests pass; or endpoint disabled on public edge |
| G-005 | P1 | 76 `innerHTML` sinks in the UI | `orca/serve/web/index.html` | stored/reflected XSS | redesign (D) | model/user content rendered via a sanitizer or `textContent`; CSP; XSS regression tests |
| G-006 | P1 | **Addressed in #30 (not independently reviewed):** adversarial two-user tests found and fixed 9 defects; categories 9 and 11 recorded as NOT_IMPLEMENTED / KNOWN_UNFIXED | `orca/serve`, `orca/auth`, `orca/brain`, `orca/docs` | cross-user data exposure | independent review of #30 | see `G006_TENANT_ISOLATION_REPORT.md` |
| G-020 | **P0/P1** | **MITIGATED in #35 (web surface only; not secured):** server-authority tools are not registered on any web path and `/api/code/run` (which leaked `ORNEUR_AUTH_SECRET` via `/proc/self/environ`) is disabled; per-user isolated execution is a design proposal only. Original finding: Agent `shell`/`read_file`/`write_file` run with the server's authority and one server-wide workspace; `cat`/`find`/`grep`/`git` read any path the OS user can read (admitted in `orca/tools/code.py`). Strict-xfail tests reproduce it | `orca/tools`, web session agent | any chat user (prompt-injectable) can reach other tenants' stored data and server files | **founder/product decision**: drop tools for web sessions, or per-session workspace + argv path confinement, or real sandbox (G-004) | G-006 xfail tests flip to passing |
| G-021 | P1 | **FIXED in #35:** signup never yields owner; single-use email-bound operator token; fail-closed on a public edge. Original finding: First account on a fresh install becomes `owner`; count-then-insert is racy | `orca/auth/store.py::create_user` | first visitor of a new public deployment owns it; two simultaneous first signups can both be owner | provisioning flow decision | owner creation only via explicit bootstrap; test |
| G-022 | P2 | Per-session storage keyed by `session_id[:8]`; #30 makes collisions fail closed (404) but does not remove the 32-bit space | `orca/brain/memory.py`, `orca/docs/store.py` | rare spurious refusal at scale | data migration to full-id keys | migration + dual-read tests |
| G-023 | P1 | **FIXED in #36** (stable `ERROR_CATALOG`, cause-chain classification, handlers). Original finding: On the cognitive-kernel path a backend failure returns one generic message with no `code`/`error_id` (other routes use `public_error`) | `orca/serve/api.py` (`/api/chat`, `/api/stream`) | UI cannot distinguish model-unavailable / timeout / backend error | UI states (P2) | error body carries code + error_id; strict-xfail test flips |
| G-024 | P1 | **FIXED in #36.** Original finding: `/api/chat` sends an uploaded document to the model only when the question triggers retrieval; `/api/stream` always does | `orca/serve/api.py`, `orca/cognitive` | a plain question about an uploaded file is answered without it | — | one document-grounding policy for both routes; xfail flips |
| G-025 | P1 | **Fixed in #34:** deleted user's conversation title resurrected on the next rename | `orca/serve/account_delete.py` | personal data persisted after deletion | review | test in `test_product_flows_fake_ollama.py` |
| G-026 | P1 | **FIXED (kernel-direct `/api/stream`):** Kernel plans with `defer_direct_generation` and `/api/stream` forwards `ModelGateway.stream()`; disconnect cancels upstream. Truth-Fabric and frontier paths that already hold a complete answer stay labelled `replayed`. Original finding: Simple answers were generated non-streaming and delivered as one chunk | `orca/cognitive`, `orca/serve/api.py` | frontier/OpenAI still replayed | native model streaming on frontier backends | remaining replayed paths stay honestly labelled |
| G-027 | P1 | **FIXED in #36** (`orneur.sources/1`; Truth Fabric passages via optional `CognitiveResult.evidence_passages`). Original finding: No structured sources (source, locator, retrieved-at) in the stream `done` event | `orca/serve/api.py`, `orca/truth` | UI source cards have no contract | UI (P2) | `done.sources[]`; xfail flips |
| G-007 | P1 | Conversation durability is opt-in | `serve/session_store.py` | history lost on restart | — | durable store by default for non-dev profiles; restart test |
| G-008 | P1 | No licensed search provider | `truth/search_provider.py` | unreliable/ToS-risky research | founder (D-5) | pluggable provider, rate limits, tests with a recorded fixture |
| G-009 | P2 | Real connectors absent | `orca/connectors` | integrations are mock-only | scope decision | ≥1 real read-only connector with contract + audit tests |
| G-010 | P1 | Model artifacts not archived/recoverable | §2 | evidence can be lost | owner access | hash-verified archive manifest of adapters/GGUF + Kaggle exports (**owner action**) |
| G-011 | P1 | Raw eval reports never committed | §2.2 | all NOVUS metrics unreproducible | G-010 | committed report JSON + command + hash per metric; independent re-run |
| G-012 | P1 | Conflicting readiness claims in docs | §7 | wrong decisions | — | this register referenced; conflicts reconciled |
| G-013 | P1 | Six baseline test failures unexplained | §6 | masks regressions | — | **Causes established** (§6); flaky test fixed in this PR; others run non-root/with DNS |
| G-014 | P1 | Genesis foundation unresolved | §2.1 | blocks any Genesis training | V2 eval, D-3 | frozen V2 eval + candidate comparison per pre-registered criteria |
| G-015 | P1 | **FIXED in #36** (`model_identity`). Original finding: No per-response model-lifecycle disclosure | `serve/api.py` | users cannot tell which model answered | UI (P2) | header + visible label on every response |
| G-016 | P2 | Accessibility & responsive layout absent | UI | unusable on mobile/AT | redesign | WCAG 2.2 AA audit pass, mobile viewport tests |
| G-017 | P2 | No end-to-end browser tests | `tests/frontend` (1 file) | UI regressions invisible | redesign | Playwright suite for chat, auth, upload, stream, cancel |
| G-019 | P1 | **Fixed in #28:** directory validation opened every ancestor with `O_RDONLY`; an execute-only (`0711`) ancestor owned by another user makes startup fail with `PermissionError` | `orca/config.py::_mkdir_owner_only` (PR #22/#23) | spurious startup failure on some hosts | — | ancestors opened with `O_PATH` where available; test with a 0711 root-owned ancestor |
| G-018 | P3 | No load/soak, alerting, restore drills | ops | reliability unknown | deployment | k6-style load report; alert rules; restore drill log |

## 6. Baseline test failures — root causes (G-013)

Established by running each as root and as uid 65534 and by direct probes (VERIFIED):

| Test | Cause |
|---|---|
| `test_eval_sandbox.py` ×2 (`…blocked_by_resource_limit`, `…os_system_spawn…`) | **Root-specific** — pass as uid 65534 (mechanism not traced; consistent with uid 0 not being bound by process limits) |
| `test_genesis_v2_tier0s_phase_gate.py::test_Q6_…mocked_metadata` | **Root-specific** — passes as uid 65534 (the test's ownership check special-cases uid 0) |
| `test_training_provenance.py::test_snapshot_files_…chmod_readonly…` | **Root-specific** — passes as uid 65534 (consistent with uid 0 ignoring file permissions) |
| `test_truth_fetch_security.py::test_ssrf_risk_not_flagged_for_ordinary_public_url` | **Environment** — `example.com` does not resolve here (`gaierror`), and the SSRF check fails closed |
| `test_redteam_jailbreak_trials.py::test_avg_block_rate_differs_from_strict_block_rate` | **Genuine flake** — shared counter inside a 6-thread pool; four identical runs gave `20.0, 20.0, 10.0, 0.0`; with one worker it is deterministically `0.0`. Passes in CI by scheduling luck. **Fixed in this PR** (sequential worker). |

## 7. Conflicting claims found (to reconcile)

1. Genesis foundation: `model_spec.py`/Phase 20 "SELECTED (Qwen2.5-3B)" vs Phase 21 `foundation_selected: null`.
2. `ORCA_BLUEPRINT.md` "Genesis fine-tune complete" vs Phase 20 "never trained" (reconciled in §2.1: legacy vs canonical).
3. `LIVE_SERVING_CUTOVER.md` says the live core tier serves `orca-core-combined-v2`; the repo default is `orca-core`. Deployment-dependent.
4. `docs/orneur/phase-0/MODEL_TRAINING_STATUS.md` ("Genesis never received the joint treatment", Novus attempt 3 "pending") predates `NOVUS_PROMOTION_DECISION.md`.
5. Documented "training authorization gates" were described as mandatory; before PR #24 they were not code-enforced.

## 8. Founder decisions required

| ID | Decision | Default until decided |
|---|---|---|
| D-1 | May the retired Qwen-7B Genesis keep serving the nano tier on a public edge? | Serves (unchanged) |
| D-2 | Approve/reject the UI design specification (P2) | No UI implementation starts |
| D-3 | Provision a training authority key (registry + pin, reviewed) | **Training NO-GO** |
| D-4 | Public-edge UX when `core` is refused (error vs step-down to nano) | Error (closed) |
| D-5 | Search provider licensing for research workflows | DuckDuckGo scraper stays, flagged |
| D-6 | Owner action: archive Novus/Genesis artifacts and export raw eval reports | Not done |
| D-7 | **Agent tools (G-020):** `shell`/`read_file`/`write_file` run with the server's authority and one shared workspace — drop them for web sessions, confine per session, or sandbox? | Disabled on the web in #35 (no flag); re-enable only via the per-user execution design |
| D-8 | Genesis served under the default alias `orca-nano` is no longer treated as legacy on a public edge (only `orca-nano-v7`); set `ORNEUR_NANO_MODEL=orca-nano-v7` or issue a grant. Also: adopt signed public-serving grants as the only path to a public experiment? | Refused (closed) until decided |
| D-9 | Provisioning flow for the first owner account (G-021) before any public deployment | Operator token procedure implemented in #35; the founder must run `python -m orca.auth.bootstrap issue` on the host |
| D-7 | Merge order and timing for #19–#25 after Antigravity | Nothing merged |

## 9. Execution board

| Pri | Work package | Status |
|---|---|---|
| P0 | Training authorization gate (#24) | Implemented; CI 9/9; audit pending |
| P0 | Experimental serving policy (#25) | Implemented; CI 9/9; audit pending |
| P0 | PR #23 independent retest | Awaiting Antigravity Audit #008 |
| P1 | This register + baseline-failure causes + flake fix | In this PR |
| P1 | G-003 container non-root (#27) / G-019 (#28) | Implemented; CI 9/9; audit pending |
| P1 | G-006 tenant-isolation adversarial tests + fixes (#30) | Implemented; CI see PR; **G-020 needs a decision** |
| P2 | Design specification + Light/Dark screens for founder review | Delivered in #29; **awaiting D-2** (no implementation before approval) |
| P4 | GENESIS/NOVUS future-training preparation docs | Not started |

## 10. Restrictions in force (unchanged)

RSE-ARCH-1.2 frozen · Manifest V3 protected · R65 `NOT_VERIFIABLE` · C27/Class K unresolved · G1 pending · pre-training 0/95 · no founder
trust roots provisioned · secure P1/P2 not qualified · protected corpus generation unauthorized · GENESIS training NO-GO · NOVUS resumption
unauthorized · Phase 21C not authorized · no merges · no live keys · no GPU · no spend.
