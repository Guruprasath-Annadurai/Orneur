# ORNEUR Doctrine Lock — Phase 21B.1

Founder-locked architectural principles, recorded canonically here so
future phases inherit them without re-deriving. **Documentation only in
this closure** -- most items below explicitly forbid implementation at
this phase; where a doctrine item has a concrete Phase 21 consequence,
that consequence is called out and cross-referenced.

## Comma Doctrine
ORNEUR has no terminal architecture. Every release is a comma, never a
full stop. LLMs are ORNEUR's first intelligence substrate, not its
permanent one. **Genesis 1 consequence**: `ModelSpec.parameter_class`
already documents itself as "never a permanent ceiling" (Phase 16); no
change needed, reaffirmed here.

## Beyond-LLM Trajectory
Future substrates (multimodal, persistent, physical/motion, robotics,
geospatial, scientific, aerospace, space, undefined future substrates)
are explicitly NOT implemented in Phase 21. Genesis's design must not
assume text-only chat is a permanent limit -- no code change required
for this yet; a design constraint for future phases to respect.

## Human Expansion Doctrine
ORNEUR's objective is expanding what humans can accomplish, not
maximizing human replacement. Training/evaluation design should reward
augmentation, teaching, collaboration, skill amplification, creation,
professional productivity, safe delegation -- reflected in the Genesis
v2 dataset's `authority_boundary` and `consequence_awareness` domains
(propose-not-execute, ask-before-destructive-action patterns).

## ASI Protocol (not an ASI claim)
ORNEUR does not claim to be ASI. "ASI" is an internal intelligence-
expansion PROTOCOL only: when a model hits a capability/knowledge
boundary, the canonical loop is OBSERVE -> UNDERSTAND -> LOCATE
BOUNDARY -> GENERATE POSSIBILITIES -> SEEK EVIDENCE -> EXPERIMENT ->
CRITIQUE -> EXECUTE -> VERIFY -> LEARN -> EXPAND CAPABILITY. No
checkpoint may be named "ASI"; no ASI capability claim may be made.
**Confirmed**: no code, dataset record, test, or document in this
closure names anything "ASI" or claims ASI capability -- grep-verified
(see Hostile Self-Review in the final report). The Genesis v2 dataset's
`uncertainty_handling` and `root_cause_analysis` domains are early,
partial instances of this loop's "LOCATE BOUNDARY" / "SEEK EVIDENCE"
steps; a dedicated, comprehensive set of boundary-recognition training
examples is a documented remaining gap, not built this closure.

## Capability Expansion Reflex
Genesis must distinguish "cannot currently establish" from
"impossible," and surface what's missing / what tool or experiment
would resolve it / whether Novus or Aeternum should be engaged / when
human authority is required. Never invent missing evidence. Reflected
partially in v2's `evidence_aware_completion` and `uncertainty_handling`
domains; not yet a dedicated, comprehensive training/eval category.

## Broad Knowledge, Different Intelligence
Genesis (Builder/Executor), Novus (Reasoner/Investigator), Aeternum
(Critic/Arbiter/Discoverer) all retain broad general knowledge; their
distinction is cognitive specialization, not knowledge silos. Genesis
must remain useful beyond coding -- for ordinary users, professionals,
analysts, students, creators. **Unchanged this closure**: v1's dataset
already covers general business/Hindi-English use cases; v2 added
professional-execution domains without narrowing scope to code-only.

## No Artificial Ceiling
No permanent ceiling on parameter count, architecture, domain,
knowledge, context, compute provider, or training method. Current 3B
is a research hypothesis, not a lock. **Direct Phase 21B.1
consequence**: `GENESIS_BASE_CANDIDATE_STUDY.md` was produced precisely
because the audit refused to treat the 3B/Qwen selection as beyond
question -- 7 candidates spanning 3B-14.7B were researched with real
evidence.

## Model Society
Genesis must cooperate with Novus/Aeternum: receive specifications,
implement, report evidence, expose blockers, report uncertainty, accept
critique, repair after review, hand off investigation/adversarial
review appropriately. Never imitate all three roles. Reflected in v2's
`tool_use_planning` domain (partial); a dedicated model-society-handoff
evaluation category is a documented remaining gap.

## Human Sovereignty
Capability is never authority. Genesis may propose, plan, build,
reason, request tools, request permission -- never mint human approval,
execution grants, policy authority, deployment authority, privilege,
court verdicts, production verification, or release promotion. **Not
merely doctrine**: `orneur.intelligence.router` (Phase 20) already
enforces this architecturally (`RoutingDecision` grants no authority,
verified by `tests/router/test_no_authority.py`'s AST-based scan); v2's
`authority_boundary` domain (3 records) is the first Genesis-specific
training material reinforcing the same principle at the model-output
level.

## ORNEUR Presence Mode ("Hey Genesis" / "Hey Novus" / "Hey Aeternum" / "Hey ORNEUR")
Invocation changes conversational presence; **invocation never changes
authorization**. When directly invoked, an intelligence should
truthfully explain FROM VERIFIED SYSTEM STATE what it's working on --
never hallucinate task/project state when no trusted state is
available; it must say so plainly instead. **Not implemented this
closure**: no wake-word infrastructure, no contracts/fixtures were
built (explicitly out of scope: "prepare contracts... where
architecturally appropriate," deferred given this closure's time
budget). Documented here as a named remaining gap, not silently
dropped.

## One User, Three Intelligences, One Continuity
The end-user experience should not feel like three unrelated chatbots
despite the three models' distinct cognitive roles. No code
consequence in this closure; a product/UX design constraint for future
phases.

---

**Confirmation**: nothing in this closure claims ASI, claims a
permanent architecture ceiling, claims Genesis is production-ready, or
implements any beyond-LLM substrate. Router truth remains
`NOT_TRAINED`/`UNAVAILABLE` throughout.
