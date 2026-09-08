SPEC_VERSION: 1.0
STATUS: CANONICAL_PHASE15
SOURCE: OWNER-PROVIDED
PHASE16_GATE: LOCKED_UNTIL_PHASE15_PASS

---

ORNEUR — PHASE 15
ORNEUR CODE + ORNEUR RELAY
CANONICAL V1 MASTER SPECIFICATION + IMPLEMENTATION PROGRAM

OWNER APPROVAL:
Phase 14C.1 has passed.
Phase 15 is explicitly authorized.

IMPORTANT CORRECTION

You were correct to stop previously.

The ORNEUR Code + ORNEUR Relay specification existed in architecture
planning outside the repository, but it was never persisted into the repo.

Therefore:

- do NOT pretend you previously had this specification;
- do NOT rewrite Phase 14 history;
- do NOT infer requirements from the phrase "ORNEUR Code";
- treat THIS document as the canonical Phase 15 specification;
- persist it into the repository BEFORE implementation;
- all Phase 15 work must trace back to requirements defined here.

The purpose of Phase 15 is to implement and qualify the first governed
ORNEUR Code + ORNEUR Relay foundation.

Phase 16 — ORNEUR Native Intelligence Core — remains LOCKED.

======================================================================
0. FIRST ACTION — PERSIST THIS SPECIFICATION
======================================================================

Before implementation:

Create:

docs/orneur/phase-15/
docs/orneur/phase-15/ORNEUR_CODE_RELAY_MASTER_SPEC_V1.md
docs/orneur/phase-15/PHASE15_IMPLEMENTATION_PLAN.md
docs/orneur/phase-15/PHASE15_EVIDENCE.md
docs/orneur/phase-15/PHASE15_REQUIREMENTS.md

Persist this specification faithfully into:

docs/orneur/phase-15/ORNEUR_CODE_RELAY_MASTER_SPEC_V1.md

Do not summarize away normative requirements.

Record:

SPEC_VERSION: 1.0
STATUS: CANONICAL_PHASE15
SOURCE: OWNER-PROVIDED
PHASE16_GATE: LOCKED_UNTIL_PHASE15_PASS

Then inspect the repository and create an implementation mapping before
touching production code.

======================================================================
1. PRODUCT DEFINITION
======================================================================

ORNEUR Code is not merely a coding chatbot.

ORNEUR Code is ORNEUR's governed software-engineering system capable of:

- understanding an idea/specification;
- inspecting an existing repository;
- planning work;
- editing code;
- running tools;
- debugging;
- testing;
- verifying;
- reviewing;
- checkpointing;
- recovering;
- producing evidence;
- preparing software for release;
- refusing to claim completion without proof.

ORNEUR Relay is not merely file synchronization.

ORNEUR Relay is the secure cross-device continuation/control layer for
the SAME ORNEUR Code workspace and mission.

It must preserve governed engineering state including:

- workspace/repository;
- branch/revision;
- uncommitted changes;
- mission;
- phase;
- requirements;
- execution state;
- test state;
- verification state;
- Production Proof;
- approvals;
- pending dangerous operations;
- checkpoints;
- model/tool activity;
- authority context;
- device/session information;
- secret REFERENCES, never raw secret disclosure.

Canonical distinction:

ORNEUR Code = engineer software.

ORNEUR Relay = securely continue/control that engineering mission
from another authorized device.

======================================================================
2. PHASE 15 BOUNDARY
======================================================================

Phase 15 builds the SOFTWARE SYSTEM required for ORNEUR Code + Relay.

Phase 15 does NOT train or claim availability of the future ORNEUR
native model society.

Do not claim:

- Genesis is operational unless a real qualified Genesis checkpoint exists;
- Novus has been rehabilitated unless separately re-evaluated;
- Aeternum exists when no real trained checkpoint exists;
- Auto native-model routing is production-qualified.

Instead build model/provider abstractions so later Phase 16 can plug in:

Genesis
Novus
Aeternum
ORNEUR Auto

without rewriting the mission system.

Phase 16 owns:

- ORNEUR Cognitive Language
- full Epistemic State Machine integration
- Epistemic Integrity Protocol
- Genesis role implementation
- Novus role implementation
- Aeternum role implementation
- Auto intelligence routing
- Epistemic Twin Distillation
- Failure Genome intelligence integration
- Outcome Memory intelligence integration
- Capability Delta intelligence integration
- governed self-improvement

Phase 15 may create storage/interfaces required by those future systems,
but MUST NOT falsely claim those intelligence capabilities are complete.

======================================================================
3. ORNEUR CODE MODES
======================================================================

Implement four first-class mission modes.

ASSIST

Human drives.
ORNEUR suggests, explains, edits when authorized, runs bounded tools,
and verifies requested work.

PROTOTYPE

Idea -> working prototype.

Priority:
speed and validated product direction.

Shortcuts are permitted only when explicitly tracked as:

PROTOTYPE_DEBT

Prototype debt MUST NOT silently become production-ready code.

BUILD

Specification -> production-oriented implementation.

Requires:

- requirements;
- acceptance criteria;
- implementation;
- testing;
- regression analysis;
- security evaluation where applicable;
- evidence.

LAUNCH

Verification/release mode.

Requires:

- requirement traceability;
- release checks;
- security checks;
- supply-chain checks;
- deployment checks;
- rollback readiness;
- Production Proof.

LAUNCH does NOT mean external platform acceptance.

External states must remain distinct:

ENGINEERING_READY
SUBMISSION_READY
RELEASE_CANDIDATE
PUBLISHED

PUBLISHED is allowed only after external confirmation.

======================================================================
4. CONCEPT COMPILER / PRODUCT CONTRACT
======================================================================

A vague product idea must be transformed into a typed Product Contract.

Minimum fields:

product purpose
actors/users
user journeys
functional requirements
non-functional requirements
data classes
authentication needs
permissions
integrations
risk areas
assumptions
unknowns
target platforms
acceptance criteria
launch target
out-of-scope items

Assumptions must be explicit.

Never silently transform assumptions into facts.

Until Phase 16's full epistemic system exists, Phase 15 must at minimum
support explicit assumption states such as:

VERIFIED
UNVERIFIED
UNKNOWN
CONTESTED

Do not claim this limited representation is the complete future ORNEUR
Epistemic State Machine.

======================================================================
5. REQUIREMENT COMPILER
======================================================================

Every material requirement receives a stable requirement ID.

Example:

REQ-AUTH-DELETE-001

A requirement must map to executable/testable acceptance criteria.

Example account deletion requirement may require evidence that:

- authenticated deletion was authorized;
- active tokens/sessions were invalidated;
- defined user-owned data was deleted or queued according to policy;
- subsequent login behaves correctly;
- retention exceptions are recorded;
- audit evidence exists.

Every verification artifact should be traceable back to requirement IDs.

Phase 15 must create a requirement -> implementation -> test -> evidence
traceability path.

======================================================================
6. MISSION ENGINE
======================================================================

A Mission is the durable unit of ORNEUR Code work.

A mission must NOT exist only as chat history.

Canonical mission states:

DRAFT
PLANNING
READY
RUNNING
WAITING_TOOL
WAITING_EXTERNAL_EVENT
WAITING_APPROVAL
VERIFYING
COURT_REVIEW
PAUSED_USER
PAUSED_WINDOW_REACHED
BLOCKED
FAILED
COMPLETED_UNVERIFIED
COMPLETED_VERIFIED
CANCELLED

State transitions must be explicit and validated.

Invalid transitions must be rejected.

Mission state must survive:

- browser refresh;
- browser close;
- Relay disconnect;
- process restart;
- worker restart;
- temporary model failure;
- network interruption;
- six-hour mission-window expiration;
- normal service restart.

======================================================================
7. SIX-HOUR AUTONOMOUS MISSION WINDOW
======================================================================

Standard ORNEUR Code autonomous mission window:

6 HOURS WALL CLOCK

This does NOT mean:

- unlimited tokens;
- unlimited model use;
- unlimited GPU;
- unlimited API cost;
- unlimited storage;
- unlimited network;
- unrestricted system authority.

During an autonomous mission ORNEUR must:

RUN
OBSERVE
VERIFY
CHECKPOINT
CONTINUE

The user may interrupt at any time.

At the six-hour limit:

- stop starting new discretionary work;
- safely complete/abort active atomic work;
- persist state;
- persist repo revision;
- persist diff;
- persist requirement progress;
- persist test state;
- persist evidence;
- persist failures;
- persist remaining plan;
- transition to:

PAUSED_WINDOW_REACHED

The mission must then be resumable.

No state loss.

======================================================================
8. AUTONOMY LEVELS
======================================================================

L0 — ADVISE
No modifications.

L1 — EDIT
May edit authorized workspace files.

L2 — EXECUTE
May run approved local/sandbox commands.

L3 — AUTONOMOUS MISSION
Standard bounded six-hour mission.

L4 — GOVERNED ENTERPRISE AUTONOMY
Persistent, organization-policy-bound missions.

There is no uncontrolled L5 root autonomy.

Human/user/organization remains the authority.

======================================================================
9. DURABLE MISSION STATE
======================================================================

Persist typed state, not one giant conversation transcript.

Minimum durable domains:

users / principals where applicable
organizations where applicable
workspaces
repositories
missions
mission_steps
checkpoints
requirements
requirement_acceptance_criteria
assumptions
evidence
model_invocations
tool_invocations
approvals
authority_decisions
relay_sessions
devices
operation_records
production_proofs
audit_events

Future-compatible domains may also be reserved for:

epistemic_transitions
escalations
failure_genome
outcome_memory
capability_delta

but do not claim the Phase 16 intelligence semantics are implemented
merely because storage tables exist.

Canonical durable database for the current architecture:

Neon / Lakebase Postgres

Current project:

orneur-core
project id little-boat-61470844
production branch
Singapore region

Postgres only is currently intentional.

Do not enable Neon Auth, Functions, Object Storage, or AI Gateway merely
because they exist.

Application traffic should use the normal pooled database URL.

Schema migrations/admin operations should use the direct/unpooled
connection.

Secrets must never be committed.

======================================================================
10. CHECKPOINT SYSTEM
======================================================================

Every material mission checkpoint should record enough information to
resume deterministically.

At minimum:

checkpoint ID
mission ID
timestamp
mission state
current step
completed steps
remaining steps
repository identity
branch
base revision
current revision
working diff reference/hash
requirement states
test states
verification states
evidence references
pending approvals
active blocker
resource/budget state if tracked
tool outcomes
environment identity

Checkpoint creation must be tested.

Checkpoint restoration must be tested.

A restored mission must not silently duplicate already-completed
dangerous operations.

======================================================================
11. OPERATION IDEMPOTENCY
======================================================================

Every significant external/dangerous operation requires a stable
operation ID.

Operation lifecycle:

REQUESTED
AUTHORIZED
STARTED
SUCCEEDED
FAILED
CANCELLED

Reconnect/retry logic must determine whether an operation already ran.

Never redeploy, charge, delete, migrate, send, publish, or perform another
dangerous action twice merely because a response was lost.

======================================================================
12. EXECUTION SANDBOX
======================================================================

Generated/untrusted code must not run with unrestricted host authority.

Define controlled execution boundaries for:

DEVELOPMENT
TEST
STAGING
PRODUCTION

Control where supported:

filesystem
network
environment variables
secrets
CPU
RAM
runtime duration
process count
privileges
child processes
working directory

Phase 15 does not need to implement every future container platform,
but it must establish a real enforceable sandbox boundary for supported
execution paths.

No "sandboxed" claim based only on instructions to the model.

======================================================================
13. SECRETS
======================================================================

Secrets must not be casual model context.

Examples:

database credentials
API tokens
signing certificates
mobile signing keys
cloud tokens
production credentials
.env values

Use:

- environment injection;
- vault/secret-provider references;
- scoped capabilities;
- least privilege;

where supported.

Audit sensitive access.

Never store secret values in:

mission transcript
Production Proof
Relay payload history
Git commits
logs
screenshots
evidence docs

======================================================================
14. AUTHORITY ENGINE
======================================================================

Models are NOT organizational authorities.

Policy must be enforced outside model prose.

Dangerous operations must be classified.

Examples that may require approval according to policy:

production deployment
destructive migration
production data modification
credential rotation
payment changes
auth/security changes
infrastructure deletion
secret access
irreversible filesystem operations
external publication

The model cannot approve its own authority escalation.

Human approval states must be durable and auditable.

Existing ORNEUR authority/security invariants from earlier phases are
non-regression constraints.

======================================================================
15. ANTI-TEST-GAMING
======================================================================

ORNEUR Code must detect or block attempts to make a task "pass" by:

deleting tests
disabling tests
skipping relevant tests
weakening assertions
changing expected behavior merely to match broken output
suppressing errors
disabling validation
mocking away required real behavior
hardcoding test-specific output
weakening authentication
weakening authorization
weakening security controls

Not every legitimate test edit is malicious.

Therefore analyze whether a test modification is justified by a real,
approved requirement change.

Critical test/security weakening blocks verified completion.

======================================================================
16. COGNITIVE COURT — PHASE 15 SOFTWARE VERSION
======================================================================

Implement a risk-aware review/court abstraction.

Possible roles:

Constructor
Falsifier
Security Critic
Regression Critic
Test Critic
Performance Critic
Arbiter

Do not require all roles for every trivial operation.

Court activation must be proportional to risk.

Possible verdicts:

ACCEPT
REJECT
NEED_MORE_EVIDENCE
ESCALATE
HUMAN_APPROVAL_REQUIRED

During Phase 15 these roles may be implemented through available
provider/model adapters.

Do not claim that Aeternum is the Arbiter until a real qualified
Aeternum checkpoint exists.

The role abstraction must allow Aeternum to take that position in
Phase 16+.

======================================================================
17. NO FAKE COMPLETION
======================================================================

Hard invariant.

Never say:

Fixed
Complete
Production ready
Verified
Secure
Launch ready

without corresponding evidence.

Examples:

If code was implemented but tests were not run:

IMPLEMENTATION: COMPLETE
VERIFICATION: UNVERIFIED

If tests ran but external deployment was never performed:

ENGINEERING_READY may be valid.
PUBLISHED is not.

COMPLETED_UNVERIFIED and COMPLETED_VERIFIED must remain distinct mission
states.

======================================================================
18. PRODUCTION PROOF
======================================================================

Production Proof is a first-class evidence artifact.

It must be machine-readable where practical and human-readable.

Minimum categories:

product/mission identity
revision/commit
requirements satisfied
requirements unresolved
build evidence
unit-test evidence
integration-test evidence
E2E evidence
regression evidence
security evidence
authority evidence
dependency/supply-chain evidence
accessibility evidence where applicable
performance evidence where applicable
release-build evidence
deployment evidence where applicable
post-deploy smoke evidence where applicable
rollback evidence
known limitations
unverified assumptions
blockers
warnings
artifact hashes
verifier/tool versions where practical
timestamp

Production Proof must never invent evidence.

A missing test produces:

UNVERIFIED

not PASS.

======================================================================
19. SUPPLY CHAIN + LICENSING
======================================================================

Launch qualification must support checks for:

known vulnerable dependencies
compromised packages where detectable
abandoned/high-risk critical dependencies
dependency confusion risks
unpinned critical dependencies
lockfile state
transitive dependency risk
malicious install hooks where detectable
SBOM/provenance where supported

Also track applicable:

source licenses
dependency licenses
asset licenses
font/image licenses
attribution requirements
commercial restrictions

Do not make unsupported legal guarantees.

======================================================================
20. DEPLOYMENT + ROLLBACK
======================================================================

Launch workflows must reason about:

deployment configuration
environment variables
migrations
health checks
backups
rollback
observability
endpoints
post-deploy smoke tests

Preserve Phase 14C.1's honest distinction:

Northflank currently does not provide a native rollback mechanism on the
used plan.

The proven mechanism is:

git revert / redeploy-to-known-good-commit

Do not relabel this "native rollback."

Preserve Phase 14C.1 evidence.

Do not rerun destructive rollback drills merely for ceremony unless new
risk warrants it.

======================================================================
21. POST-LAUNCH OUTCOME LOOP INTERFACE
======================================================================

With explicit user permission, ORNEUR Code should be able to ingest:

crash reports
error reports
latency changes
deployment failures
test regressions

and attach them to mission/outcome records.

Full Outcome Memory intelligence belongs to Phase 16.

Phase 15 should implement only the clean software interface/storage hooks
required for future integration.

No autonomous model-weight promotion.

======================================================================
22. ORNEUR RELAY — CORE
======================================================================

Relay allows authorized users to reconnect to an existing mission from
another device.

Relay must synchronize governed engineering state, not just files.

Minimum synchronized state:

workspace
repository
branch
revision
mission state
mission step
requirement progress
test progress
verification state
Production Proof status
pending approvals
pending dangerous actions
checkpoints
agent/model activity summary
tool activity summary
authority context

Raw secrets must not be relayed.

======================================================================
23. RELAY MODES
======================================================================

TRUSTED DEVICE

May expose, subject to authority policy:

editor
terminal
files
diffs
tests
logs
agents
deploy controls
approval controls

PUBLIC DEVICE MODE

Designed for:

café computer
borrowed computer
shared workstation

Requirements:

strong reauthentication
short-lived session
clear PUBLIC DEVICE indicator
no raw secret exposure
sensitive file masking where feasible
optional clipboard restriction
optional download restriction
short inactivity timeout
reauthentication for dangerous actions
remote session revocation
dangerous actions may require separate trusted-device approval

Do not store durable secrets/browser tokens unnecessarily.

MOBILE REVIEW

Do not cram a desktop IDE onto a phone.

Focus on:

mission status
diff review
test results
Production Proof
blockers
message to agent
approve
reject
pause
resume
revoke session

ENTERPRISE RELAY

Architecture must remain extensible for:

SSO
RBAC
managed devices
private networks
IP/region rules
audit
no-download policy
VPC/private deployment
data residency
approval chains
retention policies

Enterprise completion is not required for V1 unless specifically evidenced.

======================================================================
24. RELAY THREAT MODEL
======================================================================

Explicitly model at least:

stolen browser session
shared/public computer
malicious browser extension
compromised Wi-Fi
token theft
session fixation
cross-device race
source-code exfiltration
secrets leakage
replay
CSRF
XSS
websocket/session hijack
privilege escalation
unauthorized deployment

Do not invent custom cryptography.

Use established security primitives.

======================================================================
25. DEVICE TRUST + SESSION REVOCATION
======================================================================

Relay requires device/session identity.

Support:

session creation
session expiry
device association
last-seen state
revocation
revoke-current
revoke-other
revoke-all-others

Public Device Mode must be visibly and technically distinct from
Trusted Device mode.

Critical actions may require reauthentication.

======================================================================
26. NETWORK LOSS + RECONNECT TRUTHFULNESS
======================================================================

Relay must distinguish:

CONNECTED
RECONNECTING
OFFLINE
STALE
PENDING
CONFIRMED
FAILED

A lost response must not become a fake success.

Reconnect must reconcile server-side durable mission/operation state.

Example:

Client requests deployment.
Connection drops.
Deployment succeeds server-side.
Client reconnects.

Correct behavior:

look up operation ID
discover SUCCEEDED
render confirmed result

Incorrect behavior:

automatically issue deploy again.

======================================================================
27. MULTI-DEVICE CONSISTENCY
======================================================================

Two devices may be connected simultaneously.

Define conflict behavior for:

simultaneous edits
pause/resume
approvals
mission cancellation
dangerous actions
checkpoint updates

At minimum prevent duplicate irreversible actions and stale-authority
decisions.

Use optimistic concurrency/versioning or another real consistency
mechanism where appropriate.

======================================================================
28. INITIAL SUPPORTED PRODUCT-GENERATION SCOPE
======================================================================

Do NOT promise every language/platform in V1.

Initial preferred product-generation scope:

WEB

TypeScript
React / Next.js where appropriate
Node.js
Python / FastAPI
PostgreSQL

MOBILE

React Native initially

Existing repositories using other stacks may still be supported through
Assist/Build where tooling permits, but V1 launch guarantees must remain
bounded to actually-qualified stacks.

======================================================================
29. ACCURACY / QUALITY METRICS
======================================================================

Do not advertise universal "99% coding accuracy."

Primary system metrics:

VTCR — Verified Task Completion Rate

A task counts complete only when the applicable requirement has been
implemented AND required verification evidence exists.

FCR — False Completion Rate

How often ORNEUR claims completion when the result is incomplete,
incorrect, unsafe, or unverified.

ZHRR — Zero-Human-Rescue Rate

Percentage of tasks reaching a verified result without the human manually
repairing generated implementation.

Internal aspirational V1 targets may be recorded as TARGETS, never current
measured claims:

routine edits >=95% verified
standard bug fixes >=92%
multi-file features >=90%
repository-level workflows approximately 88-90%+
difficult architecture/migration tasks >=85%
supported launch pipeline >=95% of required release gates
FCR target <1%
critical authority/security violations = 0 tolerated

These remain unverified targets until reproducibly measured.

======================================================================
30. PHASE 15 IMPLEMENTATION PROGRAM
======================================================================

Execute Phase 15 as SUBPHASES.

Do not treat the whole program as one giant uncontrolled change.

-------------------------
PHASE 15.0 — BASELINE
-------------------------

Inspect repository.

Record:

current branch
HEAD
dirty state
architecture
existing state stores
auth
authority
audit
deployment
edge controls
database layer
tests
security suite
CI
known deferred model-runtime gates
Phase 14C evidence

Produce implementation dependency map.

No speculative rewrite.

-------------------------
PHASE 15.1 — CANONICAL SPEC + REQUIREMENTS
-------------------------

Persist this specification.

Compile stable requirement IDs.

Create traceability structure.

Test/document requirement lifecycle.

-------------------------
PHASE 15.2 — DURABLE DATA MODEL
-------------------------

Design durable schema for:

missions
mission steps
checkpoints
requirements
acceptance criteria
assumptions
evidence
operations
approvals
relay sessions
devices
production proofs
audit relations

Use migrations as code.

Do not apply an untested migration directly to production.

Use Neon branch-first migration validation where feasible.

Migrations must use the direct/unpooled connection.

-------------------------
PHASE 15.3 — MISSION STATE MACHINE
-------------------------

Implement mission states and validated transitions.

Test:

valid transitions
invalid transitions
terminal states
pause
resume
blocked
failed
verified/unverified completion distinction

-------------------------
PHASE 15.4 — CHECKPOINT + RESUME
-------------------------

Implement durable checkpoints.

Prove:

checkpoint creation
process restart recovery
mission restoration
remaining-plan recovery
test/evidence recovery
no duplicate completed operations

-------------------------
PHASE 15.5 — OPERATION / AUTHORITY ENGINE
-------------------------

Implement durable operation IDs and lifecycle.

Integrate with existing ORNEUR authority/security architecture rather than
replacing it.

Prove dangerous operations cannot self-authorize.

-------------------------
PHASE 15.6 — CODE EXECUTION FOUNDATION
-------------------------

Implement governed Code execution abstraction.

Support:

Assist
Prototype
Build
Launch

Establish sandbox controls.

Do not require a native ORNEUR model.

Use provider/model abstraction.

-------------------------
PHASE 15.7 — PRODUCT + REQUIREMENT COMPILERS
-------------------------

Implement Product Contract.

Implement stable Requirement Compiler.

Trace requirement -> implementation -> test -> evidence.

-------------------------
PHASE 15.8 — VERIFICATION ENGINE
-------------------------

Implement verification records.

Integrate:

build
tests
regression
security
authority
applicable performance/accessibility/release checks

Preserve exact command outputs/evidence references.

-------------------------
PHASE 15.9 — ANTI-TEST-GAMING + COURT
-------------------------

Implement detection/review workflow for suspicious verification changes.

Implement risk-aware Cognitive Court abstraction.

Do not claim native Aeternum arbitration.

-------------------------
PHASE 15.10 — PRODUCTION PROOF
-------------------------

Implement Production Proof schema/generator.

Test partial/unverified evidence behavior.

Prove missing checks never become PASS.

-------------------------
PHASE 15.11 — RELAY SESSION CORE
-------------------------

Implement Relay session/device state.

Support secure reconnect to same mission.

Raw secrets excluded.

-------------------------
PHASE 15.12 — RELAY SECURITY MODES
-------------------------

Implement/test at least foundational:

Trusted Device
Public Device
Mobile Review API/state surface

Enterprise Relay may remain architecture-level unless actually
implemented.

Test session revocation and reauthentication boundaries.

-------------------------
PHASE 15.13 — RECONNECT + IDEMPOTENCY
-------------------------

Simulate:

network drop before response
operation succeeds remotely
client reconnects

Prove no duplicate dangerous operation.

Test multi-device concurrency.

-------------------------
PHASE 15.14 — SIX-HOUR MISSION GOVERNANCE
-------------------------

Implement configurable mission-window logic with canonical production
default of 6 hours.

DO NOT make tests wait six hours.

Use injected clock/time abstraction.

Test boundary precisely.

At expiration prove:

checkpoint persisted
state = PAUSED_WINDOW_REACHED
no state loss
resume works

-------------------------
PHASE 15.15 — INTEGRATED QUALIFICATION
-------------------------

Run end-to-end qualification of the implemented Phase 15 system.

At minimum attempt to prove:

idea/spec -> Product Contract
Product Contract -> requirements
requirements -> mission
mission -> execution
execution -> verification
verification -> Production Proof
checkpoint -> process restart -> resume
Relay -> disconnect -> reconnect
operation -> lost response -> reconcile without duplicate action
public-device restrictions
approval boundary
anti-test-gaming
COMPLETED_UNVERIFIED cannot masquerade as COMPLETED_VERIFIED
six-hour-window logic via controlled clock
existing Phase 14 security regressions remain green

Run full deterministic regression.

Run security suite.

Run authority/godmode/cancellation subsets.

Run Docker/container smoke where applicable.

Run real database migration testing against a non-production Neon branch
before production migration.

Do not manufacture unavailable external tests.

======================================================================
31. CURRENT INFRASTRUCTURE CONSTRAINTS
======================================================================

Current verified/selected architecture includes:

GitHub
Neon Postgres
Cloudflare edge
existing Northflank staging evidence from Phase 14

Planned/supporting architecture may include:

Modal for AI/worker compute
Vercel for web product surfaces

Do not mark Modal/Vercel production verified unless they actually are.

Do not activate AWS, GCP, or Azure simply for trial credits.

Do not destroy or replace the proven Phase 14 deployment merely because
another architecture is planned.

Migration of hosting providers is a separate evidence-bearing decision.

======================================================================
32. PHASE 14 NON-REGRESSION INVARIANTS
======================================================================

Phase 15 must preserve:

authority isolation
security-root behavior
tenant isolation
private-origin protection
Cloudflare Access behavior
host-spoof protection
CORS restrictions
request-body-size protection
rate limiting
secret redaction
security headers
container boot
health/readiness semantics
audit integrity
cancellation behavior

Phase 14C.1 known limitations remain explicit.

Particularly:

Cloudflare Free Managed Ruleset was live-tested and did NOT block the
synthetic SQLi/XSS-shaped requests used in qualification.

Do not rewrite that limitation into a PASS claim.

Existing leaked-credential rule was deliberately preserved.

Current trusted proxy wildcard remains a production hardening gate:

ORNEUR_TRUSTED_PROXY_CIDRS=*

It is currently acceptable only under the already-evidenced private-origin
boundary.

Before enterprise production claims, stronger network/service identity
should be implemented where the selected platform supports it.

======================================================================
33. DEFERRED MODEL-RUNTIME GATES
======================================================================

Phase 14 deferred:

live SSE/model streaming qualification
live model-driven SSRF qualification

because a real cloud model runtime was absent.

When Phase 15 introduces a genuine remote model execution path, these gates
must automatically become mandatory.

Do not leave them deferred after their prerequisite exists.

======================================================================
34. SECURITY HARD RULES
======================================================================

No credentials in Git.

No secrets in evidence.

No secret forwarding through Relay.

No model authority over approval policy.

No silent privilege escalation.

No public-device raw secret access.

No duplicate dangerous actions after reconnect.

No test weakening.

No bypassing existing security middleware.

No destructive production schema migration without tested branch evidence
and appropriate approval.

No arbitrary host execution marketed as sandboxing.

No custom cryptography without compelling audited justification.

======================================================================
35. TEST HARD RULES
======================================================================

Never:

delete failing tests to pass
rename tests to evade collection
weaken assertion strength without requirement justification
exclude suites to improve numbers
mock away the behavior being qualified
modify expected values merely to match bad output
disable security tests
skip known regressions

Every collection-count change must be reconciled.

Distinguish:

NEW TEST
REMOVED TEST
RENAMED TEST
PARAMETRIZATION DRIFT
COLLECTION FAILURE

Preserve Phase 14 evidence rather than overwriting it.

======================================================================
36. EVIDENCE POLICY
======================================================================

Every Phase 15 subphase ends with an evidence checkpoint.

Required checkpoint format:

PHASE:
OBJECTIVE:
BASELINE:
IMPLEMENTED:
FILES / COMPONENTS:
MIGRATIONS:
COMMANDS EXECUTED:
TESTS EXECUTED:
EXACT RESULTS:
SECURITY FINDINGS:
AUTHORITY FINDINGS:
MISSION STATE FINDINGS:
CHECKPOINT / RESUME FINDINGS:
RELAY FINDINGS:
ANTI-TEST-GAMING FINDINGS:
PRODUCTION PROOF STATUS:
REGRESSIONS:
TEST COLLECTION DELTA:
TECHNICAL DEBT:
KNOWN LIMITATIONS:
UNVERIFIED ITEMS:
DEFERRED ITEMS:
OWNER ACTION REQUIRED:
EVIDENCE:
EPISTEMIC STATE:

PROGRESSION VERDICT:

YES — EVIDENCE SUPPORTS PROGRESSION

or

NO — BLOCKING ISSUES REMAIN

Do not proceed to the next subphase after NO until the blocking issue has
been resolved or explicitly owner-deferred with justification that does
not invalidate the final gate.

======================================================================
37. PHASE 15 FINAL ACCEPTANCE GATE
======================================================================

Phase 15 may PASS only when evidence demonstrates, for the implemented
V1 scope:

1. durable mission state exists;
2. mission state transitions are validated;
3. checkpoints survive restart;
4. resumability is real;
5. operation idempotency prevents duplicate dangerous work;
6. authority decisions are external to model self-approval;
7. Code modes exist with enforceable distinctions;
8. requirements are traceable to tests/evidence;
9. anti-test-gaming controls exist;
10. Production Proof exists and does not fabricate missing evidence;
11. Relay securely reconnects to durable mission state;
12. device/session revocation works;
13. Public Device restrictions are enforceable;
14. reconnect truthfully resolves pending operations;
15. multi-device races do not duplicate privileged operations;
16. six-hour mission-window semantics are implemented/tested;
17. existing security/authority regressions remain green;
18. database migrations are reproducible and safely tested;
19. secrets remain untracked/unexposed;
20. known limitations remain explicit.

The existence of classes/interfaces alone is not sufficient.

The final verdict must be:

YES — EVIDENCE SUPPORTS PROGRESSION

or

NO — BLOCKING ISSUES REMAIN

======================================================================
38. PHASE 16 LOCK
======================================================================

DO NOT START PHASE 16 during this run unless:

Phase 15.15 has completed,
all blocking Phase 15 requirements are satisfied,
and the final Phase 15 verdict is exactly:

YES — EVIDENCE SUPPORTS PROGRESSION

Even after PASS, STOP and report readiness.

Wait for explicit owner authorization before beginning Phase 16.

Phase 16 will be:

ORNEUR NATIVE INTELLIGENCE CORE

including:

ORNEUR Cognitive Language
Epistemic State Machine
Epistemic Integrity Protocol
Intelligence Escalation Reflex
Genesis
Novus
Aeternum
ORNEUR Auto
Epistemic Twin Distillation
Failure Genome
Outcome Memory Loop
Capability Delta Ledger
Three-Level Self-Improvement
Training / Promotion Governance
Model Society Integration
Native Intelligence Evaluation
Adversarial Hardening
Release Readiness

======================================================================
39. EXECUTION INSTRUCTION
======================================================================

Begin now.

First print:

PHASE 15.0 — BASELINE

OBJECTIVE:
CURRENT BASELINE:
INVARIANTS:
ACCEPTANCE CRITERIA:
TEST PLAN:
SECURITY PLAN:
ROLLBACK PLAN:

Then inspect the repository.

Then persist this canonical specification.

Then create the Phase 15 requirements/implementation plan.

Then execute sequentially:

15.0
15.1
15.2
...
15.15

Do not jump ahead.

Do not ask the owner for implementation decisions that can be resolved
from repository evidence and this specification.

Stop only for:

- genuinely missing credentials;
- external authorization;
- irreversible or paid operation approval;
- ambiguous product decisions that materially change the agreed scope;
- a failed evidence gate that cannot be resolved locally.

Evidence over confidence.
Verification over assertion.
Authority over autonomy.
Correct uncertainty over fabricated certainty.
