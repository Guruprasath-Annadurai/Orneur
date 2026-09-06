# Current Reasoning Architecture Audit (Phase 6, required first action)

Maps exactly what exists today, before any Deliberation Fabric code is
written. Classification legend: REAL / RULE_BASED / MODEL_ONLY /
DUPLICATED / UNBOUNDED / DEAD / LEGACY / UNSAFE / MISSING.

| Component | Classification | Notes |
|---|---|---|
| `orca/brain/agent.py::AgentLoop._reflect()` | REAL, MODEL_ONLY, UNSAFE | The exact "reflect on your answer" pattern spec §29 asks to replace. One raw `self.brain.complete()` call (Gateway bypass — same class Phase 4/5 disclosed elsewhere), fed `REFLECTION_PROMPT` (`orca/character.py`) — four vague free-text questions, output is unstructured prose, no claims/evidence/hypotheses. Bounded by `REFLECTION_THRESHOLD=150` words (only reflects on long responses) — the one real bound. |
| `orca/brain/agent.py::AgentLoop._plan()` | REAL, RULE_BASED-ish/MODEL_ONLY hybrid | Single model call classifying `direct` vs tool-use; JSON-shaped output with a deterministic fallback (`{"action": "direct"}`) on parse failure. Bounded (`MAX_TOOL_ROUNDS` caps `_execute_tools`). Not reasoning in Phase 6's sense — a routing decision, not hypothesis/evidence work. |
| `orca/variants/ultra.py::OrcaUltra` | REAL, MODEL_ONLY, UNSAFE, DUPLICATED (of what Court formalizes) | Multi-agent pod: decompose → parallel sub-agents → synthesize → **grade (0-100 score via one model call)** → self-heal retry if `score < 65` (bounded, `max_retries=2`). This IS a real, working "critic checks work and triggers retry" loop — but the "critic" is a single unstructured JSON score/feedback, not independent Constructor/Falsifier roles, no evidence citations, no hypothesis tracking, no verdict states beyond a number. All model calls are raw `self.brain.complete()` (Gateway bypass). This is the closest existing thing to Cognitive Court and is the system Phase 6's Court supersedes for anything Court-eligible — not deleted, since it also does real multi-agent task decomposition/parallel execution Court doesn't replace. |
| `orca/brain/reasoning.py::ReasoningEngine` | DEAD/LEGACY, UNSAFE | A thin `OrcaBrain` wrapper (`get_brain()`, raw Gateway bypass). Grep confirms zero callers outside its own module — dead code, kept for any external/notebook usage. Not reasoning logic itself, just a convenience wrapper predating `ModelGateway`. |
| `orca/serve/routing.py::decide_route`/`classify_query` | REAL, RULE_BASED, well-bounded | **Not reasoning** in Phase 6's sense — this is cost-aware BACKEND routing (self-hosted vs. frontier API for a single tier), gated by an explicit operator opt-in, a sovereignty lock, a daily escalation cap, and a lexical heuristic (`_TIME_RE`/`_COMPLEX_RE`). Genuinely well-designed (four independent gates, documented as heuristic, never silently escalates). Kept entirely as-is — Phase 6's `ReasoningCompiler` decides reasoning MODE (DIRECT/ANALYTICAL/DELIBERATIVE/COURT_REVIEW/...), a completely separate decision from which backend serves the chosen model tier. |
| `orca/cognitive/complexity.py`/`risk.py`/`evidence.py` (Phase 3) | REAL, RULE_BASED | Already classify complexity/risk/evidence-requirement deterministically. `ReasoningCompiler` consumes these AS INPUT (per spec §5) rather than re-deriving them — no duplication. |
| `orca/truth/truth_fabric.py` (Phase 4/4.1) | REAL | Already the evidence authority (retrieval, `EvidenceGraph`, claim verification, citation, contradiction, counter-evidence, `EvidenceState`). Deliberation Fabric consumes this via its existing interfaces (spec §38) — no second retrieval/verification stack built in Phase 6. |
| `orca/memory/*` (Phase 5/5.1) | REAL | `MemoryFirewall`, `MemoryArbiter`, epistemic states, `WorkingMemory` all already real. Court consumes memory only through the Firewall (spec §35) — no new memory access path. |
| Any existing `Hypothesis`/`CourtVerdict`/`CausalGraph`/`Counterfactual`/`WorldState` contract | MISSING | Confirmed by search — none of these concepts exist anywhere in the codebase today. Net-new for Phase 6. |
| Any existing "majority vote across N models" mechanism | MISSING | Confirmed absent — nothing to disable/guard against; the spec's warning against majority voting (§20) is a forward-looking constraint on the NEW Court, not a removal of existing code. |
| Failure recovery / retry logic outside `OrcaUltra`'s self-heal | REAL, bounded, scattered | `orca/gateway/`'s own retry/circuit-breaker (Phase 2, unrelated to reasoning), `tests/ollama_test_support.py`'s bounded transient-error retry (test infrastructure, not production reasoning). No production "replan on contradiction" loop exists anywhere — MISSING, net-new for Phase 6 (spec §28). |

## What Phase 6 must NOT rewrite (spec §3's "do not rewrite until classified")

- `orca/serve/routing.py` — a different, already-correct concern (backend
  cost routing), untouched.
- `orca/brain/agent.py::AgentLoop`'s tool-use loop and `_plan()` —
  real, working, still the execution engine for `USE_TOOL`/
  `DELEGATE_AGENT` plans per Phase 3's `CUTOVER.md` discipline
  (unchanged again this phase — spec §60 explicitly forbids redesigning
  Agent Runtime).
- `orca/variants/ultra.py::OrcaUltra`'s task decomposition/parallel
  execution — Court does not replace multi-agent task orchestration,
  only the "grade the output" critic step is superseded where a request
  is Court-eligible.

## What Phase 6 replaces/supersedes for Court-eligible requests

- `AgentLoop._reflect()`'s vague reflection prompt is superseded by
  structured `DeliberationRound`/`Argument`/`CourtVerdict` objects for
  any request the `ReasoningCompiler` routes to `DELIBERATIVE`/
  `COURT_REVIEW` mode. `_reflect()` itself is left in place, unmodified,
  for the (majority of) requests that don't need Court — matching spec
  §41-42's "not every request needs Court, simple requests stay fast."
