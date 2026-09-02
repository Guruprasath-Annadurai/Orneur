# Cognitive Court (Phase 6)

`orca/deliberation/court.py::CognitiveCourt`. Orchestrates the bounded
roles into one Constructor+Falsifier round per Court invocation (first
production version — spec §14).

## Roles

| Role | Module | Decides the case? | Authorizes anything? |
|---|---|---|---|
| Constructor | `twin.py` | No — builds candidate claims | No |
| Falsifier | `twin.py` | No — attacks claims | No |
| EvidenceClerk | `evidence_clerk.py` | No — reports evidence state | No |
| RiskCounsel | `risk_counsel.py` | No — recommends | No |
| Arbiter | `arbiter.py` | **Yes — the only role that produces `CourtVerdict`** | No (see [SECURITY.md](SECURITY.md)) |

`AuthorityJudge` exists as a **hook only** — no code implements it this
phase (spec §14: Godmode/capability leases are out of scope).

## EvidenceClerk reuses, never duplicates (spec §17)

`build_evidence_report()` reads `TruthResult.contradictions`/`.sources`/
`.evidence` directly — it never calls a verification function itself.
Its `EvidenceReport` has no verdict/accept/reject field at all
(structurally checked:
`tests/test_deliberation_evidence_risk_arbiter.py::
test_evidence_clerk_does_not_decide_anything`).

## RiskCounsel recommends, never authorizes (spec §18)

`assess_risk_opinion()` returns one of `proceed`/`more_verification`/
`simulation`/`human_approval`/`abstain` — `RiskOpinion` has no
permission-granting field (structurally checked). `CRITICAL` risk always
recommends `human_approval`, regardless of how clean the evidence
otherwise looks.

## Arbiter — deterministic, never a model vote (spec §19-20)

`arbitrate()` is pure Python control flow over the other roles'
structured outputs, in this order:

1. No claims at all → `INSUFFICIENT_EVIDENCE`.
2. A real `DIRECT_CONTRADICTION` at `AUDIT_GRADE`/`HIGH`/`CRITICAL` →
   `INSUFFICIENT_EVIDENCE` (spec §39 — blocks `ACCEPT` before anything
   else is even considered).
3. RiskCounsel recommends `human_approval` → `INSUFFICIENT_EVIDENCE`
   (Court cannot `ACCEPT` its way past a human-approval recommendation).
4. All claims disputed, real counter-evidence/unsupported assumptions
   found → `REJECT`. All disputed but no confirmed counter-evidence →
   `REVISE`.
5. Some disputed, some survive → `REVISE`.
6. Nothing disputed → `ACCEPT` (confidence/epistemic_state reflect
   whether every claim also cited evidence).

This is the direct fix for the exact failure mode the Phase 6 audit
found in `orca/variants/ultra.py`'s grading step — a single unstructured
0-100 score from one model call, with no independent roles and no
evidence citation requirement.

## Court ACCEPT does not authorize action (spec §48)

`CognitiveKernel` treats `ACCEPT`/`REVISE` as "proceed to answer
generation" — nothing more. The existing `verify_answer()` check still
runs independently afterward for `AUDIT_GRADE`. No code path anywhere
lets a `CourtVerdict` call a tool, grant an entitlement, or change
memory scope — that remains, unambiguously, the Agent Runtime/capability
system's job, not built in this phase (spec §60-61).

## Same-model role limitation (spec §21, §57) — disclosed, not hidden

`RoleExecution.model_id` records which model actually served each role.
Today, with Genesis untrained, Novus not production-promotable, and
Aeternum absent, Constructor and Falsifier both resolve to the same
`nano`-tier deployment. This is recorded explicitly on every
`CourtCase.role_executions` entry and verified directly:
`tests/test_deliberation_court_integration.py::
test_court_records_which_model_served_each_role`. **No independent
ensemble intelligence is claimed** — model-society hooks
(role→`ModelPolicy` mapping: Constructor→BALANCED/DEEP,
Falsifier→VERIFICATION, EvidenceClerk→FAST/VERIFICATION,
RiskCounsel→REASONING, Arbiter→DEEP) are prepared conceptually in this
document but not hardcoded to specific model deployments —
`ModelGateway` remains authoritative over actual resolution (spec §22).
