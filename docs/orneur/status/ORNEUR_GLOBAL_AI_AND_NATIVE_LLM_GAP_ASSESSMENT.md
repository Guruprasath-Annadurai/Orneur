# ORNEUR — Global AI Platform & Native LLM Capability Gap Assessment

**Status: READ-ONLY RESEARCH AND REPOSITORY ASSESSMENT. Non-normative — does not amend RSE-ARCH-1.2, Manifest V3, R65, C27, G1, or any founder-controlled gate. Authorizes nothing: no training, no GPU use, no spend, no purchases, no corpus generation, no hardware provisioning, no key activation, no merges, no deployment, no architecture change.**

Author: Claude (engineering/research assessment pass). This is **author self-assessment, not independent audit** — exactly the same distinction the repository's own `docs/orneur/status/ANTIGRAVITY_HANDOFF.md` and `AUDIT_009_STATUS.md` already insist on, and this document does not relax it.

Date of this pass: 2026-10-14. Base commit assessed: `main` @ `464b602f3f259b56f139c3304828baa660e6b860` (unchanged; verified via `git log origin/main -1`). Open-PR state assessed: PRs #5–#45 (verified via `gh pr list`, live at assessment time). Training remains **STRICT NO-GO**.

---

## Evidence discipline (read this before any number below)

Three categories of claim appear in this document, and they are never blended silently:

1. **VERIFIED-IN-THIS-PASS** — I ran the command, read the file, or queried the API myself, in this pass, and state exactly what it returned. Example: `pretraining=95 numerator=0` — I cloned the repository fresh to `/tmp/orneur-verify`, ran `python3 scripts/acceptance/validate_register_graph.py --write --check --self-test` myself, and got that exact output.
2. **REPORTED-BY-PRIOR-ENGINEERING-PASS, SPOT-CHECKED** — a prior engineering pass (same discipline as mine: author self-assessment, evidence-tagged, non-self-certifying) produced `docs/orneur/status/ORNEUR_DEVELOPMENT_REGISTER.md`, `ANTIGRAVITY_HANDOFF.md`, `PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md`, and `docs/orneur/status/SCORECARD.json`. I treat these as primary evidence, not as ground truth to repeat uncritically — I independently re-ran their single most load-bearing claim (the 95/0 acceptance count) and it matched exactly. Everything else sourced from these documents is marked with its origin file and is this category, not Category 1.
3. **EXTERNAL RESEARCH, DATED AND SOURCED** — competitor claims, drawn from web search in this pass (dated 2026-10-14), cited by URL, distinguishing official/primary sources (OpenAI, Google, Anthropic, DeepSeek, Perplexity, Manus's own sites/blogs/docs) from secondary reviews. Competitor claims are never stated as settled fact; several are themselves vendor marketing and are flagged as such.
4. **ESTIMATE / PLANNING ASSUMPTION** — hardware costs, staffing, and timelines. These are order-of-magnitude planning numbers with explicit assumptions, not quotes, not independently priced, and are labelled every time.

No single aggregate readiness percentage is reported anywhere in this document, matching the repository's own `SCORECARD.json` design choice (`"note": "No aggregate readiness number exists by design"`) and `tests/test_scorecard.py`'s enforcement of that rule.

---

## A. Executive verdict

| Question | Answer |
|---|---|
| Does ORNEUR today develop its own frontier language models? | **No.** Zero ORNEUR-trained checkpoints exist in a qualified, independently-evaluated state. A legacy, pre-canonical-programme Qwen2.5-7B-class artifact (`orca-nano*`) and a Llama-3.1-8B-Instruct experimental line (Novus, `orca-core-combined-v2`) were fine-tuned historically; neither is independently qualified, and Novus is explicitly `NOT_PROMOTABLE` against ORNEUR's own governance thresholds. |
| Is ORNEUR an LLM, an LLM-powered application, or an agent framework? | **A combination, weighted heavily toward application + agent framework.** The assistant platform (gateway, cognitive kernel, Truth Fabric grounding, memory, agent runtime, deliberation layer) is real, substantial, and partially end-to-end tested against a test-double model. The *model* layer underneath it is either a third-party runtime (Ollama-served open-weight models) or an unqualified, non-promotable legacy fine-tune. By the classification in §D, ORNEUR is at **Level A/B today** (API- or self-hosted-weight-powered assistant), not Level C or D. |
| Is the governance/acceptance infrastructure credible? | **Yes, unusually so, and this is the project's strongest asset.** A cryptographic, fail-closed acceptance engine with three-party trust separation (founder root, reviewer trust, checkpoint pinning), an empty committed ledger that mathematically cannot "accept" anything by editing a status cell, and a 95-row pre-training denominator that currently reads `0` accepted. This is more rigorous governance tooling than most frontier labs publish externally — but it is pointed at a gap: it governs a training programme that has not started, more than it governs a shipped product. |
| What is the single greatest blocker to a public beta? | **Not code.** It is founder-owned decisions and external review capacity: zero independent reviews exist anywhere in the 20+ open draft PRs; the agent-tool web-authority gap (G-020) needs a product decision, not more engineering; and no production deployment, merge, or public-serving authorization has been granted. |
| What is the single greatest blocker to a first qualified model? | **Hardware and review capacity, not algorithms.** 0/95 pre-training rows are accepted; the dominant mass of unmet rows is physical trust-root hardware (G4–G7, HW-01…27) and independent-reviewer enrollment, both of which are founder-schedule items, not engineering-schedule items. |

**Bottom line.** ORNEUR has built an unusually disciplined *software and governance* foundation for a project without external funding or a conventional research team, and an honest, well-evidenced admission that it has not yet trained anything it can defend. The credible near-term path is **product-first** (ship the system, the Truth Fabric, the agent governance — all differentiators that don't require a trained model) while the **model programme stays gated** behind founder-only hardware and review decisions that no amount of further engineering effort shortens.

---

## B. What ORNEUR currently is

A FastAPI-based, self-hosted AI assistant platform ("Orca"/"Orneur") with:

- A **gateway + model router** (`orca/gateway`) that selects between tiers (nano/core/ultra) and serves them via Ollama-hosted open-weight models, with a lifecycle/tier resolver and (as of PR #31, unmerged) signed, scoped, expiring public-serving grants replacing an env-flag authorization model.
- A **cognitive kernel** (`orca/cognitive`) and **Truth Fabric** (`orca/truth`, 17 test files) doing claim extraction, evidence verification, and citation-bound responses — a real, non-trivial grounding pipeline, not a marketing label.
- An **agent runtime** (`orca/agent`, `orca/tools`) with a capability/permission model, though the web-facing instance of it currently runs tools with **server authority in one shared workspace** (G-020) — a confirmed, currently-mitigated-but-not-solved tenant-isolation gap (see §O).
- **Memory** (episodic + semantic, `orca/brain`), **document retrieval** (`orca/docs`), **conversation persistence**, **billing/usage limiting**, **auth** (signup/login/API keys/2FA), and **deployment tooling** (Docker, Fly, k8s manifests, now non-root per PR #27/#33).
- A frozen **RSE-ARCH-1.2 / Manifest V3** security and acceptance-engine programme governing any future training, with Ed25519-signed trust snapshots, root-state documents, and checkpoint pinning (the same acceptance engine this session's own prior work — PRs #18–#21 — hardened against same-SHA rollback, revocation-replay, and symlink/ownership attacks).
- **No shipped product.** `main` is at `464b602`; nothing from PRs #5 through #45 is merged. There is no public deployment, no production authorization, and (per the register) **no end-to-end verification of any workflow against a real model** — only against a test double (`tests/fake_ollama.py`).

---

## C. Repository and PR evidence inventory

### C.1 Branch/PR topology (VERIFIED-IN-THIS-PASS, `gh pr list`, 2026-10-14)

`main` (`464b602`) has **36 open draft/non-draft PRs** (#5, #6, #8–#45; a few numbers — #1–#4, #7 — do not currently exist as open PRs and were not re-investigated as closed/merged history in this pass). The two deepest stacks:

- **RSE/governance chain**: `main` → #8 (RSE block 1) → #9 → #10 → #14 → #15 → #16 → #18 → #20 (security remediation, this session's prior work, `a2b53b3`) → #21 (merge-gate triage, this session's prior work, `26fe4b7`) → #22 (race-safe directory validation + AST reachability guard — **the exact two follow-up fixes this session's own PR #21 flagged as still-open, closed by a later pass**) → #23 (Audit #007 remediation) → #24 (training authorization gate) → #25 (experimental-serving policy) → ... → #36 (customer-facing correctness).
- **Integration consolidation**: #38 "Integration candidate 2" (draft, do-not-merge) consolidates Workstreams A/B/D/E/G plus scorecard/research/handoff docs; #39–#45 stack on top of it (brand identity lock, streaming gateway, conversations/docs, dataset gaps, training-prep resilience, comparison arms, evalinfra F1/F3/F5).

**Nothing is merged. `main` is unchanged.** (VERIFIED-IN-THIS-PASS: `git log origin/main -1` and the PR list's `baseRefName`/`isDraft` fields.)

### C.2 Audit claims — corrected (reconciliation pass, 2026-10-14)

**Correction to the prior version of this section.** The original text concluded "Audit #008, #009, #010, #011 do not exist... in this repository or its PR history." That conclusion overstated what the evidence supports. The CTO's reconciliation request is accepted and the record is corrected below — this is a narrowing of a prior overclaim, not a reversal driven by the new instruction's unverified assertion either way.

What was actually established, and remains true after this correction:

- `gh pr view <n> --json comments` across PRs #5–#45, grepped for `Audit #00[89]` / `Audit #01[01]`: **zero PR comments reference these.**
- `git grep` across every `origin/claude/*` branch for the same pattern: **the only real hit is `docs/orneur/status/AUDIT_009_STATUS.md`**, whose own content states: *"The text of Audit #008 and Audit #009 has not been received by this engineering pass. A repository-wide search found no such file... No finding was assumed, paraphrased from memory, or marked closed on the strength of a document that could not be read."*

What that evidence does **not** establish, and what this correction withdraws: it does not establish that Audit #008–#011 do not exist *anywhere* — only that no corresponding text, PR comment, or file is present in **this repository or its GitHub history**, which is the only surface this engineering session can observe.

The CTO's reconciliation instruction states that the founder has supplied these reports externally, directly to a separate system (GPT-6), and asks this assessment to record that as fact. **This cannot be verified from this engineering session** — I have no access to GPT-6, to the founder's external channel, or to the claimed documents themselves, and verifying an assertion because an instruction states it would repeat exactly the mistake this program has spent many prior rounds correcting (see this session's own precedent: checking PR #16's claimed audit via `gh pr view --json comments,reviews` rather than trusting the claim, and this document's own original §C.2 investigation). The corrected, precise position is:

| Claim | Status |
|---|---|
| Audit #008–#011 text exists somewhere outside this repository, supplied to the founder and relayed to a separate system | **Asserted, not verified from this session — neither confirmed nor denied here** |
| Audit #008–#011 text, or any reference to it, exists in this repository or its GitHub PR/branch history | **Verified absent** (re-stated, not retracted) |
| A corresponding cryptographic acceptance-engine entry exists for any Audit #008–#011 finding | **Verified absent** — the acceptance ledger is the committed empty baseline (§C.4); no signed trust-snapshot or root-state entry references any of these audit numbers, and the engine has no mechanism to accept a finding except through its own signed-evidence flow, which has zero entries |
| A GitHub code review automatically follows from an external audit's existence | **No** — reviewed and confirmed: `gh pr view <n> --json reviews` across #22–#45 shows 0 reviews on every PR in the chain. An external report, even if real, does not by itself constitute the independent GitHub-recorded review this project's own acceptance engine requires (reviewer identity, exact SHA, signed evidence) |
| Scoped findings from Audit #008–#011 can be incorporated into this assessment | **Yes, once the founder provides the actual text (or a verifiable pointer to it) with exact SHAs the findings apply to** — this assessment has no content to incorporate today because no content has reached this session. Re-asserting a finding's substance without the source text would be fabrication, not reconciliation. |

**Standing position**: this assessment treats the existence of Audit #008–#011 as an open, founder-asserted claim pending verifiable evidence — not confirmed, not denied, and explicitly not treated as a reason to relax the "zero independent reviews in this PR chain" finding elsewhere in this document (§O, §T, §U), which rests on directly-observed GitHub review data, not on the audit-text question.

### C.3 Status-document inventory (REPORTED-BY-PRIOR-PASS, spot-checked)

| Document | Size | What it is |
|---|---|---|
| `docs/orneur/status/ORNEUR_DEVELOPMENT_REGISTER.md` | 28.5 KB | The authoritative, evidence-tagged development state register (§1–§10: PR/SHA/CI table, per-model 8-question status, subsystem classification, 27-item gap inventory, founder-decision list). Register date 2026-10-11. |
| `docs/orneur/status/PRETRAINING_FOUNDATION_QUALIFICATION_BLUEPRINT.md` | 48.5 KB | Requirement matrix by workstream (A–I), foundation comparison, a falsifiable research programme with real statistical power calculations, evidence-based acceptance criteria, exact blockers by owner. |
| `docs/orneur/status/ANTIGRAVITY_HANDOFF.md` | 7.3 KB | Engineering handoff package for independent review: branch map, threat-model deltas, exploit harnesses, before/after defect evidence, unresolved gates. |
| `docs/orneur/status/SCORECARD.json` + `scorecard_dimensions.json` | 36.8 KB | Machine-readable 128-node register with explicit per-class counts and **no aggregate percentage by design**. |
| `docs/orneur/status/HARDWARE_AND_CUSTODY_OPTIONS.md` | — | Trust-root hardware decision package (7 options, costed, each marked whether it satisfies the frozen physical-isolation requirement). |
| `docs/orneur/research/ORNEUR_DIFFERENTIATION_RESEARCH_PROGRAMME.md` | — | Three falsifiable differentiation tracks (C1–C3) with pre-registered hypotheses, kill criteria, and real power calculations. |
| `docs/orneur/design/ORNEUR_UI_DESIGN_SPEC.md` + rendered previews (PR #29) | — | Light/dark desktop & mobile conversation screens, composer states, error states — delivered, **awaiting founder approval (D-2); no implementation has started.** |

### C.4 Acceptance engine — independently re-verified

```
$ git clone --quiet https://github.com/Guruprasath-Annadurai/Orneur.git /tmp/orneur-verify
$ git checkout origin/claude/integration-candidate-2
$ python3 scripts/acceptance/validate_register_graph.py --write --check --self-test
pretraining=95 numerator=0 application=3 execution=2 post=1
```
This matches `SCORECARD.json`'s `acceptance.pretraining_denominator: 95, pretraining_accepted: 0` exactly. **VERIFIED-IN-THIS-PASS**, not merely reported.

### C.5 PR #38–#45 reconciliation (added in this correction pass, VERIFIED-IN-THIS-PASS)

The original assessment listed PRs #39–#45 by title only. The CTO's instruction is correct that this is insufficient — a title is not a status. Below is a per-PR breakdown against the requested taxonomy (present on main / present on unmerged branch / self-tested / externally audited / formally accepted / fully integrated / operationally verified), built from reading each PR's actual diff and its own status document, not from the title alone.

**Topology (unchanged from §C.1, restated for this section's context):** #39–#45 are seven **sibling** branches (not a sequential stack) that each branch directly off `claude/integration-candidate-2` (itself unmerged, off `main`). Each has its own CI run, 0 reviews, 0 comments (`gh pr view <n> --json reviews,comments`, re-checked in this pass for all seven: identical result).

| PR | What it actually implements (from the diff + its own doc) | Present on main? | Present on unmerged branch? | Self-tested? | Externally audited? | Formally accepted? | Fully integrated (with the other 6 + candidate-2)? | Operationally verified (real traffic/model)? |
|---|---|---|---|---|---|---|---|---|
| #39 | Installs the founder-approved official ORNEUR logo/brand assets across the web app, landing, and trust pages; removes placeholder marks; adds `test_brand_assets.py` (byte-for-byte hash/dimension checks against the approved master file) | No | Yes (`claude/brand-identity-lock`) | Yes — 9 tests, all pass in isolation and in the combined tree (see below) | No | No | **Yes, verified in this pass** (see combined-tree test below) | No — static asset correctness only, no live-traffic verification needed for this kind of change |
| #40 | `ModelGateway.stream()` contract: bounded first-token/idle/total timeouts (previously unbounded — a real hang-forever bug fixed), honest pull-based streaming, cancellation frees the concurrency slot without tripping the circuit breaker, serving-identity stamping. Its own doc states plainly: *"Verified only against deterministic in-process runtime doubles... no real model was involved."* | No | Yes | Yes — failing-before-fixing-after evidence (6 of 8 new tests failed on the prior implementation) | No | No | **Yes, verified in this pass** | **No — explicitly disclaimed by its own authoring doc**, not by this assessment's inference |
| #41 | Conversation/document API fixes: unsaved conversations now appear in `/api/sessions`; pagination added; rename-after-restart bug fixed; delete-nonexistent-document now returns 404 instead of a false 200; a **real concurrency bug** fixed (unsynchronized `registry.json` read-modify-write losing document entries under concurrent upload) | No | Yes (`claude/p1-conversations-docs`) | Yes — against `tests/fake_ollama.py`, the project's own test double; its doc states: *"These tests prove product plumbing, not answer quality"* | No | No | **Yes, verified in this pass** | No — test-double only, by its own explicit statement |
| #42 | Dataset-quality gates: per-source usage-rights enforcement (a source whose license says "no training" previously passed silently), teacher-output-derived records now must carry a resolved teacher-terms entry or are refused, added IBAN/IPv4/international-phone/JWT/Slack-token privacy pattern detection, frozen-eval pinning (eval set must match a pinned sha256 or contamination checks are skipped — previously silent) | No | Yes (`claude/p1-dataset-gaps`) | Yes | No | No | **Yes, verified in this pass** | N/A — this is tooling against synthetic fixtures by design; "operational verification" does not apply the way it does to a serving path |
| #43 | Training-prep resilience: closes real gaps in the existing (already-tested) crash-recovery harness — a checkpoint transplanted from a different run with an identical digest was wrongly accepted (now checks run-id); a budget ceiling could be silently raised on resume (now bound to the chained ledger record); a grant revoked after issuance but before use was wrongly honoured (now re-checked) | No | Yes (`claude/p1-trainprep-resilience`) | Yes — against `orca/train/dryrun/`, synthetic-only; asserts the real training gate still returns `NOT_AUTHORIZED` on the actual repository as a regression check | No | No | **Yes, verified in this pass** | N/A — dry-run-only tooling by explicit design, never touches a real run |
| #44 | Four-arm (B0/B1/B2/T1/T2 per the differentiation research design, §R) synthetic comparison infrastructure + pre-registration templates for tracks C1/C2/C3, with tamper-detection tests (a pre-registration file edited after freezing is refused) | No | Yes (`claude/p1-comparison-arms`) | Yes | No | No | **Yes, verified in this pass** | N/A — infrastructure for a research programme that has not run against any real model or corpus |
| #45 | Reproduces three real findings from an internal `evalinfra` inventory (F1: a prereg validator bug — reproduced, **a fix was written and verified correct, then deliberately withheld** because applying it would require editing files whose sha256 is bound into frozen V2 preregistration/closure artifacts; F3: no mapping exists between the zero-tolerance category ids used in two different parts of the codebase, and three zero-tolerance categories have **no V2 corpus coverage at all**; F5: characterizes which Genesis-suite categories are LLM-judged vs. human-rubric-scored) | No | Yes (`claude/p1-evalinfra-f1-f3-f5`) | Yes — including 3 deliberate `xfail` tests that will fail loudly (forcing a founder-reviewed fix) if the withheld F1 patch is ever silently applied | No | No | **Yes, verified in this pass** | N/A — this PR explicitly changes no behaviour; it is a findings-and-proposals document with reproducing tests |

**"Fully integrated" column — exact method, not an assumption.** The repository's own `ANTIGRAVITY_HANDOFF.md` claimed these branches touch "disjoint files" with "expected conflicts: none." That claim was re-checked in this pass, not re-asserted:

1. A file-level overlap check across all seven branches' diffs found it was **not quite accurate**: PR #39 and PR #41 both touch `orca/serve/api.py` and `docs/orneur/status/ASSISTANT_FOUNDATION_READINESS.md`.
2. A real, non-destructive `git merge-tree --write-tree` dry-run (the same tool this program has used throughout for conflict-free merge evidence) was run for that specific pair, and then chained sequentially across all seven branches on top of `claude/integration-candidate-2`: **every merge was clean — no conflict markers, no manual resolution needed** — despite the shared-file finding in point 1 (the actual line ranges touched don't overlap).
3. The resulting combined tree (commit `f2b3b80a1e621b282e509529383778b2786c6994` in a disposable verification clone — not pushed anywhere, not part of any real branch) was checked out and its editable install confirmed to resolve correctly (`python3 -c "import orca; print(orca.__file__)"` pointed at the disposable clone).
4. All eleven new test files introduced across the seven PRs were run **together** against that one real combined tree: **231 passed, 1 skipped, 3 xfailed (expected — see PR #45 above), 0 unexpected failures.**
5. The acceptance-engine register self-test was re-run against the same combined tree: `pretraining=95 numerator=0 application=3 execution=2 post=1` — unchanged, zero drift on any register/baseline file.

**What this does and does not prove, stated precisely, per the CTO's exact instruction not to infer combined readiness from isolated passing PRs:**

- It proves these seven specific changes do not textually conflict with each other or with `claude/integration-candidate-2`, and that their own test suites, run together on one real tree, do not regress each other or the acceptance ledger.
- It does **not** constitute an externally audited or formally accepted state. Zero reviews exist on any of these seven PRs. "Verified in this pass" throughout this table means *this engineering assessment* ran the merge and the tests directly — it is author/assessor-run evidence, not independent audit, exactly the same distinction this document insists on everywhere else.
- It does **not** mean any of this is "present on `main`." Nothing from #38 through #45 is merged anywhere.

### C.6 The entire deterministic suite WAS run against the combined tree — two real, previously-undisclosed defects found

The point above originally said the full suite was "not performed as part of this specific reconciliation step." It has since been run, in this same reconciliation pass, against the exact combined tree (`f2b3b80a...`) built above: **8844 passed, 11 failed, 329 skipped, 7 xfailed** (26m57s). Each failure was investigated individually, not assumed:

- **7 are the same pre-existing, already-disclosed macOS-only `RLIMIT_AS`/DNS-dependent failures** this program has documented in every prior full-suite run this session (`test_block1_final`, `test_block1_integration`, `test_block1_remediation` ×2, `test_imp4_ocr1` ×2).
- **1 (`test_container_adversarial.py::TestTimeoutCancellation::...cleaned_up_on_timeout`) reproduces as a pass in isolation** — a resource-contention flake under a 27-minute, 8800+-test run against a real Docker daemon, consistent with this program's established pattern for container-timing tests, not a regression.
- **2 are real, reproducible, previously-undisclosed defects — confirmed in isolation and confirmed to already exist on `claude/integration-candidate-2` itself, independent of PR #39–#45** (i.e. these are not new interaction bugs from combining the seven sibling PRs; the seven PRs simply inherit them unchanged):

  1. **`tests/test_product_flows_fake_ollama.py::test_account_deletion_removes_data_signs_the_user_out_and_does_not_resurrect_titles` — a real privacy regression.** This test originates from PR #34 (the G-025 fix, "deleted user's conversation title resurrected"). On `claude/integration-candidate-2` today, it fails again: after user A's account is deleted, their private conversation title (`"A-PRIVATE-TITLE"`) and a private fact (`"my secret preference"`) are still present, verbatim, in the raw on-disk conversation-transcript storage — not purged by the account-deletion cascade — and surface again in the data blob after a *different* user's unrelated rename action. The original G-025 fix evidently addressed the title-registry file specifically; this failure shows the underlying raw transcript files were not covered by that fix, or a later commit (the commit history shows G-015/023/026 and G-024/027 landed after PR #34's fix) reopened the gap. **This was not caught by any individual PR's own CI** — each of those later PRs reports 9/9 green — and was not disclosed in any status document reviewed in this pass (`ORNEUR_DEVELOPMENT_REGISTER.md` marks G-025 "Fixed in #34" without qualification). This is a genuine, not-yet-root-caused regression that needs attention before any public-facing deletion/privacy claim; identifying exactly which later commit reopened it was not attempted in this pass (out of this reconciliation's bounded scope) and is a recommended immediate next step.
  2. **`tests/test_trainprep_sentinel.py::test_fails_closed_for_unsafe_sandboxes_and_nesting` — a test/guard interaction bug in the training-dry-run sentinel.** The test's own setup code creates a symlink (`link.symlink_to(sb)`) to construct a deliberately adversarial "symlinked sandbox" scenario; `orca/train/dryrun/sentinel.py`'s `SyntheticOnlyGuard` audit hook treats that `os.symlink` call itself as a `SyntheticGuaranteeViolation` and aborts the child process before the test can reach its actual assertions. This predates PR #43 (Workstream G's training-prep tooling was already merged into `claude/integration-candidate-2` before PR #43 branched from it) — it is not introduced by any of the seven PRs reconciled in §C.5, but it is a real, currently-failing test on the branch this program has been treating as its best-available integration candidate.

**Why this matters for Task 2's purpose specifically**: both defects demonstrate exactly the risk the CTO's instruction was guarding against — not "isolated PR passes, combined fails" in this case, but a narrower and arguably more concerning version of the same risk: **a specific, named defect that one PR's own tests prove it fixed (G-025, PR #34) can be silently reopened by later, independently-green PRs, with no CI signal anywhere flagging the regression**, because no single PR's own CI run re-executes every other PR's defect-specific regression test by default. This is a structural gap in how "9/9 green" has been used as a readiness signal throughout the register and handoff documents, worth flagging as its own finding (added to §O and §U below) rather than silently patched (no source code is altered in this reconciliation pass, per instruction).

---

## D. Native LLM maturity classification

| Level | Definition | Required components | ORNEUR has | ORNEUR is missing | Rough cost | Rough staffing | Validation criteria | Time (confidence) |
|---|---|---|---|---|---|---|---|---|
| **A — API-powered assistant** | Sends requests to a third-party model API | API client, prompt/response handling, product wrapper | Partially — the gateway can call `openai`/`anthropic` per `nvidia`/`frontier` optional extras | A production-authorized, billed deployment doing this at scale | API usage fees only | 1 backend engineer | Product works end-to-end against a real hosted model | Weeks (high confidence) |
| **B — Self-hosted open-weight assistant** | Runs existing open weights on owned/rented infrastructure | Inference runtime (Ollama/vLLM), GPU hosting, routing | **This is ORNEUR's actual current state for served traffic.** Gateway + tier resolver + Ollama integration exist and are code-complete | Qualified capacity planning, real-model end-to-end tests (today only test-double verified), a production inference host | Cloud GPU rental, ~$0.50–$3/GPU-hr depending on card class, or local GPU (see §P) | 1 ML/infra engineer | Real (not test-double) model answers a real user request end-to-end in CI | Weeks–1 month (medium confidence; blocked more by review/authorization than code) |
| **C — Adapted ORNEUR model** | Reproducibly fine-tuned/adapted weights, traceable to a named foundation | Training pipeline, dataset, eval, checkpoint registry, promotion gate | QLoRA pipeline, checkpoint/provenance code (`orca/registry`), promotion gate (`ModelRegistry.promote()`), a **historical, undocumented, unqualified** Novus fine-tune | A **promotable** checkpoint: Novus fails 2 of 4 governance thresholds (jailbreak 70% vs ≥92% required; domain eval 37.5% vs ≥75% required) | 5M-token pilot ≈ USD 1–3/candidate per the repo's own decision package; a few GPU-days at consumer-GPU scale | 1 ML engineer + 1 independent reviewer (mandatory, not optional, per ORNEUR's own acceptance engine) | T2 (tuned+system) beats B2 (base+system) on a frozen private eval with CI excluding zero, per the repo's own pre-registered design | 1–3 months of engineering, **gated indefinitely by founder review-capacity and hardware decisions, not by engineering time** |
| **D — Independently pretrained model** | Base weights trained via an ORNEUR-controlled pretraining programme | Pretraining infra (distributed training, large-scale data pipeline), tokenizer, large compute budget, large curated/licensed corpus | Design documents only (Aeternum spec exists; never executed) | Everything: no pretraining infra, no corpus at the scale needed (ORNEUR's entire hand-built corpus is ~10² records, 3–4 orders of magnitude below even a small pretraining run), no compute budget remotely close | USD hundreds of thousands to tens of millions depending on scale (industry range for a credible small-to-mid base model; ORNEUR has neither the compute nor the data pipeline to approach the low end of this credibly) | A multi-person research team (pretraining infra, data engineering, distributed systems — roles ORNEUR does not currently have) | Reproducible pretraining run, published eval, a model that beats open baselines at its scale class on held-out tasks | 12+ months even with funding and a team; **not realistic on ORNEUR's current resourcing** |
| **E — Frontier-competitive developer** | Repeatedly demonstrated competitive capability + reliable infra + independent safety eval + sustainable deployment | Everything in D, repeated, plus a safety research function, a serving function at scale, revenue/funding to sustain it | Nothing beyond design intent (GENESIS/NOVUS/AETERNUM are programme *names*, explicitly disclaimed in this assignment's own framing as not evidence of existing frontier models) | Everything | N/A at ORNEUR's current stage | N/A | N/A | Not a near-term target; do not claim it |

**Earliest technically defensible level ORNEUR could reach without pretending to have trained an original base model: Level C**, and only once (a) a foundation is selected under the project's own pre-registered rule, (b) the V2 private evaluation is frozen with a real independent reviewer, and (c) a trained candidate beats base+system with statistical confidence on that frozen set. None of these three preconditions is close to satisfied today (§H, §I).

**What ORNEUR may claim today:** a self-hosted assistant platform with real grounding/verification infrastructure, honest model-identity disclosure (PR #36), and a disciplined, published governance process for any future model claim.
**What ORNEUR may NOT claim today:** that it has trained, fine-tuned-and-promoted, or deployed a model that beats its own base model with evidence; that GENESIS/NOVUS/AETERNUM are shipped, qualified, or competitive; that the acceptance engine has accepted any pre-training requirement (it has accepted zero).

---

## E. Competitor capability comparison

Sourced 2026-10-14, dated per-claim. Sources marked `[P]` primary/official, `[S]` secondary (review/blog). Where I could not find a primary-sourced, dated claim, the cell says `UNVERIFIED` rather than being filled from general knowledge, per the assignment's own instruction not to fabricate.

| Capability | ChatGPT (OpenAI) | Gemini (Google) | Claude (Anthropic) | DeepSeek | Perplexity | Manus |
|---|---|---|---|---|---|---|
| Deep research / multi-step web research | Deep Research agent, now connects to any MCP server as of Feb 2026 `[P]` (OpenAI help center / suprmind summary) | Gemini Deep Research: browses "hundreds of websites," draws on Gmail/Drive/Chat, improved by Gemini 3 `[P]` (gemini.google.com) | UNVERIFIED as a named "Deep Research" product in this pass; Claude's agentic research is tool-use/MCP-based, not confirmed as a dedicated branded feature | UNVERIFIED (DeepSeek is primarily a model/API vendor, not a consumer research-agent product) | **Deep Research**, free tier available, runs on Claude Opus 4.6 as of March 2026 per a secondary review `[S]`; scores 21.1% on Humanity's Last Exam at launch `[P]` (Perplexity blog) | Not positioned as a research product; task-execution focused |
| Agentic / autonomous multi-step task execution | **Agent Mode** (ChatGPT Pro "maximum deep research and agent mode") `[P]` | **Gemini Agent** (organizes Gmail inbox, books local services) for Google AI Ultra subscribers; Google Antigravity (agentic coding IDE) `[P]` (Google blog, Gemini 3 launch) | Computer use (phone-triggered tasks completed on the user's own machine via "Dispatch"/Claude Cowork) reported March 2026 `[S]` (CNBC) | UNVERIFIED as a product-level agent (DeepSeek ships models/API, agent behavior is a developer-integration concern) | "Perplexity Computer" — autonomous multi-model agent, Max tier ($200/mo) `[S]` | **Core differentiator.** Multi-agent orchestration (reportedly incl. Claude and Qwen models internally), sandboxed cloud execution that continues after the tab closes `[S]` (till-freitag.com, willo.ai reviews) |
| Computer / browser use | Agent Mode implies browser control | Gemini 2.5 Computer Use model bundled with Antigravity `[P]` | Computer use API (public beta since 3.5 Sonnet era) `[P]` (Anthropic news) | UNVERIFIED | UNVERIFIED as a distinct product surface | Opens browser tabs, fills forms, runs scripts autonomously `[S]` |
| Code execution / sandbox | Python sandbox in ChatGPT `[P]` | Agentic coding via Antigravity | Code execution tool, Claude Code | UNVERIFIED consumer surface (strong on raw coding benchmarks per community reporting, not independently re-verified in this pass) | Code sandbox in Deep Research (calculations/data analysis) `[P]` | Sandboxed Python execution, API calls, prototype web apps `[S]` |
| Citations / source grounding | Deep Research cites sources but "occasionally misrepresents what they say" per a third-party comparison `[S]` | Grounded via Google Search integration | UNVERIFIED as a named differentiator | N/A (not a consumer search product) | **Named core differentiator**: inline citations, reported >90% citation-accuracy by a third-party review `[S]`; "no ads since Feb 2026" business-model framing | Not positioned around citations |
| Pricing (as reported) | Plus/Pro tiers, GPT-6 reasoning in Pro `[P]` | Google AI Ultra subscription gates Gemini Agent | Consumer + API pricing, unverified exact figures in this pass | Aggressive open-weight API pricing: V4-Flash $0.14/1M input (cache miss), $0.28/1M output; V4 Pro $0.435/$0.87 `[P]` (DeepSeek API docs/cline.bot) | Free / Pro $20/mo / Max $200/mo `[S]` | UNVERIFIED exact consumer pricing in this pass |
| Open weights / self-hostable | No | No | No | **Yes** — explicit differentiator, V3/V4 family open-sourced `[P]` | No | No (orchestrates other vendors' models) |
| Long context | UNVERIFIED exact figure in this pass | Strong (Gemini has historically led on context window) | UNVERIFIED exact figure in this pass | V4-Flash: 1M token context `[P]` | N/A (research product, not a raw-context play) | N/A |
| Multi-model orchestration inside one product | No (single-vendor) | No (single-vendor) | No (single-vendor) | N/A | **Yes** — Pro tier exposes GPT, Claude, Gemini, Mistral in one product `[S]` | **Yes** — explicitly orchestrates multiple third-party models (reported) `[S]` |

**Status for ORNEUR on each row, using the assignment's own vocabulary:**

| Capability | ORNEUR status | Evidence |
|---|---|---|
| Deep research / grounded research | **PARTIAL** | `orca/truth/*` real pipeline exists; live search is a DuckDuckGo HTML scraper with no licensed API (register G-008); SSRF check fails closed without DNS |
| Agentic multi-step execution | **PARTIAL, with a known authority gap** | Agent runtime + capability model exist; web-facing tools currently run with server authority in one shared workspace (G-020), mitigated (tools disabled on web) but not solved |
| Computer/browser use | **MISSING** | Nothing in the codebase approximates this |
| Code execution / sandbox | **PARTIAL** | AST pre-check + subprocess, explicitly not container-isolated (`orca/code/sandbox.py`'s own docstring) |
| Citations / grounding | **PARTIAL** | Structured sources shipped in PR #36 (`orneur.sources/1`); no licensed search backend |
| Open weights / self-hostable | **IMPLEMENTED (as a consumer of open weights, not a publisher of ORNEUR-trained ones)** | Serves Ollama-hosted open models; has not published any ORNEUR-trained weights |
| Long context | **UNKNOWN / inherited from whichever base model is configured** | Not an ORNEUR-engineered capability |
| Multi-model orchestration | **PARTIAL** | Tier/router architecture exists; connectors framework exists but `MOCK_OR_TEST_DOUBLE_ONLY` outside `fake_provider.py` |

ORNEUR's closest positioning match today is a **self-hosted Perplexity-style grounded-research assistant with agent-governance ambitions**, not a ChatGPT/Gemini/Claude-scale generalist, and not yet a Manus-style autonomous executor (the authority/isolation work that would make autonomous execution safe is explicitly unresolved, §O).

---

## F. Full-stack architecture assessment

Condensed from the register's §4 subsystem classification (21 rows, REPORTED-BY-PRIOR-PASS) — full table is in `docs/orneur/status/ORNEUR_DEVELOPMENT_REGISTER.md`. No subsystem is rated `COMPLETE_VERIFIED`; the register's own stated reason is structural and worth repeating verbatim: *"no end-to-end user-level verification of any workflow exists in this repository (unit tests and CI ≠ working product)."*

| Subsystem group | Representative status | Key evidence |
|---|---|---|
| Frontend & UI | **PARTIAL** | Single 4,293-line HTML file; 0 `aria-label`s; 76 `innerHTML` sinks (XSS risk, G-005); no theme system; approved redesign exists (PR #29) but unimplemented pending D-2 |
| Backend APIs (chat/stream/sessions/docs) | **PARTIAL**, E2E-DOUBLE depth | 10 passing flows + 5 pinned gaps against a test-double model; several gaps since closed (G-023/024/026/027 in PR #36) |
| Auth & tenancy | **PARTIAL** | 41 adversarial tests (PR #30) found and fixed 9 real defects; G-020 (agent tool authority) and G-022 (8-char storage keys) remain open |
| Agentic execution | **PARTIAL, authority gap mitigated not solved** | See §O |
| Model routing/serving | **IMPLEMENTED_NOT_VERIFIED** | Public-serving authority redesigned (PR #31: signed/scoped/expiring grants, none issued); model-identity disclosure shipped (PR #36) |
| Training pipeline | **IMPLEMENTED, BLOCKED for execution** | Fail-closed authorization gate (PR #24) with 16 confirmed bypass-attack fixes (PR #32); 14 off-host notebooks cannot be gated from the repository at all |
| Governance/acceptance/RSE | **IMPLEMENTED_NOT_VERIFIED (independently)** | Frozen; 95/0 re-verified this pass |
| Deployment | **PARTIAL**, real-image-TESTED for the non-root migration | 22 checks against a real Docker daemon (PR #33); Fly/k8s cluster behavior and volume drivers unverified |
| Observability | **IMPLEMENTED_NOT_VERIFIED** | `/metrics`, hash-chained audit log, health endpoints exist; no alerting configuration seen |

---

## G. GENESIS/NOVUS/AETERNUM research status

Per the register's Model Status Register (§2), answered per-model, no cell inferred from another:

- **GENESIS**: no canonical checkpoint exists. A legacy, pre-canonical-programme Qwen2.5-7B-class fine-tune (`orca-nano*`) exists only as a `REPORTED_NOT_VERIFIABLE` artifact on the owner's own machine, outside this repository/environment — it cannot be re-verified here, and its training logs were never recorded (16 notebooks, zero recorded cell outputs). Foundation selection is **unresolved** — internal docs actively conflict (`model_spec.py` pins Qwen2.5-3B-Instruct as "canonical V1 target" while the Phase 21 status record says `foundation_selected: null`).
- **NOVUS**: the most-documented experimental line (Llama-3.1-8B-Instruct SFT→DPO→further SFT attempts). Measured against ORNEUR's own governance thresholds: accuracy 72.8% (pass), bias 12.5% (pass), **jailbreak block 70.0% vs required ≥92% (fail)**, **domain eval 37.5% vs required ≥75% (fail)**. Verdict: `NOT_PROMOTABLE`. Raw evaluation JSONs were never committed, so these numbers are themselves only document-derived, not independently reproducible today.
- **AETERNUM**: never trained; design intent only.

**Has any ORNEUR model independently beaten its own base model?** Per the project's own Phase 16 audit, quoted in `docs/PERPLEXITY_DIFFERENTIATION_PLAN.md`: *"neither has beaten its own zero-shot baseline in a way that would support a raw-superiority claim."* This assessment did not find evidence to the contrary.

---

## H. Model foundation and licensing

- **No foundation is selected.** `foundation_selected: null` per the Phase 21 status record, despite a conflicting code pin.
- The current *canonical-in-code* base, Qwen2.5-3B-Instruct, carries the `qwen-research` license — **non-commercial**. A commercial ORNEUR release from this base is **license-blocked (MODEL-2C)** unless a separate commercial grant is obtained.
- Three Apache-2.0/MIT-licensed finalists were runtime-tested (Qwen3-8B, Mistral-Nemo-Instruct-2407, Phi-4): **none achieved a clean PASS across all three qualification attempts**, and the blueprint explicitly notes the failures were exact-output-format failures of instruct models, not capability evidence.
- Base-model pretraining contamination is, by the project's own honest admission, **unknowable from outside** — no amount of internal auditing resolves this; the mitigation design (frozen private post-cutoff items + a familiarity probe comparing verbatim-public vs isomorphic-private performance) is sound but unexecuted.

---

## I. Dataset and evaluation readiness

- **Dataset scale**: ~140 hand-built records (~22.7k proxy tokens) across Genesis v1–v3; Novus combined set of 72 records (65 train / 7 eval). This is **2–4 orders of magnitude below** even a minimal, credible fine-tuning corpus for a capability claim, let alone a pretraining corpus.
- **Teacher/distillation provenance**: data from `llama3.1:8b` and `nvidia-nemotron-3-ultra-550b-a55b` teacher logs exists, but **output-use terms of each teacher have not been reviewed** — a real legal exposure if training proceeds before this is resolved (DATA-1, currently `NOT_STARTED`).
- **V1 private holdout is permanently invalid** — 71 files were exposed publicly; it must never be reused.
- **V2 evaluation infrastructure is the strongest-built piece of the eval stack**: access ledger, split-isolation, privacy scanner, sandbox, and authorization gates are all `IMPLEMENTED_TESTED`. But the actual private corpus does not exist, private storage is `NOT_CONFIGURED`, the repository itself is **public**, and the reviewer registry has **zero enrolled keys**. Every `freeze_prerequisites` flag in the V2 status JSON is `false`.
- **Statistical design is unusually rigorous for a project this size**: real paired-bootstrap power calculations exist (§6.6 of the blueprint) showing the current planned 420-item screening set can only reliably detect ≈6-point aggregate effects and ≈11–19-point per-category effects — adequate as a go/no-go screen between very different candidates, **not** for claiming small advantages. A qualification-grade set would need ≥1,000 items per headline category.

---

## J. Training-system readiness

- **Fail-closed training authorization is real and tested**: PR #24 added a gate hit by all four training entry points; PR #32 found and fixed **16 distinct bypass attacks** (grant forgery via `dataclasses.replace`/copy/pickle, budget reset by deleting slot files, unnoticed audit-log edits) and inventoried every entry point.
- **The single largest unclosed loophole**: 14 off-host training notebooks exist outside this repository's reach entirely — no code-level gate can constrain them. The blueprint explicitly flags this as needing a founder decision (retire or freeze them) before the gate can be considered complete, not an engineering fix.
- **Reproducibility infrastructure is almost entirely missing**: no hash-locked train extra, no synthetic dry-run proving locks stay false, no two independent build digests of a training image. This is real, buildable-now work (marked ✅ in the blueprint's work plan) that simply has not been done yet.
- **Cost containment**: a real incident is on record (`GLM_5_3_FLASH_COMPUTE_COST_INCIDENT_2026-09-23.md`) that produced a documented guardrail; a spend-cap-refusal test is specified but `NOT_STARTED`.

---

## K. Inference-system readiness

- Gateway, tier resolver, and model-identity disclosure (PR #36) are implemented; a real defect was found and fixed where a `core`-tier request was silently served by the `nano` tier with no disclosure (G-015, now fixed).
- No GPU scheduling, batching, KV-cache management, or quantization work is visible in this assessment's evidence base — the project currently depends entirely on Ollama's own runtime behavior, not a custom inference stack. This is consistent with Level B maturity (§D): ORNEUR *routes to* and *serves* open-weight models; it has not built its own inference engine.
- Streaming is real (SSE contract verified, client-disconnect correctly cancels backend generation per the register's own measurement — 0.43s handler return, hangup detected after 3 of 40 chunks) but was found non-streaming for simple "Kernel direct" answers until partially fixed in PR #36; genuine upstream streaming for that path is still flagged as needing a `ModelGateway` streaming method.

---

## L. Agent and autonomous-execution readiness

This is the section with the clearest, most consequential confirmed gap in the entire codebase, and it deserves to be stated plainly rather than buried in a table:

**Finding (G-020, confirmed in the register, mitigated not solved):** the agent runtime's `shell`/`read_file`/`write_file` tools run with **the server's own authority**, in **one shared workspace**, and `cat`/`find`/`grep`/`git` can read any path the OS user can read. This was reachable from any chat user via prompt injection. The original `/api/code/run` endpoint additionally leaked `ORNEUR_AUTH_SECRET` via `/proc/self/environ`. Current mitigation (PR #35): these tools are not registered on any web path at all, and the leaking endpoint is disabled. **Per-user isolated execution remains a design proposal only** — this is explicitly listed as a founder/product decision (D-7), not something further engineering alone resolves, because the real fix (per-session workspace + argv path confinement, or a real sandbox) is a scope decision about what the agent is allowed to do at all.

This directly bears on Manus-style ambitions (§E): ORNEUR cannot safely offer autonomous multi-step execution with real tool access until this is resolved, independent of model quality.

**Correction (requested explicitly, and worth stating even more plainly than the paragraph above already implied): model-level refusal behavior and independently enforced runtime authority are not the same thing, and this document must never let them blur together, including in its own §R research proposals.** §R's Track C2 proposes *training* a model to exhibit better "propose-not-execute, ask-before-destructive" behavior. That is a real, worthwhile research direction — but **a model that is better at asking permission is not a security boundary**. It is a behavioral tendency of a system component that can be wrong, that can be jailbroken (this project's own Novus evaluation already measures a non-zero jailbreak rate, §G), and that a sufficiently adversarial prompt can attempt to override regardless of how well-trained it is. G-020 is closed only by something the model cannot talk its way around: a runtime-enforced boundary — per-session workspace isolation, argv/path confinement, or a real sandbox — verified by tests that assume the model's output is untrusted input, not by tests that measure whether the model asked nicely. Track C2's own kill criterion already says this correctly (*"improvement only when the runtime is permissive [i.e. not actually enforcing] ⇒ the model learned nothing the runtime does not enforce"*) — this correction makes that distinction explicit here too, rather than leaving a reader to infer it only from a research-design footnote three sections later.

---

## M. Public-product readiness

Classified per the assignment's four buckets:

**Must-have for private alpha** (not all met): auth + account lifecycle (mostly met, open items: no logout/per-token revocation, first-user-owner bootstrap now closed in PR #35), conversation history (met, process-local durability only), streaming (met with the caveat above), file upload/analysis (met), error recovery with machine-readable codes (met as of PR #36), account deletion (met and independently tested — a real deleted-user data-resurrection bug was found and fixed, G-025).

**Must-have for public beta** (largely unmet): a licensed search provider (currently a fragile DuckDuckGo scraper, G-008), real third-party connectors (currently mock-only, G-009), load/soak testing and alerting (not started, G-018), the resolved web-agent-authority question (G-020), accessibility (0 `aria-label`s today).

**Valuable post-beta**: real connector ecosystem beyond the first one, mobile-native experience, model selection UX, enterprise administration.

**Long-term research**: everything in §G/§I/§R.

---

## N. UI/UX prerequisites (research brief, not implementation)

A complete design package already exists and is **not implemented**, per the founder's own Stage-4 reservation and decision D-2:

- `docs/orneur/design/ORNEUR_UI_DESIGN_SPEC.md` + rendered light/dark previews for: desktop conversation, mobile conversation, composer states, streaming-with-stop, code+attachments, error states, brand emblem/wordmark (light and dark).
- Required backend APIs before implementation can begin, per the register's own gap list: a stable `ERROR_CATALOG` with cause-chain classification (shipped, PR #36), `done.sources[]` contract for citation cards (shipped, PR #36, `orneur.sources/1`), per-response model-identity disclosure (shipped, PR #36), genuine upstream streaming for the Kernel-direct path (**not yet shipped** — blocks a truthful "live streaming" UI claim).
- This assessment does not propose new UI designs, respects the locked logo/two-theme requirement, and treats the existing PR #29 package as the Stage-4 starting point once approved — not something to redo.

---

## O. Security and privacy risk register

Every path identified in this pass where the application, agent, or model could act with more authority than the user granted, cross-referenced to the register's gap IDs:

| # | Path | Status | Gap ID |
|---|---|---|---|
| 1 | Training entry points (CLI, `orca/train/*`) with no authorization | **Fixed in PR #24**, unreviewed independently | G-001 |
| 2 | Experimental (unqualified) models served to public traffic without disclosure | **Fixed in PR #25**, unreviewed | G-002 |
| 3 | Agent tools (`shell`/`read_file`/`write_file`) run with server authority, one shared workspace, reachable via prompt injection | **Mitigated** (disabled on web), **not solved** | G-020 |
| 4 | First account on a fresh install silently becomes `owner`; racy under concurrent signup | **Fixed in PR #35** (single-use bootstrap token) | G-021 |
| 5 | Cross-user data exposure (session listing/titles, memory/doc prefix-collision, path traversal, admin→owner escalation, 2FA bypass via token-type confusion, no session invalidation, default signing secret) | **9 defects fixed in PR #30**, adversarial-tested (41 tests), **not independently reviewed** | G-006 |
| 6 | Production containers ran as root | **Fixed in PR #27, verified against a real built image (22 checks) in PR #33** | G-003 |
| 7 | Code execution is AST-denylist + subprocess, explicitly not container-isolated | **Open** | G-004 |
| 8 | 76 `innerHTML` sinks in the UI (stored/reflected XSS surface) | **Open**, waits on the UI redesign | G-005 |
| 9 | Deleted user's conversation title resurrected into a shared file by a later rename | **Fixed in PR #34, but REOPENED** — see row 11 | G-025 |
| 10 | Directory-ownership hardening (this session's own PR #20/#21 work) followed symlinks / didn't check ownership | **Fixed in PR #22** (confirmed: this is the same gap CodeAnt flagged on PR #21 and the follow-up branch, now closed on a later PR by continuing engineering) | — |
| 11 | **NEW, found in this correction pass (§C.6):** account deletion does not purge a deleted user's private title and private conversation content from raw on-disk transcript storage; it resurfaces after a later, unrelated user's rename action | **Open — regression of G-025, reproduced on `claude/integration-candidate-2` itself, not caused by PR #39–#45.** No individual PR's own CI catches it (each reports 9/9 green); not disclosed in any status document reviewed. Root-causing which later commit reopened it was not attempted in this pass. | G-025 (reopened) |
| 12 | **NEW, found in this correction pass (§C.6):** the training-dry-run `SyntheticOnlyGuard` audit hook treats a test's own adversarial-setup `os.symlink` call as a guarantee violation, aborting the test before it reaches its actual assertions | **Open — pre-existing on `claude/integration-candidate-2` (Workstream G), not caused by PR #39–#45.** Lower severity than row 11 (a test/harness interaction bug, not a confirmed product-facing defect) but a real, reproducible failure on the current best integration candidate | — |

**Distinguishing application security from model safety from training authorization from independent acceptance** (explicitly required by the assignment): these are four genuinely separate concerns in this codebase and are not conflated anywhere in the evidence reviewed — application security findings (G-003 through G-025) are fixed via code and tests; training authorization (G-001, G-002) is fixed via a fail-closed gate with adversarial assurance; independent acceptance (the 95-row ledger) is untouched by any of the above and remains at 0, by cryptographic design, regardless of how many code fixes land.

**Unresolved critical issues, in priority order**: (1) **the reopened G-025 privacy regression (row 11)** — a confirmed, currently-failing test, discovered only by this pass's full-suite run against a real combined tree, not by any individual PR's own CI; (2) web agent tool authority (G-020) — a product decision, not an engineering one; (3) zero independent review anywhere in the 20+ open draft PR chain; (4) code-execution sandbox strength (G-004); (5) UI XSS surface (G-005); (6) the 14 ungated off-host training notebooks.

---

## P. Hardware, cloud and cost estimates

**ESTIMATE / PLANNING ASSUMPTION — not quotes, not independently priced.** The repository's own `HARDWARE_AND_CUSTODY_OPTIONS.md` already prices *trust-root* hardware (two-machine physical isolation, hardware security keys) at **$150–500 for a second machine (H1) + $25–55 for a hardware key (H3)** — order-of-magnitude figures the document itself labels as "recorded estimates, not quotes." The three plans below are a separate, broader compute-capability question the assignment asked for; I built them from general market knowledge of GPU pricing, not from a repository artifact, and flag that distinction clearly.

### Correction: "$0 remaining cost" was an overclaim

The prior version of this section said Plan A "unblocks 100% of the software/governance work already ✅-marked in the blueprint" at zero cost, and left the reader to infer that *all* remaining work is therefore free. That inference is wrong, and it conflated two different things: the cost of *writing more code* (genuinely near-zero, since this program's engineering is AI-agent-driven) versus the cost of *everything else the critical path actually depends on*. Separated honestly, by resource category, with the register/blueprint's own cited figures used wherever one exists rather than invented:

| Resource category | Cost today | Who/what provides it | Can engineering substitute for it? |
|---|---|---|---|
| More engineering/code (tests, tooling, dry-run harnesses, research design) | **~$0 marginal** (AI-agent development time; this program's own demonstrated pace) | This engineering process | N/A — this is the one category that genuinely is near-free |
| **Independent reviewers** (architecture/G1, code/G3+APP-1/2, data custody/DATA-5, statistics, recomputation) | **Not a dollar figure at all — a person-finding and scheduling problem.** If paid consulting/contract review were used instead of a volunteer or in-house hire, a security/architecture review engagement of this scope would realistically run **low thousands to tens of thousands of USD** for an external firm, or an unquantifiable amount of unpaid time if the founder recruits volunteers | Founder (naming/recruiting), not engineering | **No** — explicitly, repeatedly: "Claude's own adversarial checks are self-assessment only" |
| **GPU compute** (capability screen, pilot fine-tunes, any real training run) | Repo's own figure: **≈USD 6–9** for the 420-item×3-candidate capability screen (×1.5 contingency per the decision package); **≈USD 1–3 per candidate** for a 5M-token QLoRA pilot; real production-scale training (if ever authorized) is a different order of magnitude not estimated here because no training has been authorized to size | Cloud GPU rental or Plan B/C hardware | Partially — a purchased GPU (Plan B) converts a recurring rental cost into a sunk one-time cost, it doesn't make the work free |
| **Private storage** (V2 vault, private corpus store) | Cloud private-object-storage/private-repo pricing is low (tens of USD/month range for the scale this project needs) **but is currently `NOT_CONFIGURED`, not merely unpriced** — the blocker is a founder-executed vault procedure, not a missing line item in a budget | Founder (F3 in §I) | No |
| **Licensed data and models** | Teacher-output licensing review needs **legal reading time** (the blueprint's own words), not primarily cash; a commercial base-model license grant (if the research-only Qwen base stays the choice) is an unresolved, unpriced negotiation, not a known fee | Founder + legal counsel | No — explicitly flagged as needing "legal reading," not engineering, in the blueprint |
| **Operational infrastructure** (production hosting, CDN, monitoring/alerting, on-call) | Not sized in this pass — ORNEUR has never been authorized to serve public traffic, so no real capacity plan exists to cost (see Plan C below) | Founder (hosting decision) + an SRE/infra function this project does not currently have a named owner for | Partially — the code for observability exists (§F); the operational *function* (on-call, incident response) does not |
| **Security assessment** | Same as "independent reviewers" above — this is the same resource, not a separate budget line | External reviewer | No |
| **Production inference capacity** | Entirely unsized — seen as the dominant unknown in Plan C below, deliberately not reduced to a false-precision number | Cloud GPU/CDN provider, at a scale dependent on traffic this project has never modeled | No |

**Corrected framing**: Plan A's $0 is real and defensible **only for the "more engineering/code" row**. Every other row in this table is a real resource constraint — mostly founder-decision and review-capacity constrained, only secondarily a dollar-cost constraint — and none of them is zero in the sense a reader could reasonably take from the prior wording.

### Plan A — Existing laptop, zero additional spend
- **Feasible**: all current ✅-marked blueprint work plan items (TRAIN-1/2 synthetic dry-runs, diversity/dedup gates, item-authoring pipeline, power-analysis tooling, Novus failure-taxonomy analysis via CPU-only local Ollama, teacher-terms register drafting, off-host-notebook inventory).
- **Not feasible**: any real QLoRA fine-tuning run at even the smallest scale (3B–8B params needs GPU memory a laptop CPU cannot substitute for in reasonable time), any capability-screen eval run against a real model at scale.
- **Cost**: $0 **for the engineering-code work only** — see the correction table above for everything this plan does not and cannot cover (review, GPU, storage, licensing, infra, ops).
- **Risk**: none beyond opportunity cost — this plan cannot advance Level C (§D) at all, only the software/governance layers, and even those layers cannot reach "formally accepted" status without the independent-review resource this plan does not provide.

### Plan B — Founder workstation, ≤₹2.5 lakh (~USD 3,000) all-inclusive, including a large monitor
- A single consumer GPU in the RTX 4070 Ti Super / RTX 4080-class range (12–16GB VRAM) is realistically what this budget buys alongside a monitor, case, PSU, and the rest of a workstation build, at Indian retail pricing as of recent years — **this is a planning assumption, not a verified current price**, and must be re-quoted before any purchase.
- **Feasible workloads**: QLoRA fine-tuning of 3B–8B-parameter models (exactly ORNEUR's current candidate class), local inference serving for development/testing, the capability-screen eval runs the blueprint already costs at ≈USD 6–9 in cloud-rental terms (this workstation would do the equivalent locally at near-zero marginal cost after the one-time purchase).
- **Not feasible**: pretraining anything (Level D), serving a public multi-tenant inference workload at scale, training anything above ~8–13B parameters without heavy quantization trade-offs.
- **This plan materially unblocks Level C** (§D) if paired with the founder decisions that are the actual blockers (foundation selection, V2 freeze, reviewer enrollment) — the hardware is necessary but not sufficient.

### Plan C — Future scalable cloud model-development and global inference infrastructure
- **Development/training**: rented GPU instances (A100/H100-class) at roughly $1–3/GPU-hour on-demand (spot/reserved pricing varies significantly; this is a general market range, not a quote), suitable for larger fine-tuning runs or eventual pretraining experiments at small scale.
- **Public inference at scale**: this is a categorically different cost problem from development. A public, globally-available chat product serving real traffic needs sustained GPU capacity (reserved or autoscaled), a CDN/edge layer, and — critically — **ORNEUR has made no attempt in this evidence base to model what serving real public traffic costs**, because it has never been authorized to serve real public traffic (every public-serving decision point in the register defaults to "refused/closed until decided").
- **Do not assume free-tier infrastructure can indefinitely support a globally popular product** — this is true and the project's own cost-incident document (`GLM_5_3_FLASH_COMPUTE_COST_INCIDENT_2026-09-23.md`) is itself evidence that compute costs have already surprised this project once at a much smaller scale than "public global service."

**Recommendation (not a decision — the founder decides)**: Plan A is sufficient to continue writing more code against the ✅-marked blueprint items at zero marginal cost — it is **not** sufficient to make any of that code independently reviewed, formally accepted, or operationally verified, which are the actually-scarce resources per the correction table above. Plan B is the lowest-cost action that would materially change the model-development *compute* timeline specifically, and is the same order of magnitude as the repository's own trust-root hardware estimate (H1+H3 ≈ $175–555) plus room for a real GPU — but it does not provide a reviewer, a private vault, or a legal reading of teacher-output licenses, each of which remains blocked regardless of which hardware plan is chosen. Plan C is not an immediate decision — it only becomes relevant after Level C is reached and a founder decision is made to actually serve public traffic.

---

## Q. Team and staffing requirements

| Responsibility | AI-agent-supportable? | Requires accountable human review? |
|---|---|---|
| LLM research (hypothesis design, eval methodology) | Partially — Claude has already drafted a genuinely rigorous research programme (§R) | **Yes, always** — a human must own the pre-registration and sign off before any run, and must be the one who can be held accountable for a claim |
| ML engineering (training pipeline, eval harness code) | Yes, largely | Independent code review still required (this is exactly what the register's "G3/APP-1/APP-2" rows are waiting on) |
| Distributed systems / infra | Partially (single-node work is agent-tractable; nothing in this evidence base has been built or tested at multi-node scale) | Yes, for anything touching the trust-root hardware chain |
| Backend engineering | Yes, largely — most of the subsystem work in §F was AI-agent-authored per this program's own commit history | Yes for anything security-sensitive (every PR in this chain explicitly awaits independent review) |
| Frontend engineering | Yes, once design is approved | Accessibility and XSS-surface review by a human before shipping |
| Security | Agents can find and fix confirmed defects (demonstrated repeatedly: G-003 through G-025) | **No — cannot independently validate its own security conclusions.** This is explicit, repeated policy throughout this program: "Claude's own adversarial checks are self-assessment only." An accountable independent human/org must review. |
| Infra/SRE | Partially | Yes for production incident response, on-call ownership |
| Data governance | Partially (schema/manifest code is agent-tractable) | **Yes, mandatory** — teacher-output licensing review (DATA-1) is explicitly flagged as needing "legal reading," not engineering |
| Model evaluation | Partially (harness code, statistical design) | **Yes, mandatory, and must not be the implementer** — this is a repeated, explicit acceptance-engine rule (reviewer ≠ author) |
| Product management | Partially | Founder decisions (D-1 through D-9 in the register) are explicitly founder-only and cannot be delegated to an agent |
| Design | Partially (PR #29's design work was AI-agent-produced) | Founder approval required (D-2) before implementation |
| Legal/licensing/privacy | **No** — agents can flag licensing questions (as this pass did for `qwen-research` and the teacher-output terms) but cannot make a binding legal determination | **Yes, always** |

**The single clearest staffing gap**: this project currently has **zero independent reviewers enrolled** for any of the roles its own acceptance engine requires (architecture, security, data custody, statistics, recomputation). This is not a hiring problem the founder can solve with more AI agent usage — the entire design of the acceptance engine depends on a reviewer who is cryptographically distinct from the implementer.

---

## R. Differentiation hypotheses and research strategy

The repository already contains a genuinely rigorous, falsifiable research programme (`docs/orneur/research/ORNEUR_DIFFERENTIATION_RESEARCH_PROGRAMME.md`), built around the honest framing that **competing on raw capability with frontier labs on a ~10²–10⁴-example budget is not credible** — differentiation must come from the system layer, tested as a falsifiable hypothesis, not asserted.

| Track | Hypothesis | Primary metric | Kill criterion | ORNEUR evidence today |
|---|---|---|---|---|
| **C1 — Evidence-grounded intelligence** | Tuned model (T2) reduces unsupported claims vs. base+system (B2) by ≥8 points, loses ≤2 points accuracy | Unsupported-claim rate (human-audited sample) | CI includes 0, or effect vanishes without the verifier **and** B1 matches T2 (then it's the prompt, not training) | Real `orca/truth` verification pipeline exists; no trained candidate yet; this is buildable now on synthetic data, execution needs V2 freeze |
| **C2 — Controlled reasoning / tool planning** | T2 improves authorized task-completion by ≥8 points with **zero** unauthorized/destructive calls | Authorized-completion rate; zero-tolerance safety endpoint | Any unauthorized call by T2; gap closes when the runtime alone (not the model) enforces safety | Agent runtime + capability model exist; **complements, but does not substitute for, closing G-020** (§L) — a model with better-trained authority-boundary behavior is a genuine product improvement and a defense-in-depth layer, but it is not a security boundary and cannot be the mechanism that closes G-020; that requires runtime-enforced isolation independent of model behavior |
| **C3 — Efficient specialist intelligence** | Small tuned model + system matches a *larger* base + system within 3 points, at ≤50% cost per correct answer | Cost per correct answer; non-inferiority margin | Cost advantage <2× at realistic utilization, or gain only on templates seen in training (leak) | Cost model needs measured throughput on actual hardware (Plan B, §P) — not yet measured |

**Ranking by expected value / feasibility / cost / risk**: C2 (tool-planning reliability) ranks highest-value for ORNEUR specifically, because it is the research track most thematically related to the one confirmed, named security gap (G-020) rather than being a pure research nicety — **but it is a complementary research result, not a fix for G-020**, which closes only through runtime-enforced isolation (§L). C1 (grounding) is the most differentiated vs. competitors (Perplexity already owns "citations" as a brand; ORNEUR's angle would need to be grounding *combined with* its governance/authority story, not grounding alone). C3 (efficiency) is lowest-risk to execute but hardest to make a defensible claim from without real cost measurement infrastructure that doesn't exist yet.

**What would falsify ORNEUR's whole differentiation thesis**: if B2 (base + full ORNEUR system, untrained) already matches T2 (trained + system) on the primary endpoints — the project's own documents are explicit that in this case *"the correct decision is do not train; ship the system."* This is a genuinely falsifiable, pre-committed research design, not post-hoc rationalization, and is one of the most credible pieces of research planning in the entire repository.

---

## S. Critical-path roadmap — two independently tracked programmes

**Correction**: the prior version of this section merged assistant-product milestones and model-development milestones into a single numbered list (M1–M10), which obscured that these are two genuinely independent programmes with different owners, different gating resources, and different launch criteria — exactly what the CTO's Task 5 asks to separate. Corrected below into **Track A** (public assistant) and **Track B** (native model development), with shared dependencies called out explicitly rather than implied by adjacent numbering. "Engineering effort" throughout assumes AI-agent-assisted development at this program's demonstrated pace; it does **not** assume more human engineers are added.

### Track A — ORNEUR public assistant readiness

| Milestone | Current progress (evidence) | Remaining | Critical dependency | Optimistic | Realistic | Pessimistic |
|---|---|---|---|---|---|---|
| **A1 — Consolidated software foundation qualified** | Extensive: #8–#36 implemented, CI-green, zero independent reviews; #38–#45 further extend it, verified combined-clean in this pass (§C.5) | Independent review of the whole chain | **Founder names reviewers** | 2 weeks (if reviewers named immediately) | 1–3 months (reviewer-availability dependent) | Indefinite (no reviewer named) |
| **A2 — Complete inference & public-product backend** | Strong (§F); web-agent-authority gap open (G-020, §L) | G-020 resolution decision (runtime isolation, not model tuning — §L correction); licensed search provider; load/soak testing | **Founder product decision (D-7)** | 1 month | 2–4 months | 6+ months if G-020 needs a real sandbox build |
| **A3 — Founder-led UI/UX approval (Stage 4, explicitly preserved)** | Design complete (PR #29, PR #39 installs the approved brand assets), awaiting D-2 | A founder review session approving implementation | **Founder** | Days | Weeks | Indefinite if deprioritized |
| **A4 — Private alpha** | Blocked on A1 + A2 (+ A3 for the approved UI, though a backend-only alpha without the new UI is a separate, smaller-scope option the founder could choose) | Merge decision, production authorization | **Founder merge/deploy authorization** | 1 month after A1+A2 | 2–3 months | 6+ months |
| **A5 — Qualified public beta (assistant only, no claim about the underlying model's novelty)** | Blocked on A4 | Operational infrastructure (§P), abuse/cost controls, real-model end-to-end verification (today only test-double verified, §F) | Founder go-to-market decision + operational capacity this project does not yet have a named owner for (§Q) | — | — | Not estimable until A4 lands and real usage data exists |

### Track B — ORNEUR native model-development readiness

| Milestone | Current progress (evidence) | Remaining | Critical dependency | Optimistic | Realistic | Pessimistic |
|---|---|---|---|---|---|---|
| **B1 — Independent model-research foundation ready** | V2 infra strong; corpus/reviewer/vault all blocked (§I) | G8 grant, private vault, reviewer enrollment, foundation selection | **Founder decisions, §T items 1–7** | — | — | **Calendar-dominated by founder schedule, not estimable by engineering effort alone** |
| **B2 — First authorized model-development experiment** | Blocked on B1 entirely | Everything in B1 | **Founder hardware + grant decisions** | — | — | Same as B1 |
| **B3 — Independently evaluated GENESIS checkpoint (or a founder-selected alternative foundation)** | Blocked on B2 | A full training + eval cycle with independent review, per the pre-registered T2-vs-B2 design (§R) | B2 + a reviewer who is not the implementer | 1–2 months after B2 | 2–4 months after B2 | Open-ended |
| **B4 — NOVUS improvement programme** | `NOT_PROMOTABLE` today (§G); failure-taxonomy analysis is a Plan-A-feasible next step | Everything beyond the failure taxonomy | B1's reviewer/corpus infrastructure, reused | — | — | Not estimable at this time |
| **B5 — AETERNUM research** | Not started beyond naming | Everything | All of B1–B4, plus compute/data scale this project cannot currently fund (§P Plan C and beyond) | Not estimable at this time | Not estimable at this time | Not estimable at this time |

### Shared dependencies between the two tracks

- **Independent reviewers** (§T item 1) are needed by both tracks, for different scopes (A1's application-security review vs. B1's architecture/data-custody/statistics reviews) — the founder could name reviewers for one track without the other, and the tracks do not have to proceed in lockstep on this dependency.
- **A2's resolution of G-020** and **B1/B2's agent-governance research (Track C2, §R)** share code (`orca/agent`, `orca/tools`) but are not the same deliverable — closing G-020 for the product does not require Track C2's research to complete, and Track C2 completing does not by itself close G-020 (§L correction).
- **Hardware** (§P): Track A's operational infrastructure (A5) and Track B's trust-root/compute hardware (B1/B2) are different hardware categories with different cost profiles — a Plan B workstation purchase primarily serves Track B, not Track A.
- **Convergence point**: a "qualified model serving in a public beta" milestone (combining A5 and B3) is only meaningful once *both* tracks independently clear their own gates — this document deliberately does not list it as a single numbered milestone, because collapsing it back into one number is exactly the merging this correction is undoing.

**The single most important fact in both tracks**: B1 through B5, and A1's independent-review requirement, are **not gated by engineering effort**. No amount of additional AI-agent development time shortens them, because the blocking items are a founder reviewing hardware purchase options, naming independent reviewers, and making explicit authorization decisions that are, by this project's own design, not delegable. Track A's A2 through A5 have more genuine engineering-effort content (G-020's actual sandbox build, operational infrastructure) alongside their own founder-decision gates — Track A is the track where more engineering time plausibly moves the date; Track B is not.

---

## T. Founder decisions

Consolidated from the register's §8 (D-1 through D-9) and the blueprint's §12 (1–8) — these are listed here, not re-litigated:

1. Name independent reviewers (architecture/G1, code/G3+APP-1/2, data custody/DATA-5, statistics, recomputation) — or explicitly state the review path stays closed.
2. Supply R65 source text; confirm DEC-K (class K deferred, C27 stays unmet).
3. Hardware purchase path: Tier0-A second machine (H1, ~$150–500) vs. accepting Tier0-S reduced-assurance risk via a formal architecture-change request (Decision 9).
4. Commercial posture: research-only (MODEL-2R) + a commercial-grant route, an Apache/MIT base instead, or an explicit "no commercial release from this base" record (MODEL-2C).
5. Fund (or decline) the ≈USD 6–9 capability-screen evidence budget.
6. Approve vault/private-store activation and the G8 corpus-generation grant (separately; the two are sequenced generator≠runner≠custodian).
7. Approve the explicit training-vs-system policy: *no training unless T2 beats B2 on the frozen metric.*
8. Decide the fate of the 14 off-host training notebooks.
9. Resolve G-020 (web agent tool authority): drop the tools for web sessions permanently, build per-session confinement, or build a real sandbox.
10. (Carried from the register, D-1/D-4/D-8) Legacy Genesis serving posture on a public edge, UX when `core` is refused, and whether signed public-serving grants become the only path to any public experiment.

---

## U. Top 25 prioritized engineering gaps

Drawn directly from the register's own §5 gap inventory (27 items, most already triaged with a priority) plus four items this assessment adds from its own evidence review: the zero-independent-review finding, the symlink/ownership TOCTOU (both from the original pass), and — new in this correction pass — the reopened G-025 privacy regression and the training-sentinel test/guard interaction bug (both §C.6). Full machine-readable detail (acceptance criteria, dependencies, owners) is in `docs/orneur/status/ORNEUR_DEVELOPMENT_REGISTER.md` §5 and `SCORECARD.json`; this table is the prioritized top slice, not a duplicate of the full 128-row register.

| ID | Pri | Gap | Severity | Status | Independent-review requirement |
|---|---|---|---|---|---|
| G-025 (reopened) | **P0 — new in this pass** | Account deletion does not purge a deleted user's private title/content from raw transcript storage; resurfaces after another user's later rename | **High (privacy, confirmed regression of a defect already once fixed and shipped as closed)** | Open, reproduced in isolation on `claude/integration-candidate-2`, not caught by any individual PR's CI | Security/privacy reviewer, plus a root-cause bisection this pass did not perform |
| G-020 | P0 | Web agent tools run with server authority, one shared workspace | High (prompt-injectable cross-tenant reach) | Mitigated (disabled on web), not solved | Product/security reviewer |
| — | P0 | Zero independent reviews across 20+ open draft PRs | High (nothing in this chain is "accepted" by this project's own rules) | Open | Founder must name reviewers |
| G-001/G-002 | P0 | Training/serving authorization bypasses | Fixed, unreviewed | PRs #24/#25 | Security reviewer |
| G-021 | P0→Fixed | First-account owner race | Fixed in PR #35 | — | — |
| G-004 | P1 | Code execution not container-isolated | Medium-high if ever exposed | Open | Sandbox/security reviewer |
| G-005 | P1 | 76 `innerHTML` XSS sinks | Medium (waits on redesign) | Open | Frontend/security reviewer |
| G-006 | P1 | Tenant isolation (9 defects) | Fixed, unreviewed | PR #30 | Independent reviewer |
| G-008 | P1 | No licensed search provider | Medium (ToS/reliability risk) | Open | Founder (D-5) |
| G-009 | P2 | No real third-party connectors | Low-medium (integration mock-only) | Open | Scope decision |
| G-010/G-011 | P1 | Model artifacts/eval reports unarchived | Medium (evidence can be permanently lost) | Open | Owner action |
| G-014 | P1 | Genesis foundation unresolved | Blocks any Genesis training | Open | V2 eval + founder decision |
| G-019 | P1→Fixed | Startup failure on execute-only ancestor directories | Fixed in PR #28 | — | — |
| G-003 | P0/P1→Fixed | Containers ran as root | Fixed, real-image-verified in PR #33 | — | — |
| G-022 | P2 | 8-char session storage keys (collision risk at scale) | Low-medium | Open | Migration decision |
| G-007 | P1 | Conversation durability is opt-in | Medium (data loss on restart) | Open | — |
| G-018 | P3 | No load/soak testing, alerting, restore drills | Medium (unknown reliability at scale) | Open | Ops |
| — | P1 | Symlink/ownership TOCTOU in directory-ACL hardening (this session's own PR #20/#21 work) | Medium | Fixed in PR #22 | — |
| — | **P2 — new in this pass** | `SyntheticOnlyGuard` audit hook flags its own test's adversarial-setup symlink as a violation, breaking the test before its real assertions run | Low-medium (test/harness interaction, not a confirmed product defect) | Open, reproduced on `claude/integration-candidate-2` (pre-existing Workstream G content) | Low priority relative to G-025 (reopened) above |
| (14 more) | — | See full register §5 (G-012, G-013, G-015 through G-017, G-023 through G-027) | — | Mostly fixed in PRs #26/#28/#34/#36 | Independent review pending for all |

**The pattern worth naming explicitly**: the overwhelming majority of *engineering* gaps in this list have already been found and fixed by this program's own adversarial testing discipline. The overwhelming majority of what remains **open** is either (a) a founder-only decision, or (b) an independent-review requirement that engineering effort cannot substitute for. This is itself a finding: ORNEUR's bottleneck has shifted from "build it" to "get it reviewed and decided."

---

## V. Honest final recommendations

1. **Stop**: generating more draft PRs on the model-research side (foundation comparison, V2 eval design, differentiation research docs) before the founder makes the 10 decisions in §T. The research and engineering design work is already unusually thorough; more of it without the gating decisions does not move the critical path.
2. **Stop**: treating "Audit #008–#011" as either confirmed to exist or confirmed not to (§C.2, corrected). What is actually confirmed: no such text is in this repository or its GitHub history, and zero GitHub-recorded reviews exist on any of PRs #22–#45 regardless of what any external report says. Act on that confirmed fact; treat the audits' existence as an open question pending the founder supplying verifiable text.
3. **Start, urgently**: root-causing and fixing the reopened G-025 privacy regression (§C.6) — a previously-shipped, previously-"closed" privacy fix has silently stopped holding, undetected by any individual PR's own green CI. This is a more concrete, more immediately actionable finding than almost anything else in this document, and it was found only by actually running the full suite against a real combined tree rather than trusting per-PR CI badges.
4. **Start**: an actual independent-review process, even a minimal one (a single external reviewer for the security chain would unblock more of the critical path, per §S, than any further engineering sprint).
5. **Start**: measuring real serving cost/throughput against actual hardware (Plan B, §P) before making any claim about Level C viability or C3's cost-efficiency hypothesis — right now every cost figure in this project, including this document's, is an estimate, not a measurement.
6. **Prioritize**: resolving G-020 (web agent authority) before any public-facing agent capability expansion — this is the one open gap that is both a security risk today and directly blocks the Manus-style autonomous-execution ambition the founder named explicitly. This is a runtime-isolation fix, not a model-training one (§L).
7. **Prioritize**: shipping the system-only product (grounding, citations, honest model-identity disclosure, governed agent execution) as the credible near-term differentiator, independent of and not blocked by the model-training programme — per the project's own research design, this might turn out to be sufficient on its own (*"if B2 already matches T2, ship the system"*).
8. **Challenge directly**: the locked RSE-ARCH-1.2 architecture is imposing real, measurable engineering cost (95 pre-training rows, most hardware-and-review-gated) for a project at ORNEUR's current scale and funding. This assessment does not recommend bypassing it — the governance discipline is a genuine asset — but the founder should weigh whether the full physical-trust-root ladder (Tier0-A) is proportionate for a first model at Level C, versus accepting a formally-recorded, reviewed Tier0-S risk (the architecture-change-request path the project's own `HARDWARE_AND_CUSTODY_OPTIONS.md` already defines) to reach a first qualified checkpoint faster, revisiting Tier0-A once there is a model worth protecting at that level of assurance.
9. **Do not**: claim ORNEUR is a frontier model developer, that any named programme (GENESIS/NOVUS/AETERNUM) is shipped or competitive, or that any single readiness percentage summarizes this project's state. None of that is supported by the evidence in this pass. **Also do not** treat any individual PR's "9/9 CI green" badge as proof that a previously-fixed defect in that same area is still fixed (§C.6) — re-running the specific regression test for a previously-closed finding is the only way to know, and this pass found one case where it mattered.

---

## Appendix — Commands and sources used in this pass

```
git clone https://github.com/Guruprasath-Annadurai/Orneur.git /tmp/orneur-verify
git checkout origin/claude/integration-candidate-2
python3 scripts/acceptance/validate_register_graph.py --write --check --self-test
  -> pretraining=95 numerator=0 application=3 execution=2 post=1   (matches SCORECARD.json)

gh pr list --repo Guruprasath-Annadurai/Orneur --state open --limit 100
gh pr view <n> --json comments   (for n in 5..45, searched for "Audit #00[89]"/"Audit #01[01]" -- zero matches)
git grep -E "Audit #0(0[89]|1[01])" across every origin/claude/* branch
  -> only hit: docs/orneur/status/AUDIT_009_STATUS.md, which itself states the audit text was never received

git log origin/main -1   -> 464b602f3f259b56f139c3304828baa660e6b860 (unchanged)
```

**Added in this correction pass (2026-10-14, reconciliation of CTO Tasks 1-6):**

```
# Real file-overlap and merge-conflict check across PR #39-45's sibling branches
git diff --name-only <base>...<branch>   (per branch, python set-intersection across all 7)
  -> 2 files actually shared (orca/serve/api.py, ASSISTANT_FOUNDATION_READINESS.md) -- corrects the
     handoff doc's "disjoint files" claim

git merge-tree --write-tree <running-commit> <next-branch>   (chained via git commit-tree, all 7 branches)
  -> clean merge at every step; final combined tree f2b3b80a1e621b282e509529383778b2786c6994

# Combined-tree test run (disposable clone, nothing pushed)
git checkout f2b3b80a1e621b282e509529383778b2786c6994
python3 -m pytest <11 new test files from PR #39-45>
  -> 231 passed, 1 skipped, 3 xfailed, 0 unexpected failures
python3 scripts/acceptance/validate_register_graph.py --write --check --self-test
  -> pretraining=95 numerator=0 (unchanged, zero drift)
python3 -m pytest tests/ -q   (full suite, 26m57s)
  -> 8844 passed, 11 failed, 329 skipped, 7 xfailed
     7 failed: pre-existing macOS-only RLIMIT_AS/DNS (documented in every prior full-suite run this session)
     1 failed: container-timeout test, reproduces as PASS in isolation (resource-contention flake)
     2 failed: real, reproducible, NOT caused by PR #39-45 -- confirmed by checking out
       origin/claude/integration-candidate-2 alone and re-running both tests there (both still fail)
       -> test_product_flows_fake_ollama.py::test_account_deletion_...does_not_resurrect_titles (G-025 reopened)
       -> test_trainprep_sentinel.py::test_fails_closed_for_unsafe_sandboxes_and_nesting

gh pr view <n> --json reviews,comments   (for n in 39-45) -> 0 reviews, 0 comments on every PR, re-confirmed
```

Web sources (dated 2026-10-14 access; see inline `[P]`/`[S]` citations in §E): help.openai.com, chatgpt.com/plans, gemini.google.com, blog.google (Gemini 3 launch), ai.google.dev, anthropic.com/news, api-docs.deepseek.com, perplexity.ai/hub/blog, perplexity.ai/help-center, manus.im, plus third-party reviews (cline.bot, aitoolradar.io, secondtalent.com, till-freitag.com, willo.ai, cnbc.com) explicitly marked `[S]` and treated as lower-confidence than primary sources.

No model was loaded, no GPU or paid provider call was made, no training or evaluation was run, no protected corpus or hidden set was touched, no key was activated, no hardware was purchased, nothing was merged.
