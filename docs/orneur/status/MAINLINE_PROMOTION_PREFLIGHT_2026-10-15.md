# Mainline Promotion Preflight — Founder Merge Decision Package

Status date: 2026-10-15. Triggered by Antigravity Audit #014
(`ACCEPTED_VERIFIED` for PR #49). This document does not merge anything —
it is the evidence package for a founder decision.

## 1. Main baseline SHA

`464b602f3f259b56f139c3304828baa660e6b860` — `origin/main`'s exact current
tip, confirmed by direct fetch (not assumed from memory).

## 2. Proposed final candidate SHA

`526f05f3e4d867d0e84047001790b1ce1ccc0ea8` — branch
`claude/main-promotion-candidate-2026-10-15`, pushed to GitHub. Identical
content to PR #49 (Audit #014 `ACCEPTED_VERIFIED`); created as a
separately-named branch rather than overwriting PR #49's own branch, per
instruction.

## 3. Merge topology (Mission 1)

- `git merge-base origin/main HEAD` = `464b602f...` — **main's own tip**.
  This means main has had **zero commits** since this entire 29-PR program
  branched from it (confirmed: PR #20 and PR #38, two independent
  integration lines, both base at this exact same SHA).
- `git log HEAD..origin/main` — **empty**. No commit exists on main that
  is missing from this candidate.
- Conclusion: promotion carries no risk of omitting a security-critical
  main-side commit or silently reintroducing superseded historical state,
  because there is nothing on main that isn't already an ancestor of this
  candidate.

## 4. Integration manifest and diff summary (Mission 2)

Full PR-level manifest: see
[`INTEGRATION_CANDIDATE_3_MANIFEST.md`](INTEGRATION_CANDIDATE_3_MANIFEST.md)
(PRs #39–45 inclusion decisions, evidence per PR) and PR #48's own record
(deletion-assurance + architecture-decision correction + test-isolation
fix) and PR #47/#38's prior, independently-audited history.

`git diff origin/main HEAD --stat`: **443 files changed, 82065
insertions(+), 367 deletions(-)**. This is the full accumulated diff of
the entire program (PRs #20–49) relative to main's Oct-10 freeze point,
not just today's work — consistent with main not having moved.

**Frozen requirements/security gates/brand assets preserved**: directly
verified, not assumed. `git diff 42e4f57 HEAD -- docs/orneur/acceptance/
docs/orneur/authorization/ docs/orneur/ORNEUR_MASTER_EXECUTION_AND_ACCEPTANCE_REGISTER.md
scripts/acceptance/` (i.e., since PR #48's own already-audited state) is
**empty** — nothing in the acceptance register, training-authorization
gate, or acceptance engine changed during this integration work. The
founder-approved brand assets (PR #39) were verified byte-for-byte
against their founder-supplied SHA-256 digests in
`BRAND_IDENTITY_LOCK.md` (§3 of the integration manifest).

## 5. Release-independent guarantee revalidation (Mission 3)

Targeted battery run against this exact candidate: authentication
(`test_auth_privacy.py`, `test_auth_store.py`, `test_a_bootstrap_hardening.py`),
tenant isolation (`test_g006_tenant_isolation.py`), deletion
(`test_deletion_end_to_end.py`, `test_memory_long_term_chroma_privacy.py`,
`test_account_delete.py`), test isolation
(`test_conftest_memory_isolation.py`), streaming
(`test_gateway_stream_contract.py`, and the specific instructed check:
`test_serve_streaming.py::test_real_socket_disconnect_closes_the_backend_generator_and_frees_admission`
— a real HTTP streaming-disconnect test against a fake upstream runtime,
confirmed already present and passing, proving resource cleanup and
concurrency-slot release on a real socket disconnect), documents
(`test_b2_conversation_documents.py`), tool authorization
(`test_g020_agent_tool_authority.py`, `test_g021_owner_bootstrap.py`),
training-gate (`test_training_authorization_gate.py`,
`test_training_authorization_assurance.py`, `test_trainprep_sentinel.py`
run in its required isolation).

**Result: all passing.** (One run included the sentinel test in the same
batch as chromadb-using tests, which fails due to the
already-documented `tokenizers` cross-contamination — a batching
mistake, not a finding; isolated rerun: 13/13 passed.)

## 6. Qualification (Mission 4)

- This candidate's content is byte-identical to PR #49's already-locally-
  qualified tip (no new commits) — the full canonical-suite run already
  performed for PR #49 (8843 passed / 10 failed, all 10 traced to
  confirmed macOS-only / Docker-resource-state / load-sensitivity causes,
  none regressions) applies directly; it was not blindly assumed to
  "automatically qualify" without re-verification — re-verification took
  the form of fresh, independent Linux CI below, which is a stronger,
  not weaker, form of evidence than a repeat local run.
- **Exact-SHA Linux CI, PR #49, SHA `526f05f3e4d867d0e84047001790b1ce1ccc0ea8`**:

| Job | Result | Duration | URL |
|---|---|---|---|
| Deterministic Unit Tests | **pass** | 14m39s | [job/116374666976](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666976) |
| Genesis V2 Sandbox | pass | 37s | [job/116374666517](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666517) |
| Genesis V2 Security | pass | 1m29s | [job/116374666845](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666845) |
| Production Container Build + Boot Smoke | pass | 38s | [job/116374666773](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666773) |
| RSE Docker Synthetic Integration Lab | pass | 34s | [job/116374666584](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666584) |
| RSE dependency lock/vuln scan | pass | 11s | [job/116374666688](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666688) |
| SSE Diagnostics | pass | 15s | [job/116374666962](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666962) |
| Training Math Unit Tests (Torch) | pass | 34s | [job/116374666604](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666604) |
| Dependency Vulnerability Scan | pass | 16s | [job/116374666862](https://github.com/Guruprasath-Annadurai/Orneur/actions/runs/38720831682/job/116374666862) |

**9/9 passing**, including "Deterministic Unit Tests" clean on Linux —
notably, this confirms the 7 RSE/`imp4_ocr1` local failures (macOS-only
`RLIMIT_AS` rejection, root-caused and reproduced directly in prior
evidence) genuinely do not occur on Linux, exactly as that root-cause
analysis predicted. This is independent corroboration, not a new
assumption.

**Independent delta audit**: not separately re-requested for this exact
SHA, because the resulting tree is **not materially different** from the
already-audited PR #49 state (identical content, zero new commits,
confirmed via `git diff 526f05f 526f05f` trivially empty since it's the
same commit under two branch names). Per the instruction's own
condition ("if the resulting main-target tree differs materially"), no
new audit trigger applies here; Audit #014's `ACCEPTED_VERIFIED` already
covers this exact tree.

## 7. Risk register

| Risk | Status | Carried forward from |
|---|---|---|
| ChromaDB cross-process architecture anomaly (`NotFoundError`, properly sequenced, unreproduced after 7 controlled attempts) | **Open, `ROOT_CAUSE_UNRESOLVED`** | PR #48 §8.3 |
| Multi-tenant agent-tool restriction completeness | **Open, not independently re-verified beyond `test_g020_agent_tool_authority.py`'s existing coverage in this pass** — flagged per directive, not newly discovered, not newly closed | Historical (PR #30/#35 chain) |
| Container PID-namespace teardown — local environment inconclusive | Resolved for promotion purposes by Linux CI (§6) passing; local Docker-daemon-state explanation stands as the non-regression finding | PR #49 §5 |
| 52-actor durable-audit concurrency test — load-sensitive | Resolved for promotion purposes by Linux CI (§6) passing clean; local load-sensitivity explanation stands | PR #49 §6 |
| Gateway cancellation race (PR #40) | **Closed** — root-caused and fixed with deterministic synchronization, verified 15/15 + held under full suite + Linux CI | PR #49 §4 |

No new risk was discovered in this preflight beyond what PR #48/#49
already carried forward; none of the open items are newly introduced by
promotion itself, since the candidate tree is unchanged from the already-
audited state.

## 8. Rollback plan

- **Before any merge**: none required — nothing has been merged to
  `main`. `claude/main-promotion-candidate-2026-10-15` and PR #49 remain
  separate, reviewable branches; `main` is untouched.
- **If a founder-approved merge later needs to be reverted**: since main
  has had zero divergent commits during this entire program, a merge of
  this candidate onto main would be a clean, single merge commit (not a
  rebase or history rewrite) — reverting it is a standard `git revert
  -m 1 <merge-sha>` against that one commit, with no risk of touching
  unrelated main-side history because none exists in this window.
- **Data/runtime rollback**: not applicable — no deployment, infrastructure
  change, or real-data mutation occurred in this preflight or in the
  candidate's own history (verified throughout this program via isolated
  test storage, confirmed MD5-identical real-store state, and no
  production config changes in the diff).

## 9. Final recommendation

**`READY_FOR_FOUNDER_MERGE_APPROVAL`**

Basis: main has zero divergent commits (no omission risk); the candidate
is byte-identical to the already-independently-audited PR #49
(`ACCEPTED_VERIFIED`, Audit #014); frozen requirements, the acceptance
register, and training-authorization gates are confirmed unchanged since
that audit; all targeted release-independent guarantees re-verified
passing; fresh, independent Linux CI at this exact SHA is 9/9 green,
including confirmation that the known macOS-only local failures do not
occur on Linux. The two carried-forward open risks (chromadb
cross-process anomaly, multi-tenant tool-restriction completeness) are
named precisely, not hidden, and do not block this recommendation since
neither is newly introduced or newly discovered by this preflight.

**This recommendation is evidence for the founder's own merge decision.
No merge, deployment, model training, infrastructure spend, or real-data
cleanup has been performed.**
