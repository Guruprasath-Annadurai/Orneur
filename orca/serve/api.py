"""
Orneur Web Server — FastAPI backend for the browser UI.

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
import hmac
import contextlib
import json
import re
import logging
import os
import time
import uuid
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Phase 14A.3/14A.4: mandatory startup configuration validation MUST run
# before any `orca.*` import that could transitively connect to a
# database -- `orca.auth` (imported below) pulls in `orca.auth.db`,
# whose `init_db()` runs UNCONDITIONALLY at that module's own import
# time and would otherwise raise its own uncontrolled
# psycopg/sqlite3 exception (potentially with connection details in
# the message) before this clean, secret-free check ever got a chance
# to run. `orca.godmode.deployment_profile` itself only depends on
# `orca.config` (no database connection), so importing and calling it
# FIRST is safe regardless of profile/configuration validity.
from orca.godmode.deployment_profile import validate_deployment_config as _validate_deployment_config
_validate_deployment_config()

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
from orca.gateway.wiring import brain_for_tier_resolution, public_serving_decision
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
from orca.serve.errors import public_error, coded_error, default_code_for_status
from orca.serve.model_identity import model_identity as _model_identity
from orca.serve.citations import build_sources as _build_sources
from orca.serve import streaming
from orca.serve.streaming import aiter_blocking
from orca.serve.moderation import check_input, CRISIS_RESOURCES
from orca.code import run_code

_START_TIME = time.time()
WEB_DIR = Path(__file__).parent / "web"
_logger = logging.getLogger("orca.serve")

_RETENTION_INTERVAL_S = 6 * 3600


async def _retention_loop():
    """Workstream B: honour each user's conversation-retention setting. Never lets one failure stop the loop or the server."""
    from orca.serve.retention import purge_expired_conversations

    while True:
        try:
            await asyncio.to_thread(purge_expired_conversations)
        except Exception:
            _logger.debug("retention purge failed", exc_info=True)
        await asyncio.sleep(_RETENTION_INTERVAL_S)


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    _retention_task = asyncio.create_task(_retention_loop())
    try:
        yield
    finally:
        _retention_task.cancel()
    # Clean shutdown for the bounded streaming worker pool (DEF-CP1-01).
    # wait=False: blocking the event loop here to join every worker would
    # itself hang shutdown behind a slow backend call -- the same class of
    # problem this pool exists to avoid. Workers finish their current
    # next()/close naturally; new submissions after this point raise, which
    # aiter_blocking surfaces as an ordinary stream error to any request
    # still in flight.
    streaming.shutdown_streaming_pool(wait=False)


app = FastAPI(title="ORNEUR API", version="1.0.0", docs_url=None, redoc_url=None, lifespan=_lifespan)


def _is_public_edge() -> bool:
    """`ORNEUR_PUBLIC_EDGE=1`: set on any deployment that is (or will
    be) reachable through a public edge (Cloudflare Tunnel, a public
    load balancer, etc.) -- distinct from `ORNEUR_DEPLOYMENT_PROFILE`
    (DISTRIBUTED/SOVEREIGN), which is about the authority/DB backend,
    not public HTTP reachability. Phase 14B ran DISTRIBUTED entirely
    privately with no public edge at all, so the two flags are
    deliberately independent."""
    return orneur_env("PUBLIC_EDGE", "").strip().lower() in ("1", "true", "yes")


def _validate_startup_config() -> None:
    """Workstream A: refuse to boot a production-like deployment with a forgeable or unsafe configuration (see orca/serve/config_validation.py)."""
    from orca.serve.config_validation import validate_production_config

    for f in validate_production_config():
        _logger.warning("config %s: %s %s", f.severity, f.code, f.message) if f.severity == "WARN" else None


_validate_startup_config()


def _allowed_origins() -> list[str]:
    """`ORNEUR_ALLOWED_ORIGINS`: comma-separated explicit origin
    allowlist. Unset/empty defaults to `["*"]` -- unchanged for every
    existing local/self-hosted/private-staging deployment (this
    codebase's zero-config default). Phase 14C spec Step 7: a wildcard
    is forbidden once `ORNEUR_PUBLIC_EDGE` is set -- fails closed at
    import time (same pattern as `deployment_profile.validate_deployment_config()`)
    rather than silently serving a publicly-reachable deployment with
    an open CORS policy."""
    raw = orneur_env("ALLOWED_ORIGINS", "*").strip()
    if not raw or raw == "*":
        if _is_public_edge():
            raise RuntimeError(
                "ORNEUR_PUBLIC_EDGE is set but ORNEUR_ALLOWED_ORIGINS is unset/wildcard -- "
                "refusing to start with an open CORS policy on a publicly-reachable deployment. "
                "Set ORNEUR_ALLOWED_ORIGINS to an explicit, comma-separated origin list."
            )
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def _trusted_hosts() -> list[str]:
    """`ORNEUR_TRUSTED_HOSTS`: comma-separated allowed Host header
    values (e.g. `staging.orneur.com`). Unset/empty defaults to `["*"]`
    -- unchanged for every existing local/self-hosted deployment.
    Phase 14C spec Step 9: reject arbitrary Host header abuse once a
    real public hostname is known, while never breaking Northflank's
    own internal liveness probe (which connects via `localhost`/the
    pod's own address, not the public hostname) -- `localhost`/
    `127.0.0.1` are always included alongside whatever is configured,
    specifically so tightening this can never break `/livez`."""
    raw = orneur_env("TRUSTED_HOSTS", "").strip()
    if not raw:
        return ["*"]
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    for always in ("localhost", "127.0.0.1"):
        if always not in hosts:
            hosts.append(always)
    return hosts


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts())


MAX_REQUEST_BODY_BYTES = int(orneur_env("MAX_REQUEST_BODY_BYTES", str(30 * 1024 * 1024)))  # 30MB default


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Phase 14C spec Step 22: safe-by-default browser security headers.
    Deliberately conservative -- no CSP (would require auditing every
    inline script/style in orca/serve/web first, out of scope here) and
    no frame-ancestors/X-Frame-Options DENY (the `/app` UI may need to
    remain embeddable in contexts not yet audited); HSTS is only added
    when the request actually arrived over HTTPS (or is marked as such
    by a trusted proxy's X-Forwarded-Proto), never unconditionally, so
    a local plain-HTTP dev server is never told to force HTTPS on
    itself."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


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


class _BodySizeLimitExceeded(Exception):
    """Internal signal only -- never leaks past RequestBodySizeLimitMiddleware."""


class RequestBodySizeLimitMiddleware:
    """Phase 14C spec Step 17, closing a real gap found in the first
    version of this control: a Content-Length PRE-CHECK (the previous
    `request_size_limit_middleware`) only catches a request that
    honestly reports its size upfront -- it does nothing for chunked
    transfer-encoding (no Content-Length header at all) or a request
    that lies about a smaller Content-Length than it actually sends.
    Either way, a route with no body-size ceiling of its own (chat,
    memory, code/run, ...) could still have its FULL oversized body
    read into memory before any per-route validation ran.

    This is a pure ASGI middleware (not `@app.middleware("http")`/
    BaseHTTPMiddleware) so it can wrap the raw `receive` callable
    directly and count bytes as they actually arrive on the wire,
    regardless of what the client claims. Registered via
    `app.add_middleware()` AFTER every other middleware in this file
    (Starlette wraps in reverse registration order -- the LAST
    `add_middleware`/`@app.middleware("http")` call ends up OUTERMOST,
    confirmed by reading `Starlette.build_middleware_stack()`), so this
    is the very first thing that sees each incoming byte and the very
    last thing that sees each outgoing one -- nothing downstream (CORS,
    TrustedHost, the other `@app.middleware("http")` functions, FastAPI's
    own body parsing, a route handler's manual `await request.body()`)
    can ever see more than `max_bytes` of body, chunked or not.

    Still a fast Content-Length pre-check first (rejects an honest
    oversized request before reading anything at all); the streaming
    counter is the real backstop for everyone else.
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass

        total = 0
        response_started = False

        async def counting_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise _BodySizeLimitExceeded()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodySizeLimitExceeded:
            if not response_started:
                await self._reject(scope, receive, send)
            # else: downstream already started sending a response before
            # the overflow was detected -- too late to swap it for a 413
            # without corrupting the response; the connection simply
            # ends here rather than risk sending a malformed response.

    async def _reject(self, scope, receive, send):
        response = JSONResponse(
            {"error": f"Request body too large. Max: {self.max_bytes // 1024 // 1024}MB"},
            status_code=413,
        )
        await response(scope, receive, send)


app.add_middleware(RequestBodySizeLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)


app.include_router(auth_router)
from orca.sovereign_mission.routes import router as sovereign_router  # noqa: E402

app.include_router(sovereign_router)
from orca.serve.document_routes import router as document_router  # noqa: E402
from orca.specialists.routes import router as specialist_router  # noqa: E402

app.include_router(document_router)
app.include_router(specialist_router)


# G-023: every HTTPException / validation failure also carries a stable machine-readable `code` and an `error_id`, in the same shape the chat routes use.
# `detail` is kept exactly as before so existing clients keep working.
from fastapi.exceptions import RequestValidationError  # noqa: E402
from starlette.exceptions import HTTPException as _StarletteHTTPException  # noqa: E402


@app.exception_handler(_StarletteHTTPException)
async def _http_exception_with_code(request: Request, exc: _StarletteHTTPException):
    detail = exc.detail
    code = default_code_for_status(exc.status_code)
    message = detail if isinstance(detail, str) else "Request failed."
    if isinstance(detail, dict):
        code = detail.get("code", code)
        message = detail.get("error", message)
    body = {"detail": detail, "error": message, "code": code, "error_id": uuid.uuid4().hex[:12]}
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def _unhandled_with_code(request: Request, exc: Exception):
    """Last resort: a stable code and a correlation id, never the exception text."""
    e = public_error(exc, route=request.url.path, code="internal_error", message="Something went wrong on our side. Please try again.")
    return JSONResponse(e.as_json(), status_code=500)


@app.exception_handler(RequestValidationError)
async def _validation_error_with_code(request: Request, exc: RequestValidationError):
    from fastapi.encoders import jsonable_encoder
    body = {"detail": jsonable_encoder(exc.errors()), "error": "The request was not valid.", "code": "invalid_request", "error_id": uuid.uuid4().hex[:12]}
    return JSONResponse(body, status_code=422)


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


def _resolve_model_with_fallback(variant: str | None) -> tuple[str, str | None]:
    """Like `_model_name_for_variant`, but also returns the model that was asked for when the registry had to fall back (None otherwise) -- G-015."""
    seen: dict = {}

    def _on_fallback(requested_tier: str, requested_model: str, resolved_model: str) -> None:
        seen["from"] = requested_model
        _logger.warning("Tier '%s' requested model '%s' which is not installed in Ollama -- falling back to '%s'.", requested_tier, requested_model, resolved_model)
        metrics.record_registry_fallback(requested_tier, resolved_model)

    return resolve_tier_model(variant or "core", on_fallback=_on_fallback), seen.get("from")


def _identity_for_frontier(requested_variant, resolution, routing_decision, user) -> dict:
    reason = "cost_routing_escalation" if routing_decision.escalated else ("sovereignty_override" if getattr(resolution, "sovereignty_overridden", False) else None)
    return _model_identity(requested_variant=requested_variant, served_tier=resolution.tier, served_model=resolution.model, backend=resolution.backend,
                           reason=reason, viewer_user_id=user.id if user else None, data_left_infrastructure=resolution.data_left_infrastructure)


def _identity_for_ollama(requested_variant, sess, cognitive_result, user, *, kernel_answered: bool) -> dict:
    """What actually generated the text. If the Kernel answered directly, that is the Kernel's resolved tier/model (which may be smaller than requested);
    otherwise it is the session's own tier/model."""
    uid = user.id if user else None
    if kernel_answered:
        return _model_identity(requested_variant=requested_variant, served_tier=cognitive_result.resolved_tier, served_model=cognitive_result.resolved_model,
                               reason="entitlement_limit" if cognitive_result.degraded else None, viewer_user_id=uid)
    return _model_identity(requested_variant=requested_variant, served_tier=getattr(sess, "model_variant", None), served_model=getattr(sess, "served_model", None), fallback_from=getattr(sess, "fallback_from", None),
                           viewer_user_id=uid)


def _persist_turn(user, session_id: str, user_text: str, assistant_text: str, *, identity=None, src=None, message_id=None) -> None:
    """Workstream B: durable, append-only transcript for SIGNED-IN users (anonymous sessions are not persisted). Best-effort: history must never fail a request."""
    if not user or not session_id:
        return
    try:
        from orca.serve import conversations

        conversations.append(session_id, "user", user_text)
        meta: dict = {}
        if identity:
            meta["model_identity"] = identity
        if src:
            meta["source_summary"] = src["summary"]
            meta["sources"] = [{k: s.get(k) for k in ("ref", "kind", "filename", "url", "locator", "cited_in_answer")} for s in src["sources"]]
        if message_id:
            meta["message_id"] = message_id
        conversations.append(session_id, "assistant", assistant_text, meta=meta or None)
    except Exception:
        _logger.debug("conversation persistence failed", exc_info=True)


def _authorize_inference(user, model_variant, message, *, route: str, quota_kind: str = "message"):
    """The single authorization every inference-spending route applies BEFORE any model, session cost or tool is touched: per-user quota, per-user plan gate
    for the requested tier, and input moderation. Returns a `PublicError` to refuse, or None to proceed.

    Workstream A: /api/ultra relied only on the SERVER's licence tier and /api/vision had no gate at all, so an anonymous caller could spend the most
    expensive tier (or unmetered vision) on any licensed instance. A structural test (`tests/test_a_serving_authorization.py`) fails if a new inference route
    skips this helper."""
    if user:
        allowed, used, limit = check_quota(user.id, user.tier, quota_kind)
        if not allowed:
            return coded_error("quota_exceeded", message=f"Daily limit reached ({used}/{limit}). Upgrade to Pro for unlimited use.", used=used, limit=limit)
    model_allowed, model_reason = model_access_allowed(user, model_variant)
    if not model_allowed:
        return coded_error("model_access_denied", message=model_reason)
    mod_result = check_input(message)
    metrics.record_moderation_action(mod_result.action)
    if mod_result.action == "block":
        audit.log("input_moderation_blocked", user_id=user.id if user else None, detail={"categories": mod_result.flagged_categories, "endpoint": route})
        return coded_error("content_refused")
    if mod_result.action in ("support", "flag"):
        audit.log(f"input_moderation_{mod_result.action}", user_id=user.id if user else None, detail={"categories": mod_result.flagged_categories, "endpoint": route})
    return None


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
        f"{resolution.backend}'s {resolution.model} model via API, not an Orneur-trained model. "
        f"Orneur's own eval/red-team gating does not apply to a model Orneur did not train — "
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
    def __init__(self, session_id: str, model_variant: str | None = None, user_id: str | None = None):
        self.id = session_id
        # Who this session serves: public-experiment eligibility is per user (orca/gateway/serving_authority.py).
        self.user_id = user_id

        # Cross-instance continuity: if Redis has this session's state (from
        # this or another API instance), restore the exact conversation
        # history instead of starting cold. An explicit model_variant from
        # the caller wins over the persisted one (user actively switching
        # models mid-conversation should be respected); Redis only fills in
        # when the caller didn't specify (session_id known, variant omitted).
        redis_state = session_store.load_session_state(session_id)
        self._restored_history = None
        if redis_state:
            model_variant = model_variant or redis_state.get("model_variant")
            self._restored_history = redis_state.get("history")

        self.model_variant = model_variant or "core"
        self.memory = MemoryEngine(session_id=session_id)
        # Brain/agent/ctx resolution is LAZY -- see _ensure_agent() below.
        # Phase 14C edge-qualification finding: doc upload/list/delete,
        # memory recall/remember, knowledge graph, explain, and session
        # export never touch the model at all, but used to pay for (and
        # hard-fail on) a full tier/backend resolution anyway just because
        # they went through _get_session(). model_runtime being
        # unavailable is an expected, documented deployment state (see
        # /readyz) -- a doc-only route shouldn't 500 because of it. Only
        # chat/stream/ultra/session-load/vision actually need a brain, so
        # those are the only paths that trigger resolution now, via the
        # `agent`/`brain`/`ctx` properties.
        self._brain = None
        self._ctx = None
        self._agent = None
        self.served_model: str | None = None
        self.fallback_from: str | None = None
        self.doc_store = DocStore(session_id=session_id, ollama_host=CONFIG.ollama.host)
        self.explain_store = ExplainStore()
        self.knowledge_graph = KnowledgeGraph(session_id=session_id)
        self.last_active = time.time()

    def _ensure_agent(self):
        if self._agent is not None:
            return
        # Cut over to the Model Gateway (Phase 2.1) -- GatewayBrain is a
        # drop-in replacement for OrcaBrain's exact interface, so nothing
        # below this line (ContextManager, AgentLoop, tools, memory) needed
        # to change. See docs/orneur/phase-2/LIVE_SERVING_CUTOVER.md.
        served_model, fallback_from = _resolve_model_with_fallback(self.model_variant)
        self.served_model, self.fallback_from = served_model, fallback_from      # G-015: remembered so responses can say what served them
        tier_resolution = TierResolution(
            tier=(self.model_variant or "core").removeprefix("orca-"),
            backend="ollama",
            model=served_model,
            data_left_infrastructure=False,
        )
        brain = brain_for_tier_resolution(tier_resolution, viewer_user_id=self.user_id)
        self._ctx = ContextManager(brain)
        tools = build_registry(memory_engine=self.memory, surface="web")  # G-020: no shell/file/exec tools on the web
        self._agent = AgentLoop(brain=brain, tools=tools, session_id=self.id)
        self._brain = brain

        if self._restored_history:
            self._agent.load_history(self._restored_history)
        else:
            # Fallback: no exact turn history available (fresh session, or
            # Redis disabled/empty) — reconstruct rough context from the
            # long-term summary store instead. Less precise than Redis's
            # exact history, only used when that's unavailable.
            prior = self.memory.load_prior_context()
            if prior:
                self._agent.load_history([
                    {"role": "user", "content": f"[Prior context]\n{prior}"},
                    {"role": "assistant", "content": "Context loaded."},
                ])

    @property
    def agent(self):
        self._ensure_agent()
        return self._agent

    @property
    def brain(self):
        self._ensure_agent()
        return self._brain

    @property
    def ctx(self):
        self._ensure_agent()
        return self._ctx

    def touch(self):
        self.last_active = time.time()

    def persist_to_redis(self):
        """Save current conversation history so any instance can pick this session back up."""
        session_store.save_session_state(self.id, self.model_variant, self.agent.get_history())


_sessions: dict[str, _Session] = {}


_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_session_id(session_id: str | None) -> None:
    """G-006: a caller-supplied session id becomes a file name
    (episodes/<id>.json, knowledge/<id>.json), a database key and a storage
    prefix. Anything outside ``[A-Za-z0-9_-]{1,64}`` (``../``, separators,
    NULs, megabyte strings, markup that the web client interpolates into
    attributes) is refused before it can reach any of them. The server's own
    ids are UUIDs and always pass."""
    if session_id and not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=422, detail="invalid session id")


def _check_session_ownership(session_id: str | None, user_id: str | None) -> None:
    """The raise-only half of `_get_session()`'s access check, exposed
    separately so a route needing to check a session it is NOT about to
    construct/touch (e.g. `load_session()`'s SOURCE `req.session_id`) can do
    so without eagerly constructing a full `_Session` for a request that is
    about to be denied anyway. Denies (404, never 403 -- an unauthorized
    caller must not be able to confirm the session exists) when another user
    owns it, when an anonymous caller names an owned session, or when the id
    shares a storage prefix with a different claimed session."""
    if not session_id:
        return
    _validate_session_id(session_id)
    from orca.auth.store import check_session_access
    if not check_session_access(session_id, user_id):
        raise HTTPException(status_code=404, detail="session not found")


def _get_session(session_id: str | None, model_variant: str | None = None, user_id: str | None = None) -> _Session:
    """Phase 14C edge-qualification finding, fixed centrally here rather
    than per-route: a CALLER-SUPPLIED `session_id` (never a freshly
    generated one -- `session_id is None` always means "give me a new
    session", never an ownership question) that was previously recorded
    as belonging to a signed-in user may only be read back by that SAME
    user_id. Every route that reaches a session through this function
    gets this protection uniformly.

    G-006: the check and the ownership record are ONE atomic
    ``claim_session()`` (two workers can no longer both "see it unowned" and
    both become owner), the id is validated before it touches any path, and
    sessions whose ids collide on the 8-character storage prefix used by
    long-term memory / semantic facts / the document store are refused
    instead of silently sharing data. A session with NO recorded owner
    (created anonymously) stays reachable by anyone who holds its id -- the
    session_id itself remains its own shareable credential. Raises
    `HTTPException(404)` (never 403) so an unauthorized caller cannot even
    confirm the session exists."""
    from orca.auth.store import claim_session

    _validate_session_id(session_id)
    if session_id:
        if not claim_session(session_id, user_id):
            raise HTTPException(status_code=404, detail="session not found")
        sid = session_id
    else:
        for _ in range(5):  # a fresh uuid4 colliding on 8 chars is ~1e-9 per session at 10k sessions
            sid = str(uuid.uuid4())
            if claim_session(sid, user_id):
                break
        else:
            raise HTTPException(status_code=503, detail="could not allocate a session")

    if sid not in _sessions:
        _sessions[sid] = _Session(sid, model_variant, user_id=user_id)
    _sessions[sid].touch()
    session_store.touch_session(sid)  # refresh Redis TTL — no-op if Redis disabled

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
    return HTMLResponse("<h1>Orneur landing page not found</h1>")


@app.get("/app", response_class=HTMLResponse)
async def serve_ui():
    index = WEB_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>Orneur UI not found</h1><p>Run: orneur serve</p>")


@app.get("/trust", response_class=HTMLResponse)
async def serve_trust():
    trust = WEB_DIR / "trust.html"
    if trust.exists():
        return HTMLResponse(trust.read_text())
    return HTMLResponse("<h1>Orneur trust page not found</h1>")


def _brand_asset(role: str) -> Optional[Path]:
    """Founder-approved brand file for ``role`` (see web/brand/ASSETS.json), or None."""
    try:
        doc = json.loads((WEB_DIR / "brand" / "ASSETS.json").read_text(encoding="utf-8"))
        for a in doc["assets"]:
            if a["role"] == role:
                return WEB_DIR / "brand" / a["file"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def _brand_response(role: str, media_type: str):
    path = _brand_asset(role)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    # Stable URLs browsers request unprompted: always revalidate, so a replaced icon is never served stale.
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    return _brand_response("favicon_ico", "image/x-icon")


@app.get("/apple-touch-icon.png", include_in_schema=False)
async def serve_apple_touch_icon():
    return _brand_response("apple_touch_icon", "image/png")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def serve_web_manifest():
    icons = []
    for role, size in (("pwa_192", "192x192"), ("pwa_512", "512x512")):
        path = _brand_asset(role)
        if path is not None:
            icons.append({"src": f"/static/brand/{path.name}", "sizes": size, "type": "image/png", "purpose": "any"})
    return JSONResponse(
        {"name": "ORNEUR", "short_name": "ORNEUR", "start_url": "/app", "scope": "/", "display": "standalone",
         "background_color": "#03050A", "theme_color": "#03050A", "icons": icons},
        media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


@app.get("/livez")
async def livez():
    """
    Phase 14 §18-19: LIVENESS only -- "is this process alive?" Answers in
    microseconds, does no I/O, calls no dependency (Ollama, gateway,
    authority store, disk). A liveness probe exists so an orchestrator
    (k8s, etc.) can decide "this process is wedged, restart it" -- it
    must never itself perform the expensive check that would make a slow
    DEPENDENCY (not a wedged process) look like a reason to kill and
    restart an otherwise-healthy worker. That confusion is exactly what
    Phase 14's audit found: both livenessProbe and readinessProbe in the
    existing k8s manifest pointed at the same endpoint (see
    docs/orneur/phase-14/CURRENT_DEPLOYMENT_ARCHITECTURE.md's "Health
    endpoints" finding) -- this endpoint and /readyz below are the fix.
    """
    return {"status": "alive", "pid": os.getpid()}


@app.get("/readyz")
async def readyz():
    """
    Phase 14 §20-22: READINESS -- "can this worker safely serve the
    claimed model / claimed capabilities right now?" Unlike /livez, this
    DOES check dependencies, each reported separately (spec §21:
    "Track dependencies separately... Do not mark entire service healthy
    when a critical required dependency is down"), and applies the
    fail-closed/fail-soft matrix from
    docs/orneur/phase-14/HEALTH_AND_READINESS.md: the model runtime and
    Godmode authority store are REQUIRED (their failure -> 503, not
    ready); the gateway's own health report and connector state are
    reported but do not by themselves flip readiness to false, since
    normal (non-elevated) requests do not depend on them.
    """
    dependencies: dict[str, dict] = {}
    ready = True

    try:
        resolved = resolve_tier_model("nano", host=CONFIG.ollama.host)
        dependencies["model_runtime"] = {"status": "ok", "nano_model": resolved}
    except RuntimeError as e:
        dependencies["model_runtime"] = {"status": "unavailable", "reason": str(e)}
        ready = False  # REQUIRED dependency -- fail closed, per spec §21-22

    try:
        from orca.godmode.lease_store import _backend  # noqa: PLC0415 -- see api.py's existing lazy-import convention below
        dependencies["authority_store"] = {"status": "ok", "backend": _backend()}
    except Exception as e:
        # The authority store being unreachable does not mean ORDINARY
        # (non-elevated) requests can't be served -- spec §22/§53: "Godmode
        # store unavailable -> elevated actions DENY. Normal operations
        # continue where safe." So this is reported, but does not flip
        # `ready` to False by itself; individual elevated-action call
        # sites already fail closed on their own (AuthorityStoreUnavailableError).
        dependencies["authority_store"] = {"status": "error", "reason": str(e)}

    try:
        from orca.gateway.wiring import get_shared_gateway
        dependencies["gateway"] = get_shared_gateway().report_health()
    except Exception as e:
        dependencies["gateway"] = {"error": str(e)}

    # Phase 14A.3 §7: in DISTRIBUTED profile specifically, an
    # unavailable/misconfigured security root is NOT the same lenient
    # case as SOVEREIGN's authority_store above -- it means this worker
    # cannot safely serve elevated-capability requests to a shared
    # security authority at all, which is exactly the "no silent
    # fallback" configuration gate this phase closed. SOVEREIGN is
    # deliberately NOT held to this stricter standard here (its
    # authority store being down is the existing, softer,
    # non-gating case above).
    try:
        from orca.godmode.deployment_profile import is_distributed
        if is_distributed():
            from orca.godmode.security_root import get_epoch_and_state
            epoch, state = get_epoch_and_state()
            if state == "UNKNOWN":
                dependencies["security_root"] = {"status": "unavailable"}
                ready = False  # never advertise READY while distributed security authority is unavailable
            else:
                dependencies["security_root"] = {"status": "ok", "epoch": epoch}
    except Exception as e:
        dependencies["security_root"] = {"status": "error", "reason": str(e)}
        ready = False

    # Phase 14A.4 §7: same stricter-than-SOVEREIGN treatment for the
    # core auth/session/audit backend -- a DISTRIBUTED worker whose
    # shared core database is unreachable cannot guarantee session/
    # auth correctness (spec §7: "Do not return fully READY when
    # session/auth correctness cannot be guaranteed"), so this flips
    # overall readiness the same way an unavailable security root does.
    # A lightweight `SELECT 1` is enough to prove connectivity without
    # adding real load to a low-frequency probe endpoint.
    try:
        from orca.godmode.deployment_profile import is_distributed
        if is_distributed():
            from orca.auth.db import get_conn
            with get_conn() as conn:
                conn.execute("SELECT 1")
            dependencies["core_database"] = {"status": "ok"}
    except Exception as e:
        dependencies["core_database"] = {"status": "unavailable", "reason": str(e)}
        ready = False  # never advertise READY while session/auth correctness cannot be guaranteed

    status_code = 200 if ready else 503
    return JSONResponse({"status": "ready" if ready else "not_ready", "dependencies": dependencies}, status_code=status_code)


@app.get("/healthz")
async def healthz():
    """
    Preserved EXACTLY as before Phase 14 -- same response shape
    (`status`/`nano_model`/`gateway` at the top level), same existing
    test contract (tests/test_healthz_endpoint.py,
    tests/test_healthz_gateway_readiness.py). Phase 14 §18 requires that
    liveness and readiness EXIST as separate concepts, not that this
    already-established endpoint's shape be broken for existing callers
    in the same change -- /livez and /readyz above are the new,
    recommended entry points (see the updated k8s/deployment.yaml); this
    one is kept, unmodified, for backward compatibility.
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
            e = coded_error("quota_exceeded", message=f"Daily limit reached ({used}/{limit}). Upgrade to Pro for unlimited messages.", used=used, limit=limit)
            return JSONResponse(e.as_json(), status_code=e.status)

    mod_result = check_input(req.objective)
    metrics.record_moderation_action(mod_result.action)
    if mod_result.action == "block":
        audit.log("input_moderation_blocked", user_id=user.id if user else None,
                  detail={"categories": mod_result.flagged_categories, "endpoint": "cognitive_execute"})
        e = coded_error("content_refused")
        return JSONResponse(e.as_json(), status_code=e.status)

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
    """Chat. A signed-in client may send `Idempotency-Key` (8-128 chars of [A-Za-z0-9_-]): the same key + same payload replays the stored answer without a second
    model call or quota charge (`Idempotent-Replay: true`); the same key with a different payload is 422; a concurrent duplicate is 409."""
    key = request.headers.get("idempotency-key")
    if key is None or user is None:
        return await _chat_impl(req, request, user)
    from orca.serve import idempotency

    if not idempotency.valid_key(key):
        e = coded_error("invalid_request", message="Idempotency-Key must be 8-128 characters of letters, digits, '-' or '_'.")
        return JSONResponse(e.as_json(), status_code=e.status)
    state, cached = idempotency.begin(user.id, key, idempotency.request_hash(req.model_dump()))
    if state == "done":
        return JSONResponse(cached, headers={"Idempotent-Replay": "true"})
    if state == "in_progress":
        e = coded_error("conflict", message="A request with this Idempotency-Key is still being processed.")
        return JSONResponse(e.as_json(), status_code=e.status)
    if state == "mismatch":
        e = coded_error("invalid_request", message="This Idempotency-Key was already used with a different request.")
        return JSONResponse(e.as_json(), status_code=e.status)
    try:
        result = await _chat_impl(req, request, user)
    except BaseException:
        idempotency.abort(user.id, key)
        raise
    if isinstance(result, dict):
        idempotency.complete(user.id, key, result)
    else:
        idempotency.abort(user.id, key)                      # errors are not cached: a retry is a real retry
    return result


async def _chat_impl(
    req: ChatRequest,
    request: Request,
    user: User | None,
):
    # IP-based floor applies regardless of auth status — the per-user tier
    # quota below only ever ran `if user:`, leaving anonymous requests with
    # zero limit. This closes that gap; authenticated users still also get
    # their tier quota checked right after.
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="chat")

    # Generation requests (image/video) short-circuit here, before any
    # text-tier quota/model-access check — Genesis/Novus/Aeternum never see
    # these messages at all. Orneur Lens's actual generation backend isn't
    # built yet (pending model choice), so this is an honest "not yet
    # available" response, not a silent fallthrough to the text models.
    gen_intent = detect_generation_intent(req.message)
    if gen_intent != "chat":
        audit.log("lens_generation_requested", user_id=user.id if user else None,
                  detail={"intent": gen_intent})
        return JSONResponse(
            {"error": f"Orneur Lens ({gen_intent} generation) isn't available yet — coming soon.",
             "intent": gen_intent},
            status_code=501,
        )

    if user:
        allowed, used, limit = check_quota(user.id, user.tier, "message")
        if not allowed:
            e = coded_error("quota_exceeded", message=f"Daily limit reached ({used}/{limit}). Upgrade to Pro for unlimited messages.", used=used, limit=limit)
            return JSONResponse(e.as_json(), status_code=e.status)

    model_allowed, model_reason = model_access_allowed(user, req.model_variant)
    if not model_allowed:
        e = coded_error("model_access_denied", message=model_reason)
        return JSONResponse(e.as_json(), status_code=e.status)

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
        e = coded_error("content_refused")
        return JSONResponse(e.as_json(), status_code=e.status)
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
        e2 = public_error(e, route="/api/chat", user_id=user.id if user else None)
        return JSONResponse(e2.as_json(), status_code=500)

    if cognitive_result.status == CognitiveState.ABSTAINED:
        audit.log("cognitive_abstained", user_id=user.id if user else None, detail={
            "reason": cognitive_result.abstention_reason.value if cognitive_result.abstention_reason else None,
        })
        reason_key = cognitive_result.abstention_reason.value if cognitive_result.abstention_reason else ""
        e = coded_error("request_abstained", message=_ABSTENTION_MESSAGES.get(reason_key, "This request can't be completed."), abstained=True,
                        reason=(reason_key or "UNSPECIFIED").lower())
        return JSONResponse(e.as_json(), status_code=e.status)

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
            _err = public_error(e, route="/api/chat", user_id=user.id if user else None)
            return JSONResponse(_err.as_json(), status_code=503 if _err.code == "model_unavailable" else 500)

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

        _fsid = req.session_id or str(uuid.uuid4())
        _fident = _identity_for_frontier(req.model_variant, backend_resolution, routing_decision, user)
        _persist_turn(user, _fsid, req.message, dlp_result["safe_text"], identity=_fident)
        return {
            "response": dlp_result["safe_text"],
            "session_id": _fsid,
            "used_tools": [],
            "plan": "frontier_passthrough",
            "model_identity": _fident,
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
    # G-024: same rule as /api/stream. The Kernel's no-retrieval direct answer is used only if this session has no documents, or the Kernel itself
    # grounded the answer in them (Truth Fabric). Otherwise the uploaded documents go through the deep-RAG pipeline and into the model's context --
    # they used to be silently ignored on this route unless the wording happened to trigger retrieval.
    kernel_answered = cognitive_result.output is not None and (sess.doc_store.count() == 0 or cognitive_result.evidence_state is not None)
    rag_result = None
    if not kernel_answered and sess.doc_store.count() > 0:
        history = sess.memory.messages() if hasattr(sess.memory, "messages") else []
        history_strs = [f"{m.get('role','')}: {m.get('content','')[:200]}" for m in history[-6:]]
        try:
            rag_result = await asyncio.to_thread(
                run_deep_rag, req.message, sess.doc_store, history_strs, CONFIG.ollama.host, _model_name_for_variant(req.model_variant),
            )
        except Exception as e:
            # Never answer as if the uploaded documents had been consulted when retrieval failed.
            _err = public_error(e, route="/api/chat", user_id=user.id if user else None)
            return JSONResponse(_err.as_json(), status_code=503 if _err.code == "model_unavailable" else 500)
        if rag_result.context_block:
            enriched = f"[Document context — cite sources as [D1], [D2], etc.]\n{rag_result.context_block}\n\n{enriched}"
    if kernel_answered:
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
            _err = public_error(e, route="/api/chat", user_id=user.id if user else None)
            return JSONResponse(_err.as_json(), status_code=503 if _err.code == "model_unavailable" else 500)
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

    _src = _build_sources(answer=final, session_id=sess.id, rag_result=rag_result,
                          evidence_state=cognitive_result.evidence_state if kernel_answered else None,
                          citation_coverage=cognitive_result.citation_coverage if kernel_answered else None,
                          evidence_passages=cognitive_result.evidence_passages if kernel_answered else None)
    _ident = _identity_for_ollama(req.model_variant, sess, cognitive_result, user, kernel_answered=kernel_answered)
    _persist_turn(user, sess.id, req.message, dlp_result["safe_text"], identity=_ident, src=_src)
    return {
        "response": dlp_result["safe_text"],
        "session_id": sess.id,
        "used_tools": used_tools,
        "plan": plan_action,
        "model_identity": _ident,
        "source_summary": _src["summary"],
        "sources": _src["sources"],
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
        _lens_msg = f"Orneur Lens ({gen_intent} generation) isn't available yet — coming soon."
        async def _lens_not_available():
            yield f"data: {json.dumps({'type': 'error', 'text': _lens_msg, 'intent': gen_intent})}\n\n"
        return StreamingResponse(_lens_not_available(), media_type="text/event-stream")

    if user:
        allowed, used, limit = check_quota(user.id, user.tier, "message")
        if not allowed:
            _q = coded_error("quota_exceeded", message=f"Daily limit reached ({used}/{limit}). Upgrade to Pro.", used=used, limit=limit)
            async def _quota_err():
                yield f"data: {json.dumps(_q.as_sse())}\n\n"
            return StreamingResponse(_quota_err(), media_type="text/event-stream")

    model_allowed, model_reason = model_access_allowed(user, req.model_variant)
    if not model_allowed:
        _g = coded_error("model_access_denied", message=model_reason)
        async def _model_gate_err():
            yield f"data: {json.dumps(_g.as_sse())}\n\n"
        return StreamingResponse(_model_gate_err(), media_type="text/event-stream")

    mod_result = check_input(req.message)
    metrics.record_moderation_action(mod_result.action)
    if mod_result.action == "block":
        audit.log("input_moderation_blocked", user_id=user.id if user else None,
                  detail={"categories": mod_result.flagged_categories})
        _m = coded_error("content_refused")
        async def _mod_block():
            yield f"data: {json.dumps(_m.as_sse())}\n\n"
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
        _f = public_error(e, route="/api/stream", user_id=user.id if user else None)
        async def _fail_stream():
            yield f"data: {json.dumps(_f.as_sse())}\n\n"
        return StreamingResponse(_fail_stream(), media_type="text/event-stream")

    if cognitive_result.status == CognitiveState.ABSTAINED:
        audit.log("cognitive_abstained", user_id=user.id if user else None, detail={
            "reason": cognitive_result.abstention_reason.value if cognitive_result.abstention_reason else None,
        })
        reason_key = cognitive_result.abstention_reason.value if cognitive_result.abstention_reason else ""
        _a = coded_error("request_abstained", message=_ABSTENTION_MESSAGES.get(reason_key, "This request can't be completed."), abstained=True,
                         reason=(reason_key or "UNSPECIFIED").lower())
        async def _abstain_stream():
            yield f"data: {json.dumps(_a.as_sse())}\n\n"
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
            yield f"data: {json.dumps({'type': 'model', 'identity': _identity_for_frontier(req.model_variant, backend_resolution, routing_decision, user)})}\n\n"
            yield f"data: {json.dumps({'type': 'thinking', 'text': f'escalating to {backend_resolution.backend}...'})}\n\n"

            try:
                result = await asyncio.to_thread(
                    _generate_via_frontier_backend, backend_resolution, persona_system, req.message
                )
            except Exception as e:
                yield f"data: {json.dumps(public_error(e, route='/api/stream', user_id=user.id if user else None).as_sse())}\n\n"
                return

            dlp_result = dlp.scan_output(result.text)
            if dlp_result["has_findings"]:
                audit.log("output_dlp_finding", user_id=user.id if user else None, detail={
                    "pii_flagged": dlp_result["pii_flagged"], "secrets_redacted": dlp_result["secrets_redacted"],
                })

            # G-026: _generate_via_frontier_backend / Backend.generate() are synchronous -- the whole answer already exists. It used to be cut into
            # words and re-emitted with a sleep(0) between them, which LOOKED like token streaming. It is now delivered once and labelled as replayed.
            yield f"data: {json.dumps({'type': 'stream', 'delivery': 'replayed', 'cancellable': False})}\n\n"
            yield f"data: {json.dumps({'type': 'chunk', 'text': dlp_result['safe_text'], 'replayed': True})}\n\n"
            _persist_turn(user, session_id, req.message, dlp_result["safe_text"], identity=_identity_for_frontier(req.model_variant, backend_resolution, routing_decision, user), message_id=message_id)

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

            yield f"data: {json.dumps({'type': 'done', 'tools': [], 'message_id': message_id, 'backend': backend_resolution.backend, 'escalated_by_cost_router': routing_decision.escalated, 'routing_reason': routing_decision.reason if routing_decision.escalated else None, 'data_left_infrastructure': backend_resolution.data_left_infrastructure, 'delivery': 'replayed', 'model_identity': _identity_for_frontier(req.model_variant, backend_resolution, routing_decision, user)})}\n\n"

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
        identity = _identity_for_ollama(req.model_variant, sess, cognitive_result, user, kernel_answered=use_kernel_direct)
        yield f"data: {json.dumps({'type': 'model', 'identity': identity})}\n\n"
        if rag_result and rag_result.sources:
            yield f"data: {json.dumps({'type': 'rag', 'sources': rag_result.sources, 'confidence': rag_result.sufficiency_confidence, 'rounds': rag_result.retrieval_rounds, 'contradictions': rag_result.contradictions})}\n\n"

        full = ""
        tool_names: list[str] = []
        plan_action = "direct"
        delivery = "upstream"

        if use_kernel_direct:
            # Kernel's plan needed nothing beyond a direct model call --
            # already answered via ModelGateway, entitlement-reconciled.
            # Word-chunked for the same incremental SSE UX as any other
            # path (same pattern as the frontier-passthrough branch above)
            # -- ModelGateway.generate() was a single non-streaming call,
            # this is presentation-layer chunking, not fake generation.
            plan_action = "cognitive_direct"
            # G-026: the Kernel's ModelGateway call is non-streaming -- the answer is already complete here. It used to be split into words and
            # re-emitted with sleep(0) between them (presentation-layer "typing"). It is now sent once and labelled, so a client can neither mistake it
            # for live generation nor offer a "stop generating" control that would not stop anything.
            delivery = "replayed"
            full = cognitive_result.output or ""
            yield f"data: {json.dumps({'type': 'stream', 'delivery': 'replayed', 'cancellable': False})}\n\n"
            yield f"data: {json.dumps({'type': 'chunk', 'text': full, 'replayed': True})}\n\n"
        else:
            try:
                gen, trace = await asyncio.to_thread(
                    lambda: sess.agent.stream(enriched, persona_system)
                )
                # Send tool activity if any
                if trace.plan_action == "tools":
                    yield f"data: {json.dumps({'type': 'thinking', 'text': 'using tools...'})}\n\n"
                # G-026: from here chunks are forwarded as the backend produces them; closing the connection cancels the upstream generation.
                yield f"data: {json.dumps({'type': 'stream', 'delivery': 'upstream', 'cancellable': True})}\n\n"

                # contextlib.aclosing, not a bare `async for`: breaking the
                # loop below on client disconnect does not by itself call
                # aclose() on an async generator (same rule as a sync
                # generator abandoned mid-`for`) -- without this, a
                # disconnected client's backend generator is only closed
                # whenever Python eventually garbage-collects it, leaking
                # the worker thread and the backend connection until then.
                async with contextlib.aclosing(aiter_blocking(gen)) as achunks:
                    async for chunk in achunks:
                        full += chunk
                        yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
                        if await request.is_disconnected():
                            audit.log("stream_client_disconnected", user_id=user.id if user else None,
                                      detail={"chars_sent": len(full)})
                            return

                tool_names = [tc.tool for tc in trace.tool_calls]
                plan_action = trace.plan_action

            except streaming.StreamingUnavailable as e:
                err = public_error(e, route="/api/stream", user_id=user.id if user else None,
                                   code="server_busy", message="The server is at capacity. Please retry shortly.")
                yield f"data: {json.dumps(err.as_sse())}\n\n"
                return
            except Exception as e:
                yield f"data: {json.dumps(public_error(e, route='/api/stream', user_id=user.id if user else None).as_sse())}\n\n"
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
        _src = _build_sources(answer=full, session_id=sess.id, rag_result=rag_result,
                              evidence_state=cognitive_result.evidence_state if use_kernel_direct else None,
                              citation_coverage=cognitive_result.citation_coverage if use_kernel_direct else None,
                              evidence_passages=cognitive_result.evidence_passages if use_kernel_direct else None)
        _persist_turn(user, sess.id, req.message, full, identity=identity, src=_src, message_id=message_id)
        explain_record = build_from_rag_result(message_id, rag_result, plan_action, tool_names)
        sess.explain_store.add(explain_record)

        yield f"data: {json.dumps({'type': 'done', 'tools': tool_names, 'message_id': message_id, 'citation_compliance': citation_report, 'degraded': cognitive_result.degraded, 'degradation_reason': cognitive_result.degradation_reason if cognitive_result.degraded else None, 'delivery': delivery, 'model_identity': identity, 'source_summary': _src['summary'], 'sources': _src['sources']})}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/memory/recall")
async def recall_memory(req: MemoryRequest, user: User | None = Depends(get_current_user_optional)):
    sess = _get_session(req.session_id, user_id=user.id if user else None)
    hits = sess.memory.long.recall(req.query, n=8)
    prior = sess.memory.load_prior_context()
    return {
        "hits": hits,
        "prior_context": prior[:1000] if prior else "",
        "session_id": sess.id,
    }


@app.post("/api/remember")
async def remember(req: RememberRequest, user: User | None = Depends(get_current_user_optional)):
    sess = _get_session(req.session_id, user_id=user.id if user else None)
    sess.memory.commit_to_long_term(req.fact, {"type": "user_fact", "manual": True})
    # G-006: this route used to ALSO append every user's note to one global,
    # unscoped `all_sessions_summary` string. Nothing reads it any more (the
    # read path was retired in Phase 5.1), and it mixed tenants' private text
    # in a single value that account deletion did not scrub. The note is kept
    # where it belongs: this session's own long-term memory, above.
    return {"stored": True, "fact": req.fact, "session_id": sess.id}


def _anonymous_listing_allowed() -> bool:
    """Anonymous callers may list saved sessions only on a private install
    that has no accounts at all (a single-user local deployment has no
    tenants to isolate). Any public edge, or any instance with an account,
    answers anonymous callers with an empty list."""
    from orca.auth.store import _count_users
    from orca.gateway.wiring import public_edge_enabled

    return not public_edge_enabled() and _count_users() == 0


@app.get("/api/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User | None = Depends(get_current_user_optional),
):
    """Lists the CALLER's conversations, most recently active first, paginated.

    G-006: this used to return every session id and title on the server to anyone. A signed-in caller now sees their own conversations -- those with a
    durable transcript (written on every turn, no explicit save needed) plus any older explicitly saved episode -- never anyone else's."""
    from orca.serve import conversations

    saved = EpisodicMemory.list_sessions()                         # newest first by episode mtime
    if user is not None:
        from orca.auth.store import get_user_session_ids

        owned = set(get_user_session_ids(user.id))
        episode_ids = [s for s in saved if s in owned]
        activity: dict[str, float] = {}
        for sid in owned:
            ts = conversations.last_activity(sid)
            if ts is not None:
                activity[sid] = ts
        for sid in episode_ids:
            activity.setdefault(sid, 0.0)
        visible = sorted(activity, key=lambda s: activity[s], reverse=True)
    elif _anonymous_listing_allowed():
        visible = saved
        activity = {}
    else:
        visible = []
        activity = {}
    total = len(visible)
    page = visible[offset:offset + limit]
    nxt = offset + limit if offset + limit < total else None
    return {
        "sessions": [{"id": s, "title": _session_titles.get(s, ""), "updated_at": activity.get(s) or None} for s in page],
        "total": total, "limit": limit, "offset": offset, "next_offset": nxt,
    }


@app.post("/api/session/load")
async def load_session(req: LoadSessionRequest, user: User | None = Depends(get_current_user_optional)):
    uid = user.id if user else None
    _check_session_ownership(req.session_id, uid)  # SOURCE session -- checked first, before constructing anything
    sess = _get_session(req.target_session_id, user_id=uid)
    loaded = sess.memory.load_session(req.session_id)
    if loaded:
        sess.agent.load_history(sess.memory.messages())
    return {"loaded": loaded, "session_id": sess.id}


class TitleRequest(BaseModel):
    title: str


@app.patch("/api/session/{session_id}/title")
async def set_session_title(session_id: str, req: TitleRequest, user: User | None = Depends(get_current_user_optional)):
    # G-006: was unauthenticated and unscoped -- anyone could overwrite any
    # session's title (and mint new keys in the shared titles file for ids
    # that do not exist). Same access rule as every other session route, and
    # only for a session this process has actually seen or that has a saved
    # episode.
    _check_session_ownership(session_id, user.id if user else None)
    from orca.serve import conversations

    if (session_id not in _sessions and session_id not in EpisodicMemory.list_sessions()
            and conversations.last_activity(session_id) is None):
        raise HTTPException(status_code=404, detail="session not found")
    title = req.title.strip()[:80]
    if not title:
        e = coded_error("invalid_request", message="A conversation title can't be blank.")
        return JSONResponse(e.as_json(), status_code=422)
    _save_title(session_id, title)
    return {"ok": True, "title": title}


@app.get("/api/explain/{session_id}/{message_id}")
async def explain_answer(session_id: str, message_id: str, user: User | None = Depends(get_current_user_optional)):
    """
    'Explain this answer' — full retrieval chain, query intelligence, citation
    DNA, sufficiency confidence, contradictions, and agent reasoning trace
    for a specific assistant message.
    """
    sess = _get_session(session_id, user_id=user.id if user else None)
    record = sess.explain_store.get(message_id)
    if record is None:
        return JSONResponse(
            {"error": "No explain data found for this message. It may have expired (max 50 kept per session) or belong to a different session."},
            status_code=404,
        )
    return record.to_dict()


@app.get("/api/knowledge/{session_id}")
async def knowledge_graph_summary(session_id: str, user: User | None = Depends(get_current_user_optional)):
    """Lists every entity the knowledge graph has extracted for this session."""
    sess = _get_session(session_id, user_id=user.id if user else None)
    return {
        "session_id": session_id,
        "count": sess.knowledge_graph.count(),
        "entities": sess.knowledge_graph.all_entities(),
    }


@app.get("/api/knowledge/{session_id}/{entity_name}")
async def knowledge_graph_entity(session_id: str, entity_name: str, user: User | None = Depends(get_current_user_optional)):
    """Full detail on one entity — its relationships as subject and object, plus one-hop neighbors."""
    sess = _get_session(session_id, user_id=user.id if user else None)
    info = sess.knowledge_graph.query_entity(entity_name)
    if info is None:
        return JSONResponse({"error": f"No entity '{entity_name}' found in this session's knowledge graph."}, status_code=404)
    info["neighbors"] = sess.knowledge_graph.neighbors(entity_name)
    return info


def _owned_session_or_404(session_id: str, user: "User | None") -> None:
    """Read-only access decision for transcript-style routes: never claims, never creates; a foreign or unknown-to-you session is 404."""
    _check_session_ownership(session_id, user.id if user else None)


@app.get("/api/session/{session_id}/messages")
async def session_messages(session_id: str, limit: int = 200, offset: int = 0, user: User | None = Depends(get_current_user_optional)):
    """The durable transcript of one of the caller's conversations (paged). Signed-in users only; anonymous sessions are not persisted."""
    _owned_session_or_404(session_id, user)
    if user is None:
        e = coded_error("auth_required")
        return JSONResponse(e.as_json(), status_code=e.status)
    from orca.serve import conversations

    return conversations.transcript(session_id, limit=limit, offset=offset)


@app.get("/api/sessions/search")
async def search_sessions(q: str, request: Request, limit: int = 20, user: User | None = Depends(get_current_user_optional)):
    """Full-text search over the CALLER's own conversations (titles and messages). Plain substring match, never a regex. Anonymous callers get nothing."""
    if user is None:
        e = coded_error("auth_required")
        return JSONResponse(e.as_json(), status_code=e.status)
    ratelimit.enforce(request, ratelimit.CHAT_ANY, extra_key="search")
    q = (q or "").strip()
    if not (2 <= len(q) <= 200):
        e = coded_error("invalid_request", message="Search text must be 2 to 200 characters.")
        return JSONResponse(e.as_json(), status_code=e.status)
    from orca.auth.store import get_user_session_ids
    from orca.serve import conversations

    owned = get_user_session_ids(user.id)
    return await asyncio.to_thread(conversations.search, owned, _session_titles, q, limit=max(1, min(int(limit), 50)))


@app.get("/api/session/{session_id}/export")
async def export_session(session_id: str, format: str = "md", user: User | None = Depends(get_current_user_optional)):
    """Export one conversation as Markdown (default) or JSON (`?format=json`, schema orneur.conversation/1)."""
    _owned_session_or_404(session_id, user)
    title = _session_titles.get(session_id, f"Session {session_id[:8].upper()}")
    from orca.serve import conversations

    have_file = user is not None and conversations.last_activity(session_id) is not None
    if format == "json":
        if not have_file:
            return {"schema": "orneur.conversation/1", "session_id": session_id, "title": title, "total": 0, "messages": []}
        return conversations.export_json(session_id, title)
    if have_file:
        md = conversations.export_markdown(session_id, title)
    else:
        # anonymous / not-yet-persisted sessions: fall back to the live in-memory window (what the export has always shown)
        sess = _get_session(session_id, user_id=user.id if user else None)
        msgs = sess.memory.messages() if hasattr(sess.memory, "messages") else []
        lines = [f"# {title}", f"\n_Exported from ORNEUR — {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_\n", "---\n"]
        for m in msgs:
            role = "**You**" if m.get("role") == "user" else "**ORNEUR**"
            lines.append(f"{role}\n\n{m.get('content', '')}\n\n---\n")
        md = "\n".join(lines)
    return PlainTextResponse(md, headers={"Content-Disposition": f'attachment; filename="orneur-{session_id[:8]}.md"'})


@app.delete("/api/session/{session_id}")
async def delete_conversation(session_id: str, user: User | None = Depends(get_current_user_optional)):
    """Delete ONE of the caller's conversations and everything scoped to it (transcript, memory, documents, knowledge graph, titles). Owner only."""
    if user is None:
        e = coded_error("auth_required")
        return JSONResponse(e.as_json(), status_code=e.status)
    _owned_session_or_404(session_id, user)
    from orca.auth.store import get_user_session_ids, release_session
    from orca.serve.account_delete import _delete_session_data, _remove_session_title

    if session_id not in set(get_user_session_ids(user.id)):
        raise HTTPException(status_code=404, detail="session not found")      # nothing of yours by that id (an unclaimed id is not yours to delete)
    result = await asyncio.to_thread(_delete_session_data, session_id)
    _remove_session_title(session_id)
    _sessions.pop(session_id, None)
    release_session(session_id, user.id)
    audit.log("conversation_deleted", user_id=user.id, detail={"session_id": session_id})
    return {"deleted": True, "session_id": session_id, "stores": {k: v for k, v in result.items() if not k.endswith("_error")}}


@app.post("/api/session/save")
async def save_session(req: ChatRequest, user: User | None = Depends(get_current_user_optional)):
    sid = req.session_id
    # G-006: was unauthenticated -- any caller holding another user's id could
    # force a save of that user's session.
    _check_session_ownership(sid, user.id if user else None)
    if sid and sid in _sessions:
        sess = _sessions[sid]
        sess.memory.save_session()
        return {"saved": True, "session_id": sid}
    return {"saved": False}


@app.get("/api/usage")
async def my_usage(days: int = 7, user: User | None = Depends(get_current_user_optional)):
    """The caller's own metering: plan, today's counters against their limits, remaining allowance and a short history. Counts only; per-user cost accounting is not implemented."""
    if user is None:
        e = coded_error("auth_required")
        return JSONResponse(e.as_json(), status_code=e.status)
    from orca.auth.store import DAILY_LIMITS, get_usage_history, get_usage_today

    limits = DAILY_LIMITS.get(user.tier, DAILY_LIMITS["free"])
    today = get_usage_today(user.id)

    def remaining(used: int, limit: int):
        return None if limit == -1 else max(0, limit - used)

    return {
        "plan": user.tier,
        "today": today,
        "limits": limits,
        "remaining": {"messages": remaining(today["messages"], limits.get("messages", 50)), "ultra_runs": remaining(today["ultra_runs"], limits.get("ultra", 0))},
        "history": get_usage_history(user.id, days),
        "cost_accounting": "not_implemented",
    }


@app.get("/api/tools")
async def available_tools():
    """What the assistant may do on THIS surface, stated truthfully. Server-authority tools are not registered on the web (G-020); this lists them as blocked."""
    from orca.tools import SERVER_AUTHORITY_TOOLS, build_registry

    reg = build_registry(surface="web")
    return {
        "surface": "web",
        "available": [{"name": t["name"], "description": t["description"]} for t in reg.schema_list()],
        "available_when_session_bound": ["memory_recall"],
        "blocked": [{"name": n, "reason": "not_available_on_web"} for n in sorted(SERVER_AUTHORITY_TOOLS)],
    }


@app.get("/api/models")
async def list_models():
    """
    Return which Orneur model variants are available in Ollama — and, crucially,
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

        # What a client may truthfully say about this tier for the (anonymous) public: lifecycle, disclosure label and whether it would be
        # served here at all. Eligibility for a user-scoped public experiment is decided per request, so an anonymous view never over-promises.
        served = resolved_model or configured_model
        decision = public_serving_decision(tier, served)
        return {
            "model": configured_model,
            "available": _available(configured_model),
            "vision_capable": is_vision_capable(configured_model),
            "resolved_model": resolved_model,
            "fallback_active": resolved_model is not None and resolved_model != configured_model,
            "lifecycle": decision.lifecycle,
            "publicly_served": decision.allowed,
            "disclosure": decision.label or ("Experimental model -- not qualified." if decision.lifecycle == "EXPERIMENTAL" else ""),
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

    from orca.gateway.wiring import serving_policy

    return {
        "serving_policy": serving_policy(),
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
    """AI Policy & Risk Register — the policy Orneur's technical safety controls actually enforce."""
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
    lines = ["Orneur Documentation", "====================", ""]
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
        return JSONResponse(
            public_error(e, route="/api/billing/checkout", user_id=user.id, code="checkout_unavailable",
                         message="Could not create a checkout session. Please try again later.").as_json(),
            status_code=502,
        )

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
async def ultra_run(req: UltraRequest, user: User | None = Depends(get_current_user_optional)):
    """SSE endpoint — runs OrcaUltra multi-agent pipeline and streams progress."""
    if not has_feature("ultra"):
        async def _gate_stream():
            yield f"data: {json.dumps({'type': 'error', 'text': 'Ultra requires a Pro license. Run: orca activate <key>'})}\n\n"
        return StreamingResponse(_gate_stream(), media_type="text/event-stream")

    _refusal = _authorize_inference(user, "ultra", req.task, route="/api/ultra", quota_kind="ultra")
    if _refusal is not None:
        async def _ultra_refused():
            yield f"data: {json.dumps(_refusal.as_sse())}\n\n"
        return StreamingResponse(_ultra_refused(), media_type="text/event-stream")

    sess = _get_session(req.session_id, user_id=user.id if user else None)
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
    try:
        ultra_resolution = TierResolution(
            tier="ultra",
            backend="ollama",
            model=_model_name_for_variant("ultra"),
            data_left_infrastructure=False,
        )
        ultra_brain = brain_for_tier_resolution(ultra_resolution, viewer_user_id=user.id if user else None)
    except Exception as _e:        # no installed model for the tier, or the tier is not routable: a clean coded error, never an unhandled 500
        _unavail = public_error(_e, route="/api/ultra", user_id=user.id if user else None, code="model_unavailable")
        async def _ultra_unavailable():
            yield f"data: {json.dumps(_unavail.as_sse())}\n\n"
        return StreamingResponse(_ultra_unavailable(), media_type="text/event-stream")

    def on_progress(msg: str):
        # Called from within async coroutine context (main event loop thread)
        try:
            progress_queue.put_nowait({"type": "progress", "text": msg.strip()})
        except asyncio.QueueFull:
            pass

    async def _event_stream() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'type': 'session', 'session_id': sess.id})}\n\n"
        yield f"data: {json.dumps({'type': 'pod_launch'})}\n\n"

        ultra = OrcaUltra(on_progress=on_progress, use_tools=True, brain=ultra_brain, surface="web")
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
            yield f"data: {json.dumps(public_error(e, route='/api/ultra').as_sse())}\n\n"
            return

        # Stream final output in small chunks for smooth rendering
        _dlp = dlp.scan_output(pipeline.final_output)
        if _dlp["has_findings"]:
            audit.log("output_dlp_finding", user_id=user.id if user else None, detail={
                "pii_flagged": _dlp["pii_flagged"], "secrets_redacted": _dlp["secrets_redacted"], "endpoint": "ultra",
            })
        text = _dlp["safe_text"]
        if user:
            increment_usage(user.id, "ultra")
        chunk_size = 25
        for i in range(0, len(text), chunk_size):
            yield f"data: {json.dumps({'type': 'chunk', 'text': text[i:i+chunk_size]})}\n\n"
            await asyncio.sleep(0)

        # Persist to memory
        sess.memory.add_turn("user", req.task)
        sess.memory.add_turn("assistant", pipeline.final_output)
        _persist_turn(user, sess.id, req.task, text)
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
    except ValueError as e:
        # The extractor raises ValueError only for caller-fixable input
        # problems ("Unsupported file type: .xyz"); that text is safe and useful.
        return JSONResponse({"error": f"Extraction failed: {e}", "code": "unsupported_file"}, status_code=422)
    except ImportError as e:
        return JSONResponse(
            public_error(e, route="/api/docs/upload", user_id=user.id if user else None, code="extractor_unavailable",
                         message="This file type isn't supported on this deployment.").as_json(),
            status_code=422,
        )
    except Exception as e:
        return JSONResponse(
            public_error(e, route="/api/docs/upload", user_id=user.id if user else None, code="extraction_failed",
                         message="This file could not be read.").as_json(),
            status_code=422,
        )

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
async def list_session_docs(session_id: str | None = None, user: User | None = Depends(get_current_user_optional)):
    """List all documents uploaded in the current session."""
    sess = _get_session(session_id, user_id=user.id if user else None)
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
    if not any(d.get("doc_id") == doc_id for d in list_docs(sess.id)):
        # Say so instead of answering 200 {"deleted": false}: this document is not in this conversation.
        return JSONResponse({"error": "No such document in this conversation.", "code": "not_found", "doc_id": doc_id}, status_code=404)
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
    """DISABLED on the web (G-020).

    This ran model-independent, caller-supplied Python on the server host under
    the server's identity. The AST allow-list is not a sandbox: `pathlib` was
    allowed, so `Path('/proc/self/environ').read_text()` returned the server's
    environment, including `ORNEUR_AUTH_SECRET` (reproduced against the previous
    code). Re-enabling needs isolated per-user execution and an independent audit,
    not a flag. The local CLI is unaffected.
    """
    audit.log("code_run_refused", user_id=user.id if user else None, detail={"route": "/api/code/run"})
    return JSONResponse(
        {"error": "Code execution is not available in this environment.", "code": "capability_disabled"},
        status_code=403,
    )


MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB


def _looks_like_image(data: bytes) -> bool:
    """Magic-byte check (PNG, JPEG, GIF, WebP). The declared content type is attacker-controlled and is not trusted."""
    return (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff") or data[:6] in (b"GIF87a", b"GIF89a")
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


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

    data = await image.read(MAX_IMAGE_SIZE + 1)         # bounded read: never buffer an arbitrarily large upload
    if len(data) > MAX_IMAGE_SIZE:
        return JSONResponse(
            {"error": f"Image too large. Max: {MAX_IMAGE_SIZE//1024//1024}MB", "code": "invalid_request"},
            status_code=413,
        )
    if not _looks_like_image(data):
        e = coded_error("invalid_request", message="The uploaded file is not a supported image (PNG, JPEG, GIF or WebP).", status=415)
        return JSONResponse(e.as_json(), status_code=e.status)

    _refusal = _authorize_inference(user, model_variant, message, route="/api/vision")
    if _refusal is not None:
        return JSONResponse(_refusal.as_json(), status_code=_refusal.status)

    model_name = _model_name_for_variant(model_variant)
    if not is_vision_capable(model_name):
        return JSONResponse(
            {"error": f"Model '{model_name}' does not appear to be vision-capable. "
                      f"Pull a vision model (e.g. `ollama pull llava` or `ollama pull llama3.2-vision`) "
                      f"and configure it for this variant."},
            status_code=400,
        )

    sess = _get_session(session_id, model_variant, user_id=user.id if user else None)
    image_b64 = encode_image(data)
    vision_message = build_vision_message(message, image_b64)

    try:
        response = await asyncio.to_thread(sess.brain.complete, [vision_message])
    except Exception as e:
        _err = public_error(e, route="/api/vision", user_id=user.id if user else None)
        return JSONResponse(_err.as_json(), status_code=503 if _err.code == "model_unavailable" else 500)

    _dlp = dlp.scan_output(response)
    if _dlp["has_findings"]:
        audit.log("output_dlp_finding", user_id=user.id if user else None, detail={
            "pii_flagged": _dlp["pii_flagged"], "secrets_redacted": _dlp["secrets_redacted"], "endpoint": "vision",
        })
    response = _dlp["safe_text"]
    if user:
        increment_usage(user.id, "message")

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
async def prometheus_metrics(request: Request):
    """
    Prometheus exposition format — no auth, standard scrape convention.
    If exposing this port publicly, put a firewall/reverse-proxy rule in
    front of it; this endpoint reveals operational detail (request volumes,
    error rates, endpoint names) that shouldn't be internet-visible.
    """
    if _is_public_edge():
        # Workstream A: on a public edge the scrape endpoint is closed unless a scrape token is configured AND presented (constant-time compare).
        token = orneur_env("METRICS_TOKEN", "")
        presented = request.headers.get("authorization", "")
        if not token or len(token) < 32 or not hmac.compare_digest(presented, f"Bearer {token}"):
            e = coded_error("forbidden")
            return JSONResponse(e.as_json(), status_code=403)
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

class _BrandStaticFiles(StaticFiles):
    """Files under /static/brand/ carry their own content hash in the filename, so they are immutable."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path.startswith("brand/") and _HASHED_BRAND_FILE.search(path) and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


_HASHED_BRAND_FILE = re.compile(r"\.[0-9a-f]{8}\.(png|ico)$")

if WEB_DIR.exists():
    app.mount("/static", _BrandStaticFiles(directory=str(WEB_DIR)), name="static")


def create_app() -> FastAPI:
    return app
