"""Research-only retrieval kernel.

Canonical local retrieval is `orca.truth.indexed_query.run_authorized_retrieval`
on `orca.docs.authorized_index.AuthorizedIndex`. This module does not make
that path's authorization or evidence-policy decisions.

Strategies here are selected by `RetrievalRequest.mode` and run on synthetic
fixtures. A retrieved document cannot change the caller's scope or grant a tool.
`synthetic_hash_v1` is not a neural encoder.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence

from orca.rag_x.contracts import (
    NATIVE_MODEL_IDS,
    SCHEMA_VERSION,
    AnswerEvidenceManifest,
    AnswerResult,
    AuthorizedRetrievalScope,
    ClaimVerification,
    ContradictionRecord,
    EvidenceSpan,
    RetrievedEvidence,
    RetrievalRequest,
    RetrievalStatus,
)
from orca.rag_x.corpus import Chunk, Corpus, Document
from orca.rag_x.rank import (
    HASH_EMBEDDING_ID,
    bm25_scores,
    cosine,
    hash_embed,
    maxsim,
    rrf_fuse,
    term_count_scores,
    tokenize,
)

_ASSERTION = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*([A-Za-z0-9_.:-]+)")
Connector = Callable[[], list[Document]]


def execute(
    request: RetrievalRequest,
    corpus: Corpus,
    *,
    software_revision: str = "unspecified",
    embedder: Callable[[str], tuple[float, ...]] | None = None,
    embedder_id: str | None = None,
    reranker: Callable[[str, list[str]], list[float]] | None = None,
    connectors: Sequence[tuple[str, Connector]] | None = None,
    challenge: bool | None = None,
    generation: Callable[[str], str] | None = None,
) -> AnswerResult:
    """Run one authorized retrieval. Predecessor failures stop the flow."""
    steps = ["authenticate", "resolve-scope", "classify", "check-capability"]
    scope = request.scope
    corpus.log.append(f"{request.mode}:{corpus.redact(request.query)}")
    if request.model_identity.lower() in NATIVE_MODEL_IDS:
        return _finish(
            request, [], [], RetrievalStatus.MODEL_NOT_TRAINED,
            "native model is not trained", steps + ["refuse-untrained-model"],
            software_revision, ["model identity is not a trained backend"],
        )
    mode = request.mode
    if mode in {"audio", "video", "colbert"}:
        return _finish(
            request, [], [], RetrievalStatus.BACKEND_UNAVAILABLE,
            f"{mode} backend is not available", steps + ["backend-unavailable"],
            software_revision, [f"{mode} has no permitted encoder or model in this process"],
        )
    if mode == "dense-neural" and embedder is None:
        return _finish(
            request, [], [], RetrievalStatus.BACKEND_UNAVAILABLE,
            "neural embedding backend is not available", steps + ["backend-unavailable"],
            software_revision, ["no neural embedder was injected"],
        )
    if request.raw_sql:
        return _finish(
            request, [], [], RetrievalStatus.UNAUTHORIZED,
            "raw SQL is not accepted", steps + ["reject-raw-sql"],
            software_revision, ["structured filters are required"],
        )
    do_challenge = _default_challenge(mode) if challenge is None else challenge
    steps.append("plan")
    if request.budget.max_retrieval_calls <= 0 or request.budget.deadline_steps <= 0:
        return _finish(
            request, [], [], RetrievalStatus.BUDGET_EXHAUSTED,
            "retrieval budget is exhausted", steps + ["budget-stop"],
            software_revision, ["no retrieval call was issued"],
        )
    if mode == "self-rag" and not _needs_evidence(request.query):
        return _finish(
            request, [], [], RetrievalStatus.NO_RETRIEVAL_REQUIRED,
            "no retrieval was required", steps + ["skip-retrieval"],
            software_revision, ["runtime heuristic only; this is not trained Self-RAG"],
        )

    query = _resolve_query(request)
    calls = 0
    notes: list[str] = []
    if mode == "adaptive":
        mode = _adapt(query)
        notes.append(f"adaptive-selected:{mode}")
    steps.extend(["select-mode", "query-sources", "filter-access", "version-filter"])
    evidence, calls, partial = _retrieve(
        mode, query, request, corpus, scope, embedder, embedder_id, reranker, connectors, calls, notes,
    )
    steps.extend(["dedupe", "rerank" if mode == "rerank" else "rank", "corrective" if mode == "corrective" else "assess"])
    if mode == "corrective" and calls < request.budget.max_retrieval_calls and not evidence:
        calls += 1
        evidence, extra_calls, more = _retrieve(
            "sparse", f"\"{query}\"", request, corpus, scope, embedder, embedder_id, reranker, connectors, 0, notes,
        )
        calls += extra_calls
        partial.extend(more)
        notes.append("corrective-reformulation")
    if mode == "hyde":
        notes.append("hypothetical-text-is-synthetic")
        evidence = [item for item in evidence if not item.synthetic_query]
    evidence = _dedupe(evidence)
    if mode == "reflection":
        notes.append("reflection-checked-span-consistency")
    packed, dropped = _pack(evidence, request.budget.max_tokens)
    if dropped:
        partial.append(f"token budget omitted {dropped} evidence item(s)")
    observed = _contradictions(packed)
    if do_challenge:
        steps.append("challenge-evidence")
    steps.extend(["pack-context", "verify-claims", "record-provenance"])
    status, answer, claims = _answer(packed, observed if do_challenge else [], generation, mode)
    if mode == "reflection" and status == RetrievalStatus.SUCCESS:
        checked = verify_claim(answer, packed)
        if not checked.supported:
            status = RetrievalStatus.INSUFFICIENT
            answer = "reflection rejected the draft"
            claims = [checked]
            notes.append("reflection-rejected-draft")
    if mode == "domain":
        notes.append("domain_reliability=not_qualified")
    if any(item.provider_status == "disconnected" for item in packed):
        status = RetrievalStatus.SOURCE_INACCESSIBLE
    elif partial and status == RetrievalStatus.SUCCESS:
        status = RetrievalStatus.PARTIAL
    if not packed and status == RetrievalStatus.SUCCESS:
        status = RetrievalStatus.INSUFFICIENT
        answer = "insufficient evidence"
    if mode == "live" and not packed and partial:
        status = RetrievalStatus.SOURCE_INACCESSIBLE
        answer = "source inaccessible"
    if mode == "federated" and partial:
        status = RetrievalStatus.PARTIAL
        if not packed:
            answer = "partial retrieval"
    steps.append("no-tool-grant")
    result = _finish(
        request, packed, observed, status, answer, steps, software_revision, partial, calls, notes,
    )
    result.claims = claims
    result.lexical_scores = {item.evidence_id: item.score for item in packed}
    return result


def verify_claim(claim: str, evidence: list[RetrievedEvidence]) -> ClaimVerification:
    """A citation counts only when the claim text sits in an authoritative span."""
    ids = tuple(item.evidence_id for item in evidence)
    if not claim.strip():
        return ClaimVerification(claim, False, ids, "empty claim")
    authoritative = [item for item in evidence if item.span.authoritative]
    for item in authoritative:
        if claim.strip() in item.span.text:
            return ClaimVerification(claim, True, (item.evidence_id,), "span contains the claim")
    if evidence and not authoritative:
        return ClaimVerification(claim, False, ids, "only non-authoritative summary text is present")
    return ClaimVerification(claim, False, ids, "claim text is not in an authoritative span")


def replay_evidence(result: AnswerResult, corpus: Corpus, scope: AuthorizedRetrievalScope) -> list[str]:
    """Reconstruct evidence ids that are still authorized. Generation is not replayed."""
    visible = {(doc.document_id, doc.version_id) for doc in corpus.visible(scope)}
    kept = []
    for item in result.evidence:
        key = (item.span.document_id, item.span.version_id)
        if key in visible:
            kept.append(item.evidence_id)
    return kept


def _retrieve(mode, query, request, corpus, scope, embedder, embedder_id, reranker, connectors, calls, notes):
    partial: list[str] = []
    if mode == "federated":
        return _federated(query, request, corpus, scope, connectors, calls, partial, notes)
    if mode == "sql":
        return _sql(request, corpus, scope, calls, partial)
    if mode == "code":
        return _code(query, corpus, scope, calls, notes)
    if mode == "multi-hop":
        return _multihop(query, corpus, scope, request, calls, notes)
    if mode == "decompose":
        return _decompose(query, request, corpus, scope, calls, notes)
    if mode == "multi-query":
        return _multi_query(query, request, corpus, scope, calls, notes)
    if mode == "graph":
        evidence, calls, partial = _score_mode("sparse", query, request, corpus, scope, embedder, embedder_id, reranker, calls + 1, notes, partial)
        return _expand_graph(evidence, corpus, scope, notes), calls, partial
    if mode == "agentic":
        evidence: list[RetrievedEvidence] = []
        rounds = 0
        while rounds < request.budget.max_rounds and calls < request.budget.max_retrieval_calls:
            calls += 1
            batch, calls, partial = _score_mode("sparse", query, request, corpus, scope, embedder, embedder_id, reranker, calls, notes, partial)
            evidence.extend(batch)
            rounds += 1
            if batch:
                break
        notes.append(f"agentic-rounds:{rounds}")
        return _dedupe(evidence), calls, partial
    calls += 1
    search_mode = "sparse" if mode in {"corrective", "self-rag", "budget", "reflection", "contradiction", "contradiction-first", "citation", "uncertainty", "permission", "privacy", "adversarial", "provenance", "versioned", "live", "memory", "conversational", "domain", "temporal"} else mode
    if mode == "hyde":
        query = f"{query} synthetic passage about {query}"
        notes.append("hyde-query-synthetic")
        search_mode = "sparse"
    return _score_mode(search_mode, query, request, corpus, scope, embedder, embedder_id, reranker, calls, notes, partial)


def _score_mode(mode, query, request, corpus, scope, embedder, embedder_id, reranker, calls, notes, partial):
    search_scope = scope
    if request.as_of is not None:
        search_scope = AuthorizedRetrievalScope(
            scope.tenant_id, scope.principal_id, scope.workspace_id, scope.session_id, request.as_of,
        )
    documents = corpus.visible(search_scope)
    if mode == "memory":
        documents = [doc for doc in documents if doc.memory_owner is not None]
    if mode == "live":
        silent = [doc.document_id for doc in documents if doc.provider_status in {"disconnected", "stale"}]
        documents = [doc for doc in documents if doc.provider_status == "available"]
        for doc_id in silent:
            partial.append(f"provider skipped {doc_id}")
    pairs: list[tuple[Document, Chunk, str]] = []
    image_skipped = 0
    for document in documents:
        for chunk in document.chunks:
            if chunk.modality in {"image", "audio", "video"} or document.modality in {"image", "audio", "video"}:
                image_skipped += 1
                continue
            if mode == "raptor" and chunk.authoritative:
                continue
            text = chunk.text
            if mode == "contextual" and chunk.context_prefix:
                text = f"{chunk.context_prefix} {text}"
            if corpus.glossary:
                text = _apply_glossary(text, corpus.glossary)
            pairs.append((document, chunk, text))
    if image_skipped and not pairs and mode == "multimodal":
        partial.append("image, audio, and video encoders are not available")
        return [], calls, partial
    if image_skipped:
        partial.append(f"unsupported modality skipped {image_skipped}")
    texts = [text for _, _, text in pairs]
    scores = _scores(mode, query, texts, embedder, embedder_id, notes)
    order = sorted(range(len(pairs)), key=lambda index: scores[index], reverse=True)
    if mode == "rerank":
        lexical = list(order)
        rerank_scores = (reranker or _overlap_rerank)(query, [texts[index] for index in lexical])
        order = [lexical[index] for index in sorted(range(len(lexical)), key=lambda item: rerank_scores[item], reverse=True)]
        scores_for_rank = {lexical[index]: rerank_scores[index] for index in range(len(lexical))}
    else:
        scores_for_rank = {index: scores[index] for index in order}
    evidence = []
    for rank, index in enumerate(order, start=1):
        if scores_for_rank[index] <= 0:
            continue
        document, chunk, _text = pairs[index]
        evidence.append(_evidence(document, chunk, scores_for_rank[index], rank, mode))
    if mode == "long-context":
        notes.append("long-context-packing")
    return evidence, calls, partial


def _scores(mode, query, texts, embedder, embedder_id, notes) -> list[float]:
    if mode == "naive":
        notes.append("method:naive-term-count")
        return term_count_scores(query, texts)
    if mode == "dense":
        identity = embedder_id or (HASH_EMBEDDING_ID if embedder is None else "injected-embedder")
        notes.append(f"embedding:{identity}")
        function = embedder or hash_embed
        query_vector = function(query)
        return [cosine(query_vector, function(text)) for text in texts]
    if mode == "hybrid":
        notes.append("method:hybrid-rrf")
        notes.append(f"embedding:{HASH_EMBEDDING_ID if embedder is None else embedder_id or 'injected-embedder'}")
        lexical = _ranking(bm25_scores(query, texts))
        function = embedder or hash_embed
        query_vector = function(query)
        dense_scores = [cosine(query_vector, function(text)) for text in texts]
        fused = rrf_fuse([lexical, _ranking(dense_scores)])
        return [fused.get(index, 0.0) for index in range(len(texts))]
    if mode == "late-interaction":
        notes.append("method:synthetic-maxsim-not-colbert")
        return [maxsim(query, text) for text in texts]
    if mode == "rerank":
        notes.append("method:bm25-then-rerank")
        return bm25_scores(query, texts)
    notes.append(f"method:{mode if mode in {'contextual', 'raptor', 'sparse'} else 'bm25'}")
    return bm25_scores(query, texts)


def _federated(query, request, corpus, scope, connectors, calls, partial, notes):
    notes.append("method:federated")
    collected: list[Document] = []
    if connectors:
        for name, connector in connectors:
            if calls >= request.budget.max_retrieval_calls:
                partial.append(f"budget skipped connector {name}")
                break
            calls += 1
            try:
                produced = connector()
            except Exception as exc:
                partial.append(f"{name} failed: {type(exc).__name__}")
                continue
            for document in produced:
                if (
                    document.tenant_id != scope.tenant_id
                    or document.workspace_id != scope.workspace_id
                    or scope.principal_id not in document.principals
                ):
                    partial.append(f"{name} dropped unauthorized document")
                    continue
                collected.append(document)
    else:
        calls += 1
        collected = corpus.visible(scope)
    texts = []
    pairs = []
    for document in collected:
        for chunk in document.chunks:
            pairs.append((document, chunk))
            texts.append(chunk.text)
    scores = bm25_scores(query, texts)
    evidence = []
    for rank, index in enumerate(sorted(range(len(pairs)), key=lambda item: scores[item], reverse=True), start=1):
        if scores[index] <= 0:
            continue
        document, chunk = pairs[index]
        evidence.append(_evidence(document, chunk, scores[index], rank, "federated"))
    return evidence, calls, partial


def _sql(request, corpus, scope, calls, partial):
    calls += 1
    filters = dict(request.structured_filter or {})
    filters["tenant_id"] = scope.tenant_id
    evidence = []
    for document in corpus.visible(scope):
        for row in document.rows:
            if any(row.get(key) != value for key, value in filters.items()):
                continue
            text = " ".join(f"{key}={value}" for key, value in sorted(row.items()))
            chunk = Chunk(f"{document.document_id}-row-{len(evidence)}", document.document_id, document.version_id, text, modality="table")
            evidence.append(_evidence(document, chunk, 1.0, len(evidence) + 1, "sql"))
    return evidence, calls, partial


def _code(query, corpus, scope, calls, notes):
    notes.append("method:code-symbols")
    calls += 1
    prefix = "callers of "
    evidence = []
    if query.lower().startswith(prefix):
        target = query[len(prefix):].strip()
        for document in corpus.visible(scope):
            for symbol in document.symbols:
                if target not in symbol.references and symbol.name != target:
                    continue
                chunk = next(item for item in document.chunks if item.chunk_id == symbol.chunk_id)
                evidence.append(_evidence(document, chunk, 1.0, len(evidence) + 1, "code"))
        return evidence, calls, []
    return _score_mode("sparse", query, _dummy_budget_request(query, scope), corpus, scope, None, None, None, calls, notes, [])


def _multihop(query, corpus, scope, request, calls, notes):
    notes.append("method:multi-hop")
    calls += 1
    first, calls, partial = _score_mode("sparse", query, request, corpus, scope, None, None, None, calls, notes, [])
    if not first or calls >= request.budget.max_retrieval_calls:
        return first, calls, partial
    calls += 1
    entities = set()
    for item in first[:1]:
        document = corpus.documents[(item.span.document_id, item.span.version_id)]
        entities.update(entity for entity, _role in document.entities)
    second: list[RetrievedEvidence] = []
    for edge in corpus.edges:
        if edge.tenant_id != scope.tenant_id or edge.kind != "entity":
            continue
        if edge.src not in entities and edge.dst not in entities:
            continue
        linked = edge.dst if edge.src in entities else edge.src
        for document in corpus.visible(scope):
            if all(entity != linked for entity, _role in document.entities):
                continue
            if document.document_id == first[0].span.document_id:
                continue
            chunk = document.chunks[0]
            hop = _evidence(document, chunk, 1.0, len(second) + 1, "multi-hop")
            second.append(_replace_hop(hop, 1))
    if not second:
        partial.append("multi-hop found no connected second document")
        return first, calls, partial
    notes.append("multi-hop-connected")
    return first + second, calls, partial


def _decompose(query, request, corpus, scope, calls, notes):
    parts = [part.strip() for part in re.split(r"\band\b", query, flags=re.IGNORECASE) if part.strip()]
    evidence: list[RetrievedEvidence] = []
    partial: list[str] = []
    for part in parts or [query]:
        if calls >= request.budget.max_retrieval_calls:
            partial.append("budget skipped a subquery")
            break
        calls += 1
        batch, calls, more = _score_mode("sparse", part, request, corpus, scope, None, None, None, calls, notes, [])
        evidence.extend(batch)
        partial.extend(more)
    notes.append(f"subqueries:{len(parts) or 1}")
    return evidence, calls, partial


def _multi_query(query, request, corpus, scope, calls, notes):
    variants = [query]
    stripped = " ".join(tokenize(query))
    if stripped != query.lower():
        variants.append(stripped)
    evidence: list[RetrievedEvidence] = []
    partial: list[str] = []
    for variant in variants:
        if calls >= request.budget.max_retrieval_calls:
            partial.append("budget skipped a query variant")
            break
        calls += 1
        batch, calls, more = _score_mode("sparse", variant, request, corpus, scope, None, None, None, calls, notes, [])
        evidence.extend(batch)
        partial.extend(more)
    notes.append("multi-query-deduped")
    return evidence, calls, partial


def _expand_graph(evidence, corpus, scope, notes):
    notes.append("entity-graph-is-not-support")
    if not evidence:
        return evidence
    top = evidence[0]
    document = corpus.documents.get((top.span.document_id, top.span.version_id))
    if document is None:
        return evidence
    entities = {entity for entity, _role in document.entities}
    extra: list[RetrievedEvidence] = []
    for edge in corpus.edges:
        if edge.kind != "entity" or edge.tenant_id != scope.tenant_id:
            continue
        if edge.src not in entities and edge.dst not in entities:
            continue
        linked = edge.dst if edge.src in entities else edge.src
        for neighbor in corpus.visible(scope):
            if neighbor.document_id == document.document_id:
                continue
            if any(entity == linked for entity, _role in neighbor.entities):
                extra.append(_evidence(neighbor, neighbor.chunks[0], 0.5, len(evidence) + len(extra) + 1, "entity-graph"))
    return evidence + extra


def _answer(evidence, contradictions, generation, mode):
    conflicts = [item for item in contradictions if not item.temporal]
    if conflicts:
        claim = ClaimVerification(
            "conflicting values", False,
            (conflicts[0].left_evidence_id, conflicts[0].right_evidence_id),
            "non-temporal contradiction",
        )
        return RetrievalStatus.CONTRADICTORY, "evidence conflicts and no single value is asserted", [claim]
    if not evidence:
        return RetrievalStatus.INSUFFICIENT, "insufficient evidence", []
    top = next((item for item in evidence if item.span.authoritative), evidence[0])
    draft = top.span.text
    if generation is not None:
        try:
            draft = generation(draft)
        except Exception:
            return RetrievalStatus.GENERATION_INTERRUPTED, "generation interrupted", []
    claim = verify_claim(draft, evidence)
    if not claim.supported:
        return RetrievalStatus.INSUFFICIENT, "insufficient evidence", [claim]
    if mode == "uncertainty" and len(evidence) < 2:
        return RetrievalStatus.INSUFFICIENT, "insufficient evidence", [ClaimVerification(draft, False, (top.evidence_id,), "single source is not enough for this mode")]
    return RetrievalStatus.SUCCESS, draft, [claim]


def _contradictions(evidence: list[RetrievedEvidence]) -> list[ContradictionRecord]:
    found: dict[str, list[tuple[RetrievedEvidence, str]]] = {}
    for item in evidence:
        for subject, value in _ASSERTION.findall(item.span.text):
            found.setdefault(subject, []).append((item, value))
    records = []
    for subject, rows in found.items():
        for index, (left, left_value) in enumerate(rows):
            for right, right_value in rows[index + 1:]:
                if left_value == right_value:
                    continue
                temporal = _disjoint(left, right)
                records.append(ContradictionRecord(subject, left.evidence_id, right.evidence_id, left_value, right_value, temporal))
    return records


def _disjoint(left: RetrievedEvidence, right: RetrievedEvidence) -> bool:
    if left.valid_to is None or right.valid_to is None:
        if left.valid_from == right.valid_from:
            return False
    if left.valid_to is not None and left.valid_to <= right.valid_from:
        return True
    if right.valid_to is not None and right.valid_to <= left.valid_from:
        return True
    return False


def _pack(evidence: list[RetrievedEvidence], max_tokens: int) -> tuple[list[RetrievedEvidence], int]:
    kept = []
    used = 0
    for item in evidence:
        cost = max(1, len(item.span.text) // 4)
        if used + cost > max_tokens:
            continue
        kept.append(item)
        used += cost
    return kept, len(evidence) - len(kept)


def _dedupe(evidence: list[RetrievedEvidence]) -> list[RetrievedEvidence]:
    seen = set()
    kept = []
    for item in evidence:
        if item.span.chunk_id in seen:
            continue
        seen.add(item.span.chunk_id)
        kept.append(item)
    return kept


def _evidence(document: Document, chunk: Chunk, score: float, rank: int, method: str) -> RetrievedEvidence:
    span = EvidenceSpan(
        document.document_id, document.version_id, chunk.chunk_id, chunk.text,
        0, len(chunk.text), document.digest, chunk.authoritative,
    )
    return RetrievedEvidence(
        evidence_id=f"{document.document_id}:{document.version_id}:{chunk.chunk_id}",
        span=span, score=score, rank=rank, method=method, tenant_id=document.tenant_id,
        source_uri=document.source_uri, language=document.language, modality=chunk.modality or document.modality,
        valid_from=document.valid_from, valid_to=document.valid_to, provider_status=document.provider_status,
    )


def _replace_hop(item: RetrievedEvidence, hop: int) -> RetrievedEvidence:
    return RetrievedEvidence(
        item.evidence_id, item.span, item.score, item.rank, item.method, item.tenant_id,
        item.source_uri, item.language, item.modality, item.valid_from, item.valid_to,
        item.provider_status, item.synthetic_query, hop,
    )


def _finish(request, evidence, contradictions, status, answer, steps, revision, partial, calls=0, notes=None) -> AnswerResult:
    versions = tuple(sorted({f"{item.span.document_id}@{item.span.version_id}" for item in evidence}))
    config_digest = hashlib.sha256(f"{SCHEMA_VERSION}|{request.config_id}|{request.mode}".encode()).hexdigest()
    scope_digest = hashlib.sha256(
        f"{request.scope.tenant_id}|{request.scope.principal_id}|{request.scope.workspace_id}|{request.scope.session_id}".encode()
    ).hexdigest()
    manifest = AnswerEvidenceManifest(
        schema_version=SCHEMA_VERSION,
        request_id=hashlib.sha256(f"{request.query}|{request.mode}|{scope_digest}".encode()).hexdigest()[:16],
        scope_digest=scope_digest,
        config_id=request.config_id,
        config_digest=config_digest,
        mode=request.mode,
        model_identity=request.model_identity,
        backend_id=request.backend_id,
        status=status,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        document_versions=versions,
        steps=steps,
        retrieval_calls=calls,
        software_revision=revision,
        partial_reasons=list(partial),
    )
    return AnswerResult(status, answer, [], evidence, contradictions, manifest, notes=list(notes or []))


def _needs_evidence(query: str) -> bool:
    tokens = tokenize(query)
    return "?" in query or any(ch.isdigit() for ch in query) or len(tokens) >= 3


def _adapt(query: str) -> str:
    lowered = query.lower()
    if " and " in lowered:
        return "decompose"
    if lowered.startswith("compare") or "conflict" in lowered:
        return "contradiction"
    if "who " in lowered or "founded" in lowered:
        return "multi-hop"
    return "sparse"


def _default_challenge(mode: str) -> bool:
    return mode not in {"naive", "hyde"}


def _resolve_query(request: RetrievalRequest) -> str:
    if request.mode == "conversational" and tokenize(request.query) in (["it"], ["that"], ["same"]):
        return request.history[-1] if request.history else request.query
    return request.query


def _apply_glossary(text: str, glossary: dict[str, str]) -> str:
    expanded = text
    for source, target in glossary.items():
        if source in expanded and target not in expanded:
            expanded = expanded.replace(source, f"{source} {target}")
    return expanded


def _ranking(scores: list[float]) -> list[int]:
    return [index for index in sorted(range(len(scores)), key=lambda item: scores[item], reverse=True) if scores[index] > 0]


def _overlap_rerank(query: str, texts: list[str]) -> list[float]:
    needed = set(tokenize(query))
    return [float(len(needed & set(tokenize(text)))) for text in texts]


def _dummy_budget_request(query: str, scope: AuthorizedRetrievalScope) -> RetrievalRequest:
    from orca.rag_x.contracts import RetrievalBudget, RetrievalRequest as Request
    return Request(query, scope, "sparse", RetrievalBudget())
