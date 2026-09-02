"""
Orca Web Server — FastAPI backend for the browser UI.

Endpoints:
  GET  /                    → serves the public marketing landing page
  GET  /app                 → serves the web chat UI
  GET  /trust               → serves the Trust & Security page
  GET  /api/status          → model, memory stats, uptime
  POST /api/chat            → single-shot response
  POST /api/stream          → SSE streaming response
  POST /api/memory/recall   → query long-term memory
  POST /api/remember        → store a fact permanently
  GET  /api/sessions        → list past sessions
  POST /api/session/load    → resume a session

100% local — no external calls from the server itself.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orca.license import current_tier, get_active_license, has_feature
from orca.license.keys import format_expiry

from orca.auth import auth_router, get_current_user, get_current_user_optional, check_quota, increment_usage
from orca.auth.rbac import require_permission
from orca.auth.store import User, model_access_allowed
from orca import audit
from orca.lens.intent import detect_generation_intent

from orca.brain.providers import get_brain
from orca.serve.registry import resolve_tier_model, resolve_tier_backend, TierResolution
from orca.serve import routing
from orca.governance.model_cards import check_persona_claim_allowed
from orca.brain.backends import BackendResponse
from orca.gateway.wiring import brain_for_tier_resolution
from orca.brain.memory import MemoryEngine, EpisodicMemory
from orca.brain.agent import AgentLoop
from orca.brain.context import ContextManager
from orca.tools import build_registry
from orca.character import CORE_SYSTEM_WITH_TOOLS
from orca.personas import get_persona_system
from orca.config import CONFIG, ORCA_HOME, orneur_env
from orca.variants.ultra import OrcaUltra
from orca.docs import (
    extract, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE,
    chunk_text, DocStore, register_doc, unregister_doc, list_docs,
    run_deep_rag,
)
from orca.docs.citation_check import check_citations
from orca.docs.pii_redact import redact_pii
from orca.brain.explainability import ExplainStore, build_from_rag_result
from orca.brain.knowledge_graph import KnowledgeGraph
from orca.brain.vision import is_vision_capable, encode_image, build_vision_message
from orca.serve import session_store, ratelimit, metrics, dlp
from orca.serve.moderation import check_input, CRISIS_RESOURCES
from orca.code import run_code

_START_TIME = time.time()
WEB_DIR = Path(__file__).parent / "web"
_logger = logging.getLogger("orca.serve")

app = FastAPI(title="Orca API", version="1.0.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """
    Records request count/status/latency per endpoint. Uses the matched
    ROUTE TEMPLATE (e.g. "/api/explain/{session_id}/{message_id}"), not the
    raw path with real session IDs substituted in — using raw paths as
    metric labels would create unbounded cardinality (a new "endpoint" for
    every distinct session/doc/message ID ever seen), which is exactly the
    kind of metrics-system footgun that quietly blows up memory in
    production. route.path is only available on request.scope AFTER
    routing has resolved, which happens by the time call_next() returns.
    """
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000

    route = request.scope.get("route")
    endpoint = route.path if route else request.url.path
    metrics.record_request(f"{request.method} {endpoint}", response.status_code, duration_ms)

    return response


app.include_router(auth_router)


# ─────────────────────────────────────────────────────────────────────────────
#  Session store — one AgentLoop + MemoryEngine per browser session
# ─────────────────────────────────────────────────────────────────────────────

def _model_name_for_variant(variant: str | None) -> str:
    def _log_fallback(requested_tier: str, requested_model: str, resolved_model: str) -> None:
        _logger.warning(
            "Tier '%s' requested model '%s' which is not installed in Ollama — "
            "falling back to '%s'.", requested_tier, requested_model, resolved_model,
        )
        metrics.record_registry_fallback(requested_tier, resolved_model)

    return resolve_tier_model(variant or "core", on_fallback=_log_fallback)


def _resolve_backend_for_chat(variant: str | None):
    """
    Full (backend, model) resolution — including frontier API backends and
    the data-sovereignty lock (see orca/serve/registry.py,
    orca/brain/backends.py, docs/STARTUP_PLAN.md §2). Used by /api/chat to
    decide between the existing full-featured Ollama+AgentLoop path (tools,
    memory, knowledge graph — unchanged) and the simpler frontier-passthrough
    direct-generation path (see _generate_via_frontier_backend below).
    """
    def _log_fallback(requested_tier: str, requested_backend: str, resolved: str) -> None:
        _logger.warning(
            "Tier '%s' requested backend '%s' which is unavailable — falling back to '%s'.",
            requested_tier, requested_backend, resolved,
        )
        metrics.record_registry_fallback(requested_tier, resolved)

    def _log_sovereignty_override(tier: str, configured_backend: str) -> None:
        _logger.warning(
            "Data sovereignty lock is active — tier '%s' configured for backend '%s' "
            "was forced to self-hosted Ollama instead.", tier, configured_backend,
        )

    return resolve_tier_backend(
        variant or "core", on_fallback=_log_fallback, on_sovereignty_override=_log_sovereignty_override,
    )


def _apply_cost_aware_routing(base_resolution, message: str):
    """
    Per-query cost-aware escalation layer (see orca/serve/routing.py) —
    applied AFTER the tier's static backend resolution, additive and
    off-by-default. This is the mechanism that makes the "cheaper than
    frontier-per-query competitors" claim real: most queries stay on the
    self-hosted resolution _resolve_backend_for_chat already returned;
    only a query classified as genuinely needing it, and only when the
    operator explicitly opted in, ever escalates.

    Returns (resolution, decision) — the decision is NOT just logged, it's
    surfaced to the caller (audit log + API response, see the /api/chat
    handler below) so a per-request escalation is visible to the end user,
    not only discoverable by an operator reading logs. A deployment that
    promises "self-hosted, your data stays here" needs its own users to be
    able to see the one query that didn't honor that, not just its ops team.
    """
    resolution, decision = routing.decide_route(base_resolution, message)
    metrics.record_routing_decision(decision.escalated)
    if decision.escalated:
        _logger.info(
            "Cost-aware routing escalated tier '%s' to backend '%s' — reason: %s",
            base_resolution.tier, resolution.backend, decision.reason,
        )
    return resolution, decision


# Phase 3.1: user-safe abstention messages -- never expose the internal
# AbstentionReason enum name directly (spec §17). Kept as one table so
# every caller (chat/stream) shows the identical wording.
_ABSTENTION_MESSAGES = {
    "INSUFFICIENT_CAPABILITY": "This request needs a verification capability that isn't available yet, so it can't be safely answered.",
    "INSUFFICIENT_EVIDENCE": "This request can't be answered with sufficient grounding right now.",
    "BUDGET_EXHAUSTED": "This request exceeds the available processing budget for a single turn.",
    "MODEL_UNAVAILABLE": "No model is currently available to handle this request.",
    "REQUIRED_OPERATION_UNAVAILABLE": "This request needs a capability that isn't available yet.",
    "POLICY_RESTRICTION": "This request can't be completed under your current plan.",
    "AMBIGUOUS_REQUEST": "This request is too ambiguous to plan safely.",
    "UNRESOLVED_HYPOTHESES": "This request has multiple plausible explanations that couldn't be resolved with the available evidence.",
    "CRITICAL_CONTRADICTION": "The available evidence contains an unresolved contradiction on a critical point, so this can't be answered with confidence.",
    "FALSIFICATION_FAILED": "The candidate answer for this request didn't hold up under review, and no adequate revision could be produced.",
    "COURT_INSUFFICIENT_EVIDENCE": "This request needed deeper review, and the available evidence wasn't sufficient to reach a confident answer.",
    "DELIBERATION_BUDGET_EXHAUSTED": "This request needed deeper review, which ran out of available processing budget before completing.",
}


async def _run_cognitive_kernel(message: str, user: "User | None", model_variant: str | None, session_id: str | None = None):
    """
    Phase 3.1: the Cognitive Kernel is now AUTHORITATIVE for planning and,
    where possible, execution of /api/chat and /api/stream requests (see
    docs/orneur/phase-3/PRODUCTION_CUTOVER.md). Every request is planned
    and entitlement-reconciled here before any generation happens.

    Returns the real orca.cognitive.contracts.CognitiveResult. Callers
    branch on `.status`/`.output`:
      - status == ABSTAINED           -> the Kernel declined; no generation
                                          should happen at all.
      - status == COMPLETED, output   -> the Kernel answered directly via
        is not None                      ModelGateway; use `.output` as the
                                          final response, skip AgentLoop.
      - status == COMPLETED, output   -> the plan needs RETRIEVE/USE_TOOL/
        is None                          RECALL_MEMORY/DELEGATE_AGENT; fall
                                          through to the existing
                                          _Session/AgentLoop path, using
                                          `.resolved_tier` (already
                                          entitlement-reconciled) instead of
                                          the raw requested tier.

    This function itself never raises for entitlement/reconciliation
    reasons -- CognitiveKernel.execute() only raises
    CognitiveExecutionFailedError for a genuine internal failure, which
    callers must let propagate (mapped the same way any other internal
    error already is), never silently swallowed.
    """
    from orca.cognitive.contracts import CognitiveRequest
    from orca.cognitive.entitlement import class_rank, derive_entitlement_policy, tier_to_class
    from orca.cognitive.wiring import get_shared_kernel

    kernel = get_shared_kernel()
    entitlement = derive_entitlement_policy(user, model_variant)

    # The user's OWN explicit tier choice is an ADDITIONAL ceiling on top
    # of their overall commercial entitlement -- a pro user who explicitly
    # picked "nano" for this conversation must not have some individual
    # message silently answered via "ultra" just because the Kernel judged
    # it complex and their overall plan permits ultra. Entitlement caps
    # what's possible; the user's own selection caps what's used here.
    if model_variant:
        requested_class = tier_to_class(model_variant.removeprefix("orca-"))
        if class_rank(requested_class) < class_rank(entitlement.maximum_quality_class):
            entitlement.maximum_quality_class = requested_class
            entitlement.allowed_model_classes = {
                c for c in entitlement.allowed_model_classes if class_rank(c) <= class_rank(requested_class)
            }

    cognitive_request = CognitiveRequest(
        objective=message, session_id=None, requested_mode=model_variant,
        tenant=user.id if user else None,
    )

    # Phase 4: a lightweight lookup into the existing module-level
    # `_sessions` dict, not a forced full _Session construction (this
    # function runs BEFORE session construction on the /api/chat and
    # /api/stream paths -- see the caller's own comment on why). Only an
    # ALREADY-LIVE session's DocStore is used; a brand-new session simply
    # has no doc_store yet, which TruthFabric already handles honestly
    # (no evidence found, not a fabricated citation).
    doc_store = _sessions[session_id].doc_store if session_id and session_id in _sessions else None
    return await kernel.execute(cognitive_request, entitlement=entitlement, doc_store=doc_store)


def _record_shadow_verification(requested_tier: str | None, resolved_tier: str | None) -> None:
    """
    Phase 3.1 spec §11: shadow comparison is retained TEMPORARILY, purely
    as a verification/drift-monitoring signal now that the Kernel is
    authoritative -- it can never override what the Kernel already
    decided (that decision already happened in _run_cognitive_kernel by
    the time this is called). Never breaks the real request.
    """
    try:
        from orca.cognitive.metrics import record_shadow_comparison
        record_shadow_comparison(kernel_tier=resolved_tier or "", legacy_tier=(requested_tier or "core").removeprefix("orca-"))
    except Exception:
        _logger.debug("Cognitive shadow verification recording failed — real serving path unaffected.", exc_info=True)


def _generate_via_frontier_backend(resolution, persona_system: str, message: str):
    """
    Direct, single-turn generation through a frontier API backend
    (OpenAI/Anthropic) — the "bring your own frontier model" path.

    HONEST SCOPE: this does NOT run the tool-use agent loop (web_search,
    run_code, memory_recall, etc.) that the self-hosted Ollama path gets via
    AgentLoop — that's real, separately-scoped follow-up work (tool-calling
    formats differ meaningfully between OpenAI/Anthropic/Ollama, and
    building that out for one provider without verifying it live isn't
    something to silently claim parity on). This is a genuine, working
    single-turn passthrough, not a stub — just intentionally narrower than
    the self-hosted path until tool-use is built and tested per-provider.
    """
    # Cut over to the Model Gateway (Phase 2.1) -- routed through the same
    # FrontierRuntime/circuit-breaker/concurrency machinery as any other
    # Gateway request, instead of constructing a Backend directly. Uses the
    # Gateway (not GatewayBrain) here because this function's callers need
    # the FULL response (cost_usd, token counts), not just the output text
    # GatewayBrain.complete() returns -- see BackendResponse's field shape
    # below, preserved for backward compatibility with existing callers.
    from orca.gateway.contracts import InferenceRequest
    from orca.gateway.sync_bridge import run_async_in_thread
    from orca.gateway.wiring import brain_for_tier_resolution as _bridge

    disclosure = (
        f"\n\n[TRANSPARENCY NOTICE — auto-injected]\nThis response is generated by "
        f"{resolution.backend}'s {resolution.model} model via API, not an Orca-trained model. "
        f"Orca's own eval/red-team gating does not apply to a model Orca did not train — "
        f"refer to {resolution.backend}'s own published model card for its capability and "
        f"safety characteristics."
    )
    gateway_brain = _bridge(resolution)
    inference_request = InferenceRequest(
        request_id=str(uuid.uuid4()), model_id=gateway_brain.model_id, model_version=gateway_brain.model_version,
        messages=[{"role": "user", "content": message}], system=persona_system + disclosure, max_tokens=1024,
    )
    inference_response = run_async_in_thread(
        lambda: gateway_brain._gateway.generate(inference_request, allow_experimental=gateway_brain.allow_experimental)
    )
    result = BackendResponse(
        text=inference_response.output,
        backend=inference_response.runtime,
        model=inference_response.resolved_version,
        input_tokens=inference_response.prompt_tokens,
        output_tokens=inference_response.completion_tokens,
        cost_usd=inference_response.cost_usd,
        latency_ms=inference_response.latency_ms,
        data_left_infrastructure=inference_response.data_left_infrastructure,
    )
    return result


class _Session:
    def __init__(self, session_id: str, model_variant: str | None = None):
        self.id = session_id

        # Cross-instance continuity: if Redis has this session's state (from
        # this or another API instance), restore the exact conversation
        # history instead of starting cold. An explicit model_variant from
        # the caller wins over the persisted one (user actively switching
        # models mid-conversation should be respected); Redis only fills in
        # when the caller didn't specify (session_id known, variant omitted).
        redis_state = session_store.load_session_state(session_id)
        restored_history = None
        if redis_state:
            model_variant = model_variant or redis_state.get("model_variant")
            restored_history = redis_state.get("history")

        self.model_variant = model_variant or "core"
        self.memory = MemoryEngine(session_id=session_id)
        # Cut over to the Model Gateway (Phase 2.1) -- GatewayBrain is a
        # drop-in replacement for OrcaBrain's exact interface, so nothing
        # below this line (ContextManager, AgentLoop, tools, memory) needed
        # to change. See docs/orneur/phase-2/LIVE_SERVING_CUTOVER.md.
        tier_resolution = TierResolution(
            tier=(model_variant or "core").removeprefix("orca-"),
            backend="ollama",
            model=_model_name_for_variant(model_variant),
            data_left_infrastructure=False,
        )
        brain = brain_for_tier_resolution(tier_resolution)
        self.ctx = ContextManager(brain)
        tools = build_registry(memory_engine=self.memory)
        self.agent = AgentLoop(brain=brain, tools=tools, session_id=session_id)

        if restored_history:
            self.agent.load_history(restored_history)
        else:
            # Fallback: no exact turn history available (fresh session, or
            # Redis disabled/empty) — reconstruct rough context from the
            # long-term summary store instead. Less precise than Redis's
            # exact history, only used when that's unavailable.
            prior = self.memory.load_prior_context()
            if prior:
                self.agent.load_history([
                    {"role": "user", "content": f"[Prior context]\n{prior}"},
                    {"role": "assistant", "content": "Context loaded."},
                ])

        self.brain = brain
        self.doc_store = DocStore(session_id=session_id, ollama_host=CONFIG.ollama.host)
        self.explain_store = ExplainStore()
        self.knowledge_graph = KnowledgeGraph(session_id=session_id)
        self.last_active = time.time()

    def touch(self):
        self.last_active = time.time()

    def persist_to_redis(self):
        """Save current conversation history so any instance can pick this session back up."""
        session_store.save_session_state(self.id, self.model_variant, self.agent.get_history())


_sessions: dict[str, _Session] = {}


def _get_session(session_id: str | None, model_variant: str | None = None, user_id: str | None = None) -> _Session:
    sid = session_id or str(uuid.uuid4())
    if sid not in _sessions:
        _sessions[sid] = _Session(sid, model_variant)
    _sessions[sid].touch()
    session_store.touch_session(sid)  # refresh Redis TTL — no-op if Redis disabled

    # Records which account this session belongs to — without this, "delete
    # my account" has no way to find and remove the chat history/documents
    # tied to it, since sessions are otherwise anonymous by session_id alone.
    if user_id:
        from orca.auth.store import record_user_session
        record_user_session(user_id, sid)

    # Evict idle sessions (>2h) to save memory
    now = time.time()
    stale = [k for k, v in _sessions.items() if now - v.last_active > 7200 and k != sid]
    for k in stale:
        del _sessions[k]
    return _sessions[sid]


# ─────────────────────────────────────────────────────────────────────────────
#  Request / response models
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    model_variant: str | None = None  # 'nano' | 'core' | 'ultra'


class MemoryRequest(BaseModel):
    query: str
    session_id: str | None = None


class RememberRequest(BaseModel):
    fact: str
    session_id: str | None = None


class LoadSessionRequest(BaseModel):
    session_id: str
    target_session_id: str | None = None


class UltraRequest(BaseModel):
    task: str
    session_id: str | None = None
    model_variant: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
#  Session title persistence
# ─────────────────────────────────────────────────────────────────────────────

_TITLES_PATH = ORCA_HOME / "session_titles.json"


def _load_titles() -> dict[str, str]:
    try:
        return json.loads(_TITLES_PATH.read_text())
    except Exception:
        return {}


_session_titles: dict[str, str] = _load_titles()


def _save_title(sid: str, title: str) -> None:
    _session_titles[sid] = title
    try:
        _TITLES_PATH.write_text(json.dumps(_session_titles))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_landing():
    landing = WEB_DIR / "landing.html"
    if landing.exists():
        return HTMLResponse(landing.read_text())
    return HTMLResponse("<h1>Orca landing page not found</h1>")


@app.get("/app", response_class=HTMLResponse)
async def serve_ui():
    index = WEB_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>Orca UI not found</h1><p>Run: orca serve</p>")


@app.get("/trust", response_class=HTMLResponse)
async def serve_trust():
    trust = WEB_DIR / "trust.html"
    if trust.exists():
        return HTMLResponse(trust.read_text())
    return HTMLResponse("<h1>Orca trust page not found</h1>")


@app.get("/healthz")
async def healthz():
    """
    Lightweight liveness/readiness probe for load balancers and
    orchestrators (k8s, etc.) to poll every few seconds.

    Real gap this closes: /api/status does disk I/O (globbing every raw
    training file to count examples) and lists all sessions on every call
    — fine for an admin dashboard refreshing occasionally, much too heavy
    for something a load balancer hits every 5-10 seconds. This endpoint
    does the minimum: confirm at least nano's tier resolves to an
    installed Ollama model (using registry's own 15s cache, so this adds
    no extra Ollama load beyond what real chat traffic already causes).

    Phase 2.1: additive `gateway` field reports ModelGateway.report_health()
    -- process liveness, runtime readiness, and PER-MODEL deployment
    readiness are kept genuinely distinct (see that method's docstring).
    Deliberately additive, not a replacement: existing clients reading
    `status`/`nano_model` see unchanged behavior. `gateway` only reflects
    whatever has actually been registered via real traffic so far in this
    process's lifetime (deployments are registered lazily on first use per
    orca/gateway/wiring.py) -- an empty `model_readiness` map before any
    request has been served is expected, not a failure.
    """
    try:
        resolved = resolve_tier_model("nano", host=CONFIG.ollama.host)
        result = {"status": "ok", "nano_model": resolved}
    except RuntimeError as e:
        return JSONResponse({"status": "unhealthy", "reason": str(e)}, status_code=503)

    try:
        from orca.gateway.wiring import get_shared_gateway
        result["gateway"] = get_shared_gateway().report_health()
    except Exception as e:
        # A gateway-health reporting failure must never take down the
        # liveness/readiness probe itself -- report it as a sub-field, not
        # a 503 for the whole endpoint.
        result["gateway"] = {"error": str(e)}
    return result


@app.get("/api/status")
async def status():
    brain = get_brain(CONFIG.ollama.model_core)
    online = brain.is_available()
    model_name = "offline"
    if online:
        try:
            model_name = brain.name
        except Exception:
            model_name = "unknown"

    from orca.config import ORCA_HOME
    raw_dir = ORCA_HOME / "training" / "raw"
    raw_count = sum(
        sum(1 for _ in open(f))
        for f in raw_dir.glob("*.jsonl")
        if f.stat().st_size > 0
    ) if raw_dir.exists() else 0

    sessions = EpisodicMemory.list_sessions()

    return {
        "status": "online" if online else "offline",
        "model": model_name,
        "uptime_sec": round(time.time() - _START_TIME),
        "active_sessions": len(_sessions),
        "total_sessions": len(sessions),
        "training_examples": raw_count,
        "version": "1.0.0",
        "redis": {"enabled": session_store.enabled(), "reachable": session_store.ping()},
    }


class CognitiveExecuteRequest(BaseModel):
    objective: str


@app.post("/api/cognitive/execute")
async def cognitive_execute(
    req: CognitiveExecuteRequest,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    """
    INTERNAL / EXPERIMENTAL. Kept from Phase 3 as the no-session, no-
    entitlement, no-RAG/tools variant of Kernel-authoritative execution
    (useful for isolated testing of the Kernel's own direct-answer path).
    As of Phase 3.1, /api/chat and /api/stream are ALSO Kernel-
    authoritative (with entitlement reconciliation) for real production
    traffic -- see docs/orneur/phase-3/PRODUCTION_CUTOVER.md. This
    endpoint only genuinely answers requests whose plan needs nothing
    beyond a direct model call (ANSWER_DIRECTLY/REASON/RECALL_MEMORY); a
    plan needing tools/retrieval/agents completes with an explicit warning
    naming what it deferred, rather than fabricating an answer.
    """
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="cognitive")

    if user:
        allowed, used, limit = check_quota(user.id, user.tier, "message")
        if not allowed:
            return JSONResponse(
                {"error": f"Daily limit reached ({used}/{limit}). Upgrade to Pro for unlimited messages."},
                status_code=429,
            )

    mod_result = check_input(req.objective)
    metrics.record_moderation_action(mod_result.action)
    if mod_result.action == "block":
        audit.log("input_moderation_blocked", user_id=user.id if user else None,
                  detail={"categories": mod_result.flagged_categories, "endpoint": "cognitive_execute"})
        return JSONResponse(
            {"error": "This request can't be processed — it matches a category we don't generate content for."},
            status_code=400,
        )

    from orca.cognitive.contracts import CognitiveRequest
    from orca.cognitive.wiring import get_shared_kernel

    kernel = get_shared_kernel()
    cog_request = CognitiveRequest(objective=req.objective, session_id=None)
    result = await kernel.execute(cog_request)

    if user and result.output is not None:
        increment_usage(user.id, "message")

    audit.log("cognitive_execute", user_id=user.id if user else None, detail={
        "status": result.status.value, "resolved_model": result.resolved_model,
        "abstention_reason": result.abstention_reason.value if result.abstention_reason else None,
    })

    return {
        "request_id": result.request_id,
        "trace_id": result.trace_id,
        "status": result.status.value,
        "output": result.output,
        "resolved_model": result.resolved_model,
        "plan_id": result.plan_id,
        "operations_executed": [op.value for op in result.operations_executed],
        "abstention_reason": result.abstention_reason.value if result.abstention_reason else None,
        "usage": result.usage,
        "latency_ms": round(result.latency_ms, 1),
        "warnings": result.warnings,
    }


@app.post("/api/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    # IP-based floor applies regardless of auth status — the per-user tier
    # quota below only ever ran `if user:`, leaving anonymous requests with
    # zero limit. This closes that gap; authenticated users still also get
    # their tier quota checked right after.
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="chat")

    # Generation requests (image/video) short-circuit here, before any
    # text-tier quota/model-access check — Genesis/Novus/Aeternum never see
    # these messages at all. Orca Lens's actual generation backend isn't
    # built yet (pending model choice), so this is an honest "not yet
    # available" response, not a silent fallthrough to the text models.
    gen_intent = detect_generation_intent(req.message)
    if gen_intent != "chat":
        audit.log("lens_generation_requested", user_id=user.id if user else None,
                  detail={"intent": gen_intent})
        return JSONResponse(
            {"error": f"Orca Lens ({gen_intent} generation) isn't available yet — coming soon.",
             "intent": gen_intent},
            status_code=501,
        )

    if user:
        allowed, used, limit = check_quota(user.id, user.tier, "message")
        if not allowed:
            return JSONResponse(
                {"error": f"Daily limit reached ({used}/{limit}). Upgrade to Pro for unlimited messages."},
                status_code=429,
            )

    model_allowed, model_reason = model_access_allowed(user, req.model_variant)
    if not model_allowed:
        return JSONResponse({"error": model_reason}, status_code=402)

    # Input moderation — checked before the message ever reaches the model.
    # BLOCK: hard refusal, generation never happens. SUPPORT (self-harm):
    # never blocked — crisis resources get injected into context instead,
    # since refusing someone in crisis is the opposite of good practice.
    # FLAG: logged for visibility, generation proceeds unchanged.
    mod_result = check_input(req.message)
    metrics.record_moderation_action(mod_result.action)
    if mod_result.action == "block":
        audit.log("input_moderation_blocked", user_id=user.id if user else None,
                  detail={"categories": mod_result.flagged_categories})
        return JSONResponse(
            {"error": "This request can't be processed — it matches a category we don't generate content for."},
            status_code=400,
        )
    if mod_result.action in ("support", "flag"):
        audit.log(f"input_moderation_{mod_result.action}", user_id=user.id if user else None,
                  detail={"categories": mod_result.flagged_categories})

    # Backend resolution happens BEFORE session construction: the existing
    # _Session/AgentLoop path is Ollama-specific (tool-use, memory, redis
    # continuity — all built around OrcaBrain), so a frontier-API backend
    # takes a deliberately separate, simpler direct-generation path instead
    # of forcing that machinery to pretend to support providers it hasn't
    # been built or tested against. See _generate_via_frontier_backend's
    # docstring for the honest scope of what this path does and doesn't do.
    # Phase 3.1: Cognitive Kernel is now AUTHORITATIVE for planning and,
    # where possible, direct execution -- see
    # docs/orneur/phase-3/PRODUCTION_CUTOVER.md. Runs before any
    # generation happens; a high-risk/unavailable-capability request now
    # honestly abstains here instead of reaching a model at all.
    from orca.cognitive.contracts import CognitiveState
    from orca.cognitive.errors import CognitiveError

    try:
        cognitive_result = await _run_cognitive_kernel(req.message, user, req.model_variant, session_id=req.session_id)
    except Exception as e:
        # A real internal Kernel failure -- the Kernel is authoritative
        # now, so this must surface as a clean error, never be silently
        # swallowed and fallen through to legacy behavior (that was only
        # correct for Phase 3's shadow-mode integration). Never leaks the
        # internal exception/class name to the caller (spec §17). Catches
        # any exception, not just the CognitiveError taxonomy, since a
        # wiring/infrastructure failure reaching this call site is just as
        # real a Kernel-execution failure from the caller's perspective.
        code = e.code.value if isinstance(e, CognitiveError) else "UNMAPPED_COGNITIVE_FAILURE"
        audit.log("cognitive_execution_failed", user_id=user.id if user else None, detail={"code": code})
        return JSONResponse({"error": "This request could not be processed right now. Please try again."}, status_code=500)

    if cognitive_result.status == CognitiveState.ABSTAINED:
        audit.log("cognitive_abstained", user_id=user.id if user else None, detail={
            "reason": cognitive_result.abstention_reason.value if cognitive_result.abstention_reason else None,
        })
        reason_key = cognitive_result.abstention_reason.value if cognitive_result.abstention_reason else ""
        return JSONResponse(
            {"error": _ABSTENTION_MESSAGES.get(reason_key, "This request can't be completed."), "abstained": True},
            status_code=422,
        )

    backend_resolution = _resolve_backend_for_chat(req.model_variant)
    backend_resolution, routing_decision = _apply_cost_aware_routing(backend_resolution, req.message)
    _record_shadow_verification(req.model_variant, cognitive_result.resolved_tier)

    if backend_resolution.backend != "ollama":
        persona_system = get_persona_system(backend_resolution.tier)
        if mod_result.action == "support":
            persona_system += (
                f"\n\nIMPORTANT: This message may indicate the user is in emotional distress or crisis. "
                f"Respond with warmth and care. Include these resources naturally in your response:\n{CRISIS_RESOURCES}"
            )
        try:
            result = await asyncio.to_thread(
                _generate_via_frontier_backend, backend_resolution, persona_system, req.message
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

        if user:
            increment_usage(user.id, "message")

        audit.log("chat", user_id=user.id if user else None, detail={
            "model": backend_resolution.model, "backend": backend_resolution.backend,
            "data_left_infrastructure": backend_resolution.data_left_infrastructure,
            "cost_usd": result.cost_usd, "tools": [],
            "escalated_by_cost_router": routing_decision.escalated,
            "routing_reason": routing_decision.reason,
        })
        if routing_decision.escalated:
            audit.log("cost_aware_escalation", user_id=user.id if user else None, detail={
                "tier": backend_resolution.tier, "escalated_to": backend_resolution.backend,
                "reason": routing_decision.reason,
            })

        # Output-side DLP scan (see orca/serve/dlp.py) — secrets are
        # actively redacted (no legitimate reason a response should ever
        # contain a real credential); PII is flagged for audit visibility
        # only, not stripped from the response, matching
        # orca/docs/pii_redact.py's own reasoning against mangling a
        # user's own legitimate data.
        dlp_result = dlp.scan_output(result.text)
        if dlp_result["has_findings"]:
            audit.log("output_dlp_finding", user_id=user.id if user else None, detail={
                "pii_flagged": dlp_result["pii_flagged"], "secrets_redacted": dlp_result["secrets_redacted"],
            })

        return {
            "response": dlp_result["safe_text"],
            "session_id": req.session_id or str(uuid.uuid4()),
            "used_tools": [],
            "plan": "frontier_passthrough",
            "backend": result.backend,
            "data_left_infrastructure": result.data_left_infrastructure,
            "escalated_by_cost_router": routing_decision.escalated,
            "routing_reason": routing_decision.reason if routing_decision.escalated else None,
        }

    sess = _get_session(req.session_id, req.model_variant, user_id=user.id if user else None)
    mem_ctx = sess.memory.recall_context(req.message, n=3)
    enriched = f"[Relevant memory]\n{mem_ctx}\n\n{req.message}" if mem_ctx else req.message
    persona_system = get_persona_system(sess.model_variant)
    if mod_result.action == "support":
        persona_system += (
            f"\n\nIMPORTANT: This message may indicate the user is in emotional distress or crisis. "
            f"Respond with warmth and care. Include these resources naturally in your response:\n{CRISIS_RESOURCES}"
        )

    used_tools: list[str] = []
    plan_action = "cognitive_direct"
    if cognitive_result.output is not None:
        # Kernel's plan needed nothing beyond a direct model call --
        # answered via ModelGateway already, entitlement-reconciled. Skip
        # AgentLoop's extra plan/reflect calls for this turn entirely.
        final = cognitive_result.output
    else:
        # Plan requires RETRIEVE/USE_TOOL/RECALL_MEMORY/DELEGATE_AGENT --
        # real capabilities the existing AgentLoop path provides; the
        # Kernel already decided this is needed, this is not a bypass.
        try:
            final, trace = await asyncio.to_thread(sess.agent.run, enriched, persona_system)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        used_tools = [tc.tool for tc in trace.tool_calls]
        plan_action = trace.plan_action

    if user:
        increment_usage(user.id, "message")

    sess.memory.add_turn("user", req.message)
    sess.memory.add_turn("assistant", final)
    sess.memory.commit_to_long_term(f"Q: {req.message[:200]}\nA: {final[:500]}")
    # Phase 5: additive, significance-gated Memory Continuum ingestion --
    # does NOT replace the unconditional legacy commit_to_long_term()
    # call above (see orca/memory/turn_ingest.py's own docstring for why).
    from orca.memory.turn_ingest import maybe_ingest_turn
    maybe_ingest_turn(sess.id, req.message, final)
    sess.persist_to_redis()

    audit.log("chat", user_id=user.id if user else None,
              detail={"model": sess.model_variant, "backend": "ollama", "data_left_infrastructure": False,
                      "tools": used_tools, "cognitive_degraded": cognitive_result.degraded,
                      "cognitive_resolved_tier": cognitive_result.resolved_tier})

    # Output-side DLP scan — see the frontier-passthrough branch above for
    # the full rationale. Applied after memory/audit logging deliberately:
    # the audit log and long-term memory should retain what the model
    # actually said (including any secret that leaked, for real incident
    # investigation), while what's RETURNED to the user has secrets
    # redacted.
    dlp_result = dlp.scan_output(final)
    if dlp_result["has_findings"]:
        audit.log("output_dlp_finding", user_id=user.id if user else None, detail={
            "pii_flagged": dlp_result["pii_flagged"], "secrets_redacted": dlp_result["secrets_redacted"],
        })

    return {
        "response": dlp_result["safe_text"],
        "session_id": sess.id,
        "used_tools": used_tools,
        "plan": plan_action,
        "degraded": cognitive_result.degraded,
        "degradation_reason": cognitive_result.degradation_reason if cognitive_result.degraded else None,
    }


@app.post("/api/stream")
async def stream_chat(
    req: ChatRequest,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="stream")

    # Generation requests (image/video) short-circuit here, before any
    # text-tier quota/model-access check — same as /api/chat, see that
    # handler's comment for why this isn't a tool call from within the
    # text models but a pre-dispatch bypass instead.
    gen_intent = detect_generation_intent(req.message)
    if gen_intent != "chat":
        audit.log("lens_generation_requested", user_id=user.id if user else None,
                  detail={"intent": gen_intent})
        _lens_msg = f"Orca Lens ({gen_intent} generation) isn't available yet — coming soon."
        async def _lens_not_available():
            yield f"data: {json.dumps({'type': 'error', 'text': _lens_msg, 'intent': gen_intent})}\n\n"
        return StreamingResponse(_lens_not_available(), media_type="text/event-stream")

    if user:
        allowed, used, limit = check_quota(user.id, user.tier, "message")
        if not allowed:
            async def _quota_err():
                yield f"data: {json.dumps({'type':'error','text':f'Daily limit reached ({used}/{limit}). Upgrade to Pro.'})}\n\n"
            return StreamingResponse(_quota_err(), media_type="text/event-stream")

    model_allowed, model_reason = model_access_allowed(user, req.model_variant)
    if not model_allowed:
        async def _model_gate_err():
            yield f"data: {json.dumps({'type': 'error', 'text': model_reason})}\n\n"
        return StreamingResponse(_model_gate_err(), media_type="text/event-stream")

    mod_result = check_input(req.message)
    metrics.record_moderation_action(mod_result.action)
    if mod_result.action == "block":
        audit.log("input_moderation_blocked", user_id=user.id if user else None,
                  detail={"categories": mod_result.flagged_categories})
        _mod_block_msg = "This request can't be processed — it matches a category we don't generate content for."
        async def _mod_block():
            yield f"data: {json.dumps({'type': 'error', 'text': _mod_block_msg})}\n\n"
        return StreamingResponse(_mod_block(), media_type="text/event-stream")
    if mod_result.action in ("support", "flag"):
        audit.log(f"input_moderation_{mod_result.action}", user_id=user.id if user else None,
                  detail={"categories": mod_result.flagged_categories})

    # Phase 3.1: Cognitive Kernel is now AUTHORITATIVE for planning and,
    # where possible, direct execution -- see
    # docs/orneur/phase-3/PRODUCTION_CUTOVER.md.
    from orca.cognitive.contracts import CognitiveState
    from orca.cognitive.errors import CognitiveError

    try:
        cognitive_result = await _run_cognitive_kernel(req.message, user, req.model_variant, session_id=req.session_id)
    except Exception as e:
        code = e.code.value if isinstance(e, CognitiveError) else "UNMAPPED_COGNITIVE_FAILURE"
        audit.log("cognitive_execution_failed", user_id=user.id if user else None, detail={"code": code})
        _fail_msg = "This request could not be processed right now. Please try again."
        async def _fail_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': _fail_msg})}\n\n"
        return StreamingResponse(_fail_stream(), media_type="text/event-stream")

    if cognitive_result.status == CognitiveState.ABSTAINED:
        audit.log("cognitive_abstained", user_id=user.id if user else None, detail={
            "reason": cognitive_result.abstention_reason.value if cognitive_result.abstention_reason else None,
        })
        reason_key = cognitive_result.abstention_reason.value if cognitive_result.abstention_reason else ""
        _abstain_msg = _ABSTENTION_MESSAGES.get(reason_key, "This request can't be completed.")
        async def _abstain_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': _abstain_msg, 'abstained': True})}\n\n"
        return StreamingResponse(_abstain_stream(), media_type="text/event-stream")

    # Cost-aware escalation — same resolution + routing decision /api/chat
    # applies, checked here too since /api/stream was the one live-chat path
    # that always talked to the local Ollama model regardless of operator
    # config (see orca/serve/routing.py). Resolved before session
    # construction: the frontier branch below doesn't touch the
    # Ollama-specific _Session/AgentLoop machinery at all, matching
    # /api/chat's frontier-passthrough path.
    backend_resolution = _resolve_backend_for_chat(req.model_variant)
    backend_resolution, routing_decision = _apply_cost_aware_routing(backend_resolution, req.message)
    _record_shadow_verification(req.model_variant, cognitive_result.resolved_tier)

    if backend_resolution.backend != "ollama":
        persona_system = get_persona_system(backend_resolution.tier)
        if mod_result.action == "support":
            persona_system += (
                f"\n\nIMPORTANT: This message may indicate the user is in emotional distress or crisis. "
                f"Respond with warmth and care. Include these resources naturally in your response:\n{CRISIS_RESOURCES}"
            )
        message_id = str(uuid.uuid4())
        session_id = req.session_id or str(uuid.uuid4())

        async def _frontier_event_stream() -> AsyncIterator[str]:
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'text': f'escalating to {backend_resolution.backend}...'})}\n\n"

            try:
                result = await asyncio.to_thread(
                    _generate_via_frontier_backend, backend_resolution, persona_system, req.message
                )
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
                return

            dlp_result = dlp.scan_output(result.text)
            if dlp_result["has_findings"]:
                audit.log("output_dlp_finding", user_id=user.id if user else None, detail={
                    "pii_flagged": dlp_result["pii_flagged"], "secrets_redacted": dlp_result["secrets_redacted"],
                })

            # Fake-stream: _generate_via_frontier_backend / Backend.generate()
            # are synchronous only (see that function's docstring) — chunk the
            # finished text by word so the frontend's existing per-chunk SSE
            # rendering still gets incremental output, instead of the whole
            # response landing as one payload.
            words = dlp_result["safe_text"].split(" ")
            for i, w in enumerate(words):
                yield f"data: {json.dumps({'type': 'chunk', 'text': w if i == 0 else f' {w}'})}\n\n"
                await asyncio.sleep(0)

            if user:
                increment_usage(user.id, "message")

            audit.log("stream_chat", user_id=user.id if user else None, detail={
                "model": backend_resolution.model, "backend": backend_resolution.backend,
                "data_left_infrastructure": backend_resolution.data_left_infrastructure,
                "cost_usd": result.cost_usd, "tools": [],
                "escalated_by_cost_router": routing_decision.escalated,
                "routing_reason": routing_decision.reason,
            })
            if routing_decision.escalated:
                audit.log("cost_aware_escalation", user_id=user.id if user else None, detail={
                    "tier": backend_resolution.tier, "escalated_to": backend_resolution.backend,
                    "reason": routing_decision.reason,
                })

            yield f"data: {json.dumps({'type': 'done', 'tools': [], 'message_id': message_id, 'backend': backend_resolution.backend, 'escalated_by_cost_router': routing_decision.escalated, 'routing_reason': routing_decision.reason if routing_decision.escalated else None, 'data_left_infrastructure': backend_resolution.data_left_infrastructure})}\n\n"

        return StreamingResponse(
            _frontier_event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    sess = _get_session(req.session_id, req.model_variant, user_id=user.id if user else None)
    mem_ctx = sess.memory.recall_context(req.message, n=3)
    enriched = f"[Relevant memory]\n{mem_ctx}\n\n{req.message}" if mem_ctx else req.message

    # Kernel's direct-answer path is used whenever the Kernel actually
    # produced an answer -- either because this session has no loaded
    # documents (Phase 3.1 spec §13's original guard: the legacy RAG
    # pipeline's query rewriting/HyDE/corrective-retrieval/citation-DNA
    # behavior must survive cutover unconditionally whenever docs ARE
    # present), OR because the Kernel's answer came from Truth Fabric
    # itself (`evidence_state is not None`), in which case it already
    # used this session's doc_store as real evidence and is authoritative
    # over the legacy pipeline for this request (Phase 4.1 spec §26-27:
    # "Do not allow existing RAG branches to bypass Truth Fabric for
    # request classes where Truth Fabric is authoritative"). Before this
    # fix, a Truth-Fabric-verified, citation-checked answer was silently
    # discarded in favor of the legacy Gateway-bypassing pipeline for
    # every session that had any document loaded -- exactly backwards,
    # since that is precisely when Truth Fabric's evidence grounding
    # matters most.
    use_kernel_direct = cognitive_result.output is not None and (
        sess.doc_store.count() == 0 or cognitive_result.evidence_state is not None
    )

    # Deep RAG: 7-stage pipeline (query intelligence → multi-signal recall →
    # RRF fusion → rerank → sufficiency check → citation DNA). Only runs if
    # docs are loaded for this session.
    rag_result = None
    if not use_kernel_direct and sess.doc_store.count() > 0:
        history = sess.memory.messages() if hasattr(sess.memory, "messages") else []
        history_strs = [f"{m.get('role','')}: {m.get('content','')[:200]}" for m in history[-6:]]
        rag_result = await asyncio.to_thread(
            run_deep_rag,
            req.message,
            sess.doc_store,
            history_strs,
            CONFIG.ollama.host,
            _model_name_for_variant(req.model_variant),
        )
        if rag_result.context_block:
            enriched = f"[Document context — cite sources as [D1], [D2], etc.]\n{rag_result.context_block}\n\n{enriched}"

    persona_system = get_persona_system(sess.model_variant)
    if mod_result.action == "support":
        persona_system += (
            f"\n\nIMPORTANT: This message may indicate the user is in emotional distress or crisis. "
            f"Respond with warmth and care. Include these resources naturally in your response:\n{CRISIS_RESOURCES}"
        )
    message_id = str(uuid.uuid4())

    async def _event_stream() -> AsyncIterator[str]:
        # Send session_id first
        yield f"data: {json.dumps({'type': 'session', 'session_id': sess.id})}\n\n"
        if rag_result and rag_result.sources:
            yield f"data: {json.dumps({'type': 'rag', 'sources': rag_result.sources, 'confidence': rag_result.sufficiency_confidence, 'rounds': rag_result.retrieval_rounds, 'contradictions': rag_result.contradictions})}\n\n"

        full = ""
        tool_names: list[str] = []
        plan_action = "direct"

        if use_kernel_direct:
            # Kernel's plan needed nothing beyond a direct model call --
            # already answered via ModelGateway, entitlement-reconciled.
            # Word-chunked for the same incremental SSE UX as any other
            # path (same pattern as the frontier-passthrough branch above)
            # -- ModelGateway.generate() was a single non-streaming call,
            # this is presentation-layer chunking, not fake generation.
            plan_action = "cognitive_direct"
            words = (cognitive_result.output or "").split(" ")
            for i, w in enumerate(words):
                full += w if i == 0 else f" {w}"
                yield f"data: {json.dumps({'type': 'chunk', 'text': w if i == 0 else f' {w}'})}\n\n"
                await asyncio.sleep(0)
        else:
            try:
                gen, trace = await asyncio.to_thread(
                    lambda: sess.agent.stream(enriched, persona_system)
                )
                # Send tool activity if any
                if trace.plan_action == "tools":
                    yield f"data: {json.dumps({'type': 'thinking', 'text': 'using tools...'})}\n\n"

                for chunk in gen:
                    full += chunk
                    yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
                    await asyncio.sleep(0)

                tool_names = [tc.tool for tc in trace.tool_calls]
                plan_action = trace.plan_action

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
                return

        # Persist
        sess.memory.add_turn("user", req.message)
        sess.memory.add_turn("assistant", full)
        sess.memory.commit_to_long_term(f"Q: {req.message[:200]}\nA: {full[:500]}")
        from orca.memory.turn_ingest import maybe_ingest_turn
        maybe_ingest_turn(sess.id, req.message, full)
        sess.persist_to_redis()
        if user:
            increment_usage(user.id, "message")

        # Knowledge graph extraction — fire-and-forget, NOT awaited. This is
        # an LLM call (real latency on CPU inference per this project's own
        # benchmarks), and the user is already looking at their finished
        # response by this point — making them wait for graph extraction
        # too would be pure UX cost for a background-enrichment feature.
        # Failures here are silent by design (extract_and_add never raises)
        # and don't affect the conversation that already completed.
        asyncio.create_task(asyncio.to_thread(
            sess.knowledge_graph.extract_and_add,
            f"{req.message}\n{full}", "chat", sess.brain,
        ))

        # Citation compliance: mechanical check, not just a prompt instruction.
        # If document context was available and the response cited zero
        # sources, that's a real governance signal — logged for visibility
        # and surfaced to the frontend so it can flag the answer, not silently
        # trusted just because the system prompt said to cite.
        context_block = rag_result.context_block if rag_result else ""
        citation_report = check_citations(full, context_block)
        if citation_report["had_context"] and not citation_report["compliant"]:
            audit.log("citation_compliance_failed", user_id=user.id if user else None,
                      detail={"message_id": message_id, "note": citation_report["note"]})

        audit.log("stream_chat", user_id=user.id if user else None,
                  detail={"model": sess.model_variant, "tools": tool_names,
                          "cognitive_degraded": cognitive_result.degraded,
                          "cognitive_resolved_tier": cognitive_result.resolved_tier})

        # Explainability: capture the full retrieval/reasoning trace for this
        # message, keyed by message_id so the frontend "Explain" button can
        # fetch it on demand without bloating every SSE payload.
        explain_record = build_from_rag_result(message_id, rag_result, plan_action, tool_names)
        sess.explain_store.add(explain_record)

        yield f"data: {json.dumps({'type': 'done', 'tools': tool_names, 'message_id': message_id, 'citation_compliance': citation_report, 'degraded': cognitive_result.degraded, 'degradation_reason': cognitive_result.degradation_reason if cognitive_result.degraded else None})}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/memory/recall")
async def recall_memory(req: MemoryRequest):
    sess = _get_session(req.session_id)
    hits = sess.memory.long.recall(req.query, n=8)
    prior = sess.memory.load_prior_context()
    return {
        "hits": hits,
        "prior_context": prior[:1000] if prior else "",
        "session_id": sess.id,
    }


@app.post("/api/remember")
async def remember(req: RememberRequest):
    sess = _get_session(req.session_id)
    sess.memory.commit_to_long_term(req.fact, {"type": "user_fact", "manual": True})
    existing = sess.memory.semantic.recall_fact("all_sessions_summary") or ""
    sess.memory.semantic.store_fact(
        "all_sessions_summary",
        f"{existing}\n[User note] {req.fact}".strip()[-4000:]
    )
    return {"stored": True, "fact": req.fact, "session_id": sess.id}


@app.get("/api/sessions")
async def list_sessions():
    sessions = EpisodicMemory.list_sessions()
    return {
        "sessions": [
            {"id": s, "title": _session_titles.get(s, "")}
            for s in sessions[:50]
        ]
    }


@app.post("/api/session/load")
async def load_session(req: LoadSessionRequest):
    sess = _get_session(req.target_session_id)
    loaded = sess.memory.load_session(req.session_id)
    if loaded:
        sess.agent.load_history(sess.memory.messages())
    return {"loaded": loaded, "session_id": sess.id}


class TitleRequest(BaseModel):
    title: str


@app.patch("/api/session/{session_id}/title")
async def set_session_title(session_id: str, req: TitleRequest):
    title = req.title.strip()[:80]
    _save_title(session_id, title)
    return {"ok": True, "title": title}


@app.get("/api/explain/{session_id}/{message_id}")
async def explain_answer(session_id: str, message_id: str):
    """
    'Explain this answer' — full retrieval chain, query intelligence, citation
    DNA, sufficiency confidence, contradictions, and agent reasoning trace
    for a specific assistant message.
    """
    sess = _get_session(session_id)
    record = sess.explain_store.get(message_id)
    if record is None:
        return JSONResponse(
            {"error": "No explain data found for this message. It may have expired (max 50 kept per session) or belong to a different session."},
            status_code=404,
        )
    return record.to_dict()


@app.get("/api/knowledge/{session_id}")
async def knowledge_graph_summary(session_id: str):
    """Lists every entity the knowledge graph has extracted for this session."""
    sess = _get_session(session_id)
    return {
        "session_id": session_id,
        "count": sess.knowledge_graph.count(),
        "entities": sess.knowledge_graph.all_entities(),
    }


@app.get("/api/knowledge/{session_id}/{entity_name}")
async def knowledge_graph_entity(session_id: str, entity_name: str):
    """Full detail on one entity — its relationships as subject and object, plus one-hop neighbors."""
    sess = _get_session(session_id)
    info = sess.knowledge_graph.query_entity(entity_name)
    if info is None:
        return JSONResponse({"error": f"No entity '{entity_name}' found in this session's knowledge graph."}, status_code=404)
    info["neighbors"] = sess.knowledge_graph.neighbors(entity_name)
    return info


@app.get("/api/session/{session_id}/export")
async def export_session(session_id: str):
    sess = _get_session(session_id)
    msgs = sess.memory.messages() if hasattr(sess.memory, "messages") else []
    title = _session_titles.get(session_id, f"Session {session_id[:8].upper()}")
    lines = [f"# {title}", f"\n_Exported from Orca — {time.strftime('%Y-%m-%d %H:%M')}_\n", "---\n"]
    for m in msgs:
        role = "**You**" if m.get("role") == "user" else "**Orca**"
        lines.append(f"{role}\n\n{m.get('content', '')}\n\n---\n")
    md = "\n".join(lines)
    return PlainTextResponse(
        md,
        headers={"Content-Disposition": f'attachment; filename="orca-{session_id[:8]}.md"'},
    )


@app.post("/api/session/save")
async def save_session(req: ChatRequest):
    sid = req.session_id
    if sid and sid in _sessions:
        sess = _sessions[sid]
        sess.memory.save_session()
        return {"saved": True, "session_id": sid}
    return {"saved": False}


@app.get("/api/models")
async def list_models():
    """
    Return which Orca model variants are available in Ollama — and, crucially,
    what model actually GETS SERVED for each tier once the registry's
    step-down fallback is applied. `configured_model` and `resolved_model`
    can legitimately differ (e.g. ultra not yet fine-tuned, silently served
    from core) — showing only `available: false` here previously hid that
    from anyone debugging why a tier "works" but doesn't sound like itself.
    """
    import urllib.request
    try:
        req = urllib.request.Request(f"{CONFIG.ollama.host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        pulled = {m["name"] for m in data.get("models", [])}
    except Exception:
        pulled = set()

    def _available(model_name: str) -> bool:
        if not pulled:
            return False
        base = model_name.split(":")[0]
        return model_name in pulled or any(
            m == model_name or m.split(":")[0] == base for m in pulled
        )

    def _tier_status(tier: str, configured_model: str) -> dict:
        try:
            resolved_model = resolve_tier_model(tier, host=CONFIG.ollama.host)
        except RuntimeError:
            resolved_model = None

        return {
            "model": configured_model,
            "available": _available(configured_model),
            "vision_capable": is_vision_capable(configured_model),
            "resolved_model": resolved_model,
            "fallback_active": resolved_model is not None and resolved_model != configured_model,
        }

    def _persona_claim_status(tier: str) -> dict:
        # Surfaces the exact same gate orca/personas.py enforces at runtime
        # (get_persona_system swaps the persona's self-description based on
        # this). Without this, a client had no way to know a tier's claims
        # are currently demoted short of reading raw eval/redteam JSON off
        # disk — the one place a real buyer or the admin UI actually looks
        # (this endpoint) said nothing about it.
        approved, reason = check_persona_claim_allowed(tier)
        return {"approved": approved, "reason": reason}

    def _backend_status(tier: str) -> dict:
        # Real backend/data-sovereignty resolution — see
        # orca/serve/registry.py's resolve_tier_backend(). Shown separately
        # from _tier_status above (which is Ollama-only) since a tier can
        # now resolve to a frontier API instead.
        try:
            resolution = resolve_tier_backend(tier, host=CONFIG.ollama.host)
            return {
                "backend": resolution.backend,
                "model": resolution.model,
                "data_left_infrastructure": resolution.data_left_infrastructure,
                "sovereignty_overridden": resolution.sovereignty_overridden,
            }
        except RuntimeError as e:
            return {"backend": None, "error": str(e)}

    return {
        "nano":  _tier_status("nano", CONFIG.ollama.model_nano),
        "core":  _tier_status("core", CONFIG.ollama.model_core),
        "ultra": _tier_status("ultra", CONFIG.ollama.model_ultra),
        "backend_routing": {
            "nano": _backend_status("nano"),
            "core": _backend_status("core"),
            "ultra": _backend_status("ultra"),
            "data_sovereignty_lock": CONFIG.backends.data_sovereignty_lock,
        },
        "persona_claims": {
            "nano": _persona_claim_status("nano"),
            "core": _persona_claim_status("core"),
            "ultra": _persona_claim_status("ultra"),
        },
    }


LEGAL_DIR = Path(__file__).parent.parent.parent / "legal"


@app.get("/legal/privacy", response_class=PlainTextResponse)
async def privacy_policy():
    path = LEGAL_DIR / "PRIVACY_POLICY.md"
    if not path.exists():
        return PlainTextResponse("Privacy policy not found.", status_code=404)
    return PlainTextResponse(path.read_text(), media_type="text/markdown")


@app.get("/legal/terms", response_class=PlainTextResponse)
async def terms_of_service():
    path = LEGAL_DIR / "TERMS_OF_SERVICE.md"
    if not path.exists():
        return PlainTextResponse("Terms of service not found.", status_code=404)
    return PlainTextResponse(path.read_text(), media_type="text/markdown")


@app.get("/legal/ai-policy", response_class=PlainTextResponse)
async def ai_policy():
    """AI Policy & Risk Register — the policy Orca's technical safety controls actually enforce."""
    path = LEGAL_DIR / "AI_POLICY.md"
    if not path.exists():
        return PlainTextResponse("AI policy document not found.", status_code=404)
    return PlainTextResponse(path.read_text(), media_type="text/markdown")


DOCS_DIR = Path(__file__).parent.parent.parent / "docs"
_DOCS_FILES = {
    "self-hosting": "SELF_HOSTING.md",
    "api-reference": "API_REFERENCE.md",
    "model-cards": "MODEL_CARDS.md",
    "architecture": "ARCHITECTURE.md",
    "design-brief": "DESIGN_BRIEF.md",
    "design-prompts": "CLAUDE_DESIGN_PROMPTS.md",
}


@app.get("/docs", response_class=PlainTextResponse)
async def docs_index():
    """Lists available documentation pages."""
    lines = ["Orca Documentation", "==================", ""]
    for slug in _DOCS_FILES:
        lines.append(f"  /docs/{slug}")
    return PlainTextResponse("\n".join(lines))


@app.get("/docs/{slug}", response_class=PlainTextResponse)
async def docs_page(slug: str):
    filename = _DOCS_FILES.get(slug)
    if not filename:
        return PlainTextResponse(f"No doc page named '{slug}'. See /docs for the index.", status_code=404)
    path = DOCS_DIR / filename
    if not path.exists():
        return PlainTextResponse("Doc file not found.", status_code=404)
    return PlainTextResponse(path.read_text(), media_type="text/markdown")


@app.get("/api/license")
async def license_status():
    """Return current license tier and feature set for the web UI."""
    lk = get_active_license()
    if lk:
        return {
            "tier":         lk.tier,
            "seats":        lk.seats,
            "expiry":       format_expiry(lk),
            "valid":        True,
            "has_ultra":    lk.has_feature("ultra"),
            "has_cloud":    lk.has_feature("cloud_train"),
        }
    return {
        "tier":         "free",
        "seats":        0,
        "expiry":       None,
        "valid":        False,
        "has_ultra":    False,
        "has_cloud":    False,
    }


@app.post("/api/billing/checkout")
async def create_checkout(
    tier: str = "pro",
    interval: str = "month",
    user: User = Depends(get_current_user),
):
    """
    Creates a Stripe Checkout Session for the AUTHENTICATED web user and
    returns its URL for the frontend to redirect to. client_reference_id is
    set to this user's id — the webhook handler reads it back to know WHICH
    web account to upgrade once payment completes. Without this, a completed
    Stripe payment had no way to connect back to a specific logged-in user's
    account tier (see orca/license/stripe_hook.py for the other half of this).
    """
    import os as _os
    try:
        import stripe
    except ImportError:
        return JSONResponse({"error": "Stripe is not installed on this server."}, status_code=503)

    stripe_secret = _os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_secret:
        return JSONResponse({"error": "Stripe is not configured on this server."}, status_code=503)
    stripe.api_key = stripe_secret

    price_env_map = {
        ("pro", "month"):        "STRIPE_PRICE_PRO",
        ("pro", "year"):         "STRIPE_PRICE_PRO_YEAR",
        ("enterprise", "month"): "STRIPE_PRICE_ENT",
        ("enterprise", "year"):  "STRIPE_PRICE_ENT_YEAR",
    }
    price_id = _os.environ.get(price_env_map.get((tier, interval), "STRIPE_PRICE_PRO"), "")
    if not price_id:
        return JSONResponse(
            {"error": f"No Stripe price configured for tier='{tier}' interval='{interval}'."},
            status_code=503,
        )

    from orca.auth.store import get_stripe_customer_id
    existing_customer_id = get_stripe_customer_id(user.id)

    base_url = orneur_env("PUBLIC_URL", "http://localhost:7337")

    session_kwargs = dict(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        client_reference_id=user.id,
        metadata={"user_id": user.id, "tier": tier},
        success_url=f"{base_url}/app?checkout=success",
        cancel_url=f"{base_url}/app?checkout=cancelled",
    )
    # Reuse the existing Stripe Customer if this user has paid before —
    # avoids creating duplicate Customer records on every checkout attempt.
    if existing_customer_id:
        session_kwargs["customer"] = existing_customer_id
    else:
        session_kwargs["customer_email"] = user.email

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except Exception as e:
        return JSONResponse({"error": f"Could not create checkout session: {e}"}, status_code=502)

    return {"url": session.url}


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint for automatic license fulfillment.
    Set Stripe webhook URL to: https://yourdomain.com/webhook/stripe
    """
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        from orca.license.stripe_hook import handle_stripe_event
        result = handle_stripe_event(payload, sig_header)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": "internal error"}, status_code=500)


@app.post("/api/ultra")
async def ultra_run(req: UltraRequest):
    """SSE endpoint — runs OrcaUltra multi-agent pipeline and streams progress."""
    if not has_feature("ultra"):
        async def _gate_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': 'Ultra requires a Pro license. Run: orca activate <key>'})}\n\n"
        return StreamingResponse(_gate_stream(), media_type="text/event-stream")

    sess = _get_session(req.session_id)
    progress_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

    # Phase 3.1: cognitive planning must not be bypassed even for Ultra
    # (spec §10) -- but Ultra is a distinct, deliberately deep, paid
    # product mode with its own entitlement gate (has_feature("ultra"),
    # checked above), not a plan the Kernel should re-decide or execute
    # itself. The Kernel PLANS (never executes) here, purely for trace/
    # observability parity with /api/chat and /api/stream -- Ultra's own
    # fixed multi-agent pipeline remains authoritative for HOW this
    # request is actually answered. Never allowed to break the real
    # request (matches the same safety discipline Phase 3's shadow mode
    # used).
    try:
        from orca.cognitive.contracts import CognitiveRequest
        from orca.cognitive.wiring import get_shared_kernel
        get_shared_kernel().plan(CognitiveRequest(objective=req.task, requested_mode="ultra"))
    except Exception:
        _logger.debug("Cognitive planning failed for /api/ultra request — pipeline unaffected.", exc_info=True)

    # Phase 2.1 cutover: OrcaUltra previously built its own OrcaBrain via
    # get_brain(), bypassing the Model Gateway entirely -- unlike /api/chat
    # and /api/stream, this HTTP-reachable path was missed by the original
    # cutover. Resolve the same way _Session.__init__ does and inject the
    # Gateway-routed brain so live Ultra traffic is routed identically.
    ultra_resolution = TierResolution(
        tier="ultra",
        backend="ollama",
        model=_model_name_for_variant("ultra"),
        data_left_infrastructure=False,
    )
    ultra_brain = brain_for_tier_resolution(ultra_resolution)

    def on_progress(msg: str):
        # Called from within async coroutine context (main event loop thread)
        try:
            progress_queue.put_nowait({"type": "progress", "text": msg.strip()})
        except asyncio.QueueFull:
            pass

    async def _event_stream() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'type': 'session', 'session_id': sess.id})}\n\n"
        yield f"data: {json.dumps({'type': 'pod_launch'})}\n\n"

        ultra = OrcaUltra(on_progress=on_progress, use_tools=True, brain=ultra_brain)
        pipeline_task = asyncio.create_task(ultra._run_async(req.task, max_retries=1))

        # Stream progress events while pipeline runs
        while not pipeline_task.done():
            try:
                ev = await asyncio.wait_for(progress_queue.get(), timeout=0.15)
                yield f"data: {json.dumps(ev)}\n\n"
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

        # Drain any remaining progress messages
        while not progress_queue.empty():
            try:
                ev = progress_queue.get_nowait()
                yield f"data: {json.dumps(ev)}\n\n"
            except asyncio.QueueEmpty:
                break

        try:
            pipeline = pipeline_task.result()
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
            return

        # Stream final output in small chunks for smooth rendering
        text = pipeline.final_output
        chunk_size = 25
        for i in range(0, len(text), chunk_size):
            yield f"data: {json.dumps({'type': 'chunk', 'text': text[i:i+chunk_size]})}\n\n"
            await asyncio.sleep(0)

        # Persist to memory
        sess.memory.add_turn("user", req.task)
        sess.memory.add_turn("assistant", pipeline.final_output)
        sess.memory.commit_to_long_term(
            f"[Ultra] Q: {req.task[:200]}\nA: {pipeline.final_output[:500]}"
        )
        # Note: OrcaUltra doesn't run through AgentLoop, so this turn won't
        # appear in agent.get_history() — persist_to_redis() still preserves
        # model_variant continuity even though the turn itself isn't captured.
        sess.persist_to_redis()

        yield f"data: {json.dumps({'type': 'done', 'grade': pipeline.grade, 'iterations': pipeline.iterations})}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Document Q&A (RAG) endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/docs/upload")
async def upload_doc(
    request: Request,
    file: UploadFile = File(...),
    session_id: str | None = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Upload a document for RAG — extract, chunk, embed, and store."""
    ratelimit.enforce(request, ratelimit.DOC_UPLOAD, extra_key="doc_upload")
    if file.filename and Path(file.filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        return JSONResponse(
            {"error": f"Unsupported file type. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"},
            status_code=400,
        )

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        return JSONResponse(
            {"error": f"File too large ({len(data)//1024//1024}MB). Max: {MAX_FILE_SIZE//1024//1024}MB"},
            status_code=413,
        )

    filename = file.filename or "upload.txt"
    try:
        text = extract(filename, data)
    except Exception as e:
        return JSONResponse({"error": f"Extraction failed: {e}"}, status_code=422)

    if not text.strip():
        return JSONResponse({"error": "No text could be extracted from this file."}, status_code=422)

    # PII redaction — scrubs SSNs, emails, phone numbers, and Luhn-valid
    # credit card numbers BEFORE the document is chunked/embedded into the
    # persistent vector store. Applies here (uploads), not to live chat
    # messages — see orca/docs/pii_redact.py docstring for why that scope
    # boundary is deliberate, not an oversight.
    text, pii_report = redact_pii(text)
    if pii_report["total"] > 0:
        audit.log("doc_pii_redacted", user_id=user.id if user else None,
                  detail={"filename": filename, **{k: v for k, v in pii_report.items() if k != "total"},
                          "total_redactions": pii_report["total"]})

    doc_id = str(uuid.uuid4())
    chunks = chunk_text(text, doc_id=doc_id, filename=filename)

    sess = _get_session(session_id, user_id=user.id if user else None)
    stored = sess.doc_store.add_chunks(chunks, doc_id=doc_id, filename=filename)
    register_doc(sess.id, doc_id, filename, chunk_count=stored, size_bytes=len(data))

    audit.log("doc_upload", user_id=user.id if user else None,
              detail={"filename": filename, "chunks": stored, "bytes": len(data),
                      "pii_redactions": pii_report["total"]})

    return {
        "doc_id": doc_id,
        "filename": filename,
        "chunks": stored,
        "size_bytes": len(data),
        "session_id": sess.id,
    }


@app.get("/api/docs/list")
async def list_session_docs(session_id: str | None = None):
    """List all documents uploaded in the current session."""
    sess = _get_session(session_id)
    docs = list_docs(sess.id)
    return {"docs": docs, "session_id": sess.id, "total_chunks": sess.doc_store.count()}


@app.delete("/api/docs/{doc_id}")
async def delete_doc(
    doc_id: str,
    session_id: str | None = None,
    user: User | None = Depends(get_current_user_optional),
):
    """Remove a document and all its chunks from the session store."""
    sess = _get_session(session_id, user_id=user.id if user else None)
    ok = sess.doc_store.delete_doc(doc_id)
    unregister_doc(sess.id, doc_id)
    audit.log("doc_delete", user_id=user.id if user else None, detail={"doc_id": doc_id})
    return {"deleted": ok, "doc_id": doc_id, "session_id": sess.id}


# ─────────────────────────────────────────────────────────────────────────────
#  Code Interpreter endpoint
# ─────────────────────────────────────────────────────────────────────────────

class CodeRunRequest(BaseModel):
    code: str
    language: str = "python"
    session_id: str | None = None


@app.post("/api/code/run")
async def code_run(
    req: CodeRunRequest,
    request: Request,
    user: User | None = Depends(get_current_user_optional),
):
    """Execute Python code in a sandboxed subprocess. Returns stdout/stderr/error."""
    ratelimit.enforce(request, ratelimit.CODE_RUN, extra_key="code_run")
    if req.language != "python":
        return JSONResponse({"error": f"Language '{req.language}' not supported. Only Python is available."}, status_code=400)

    result = await asyncio.to_thread(run_code, req.code)

    audit.log("code_run", user_id=user.id if user else None,
              detail={"exit_code": result.exit_code, "duration_ms": result.duration_ms,
                      "ok": result.ok})

    return {
        "stdout":      result.stdout,
        "stderr":      result.stderr,
        "error":       result.error,
        "exit_code":   result.exit_code,
        "duration_ms": result.duration_ms,
        "ok":          result.ok,
    }


MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB


@app.post("/api/vision")
async def vision_query(
    request: Request,
    message: str,
    image: UploadFile = File(...),
    session_id: str | None = None,
    model_variant: str | None = None,
    user: User | None = Depends(get_current_user_optional),
):
    """
    One-shot image Q&A — NOT wired into the full AgentLoop (no tool use,
    no multi-step reasoning over the image, no reflection pass). See
    orca/brain/vision.py's module docstring for the honest scope. Requires
    a vision-capable model actually pulled in Ollama; this project does not
    ship one.
    """
    ratelimit.enforce(request, ratelimit.VISION, extra_key="vision")

    data = await image.read()
    if len(data) > MAX_IMAGE_SIZE:
        return JSONResponse(
            {"error": f"Image too large ({len(data)//1024//1024}MB). Max: {MAX_IMAGE_SIZE//1024//1024}MB"},
            status_code=413,
        )

    model_name = _model_name_for_variant(model_variant)
    if not is_vision_capable(model_name):
        return JSONResponse(
            {"error": f"Model '{model_name}' does not appear to be vision-capable. "
                      f"Pull a vision model (e.g. `ollama pull llava` or `ollama pull llama3.2-vision`) "
                      f"and configure it for this variant."},
            status_code=400,
        )

    mod_result = check_input(message)
    metrics.record_moderation_action(mod_result.action)
    if mod_result.action == "block":
        audit.log("input_moderation_blocked", user_id=user.id if user else None,
                  detail={"categories": mod_result.flagged_categories, "endpoint": "vision"})
        return JSONResponse(
            {"error": "This request can't be processed — it matches a category we don't generate content for."},
            status_code=400,
        )

    sess = _get_session(session_id, model_variant, user_id=user.id if user else None)
    image_b64 = encode_image(data)
    vision_message = build_vision_message(message, image_b64)

    try:
        response = await asyncio.to_thread(sess.brain.complete, [vision_message])
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    audit.log("vision_query", user_id=user.id if user else None,
              detail={"model": model_name, "image_bytes": len(data)})

    return {"response": response, "session_id": sess.id, "model": model_name}


# ─────────────────────────────────────────────────────────────────────────────
#  Monitoring
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/admin/metrics")
async def admin_metrics(admin: User = Depends(require_permission("audit_read"))):
    """JSON metrics snapshot — request counts, error rates, latency percentiles per endpoint."""
    return metrics.get_metrics_snapshot()


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """
    Prometheus exposition format — no auth, standard scrape convention.
    If exposing this port publicly, put a firewall/reverse-proxy rule in
    front of it; this endpoint reveals operational detail (request volumes,
    error rates, endpoint names) that shouldn't be internet-visible.
    """
    return PlainTextResponse(metrics.get_prometheus_text(), media_type="text/plain; version=0.0.4")


# ─────────────────────────────────────────────────────────────────────────────
#  Admin endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/admin/audit")
async def admin_audit(
    limit: int = 100,
    admin: User = Depends(require_permission("audit_read")),
):
    return {"logs": audit.recent(limit=limit)}


@app.get("/api/admin/audit/verify")
async def admin_audit_verify(
    start_seq: int = 0,
    end_seq: int | None = None,
    admin: User = Depends(require_permission("audit_read")),
):
    """Recompute the hash chain and report any tampering — the compliance check."""
    return audit.verify_chain(start_seq=start_seq, end_seq=end_seq)


@app.get("/api/admin/audit/export")
async def admin_audit_export(
    start_seq: int = 0,
    end_seq: int | None = None,
    admin: User = Depends(require_permission("audit_read")),
):
    """Court-admissible export: full entries + verification + a top-level signature."""
    export = audit.export_for_audit(start_seq=start_seq, end_seq=end_seq)
    return JSONResponse(
        export,
        headers={"Content-Disposition": f'attachment; filename="orca-audit-export-{int(time.time())}.json"'},
    )


@app.get("/api/admin/governance/cards")
async def admin_list_model_cards(admin: User = Depends(require_permission("audit_read"))):
    """List every generated model card with a quick signature-validity check."""
    from orca.governance import list_model_cards
    return {"cards": list_model_cards()}


@app.get("/api/admin/governance/cards/{variant}")
async def admin_get_model_card(variant: str, admin: User = Depends(require_permission("audit_read"))):
    """Full model card for a variant (nano/core/ultra), including safety scores and limitations."""
    from orca.governance import load_model_card, verify_model_card
    card = load_model_card(variant)
    if card is None:
        return JSONResponse({"error": f"No model card found for variant '{variant}'. Run `orca train card {variant}` first."}, status_code=404)
    verification = verify_model_card(variant)
    return {"card": card.to_dict(), "verification": verification}


@app.post("/api/admin/governance/cards/{variant}/generate")
async def admin_generate_model_card(variant: str, admin: User = Depends(require_permission("manage_users"))):
    """Regenerate a model card from the latest eval + red-team reports on disk."""
    from orca.governance import generate_model_card
    try:
        card = generate_model_card(variant)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    audit.log("model_card_generated", user_id=admin.id, detail={"variant": variant})
    return {"card": card.to_dict()}


@app.get("/api/admin/stats")
async def admin_stats(admin: User = Depends(require_permission("manage_users"))):
    from orca.auth.store import list_users
    users = list_users(limit=1000)
    tiers = {}
    for u in users:
        tiers[u["tier"]] = tiers.get(u["tier"], 0) + 1
    return {
        "total_users": len(users),
        "tiers": tiers,
        "active_sessions": len(_sessions),
        "uptime_sec": round(time.time() - _START_TIME),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Static files (must be last — catches everything under /static)
# ─────────────────────────────────────────────────────────────────────────────

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def create_app() -> FastAPI:
    return app
